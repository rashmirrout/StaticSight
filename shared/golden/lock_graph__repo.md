### 🔐 LOCK GRAPH: repository
3 locks taken by 5 functions; 2 order edges (A → B: B is taken while A is held).

```mermaid
graph LR
  L1["ConnPool::pool_mutex"]
  L2["ConnPool::stats_mutex"]
  L1 -->|"rebalance"| L2
  L2 -->|"report via drain"| L1
```

| Lock | Taken in | Then takes |
|---|---|---|
| `ConnPool::pool_mutex` | `ConnPool::drain`, `ConnPool::rebalance` | `ConnPool::stats_mutex` |
| `ConnPool::stats_mutex` | `ConnPool::rebalance`, `ConnPool::report` | `ConnPool::pool_mutex` |
| `Router::route_mutex` | `Router::process_packet`, `Router::reconfigure_routes` | — |

_Use `track_lock_order` for cycles, locks taken twice and locks held across blocking calls._
