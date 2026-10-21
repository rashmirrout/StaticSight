### 🧩 SWITCH COVERAGE: `MsgType`
_Code graph up to date (28 files)._
Defined at `src/net/proto.hpp:3` with 5 values: `Ack`, `Close`, `Data`, `Hello`, `Ping`.
2 switches, 1 with missing values:
- ✅ `src/net/proto.cpp:6` in `encode_msg`: all 5 values handled
- ⚠️ `src/net/proto.cpp:31` in `msg_name`: missing `Ping`; handled by `default:` — check that is right `F7b1502`
