### 🧭 DIFF SCOPES vs merge-base with `origin/main` (7cd1f773cb)
6 C/C++ files changed (+30 / -1).
By status: 5 modified, 1 untracked.

#### `src/net/conn_pool.cpp` (source, modified, +9 -0)
- `ConnPool` (class, L4-14) — changed L8 — declarations changed (no data-member change detected)
- `ConnPool::report` (prototype, L8) — 🆕 new
- `ConnPool::report` (function, L30-35) — 🆕 new
- file-level lines (outside any function/type): L29

#### `src/net/packet.hpp` (header, modified, +1 -0)
- `Packet` (struct, L4-10) — changed L8 — 🧱 layout change (data members/virtuals)

#### `src/new_feature.cpp` (source, new, untracked, +8 -0)
- 🆕 new file: 1 function, 0 types, 0 macros: `new_feature`

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
- `get_branch_skeleton("src/router.cpp", symbol="Router::process_packet")`
- `get_upstream_callers("process_packet")`
- `get_branch_skeleton("src/router.cpp", symbol="Router::get_route_count")`
- `get_upstream_callers("get_route_count")`
- `get_upstream_callers("report")` — declaration changed
- `get_upstream_callers("reset")` — declaration changed
- `track_struct_risks("Packet")`
- `run_file_static_audit("src/net/conn_pool.cpp", only_changed_lines=true)`
- `get_include_blast_radius("src/net/packet.hpp")`
- `run_file_static_audit("src/new_feature.cpp", only_changed_lines=true)`
- `run_file_static_audit("src/router.cpp", only_changed_lines=true)`
- `get_include_blast_radius("src/router.hpp")`
- `run_file_static_audit("src/storage/wal.cpp", only_changed_lines=true)`
- `get_branch_skeleton("src/net/conn_pool.cpp", symbol="ConnPool::report")` — audit the new function
- `get_branch_skeleton("src/new_feature.cpp", symbol="new_feature")` — audit the new function
_…and 2 more suggestions._
