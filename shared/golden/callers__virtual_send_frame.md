### 📞 UPSTREAM CALLERS: `send_frame`
Found 2 call sites in 1 file (source: GNU Global).
Returns `int`.

**`src/net/transport.cpp`**
1. L11 in `TlsTransport::send_frame` — result used
   `return TcpTransport::send_frame(data, len);`
2. L15 in `flush_all` — result used
   `return t.send_frame(data, len);`

ℹ️ `send_frame` is virtual (`TcpTransport::send_frame`, `TlsTransport::send_frame`, `Transport::send_frame`): calls through a base pointer reach every override. `get_impact("send_frame")` resolves them through the class hierarchy.
