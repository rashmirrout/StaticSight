### 🚨 STATIC AUDIT: `src/win/service.cpp` (cppcheck 2.18.3)
1 finding (1 error); 0 on changed lines.
1. **L10** `[error: resourceLeak]` Resource leak: h (CWE-775)
   `return E_FAIL;`

_MSVC mode: Windows/SAL code detected, cppcheck ran with `--library=windows --platform=win64`; zero-compile mode: includes are best-effort and missing-include diagnostics are suppressed. ✏️ = on a changed line, 🔶 = inside a changed function._
