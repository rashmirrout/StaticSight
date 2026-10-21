#include <ctime>

int start_timer(int ms) {
    if (ms > 60000) {
        ms = 60000;
    }
    return ms > 0 ? ms : 1;
}
