#include "net/packet.hpp"

int new_feature(const Packet& p) {
    if (p.len == 0) {
        throw 1;
    }
    return p.len;
}
