### 🧩 SYMBOL CONTRACT: `release_buffer`
_Sources: GNU Global; declarations via ctags._
- **Declaration:** `src/memory/pool.hpp:16` — `void mem::release_buffer(uint8_t * buffer)`
- **Definition:** `src/memory/pool.cpp:10-12` — `void mem::release_buffer(uint8_t * buffer)`
- **Qualifiers:** `noexcept`

**📜 Doc comment** (`src/memory/pool.hpp:16`):
> Returns a buffer obtained from zero_copy_allocate() to the ring.

**Body** (`src/memory/pool.cpp:10-12`):
```cpp
 10 | void release_buffer(uint8_t* buffer) noexcept {
 11 |     std::free(buffer);
 12 | }
```
