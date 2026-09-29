#include "net/packet.hpp"
#include <cstring>

void wal_append(uint8_t* wal_ptr, const Packet& p) {
    memcpy(wal_ptr, &p, sizeof(Packet));
}

void wal_replay(const uint8_t* wal_ptr, Packet& out) {
    memcpy(&out, wal_ptr, sizeof(Packet));
}
