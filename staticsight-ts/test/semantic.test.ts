// Semantic search: chunking, classification, test embedder, incremental index, drift policy, CLI.
import { spawnSync } from "node:child_process";
import { readFileSync, unlinkSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { beforeAll, describe, expect, it } from "vitest";
import { Tag } from "../src/engines/ctags.js";
import { fnv1a32, HashEmbedder, hashTokens } from "../src/engines/embedder.js";
import { chunkFile, MAX_CHARS } from "../src/semantic/chunker.js";
import { contentSkipReason, languageOf, preSkipReason } from "../src/semantic/files.js";
import { getSemanticIndex } from "../src/semantic/index.js";
import { similarForReview } from "../src/semantic/search.js";
import { loadConfig } from "../src/config.js";
import { safeTool, TOOLS } from "../src/server.js";
import { setupWorkspace } from "./helpers.js";

const T = (name: string, args: Record<string, unknown> = {}) => safeTool(name, TOOLS[name])(args);
const serverJs = join(dirname(fileURLToPath(import.meta.url)), "..", "dist", "server.js");
let root = "";

describe("semantic units", () => {
  it("classifies languages and skips", () => {
    expect(languageOf("src/a.cpp")).toBe("cpp");
    expect(languageOf("x/CMakeLists.txt")).toBe("cmake");
    expect(languageOf("LICENSE")).toBe("text");
    expect(preSkipReason("package-lock.json", 10, 512)).toBe("generated");
    expect(preSkipReason("img/logo.PNG", 10, 512)).toBe("binary");
    expect(preSkipReason("big.cpp", 600 * 1024, 512)).toBe("too-large");
    expect(contentSkipReason(Uint8Array.from([97, 0, 98]), "a\u0000b")).toBe("binary");
    expect(contentSkipReason(Uint8Array.from([0xff, 0xfe, 65, 0]), "A")).toBe("");
    expect(contentSkipReason(Uint8Array.from([120]), "var a=1;".repeat(2000))).toBe("minified");
  });
  it("chunks structurally like the Python implementation", () => {
    const lines = ["#include <x.h>", "#define LIMIT 10", "", "// Doc for Foo", "class Foo {", "  int a;", "  int b;", "  void m() {", "    run();", "  }", "};", "", "/// adds", "int add(int x, int y) {", "  return x + y;", "}"];
    const tags = [new Tag("Foo", "class", 5, 11, "f.cpp"), new Tag("a", "member", 6, 6, "f.cpp", "Foo"), new Tag("m", "function", 8, 10, "f.cpp", "Foo", "", "()"), new Tag("add", "function", 14, 16, "f.cpp", "", "", "(int x, int y)")];
    const got = chunkFile("f.cpp", lines, "cpp", tags).map((c) => [c.startLine, c.endLine, c.kind, c.symbol]);
    expect(got).toContainEqual([1, 2, "file", ""]);
    expect(got).toContainEqual([8, 10, "function", "Foo::m"]);
    expect(got).toContainEqual([4, 7, "class", "Foo"]);
    expect(got).toContainEqual([13, 16, "function", "add"]);
    const big = ["void big() {", ...Array.from({ length: 200 }, (_, i) => `  value_${i} = compute(${i});`), "}"];
    const parts = chunkFile("b.cpp", big, "cpp", [new Tag("big", "function", 1, 202, "b.cpp")]);
    expect(parts.length).toBeGreaterThan(3);
    expect(parts.every((c) => c.text.length <= MAX_CHARS + 200)).toBe(true);
    const md = ["# T", "intro", "", "## A", "a text", "```", "# not a heading", "```", "## B", "b text"];
    expect(chunkFile("r.md", md, "markdown", null).map((c) => [c.symbol, c.startLine, c.endLine])).toEqual([["T", 1, 2], ["A", 4, 8], ["B", 9, 10]]);
  });
  it("hash embedder matches Python", async () => {
    expect(hashTokens("parseHTTPHeader my_value2")).toEqual(["parse", "http", "header", "my", "value", "2"]);
    expect(fnv1a32(Buffer.from("a"))).toBe(0xe40c292c);
    const [a, b] = await new HashEmbedder(256).embed(["retry the connection", "retry connection"]);
    let dot = 0;
    for (let i = 0; i < 256; i++) dot += a[i] * b[i];
    expect(dot).toBeGreaterThan(0.8);
  });
});

describe("semantic tools", () => {
  beforeAll(async () => {
    root = await setupWorkspace();
  });
  it("indexes every language", async () => {
    const out = await T("get_index_status");
    for (const l of ["cpp (", "markdown (1)", "python (1)", "yaml (1)"]) expect(out).toContain(l);
  });
  it("refreshes small drift before searching", async () => {
    const f = join(root, "tools", "retry.py");
    const original = readFileSync(f);
    try {
      writeFileSync(f, Buffer.concat([original, Buffer.from("\n\ndef jitter_sleep_helper(seconds):\n    return seconds * 1.1\n")]));
      const out = await T("semantic_search", { query: "jitter sleep helper" });
      expect(out).toContain("Refreshed before searching: re-indexed 1 changed file(s)");
      expect(out).toContain("jitter_sleep_helper");
    } finally {
      writeFileSync(f, original);
    }
    expect(await T("semantic_search", { query: "retry" })).toContain("Refreshed before searching");
    expect(await T("semantic_search", { query: "retry" })).toContain("Index is up to date.");
  });
  it("sends large drift to the background", async () => {
    process.env.STATICSIGHT_SEMANTIC_AUTO_REFRESH_FILES = "0";
    const f = join(root, "docs", "design.md");
    const original = readFileSync(f);
    try {
      writeFileSync(f, Buffer.concat([original, Buffer.from("\n## Metrics\nCounters are exported every minute.\n")]));
      expect(await T("semantic_search", { query: "exported counters" })).toContain("a background refresh has started");
      await getSemanticIndex().waitForBackground();
      expect(await T("semantic_search", { query: "exported counters every minute", language: "markdown" })).toContain("Metrics");
    } finally {
      delete process.env.STATICSIGHT_SEMANTIC_AUTO_REFRESH_FILES;
      writeFileSync(f, original);
      await getSemanticIndex().refresh();
    }
  });
  it("reports staleness when auto refresh is disabled, and the lock", async () => {
    process.env.STATICSIGHT_SEMANTIC_AUTO_REFRESH = "0";
    const f = join(root, "tools", "router.yaml");
    const original = readFileSync(f);
    try {
      writeFileSync(f, Buffer.concat([original, Buffer.from("  timeout_ms: 250\n")]));
      const out = await T("semantic_search", { query: "router queues" });
      expect(out).toContain("automatic refresh disabled");
      const lock = getSemanticIndex().dbPath.replace(/\.db$/, ".lock");
      writeFileSync(lock, "other");
      try {
        expect(await T("refresh_semantic_index")).toContain("Another process is refreshing");
      } finally {
        unlinkSync(lock);
      }
      expect(await T("refresh_semantic_index")).toContain("Re-indexed 1 changed file(s)");
    } finally {
      delete process.env.STATICSIGHT_SEMANTIC_AUTO_REFRESH;
      writeFileSync(f, original);
      await getSemanticIndex().refresh();
    }
  });
  it("finds similar code and review near-duplicates", async () => {
    const out = await T("find_similar_code", { file_path: "src/storage/wal.cpp", start_line: 5, top_k: 3 });
    expect(out).toContain("Source: function `wal_append`");
    expect(out).toContain("wal_replay");
    const lines = await similarForReview(loadConfig(), [["src/storage/wal.cpp", 5, "wal_append"]], 0.0, 2);
    expect(lines[0]).toMatch(/^- `wal_append` \(`src\/storage\/wal\.cpp:5`\) resembles: /);
  });
  it("CLI builds and searches", () => {
    const env = { ...process.env, WORKSPACE_ROOT: root, STATICSIGHT_SEMANTIC_AUTO_REFRESH: "0" };
    const r = spawnSync(process.execPath, [serverJs, "search", "wal replay", "--top", "1"], { env, encoding: "utf8" });
    expect(r.status).toBe(0);
    expect(r.stdout).toContain("wal_replay");
    const bad = spawnSync(process.execPath, [serverJs, "search", "x"], { env: { ...env, STATICSIGHT_EMBED_MODEL: "nope" }, encoding: "utf8" });
    expect(bad.status).toBe(1);
    expect(bad.stderr).toContain("Unknown embedding model");
  });
});

describe("per-repo data folder", () => {
  it("lives in .staticsight with a self-ignoring .gitignore, found from subfolders", async () => {
    const { findRepoRoot, loadConfig: lc, workspaceDataDir, workspaceCacheDir } = await import("../src/config.js");
    const { existsSync, readFileSync: rf } = await import("node:fs");
    expect(existsSync(join(root, ".staticsight", "semantic.db"))).toBe(true);
    expect(existsSync(join(root, ".staticsight", "GTAGS"))).toBe(true);
    expect(rf(join(root, ".staticsight", ".gitignore"), "utf8").trim().endsWith("*")).toBe(true);
    const st = spawnSync("git", ["status", "--porcelain"], { cwd: root, encoding: "utf8" });
    expect(st.stdout).not.toContain(".staticsight");
    expect(findRepoRoot(join(root, "src", "net"))).toBe(root);
    const saved = process.env.STATICSIGHT_DATA_DIR;
    try {
      process.env.STATICSIGHT_DATA_DIR = "cache";
      const cfg = lc();
      expect(workspaceDataDir(cfg)[0]).toBe(workspaceCacheDir(cfg));
    } finally {
      if (saved === undefined) delete process.env.STATICSIGHT_DATA_DIR;
      else process.env.STATICSIGHT_DATA_DIR = saved;
    }
  });
});
