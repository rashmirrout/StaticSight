"""Code graph, finding IDs, continuation pages, edit checks, cppcheck project library and prompts (StaticSight v3)."""

import json
import re
import shutil

import pytest

from staticsight.graph.store import get_graph
from staticsight.server import TOOLS, build_server, mcp_tool, render_prompt, safe_tool

T = {fn.__name__: safe_tool(fn) for fn in TOOLS}


@pytest.fixture
async def scratch(workspace, tmp_path, monkeypatch):
    """A private copy of the fixture repository that a test may edit."""
    root = tmp_path / "repo"
    shutil.copytree(workspace, root, ignore=shutil.ignore_patterns(".staticsight"))
    monkeypatch.setenv("WORKSPACE_ROOT", str(root))
    yield root


def _edit(root, rel, old, new):
    p = root / rel
    text = p.read_text()
    assert old in text, (rel, old)
    p.write_text(text.replace(old, new, 1))


async def test_check_my_edit_finds_the_planted_problems(scratch):
    _edit(scratch, "src/net/proto.cpp", "int decode_msg(const char* in, MsgType* t) {",
          "int decode_msg(const char* in, MsgType* t, int len) {\n    uint8_t* scratch = mem::zero_copy_allocate(16);\n"
          "    if (len <= 0) {\n        return -2;\n    }\n    mem::release_buffer(scratch);")
    _edit(scratch, "src/net/proto.cpp", "    case 'A': *t = MsgType::Ack; return 0;",
          "    case 'A': *t = MsgType::Ack; return 0;\n    case 'P': *t = MsgType::Ping; return 0;")
    _edit(scratch, "src/platform/timer_posix.cpp", "int start_timer(int ms) {", "int start_timer(int ms) {\n    if (ms < 0) {\n        return -1;\n    }")
    out = await T["check_my_edit"]("HEAD")
    assert "signature `int (const char * in,MsgType * t)` → `int (const char * in,MsgType * t,int len)`" in out
    assert "Memory leak: scratch" in out  # cppcheck, thanks to the project library
    assert "leaves `scratch` (L17) unreleased" in out  # branch skeleton
    assert "`TEST(Proto,RoundTrip)` calls `decode_msg` but its file is not part of the change" in out
    assert "switch in msg_name misses Ping" in out
    assert "counterpart `start_timer` (src/platform/timer_win.cpp:3) did not" in out
    again = await T["check_my_edit"]()
    assert "Nothing changed since the last check" in again
    ids = re.findall(r"`(F[0-9a-f]{6})` `src/net/proto.cpp:\d+` switch", out)
    assert len(ids) == 1
    v = await T["verify_finding"](ids[0])
    assert "✅ Reproduced" in v and ">" in v
    _edit(scratch, "src/net/proto.cpp", '    case MsgType::Ack: return "ack";', '    case MsgType::Ack: return "ack";\n    case MsgType::Ping: return "ping";')
    v = await T["verify_finding"](ids[0])
    assert "❎ Not reproduced" in v


async def test_findings_are_stored_and_returned_as_structured_content(scratch):
    res = await mcp_tool(TOOLS[[f.__name__ for f in TOOLS].index("get_branch_skeleton")])(
        file_path="src/router.cpp", symbol="process_packet")
    assert res.structuredContent["findings"][0]["id"] == "F7a0cc5"
    assert res.structuredContent["findings"][0]["kind"] == "leak_path"
    assert "[F7a0cc5]" in res.content[0].text
    stored = json.loads((scratch / ".staticsight" / "findings.json").read_text())["findings"]
    f = next(x for x in stored if x["id"] == "F7a0cc5")
    assert f["tool"] == "get_branch_skeleton" and f["code"] == "return -2;"
    plain = await mcp_tool(TOOLS[[f.__name__ for f in TOOLS].index("get_enclosing_scope")])(file_path="src/router.cpp", target_line=13)
    assert isinstance(plain, str)


async def test_get_more_pages_through_a_truncated_list(scratch, monkeypatch):
    monkeypatch.setenv("STATICSIGHT_MAX_RESULTS", "3")
    out = await T["get_change_hotspots"]()
    token = re.search(r'get_more\("(P[0-9a-f]{6})"\)', out).group(1)
    more = await T["get_more"](token)
    assert more.startswith("### ➕ MORE FILES (")
    assert "| File | Commits |" in more  # the table header travels with the page
    assert "❌" in await T["get_more"]("Pffffff")


async def test_project_cppcheck_library_comes_from_contracts(scratch):
    out = await T["run_file_static_audit"]("src/net/proto.cpp")
    assert "Memory leak: ring" in out and "`mem::zero_copy_allocate`/`mem::release_buffer`" in out
    cfg = (scratch / ".staticsight" / "cppcheck-project.cfg").read_text()
    assert '<alloc init="false">mem::zero_copy_allocate</alloc>' in cfg and "<dealloc>mem::release_buffer</dealloc>" in cfg


async def test_graph_refreshes_after_an_edit(scratch):
    first = await T["get_impact"]("decode_msg")
    assert "TEST(Proto,RoundTrip)" in first
    (scratch / "src" / "extra.cpp").write_text('#include "net/proto.hpp"\nint use_it(const char* b) {\n'
                                               "    MsgType t;\n    return decode_msg(b, &t);\n}\n")
    out = await T["get_impact"]("decode_msg")
    assert "Code graph refreshed before answering: re-parsed 1 changed file(s)" in out
    assert "`use_it` — `src/extra.cpp:4` — result used" in out
    assert "files" in "\n".join(get_graph().status_lines())


async def test_plan_change_and_virtual_callers(scratch):
    plan = await T["plan_change"]("decode_msg", "add a length parameter")
    assert "Update 1 call site in 1 file" in plan and "Do not undo it." in plan
    callers = await T["get_upstream_callers"]("send_frame")
    assert "is virtual" in callers and "Transport::send_frame" in callers


async def test_prompts_are_registered_with_arguments():
    prompts = await build_server().list_prompts()
    assert {p.name: [a.name for a in p.arguments] for p in prompts} == {
        "review_cpp_changes": ["focus"], "investigate_hang": ["symptom"], "investigate_incident": ["log_text"],
        "plan_refactor": ["symbol", "change"], "onboard_me": ["area"]}
    spec = json.loads((__import__("staticsight.shared", fromlist=["x"]).shared_file("tool-spec.json")).read_text())
    p = next(x for x in spec["prompts"] if x["name"] == "plan_refactor")
    text = render_prompt(p, {"symbol": "decode_msg"})
    assert "The target: `decode_msg`." in text and "{change}" not in text and "The intended change" not in text


async def test_check_my_edit_defers_extra_functions_to_the_next_call(scratch):
    body = "".join(f"int extra_{i}(int v) {{\n    if (v > {i}) {{\n        return v;\n    }}\n    return {i};\n}}\n" for i in range(10))
    (scratch / "src" / "extra.cpp").write_text(body)
    first = await T["check_my_edit"]("HEAD")
    assert "more changed functions (checked in the next call)" in first
    second = await T["check_my_edit"]()
    assert "Nothing changed" not in second and "extra_9" in second


async def test_pages_are_pruned(scratch, monkeypatch):
    from staticsight.core import md

    monkeypatch.setattr(md, "MAX_PAGES", 2)
    tok = md.pages_dir.set(scratch / ".staticsight" / "pages")
    try:
        for i in range(5):
            md.truncate_list([f"item {i} {j}" for j in range(3)], 1, "things")
        assert len(list((scratch / ".staticsight" / "pages").glob("P*.json"))) == 2
    finally:
        md.pages_dir.reset(tok)


def test_serve_refuses_non_loopback_hosts(workspace):
    import subprocess
    import sys

    from .test_entry import SCRIPT

    r = subprocess.run([sys.executable, str(SCRIPT), "--repo", str(workspace), "serve", "--host", "0.0.0.0"],
                       capture_output=True, text=True, timeout=60)
    assert r.returncode == 2 and "this machine only" in r.stderr


def test_serve_ipv6_loopback_url_is_bracketed():
    from staticsight.server import _http_host

    assert _http_host("127.0.0.1") == "127.0.0.1"
    assert _http_host("localhost") == "localhost"
    assert _http_host("::1") == "[::1]"
