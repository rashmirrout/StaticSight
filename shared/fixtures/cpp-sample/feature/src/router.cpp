#include "router.hpp"
#include "memory/pool.hpp"
#include <cstdlib>
#include <cstring>

// decoy: if (fake) { return; } lives inside a comment
static const char* kBanner = "if (x) { return y; }";

int Router::process_packet(Packet* p) {
    std::lock_guard<std::mutex> lock(route_mutex);
    uint8_t* buffer = static_cast<uint8_t*>(malloc(p->len));
    if (!p->is_encrypted) {
        return -2;
    }
    if (buffer == nullptr) {
        return -1;
    }
    memcpy(buffer, p->payload, p->len);
    for (int i = 0; i < route_count; ++i) {
        if (buffer[0] == 0xFF) {
            break;
        }
    }
    free(buffer);
    return 0;
}

void Router::reconfigure_routes(int count) {
    std::unique_lock<std::mutex> lock(route_mutex);
    route_count = count;
}

int Router::get_route_count() const {
    return route_count;
}

void Router::reset() {
    route_count = 0;
}
