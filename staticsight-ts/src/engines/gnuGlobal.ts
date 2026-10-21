// GNU Global adapter: database build/update and queries.
import { join } from "node:path";
import type { Config } from "../config.js";
import { StaticSightError } from "../core/errors.js";
import { readLines } from "../core/paths.js";
import type { CmdResult } from "../platform/index.js";
import { isAvailable, runEngine, toPosix } from "./base.js";
import { cmpStr } from "./ctags.js";

export const GLOBAL_LINE = /^(\S+)\s+(\d+)\s+(\S+)\s?(.*)$/;
export const INDEX_TIMEOUT_S = 1800;

export interface Hit {
  path: string;
  line: number;
  text: string;
}

export function available(): boolean {
  return isAvailable("gtags") && isAvailable("global");
}

export function parseXOutput(stdout: string): Hit[] {
  // Legacy ctags-x parser. Live queries use tab-delimited ctags output because this format cannot represent spaces
  // inside a path unambiguously.
  const seen = new Map<string, Hit>();
  for (const raw of stdout.split("\n")) {
    const m = GLOBAL_LINE.exec(raw.replace(/\r$/, ""));
    if (!m) continue;
    const hit = { path: toPosix(m[3]), line: parseInt(m[2], 10), text: m[4] };
    seen.set(`${hit.path}\u0000${hit.line}\u0000${hit.text}`, hit);
  }
  return [...seen.values()].sort((a, b) => cmpStr(a.path, b.path) || a.line - b.line);
}

export function parseCtagsOutput(stdout: string): Array<[string, number]> {
  const seen = new Map<string, [string, number]>();
  for (const raw of stdout.split(/\r?\n/)) {
    const parts = raw.split("\t");
    if (parts.length !== 3 || !/^\d+$/.test(parts[2])) continue;
    const path = toPosix(parts[1]), line = Number(parts[2]);
    seen.set(`${path}\u0000${line}`, [path, line]);
  }
  return [...seen.values()].sort((a, b) => cmpStr(a[0], b[0]) || a[1] - b[1]);
}

/** `global <flag> -- symbol`; null when the query cannot be answered (caller falls back). */
export async function query(cfg: Config, env: Record<string, string>, flag: string, symbol: string): Promise<Hit[] | null> {
  const mode = flag.replace("x", "");
  let res;
  try {
    res = await runEngine("global", ["--result=ctags", mode, "--", symbol], { cwd: cfg.workspaceRoot, timeout: cfg.timeoutS, env });
  } catch (e) {
    if (e instanceof StaticSightError) return null;
    throw e;
  }
  if (res.returncode !== 0 && res.returncode !== 1) return null;
  return parseCtagsOutput(res.stdout).map(([path, line]) => {
    let text = "";
    try {
      const lines = readLines(join(cfg.workspaceRoot, path));
      if (line > 0 && line <= lines.length) text = lines[line - 1];
    } catch {
      /* the file may have disappeared after the index query */
    }
    return { path, line, text };
  });
}

/** Incremental update of an existing in-repo GTAGS database. */
export function updateInPlace(root: string, env: Record<string, string>): Promise<CmdResult> {
  return runEngine("global", ["-u"], { cwd: root, timeout: INDEX_TIMEOUT_S, env });
}

/** (Re)build the database from an explicit file list (fed on stdin). Returns [result, human-readable action]. */
export async function build(root: string, dbPath: string, env: Record<string, string>, files: string[], incremental: boolean): Promise<[CmdResult, string]> {
  const inRepo = dbPath === root;
  const args = incremental || inRepo ? ["-i", "-f", "-"] : ["-f", "-"];
  if (!inRepo) args.push(dbPath);
  const res = await runEngine("gtags", args, { cwd: root, timeout: INDEX_TIMEOUT_S, env, stdinData: files.join("\n") + "\n" });
  return [res, ["gtags", ...args].slice(0, 4).join(" ") + ` (${files.length} files)`];
}
