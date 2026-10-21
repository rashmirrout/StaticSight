"""Research tools: get_context_pack, get_line_history, get_change_hotspots, find_switch_coverage, find_counterparts,
find_related_tests, find_log_origin."""

from __future__ import annotations

import datetime as _dt
import re

from ..config import Config, is_cpp_file, load_config
from ..core import md
from ..core.cpp_text import extract_leading_comment, strip_code
from ..core.errors import InvalidArgument, StaticSightError
from ..core.locks import line_events
from ..core.paths import read_lines, resolve_in_workspace
from ..engines.git import _git
from ..engines.rg import rg_search
from ..graph import query as gq
from .findings import record
from .graph_gtags import _obligations, classify_call
from .graph_tools import _check_symbol, graph_for

_FIX = re.compile(r"\b(fix(e[sd])?|bug|revert\w*|crash\w*|leak\w*|hotfix|regress\w*|race|deadlock|overflow|cve)\b", re.I)


def _is_fix(subject: str) -> bool:
    return bool(_FIX.search(subject))


# ------------------------------------------------------------------------------------------------ get_line_history
async def _blame(cfg: Config, rel: str, a: int, b: int) -> list[tuple[str, int, str, str]]:
    """(sha, final line, yyyy-mm-dd, summary) per line."""
    text = await _git(cfg, "blame", "-w", "-M", "-C", "--line-porcelain", "-L", f"{a},{b}", "--", rel)
    out = []
    sha = ""
    final = 0
    info: dict[str, dict[str, str]] = {}
    for ln in text.splitlines():
        m = re.match(r"^([0-9a-f]{40}) \d+ (\d+)", ln)
        if m:
            sha, final = m.group(1), int(m.group(2))
            info.setdefault(sha, {})
            continue
        if ln.startswith("author-time "):
            info[sha]["date"] = _dt.datetime.fromtimestamp(int(ln.split()[1]), _dt.timezone.utc).strftime("%Y-%m-%d")
        elif ln.startswith("summary "):
            info[sha]["summary"] = ln[len("summary "):]
        elif ln.startswith("\t"):
            out.append((sha, final, info[sha].get("date", ""), info[sha].get("summary", "")))
    return out


async def _history(cfg: Config, rel: str, a: int, b: int, n: int = 10) -> list[tuple[str, str, str]]:
    try:
        text = await _git(cfg, "log", f"-L{a},{b}:{rel}", "-s", "--format=%h%x09%ad%x09%s", "--date=short", f"-n{n}")
    except StaticSightError:
        return []
    out = []
    for ln in text.splitlines():
        parts = ln.split("\t", 2)
        if len(parts) == 3 and re.fullmatch(r"[0-9a-f]{4,40}", parts[0]):
            out.append((parts[0], parts[1], parts[2]))
    return out


async def line_history_report(cfg: Config, file_path: str, start_line: int, end_line: int = 0) -> str:
    abs_path, rel = resolve_in_workspace(cfg.workspace_root, file_path)
    lines = read_lines(abs_path)
    a = int(start_line or 0)
    b = int(end_line or 0) or a
    if a < 1 or a > len(lines):
        raise InvalidArgument(f"`start_line` {a} is outside `{rel}` (1-{len(lines)}).")
    b = max(a, min(b, len(lines), a + 199))
    title = f"### 🕰️ LINE HISTORY: `{rel}` L{a}" + (f"-{b}" if b != a else "")
    try:
        blame = await _blame(cfg, rel, a, b)
    except StaticSightError as exc:
        return f"{title}\n❓ git has no history for these lines ({exc.message})."
    out = [title, "**Last change per line** (git blame, ignoring whitespace and moved code)"]
    groups: list[list] = []
    for sha, ln, date, summ in blame:
        if groups and groups[-1][0] == sha and groups[-1][2] == ln - 1:
            groups[-1][2] = ln
        else:
            groups.append([sha, ln, ln, date, summ])
    rows = []
    for sha, s, e, date, summ in groups:
        rng = f"L{s}" if s == e else f"L{s}-{e}"
        if set(sha) == {"0"}:
            rows.append(f"- {rng} ✏️ not committed yet")
        else:
            rows.append(f"- {rng} `{sha[:7]}` {date}{' 🐞' if _is_fix(summ) else ''} {md.clip(summ, 100)}")
    out += md.truncate_list(rows, cfg.max_results, "line ranges")
    hist = await _history(cfg, rel, a, b)
    fixes = [h for h in hist if _is_fix(h[2])]
    if hist:
        out.append("**Commits that changed these lines** (newest first)")
        out += [f"{i}. `{h}` {d}{' 🐞' if _is_fix(s) else ''} {md.clip(s, 100)}" for i, (h, d, s) in enumerate(hist, 1)]
    if fixes:
        out.append(f"\n⚠️ {md.plural(len(fixes), 'earlier fix', 'es')} touched these lines: make sure the change does not "
                   "undo it (" + ", ".join(f"`{h}`" for h, _, _ in fixes[:3]) + ").")
    return "\n".join(out)


async def get_line_history(file_path: str, start_line: int, end_line: int = 0) -> str:
    """Explains why lines look the way they do and whether they were fixed before: git blame per line (ignoring whitespace and moved/copied code) and every commit that changed the range, with bug-fix and revert commits marked 🐞. Use on lines a diff changes or removes, to catch changes that undo an earlier fix, and to find who-changed-what context for a review. No author names are shown."""
    return await line_history_report(load_config(), file_path, start_line, end_line)


# ------------------------------------------------------------------------------------------------ get_change_hotspots
_CPP_PATHSPECS = ["*.c", "*.cc", "*.cpp", "*.cxx", "*.h", "*.hh", "*.hpp", "*.hxx"]


async def hotspots_report(cfg: Config, path_glob: str = "", since_days: int = 365) -> str:
    from ..core.paths import matches_glob

    since_days = max(1, min(int(since_days or 365), 3650))
    head_ts = int((await _git(cfg, "log", "-1", "--format=%ct")).strip() or "0")
    since = _dt.datetime.fromtimestamp(head_ts - since_days * 86400, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    text = await _git(cfg, "log", f"--since={since}", "--no-merges", "--numstat", "--format=%x1e%h%x1f%s", "--",
                      *_CPP_PATHSPECS)
    stats: dict[str, list[int]] = {}   # path -> [commits, fixes, churn]
    for chunk in text.split("\x1e"):
        if not chunk.strip():
            continue
        head, _, rest = chunk.partition("\n")
        subj = head.split("\x1f", 1)[1] if "\x1f" in head else ""
        fix = _is_fix(subj)
        for ln in rest.splitlines():
            parts = ln.split("\t")
            if len(parts) != 3:
                continue
            add = int(parts[0]) if parts[0].isdigit() else 0
            rem = int(parts[1]) if parts[1].isdigit() else 0
            p = parts[2]
            if " => " in p:
                continue
            s = stats.setdefault(p, [0, 0, 0])
            s[0] += 1
            s[1] += 1 if fix else 0
            s[2] += add + rem
    title = f"### 🔥 CHANGE HOTSPOTS: last {since_days} days of history" + (f" in `{path_glob}`" if path_glob else "")
    stats = {p: s for p, s in stats.items() if (cfg.workspace_root / p).is_file() and (not path_glob or matches_glob(p, path_glob))}
    if not stats:
        return f"{title}\n✅ No C/C++ changes in that period."
    g, note, usable = await graph_for(cfg)
    fanin: dict[str, int] = {}
    if usable:
        db = g.db
        for p in stats:
            names = [r[0] for r in db.execute("SELECT DISTINCT name FROM defs WHERE path=? AND kind='function'", (p,))]
            n = 0
            for nm in names:
                n += db.execute("SELECT COUNT(*) FROM calls WHERE callee=? AND path<>? AND how<>'ref'", (nm, p)).fetchone()[0]
            fanin[p] = n
    rows = []
    for p, (commits, fixes, churn) in stats.items():
        fi = fanin.get(p, 0)
        score = commits * (1 + 2 * fixes) * (1 + fi).bit_length()
        rows.append((score, p, commits, fixes, churn, fi))
    rows.sort(key=lambda r: (-r[0], r[1]))
    header = ["| File | Commits | Fixes 🐞 | Lines changed | Calls from other files | Score |", "|---|---|---|---|---|---|"]
    out = [title, f"_{note}_" if usable else "_Code graph not available: fan-in not counted._", *header]
    body = [f"| `{p}` | {c} | {fx} | {ch} | {fi} | {sc} |" for sc, p, c, fx, ch, fi in rows]
    out += md.truncate_list(body, cfg.max_results, "files", header=header)
    out.append("\n_Score = commits × (1 + 2 × fix commits) × (1 + ⌊log₂(1 + calls from other files)⌋): files that change often, "
               "keep needing fixes and are used widely deserve the closest review._")
    return "\n".join(out)


async def get_change_hotspots(path_glob: str = "", since_days: int = 365) -> str:
    """Ranks the C/C++ files that deserve the closest review: how often they changed (git history up to HEAD), how many of those changes were bug fixes or reverts, how many lines changed, and how many calls come in from other files (code graph). Use to decide where to look hardest in a large diff, or to find fragile areas of an unfamiliar codebase."""
    return await hotspots_report(load_config(), path_glob, since_days)


# ------------------------------------------------------------------------------------------------ find_switch_coverage
_CASE = re.compile(r"\bcase\s+((?:[A-Za-z_]\w*\s*::\s*)*[A-Za-z_]\w*)\s*:(?!:)")
_DEFAULT = re.compile(r"\bdefault\s*:")
_SWITCH = re.compile(r"\bswitch\s*\(")


def _switch_blocks(stripped: list[str]) -> list[tuple[int, int, list[str], bool]]:
    """(switch line, end line, case labels at depth 1, has default) for every switch in a file."""
    text = "\n".join(stripped)
    starts = [0]
    for ln in stripped:
        starts.append(starts[-1] + len(ln) + 1)

    def line_of(pos: int) -> int:
        lo, hi = 0, len(starts) - 1
        while lo < hi:
            mid = (lo + hi + 1) // 2
            if starts[mid] <= pos:
                lo = mid
            else:
                hi = mid - 1
        return lo + 1

    out = []
    for m in _SWITCH.finditer(text):
        depth, i = 1, m.end()
        while i < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[i], 0)
            i += 1
        brace = text.find("{", i)
        if brace < 0 or text[i:brace].strip():
            continue
        depth, j = 0, brace
        body_parts: list[str] = []
        k = brace + 1
        depth = 1
        seg_start = k
        while k < len(text) and depth:
            ch = text[k]
            if ch == "{":
                if depth == 1:
                    body_parts.append(text[seg_start:k])
                depth += 1
            elif ch == "}":
                depth -= 1
                if depth == 1:
                    seg_start = k + 1
            k += 1
        if depth == 0:
            body_parts.append(text[seg_start:k - 1])
        top = " ".join(body_parts)
        labels = [re.sub(r"\s+", "", lab) for lab in _CASE.findall(top)]
        out.append((line_of(m.start()), line_of(k - 1), labels, bool(_DEFAULT.search(top))))
    return out


async def switch_coverage_report(cfg: Config, enum_name: str) -> str:
    name = _check_symbol(enum_name).rsplit("::", 1)[-1]
    g, note, usable = await graph_for(cfg)
    title = f"### 🧩 SWITCH COVERAGE: `{name}`"
    if not usable:
        return f"{title}\n_{note}_"
    db = g.db
    enum = list(db.execute("SELECT path, line FROM defs WHERE name=? AND kind='enum' ORDER BY path, line", (name,)))
    values = [r[0] for r in db.execute("SELECT name FROM defs WHERE kind='enumerator' AND (scope=? OR scope LIKE ?) "
                                       "ORDER BY path, line", (name, f"%::{name}"))]
    values = list(dict.fromkeys(values))
    if not enum or not values:
        return f"{title}\n_{note}_\n❓ No enum named `{name}` with enumerators in the code graph."
    vs = set(values)
    res = await rg_search(cfg, values, word=True, fixed=True)
    out = [title, f"_{note}_", f"Defined at `{enum[0][0]}:{enum[0][1]}` with {md.plural(len(values), 'value')}: "
           + ", ".join(f"`{v}`" for v in values) + "."]
    rows = []
    gaps = 0
    for path in sorted(res.files):
        try:
            stripped = strip_code(read_lines(cfg.workspace_root / path))
        except StaticSightError:
            continue
        for line, _, labels, has_default in _switch_blocks(stripped):
            short = [lab.rsplit("::", 1)[-1] for lab in labels]
            quals = [lab.rsplit("::", 1)[0] if "::" in lab else "" for lab in labels]
            hits = [s for s in short if s in vs]
            if not hits or any(s not in vs for s in short) or any(q and q.rsplit("::", 1)[-1] != name for q in quals):
                continue
            fn = gq.enclosing_function(db, path, line)
            where = f"`{path}:{line}`" + (f" in `{fn.qualified}`" if fn else "")
            missing = [v for v in values if v not in set(short)]
            if not missing:
                rows.append(f"- ✅ {where}: all {len(values)} values handled")
                continue
            gaps += 1
            miss = ", ".join(f"`{v}`" for v in missing)
            if has_default:
                fid = record("switch_gap", "medium", path, line, name, f"switch{' in ' + fn.qualified if fn else ''} misses {', '.join(missing)} (falls into default)",
                             function=fn.qualified if fn else "")
                rows.append(f"- ⚠️ {where}: missing {miss}; handled by `default:` — check that is right `{fid}`")
            else:
                fid = record("switch_gap", "strong", path, line, name, f"switch{' in ' + fn.qualified if fn else ''} misses {', '.join(missing)} (no default)",
                             function=fn.qualified if fn else "")
                rows.append(f"- ❌ {where}: missing {miss} and no `default:` — the value falls through silently `{fid}`")
    if not rows:
        out.append("No `switch` over this enum was found (it may be handled with `if` chains or lookup tables).")
    else:
        out.append(f"{md.plural(len(rows), 'switch', 'es')}, {gaps} with missing values:")
        out += md.truncate_list(rows, cfg.max_results, "switches")
    return "\n".join(out)


async def find_switch_coverage(enum_name: str) -> str:
    """Checks every `switch` over an enum against the enum's values: lists each switch (file:line, function) and the values it does not handle, and whether a `default:` catches them. Use when an enum gains, loses or renames a value, the classic 'added a value, forgot a case' bug."""
    return await switch_coverage_report(load_config(), enum_name)


# ------------------------------------------------------------------------------------------------ find_counterparts
PAIRS = [("serialize", "deserialize"), ("encode", "decode"), ("marshal", "unmarshal"), ("pack", "unpack"),
         ("open", "close"), ("register", "unregister"), ("init", "uninit"), ("init", "deinit"),
         ("initialize", "uninitialize"), ("start", "stop"), ("acquire", "release"), ("alloc", "free"),
         ("allocate", "free"), ("create", "destroy"), ("create", "delete"), ("add", "remove"), ("push", "pop"),
         ("lock", "unlock"), ("connect", "disconnect"), ("load", "unload"), ("enable", "disable"),
         ("attach", "detach"), ("subscribe", "unsubscribe"), ("begin", "end"), ("enter", "leave"), ("read", "write"),
         ("get", "set"), ("insert", "erase"), ("send", "recv"), ("send", "receive"), ("increment", "decrement"),
         ("save", "load"), ("to", "from")]
_PLATFORM = re.compile(r"(^|[/_.-])(win|windows|win32|nt|posix|linux|unix|mac|darwin|apple|android)([/_.-]|$)", re.I)


def _style(word: str, like: str) -> str:
    if like.isupper():
        return word.upper()
    if like[:1].isupper():
        return word[:1].upper() + word[1:]
    return word


def counterpart_names(name: str) -> list[tuple[str, str, str]]:
    """(candidate, word, other) by swapping one word of the identifier for its pair (snake_case or CamelCase)."""
    out = []
    for a, b in PAIRS:
        for x, y in ((a, b), (b, a)):
            for m in re.finditer(re.escape(x), name, re.I):
                s, e = m.start(), m.end()
                prev = name[s - 1] if s else ""
                nxt = name[e] if e < len(name) else ""
                word = name[s:e]
                left_ok = not prev or prev == "_" or (prev.islower() and word[:1].isupper()) or prev.isdigit()
                right_ok = not nxt or nxt == "_" or nxt.isupper() or nxt.isdigit()
                if left_ok and right_ok:
                    cand = name[:s] + _style(y, word) + name[e:]
                    if cand != name:
                        out.append((cand, x, y))
    return list(dict.fromkeys(out))


async def _changed_functions(cfg: Config) -> set[tuple[str, str]] | None:
    try:
        from .diff_scopes import analyse_diff

        ds = await analyse_diff(cfg, "")
    except StaticSightError:
        return None
    return {(sc.tag.path, sc.tag.qualified) for _, sc in ds.changed_functions()}


async def _cochange(cfg: Config, rel: str, limit: int = 400) -> list[tuple[str, int, int]]:
    try:
        text = await _git(cfg, "log", f"-n{limit}", "--no-merges", "--name-only", "--format=%x1e", "--", *_CPP_PATHSPECS)
    except StaticSightError:
        return []
    mine = 0
    together: dict[str, int] = {}
    for chunk in text.split("\x1e"):
        files = [f for f in chunk.split("\n") if f.strip()]
        if not files or len(files) > 20 or rel not in files:
            continue  # bulk commits (imports, reformatting) say nothing about coupling
        mine += 1
        for f in files:
            if f != rel:
                together[f] = together.get(f, 0) + 1
    return sorted(((f, n, mine) for f, n in together.items() if n >= 2 and n * 2 >= mine), key=lambda r: (-r[1], r[0]))[:5]


async def counterparts_report(cfg: Config, symbol: str) -> str:
    sym = _check_symbol(symbol)
    g, note, usable = await graph_for(cfg)
    title = f"### 🪞 COUNTERPARTS: `{sym}`"
    if not usable:
        return f"{title}\n_{note}_"
    db = g.db
    targets = gq.functions_named(db, sym)
    if not targets:
        return f"{title}\n_{note}_\n❓ No function named `{sym}` in the code graph."
    changed = await _changed_functions(cfg)
    mine = [t for t in targets if changed and (t.path, t.qualified) in changed]
    t0 = (mine or targets)[0]
    out = [title, f"_{note}_"]
    me_changed = bool(mine)
    out.append(f"`{t0.qualified}` (`{t0.loc}`)" + (" — ✏️ changed in the current diff" if me_changed else ""))

    def status(f: gq.Fn) -> str:
        if changed is None or not me_changed:
            return ""
        if (f.path, f.qualified) in changed:
            return " — ✏️ also changed"
        fid = record("counterpart_unchanged", "medium", f.path, f.line, f.qualified,
                     f"`{t0.qualified}` ({t0.loc}) changed but its counterpart `{f.qualified}` ({f.loc}) did not", function=f.qualified)
        return f" — ⚠️ not changed in this diff `{fid}`"

    naming = []
    for cand, x, y in counterpart_names(t0.name):
        for f in gq.functions_named(db, cand if not t0.cls else f"{t0.cls}::{cand}") or gq.functions_named(db, cand):
            naming.append(f"- `{f.qualified}` (`{f.loc}`) — {x} ↔ {y}{status(f)}")
    out.append("**Naming pairs**")
    out += list(dict.fromkeys(naming)) or ["- none found"]
    twins = []
    for f in gq.functions_named(db, t0.qualified):
        if f.key == t0.key:
            continue
        if f.path == t0.path:
            twins.append(f"- `{f.qualified}` (`{f.loc}`) — same file, likely an `#ifdef` variant{status(f)}")
        elif _PLATFORM.search(f.path) or _PLATFORM.search(t0.path):
            twins.append(f"- `{f.qualified}` (`{f.loc}`) — platform variant{status(f)}")
    out.append("**Platform or `#ifdef` twins**")
    out += twins or ["- none found"]
    co = await _cochange(cfg, t0.path)
    out.append("**Files that usually change together** (git history, bulk commits ignored)")
    out += [f"- `{f}` — {n} of {m} commits that touched `{t0.path}`" for f, n, m in co] or ["- none with at least 2 shared commits"]
    out.append("\n_Use `find_similar_code` for copy-paste twins by meaning._")
    return "\n".join(out)


async def find_counterparts(symbol: str) -> str:
    """Finds code that should change together with a function: its naming pair (encode/decode, serialize/deserialize, open/close, register/unregister, acquire/release, ...), platform or #ifdef twins (the same function in *_win / *_posix files), and files that historically change together with its file (git). When the function is changed in the current diff, flags the counterparts that were not. Use to catch half-done changes."""
    return await counterparts_report(load_config(), symbol)


# ------------------------------------------------------------------------------------------------ find_related_tests
TEST_MACROS = gq.TEST_MACROS
test_label = gq.label


async def related_tests_report(cfg: Config, symbol: str, depth: int = 3) -> str:
    sym = _check_symbol(symbol)
    depth = max(1, min(int(depth or 3), 6))
    g, note, usable = await graph_for(cfg)
    title = f"### 🧪 RELATED TESTS: `{sym}`"
    if not usable:
        return f"{title}\n_{note}_"
    db = g.db
    targets = gq.functions_named(db, sym)
    if not targets:
        return f"{title}\n_{note}_\n❓ No function named `{sym}` in the code graph."
    cache: dict = {}
    found: dict[tuple, tuple[int, gq.Fn, gq.Call]] = {}
    seen = {t.key for t in targets}
    frontier = sorted(targets, key=lambda f: f.key)
    for level in range(1, depth + 1):
        nxt: dict[tuple, gq.Fn] = {}
        for tgt in frontier:
            for c in gq.callers_of(db, tgt, cache):
                if c.caller_key in seen:
                    continue
                seen.add(c.caller_key)
                fn = gq.caller_fn(db, c)
                if gq.is_test_path(fn.path):
                    found[fn.key] = (level, fn, c)
                else:
                    nxt[fn.key] = fn
        frontier = [nxt[k] for k in sorted(nxt)]
    out = [title, f"_{note}_"]
    if found:
        out.append("**Tests that reach it through calls**")
        out += [f"- `{test_label(fn)}` (`{fn.loc}`) — " + ("calls it directly" if lvl == 1 else f"{lvl} calls away")
                + f" at `{c.path}:{c.line}`" for lvl, fn, c in sorted(found.values(), key=lambda v: (v[0], v[1].key))]
    res = await rg_search(cfg, targets[0].name, word=True, fixed=True)
    mentions = []
    for p in sorted(res.files):
        if not gq.is_test_path(p):
            continue
        for m in res.files[p]:
            if not m.is_match:
                continue
            fn = gq.enclosing_function(db, p, m.line)
            if fn is not None and fn.key in found:
                continue
            mentions.append(f"- `{p}:{m.line}`" + (f" in `{test_label(fn)}`" if fn else "") + f": `{md.clip(m.text.strip(), 90)}`")
    if mentions:
        out.append("**Test files that mention it** (no resolved call)")
        out += md.truncate_list(mentions, cfg.max_results, "mentions")
    if not found and not mentions:
        out.append(f"⚠️ No test reaches `{sym}` within {md.plural(depth, 'call')}, and no test file mentions it. "
                   "Consider adding one before changing it.")
    return "\n".join(out)


async def find_related_tests(symbol: str, depth: int = 3) -> str:
    """Lists the tests that exercise a function: test functions (in test folders or test files, including gtest/Catch/Boost TEST macros) that reach it through calls within `depth` levels, plus test files that mention it. Reports when no test covers it. Use to know which tests to run or update after a change, and whether a new test is needed."""
    return await related_tests_report(load_config(), symbol, depth)


# ------------------------------------------------------------------------------------------------ get_context_pack
_FILE_LINE = re.compile(r"^(.+?):(\d+)$")


async def context_pack_report(cfg: Config, target: str, max_chars: int = 6000) -> str:
    from .ripgrep_mem import blast_radius_report
    from .syntax_ctags import branch_skeleton_report

    target = (target or "").strip()
    if not target:
        raise InvalidArgument("`target` is empty: pass a function name or `file:line`.")
    max_chars = max(1500, min(int(max_chars or 6000), 30000))
    g, note, usable = await graph_for(cfg)
    if not usable:
        return f"### 📦 CONTEXT PACK: `{target}`\n_{note}_"
    db = g.db
    fn = None
    m = _FILE_LINE.match(target)
    if m and ("/" in m.group(1) or "." in m.group(1)):
        _, rel = resolve_in_workspace(cfg.workspace_root, m.group(1))
        fn = gq.enclosing_function(db, rel, int(m.group(2)))
        if fn is None:
            raise InvalidArgument(f"No function encloses `{rel}:{m.group(2)}`.")
    else:
        sym = _check_symbol(target)
        fns = gq.functions_named(db, sym)
        if not fns:
            types = gq.types_named(db, sym.rsplit("::", 1)[-1])
            if types:
                from .graph_tools import type_hierarchy_report

                hdr = types[0][1]
                parts = [await type_hierarchy_report(cfg, sym)]
                if not is_cpp_file(hdr) or hdr.endswith((".h", ".hh", ".hpp", ".hxx")):
                    parts.append(await blast_radius_report(cfg, hdr, 2))
                return md.enforce_budget(f"### 📦 CONTEXT PACK: type `{sym}`\n_{note}_\n\n" + "\n\n".join(parts), max_chars)
            return f"### 📦 CONTEXT PACK: `{target}`\n_{note}_\n❓ No function or type named `{sym}` in the code graph."
        fn = fns[0]
    lines = read_lines(cfg.workspace_root / fn.path)
    sig = f"{fn.return_type} {fn.qualified}{fn.signature}".strip()
    out = [f"### 📦 CONTEXT PACK: `{fn.qualified}`", f"_{note}_",
           f"- **Where:** `{fn.path}:{fn.line}-{fn.end}` ({md.plural(fn.end - fn.line + 1, 'line')})",
           f"- **Signature:** `{md.clip(sig, 160)}`"]
    # contract: doc comment above the declaration(s) and definition
    doc: list[str] = []
    for d in gq.functions_named(db, fn.qualified, definitions_first=False) + [fn]:
        try:
            dl = read_lines(cfg.workspace_root / d.path)
        except StaticSightError:
            continue
        doc = extract_leading_comment(dl, d.line - 1)
        if doc:
            break
    if doc:
        obl = _obligations(doc)
        out.append("\n**Contract**")
        out += [f"> {md.clip(x, 150)}" for x in doc[:8]]
        if obl:
            out.append("Obligations: " + " · ".join(md.clip(o, 120) for o in obl[:4]))
    # logic
    try:
        sk = await branch_skeleton_report(cfg, fn.path, start_line=fn.line)
        sk = "\n".join(sk.split("\n")[1:])
        out += ["\n**Logic** (branch skeleton)", md.enforce_budget(sk, max_chars // 3)]
    except StaticSightError:
        pass
    # callers and callees
    cache: dict = {}
    callers = gq.callers_of(db, fn, cache)
    out.append(f"\n**Callers** ({len(callers)})")
    out += md.truncate_list([f"- `{gq.caller_label(db, c)}` — `{c.path}:{c.line}` — {classify_call(c.code, c.callee) or c.how}"
                             for c in callers], 8, "callers", f"`get_impact(\"{fn.qualified}\")` shows all levels.") or ["- none in the repository"]
    inside, external = [], []
    for c in gq.calls_from(db, fn):
        if c.how == "ref":
            continue
        res = gq.resolve_call(db, c, cache)
        if res:
            inside += [f"`{f.qualified}` (`{f.loc}`)" for f in res]
        elif c.how in ("call", "qualified"):
            external.append(f"`{c.callee}`")
    inside, external = list(dict.fromkeys(inside)), list(dict.fromkeys(external))
    out.append("\n**Calls**")
    out.append("- In the repository: " + (", ".join(inside[:10]) or "none"))
    if external:
        out.append("- Outside (libraries, SDK, macros): " + ", ".join(external[:12]))
    # types from the signature
    types = []
    for ident in dict.fromkeys(re.findall(r"[A-Za-z_]\w*", f"{fn.return_type} {fn.signature}")):
        t = gq.types_named(db, ident) or list(db.execute(
            "SELECT name, path, line, kind, '' FROM defs WHERE name=? AND kind IN ('enum','typedef') ORDER BY path, line", (ident,)))
        if t:
            types.append(f"`{ident}` ({t[0][3]}, `{t[0][1]}:{t[0][2]}`)")
    if types:
        out.append("\n**Types in the signature:** " + ", ".join(types[:8]))
    # locks taken inside
    stripped = strip_code(lines)
    locks = sorted({mx for n in range(fn.line, min(fn.end, len(stripped)) + 1)
                    for e in line_events(stripped[n - 1]) if e.op == "acquire" for mx in e.mutexes})
    if locks:
        out.append("\n**Locks taken:** " + ", ".join(f"`{x}`" for x in locks)
                   + " — see `track_lock_order` / `track_state_mutations` before changing the locking.")
    # tests
    tests = []
    seen = {fn.key}
    frontier = [fn]
    for _ in range(3):
        nxt = []
        for tgt in frontier:
            for c in gq.callers_of(db, tgt, cache):
                if c.caller_key in seen:
                    continue
                seen.add(c.caller_key)
                f = gq.caller_fn(db, c)
                (tests if gq.is_test_path(f.path) else nxt).append(f)
        frontier = sorted(nxt, key=lambda f: f.key)
    out.append("\n**Tests reaching it:** " + (", ".join(f"`{test_label(t)}` (`{t.loc}`)" for t in sorted(tests, key=lambda f: f.key)[:6])
                                            or "none within 3 calls ⚠️"))
    # history
    hist = await _history(cfg, fn.path, fn.line, fn.end, 3)
    if hist:
        out.append("\n**Recent history:** " + "; ".join(f"`{h}` {d}{' 🐞' if _is_fix(s) else ''} {md.clip(s, 60)}" for h, d, s in hist))
    return md.enforce_budget("\n".join(out), max_chars)


async def get_context_pack(target: str, max_chars: int = 6000) -> str:
    """Everything an agent needs about one function in a single call, within a character budget: location and signature, the documented contract and obligations, the branch skeleton, callers (with result used/ignored), in-repository and external callees, types in the signature, locks it takes, tests that reach it, and its recent git history (fixes marked). `target` is a function name or file:line; a type name returns its hierarchy and header blast radius. Use before reading or editing unfamiliar code instead of opening several files."""
    return await context_pack_report(load_config(), target, max_chars)


# ------------------------------------------------------------------------------------------------ find_log_origin
_VARIABLE = re.compile(
    r"\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b|0x[0-9a-fA-F]+|\b\d+(?:[.:]\d+)*\b|'[^']*'|\"[^\"]*\"|"
    r"\{[^}]*\}|\[[^\]]*\]|[A-Za-z]:\\\S*|(?<!\w)/\S+")


def log_fragments(text: str) -> list[str]:
    """Literal pieces of a log line that should appear in the format string (variables removed)."""
    parts = [re.sub(r"^[\s:;,.=\-|>]+|[\s:;,.=\-|<]+$", "", p) for p in _VARIABLE.split(text)]
    frags = [p for p in parts if len(p) >= 6 and re.search(r"[A-Za-z]{3}", p)]
    frags = sorted(dict.fromkeys(frags), key=lambda p: (-len(p), p))
    return frags[:6]


def _in_string(orig: str, stripped: str, col: int, length: int) -> bool:
    return stripped[col:col + length].strip() == "" and orig[:col].count('"') % 2 == 1


async def log_origin_report(cfg: Config, text: str) -> str:
    text = (text or "").strip()
    if not text:
        raise InvalidArgument("`text` is empty: paste the log or error line.")
    frags = log_fragments(text)
    title = f"### 🔍 LOG ORIGIN: \"{md.clip(text, 100)}\""
    if not frags:
        raise InvalidArgument("No literal text to search for (the line looks like numbers and identifiers only).")
    g, note, usable = await graph_for(cfg)
    db = g.db if usable else None
    hits: dict[tuple[str, int], set[str]] = {}
    texts: dict[tuple[str, int], str] = {}
    for fr in frags:
        res = await rg_search(cfg, fr, fixed=True)
        for path in sorted(res.files):
            try:
                orig = read_lines(cfg.workspace_root / path)
            except StaticSightError:
                continue
            stripped = strip_code(orig)
            for m in res.files[path]:
                if not m.is_match or m.line > len(orig):
                    continue
                col = orig[m.line - 1].find(fr)
                if col < 0 or not _in_string(orig[m.line - 1], stripped[m.line - 1], col, len(fr)):
                    continue
                # group a statement split over a few lines under its first line
                key = next(((path, ln) for (p, ln) in hits if p == path and 0 <= m.line - ln <= 3), (path, m.line))
                hits.setdefault(key, set()).add(fr)
                texts.setdefault(key, orig[key[1] - 1].strip())
    out = [title, f"Searched {md.plural(len(frags), 'literal fragment')}: " + ", ".join(f"\"{f}\"" for f in frags) + "."]
    if not hits:
        out.append("❓ No string literal in the C/C++ sources contains these fragments. The message may be built at run "
                   "time, come from a resource file or another component, or be translated.")
        return "\n".join(out)
    ranked = sorted(hits.items(), key=lambda kv: (-sum(len(f) for f in kv[1]), kv[0]))[:3]
    cache: dict = {}
    threads = gq.thread_targets(db) if db is not None else set()
    for i, ((path, line), fr) in enumerate(ranked, 1):
        fn = gq.enclosing_function(db, path, line) if db is not None else None
        out.append(f"{i}. `{path}:{line}`" + (f" in `{fn.qualified}`" if fn else "") +
                   f" — matches {len(fr)} of {len(frags)} fragments")
        out.append(f"   `{md.clip(texts[(path, line)], 140)}`")
        if fn is not None and db is not None:
            callers = gq.callers_of(db, fn, cache)
            if callers:
                out.append("   - Called from: " + ", ".join(f"`{gq.caller_label(db, c)}` (`{c.path}:{c.line}`)" for c in callers[:5])
                           + (f" _…and {len(callers) - 5} more_" if len(callers) > 5 else ""))
            else:
                out.append("   - No callers found in the repository.")
            kind = gq.entry_kind(db, fn, threads)
            if kind:
                out.append(f"   - It is itself a {'test' if kind == 'test' else 'program or thread entry point'}.")
    if not usable:
        out.append(f"\n_{note}_")
    out.append("\n_Next: `find_entry_paths(\"<function>\")` for how requests reach it, `get_context_pack` for its logic._")
    return "\n".join(out)


async def find_log_origin(text: str) -> str:
    """Finds the code that produced a log or error message: paste the line from a log, crash report or incident, and it strips the variable parts (numbers, hex, GUIDs, quoted values, paths), searches the remaining literal text inside C/C++ string literals, and returns the best-matching format strings with their function and callers. Use to start an investigation from a symptom."""
    return await log_origin_report(load_config(), text)
