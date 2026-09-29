import { describe, expect, it } from "vitest";
import { loadSpec } from "../src/server.js";
import { helpText, listText, parseToolArgs } from "../src/toolRun.js";

const spec = loadSpec();
const tool = (n: string) => spec.tools.find((t) => t.name === n)!;

describe("tool runner arguments", () => {
  it("accepts flags, positionals, negations and --json", () => {
    const t = tool("run_file_static_audit");
    expect(parseToolArgs(t, ["a.cpp"])).toEqual({ file_path: "a.cpp" });
    expect(parseToolArgs(t, ["--file-path=a.cpp", "--only-changed-lines"])).toEqual({ file_path: "a.cpp", only_changed_lines: true });
    expect(parseToolArgs(t, ["a.cpp", "--no-only-changed-lines"]).only_changed_lines).toBe(false);
    expect(parseToolArgs(t, ["a.cpp", "--only_changed_lines=no"]).only_changed_lines).toBe(false);
    expect(parseToolArgs(t, ["--json", '{"file_path": "b.cpp", "only_changed_lines": true}'])).toEqual({ file_path: "b.cpp", only_changed_lines: true });
    const e = tool("get_enclosing_scope");
    expect(parseToolArgs(e, ["x.cpp", "+7"])).toEqual({ file_path: "x.cpp", target_line: 7 });
    expect(parseToolArgs(e, ["--target-line", "3", "y.cpp"])).toEqual({ file_path: "y.cpp", target_line: 3 });
    expect(parseToolArgs(e, ["--json", '{"file_path": "z", "target_line": 5.0}']).target_line).toBe(5);
    const bad: Array<[string[], string]> = [
      [["x.cpp", "1.5"], "expects an integer"],
      [["x.cpp"], "needs --target-line"],
      [["a", "1", "b"], "too many positional"],
      [["--nope", "1"], "unknown option --nope"],
      [["--json", "[]"], "must be a JSON object"],
      [["--json", '{"target_line": true}'], "expects an integer"],
      [["--file-path"], "needs a value"],
      [["--json", '{"file_path": true}'], "expects a string, got true"],
      [["--json", '{"target_line": 5.5}'], "got 5.5"],
      [["--json", '{"target_line": NaN}'], "not valid JSON"],
    ];
    for (const [argv, msg] of bad) expect(() => parseToolArgs(e, argv)).toThrow(msg);
  });
  it("lists every tool and documents parameters", () => {
    const text = listText(spec.tools);
    for (const t of spec.tools) expect(text).toMatch(new RegExp(`^${t.name}\\b`, "m"));
    expect(helpText(tool("get_upstream_callers"))).toContain("Positional order: symbol");
  });
});
