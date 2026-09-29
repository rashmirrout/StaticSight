#include <mutex>
#include <sys/socket.h>

class ConnPool {
public:
    void rebalance();
    void drain();
private:
    std::mutex pool_mutex;
    std::mutex stats_mutex;
    int active = 0;
    int drained = 0;
};

// Lock order: pool_mutex, then stats_mutex.
void ConnPool::rebalance() {
    std::lock_guard<std::mutex> pool(pool_mutex);
    std::lock_guard<std::mutex> stats(stats_mutex);
    active = 0;
    drained = 0;
}

void ConnPool::drain() {
    std::lock_guard<std::mutex> pool(pool_mutex);
    active--;
}
