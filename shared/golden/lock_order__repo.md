### 🔀 LOCK ORDER: repository
Scanned 5 functions that take locks in 2 files: 3 locks, 2 ordering pairs.

⚠️ **1 potential deadlock cycle** (locks taken in opposite orders):
1. `ConnPool::pool_mutex` → `ConnPool::stats_mutex` → `ConnPool::pool_mutex`
   - `src/net/conn_pool.cpp:18` in `ConnPool::rebalance`: holds `ConnPool::pool_mutex` (L18), takes `ConnPool::stats_mutex` at L19
   - `src/net/conn_pool.cpp:31` in `ConnPool::report`: holds `ConnPool::stats_mutex` (L31), takes `ConnPool::pool_mutex` via `ConnPool::drain()` at L33

⏳ **Locks held across blocking calls** (latency, and deadlock if the other side needs the lock):
- `src/net/conn_pool.cpp:34` in `ConnPool::report`: `send()` while holding `ConnPool::stats_mutex`

**Acquisition order** (A → B: B is taken while A is held):
- `ConnPool::pool_mutex` → `ConnPool::stats_mutex`: 1 place, e.g. `src/net/conn_pool.cpp:19` in `ConnPool::rebalance`
- `ConnPool::stats_mutex` → `ConnPool::pool_mutex`: 1 place, e.g. `src/net/conn_pool.cpp:33` in `ConnPool::report` via `ConnPool::drain()`

_Heuristic: locks matched by name (members qualified by class), order taken inside each function plus one call level; aliases, lock hierarchies and runtime conditions are not modelled._
