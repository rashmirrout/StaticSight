### 🌿 BRANCH SKELETON: `OpenConfig` (`src/win/service.cpp` L3-14)
Paths: 3 returns, 0 throws (2 early exits), 0 loops; ⚠️ 1 potential leak path.
```text
[L3] ENTRY HRESULT OpenConfig(_In_ LPCWSTR path, _Out_ DWORD* size)
├── [L5] 📥 ALLOC `h` — HANDLE h = CreateFileW(path, GENERIC_READ, 0, NULL, OPEN_EXISTING, 0, NULL);
├── [L6] IF (h == INVALID_HANDLE_VALUE)
│   ├── [L7] 🛑 RETURN E_FAIL
├── [L9] IF (!GetFileSize(h, size))
│   ├── [L10] 🛑 RETURN E_FAIL ⚠️ early exit; `h` (L5) not released on this path
├── [L12] 📤 RELEASE `h` — CloseHandle(h);
├── [L13] ↩ RETURN S_OK
```
_✏️ changed in diff · 🛑 early exit · ⚠️ heuristic (comment/string-stripped text + brace depth, not a compiler)._
