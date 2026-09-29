#include "net/packet.hpp"

int bom_packet_len(const Packet& p) {
    if (p.len > 64) {
        return -1;
    }
    return p.len;
}
