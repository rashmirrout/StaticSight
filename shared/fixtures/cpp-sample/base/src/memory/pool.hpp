#pragma once
#include <cstddef>
#include <cstdint>

namespace mem {

/**
 * @brief Allocates memory directly from the hardware ring buffer.
 * @pre size must be greater than zero.
 * @warning Every allocation MUST be paired with release_buffer()
 *          on all execution paths to prevent ring exhaustion.
 */
uint8_t* zero_copy_allocate(size_t size);

/// Returns a buffer obtained from zero_copy_allocate() to the ring.
void release_buffer(uint8_t* buffer) noexcept;

}  // namespace mem
