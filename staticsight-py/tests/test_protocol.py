"""End-to-end MCP over stdio: spawn the server exactly like an editor would."""

import os
import sys

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from staticsight.server import load_spec


async def test_stdio_roundtrip(workspace):
    params = StdioServerParameters(
        command=sys.executable,
        args=["-m", "staticsight.server"],
        env={**os.environ, "WORKSPACE_ROOT": str(workspace)},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            init = await session.initialize()
            assert init.serverInfo.name == "StaticSight"
            tools = (await session.list_tools()).tools
            spec = load_spec()
            assert [t.name for t in tools] == [t["name"] for t in spec["tools"]]
            by_name = {t.name: t for t in tools}
            for st in spec["tools"]:
                assert by_name[st["name"]].description == st["description"]
                props = by_name[st["name"]].inputSchema.get("properties", {})
                assert list(props) == [p["name"] for p in st["params"]]
            res = await session.call_tool("get_enclosing_scope", {"file_path": "src/router.cpp", "target_line": 13})
            assert not res.isError and "ENCLOSING SCOPE: `Router::process_packet`" in res.content[0].text
            res = await session.call_tool("get_enclosing_scope", {"file_path": "/etc/passwd", "target_line": 1})
            assert "outside the workspace" in res.content[0].text
            prompts = (await session.list_prompts()).prompts
            assert [p.name for p in prompts] == ["review_cpp_changes"]
            prompt = await session.get_prompt("review_cpp_changes", {"focus": "locking"})
            assert "Pay special attention to: locking." in prompt.messages[0].content.text
