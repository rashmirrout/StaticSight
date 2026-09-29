### 🔎 SEMANTIC SEARCH: "copy packet bytes"
Index: 21 files, 48 chunks (test-hash@builtin). Index is up to date.
1. `src/storage/wal.cpp:4-6` — function `wal_append` (cpp) · 0.18 · semantic+keyword
   ```cpp
   4 | void wal_append(uint8_t* wal_ptr, const Packet& p) {
   5 |     memcpy(wal_ptr, &p, sizeof(Packet));
   6 | }
   ```
2. `src/storage/wal.cpp:8-10` — function `wal_replay` (cpp) · 0.18 · semantic+keyword
   ```cpp
    8 | void wal_replay(const uint8_t* wal_ptr, Packet& out) {
    9 |     memcpy(&out, wal_ptr, sizeof(Packet));
   10 | }
   ```

_Scores are cosine similarity from the local embedding model (higher is closer); results are ranked by fusing semantic and keyword matches. Verify the code before asserting._
