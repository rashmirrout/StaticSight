### 🌊 IMPACT: `run_server` (callees, depth 2)
_Code graph up to date (28 files)._
**Target:** `run_server` — `src/net/server_loop.cpp:12` · returns `int`
- **Depth 1:** 1 call
  - `pump_loop` — `src/net/server_loop.cpp:7` (called at `src/net/server_loop.cpp:13`, as a thread/callback)
- **Depth 2:** 1 call
  - `Router::process_packet` — `src/router.cpp:9` ← `pump_loop` (called at `src/net/server_loop.cpp:9`)

_Heuristic: calls are matched by name and narrowed by class where the code says so (`C::f()`, calls inside `C`'s members); `obj.f()` may reach any `f`. Threads/callbacks are followed; other function pointers are not._
