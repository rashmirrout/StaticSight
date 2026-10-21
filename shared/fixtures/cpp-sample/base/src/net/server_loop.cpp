#include "router.hpp"
#include "net/packet.hpp"
#include <thread>

static Router g_router;

static void pump_loop() {
    Packet p{};
    g_router.process_packet(&p);
}

int run_server() {
    std::thread worker(pump_loop);
    worker.join();
    return 0;
}
