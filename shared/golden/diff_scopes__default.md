### 🧭 DIFF SCOPES vs merge-base with `origin/main` (c945b1033a)
9 C/C++ files changed (+49 / -2).
By status: 8 modified, 1 untracked.

#### `src/net/conn_pool.cpp` (source, modified, +9 -0)
- `ConnPool` (class, L4-14) — changed L8 — declarations changed (no data-member change detected)
- `ConnPool::report` (prototype, L8) — 🆕 new
- `ConnPool::report` (function, L30-35) — 🆕 new
- file-level lines (outside any function/type): L29

#### `src/net/packet.hpp` (header, modified, +1 -0)
- `Packet` (struct, L4-10) — changed L8 — 🧱 layout change (data members/virtuals)

#### `src/net/proto.cpp` (source, modified, +14 -0)
- `encode_msg` (function, L5-14) — changed L11
- `encode_batch` (function, L40-50) — 🆕 new
- file-level lines (outside any function/type): L3
- 📎 #include lines changed

#### `src/net/proto.hpp` (header, modified, +2 -1)
- `MsgType` (enum, L3) — changed L3 — 1 line(s) removed — 🧱 layout change (data members/virtuals)
- `encode_batch` (prototype, L8) — 🆕 new
- file-level lines (outside any function/type): L8

#### `src/new_feature.cpp` (source, new, untracked, +8 -0)
- 🆕 new file: 1 function, 0 types, 0 macros: `new_feature`

#### `src/platform/timer_posix.cpp` (source, modified, +3 -0)
- `start_timer` (function, L3-8) — changed L4-6

#### `src/router.cpp` (source, modified, +7 -1)
- `Router::process_packet` (function, L9-26) — changed L12-14
- `Router::get_route_count` (function, L33-35) — 1 line(s) removed
- `Router::reset` (function, L37-39) — 🆕 new

#### `src/router.hpp` (header, modified, +1 -0)
- `Router` (class, L5-21) — changed L16 — declarations changed (no data-member change detected)
- `Router::reset` (prototype, L16) — 🆕 new

#### `src/storage/wal.cpp` (source, modified, +4 -0)
- `wal_replay` (function, L8-10) — 🆕 new

#### 🔎 Suggested next calls
- `get_branch_skeleton("src/net/proto.cpp", symbol="encode_msg")`
- `get_upstream_callers("encode_msg")`
- `get_branch_skeleton("src/platform/timer_posix.cpp", symbol="start_timer")`
- `get_upstream_callers("start_timer")`
- `get_branch_skeleton("src/router.cpp", symbol="Router::process_packet")`
- `get_upstream_callers("process_packet")`
- `get_branch_skeleton("src/router.cpp", symbol="Router::get_route_count")`
- `get_upstream_callers("get_route_count")`
- `get_upstream_callers("report")` — declaration changed
- `get_upstream_callers("encode_batch")` — declaration changed
- `get_upstream_callers("reset")` — declaration changed
- `track_struct_risks("Packet")`
- `track_struct_risks("MsgType")`
- `run_file_static_audit("src/net/conn_pool.cpp", only_changed_lines=true)`
- `get_include_blast_radius("src/net/packet.hpp")`
_…and 12 more suggestions. Next: `get_more("Pcf62ec")`._
