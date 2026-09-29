"""Missing CLI tools, timeouts and hostile input must yield helpful Markdown, never exceptions."""

import os
import shutil
import stat
import sys

import pytest

from staticsight.engines import ctags
from staticsight.indexer import get_indexer, reset_indexers
from staticsight.server import TOOLS, safe_tool

T = {fn.__name__: safe_tool(fn) for fn in TOOLS}


@pytest.fixture
async def limited_path(workspace, tmp_path):
    """PATH containing only the given tools (symlinked); restores PATH and the index afterwards."""
    old_path = os.environ["PATH"]
    old_timeout = os.environ.get("STATICSIGHT_TIMEOUT")

    def make(*tools: str, fake: dict[str, str] | None = None) -> None:
        bindir = tmp_path / "bin"
        bindir.mkdir(exist_ok=True)
        for t in tools:
            real = shutil.which(t, path=old_path)
            assert real, t
            (bindir / t).symlink_to(real)
        for name, script in (fake or {}).items():
            p = bindir / name
            p.write_text(script)
            p.chmod(p.stat().st_mode | stat.S_IEXEC)
        os.environ["PATH"] = str(bindir)
        reset_indexers()
        ctags.clear_cache()

    yield make
    os.environ["PATH"] = old_path
    if old_timeout is None:
        os.environ.pop("STATICSIGHT_TIMEOUT", None)
    else:
        os.environ["STATICSIGHT_TIMEOUT"] = old_timeout
    reset_indexers()
    ctags.clear_cache()
    await get_indexer().start()
    assert get_indexer().state == "ready"


@pytest.fixture
async def disable(workspace):
    """Force engines 'missing' through STATICSIGHT_DISABLE_ENGINES (portable: works the same on Windows)."""

    def make(*tools: str) -> None:
        os.environ["STATICSIGHT_DISABLE_ENGINES"] = ",".join(tools)
        reset_indexers()
        ctags.clear_cache()

    yield make
    os.environ.pop("STATICSIGHT_DISABLE_ENGINES", None)
    os.environ.pop("STATICSIGHT_TIMEOUT", None)
    reset_indexers()
    ctags.clear_cache()
    await get_indexer().start()
    assert get_indexer().state == "ready"


@pytest.mark.skipif(sys.platform == "win32", reason="PATH symlink farm is POSIX-only; covered by `disable` tests")
async def test_real_path_lookup_without_global(limited_path):
    limited_path("git", "rg", "ctags")
    out = await T["get_upstream_callers"]("process_packet")
    assert "ripgrep fallback" in out


async def test_callers_fall_back_to_ripgrep_without_global(disable):
    disable("global", "gtags")
    out = await T["get_upstream_callers"]("process_packet")
    assert "ripgrep fallback" in out
    assert "L17 in `Listener::dispatch_batch` — ⚠️ result ignored" in out
    assert "router.hpp" not in out
    status = await T["get_index_status"]()
    assert "unavailable" in status and "`global` ❌" in status


async def test_definition_fallback_without_global(disable):
    disable("global", "gtags")
    out = await T["get_symbol_definition"]("Packet")
    assert "`src/net/packet.hpp:4-10` — struct `Packet`" in out and "ripgrep fallback" in out


async def test_missing_cppcheck_is_reported(disable):
    disable("cppcheck")
    out = await T["run_file_static_audit"]("src/router.cpp")
    assert out.startswith("### ❌ Required CLI tool is not installed") and "cppcheck" in out and "💡" in out


async def test_missing_ctags_is_reported(disable):
    disable("ctags")
    out = await T["get_enclosing_scope"]("src/router.cpp", 13)
    assert "`ctags` was not found on PATH" in out and "Universal Ctags" in out


async def test_missing_git_is_reported(disable):
    disable("git")
    out = await T["get_diff_scopes"]()
    assert "`git` was not found on PATH" in out
    # skeleton still works without git (diff markers are best-effort)
    assert "BRANCH SKELETON" in await T["get_branch_skeleton"]("src/router.cpp", symbol="process_packet")


@pytest.mark.skipif(sys.platform == "win32", reason="fake shell-script engine is POSIX-only; see test_platform timeout test")
async def test_subprocess_timeout(limited_path):
    limited_path("git", "ctags", fake={"rg": "#!/bin/sh\n/bin/sleep 5\n"})
    os.environ["STATICSIGHT_TIMEOUT"] = "1"
    out = await T["track_struct_risks"]("Packet")
    assert out.startswith("### ❌ CLI tool timed out") and "STATICSIGHT_TIMEOUT" in out


async def test_deleted_file_after_indexing(workspace):
    victim = workspace / "src" / "metrics.cpp"
    backup = victim.read_bytes()
    victim.unlink()
    try:
        out = await T["get_enclosing_scope"]("src/metrics.cpp", 1)
        assert "does not exist" in out
        assert "BLAST RADIUS" in await T["get_include_blast_radius"]("include_chain.hpp")
    finally:
        victim.write_bytes(backup)


async def test_symlink_escape_rejected(workspace, tmp_path):
    outside = tmp_path / "secret.cpp"
    outside.write_text("int secret() { return 1; }\n")
    link = workspace / "src" / "link.cpp"
    try:
        link.symlink_to(outside)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks not permitted on this system")
    try:
        out = await T["get_enclosing_scope"]("src/link.cpp", 1)
        assert "outside the workspace" in out
    finally:
        link.unlink()


async def test_exuberant_ctags_is_explained(workspace, tmp_path):
    """A ctags without JSON support (e.g. `scoop install ctags` = Exuberant 5.8) gets a precise fix hint."""
    from staticsight.engines import capabilities
    from staticsight.platform import current

    fake_status = capabilities.EngineStatus("ctags", "required", path="/fake/ctags", version="Exuberant Ctags 5.8",
                                            ok=False, problem="`Exuberant Ctags 5.8` has no JSON output",
                                            hint=capabilities.EXUBERANT_HINT)
    exe = current().find_executable("ctags")
    capabilities._cache[("ctags", exe)] = fake_status
    ctags.clear_cache()
    try:
        out = await T["get_enclosing_scope"]("src/router.cpp", 13)
        assert "has no JSON output" in out and "universal-ctags" in out
    finally:
        capabilities.clear_cache()
