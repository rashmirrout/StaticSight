### 📄 FILE-LEVEL CONTEXT: `src/router.cpp` L7
_No enclosing function/class found by ctags (global scope, preprocessor block, or code ctags could not parse)._
```cpp
  1 | #include "router.hpp"
  2 | #include "memory/pool.hpp"
  3 | #include <cstdlib>
  4 | #include <cstring>
  5 | 
  6 | // decoy: if (fake) { return; } lives inside a comment
> 7 | static const char* kBanner = "if (x) { return y; }";
  8 | 
  9 | int Router::process_packet(Packet* p) {
 10 |     std::lock_guard<std::mutex> lock(route_mutex);
 11 |     uint8_t* buffer = static_cast<uint8_t*>(malloc(p->len));
 12 |     if (!p->is_encrypted) {
 13 |         return -2;
 14 |     }
 15 |     if (buffer == nullptr) {
 16 |         return -1;
 17 |     }
 18 |     memcpy(buffer, p->payload, p->len);
 19 |     for (int i = 0; i < route_count; ++i) {
```
