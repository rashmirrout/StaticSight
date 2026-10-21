### 🧭 CALL PATHS: `main` → `process_packet`
_Code graph up to date (28 files)._
1 path, shortest 3 calls:
1. `main` → `run_server` → `pump_loop` → `Router::process_packet`
   - `src/main.cpp:4` in `main`: calls `run_server`: `return run_server();`
   - `src/net/server_loop.cpp:13` in `run_server`: starts `pump_loop` as a thread/callback: `std::thread worker(pump_loop);`
   - `src/net/server_loop.cpp:9` in `pump_loop`: calls `process_packet`: `g_router.process_packet(&p);`

_Heuristic: calls are matched by name and narrowed by class where the code says so (`C::f()`, calls inside `C`'s members); `obj.f()` may reach any `f`. Threads/callbacks are followed; other function pointers are not._
