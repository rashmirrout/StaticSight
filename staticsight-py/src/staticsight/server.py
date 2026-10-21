"""StaticSight MCP server entrypoint: FastMCP instance, tool registration, prompt, and indexer startup."""

from __future__ import annotations

import functools
import inspect
import json
import logging
import os
import re
import sys
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable

from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, TextContent, ToolAnnotations

from .config import load_config, workspace_data_dir
from .core import md
from .core.errors import StaticSightError
from .engines.capabilities import probe_all
from .semantic.search import status_section
from .shared import shared_file as _shared_file
from .platform import current as current_platform
from .indexer import get_indexer
from .tools import findings
from .tools.diff_scopes import get_diff_scopes
from .tools.graph_tools import find_entry_paths, get_call_paths, get_impact, get_lock_graph, get_type_hierarchy, query_graph
from .tools.research import (find_counterparts, find_log_origin, find_related_tests, find_switch_coverage, get_change_hotspots,
                             get_context_pack, get_line_history)
from .tools.trust import check_my_edit, get_more, plan_change, verify_finding
from .tools.graph_gtags import get_symbol_contract, get_symbol_definition, get_upstream_callers
from .tools.review import review_changes
from .tools.semantic import find_similar_code, refresh_semantic_index, semantic_search
from .tools.ripgrep_mem import get_include_blast_radius, track_struct_risks
from .tools.state_mutation import track_state_mutations
from .tools.lock_order import track_lock_order
from .tools.static_cpp import run_file_static_audit
from .tools.syntax_ctags import get_branch_skeleton, get_enclosing_scope

log = logging.getLogger("staticsight")


def load_spec() -> dict[str, Any]:
    p = _shared_file("tool-spec.json")
    if p is None:
        return {"server": {"name": "StaticSight", "instructions": ""}, "tools": [], "prompts": []}
    return json.loads(p.read_text(encoding="utf-8"))


async def get_index_status() -> str:
    """Reports the state of the GNU Global symbol index, the semantic search index and the code graph (building with progress, ready, stale, not built), their locations and age, the embedding model, and which CLI engines are installed. Use when caller/definition results say they came from the ripgrep fallback, or to follow a background semantic index build."""
    cfg = load_config()
    idx = get_indexer(cfg)
    st = idx.status()
    statuses = await probe_all()
    engines = ", ".join(f"`{e.name}` {'✅' if e.ok else '❌'}" for e in statuses)
    out = [
        "### 🗂️ INDEX STATUS",
        f"- **Workspace:** `{cfg.workspace_root}`",
        f"- **State:** {st['state']}",
    ]
    if st["detail"]:
        out.append(f"- **Detail:** {st['detail']}")
    if st["db_path"]:
        out.append(f"- **Database:** `{st['db_path']}`")
    if st["age_s"] is not None:
        out.append(f"- **Age:** {st['age_s']}s (auto-refresh after {cfg.reindex_after_s}s)")
    out.append(f"- **Engines:** {engines}")
    out.append(f"- **Platform:** {current_platform().name}")
    for e in statuses:
        if e.ok and e.version:
            out.append(f"  - `{e.name}`: {e.version}")
        elif not e.ok:
            out.append(f"  - `{e.name}` ({e.level}): {e.problem}" + (f". 💡 {e.hint}" if e.hint else ""))
    out += status_section(cfg)
    from .graph.store import get_graph

    out += [""] + get_graph(cfg).status_lines()
    return "\n".join(out)


TOOLS: list[Callable[..., Awaitable[str]]] = [
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
]


async def call_tool(fn: Callable[..., Awaitable[str]], kwargs: dict[str, Any]) -> tuple[str, list[findings.Finding]]:
    """Run one tool: failures become Markdown cards, the output budget is enforced, findings and pages are stored."""
    cfg = load_config()
    limit = cfg.review_max_chars if fn.__name__ == "review_changes" else cfg.max_chars
    try:
        data_dir: Path | None = workspace_data_dir(cfg)[0]
    except Exception:  # noqa: BLE001 - a read-only or odd workspace must not break the tool
        data_dir = None
    token = findings.begin()
    page_tok = md.pages_dir.set(data_dir / "pages" if data_dir else None)
    try:
        try:
            result = md.enforce_budget(await fn(**kwargs), limit)
        except StaticSightError as exc:
            result = md.error_card(exc.title, exc.message, exc.hint)
        except (TypeError, ValueError) as exc:
            log.exception("tool %s rejected arguments", fn.__name__)
            result = md.error_card("Invalid argument", str(exc))
        except Exception as exc:  # the server must never crash because of one tool call
            log.exception("tool %s failed", fn.__name__)
            result = md.error_card("Internal error", f"`{fn.__name__}` failed: {type(exc).__name__}: {exc}",
                                   "This is a StaticSight bug; the other tools are still usable.")
    finally:
        md.pages_dir.reset(page_tok)
        found = findings.end(token)
    if data_dir is not None and found:
        findings.flush(cfg.workspace_root, data_dir, found, fn.__name__, kwargs)
    return result, found


def safe_tool(fn: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[str]]:
    """Tool wrapper returning Markdown only (CLI, tests)."""

    sig = inspect.signature(fn)

    @functools.wraps(fn)
    async def wrapper(*args: Any, **kwargs: Any) -> str:
        try:
            bound = sig.bind(*args, **kwargs).arguments
        except TypeError as exc:
            return md.error_card("Invalid argument", str(exc))
        return (await call_tool(fn, dict(bound)))[0]

    wrapper.__signature__ = inspect.signature(fn)  # type: ignore[attr-defined]
    return wrapper


def mcp_tool(fn: Callable[..., Awaitable[str]]) -> Callable[..., Awaitable[Any]]:
    """Tool wrapper for MCP: the same Markdown, plus the findings as structured content when there are any."""

    @functools.wraps(fn)
    async def wrapper(**kwargs: Any) -> Any:
        text, found = await call_tool(fn, kwargs)
        if not found:
            return text
        return CallToolResult(content=[TextContent(type="text", text=text)],
                              structuredContent={"findings": [findings.as_dict(f) for f in found]})

    wrapper.__signature__ = inspect.signature(fn)  # type: ignore[attr-defined]
    return wrapper


@asynccontextmanager
async def lifespan(_server: FastMCP) -> AsyncIterator[dict[str, Any]]:
    cfg = load_config()
    idx = get_indexer(cfg)
    idx.start()  # background: the MCP handshake must not wait for gtags
    from .graph.store import get_graph

    g = get_graph(cfg)
    if cfg.graph_auto_refresh and (not g.exists or g.file_count() == 0):
        g.start_background(full=True)  # first build of a large repository must not block the first tool call
    yield {"indexer": idx}


def render_prompt(p: dict[str, Any], values: dict[str, str]) -> str:
    """Prompt text with each `{arg}` replaced by the argument's template (or nothing when the argument is empty)."""
    f = _shared_file(p["file"])
    text = f.read_text(encoding="utf-8") if f else p.get("description", "")
    for a in p.get("args", []):
        v = (values.get(a["name"]) or "").strip()
        text = text.replace("{" + a["name"] + "}", a.get("template", "{value}").replace("{value}", v) if v else "")
    return re.sub(r"[ \t]+\n", "\n", text)


def _register_prompt(mcp: FastMCP, p: dict[str, Any]) -> None:
    from mcp.server.fastmcp.prompts.base import Prompt, PromptArgument

    async def fn(**kwargs: str) -> str:
        return render_prompt(p, kwargs)

    mcp.add_prompt(Prompt(name=p["name"], description=p["description"], fn=fn,
                          arguments=[PromptArgument(name=a["name"], description=a.get("description"), required=False)
                                     for a in p.get("args", [])]))


def build_server() -> FastMCP:
    spec = load_spec()
    mcp = FastMCP(spec["server"].get("name", "StaticSight"), instructions=spec["server"].get("instructions") or None, lifespan=lifespan)
    default_ann = {"readOnlyHint": True, "destructiveHint": False, "idempotentHint": True, "openWorldHint": False}
    per_tool = {t["name"]: t.get("annotations", {}) for t in spec.get("tools", [])}
    for fn in TOOLS:
        annotations = ToolAnnotations(**{**default_ann, **per_tool.get(fn.__name__, {})})
        mcp.tool(description=inspect.cleandoc(fn.__doc__ or ""), annotations=annotations, structured_output=False)(mcp_tool(fn))

    for p in spec.get("prompts", []):
        _register_prompt(mcp, p)
    return mcp


mcp = build_server()


def apply_repo_option(argv: list[str]) -> list[str]:
    """Strip a global `--repo PATH` / `--repo=PATH` (any position) and make it the workspace, like WORKSPACE_ROOT."""
    out: list[str] = []
    i = 0
    while i < len(argv):
        a = argv[i]
        if a == "--repo" or a.startswith("--repo="):
            if a == "--repo":
                if i + 1 >= len(argv):
                    print("error: --repo needs a folder", file=sys.stderr)
                    raise SystemExit(2)
                val, i = argv[i + 1], i + 2
            else:
                val, i = a.split("=", 1)[1], i + 1
            p = Path(val).expanduser()
            if not p.is_dir():
                print(f"error: --repo {val}: not a folder", file=sys.stderr)
                raise SystemExit(2)
            os.environ["WORKSPACE_ROOT"] = str(p.resolve())
            continue
        out.append(a)
        i += 1
    return out


def _http_host(host: str) -> str:
    """Host spelling inside a URL; IPv6 literals require brackets."""
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def serve(argv: list[str]) -> int:
    """`staticsight serve`: a long-running local server (streamable HTTP) so CLI calls reuse warm indexes."""
    import argparse

    ap = argparse.ArgumentParser(prog="staticsight serve", description="Serve StaticSight over HTTP on this machine.")
    ap.add_argument("--host", default="127.0.0.1", help="loopback interface to listen on: 127.0.0.1 (default), localhost or ::1")
    ap.add_argument("--port", type=int, default=8765, help="port (default 8765)")
    a = ap.parse_args(argv)
    if a.host not in ("127.0.0.1", "localhost", "::1"):
        # the endpoint has no authentication and reads any file in the workspace: this machine only
        print(f"error: serve listens on this machine only (127.0.0.1, localhost or ::1), not {a.host!r}", file=sys.stderr)
        return 2
    mcp.settings.host, mcp.settings.port = a.host, a.port
    url = f"http://{_http_host(a.host)}:{a.port}{mcp.settings.streamable_http_path}"
    print(f"StaticSight serving {load_config().workspace_root} at {url}\n"
          f"  CLI:  staticsight tool --server {url} NAME ARGS   (or set STATICSIGHT_SERVER={url})", file=sys.stderr, flush=True)
    mcp.run(transport="streamable-http")
    return 0


def main() -> None:
    sys.argv[1:] = apply_repo_option(sys.argv[1:])
    if len(sys.argv) > 1 and sys.argv[1] == "tool":
        from .toolrun import run_tool_cli

        raise SystemExit(run_tool_cli(sys.argv[2:]))
    if len(sys.argv) > 1 and sys.argv[1] == "doctor":
        from .doctor import run_doctor

        raise SystemExit(run_doctor())
    if len(sys.argv) > 1 and sys.argv[1] in ("index", "search", "similar", "model", "-h", "--help", "help"):
        from .cli import USAGE, run_cli

        if sys.argv[1] in ("-h", "--help", "help"):
            print(USAGE)
            raise SystemExit(0)
        raise SystemExit(run_cli(sys.argv[1:]))
    logging.basicConfig(stream=sys.stderr, level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s")
    if len(sys.argv) > 1 and sys.argv[1] == "serve":
        raise SystemExit(serve(sys.argv[2:]))
    transport = "stdio"
    if len(sys.argv) > 1 and sys.argv[1] in ("stdio", "sse", "streamable-http"):
        transport = sys.argv[1]
    mcp.run(transport=transport)  # type: ignore[arg-type]


if __name__ == "__main__":
    main()
