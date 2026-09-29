// Platform layer: boundary rule + Windows/POSIX behaviour (the Windows logic is testable on any OS).
import { mkdtempSync, readdirSync, readFileSync, statSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join, relative } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import { ToolTimeout } from "../src/core/errors.js";
import { decodeSource, matchesGlob, readLines } from "../src/core/paths.js";
import { parseXOutput } from "../src/engines/gnuGlobal.js";
import { current, detect, PosixPlatform, use, WindowsPlatform } from "../src/platform/index.js";

const SRC = join(dirname(fileURLToPath(import.meta.url)), "..", "src");
const FORBIDDEN = /process\.platform|node:child_process|\bspawn(Sync)?\(|process\.kill\(|os\.platform\(/g;

function walk(d: string): string[] {
  return readdirSync(d).flatMap((n) => (statSync(join(d, n)).isDirectory() ? walk(join(d, n)) : [join(d, n)]));
}

describe("platform layer", () => {
  it("keeps OS-specific code inside src/platform", () => {
    const offenders: string[] = [];
    for (const f of walk(SRC).filter((p) => p.endsWith(".ts"))) {
      const rel = relative(SRC, f).split(/[\\/]/);
      if (rel[0] === "platform") continue;
      for (const m of readFileSync(f, "utf8").matchAll(FORBIDDEN)) offenders.push(`${rel.join("/")}: ${m[0]}`);
    }
    expect(offenders).toEqual([]);
  });
  it("detects the host", () => {
    expect(detect().name).toBe(process.platform === "win32" ? "windows" : "posix");
  });
  it("normalises Windows paths and case", () => {
    const w = new WindowsPlatform();
    expect(w.toPosix("src\\net\\packet.hpp")).toBe("src/net/packet.hpp");
    expect(w.toPosix(".\\src\\a.cpp")).toBe("src/a.cpp");
    expect(w.samePath("Src/Router.CPP", "src\\router.cpp")).toBe(true);
    expect(w.fnmatch("SRC/Net/a.cpp", "src/net/*")).toBe(true);
    const p = new PosixPlatform();
    expect(p.toPosix("odd\\name.cpp")).toBe("odd\\name.cpp");
    expect(p.samePath("Src/a.cpp", "src/a.cpp")).toBe(false);
  });
  it("refuses .cmd/.bat shims on Windows", () => {
    const d = mkdtempSync(join(tmpdir(), "ss-win-"));
    writeFileSync(join(d, "rg.cmd"), "@echo off");
    writeFileSync(join(d, "ctags.exe"), "MZ");
    const old = process.env.PATH;
    process.env.PATH = d;
    try {
      const w = new WindowsPlatform();
      expect(w.findExecutable("ctags")).toBe(join(d, "ctags.exe"));
      expect(w.findExecutable("rg")).toBeNull();
    } finally {
      process.env.PATH = old;
    }
  });
  it("uses platform case rules for globs", () => {
    use(new WindowsPlatform());
    try {
      expect(matchesGlob("Src/Net/A.cpp", "src/net/*")).toBe(true);
      expect(matchesGlob("src/net/a.cpp", "src\\net\\*")).toBe(true);
    } finally {
      use(null);
    }
    use(new PosixPlatform());
    try {
      expect(matchesGlob("Src/Net/A.cpp", "src/net/*")).toBe(false);
    } finally {
      use(null);
    }
  });
  it("parses GNU Global output with backslash paths", () => {
    use(new WindowsPlatform());
    try {
      const hits = parseXOutput("process_packet      9 src\\net\\listener.cpp         int rc = f();\r\n");
      expect([hits[0].path, hits[0].line, hits[0].text.trim()]).toEqual(["src/net/listener.cpp", 9, "int rc = f();"]);
    } finally {
      use(null);
    }
  });
  it("decodes BOM and UTF-16 sources", () => {
    const d = mkdtempSync(join(tmpdir(), "ss-enc-"));
    const body = '#include "a.h"\r\nint f() { return 1; }\r\n';
    writeFileSync(join(d, "u8.cpp"), Buffer.concat([Buffer.from([0xef, 0xbb, 0xbf]), Buffer.from(body)]));
    writeFileSync(join(d, "u16.cpp"), Buffer.concat([Buffer.from([0xff, 0xfe]), Buffer.from(body, "utf16le")]));
    const be = Buffer.from(body, "utf16le");
    be.swap16();
    writeFileSync(join(d, "u16be.cpp"), Buffer.concat([Buffer.from([0xfe, 0xff]), be]));
    for (const n of ["u8.cpp", "u16.cpp", "u16be.cpp"]) expect(readLines(join(d, n))).toEqual(['#include "a.h"', "int f() { return 1; }"]);
    expect(decodeSource(Uint8Array.from([0xff, 0xfe, 0x41, 0x00]))).toBe("A");
  });
  it("kills timed-out processes", async () => {
    await expect(current().run(process.execPath, ["-e", "setTimeout(() => {}, 30000)"], { cwd: tmpdir(), timeout: 1 })).rejects.toBeInstanceOf(ToolTimeout);
  });
  it("caps output", async () => {
    const res = await current().run(process.execPath, ["-e", "process.stdout.write('x'.repeat(200000))"], { cwd: tmpdir(), timeout: 20, maxBytes: 1000 });
    expect(res.truncated).toBe(true);
    expect(res.stdout.length).toBe(1000);
  });
});

describe("doctor", () => {
  it("reports engines and exit codes", async () => {
    const { doctorReport } = await import("../src/doctor.js");
    const [ok, code] = await doctorReport();
    expect(code).toBe(0);
    expect(ok).toContain("OK   ctags");
    process.env.STATICSIGHT_DISABLE_ENGINES = "rg,global";
    try {
      const [bad, badCode] = await doctorReport();
      expect(badCode).toBe(1);
      expect(bad).toContain("FAIL rg");
      expect(bad).toContain("WARN global");
      expect(bad).toContain("fix:");
    } finally {
      delete process.env.STATICSIGHT_DISABLE_ENGINES;
    }
  });
});
