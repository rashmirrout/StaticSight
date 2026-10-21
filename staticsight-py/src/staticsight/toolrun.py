"""`staticsight tool …`: run any MCP tool from the command line and print the exact Markdown an agent would receive.

Arguments are validated against shared/tool-spec.json, so the command line and the MCP server share one contract.
The TypeScript twin (staticsight-ts/src/toolRun.ts) produces byte-identical help, errors and output.
"""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
from typing import Any

SEMANTIC_TOOLS = {"semantic_search", "find_similar_code", "refresh_semantic_index"}
# Tools that read the code graph: a one-shot process builds it in the foreground instead of answering from a
# half-built graph (the MCP server refreshes large drifts in the background).
GRAPH_TOOLS = {"get_impact", "get_call_paths", "find_entry_paths", "get_type_hierarchy", "query_graph", "get_lock_graph",
               "get_context_pack", "get_change_hotspots", "find_switch_coverage", "find_counterparts", "find_related_tests",
               "find_log_origin", "plan_change", "check_my_edit", "review_changes", "get_upstream_callers", "verify_finding"}


class UsageError(Exception):
    pass


def _q(v: Any) -> str:
    return json.dumps(v, ensure_ascii=False, separators=(",", ":"))


def _reject_constant(name: str) -> Any:
    raise ValueError(name)


def _from_json(p: dict[str, Any], v: Any) -> Any:
    """--json values must already have the parameter's JSON type (identical rule in toolRun.ts)."""
    kind = p["type"]
    ok = (isinstance(v, str) if kind == "string" else isinstance(v, bool) if kind == "boolean"
          else (not isinstance(v, bool) and (isinstance(v, int) or (isinstance(v, float) and v.is_integer()))))
    if not ok:
        want = {"string": "a string", "boolean": "true or false", "integer": "an integer"}[kind]
        raise UsageError(f"{_flag(p['name'])} expects {want}, got {_q(v)}")
    return int(v) if kind == "integer" else v


def _flag(name: str) -> str:
    return "--" + name.replace("_", "-")


def _meta(p: dict[str, Any]) -> str:
    return {"integer": "N", "boolean": ""}.get(p["type"], "TEXT")


def _synopsis(t: dict[str, Any]) -> str:
    parts = [t["name"]]
    for p in t["params"]:
        f = _flag(p["name"]) + (f" {_meta(p)}" if _meta(p) else "")
        parts.append(f if "default" not in p else f"[{f}]")
    return " ".join(parts)


def _first_sentence(text: str, limit: int = 110) -> str:
    s = text.split(". ", 1)[0].rstrip(".") + "."
    return s if len(s) <= limit else s[: limit - 1].rstrip() + "…"


def list_text(spec: dict[str, Any]) -> str:
    tools = spec["tools"]
    out = [f"{len(tools)} tools, the same ones the MCP server offers. Details: tool NAME --help", ""]
    for t in tools:
        out += [_synopsis(t), "    " + _first_sentence(t["description"])]
    out += ["", "Required parameters can also be given positionally, in order.",
            "Boolean parameters: --flag (true) or --no-flag (false). --json '{...}' passes raw MCP arguments."]
    return "\n".join(out)


def help_text(t: dict[str, Any]) -> str:
    out = [_synopsis(t), "", t["description"], ""]
    if not t["params"]:
        out.append("No parameters.")
    else:
        out.append("Parameters:")
        for p in t["params"]:
            left = _flag(p["name"]) + (f" {_meta(p)}" if _meta(p) else "")
            dflt = f"default {_q(p['default'])}" if "default" in p else "required"
            out.append(f"  {left:<24} ({p['type']}, {dflt}) {p.get('description', '')}".rstrip())
        req = [p["name"] for p in t["params"] if "default" not in p]
        if req:
            out += ["", "Positional order: " + " ".join(req)]
    return "\n".join(out)


def _coerce(p: dict[str, Any], raw: Any) -> Any:
    kind = p["type"]
    if kind == "integer":
        if isinstance(raw, bool):
            raise UsageError(f"{_flag(p['name'])} expects an integer, got {_q(raw)}")
        if isinstance(raw, int):
            return raw
        text = str(raw).strip()
        if not re.fullmatch(r"[+-]?[0-9]+", text):
            raise UsageError(f"{_flag(p['name'])} expects an integer, got {_q(str(raw))}")
        return int(text)
    if kind == "boolean":
        if isinstance(raw, bool):
            return raw
        v = str(raw).strip().lower()
        if v in ("1", "true", "yes", "on"):
            return True
        if v in ("0", "false", "no", "off"):
            return False
        raise UsageError(f"{_flag(p['name'])} expects true or false, got {_q(str(raw))}")
    return raw if isinstance(raw, str) else str(raw)


def parse_tool_args(t: dict[str, Any], argv: list[str]) -> dict[str, Any]:
    params = {p["name"]: p for p in t["params"]}
    given: dict[str, Any] = {}
    positional: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--json":
            if i + 1 >= len(argv):
                raise UsageError("--json needs a value")
            try:
                obj = json.loads(argv[i + 1], parse_constant=_reject_constant)
            except ValueError:
                raise UsageError("--json is not valid JSON") from None
            if not isinstance(obj, dict):
                raise UsageError("--json must be a JSON object")
            for k, v in obj.items():
                if k not in params:
                    raise UsageError(f"unknown parameter {_q(k)} for {t['name']}")
                given[k] = _from_json(params[k], v)
            i += 2
            continue
        if a.startswith("--") and len(a) > 2:
            key, eq, val = a[2:].partition("=")
            name = key.replace("-", "_")
            neg = False
            if name not in params and name.startswith("no_") and name[3:] in params and params[name[3:]]["type"] == "boolean":
                name, neg = name[3:], True
            if name not in params:
                raise UsageError(f"unknown option --{key} for {t['name']} (see: tool {t['name']} --help)")
            p = params[name]
            if p["type"] == "boolean":
                given[name] = (not neg) if not eq else _coerce(p, val) != neg
                i += 1
                continue
            if not eq:
                if i + 1 >= len(argv):
                    raise UsageError(f"{_flag(name)} needs a value")
                val = argv[i + 1]
                i += 1
            given[name] = _coerce(p, val)
            i += 1
            continue
        positional.append(a)
        i += 1
    free = [p for p in t["params"] if "default" not in p and p["name"] not in given]
    if len(positional) > len(free):
        raise UsageError(f"too many positional arguments for {t['name']}: {' '.join(positional[len(free):])}")
    for p, v in zip(free, positional):
        given[p["name"]] = _coerce(p, v)
    missing = [_flag(p["name"]) for p in t["params"] if "default" not in p and p["name"] not in given]
    if missing:
        raise UsageError(f"{t['name']} needs {', '.join(missing)} (see: tool {t['name']} --help)")
    return given


async def _prepare(name: str) -> None:
    """A one-shot process cannot rely on the server's background indexing: build/update the indexes first."""
    if name in SEMANTIC_TOOLS:
        if name != "refresh_semantic_index":
            from .cli import ensure_semantic_built

            await ensure_semantic_built()
        return
    from .config import load_config, workspace_data_dir
    from .indexer import get_indexer

    cfg = load_config()
    if not (workspace_data_dir(cfg, create=False)[0] / "GTAGS").exists():
        print("  … building the GNU Global index (first run; large repositories take a few minutes)", file=sys.stderr, flush=True)
    await get_indexer(cfg).start()
    if name in GRAPH_TOOLS:
        await ensure_graph_built(cfg)


async def ensure_graph_built(cfg) -> None:
    from .graph.store import get_graph

    g = get_graph(cfg)
    d = await g.drift()
    if d.total > cfg.graph_auto_refresh_files:
        verb = "building" if not g.exists or g.file_count() == 0 else "refreshing"
        print(f"  … {verb} the code graph ({d.total} files; large repositories take a minute)", file=sys.stderr, flush=True)
        await g.refresh()


async def _finish_background() -> None:
    """The MCP answer may say a build continues in the background; a one-shot process must not cut it short."""
    from .config import load_config
    from .semantic.index import get_semantic_index

    idx = get_semantic_index(load_config())
    if idx.building:
        print("  … waiting for the background index build to finish (Ctrl+C stops it; it resumes next time)",
              file=sys.stderr, flush=True)
        await idx.wait_for_background()


async def call_server(url: str, name: str, args: dict[str, Any]) -> str:
    """Call a tool on a running `staticsight serve` (warm indexes, no start-up cost)."""
    import logging

    from mcp import ClientSession
    from mcp.client.streamable_http import streamablehttp_client

    for noisy in ("httpx", "mcp", "httpcore"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    async with streamablehttp_client(url) as (read, write, _):
        async with ClientSession(read, write) as session:
            await session.initialize()
            res = await session.call_tool(name, args)
    return "\n".join(c.text for c in res.content if getattr(c, "type", "") == "text")


def run_tool_cli(argv: list[str]) -> int:
    import logging

    from .server import TOOLS, load_spec, safe_tool

    logging.getLogger("staticsight").setLevel(logging.WARNING)  # the Markdown on stdout is the output
    spec = load_spec()
    by_name = {t["name"]: t for t in spec["tools"]}
    server_url = os.environ.get("STATICSIGHT_SERVER", "").strip()
    if argv[:1] == ["--server"] or (argv and argv[0].startswith("--server=")):
        if argv[0] == "--server":
            if len(argv) < 2:
                print("error: --server needs a URL, e.g. http://127.0.0.1:8765/mcp", file=sys.stderr)
                return 2
            server_url, argv = argv[1], argv[2:]
        else:
            server_url, argv = argv[0].split("=", 1)[1], argv[1:]
    if not argv or argv[0] in ("--list", "-l", "list", "-h", "--help", "help"):
        print(list_text(spec))
        return 0
    name, rest = argv[0], argv[1:]
    t = by_name.get(name)
    if t is None:
        print(f"error: unknown tool {_q(name)}. Available: {', '.join(by_name)}", file=sys.stderr)
        return 2
    if any(a in ("-h", "--help") for a in rest):
        print(help_text(t))
        return 0
    try:
        args = parse_tool_args(t, rest)
    except UsageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    if server_url:
        try:
            text = asyncio.run(call_server(server_url, name, args))
        except Exception as exc:  # noqa: BLE001 - connection problems become a clear CLI error
            print(f"error: cannot reach the StaticSight server at {server_url}: {type(exc).__name__}: {exc}\n"
                  "Start it with `staticsight serve` (it keeps the indexes warm), or drop --server.", file=sys.stderr)
            return 3
        print(text)
        return 1 if text.startswith("### ❌") else 0
    fn = {f.__name__: f for f in TOOLS}[name]
    from .cli import one_shot_semantic

    one_shot_semantic()

    async def go() -> str:
        await _prepare(name)
        text = await safe_tool(fn)(**args)
        if name in SEMANTIC_TOOLS:
            await _finish_background()
        return text

    text = asyncio.run(go())
    print(text)
    return 1 if text.startswith("### ❌") else 0
