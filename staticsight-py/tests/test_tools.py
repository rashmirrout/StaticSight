"""Behavioural checks: every seeded issue in the fixture must be surfaced."""

from staticsight.server import TOOLS, safe_tool

T = {fn.__name__: safe_tool(fn) for fn in TOOLS}


async def test_diff_scopes_maps_changes(workspace):
    out = await T["get_diff_scopes"]()
    assert "merge-base with `origin/main`" in out
    assert "`Router::process_packet` (function, L9-26) — changed L12-14" in out
    assert "`Router::reset` (function, L37-39) — 🆕 new" in out
    assert "`Packet` (struct, L4-10) — changed L8 — 🧱 layout change" in out
    assert "src/new_feature.cpp" in out and "untracked" in out
    assert "`wal_replay` (function, L8-10) — 🆕 new" in out  # unstaged edit
    assert 'track_struct_risks("Packet")' in out and 'track_struct_risks("Router")' not in out


async def test_skeleton_flags_leak_on_early_return(workspace):
    out = await T["get_branch_skeleton"]("src/router.cpp", symbol="process_packet")
    assert "[L13] 🛑 RETURN -2 ⚠️ early exit; `buffer` (L11) not released on this path ✏️" in out
    assert "[L16] 🛑 RETURN -1\n" in out  # null-checked path must not be flagged
    assert "decoy" not in out and "RETURN y" not in out  # comment/string decoys ignored


async def test_callers_detect_ignored_results(workspace):
    out = await T["get_upstream_callers"]("process_packet")
    assert "source: GNU Global" in out
    assert "L17 in `Listener::dispatch_batch` — ⚠️ result ignored" in out
    assert "L9 in `Listener::on_socket_read` — result used" in out
    assert "router.hpp" not in out  # declaration is not a call site


async def test_contract_extracts_obligations(workspace):
    out = await T["get_symbol_contract"]("zero_copy_allocate")
    assert "MUST be paired with release_buffer() on all execution paths" in out
    assert "src/memory/pool.hpp:13" in out and "src/memory/pool.cpp:6-8" in out
    out2 = await T["get_symbol_contract"]("release_buffer")
    assert "`noexcept`" in out2


async def test_struct_risks_context_and_comments(workspace):
    out = await T["track_struct_risks"]("Packet")
    assert "`src/net/socket.cpp:6` in `send_packet` — 🌐 raw I/O" in out
    assert "`src/net/socket.cpp:9` in `copy_packet`" in out and "within ±2 lines" in out
    assert "packet_count" not in out
    assert "src/storage/wal.cpp:9" in out


async def test_blast_radius_escapes_and_transitive(workspace):
    out = await T["get_include_blast_radius"]("packet.hpp")
    assert "decoy.cpp" not in out  # 'packetXhpp' must not match an unescaped '.'
    assert "`src/metrics.cpp` (depth 2)" in out
    assert "**Direct includers:** 7 files" in out
    assert "src/enc/bom_utf8.cpp:1" in out  # UTF-8 BOM must not hide a line-1 #include


async def test_state_mutations_inconsistent_locking(workspace):
    out = await T["track_state_mutations"]("route_count")
    assert "Inconsistent locking" in out
    assert "| `src/router.cpp:38` | `Router::reset` | write | ❌ BARE |" in out
    assert "🔒 unique_lock (L29)" in out


async def test_static_audit_memleak_in_diff(workspace):
    out = await T["run_file_static_audit"]("src/router.cpp", only_changed_lines=True)
    assert "✏️ **L13** `[error: memleak]` Memory leak: buffer (CWE-401)" in out


async def test_review_bundle_covers_everything(workspace):
    out = await T["review_changes"]()
    for needle in ("memleak", "not released", "result ignored", "LOW-LEVEL MEMORY USAGES: `Packet`",
                   "BLAST RADIUS", "Inconsistent locking", "Reviewer checklist"):
        assert needle in out, needle
    assert len(out) <= 16000 + 200


async def test_index_status(workspace):
    out = await T["get_index_status"]()
    assert "**State:** ready" in out and "`ctags` ✅" in out


async def test_errors_are_markdown(workspace):
    assert (await T["get_enclosing_scope"]("../../etc/passwd", 1)).startswith("### ❌ Invalid argument")
    assert "does not exist" in await T["get_branch_skeleton"]("src/deleted.cpp", symbol="x")
    assert "out of range" in await T["get_enclosing_scope"]("src/router.cpp", 999)
    assert "not a valid C++ identifier" in await T["get_upstream_callers"]("-rf")
    assert "git ref `does-not-exist` does not exist" in await T["get_diff_scopes"](base_ref="does-not-exist")
    assert "not a C/C++" in await T["run_file_static_audit"]("README.md") or "does not exist" in await T["run_file_static_audit"]("README.md")
