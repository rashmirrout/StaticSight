### 🔎 SEMANTIC SEARCH: "retry transient network failures with exponential backoff"
Index: 21 files, 48 chunks (test-hash@builtin). Index is up to date.
1. `docs/design.md:5-8` — section `Retry policy` (markdown) · 0.61 · semantic+keyword
   ```markdown
   5 | ## Retry policy
   6 | 
   7 | Transient network failures are retried with exponential backoff (see `tools/retry.py`).
   8 | Never retry authentication errors.
   ```
2. `tools/retry.py:6-7` — function `retry_with_backoff` (python) · 0.31 · semantic+keyword
   ```python
   6 | def retry_with_backoff(call, attempts=5, base_delay=0.5):
   7 |     """Call `call()` until it succeeds, sleeping exponentially longer after each ConnectionError."""
   ```
3. `tools/retry.py:1-3` — file (python) · 0.22 · semantic+keyword
   ```python
   1 | """Helpers for calling flaky network services."""
   2 | 
   3 | import time
   ```
4. `tools/router.yaml:1-5` — window (yaml) · 0.18 · semantic+keyword
   ```yaml
   1 | router:
   2 |   queues: 4
   3 |   retry:
   4 |     attempts: 5
   5 |     backoff_seconds: 0.5
   ```
5. `src/router.hpp:5-21` — class `Router` (cpp) · -0.03 · semantic+keyword
   ```cpp
    5 | class Router {
    6 | public:
    7 |     /**
    8 |      * @brief Ingests an inbound network packet.
    9 |      * @pre Parameter p must be non-null and pre-validated by the listener.
   10 |      * @return 0 on success, negative value on failure.
      | … 11 more lines
   ```

_Scores are cosine similarity from the local embedding model (higher is closer); results are ranked by fusing semantic and keyword matches. Verify the code before asserting._
