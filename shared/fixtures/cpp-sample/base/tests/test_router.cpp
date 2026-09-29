#include <router.hpp>

void test_drop_invalid() {
    Router r;
    Packet dummy{};
    r.process_packet(&dummy);
}
