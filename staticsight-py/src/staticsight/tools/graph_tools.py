"""Graph tools: get_impact, get_call_paths, find_entry_paths, get_type_hierarchy, query_graph, get_lock_graph."""

from __future__ import annotations

import re

from ..config import Config, load_config
from ..core import md
from ..core.errors import InvalidArgument
from ..core.paths import matches_glob
from ..graph import query as gq
from ..graph.store import CodeGraph, get_graph
from .graph_gtags import callers_report, classify_call, normalize_symbol

HEURISTIC = ("_Heuristic: calls are matched by name and narrowed by class where the code says so (`C::f()`, calls inside "
             "`C`'s members); `obj.f()` may reach any `f`. Threads/callbacks are followed; other function pointers are not._")
HOW_LABEL = {"thread": "starts as a thread/callback", "ref": "takes the address of"}


async def graph_for(cfg: Config) -> tuple[CodeGraph, str, bool]:
    g = get_graph(cfg)
    note, usable = await g.ensure_fresh()
    return g, note, usable


def _check_symbol(symbol: str) -> str:
    s = (symbol or "").strip().rstrip("()").strip()
    if not s:
        raise InvalidArgument("`symbol` is empty.")
    normalize_symbol(s.rsplit("::", 1)[-1])  # validates the identifier
    return s


def _use(c: gq.Call) -> str:
    if c.how in HOW_LABEL:
        return HOW_LABEL[c.how]
    return classify_call(c.code, c.callee) or "call"


def _tag(kind: str) -> str:
    return {"program": " 🚪 program entry", "thread": " 🧵 thread/callback", "test": " 🧪 test"}.get(kind, "")


# ------------------------------------------------------------------------------------------------ get_impact
async def impact_report(cfg: Config, symbol: str, depth: int = 3, direction: str = "callers", path_glob: str = "") -> str:
    sym = _check_symbol(symbol)
    depth = max(1, min(int(depth or 3), 6))
    direction = (direction or "callers").strip().lower()
    if direction not in ("callers", "callees"):
        raise InvalidArgument("`direction` must be `callers` or `callees`.")
    g, note, usable = await graph_for(cfg)
    title = f"### 🌊 IMPACT: `{sym}` ({direction}, depth {depth})"
    if not usable:
        fallback = await callers_report(cfg, sym.rsplit("::", 1)[-1], path_glob) if direction == "callers" else ""
        return "\n".join([title, f"_{note}_", "Showing direct callers from GNU Global meanwhile:", "", fallback]).rstrip()
    db = g.db
    targets = gq.functions_named(db, sym)
    if not targets:
        return f"{title}\n_{note}_\n❓ No function named `{sym}` in the code graph. Check the spelling, or use `get_symbol_definition`."
    cache: dict = {}
    threads = gq.thread_targets(db)
    out = [title, f"_{note}_"]
    for t in targets[:3]:
        rt = f" · returns `{t.return_type}`" if t.return_type else ""
        out.append(f"**Target:** `{t.qualified}` — `{t.loc}`{rt}")
    if len(targets) > 3:
        out.append(f"_…and {len(targets) - 3} more definitions named `{sym}` (pass `Class::{sym.rsplit('::', 1)[-1]}` to narrow)._")
    virt_all = [o for t in targets for o in gq.overrides_of(db, t)]
    by_q: dict[str, gq.Fn] = {}
    for o in sorted(virt_all, key=lambda f: (f.kind != "function", f.key)):
        if o.qualified not in {t.qualified for t in targets}:
            by_q.setdefault(o.qualified, o)
    virt = [by_q[q] for q in sorted(by_q)]
    if virt:
        out.append("**Virtual:** calls through a base or derived type can also reach " +
                   ", ".join(f"`{o.qualified}` (`{o.loc}`)" for o in virt[:6]) + ".")
    if direction == "callees":
        return "\n".join(out + _callees(db, targets, depth, cache, cfg)) + "\n\n" + HEURISTIC
    seen = {t.key for t in targets} | {o.key for o in virt}
    frontier = sorted({t.key: t for t in targets + virt}.values(), key=lambda f: f.key)
    reached: list[tuple[int, gq.Fn, gq.Call]] = []
    for level in range(1, depth + 1):
        nxt: dict[tuple, tuple[gq.Fn, gq.Call]] = {}
        rows: list[tuple[gq.Call, gq.Fn]] = []
        sites: set[tuple] = set()
        for tgt in frontier:
            for c in gq.callers_of(db, tgt, cache):
                if path_glob and not matches_glob(c.path, path_glob):
                    continue
                site = (c.path, c.line, c.caller, c.callee)
                if (level == 1 or c.caller_key not in seen) and site not in sites:
                    sites.add(site)
                    rows.append((c, tgt))
                if c.caller_key not in seen and c.caller_key not in nxt:
                    nxt[c.caller_key] = (gq.caller_fn(db, c), c)
        if not rows:
            break
        rows.sort(key=lambda r: (r[0].path, r[0].line, r[0].caller, r[1].qualified))
        lines = []
        for c, tgt in rows:
            kind = gq.entry_kind(db, gq.caller_fn(db, c), threads)
            via = f" → `{tgt.name}`" if level > 1 else ""
            lines.append(f"  - `{gq.caller_label(db, c)}`{_tag(kind)}{via} — `{c.path}:{c.line}` — {_use(c)}")
        fns = {c.caller_key for c, _ in rows}
        out.append(f"- **Depth {level}:** {md.plural(len(rows), 'call site')} in {md.plural(len(fns), 'function')}")
        out += md.truncate_list(lines, cfg.max_results, f"call sites at depth {level}")
        for key in sorted(nxt):
            fn, c = nxt[key]
            seen.add(key)
            reached.append((level, fn, c))
        frontier = [nxt[k][0] for k in sorted(nxt)]
        if not frontier:
            break
    if not reached:
        out.append("✅ No callers found in the repository (unused, called through a function pointer or virtual call on an "
                   "interface, or from outside the repository).")
    else:
        mods: dict[str, int] = {}
        for _, fn, _ in reached:
            mods[gq.module_of(fn.path)] = mods.get(gq.module_of(fn.path), 0) + 1
        entries = sorted({fn.qualified for _, fn, _ in reached if gq.entry_kind(db, fn, threads) in ("program", "thread")})
        tests = sorted({gq.label(fn) for _, fn, _ in reached if gq.entry_kind(db, fn, threads) == "test"})
        files = {fn.path for _, fn, _ in reached}
        summary = (f"**Reach:** {md.plural(len(reached), 'function')} in {md.plural(len(files), 'file')}; modules: "
                   + ", ".join(f"`{m}` ({n})" for m, n in sorted(mods.items(), key=lambda kv: (-kv[1], kv[0]))))
        if entries:
            summary += "; entry points: " + ", ".join(f"`{e}`" for e in entries[:5])
        if tests:
            summary += "; tests: " + ", ".join(f"`{t}`" for t in tests[:5])
        out.append(summary + ".")
    return "\n".join(out) + "\n\n" + HEURISTIC


def _callees(db, targets: list[gq.Fn], depth: int, cache: dict, cfg: Config) -> list[str]:
    out: list[str] = []
    seen = {t.key for t in targets}
    frontier = list(targets)
    external: set[str] = set()
    for level in range(1, depth + 1):
        lines: list[str] = []
        nxt: dict[tuple, gq.Fn] = {}
        for fn in frontier:
            for c in gq.calls_from(db, fn):
                if c.how == "ref":
                    continue
                res = gq.resolve_call(db, c, cache)
                if not res:
                    if c.how in ("call", "qualified"):
                        external.add(c.callee)
                    continue
                for f in res:
                    via = f" ← `{fn.name}`" if level > 1 else ""
                    lines.append(f"  - `{f.qualified}` — `{f.loc}`{via} (called at `{c.path}:{c.line}`"
                                 + (", as a thread/callback" if c.how == "thread" else "") + ")")
                    if f.key not in seen:
                        seen.add(f.key)
                        nxt[f.key] = f
        if not lines:
            break
        lines = sorted(dict.fromkeys(lines))
        out.append(f"- **Depth {level}:** {md.plural(len(lines), 'call')}")
        out += md.truncate_list(lines, cfg.max_results, f"calls at depth {level}")
        frontier = [nxt[k] for k in sorted(nxt)]
    if external:
        ext = sorted(external)
        out.append("- **Outside the repository** (libraries, SDK, macros): " + ", ".join(f"`{e}`" for e in ext[:20])
                   + (f" _…and {len(ext) - 20} more_" if len(ext) > 20 else ""))
    if not out:
        out.append("✅ It calls nothing in the repository.")
    return out


async def get_impact(symbol: str, depth: int = 3, direction: str = "callers", path_glob: str = "") -> str:
    """Shows everything a change to a function can affect, several levels deep, in one call: its callers, their callers, and so on (or, with direction='callees', everything it calls). Each call site shows file:line, whether the result is used or ignored, and which callers are program entry points, threads/callbacks or tests; virtual methods include their overrides. Use instead of repeated get_upstream_callers when a function's signature, return values, error handling or side effects change and you need the full blast radius."""
    return await impact_report(load_config(), symbol, depth, direction, path_glob)


# ------------------------------------------------------------------------------------------------ get_call_paths
def _hop(c: gq.Call, callee: gq.Fn) -> str:
    what = f"starts `{callee.name}` as a thread/callback" if c.how == "thread" else f"calls `{callee.name}`"
    return f"   - `{c.path}:{c.line}` in `{c.caller}`: {what}: `{md.clip(c.text, 100)}`"


async def call_paths_report(cfg: Config, from_symbol: str, to_symbol: str, max_depth: int = 8) -> str:
    src, dst = _check_symbol(from_symbol), _check_symbol(to_symbol)
    max_depth = max(1, min(int(max_depth or 8), 12))
    g, note, usable = await graph_for(cfg)
    title = f"### 🧭 CALL PATHS: `{src}` → `{dst}`"
    if not usable:
        return f"{title}\n_{note}_"
    db = g.db
    starts = gq.functions_named(db, src)
    goals = {f.key for f in gq.functions_named(db, dst)}
    if not starts or not goals:
        missing = src if not starts else dst
        return f"{title}\n_{note}_\n❓ No function named `{missing}` in the code graph."
    cache: dict = {}
    parents: dict[tuple, list[tuple[tuple, gq.Call, gq.Fn]]] = {s.key: [] for s in starts}
    frontier = sorted(starts, key=lambda f: f.key)
    found_depth = None
    for level in range(1, max_depth + 1):
        nxt: dict[tuple, gq.Fn] = {}
        for fn in frontier:
            for c in gq.calls_from(db, fn):
                if c.how == "ref":
                    continue
                for f in gq.resolve_call(db, c, cache):
                    if f.key in parents and f.key not in nxt:
                        continue
                    parents.setdefault(f.key, []).append((fn.key, c, f))
                    nxt[f.key] = f
        if any(k in goals for k in nxt):
            found_depth = level
            break
        frontier = [nxt[k] for k in sorted(nxt)]
        if not frontier:
            break
    out = [title, f"_{note}_"]
    if found_depth is None:
        out.append(f"✅ No call path from `{src}` to `{dst}` within {max_depth} calls (it may go through a function pointer, "
                   "a virtual call on an interface, or code outside the repository).")
        return "\n".join(out) + "\n\n" + HEURISTIC

    def paths_to(key: tuple, limit: int) -> list[list[tuple[gq.Call, gq.Fn]]]:
        if not parents.get(key):
            return [[]]
        res = []
        for pkey, c, f in sorted(parents[key], key=lambda p: (p[1].path, p[1].line, p[0])):
            for p in paths_to(pkey, limit):
                res.append(p + [(c, f)])
                if len(res) >= limit:
                    return res
        return res

    paths: list[list[tuple[gq.Call, gq.Fn]]] = []
    for k in sorted(k for k in goals if k in parents):
        paths += paths_to(k, 3)
    paths = [p for p in paths if p][:3]
    out.append(f"{md.plural(len(paths), 'path')}, shortest {md.plural(found_depth, 'call')}:")
    for i, p in enumerate(paths, 1):
        chain = " → ".join([f"`{gq.caller_label(db, p[0][0])}`"] + [f"`{f.qualified}`" for _, f in p])
        out.append(f"{i}. {chain}")
        out += [_hop(c, f) for c, f in p]
    return "\n".join(out) + "\n\n" + HEURISTIC


async def get_call_paths(from_symbol: str, to_symbol: str, max_depth: int = 8) -> str:
    """Finds how one function reaches another: the shortest call chains from `from_symbol` to `to_symbol` (up to 3), with the file:line and source line of every hop, including threads and callbacks started on the way. Use to answer 'how does the RPC handler end up in this code?', 'is this path possible?', or to explain a stack trace."""
    return await call_paths_report(load_config(), from_symbol, to_symbol, max_depth)


# ------------------------------------------------------------------------------------------------ find_entry_paths
async def entry_paths_report(cfg: Config, symbol: str, max_depth: int = 10) -> str:
    sym = _check_symbol(symbol)
    max_depth = max(1, min(int(max_depth or 10), 15))
    g, note, usable = await graph_for(cfg)
    title = f"### 🚪 ENTRY PATHS: `{sym}`"
    if not usable:
        return f"{title}\n_{note}_"
    db = g.db
    targets = gq.functions_named(db, sym)
    if not targets:
        return f"{title}\n_{note}_\n❓ No function named `{sym}` in the code graph."
    cache: dict = {}
    threads = gq.thread_targets(db)
    # reverse BFS: child pointer = the call that leads towards the target
    nxt_hop: dict[tuple, tuple[gq.Call, gq.Fn] | None] = {t.key: None for t in targets}
    fn_of: dict[tuple, gq.Fn] = {t.key: t for t in targets}
    frontier = sorted(targets, key=lambda f: f.key)
    entries: list[tuple[int, str, gq.Fn]] = []
    for t in targets:
        k = gq.entry_kind(db, t, threads)
        if k:
            entries.append((0, k, t))
    for level in range(1, max_depth + 1):
        new: dict[tuple, gq.Fn] = {}
        for tgt in frontier:
            for c in gq.callers_of(db, tgt, cache):
                if c.caller_key in nxt_hop:
                    continue
                fn = gq.caller_fn(db, c)
                nxt_hop[c.caller_key] = (c, tgt)
                fn_of[c.caller_key] = fn
                new[c.caller_key] = fn
                kind = gq.entry_kind(db, fn, threads)
                if kind:
                    entries.append((level, kind, fn))
        frontier = [new[k] for k in sorted(new)]
        if not frontier:
            break
    out = [title, f"_{note}_"]
    prog = [e for e in entries if e[1] == "program"]
    thr = [e for e in entries if e[1] == "thread"]
    tst = [e for e in entries if e[1] == "test"]
    if not prog and not thr:
        out.append("⚠️ No program entry point, thread or callback reaches it within "
                   f"{max_depth} calls. It may be called through a function pointer, a virtual call on an interface, "
                   "from outside the repository, or not at all.")
    else:
        out.append(f"Reached from {md.plural(len(prog), 'program entry point')} and "
                   f"{len(thr)} thread/callback {'entry' if len(thr) == 1 else 'entries'}:")
        for i, (lvl, kind, fn) in enumerate(sorted(prog + thr, key=lambda e: (e[0], e[1], e[2].key))[:5], 1):
            chain, hops = [f"`{fn.qualified}`"], []
            key = fn.key
            while nxt_hop.get(key):
                c, tgt = nxt_hop[key]
                chain.append(f"`{tgt.qualified}`")
                hops.append(_hop(c, tgt))
                key = tgt.key
            label = "program entry" if kind == "program" else "thread/callback"
            out.append(f"{i}. {'🚪' if kind == 'program' else '🧵'} " + " → ".join(chain) + f" ({label}, {md.plural(lvl, 'call')})")
            out += hops
    if tst:
        out.append("🧪 Tests that reach it: " + ", ".join(f"`{gq.label(fn)}` (`{fn.loc}`)" for _, _, fn in
                                                     sorted(tst, key=lambda e: (e[0], e[2].key))[:8]))
    return "\n".join(out) + "\n\n" + HEURISTIC


async def find_entry_paths(symbol: str, max_depth: int = 10) -> str:
    """Answers 'can outside input reach this code, and how?': walks callers back from a function to program entry points (main, WinMain, DllMain, ServiceMain), thread start routines and registered callbacks, and shows the call chain from each entry with file:line; also lists the tests that reach it. Use when judging the exposure of a risky change (a memcpy, a parser, a new error path) or when code looks unreachable."""
    return await entry_paths_report(load_config(), symbol, max_depth)


# ------------------------------------------------------------------------------------------------ get_type_hierarchy
async def type_hierarchy_report(cfg: Config, type_name: str) -> str:
    name = _check_symbol(type_name).rsplit("::", 1)[-1]
    g, note, usable = await graph_for(cfg)
    title = f"### 🧬 TYPE HIERARCHY: `{name}`"
    if not usable:
        return f"{title}\n_{note}_"
    db = g.db
    defs = gq.types_named(db, name)
    if not defs:
        return f"{title}\n_{note}_\n❓ No class or struct named `{name}` in the code graph."
    loc = {}
    for n, p, ln, _, _ in db.execute("SELECT name, path, line, kind, inherits FROM defs WHERE kind IN ('class','struct','union') "
                                     "ORDER BY path, line"):
        loc.setdefault(n, f"{p}:{ln}")
    chain = [name]
    extra_bases: list[str] = []
    cur = name
    while len(chain) < 12:
        bs = gq.bases(db, cur)
        if not bs:
            break
        extra_bases += [b for b in bs[1:] if b not in extra_bases]
        if bs[0] in chain:
            break
        chain.insert(0, bs[0])
        cur = bs[0]
    tree: list[str] = []
    for i, c in enumerate(chain):
        pre = "" if i == 0 else "    " * (i - 1) + "└── "
        mark = "  ◀ this type" if c == name else ""
        tree.append(f"{pre}{c}{mark}  ({loc.get(c, 'outside the repository')})")

    def down(c: str, indent: int, seen: set[str]) -> None:
        for d in gq.derived(db, c):
            if d in seen or len(tree) > 60:
                continue
            seen.add(d)
            tree.append("    " * indent + f"└── {d}  ({loc.get(d, '?')})")
            down(d, indent + 1, seen)

    down(name, len(chain) - 1, {name})
    out = [title, f"_{note}_", "```text", *tree, "```"]
    if extra_bases:
        out.append("Also derives from: " + ", ".join(f"`{b}`" for b in extra_bases))
    fam = sorted(gq.family(db, name))
    methods: dict[str, list[tuple[int, str, str, str, int, str]]] = {}
    order = {c: i for i, c in enumerate(chain)}
    for q, n, p, ln, _, kind, scope, sk, _, _, props in db.execute(
            f"SELECT {gq._FN_COLS} FROM defs WHERE kind IN ('function','prototype') AND properties<>'' ORDER BY path, line"):
        cls = scope.rsplit("::", 1)[-1] if scope and sk in gq.TYPE_KINDS else ""
        if cls in fam and ("virtual" in props or "override" in props or "pure" in props):
            methods.setdefault(n, []).append((order.get(cls, 99), cls, props, p, ln, kind))
    if methods:
        out += ["", "**Virtual methods**", "| Method | Introduced in | Overridden in |", "|---|---|---|"]
        for m in sorted(methods):
            rows = sorted({(o, c, pr, p, ln) for o, c, pr, p, ln, _ in methods[m]}, key=lambda r: (r[0], r[1], r[3], r[4]))
            intro = next((r for r in rows if "override" not in r[2]), rows[0])
            pure = " (pure)" if "pure" in intro[2] else ""
            others = [r for r in rows if r is not intro and r[1] != intro[1]]
            ov = ", ".join(f"`{r[1]}` `{r[3]}:{r[4]}`" for r in others) or "—"
            out.append(f"| `{m}` | `{intro[1]}`{pure} `{intro[3]}:{intro[4]}` | {ov} |")
        out.append("\n_A signature change to a virtual method must be mirrored in every override; a call through a base "
                   "pointer or reference can reach any of them._")
    return "\n".join(out)


async def get_type_hierarchy(type_name: str) -> str:
    """Shows a class's place in the inheritance tree: its base classes, every class derived from it (recursively), and each virtual method with the class that introduces it and every override (file:line), from Universal Ctags without compiling. Use before changing a virtual method, a base class or an interface, and to find every implementation behind a call through a base pointer."""
    return await type_hierarchy_report(load_config(), type_name)


# ------------------------------------------------------------------------------------------------ query_graph
QUERY_HELP = ("`<relation>[*<depth>] of <name> [in <glob>]`, relations: callers, callees, bases, derived, overrides, members, "
              "includers, includes, definitions; or `entry-points [in <glob>]`. Examples: `callers*2 of process_packet`, "
              "`derived of Transport`, `includers*2 of packet.hpp in src/*`, `entry-points`.")
_QUERY = re.compile(r"^\s*(?:(entry-points)|([a-z]+)(?:\s*\*\s*(\d+))?\s+of\s+([\w:.~/\\-]+))(?:\s+in\s+(\S+))?\s*$", re.I)


def _base(path: str) -> str:
    return path.replace("\\", "/").rsplit("/", 1)[-1]


def _include_matches(target: str, name: str) -> bool:
    t = target.replace("\\", "/")
    n = name.replace("\\", "/")
    return t == n or t.endswith("/" + n) or n.endswith("/" + t) or t.rsplit("/", 1)[-1] == n


async def query_graph_report(cfg: Config, query: str) -> str:
    m = _QUERY.match(query or "")
    title = f"### 🔎 GRAPH QUERY: `{(query or '').strip()}`"
    if not m:
        raise InvalidArgument(f"Cannot parse the query. Grammar: {QUERY_HELP}")
    entry, rel, dep, name, glob = m.groups()
    rel = (rel or "").lower()
    depth = max(1, min(int(dep or 1), 6))
    if not entry and rel not in ("callers", "callees", "bases", "derived", "overrides", "members", "includers",
                                 "includes", "definitions"):
        raise InvalidArgument(f"Unknown relation `{rel}`. Grammar: {QUERY_HELP}")
    g, note, usable = await graph_for(cfg)
    if not usable:
        return f"{title}\n_{note}_"
    db = g.db
    cache: dict = {}
    items: list[tuple[int, str, str]] = []   # (depth, rendered, path used for `in <glob>`)
    if entry:
        threads = gq.thread_targets(db)
        for f in gq._fns(db.execute(f"SELECT {gq._FN_COLS} FROM defs WHERE kind='function' ORDER BY path, line, qualified")):
            k = gq.entry_kind(db, f, threads)
            if k in ("program", "thread") and (not glob or matches_glob(f.path, glob)):
                items.append((0, f"`{f.qualified}` — `{f.loc}` ({'program entry' if k == 'program' else 'thread/callback'})", f.path))
    elif rel in ("callers", "callees"):
        frontier = gq.functions_named(db, name)
        seen = {f.key for f in frontier}
        for d in range(1, depth + 1):
            nxt: dict[tuple, gq.Fn] = {}
            for fn in frontier:
                if rel == "callers":
                    for c in gq.callers_of(db, fn, cache):
                        if c.caller_key not in seen:
                            seen.add(c.caller_key)
                            f = gq.caller_fn(db, c)
                            nxt[f.key] = f
                            items.append((d, f"`{f.qualified}` — `{c.path}:{c.line}`", c.path))
                else:
                    for c in gq.calls_from(db, fn):
                        if c.how == "ref":
                            continue
                        for f in gq.resolve_call(db, c, cache):
                            if f.key not in seen:
                                seen.add(f.key)
                                nxt[f.key] = f
                                items.append((d, f"`{f.qualified}` — `{f.loc}`", f.path))
            frontier = [nxt[k] for k in sorted(nxt)]
    elif rel in ("bases", "derived"):
        frontier, seen = [name.rsplit("::", 1)[-1]], {name.rsplit("::", 1)[-1]}
        for d in range(1, depth + 1):
            nxt2: list[str] = []
            for c in frontier:
                for n in (gq.bases(db, c) if rel == "bases" else gq.derived(db, c)):
                    if n not in seen:
                        seen.add(n)
                        nxt2.append(n)
                        loc = gq.types_named(db, n)
                        items.append((d, f"`{n}`" + (f" — `{loc[0][1]}:{loc[0][2]}`" if loc else " (outside the repository)"),
                                      loc[0][1] if loc else ""))
            frontier = nxt2
    elif rel == "overrides":
        for fn in gq.functions_named(db, name, definitions_first=False):
            for o in gq.overrides_of(db, fn):
                items.append((1, f"`{o.qualified}` — `{o.loc}` ({o.kind})", o.path))
        items = sorted(set(items))
    elif rel == "members":
        cls = name.rsplit("::", 1)[-1]
        for q, k, p, ln in db.execute("SELECT qualified, kind, path, line FROM defs WHERE scope=? OR scope LIKE ? "
                                      "ORDER BY path, line, qualified", (cls, f"%::{cls}")):
            items.append((1, f"`{q}` ({k}) — `{p}:{ln}`", p))
    elif rel == "definitions":
        cls, short = gq.split_symbol(name)
        for q, k, p, ln in db.execute("SELECT qualified, kind, path, line FROM defs WHERE name=? ORDER BY path, line, kind",
                                      (short,)):
            if not cls or q.endswith(f"{cls}::{short}"):
                items.append((1, f"`{q}` ({k}) — `{p}:{ln}`", p))
    elif rel in ("includers", "includes"):
        frontier, seen = [name], {name}
        # one scan, indexed by basename: every match of _include_matches shares the basename
        by_target: dict[str, list[tuple[str, int, str]]] = {}
        by_path: dict[str, list[tuple[str, int, str]]] = {}
        for row in db.execute("SELECT path, line, target FROM includes ORDER BY path, line"):
            by_target.setdefault(_base(row[2]), []).append(row)
            by_path.setdefault(_base(row[0]), []).append(row)
        for d in range(1, depth + 1):
            nxt3: list[str] = []
            for x in frontier:
                if rel == "includers":
                    rows = [r for r in by_target.get(_base(x), []) if _include_matches(r[2], x)]
                    for p, ln, _ in rows:
                        if p not in seen:
                            seen.add(p)
                            nxt3.append(p)
                            items.append((d, f"`{p}:{ln}`", p))
                else:
                    for p, ln, t in by_path.get(_base(x), []):
                        if (p == x or p.endswith("/" + x)) and t not in seen:
                            seen.add(t)
                            nxt3.append(t)
                            items.append((d, f"`{t}` (from `{p}:{ln}`)", t))
            frontier = nxt3
    if glob:
        items = [it for it in items if it[2] and matches_glob(it[2], glob)]
    out = [title, f"_{note}_", f"{md.plural(len(items), 'result')}:"]
    lines = [f"- {txt}" + (f" · depth {d}" if depth > 1 else "") for d, txt, _ in items]
    out += md.truncate_list(lines, cfg.max_results * 2, "results", "Narrow with `in <glob>` or a smaller depth.")
    return "\n".join(out)


async def query_graph(query: str) -> str:
    """Answers free-form structural questions over the code graph with a small query language: `callers*2 of process_packet`, `callees of Router::process_packet`, `derived of Transport`, `bases*3 of TlsTransport`, `overrides of send_frame`, `members of Router`, `includers*2 of packet.hpp in src/*`, `definitions of Packet`, `entry-points`. Use when the dedicated tools do not fit the question; depth up to 6."""
    return await query_graph_report(load_config(), query)


# ------------------------------------------------------------------------------------------------ get_lock_graph
async def lock_graph_report(cfg: Config, path_glob: str = "", symbol: str = "") -> str:
    from .lock_order import _involves, analyse

    symbol = (symbol or "").strip()
    fns, edges, _, _ = await analyse(cfg, path_glob)
    scope = f"`{symbol}`" if symbol else (f"`{path_glob}`" if path_glob else "repository")
    title = f"### 🔐 LOCK GRAPH: {scope}"
    taken: dict[str, list[str]] = {}
    for f in fns:
        for k in f.acquired:
            taken.setdefault(k, []).append(f.qualified)
    pairs: dict[tuple[str, str], list] = {}
    for e in edges:
        pairs.setdefault((e.first, e.second), []).append(e)
    if symbol:
        pairs = {k: v for k, v in pairs.items() if _involves(k[0], symbol) or _involves(k[1], symbol)}
        keys = sorted({k for p in pairs for k in p} | {k for k in taken if _involves(k, symbol)})
    else:
        keys = sorted(taken)
    if not keys:
        return f"{title}\n✅ No lock acquisitions found."
    shown = sorted({k for p in pairs for k in p}) or keys
    shown = shown[:20]
    ids = {k: f"L{i + 1}" for i, k in enumerate(shown)}
    out = [title, f"{md.plural(len(keys), 'lock')} taken by {md.plural(len({q for k in keys for q in taken.get(k, [])}), 'function')}; "
                  f"{md.plural(len(pairs), 'order edge')} (A → B: B is taken while A is held)."]
    if pairs:
        out += ["", "```mermaid", "graph LR"]
        out += [f'  {ids[k]}["{k}"]' for k in shown]
        for (a, b), ev in sorted(pairs.items()):
            if a in ids and b in ids:
                e0 = sorted(ev, key=lambda e: (e.path, e.line_second, e.via))[0]
                label = e0.fn.rsplit("::", 1)[-1] + (f" via {e0.via.rsplit('::', 1)[-1]}" if e0.via else "")
                out.append(f'  {ids[a]} -->|"{label}"| {ids[b]}')
        out.append("```")
    out += ["", "| Lock | Taken in | Then takes |", "|---|---|---|"]
    rows = []
    for k in keys:
        users = sorted(set(taken.get(k, [])))
        then = sorted({b for (a, b) in pairs if a == k})
        rows.append(f"| `{k}` | {', '.join(f'`{u}`' for u in users[:4])}{' …' if len(users) > 4 else ''} | "
                    f"{', '.join(f'`{t}`' for t in then) or '—'} |")
    out += md.truncate_list(rows, cfg.max_results, "locks")
    out.append("\n_Use `track_lock_order` for cycles, locks taken twice and locks held across blocking calls._")
    return "\n".join(out)


async def get_lock_graph(path_glob: str = "", symbol: str = "") -> str:
    """Maps the locks of a subsystem: every lock, the functions that take it, and which lock is taken while another is held, drawn as a small Mermaid diagram plus a table. Use to understand a module's locking design before adding or reordering locks; use track_lock_order to find problems (cycles, locks held across blocking calls)."""
    return await lock_graph_report(load_config(), path_glob, symbol)
