### 📦 ENCLOSING SCOPE: `Router::process_packet` (function)
- **File:** `src/router.cpp` L9-26 (18 lines)
- **Signature:** `int Router::process_packet(Packet * p)`
- **Parent:** class `Router`
```cpp
  9 | int Router::process_packet(Packet* p) {
 10 |     std::lock_guard<std::mutex> lock(route_mutex);
 11 |     uint8_t* buffer = static_cast<uint8_t*>(malloc(p->len));
 12 |     if (!p->is_encrypted) {
>13 |         return -2;
 14 |     }
 15 |     if (buffer == nullptr) {
 16 |         return -1;
 17 |     }
 18 |     memcpy(buffer, p->payload, p->len);
 19 |     for (int i = 0; i < route_count; ++i) {
 20 |         if (buffer[0] == 0xFF) {
 21 |             break;
 22 |         }
 23 |     }
 24 |     free(buffer);
 25 |     return 0;
 26 | }
```
