### 🔒 STATE MUTATION & ACCESS SITES: `route_mutex`
0 accesses (0 writes), 2 lock operations in 1 file.

| Location | Function | Access | Sync | Code |
|---|---|---|---|---|
| `src/router.cpp:10` | `Router::process_packet` | lock operation | — (this is the mutex) | `std::lock_guard<std::mutex> lock(route_mutex);` |
| `src/router.cpp:29` | `Router::reconfigure_routes` | lock operation | — (this is the mutex) | `std::unique_lock<std::mutex> lock(route_mutex);` |

_Heuristic: lock scope inferred from RAII guards/.lock() inside the enclosing function; locks held by callers are not visible._
