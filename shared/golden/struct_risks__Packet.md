### ⚠️ LOW-LEVEL MEMORY USAGES: `Packet`
Defined at: `src/net/packet.hpp:4-10`.
Modifying the size, padding or member order of `Packet` may break 4 sites (out of 16 references):

1. `src/net/socket.cpp:6` in `send_packet` — 🌐 raw I/O, 📏 size/offset assumption, 🎭 type punning
   `return send(fd, reinterpret_cast<const char*>(&pkt), sizeof(Packet), 0);`
2. `src/net/socket.cpp:9` in `copy_packet` — 🧬 raw memory op, 📏 size/offset assumption (operation within ±2 lines)
   `void copy_packet(uint8_t* dst, const Packet& pkt) {`
3. `src/storage/wal.cpp:5` in `wal_append` — 🧬 raw memory op, 📏 size/offset assumption
   `memcpy(wal_ptr, &p, sizeof(Packet));`
4. `src/storage/wal.cpp:9` in `wal_replay` — 🧬 raw memory op, 📏 size/offset assumption
   `memcpy(&out, wal_ptr, sizeof(Packet));`

**Why it matters:**
- 🌐 **raw I/O:** struct bytes sent/received/persisted directly: size, padding or member order changes break the wire/disk format and peers built from older code.
- 🧬 **raw memory op:** memcpy/memmove/memset/memcmp over the object: layout changes shift offsets, and memcmp also compares padding bytes.
- 📏 **size/offset assumption:** sizeof/offsetof/alignof values change with the layout; buffers, protocol lengths and array math sized from them shift silently.
- 🎭 **type punning:** reinterpret_cast / C-style pointer cast / bit_cast reinterprets raw bytes: the layout must match the producer exactly.
