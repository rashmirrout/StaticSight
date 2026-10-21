import { createHash } from "node:crypto";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { isHeader, loadConfig, workspaceDataDir } from "../config.js";
import * as md from "../core/md.js";
import { extractLeadingComment, stripCode } from "../core/cppText.js";
import { InvalidArgument, StaticSightError } from "../core/errors.js";
import { lineEvents } from "../core/locks.js";
import { readLines, resolveInWorkspace } from "../core/paths.js";
import * as gq from "../graph/query.js";
import * as findings from "./findings.js";
import { obligations, classifyCall } from "./graphGtags.js";
import { checkSymbol, graphFor } from "./graphTools.js";
import { _PLATFORM, _history, _is_fix, counterpartNames, switchCoverageReport } from "./research.js";

const ICON: Record<string, string> = { strong: "❌", medium: "⚠️", weak: "ℹ️" };
const RANK: Record<string, number> = { strong: 0, medium: 1, weak: 2 };
const COUNTER: Record<string, string[]> = {
  leak_path: ["The resource is released by an RAII owner, a `goto cleanup`, or a callee that takes ownership.", "The allocation failed on this path (null), so there is nothing to release."],
  cppcheck: ["The path cppcheck assumed cannot happen (a precondition or earlier check rules it out).", "A macro or an unparsed header hides the code that makes it safe."],
  ignored_result: ["The function cannot fail in a way the caller must handle (check its contract).", "The result is intentionally discarded, e.g. best-effort cleanup."],
  switch_gap: ["The missing value cannot reach this switch (validated or filtered earlier).", "The `default:` branch is the intended handling for it."],
  counterpart_unchanged: ["The other platform or twin does not have the problem the change fixes.", "It is changed in a separate commit or pull request."],
  lock_cycle: ["The two orders can never run at the same time (same thread, start-up only, or an outer lock).", "The \"locks\" are different objects that only share a name."],
  lock_twice: ["The mutex is recursive, or the inner call runs on a path where the lock is not held."],
  lock_blocking: ["The call does not block in practice (non-blocking socket, zero timeout)."],
  unlocked_access: ["The access happens before other threads start or after they stop.", "A caller holds the lock (locks taken by callers are not visible to this analysis)."],
  shared_lock_write: ["The write is to thread-local or per-reader state, or it is atomic."],
  stale_caller: ["The caller already matches the new signature (default arguments or an overload)."],
};

export async function get_more(args: { token: string }): Promise<string> {
  const page = md.loadPage(args.token || "");
  if (!page) throw new InvalidArgument("Unknown or expired continuation token `" + (args.token || "").trim() + "`.", "Tokens come from the `Next: get_more(...)` note of a truncated list in this workspace.");
  const [noun, items, header] = page;
  return ["### ➕ MORE " + noun.toUpperCase() + " (" + items.length + " left)", ...header, ...md.truncateList(items, md.PAGE_SIZE, noun, "", header)].join("\n");
}

async function rerunTool(tool: string, args: Record<string, unknown>): Promise<findings.Finding[]> {
  const fn = await toolFn(tool);
  if (!fn || tool === "verify_finding" || tool === "get_more") return [];
  try { const [, found] = await findings.collect(async () => { await fn(args); return ""; }); return found; } catch (e) { if (e instanceof StaticSightError) return []; throw e; }
}

async function toolFn(name: string): Promise<((args: Record<string, unknown>) => Promise<string>) | null> {
  if (name === "get_context_pack") return (await import("./research.js")).get_context_pack as any;
  if (name === "check_my_edit") return check_my_edit as any;
  if (name === "run_file_static_audit") return (await import("./staticCpp.js")).run_file_static_audit as any;
  if (name === "get_branch_skeleton") return (await import("./syntaxCtags.js")).get_branch_skeleton as any;
  if (name === "track_lock_order") return (await import("./lockOrder.js")).track_lock_order as any;
  if (name === "track_state_mutations") return (await import("./stateMutation.js")).track_state_mutations as any;
  if (name === "find_switch_coverage") return (await import("./research.js")).find_switch_coverage as any;
  if (name === "find_counterparts") return (await import("./research.js")).find_counterparts as any;
  if (name === "get_upstream_callers") return (await import("./graphGtags.js")).get_upstream_callers as any;
  return null;
}

export async function verify_finding(args: { finding_id: string }): Promise<string> {
  const cfg = loadConfig(), fid = (args.finding_id || "").trim().replace(/`/g, "");
  if (!/^F[0-9a-f]{6}$/.test(fid)) throw new InvalidArgument("`" + fid + "` is not a finding ID.", "IDs look like `F1a2b3c` and appear next to findings.");
  const dataDir = workspaceDataDir(cfg)[0], f = findings.lookup(dataDir, fid);
  if (!f) throw new InvalidArgument("Unknown finding `" + fid + "` in this workspace.", "Findings are stored when a tool reports them; run the tool again, then verify its IDs.");
  const out = ["### 🔎 VERIFY `" + fid + "`: " + f.kind, "**Claim** (" + f.confidence + "): " + f.message, "**Where:** `" + f.path + ":" + f.line + "`" + (f.function ? " in `" + f.function + "`" : "")];
  const tool = f.tool ?? "", callArgs = { ...(f.args ?? {}) }; if (tool === "check_my_edit") callArgs.baseline = "HEAD";
  const again = await rerunTool(tool, callArgs);
  const call = "`" + tool + "(" + Object.keys(callArgs).sort().map((k) => k + "=" + JSON.stringify(callArgs[k])).join(", ") + ")`";
  if (again.length) findings.flush(cfg.workspaceRoot, dataDir, again, tool, callArgs);
  const same = again.filter((g) => g.id === fid), moved = again.filter((g) => g.id !== fid && g.kind === f.kind && g.symbol === f.symbol && g.path === f.path);
  if (same.length) out.push("**Status:** ✅ Reproduced: re-running " + call + " reports the same finding.");
  else if (moved.length) out.push("**Status:** ↪️ Still reported, but it moved: now `" + moved[0].path + ":" + moved[0].line + "` (`" + moved[0].id + "`).");
  else if (!tool || tool === "verify_finding" || tool === "get_more") out.push("**Status:** ❓ Could not re-run `" + tool + "`; judge from the code below.");
  else out.push("**Status:** ❎ Not reproduced: " + call + " no longer reports it (fixed, or the code changed).");
  let lines: string[] = [], line = Number(f.line);
  try { const [abs] = resolveInWorkspace(cfg.workspaceRoot, f.path); lines = readLines(abs); } catch { out.push("\n⚠️ `" + f.path + "` no longer exists."); }
  if (lines.length) {
    const code = f.code ?? "";
    if (code && !(line > 0 && line <= lines.length && lines[line - 1].trim() === code)) {
      const hits = lines.map((t, i) => [t.trim(), i + 1] as [string, number]).filter(([t]) => t === code).map(([, n]) => n);
      if (hits.length) { line = hits.sort((a, b) => Math.abs(a - line) - Math.abs(b - line))[0]; out.push("_The flagged line moved to L" + line + "._"); }
      else out.push("_The flagged line changed since the finding: was `" + md.clip(code, 100) + "`._");
    }
    const a = Math.max(1, line - 3), b = Math.min(lines.length, line + 3);
    out.push("", "```text", ...md.numberedCode(lines.slice(a - 1, b), a, [line]), "```");
  }
  if (COUNTER[f.kind]?.length) out.push("**Before reporting it, rule out:**", ...COUNTER[f.kind].map((c) => "- " + c));
  out.push("\n_A finding is evidence, not proof: report it with its ID and what you checked._");
  return out.join("\n");
}

const SIG_WORDS = /\b(signature|param|parameter|argument|arg|rename|remove|delete|return type|overload)/i;
export async function plan_change(args: { symbol: string; change?: string }): Promise<string> {
  const cfg = loadConfig(), sym = checkSymbol(args.symbol), change = args.change ?? "", [g, note, usable] = await graphFor(cfg), title = "### 🗺️ CHANGE PLAN: `" + sym + "`" + (change.trim() ? " (" + md.clip(change.trim(), 80) + ")" : "");
  if (!usable) return title + "\n_" + note + "_"; const db = g.db, targets = gq.functionsNamed(db, sym); if (!targets.length) return title + "\n_" + note + "_\n❓ No function named `" + sym + "` in the code graph.";
  const t0 = targets[0], signatureChange = Boolean(change && SIG_WORDS.test(change)), out = [title, "_" + note + "_"];
  let lines: string[] = []; try { lines = readLines(join(cfg.workspaceRoot, t0.path)); } catch { /* ignore */ }
  const protos = gq.allNamed(db, t0.name, ["prototype"]).filter((p) => p.qualified === t0.qualified);
  let doc: string[] = []; for (const p of [...protos, t0]) try { doc = extractLeadingComment(readLines(join(cfg.workspaceRoot, p.path)), p.line - 1); if (doc.length) break; } catch { /* ignore */ }
  const obl = obligations(doc); out.push("**Target:** `" + t0.qualified + "` (`" + t0.loc + "`) · returns `" + (t0.returnType || "?") + "`" + (t0.properties ? " · " + t0.properties : "")); if (obl.length) out.push("**Contract to keep:** " + obl.slice(0, 4).map((o) => md.clip(o, 120)).join("; "));
  const steps = ["Edit the definition: `" + t0.loc + "`" + (targets.length > 1 ? " (+" + (targets.length - 1) + " overloads/variants)" : "")];
  for (const p of protos) steps.push("Update the declaration: `" + p.loc + "`");
  const over = gq.overridesOf(db, t0).filter((o) => o.key !== t0.key); if (over.length) steps.push("Keep " + md.plural(over.length, "override") + " consistent: " + over.slice(0, 6).map((o) => "`" + o.qualified + "` (`" + o.loc + "`)").join(", "));
  const cache = new Map<string, any>(), calls = new Map<string, gq.Call>(); for (const t of targets) for (const c of gq.callersOf(db, t, cache)) calls.set(c.path + "\0" + c.line + "\0" + c.caller + "\0" + c.code, c);
  if (calls.size) { const files = new Map<string, number[]>(); for (const c of calls.values()) files.set(c.path, [...(files.get(c.path) ?? []), c.line]); const perFile = [...files.entries()].sort().map(([p, ls]) => "`" + p + "` " + md.compressRanges(ls, 6)); steps.push((signatureChange ? "Update " : "Check ") + md.plural(calls.size, "call site") + " in " + md.plural(files.size, "file") + ": " + perFile.slice(0, 8).join("; ") + (perFile.length > 8 ? "; +" + (perFile.length - 8) + " more files" : "")); }
  const pairs: gq.Fn[] = []; for (const [cand] of counterpartNames(t0.name)) pairs.push(...gq.functionsNamed(db, cand)); if (pairs.length) steps.push("Mirror the change in counterparts: " + pairs.slice(0, 6).map((f) => "`" + f.qualified + "` (`" + f.loc + "`)").join(", "));
  if (protos.some((p) => isHeader(p.path))) { const hdr = protos.find((p) => isHeader(p.path))!.path, base = hdr.split("/").pop()!, n = Number((db.prepare("SELECT COUNT(DISTINCT path) AS n FROM includes WHERE target=? OR target LIKE ?").get(base, "%/" + base) as any).n); if (n) steps.push("Expect a rebuild of `" + hdr + "` includers: " + md.plural(n, "file") + " include it directly (`get_include_blast_radius(\"" + hdr + "\")` for the full list)"); }
  const tests: gq.Fn[] = [], seen = new Set(targets.map((t) => t.key)); let frontier = targets; for (let i = 0; i < 3; i++) { const nxt = new Map<string, gq.Fn>(); for (const tgt of frontier) for (const c of gq.callersOf(db, tgt, cache)) if (!seen.has(c.callerKey)) { seen.add(c.callerKey); const fn = gq.callerFn(db, c); if (gq.isTestPath(fn.path)) tests.push(fn); else nxt.set(fn.key, fn); } frontier = [...nxt.keys()].sort().map((k) => nxt.get(k)!); }
  steps.push(tests.length ? "Run the tests that reach it: " + tests.sort((a, b) => gq.cmp(a.key, b.key)).slice(0, 6).map((t) => "`" + gq.label(t) + "` (`" + t.loc + "`)").join(", ") : "Add a test first: no test reaches it within 3 calls");
  out.push("\n**Steps**", ...steps.map((s, i) => (i + 1) + ". [ ] " + s));
  const risks: string[] = [], hist = await _history(cfg, t0.path, t0.line, t0.end, 10), fixes = hist.filter((h) => _is_fix(h[2])); if (fixes.length) risks.push(md.plural(fixes.length, "earlier fix", "es") + " touched it: " + fixes.slice(0, 3).map(([h, , s]) => "`" + h + "` " + md.clip(s, 60)).join(", ") + (fixes.length === 1 ? ". Do not undo it." : ". Do not undo them."));
  if (lines.length) { const held = new Set<string>(); for (const ln of stripCode(lines.slice(t0.line - 1, t0.end))) for (const e of lineEvents(ln)) for (const mx of e.mutexes) held.add(mx); if (held.size) risks.push("Takes " + [...held].sort().slice(0, 4).map((m) => "`" + m + "`").join(", ") + ": check `get_lock_graph` before adding calls under it."); }
  const ignored = [...calls.values()].filter((c) => classifyCall(c.code, t0.name).startsWith("⚠️")); if (ignored.length && t0.returnType && t0.returnType !== "void") risks.push((ignored.length === 1 ? "1 caller ignores" : ignored.length + " callers ignore") + " the `" + t0.returnType + "` result: new error values will go unnoticed there.");
  if (risks.length) out.push("\n**Risks**", ...risks.map((r) => "- " + r)); out.push("\n_After editing: `check_my_edit()` for a quick check, then `review_changes()` before committing._"); return out.join("\n");
}

function snapKey(r: any, s: any): string { return r.diff.path + "|" + s.tag.qualified + "|" + s.tag.signature; }
function bodyHash(lines: string[], a: number, b: number): string { return createHash("sha1").update(lines.slice(a - 1, b).join("\n")).digest("hex").slice(0, 12); }
async function collectFindings(fn: () => unknown | Promise<unknown>): Promise<findings.Finding[]> { try { const [, found] = await findings.collect(async () => { await fn(); return ""; }); return found; } catch (e) { if (e instanceof StaticSightError) return []; throw e; } }

export async function check_my_edit(args: { baseline?: string }): Promise<string> {
  const cfg = loadConfig(), baseline = (args.baseline ?? "last").trim(); if (!["last", "HEAD"].includes(baseline)) throw new InvalidArgument("`baseline` must be \"last\" (changes since the previous check) or \"HEAD\" (all uncommitted changes).");
  const { analyseDiff } = await import("./diffScopes.js"), { staticAuditReport } = await import("./staticCpp.js"), { buildSkeleton } = await import("./syntaxCtags.js");
  const ds = await analyseDiff(cfg, "HEAD"), funcs = ds.changedFunctions().filter(([r]: any) => r.diff.status !== "deleted"), title = "### 🩺 EDIT CHECK";
  if (!funcs.length) return title + "\n✅ No uncommitted changes to C/C++ functions (the working tree matches HEAD).";
  const snapPath = join(workspaceDataDir(cfg)[0], "edit_snapshot.json"); let snap: Record<string, string> = {}; try { if (baseline === "last" && existsSync(snapPath)) snap = JSON.parse(readFileSync(snapPath, "utf8")); } catch { snap = {}; }
  const texts = new Map<string, string[]>(), current: Record<string, string> = {}; for (const [r, s] of funcs as any[]) { if (!texts.has(r.diff.path)) try { texts.set(r.diff.path, readLines(join(cfg.workspaceRoot, r.diff.path))); } catch { texts.set(r.diff.path, []); } current[snapKey(r, s)] = bodyHash(texts.get(r.diff.path)!, s.tag.line, s.tag.end); }
  const picked = (funcs as any[]).filter(([r, s]) => current[snapKey(r, s)] !== snap[snapKey(r, s)]), shown = picked.slice(0, 8), saved: Record<string, string> = { ...current }; for (const [r, s] of picked.slice(8)) if (snap[snapKey(r, s)]) saved[snapKey(r, s)] = snap[snapKey(r, s)]; else delete saved[snapKey(r, s)];
  try { writeFileSync(snapPath, JSON.stringify(saved, null, 0), "utf8"); } catch { /* ignore */ }
  if (!picked.length) return title + "\n✅ Nothing changed since the last check (" + md.plural(funcs.length, "function") + " still differ from HEAD; pass `baseline=\"HEAD\"` to check them all again).";
  const out = [title + ": " + md.plural(picked.length, "changed function") + (baseline === "last" && Object.keys(snap).length ? " since the last check" : " vs HEAD")], found: findings.Finding[] = [], [g, , usable] = await graphFor(cfg), db = usable ? g.db : null, diffFiles = new Set(ds.reports.map((r: any) => r.diff.path)), changedKeys = new Set((funcs as any[]).map(([r, s]) => r.diff.path + "\0" + s.tag.qualified));
  for (const [r, s] of shown) {
    const rel = r.diff.path, t = s.tag, flags = []; if (s.isNew) flags.push("new"); if (s.signatureChanged) flags.push("signature `" + s.signatureChanged.split(" -> ")[0] + "` → `" + s.signatureChanged.split(" -> ").pop() + "`");
    out.push("- `" + t.qualified + "` (`" + rel + ":" + t.line + "`)" + (flags.length ? ": " + flags.join("; ") : ""));
    const lines = texts.get(rel) ?? []; if (lines.length && !isHeader(rel)) found.push(...await collectFindings(() => buildSkeleton(lines, t.line, Math.min(t.end, lines.length), t.qualified, rel, s.lines)));
    if (db && s.signatureChanged && !s.isNew) { const cache = new Map<string, any>(); for (const fn of gq.functionsNamed(db, t.qualified)) for (const c of gq.callersOf(db, fn, cache)) if (!diffFiles.has(c.path)) found.push(findings.make("stale_caller", "strong", c.path, c.line, t.qualified, "`" + gq.callerLabel(db, c) + "` calls `" + t.qualified + "` but its file is not part of the change, so it still uses the old signature", gq.callerLabel(db, c))); }
    if (db) for (const f of gq.functionsNamed(db, t.qualified)) if (!changedKeys.has(f.path + "\0" + f.qualified) && f.path !== rel && (_PLATFORM.test(f.path) || _PLATFORM.test(rel))) found.push(findings.make("counterpart_unchanged", "medium", f.path, f.line, f.qualified, "`" + t.qualified + "` (" + rel + ":" + t.line + ") changed but its counterpart `" + f.qualified + "` (" + f.loc + ") did not", f.qualified));
  }
  if (picked.length > shown.length) out.push("- _…and " + (picked.length - shown.length) + " more changed functions (checked in the next call)._");
  for (const rel of [...new Set(shown.map(([r]) => r.diff.path).filter((p) => !isHeader(p)))]) found.push(...(await collectFindings(() => staticAuditReport(cfg, rel, true, "HEAD"))).filter((f) => f.kind === "cppcheck"));
  const enums = new Set<string>(); if (db) { for (const [r, s] of shown) for (const ln of s.lines) for (const m of ((texts.get(r.diff.path) ?? [])[ln - 1] ?? "").matchAll(/\b(\w+)::\w+/g)) if (db.prepare("SELECT 1 FROM defs WHERE name=? AND kind='enum' LIMIT 1").get(m[1])) enums.add(m[1]); for (const [, s] of ds.changedTypes() as any[]) if (s.tag.kind === "enum") enums.add(s.tag.name); }
  for (const e of [...enums].sort()) found.push(...await collectFindings(() => switchCoverageReport(cfg, e)));
  const uniq = new Map<string, findings.Finding>(); for (const f of found) uniq.set(f.id, f); for (const f of uniq.values()) findings.add(f); const items = [...uniq.values()].sort((a, b) => RANK[a.confidence] - RANK[b.confidence] || (gq.cmp(a.path, b.path) || a.line - b.line || gq.cmp(a.id, b.id)));
  if (items.length) out.push("\n**" + md.plural(items.length, "finding") + "**", ...md.truncateList(items.map((f) => "- " + ICON[f.confidence] + " `" + f.id + "` `" + f.path + ":" + f.line + "` " + f.message), cfg.maxResults, "findings"));
  else out.push("\n✅ The quick checks found nothing: exit paths release what they allocate, cppcheck is clean on the changed lines, callers match changed signatures, switches cover changed enums, platform twins agree.");
  out.push("\n_Checks: exit-path leaks, cppcheck on changed lines, callers of changed signatures outside the diff, switch coverage of enums used in the change, unchanged platform twins. Next: `verify_finding(\"F…\")`, then `review_changes()` before committing._"); return out.join("\n");
}
