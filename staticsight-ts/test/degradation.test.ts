import { chmodSync, mkdirSync, mkdtempSync, symlinkSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { afterEach, beforeAll, describe, expect, it } from "vitest";
import * as capabilities from "../src/engines/capabilities.js";
import { clearCache } from "../src/engines/ctags.js";
import { getIndexer, resetIndexers } from "../src/indexer.js";
import { current } from "../src/platform/index.js";
import { safeTool, TOOLS } from "../src/server.js";
import { setupWorkspace } from "./helpers.js";

const T = (name: string, args: Record<string, unknown> = {}) => safeTool(name, TOOLS[name])(args);
let oldPath = "";
const posixOnly = process.platform === "win32" ? it.skip : it;

function disable(...tools: string[]): void {
  process.env.STATICSIGHT_DISABLE_ENGINES = tools.join(",");
  resetIndexers();
  clearCache();
}

function limitPath(tools: string[], fake: Record<string, string> = {}): void {
  const bin = join(mkdtempSync(join(tmpdir(), "ss-bin-")), "bin");
  mkdirSync(bin);
  for (const t of tools) symlinkSync(current().findExecutable(t)!, join(bin, t));
  for (const [name, script] of Object.entries(fake)) {
    writeFileSync(join(bin, name), script);
    chmodSync(join(bin, name), 0o755);
  }
  process.env.PATH = bin;
  resetIndexers();
  clearCache();
}

describe("degradation", () => {
  beforeAll(async () => {
    await setupWorkspace();
    oldPath = process.env.PATH!;
  });
  afterEach(async () => {
    process.env.PATH = oldPath;
    delete process.env.STATICSIGHT_TIMEOUT;
    delete process.env.STATICSIGHT_DISABLE_ENGINES;
    capabilities.clearCache();
    resetIndexers();
    clearCache();
    await getIndexer().start();
  });

  posixOnly("real PATH lookup without GNU Global", async () => {
    limitPath(["git", "rg", "ctags"]);
    expect(await T("get_upstream_callers", { symbol: "process_packet" })).toContain("ripgrep fallback");
  });
  it("callers fall back to ripgrep without GNU Global", async () => {
    disable("global", "gtags");
    const out = await T("get_upstream_callers", { symbol: "process_packet" });
    expect(out).toContain("ripgrep fallback");
    expect(out).toContain("L17 in `Listener::dispatch_batch` — ⚠️ result ignored");
    expect(await T("get_index_status")).toContain("`global` ❌");
  });
  it("reports missing cppcheck", async () => {
    disable("cppcheck");
    const out = await T("run_file_static_audit", { file_path: "src/router.cpp" });
    expect(out.startsWith("### ❌ Required CLI tool is not installed")).toBe(true);
  });
  it("reports missing ctags", async () => {
    disable("ctags");
    expect(await T("get_enclosing_scope", { file_path: "src/router.cpp", target_line: 13 })).toContain("`ctags` was not found on PATH");
  });
  it("reports missing git but skeleton still works", async () => {
    disable("git");
    expect(await T("get_diff_scopes")).toContain("`git` was not found on PATH");
    expect(await T("get_branch_skeleton", { file_path: "src/router.cpp", symbol: "process_packet" })).toContain("BRANCH SKELETON");
  });
  it("explains a ctags without JSON (Exuberant)", async () => {
    const exe = current().findExecutable("ctags")!;
    capabilities.cache.set(`ctags\u0000${exe}`, {
      name: "ctags", level: "required", path: exe, version: "Exuberant Ctags 5.8", ok: false,
      problem: "`Exuberant Ctags 5.8` has no JSON output", hint: capabilities.EXUBERANT_HINT,
    });
    clearCache();
    const out = await T("get_enclosing_scope", { file_path: "src/router.cpp", target_line: 13 });
    expect(out).toContain("has no JSON output");
    expect(out).toContain("universal-ctags");
  });
  posixOnly("times out slow tools", async () => {
    limitPath(["git", "ctags"], { rg: "#!/bin/sh\n/bin/sleep 5\n" });
    process.env.STATICSIGHT_TIMEOUT = "1";
    expect((await T("track_struct_risks", { struct_name: "Packet" })).startsWith("### ❌ CLI tool timed out")).toBe(true);
  });
});
