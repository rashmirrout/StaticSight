import { statSync } from "node:fs";
import { join } from "node:path";
import { type Config, isCppFile, loadConfig } from "../config.js";
import * as md from "../core/md.js";
import { extractLeadingComment, stripCode } from "../core/cppText.js";
import { InvalidArgument, StaticSightError } from "../core/errors.js";
import { lineEvents } from "../core/locks.js";
import { matchesGlob, readLines, resolveInWorkspace } from "../core/paths.js";
import { runEngine } from "../engines/base.js";
import { cmpStr } from "../engines/ctags.js";
import { rgSearch } from "../engines/rg.js";
import * as gq from "../graph/query.js";
import { record } from "./findings.js";
import { obligations, classifyCall } from "./graphGtags.js";
import { checkSymbol, graphFor } from "./graphTools.js";

const FIX = /\b(fix(e[sd])?|bug|revert\w*|crash\w*|leak\w*|hotfix|regress\w*|race|deadlock|overflow|cve)\b/i;
export const _PLATFORM = /(^|[/_.-])(win|windows|win32|nt|posix|linux|unix|mac|darwin|apple|android)([/_.-]|$)/i;
const CPP_PATHSPECS = ["*.c", "*.cc", "*.cpp", "*.cxx", "*.h", "*.hh", "*.hpp", "*.hxx"];

async function git(cfg: Config, ...args: string[]): Promise<string> {
  const res = await runEngine("git", ["-c", "core.quotepath=off", ...args], { cwd: cfg.workspaceRoot, timeout: cfg.timeoutS });
  if (res.returncode !== 0) throw new StaticSightError("`git " + args.slice(0, 2).join(" ") + "` failed: " + res.stderr.trim().slice(0, 300));
  return res.stdout;
}
export function _is_fix(subject: string): boolean { return FIX.test(subject); }

export async function _history(cfg: Config, rel: string, a: number, b: number, n = 10): Promise<Array<[string, string, string]>> {
  try {
    const text = await git(cfg, "log", "-L" + a + "," + b + ":" + rel, "-s", "--format=%h%x09%ad%x09%s", "--date=short", "-n" + n);
    return text.split("\n").map((ln) => ln.split("\t", 3)).filter((p) => p.length === 3 && /^[0-9a-f]{4,40}$/.test(p[0])) as Array<[string, string, string]>;
  } catch { return []; }
}

async function blame(cfg: Config, rel: string, a: number, b: number): Promise<Array<[string, number, string, string]>> {
  const text = await git(cfg, "blame", "-w", "-M", "-C", "--line-porcelain", "-L", a + "," + b, "--", rel);
  const out: Array<[string, number, string, string]> = [];
  let sha = "", final = 0; const info = new Map<string, Record<string, string>>();
  for (const ln of text.split("\n")) {
    const m = /^([0-9a-f]{40}) \d+ (\d+)/.exec(ln);
    if (m) { sha = m[1]; final = Number(m[2]); if (!info.has(sha)) info.set(sha, {}); continue; }
    if (ln.startsWith("author-time ")) info.get(sha)!.date = new Date(Number(ln.split(/\s+/)[1]) * 1000).toISOString().slice(0, 10);
    else if (ln.startsWith("summary ")) info.get(sha)!.summary = ln.slice("summary ".length);
    else if (ln.startsWith("\t")) out.push([sha, final, info.get(sha)!.date ?? "", info.get(sha)!.summary ?? ""]);
  }
  return out;
}

export async function get_line_history(args: { file_path: string; start_line: number; end_line?: number }): Promise<string> {
  const cfg = loadConfig(), [abs, rel] = resolveInWorkspace(cfg.workspaceRoot, args.file_path), lines = readLines(abs);
  const a = Number(args.start_line || 0), b = Math.max(a, Math.min(Number(args.end_line || 0) || a, lines.length, a + 199));
  if (a < 1 || a > lines.length) throw new InvalidArgument("`start_line` " + a + " is outside `" + rel + "` (1-" + lines.length + ").");
  const title = "### 🕰️ LINE HISTORY: `" + rel + "` L" + a + (b !== a ? "-" + b : "");
  let bl: Array<[string, number, string, string]>;
  try { bl = await blame(cfg, rel, a, b); } catch (e) { return title + "\n❓ git has no history for these lines (" + (e as Error).message + ")."; }
  const out = [title, "**Last change per line** (git blame, ignoring whitespace and moved code)"];
  const groups: Array<[string, number, number, string, string]> = [];
  for (const [sha, ln, date, summ] of bl) {
    const last = groups[groups.length - 1];
    if (last && last[0] === sha && last[2] === ln - 1) last[2] = ln;
    else groups.push([sha, ln, ln, date, summ]);
  }
  const rows = groups.map(([sha, s, e, date, summ]) => {
    const rng = s === e ? "L" + s : "L" + s + "-" + e;
    return new Set(sha).size === 1 && sha[0] === "0" ? "- " + rng + " ✏️ not committed yet" : "- " + rng + " `" + sha.slice(0, 7) + "` " + date + (_is_fix(summ) ? " 🐞" : "") + " " + md.clip(summ, 100);
  });
  out.push(...md.truncateList(rows, cfg.maxResults, "line ranges"));
  const hist = await _history(cfg, rel, a, b), fixes = hist.filter((h) => _is_fix(h[2]));
  if (hist.length) out.push("**Commits that changed these lines** (newest first)", ...hist.map(([h, d, s], i) => (i + 1) + ". `" + h + "` " + d + (_is_fix(s) ? " 🐞" : "") + " " + md.clip(s, 100)));
  if (fixes.length) out.push("\n⚠️ " + md.plural(fixes.length, "earlier fix", "es") + " touched these lines: make sure the change does not undo it (" + fixes.slice(0, 3).map(([h]) => "`" + h + "`").join(", ") + ").");
  return out.join("\n");
}

function bitLength(n: number): number { return n <= 0 ? 0 : Math.floor(Math.log2(n)) + 1; }
export async function get_change_hotspots(args: { path_glob?: string; since_days?: number }): Promise<string> {
  const cfg = loadConfig(), pathGlob = args.path_glob ?? "", sinceDays = Math.max(1, Math.min(Number(args.since_days ?? 365), 3650));
  const headTs = Number((await git(cfg, "log", "-1", "--format=%ct")).trim() || "0"), since = new Date((headTs - sinceDays * 86400) * 1000).toISOString().replace(/\.\d+Z$/, "Z");
  const text = await git(cfg, "log", "--since=" + since, "--no-merges", "--numstat", "--format=%x1e%h%x1f%s", "--", ...CPP_PATHSPECS);
  const stats = new Map<string, [number, number, number]>();
  for (const chunk of text.split("\x1e")) {
    if (!chunk.trim()) continue;
    const [head, ...rest] = chunk.split("\n"), subj = head.includes("\x1f") ? head.split("\x1f", 2)[1] : "", fix = _is_fix(subj);
    for (const ln of rest) {
      const parts = ln.split("\t"); if (parts.length !== 3 || parts[2].includes(" => ")) continue;
      const p = parts[2], cur = stats.get(p) ?? [0, 0, 0];
      cur[0]++; if (fix) cur[1]++; cur[2] += (/^\d+$/.test(parts[0]) ? Number(parts[0]) : 0) + (/^\d+$/.test(parts[1]) ? Number(parts[1]) : 0); stats.set(p, cur);
    }
  }
  const title = "### 🔥 CHANGE HOTSPOTS: last " + sinceDays + " days of history" + (pathGlob ? " in `" + pathGlob + "`" : "");
  for (const p of [...stats.keys()]) {
    let isFile = false;
    try { isFile = statSync(join(cfg.workspaceRoot, p)).isFile(); } catch { isFile = false; }
    if (!isFile || (pathGlob && !matchesGlob(p, pathGlob))) stats.delete(p);
  }
  if (!stats.size) return title + "\n✅ No C/C++ changes in that period.";
  const [g, note, usable] = await graphFor(cfg), fanin = new Map<string, number>();
  if (usable) for (const p of stats.keys()) { let n = 0; for (const r of g.db.prepare("SELECT DISTINCT name FROM defs WHERE path=? AND kind='function'").all(p) as any[]) n += Number((g.db.prepare("SELECT COUNT(*) AS n FROM calls WHERE callee=? AND path<>? AND how<>'ref'").get(r.name, p) as any).n); fanin.set(p, n); }
  const rows = [...stats.entries()].map(([p, [c, fx, ch]]) => { const fi = fanin.get(p) ?? 0, sc = c * (1 + 2 * fx) * bitLength(1 + fi); return [sc, p, c, fx, ch, fi] as [number, string, number, number, number, number]; }).sort((a, b) => b[0] - a[0] || cmpStr(a[1], b[1]));
  const header = ["| File | Commits | Fixes 🐞 | Lines changed | Calls from other files | Score |", "|---|---|---|---|---|---|"];
  return [title, usable ? "_" + note + "_" : "_Code graph not available: fan-in not counted._", ...header, ...md.truncateList(rows.map(([sc, p, c, fx, ch, fi]) => "| `" + p + "` | " + c + " | " + fx + " | " + ch + " | " + fi + " | " + sc + " |"), cfg.maxResults, "files", "", header), "\n_Score = commits × (1 + 2 × fix commits) × (1 + ⌊log₂(1 + calls from other files)⌋): files that change often, keep needing fixes and are used widely deserve the closest review._"].join("\n");
}

const CASE = /\bcase\s+((?:[A-Za-z_]\w*\s*::\s*)*[A-Za-z_]\w*)\s*:(?!:)/g, DEFAULT = /\bdefault\s*:/, SWITCH = /\bswitch\s*\(/g;
function switchBlocks(stripped: string[]): Array<[number, number, string[], boolean]> {
  const text = stripped.join("\n"), starts = [0]; for (const ln of stripped) starts.push(starts[starts.length - 1] + ln.length + 1);
  const lineOf = (pos: number): number => { let lo = 0, hi = starts.length - 1; while (lo < hi) { const mid = Math.floor((lo + hi + 1) / 2); if (starts[mid] <= pos) lo = mid; else hi = mid - 1; } return lo + 1; };
  const out: Array<[number, number, string[], boolean]> = [];
  for (const m of text.matchAll(SWITCH)) {
    let depth = 1, i = m.index + m[0].length;
    while (i < text.length && depth) { if (text[i] === "(") depth++; else if (text[i] === ")") depth--; i++; }
    const brace = text.indexOf("{", i); if (brace < 0 || text.slice(i, brace).trim()) continue;
    let k = brace + 1, d = 1, segStart = k; const parts: string[] = [];
    while (k < text.length && d) { const ch = text[k]; if (ch === "{") { if (d === 1) parts.push(text.slice(segStart, k)); d++; } else if (ch === "}") { d--; if (d === 1) segStart = k + 1; } k++; }
    if (d === 0) parts.push(text.slice(segStart, k - 1));
    const top = parts.join(" "), labels = [...top.matchAll(CASE)].map((x) => x[1].replace(/\s+/g, ""));
    out.push([lineOf(m.index), lineOf(k - 1), labels, DEFAULT.test(top)]);
  }
  return out;
}

export async function switchCoverageReport(cfg: Config, enumName: string): Promise<string> {
  const name = checkSymbol(enumName).split("::").pop()!, [g, note, usable] = await graphFor(cfg), title = "### 🧩 SWITCH COVERAGE: `" + name + "`";
  if (!usable) return title + "\n_" + note + "_";
  const db = g.db, enumRows = db.prepare("SELECT path, line FROM defs WHERE name=? AND kind='enum' ORDER BY path, line").all(name) as any[], values = [...new Set((db.prepare("SELECT name FROM defs WHERE kind='enumerator' AND (scope=? OR scope LIKE ?) ORDER BY path, line").all(name, "%::" + name) as any[]).map((r) => String(r.name)))];
  if (!enumRows.length || !values.length) return title + "\n_" + note + "_\n❓ No enum named `" + name + "` with enumerators in the code graph.";
  const res = await rgSearch(cfg, values, { word: true, fixed: true }), out = [title, "_" + note + "_", "Defined at `" + enumRows[0].path + ":" + enumRows[0].line + "` with " + md.plural(values.length, "value") + ": " + values.map((v) => "`" + v + "`").join(", ") + "."], rows: string[] = [];
  let gaps = 0; const vs = new Set(values);
  for (const path of res.sortedPaths()) {
    let stripped: string[]; try { stripped = stripCode(readLines(join(cfg.workspaceRoot, path))); } catch { continue; }
    for (const [line, , labels, hasDefault] of switchBlocks(stripped)) {
      const short = labels.map((lab) => lab.split("::").pop()!), quals = labels.map((lab) => lab.includes("::") ? lab.slice(0, lab.lastIndexOf("::")) : "");
      const hits = short.filter((s) => vs.has(s)); if (!hits.length || short.some((s) => !vs.has(s)) || quals.some((q) => q && q.split("::").pop() !== name)) continue;
      const fn = gq.enclosingFunction(db, path, line), where = "`" + path + ":" + line + "`" + (fn ? " in `" + fn.qualified + "`" : ""), missing = values.filter((v) => !new Set(short).has(v));
      if (!missing.length) rows.push("- ✅ " + where + ": all " + values.length + " values handled");
      else { gaps++; const fid = record("switch_gap", hasDefault ? "medium" : "strong", path, line, name, "switch" + (fn ? " in " + fn.qualified : "") + " misses " + missing.join(", ") + (hasDefault ? " (falls into default)" : " (no default)"), fn?.qualified ?? ""); rows.push("- " + (hasDefault ? "⚠️ " : "❌ ") + where + ": missing " + missing.map((v) => "`" + v + "`").join(", ") + (hasDefault ? "; handled by `default:` — check that is right `" : " and no `default:` — the value falls through silently `") + fid + "`"); }
    }
  }
  if (!rows.length) out.push("No `switch` over this enum was found (it may be handled with `if` chains or lookup tables).");
  else out.push(md.plural(rows.length, "switch", "es") + ", " + gaps + " with missing values:", ...md.truncateList(rows, cfg.maxResults, "switches"));
  return out.join("\n");
}
export async function find_switch_coverage(args: { enum_name: string }): Promise<string> { return switchCoverageReport(loadConfig(), args.enum_name); }

const PAIRS: Array<[string, string]> = [["serialize", "deserialize"], ["encode", "decode"], ["marshal", "unmarshal"], ["pack", "unpack"], ["open", "close"], ["register", "unregister"], ["init", "uninit"], ["init", "deinit"], ["initialize", "uninitialize"], ["start", "stop"], ["acquire", "release"], ["alloc", "free"], ["allocate", "free"], ["create", "destroy"], ["create", "delete"], ["add", "remove"], ["push", "pop"], ["lock", "unlock"], ["connect", "disconnect"], ["load", "unload"], ["enable", "disable"], ["attach", "detach"], ["subscribe", "unsubscribe"], ["begin", "end"], ["enter", "leave"], ["read", "write"], ["get", "set"], ["insert", "erase"], ["send", "recv"], ["send", "receive"], ["increment", "decrement"], ["save", "load"], ["to", "from"]];
function style(word: string, like: string): string { return like.toUpperCase() === like ? word.toUpperCase() : like[0]?.toUpperCase() === like[0] ? word[0].toUpperCase() + word.slice(1) : word; }
export function counterpartNames(name: string): Array<[string, string, string]> {
  const out: Array<[string, string, string]> = [];
  for (const [a, b] of PAIRS) for (const [x, y] of [[a, b], [b, a]] as Array<[string, string]>) {
    const rx = new RegExp(x, "ig"); let m: RegExpExecArray | null;
    while ((m = rx.exec(name))) { const s = m.index, e = s + m[0].length, prev = s ? name[s - 1] : "", nxt = e < name.length ? name[e] : "", word = name.slice(s, e); if ((!prev || prev === "_" || (/[a-z]/.test(prev) && /^[A-Z]/.test(word)) || /\d/.test(prev)) && (!nxt || nxt === "_" || /[A-Z0-9]/.test(nxt))) out.push([name.slice(0, s) + style(y, word) + name.slice(e), x, y]); }
  }
  return [...new Map(out.map((x) => [x.join("\0"), x])).values()];
}
async function changedFunctions(cfg: Config): Promise<Set<string> | null> { try { const { analyseDiff } = await import("./diffScopes.js"); const ds = await analyseDiff(cfg, ""); return new Set(ds.changedFunctions().map(([r, sc]: any) => r.diff.path + "\0" + sc.tag.qualified)); } catch { return null; } }
async function cochange(cfg: Config, rel: string, limit = 400): Promise<Array<[string, number, number]>> {
  try { const text = await git(cfg, "log", "-n" + limit, "--no-merges", "--name-only", "--format=%x1e", "--", ...CPP_PATHSPECS); let mine = 0; const together = new Map<string, number>(); for (const chunk of text.split("\x1e")) { const files = chunk.split("\n").filter((f) => f.trim()); if (!files.length || files.length > 20 || !files.includes(rel)) continue; mine++; for (const f of files) if (f !== rel) together.set(f, (together.get(f) ?? 0) + 1); } return [...together.entries()].filter(([, n]) => n >= 2 && n * 2 >= mine).map(([f, n]) => [f, n, mine] as [string, number, number]).sort((a, b) => b[1] - a[1] || gq.cmp(a[0], b[0])).slice(0, 5); } catch { return []; }
}
export async function find_counterparts(args: { symbol: string }): Promise<string> {
  const cfg = loadConfig(), sym = checkSymbol(args.symbol), [g, note, usable] = await graphFor(cfg), title = "### 🪞 COUNTERPARTS: `" + sym + "`";
  if (!usable) return title + "\n_" + note + "_"; const db = g.db, targets = gq.functionsNamed(db, sym); if (!targets.length) return title + "\n_" + note + "_\n❓ No function named `" + sym + "` in the code graph.";
  const changed = await changedFunctions(cfg), mine = targets.filter((t) => changed?.has(t.path + "\0" + t.qualified)), t0 = (mine[0] ?? targets[0]), meChanged = mine.length > 0, out = [title, "_" + note + "_", "`" + t0.qualified + "` (`" + t0.loc + "`)" + (meChanged ? " — ✏️ changed in the current diff" : "")];
  const status = (f: gq.Fn): string => { if (!changed || !meChanged) return ""; if (changed.has(f.path + "\0" + f.qualified)) return " — ✏️ also changed"; const fid = record("counterpart_unchanged", "medium", f.path, f.line, f.qualified, "`" + t0.qualified + "` (" + t0.loc + ") changed but its counterpart `" + f.qualified + "` (" + f.loc + ") did not", f.qualified); return " — ⚠️ not changed in this diff `" + fid + "`"; };
  const naming: string[] = []; for (const [cand, x, y] of counterpartNames(t0.name)) for (const f of [...gq.functionsNamed(db, t0.cls ? t0.cls + "::" + cand : cand), ...gq.functionsNamed(db, cand)]) naming.push("- `" + f.qualified + "` (`" + f.loc + "`) — " + x + " ↔ " + y + status(f));
  out.push("**Naming pairs**", ...([...new Set(naming)].length ? [...new Set(naming)] : ["- none found"]));
  const twins: string[] = []; for (const f of gq.functionsNamed(db, t0.qualified)) if (f.key !== t0.key) { if (f.path === t0.path) twins.push("- `" + f.qualified + "` (`" + f.loc + "`) — same file, likely an `#ifdef` variant" + status(f)); else if (_PLATFORM.test(f.path) || _PLATFORM.test(t0.path)) twins.push("- `" + f.qualified + "` (`" + f.loc + "`) — platform variant" + status(f)); }
  out.push("**Platform or `#ifdef` twins**", ...(twins.length ? twins : ["- none found"]), "**Files that usually change together** (git history, bulk commits ignored)", ...(await cochange(cfg, t0.path)).map(([f, n, m]) => "- `" + f + "` — " + n + " of " + m + " commits that touched `" + t0.path + "`"));
  if (out[out.length - 1] === "**Files that usually change together** (git history, bulk commits ignored)") out.push("- none with at least 2 shared commits");
  out.push("\n_Use `find_similar_code` for copy-paste twins by meaning._"); return out.join("\n");
}

export const TEST_MACROS = gq.TEST_MACROS, testLabel = gq.label;
export async function find_related_tests(args: { symbol: string; depth?: number }): Promise<string> {
  const cfg = loadConfig(), sym = checkSymbol(args.symbol), depth = Math.max(1, Math.min(Number(args.depth ?? 3), 6)), [g, note, usable] = await graphFor(cfg), title = "### 🧪 RELATED TESTS: `" + sym + "`";
  if (!usable) return title + "\n_" + note + "_"; const db = g.db, targets = gq.functionsNamed(db, sym); if (!targets.length) return title + "\n_" + note + "_\n❓ No function named `" + sym + "` in the code graph.";
  const cache = new Map<string, any>(), found = new Map<string, [number, gq.Fn, gq.Call]>(), seen = new Set(targets.map((t) => t.key)); let frontier = targets.sort((a, b) => gq.cmp(a.key, b.key));
  for (let level = 1; level <= depth; level++) { const nxt = new Map<string, gq.Fn>(); for (const tgt of frontier) for (const c of gq.callersOf(db, tgt, cache)) if (!seen.has(c.callerKey)) { seen.add(c.callerKey); const fn = gq.callerFn(db, c); if (gq.isTestPath(fn.path)) found.set(fn.key, [level, fn, c]); else nxt.set(fn.key, fn); } frontier = [...nxt.keys()].sort().map((k) => nxt.get(k)!); }
  const out = [title, "_" + note + "_"]; if (found.size) out.push("**Tests that reach it through calls**", ...[...found.values()].sort((a, b) => a[0] - b[0] || gq.cmp(a[1].key, b[1].key)).map(([lvl, fn, c]) => "- `" + testLabel(fn) + "` (`" + fn.loc + "`) — " + (lvl === 1 ? "calls it directly" : lvl + " calls away") + " at `" + c.path + ":" + c.line + "`"));
  const res = await rgSearch(cfg, targets[0].name, { word: true, fixed: true }), mentions: string[] = []; for (const p of res.sortedPaths()) if (gq.isTestPath(p)) for (const m of res.files.get(p) ?? []) if (m.isMatch) { const fn = gq.enclosingFunction(db, p, m.line); if (fn && found.has(fn.key)) continue; mentions.push("- `" + p + ":" + m.line + "`" + (fn ? " in `" + testLabel(fn) + "`" : "") + ": `" + md.clip(m.text.trim(), 90) + "`"); }
  if (mentions.length) out.push("**Test files that mention it** (no resolved call)", ...md.truncateList(mentions, cfg.maxResults, "mentions"));
  if (!found.size && !mentions.length) out.push("⚠️ No test reaches `" + sym + "` within " + md.plural(depth, "call") + ", and no test file mentions it. Consider adding one before changing it.");
  return out.join("\n");
}

const FILE_LINE = /^(.+?):(\d+)$/;
export async function get_context_pack(args: { target: string; max_chars?: number }): Promise<string> {
  const cfg = loadConfig(), target = (args.target ?? "").trim(), maxChars = Math.max(1500, Math.min(Number(args.max_chars ?? 6000), 30000));
  if (!target) throw new InvalidArgument("`target` is empty: pass a function name or `file:line`.");
  const [g, note, usable] = await graphFor(cfg); if (!usable) return "### 📦 CONTEXT PACK: `" + target + "`\n_" + note + "_"; const db = g.db; let fn: gq.Fn | null = null;
  const m = FILE_LINE.exec(target); if (m && (m[1].includes("/") || m[1].includes("."))) { const [, rel] = resolveInWorkspace(cfg.workspaceRoot, m[1]); fn = gq.enclosingFunction(db, rel, Number(m[2])); if (!fn) throw new InvalidArgument("No function encloses `" + rel + ":" + m[2] + "`."); } else { const sym = checkSymbol(target), fns = gq.functionsNamed(db, sym); if (!fns.length) { const types = gq.typesNamed(db, sym.split("::").pop()!); if (types.length) { const { get_type_hierarchy } = await import("./graphTools.js"), { blastRadiusReport } = await import("./ripgrepMem.js"); const parts = [await get_type_hierarchy({ type_name: sym })]; if (!isCppFile(types[0][1]) || /\.(h|hh|hpp|hxx)$/.test(types[0][1])) parts.push(await blastRadiusReport(cfg, types[0][1], 2)); return md.enforceBudget("### 📦 CONTEXT PACK: type `" + sym + "`\n_" + note + "_\n\n" + parts.join("\n\n"), maxChars); } return "### 📦 CONTEXT PACK: `" + target + "`\n_" + note + "_\n❓ No function or type named `" + sym + "` in the code graph."; } fn = fns[0]; }
  const lines = readLines(join(cfg.workspaceRoot, fn.path)), sig = (fn.returnType + " " + fn.qualified + fn.signature).trim(), out = ["### 📦 CONTEXT PACK: `" + fn.qualified + "`", "_" + note + "_", "- **Where:** `" + fn.path + ":" + fn.line + "-" + fn.end + "` (" + md.plural(fn.end - fn.line + 1, "line") + ")", "- **Signature:** `" + md.clip(sig, 160) + "`"];
  let doc: string[] = []; for (const d of [...gq.functionsNamed(db, fn.qualified, false), fn]) try { doc = extractLeadingComment(readLines(join(cfg.workspaceRoot, d.path)), d.line - 1); if (doc.length) break; } catch { /* ignore */ }
  if (doc.length) { const obl = obligations(doc); out.push("\n**Contract**", ...doc.slice(0, 8).map((x) => "> " + md.clip(x, 150))); if (obl.length) out.push("Obligations: " + obl.slice(0, 4).map((o) => md.clip(o, 120)).join(" · ")); }
  try { const { branchSkeletonReport } = await import("./syntaxCtags.js"); const sk = (await branchSkeletonReport(cfg, fn.path, "", fn.line, 0)).split("\n").slice(1).join("\n"); out.push("\n**Logic** (branch skeleton)", md.enforceBudget(sk, Math.floor(maxChars / 3))); } catch { /* ignore */ }
  const cache = new Map<string, any>(), callers = gq.callersOf(db, fn, cache); out.push("\n**Callers** (" + callers.length + ")", ...(md.truncateList(callers.map((c) => "- `" + gq.callerLabel(db, c) + "` — `" + c.path + ":" + c.line + "` — " + (classifyCall(c.code, c.callee) || c.how)), 8, "callers", "`get_impact(\"" + fn.qualified + "\")` shows all levels.").length ? md.truncateList(callers.map((c) => "- `" + gq.callerLabel(db, c) + "` — `" + c.path + ":" + c.line + "` — " + (classifyCall(c.code, c.callee) || c.how)), 8, "callers", "`get_impact(\"" + fn.qualified + "\")` shows all levels.") : ["- none in the repository"]));
  const inside: string[] = [], external: string[] = []; for (const c of gq.callsFrom(db, fn)) if (c.how !== "ref") { const res = gq.resolveCall(db, c, cache); if (res.length) inside.push(...res.map((f) => "`" + f.qualified + "` (`" + f.loc + "`)")); else if (c.how === "call" || c.how === "qualified") external.push("`" + c.callee + "`"); }
  out.push("\n**Calls**", "- In the repository: " + ([...new Set(inside)].slice(0, 10).join(", ") || "none")); if (external.length) out.push("- Outside (libraries, SDK, macros): " + [...new Set(external)].slice(0, 12).join(", "));
  const types: string[] = []; for (const ident of [...new Set((fn.returnType + " " + fn.signature).match(/[A-Za-z_]\w*/g) ?? [])]) { const t = gq.typesNamed(db, ident); if (t.length) types.push("`" + ident + "` (" + t[0][3] + ", `" + t[0][1] + ":" + t[0][2] + "`)"); else { const r = (db.prepare("SELECT name, path, line, kind FROM defs WHERE name=? AND kind IN ('enum','typedef') ORDER BY path, line").get(ident) as any); if (r) types.push("`" + ident + "` (" + r.kind + ", `" + r.path + ":" + r.line + "`)"); } }
  if (types.length) out.push("\n**Types in the signature:** " + types.slice(0, 8).join(", "));
  const stripped = stripCode(lines), locks = new Set<string>(); for (let n = fn.line; n <= Math.min(fn.end, stripped.length); n++) for (const e of lineEvents(stripped[n - 1])) if (e.op === "acquire") for (const mx of e.mutexes) locks.add(mx);
  if (locks.size) out.push("\n**Locks taken:** " + [...locks].sort().map((x) => "`" + x + "`").join(", ") + " — see `track_lock_order` / `track_state_mutations` before changing the locking.");
  const tests: gq.Fn[] = [], seen = new Set([fn.key]); let frontier = [fn]; for (let i = 0; i < 3; i++) { const nxt: gq.Fn[] = []; for (const tgt of frontier) for (const c of gq.callersOf(db, tgt, cache)) if (!seen.has(c.callerKey)) { seen.add(c.callerKey); const f = gq.callerFn(db, c); (gq.isTestPath(f.path) ? tests : nxt).push(f); } frontier = nxt.sort((a, b) => gq.cmp(a.key, b.key)); }
  out.push("\n**Tests reaching it:** " + (tests.length ? tests.sort((a, b) => gq.cmp(a.key, b.key)).slice(0, 6).map((t) => "`" + testLabel(t) + "` (`" + t.loc + "`)").join(", ") : "none within 3 calls ⚠️"));
  const hist = await _history(cfg, fn.path, fn.line, fn.end, 3); if (hist.length) out.push("\n**Recent history:** " + hist.map(([h, d, s]) => "`" + h + "` " + d + (_is_fix(s) ? " 🐞" : "") + " " + md.clip(s, 60)).join("; "));
  return md.enforceBudget(out.join("\n"), maxChars);
}

const VARIABLE = /\b[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}\b|0x[0-9a-fA-F]+|\b\d+(?:[.:]\d+)*\b|'[^']*'|"[^"]*"|\{[^}]*\}|\[[^\]]*\]|[A-Za-z]:\\\S*|(?<!\w)\/\S+/g;
export function logFragments(text: string): string[] { return [...new Set(text.split(VARIABLE).map((p) => p.replace(/^[\s:;,.=\-|>]+|[\s:;,.=\-|<]+$/g, "")).filter((p) => p.length >= 6 && /[A-Za-z]{3}/.test(p)))].sort((a, b) => b.length - a.length || gq.cmp(a, b)).slice(0, 6); }
function inString(orig: string, stripped: string, col: number, length: number): boolean { return stripped.slice(col, col + length).trim() === "" && (orig.slice(0, col).match(/"/g) ?? []).length % 2 === 1; }
export async function find_log_origin(args: { text: string }): Promise<string> {
  const cfg = loadConfig(), text = (args.text ?? "").trim(); if (!text) throw new InvalidArgument("`text` is empty: paste the log or error line."); const frags = logFragments(text), title = '### 🔍 LOG ORIGIN: "' + md.clip(text, 100) + '"'; if (!frags.length) throw new InvalidArgument("No literal text to search for (the line looks like numbers and identifiers only).");
  const [g, note, usable] = await graphFor(cfg), db = usable ? g.db : null, hits = new Map<string, Set<string>>(), texts = new Map<string, string>();
  for (const fr of frags) { const res = await rgSearch(cfg, fr, { fixed: true }); for (const path of res.sortedPaths()) { let orig: string[], stripped: string[]; try { orig = readLines(join(cfg.workspaceRoot, path)); stripped = stripCode(orig); } catch { continue; } for (const m of res.files.get(path) ?? []) if (m.isMatch && m.line <= orig.length) { const col = orig[m.line - 1].indexOf(fr); if (col < 0 || !inString(orig[m.line - 1], stripped[m.line - 1], col, fr.length)) continue; const existing = [...hits.keys()].find((k) => k.startsWith(path + "\0") && m.line - Number(k.split("\0")[1]) >= 0 && m.line - Number(k.split("\0")[1]) <= 3); const key = existing ?? path + "\0" + m.line; if (!hits.has(key)) hits.set(key, new Set()); hits.get(key)!.add(fr); texts.set(key, orig[Number(key.split("\0")[1]) - 1].trim()); } } }
  const out = [title, "Searched " + md.plural(frags.length, "literal fragment") + ": " + frags.map((f) => '"' + f + '"').join(", ") + "."]; if (!hits.size) return out.concat("❓ No string literal in the C/C++ sources contains these fragments. The message may be built at run time, come from a resource file or another component, or be translated.").join("\n");
  const ranked = [...hits.entries()].sort((a, b) => [...b[1]].reduce((s, x) => s + x.length, 0) - [...a[1]].reduce((s, x) => s + x.length, 0) || gq.cmp(a[0], b[0])).slice(0, 3), cache = new Map<string, any>(), threads = db ? gq.threadTargets(db) : new Set<string>();
  ranked.forEach(([key, fr], i) => { const [path, lineS] = key.split("\0"), line = Number(lineS), fn = db ? gq.enclosingFunction(db, path, line) : null; out.push((i + 1) + ". `" + path + ":" + line + "`" + (fn ? " in `" + fn.qualified + "`" : "") + " — matches " + fr.size + " of " + frags.length + " fragments", "   `" + md.clip(texts.get(key) ?? "", 140) + "`"); if (fn && db) { const callers = gq.callersOf(db, fn, cache); out.push(callers.length ? "   - Called from: " + callers.slice(0, 5).map((c) => "`" + gq.callerLabel(db, c) + "` (`" + c.path + ":" + c.line + "`)").join(", ") + (callers.length > 5 ? " _…and " + (callers.length - 5) + " more_" : "") : "   - No callers found in the repository."); const kind = gq.entryKind(db, fn, threads); if (kind) out.push("   - It is itself a " + (kind === "test" ? "test" : "program or thread entry point") + "."); } });
  if (!usable) out.push("\n_" + note + "_"); out.push("\n_Next: `find_entry_paths(\"<function>\")` for how requests reach it, `get_context_pack` for its logic._"); return out.join("\n");
}
