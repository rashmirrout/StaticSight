### 🔍 LOG ORIGIN: "decode_msg: unknown message type 'Z' from peer 10.0.0.7"
Searched 2 literal fragments: "decode_msg: unknown message type", "from peer".
1. `src/net/proto.cpp:26` in `decode_msg` — matches 2 of 2 fragments
   `log_error("decode_msg: unknown message type '%c' from peer %s", in[0], "?");`
   - Called from: `TEST(Proto,RoundTrip)` (`tests/test_proto.cpp:9`)

_Next: `find_entry_paths("<function>")` for how requests reach it, `get_context_pack` for its logic._
