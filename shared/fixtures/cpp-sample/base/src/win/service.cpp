#include <windows.h>

HRESULT OpenConfig(_In_ LPCWSTR path, _Out_ DWORD* size)
{
    HANDLE h = CreateFileW(path, GENERIC_READ, 0, NULL, OPEN_EXISTING, 0, NULL);
    if (h == INVALID_HANDLE_VALUE) {
        return E_FAIL;
    }
    if (!GetFileSize(h, size)) {
        return E_FAIL;
    }
    CloseHandle(h);
    return S_OK;
}
