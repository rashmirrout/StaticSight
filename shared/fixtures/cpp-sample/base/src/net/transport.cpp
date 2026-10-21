#include "net/transport.hpp"

int TcpTransport::send_frame(const char* data, size_t len) {
    return len > 0 && data != nullptr ? static_cast<int>(len) : -1;
}

void TcpTransport::close() {
}

int TlsTransport::send_frame(const char* data, size_t len) {
    return TcpTransport::send_frame(data, len);
}

int flush_all(Transport& t, const char* data, size_t len) {
    return t.send_frame(data, len);
}
