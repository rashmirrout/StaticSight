### 🚨 STATIC AUDIT: `src/router.cpp` (cppcheck 2.18.3)
2 findings (1 error, 1 style); 1 on changed lines.
1. ✏️ **L13** `[error: memleak]` Memory leak: buffer (CWE-401)
   `return -2;`
2. 🔶 **L9** `[style: constParameterPointer]` Parameter 'p' can be declared as pointer to const (CWE-398)
   `int Router::process_packet(Packet* p) {`

_zero-compile mode: includes are best-effort and missing-include diagnostics are suppressed. ✏️ = on a changed line, 🔶 = inside a changed function._
