import { AsyncLocalStorage } from "node:async_hooks";
import { createHash } from "node:crypto";
import { existsSync, mkdirSync, readFileSync, renameSync, writeFileSync } from "node:fs";
import { join } from "node:path";

const CONFIDENCE = new Set(["strong", "medium", "weak"]);
const MAX_STORED = 2000;

export interface Finding {
  id: string;
  kind: string;
  confidence: string;
  path: string;
  line: number;
  symbol: string;
  message: string;
  function: string;
}

const current = new AsyncLocalStorage<Finding[] | null>();

export function findingId(kind: string, path: string, line: number, key: string): string {
  return "F" + createHash("sha1").update(`${kind}|${path}|${line}|${key}`).digest("hex").slice(0, 6);
}

export async function collect<T>(fn: () => Promise<T>): Promise<[T, Finding[]]> {
  const bucket: Finding[] = [];
  const value = await current.run(bucket, fn);
  return [value, bucket];
}

export async function withBucket<T>(fn: () => Promise<T>): Promise<T> {
  return current.run([], fn);
}

export function begin(): Finding[] {
  const bucket: Finding[] = [];
  current.enterWith(bucket);
  return bucket;
}

export function end(bucket: Finding[]): Finding[] {
  return bucket;
}

export function make(kind: string, confidence: string, path: string, line: number, symbol: string, message: string, fn = ""): Finding {
  if (!CONFIDENCE.has(confidence)) throw new Error("confidence must be one of ('strong', 'medium', 'weak')");
  return { id: findingId(kind, path, line, symbol), kind, confidence, path, line, symbol, message, function: fn };
}

export function add(f: Finding): void {
  const bucket = current.getStore();
  if (bucket && !bucket.some((x) => x.id === f.id)) bucket.push(f);
}

export function record(kind: string, confidence: string, path: string, line: number, symbol: string, message: string, fn = ""): string {
  const f = make(kind, confidence, path, line, symbol, message, fn);
  add(f);
  return f.id;
}

export function asDict(f: Finding): Finding {
  return { ...f };
}

function store(dataDir: string): string {
  return join(dataDir, "findings.json");
}

export function load(dataDir: string): Record<string, any> {
  try {
    const data = JSON.parse(readFileSync(store(dataDir), "utf8"));
    const out: Record<string, any> = {};
    for (const f of data.findings ?? []) if (f && typeof f === "object" && "id" in f) out[String(f.id)] = f;
    return out;
  } catch {
    return {};
  }
}

function lineText(root: string, rel: string, line: number, cache: Map<string, string[]>): string {
  if (!cache.has(rel)) {
    try {
      cache.set(rel, readFileSync(join(root, rel), "utf8").split(/\r?\n/));
    } catch {
      cache.set(rel, []);
    }
  }
  const lines = cache.get(rel)!;
  return line > 0 && line <= lines.length ? lines[line - 1].trim() : "";
}

export function flush(root: string, dataDir: string, found: Finding[], tool: string, args: Record<string, unknown>): void {
  if (!found.length) return;
  const known = load(dataDir);
  const cache = new Map<string, string[]>();
  for (const f of found) {
    delete known[f.id];
    known[f.id] = { ...f, code: lineText(root, f.path, f.line, cache), tool, args };
  }
  const items = Object.values(known).slice(-MAX_STORED);
  try {
    mkdirSync(dataDir, { recursive: true });
    const tmp = store(dataDir) + ".tmp";
    writeFileSync(tmp, JSON.stringify({ version: 1, findings: items }, null, 1), "utf8");
    renameSync(tmp, store(dataDir));
  } catch {
    /* ignore */
  }
}

export function lookup(dataDir: string, fid: string): any | null {
  return existsSync(store(dataDir)) ? load(dataDir)[fid.trim()] ?? null : null;
}
