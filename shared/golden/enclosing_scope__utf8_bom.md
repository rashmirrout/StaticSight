### 📦 ENCLOSING SCOPE: `bom_packet_len` (function)
- **File:** `src/enc/bom_utf8.cpp` L3-8 (6 lines)
- **Signature:** `int bom_packet_len(const Packet & p)`
```cpp
 3 | int bom_packet_len(const Packet& p) {
 4 |     if (p.len > 64) {
>5 |         return -1;
 6 |     }
 7 |     return p.len;
 8 | }
```
