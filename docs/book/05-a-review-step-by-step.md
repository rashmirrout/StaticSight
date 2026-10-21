<!-- nav:top -->
📚 [Documentation](../README.md) › 📖 [The book](00-preface.md) › **Chapter 5: A review, step by step**
<!-- /nav:top -->

# 5. A review, step by step

This chapter follows one request from beginning to end: *"Review my changes. What did I miss, and could anything
break?"*, asked on the test repository. Every output is real. You can replay each step yourself with
`staticsight tool …` (see the [command-line guide](../cli-guide.md)).

## The change under review

The test repository has a branch with six changed C/C++ files. In plain words, the author:
- added an encryption check to `Router::process_packet` that returns `-2` early;
- added a `checksum` field to the `Packet` struct;
- removed the lock from `Router::get_route_count`;
- added `Router::reset`, which sets `route_count = 0`;
- added `ConnPool::report`, which takes the stats lock, calls `drain()` (which takes the pool lock) and sends while
  still holding the lock;
- added a `wal_replay` function and a new file, `new_feature.cpp`.

Some changes are committed, one is unstaged and one file is untracked, as in a real working copy.

## Step 1: the agent chooses a tool

The agent has read the tool catalogue at the start of the session. The description of `review_changes` begins with
*"START HERE for 'review my changes' / 'what could break?'"*, and the server instructions say "For a code review,
start with review_changes". So the agent calls:

```json
{"name": "review_changes", "arguments": {}}
```

No base ref is given, so StaticSight picks the merge-base of `HEAD` and `origin/main`.

## Step 2: what changed (git + ctags)

StaticSight asks git for the diff (committed, staged, unstaged and untracked), then runs ctags on the new and old
version of each changed file to map every changed line to a symbol:

```text
## 1. What changed
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
```

Already the diff is described in the reviewer's terms: which functions changed, which are new, and that `Packet`'s
**layout** changed (a data member was added), which is different from adding a method.

## Step 3: static audit on changed lines (cppcheck)

For each changed source file, cppcheck runs, and only findings on changed lines (✏️) or inside changed functions (🔶)
are kept:

```text
### 🚨 STATIC AUDIT: `src/router.cpp` (cppcheck 2.18.3)
2 findings (1 error, 1 style); 1 on changed lines.
1. ✏️ **L13** `[error: memleak]` Memory leak: buffer (CWE-401)
   `return -2;`
2. 🔶 **L9** `[style: constParameterPointer]` Parameter 'p' can be declared as pointer to const (CWE-398)
   `int Router::process_packet(Packet* p) {`
```

The strongest evidence of the whole review is here: a real analyser reports a leak on a line the author just wrote.

## Step 4: the logic of each changed function (ctags + skeleton)

For each changed function, StaticSight prints only its control flow, annotated:

```text
### 🌿 BRANCH SKELETON: `Router::process_packet` (`src/router.cpp` L9-26)
Paths: 3 returns, 0 throws (2 early exits), 1 loop; ⚠️ 1 potential leak path.
[L9] ENTRY int Router::process_packet(Packet* p) {
├── [L10] 🔒 LOCK — std::lock_guard<std::mutex> lock(route_mutex);
├── [L11] 📥 ALLOC `buffer` — uint8_t* buffer = static_cast<uint8_t*>(malloc(p->len));
├── [L12] IF (!p->is_encrypted) ✏️
│   ├── [L13] 🛑 RETURN -2 ⚠️ early exit; `buffer` (L11) not released on this path ✏️
├── [L15] IF (buffer == nullptr)
│   ├── [L16] 🛑 RETURN -1
├── [L19] FOR (int i = 0; i < route_count; ++i)
│   ├── [L20] IF (buffer[0] == 0xFF)
│   │   ├── [L21] BREAK
├── [L24] 📤 RELEASE `buffer` — free(buffer);
├── [L25] ↩ RETURN 0
```

The skeleton confirms cppcheck independently and explains *why*: `buffer` is allocated on L11, the new early return on
L13 skips the `free` on L24. It also shows what is *not* a bug: `RETURN -1` on L16 is inside `if (buffer == nullptr)`,
so there is nothing to free there, and it is correctly not flagged.

## Step 5: who is affected (GNU Global)

For changed functions, the callers:

```text
### 📞 UPSTREAM CALLERS: `process_packet`
Found 3 call sites in 2 files (source: GNU Global).
Returns `int`; ⚠️ 2 caller(s) ignore the result — check they tolerate new error values.

**`src/net/listener.cpp`**
1. L9 in `Listener::on_socket_read` — result used
   `int rc = router_->process_packet(&raw);`
2. L17 in `Listener::dispatch_batch` — ⚠️ result ignored
   `router_->process_packet(&batch[i]);`
```

`process_packet` has a new return value (`-2`). Two callers throw the result away, so the new failure is silent there.

## Step 6: the layout change (ripgrep + ctags)

`Packet` gained a field. StaticSight looks for every place where the struct's exact bytes matter:

```text
### ⚠️ LOW-LEVEL MEMORY USAGES: `Packet`
Defined at: `src/net/packet.hpp:4-10`.
Modifying the size, padding or member order of `Packet` may break 4 sites (out of 16 references):

1. `src/net/socket.cpp:6` in `send_packet` — 🌐 raw I/O, 📏 size/offset assumption, 🎭 type punning
   `return send(fd, reinterpret_cast<const char*>(&pkt), sizeof(Packet), 0);`
2. `src/net/socket.cpp:9` in `copy_packet` — 🧬 raw memory op, 📏 size/offset assumption (operation within ±2 lines)
   `void copy_packet(uint8_t* dst, const Packet& pkt) {`
3. `src/storage/wal.cpp:5` in `wal_append` — 🧬 raw memory op, 📏 size/offset assumption
   `memcpy(wal_ptr, &p, sizeof(Packet));`
4. `src/storage/wal.cpp:9` in `wal_replay` — 🧬 raw memory op, 📏 size/offset assumption
   `memcpy(&out, wal_ptr, sizeof(Packet));`
```

Out of 16 references to `Packet`, 4 depend on its byte layout: one sends it over the network and two write it to a log.
This is the wire-format and disk-format break from Chapter 1, found without anyone reading `socket.cpp` or `wal.cpp`.

And the header's reach:

```text
### 💥 BLAST RADIUS: `src/net/packet.hpp`
- **Direct includers:** 7 files; **transitive:** 3 more files (depth 2)
- **Translation units affected:** 8 of 13 source files (62%); headers affected: 2
```

## Step 7: locking (ripgrep + ctags + lock inference)

Changed functions use the member `route_count`. StaticSight lists every access and the lock active at that line:

```text
⚠️ **Inconsistent locking:** accessed under a lock in 2 place(s) but without one in 2: `src/router.cpp:34` (Router::get_route_count, read), `src/router.cpp:38` (Router::reset, write). Potential data race if these run concurrently.

| Location | Function | Access | Sync | Code |
|---|---|---|---|---|
| `src/router.cpp:19` | `Router::process_packet` | read | 🔒 lock_guard (L10) | `for (int i = 0; i < route_count; ++i) {` |
| `src/router.cpp:30` | `Router::reconfigure_routes` | write | 🔒 unique_lock (L29) | `route_count = count;` |
| `src/router.cpp:34` | `Router::get_route_count` | read | ❌ BARE | `return route_count;` |
| `src/router.cpp:38` | `Router::reset` | write | ❌ BARE | `route_count = 0;` |
```

Both lock bugs from the branch appear in one table.

## Step 8: lock order (ripgrep + ctags + lock walk)

A changed function, `ConnPool::report`, takes a lock, so StaticSight builds the lock-acquisition order of the whole
repository and keeps what concerns the locks that function takes:

```text
## 8. Lock order
### 🔀 LOCK ORDER: locks taken by changed functions
Scanned 5 functions that take locks in 2 files: 3 locks, 2 ordering pairs.

⚠️ **1 potential deadlock cycle** (locks taken in opposite orders):
1. `ConnPool::pool_mutex` → `ConnPool::stats_mutex` → `ConnPool::pool_mutex`
   - `src/net/conn_pool.cpp:18` in `ConnPool::rebalance`: holds `ConnPool::pool_mutex` (L18), takes `ConnPool::stats_mutex` at L19
   - `src/net/conn_pool.cpp:31` in `ConnPool::report`: holds `ConnPool::stats_mutex` (L31), takes `ConnPool::pool_mutex` via `ConnPool::drain()` at L33

⏳ **Locks held across blocking calls** (latency, and deadlock if the other side needs the lock):
- `src/net/conn_pool.cpp:34` in `ConnPool::report`: `send()` while holding `ConnPool::stats_mutex`
```

The inversion is invisible in the diff: `report()` never names `pool_mutex`. It shows up only when the call to
`drain()` is followed to the lock that `drain()` takes, and compared with the order used by `rebalance()` in an
unchanged part of the file.

## Step 9: reach, completeness and history (code graph + git)

The next sections look beyond the diff. **Reach** follows callers three levels up through the
[code graph](../code-graph.md) and names the entry points, threads and tests that reach each changed function.
**Completeness** asks what should have changed too. **Earlier fixes** (not in this example) lists bug-fix commits that
touched the changed lines before.

```text
## 11. Reach of changed functions (code graph)
- `encode_msg`: 2 functions in 2 files within 3 calls; tests: `TEST(Proto,RoundTrip)`
- `start_timer`: no callers in the repository; tests: ⚠️ none
- `Router::process_packet`: 6 functions in 4 files within 3 calls; reached from `main` (program), `pump_loop` (thread); tests: `test_drop_invalid`
- `Router::get_route_count`: no callers in the repository; tests: ⚠️ none

## 12. Completeness
- ⚠️ `src/net/proto.cpp:31` in `msg_name`: missing `Ping`; handled by `default:` — check that is right `F7b1502`
- ⚠️ `start_timer` (`src/platform/timer_win.cpp:3`) is the platform twin of changed `start_timer` but was not changed `Ff8880b`
```

`process_packet` runs on the `pump_loop` worker thread started from `main`: the leak and the ignored result are
reachable in production, not only in a test. The `Ping` value and the Windows timer are the kind of miss a diff can
never show, because the missing lines are exactly the ones that were not written. `F7b1502` and `Ff8880b` are finding
IDs, which the agent can re-check with `verify_finding`.

(Excerpts in this chapter are shortened; the current output also puts an ID such as `F7a0cc5` next to each leak,
cppcheck error, ignored result and lock-order cycle.)

## Step 10: new calls and the checklist

The bundle ends with the functions newly called by the diff (so the agent can check their contracts with
`get_symbol_contract`) and a checklist generated from what was found:

```text
## ✅ Reviewer checklist
- [ ] Fix the cppcheck **errors** on changed lines (✏️) first; they are the strongest evidence.
- [ ] Confirm every allocation/acquire flagged ⚠️ is released on the early-exit paths shown in the skeletons.
- [ ] Some callers ignore return values of changed functions: check new/changed error codes are handled.
- [ ] Layout-changed types are copied/sent/cast as raw bytes: check wire/disk format versioning, peers built from old code, and add/update `static_assert(sizeof(...))`.
- [ ] Changed headers recompile every includer listed in the blast radius: rebuild and run their tests.
- [ ] Members are accessed both with and without their mutex: confirm thread-safety or restore the lock.
- [ ] Locks are taken in conflicting orders (or twice): fix the order before merging; this can deadlock.
- [ ] A lock is held across a blocking call: shrink the critical section or document why it is safe.
```

The whole bundle fills the 16,000-character budget. When the sections do not all fit, the longest are shortened first,
so every section keeps its heading and first findings and the checklist is always complete. That is still far smaller
than the source files the agent would otherwise have to read.

## Step 11: the agent drills down, verifies and reports

With the bundle in context, the agent can ask follow-up questions, for example `get_symbol_contract` on a newly called
function, `get_impact` for the full chains, or `track_struct_risks` with a narrower `path_glob`. Before reporting a
finding it runs `verify_finding` on its ID, which re-runs the check on the current code and lists what would disprove
it. Then it writes the review. A typical report, built from
the evidence above:

> **Blockers**
> 1. `src/router.cpp:13`: the new early `return -2` leaks `buffer` (allocated at L11). Evidence: cppcheck `memleak`
>    on a changed line, and the skeleton shows the early exit before `free` at L24. Fix: move the check above the
>    `malloc`, or free before returning.
> 2. `src/net/packet.hpp:8`: the new `checksum` field changes `sizeof(Packet)`, and the struct is sent and persisted as
>    raw bytes (`socket.cpp:6`, `wal.cpp:5`, `wal.cpp:9`). This breaks the wire and log formats.
> 3. `src/router.cpp:34` and `:38`: `route_count` is accessed without `route_mutex` while other paths hold it.
> 4. `src/net/conn_pool.cpp:31`: `report()` holds `stats_mutex` while `drain()` takes `pool_mutex`, the reverse of
>    `rebalance()`. Two threads can deadlock. It also calls `send()` while holding the lock. Fix: take the locks in one
>    order (or `std::scoped_lock` both), and send after unlocking.
>
> **Major**
> 5. `src/net/listener.cpp:17` ignores the new `-2` result of `process_packet`, and so does the `pump_loop` worker
>    thread (`server_loop.cpp:9`), which `main` starts.
> 6. `src/net/proto.cpp:43`: `encode_batch` returns early without releasing `ring` from `mem::zero_copy_allocate`
>    (cppcheck `memleak`, through the contract "MUST be paired with release_buffer()").
> 7. `src/net/proto.cpp:31`: `msg_name` has no case for the new `MsgType::Ping`; it falls into `default:`.
> 8. `src/platform/timer_win.cpp:3`: the clamp added to the POSIX `start_timer` is missing on Windows.
>
> **Verdict:** not ready to merge.

Every sentence in that report points to evidence. That is the difference StaticSight makes: the agent is no longer
guessing from the active tab.

## What it cost

Measured on the test repository, from a terminal (`staticsight tool …`, which includes about 0.7 s to start Python):

| Call | Time |
|---|---|
| each single tool (diff scopes, audit of one file, skeleton, callers, layout risks, blast radius, locking) | 0.75-0.8 s in total, so well under 0.1 s of actual work |
| the whole `review_changes` bundle | 2.2 s |

Inside the MCP server there is no start-up cost per call. On large repositories cppcheck dominates (seconds per file),
which is why the bundle audits at most six files and the agent can audit more on request.

---

<!-- nav:bottom -->
| ⬅️ [Architecture](04-architecture.md) | 📚 [Documentation](../README.md) | [The review tools in depth](06-review-tools-in-depth.md) ➡️ |
|:---|:---:|---:|
<!-- /nav:bottom -->
