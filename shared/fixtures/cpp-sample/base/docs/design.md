# Router design

The router receives packets from the listener and forwards them to the right queue.

## Retry policy

Transient network failures are retried with exponential backoff (see `tools/retry.py`).
Never retry authentication errors.

## Write-ahead log format

Each record is the raw bytes of a `Packet` struct. Changing the struct layout breaks replay of old logs,
so the format must be versioned.
