### 📦 CONTEXT PACK: `decode_msg`
_Code graph up to date (28 files)._
- **Where:** `src/net/proto.cpp:16-28` (13 lines)
- **Signature:** `int decode_msg(const char * in,MsgType * t)`

**Logic** (branch skeleton)
Paths: 2 returns, 0 throws (1 early exit), 0 loops.
```text
[L16] ENTRY int decode_msg(const char* in, MsgType* t) {
├── [L17] IF (in == nullptr)
│   ├── [L18] 🛑 RETURN -1
├── [L20] SWITCH (in[0])
│   ├── [L21] CASE 'H'
│   ├── [L22] CASE 'D'
│   ├── [L23] CASE 'A'
│   ├── [L24] CASE 'C'
├── [L27] ↩ RETURN -1
```
_✏️ changed in diff · 🛑 early exit · ⚠️ heuristic (comment/string-stripped text + brace depth, not a compiler)._

**Callers** (1)
- `TEST(Proto,RoundTrip)` — `tests/test_proto.cpp:9` — ⚠️ result ignored

**Calls**
- In the repository: `log_error` (`src/log.hpp:4`)

**Types in the signature:** `MsgType` (enum, `src/net/proto.hpp:3`)

**Tests reaching it:** `TEST(Proto,RoundTrip)` (`tests/test_proto.cpp:5`)

**Recent history:** `c945b10` 2024-01-01 🐞 fix: crash on null buffer in decode_msg; `d4d7f9b` 2024-01-01 base
