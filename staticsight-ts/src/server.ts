#!/usr/bin/env node
// StaticSight MCP server entrypoint (TypeScript): tool registration from shared/tool-spec.json, prompt, indexer startup.
import { readFileSync, realpathSync, statSync } from "node:fs";
import { createServer } from "node:http";
import { homedir } from "node:os";
import { join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z, type ZodTypeAny } from "zod";
import { loadConfig, workspaceDataDir } from "./config.js";
import * as md from "./core/md.js";
import { StaticSightError } from "./core/errors.js";
import { probeAll } from "./engines/capabilities.js";
import { current as currentPlatform } from "./platform/index.js";
import { getIndexer } from "./indexer.js";
import { getGraph } from "./graph/store.js";
import * as findings from "./tools/findings.js";
import { get_diff_scopes } from "./tools/diffScopes.js";
import { get_symbol_contract, get_symbol_definition, get_upstream_callers } from "./tools/graphGtags.js";
import { find_entry_paths, get_call_paths, get_impact, get_lock_graph, get_type_hierarchy, query_graph } from "./tools/graphTools.js";
import { find_counterparts, find_log_origin, find_related_tests, find_switch_coverage, get_change_hotspots, get_context_pack, get_line_history } from "./tools/research.js";
import { check_my_edit, get_more, plan_change, verify_finding } from "./tools/trust.js";
import { review_changes } from "./tools/review.js";
import { find_similar_code, refresh_semantic_index, semantic_search } from "./tools/semantic.js";
import { statusSection } from "./semantic/search.js";
import { sharedFile as sharedFileImpl } from "./shared.js";
import { get_include_blast_radius, track_struct_risks } from "./tools/ripgrepMem.js";
import { track_state_mutations } from "./tools/stateMutation.js";
import { track_lock_order } from "./tools/lockOrder.js";
import { run_file_static_audit } from "./tools/staticCpp.js";
import { get_branch_skeleton, get_enclosing_scope } from "./tools/syntaxCtags.js";

export interface ParamSpec {
  name: string;
  type: "string" | "integer" | "boolean";
  required?: boolean;
  default?: unknown;
  description: string;
}
export interface ToolSpec {
  name: string;
  description: string;
  params: ParamSpec[];
  annotations?: Record<string, boolean>;
}
interface PromptSpec { name: string; description: string; file: string; args?: Array<{ name: string; description?: string; template?: string }> }
interface Spec {
  server: { name: string; instructions: string };
  tools: ToolSpec[];
  prompts: PromptSpec[];
}


export function sharedFile(name: string): string | null {
  return sharedFileImpl(name);
}

export function loadSpec(): Spec {
  const p = sharedFile("tool-spec.json");
  if (!p) throw new Error("tool-spec.json not found (run `npm run build`)");
  return JSON.parse(readFileSync(p, "utf8"));
}

export async function get_index_status(): Promise<string> {
  const cfg = loadConfig();
  const st = getIndexer(cfg).status();
  const statuses = await probeAll();
  const engines = statuses.map((e) => `\`${e.name}\` ${e.ok ? "✅" : "❌"}`).join(", ");
  const out = ["### 🗂️ INDEX STATUS", `- **Workspace:** \`${cfg.workspaceRoot}\``, `- **State:** ${st.state}`];
  if (st.detail) out.push(`- **Detail:** ${st.detail}`);
  if (st.dbPath) out.push(`- **Database:** \`${st.dbPath}\``);
  if (st.ageS !== null) out.push(`- **Age:** ${st.ageS}s (auto-refresh after ${cfg.reindexAfterS}s)`);
  out.push(`- **Engines:** ${engines}`);
  out.push(`- **Platform:** ${currentPlatform().name}`);
  for (const e of statuses) {
    if (e.ok && e.version) out.push(`  - \`${e.name}\`: ${e.version}`);
    else if (!e.ok) out.push(`  - \`${e.name}\` (${e.level}): ${e.problem}` + (e.hint ? `. 💡 ${e.hint}` : ""));
  }
  out.push(...(await statusSection(cfg)));
  out.push("", ...getGraph(cfg).statusLines());
  return out.join("\n");
}

type Handler = (args: any) => Promise<string>;

export const TOOLS: Record<string, Handler> = {
  review_changes,
  check_my_edit,
  plan_change,
  get_diff_scopes,
  get_enclosing_scope,
  get_branch_skeleton,
  get_context_pack,
  get_upstream_callers,
  get_impact,
  get_call_paths,
  find_entry_paths,
  get_symbol_definition,
  get_symbol_contract,
  get_type_hierarchy,
  query_graph,
  track_struct_risks,
  get_include_blast_radius,
  track_state_mutations,
  track_lock_order,
  get_lock_graph,
  run_file_static_audit,
  find_switch_coverage,
  find_counterparts,
  find_related_tests,
  get_line_history,
  get_change_hotspots,
  find_log_origin,
  verify_finding,
  get_more,
  semantic_search,
  find_similar_code,
  refresh_semantic_index,
  get_index_status,
};

async function callTool(name: string, fn: Handler, args: any): Promise<[string, findings.Finding[]]> {
    const cfg = loadConfig();
    const limit = name === "review_changes" ? cfg.reviewMaxChars : cfg.maxChars;
    let dataDir: string | null = null;
    try { dataDir = workspaceDataDir(cfg)[0]; } catch { dataDir = null; }
    const pages = dataDir ? join(dataDir, "pages") : null;
    const [result, found] = await findings.collect(async () => md.pagesDir.run(pages, async () => {
      try {
        return md.enforceBudget(await fn(args ?? {}), limit);
      } catch (e) {
        if (e instanceof StaticSightError) return md.errorCard(e.title, e.message, e.hint);
        if (e instanceof TypeError || e instanceof RangeError) return md.errorCard("Invalid argument", e.message);
      process.stderr.write(`[staticsight] tool ${name} failed: ${(e as Error)?.stack ?? String(e)}\n`);
      const err = e as Error;
      return md.errorCard("Internal error", `\`${name}\` failed: ${err?.name ?? "Error"}: ${err?.message ?? String(e)}`, "This is a StaticSight bug; the other tools are still usable.");
      }
    }));
    if (dataDir && found.length) findings.flush(cfg.workspaceRoot, dataDir, found, name, args ?? {});
    return [result, found];
}

/** Convert every failure into a Markdown card and enforce the output budget. */
export function safeTool(name: string, fn: Handler): Handler {
  return async (args: any) => (await callTool(name, fn, args))[0];
}

function zodFor(p: ParamSpec): ZodTypeAny {
  let t: ZodTypeAny = p.type === "string" ? z.string() : p.type === "integer" ? z.number().int() : z.boolean();
  t = t.describe(p.description);
  if (!p.required) t = t.default(p.default as never);
  return t;
}

export function buildServer(): McpServer {
  const spec = loadSpec();
  const server = new McpServer(
    { name: spec.server.name || "StaticSight", version: "0.1.0" },
    { instructions: spec.server.instructions || undefined },
  );
  for (const ts of spec.tools) {
    const fn = TOOLS[ts.name];
    if (!fn) throw new Error(`tool ${ts.name} from tool-spec.json has no implementation`);
    const shape: Record<string, ZodTypeAny> = {};
    for (const p of ts.params) shape[p.name] = zodFor(p);
    server.registerTool(
      ts.name,
      {
        description: ts.description,
        inputSchema: shape,
        annotations: { readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false, ...(ts.annotations ?? {}) },
      },
      async (args: Record<string, unknown>) => {
        const [text, found] = await callTool(ts.name, fn, args);
        const res: any = { content: [{ type: "text" as const, text }] };
        if (found.length) res.structuredContent = { findings: found.map(findings.asDict) };
        return res;
      },
    );
  }
  for (const p of spec.prompts) {
    const shape: Record<string, ZodTypeAny> = {};
    for (const a of p.args ?? []) shape[a.name] = z.string().optional().describe(a.description ?? "");
    server.registerPrompt(p.name, { description: p.description, argsSchema: shape }, (values: Record<string, string | undefined>) => {
      const f = sharedFile(p.file);
      let text = f ? readFileSync(f, "utf8") : p.description;
      for (const a of p.args ?? []) {
        const v = (values[a.name] ?? "").trim();
        text = text.replaceAll("{" + a.name + "}", v ? (a.template ?? "{value}").replaceAll("{value}", v) : "");
      }
      text = text.replace(/[ \t]+\n/g, "\n");
      return { messages: [{ role: "user" as const, content: { type: "text" as const, text } }] };
    });
  }
  return server;
}

export async function main(): Promise<void> {
  const server = buildServer();
  await server.connect(new StdioServerTransport());
  void getIndexer(loadConfig()).start(); // background: the MCP handshake must not wait for gtags
  const cfg = loadConfig();
  const g = getGraph(cfg);
  if (cfg.graphAutoRefresh && (!g.exists || g.fileCount() === 0)) g.startBackground(true);
}

export function httpHost(host: string): string {
  return host.includes(":") && !host.startsWith("[") ? `[${host}]` : host;
}

export async function serve(argv: string[]): Promise<number> {
  const hostIdx = argv.indexOf("--host"), portIdx = argv.indexOf("--port");
  const hostArg = hostIdx >= 0 && hostIdx + 1 < argv.length ? argv[hostIdx + 1] : (argv.find((a) => a.startsWith("--host="))?.slice(7) ?? "127.0.0.1");
  const portArg = portIdx >= 0 && portIdx + 1 < argv.length ? argv[portIdx + 1] : (argv.find((a) => a.startsWith("--port="))?.slice(7) ?? "8765");
  if (!["127.0.0.1", "localhost", "::1"].includes(hostArg)) {
    process.stderr.write(`error: serve listens on this machine only (127.0.0.1, localhost or ::1), not ${JSON.stringify(hostArg)}\n`);
    return 2;
  }
  const port = Number(portArg);
  const { StreamableHTTPServerTransport } = await import("@modelcontextprotocol/sdk/server/streamableHttp.js");
  // Stateless streamable HTTP: one server + transport per request (the SDK's pattern). The indexes, the code graph
  // and the embedding model are module-level, so they stay warm across requests.
  const srv = createServer((req, res) => {
    if ((req.url ?? "").split("?")[0] !== "/mcp") { res.statusCode = 404; res.end("not found"); return; }
    const mcp = buildServer();
    const transport = new StreamableHTTPServerTransport({ sessionIdGenerator: undefined });
    res.on("close", () => { void transport.close(); void mcp.close(); });
    void mcp.connect(transport).then(() => transport.handleRequest(req, res)).catch((e) => {
      process.stderr.write(`[staticsight] request failed: ${(e as Error)?.stack ?? String(e)}\n`);
      if (!res.headersSent) { res.statusCode = 500; res.end(); }
    });
  });
  const url = `http://${httpHost(hostArg)}:${port}/mcp`;
  process.stderr.write(`StaticSight serving ${loadConfig().workspaceRoot} at ${url}\n  CLI:  staticsight tool --server ${url} NAME ARGS   (or set STATICSIGHT_SERVER=${url})\n`);
  await new Promise<void>((resolveListen) => srv.listen(port, hostArg, resolveListen));
  await new Promise(() => undefined);
  return 0;
}

function isEntrypoint(): boolean {
  if (!process.argv[1]) return false;
  try {
    const self = realpathSync.native(fileURLToPath(import.meta.url));
    const invoked = realpathSync.native(process.argv[1]);
    return currentPlatform().samePath(self, invoked);
  } catch {
    return false;
  }
}

/** Strip a global `--repo PATH` / `--repo=PATH` (any position) and make it the workspace, like WORKSPACE_ROOT. */
export function applyRepoOption(argv: string[]): string[] {
  const out: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i];
    if (a === "--repo" || a.startsWith("--repo=")) {
      let val: string;
      if (a === "--repo") {
        if (i + 1 >= argv.length) {
          process.stderr.write("error: --repo needs a folder\n");
          process.exit(2);
        }
        val = argv[++i];
      } else val = a.slice("--repo=".length);
      const p = resolve(val.startsWith("~") ? join(homedir(), val.slice(1)) : val);
      let ok = false;
      try {
        ok = statSync(p).isDirectory();
      } catch {
        ok = false;
      }
      if (!ok) {
        process.stderr.write(`error: --repo ${val}: not a folder\n`);
        process.exit(2);
      }
      process.env.WORKSPACE_ROOT = p;
      continue;
    }
    out.push(a);
  }
  return out;
}

if (isEntrypoint()) process.argv.splice(2, process.argv.length, ...applyRepoOption(process.argv.slice(2)));

if (isEntrypoint() && process.argv[2] === "tool") {
  const { runToolCli } = await import("./toolRun.js");
  process.exitCode = await runToolCli(process.argv.slice(3), { tools: loadSpec().tools, handlers: TOOLS, safeTool });
} else if (isEntrypoint() && process.argv[2] === "doctor") {
  const { runDoctor } = await import("./doctor.js");
  process.exitCode = await runDoctor();
} else if (isEntrypoint() && ["index", "search", "similar", "model", "help", "--help", "-h"].includes(process.argv[2])) {
  const { runCli, USAGE } = await import("./cli.js");
  if (["help", "--help", "-h"].includes(process.argv[2])) process.stdout.write(USAGE + "\n");
  else process.exitCode = await runCli(process.argv.slice(2));
} else if (isEntrypoint() && process.argv[2] === "serve") {
  process.exitCode = await serve(process.argv.slice(3));
} else if (isEntrypoint()) {
  main().catch((e) => {
    process.stderr.write(`[staticsight] fatal: ${String(e)}\n`);
    process.exit(1);
  });
}
