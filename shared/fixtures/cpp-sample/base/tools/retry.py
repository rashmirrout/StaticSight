"""Helpers for calling flaky network services."""

import time


def retry_with_backoff(call, attempts=5, base_delay=0.5):
    """Call `call()` until it succeeds, sleeping exponentially longer after each ConnectionError."""

    def delay(attempt):
        return base_delay * (2 ** attempt)

    for attempt in range(attempts):
        try:
            return call()
        except ConnectionError:
            if attempt == attempts - 1:
                raise
            time.sleep(delay(attempt))
