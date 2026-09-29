#include "net/packet.hpp"
#include <cstring>
#include <sys/socket.h>

int send_packet(int fd, const Packet& pkt) {
    return send(fd, reinterpret_cast<const char*>(&pkt), sizeof(Packet), 0);
}

void copy_packet(uint8_t* dst, const Packet& pkt) {
    std::memcpy(dst, &pkt,
                sizeof(pkt));
}

// A Packet mentioned in a comment only; no memory operation here.
int packet_count(const Packet* list, int n) {
    return n;
}
