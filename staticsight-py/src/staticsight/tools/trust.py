"""Tools that make the agent's work checkable: continue truncated lists, re-verify findings, plan a change, check an edit."""

from __future__ import annotations

import hashlib
import inspect
import json
import re

from ..config import Config, is_header, load_config, workspace_data_dir
from ..core import md
from ..core.cpp_text import extract_leading_comment, strip_code
from ..core.errors import InvalidArgument, StaticSightError
from ..core.paths import read_lines, resolve_in_workspace
from ..graph import query as gq
from . import findings
from .graph_gtags import _obligations, classify_call
from .graph_tools import _check_symbol, graph_for
from .research import _PLATFORM, _history, _is_fix, counterpart_names, switch_coverage_report

ICON = {"strong": "❌", "medium": "⚠️", "weak": "ℹ️"}
RANK = {"strong": 0, "medium": 1, "weak": 2}

# What would prove each kind of finding wrong: the agent should look for this before reporting it.
COUNTER = {
    "leak_path": ["The resource is released by an RAII owner, a `goto cleanup`, or a callee that takes ownership.",
                  "The allocation failed on this path (null), so there is nothing to release."],
    "cppcheck": ["The path cppcheck assumed cannot happen (a precondition or earlier check rules it out).",
                 "A macro or an unparsed header hides the code that makes it safe."],
    "ignored_result": ["The function cannot fail in a way the caller must handle (check its contract).",
                       "The result is intentionally discarded, e.g. best-effort cleanup."],
    "switch_gap": ["The missing value cannot reach this switch (validated or filtered earlier).",
                   "The `default:` branch is the intended handling for it."],
    "counterpart_unchanged": ["The other platform or twin does not have the problem the change fixes.",
                              "It is changed in a separate commit or pull request."],
    "lock_cycle": ["The two orders can never run at the same time (same thread, start-up only, or an outer lock).",
                   "The \"locks\" are different objects that only share a name."],
    "lock_twice": ["The mutex is recursive, or the inner call runs on a path where the lock is not held."],
    "lock_blocking": ["The call does not block in practice (non-blocking socket, zero timeout)."],
    "unlocked_access": ["The access happens before other threads start or after they stop.",
                        "A caller holds the lock (locks taken by callers are not visible to this analysis)."],
    "shared_lock_write": ["The write is to thread-local or per-reader state, or it is atomic."],
    "stale_caller": ["The caller already matches the new signature (default arguments or an overload)."],
}


# ── get_more ─────────────────────────────────────────────────────────────────────────────────────────────────────

async def more_report(token: str) -> str:
    page = md.load_page(token or "")
    if page is None:
        raise InvalidArgument(f"Unknown or expired continuation token `{(token or '').strip()}`.",
                              "Tokens come from the `Next: get_more(...)` note of a truncated list in this workspace.")
    noun, items, header = page
    return "\n".join([f"### ➕ MORE {noun.upper()} ({len(items)} left)", *header,
                      *md.truncate_list(items, md.PAGE_SIZE, noun, header=header)])


async def get_more(token: str) -> str:
    """Returns the next page of a list that another StaticSight tool truncated. Truncated lists end with a note like `…and 42 more call sites. Next: get_more("P1a2b3c")`; pass that token to see the following items (and a new token if there are still more). Use when the first page was not enough to finish the analysis, instead of re-running the tool with a narrower filter."""
    return await more_report(token)


# ── verify_finding ───────────────────────────────────────────────────────────────────────────────────────────────

def _tool_map() -> dict:
    from ..server import TOOLS  # late import: the server module imports this one

    return {fn.__name__: fn for fn in TOOLS}


async def verify_report(cfg: Config, finding_id: str) -> str:
    fid = (finding_id or "").strip().strip("`")
    if not re.fullmatch(r"F[0-9a-f]{6}", fid):
        raise InvalidArgument(f"`{fid}` is not a finding ID.", "IDs look like `F1a2b3c` and appear next to findings.")
    data_dir = workspace_data_dir(cfg)[0]
    f = findings.lookup(data_dir, fid)
    if f is None:
        raise InvalidArgument(f"Unknown finding `{fid}` in this workspace.",
                              "Findings are stored when a tool reports them; run the tool again, then verify its IDs.")
    out = [f"### 🔎 VERIFY `{fid}`: {f['kind']}",
           f"**Claim** ({f['confidence']}): {f['message']}",
           f"**Where:** `{f['path']}:{f['line']}`" + (f" in `{f['function']}`" if f.get("function") else "")]
    tool, args = f.get("tool", ""), dict(f.get("args") or {})
    if tool == "check_my_edit":
        args["baseline"] = "HEAD"
    fn = _tool_map().get(tool) if tool not in ("verify_finding", "get_more") else None
    again: list[findings.Finding] = []
    if fn is not None:
        token = findings.begin()
        try:
            params = inspect.signature(fn).parameters
            await fn(**{k: v for k, v in args.items() if k in params})
        except StaticSightError:
            pass
        finally:
            again = findings.end(token)
    call = f"`{tool}(" + ", ".join(f"{k}={json.dumps(v, ensure_ascii=False)}" for k, v in sorted(args.items())) + ")`"
    if again and fn is not None:
        # store what the re-run reports under the original call, so a "moved" ID can be verified in turn
        findings.flush(cfg.workspace_root, data_dir, again, tool, args)
    same = [g for g in again if g.id == fid]
    moved = [g for g in again if g.id != fid and g.kind == f["kind"] and g.symbol == f["symbol"] and g.path == f["path"]]
    if same:
        out.append(f"**Status:** ✅ Reproduced: re-running {call} reports the same finding.")
    elif moved:
        out.append(f"**Status:** ↪️ Still reported, but it moved: now `{moved[0].path}:{moved[0].line}` (`{moved[0].id}`).")
    elif fn is None:
        out.append(f"**Status:** ❓ Could not re-run `{tool}`; judge from the code below.")
    else:
        out.append(f"**Status:** ❎ Not reproduced: {call} no longer reports it (fixed, or the code changed).")
    try:
        abs_path, rel = resolve_in_workspace(cfg.workspace_root, f["path"])
        lines = read_lines(abs_path)
    except StaticSightError:
        out.append(f"\n⚠️ `{f['path']}` no longer exists.")
        lines = []
    if lines:
        line = int(f["line"])
        code = f.get("code", "")
        if code and not (0 < line <= len(lines) and lines[line - 1].strip() == code):
            hits = [i + 1 for i, t in enumerate(lines) if t.strip() == code]
            if hits:
                line = min(hits, key=lambda n: abs(n - line))
                out.append(f"_The flagged line moved to L{line}._")
            else:
                out.append(f"_The flagged line changed since the finding: was `{md.clip(code, 100)}`._")
        a, b = max(1, line - 3), min(len(lines), line + 3)
        out += ["", "```text", *md.numbered_code(lines[a - 1:b], a, [line]), "```"]
    checks = COUNTER.get(f["kind"], [])
    if checks:
        out.append("**Before reporting it, rule out:**")
        out += [f"- {c}" for c in checks]
    out.append("\n_A finding is evidence, not proof: report it with its ID and what you checked._")
    return "\n".join(out)


async def verify_finding(finding_id: str) -> str:
    """Re-checks one finding reported earlier by a StaticSight tool (IDs like `F1a2b3c` appear next to leaks, cppcheck errors, ignored results, lock-order cycles, unlocked accesses, switch gaps and unchanged counterparts). Re-runs the tool that produced it on the current code and says whether the finding is reproduced, moved or gone, shows the code around it, and lists what would prove it wrong. Use before putting a finding in a review, and after a fix to confirm it is gone."""
    return await verify_report(load_config(), finding_id)


# ── plan_change ──────────────────────────────────────────────────────────────────────────────────────────────────

_SIG_WORDS = re.compile(r"\b(signature|param|parameter|argument|arg|rename|remove|delete|return type|overload)", re.I)


async def plan_report(cfg: Config, symbol: str, change: str = "") -> str:
    sym = _check_symbol(symbol)
    g, note, usable = await graph_for(cfg)
    title = f"### 🗺️ CHANGE PLAN: `{sym}`" + (f" ({md.clip(change.strip(), 80)})" if change and change.strip() else "")
    if not usable:
        return f"{title}\n_{note}_"
    db = g.db
    targets = gq.functions_named(db, sym)
    if not targets:
        return f"{title}\n_{note}_\n❓ No function named `{sym}` in the code graph."
    t0 = targets[0]
    signature_change = bool(change and _SIG_WORDS.search(change))
    out = [title, f"_{note}_"]
    # contract
    try:
        lines = read_lines(cfg.workspace_root / t0.path)
    except StaticSightError:
        lines = []
    protos = [p for p in gq.all_named(db, t0.name, ("prototype",)) if p.qualified == t0.qualified]
    doc: list[str] = []
    for p in protos + [t0]:
        try:
            doc = extract_leading_comment(read_lines(cfg.workspace_root / p.path), p.line - 1)
        except StaticSightError:
            doc = []
        if doc:
            break
    obligations = _obligations(doc)
    out.append(f"**Target:** `{t0.qualified}` (`{t0.loc}`) · returns `{t0.return_type or '?'}`"
               + (f" · {t0.properties}" if t0.properties else ""))
    if obligations:
        out.append("**Contract to keep:** " + "; ".join(md.clip(o, 120) for o in obligations[:4]))
    steps: list[str] = []
    steps.append(f"Edit the definition: `{t0.loc}`" + (f" (+{len(targets) - 1} overloads/variants)" if len(targets) > 1 else ""))
    for p in protos:
        steps.append(f"Update the declaration: `{p.loc}`")
    over = [o for o in gq.overrides_of(db, t0) if o.key != t0.key]
    if over:
        steps.append(f"Keep {md.plural(len(over), 'override')} consistent: " + ", ".join(f"`{o.qualified}` (`{o.loc}`)" for o in over[:6]))
    cache: dict = {}
    calls = sorted({(c.path, c.line, c.caller, c.code) for t in targets for c in gq.callers_of(db, t, cache)})
    if calls:
        files: dict[str, list[int]] = {}
        for p, ln, _, _ in calls:
            files.setdefault(p, []).append(ln)
        verb = "Update" if signature_change else "Check"
        per_file = [f"`{p}` {md.compress_ranges(ls, 6)}" for p, ls in sorted(files.items())]
        steps.append(f"{verb} {md.plural(len(calls), 'call site')} in {md.plural(len(files), 'file')}: "
                     + "; ".join(per_file[:8]) + (f"; +{len(per_file) - 8} more files" if len(per_file) > 8 else ""))
    twins = [f for f in gq.functions_named(db, t0.qualified) if f.key != t0.key
             and (f.path == t0.path or _PLATFORM.search(f.path) or _PLATFORM.search(t0.path))]
    pairs = [f for cand, _, _ in counterpart_names(t0.name) for f in gq.functions_named(db, cand)]
    if twins or pairs:
        steps.append("Mirror the change in counterparts: " + ", ".join(f"`{f.qualified}` (`{f.loc}`)" for f in (twins + pairs)[:6]))
    if protos and any(is_header(p.path) for p in protos):
        hdr = next(p.path for p in protos if is_header(p.path))
        base = hdr.rsplit("/", 1)[-1]
        n = db.execute("SELECT COUNT(DISTINCT path) FROM includes WHERE target=? OR target LIKE ?", (base, f"%/{base}")).fetchone()[0]
        if n:
            steps.append(f"Expect a rebuild of `{hdr}` includers: {md.plural(n, 'file')} include it directly "
                         f"(`get_include_blast_radius(\"{hdr}\")` for the full list)")
    # tests
    seen = {t.key for t in targets}
    frontier, tests = sorted(targets, key=lambda f: f.key), []
    for _ in range(3):
        nxt: dict[tuple, gq.Fn] = {}
        for tgt in frontier:
            for c in gq.callers_of(db, tgt, cache):
                if c.caller_key in seen:
                    continue
                seen.add(c.caller_key)
                fn = gq.caller_fn(db, c)
                (tests.append(fn) if gq.is_test_path(fn.path) else nxt.__setitem__(fn.key, fn))
        frontier = [nxt[k] for k in sorted(nxt)]
    if tests:
        steps.append("Run the tests that reach it: " + ", ".join(f"`{gq.label(t)}` (`{t.loc}`)" for t in sorted(tests, key=lambda f: f.key)[:6]))
    else:
        steps.append("Add a test first: no test reaches it within 3 calls")
    out.append("\n**Steps**")
    out += [f"{i}. [ ] {s}" for i, s in enumerate(steps, 1)]
    # risks
    risks: list[str] = []
    hist = await _history(cfg, t0.path, t0.line, max(t0.line, t0.end), 10)
    fixes = [h for h in hist if _is_fix(h[2])]
    if fixes:
        risks.append(f"{md.plural(len(fixes), 'earlier fix', 'es')} touched it: " + ", ".join(f"`{h[0]}` {md.clip(h[2], 60)}" for h in fixes[:3])
                     + (". Do not undo it." if len(fixes) == 1 else ". Do not undo them."))
    if lines:
        body = strip_code(lines[t0.line - 1:t0.end])
        from ..core.locks import line_events

        held = sorted({mx for ln in body for e in line_events(ln) for mx in e.mutexes})
        if held:
            risks.append("Takes " + ", ".join(f"`{m}`" for m in held[:4]) + ": check `get_lock_graph` before adding calls under it.")
    ignored = [c for c in calls if classify_call(c[3], t0.name).startswith("⚠️")]
    if ignored and t0.return_type not in ("", "void"):
        who = "1 caller ignores" if len(ignored) == 1 else f"{len(ignored)} callers ignore"
        risks.append(f"{who} the `{t0.return_type}` result: new error values will go unnoticed there.")
    if risks:
        out.append("\n**Risks**")
        out += [f"- {r}" for r in risks]
    out.append("\n_After editing: `check_my_edit()` for a quick check, then `review_changes()` before committing._")
    return "\n".join(out)


async def plan_change(symbol: str, change: str = "") -> str:
    """Plans a change to one function before you edit it: an ordered checklist of every place to touch (definition, declarations, overrides, call sites grouped by file, platform or naming counterparts, header includers), the tests that reach it, its contract, and risks (earlier fixes on these lines, locks it takes, callers that ignore its result). Describe the change in `change` (e.g. "add a timeout parameter"): signature words turn call-site checks into required updates. Use before a refactor or any edit whose ripple you have not mapped yet."""
    return await plan_report(load_config(), symbol, change)


# ── check_my_edit ────────────────────────────────────────────────────────────────────────────────────────────────

def _snap_key(r, s) -> str:
    """One entry per function; the signature keeps overloads in the same file apart."""
    return f"{r.diff.path}|{s.tag.qualified}|{s.tag.signature}"


def _body_hash(lines: list[str], a: int, b: int) -> str:
    return hashlib.sha1("\n".join(lines[a - 1:b]).encode("utf-8")).hexdigest()[:12]


async def _collect(coro) -> list[findings.Finding]:
    token = findings.begin()
    try:
        await coro
    except StaticSightError:
        pass
    finally:
        found = findings.end(token)
    return found


async def edit_check_report(cfg: Config, baseline: str = "last") -> str:
    from .diff_scopes import analyse_diff
    from .static_cpp import static_audit_report
    from .syntax_ctags import build_skeleton

    baseline = (baseline or "last").strip()
    if baseline not in ("last", "HEAD"):
        raise InvalidArgument("`baseline` must be \"last\" (changes since the previous check) or \"HEAD\" (all uncommitted changes).")
    ds = await analyse_diff(cfg, "HEAD")
    funcs = [(r, s) for r, s in ds.changed_functions() if r.diff.status != "deleted"]
    title = "### 🩺 EDIT CHECK"
    if not funcs:
        return f"{title}\n✅ No uncommitted changes to C/C++ functions (the working tree matches HEAD)."
    snap_path = workspace_data_dir(cfg)[0] / "edit_snapshot.json"
    try:
        snap = json.loads(snap_path.read_text(encoding="utf-8")) if baseline == "last" else {}
    except (OSError, ValueError):
        snap = {}
    texts: dict[str, list[str]] = {}
    current: dict[str, str] = {}
    for r, s in funcs:
        if r.diff.path not in texts:
            try:
                texts[r.diff.path] = read_lines(cfg.workspace_root / r.diff.path)
            except StaticSightError:
                texts[r.diff.path] = []
        current[_snap_key(r, s)] = _body_hash(texts[r.diff.path], s.tag.line, s.tag.end)
    picked = [(r, s) for r, s in funcs if current[_snap_key(r, s)] != snap.get(_snap_key(r, s))]
    since = "since the last check" if baseline == "last" and snap else "vs HEAD"
    shown = picked[:8]
    # functions not checked this time keep their old snapshot value, so the next call picks them up
    saved = dict(current)
    for r, s in picked[8:]:
        k = _snap_key(r, s)
        if k in snap:
            saved[k] = snap[k]
        else:
            saved.pop(k, None)
    try:
        snap_path.parent.mkdir(parents=True, exist_ok=True)
        snap_path.write_text(json.dumps(saved, indent=0, sort_keys=True), encoding="utf-8")
    except OSError:
        pass
    if not picked:
        return (f"{title}\n✅ Nothing changed since the last check ({md.plural(len(funcs), 'function')} still differ from HEAD; "
                "pass `baseline=\"HEAD\"` to check them all again).")
    out = [f"{title}: {md.plural(len(picked), 'changed function')} {since}"]
    found: list[findings.Finding] = []
    g, note, usable = await graph_for(cfg)
    db = g.db if usable else None
    diff_files = {r.diff.path for r in ds.reports}
    changed_keys = {(r.diff.path, s.tag.qualified) for r, s in funcs}
    for r, s in shown:
        rel, t = r.diff.path, s.tag
        flags = ["new"] if s.is_new else []
        if s.signature_changed:
            flags.append(f"signature `{s.signature_changed.split(' -> ')[0]}` → `{s.signature_changed.split(' -> ')[-1]}`")
        out.append(f"- `{t.qualified}` (`{rel}:{t.line}`)" + (f": {'; '.join(flags)}" if flags else ""))
        lines = texts.get(rel, [])
        if lines and not is_header(rel):
            found += await _collect(_skeleton(build_skeleton, lines, t, rel, s.lines))
        if db is not None and s.signature_changed and not s.is_new:
            cache: dict = {}
            for fn in gq.functions_named(db, t.qualified):
                for c in gq.callers_of(db, fn, cache):
                    if c.path not in diff_files:
                        found.append(findings.make("stale_caller", "strong", c.path, c.line, t.qualified,
                                                   f"`{gq.caller_label(db, c)}` calls `{t.qualified}` but its file is not "
                                                   "part of the change, so it still uses the old signature",
                                                   gq.caller_label(db, c)))
        if db is not None:
            for f in gq.functions_named(db, t.qualified):
                if (f.path, f.qualified) in changed_keys or f.path == rel:
                    continue
                if _PLATFORM.search(f.path) or _PLATFORM.search(rel):
                    found.append(findings.make("counterpart_unchanged", "medium", f.path, f.line, f.qualified,
                                               f"`{t.qualified}` ({rel}:{t.line}) changed but its counterpart "
                                               f"`{f.qualified}` ({f.loc}) did not", f.qualified))
    if len(picked) > len(shown):
        out.append(f"- _…and {len(picked) - len(shown)} more changed functions (checked in the next call)._")
    for rel in sorted({r.diff.path for r, _ in shown if not is_header(r.diff.path)}):
        found += [f for f in await _collect(static_audit_report(cfg, rel, True, "HEAD")) if f.kind == "cppcheck"]
    enums: set[str] = set()
    if db is not None:
        for r, s in shown:
            for ln in s.lines:
                text = texts.get(r.diff.path, [])
                for m in re.finditer(r"\b(\w+)::\w+", text[ln - 1] if 0 < ln <= len(text) else ""):
                    if db.execute("SELECT 1 FROM defs WHERE name=? AND kind='enum' LIMIT 1", (m.group(1),)).fetchone():
                        enums.add(m.group(1))
        for r, s in ds.changed_types():
            if s.tag.kind == "enum":
                enums.add(s.tag.name)
    for e in sorted(enums):
        found += await _collect(switch_coverage_report(cfg, e))
    uniq: dict[str, findings.Finding] = {}
    for f in found:
        uniq.setdefault(f.id, f)
    for f in uniq.values():
        findings.add(f)
    items = sorted(uniq.values(), key=lambda f: (RANK[f.confidence], f.path, f.line, f.id))
    if items:
        out.append(f"\n**{md.plural(len(items), 'finding')}**")
        out += md.truncate_list([f"- {ICON[f.confidence]} `{f.id}` `{f.path}:{f.line}` {f.message}" for f in items],
                                load_config().max_results, "findings")
    else:
        out.append("\n✅ The quick checks found nothing: exit paths release what they allocate, cppcheck is clean on the "
                   "changed lines, callers match changed signatures, switches cover changed enums, platform twins agree.")
    out.append("\n_Checks: exit-path leaks, cppcheck on changed lines, callers of changed signatures outside the diff, "
               "switch coverage of enums used in the change, unchanged platform twins. Next: `verify_finding(\"F…\")`, "
               "then `review_changes()` before committing._")
    return "\n".join(out)


async def _skeleton(build, lines: list[str], t, rel: str, changed: set[int]) -> None:
    build(lines, t.line, min(t.end, len(lines)), t.qualified, rel, changed)


async def check_my_edit(baseline: str = "last") -> str:
    """Fast self-check of your own uncommitted C++ edits, meant to run after every edit: for each function changed since the previous check (baseline="last", the default) or since HEAD (baseline="HEAD"), it looks for exit paths that leak what the function allocates, cppcheck errors on the changed lines, callers outside the change that still use an old signature, switches missing a value of an enum the change uses, and platform twins that were not changed. Findings get IDs for `verify_finding`. Use while coding; use `review_changes` for the full review before committing."""
    return await edit_check_report(load_config(), baseline)
