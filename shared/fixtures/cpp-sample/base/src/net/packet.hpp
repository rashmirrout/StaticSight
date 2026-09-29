#pragma once
#include <cstdint>

struct Packet {
    uint32_t id;
    uint16_t len;
    bool is_encrypted;
    uint8_t payload[64];
};
