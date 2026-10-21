### 📦 CONTEXT PACK: `Router::process_packet`
_Code graph up to date (28 files)._
- **Where:** `src/router.cpp:9-26` (18 lines)
- **Signature:** `int Router::process_packet(Packet * p)`

**Contract**
> @brief Ingests an inbound network packet.
> @pre Parameter p must be non-null and pre-validated by the listener.
> @return 0 on success, negative value on failure.
> @note Thread-safe. Acquires route_mutex internally.
Obligations: @pre Parameter p must be non-null and pre-validated by the listener. · @return 0 on success, negative value on failure. · @note Thread-safe. Acquires route_mutex internally.

**Logic** (branch skeleton)
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

**Callers** (4)
- `Listener::on_socket_read` — `src/net/listener.cpp:9` — result used
- `Listener::dispatch_batch` — `src/net/listener.cpp:17` — ⚠️ result ignored
- `pump_loop` — `src/net/server_loop.cpp:9` — ⚠️ result ignored
- `test_drop_invalid` — `tests/test_router.cpp:6` — ⚠️ result ignored

**Calls**
- In the repository: none
- Outside (libraries, SDK, macros): `malloc`, `memcpy`, `free`

**Types in the signature:** `Packet` (struct, `src/net/packet.hpp:4`)

**Locks taken:** `route_mutex` — see `track_lock_order` / `track_state_mutations` before changing the locking.

**Tests reaching it:** `test_drop_invalid` (`tests/test_router.cpp:3`)

**Recent history:** `468560c` 2024-01-01 feature: encryption gate, checksum field, reset(); `d4d7f9b` 2024-01-01 base
