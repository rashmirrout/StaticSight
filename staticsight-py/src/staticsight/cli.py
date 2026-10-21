"""Command-line entry points besides the MCP server: doctor, semantic index management, search, model download."""

from __future__ import annotations

import argparse
import asyncio
import sys
from dataclasses import replace

from .config import load_config
from .core.errors import StaticSightError

USAGE = """staticsight [COMMAND]

  (no command) | stdio | sse | streamable-http   run the MCP server
  serve [--host H] [--port P]                    keep a local HTTP server running (warm indexes for `tool --server`)
  doctor                                         check engines and workspace
  index build [--full]                           build/refresh the code graph, then the semantic index (blocking)
  index refresh                                  incremental refresh of both (only changed files)
  index status                                   show code graph, semantic and GNU Global index status
  search "query" [--glob G] [--language L] [--kind K] [--top N]
  similar FILE LINE [--end N] [--top N]
  model list                                     list selectable embedding models
  model download | status [--model NAME]         fetch / verify one pinned embedding model
  tool --list                                    list the 33 tools and their parameters
  tool NAME [ARGS] [--param VALUE ...]           run one tool, print the Markdown an agent receives
  tool --server URL NAME [ARGS]                  the same, answered by a running `serve` (STATICSIGHT_SERVER)

Global option: --repo PATH selects the repository (same as WORKSPACE_ROOT). Default: the nearest folder above
the current directory that holds .staticsight/ or .git. Indexes live in <repo>/.staticsight/ (git-ignored)."""


def _progress(msg: str) -> None:
    print(f"  … {msg}", file=sys.stderr, flush=True)


def _command_model(action: str, requested: str, default: str) -> str:
    """Explicit --model wins; otherwise only `download` selects the built-in default."""
    return requested or (default if action == "download" else "")


def one_shot_semantic() -> None:
    """A command-line process exits after one answer, so a background refresh would die with it: refresh in the
    foreground instead, whatever the drift (the MCP server keeps its 200-file threshold)."""
    import os

    os.environ["STATICSIGHT_SEMANTIC_AUTO_REFRESH_FILES"] = str(10**9)


async def ensure_semantic_built() -> None:
    """First use in a terminal: build the index now, with progress, instead of answering keyword-only."""
    from .semantic.index import get_semantic_index

    cfg = load_config()
    idx = get_semantic_index(cfg)
    if not cfg.semantic_auto_refresh or (idx.exists() and idx.compatible()):
        return
    _progress("building the semantic index (first run in this repository)")
    try:
        await idx.refresh(progress=_progress)
    except StaticSightError:
        pass  # the tool itself reports what is missing (packages, model, ...)


async def _index(args) -> int:
    from .semantic.index import get_semantic_index
    from .semantic.search import status_section

    from .graph.store import get_graph

    cfg = load_config()
    idx = get_semantic_index(cfg)
    g = get_graph(cfg)
    if args.action in ("build", "refresh"):
        full = bool(getattr(args, "full", False))
        print(f"Code graph for {cfg.workspace_root}", file=sys.stderr)
        print(f"Code graph: {await g.refresh(full=full)}")
        print(f"Semantic index for {cfg.workspace_root}", file=sys.stderr)

        async def ticker():
            last = ""
            while True:
                await asyncio.sleep(2)
                note = idx.progress_note(short=True)
                if note != last and idx.state.status == "building":
                    _progress(note)
                    last = note

        t = asyncio.create_task(ticker())
        try:
            summary = await idx.refresh(full=full, progress=_progress)
        finally:
            t.cancel()
        print(summary)
        return 0
    print("\n".join(g.status_lines() + [""] + status_section(cfg)).strip())
    return 0


async def _search(args) -> int:
    from .semantic.search import semantic_search_report

    await ensure_semantic_built()
    cfg = load_config()
    print(await semantic_search_report(cfg, args.query, args.glob, args.language, args.kind, args.top))
    return 0


async def _similar(args) -> int:
    from .semantic.search import similar_code_report

    await ensure_semantic_built()
    print(await similar_code_report(load_config(), args.file, args.line, args.end, args.top))
    return 0


def _model(args) -> int:
    from .engines.embedder import download_model, missing_model_files, model_catalog, model_dir, model_id, model_spec

    base = load_config()
    if args.model:
        model_spec(args.model)  # validate the explicit selection even for `model list`
    default, models, manifest = model_catalog()
    # `model download` with no option always means the built-in default. Environment selection controls
    # indexing/search/MCP; it must not silently change what this explicit one-time download command fetches.
    selected = _command_model(args.action, args.model, default)
    cfg = replace(base, embed_model=selected, embed_model_dir="") if selected else base
    if args.action == "list":
        print(f"Available embedding models (default: {default}):")
        for name in sorted(models):
            spec = models[name]
            mark = "*" if not cfg.embed_model_dir and cfg.embed_model == name else " "
            print(f"{mark} {name} — {spec['dims']} dims, {spec['max_tokens']} tokens, {spec.get('license', 'license n/a')}")
            if spec.get("repo"):
                print(f"    {spec['repo']}@{spec['revision']}")
            print(f"    {spec['description']}")
        selected = model_id(cfg) if cfg.embed_model_dir else cfg.embed_model
        print(f"Selected: {selected}")
        if manifest:
            print(f"External manifest: {manifest}")
        print("Download default: staticsight model download")
        print("Download another: staticsight model download --model NAME")
        print("Alternatives require: set STATICSIGHT_EMBED_MODEL=NAME, then run `staticsight index build --full`.")
        return 0
    if cfg.embed_model == "test-hash" and not cfg.embed_model_dir:
        print("test-hash needs no download")
        return 0
    if args.action == "download":
        d = download_model(cfg, _progress)
        print(f"model {model_id(cfg)} ready in {d}")
        if args.model:
            print(f"To use it: set STATICSIGHT_EMBED_MODEL={args.model} and run `staticsight index build --full`.")
        return 0
    missing = missing_model_files(cfg)
    print(f"model {model_id(cfg)} in {model_dir(cfg)}: " + ("OK (verified)" if not missing else "missing " + ", ".join(missing)))
    return 0 if not missing else 1


def run_cli(argv: list[str]) -> int:
    p = argparse.ArgumentParser(prog="staticsight", usage=USAGE, add_help=True)
    sub = p.add_subparsers(dest="cmd")
    pi = sub.add_parser("index")
    pi.add_argument("action", choices=["build", "refresh", "status"])
    pi.add_argument("--full", action="store_true")
    ps = sub.add_parser("search")
    ps.add_argument("query")
    ps.add_argument("--glob", default="")
    ps.add_argument("--language", default="")
    ps.add_argument("--kind", default="")
    ps.add_argument("--top", type=int, default=10)
    psim = sub.add_parser("similar")
    psim.add_argument("file")
    psim.add_argument("line", type=int)
    psim.add_argument("--end", type=int, default=0)
    psim.add_argument("--top", type=int, default=8)
    pm = sub.add_parser("model")
    pm.add_argument("action", choices=["list", "download", "status"])
    pm.add_argument("--model", default="", help="model name from `model list` (overrides STATICSIGHT_EMBED_MODEL for this command)")
    args = p.parse_args(argv)
    one_shot_semantic()
    try:
        if args.cmd == "index":
            return asyncio.run(_index(args))
        if args.cmd == "search":
            return asyncio.run(_search(args))
        if args.cmd == "similar":
            return asyncio.run(_similar(args))
        if args.cmd == "model":
            return _model(args)
    except StaticSightError as exc:
        print(f"error: {exc.message}" + (f"\nhint: {exc.hint}" if exc.hint else ""), file=sys.stderr)
        return 1
    print(USAGE)
    return 2
