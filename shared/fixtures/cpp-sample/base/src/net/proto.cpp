#include "net/proto.hpp"
#include "log.hpp"

int encode_msg(MsgType t, char* out) {
    switch (t) {
    case MsgType::Hello: out[0] = 'H'; return 1;
    case MsgType::Data: out[0] = 'D'; return 1;
    case MsgType::Ack: out[0] = 'A'; return 1;
    case MsgType::Close: out[0] = 'C'; return 1;
    }
    return -1;
}

int decode_msg(const char* in, MsgType* t) {
    switch (in[0]) {
    case 'H': *t = MsgType::Hello; return 0;
    case 'D': *t = MsgType::Data; return 0;
    case 'A': *t = MsgType::Ack; return 0;
    case 'C': *t = MsgType::Close; return 0;
    }
    log_error("decode_msg: unknown message type '%c' from peer %s", in[0], "?");
    return -1;
}

const char* msg_name(MsgType t) {
    switch (t) {
    case MsgType::Hello: return "hello";
    case MsgType::Data: return "data";
    case MsgType::Ack: return "ack";
    case MsgType::Close: return "close";
    default: return "?";
    }
}
