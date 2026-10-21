// Code graph, finding IDs, continuation pages, edit checks, project cppcheck library, prompts and serve (twin of
// staticsight-py/tests/test_v3.py).
import { spawn, spawnSync } from "node:child_process";
import { cpSync, readFileSync, writeFileSync } from "node:fs";
import { createServer, connect } from "node:net";
import { mkdtempSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { beforeAll, describe, expect, it } from "vitest";
import { httpHost, safeTool, serve, TOOLS } from "../src/server.js";
import { setupWorkspace } from "./helpers.js";

const serverJs = join(dirname(fileURLToPath(import.meta.url)), "..", "dist", "server.js");
const T = (name: string, args: Record<string, unknown> = {}) => safeTool(name, TOOLS[name])(args);
let workspace = "";

/** A private copy of the fixture repository that a test may edit (the tools then work on the copy). */
function scratch(): string {
  const root = join(mkdtempSync(join(tmpdir(), "ss-v3-")), "repo");
  cpSync(workspace, root, { recursive: true, filter: (src) => !src.includes(".staticsight") });
  process.env.WORKSPACE_ROOT = root;
  return root;
}

function edit(root: string, rel: string, old: string, next: string): void {
  const p = join(root, rel);
  const text = readFileSync(p, "utf8");
  expect(text.includes(old)).toBe(true);
  writeFileSync(p, text.replace(old, next));
}

describe("v3: graph, findings, pages, edits", () => {
  beforeAll(async () => {
    workspace = await setupWorkspace();
  });

  it("check_my_edit finds the planted problems and verify_finding follows the fix", async () => {
    const root = scratch();
    edit(root, "src/net/proto.cpp", "int decode_msg(const char* in, MsgType* t) {",
      "int decode_msg(const char* in, MsgType* t, int len) {\n    uint8_t* scratch = mem::zero_copy_allocate(16);\n"
      + "    if (len <= 0) {\n        return -2;\n    }\n    mem::release_buffer(scratch);");
    edit(root, "src/net/proto.cpp", "    case 'A': *t = MsgType::Ack; return 0;",
      "    case 'A': *t = MsgType::Ack; return 0;\n    case 'P': *t = MsgType::Ping; return 0;");
    edit(root, "src/platform/timer_posix.cpp", "int start_timer(int ms) {", "int start_timer(int ms) {\n    if (ms < 0) {\n        return -1;\n    }");
    const out = await T("check_my_edit", { baseline: "HEAD" });
    expect(out).toContain("signature `int (const char * in,MsgType * t)` → `int (const char * in,MsgType * t,int len)`");
    expect(out).toContain("Memory leak: scratch");
    expect(out).toContain("leaves `scratch` (L17) unreleased");
    expect(out).toContain("`TEST(Proto,RoundTrip)` calls `decode_msg` but its file is not part of the change");
    expect(out).toContain("switch in msg_name misses Ping");
    expect(out).toContain("counterpart `start_timer` (src/platform/timer_win.cpp:3) did not");
    expect(await T("check_my_edit")).toContain("Nothing changed since the last check");
    const id = /`(F[0-9a-f]{6})` `src\/net\/proto.cpp:\d+` switch/.exec(out)![1];
    expect(await T("verify_finding", { finding_id: id })).toContain("✅ Reproduced");
    edit(root, "src/net/proto.cpp", '    case MsgType::Ack: return "ack";', '    case MsgType::Ack: return "ack";\n    case MsgType::Ping: return "ping";');
    expect(await T("verify_finding", { finding_id: id })).toContain("❎ Not reproduced");
  });

  it("check_my_edit defers extra functions to the next call", async () => {
    const root = scratch();
    let body = "";
    for (let i = 0; i < 10; i++) body += `int extra_${i}(int v) {\n    if (v > ${i}) {\n        return v;\n    }\n    return ${i};\n}\n`;
    writeFileSync(join(root, "src", "extra.cpp"), body);
    expect(await T("check_my_edit", { baseline: "HEAD" })).toContain("more changed functions (checked in the next call)");
    const second = await T("check_my_edit");
    expect(second).not.toContain("Nothing changed");
    expect(second).toContain("extra_9");
  });

  it("get_more pages through a truncated list with its table header", async () => {
    scratch();
    process.env.STATICSIGHT_MAX_RESULTS = "3";
    try {
      const out = await T("get_change_hotspots");
      const token = /get_more\("(P[0-9a-f]{6})"\)/.exec(out)![1];
      const more = await T("get_more", { token });
      expect(more.startsWith("### ➕ MORE FILES (")).toBe(true);
      expect(more).toContain("| File | Commits |");
      expect(await T("get_more", { token: "Pffffff" })).toContain("❌");
    } finally {
      delete process.env.STATICSIGHT_MAX_RESULTS;
    }
  });

  it("builds a cppcheck library from contract comments", async () => {
    const root = scratch();
    const out = await T("run_file_static_audit", { file_path: "src/net/proto.cpp" });
    expect(out).toContain("Memory leak: ring");
    expect(out).toContain("`mem::zero_copy_allocate`/`mem::release_buffer`");
    const cfg = readFileSync(join(root, ".staticsight", "cppcheck-project.cfg"), "utf8");
    expect(cfg).toContain('<alloc init="false">mem::zero_copy_allocate</alloc>');
  });

  it("refreshes the graph after an edit", async () => {
    const root = scratch();
    expect(await T("get_impact", { symbol: "decode_msg" })).toContain("TEST(Proto,RoundTrip)");
    writeFileSync(join(root, "src", "extra.cpp"), '#include "net/proto.hpp"\nint use_it(const char* b) {\n    MsgType t;\n    return decode_msg(b, &t);\n}\n');
    const out = await T("get_impact", { symbol: "decode_msg" });
    expect(out).toContain("Code graph refreshed before answering: re-parsed 1 changed file(s)");
    expect(out).toContain("`use_it` — `src/extra.cpp:4` — result used");
  });

  it("plans a change and notes virtual callers", async () => {
    scratch();
    const plan = await T("plan_change", { symbol: "decode_msg", change: "add a length parameter" });
    expect(plan).toContain("Update 1 call site in 1 file");
    expect(plan).toContain("Do not undo it.");
    expect(await T("get_upstream_callers", { symbol: "send_frame" })).toContain("is virtual");
  });

  it("returns findings as structured content and registers the prompts", async () => {
    const root = scratch();
    const transport = new StdioClientTransport({
      command: process.execPath, args: [serverJs],
      env: { ...(process.env as Record<string, string>), WORKSPACE_ROOT: root }, stderr: "ignore",
    });
    const client = new Client({ name: "test", version: "0" });
    await client.connect(transport);
    try {
      const res: any = await client.callTool({ name: "get_branch_skeleton", arguments: { file_path: "src/router.cpp", symbol: "process_packet" } });
      expect(res.structuredContent.findings[0]).toMatchObject({ id: "F7a0cc5", kind: "leak_path", path: "src/router.cpp", line: 13 });
      expect(res.content[0].text).toContain("[F7a0cc5]");
      const plain: any = await client.callTool({ name: "get_enclosing_scope", arguments: { file_path: "src/router.cpp", target_line: 13 } });
      expect(plain.structuredContent).toBeUndefined();
      const prompts = (await client.listPrompts()).prompts;
      expect(Object.fromEntries(prompts.map((p) => [p.name, (p.arguments ?? []).map((a) => a.name)]))).toEqual({
        review_cpp_changes: ["focus"], investigate_hang: ["symptom"], investigate_incident: ["log_text"],
        plan_refactor: ["symbol", "change"], onboard_me: ["area"],
      });
      const pr: any = await client.getPrompt({ name: "plan_refactor", arguments: { symbol: "decode_msg" } });
      const text: string = pr.messages[0].content.text;
      expect(text).toContain("The target: `decode_msg`.");
      expect(text).not.toContain("{change}");
      expect(text).not.toContain("The intended change");
    } finally {
      await client.close();
    }
    const stored = JSON.parse(readFileSync(join(root, ".staticsight", "findings.json"), "utf8")).findings;
    const f = stored.find((x: any) => x.id === "F7a0cc5");
    expect(f.tool).toBe("get_branch_skeleton");
    expect(f.code).toBe("return -2;");
  });

  it("serve refuses non-loopback hosts", async () => {
    expect(await serve(["--host", "0.0.0.0"])).toBe(2);
  });

  it("formats an IPv6 loopback URL with brackets", async () => {
    expect(httpHost("127.0.0.1")).toBe("127.0.0.1");
    expect(httpHost("localhost")).toBe("localhost");
    expect(httpHost("::1")).toBe("[::1]");
  });

  it("serve keeps indexes warm and tool --server prints what the one-shot CLI prints", async () => {
    const port: number = await new Promise((res) => { const s = createServer(); s.listen(0, "127.0.0.1", () => { const p = (s.address() as any).port; s.close(() => res(p)); }); });
    const url = `http://127.0.0.1:${port}/mcp`;
    const srv = spawn(process.execPath, [serverJs, "--repo", workspace, "serve", "--port", String(port)], { stdio: "ignore" });
    try {
      for (let i = 0; i < 200; i++) {
        const ok = await new Promise<boolean>((res) => { const c = connect(port, "127.0.0.1"); c.on("connect", () => { c.destroy(); res(true); }); c.on("error", () => res(false)); });
        if (ok) break;
        await new Promise((r) => setTimeout(r, 100));
      }
      const warm = spawnSync(process.execPath, [serverJs, "tool", "--server", url, "get_upstream_callers", "process_packet"], { encoding: "utf8" });
      const golden = readFileSync(join(dirname(fileURLToPath(import.meta.url)), "..", "..", "shared", "golden", "callers__process_packet.md"), "utf8");
      expect(warm.status).toBe(0);
      expect(warm.stdout).toBe(golden);
      const bad = spawnSync(process.execPath, [serverJs, "tool", "--server", `http://127.0.0.1:${port === 65535 ? port - 1 : port + 1}/mcp`, "get_index_status"], { encoding: "utf8" });
      expect(bad.status).toBe(3);
      expect(bad.stderr).toContain("staticsight serve");
    } finally {
      srv.kill();
    }
  }, 60000);
});
