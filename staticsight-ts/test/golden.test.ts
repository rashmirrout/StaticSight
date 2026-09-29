// Byte-for-byte parity with the Python implementation's golden outputs.
import { readFileSync } from "node:fs";
import { join } from "node:path";
import { beforeAll, describe, expect, it } from "vitest";
import { safeTool, TOOLS } from "../src/server.js";
import { SHARED, setupWorkspace } from "./helpers.js";

const cases: Array<{ id: string; tool: string; args: Record<string, unknown> }> = JSON.parse(
  readFileSync(join(SHARED, "golden", "cases.json"), "utf8"),
);

// STATICSIGHT_GOLDEN_DIR: compare against goldens generated on this machine by the Python suite (CI parity mode).
const GOLDEN_DIR = process.env.STATICSIGHT_GOLDEN_DIR || join(SHARED, "golden");

describe("golden parity", () => {
  beforeAll(async () => {
    await setupWorkspace();
  });
  for (const c of cases) {
    it(c.id, async () => {
      const out = await safeTool(c.tool, TOOLS[c.tool])(c.args);
      expect(out + "\n").toBe(readFileSync(join(GOLDEN_DIR, `${c.id}.md`), "utf8"));
    });
  }
});
