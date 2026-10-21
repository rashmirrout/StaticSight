### 🧭 DIFF SCOPES vs merge-base with `origin/main` (c945b1033a)
4 C/C++ files changed (+26 / -1).
By status: 4 modified.

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

#### 🔎 Suggested next calls
- `get_branch_skeleton("src/net/proto.cpp", symbol="encode_msg")`
- `get_upstream_callers("encode_msg")`
- `get_upstream_callers("report")` — declaration changed
- `get_upstream_callers("encode_batch")` — declaration changed
- `track_struct_risks("Packet")`
- `track_struct_risks("MsgType")`
- `run_file_static_audit("src/net/conn_pool.cpp", only_changed_lines=true)`
- `get_include_blast_radius("src/net/packet.hpp")`
- `run_file_static_audit("src/net/proto.cpp", only_changed_lines=true)`
- `get_include_blast_radius("src/net/proto.hpp")`
- `get_branch_skeleton("src/net/conn_pool.cpp", symbol="ConnPool::report")` — audit the new function
- `get_branch_skeleton("src/net/proto.cpp", symbol="encode_batch")` — audit the new function
