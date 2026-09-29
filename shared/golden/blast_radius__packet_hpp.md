### 💥 BLAST RADIUS: `src/net/packet.hpp`
- **Direct includers:** 7 files; **transitive:** 3 more files (depth 2)
- **Translation units affected:** 8 of 13 source files (62%); headers affected: 2
- **By directory:** `src/` (5), `src/net/` (2), `src/enc/` (1), `src/storage/` (1), `tests/` (1)

**Direct includers:**
- `src/enc/bom_utf8.cpp:1` `#include "net/packet.hpp"`
- `src/include_chain.hpp:2` `#include "net/packet.hpp"`
- `src/net/listener.cpp:2` `#include "net/packet.hpp"`
- `src/net/socket.cpp:1` `#include "net/packet.hpp"`
- `src/new_feature.cpp:1` `#include "net/packet.hpp"`
- `src/router.hpp:3` `#include "net/packet.hpp"`
- `src/storage/wal.cpp:1` `#include "net/packet.hpp"`

**Transitive includers:**
- `src/metrics.cpp` (depth 2)
- `src/router.cpp` (depth 2)
- `tests/test_router.cpp` (depth 2)

_High-fan-out header: macro, inline, template or layout changes here recompile and can alter many modules._
