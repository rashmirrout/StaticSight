### 🧩 SYMBOL CONTRACT: `zero_copy_allocate`
_Sources: GNU Global; declarations via ctags._
- **Declaration:** `src/memory/pool.hpp:13` — `uint8_t * mem::zero_copy_allocate(size_t size)`
- **Definition:** `src/memory/pool.cpp:6-8` — `uint8_t * mem::zero_copy_allocate(size_t size)`

**📜 Doc comment** (`src/memory/pool.hpp:13`):
> @brief Allocates memory directly from the hardware ring buffer.
> @pre size must be greater than zero.
> @warning Every allocation MUST be paired with release_buffer()
> on all execution paths to prevent ring exhaustion.

**⚖️ Obligations / preconditions:**
- @pre size must be greater than zero.
- @warning Every allocation MUST be paired with release_buffer() on all execution paths to prevent ring exhaustion.

**Body** (`src/memory/pool.cpp:6-8`):
```cpp
 6 | uint8_t* zero_copy_allocate(size_t size) {
 7 |     return static_cast<uint8_t*>(std::malloc(size));
 8 | }
```
