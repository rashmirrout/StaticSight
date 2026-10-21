### 🌊 IMPACT: `process_packet` (callers, depth 3)
_Code graph up to date (28 files)._
**Target:** `Router::process_packet` — `src/router.cpp:9` · returns `int`
- **Depth 1:** 4 call sites in 4 functions
  - `Listener::on_socket_read` — `src/net/listener.cpp:9` — result used
  - `Listener::dispatch_batch` — `src/net/listener.cpp:17` — ⚠️ result ignored
  - `pump_loop` 🧵 thread/callback — `src/net/server_loop.cpp:9` — ⚠️ result ignored
  - `test_drop_invalid` 🧪 test — `tests/test_router.cpp:6` — ⚠️ result ignored
- **Depth 2:** 1 call site in 1 function
  - `run_server` → `pump_loop` — `src/net/server_loop.cpp:13` — starts as a thread/callback
- **Depth 3:** 1 call site in 1 function
  - `main` 🚪 program entry → `run_server` — `src/main.cpp:4` — result used
**Reach:** 6 functions in 4 files; modules: `src/net` (4), `src` (1), `tests` (1); entry points: `main`, `pump_loop`; tests: `test_drop_invalid`.

_Heuristic: calls are matched by name and narrowed by class where the code says so (`C::f()`, calls inside `C`'s members); `obj.f()` may reach any `f`. Threads/callbacks are followed; other function pointers are not._
