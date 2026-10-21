// Command-line entry points besides the MCP server: semantic index management, search, model download.
import { loadConfig } from "./config.js";
import { StaticSightError } from "./core/errors.js";
import { downloadModel, missingModelFiles, modelCatalog, modelDir, modelId, modelSpec } from "./engines/embedder.js";
import { getGraph } from "./graph/store.js";
import { getSemanticIndex } from "./semantic/index.js";
import { semanticSearchReport, similarCodeReport, statusSection } from "./semantic/search.js";

export const USAGE = `staticsight-ts [COMMAND]

  (no command)                                   run the MCP server (stdio)
  serve [--host H] [--port P]                    keep a local HTTP server running (warm indexes for \`tool --server\`)
  doctor                                         check engines and workspace
  index build [--full]                           build/refresh the code graph, then the semantic index (blocking)
  index refresh                                  incremental refresh of both (only changed files)
  index status                                   show code graph and semantic index status
  search "query" [--glob G] [--language L] [--kind K] [--top N]
  similar FILE LINE [--end N] [--top N]
  model list                                     list selectable embedding models
  model download | status [--model NAME]         fetch / verify one pinned embedding model
  tool --list                                    list the 33 tools and their parameters
  tool NAME [ARGS] [--param VALUE ...]           run one tool, print the Markdown an agent receives
  tool --server URL NAME [ARGS]                  the same, answered by a running \`serve\` (STATICSIGHT_SERVER)

Global option: --repo PATH selects the repository (same as WORKSPACE_ROOT). Default: the nearest folder above
the current directory that holds .staticsight/ or .git. Indexes live in <repo>/.staticsight/ (git-ignored).`;

const progress = (m: string) => process.stderr.write(`  … ${m}\n`);

export function commandModel(action: string, requested: string, defaultName: string): string {
  return requested || (action === "download" ? defaultName : "");
}

/**
 * A command-line process exits after one answer, so a background refresh would die with it: refresh in the
 * foreground instead, whatever the drift (the MCP server keeps its 200-file threshold).
 */
export function oneShotSemantic(): void {
  process.env.STATICSIGHT_SEMANTIC_AUTO_REFRESH_FILES = String(10 ** 9);
}

/** First use in a terminal: build the index now, with progress, instead of answering keyword-only. */
export async function ensureSemanticBuilt(): Promise<void> {
  const cfg = loadConfig();
  const idx = getSemanticIndex(cfg);
  if (!cfg.semanticAutoRefresh || (idx.exists() && idx.compatible())) return;
  progress("building the semantic index (first run in this repository)");
  try {
    await idx.refresh(false, progress);
  } catch (e) {
    if (!(e instanceof StaticSightError)) throw e; // the tool itself reports what is missing
  }
}

function opt(argv: string[], name: string, dflt: string): string {
  const i = argv.indexOf(name);
  if (i >= 0 && i + 1 < argv.length) return argv[i + 1];
  const eq = argv.find((a) => a.startsWith(name + "="));
  return eq ? eq.slice(name.length + 1) : dflt;
}

function positional(argv: string[]): string[] {
  const out: string[] = [];
  for (let i = 0; i < argv.length; i++) {
    if (argv[i].startsWith("--")) {
      if (argv[i] !== "--full" && !argv[i].includes("=")) i++;
      continue;
    }
    out.push(argv[i]);
  }
  return out;
}

export async function runCli(argv: string[]): Promise<number> {
  const [cmd, ...rest] = argv;
  const pos = positional(rest);
  oneShotSemantic();
  try {
    if ((cmd === "search" && pos[0]) || (cmd === "similar" && pos[0] && pos[1])) await ensureSemanticBuilt();
    const baseCfg = loadConfig();
    const selectedModel = opt(rest, "--model", "");
    if (selectedModel) modelSpec(selectedModel); // validate the explicit selection even for `model list`
    const catalog = cmd === "model" ? modelCatalog() : null;
    // Bare `model download` always fetches the built-in default. Environment selection controls indexing/search/MCP;
    // it must not silently change what this explicit one-time download command fetches.
    const selectedForCommand = commandModel(pos[0] ?? "", selectedModel, catalog?.defaultName ?? "");
    const cfg = selectedForCommand ? { ...baseCfg, embedModel: selectedForCommand, embedModelDir: "" } : baseCfg;
    if (cmd === "index") {
      const action = pos[0];
      if (action === "build" || action === "refresh") {
        const idx = getSemanticIndex(cfg);
        const g = getGraph(cfg);
        process.stderr.write(`Semantic index for ${cfg.workspaceRoot}\n`);
        let last = "";
        const timer = setInterval(() => {
          const n = idx.progressNote(true);
          if (n !== last && idx.state.status === "building") {
            progress(n);
            last = n;
          }
        }, 2000);
        try {
          const graphSummary = await g.refresh(rest.includes("--full"));
          process.stdout.write(`Code graph: ${graphSummary}\n`);
          process.stdout.write((await idx.refresh(rest.includes("--full"), progress)) + "\n");
        } finally {
          clearInterval(timer);
        }
        return 0;
      }
      if (action === "status") {
        process.stdout.write([...getGraph(cfg).statusLines(), "", ...(await statusSection(cfg))].join("\n").trim() + "\n");
        return 0;
      }
    } else if (cmd === "search" && pos[0]) {
      process.stdout.write(
        (await semanticSearchReport(cfg, pos[0], opt(rest, "--glob", ""), opt(rest, "--language", ""), opt(rest, "--kind", ""), Number(opt(rest, "--top", "10")))) + "\n",
      );
      return 0;
    } else if (cmd === "similar" && pos[0] && pos[1]) {
      process.stdout.write((await similarCodeReport(cfg, pos[0], Number(pos[1]), Number(opt(rest, "--end", "0")), Number(opt(rest, "--top", "8")))) + "\n");
      return 0;
    } else if (cmd === "model" && ["list", "download", "status"].includes(pos[0])) {
      if (pos[0] === "list") {
        process.stdout.write(`Available embedding models (default: ${catalog!.defaultName}):\n`);
        for (const name of Object.keys(catalog!.models).sort()) {
          const spec = catalog!.models[name];
          const mark = !cfg.embedModelDir && cfg.embedModel === name ? "*" : " ";
          process.stdout.write(`${mark} ${name} — ${spec.dims} dims, ${spec.max_tokens} tokens, ${(spec as any).license ?? "license n/a"}\n`);
          if (spec.repo) process.stdout.write(`    ${spec.repo}@${spec.revision}\n`);
          process.stdout.write(`    ${spec.description}\n`);
        }
        process.stdout.write(`Selected: ${cfg.embedModelDir ? modelId(cfg) : cfg.embedModel}\n`);
        if (catalog!.manifest) process.stdout.write(`External manifest: ${catalog!.manifest}\n`);
        process.stdout.write("Download default: staticsight model download\n");
        process.stdout.write("Download another: staticsight model download --model NAME\n");
        process.stdout.write("Alternatives require: set STATICSIGHT_EMBED_MODEL=NAME, then run `staticsight index build --full`.\n");
        return 0;
      }
      if (cfg.embedModel === "test-hash" && !cfg.embedModelDir) {
        process.stdout.write("test-hash needs no download\n");
        return 0;
      }
      if (pos[0] === "download") {
        const d = await downloadModel(cfg, progress);
        process.stdout.write(`model ${modelId(cfg)} ready in ${d}\n`);
        if (selectedModel) process.stdout.write(`To use it: set STATICSIGHT_EMBED_MODEL=${selectedModel} and run \`staticsight index build --full\`.\n`);
        return 0;
      }
      const missing = await missingModelFiles(cfg);
      process.stdout.write(`model ${modelId(cfg)} in ${modelDir(cfg)}: ` + (missing.length ? "missing " + missing.join(", ") : "OK (verified)") + "\n");
      return missing.length ? 1 : 0;
    }
  } catch (e) {
    if (e instanceof StaticSightError) {
      process.stderr.write(`error: ${e.message}` + (e.hint ? `\nhint: ${e.hint}` : "") + "\n");
      return 1;
    }
    throw e;
  }
  process.stdout.write(USAGE + "\n");
  return 2;
}
