### 🔒 STATE MUTATION & ACCESS SITES: `route_count`
4 accesses (2 writes) in 2 files.
⚠️ **Inconsistent locking:** accessed under a lock in 2 place(s) but without one in 2: `src/router.cpp:34` (Router::get_route_count, read), `src/router.cpp:38` (Router::reset, write). Potential data race if these run concurrently.

| Location | Function | Access | Sync | Code |
|---|---|---|---|---|
| `src/router.cpp:19` | `Router::process_packet` | read | 🔒 lock_guard (L10) | `for (int i = 0; i < route_count; ++i) {` |
| `src/router.cpp:30` | `Router::reconfigure_routes` | write | 🔒 unique_lock (L29) | `route_count = count;` |
| `src/router.cpp:34` | `Router::get_route_count` | read | ❌ BARE | `return route_count;` |
| `src/router.cpp:38` | `Router::reset` | write | ❌ BARE | `route_count = 0;` |
| `src/router.hpp:20` | `Router` | declaration | — | `int route_count = 0;` |

_Heuristic: lock scope inferred from RAII guards/.lock() inside the enclosing function; locks held by callers are not visible._
