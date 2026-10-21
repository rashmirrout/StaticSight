#pragma once
#include <cstddef>

/// Abstract transport. Every implementation MUST be thread-safe.
class Transport {
public:
    virtual ~Transport() = default;
    virtual int send_frame(const char* data, size_t len) = 0;
    virtual void close() {}
};

class TcpTransport : public Transport {
public:
    int send_frame(const char* data, size_t len) override;
    void close() override;
};

class TlsTransport : public TcpTransport {
public:
    int send_frame(const char* data, size_t len) override;
};
