### 🌊 IMPACT: `Transport::send_frame` (callers, depth 2)
_Code graph up to date (28 files)._
**Target:** `Transport::send_frame` — `src/net/transport.hpp:8` · returns `int`
**Virtual:** calls through a base or derived type can also reach `TcpTransport::send_frame` (`src/net/transport.cpp:3`), `TlsTransport::send_frame` (`src/net/transport.cpp:10`).
- **Depth 1:** 2 call sites in 2 functions
  - `TlsTransport::send_frame` — `src/net/transport.cpp:11` — result used
  - `flush_all` — `src/net/transport.cpp:15` — result used
**Reach:** 1 function in 1 file; modules: `src/net` (1).

_Heuristic: calls are matched by name and narrowed by class where the code says so (`C::f()`, calls inside `C`'s members); `obj.f()` may reach any `f`. Threads/callbacks are followed; other function pointers are not._
