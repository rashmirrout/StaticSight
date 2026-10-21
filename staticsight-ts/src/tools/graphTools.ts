import { loadConfig, type Config } from "../config.js";
import * as md from "../core/md.js";
import { InvalidArgument } from "../core/errors.js";
import { matchesGlob } from "../core/paths.js";
import * as gq from "../graph/query.js";
import { getGraph, type CodeGraph } from "../graph/store.js";
import { callersReport, classifyCall, normalizeSymbol } from "./graphGtags.js";

const HEURISTIC = "_Heuristic: calls are matched by name and narrowed by class where the code says so (`C::f()`, calls inside `C`'s members); `obj.f()` may reach any `f`. Threads/callbacks are followed; other function pointers are not._";
const HOW_LABEL: Record<string, string> = { thread: "starts as a thread/callback", ref: "takes the address of" };

export async function graphFor(cfg: Config): Promise<[CodeGraph, string, boolean]> {
  const g = getGraph(cfg);
  const [note, usable] = await g.ensureFresh();
  return [g, note, usable];
}

export function checkSymbol(symbol: string): string {
  const s = (symbol ?? "").trim().replace(/\(\)$/, "").trim();
  if (!s) throw new InvalidArgument("`symbol` is empty.");
  normalizeSymbol(s.split("::").pop() ?? s);
  return s;
}

function use(c: gq.Call): string { return (HOW_LABEL[c.how] ?? classifyCall(c.code, c.callee)) || "call"; }
function tag(kind: string): string { return ({ program: " 🚪 program entry", thread: " 🧵 thread/callback", test: " 🧪 test" } as Record<string, string>)[kind] ?? ""; }

function callees(db: any, targets: gq.Fn[], depth: number, cache: Map<string, any>, cfg: Config): string[] {
  const out: string[] = [];
  const seen = new Set(targets.map((t) => t.key));
  let frontier = [...targets];
  const external = new Set<string>();
  for (let level = 1; level <= depth; level++) {
    const lines: string[] = [];
    const nxt = new Map<string, gq.Fn>();
    for (const fn of frontier) {
      for (const c of gq.callsFrom(db, fn)) {
        if (c.how === "ref") continue;
        const res = gq.resolveCall(db, c, cache);
        if (!res.length) {
          if (c.how === "call" || c.how === "qualified") external.add(c.callee);
          continue;
        }
        for (const f of res) {
          const via = level > 1 ? " ← `" + fn.name + "`" : "";
          lines.push("- `" + f.qualified + "` — `" + f.loc + "`" + via + " (called at `" + c.path + ":" + c.line + "`" + (c.how === "thread" ? ", as a thread/callback" : "") + ")");
          if (!seen.has(f.key)) { seen.add(f.key); nxt.set(f.key, f); }
        }
      }
    }
    if (!lines.length) break;
    const uniq = [...new Set(lines)].sort();
    out.push("- **Depth " + level + ":** " + md.plural(uniq.length, "call"));
    out.push(...md.truncateList(uniq.map((x) => "  " + x), cfg.maxResults, "calls at depth " + level));
    frontier = [...nxt.keys()].sort().map((k) => nxt.get(k)!);
  }
  if (external.size) {
    const ext = [...external].sort();
    out.push("- **Outside the repository** (libraries, SDK, macros): " + ext.slice(0, 20).map((e) => "`" + e + "`").join(", ") + (ext.length > 20 ? " _…and " + (ext.length - 20) + " more_" : ""));
  }
  if (!out.length) out.push("✅ It calls nothing in the repository.");
  return out;
}

export async function impactReport(cfg: Config, symbol: string, depth = 3, direction = "callers", pathGlob = ""): Promise<string> {
  const sym = checkSymbol(symbol);
  depth = Math.max(1, Math.min(Number(depth || 3), 6));
  direction = (direction || "callers").trim().toLowerCase();
  if (!["callers", "callees"].includes(direction)) throw new InvalidArgument("`direction` must be `callers` or `callees`.");
  const [g, note, usable] = await graphFor(cfg);
  const title = "### 🌊 IMPACT: `" + sym + "` (" + direction + ", depth " + depth + ")";
  if (!usable) {
    const fallback = direction === "callers" ? await callersReport(cfg, sym.split("::").pop() ?? sym, pathGlob) : "";
    return [title, "_" + note + "_", "Showing direct callers from GNU Global meanwhile:", "", fallback].join("\n").trimEnd();
  }
  const db = g.db;
  const targets = gq.functionsNamed(db, sym);
  if (!targets.length) return title + "\n_" + note + "_\n❓ No function named `" + sym + "` in the code graph. Check the spelling, or use `get_symbol_definition`.";
  const cache = new Map<string, any>();
  const out = [title, "_" + note + "_"];
  for (const t of targets.slice(0, 3)) out.push("**Target:** `" + t.qualified + "` — `" + t.loc + "`" + (t.returnType ? " · returns `" + t.returnType + "`" : ""));
  if (targets.length > 3) out.push("_…and " + (targets.length - 3) + " more definitions named `" + sym + "` (pass `Class::" + (sym.split("::").pop() ?? sym) + "` to narrow)._");
  const virtMap = new Map<string, gq.Fn>();
  const virtAll = targets.flatMap((t) => gq.overridesOf(db, t)).sort((a, b) => Number(a.kind !== "function") - Number(b.kind !== "function") || gq.cmp(a.key, b.key));
  for (const o of virtAll) if (!targets.some((x) => x.qualified === o.qualified) && !virtMap.has(o.qualified)) virtMap.set(o.qualified, o);
  const virt = [...virtMap.keys()].sort().map((k) => virtMap.get(k)!);
  if (virt.length) out.push("**Virtual:** calls through a base or derived type can also reach " + virt.slice(0, 6).map((o) => "`" + o.qualified + "` (`" + o.loc + "`)").join(", ") + ".");
  if (direction === "callees") return out.concat(callees(db, targets, depth, cache, cfg)).join("\n") + "\n\n" + HEURISTIC;
  const seen = new Set([...targets.map((t) => t.key), ...virt.map((o) => o.key)]);
  let frontier = [...new Map([...targets, ...virt].map((t) => [t.key, t])).values()].sort((a, b) => gq.cmp(a.key, b.key));
  const reached: Array<[number, gq.Fn, gq.Call]> = [];
  const threads = gq.threadTargets(db);
  for (let level = 1; level <= depth; level++) {
    const nxt = new Map<string, [gq.Fn, gq.Call]>();
    const rows: Array<[gq.Call, gq.Fn]> = [];
    const sites = new Set<string>();
    for (const tgt of frontier) {
      for (const c of gq.callersOf(db, tgt, cache)) {
        if (pathGlob && !matchesGlob(c.path, pathGlob)) continue;
        const site = c.path + "\0" + c.line + "\0" + c.caller + "\0" + c.callee;
        if ((level === 1 || !seen.has(c.callerKey)) && !sites.has(site)) { sites.add(site); rows.push([c, tgt]); }
        if (!seen.has(c.callerKey) && !nxt.has(c.callerKey)) nxt.set(c.callerKey, [gq.callerFn(db, c), c]);
      }
    }
    if (!rows.length) break;
    rows.sort((a, b) => gq.cmp(a[0].path, b[0].path) || a[0].line - b[0].line || gq.cmp(a[0].caller, b[0].caller) || gq.cmp(a[1].qualified, b[1].qualified));
    const lines = rows.map(([c, tgt]) => "  - `" + gq.callerLabel(db, c) + "`" + tag(gq.entryKind(db, gq.callerFn(db, c), threads)) + (level > 1 ? " → `" + tgt.name + "`" : "") + " — `" + c.path + ":" + c.line + "` — " + use(c));
    out.push("- **Depth " + level + ":** " + md.plural(rows.length, "call site") + " in " + md.plural(new Set(rows.map(([c]) => c.callerKey)).size, "function"));
    out.push(...md.truncateList(lines, cfg.maxResults, "call sites at depth " + level));
    for (const key of [...nxt.keys()].sort()) { const [fn, c] = nxt.get(key)!; seen.add(key); reached.push([level, fn, c]); }
    frontier = [...nxt.keys()].sort().map((k) => nxt.get(k)![0]);
    if (!frontier.length) break;
  }
  if (!reached.length) out.push("✅ No callers found in the repository (unused, called through a function pointer or virtual call on an interface, or from outside the repository).");
  else {
    const mods = new Map<string, number>();
    for (const [, fn] of reached) mods.set(gq.moduleOf(fn.path), (mods.get(gq.moduleOf(fn.path)) ?? 0) + 1);
    const entries = [...new Set(reached.filter(([, fn]) => ["program", "thread"].includes(gq.entryKind(db, fn, threads))).map(([, fn]) => fn.qualified))].sort();
    const tests = [...new Set(reached.filter(([, fn]) => gq.entryKind(db, fn, threads) === "test").map(([, fn]) => gq.label(fn)))].sort();
    const files = new Set(reached.map(([, fn]) => fn.path));
    let summary = "**Reach:** " + md.plural(reached.length, "function") + " in " + md.plural(files.size, "file") + "; modules: " + [...mods.entries()].sort((a, b) => b[1] - a[1] || gq.cmp(a[0], b[0])).map(([m, n]) => "`" + m + "` (" + n + ")").join(", ");
    if (entries.length) summary += "; entry points: " + entries.slice(0, 5).map((e) => "`" + e + "`").join(", ");
    if (tests.length) summary += "; tests: " + tests.slice(0, 5).map((t) => "`" + t + "`").join(", ");
    out.push(summary + ".");
  }
  return out.join("\n") + "\n\n" + HEURISTIC;
}

export async function get_impact(args: { symbol: string; depth?: number; direction?: string; path_glob?: string }): Promise<string> {
  return impactReport(loadConfig(), args.symbol, args.depth ?? 3, args.direction ?? "callers", args.path_glob ?? "");
}

function hop(c: gq.Call, callee: gq.Fn): string {
  const what = c.how === "thread" ? "starts `" + callee.name + "` as a thread/callback" : "calls `" + callee.name + "`";
  return "   - `" + c.path + ":" + c.line + "` in `" + c.caller + "`: " + what + ": `" + md.clip(c.text, 100) + "`";
}

export async function get_call_paths(args: { from_symbol: string; to_symbol: string; max_depth?: number }): Promise<string> {
  const cfg = loadConfig(), src = checkSymbol(args.from_symbol), dst = checkSymbol(args.to_symbol), maxDepth = Math.max(1, Math.min(Number(args.max_depth ?? 8), 12));
  const [g, note, usable] = await graphFor(cfg);
  const title = "### 🧭 CALL PATHS: `" + src + "` → `" + dst + "`";
  if (!usable) return title + "\n_" + note + "_";
  const db = g.db, starts = gq.functionsNamed(db, src), goals = new Set(gq.functionsNamed(db, dst).map((f) => f.key));
  if (!starts.length || !goals.size) return title + "\n_" + note + "_\n❓ No function named `" + (!starts.length ? src : dst) + "` in the code graph.";
  const cache = new Map<string, any>(), parents = new Map<string, Array<[string, gq.Call, gq.Fn]>>();
  for (const s of starts) parents.set(s.key, []);
  let frontier = starts.sort((a, b) => gq.cmp(a.key, b.key)), foundDepth: number | null = null;
  for (let level = 1; level <= maxDepth; level++) {
    const nxt = new Map<string, gq.Fn>();
    for (const fn of frontier) for (const c of gq.callsFrom(db, fn)) if (c.how !== "ref") for (const f of gq.resolveCall(db, c, cache)) {
      if (parents.has(f.key) && !nxt.has(f.key)) continue;
      if (!parents.has(f.key)) parents.set(f.key, []);
      parents.get(f.key)!.push([fn.key, c, f]); nxt.set(f.key, f);
    }
    if ([...nxt.keys()].some((k) => goals.has(k))) { foundDepth = level; break; }
    frontier = [...nxt.keys()].sort().map((k) => nxt.get(k)!);
    if (!frontier.length) break;
  }
  const out = [title, "_" + note + "_"];
  if (foundDepth === null) return out.concat("✅ No call path from `" + src + "` to `" + dst + "` within " + maxDepth + " calls (it may go through a function pointer, a virtual call on an interface, or code outside the repository).").join("\n") + "\n\n" + HEURISTIC;
  const pathsTo = (key: string, limit: number): Array<Array<[gq.Call, gq.Fn]>> => {
    const ps = parents.get(key) ?? [];
    if (!ps.length) return [[]];
    const res: Array<Array<[gq.Call, gq.Fn]>> = [];
    for (const [pkey, c, f] of ps.sort((a, b) => a[1].path < b[1].path ? -1 : a[1].path > b[1].path ? 1 : a[1].line - b[1].line)) {
      for (const p of pathsTo(pkey, limit)) { res.push([...p, [c, f]]); if (res.length >= limit) return res; }
    }
    return res;
  };
  let paths: Array<Array<[gq.Call, gq.Fn]>> = [];
  for (const k of [...goals].filter((k) => parents.has(k)).sort()) paths = paths.concat(pathsTo(k, 3));
  paths = paths.filter((p) => p.length).slice(0, 3);
  out.push(md.plural(paths.length, "path") + ", shortest " + md.plural(foundDepth, "call") + ":");
  paths.forEach((p, i) => { out.push((i + 1) + ". " + ["`" + gq.callerLabel(db, p[0][0]) + "`", ...p.map(([, f]) => "`" + f.qualified + "`")].join(" → ")); out.push(...p.map(([c, f]) => hop(c, f))); });
  return out.join("\n") + "\n\n" + HEURISTIC;
}

export async function find_entry_paths(args: { symbol: string; max_depth?: number }): Promise<string> {
  const cfg = loadConfig(), sym = checkSymbol(args.symbol), maxDepth = Math.max(1, Math.min(Number(args.max_depth ?? 10), 15));
  const [g, note, usable] = await graphFor(cfg);
  const title = "### 🚪 ENTRY PATHS: `" + sym + "`";
  if (!usable) return title + "\n_" + note + "_";
  const db = g.db, targets = gq.functionsNamed(db, sym);
  if (!targets.length) return title + "\n_" + note + "_\n❓ No function named `" + sym + "` in the code graph.";
  const cache = new Map<string, any>(), threads = gq.threadTargets(db), nxtHop = new Map<string, [gq.Call, gq.Fn] | null>(), fnOf = new Map<string, gq.Fn>(), entries: Array<[number, string, gq.Fn]> = [];
  for (const t of targets) { nxtHop.set(t.key, null); fnOf.set(t.key, t); const k = gq.entryKind(db, t, threads); if (k) entries.push([0, k, t]); }
  let frontier = targets.sort((a, b) => gq.cmp(a.key, b.key));
  for (let level = 1; level <= maxDepth; level++) {
    const news = new Map<string, gq.Fn>();
    for (const tgt of frontier) for (const c of gq.callersOf(db, tgt, cache)) if (!nxtHop.has(c.callerKey)) {
      const fn = gq.callerFn(db, c); nxtHop.set(c.callerKey, [c, tgt]); fnOf.set(c.callerKey, fn); news.set(c.callerKey, fn);
      const kind = gq.entryKind(db, fn, threads); if (kind) entries.push([level, kind, fn]);
    }
    frontier = [...news.keys()].sort().map((k) => news.get(k)!); if (!frontier.length) break;
  }
  const out = [title, "_" + note + "_"], prog = entries.filter((e) => e[1] === "program"), thr = entries.filter((e) => e[1] === "thread"), tst = entries.filter((e) => e[1] === "test");
  if (!prog.length && !thr.length) out.push("⚠️ No program entry point, thread or callback reaches it within " + maxDepth + " calls. It may be called through a function pointer, a virtual call on an interface, from outside the repository, or not at all.");
  else {
    out.push("Reached from " + md.plural(prog.length, "program entry point") + " and " + thr.length + " thread/callback " + (thr.length === 1 ? "entry" : "entries") + ":");
    [...prog, ...thr].sort((a, b) => a[0] - b[0] || gq.cmp(a[1], b[1]) || gq.cmp(a[2].key, b[2].key)).slice(0, 5).forEach(([lvl, kind, fn], i) => {
      const chain = ["`" + fn.qualified + "`"], hops: string[] = []; let key = fn.key;
      while (nxtHop.get(key)) { const [c, tgt] = nxtHop.get(key)!; chain.push("`" + tgt.qualified + "`"); hops.push(hop(c, tgt)); key = tgt.key; }
      out.push((i + 1) + ". " + (kind === "program" ? "🚪 " : "🧵 ") + chain.join(" → ") + " (" + (kind === "program" ? "program entry" : "thread/callback") + ", " + md.plural(lvl, "call") + ")");
      out.push(...hops);
    });
  }
  if (tst.length) out.push("🧪 Tests that reach it: " + tst.sort((a, b) => a[0] - b[0] || gq.cmp(a[2].key, b[2].key)).slice(0, 8).map(([, , fn]) => "`" + gq.label(fn) + "` (`" + fn.loc + "`)").join(", "));
  return out.join("\n") + "\n\n" + HEURISTIC;
}

export async function get_type_hierarchy(args: { type_name: string }): Promise<string> {
  const cfg = loadConfig(), name = checkSymbol(args.type_name).split("::").pop()!;
  const [g, note, usable] = await graphFor(cfg);
  const title = "### 🧬 TYPE HIERARCHY: `" + name + "`";
  if (!usable) return title + "\n_" + note + "_";
  const db = g.db, defs = gq.typesNamed(db, name);
  if (!defs.length) return title + "\n_" + note + "_\n❓ No class or struct named `" + name + "` in the code graph.";
  const loc = new Map<string, string>();
  for (const r of db.prepare("SELECT name, path, line, kind, inherits FROM defs WHERE kind IN ('class','struct','union') ORDER BY path, line").all() as any[]) if (!loc.has(r.name)) loc.set(r.name, r.path + ":" + r.line);
  const chain = [name], extraBases: string[] = []; let cur = name;
  while (chain.length < 12) { const bs = gq.bases(db, cur); if (!bs.length) break; extraBases.push(...bs.slice(1).filter((b) => !extraBases.includes(b))); if (chain.includes(bs[0])) break; chain.unshift(bs[0]); cur = bs[0]; }
  const tree = chain.map((c, i) => (i === 0 ? "" : "    ".repeat(i - 1) + "└── ") + c + (c === name ? "  ◀ this type" : "") + "  (" + (loc.get(c) ?? "outside the repository") + ")");
  const down = (c: string, indent: number, seen: Set<string>): void => { for (const d of gq.derived(db, c)) if (!seen.has(d) && tree.length <= 60) { seen.add(d); tree.push("    ".repeat(indent) + "└── " + d + "  (" + (loc.get(d) ?? "?") + ")"); down(d, indent + 1, seen); } };
  down(name, chain.length - 1, new Set([name]));
  const out = [title, "_" + note + "_", "```text", ...tree, "```"];
  if (extraBases.length) out.push("Also derives from: " + extraBases.map((b) => "`" + b + "`").join(", "));
  const fam = gq.family(db, name), order = new Map(chain.map((c, i) => [c, i])), methods = new Map<string, Array<[number, string, string, string, number]>>();
  for (const r of db.prepare("SELECT " + gq.FN_COLS + " FROM defs WHERE kind IN ('function','prototype') AND properties<>'' ORDER BY path, line").all() as any[]) {
    const cls = r.scope && (gq.TYPE_KINDS as readonly string[]).includes(r.scope_kind) ? String(r.scope).split("::").pop()! : "";
    if (fam.has(cls) && (r.properties.includes("virtual") || r.properties.includes("override") || r.properties.includes("pure"))) {
      const arr = methods.get(r.name) ?? []; arr.push([order.get(cls) ?? 99, cls, r.properties, r.path, Number(r.line)]); methods.set(r.name, arr);
    }
  }
  if (methods.size) {
    out.push("", "**Virtual methods**", "| Method | Introduced in | Overridden in |", "|---|---|---|");
    for (const m of [...methods.keys()].sort()) {
      const rows = [...new Map(methods.get(m)!.map((r) => [r.join("\0"), r])).values()].sort((a, b) => a[0] - b[0] || gq.cmp(a[1], b[1]) || gq.cmp(a[3], b[3]) || a[4] - b[4]);
      const intro = rows.find((r) => !r[2].includes("override")) ?? rows[0], pure = intro[2].includes("pure") ? " (pure)" : "";
      const others = rows.filter((r) => r !== intro && r[1] !== intro[1]);
      out.push("| `" + m + "` | `" + intro[1] + "`" + pure + " `" + intro[3] + ":" + intro[4] + "` | " + (others.map((r) => "`" + r[1] + "` `" + r[3] + ":" + r[4] + "`").join(", ") || "—") + " |");
    }
    out.push("\n_A signature change to a virtual method must be mirrored in every override; a call through a base pointer or reference can reach any of them._");
  }
  return out.join("\n");
}

const QUERY_HELP = "`<relation>[*<depth>] of <name> [in <glob>]`, relations: callers, callees, bases, derived, overrides, members, includers, includes, definitions; or `entry-points [in <glob>]`. Examples: `callers*2 of process_packet`, `derived of Transport`, `includers*2 of packet.hpp in src/*`, `entry-points`.";
const QUERY = /^\s*(?:(entry-points)|([a-z]+)(?:\s*\*\s*(\d+))?\s+of\s+([\w:.~/\\-]+))(?:\s+in\s+(\S+))?\s*$/i;
const base = (p: string): string => p.replace(/\\/g, "/").split("/").pop() ?? p;
const includeMatches = (target: string, name: string): boolean => { const t = target.replace(/\\/g, "/"), n = name.replace(/\\/g, "/"); return t === n || t.endsWith("/" + n) || n.endsWith("/" + t) || base(t) === n; };

export async function query_graph(args: { query: string }): Promise<string> {
  const cfg = loadConfig(), query = args.query ?? "", m = QUERY.exec(query);
  const title = "### 🔎 GRAPH QUERY: `" + query.trim() + "`";
  if (!m) throw new InvalidArgument("Cannot parse the query. Grammar: " + QUERY_HELP);
  const [, entry, relRaw, dep, nameRaw, glob] = m, rel = (relRaw ?? "").toLowerCase(), depth = Math.max(1, Math.min(Number(dep ?? 1), 6)), name = nameRaw ?? "";
  if (!entry && !["callers", "callees", "bases", "derived", "overrides", "members", "includers", "includes", "definitions"].includes(rel)) throw new InvalidArgument("Unknown relation `" + rel + "`. Grammar: " + QUERY_HELP);
  const [g, note, usable] = await graphFor(cfg); if (!usable) return title + "\n_" + note + "_";
  const db = g.db, cache = new Map<string, any>(), items: Array<[number, string, string]> = [];
  if (entry) {
    const threads = gq.threadTargets(db);
    for (const r of db.prepare("SELECT " + gq.FN_COLS + " FROM defs WHERE kind='function' ORDER BY path, line, qualified").all() as any[]) {
      const f = new gq.Fn(r.qualified, r.name, r.path, Number(r.line), Number(r.end_line), r.kind, r.scope, r.scope_kind, r.signature, r.typeref, r.properties), k = gq.entryKind(db, f, threads);
      if (["program", "thread"].includes(k) && (!glob || matchesGlob(f.path, glob))) items.push([0, "`" + f.qualified + "` — `" + f.loc + "` (" + (k === "program" ? "program entry" : "thread/callback") + ")", f.path]);
    }
  } else if (rel === "callers" || rel === "callees") {
    let frontier = gq.functionsNamed(db, name); const seen = new Set(frontier.map((f) => f.key));
    for (let d = 1; d <= depth; d++) { const nxt = new Map<string, gq.Fn>(); for (const fn of frontier) {
      if (rel === "callers") for (const c of gq.callersOf(db, fn, cache)) if (!seen.has(c.callerKey)) { seen.add(c.callerKey); const f = gq.callerFn(db, c); nxt.set(f.key, f); items.push([d, "`" + f.qualified + "` — `" + c.path + ":" + c.line + "`", c.path]); }
      else for (const c of gq.callsFrom(db, fn)) if (c.how !== "ref") for (const f of gq.resolveCall(db, c, cache)) if (!seen.has(f.key)) { seen.add(f.key); nxt.set(f.key, f); items.push([d, "`" + f.qualified + "` — `" + f.loc + "`", f.path]); }
    } frontier = [...nxt.keys()].sort().map((k) => nxt.get(k)!); }
  } else if (rel === "bases" || rel === "derived") {
    let frontier = [name.split("::").pop()!]; const seen = new Set(frontier);
    for (let d = 1; d <= depth; d++) { const nxt: string[] = []; for (const c of frontier) for (const n of (rel === "bases" ? gq.bases(db, c) : gq.derived(db, c))) if (!seen.has(n)) { seen.add(n); nxt.push(n); const loc = gq.typesNamed(db, n); items.push([d, "`" + n + "`" + (loc.length ? " — `" + loc[0][1] + ":" + loc[0][2] + "`" : " (outside the repository)"), loc.length ? loc[0][1] : ""]); } frontier = nxt; }
  } else if (rel === "overrides") {
    for (const fn of gq.functionsNamed(db, name, false)) for (const o of gq.overridesOf(db, fn)) items.push([1, "`" + o.qualified + "` — `" + o.loc + "` (" + o.kind + ")", o.path]);
  } else if (rel === "members") {
    const cls = name.split("::").pop()!;
    for (const r of db.prepare("SELECT qualified, kind, path, line FROM defs WHERE scope=? OR scope LIKE ? ORDER BY path, line, qualified").all(cls, "%::" + cls) as any[]) items.push([1, "`" + r.qualified + "` (" + r.kind + ") — `" + r.path + ":" + r.line + "`", r.path]);
  } else if (rel === "definitions") {
    const [cls, short] = gq.splitSymbol(name);
    for (const r of db.prepare("SELECT qualified, kind, path, line FROM defs WHERE name=? ORDER BY path, line, kind").all(short) as any[]) if (!cls || String(r.qualified).endsWith(cls + "::" + short)) items.push([1, "`" + r.qualified + "` (" + r.kind + ") — `" + r.path + ":" + r.line + "`", r.path]);
  } else if (rel === "includers" || rel === "includes") {
    let frontier = [name]; const seen = new Set(frontier), byTarget = new Map<string, any[]>(), byPath = new Map<string, any[]>();
    for (const r of db.prepare("SELECT path, line, target FROM includes ORDER BY path, line").all() as any[]) { byTarget.set(base(r.target), [...(byTarget.get(base(r.target)) ?? []), r]); byPath.set(base(r.path), [...(byPath.get(base(r.path)) ?? []), r]); }
    for (let d = 1; d <= depth; d++) { const nxt: string[] = []; for (const x of frontier) if (rel === "includers") for (const r of (byTarget.get(base(x)) ?? []).filter((r) => includeMatches(r.target, x))) { if (!seen.has(r.path)) { seen.add(r.path); nxt.push(r.path); items.push([d, "`" + r.path + ":" + r.line + "`", r.path]); } } else for (const r of byPath.get(base(x)) ?? []) if ((r.path === x || r.path.endsWith("/" + x)) && !seen.has(r.target)) { seen.add(r.target); nxt.push(r.target); items.push([d, "`" + r.target + "` (from `" + r.path + ":" + r.line + "`)", r.target]); } frontier = nxt; }
  }
  const filtered = glob ? items.filter((it) => it[2] && matchesGlob(it[2], glob)) : items;
  return [title, "_" + note + "_", md.plural(filtered.length, "result") + ":", ...md.truncateList(filtered.map(([d, txt]) => "- " + txt + (depth > 1 ? " · depth " + d : "")), cfg.maxResults * 2, "results", "Narrow with `in <glob>` or a smaller depth.")].join("\n");
}

export async function get_lock_graph(args: { path_glob?: string; symbol?: string }): Promise<string> {
  const { analyse, _involves } = await import("./lockOrder.js");
  const cfg = loadConfig(), symbol = (args.symbol ?? "").trim(), pathGlob = args.path_glob ?? "";
  const { fns, edges } = await analyse(cfg, pathGlob);
  const scope = symbol ? "`" + symbol + "`" : pathGlob ? "`" + pathGlob + "`" : "repository";
  const title = "### 🔐 LOCK GRAPH: " + scope, taken = new Map<string, string[]>(), pairs = new Map<string, any[]>();
  for (const f of fns) for (const k of f.acquired.keys()) taken.set(k, [...(taken.get(k) ?? []), f.qualified]);
  for (const e of edges) pairs.set(e.first + "\0" + e.second, [...(pairs.get(e.first + "\0" + e.second) ?? []), e]);
  let pairEntries = [...pairs.entries()].map(([k, v]) => [k.split("\0") as [string, string], v] as [[string, string], any[]]);
  let keys = symbol ? [...new Set([...pairEntries.flatMap(([k]) => k), ...[...taken.keys()].filter((k) => _involves(k, symbol))])] : [...taken.keys()].sort();
  if (symbol) pairEntries = pairEntries.filter(([[a, b]]) => _involves(a, symbol) || _involves(b, symbol));
  if (!keys.length) return title + "\n✅ No lock acquisitions found.";
  const shown = ([...new Set(pairEntries.flatMap(([[a, b]]) => [a, b]))].sort().length ? [...new Set(pairEntries.flatMap(([[a, b]]) => [a, b]))].sort() : keys).slice(0, 20), ids = new Map(shown.map((k, i) => [k, "L" + (i + 1)]));
  const out = [title, md.plural(keys.length, "lock") + " taken by " + md.plural(new Set(keys.flatMap((k) => taken.get(k) ?? [])).size, "function") + "; " + md.plural(pairEntries.length, "order edge") + " (A → B: B is taken while A is held)."];
  if (pairEntries.length) { out.push("", "```mermaid", "graph LR", ...shown.map((k) => '  ' + ids.get(k) + '["' + k + '"]')); for (const [[a, b], ev] of pairEntries.sort()) if (ids.has(a) && ids.has(b)) { const e0 = ev.sort((x, y) => x.path < y.path ? -1 : x.path > y.path ? 1 : x.lineSecond - y.lineSecond)[0];   out.push('  ' + ids.get(a) + ' -->|"' + e0.fn.split("::").pop() + (e0.via ? " via " + e0.via.split("::").pop() : "") + '"| ' + ids.get(b)); } out.push("```"); }
  out.push("", "| Lock | Taken in | Then takes |", "|---|---|---|");
  const rows = keys.sort().map((k) => "| `" + k + "` | " + [...new Set(taken.get(k) ?? [])].sort().slice(0, 4).map((u) => "`" + u + "`").join(", ") + (((taken.get(k) ?? []).length > 4) ? " …" : "") + " | " + ([...new Set(pairEntries.filter(([[a]]) => a === k).map(([[, b]]) => b))].sort().map((t) => "`" + t + "`").join(", ") || "—") + " |");
  out.push(...md.truncateList(rows, cfg.maxResults, "locks"));
  out.push("\n_Use `track_lock_order` for cycles, locks taken twice and locks held across blocking calls._");
  return out.join("\n");
}
