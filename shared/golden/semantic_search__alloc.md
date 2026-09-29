### 🔎 SEMANTIC SEARCH: "check that a memory allocation succeeded before using the buffer"
Index: 21 files, 48 chunks (test-hash@builtin). Index is up to date.
1. `src/memory/pool.hpp:5-18` — namespace `mem` (cpp) · 0.20 · semantic+keyword
   ```cpp
    5 | namespace mem {
    6 | 
    7 | /**
    8 |  * @brief Allocates memory directly from the hardware ring buffer.
    9 |  * @pre size must be greater than zero.
   10 |  * @warning Every allocation MUST be paired with release_buffer()
      | … 8 more lines
   ```
2. `src/net/socket.cpp:14-17` — function `packet_count` (cpp) · 0.15 · semantic+keyword
   ```cpp
   14 | // A Packet mentioned in a comment only; no memory operation here.
   15 | int packet_count(const Packet* list, int n) {
   16 |     return n;
   17 | }
   ```
3. `src/memory/pool.cpp:1-2` — file (cpp) · 0.13 · semantic+keyword
   ```cpp
   1 | #include "memory/pool.hpp"
   2 | #include <cstdlib>
   ```
4. `src/memory/pool.cpp:10-12` — function `mem::release_buffer` (cpp) · 0.07 · semantic+keyword
   ```cpp
   10 | void release_buffer(uint8_t* buffer) noexcept {
   11 |     std::free(buffer);
   12 | }
   ```
5. `src/router.cpp:1-7` — file (cpp) · 0.11 · semantic+keyword
   ```cpp
   1 | #include "router.hpp"
   2 | #include "memory/pool.hpp"
   3 | #include <cstdlib>
   4 | #include <cstring>
   5 | 
   6 | // decoy: if (fake) { return; } lives inside a comment
     | … 1 more lines
   ```

_Scores are cosine similarity from the local embedding model (higher is closer); results are ranked by fusing semantic and keyword matches. Verify the code before asserting._
