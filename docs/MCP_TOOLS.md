<!-- nav:top -->
📚 [Documentation](README.md) › **MCP tool reference**
<!-- /nav:top -->

# StaticSight MCP tool reference

StaticSight exposes **16 MCP tools** (15 read-only; `refresh_semantic_index` writes only to StaticSight's data folder `.staticsight/`) and **1 prompt**. The Python and TypeScript servers behave
identically. Names, parameters and the descriptions the agent sees come from
[`shared/tool-spec.json`](../shared/tool-spec.json).

<!-- nav:toc -->
**On this page:** [1. review_changes](#1-review_changes) · [2. get_diff_scopes](#2-get_diff_scopes) · [3. get_enclosing_scope](#3-get_enclosing_scope) · [4. get_branch_skeleton](#4-get_branch_skeleton) · [5. get_upstream_callers](#5-get_upstream_callers) · [6. get_symbol_definition](#6-get_symbol_definition) · [7. get_symbol_contract](#7-get_symbol_contract) · [8. track_struct_risks](#8-track_struct_risks) · [9. get_include_blast_radius](#9-get_include_blast_radius) · [10. track_state_mutations](#10-track_state_mutations) · [11. track_lock_order](#11-track_lock_order) · [12. run_file_static_audit](#12-run_file_static_audit) · [13. semantic_search](#13-semantic_search) · [14. find_similar_code](#14-find_similar_code) · [15. refresh_semantic_index](#15-refresh_semantic_index) · [16. get_index_status](#16-get_index_status) · [Prompt: review_cpp_changes](#prompt-review_cpp_changes) · [Engines at a glance](#engines-at-a-glance)
<!-- /nav:toc -->

Every tool returns concise Markdown with `file:line` references, and keeps to an output budget
(`STATICSIGHT_MAX_CHARS`, default 6000 characters; 16000 for `review_changes`). Lists longer than
`STATICSIGHT_MAX_RESULTS` (default 15) end with "…and N more". Errors never crash the server. They come
back as a card like `### ❌ Invalid argument` with a 💡 hint.

**Common conventions**
- `file_path` is relative to `WORKSPACE_ROOT`. Absolute paths inside the workspace are accepted. Paths that
  escape the workspace (including via symlinks) are rejected.
- `symbol` must be a C++ identifier. A `Class::` prefix and a trailing `()` are accepted and stripped.
- `base_ref` empty means the merge-base with `origin/main`, then `origin/master`, `main`, `master`, `HEAD`
  (or `STATICSIGHT_BASE_REF`). The diff always includes committed, staged, unstaged and untracked changes.
- `path_glob` is an fnmatch pattern such as `src/net/*`. `*` also matches `/`. `\` is accepted as a separator.
  Matching is case-insensitive on Windows (like its file system) and case-sensitive on Linux/macOS.
- Paths in output always use `/`, on every OS. Source files with a UTF-8 or UTF-16 BOM (common in MSVC repos) are
  decoded correctly, and the BOM never hides a line-1 `#include`.
- Output markers: ✏️ changed in the diff · 🔶 inside a changed function · 🛑 early exit · ⚠️ heuristic warning
  · 🔒 lock · 📥 allocation · 📤 release.

| # | Tool | One-line purpose |
|---|---|---|
| 1 | [`review_changes`](#1-review_changes) | Full review bundle for the current diff in one call |
| 2 | [`get_diff_scopes`](#2-get_diff_scopes) | Which functions/types/macros the diff touches |
| 3 | [`get_enclosing_scope`](#3-get_enclosing_scope) | Full code of the function/class around a line |
| 4 | [`get_branch_skeleton`](#4-get_branch_skeleton) | Control-flow tree with lock/alloc/leak annotations |
| 5 | [`get_upstream_callers`](#5-get_upstream_callers) | Who calls a function, and whether they use the result |
| 6 | [`get_symbol_definition`](#6-get_symbol_definition) | Where a symbol is defined (incl. overloads) |
| 7 | [`get_symbol_contract`](#7-get_symbol_contract) | Signature, qualifiers, doc comment, obligations |
| 8 | [`track_struct_risks`](#8-track_struct_risks) | Code that depends on a struct's exact byte layout |
| 9 | [`get_include_blast_radius`](#9-get_include_blast_radius) | Files affected by a header change |
| 10 | [`track_state_mutations`](#10-track_state_mutations) | Reads/writes of shared state and their locking |
| 11 | [`track_lock_order`](#11-track_lock_order) | Lock-acquisition order: potential deadlocks, same lock twice, locks held across blocking calls |
| 12 | [`run_file_static_audit`](#12-run_file_static_audit) | cppcheck findings for one file, mapped to the diff |
| 13 | [`semantic_search`](#13-semantic_search) | Find code by meaning across every language in the repo |
| 14 | [`find_similar_code`](#14-find_similar_code) | Copy-paste twins / parallel implementations of a region |
| 15 | [`refresh_semantic_index`](#15-refresh_semantic_index) | Build or refresh the semantic index on demand |
| 16 | [`get_index_status`](#16-get_index_status) | Index states (GNU Global + semantic), engines, model |
| — | [`review_cpp_changes` prompt](#prompt-review_cpp_changes) | The recommended review workflow |

---

## 1. `review_changes`

**What it does:** runs the most useful tools for the current diff and merges the results into one report, within
the output budget. This is the entry point for "review my changes" and "what could break?".

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `base_ref` | string | `""` | Diff base (see conventions). Use e.g. `HEAD~1` for "my last commit". |
| `max_symbols` | integer | `8` | How many changed functions/types to analyse in depth (1-25). |

**Sections of the report**
1. **What changed:** compact `get_diff_scopes` output.
2. **Static audit:** `run_file_static_audit(only_changed_lines=true)` on up to 6 changed source files.
3. **Branch skeletons** of changed functions. Modified functions come before new ones. Functions without
   branches are listed on one line.
4. **Caller impact** for modified functions, changed declarations, and removed functions.
5. **Memory-layout risks** for structs/classes whose data members or virtuals changed.
6. **Header blast radius** for changed headers.
7. **Lock consistency:** `track_state_mutations` for class members used by changed functions. It is only shown
   when locking is inconsistent.
8. **Lock order:** `track_lock_order` focused on the locks that changed functions take. It is only shown (and only
   run) when a changed function takes a lock and there is a cycle, a lock taken twice, or a lock held across a blocking call.
9. **Calls introduced by the diff:** functions newly called in added lines. Check their contracts.
10. **Similar code elsewhere:** near-duplicates of changed functions, when the semantic index exists.
11. **Reviewer checklist:** items generated from what was found, plus two standing reminders.

**Engines:** git, ctags, GNU Global/ripgrep, cppcheck.

---

## 2. `get_diff_scopes`

**What it does:** maps every changed line to the innermost C++ scope that contains it (function, method, class,
struct, union, enum or macro) and describes the change.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `base_ref` | string | `""` | Diff base. |
| `path_glob` | string | `""` | Restrict to matching files, e.g. `src/net/*`. |

**How it works:** `git diff -U0 -M <base>` plus `git ls-files --others` for untracked files. Hunks are parsed
into added lines and removal points. Universal Ctags (JSON, with end lines) runs on the current file, and on the
**old blob** of the file so old and new symbols can be compared.

**It reports, per file:**
- Changed scopes with changed line ranges and removed-line counts.
- 🆕 new symbols and 🗑️ removed symbols.
- 🔁 signature changes, shown as old → new.
- 🧱 layout changes when data members, enumerators or virtuals change. Method-only changes are reported as
  "declarations changed".
- Macros defined or changed, changed `#include` lines, and file-level lines outside any scope.
- A one-line summary for new files; deleted and renamed files.
- **Suggested next calls** at the end, listing which tool to run for which item.

---

## 3. `get_enclosing_scope`

**What it does:** returns the innermost function/method/class/struct around a line, with its qualified name,
signature, parent scope, line range and line-numbered source. The target line is marked `>`.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `file_path` | string | required | File to inspect. |
| `target_line` | integer | required | 1-based line number. |

**Details**
- Scopes over 150 lines are shortened: the first 15 lines, ±30 lines around the target, and the last 10 lines.
- If no scope contains the line (global code, preprocessor blocks), it shows ±12 lines of file-level context.
- Anonymous namespaces are shown as `(anonymous)`.

---

## 4. `get_branch_skeleton`

**What it does:** shows only the control flow of a function as a tree, so logic and error paths can be checked
without reading the whole body.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `file_path` | string | required | File containing the function. |
| `symbol` | string | `""` | Function name, e.g. `process_packet` or `Router::process_packet`. |
| `start_line` | integer | `0` | Used alone: the function enclosing this line. |
| `end_line` | integer | `0` | Used with `start_line`: an explicit range. |

**What it shows**
- Nodes: `if` / `else if` / `else` / `switch` / `case` / `default` / `for` / `while` / `do` / `try` / `catch` /
  `return` / `co_return` / `throw` / `break` / `continue` / `goto`, with conditions and return values.
- Annotations: 🔒 lock acquisitions, 🔓 unlocks, 📥 allocations, 📤 releases. Resource pairs cover C/C++
  (`malloc`/`free`, `new`/`delete`, `fopen`/`fclose`), POSIX (`open`/`close`, `socket`/`close`, `mmap`/`munmap`),
  Win32 (`CreateFile*`/`CloseHandle`, `OpenSCManager*`/`OpenService*`/`CloseServiceHandle`, `CoTaskMemAlloc`/`CoTaskMemFree`,
  `SysAllocString*`/`SysFreeString`, ...) and COM `->Release()`.
- 🛑 for early exits; ↩ for final returns.
- ⚠️ when an exit leaves an allocation unreleased. Paths already guarded by a failure check such as
  `if (h == INVALID_HANDLE_VALUE)`, `if (fd < 0)` or
  `if (buf == nullptr)` are not flagged.
- ✏️ on lines changed in the current diff.
- A summary line with the number of returns, throws, early exits, loops and potential leak paths.

**How it works:** comments and string literals are blanked first (column-preserving, raw strings and digit
separators included). Nesting comes from brace depth, not indentation. Single-statement `if`/`else` bodies are
handled. This is a heuristic, and the output says so.

---

## 5. `get_upstream_callers`

**What it does:** lists every call site of a function, with the calling function and how the return value is used.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `symbol` | string | required | Function/method name. |
| `path_glob` | string | `""` | Restrict caller files. |

**How it works:** `global -xr` against the background GNU Global index. If the index is not available, it falls
back to a ripgrep search for `symbol(` and `&symbol`, and the output says "ripgrep fallback".

**Filtering and classification**
- Removed from the results: hits in comments or strings, the declaration/definition itself, and variables or
  parameters that merely share the name.
- Each remaining call is classified:
  - **result used**
  - **⚠️ result ignored**, a bare statement like `obj->f(x);`
  - **result explicitly discarded**, `(void)f(x)`
  - **referenced (address/callback)**
- For `void` functions no classification is shown.
- The header states the return type and how many callers ignore it.
- Call sites are grouped by file. When results are truncated, the top files are listed.

---

## 6. `get_symbol_definition`

**What it does:** finds where a symbol is defined: functions, methods, classes, structs, unions, enums, macros,
typedefs, namespaces, variables and members. Overloads are included.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `symbol` | string | required | Symbol name. |

**How it works:** `global -xd`, enriched with ctags kind and signature. If GNU Global finds nothing (for example
data members), or is unavailable, it uses ripgrep to find candidate files and ctags to find definitions. The
engine used is shown in the header.

---

## 7. `get_symbol_contract`

**What it does:** shows what a function or type requires of the code that uses it.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `symbol` | string | required | Function or type name. |

**It reports**
- **Declarations**, from headers first, and **definitions**, each with the full signature.
- **Qualifiers:** `const`, `noexcept`, `virtual`, `override`, `final`, `static`, `inline`, `constexpr`,
  `explicit`, `[[nodiscard]]`, `[[deprecated]]`, `template`, `= delete`, `= default`, pure virtual.
- **The doc comment** directly above the declaration or definition (`/** */`, `///`, `//!`, `//` blocks, or a
  trailing `///<`).
- **Obligations / preconditions:** Doxygen tags (`@pre`, `@post`, `@return`, `@throws`, `@warning`, `@note`,
  `@invariant`, ...) with their continuation lines, plus sentences with words like MUST, NEVER, thread-safe,
  ownership, non-null, lock, release, paired.
- **The body**, when it is short (functions up to 25 lines, types up to 40). Otherwise it points you to
  `get_branch_skeleton`.

---

## 8. `track_struct_risks`

**What it does:** finds code whose correctness depends on the exact byte layout of a struct/class. Use it whenever
members are added, removed, reordered or resized.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `struct_name` | string | required | Type name, e.g. `Packet`. |
| `path_glob` | string | `""` | Restrict files. |

**Risk categories** (the matching line and the 2 lines around it are checked; comments are ignored)

| Label | Matches | Why it matters |
|---|---|---|
| 🌐 raw I/O | `send`, `recv`, `write`, `read`, `fwrite`, `fread`, `ioctl`, `mmap`, ... | Wire/disk format breaks for peers or data from older code |
| 🧬 raw memory op | `memcpy`, `memmove`, `memset`, `memcmp`, ... | Offsets shift; `memcmp` also compares padding |
| 📏 size/offset assumption | `sizeof`, `offsetof`, `alignof` | Buffer sizes and protocol lengths change silently |
| 🎭 type punning | `reinterpret_cast`, `bit_cast`, C-style `(T*)` casts | Layout must match the producer exactly |
| 📦 packing/alignment | `#pragma pack`, `__attribute__((packed/aligned))`, `alignas` | Alignment/ABI assumptions |
| ✅ layout assertion | `static_assert` | Must be updated deliberately |
| 🔀 union aliasing | `union` | All members must stay compatible |
| 🔁 byte-order conversion | `hton*`, `ntoh*`, `htobe*`, `bswap*` | New fields need matching conversion |
| 🗃️ serialization | `*serialize*`, `*marshal*`, `*encode*`, `*decode*` | Encoders/decoders need the new member |

Each hit shows `file:line`, the enclosing function, the labels, and the code line. Hits where the operation is
only on a neighbouring line are marked "(operation within ±2 lines)". The type's own definition location is
listed, and a "Why it matters" legend explains each label found.

---

## 9. `get_include_blast_radius`

**What it does:** lists the files that `#include` a header, directly and through other headers, so you know what a
header change recompiles and can affect.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `header_filename` | string | required | `packet.hpp` or `src/net/packet.hpp`. |
| `transitive_depth` | integer | `2` | 1 = direct only; 2-3 = follow including headers. |

**It reports**
- Direct and transitive includers, grouped by directory, each with the exact `#include` line.
- The number and share of translation units affected.
- A warning when a bare `#include "x.h"` could refer to several headers with that name.
- A "high fan-out" note for widely used headers.

**How it works:** ripgrep `--json` with an escaped pattern. Includes are matched by path suffix and by resolving
relative `../` paths, so a `.` in the name can't match any character.

---

## 10. `track_state_mutations`

**What it does:** finds every access to a variable or member and whether it is protected. Use it when shared state,
mutexes or concurrency are involved.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `symbol` | string | required | Variable/member name, e.g. `route_count`. |
| `file_path` | string | `""` | Restrict to one file. |

**Access kinds**
- **write:** `=`, compound assignment, `++`/`--`.
- **mutating call:** `push_back`, `insert`, `erase`, `clear`, `store`, `fetch_*`, `set*`, ...
- **address taken**, **read**, **declaration**, and **lock operation** (the symbol is itself a mutex).

**Sync column**
- 🔒 the lock that is active at that line: std RAII guards (`lock_guard`, `unique_lock`, `scoped_lock`, `shared_lock`),
  `.lock()` / `std::lock`, Win32 critical sections and SRW locks (`EnterCriticalSection`, `AcquireSRWLockExclusive/Shared`),
  and RAII wrappers whose type names a lock (`CAutoLock l(&m_cs)`), honouring block scope and unlocks.
- ⚛️ atomic, when the declaration is `std::atomic`.
- ctor/dtor, for constructors and destructors.
- ❌ BARE, when nothing protects the access.

It flags **inconsistent locking** (the same state accessed with and without a lock), which is a likely data race.
It also warns when a shared lock is used for a write. Locks held by callers are not visible; the output notes this.

---

## 11. `track_lock_order`

**What it does:** finds potential deadlocks. It builds the lock-acquisition order of the whole repository ("B is taken
while A is held"), inside each function and through one level of calls, and reports where two code paths take the
same locks in opposite orders.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `path_glob` | string | `""` | Restrict the scanned files, e.g. `src/net/*`. |
| `symbol` | string | `""` | Focus on one lock (mutex, critical section, SRW lock), e.g. `route_mutex`. |

**It reports**
- **⚠️ Potential deadlock cycles:** `A → B → A` (up to 4 locks), with the `file:line` evidence for each direction,
  including "via `drain()`" when the second lock is taken by a called function.
- **⚠️ Same lock taken twice:** a non-recursive lock (std mutexes, SRW locks) taken again while held, directly or by an
  unconditionally locking callee. Critical sections are re-entrant and are not flagged.
- **⏳ Locks held across blocking calls:** `send`/`recv`/`connect`/`select`, file I/O, `Sleep`, `WaitForSingleObject`,
  `std::this_thread::sleep_for`, ...: latency, and a deadlock if the other side needs the lock.
- **Acquisition order:** every A → B pair with an example location.

**How it works**
- ripgrep finds the files that take locks; ctags gives each function's boundaries. Each function body is walked with
  comments and strings removed, tracking the locks held at each line (block scope for RAII guards, explicit unlocks).
- Recognised: std guards, `m.lock();` (a statement; `weak_ptr::lock()` is not a mutex), `std::lock(a, b)`, Win32
  `EnterCriticalSection` and `AcquireSRWLockExclusive/Shared`, RAII wrappers whose type names a lock. `Try*` variants
  are conditional and not counted.
- Locks are matched by name; member names are qualified by class (`ConnPool::pool_mutex`), so `m_lock` of two classes
  stays distinct. Calls through another object (`other.f()`, `p->f()`) are not followed: that object has its own locks.
  A lock taken in an `if` branch is not "held" in the `else` branch.

**Limits (labelled in the output):** one call level; no aliasing (two names for one mutex); runtime conditions and
lock hierarchies are not modelled. Treat findings as precise leads to confirm.

**Example** (test repository):

```text
⚠️ **1 potential deadlock cycle** (locks taken in opposite orders):
1. `ConnPool::pool_mutex` → `ConnPool::stats_mutex` → `ConnPool::pool_mutex`
   - `src/net/conn_pool.cpp:18` in `ConnPool::rebalance`: holds `ConnPool::pool_mutex` (L18), takes `ConnPool::stats_mutex` at L19
   - `src/net/conn_pool.cpp:31` in `ConnPool::report`: holds `ConnPool::stats_mutex` (L31), takes `ConnPool::pool_mutex` via `ConnPool::drain()` at L33

⏳ **Locks held across blocking calls** (latency, and deadlock if the other side needs the lock):
- `src/net/conn_pool.cpp:34` in `ConnPool::report`: `send()` while holding `ConnPool::stats_mutex`
```

---

## 12. `run_file_static_audit`

**What it does:** runs cppcheck on one C/C++ file without building it, and maps the findings onto the diff.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `file_path` | string | required | `.c`/`.cpp`/header to analyse. |
| `only_changed_lines` | boolean | `false` | Keep only findings on changed lines (✏️) or inside changed functions (🔶). |
| `base_ref` | string | `""` | Diff base used to find changed lines. |

**How it works**
- Runs `cppcheck --xml --enable=warning,style,performance,portability --inline-suppr` with best-effort `-I` paths:
  the file's folder, parent folders, and `include`/`inc`/`src` folders. Missing-include noise is suppressed.
- **MSVC mode:** when the file targets Windows (`windows.h`-family includes, SAL annotations such as `_In_`/`__out`,
  or several Win32 types), cppcheck also gets `--library=windows --platform=win64 -D_WIN32 -D_MSC_VER=1930`. It then
  knows the Win32 API, for example reporting a `CreateFileW` handle that isn't closed on an error path as
  `resourceLeak`. This applies on any host OS; `STATICSIGHT_CPPCHECK_MSVC=0` disables it and `=1` forces it.
- If included headers can't be parsed (for example an unknown macro), it automatically re-runs without include
  paths and names the macro. Extra flags can be passed with `STATICSIGHT_CPPCHECK_ARGS`.
- Findings are sorted error → warning → portability → performance → style. Each shows its id, CWE number,
  source line and extra locations. Findings located in headers are counted but omitted.

---

## 13. `semantic_search`

**What it does:** finds code by **meaning** across the whole repository (C/C++, C#, Python, scripts, docs, configs), for
when you know what the code does but not what it is called.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `query` | string | required | Natural-language description (identifiers may be included). |
| `path_glob` | string | `""` | Restrict files, e.g. `src/net/*`. |
| `language` | string | `""` | e.g. `cpp`, `c`, `csharp`, `python`, `markdown`, `yaml`. |
| `kind` | string | `""` | Chunk kind, e.g. `function`, `class`, `section`, `window`, `file`. |
| `top_k` | integer | `10` | 1-30 results. |

**How it works:**
- A local code-embedding model (ONNX, CPU, offline) ranks functions, classes and sections by cosine similarity.
- A keyword pass (ripgrep) runs in parallel.
- Both lists are fused (reciprocal-rank fusion, keyword weight 0.5) and grouped per symbol.

**Each result** shows `file:start-end`, kind and qualified name, language, cosine score, and why it matched
(`semantic`, `keyword` or `semantic+keyword`), plus a short numbered excerpt.

**Freshness:** before searching, the index is checked for drift:
- **Up to 200 changed files:** they are refreshed first, and the result says so.
- **Larger drift:** refreshes in the background, and the result is marked stale.
- **No index yet:** the first build starts in the background and keyword-only results are shown.

See [semantic search](semantic-search/README.md) and its [internals](semantic-search/internals.md).

---

## 14. `find_similar_code`

**What it does:** finds code elsewhere that is semantically similar to a region: copy-paste twins, Windows/Linux variants,
encode/decode pairs, and places that probably need the same fix.

| Parameter | Type | Default | Meaning |
|---|---|---|---|
| `file_path` | string | required | Source file. |
| `start_line` | integer | required | Alone: the enclosing function/chunk is the source. |
| `end_line` | integer | `0` | Explicit range end (optional). |
| `top_k` | integer | `8` | 1-30 results. |

The source region itself is excluded. Results are labelled `near-duplicate` (≥ 0.92), `very similar` (≥ 0.85) or `similar`.
`review_changes` uses the same logic for its "Similar code elsewhere" section.

---

## 15. `refresh_semantic_index`

**What it does:** builds or refreshes the semantic index on demand, for example after `git pull`.
- It is incremental: only files whose content changed are re-embedded.
- Small refreshes finish before returning; large ones continue in the background (`get_index_status` shows progress and ETA).
- `full=true` rebuilds from scratch.
- It is the only tool that writes, and only to StaticSight's data folder (`<repo>/.staticsight/`, ignored by git), never to source files.

---

## 16. `get_index_status`

**What it does:** also reports the **semantic index**: its state (ready / building with progress and ETA / not built /
needs rebuild / failed), files, chunks and vectors, skipped files by reason, languages, model and database path.

It also reports the platform (`posix`/`windows`), each engine's version, and problems with a fix hint (for
example a ctags without JSON support). It also reports the GNU Global index state (`building`, `ready`, `failed`,
`unavailable`), its database
location and age, and whether `ctags`, `global`, `gtags`, `rg`, `cppcheck` and `git` are installed. No parameters.

**Indexing behaviour**
- The index is built in the background after the MCP handshake (the command line `staticsight tool …` builds it first).
  It lives in `<repo>/.staticsight/`, next to the semantic index, or in the repository root when a `GTAGS` file already
  exists there. `STATICSIGHT_DATA_DIR=cache` (or a read-only repository) puts it in the per-user cache.
- It is refreshed incrementally after `STATICSIGHT_REINDEX_SECONDS` (default 300).
- Graph tools wait up to 2 seconds for it, then use the ripgrep fallback.

---

## Prompt: `review_cpp_changes`

An MCP prompt (optional argument `focus`, e.g. `"locking"`). It gives the agent the step-by-step review workflow,
a checklist of small but costly C++ issues, and the reporting format (Blocker/Major/Minor/Nit, evidence, fix,
verdict). The same guidance is in the Copilot skill `.github/skills/staticsight-cpp-review/SKILL.md`.

## Engines at a glance

| Engine | Used by | Required? |
|---|---|---|
| Universal Ctags (JSON) | scopes, skeletons, diff scopes, enrichment everywhere | yes |
| ripgrep | struct risks, blast radius, mutations, lock order, fallbacks | yes |
| git | diff scopes, review, ✏️ markers | for diff features |
| cppcheck | static audit | for `run_file_static_audit` |
| GNU Global | callers, definitions (precise) | optional (ripgrep fallback) |

---

<!-- nav:bottom -->
| ⬅️ [Learn and experiment](semantic-search/experiments.md) | 📚 [Documentation](README.md) | [Raw commands](COMMANDS.md) ➡️ |
|:---|:---:|---:|
<!-- /nav:bottom -->
