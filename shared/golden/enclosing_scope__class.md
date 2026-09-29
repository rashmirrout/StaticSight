### 📦 ENCLOSING SCOPE: `Router` (class)
- **File:** `src/router.hpp` L5-21 (17 lines)
```cpp
  5 | class Router {
  6 | public:
  7 |     /**
  8 |      * @brief Ingests an inbound network packet.
  9 |      * @pre Parameter p must be non-null and pre-validated by the listener.
 10 |      * @return 0 on success, negative value on failure.
 11 |      * @note Thread-safe. Acquires route_mutex internally.
 12 |      */
 13 |     int process_packet(Packet* p);
 14 |     void reconfigure_routes(int count);
 15 |     int get_route_count() const;
 16 |     void reset();
 17 | 
 18 | private:
>19 |     mutable std::mutex route_mutex;
 20 |     int route_count = 0;
 21 | };
```
