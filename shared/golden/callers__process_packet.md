### 📞 UPSTREAM CALLERS: `process_packet`
Found 4 call sites in 3 files (source: GNU Global).
Returns `int`; ⚠️ 3 caller(s) ignore the result — check they tolerate new error values.

**`src/net/listener.cpp`**
1. L9 in `Listener::on_socket_read` — result used
   `int rc = router_->process_packet(&raw);`
2. L17 in `Listener::dispatch_batch` — ⚠️ result ignored `F75b93d`
   `router_->process_packet(&batch[i]);`
**`src/net/server_loop.cpp`**
3. L9 in `pump_loop` — ⚠️ result ignored `F39b260`
   `g_router.process_packet(&p);`
**`tests/test_router.cpp`**
4. L6 in `test_drop_invalid` — ⚠️ result ignored `F2a070a`
   `r.process_packet(&dummy);`
