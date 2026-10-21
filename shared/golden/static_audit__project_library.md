### 🚨 STATIC AUDIT: `src/net/proto.cpp` (cppcheck 2.18.3)
1 finding (1 error); 1 on changed lines.
1. ✏️ **L43** `[error: memleak]` Memory leak: ring (CWE-401) `F6a97a8`
   `return -1;`

_project allocators from contract comments: `mem::zero_copy_allocate`/`mem::release_buffer`; zero-compile mode: includes are best-effort and missing-include diagnostics are suppressed. ✏️ = on a changed line, 🔶 = inside a changed function._
