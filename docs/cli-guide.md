<!-- nav:top -->
📚 [Documentation](README.md) › **Command-line guide**
<!-- /nav:top -->

# Command-line guide

Everything StaticSight does for an AI agent, you can do from a terminal: build and query the indexes, and run each of
the 16 review tools with the exact Markdown the agent would receive. This page lists every command, option and
environment variable, with real output from the test repository (`shared/fixtures/make_fixture.py /tmp/cpp-sample`).

<!-- nav:toc -->
**On this page:** [The command map](#the-command-map) · [Choosing the repository](#choosing-the-repository) · [Where data goes](#where-data-goes) · [doctor: check the setup](#doctor-check-the-setup) · [Run any review tool: tool](#run-any-review-tool-tool) · [Semantic index commands](#semantic-index-commands) · [Running the MCP server by hand](#running-the-mcp-server-by-hand) · [Scripting examples](#scripting-examples) · [Environment variables](#environment-variables)
<!-- /nav:toc -->

`staticsight` below is the short command from [Getting started](getting-started.md#5-make-a-short-command)
(`python3 $SS_HOME/staticsight.py`). The TypeScript twin accepts the same commands:
`node $SS_HOME/staticsight-ts/dist/server.js …`.

> 🪟 **Windows:** every command on this page works the same in PowerShell once you have the `staticsight` function from
> [Getting started](getting-started.md#5-make-a-short-command), or type `py -3 "$env:SS_HOME\staticsight.py" …`.
> Put globs in quotes (`--path-glob "src/net/*"`) on every OS.

## The command map

```bash
staticsight help
```

```text
staticsight [COMMAND]

  (no command) | stdio | sse | streamable-http   run the MCP server
  doctor                                         check engines and workspace
  index build [--full]                           build/refresh the semantic index (blocking, with progress)
  index refresh                                  incremental refresh (only changed files)
  index status                                   show semantic + GNU Global index status
  search "query" [--glob G] [--language L] [--kind K] [--top N]
  similar FILE LINE [--end N] [--top N]
  model download | status                        fetch / verify the pinned embedding model
  tool --list                                    list the 16 review tools and their parameters
  tool NAME [ARGS] [--param VALUE ...]           run one tool, print the Markdown an agent receives

Global option: --repo PATH selects the repository (same as WORKSPACE_ROOT). Default: the nearest folder above
the current directory that holds .staticsight/ or .git. Indexes live in <repo>/.staticsight/ (git-ignored).
```

The launcher itself has one more option, which needs no installed packages:

| Command | What it does |
|---|---|
| `python3 staticsight.py --install [--semantic] [--yes] [-- PIP_ARGS]` | Install the Python dependencies with pip for this interpreter. Asks first unless `--yes`. Anything after `--` goes to pip (for example `-- --user`). Explains PEP 668 errors. |

## Choosing the repository

StaticSight works on one repository at a time, the **workspace**. It is chosen in this order:

1. `--repo PATH` anywhere on the command line (`staticsight --repo ~/src/app doctor` or `staticsight doctor --repo ~/src/app`);
2. the `WORKSPACE_ROOT` environment variable;
3. otherwise the nearest folder at or above the current folder that contains `.staticsight/` or `.git`.

So from any subfolder of a repository, commands just work:

```bash
cd src/net
staticsight tool get_symbol_definition route_count
cd ../..
```

```text
### 📍 DEFINITIONS: `route_count` (1, source: ctags (GNU Global had no definition))
1. `src/router.hpp:20` — member `Router::route_count`
```

File arguments are always **relative to the workspace root**, not to the current folder, exactly as an agent passes them.
Paths outside the workspace are refused.

## Where data goes

| What | Where | Shared by |
|---|---|---|
| GNU Global database (`GTAGS`, `GRTAGS`, `GPATH`) | `<repo>/.staticsight/` | this clone only |
| Semantic index (`semantic.db`) and its lock file | `<repo>/.staticsight/` | this clone only |
| Embedding model | `~/.cache/staticsight/models/` (`%LOCALAPPDATA%\staticsight\models\` on Windows) | all repositories |

`.staticsight/` contains a `.gitignore` with `*`, so git ignores the folder without any change to your own `.gitignore`.
Deleting it is always safe. `STATICSIGHT_DATA_DIR=cache` stores the indexes in the per-user cache instead; a read-only
repository, or a folder that is not a git repository (unless chosen with `--repo`), uses the per-user cache automatically.
`STATICSIGHT_DATA_DIR=/some/folder` puts each repository's data in its own sub-folder there. `doctor` and `index status` show where the data is and why.

## `doctor`: check the setup

```bash
staticsight doctor
```

Prints the platform, the workspace, the data and cache folders, each engine with its version and what it is used for,
and the semantic-search packages and model. Exit code 0 when all required engines work, 1 otherwise. See
[Getting started](getting-started.md#4-check-the-setup) for a full sample.

## Run any review tool: `tool`

`tool` runs one MCP tool and prints exactly the Markdown the agent would receive. It is the best way to see what
StaticSight tells the agent, to script checks, or to debug a surprising answer.

```bash
staticsight tool --list
```

<details>
<summary>Show the output (16 tools)</summary>

```text
16 tools, the same ones the MCP server offers. Details: tool NAME --help

review_changes [--base-ref TEXT] [--max-symbols N]
    START HERE for 'review my changes' / 'what could break?'.
get_diff_scopes [--base-ref TEXT] [--path-glob TEXT]
    Maps every changed line of the current diff to the exact C++ function, method, class, struct, enum or macro t…
get_enclosing_scope --file-path TEXT --target-line N
    Returns the innermost C++ function/method/class/struct/namespace that encloses a given line, with its qualifi…
...
Required parameters can also be given positionally, in order.
Boolean parameters: --flag (true) or --no-flag (false). --json '{...}' passes raw MCP arguments.
```

</details>

```bash
staticsight tool get_upstream_callers --help
```

<details>
<summary>Show the help text</summary>

```text
get_upstream_callers --symbol TEXT [--path-glob TEXT]

Finds every call site of a function/method across the repository (GNU Global reference index; falls back to ripgrep when the index is unavailable). Each hit shows file:line, the enclosing caller function, the call line, and whether the return value is used or ignored. Use after changing a function's signature, return values, error codes, preconditions or side effects to check that callers still hold up.

Parameters:
  --symbol TEXT            (string, required) Function or method name, e.g. 'process_packet' (a 'Class::' prefix is accepted and stripped).
  --path-glob TEXT         (string, default "") Optional fnmatch glob to restrict caller files, e.g. 'src/*'.

Positional order: symbol
```

</details>

### Passing arguments

The parameters are the MCP parameters from `shared/tool-spec.json`. Four equivalent ways to call the same tool:

```bash
staticsight tool get_enclosing_scope src/router.cpp 13
staticsight tool get_enclosing_scope --file-path src/router.cpp --target-line 13
staticsight tool get_enclosing_scope --file_path=src/router.cpp --target_line=13
staticsight tool get_enclosing_scope --json '{"file_path": "src/router.cpp", "target_line": 13}'
```

- Required parameters can be given positionally, in the order `--help` shows.
- Dashes and underscores are interchangeable in option names.
- Integers must be whole numbers; booleans are `--flag` / `--no-flag` or `--flag=true|false|yes|no|1|0`.
- `--json` takes the raw MCP arguments object: copy it from an agent's tool call to replay it exactly.

### Exit codes

| Code | Meaning | Example |
|---|---|---|
| 0 | The tool answered (the Markdown is on stdout) | any normal result, including "no call sites found" |
| 1 | The tool answered with an error card (`### ❌ …`) | a file outside the workspace, a deleted file, a bad git ref |
| 2 | The command line was wrong; nothing ran (message on stderr) | unknown tool, missing or badly typed parameter |

```bash
staticsight tool get_enclosing_scope src/router.cpp   # exit 2
```

```text
error: get_enclosing_scope needs --target-line (see: tool get_enclosing_scope --help)
```

```bash
staticsight tool get_enclosing_scope ../../etc/passwd 1   # exit 1
```

```text
### ❌ Invalid argument
`../../etc/passwd` is outside the workspace (WORKSPACE_ROOT).

💡 Only files inside WORKSPACE_ROOT can be inspected.
```

### Indexing before a tool runs

The MCP server builds the GNU Global index in the background. A one-shot command cannot, so `tool` first builds or
updates the index into `.staticsight/` (incremental: `global -u`), printing a note on stderr the first time:

```text
  … building the GNU Global index (first run; large repositories take a few minutes)
```

The semantic tools manage their own index (see [semantic search](semantic-search/manual-guide.md)).

### The 16 tools, one example each

All examples run on the test repository. The [MCP tool reference](MCP_TOOLS.md) explains every parameter and output.

**Review a whole change** (what changed, cppcheck on changed lines, skeletons, callers, layout risks, blast radius, locking):

```bash
staticsight tool review_changes
staticsight tool review_changes --base-ref HEAD~1 --max-symbols 4
```

<details>
<summary>Show the start of the review bundle</summary>

````text
# 🔬 STATICSIGHT REVIEW BUNDLE vs merge-base with `origin/main` (7cd1f773cb)

## 1. What changed
### 🧭 DIFF SCOPES vs merge-base with `origin/main` (7cd1f773cb)
6 C/C++ files changed (+30 / -1).
By status: 5 modified, 1 untracked.

#### `src/net/conn_pool.cpp` (source, modified, +9 -0)
- `ConnPool` (class, L4-14) — changed L8 — declarations changed (no data-member change detected)
- `ConnPool::report` (prototype, L8) — 🆕 new
- `ConnPool::report` (function, L30-35) — 🆕 new
- file-level lines (outside any function/type): L29

#### `src/net/packet.hpp` (header, modified, +1 -0)
- `Packet` (struct, L4-10) — changed L8 — 🧱 layout change (data members/virtuals)
...
## 2. Static audit (cppcheck, changed lines)
### 🚨 STATIC AUDIT: `src/router.cpp` (cppcheck 2.18.3)
2 findings (1 error, 1 style); 1 on changed lines.
1. ✏️ **L13** `[error: memleak]` Memory leak: buffer (CWE-401)
   `return -2;`
...
````

</details>

**What changed, mapped to functions and types:**

```bash
staticsight tool get_diff_scopes
staticsight tool get_diff_scopes --path-glob "src/net/*"
```

```text
#### `src/router.cpp` (source, modified, +7 -1)
- `Router::process_packet` (function, L9-26) — changed L12-14
- `Router::get_route_count` (function, L33-35) — 1 line(s) removed
- `Router::reset` (function, L37-39) — 🆕 new
```

**The function around a line:**

```bash
staticsight tool get_enclosing_scope src/router.cpp 13
```

````text
### 📦 ENCLOSING SCOPE: `Router::process_packet` (function)
- **File:** `src/router.cpp` L9-26 (18 lines)
- **Signature:** `int Router::process_packet(Packet * p)`
- **Parent:** class `Router`
```cpp
  9 | int Router::process_packet(Packet* p) {
 10 |     std::lock_guard<std::mutex> lock(route_mutex);
 11 |     uint8_t* buffer = static_cast<uint8_t*>(malloc(p->len));
 12 |     if (!p->is_encrypted) {
>13 |         return -2;
 14 |     }
...
```
````

**Only the logic paths of a function** (locks, allocations, releases, early exits, possible leaks):

```bash
staticsight tool get_branch_skeleton src/router.cpp --symbol Router::process_packet
```

```text
[L9] ENTRY int Router::process_packet(Packet* p) {
├── [L10] 🔒 LOCK — std::lock_guard<std::mutex> lock(route_mutex);
├── [L11] 📥 ALLOC `buffer` — uint8_t* buffer = static_cast<uint8_t*>(malloc(p->len));
├── [L12] IF (!p->is_encrypted) ✏️
│   ├── [L13] 🛑 RETURN -2 ⚠️ early exit; `buffer` (L11) not released on this path ✏️
├── [L15] IF (buffer == nullptr)
│   ├── [L16] 🛑 RETURN -1
├── [L19] FOR (int i = 0; i < route_count; ++i)
│   ├── [L20] IF (buffer[0] == 0xFF)
│   │   ├── [L21] BREAK
├── [L24] 📤 RELEASE `buffer` — free(buffer);
├── [L25] ↩ RETURN 0
```

**Who calls a function, and do they use its result:**

```bash
staticsight tool get_upstream_callers process_packet
staticsight tool get_upstream_callers Router::process_packet --path-glob "tests/*"
```

**Where something is defined:**

```bash
staticsight tool get_symbol_definition Packet
```

```text
### 📍 DEFINITIONS: `Packet` (1, source: GNU Global)
1. `src/net/packet.hpp:4-10` — struct `Packet`
```

**What a function promises and requires** (signatures, qualifiers, doc comment, `@pre`, `@warning`, MUST/NEVER):

```bash
staticsight tool get_symbol_contract zero_copy_allocate
```

```text
### 🧩 SYMBOL CONTRACT: `zero_copy_allocate`
_Sources: GNU Global; declarations via ctags._
- **Declaration:** `src/memory/pool.hpp:13` — `uint8_t * mem::zero_copy_allocate(size_t size)`
- **Definition:** `src/memory/pool.cpp:6-8` — `uint8_t * mem::zero_copy_allocate(size_t size)`
...
**⚖️ Obligations / preconditions:**
- @pre size must be greater than zero.
- @warning Every allocation MUST be paired with release_buffer() on all execution paths to prevent ring exhaustion.
```

**Code that depends on a struct's exact layout** (`sizeof`, `memcpy`, casts, raw `send`/`write`):

```bash
staticsight tool track_struct_risks Packet
```

```text
### ⚠️ LOW-LEVEL MEMORY USAGES: `Packet`
Defined at: `src/net/packet.hpp:4-10`.
Modifying the size, padding or member order of `Packet` may break 4 sites (out of 16 references):

1. `src/net/socket.cpp:6` in `send_packet` — 🌐 raw I/O, 📏 size/offset assumption, 🎭 type punning
   `return send(fd, reinterpret_cast<const char*>(&pkt), sizeof(Packet), 0);`
...
```

**Which files include a header** (directly and transitively):

```bash
staticsight tool get_include_blast_radius packet.hpp
staticsight tool get_include_blast_radius src/router.hpp --transitive-depth 1
```

```text
### 💥 BLAST RADIUS: `src/net/packet.hpp`
- **Direct includers:** 7 files; **transitive:** 3 more files (depth 2)
- **Translation units affected:** 8 of 13 source files (62%); headers affected: 2
- **By directory:** `src/` (5), `src/net/` (2), `src/enc/` (1), `src/storage/` (1), `tests/` (1)
...
```

**Every read and write of shared state, and whether a lock protects it:**

```bash
staticsight tool track_state_mutations route_count
staticsight tool track_state_mutations route_mutex --file-path src/router.cpp
```

```text
### 🔒 STATE MUTATION & ACCESS SITES: `route_count`
4 accesses (2 writes) in 2 files.
⚠️ **Inconsistent locking:** accessed under a lock in 2 place(s) but without one in 2: `src/router.cpp:34` (Router::get_route_count, read), `src/router.cpp:38` (Router::reset, write). Potential data race if these run concurrently.
...
```

**Potential deadlocks: the lock-acquisition order of the whole repository** (cycles, same lock twice, locks held
across blocking calls):

```bash
staticsight tool track_lock_order
staticsight tool track_lock_order --symbol stats_mutex
staticsight tool track_lock_order --path-glob "src/net/*"
```

```text
### 🔀 LOCK ORDER: repository
Scanned 5 functions that take locks in 2 files: 3 locks, 2 ordering pairs.

⚠️ **1 potential deadlock cycle** (locks taken in opposite orders):
1. `ConnPool::pool_mutex` → `ConnPool::stats_mutex` → `ConnPool::pool_mutex`
   - `src/net/conn_pool.cpp:18` in `ConnPool::rebalance`: holds `ConnPool::pool_mutex` (L18), takes `ConnPool::stats_mutex` at L19
   - `src/net/conn_pool.cpp:31` in `ConnPool::report`: holds `ConnPool::stats_mutex` (L31), takes `ConnPool::pool_mutex` via `ConnPool::drain()` at L33

⏳ **Locks held across blocking calls** (latency, and deadlock if the other side needs the lock):
- `src/net/conn_pool.cpp:34` in `ConnPool::report`: `send()` while holding `ConnPool::stats_mutex`
...
```

**cppcheck on one file** (optionally only findings on changed lines):

```bash
staticsight tool run_file_static_audit src/router.cpp
staticsight tool run_file_static_audit src/router.cpp --only-changed-lines
```

```text
### 🚨 STATIC AUDIT: `src/router.cpp` (cppcheck 2.18.3)
2 findings (1 error, 1 style); 1 on changed lines.
1. ✏️ **L13** `[error: memleak]` Memory leak: buffer (CWE-401)
   `return -2;`
2. 🔶 **L9** `[style: constParameterPointer]` Parameter 'p' can be declared as pointer to const (CWE-398)
   `int Router::process_packet(Packet* p) {`
```

**Semantic search, similar code, refresh** (see the [semantic search guide](semantic-search/manual-guide.md)):

```bash
staticsight tool semantic_search "where do we retry failed connections" --top-k 3
staticsight tool find_similar_code src/storage/wal.cpp 5 --top-k 3
staticsight tool refresh_semantic_index
```

**Index and engine status:**

```bash
staticsight tool get_index_status
```

```text
### 🗂️ INDEX STATUS
- **Workspace:** `/tmp/cpp-sample`
- **State:** ready
- **Detail:** Indexed via `gtags -i -f - (18 files)` in 0.0s.
- **Database:** `/tmp/cpp-sample/.staticsight`
- **Age:** 0s (auto-refresh after 300s)
- **Engines:** `ctags` ✅, `rg` ✅, `git` ✅, `cppcheck` ✅, `global` ✅, `gtags` ✅
...
```

## Semantic index commands

| Command | What it does |
|---|---|
| `staticsight model download` | Download and verify the pinned embedding model (once per user). |
| `staticsight model status` | Check the model files (exit 1 if missing). |
| `staticsight index build [--full]` | Build or update the semantic index, blocking, with progress on stderr. `--full` re-embeds everything. |
| `staticsight index refresh` | Re-embed only changed files. |
| `staticsight index status` | State, content, languages, model and database location. |
| `staticsight search "QUERY" [--glob G] [--language L] [--kind K] [--top N]` | Search by meaning. |
| `staticsight similar FILE LINE [--end N] [--top N]` | Find code similar to a function or range. |

```bash
staticsight model status
staticsight index build
staticsight index status
staticsight search "copy packet bytes" --language cpp --kind function --top 3
staticsight similar src/storage/wal.cpp 5 --top 3
staticsight index refresh
```

The [semantic search guide](semantic-search/manual-guide.md) walks through them with real output.

## Running the MCP server by hand

`staticsight` with no command starts the MCP server on stdio. It then waits for JSON-RPC messages on stdin, so in a
terminal it looks like it hangs; that is expected (Ctrl+C to stop). Clients start it for you. `sse` and
`streamable-http` start the HTTP transports instead (Python only). The [MCP guide](mcp-guide.md) shows a full exchange.

## Scripting examples

Audit every changed C++ file and stop on the first error card:

```text
git diff --name-only origin/main -- '*.cpp' '*.cc' '*.c' | while read -r f; do
  staticsight tool run_file_static_audit "$f" --only-changed-lines || break
done
```

Save the review bundle for a pull request description:

```text
staticsight tool review_changes > review.md
```

Replay a tool call from an agent's log:

```text
staticsight tool track_struct_risks --json '{"struct_name": "Packet", "path_glob": "src/*"}'
```

## Environment variables

Command-line options win over these; `--repo` wins over `WORKSPACE_ROOT`.

| Variable | Default | Meaning |
|---|---|---|
| `WORKSPACE_ROOT` | found from the current folder | The repository to analyse. All file arguments are confined to it. |
| `STATICSIGHT_DATA_DIR` | `repo` | Where indexes go: `repo` = `<repo>/.staticsight/`, `cache` = per-user cache, anything else = a per-repository sub-folder of that folder. |
| `STATICSIGHT_CACHE_DIR` | `~/.cache/staticsight` (`$XDG_CACHE_HOME`), `%LOCALAPPDATA%\staticsight` | Per-user cache: models (and indexes in `cache` mode). |
| `STATICSIGHT_BASE_REF` | auto | Diff base. Auto = merge-base with `origin/main`, then `origin/master`, `main`, `master`, `HEAD`. |
| `STATICSIGHT_MAX_RESULTS` | 15 | Items per list before "…and N more". |
| `STATICSIGHT_MAX_CHARS` | 6000 | Output budget per tool call. |
| `STATICSIGHT_REVIEW_MAX_CHARS` | 16000 | Output budget for `review_changes`. |
| `STATICSIGHT_TIMEOUT` | 20 | Seconds per engine call. |
| `STATICSIGHT_CPPCHECK_TIMEOUT` | 60 | Seconds per cppcheck run. |
| `STATICSIGHT_CPPCHECK_ARGS` | — | Extra cppcheck arguments, e.g. `-DBEGIN_EVENT(x)=`. |
| `STATICSIGHT_CPPCHECK_MSVC` | auto | MSVC mode for Windows code: `auto`, `0`, `1`. |
| `STATICSIGHT_EXCLUDES` | — | Extra comma-separated globs to skip (a `.staticsightignore` file at the root works too). |
| `STATICSIGHT_DISABLE_ENGINES` | — | Engines to treat as missing, e.g. `global,gtags` to force the ripgrep fallback. |
| `STATICSIGHT_REINDEX_SECONDS` | 300 | Refresh the GNU Global index in the background when older than this (server). |
| `STATICSIGHT_GTAGS_IN_REPO` | 0 | Deprecated: `1` builds `GTAGS` in the repository root. Prefer the default `.staticsight/`. |
| `STATICSIGHT_SEMANTIC_*`, `STATICSIGHT_EMBED_*`, `HF_ENDPOINT` | | Semantic search settings: see [internals](semantic-search/internals.md#configuration). |

Default excludes: `.git`, `.staticsight`, `build/`, `out/`, `third_party/`, `external/`, `node_modules/`, `*.pb.h`,
`*.pb.cc`, plus everything in `.gitignore`.

---

<!-- nav:bottom -->
| ⬅️ [Getting started](getting-started.md) | 📚 [Documentation](README.md) | [MCP guide](mcp-guide.md) ➡️ |
|:---|:---:|---:|
<!-- /nav:bottom -->
