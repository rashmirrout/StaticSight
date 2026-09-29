#include "memory/pool.hpp"
#include <cstdlib>

namespace mem {

uint8_t* zero_copy_allocate(size_t size) {
    return static_cast<uint8_t*>(std::malloc(size));
}

void release_buffer(uint8_t* buffer) noexcept {
    std::free(buffer);
}

}  // namespace mem
