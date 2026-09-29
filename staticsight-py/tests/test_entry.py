"""The plain-Python entry point (repo-root staticsight.py), --repo, and the `tool` command-line runner."""

import importlib.util
import json
import os
import re
import subprocess
import sys

from pathlib import Path

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from staticsight.server import load_spec
from staticsight.toolrun import UsageError, parse_tool_args

from .conftest import SHARED

REPO = SHARED.parent
SCRIPT = REPO / "staticsight.py"
TS_DIST = REPO / "staticsight-ts" / "dist" / "server.js"
SPEC = {t["name"]: t for t in load_spec()["tools"]}
CASES = [c for c in json.loads((SHARED / "golden" / "cases.json").read_text())
         if c["tool"] not in ("semantic_search", "find_similar_code", "refresh_semantic_index")]
GOLDEN_DIR = Path(os.environ.get("STATICSIGHT_GOLDEN_DIR") or (SHARED / "golden"))


def run(*args: str, cwd: Path | None = None, python: list[str] | None = None, timeout: int = 180):
    return subprocess.run([*(python or [sys.executable]), str(SCRIPT), *args], cwd=cwd, capture_output=True,
                          text=True, encoding="utf-8", timeout=timeout)


def _reqs(name: str) -> list[str]:
    lines = (REPO / name).read_text().splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.startswith("#") and not ln.startswith("-r")]


def test_requirement_files_match_pyproject():
    tomllib = pytest.importorskip("tomllib")
    py = tomllib.loads((REPO / "staticsight-py" / "pyproject.toml").read_text())["project"]
    assert _reqs("requirements.txt") == py["dependencies"]
    assert _reqs("requirements-semantic.txt") == py["optional-dependencies"]["semantic"]
    assert "-r requirements.txt" in (REPO / "requirements-semantic.txt").read_text()


def test_root_script_doctor_and_subfolder_discovery(workspace):
    r = run("--repo", str(workspace), "doctor")
    assert r.returncode == 0, r.stderr
    assert f"Workspace: {workspace}" in r.stdout and f"Data:      {workspace / '.staticsight'}" in r.stdout
    # no --repo, no WORKSPACE_ROOT: the repository is found from a subfolder
    env = {k: v for k, v in os.environ.items() if k != "WORKSPACE_ROOT"}
    r = subprocess.run([sys.executable, str(SCRIPT), "tool", "get_enclosing_scope", "src/router.cpp", "13"],
                       cwd=workspace / "src" / "net", env=env, capture_output=True, text=True, encoding="utf-8", timeout=120)
    assert r.returncode == 0, r.stderr
    assert "ENCLOSING SCOPE: `Router::process_packet`" in r.stdout


def test_root_script_explains_missing_mcp():
    r = run("doctor", python=[sys.executable, "-S"])  # -S: no site-packages, so `mcp` cannot be imported
    assert r.returncode == 1
    assert "missing Python package(s): mcp" in r.stderr and "staticsight.py --install" in r.stderr
    assert "requirements.txt" in r.stderr and "Traceback" not in r.stderr


def _launcher(monkeypatch, name: str, pip: bool = True):
    spec = importlib.util.spec_from_file_location(name, SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    real = importlib.util.find_spec
    monkeypatch.setattr(mod, "importlib", type("I", (), {"util": type("U", (), {
        "find_spec": staticmethod(lambda m: (object() if pip else None) if m == "pip" else real(m))})}))
    return mod


def test_install_explains_pep668(monkeypatch, capsys):
    mod = _launcher(monkeypatch, "ss_launcher")
    calls = []

    def fake_run(cmd, **_kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 1, stdout="error: externally-managed-environment\n× This environment is externally managed\n")

    monkeypatch.setattr(mod.subprocess, "run", fake_run)
    assert mod.install(["--semantic", "--yes", "--", "--no-cache-dir"]) == 1
    assert calls == [[sys.executable, "-m", "pip", "install", "-r", str(REPO / "requirements-semantic.txt"), "--no-cache-dir"]]
    err = capsys.readouterr().err
    assert "PEP 668" in err and "-m venv" in err and "--break-system-packages" in err
    assert "--install --semantic --yes" in err


def test_install_needs_confirmation_without_terminal(monkeypatch, capsys):
    mod = _launcher(monkeypatch, "ss_launcher2")
    monkeypatch.setattr(mod.sys.stdin, "isatty", lambda: False, raising=False)
    monkeypatch.setattr(mod.subprocess, "run", lambda *a, **k: pytest.fail("pip must not run unconfirmed"))
    assert mod.install([]) == 1
    assert "add --yes" in capsys.readouterr().err


def test_install_without_pip_suggests_ensurepip(monkeypatch, capsys):
    mod = _launcher(monkeypatch, "ss_launcher3", pip=False)
    assert mod.install(["--yes"]) == 1
    assert "-m ensurepip" in capsys.readouterr().err


async def test_root_script_speaks_mcp(workspace):
    params = StdioServerParameters(command=sys.executable, args=[str(SCRIPT), "--repo", str(workspace)],
                                   env={k: v for k, v in os.environ.items() if k != "WORKSPACE_ROOT"})
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            assert len((await session.list_tools()).tools) == len(SPEC)
            res = await session.call_tool("get_enclosing_scope", {"file_path": "src/router.cpp", "target_line": 13})
            assert "ENCLOSING SCOPE: `Router::process_packet`" in res.content[0].text


def test_repo_option_errors(tmp_path):
    r = run("--repo", str(tmp_path / "nope"), "doctor")
    assert r.returncode == 2 and "not a folder" in r.stderr
    r = run("doctor", "--repo")
    assert r.returncode == 2 and "--repo needs a folder" in r.stderr


# ------------------------------------------------------------------------------------------------ tool runner
def test_parse_tool_args_forms():
    t = SPEC["run_file_static_audit"]
    assert parse_tool_args(t, ["a.cpp"]) == {"file_path": "a.cpp"}
    assert parse_tool_args(t, ["--file-path=a.cpp", "--only-changed-lines"]) == {"file_path": "a.cpp", "only_changed_lines": True}
    assert parse_tool_args(t, ["a.cpp", "--no-only-changed-lines"])["only_changed_lines"] is False
    assert parse_tool_args(t, ["a.cpp", "--only_changed_lines=no"])["only_changed_lines"] is False
    assert parse_tool_args(t, ["--json", '{"file_path": "b.cpp", "only_changed_lines": true}']) == {"file_path": "b.cpp", "only_changed_lines": True}
    e = SPEC["get_enclosing_scope"]
    assert parse_tool_args(e, ["x.cpp", "+7"]) == {"file_path": "x.cpp", "target_line": 7}
    assert parse_tool_args(e, ["--target-line", "3", "y.cpp"]) == {"file_path": "y.cpp", "target_line": 3}
    assert parse_tool_args(e, ["--json", '{"file_path": "z", "target_line": 5.0}'])["target_line"] == 5
    for bad, msg in [(["x.cpp", "1.5"], "expects an integer"), (["x.cpp"], "needs --target-line"),
                     (["a", "1", "b"], "too many positional"), (["--nope", "1"], "unknown option --nope"),
                     (["--json", "[]"], "must be a JSON object"), (["--json", '{"target_line": true}'], "expects an integer"),
                     (["--file-path"], "needs a value"), (["--json", '{"file_path": true}'], "expects a string, got true"),
                     (["--json", '{"target_line": 5.5}'], "got 5.5"), (["--json", '{"target_line": NaN}'], "not valid JSON")]:
        with pytest.raises(UsageError, match=re.escape(msg)):
            parse_tool_args(e, bad)


def test_tool_list_and_help():
    r = run("tool", "--list")
    assert r.returncode == 0 and r.stdout.startswith(f"{len(SPEC)} tools, the same ones the MCP server offers.")
    for name in SPEC:
        assert re.search(rf"^{name}\b", r.stdout, re.M)
    r = run("tool", "get_upstream_callers", "--help")
    assert "--symbol TEXT" in r.stdout and "Positional order: symbol" in r.stdout
    r = run("tool", "nope")
    assert r.returncode == 2 and 'unknown tool "nope"' in r.stderr



@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_tool_runner_prints_the_mcp_output(case, workspace):
    """`tool NAME --json ARGS` prints exactly what an MCP client receives, in both implementations."""
    from staticsight.server import TOOLS, safe_tool

    expected = await {f.__name__: safe_tool(f) for f in TOOLS}[case["tool"]](**case["args"]) + "\n"
    golden = GOLDEN_DIR / f"{case['id']}.md"
    if golden.is_file() and os.environ.get("STATICSIGHT_UPDATE_GOLDEN") != "1":
        assert expected == golden.read_bytes().decode("utf-8")
    args = ["--repo", str(workspace), "tool", case["tool"], "--json", json.dumps(case["args"])]
    r = run(*args)
    assert r.stdout == expected, r.stderr
    assert r.returncode == (1 if r.stdout.startswith("### ❌") else 0)
    if TS_DIST.is_file():
        t = subprocess.run(["node", str(TS_DIST), *args], capture_output=True, text=True, encoding="utf-8", timeout=180)
        assert t.stdout == r.stdout and t.returncode == r.returncode, t.stderr


def test_benchmark_script_runs_read_only(workspace, tmp_path):
    """scripts/benchmark.py measures a repository without writing to it (indexes go to the per-user cache)."""
    out_json = tmp_path / "bench.json"
    env = {k: v for k, v in os.environ.items() if k not in ("WORKSPACE_ROOT", "STATICSIGHT_DATA_DIR")}
    r = subprocess.run([sys.executable, str(REPO / "scripts" / "benchmark.py"), "--repo", str(workspace), "--base", "origin/main",
                        "--samples", "3", "--json", str(out_json)], env=env, capture_output=True, text=True, encoding="utf-8",
                       timeout=300)
    assert r.returncode == 0, r.stderr
    assert "| Measurement | Without StaticSight | With StaticSight |" in r.stdout
    data = json.loads(out_json.read_text())
    assert data["review"]["files"] >= 1 and data["locks"]["cycles"] == 1
    assert data["locks"]["held_across_blocking"] == 1
