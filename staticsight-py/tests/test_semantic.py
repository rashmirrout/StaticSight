"""Semantic search: chunking, classification, test embedder, incremental index, drift policy, CLI, cross-impl DB."""

import asyncio
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from staticsight.engines.ctags import Tag
from staticsight.engines.embedder import HashEmbedder, fnv1a32, hash_tokens
from staticsight.semantic.chunker import MAX_CHARS, chunk_file
from staticsight.semantic.files import content_skip_reason, language_of, pre_skip_reason
from staticsight.semantic.index import get_semantic_index, reset_semantic_indexes
from staticsight.server import TOOLS, safe_tool

T = {fn.__name__: safe_tool(fn) for fn in TOOLS}
TS_DIST = Path(__file__).resolve().parents[2] / "staticsight-ts" / "dist" / "server.js"


# ------------------------------------------------------------------------------------------ units
def test_language_and_skip_rules():
    assert language_of("src/a.cpp") == "cpp" and language_of("x/CMakeLists.txt") == "cmake"
    assert language_of("docs/README.md") == "markdown" and language_of("LICENSE") == "text"
    assert pre_skip_reason("package-lock.json", 10, 512) == "generated"
    assert pre_skip_reason("img/logo.PNG", 10, 512) == "binary"
    assert pre_skip_reason("big.cpp", 600 * 1024, 512) == "too-large"
    assert content_skip_reason(b"ab\x00cd", "ab\x00cd") == "binary"
    assert content_skip_reason(b"\xff\xfeA\x00", "A") == ""  # UTF-16 is text, not binary
    assert content_skip_reason(b"x", "var a=1;" * 2000) == "minified"


def test_structural_chunks_functions_members_and_gaps():
    lines = [
        "#include <x.h>", "#define LIMIT 10", "",
        "// Doc for Foo", "class Foo {", "  int a;", "  int b;", "  void m() {", "    run();", "  }", "};", "",
        "/// adds", "int add(int x, int y) {", "  return x + y;", "}",
    ]
    tags = [Tag("Foo", "class", 5, 11, "f.cpp"), Tag("a", "member", 6, 6, "f.cpp", scope="Foo"),
            Tag("m", "function", 8, 10, "f.cpp", scope="Foo", signature="()"),
            Tag("add", "function", 14, 16, "f.cpp", signature="(int x, int y)")]
    chunks = chunk_file("f.cpp", lines, "cpp", tags)
    got = [(c.start_line, c.end_line, c.kind, c.symbol) for c in chunks]
    assert (1, 2, "file", "") in got                      # includes/defines outside any unit
    assert (8, 10, "function", "Foo::m") in got          # innermost unit
    assert (4, 7, "class", "Foo") in got                 # container gap (doc + members a, b; m excluded)
    assert (13, 16, "function", "add") in got            # leading doc comment attached
    cls = next(c for c in chunks if c.kind == "class")
    assert "run();" not in cls.text and "int a;" in cls.text
    assert chunks[0].text.startswith("f.cpp | file")
    assert next(c for c in chunks if c.symbol == "add").text.startswith("f.cpp | function add | (int x, int y)")


def test_long_units_are_windowed_and_markdown_sections():
    body = [f"  value_{i} = compute({i});" for i in range(200)]
    lines = ["void big() {", *body, "}"]
    chunks = chunk_file("b.cpp", lines, "cpp", [Tag("big", "function", 1, 202, "b.cpp")])
    assert len(chunks) > 3 and all(len(c.text) <= MAX_CHARS + 200 for c in chunks)
    assert [c.part for c in chunks] == list(range(len(chunks)))
    assert chunks[1].start_line <= chunks[0].end_line  # overlap
    md = ["# T", "intro", "", "## A", "a text", "```", "# not a heading", "```", "## B", "b text"]
    secs = [(c.symbol, c.start_line, c.end_line) for c in chunk_file("r.md", md, "markdown", None)]
    assert secs == [("T", 1, 2), ("A", 4, 8), ("B", 9, 10)]


def test_hash_embedder_is_deterministic():
    assert hash_tokens("parseHTTPHeader my_value2") == ["parse", "http", "header", "my", "value", "2"]
    assert fnv1a32(b"a") == 0xE40C292C
    e = HashEmbedder(256)
    v = e.embed(["retry the connection", "retry connection"])
    assert abs(float((v[0] * v[0]).sum()) - 1.0) < 1e-6 and float(v[0] @ v[1]) > 0.8


# ---------------------------------------------------------------------------------------- tools
async def test_index_covers_all_languages(workspace):
    out = await T["get_index_status"]()
    assert "### 🧠 SEMANTIC INDEX" in out and "State:** ready" in out
    for lang in ("cpp (", "markdown (1)", "python (1)", "yaml (1)"):
        assert lang in out, lang


async def test_search_finds_code_docs_and_scripts(workspace):
    out = await T["semantic_search"]("retry transient network failures with exponential backoff", top_k=5)
    assert "tools/retry.py" in out and "docs/design.md" in out
    assert "Index is up to date." in out
    cpp_only = await T["semantic_search"]("retry with backoff", language="cpp", top_k=3)
    assert "tools/retry.py" not in cpp_only


async def test_drift_refreshes_before_search(workspace):
    f = workspace / "tools" / "retry.py"
    original = f.read_bytes()
    try:
        f.write_bytes(original + b"\n\ndef jitter_sleep_helper(seconds):\n    return seconds * 1.1\n")
        out = await T["semantic_search"]("jitter sleep helper")
        assert "Refreshed before searching: re-indexed 1 changed file(s)" in out
        assert "jitter_sleep_helper" in out
    finally:
        f.write_bytes(original)
    out = await T["semantic_search"]("jitter sleep helper")
    assert "Refreshed before searching: re-indexed 1 changed file(s)" in out and "jitter_sleep_helper" not in out
    touched = await T["semantic_search"]("retry")  # restored content -> up to date
    assert "Index is up to date." in touched


async def test_large_drift_goes_to_background(workspace):
    os.environ["STATICSIGHT_SEMANTIC_AUTO_REFRESH_FILES"] = "0"
    f = workspace / "docs" / "design.md"
    original = f.read_bytes()
    try:
        f.write_bytes(original + b"\n## Metrics\nCounters are exported every minute.\n")
        out = await T["semantic_search"]("exported counters")
        assert "a background refresh has started" in out
        idx = get_semantic_index()
        while idx.building:
            await asyncio.sleep(0.05)
        assert "Metrics" in await T["semantic_search"]("exported counters every minute", language="markdown")
    finally:
        os.environ.pop("STATICSIGHT_SEMANTIC_AUTO_REFRESH_FILES", None)
        f.write_bytes(original)
        await get_semantic_index().refresh()


async def test_auto_refresh_disabled_reports_staleness(workspace):
    os.environ["STATICSIGHT_SEMANTIC_AUTO_REFRESH"] = "0"
    f = workspace / "tools" / "router.yaml"
    original = f.read_bytes()
    try:
        f.write_bytes(original + b"  timeout_ms: 250\n")
        out = await T["semantic_search"]("router queues")
        assert "automatic refresh disabled" in out and "refresh_semantic_index" in out
        assert "1 file(s) changed" in out
        assert "Re-indexed 1 changed file(s)" in await T["refresh_semantic_index"]()
    finally:
        os.environ.pop("STATICSIGHT_SEMANTIC_AUTO_REFRESH", None)
        f.write_bytes(original)
        await get_semantic_index().refresh()


async def test_lock_contention_and_similar_code(workspace):
    idx = get_semantic_index()
    lock = idx.db_path.with_suffix(".lock")
    lock.write_text("other")
    f = workspace / "tools" / "retry.py"
    original = f.read_bytes()
    try:
        f.write_bytes(original + b"\n# touched\n")
        assert "Another process is refreshing" in await T["refresh_semantic_index"]()
    finally:
        lock.unlink()
        f.write_bytes(original)
        await idx.refresh()
    out = await T["find_similar_code"]("src/storage/wal.cpp", 5, top_k=3)
    assert "Source: function `wal_append`" in out and "wal_replay" in out


async def test_model_change_triggers_rebuild(workspace, tmp_path):
    env = {**os.environ, "WORKSPACE_ROOT": str(workspace), "STATICSIGHT_CACHE_DIR": str(tmp_path / "c"),
           "STATICSIGHT_DATA_DIR": str(tmp_path / "data"), "STATICSIGHT_EMBED_MODEL": "test-hash"}
    r = subprocess.run([sys.executable, "-m", "staticsight.server", "index", "build"], env=env, capture_output=True, text=True)
    assert r.returncode == 0 and "re-indexed" in r.stdout, r.stderr
    r = subprocess.run([sys.executable, "-m", "staticsight.server", "search", "wal replay", "--top", "1"], env=env,
                       capture_output=True, text=True)
    assert "wal_replay" in r.stdout
    bad = subprocess.run([sys.executable, "-m", "staticsight.server", "search", "x"],
                         env={**env, "STATICSIGHT_EMBED_MODEL": "nope"}, capture_output=True, text=True)
    assert bad.returncode == 1 and "Unknown embedding model" in bad.stderr


@pytest.mark.skipif(not TS_DIST.exists() or not shutil.which("node"), reason="TypeScript build not available")
async def test_typescript_reads_the_python_index(workspace):
    """One shared index format: the TS implementation answers from the DB the Python implementation built."""
    q = "check that a memory allocation succeeded before using the buffer"
    py = await T["semantic_search"](q, top_k=5)
    env = {**os.environ, "STATICSIGHT_SEMANTIC_AUTO_REFRESH": "0"}
    r = subprocess.run(["node", str(TS_DIST), "search", q, "--top", "5"], env=env, capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stderr
    assert r.stdout.strip() == py.strip()


async def test_review_near_duplicates_line_format(workspace):
    from staticsight.config import load_config
    from staticsight.semantic.search import similar_for_review

    lines = await similar_for_review(load_config(), [("src/storage/wal.cpp", 5, "wal_append")], threshold=0.0, per_target=2)
    assert lines and lines[0].startswith("- `wal_append` (`src/storage/wal.cpp:5`) resembles: ")



# ------------------------------------------------------------------------------ per-repo data folder
def test_data_dir_is_in_repo_and_self_ignored(workspace):
    d = workspace / ".staticsight"
    assert (d / "semantic.db").is_file() and (d / "GTAGS").is_file()
    assert (d / ".gitignore").read_text().strip().endswith("*")
    r = subprocess.run(["git", "status", "--porcelain", "--ignored=no"], cwd=workspace, capture_output=True, text=True)
    assert ".staticsight" not in r.stdout


async def test_root_discovery_and_modes(workspace, tmp_path, monkeypatch):
    from staticsight.config import find_repo_root, load_config, workspace_cache_dir, workspace_data_dir

    assert find_repo_root(workspace / "src" / "net") == workspace
    monkeypatch.delenv("WORKSPACE_ROOT")
    monkeypatch.chdir(workspace / "src" / "net")
    cfg = load_config()
    assert cfg.workspace_root == workspace
    assert workspace_data_dir(cfg) == (workspace / ".staticsight", "repository")
    monkeypatch.setenv("STATICSIGHT_DATA_DIR", "cache")
    cfg = load_config()
    assert workspace_data_dir(cfg)[0] == workspace_cache_dir(cfg)
    monkeypatch.setenv("STATICSIGHT_DATA_DIR", str(tmp_path / "x"))
    cfg = load_config()  # an explicit folder still gets one sub-folder per repository
    assert workspace_data_dir(cfg)[0] == tmp_path.resolve() / "x" / workspace_cache_dir(cfg).name


def test_non_repository_folder_gets_no_data_dir(tmp_path, monkeypatch):
    """Started in a folder without .git (e.g. $HOME), nothing is created there: it would become a root marker."""
    from staticsight.config import find_repo_root, load_config, workspace_cache_dir, workspace_data_dir

    home = tmp_path / "home"
    (home / "scratch").mkdir(parents=True)
    monkeypatch.delenv("WORKSPACE_ROOT", raising=False)
    monkeypatch.delenv("STATICSIGHT_DATA_DIR", raising=False)
    monkeypatch.setenv("STATICSIGHT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.chdir(home)
    cfg = load_config()
    d, why = workspace_data_dir(cfg)
    assert d == workspace_cache_dir(cfg) and why == "per-user cache (not a git repository)"
    assert not (home / ".staticsight").exists()
    assert find_repo_root(home / "scratch") == (home / "scratch").resolve()
    monkeypatch.setenv("WORKSPACE_ROOT", str(home))  # an explicit choice may use a non-git folder
    assert workspace_data_dir(load_config())[0] == home.resolve() / ".staticsight"


@pytest.mark.skipif(os.name == "nt" or (hasattr(os, "geteuid") and os.geteuid() == 0), reason="needs a non-root POSIX user")
def test_read_only_repo_falls_back_to_cache(tmp_path, monkeypatch):
    from staticsight.config import load_config, workspace_cache_dir, workspace_data_dir

    repo = tmp_path / "ro"
    (repo / ".git").mkdir(parents=True)
    repo.chmod(0o555)
    try:
        monkeypatch.setenv("WORKSPACE_ROOT", str(repo))
        cfg = load_config()
        d, why = workspace_data_dir(cfg)
        assert d == workspace_cache_dir(cfg) and "not writable" in why
    finally:
        repo.chmod(0o755)


def test_legacy_cache_index_is_migrated(tmp_path, monkeypatch):
    from staticsight.config import load_config, workspace_cache_dir, workspace_data_dir

    repo = tmp_path / "legacy"
    (repo / ".git").mkdir(parents=True)
    monkeypatch.setenv("WORKSPACE_ROOT", str(repo))
    monkeypatch.setenv("STATICSIGHT_CACHE_DIR", str(tmp_path / "cache"))
    monkeypatch.delenv("STATICSIGHT_DATA_DIR", raising=False)
    cfg = load_config()
    old = workspace_cache_dir(cfg)
    old.mkdir(parents=True)
    (old / "semantic.db").write_bytes(b"db")
    (old / "GTAGS").write_bytes(b"g")
    d, _ = workspace_data_dir(cfg)
    assert (d / "semantic.db").read_bytes() == b"db" and (d / "GTAGS").read_bytes() == b"g"
    assert not (old / "semantic.db").exists()
