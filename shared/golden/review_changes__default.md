# 🔬 STATICSIGHT REVIEW BUNDLE vs merge-base with `origin/main` (c945b1033a)

## 1. What changed
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

## 2. Static audit (cppcheck, changed lines)
### 🚨 STATIC AUDIT: `src/net/conn_pool.cpp` (cppcheck 2.18.3)
✅ No cppcheck findings on changed lines/functions.

_project allocators from contract comments: `mem::zero_copy_allocate`/`mem::release_buffer`; zero-compile mode: includes are best-effort and missing-include diagnostics are suppressed. ✏️ = on a changed line, 🔶 = inside a changed function._

### 🚨 STATIC AUDIT: `src/net/proto.cpp` (cppcheck 2.18.3)
1 finding (1 error); 1 on changed lines.
1. ✏️ **L43** `[error: memleak]` Memory leak: ring (CWE-401) `F6a97a8`
   `return -1;`

_project allocators from contract comments: `mem::zero_copy_allocate`/`mem::release_buffer`; zero-compile mode: includes are best-effort and missing-include diagnostics are suppressed. ✏️ = on a changed line, 🔶 = inside a changed function._

### 🚨 STATIC AUDIT: `src/new_feature.cpp` (cppcheck 2.18.3)
✅ No cppcheck findings on changed lines/functions.

_project allocators from contract comments: `mem::zero_copy_allocate`/`mem::release_buffer`; zero-compile mode: includes are best-effort and missing-include diagnostics are suppressed. ✏️ = on a changed line, 🔶 = inside a changed function._

### 🚨 STATIC AUDIT: `src/platform/timer_posix.cpp` (cppcheck 2.18.3)
✅ No cppcheck findings on changed lines/functions.

_project allocators from contract comments: `mem::zero_copy_allocate`/`mem::release_buffer`; zero-compile mode: includes are best-effort and missing-include diagnostics are suppressed. ✏️ = on a changed line, 🔶 = inside a changed function._

### 🚨 STATIC AUDIT: `src/router.cpp` (cppcheck 2.18.3)
2 findings (1 error, 1 style); 1 on changed lines.
1. ✏️ **L13** `[error: memleak]` Memory leak: buffer (CWE-401) `F17fe6e`
   `return -2;`
2. 🔶 **L9** `[style: constParameterPointer]` Parameter 'p' can be declared as pointer to const (CWE-398)
   `int Router::process_packet(Packet* p) {`


_…output truncated at 1942 characters to protect the context budget. Narrow the query for more._

## 3. Branch skeletons of changed functions
### 🌿 BRANCH SKELETON: `encode_msg` (`src/net/proto.cpp` L5-14)
Paths: 1 return, 0 throws (0 early exits), 0 loops.
```text
[L5] ENTRY int encode_msg(MsgType t, char* out) {
├── [L6] SWITCH (t)
│   ├── [L7] CASE MsgType
│   ├── [L8] CASE MsgType
│   ├── [L9] CASE MsgType
│   ├── [L10] CASE MsgType
│   ├── [L11] CASE MsgType ✏️
├── [L13] ↩ RETURN -1
```
_✏️ changed in diff · 🛑 early exit · ⚠️ heuristic (comment/string-stripped text + brace depth, not a compiler)._

### 🌿 BRANCH SKELETON: `start_timer` (`src/platform/timer_posix.cpp` L3-8)
Paths: 1 return, 0 throws (0 early exits), 0 loops.
```text
[L3] ENTRY int start_timer(int ms) {
├── [L4] IF (ms > 60000) ✏️
├── [L7] ↩ RETURN ms > 0 ? ms : 1
```
_✏️ changed in diff · 🛑 early exit · ⚠️ heuristic (comment/string-stripped text + brace depth, not a compiler)._

### 🌿 BRANCH SKELETON: `Router::process_packet` (`src/router.cpp` L9-26)
Paths: 3 returns, 0 throws (2 early exits), 1 loop; ⚠️ 1 potential leak path.
```text
[L9] ENTRY int Router::process_packet(Packet* p) {
├── [L10] 🔒 LOCK — std::lock_guard<std::mutex> lock(route_mutex);
├── [L11] 📥 ALLOC `buffer` — uint8_t* buffer = static_cast<uint8_t*>(malloc(p->len));
├── [L12] IF (!p->is_encrypted) ✏️
│   ├── [L13] 🛑 RETURN -2 ⚠️ early exit; `buffer` (L11) not released on this path [F7a0cc5] ✏️
├── [L15] IF (buffer == nullptr)
│   ├── [L16] 🛑 RETURN -1
├── [L19] FOR (int i = 0; i < route_count; ++i)
│   ├── [L20] IF (buffer[0] == 0xFF)
│   │   ├── [L21] BREAK
├── [L24] 📤 RELEASE `buffer` — free(buffer);
├── [L25] ↩ RETURN 0
```
_✏️ changed in diff · 🛑 early exit · ⚠️ heuristic (comment/string-stripped text + brace depth, not a compiler)._

### 🌿 BRANCH SKELETON: `Router::get_route_count` (`src/router.cpp` L33-35)
Paths: 1 return, 0 throws (0 early exits), 0 loops.
```text
[L33] ENTRY int Router::get_route_count() const { ✏️
├── [L34] ↩ RETURN route_count
```

_…output truncated at 1942 characters to protect the context budget. Narrow the query for more._

## 4. Caller impact
### 📞 UPSTREAM CALLERS: `encode_msg`
Found 2 call sites in 2 files (source: GNU Global).
Returns `int`; ⚠️ 2 caller(s) ignore the result — check they tolerate new error values.

**`src/net/proto.cpp`**
1. L46 in `encode_batch` — ⚠️ result ignored `F1457cb`
   `encode_msg(types[i], reinterpret_cast<char*>(ring + i));`
**`tests/test_proto.cpp`**
2. L8 in `TEST` — ⚠️ result ignored `F19a7ac`
   `encode_msg(MsgType::Data, buf);`

### 📞 UPSTREAM CALLERS: `start_timer`
✅ No call sites found (source: GNU Global). The symbol may be unused, called via macro, or only referenced dynamically.

### 📞 UPSTREAM CALLERS: `process_packet`
Found 4 call sites in 3 files (source: GNU Global).
Returns `int`; ⚠️ 3 caller(s) ignore the result — check they tolerate new error values.

**`src/net/listener.cpp`**
1. L9 in `Listener::on_socket_read` — result used
   `int rc = router_->process_packet(&raw);`
2. L17 in `Listener::dispatch_batch` — ⚠️ result ignored `F75b93d`
   `router_->process_packet(&batch[i]);`
**`src/net/server_loop.cpp`**
3. L9 in `pump_loop` — ⚠️ result ignored `F39b260`
   `g_router.process_packet(&p);`
**`tests/test_router.cpp`**
4. L6 in `test_drop_invalid` — ⚠️ result ignored `F2a070a`
   `r.process_packet(&dummy);`

### 📞 UPSTREAM CALLERS: `get_route_count`
✅ No call sites found (source: GNU Global). The symbol may be unused, called via macro, or only referenced dynamically.

## 5. Memory-layout risks of changed types
### ⚠️ LOW-LEVEL MEMORY USAGES: `Packet`
Defined at: `src/net/packet.hpp:4-10`.
Modifying the size, padding or member order of `Packet` may break 4 sites (out of 17 references):

1. `src/net/socket.cpp:6` in `send_packet` — 🌐 raw I/O, 📏 size/offset assumption, 🎭 type punning
   `return send(fd, reinterpret_cast<const char*>(&pkt), sizeof(Packet), 0);`
2. `src/net/socket.cpp:9` in `copy_packet` — 🧬 raw memory op, 📏 size/offset assumption (operation within ±2 lines)
   `void copy_packet(uint8_t* dst, const Packet& pkt) {`
3. `src/storage/wal.cpp:5` in `wal_append` — 🧬 raw memory op, 📏 size/offset assumption
   `memcpy(wal_ptr, &p, sizeof(Packet));`
4. `src/storage/wal.cpp:9` in `wal_replay` — 🧬 raw memory op, 📏 size/offset assumption
   `memcpy(&out, wal_ptr, sizeof(Packet));`

**Why it matters:**
- 🌐 **raw I/O:** struct bytes sent/received/persisted directly: size, padding or member order changes break the wire/disk format and peers built from older code.
- 🧬 **raw memory op:** memcpy/memmove/memset/memcmp over the object: layout changes shift offsets, and memcmp also compares padding bytes.
- 📏 **size/offset assumption:** sizeof/offsetof/alignof values change with the layout; buffers, protocol lengths and array math sized from them shift silently.
- 🎭 **type punning:** reinterpret_cast / C-style pointer cast / bit_cast reinterprets raw bytes: the layout must match the producer exactly.

### ⚠️ LOW-LEVEL MEMORY USAGES: `MsgType`
Defined at: `src/net/proto.hpp:3-3`.
Modifying the size, padding or member order of `MsgType` may break 7 sites (out of 25 references):

1. `src/net/proto.cpp:5` in `encode_msg` — 🗃️ serialization
   `int encode_msg(MsgType t, char* out) {`
2. `src/net/proto.cpp:16` in `decode_msg` — 🗃️ serialization
   `int decode_msg(const char* in, MsgType* t) {`
3. `src/net/proto.cpp:40` in `encode_batch` — 🗃️ serialization

_…output truncated at 1942 characters to protect the context budget. Narrow the query for more._

## 6. Header blast radius
### 💥 BLAST RADIUS: `src/net/packet.hpp`
- **Direct includers:** 8 files; **transitive:** 3 more files (depth 2)
- **Translation units affected:** 9 of 20 source files (45%); headers affected: 2
- **By directory:** `src/` (5), `src/net/` (3), `src/enc/` (1), `src/storage/` (1), `tests/` (1)

**Direct includers:**
- `src/enc/bom_utf8.cpp:1` `#include "net/packet.hpp"`
- `src/include_chain.hpp:2` `#include "net/packet.hpp"`
- `src/net/listener.cpp:2` `#include "net/packet.hpp"`
- `src/net/server_loop.cpp:2` `#include "net/packet.hpp"`
- `src/net/socket.cpp:1` `#include "net/packet.hpp"`
- `src/new_feature.cpp:1` `#include "net/packet.hpp"`
- `src/router.hpp:3` `#include "net/packet.hpp"`
- `src/storage/wal.cpp:1` `#include "net/packet.hpp"`

**Transitive includers:**
- `src/metrics.cpp` (depth 2)
- `src/router.cpp` (depth 2)
- `tests/test_router.cpp` (depth 2)


_…output truncated at 900 characters to protect the context budget. Narrow the query for more._

### 💥 BLAST RADIUS: `src/net/proto.hpp`
- **Direct includers:** 2 files
- **Translation units affected:** 2 of 20 source files (10%); headers affected: 0
- **By directory:** `src/net/` (1), `tests/` (1)

**Direct includers:**
- `src/net/proto.cpp:1` `#include "net/proto.hpp"`
- `tests/test_proto.cpp:1` `#include "net/proto.hpp"`

### 💥 BLAST RADIUS: `src/router.hpp`
- **Direct includers:** 4 files
- **Translation units affected:** 4 of 20 source files (20%); headers affected: 0
- **By directory:** `src/net/` (2), `src/` (1), `tests/` (1)

**Direct includers:**
- `src/net/listener.cpp:1` `#include "router.hpp"`
- `src/net/server_loop.cpp:1` `#include "router.hpp"`
- `src/router.cpp:1` `#include "router.hpp"`
- `tests/test_router.cpp:1` `#include <router.hpp>`

## 7. Lock consistency
### 🔒 STATE MUTATION & ACCESS SITES: `route_count`
4 accesses (2 writes) in 2 files.
⚠️ **Inconsistent locking:** accessed under a lock in 2 place(s) but without one in 2: `src/router.cpp:34` (Router::get_route_count, read), `src/router.cpp:38` (Router::reset, write). Potential data race if these run concurrently.

| Location | Function | Access | Sync | Code |
|---|---|---|---|---|
| `src/router.cpp:19` | `Router::process_packet` | read | 🔒 lock_guard (L10) | `for (int i = 0; i < route_count; ++i) {` |
| `src/router.cpp:30` | `Router::reconfigure_routes` | write | 🔒 unique_lock (L29) | `route_count = count;` |
| `src/router.cpp:34` | `Router::get_route_count` | read | ❌ BARE `Fc1f158` | `return route_count;` |
| `src/router.cpp:38` | `Router::reset` | write | ❌ BARE `Fda5347` | `route_count = 0;` |
| `src/router.hpp:20` | `Router` | declaration | — | `int route_count = 0;` |

_Heuristic: lock scope inferred from RAII guards/.lock() inside the enclosing function; locks held by callers are not visible._

## 8. Lock order
### 🔀 LOCK ORDER: locks taken by changed functions
Scanned 5 functions that take locks in 2 files: 3 locks, 2 ordering pairs.

⚠️ **1 potential deadlock cycle** (locks taken in opposite orders):
1. `ConnPool::pool_mutex` → `ConnPool::stats_mutex` → `ConnPool::pool_mutex` `Fa58ad6`
   - `src/net/conn_pool.cpp:18` in `ConnPool::rebalance`: holds `ConnPool::pool_mutex` (L18), takes `ConnPool::stats_mutex` at L19
   - `src/net/conn_pool.cpp:31` in `ConnPool::report`: holds `ConnPool::stats_mutex` (L31), takes `ConnPool::pool_mutex` via `ConnPool::drain()` at L33

⏳ **Locks held across blocking calls** (latency, and deadlock if the other side needs the lock):
- `src/net/conn_pool.cpp:34` in `ConnPool::report`: `send()` while holding `ConnPool::stats_mutex` `F9cfca3`

_Heuristic: locks matched by name (members qualified by class), order taken inside each function plus one call level; aliases, lock hierarchies and runtime conditions are not modelled._

## 9. Calls introduced by the diff
`drain`, `send`, `zero_copy_allocate`, `release_buffer`, `memcpy`
_Check their contracts with `get_symbol_contract` (preconditions, ownership, required pairing)._

## 10. Similar code elsewhere (semantic index)
- `start_timer` (`src/platform/timer_posix.cpp:3`) resembles: `src/platform/timer_win.cpp:3-5` `start_timer` (0.93)

## 11. Reach of changed functions (code graph)
- `encode_msg`: 2 functions in 2 files within 3 calls; tests: `TEST(Proto,RoundTrip)`
- `start_timer`: no callers in the repository; tests: ⚠️ none
- `Router::process_packet`: 6 functions in 4 files within 3 calls; reached from `main` (program), `pump_loop` (thread); tests: `test_drop_invalid`
- `Router::get_route_count`: no callers in the repository; tests: ⚠️ none
_Use `get_impact` / `find_entry_paths` for the full chains._

## 12. Completeness
- ⚠️ `src/net/proto.cpp:31` in `msg_name`: missing `Ping`; handled by `default:` — check that is right `F7b1502`
- ⚠️ `start_timer` (`src/platform/timer_win.cpp:3`) is the platform twin of changed `start_timer` but was not changed `Ff8880b`

## ✅ Reviewer checklist
- [ ] Fix the cppcheck **errors** on changed lines (✏️) first; they are the strongest evidence.
- [ ] Confirm every allocation/acquire flagged ⚠️ is released on the early-exit paths shown in the skeletons.
- [ ] Some callers ignore return values of changed functions: check new/changed error codes are handled.
- [ ] Layout-changed types are copied/sent/cast as raw bytes: check wire/disk format versioning, peers built from old code, and add/update `static_assert(sizeof(...))`.
- [ ] Changed headers recompile every includer listed in the blast radius: rebuild and run their tests.
- [ ] Members are accessed both with and without their mutex: confirm thread-safety or restore the lock.
- [ ] Locks are taken in conflicting orders (or twice): fix the order before merging; this can deadlock.
- [ ] A lock is held across a blocking call: shrink the critical section or document why it is safe.
- [ ] Near-duplicate code exists elsewhere (section 10): check whether the same change is needed there.
- [ ] Some changed functions are not reached by any test (section 11): add or run a test that covers them.
- [ ] Complete the change (section 12): handle the missing enum values and update the unchanged twins, or say why not.
- [ ] Re-read each changed function's skeleton for missing error handling on new branches.
- [ ] For signature/return-value changes, confirm every caller in section 4 still satisfies the new contract.
