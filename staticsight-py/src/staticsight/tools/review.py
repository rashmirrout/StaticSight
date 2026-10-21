"""review_changes: one-call, budgeted review bundle built from the other StaticSight tools."""

from __future__ import annotations

import re

from ..config import Config, is_header, load_config
from ..core import md
from ..core.cpp_text import strip_code
from ..engines.ctags import FUNCTION_KINDS, try_ctags_for_files
from ..core.paths import read_lines
from ..core.errors import StaticSightError
from .diff_scopes import analyse_diff, render_diff_scopes
from .graph_gtags import _FileCache, callers_report, find_definitions
from .ripgrep_mem import blast_radius_report, struct_risks_report
from .lock_order import lock_order_report
from .state_mutation import state_mutations_report
from ..core.locks import line_events
from .static_cpp import static_audit_report
from .syntax_ctags import branch_skeleton_report

_CALLEE = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_NOT_CALLEES = {
    "if", "for", "while", "switch", "return", "sizeof", "alignof", "decltype", "static_cast", "reinterpret_cast",
    "const_cast", "dynamic_cast", "catch", "throw", "noexcept", "defined", "static_assert", "typeid", "alignas",
    "assert", "co_return", "co_await", "new", "delete", "operator",
}
SECTION_CHARS = 2200
_DECL_BEFORE = re.compile(
    r"(?:^|[\s(,;{])(?!(?:return|else|throw|co_return|co_await|case|delete|new)\b)[A-Za-z_][\w:]*(?:<[^()]*>)?"
    r"(?:\s+|\s*(?:\*+|&(?!&))\s*)$"
)


def _section(title: str, body: str, limit: int) -> str:
    return f"## {title}\n" + md.enforce_budget(body, limit)


async def _safe(coro) -> str:
    try:
        return await coro
    except StaticSightError as exc:
        return md.error_card(exc.title, exc.message, exc.hint)


async def review_report(cfg: Config, base_ref: str = "", max_symbols: int = 8) -> str:
    max_symbols = max(1, min(int(max_symbols or 8), 25))
    ds = await analyse_diff(cfg, base_ref)
    parts: list[str] = [f"# 🔬 STATICSIGHT REVIEW BUNDLE vs {ds.info.base_label}"]
    if not ds.reports:
        parts.append(render_diff_scopes(ds, cfg, compact=True))
        return "\n\n".join(parts)
    checklist: list[str] = []
    parts.append(_section("1. What changed", render_diff_scopes(ds, cfg, compact=True), 3500))

    # 2. static audit of changed source files
    audits = []
    sources = [r for r in ds.reports if r.diff.status != "deleted" and not is_header(r.diff.path)]
    for rep in sources[:6]:
        audits.append(md.enforce_budget(await _safe(static_audit_report(cfg, rep.diff.path, True, base_ref)), 1200))
    if audits:
        text = "\n\n".join(audits)
        if "[error:" in text:
            checklist.append("Fix the cppcheck **errors** on changed lines (✏️) first; they are the strongest evidence.")
        parts.append(_section("2. Static audit (cppcheck, changed lines)", text, SECTION_CHARS * 2))

    # 3. branch skeletons of changed functions
    live = [(r, s) for r, s in ds.changed_functions() if r.diff.status != "deleted"]
    funcs = ([(r, s) for r, s in live if not s.is_new] + [(r, s) for r, s in live if s.is_new])[:max_symbols]
    skels = []
    flat: list[str] = []
    for rep, sc in funcs:
        sk = await _safe(branch_skeleton_report(cfg, rep.diff.path, start_line=sc.tag.line, base_ref=base_ref))
        if "✅ No control-flow branches" in sk:
            flat.append(f"`{sc.tag.qualified}`")
            continue
        skels.append(md.enforce_budget(sk, 1400))
    if flat:
        skels.append("_No branches, locks or allocations in: " + ", ".join(flat) + "._")
    if skels:
        text = "\n\n".join(skels)
        if "⚠️" in text and "not released" in text:
            checklist.append("Confirm every allocation/acquire flagged ⚠️ is released on the early-exit paths shown in the skeletons.")
        parts.append(_section("3. Branch skeletons of changed functions", text, SECTION_CHARS * 2))

    # 4. caller impact (modified, not brand-new functions + changed declarations)
    targets: list[str] = []
    for rep, sc in ds.changed_functions():
        if not sc.is_new or sc.signature_changed:
            targets.append(sc.tag.short_name)
    for rep in ds.reports:
        for sc in rep.scopes:
            if sc.kind == "prototype" and sc.signature_changed:
                targets.append(sc.tag.short_name)
        for t in rep.removed_symbols:
            if t.kind in FUNCTION_KINDS:
                targets.append(t.short_name)
    targets = list(dict.fromkeys(targets))[:max_symbols]
    callers = []
    for name in targets:
        callers.append(md.enforce_budget(await _safe(callers_report(cfg, name)), 1000))
    if callers:
        text = "\n\n".join(callers)
        if "result ignored" in text:
            checklist.append("Some callers ignore return values of changed functions: check new/changed error codes are handled.")
        parts.append(_section("4. Caller impact", text, SECTION_CHARS))

    # 5. struct layout risks
    types = [sc.tag.short_name for _, sc in ds.changed_types() if sc.layout and not sc.is_new]
    risks = []
    for name in list(dict.fromkeys(types))[:3]:
        risks.append(md.enforce_budget(await _safe(struct_risks_report(cfg, name)), 1500))
    if risks:
        text = "\n\n".join(risks)
        if "may break" in text:
            checklist.append(
                "Layout-changed types are copied/sent/cast as raw bytes: check wire/disk format versioning, peers built from old code, and add/update `static_assert(sizeof(...))`."
            )
        parts.append(_section("5. Memory-layout risks of changed types", text, SECTION_CHARS))

    # 6. header blast radius
    radii = []
    for rep in ds.changed_headers()[:3]:
        radii.append(md.enforce_budget(await _safe(blast_radius_report(cfg, rep.diff.path, 2)), 900))
    if radii:
        checklist.append("Changed headers recompile every includer listed in the blast radius: rebuild and run their tests.")
        parts.append(_section("6. Header blast radius", "\n\n".join(radii), SECTION_CHARS))

    # 7. lock consistency of members touched by changed functions
    members = await _touched_members(cfg, ds, funcs)
    locks = []
    for name in members[:4]:
        rep_text = await _safe(state_mutations_report(cfg, name))
        if "Inconsistent locking" in rep_text:
            locks.append(md.enforce_budget(rep_text, 1400))
    if locks:
        checklist.append("Members are accessed both with and without their mutex: confirm thread-safety or restore the lock.")
        parts.append(_section("7. Lock consistency", "\n\n".join(locks), SECTION_CHARS))

    # 8. lock order: only when a changed function takes a lock (the analysis scans every locking file)
    focus = _locking_functions(cfg, live)
    if focus:
        text = await _safe(lock_order_report(cfg, focus=focus))
        if text:
            if "deadlock cycle" in text or "taken twice" in text:
                checklist.append("Locks are taken in conflicting orders (or twice): fix the order before merging; this can deadlock.")
            if "blocking calls" in text:
                checklist.append("A lock is held across a blocking call: shrink the critical section or document why it is safe.")
            parts.append(_section("8. Lock order", text, SECTION_CHARS))

    # 9. newly introduced callees -> contracts
    callees = _new_callees(cfg, ds)
    if callees:
        parts.append(
            "## 9. Calls introduced by the diff\n"
            + ", ".join(f"`{c}`" for c in callees)
            + "\n_Check their contracts with `get_symbol_contract` (preconditions, ownership, required pairing)._"
        )

    # 10. near-duplicates elsewhere (semantic index, if built): the same bug/fix may apply there too
    from ..semantic.search import similar_for_review

    targets = [(r.diff.path, sc.tag.line, sc.tag.qualified) for r, sc in funcs if not sc.is_new][:3]
    similar = await similar_for_review(cfg, targets) if targets else []
    if similar:
        checklist.append("Near-duplicate code exists elsewhere (section 10): check whether the same change is needed there.")
        parts.append("## 10. Similar code elsewhere (semantic index)\n" + "\n".join(similar))

    parts += await _graph_sections(cfg, ds, funcs, base_ref, checklist)

    checklist += [
        "Re-read each changed function's skeleton for missing error handling on new branches.",
        "For signature/return-value changes, confirm every caller in section 4 still satisfies the new contract.",
    ]
    tail = "## ✅ Reviewer checklist\n" + "\n".join(f"- [ ] {c}" for c in dict.fromkeys(checklist))
    # the checklist is the summary of everything above: it must survive the budget, the sections are truncated instead
    budget = max(cfg.review_max_chars - len(tail) - 160, cfg.review_max_chars // 2)
    body = md.enforce_budget("\n\n".join(_fit(parts, budget)), budget)
    return body + "\n\n" + tail


def _fit(parts: list[str], budget: int) -> list[str]:
    """Share the budget between sections: the longest are shortened first, so every section keeps its heading and
    its first findings instead of the last sections disappearing."""
    if sum(len(p) for p in parts) + 2 * (len(parts) - 1) <= budget or len(parts) < 2:
        return parts
    head, rest = parts[0], parts[1:]
    remaining = budget - len(head) - 2 * len(rest)
    lens = sorted(len(p) for p in rest)
    cap = 0
    for i, n in enumerate(lens):
        share = remaining // (len(lens) - i)
        if n <= share:
            remaining -= n
            continue
        cap = share
        break
    else:
        return parts
    cap = max(cap - 130, 200)  # room for the truncation note
    return [head] + [p if len(p) <= cap else md.enforce_budget(p, cap) for p in rest]


async def _graph_sections(cfg: Config, ds, funcs, base_ref: str, checklist: list[str]) -> list[str]:
    """Sections 11-13 from the code graph and git history: reach, completeness, earlier fixes."""
    from ..graph import query as gq
    from .findings import record
    from .graph_tools import graph_for
    from .research import _PLATFORM, _history, _is_fix, switch_coverage_report

    parts: list[str] = []
    try:
        g, _note, usable = await graph_for(cfg)
    except StaticSightError:
        usable = False
    modified = [(r, s) for r, s in funcs if not s.is_new]
    if usable:
        db = g.db
        threads = gq.thread_targets(db)
        reach = []
        for r, sc in modified[:6]:
            targets = [f for f in gq.functions_named(db, sc.tag.qualified) if f.path == r.diff.path] or \
                gq.functions_named(db, sc.tag.qualified)
            if not targets:
                continue
            cache: dict = {}
            seen = {t.key for t in targets}
            frontier, reached = targets, []
            for _ in range(3):
                nxt: dict[tuple, gq.Fn] = {}
                for tgt in frontier:
                    for c in gq.callers_of(db, tgt, cache):
                        if c.caller_key not in seen:
                            seen.add(c.caller_key)
                            fn = gq.caller_fn(db, c)
                            reached.append(fn)
                            nxt[fn.key] = fn
                frontier = [nxt[k] for k in sorted(nxt)]
            entries = sorted({f"`{gq.label(f)}` ({gq.entry_kind(db, f, threads)})" for f in reached
                              if gq.entry_kind(db, f, threads) in ("program", "thread")})
            tests = sorted({gq.label(f) for f in reached if gq.entry_kind(db, f, threads) == "test"})
            line = (f"- `{sc.tag.qualified}`: " + (f"{md.plural(len(reached), 'function')} in "
                    f"{md.plural(len({f.path for f in reached}), 'file')} within 3 calls" if reached else "no callers in the repository"))
            if entries:
                line += "; reached from " + ", ".join(entries[:3])
            line += "; tests: " + (", ".join(f"`{t}`" for t in tests[:3]) if tests else "⚠️ none")
            reach.append(line)
        if reach:
            if any("⚠️ none" in x for x in reach):
                checklist.append("Some changed functions are not reached by any test (section 11): add or run a test that covers them.")
            parts.append("## 11. Reach of changed functions (code graph)\n" + "\n".join(reach)
                         + "\n_Use `get_impact` / `find_entry_paths` for the full chains._")
        gaps: list[str] = []
        enums: set[str] = {sc.tag.name for _, sc in ds.changed_types() if sc.tag.kind == "enum"}
        for r, sc in ds.changed_functions():
            try:
                text = read_lines(cfg.workspace_root / r.diff.path)
            except StaticSightError:
                continue
            for ln in sc.lines:
                for m in re.finditer(r"\b(\w+)::\w+", text[ln - 1] if 0 < ln <= len(text) else ""):
                    if db.execute("SELECT 1 FROM defs WHERE name=? AND kind='enum' LIMIT 1", (m.group(1),)).fetchone():
                        enums.add(m.group(1))
        for e in sorted(enums)[:3]:
            rep = await _safe(switch_coverage_report(cfg, e))
            gaps += [ln for ln in rep.splitlines() if ln.startswith("- ❌") or ln.startswith("- ⚠️")]
        changed = {(r.diff.path, sc.tag.qualified) for r, sc in ds.changed_functions()}
        for r, sc in modified:
            for f in gq.functions_named(db, sc.tag.qualified):
                if (f.path, f.qualified) in changed or f.path == r.diff.path:
                    continue
                if _PLATFORM.search(f.path) or _PLATFORM.search(r.diff.path):
                    fid = record("counterpart_unchanged", "medium", f.path, f.line, f.qualified,
                                 f"`{sc.tag.qualified}` ({r.diff.path}:{sc.tag.line}) changed but its counterpart "
                                 f"`{f.qualified}` ({f.loc}) did not", function=f.qualified)
                    gaps.append(f"- ⚠️ `{f.qualified}` (`{f.loc}`) is the platform twin of changed "
                                f"`{sc.tag.qualified}` but was not changed `{fid}`")
        if gaps:
            checklist.append("Complete the change (section 12): handle the missing enum values and update the unchanged twins, or say why not.")
            parts.append("## 12. Completeness\n" + "\n".join(gaps[:10]))
    fixes = []
    try:
        from ..engines.git import _git

        mine = (await _git(cfg, "rev-list", f"{ds.info.base_sha}..HEAD")).split() if modified else []
    except StaticSightError:
        mine = []
    for r, sc in modified[:5]:
        rows = sorted(sc.lines) or [sc.tag.line]
        hist = await _history(cfg, r.diff.path, rows[0], rows[-1], 10) if r.diff.status == "modified" else []
        for h, date, subject in hist:
            if _is_fix(subject) and not any(full.startswith(h) for full in mine):
                fixes.append(f"- `{sc.tag.qualified}` L{rows[0]}-{rows[-1]}: `{h}` {date} 🐞 {md.clip(subject, 80)}")
    if fixes:
        checklist.append("Changed lines were touched by earlier fixes (section 13): make sure the change does not undo them.")
        parts.append("## 13. Earlier fixes on the changed lines (git history)\n" + "\n".join(list(dict.fromkeys(fixes))[:8])
                     + "\n_Use `get_line_history` for the full story._")
    return parts


def _locking_functions(cfg: Config, live) -> set[tuple[str, str]]:
    """Changed functions whose body takes a lock."""
    out: set[tuple[str, str]] = set()
    cache: dict[str, list[str]] = {}
    for rep, sc in live:
        path = rep.diff.path
        if path not in cache:
            try:
                cache[path] = strip_code(read_lines(cfg.workspace_root / path))
            except StaticSightError:
                cache[path] = []
        lines = cache[path]
        if any(line_events(lines[n - 1]) for n in range(sc.tag.line, min(sc.tag.end, len(lines)) + 1)):
            out.add((path, sc.tag.qualified))
    return out


async def _touched_members(cfg: Config, ds, funcs) -> list[str]:
    classes = sorted({sc.tag.scope for _, sc in funcs if sc.tag.scope})
    if not classes:
        return []
    fc = _FileCache(cfg)
    member_names: dict[str, str] = {}
    files: list[str] = [r.diff.path for r in ds.reports if r.diff.status != "deleted"]
    for cls in classes:
        defs, _ = await find_definitions(cfg, cls.rsplit("::", 1)[-1], fc)
        files += [d.path for d in defs]
    tags = await try_ctags_for_files(cfg, list(dict.fromkeys(files)))
    short_classes = {c.rsplit("::", 1)[-1] for c in classes}
    for ts in tags.values():
        for t in ts:
            if t.kind == "member" and t.scope.rsplit("::", 1)[-1] in short_classes:
                member_names[t.short_name] = t.scope
    if not member_names:
        return []
    ranked: dict[str, int] = {}
    for rep, sc in funcs:
        try:
            lines = strip_code(read_lines(cfg.workspace_root / rep.diff.path))
        except StaticSightError:
            continue
        for n in range(sc.tag.line, min(sc.tag.end, len(lines)) + 1):
            weight = 3 if n in rep.diff.touched_lines else 1
            for ident in re.findall(r"\b[A-Za-z_]\w*\b", lines[n - 1]):
                if ident in member_names:
                    ranked[ident] = ranked.get(ident, 0) + weight
    return [k for k, _ in sorted(ranked.items(), key=lambda kv: (-kv[1], kv[0]))]


def _new_callees(cfg: Config, ds) -> list[str]:
    seen: dict[str, None] = {}
    own = {sc.tag.short_name for r in ds.reports for sc in r.scopes}
    for rep in ds.reports:
        if rep.diff.status == "deleted":
            continue
        try:
            lines = strip_code(read_lines(cfg.workspace_root / rep.diff.path))
        except StaticSightError:
            continue
        for n in sorted(rep.diff.added_lines):
            if not (0 < n <= len(lines)) or re.match(r"^\s*#", lines[n - 1]):
                continue
            code = lines[n - 1]
            for m in _CALLEE.finditer(code):
                name = m.group(1)
                raw_before = code[: m.start()]
                before = raw_before.rstrip()
                if name in _NOT_CALLEES or name in own or re.fullmatch(r"[A-Z][A-Z0-9_]*", name):
                    continue
                if _DECL_BEFORE.search(raw_before) or before.endswith("operator") or re.search(r"(?<!:):$", before):
                    continue  # declaration `Type name(...)`, operator, or ctor init-list `: member(...)`
                seen.setdefault(name)
    return list(seen)[:10]


async def review_changes(base_ref: str = "", max_symbols: int = 8) -> str:
    """START HERE for 'review my changes' / 'what could break?'. One-call C++ review bundle for the current branch (committed + staged + unstaged + untracked vs the merge-base with origin/main, falling back to origin/master). Runs, within a token budget: diff scopes, cppcheck on changed files, branch skeletons of changed functions, caller impact of changed functions, memory-layout risks of changed structs, include blast radius of changed headers, lock-consistency checks on members touched by the diff, and lock-order (deadlock) checks for locks the changed functions take. Ends with a reviewer checklist. Use the individual tools afterwards to drill into any item."""
    return await review_report(load_config(), base_ref, max_symbols)
