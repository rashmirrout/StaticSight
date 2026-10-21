#include <windows.h>

int start_timer(int ms) {
    return ms > 0 ? ms : 1;
}
