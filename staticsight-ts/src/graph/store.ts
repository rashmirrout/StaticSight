import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join } from "node:path";
import type { Config } from "../config.js";
import { loadConfig, workspaceDataDir } from "../config.js";
import { stripCode } from "../core/cppText.js";
import { StaticSightError } from "../core/errors.js";
import { decodeSource, splitLines } from "../core/paths.js";
import { ctagsForFiles, type Tag } from "../engines/ctags.js";
import { headSha } from "../engines/git.js";
import { rgFiles } from "../engines/rg.js";
import { IndexLock } from "../engines/vectorStore.js";
import { sharedText } from "../shared.js";

export const GRAPH_VERSION = "2";
const DEF_KINDS = new Set(["function", "prototype", "class", "struct", "union", "enum", "enumerator", "member", "typedef", "macro"]);
const NOT_CALLS = new Set(["if", "for", "while", "switch", "return", "sizeof", "alignof", "decltype", "static_cast", "reinterpret_cast", "const_cast", "dynamic_cast", "catch", "throw", "noexcept", "defined", "static_assert", "typeid", "alignas", "assert", "new", "delete", "operator", "co_return", "co_await", "co_yield", "__attribute__", "__declspec"]);
const THREAD_APIS = new Set(["thread", "jthread", "async", "CreateThread", "_beginthreadex", "_beginthread", "QueueUserWorkItem", "CreateThreadpoolWork", "CreateThreadpoolTimer", "CreateThreadpoolWait", "TrySubmitThreadpoolCallback", "CreateTimerQueueTimer", "RegisterWaitForSingleObject", "SetTimer", "RegisterServiceCtrlHandler", "RegisterServiceCtrlHandlerW", "RegisterServiceCtrlHandlerA", "RegisterServiceCtrlHandlerEx", "RegisterServiceCtrlHandlerExW", "RegisterServiceCtrlHandlerExA", "pthread_create", "atexit", "signal"]);
const CALL = /\b([A-Za-z_]\w*)\s*\(/g;
const QUAL = /([A-Za-z_]\w*)\s*(?:<[^<>;]*>)?\s*::\s*$/;
const OBJ = /([\w\])]+)\s*(?:\.|->)\s*$/;
const DECL_BEFORE = /(?:^|[\s(,;{])(?!(?:return|else|throw|co_return|co_await|case|delete|new|goto)\b)[A-Za-z_][\w:]*(?:<[^()]*>)?(?:\s+|\s*(?:\*+|&(?!&))\s*)$/;
const THREAD_DECL = /\b(?:std::)?j?thread\s+\w+\s*([({])/g;
const ADDR = /&\s*((?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)\b(?!\s*(?:\(|\[|\.|->|::))/g;
const FN_ARG = /^&?\s*((?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)$/;
const INCLUDE = /^\s*#\s*include\s*[<"]([^>"]+)[>"]/;
const ALLCAPS = /^[A-Z][A-Z0-9_]*$/;
const RANK: Record<string, number> = { thread: 0, ref: 1, qualified: 2, member: 3, call: 4 };

const origEmit = process.emitWarning.bind(process);
process.emitWarning = ((warning: string | Error, ...rest: unknown[]) => {
  if (String((warning as Error)?.message ?? warning).includes("SQLite")) return;
  return (origEmit as (...a: unknown[]) => void)(warning, ...rest);
}) as typeof process.emitWarning;
const { DatabaseSync } = await import("node:sqlite");
type DB = InstanceType<typeof DatabaseSync>;

export interface Drift { stats: Map<string, [number, string]>; changed: string[]; deleted: string[]; total: number }

function clip(text: string, n: number): string {
  const t = text.trimEnd();
  return t.length <= n ? t : t.slice(0, n - 1) + "…";
}

function argsOf(code: string, openIdx: number): string[] {
  const close = code[openIdx] === "(" ? ")" : "}";
  let depth = 0, cur = "";
  const out: string[] = [];
  for (let i = openIdx; i < code.length; i++) {
    const ch = code[i];
    if ("([{".includes(ch)) {
      depth++;
      if (depth === 1) continue;
    } else if (")]}".includes(ch)) {
      depth--;
      if (depth === 0 && ch === close) {
        out.push(cur);
        break;
      }
    } else if (ch === "," && depth === 1) {
      out.push(cur);
      cur = "";
      continue;
    }
    cur += ch;
  }
  return out.map((a) => a.trim()).filter(Boolean);
}

export function callsInLine(code: string, fnShort: string): Array<[string, string, string]> {
  const found: Array<[number, string, string, string]> = [];
  const addFnArgs = (openIdx: number, col: number): void => {
    for (const a of argsOf(code, openIdx)) {
      const m = FN_ARG.exec(a);
      if (m) {
        const parts = m[1].split("::");
        found.push([col, parts[parts.length - 1], parts.slice(0, -1).join("::"), "thread"]);
      }
    }
  };
  for (const m of code.matchAll(THREAD_DECL)) addFnArgs(m.index + m[0].lastIndexOf(m[1]), m.index);
  for (const m of code.matchAll(CALL)) {
    const name = m[1];
    if (NOT_CALLS.has(name) || (name.length > 1 && ALLCAPS.test(name))) continue;
    const rawBefore = code.slice(0, m.index);
    const before = rawBefore.trimEnd();
    if (THREAD_APIS.has(name)) addFnArgs(m.index + m[0].length - 1, m.index);
    if (before.endsWith("::")) {
      const q = QUAL.exec(before);
      const qual = q ? q[1] : "";
      if (qual === "std") continue;
      found.push([m.index, name, qual, "qualified"]);
    } else if (before.endsWith(".") || before.endsWith("->")) {
      const o = OBJ.exec(before);
      found.push([m.index, name, o ? o[1] : "", "member"]);
    } else {
      if (DECL_BEFORE.test(rawBefore) || before.endsWith("operator")) continue;
      if (name === fnShort && !before) continue;
      found.push([m.index, name, "", "call"]);
    }
  }
  for (const m of code.matchAll(ADDR)) {
    const prev = code.slice(0, m.index).trimEnd();
    if (prev && !"(,={?:".includes(prev[prev.length - 1])) continue;
    const parts = m[1].split("::");
    found.push([m.index, parts[parts.length - 1], parts.slice(0, -1).join("::"), "ref"]);
  }
  const best = new Map<string, [number, string, string, string]>();
  for (const f of found.sort((a, b) => a[0] - b[0] || (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0) || RANK[a[3]] - RANK[b[3]])) {
    const cur = best.get(f[1]);
    if (!cur || RANK[f[3]] < RANK[cur[3]]) best.set(f[1], [cur ? Math.min(f[0], cur[0]) : f[0], f[1], f[2], f[3]]);
  }
  return [...best.values()].sort((a, b) => a[0] - b[0] || (a[1] < b[1] ? -1 : a[1] > b[1] ? 1 : 0)).map((f) => [f[1], f[2], f[3]]);
}

export function parseFile(path: string, lines: string[], tags: Tag[]): [any[], any[], any[]] {
  const stripped = stripCode(lines);
  const defs = tags
    .filter((t) => DEF_KINDS.has(t.kind))
    .map((t) => [path, t.shortName, t.qualified, t.kind, t.line, t.end, t.scope, t.scopeKind, t.signature, t.typeref, t.inherits, t.properties])
    .sort((a, b) => Number(a[4]) - Number(b[4]) || Number(a[5]) - Number(b[5]) || (String(a[3]) < String(b[3]) ? -1 : String(a[3]) > String(b[3]) ? 1 : 0) || (String(a[2]) < String(b[2]) ? -1 : String(a[2]) > String(b[2]) ? 1 : 0));
  const calls: any[] = [];
  for (const t of tags.filter((x) => x.kind === "function").sort((a, b) => a.line - b.line || a.end - b.end || (a.qualified < b.qualified ? -1 : a.qualified > b.qualified ? 1 : 0))) {
    let start: [number, number] | null = null;
    for (let n = t.line; n <= Math.min(t.end, stripped.length); n++) {
      const c = stripped[n - 1].indexOf("{");
      if (c >= 0) { start = [n, c]; break; }
    }
    if (!start) continue;
    for (let n = start[0]; n <= Math.min(t.end, stripped.length); n++) {
      let code = stripped[n - 1];
      if (n === start[0]) code = " ".repeat(start[1] + 1) + code.slice(start[1] + 1);
      if (code.trimStart().startsWith("#") || (!code.includes("(") && !code.includes("&"))) continue;
      for (const [callee, qual, how] of callsInLine(code, t.shortName)) calls.push([path, t.qualified, t.line, callee, qual, how, n, clip(code.trim(), 300), clip((lines[n - 1] ?? "").trim(), 200)]);
    }
  }
  const includes: any[] = [];
  lines.forEach((ln, i) => { const m = INCLUDE.exec(ln); if (m) includes.push([path, i + 1, m[1]]); });
  return [defs, calls, includes];
}

export class CodeGraph {
  dbPath: string;
  private _db: DB | null = null;
  private task: Promise<void> | null = null;
  done = 0;
  total = 0;
  error = "";

  constructor(public cfg: Config) {
    this.dbPath = join(workspaceDataDir(cfg)[0], "graph.db");
  }

  get db(): DB {
    if (!this._db) {
      mkdirSync(dirname(this.dbPath), { recursive: true });
      const db = new DatabaseSync(this.dbPath) as DB;
      db.exec("PRAGMA journal_mode=WAL");
      db.exec("PRAGMA synchronous=NORMAL");
      db.exec(sharedText("graph/schema.sql"));
      const ver = db.prepare("SELECT value FROM meta WHERE key='version'").get() as any;
      if (ver && ver.value !== GRAPH_VERSION) {
        for (const t of ["defs", "calls", "includes", "files", "meta"]) db.exec("DROP TABLE IF EXISTS " + t);
        db.exec(sharedText("graph/schema.sql"));
      }
      this._db = db;
    }
    return this._db;
  }

  meta(): Record<string, string> {
    const out: Record<string, string> = {};
    for (const r of this.db.prepare("SELECT key, value FROM meta").all() as any[]) out[r.key] = r.value;
    return out;
  }
  fileCount(): number { return Number((this.db.prepare("SELECT COUNT(*) AS n FROM files").get() as any).n); }
  get exists(): boolean { return existsSync(this.dbPath) && this.meta().version === GRAPH_VERSION; }
  get building(): boolean { return this.task !== null; }

  async drift(): Promise<Drift> {
    const paths = await rgFiles(this.cfg);
    const stats = new Map<string, [number, string]>();
    for (const p of paths) {
      try {
        const st = statSync(join(this.cfg.workspaceRoot, p), { bigint: true });
        stats.set(p, [Number(st.size), String(st.mtimeNs)]);
      } catch { /* ignore */ }
    }
    const known = new Map<string, [number, string]>((this.db.prepare("SELECT path, size, mtime_ns FROM files").all() as any[]).map((r) => [r.path, [Number(r.size), String(r.mtime_ns)]]));
    const changed = [...stats.entries()].filter(([p, st]) => { const k = known.get(p); return !k || k[0] !== st[0] || k[1] !== st[1]; }).map(([p]) => p).sort();
    const deleted = [...known.keys()].filter((p) => !stats.has(p)).sort();
    return { stats, changed, deleted, total: changed.length + deleted.length };
  }

  async refresh(full = false): Promise<string> {
    mkdirSync(dirname(this.dbPath), { recursive: true });
    const lock = new IndexLock(this.dbPath.replace(/\.db$/, ".lock"));
    if (!lock.acquire()) return "another StaticSight process is refreshing the code graph";
    try { return await this.doRefresh(full, lock); } finally { lock.release(); }
  }

  private async doRefresh(full: boolean, lock: IndexLock): Promise<string> {
    const db = this.db;
    if (full) for (const t of ["defs", "calls", "includes", "files"]) db.exec("DELETE FROM " + t);
    const d = await this.drift();
    const known = new Map<string, string>((db.prepare("SELECT path, sha1 FROM files").all() as any[]).map((r) => [r.path, r.sha1]));
    this.total = d.changed.length; this.done = 0;
    let parsed = 0;
    const insertDefs = db.prepare("INSERT INTO defs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)");
    const insertCalls = db.prepare("INSERT INTO calls VALUES(?,?,?,?,?,?,?,?,?)");
    const insertIncludes = db.prepare("INSERT INTO includes VALUES(?,?,?)");
    for (let i = 0; i < d.changed.length; i += 100) {
      const batch = d.changed.slice(i, i + 100);
      const todo: Array<[string, string[], string]> = [];
      for (const p of batch) {
        try {
          const data = readFileSync(join(this.cfg.workspaceRoot, p));
          const sha = createHash("sha1").update(data).digest("hex");
          const st = d.stats.get(p)!;
          if (known.get(p) === sha) { db.prepare("UPDATE files SET size=?, mtime_ns=? WHERE path=?").run(st[0], st[1], p); continue; }
          todo.push([p, splitLines(decodeSource(data)), sha]);
        } catch { /* ignore */ }
      }
      const tags = todo.length ? await ctagsForFiles(this.cfg, todo.map(([p]) => p)) : new Map<string, Tag[]>();
      db.exec("BEGIN");
      try {
        for (const [p, lines, sha] of todo) {
          const [defs, calls, incs] = parseFile(p, lines, tags.get(p) ?? []);
          for (const t of ["defs", "calls", "includes"]) db.prepare("DELETE FROM " + t + " WHERE path=?").run(p);
          for (const r of defs) insertDefs.run(...r);
          for (const r of calls) insertCalls.run(...r);
          for (const r of incs) insertIncludes.run(...r);
          const st = d.stats.get(p)!;
          db.prepare("INSERT OR REPLACE INTO files VALUES(?,?,?,?)").run(p, st[0], st[1], sha);
          parsed++;
        }
        db.exec("COMMIT");
      } catch (e) { db.exec("ROLLBACK"); throw e; }
      this.done = Math.min(this.total, i + batch.length);
      lock.heartbeat();
    }
    if (d.deleted.length) {
      db.exec("BEGIN");
      for (const p of d.deleted) for (const t of ["defs", "calls", "includes", "files"]) db.prepare("DELETE FROM " + t + " WHERE path=?").run(p);
      db.exec("COMMIT");
    }
    let head = "";
    try { head = await headSha(this.cfg); } catch (e) { if (!(e instanceof StaticSightError)) throw e; }
    const meta = db.prepare("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)");
    meta.run("version", GRAPH_VERSION); meta.run("head", head); meta.run("updated_at", String(Math.floor(Date.now() / 1000)));
    return "re-parsed " + parsed + " changed file(s), removed " + d.deleted.length;
  }

  startBackground(full = false): boolean {
    if (this.building) return false;
    this.task = this.refresh(full).then(() => { this.error = ""; }, (e) => { this.error = e instanceof StaticSightError ? e.message : String(e); }).finally(() => { this.task = null; });
    return true;
  }
  async waitForBackground(): Promise<void> { if (this.task) await this.task; }
  progress(): string { return this.total ? this.done + "/" + this.total + " files" : "starting"; }

  async ensureFresh(): Promise<[string, boolean]> {
    // the background build counts its files first (well under a second); a small build finishes sooner than a retry would
    for (let i = 0; i < 100 && this.building && this.total === 0; i++) await new Promise((r) => setTimeout(r, 50));
    if (this.building && this.total <= this.cfg.graphAutoRefreshFiles) await this.waitForBackground();
    if (this.building) return ["⚠️ The code graph is being refreshed in the background (" + this.progress() + "); results may be incomplete. Retry for the full picture.", this.exists && this.fileCount() > 0];
    const empty = !this.exists || this.fileCount() === 0;
    if (!this.cfg.graphAutoRefresh) return empty ? ["The code graph has not been built (automatic refresh is disabled): run `staticsight index build`.", false] : ["Code graph (automatic refresh disabled; may be stale).", true];
    const d = await this.drift();
    if (d.total === 0) return ["Code graph up to date (" + this.fileCount() + " files).", true];
    if (d.total <= this.cfg.graphAutoRefreshFiles) return ["Code graph refreshed before answering: " + await this.refresh() + ".", true];
    this.startBackground(empty);
    if (empty) return ["The code graph is being built for the first time in the background (" + d.changed.length + " files). Retry in a moment; `get_index_status` shows progress.", false];
    return ["⚠️ " + d.total + " files changed since the code graph was built; a background refresh has started. Results come from the previous graph; retry for fresh results.", true];
  }

  statusLines(): string[] {
    if (!this.building && !this.exists) return ["### 🕸️ CODE GRAPH", "- **State:** not built yet (built automatically on the first graph tool call)"];
    const state = this.building ? "building (" + this.progress() + ")" : "ready (last refresh " + (Math.floor(Date.now() / 1000) - Number(this.meta().updated_at || 0)) + "s ago, HEAD " + ((this.meta().head || "").slice(0, 10) || "n/a") + ")";
    const one = (q: string) => Number((this.db.prepare(q).get() as any).n);
    const out = ["### 🕸️ CODE GRAPH", "- **State:** " + state, "- **Content:** " + one("SELECT COUNT(*) AS n FROM files") + " files, " + one("SELECT COUNT(*) AS n FROM defs") + " definitions, " + one("SELECT COUNT(*) AS n FROM calls") + " calls and references, " + one("SELECT COUNT(*) AS n FROM includes") + " includes"];
    if (this.error) out.push("- **Last error:** " + this.error);
    out.push("- **Database:** `" + this.dbPath + "`");
    return out;
  }

  close(): void { if (this._db) this._db.close(); this._db = null; }
}

const graphs = new Map<string, CodeGraph>();
export function getGraph(cfg: Config = loadConfig()): CodeGraph {
  const key = cfg.workspaceRoot + "|" + cfg.cacheDir + "|" + cfg.dataDirMode;
  let g = graphs.get(key);
  if (!g) { g = new CodeGraph(cfg); graphs.set(key, g); } else g.cfg = cfg;
  return g;
}
export function resetGraphs(): void { for (const g of graphs.values()) g.close(); graphs.clear(); }
