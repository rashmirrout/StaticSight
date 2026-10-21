### 🚪 ENTRY PATHS: `process_packet`
_Code graph up to date (28 files)._
Reached from 1 program entry point and 1 thread/callback entry:
1. 🧵 `pump_loop` → `Router::process_packet` (thread/callback, 1 call)
   - `src/net/server_loop.cpp:9` in `pump_loop`: calls `process_packet`: `g_router.process_packet(&p);`
2. 🚪 `main` → `run_server` → `pump_loop` → `Router::process_packet` (program entry, 3 calls)
   - `src/main.cpp:4` in `main`: calls `run_server`: `return run_server();`
   - `src/net/server_loop.cpp:13` in `run_server`: starts `pump_loop` as a thread/callback: `std::thread worker(pump_loop);`
   - `src/net/server_loop.cpp:9` in `pump_loop`: calls `process_packet`: `g_router.process_packet(&p);`
🧪 Tests that reach it: `test_drop_invalid` (`tests/test_router.cpp:3`)

_Heuristic: calls are matched by name and narrowed by class where the code says so (`C::f()`, calls inside `C`'s members); `obj.f()` may reach any `f`. Threads/callbacks are followed; other function pointers are not._
