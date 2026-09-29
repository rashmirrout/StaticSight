import { describe, expect, it } from "vitest";
import { extractLeadingComment, stripCode } from "../src/core/cppText.js";
import { parseDiff } from "../src/engines/git.js";
import * as md from "../src/core/md.js";
import { fnmatch } from "../src/core/fnmatch.js";
import { matchesGlob } from "../src/core/paths.js";
import { classifyCall, normalizeSymbol } from "../src/tools/graphGtags.js";
import { accessKind } from "../src/tools/stateMutation.js";
import { parseCppcheckXml } from "../src/engines/cppcheck.js";

describe("core units", () => {
  it("strips comments/strings preserving columns", () => {
    const src = ["int a = 1; // if (x) return;", 'const char* s = "if (y) { return; }";', "/* start", "return; */ int b;", 'auto r = R"(if (z) return;)";', "int n = 1'000'000; char c = '{';"];
    const out = stripCode(src);
    expect(out.map((x) => x.length)).toEqual(src.map((x) => x.length));
    expect(out[0]).not.toContain("return");
    expect(out[3].trim()).toBe("int b;");
    expect(out[4]).not.toContain("return");
    expect(out[5]).not.toContain("{");
    expect(out[5]).toContain("1'000'000");
  });
  it("extracts doc comments", () => {
    const lines = ["/**", " * @brief Hi.", " * @pre x > 0", " */", "template <class T>", "int f(T x);", "", "// one", "// two", "void g();"];
    expect(extractLeadingComment(lines, 5)).toEqual(["@brief Hi.", "@pre x > 0"]);
    expect(extractLeadingComment(lines, 9)).toEqual(["one", "two"]);
    expect(extractLeadingComment(["int x; ///< the x"], 0)).toEqual(["the x"]);
  });
  it("parses diffs", () => {
    const files = parseDiff("diff --git a/a.cpp b/a.cpp\n--- a/a.cpp\n+++ b/a.cpp\n@@ -3,0 +4,2 @@\n+x\n+y\n@@ -10 +11,0 @@\n-z\n");
    expect([...files[0].addedLines]).toEqual([4, 5]);
    expect([...files[0].removedAt.entries()]).toEqual([[11, 1]]);
  });
  it("md helpers match python semantics", () => {
    expect(md.compressRanges([1, 2, 3, 7, 9, 10])).toBe("L1-3, L7, L9-10");
    expect(md.clip("🔥".repeat(200), 5)).toBe("🔥🔥🔥🔥…");
    expect(md.formatFixed0(2.5)).toBe("2");
    expect(md.formatFixed0(3.5)).toBe("4");
    const cut = md.enforceBudget("```cpp\n" + "x\n".repeat(100) + "```", 60);
    expect((cut.split("```").length - 1) % 2).toBe(0);
  });
  it("fnmatch mirrors python", () => {
    expect(fnmatch("src/net/a.cpp", "src/*")).toBe(true);
    expect(fnmatch("a.cpp", "[!b]*.cpp")).toBe(true);
    expect(matchesGlob("src/net/a.cpp", "src/net")).toBe(true);
  });
  it("classifies calls and accesses", () => {
    expect(classifyCall("    router_->process_packet(&x);", "process_packet")).toBe("⚠️ result ignored");
    expect(classifyCall("    (void)process_packet(&x);", "process_packet")).toBe("result explicitly discarded");
    expect(accessKind("++this->count;", "count")).toBe("write");
    expect(accessKind("items.push_back(x);", "items")).toBe("mutating call");
    expect(() => normalizeSymbol("-rf")).toThrow();
  });
  it("parses cppcheck xml", () => {
    const xml = `<?xml version="1.0"?><results version="2"><cppcheck version="2.18.3"/><errors>
<error id="memleak" severity="error" msg="Memory leak: b" cwe="401"><location file="src/a.cpp" line="13" column="1"/></error>
<error id="nullPointer" severity="warning" msg="Null &apos;p&apos;" cwe="476"><location file="src/b.h" line="3"/></error>
<error id="syntaxError" severity="error" msg="bad"><location file="src/a.cpp" line="2"/></error></errors></results>`;
    const [f, elsewhere, version, parseProblem] = parseCppcheckXml(xml, "src/a.cpp");
    expect(f.map((x) => x.id)).toEqual(["memleak"]);
    expect([elsewhere, version, parseProblem]).toEqual([1, "2.18.3", true]);
  });
});

describe("lock recognition", () => {
  it("matches the shared table (shared/golden/lock_events.json)", async () => {
    const { lineEvents } = await import("../src/core/locks.js");
    const { readFileSync } = await import("node:fs");
    const { fileURLToPath } = await import("node:url");
    const table = JSON.parse(
      readFileSync(fileURLToPath(new URL("../../shared/golden/lock_events.json", import.meta.url)), "utf8"),
    ) as Array<[string, unknown[]]>;
    for (const [code, want] of table) {
      expect(lineEvents(code).map((e) => [e.op, e.kind, e.mutexes, e.scoped]), code).toEqual(want);
    }
  });
  it("does not carry branch locks into sibling branches", async () => {
    const { LockWalker } = await import("../src/core/locks.js");
    const body = ["void f() {", "  if (x) {", "    a.lock();", "  } else {", "    a.lock();", "  }",
      "  { std::lock_guard<std::mutex> g(b); }", "  c.lock();", "}"];
    const seen: unknown[] = [];
    const w = new LockWalker();
    body.forEach((code, i) => w.step(code, i + 1, (e, held) => seen.push([e.mutexes, held.map((h) => h.mutexes)])));
    expect(seen).toEqual([[["a"], []], [["a"], []], [["b"], []], [["c"], []]]);
  });
});

describe("lock order helpers", () => {
  it("treats guarded acquisitions as conditional", async () => {
    const { conditional } = await import("../src/tools/lockOrder.js");
    const body = ["void Helper(bool a) {", "  if (a) AcquireSRWLockExclusive(&m_lock);", "  if (b)", "    m.lock();",
      "  AcquireSRWLockShared(&m_lock);", "}"];
    expect(conditional(body, 2, body[1].indexOf("Acquire"))).toBe(true);
    expect(conditional(body, 4, body[3].indexOf("m.lock"))).toBe(true);
    expect(conditional(body, 5, body[4].indexOf("Acquire"))).toBe(false);
  });
});
