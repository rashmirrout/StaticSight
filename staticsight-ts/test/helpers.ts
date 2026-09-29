import { execFileSync } from "node:child_process";
import { mkdirSync, mkdtempSync, readdirSync, readFileSync, rmSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { clearCache } from "../src/engines/ctags.js";
import { getIndexer, resetIndexers } from "../src/indexer.js";
import { getSemanticIndex, resetSemanticIndexes } from "../src/semantic/index.js";

export const SHARED = join(dirname(fileURLToPath(import.meta.url)), "..", "..", "shared");
const DATA = join(SHARED, "fixtures", "cpp-sample");

function copyTree(src: string, dst: string): void {
  const walk = (d: string): string[] => readdirSync(d).flatMap((n) => (statSync(join(d, n)).isDirectory() ? walk(join(d, n)) : [join(d, n)]));
  for (const f of walk(src).sort()) {
    const out = join(dst, relative(src, f));
    mkdirSync(dirname(out), { recursive: true });
    writeFileSync(out, readFileSync(f)); // byte-exact: keeps CRLF / BOM / UTF-16 files intact
  }
}

/** Same algorithm as shared/fixtures/make_fixture.py (manifest-driven, no shell). */
export function buildFixture(target: string): string {
  const manifest = JSON.parse(readFileSync(join(DATA, "manifest.json"), "utf8"));
  const id = manifest.identity;
  rmSync(target, { recursive: true, force: true });
  mkdirSync(target, { recursive: true });
  const cfgDir = mkdtempSync(join(tmpdir(), "ss-gitcfg-"));
  const emptyCfg = join(cfgDir, "config");
  writeFileSync(emptyCfg, "");
  const env = {
    ...process.env,
    GIT_AUTHOR_NAME: id.name, GIT_AUTHOR_EMAIL: id.email, GIT_AUTHOR_DATE: id.date,
    GIT_COMMITTER_NAME: id.name, GIT_COMMITTER_EMAIL: id.email, GIT_COMMITTER_DATE: id.date,
    GIT_CONFIG_GLOBAL: emptyCfg, GIT_CONFIG_NOSYSTEM: "1",
  };
  const git = (...args: string[]) => execFileSync("git", args, { cwd: target, env, stdio: "ignore", windowsHide: true });
  try {
    for (const step of manifest.steps) {
      if (step.op === "init") {
        git("init", "-q");
        git("symbolic-ref", "HEAD", `refs/heads/${step.branch}`);
        for (const [k, v] of [["commit.gpgsign", "false"], ["core.autocrlf", "false"], ["core.eol", "lf"], ["core.safecrlf", "false"], ["core.filemode", "false"]]) git("config", k, v);
      } else if (step.op === "copy") copyTree(join(DATA, step.from), target);
      else if (step.op === "commit") {
        git("add", "-A");
        git("commit", "-q", "--no-verify", "-m", step.message);
      } else if (step.op === "ref") git("update-ref", step.name, "HEAD");
      else if (step.op === "checkout") git("checkout", "-q", "-b", step.branch);
      else throw new Error(`unknown fixture op ${step.op}`);
    }
  } finally {
    rmSync(cfgDir, { recursive: true, force: true });
  }
  return target;
}

export async function setupWorkspace(): Promise<string> {
  const base = mkdtempSync(join(tmpdir(), "ss-ts-"));
  const root = buildFixture(join(base, "cpp-sample"));
  process.env.WORKSPACE_ROOT = root;
  process.env.STATICSIGHT_CACHE_DIR = join(base, "cache");
  for (const k of ["STATICSIGHT_BASE_REF", "STATICSIGHT_MAX_RESULTS", "STATICSIGHT_MAX_CHARS", "STATICSIGHT_TIMEOUT", "STATICSIGHT_DISABLE_ENGINES",
    "STATICSIGHT_SEMANTIC_AUTO_REFRESH", "STATICSIGHT_SEMANTIC_AUTO_REFRESH_FILES", "STATICSIGHT_EMBED_MODEL_DIR"]) delete process.env[k];
  process.env.STATICSIGHT_EMBED_MODEL = "test-hash"; // deterministic, no download; identical to the Python suite
  resetIndexers();
  resetSemanticIndexes();
  clearCache();
  await getIndexer().start();
  if (getIndexer().state !== "ready") throw new Error(`index not ready: ${JSON.stringify(getIndexer().status())}`);
  await getSemanticIndex().refresh();
  return root;
}
