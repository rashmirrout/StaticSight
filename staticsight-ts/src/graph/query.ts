export const FUNC_KINDS = ["function", "prototype"] as const;
export const TYPE_KINDS = ["class", "struct", "union"] as const;
const ENTRY_NAMES = new Set(["main", "wmain", "_tmain", "WinMain", "wWinMain", "_tWinMain", "DllMain", "ServiceMain"]);
const TEST_DIR = /(^|\/)(tests?|unittests?|unit_tests?|test_\w+|\w+_tests?)\//i;
const TEST_FILE = /(^|\/)(test_\w+|\w+_tests?|\w+Tests?)\.\w+$/;

export class Fn {
  constructor(
    public qualified: string,
    public name: string,
    public path: string,
    public line: number,
    public end: number,
    public kind: string,
    public scope: string,
    public scopeKind: string,
    public signature: string,
    public typeref: string,
    public properties: string,
  ) {}
  get cls(): string { return this.scope && (TYPE_KINDS as readonly string[]).includes(this.scopeKind) ? this.scope.split("::").pop() ?? "" : ""; }
  get loc(): string { return this.path + ":" + this.line; }
  get key(): string { return this.qualified + "\0" + this.path + "\0" + padLine(this.line); }
  get returnType(): string { return this.typeref.startsWith("typename:") ? this.typeref.slice("typename:".length) : this.typeref; }
}

export class Call {
  constructor(
    public path: string,
    public caller: string,
    public callerLine: number,
    public callee: string,
    public qualifier: string,
    public how: string,
    public line: number,
    public code: string,
    public text: string,
  ) {}
  get callerCls(): string {
    const parts = this.caller.split("::");
    return parts.length >= 2 ? parts[parts.length - 2] : "";
  }
  get callerKey(): string { return this.caller + "\0" + this.path + "\0" + padLine(this.callerLine); }
}

export const FN_COLS = "qualified, name, path, line, end_line, kind, scope, scope_kind, signature, typeref, properties";
export const CALL_COLS = "path, caller, caller_line, callee, qualifier, how, line, code, text";

function fns(rows: any[]): Fn[] {
  return rows.map((r) => new Fn(r.qualified, r.name, r.path, Number(r.line), Number(r.end_line), r.kind, r.scope, r.scope_kind, r.signature, r.typeref, r.properties));
}
function calls(rows: any[]): Call[] {
  return rows.map((r) => new Call(r.path, r.caller, Number(r.caller_line), r.callee, r.qualifier, r.how, Number(r.line), r.code, r.text));
}

export function isTestPath(path: string): boolean { return TEST_DIR.test(path) || TEST_FILE.test(path); }
export function splitSymbol(symbol: string): [string, string] {
  const s = symbol.trim().replace(/\)+$/, "").replace(/\(+$/, "").trim();
  const at = s.lastIndexOf("::");
  return at >= 0 ? [s.slice(0, at).split("::").pop() ?? "", s.slice(at + 2)] : ["", s];
}

export function functionsNamed(db: any, symbol: string, definitionsFirst = true): Fn[] {
  const [cls, short] = splitSymbol(symbol);
  let rows = fns(db.prepare("SELECT " + FN_COLS + " FROM defs WHERE name=? AND kind IN ('function','prototype') ORDER BY path, line, qualified").all(short));
  if (cls) rows = rows.filter((f) => f.cls === cls) || rows.filter((f) => f.scope.endsWith(cls));
  if (cls && !rows.length) rows = fns(db.prepare("SELECT " + FN_COLS + " FROM defs WHERE name=? AND kind IN ('function','prototype') ORDER BY path, line, qualified").all(short)).filter((f) => f.scope.endsWith(cls));
  if (definitionsFirst) {
    const defs = rows.filter((f) => f.kind === "function");
    if (defs.length) return defs;
  }
  return rows;
}

export function allNamed(db: any, name: string, kinds: string[]): Fn[] {
  const marks = kinds.map(() => "?").join(",");
  return fns(db.prepare("SELECT " + FN_COLS + " FROM defs WHERE name=? AND kind IN (" + marks + ") ORDER BY path, line, qualified").all(name, ...kinds));
}

export function enclosingFunction(db: any, path: string, line: number): Fn | null {
  const rows = fns(db.prepare("SELECT " + FN_COLS + " FROM defs WHERE path=? AND kind='function' AND line<=? AND end_line>=? ORDER BY (end_line-line), line DESC, qualified").all(path, line, line));
  return rows[0] ?? null;
}

export function functionAt(db: any, qualified: string, path: string, line: number): Fn | null {
  const rows = fns(db.prepare("SELECT " + FN_COLS + " FROM defs WHERE qualified=? AND path=? AND line=? AND kind='function'").all(qualified, path, line));
  return rows[0] ?? null;
}

function basesOf(inherits: string): string[] {
  const out: string[] = [];
  for (let part of inherits.split(",")) {
    part = part.replace(/<.*>/g, "").trim().replace(/^(public|protected|private|virtual)\s+/, "").trim();
    if (part) out.push(part.split("::").pop() ?? part);
  }
  return out;
}

export function typesNamed(db: any, name: string): Array<[string, string, number, string, string]> {
  return db.prepare("SELECT name, path, line, kind, inherits FROM defs WHERE name=? AND kind IN ('class','struct','union') ORDER BY path, line").all(name).map((r: any) => [r.name, r.path, Number(r.line), r.kind, r.inherits]);
}
export function bases(db: any, cls: string): string[] {
  const out: string[] = [];
  for (const [, , , , inh] of typesNamed(db, cls)) for (const b of basesOf(inh)) if (!out.includes(b)) out.push(b);
  return out;
}

const derivedIndex = new WeakMap<any, [number, Map<string, string[]>]>();
function totalChanges(db: any): number { return Number((db.prepare("SELECT total_changes() AS n").get() as any).n); }
function derivedMap(db: any): Map<string, string[]> {
  const stamp = totalChanges(db);
  const hit = derivedIndex.get(db);
  if (hit && hit[0] === stamp) return hit[1];
  const idx = new Map<string, string[]>();
  for (const r of db.prepare("SELECT name, inherits FROM defs WHERE inherits<>'' AND kind IN ('class','struct','union') ORDER BY name, path, line").all() as any[]) {
    for (const b of basesOf(r.inherits)) {
      const lst = idx.get(b) ?? [];
      if (!lst.includes(r.name)) lst.push(r.name);
      idx.set(b, lst);
    }
  }
  derivedIndex.set(db, [stamp, idx]);
  return idx;
}
export function derived(db: any, cls: string): string[] { return [...(derivedMap(db).get(cls) ?? [])]; }
export function family(db: any, cls: string, limit = 50): Set<string> {
  const seen = new Set([cls]); const todo = [cls];
  while (todo.length && seen.size < limit) {
    const c = todo.pop()!;
    for (const n of [...bases(db, c), ...derived(db, c)]) if (!seen.has(n)) { seen.add(n); todo.push(n); }
  }
  return seen;
}
export function overridesOf(db: any, fn: Fn): Fn[] {
  if (!fn.cls) return [];
  const fam = family(db, fn.cls);
  return fns(db.prepare("SELECT " + FN_COLS + " FROM defs WHERE name=? AND kind IN ('function','prototype') ORDER BY path, line, qualified").all(fn.name)).filter((f) => fam.has(f.cls) && f.cls !== fn.cls);
}

export function callsTo(db: any, name: string): Call[] {
  return calls(db.prepare("SELECT " + CALL_COLS + " FROM calls WHERE callee=? ORDER BY path, line, caller").all(name));
}
export function callsFrom(db: any, fn: Fn): Call[] {
  return calls(db.prepare("SELECT " + CALL_COLS + " FROM calls WHERE caller=? AND path=? AND caller_line=? ORDER BY line, callee").all(fn.qualified, fn.path, fn.line));
}

function typeNames(db: any, cache: Map<string, any>): Set<string> {
  if (!cache.has("__types__")) cache.set("__types__", new Set((db.prepare("SELECT DISTINCT name FROM defs WHERE kind IN ('class','struct','union')").all() as any[]).map((r) => r.name)));
  return cache.get("__types__");
}

export function callCanReach(db: any, c: Call, target: Fn, cache: Map<string, any>): boolean {
  const cls = target.cls;
  if (!cls) {
    if (c.how === "member") return false;
    if (c.how === "qualified" && c.qualifier) {
      if (target.scope && target.scope.split("::").pop() === c.qualifier) return true;
      return !typeNames(db, cache).has(c.qualifier);
    }
    if (c.how === "call" && c.callerCls) return !functionsNamed(db, c.callee, false).some((f) => f.cls === c.callerCls);
    return true;
  }
  if (!cache.has(cls)) cache.set(cls, family(db, cls));
  const fam = cache.get(cls) as Set<string>;
  if (c.how === "qualified") return fam.has(c.qualifier);
  if (c.how === "call") return fam.has(c.callerCls);
  return true;
}
export function callersOf(db: any, target: Fn, cache: Map<string, any>): Call[] { return callsTo(db, target.name).filter((c) => callCanReach(db, c, target, cache)); }
export function resolveCall(db: any, c: Call, cache: Map<string, any>): Fn[] { return functionsNamed(db, c.callee).filter((f) => callCanReach(db, c, f, cache)); }

export const TEST_MACROS = new Set(["TEST", "TEST_F", "TEST_P", "TYPED_TEST", "TYPED_TEST_P", "TEST_CASE", "SCENARIO", "BOOST_AUTO_TEST_CASE"]);
export function label(fn: Fn): string { return TEST_MACROS.has(fn.name) && fn.signature ? fn.name + fn.signature : fn.qualified; }
export function callerLabel(db: any, c: Call): string { return TEST_MACROS.has(c.caller.split("::").pop() ?? "") ? label(callerFn(db, c)) : c.caller; }
export function callerFn(db: any, c: Call): Fn {
  const f = functionAt(db, c.caller, c.path, c.callerLine);
  if (f) return f;
  const [, short] = splitSymbol(c.caller);
  const scope = c.caller.includes("::") ? c.caller.slice(0, c.caller.lastIndexOf("::")) : "";
  return new Fn(c.caller, short, c.path, c.callerLine, c.callerLine, "function", scope, "", "", "", "");
}
export function entryKind(_db: any, fn: Fn, threadTargets: Set<string>): string {
  if (ENTRY_NAMES.has(fn.name) && !fn.cls) return "program";
  if (threadTargets.has(fn.name)) return "thread";
  if (isTestPath(fn.path)) return "test";
  return "";
}
export function threadTargets(db: any): Set<string> {
  return new Set((db.prepare("SELECT DISTINCT callee FROM calls WHERE how='thread'").all() as any[]).map((r) => r.callee));
}
export function moduleOf(path: string): string {
  const parts = path.split("/");
  return parts.length > 2 ? parts.slice(0, 2).join("/") : parts.length > 1 ? parts[0] : ".";
}

/** Keys are strings ordered like Python's (name, path, line) tuples: the line is zero-padded so it sorts as a number. */
function padLine(n: number): string { return String(n).padStart(10, "0"); }

/** Python-style three-way compare of strings (code-point order). */
export function cmp(a: string, b: string): number { return a < b ? -1 : a > b ? 1 : 0; }
