#pragma once

enum class MsgType { Hello, Data, Ack, Close };

int encode_msg(MsgType t, char* out);
int decode_msg(const char* in, MsgType* t);
const char* msg_name(MsgType t);
