### 🩺 EDIT CHECK: 2 changed functions vs HEAD
- `new_feature` (`src/new_feature.cpp:3`): new
- `wal_replay` (`src/storage/wal.cpp:8`): new

✅ The quick checks found nothing: exit paths release what they allocate, cppcheck is clean on the changed lines, callers match changed signatures, switches cover changed enums, platform twins agree.

_Checks: exit-path leaks, cppcheck on changed lines, callers of changed signatures outside the diff, switch coverage of enums used in the change, unchanged platform twins. Next: `verify_finding("F…")`, then `review_changes()` before committing._
