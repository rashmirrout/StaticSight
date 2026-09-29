#include "router.hpp"
#include "net/packet.hpp"

class Listener {
public:
    explicit Listener(Router* r) : router_(r) {}

    void on_socket_read(Packet& raw) {
        int rc = router_->process_packet(&raw);
        if (rc != 0) {
            return;
        }
    }

    void dispatch_batch(Packet* batch, int n) {
        for (int i = 0; i < n; ++i) {
            router_->process_packet(&batch[i]);
        }
    }

private:
    Router* router_;
};
