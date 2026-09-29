#pragma once
#include <mutex>
#include "net/packet.hpp"

class Router {
public:
    /**
     * @brief Ingests an inbound network packet.
     * @pre Parameter p must be non-null and pre-validated by the listener.
     * @return 0 on success, negative value on failure.
     * @note Thread-safe. Acquires route_mutex internally.
     */
    int process_packet(Packet* p);
    void reconfigure_routes(int count);
    int get_route_count() const;
    void reset();

private:
    mutable std::mutex route_mutex;
    int route_count = 0;
};
