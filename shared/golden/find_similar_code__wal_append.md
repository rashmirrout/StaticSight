### 🧬 SIMILAR CODE: `src/storage/wal.cpp:5`
Source: function `wal_append` (L4-6). Index: 21 files, 48 chunks (test-hash@builtin). Index is up to date.
1. `src/storage/wal.cpp:8-10` — function `wal_replay` (cpp) · 0.86 · very similar
   ```cpp
    8 | void wal_replay(const uint8_t* wal_ptr, Packet& out) {
    9 |     memcpy(&out, wal_ptr, sizeof(Packet));
   10 | }
   ```
2. `src/net/socket.cpp:9-12` — function `copy_packet` (cpp) · 0.43 · similar
   ```cpp
    9 | void copy_packet(uint8_t* dst, const Packet& pkt) {
   10 |     std::memcpy(dst, &pkt,
   11 |                 sizeof(pkt));
   12 | }
   ```
3. `src/enc/bom_utf8.cpp:3-8` — function `bom_packet_len` (cpp) · 0.40 · similar
   ```cpp
   3 | int bom_packet_len(const Packet& p) {
   4 |     if (p.len > 64) {
   5 |         return -1;
   6 |     }
   7 |     return p.len;
   8 | }
   ```

_near-duplicate ≥ 0.92, very similar ≥ 0.85 (cosine). Check whether a fix in the source also applies to these places._
