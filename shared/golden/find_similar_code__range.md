### 🧬 SIMILAR CODE: `src/net/socket.cpp:9-12`
Source: lines 9-12 (L9-12). Index: 21 files, 48 chunks (test-hash@builtin). Index is up to date.
1. `src/net/socket.cpp:5-7` — function `send_packet` (cpp) · 0.58 · similar
   ```cpp
   5 | int send_packet(int fd, const Packet& pkt) {
   6 |     return send(fd, reinterpret_cast<const char*>(&pkt), sizeof(Packet), 0);
   7 | }
   ```
2. `src/storage/wal.cpp:8-10` — function `wal_replay` (cpp) · 0.44 · similar
   ```cpp
    8 | void wal_replay(const uint8_t* wal_ptr, Packet& out) {
    9 |     memcpy(&out, wal_ptr, sizeof(Packet));
   10 | }
   ```
3. `src/net/packet.hpp:4-10` — struct `Packet` (cpp) · 0.39 · similar
   ```cpp
   4 | struct Packet {
   5 |     uint32_t id;
   6 |     uint16_t len;
   7 |     bool is_encrypted;
   8 |     uint32_t checksum;
   9 |     uint8_t payload[64];
     | … 1 more lines
   ```

_near-duplicate ≥ 0.92, very similar ≥ 0.85 (cosine). Check whether a fix in the source also applies to these places._
