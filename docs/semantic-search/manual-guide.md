<!-- nav:top -->
📚 [Documentation](../README.md) › [Semantic search](README.md) › **Manual guide**
<!-- /nav:top -->

# Semantic search from the command line

This guide shows how to use semantic search yourself, without an AI agent. Every output below is a real run on the
StaticSight test repository (`shared/fixtures/make_fixture.py /tmp/cpp-sample`); only timings differ on your machine.

<!-- nav:toc -->
**On this page:** [1. Install the packages (once per machine)](#1-install-the-packages-once-per-machine) · [2. Check the setup](#2-check-the-setup) · [3. Download the model (once per user)](#3-download-the-model-once-per-user) · [4. Build the index](#4-build-the-index) · [5. Search](#5-search) · [6. Find similar code](#6-find-similar-code) · [7. Keep it fresh](#7-keep-it-fresh) · [8. The same thing the agent sees](#8-the-same-thing-the-agent-sees) · [9. TypeScript](#9-typescript) · [Troubleshooting](#troubleshooting)
<!-- /nav:toc -->

The commands assume the `staticsight` alias from [Getting started](../getting-started.md#5-make-a-short-command):

```text
alias staticsight="python3 $SS_HOME/staticsight.py"            # Linux/macOS; SS_HOME = your StaticSight clone
function staticsight { py -3 "$env:SS_HOME\staticsight.py" @args }   # Windows PowerShell
```

Run every command **from inside the repository you want to search** (any subfolder works). StaticSight walks up to the
nearest folder that holds `.staticsight/` or `.git`. To search another repository, add `--repo PATH` to any command.

## 1. Install the packages (once per machine)

Semantic search needs three extra Python packages: `onnxruntime`, `tokenizers` and `numpy`. Everything else in
StaticSight works without them.

```text
python3 $SS_HOME/staticsight.py --install --semantic
```

The script shows the exact `pip` command and asks before running it. If your OS Python refuses (`externally-managed-environment`,
PEP 668), it prints the two safe alternatives: a private virtual environment (recommended), or `pip --user`.

## 2. Check the setup

```bash
staticsight doctor
```

The end of the report covers semantic search:

```text
Semantic search (optional):
  OK   packages  onnxruntime, tokenizers, numpy
  OK   model     jina-code@516f4baf13dec4ddddda8631e019b5737c8bc250 (/root/.cache/staticsight/models/jina-code/516f4baf13dec4ddddda8631e019b5737c8bc250)
```

## 3. Download the model (once per user)

The model (`jinaai/jina-embeddings-v2-base-code`, about 165 MB) is downloaded once, verified with sha256, and shared
by every repository. The first search downloads it automatically; doing it up front avoids waiting later.

```bash
staticsight model download
staticsight model status
```

```text
model jina-code@516f4baf13dec4ddddda8631e019b5737c8bc250 in /root/.cache/staticsight/models/jina-code/516f4baf13dec4ddddda8631e019b5737c8bc250: OK (verified)
```

Offline machine? Run `model download` on a connected machine, copy the `models/` folder into the same place, or point
`STATICSIGHT_EMBED_MODEL_DIR` at it. `STATICSIGHT_SEMANTIC_ALLOW_DOWNLOAD=0` forbids downloads entirely.

## 4. Build the index

```bash
staticsight index status
```

```text
### 🧠 SEMANTIC INDEX
- **State:** not built yet (built automatically on the first semantic_search, or call refresh_semantic_index)
- **Model:** jina-code@516f4baf13dec4ddddda8631e019b5737c8bc250
- **Database:** `/tmp/cpp-sample/.staticsight/semantic.db` (repository)
```

```bash
staticsight index build
```

```text
Semantic index for /tmp/cpp-sample
  … scanning files
  … embedding 0/21 files
re-indexed 21 changed file(s), removed 0; embedded 48 new chunk(s)
```

Progress lines go to stderr every few seconds. A large repository takes a while the first time (NMAgent: 3,230 files,
64.6k chunks, 54 minutes on a 16-thread CPU); code files are embedded first, and the partial index is already searchable.
Later builds only re-embed what changed.

```bash
staticsight index status
```

```text
### 🧠 SEMANTIC INDEX
- **State:** ready (last refresh 26s ago, HEAD a8f644ad5c)
- **Content:** 21 files, 48 chunks, 48 vectors; skipped: none
- **Languages:** cpp (18), markdown (1), python (1), yaml (1)
- **Model:** jina-code@516f4baf13dec4ddddda8631e019b5737c8bc250
- **Database:** `/tmp/cpp-sample/.staticsight/semantic.db` (repository)
```

## 5. Search

Describe what the code **does**, in plain words:

```bash
staticsight search "retry failed network calls" --top 3
```

````text
### 🔎 SEMANTIC SEARCH: "retry failed network calls"
Index: 21 files, 48 chunks (jina-code@516f4baf13dec4ddddda8631e019b5737c8bc250). Refreshed before searching: re-indexed 1 changed file(s), removed 0; embedded 0 new chunk(s).
1. `tools/retry.py:1-3` — file (python) · 0.74 · semantic+keyword
   ```python
   1 | """Helpers for calling flaky network services."""
   2 | 
   3 | import time
   ```
2. `tools/retry.py:6-7` — function `retry_with_backoff` (python) · 0.72 · semantic+keyword
   ```python
   6 | def retry_with_backoff(call, attempts=5, base_delay=0.5):
   7 |     """Call `call()` until it succeeds, sleeping exponentially longer after each ConnectionError."""
   ```
3. `docs/design.md:5-8` — section `Retry policy` (markdown) · 0.68 · semantic+keyword
   ```markdown
   5 | ## Retry policy
   6 | 
   7 | Transient network failures are retried with exponential backoff (see `tools/retry.py`).
   8 | Never retry authentication errors.
   ```

_Scores are cosine similarity from the local embedding model (higher is closer); results are ranked by fusing semantic and keyword matches. Verify the code before asserting._
````

How to read a result:
- **`file:start-end`**: where the code is.
- **kind and name**: `function retry_with_backoff`, `section Retry policy`, `window` (a block of lines from a file without structure), `file` (top of a file).
- **score**: cosine similarity. 1.0 means the same meaning, around 0 means unrelated. The last digit can differ
  between machines and index builds (tiny floating-point differences in the model runtime).
- **`semantic`, `keyword` or `semantic+keyword`**: which pass found it. Results are ordered by the fused rank, not only by score.

Narrow the search with filters:

```bash
staticsight search "copy packet bytes" --language cpp --kind function --top 3
```

````text
### 🔎 SEMANTIC SEARCH: "copy packet bytes"
Index: 21 files, 48 chunks (jina-code@516f4baf13dec4ddddda8631e019b5737c8bc250). Index is up to date.
1. `src/net/socket.cpp:9-12` — function `copy_packet` (cpp) · 0.76 · semantic+keyword
   ```cpp
    9 | void copy_packet(uint8_t* dst, const Packet& pkt) {
   10 |     std::memcpy(dst, &pkt,
   11 |                 sizeof(pkt));
   12 | }
   ```
2. `src/storage/wal.cpp:8-10` — function `wal_replay` (cpp) · 0.56 · semantic+keyword
   ```cpp
    8 | void wal_replay(const uint8_t* wal_ptr, Packet& out) {
    9 |     memcpy(&out, wal_ptr, sizeof(Packet));
   10 | }
   ```
3. `src/storage/wal.cpp:4-6` — function `wal_append` (cpp) · 0.56 · semantic+keyword
   ```cpp
   4 | void wal_append(uint8_t* wal_ptr, const Packet& p) {
   5 |     memcpy(wal_ptr, &p, sizeof(Packet));
   6 | }
   ```

_Scores are cosine similarity from the local embedding model (higher is closer); results are ranked by fusing semantic and keyword matches. Verify the code before asserting._
````

| Option | Meaning | Example |
|---|---|---|
| `--top N` | number of results (1-30, default 10) | `--top 5` |
| `--glob G` | only paths matching the glob | `--glob "src/net/*"` |
| `--language L` | only one language | `--language cpp`, `python`, `markdown`, `yaml` |
| `--kind K` | only one kind of chunk | `--kind function`, `class`, `section`, `window` |

## 6. Find similar code

Give a file and a line; the enclosing function is used as the question:

```bash
staticsight similar src/storage/wal.cpp 5 --top 3
```

````text
### 🧬 SIMILAR CODE: `src/storage/wal.cpp:5`
Source: function `wal_append` (L4-6). Index: 21 files, 48 chunks (jina-code@516f4baf13dec4ddddda8631e019b5737c8bc250). Index is up to date.
1. `src/storage/wal.cpp:8-10` — function `wal_replay` (cpp) · 0.87 · very similar
   ```cpp
    8 | void wal_replay(const uint8_t* wal_ptr, Packet& out) {
    9 |     memcpy(&out, wal_ptr, sizeof(Packet));
   10 | }
   ```
2. `src/net/socket.cpp:9-12` — function `copy_packet` (cpp) · 0.61 · similar
   ```cpp
    9 | void copy_packet(uint8_t* dst, const Packet& pkt) {
   10 |     std::memcpy(dst, &pkt,
   11 |                 sizeof(pkt));
   12 | }
   ```
3. `src/storage/wal.cpp:1-2` — file (cpp) · 0.56 · similar
   ```cpp
   1 | #include "net/packet.hpp"
   2 | #include <cstring>
   ```

_near-duplicate ≥ 0.92, very similar ≥ 0.85 (cosine). Check whether a fix in the source also applies to these places._
````

Use `--end N` to compare an explicit range (`similar src/net/socket.cpp 9 --end 12`).

## 7. Keep it fresh

You rarely need to do anything: every search first checks which files changed (size and timestamp, milliseconds) and
re-embeds up to 200 changed files before answering. After a `git pull` or a branch switch you can refresh explicitly:

```bash
staticsight index refresh
```

```text
Semantic index for /tmp/cpp-sample
  … scanning files
re-indexed 1 changed file(s), removed 0; embedded 0 new chunk(s)
```

"embedded 0 new chunks" means the file's timestamp changed but its chunks did not: content hashes let StaticSight
skip the expensive step. `staticsight index build --full` re-embeds everything; deleting `.staticsight/semantic.db` does the same.

## 8. The same thing the agent sees

`search` and `similar` are shortcuts. The `tool` command runs the exact MCP tools, with the same Markdown an agent receives:

```bash
staticsight tool semantic_search "where do we retry failed connections" --top-k 3
staticsight tool find_similar_code src/storage/wal.cpp 5 --top-k 3
staticsight tool refresh_semantic_index
staticsight tool get_index_status
```

See the [command-line guide](../cli-guide.md#run-any-review-tool-tool) for the `tool` command.

## 9. TypeScript

The Node implementation has the same commands and output: replace `staticsight` with
`node $SS_HOME/staticsight-ts/dist/server.js` (after `npm install && npm run build` in `staticsight-ts`).
Both read and write the same `.staticsight/semantic.db`.

## Troubleshooting

| Message | What to do |
|---|---|
| `not available … packages are missing` | `python3 staticsight.py --install --semantic` (Python) or `npm install` in `staticsight-ts` (Node ≥ 22.13). |
| `model is not downloaded` and no network | Copy the `models/` folder from a connected machine, or set `STATICSIGHT_EMBED_MODEL_DIR`. |
| First search shows only keyword results | The first build runs in the background in the MCP server. Run `staticsight index build` once in a terminal instead. |
| `index status` says `per-user cache (repository is not writable)` | The repository is read-only; the index lives in the per-user cache. This is fine. |
| Results look stale | `staticsight index refresh`. Check `STATICSIGHT_SEMANTIC_AUTO_REFRESH` is not `0`. |
| A file is missing from results | It may be ignored (`.gitignore`, `.staticsightignore`, `STATICSIGHT_EXCLUDES`), binary, minified, or over 512 KB. `index status` lists skipped files. |

---

<!-- nav:bottom -->
| ⬅️ [Semantic search](README.md) | 📚 [Documentation](../README.md) | [MCP flow](mcp-flow.md) ➡️ |
|:---|:---:|---:|
<!-- /nav:bottom -->
