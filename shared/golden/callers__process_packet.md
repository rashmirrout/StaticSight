### 📞 UPSTREAM CALLERS: `process_packet`
Found 3 call sites in 2 files (source: GNU Global).
Returns `int`; ⚠️ 2 caller(s) ignore the result — check they tolerate new error values.

**`src/net/listener.cpp`**
1. L9 in `Listener::on_socket_read` — result used
   `int rc = router_->process_packet(&raw);`
2. L17 in `Listener::dispatch_batch` — ⚠️ result ignored
   `router_->process_packet(&batch[i]);`
**`tests/test_router.cpp`**
3. L6 in `test_drop_invalid` — ⚠️ result ignored
   `r.process_packet(&dummy);`
