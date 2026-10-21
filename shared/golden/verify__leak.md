### 🔎 VERIFY `F7a0cc5`: leak_path
**Claim** (medium): return at line 13 leaves `buffer` (L11) unreleased
**Where:** `src/router.cpp:13` in `Router::process_packet`
**Status:** ✅ Reproduced: re-running `get_context_pack(max_chars=3000, target="src/router.cpp:13")` reports the same finding.

```text
 10 |     std::lock_guard<std::mutex> lock(route_mutex);
 11 |     uint8_t* buffer = static_cast<uint8_t*>(malloc(p->len));
 12 |     if (!p->is_encrypted) {
>13 |         return -2;
 14 |     }
 15 |     if (buffer == nullptr) {
 16 |         return -1;
```
**Before reporting it, rule out:**
- The resource is released by an RAII owner, a `goto cleanup`, or a callee that takes ownership.
- The allocation failed on this path (null), so there is nothing to release.

_A finding is evidence, not proof: report it with its ID and what you checked._
