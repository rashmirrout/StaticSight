### 📞 UPSTREAM CALLERS: `process_packet`
Found 1 call site in 1 file (source: GNU Global).
Returns `int`; ⚠️ 1 caller(s) ignore the result — check they tolerate new error values.

**`tests/test_router.cpp`**
1. L6 in `test_drop_invalid` — ⚠️ result ignored
   `r.process_packet(&dummy);`
