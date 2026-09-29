import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { Client } from "@modelcontextprotocol/sdk/client/index.js";
import { StdioClientTransport } from "@modelcontextprotocol/sdk/client/stdio.js";
import { beforeAll, describe, expect, it } from "vitest";
import { loadSpec } from "../src/server.js";
import { setupWorkspace } from "./helpers.js";

const serverJs = join(dirname(fileURLToPath(import.meta.url)), "..", "dist", "server.js");
let root = "";

describe("stdio protocol", () => {
  beforeAll(async () => {
    root = await setupWorkspace();
  });
  it("lists spec tools and answers calls", async () => {
    const transport = new StdioClientTransport({
      command: process.execPath,
      args: [serverJs],
      env: { ...(process.env as Record<string, string>), WORKSPACE_ROOT: root },
      stderr: "ignore",
    });
    const client = new Client({ name: "test", version: "0" });
    await client.connect(transport);
    try {
      const spec = loadSpec();
      const tools = (await client.listTools()).tools;
      expect(tools.map((t) => t.name)).toEqual(spec.tools.map((t) => t.name));
      for (const st of spec.tools) {
        const t = tools.find((x) => x.name === st.name)!;
        expect(t.description).toBe(st.description);
        expect(Object.keys(t.inputSchema.properties ?? {})).toEqual(st.params.map((p) => p.name));
        expect(t.annotations?.readOnlyHint).toBe((st as { annotations?: Record<string, boolean> }).annotations?.readOnlyHint ?? true);
      }
      const res: any = await client.callTool({ name: "get_enclosing_scope", arguments: { file_path: "src/router.cpp", target_line: 13 } });
      expect(res.content[0].text).toContain("ENCLOSING SCOPE: `Router::process_packet`");
      const prompt: any = await client.getPrompt({ name: "review_cpp_changes", arguments: { focus: "locking" } });
      expect(prompt.messages[0].content.text).toContain("Pay special attention to: locking.");
    } finally {
      await client.close();
    }
  });
});
