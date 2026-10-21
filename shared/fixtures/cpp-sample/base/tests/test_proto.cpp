#include "net/proto.hpp"

#define TEST(suite, name) void suite##_##name()

TEST(Proto, RoundTrip) {
    char buf[4];
    MsgType t;
    encode_msg(MsgType::Data, buf);
    decode_msg(buf, &t);
}

void test_names() {
    msg_name(MsgType::Ack);
}
