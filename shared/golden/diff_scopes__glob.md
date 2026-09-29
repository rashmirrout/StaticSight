### 🧭 DIFF SCOPES vs merge-base with `origin/main` (7cd1f773cb)
2 C/C++ files changed (+10 / -0).
By status: 2 modified.

#### `src/net/conn_pool.cpp` (source, modified, +9 -0)
- `ConnPool` (class, L4-14) — changed L8 — declarations changed (no data-member change detected)
- `ConnPool::report` (prototype, L8) — 🆕 new
- `ConnPool::report` (function, L30-35) — 🆕 new
- file-level lines (outside any function/type): L29

#### `src/net/packet.hpp` (header, modified, +1 -0)
- `Packet` (struct, L4-10) — changed L8 — 🧱 layout change (data members/virtuals)

#### 🔎 Suggested next calls
- `get_upstream_callers("report")` — declaration changed
- `track_struct_risks("Packet")`
- `run_file_static_audit("src/net/conn_pool.cpp", only_changed_lines=true)`
- `get_include_blast_radius("src/net/packet.hpp")`
- `get_branch_skeleton("src/net/conn_pool.cpp", symbol="ConnPool::report")` — audit the new function
