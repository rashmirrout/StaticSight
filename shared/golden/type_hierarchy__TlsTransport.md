### 🧬 TYPE HIERARCHY: `TlsTransport`
_Code graph up to date (28 files)._
```text
Transport  (src/net/transport.hpp:5)
└── TcpTransport  (src/net/transport.hpp:12)
    └── TlsTransport  ◀ this type  (src/net/transport.hpp:18)
```

**Virtual methods**
| Method | Introduced in | Overridden in |
|---|---|---|
| `close` | `Transport` `src/net/transport.hpp:9` | `TcpTransport` `src/net/transport.hpp:15` |
| `send_frame` | `Transport` (pure) `src/net/transport.hpp:8` | `TcpTransport` `src/net/transport.hpp:14`, `TlsTransport` `src/net/transport.hpp:20` |
| `~Transport` | `Transport` `src/net/transport.hpp:7` | — |

_A signature change to a virtual method must be mirrored in every override; a call through a base pointer or reference can reach any of them._
