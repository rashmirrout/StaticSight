<!-- nav:top -->
📚 [Documentation](../README.md) › 📖 [The book](00-preface.md) › **Chapter 6: The review tools in depth**
<!-- /nav:top -->

# 6. The review tools in depth

Chapter 5 showed the tools working together. This chapter opens each one: what question it answers, how it reaches its
answer without a compiler, and where it can be wrong. Knowing the limits is what lets you, and the agent, trust the
rest. The [MCP tool reference](../MCP_TOOLS.md) has every parameter.

## Common ground

All review tools share a few mechanisms.

**Finding the enclosing scope.** Ctags gives each function, class and struct a start and end line. To find what
encloses line 13, StaticSight picks the *innermost* scope containing it (the smallest range), so a line in a method
of a class inside a namespace resolves to the method. This is the most used operation in StaticSight.

**Blanking comments and strings.** Before any text analysis, comments and string literals are replaced by spaces of
the same length: column positions stay valid, but a `free(buf)` inside a comment, or a `"}"` inside a string, no longer
counts. This handles `//` and `/* */` comments, escapes, character literals, raw strings (`R"x(...)x"`) and digit
separators (`1'000`).

**Brace depth, not indentation.** Nesting is computed by counting `{` and `}` in the blanked text. Indentation is
never trusted, because C++ code is often mis-indented.

**Changed-line markers.** Tools that know the diff mark lines with ✏️ (changed) and 🔶 (inside a changed function).

## `get_diff_scopes`: what changed, in symbols

**Question:** which functions, types and macros does this diff touch, and how?

**Method:** parse `git diff -U0` hunk headers into added lines and removal points (a pure deletion has no new line,
so its position is remembered and attributed to the scope that now contains that spot). Run ctags on the current
file **and on the old version** (`git show base:path`). Compare the two symbol lists:
- symbols only in the new file are 🆕 new, symbols only in the old file are 🗑️ removed;
- same symbol, different signature: 🔁 old → new;
- for classes and structs, compare the *data members*, enumerators and virtual functions: if they differ, it is a
  🧱 **layout change**; if only methods differ, "declarations changed".

The layout test matters because only data members and virtuals change `sizeof` and member offsets, which is what
breaks binary formats (see `track_struct_risks`).

**Limits:** symbols defined through macros are invisible to ctags. A change inside a macro body is reported as a
macro change, not as a change to every function that uses the macro.

## `get_enclosing_scope`: the function around a line

**Question:** what is the full code around `file:line`?

**Method:** the innermost-scope lookup, then the source lines with line numbers and a `>` on the target. Scopes over
150 lines are shortened (the first 15 lines, ±30 around the target, the last 10). Lines outside every scope get ±12
lines of file-level context instead.

**Limits:** it relies on ctags end lines; code that ctags cannot parse (heavy macro use) falls back to file-level context.

## `get_branch_skeleton`: logic and resources

**Question:** what are the paths through this function, and does every path release what it acquired?

**Method:**
1. Blank comments and strings; locate the body by braces.
2. Walk statements and keep only control flow: `if`/`else`/`switch`/`case`/loops/`try`/`catch` and the exits
   (`return`, `throw`, `break`, `continue`, `goto`), with their conditions. Single-statement bodies without braces
   are handled.
3. Annotate resources: 🔒 locks (RAII guards, `.lock()`), 📥 allocations and 📤 releases, from a table of pairs:
   `malloc`/`free`, `new`/`delete`, `fopen`/`fclose`, `open`/`close`, `socket`/`close`, `mmap`/`munmap`,
   `CreateFile*`/`CloseHandle`, `OpenSCManager*`/`CloseServiceHandle`, `CoTaskMemAlloc`/`CoTaskMemFree`,
   `SysAllocString*`/`SysFreeString`, COM `->Release()` and more.
4. For each early exit, check which allocations made *before* it (at a shallower or equal depth) have not been
   released *before* it. If any, mark ⚠️ "not released on this path".
5. Suppress the warning when the exit sits inside a failure check of that same resource: `if (buf == nullptr)`,
   `if (fd < 0)`, `if (h == INVALID_HANDLE_VALUE)`. Returning there is correct, because there is nothing to free.

**Limits (labelled in the output):** it is text analysis, not data flow. It does not see a resource released by a
helper function, ownership passed to a smart pointer or an out-parameter, or a `goto cleanup` pattern that releases
everything at one label (this is shown as a `goto` exit, without a leak warning). Treat ⚠️ as "check this path", and
cppcheck's `memleak` as the stronger evidence.

## `get_upstream_callers`: who depends on this function

**Question:** where is this function called, and do callers use its result?

**Method:**
1. `global -xr` gives every reference. Without GNU Global: ripgrep for `name(` and `&name`.
2. Remove noise: hits in comments or strings, the function's own declaration and definition, and variables or
   parameters with the same name.
3. Find each caller function with the enclosing-scope lookup.
4. Classify the call by looking at the statement around it: assigned, compared, returned or passed on → **result used**;
   a bare statement `obj->f(x);` → **⚠️ result ignored**; `(void)f(x)` → **explicitly discarded**; `&f` or passing `f`
   → **referenced (address/callback)**.
5. Look up the return type (from the definition's signature): for `void` functions no classification is shown.

**Limits:** without type information, calls to *different* functions with the same name (overloads, methods of
unrelated classes) are grouped together. Calls through function pointers, virtual dispatch or macros that build the
name are not found. The output says "may be unused, called via macro, or only referenced dynamically" when nothing is found.

## `get_symbol_definition` and `get_symbol_contract`: what a symbol promises

**Question:** where is it defined, and what does it require from callers?

**Method:** `global -xd` for definitions, enriched with ctags kind and signature; for data members (which GNU Global
does not index as definitions) ripgrep finds candidate files and ctags finds the member. The contract tool then reads:
- **qualifiers** from the signature and the line (`const`, `noexcept`, `virtual`, `override`, `[[nodiscard]]`, `= delete`, …);
- the **doc comment** directly above the declaration or definition (`/** */`, `///`, `//!`, `//` blocks, trailing `///<`);
- **obligations**: Doxygen tags (`@pre`, `@post`, `@return`, `@throws`, `@warning`, `@note`, `@invariant`, with their
  continuation lines) and sentences with words such as MUST, NEVER, thread-safe, ownership, non-null, lock, release, paired;
- the **body**, when it is short.

This is how the agent learns that `zero_copy_allocate` "MUST be paired with release_buffer() on all execution paths".

**Limits:** it can only report what is written. Undocumented contracts stay invisible, which is itself a useful signal
in a review.

## `track_struct_risks`: where the bytes matter

**Question:** if this struct's size, padding or member order changes, which code breaks?

**Method:** ripgrep finds every whole-word reference to the type with 2 lines of context. On each hit (and its
neighbours, since `memcpy(dst, &pkt,` may continue with `sizeof(pkt))` on the next line), comments are ignored and the
line is matched against risk patterns:

| Label | Patterns |
|---|---|
| 🌐 raw I/O | `send`, `recv`, `write`, `read`, `fwrite`, `fread`, `ioctl`, `mmap`, … |
| 🧬 raw memory op | `memcpy`, `memmove`, `memset`, `memcmp`, … |
| 📏 size/offset | `sizeof`, `offsetof`, `alignof` |
| 🎭 type punning | `reinterpret_cast`, `bit_cast`, C-style pointer casts |
| 📦 packing | `#pragma pack`, `packed`/`aligned` attributes, `alignas` |
| ✅ layout assertion | `static_assert` |
| 🔀 union aliasing | `union` |
| 🔁 byte order | `hton*`, `ntoh*`, `bswap*` |
| 🗃️ serialization | `*serialize*`, `*marshal*`, `*encode*`, `*decode*` |

References without any risk pattern (for example `const Packet& p` as a parameter) are counted but not listed:
"4 sites (out of 16 references)".

**Limits:** it follows the type's *name*. Code that copies the bytes through a `void*` obtained far away, or through a
typedef with another name, is missed. Hits marked "(operation within ±2 lines)" deserve a quick look to confirm the
operation is really on this type.

## `get_include_blast_radius`: who recompiles

**Question:** which files include this header, directly or through other headers?

**Method:** ripgrep for `#include` lines whose path ends with the header's name (the name is escaped, so `.` in
`packet.hpp` is a literal dot). Includes with relative paths (`../net/packet.hpp`) are resolved against the including
file. For transitive depth 2 or 3, the headers found are searched in turn. Results are grouped by directory with the
share of translation units affected. If several headers share the bare name, the output warns.

**Limits:** include paths configured in the build (`-I`) are unknown, so `#include "packet.hpp"` from a file in
another folder is matched by name. Generated or macro-built include lines are not seen.

## `track_state_mutations`: shared state and its locks

**Question:** where is this variable read and written, and which lock protects each access?

**Method:**
1. ripgrep finds every whole-word access; comments and strings are ignored.
2. Each access is classified: **write** (`=`, `+=`, `++`, …), **mutating call** (`push_back`, `insert`, `erase`,
   `clear`, `store`, `fetch_*`, `set*`, …), **address taken**, **read**, **declaration**, or **lock operation** when
   the symbol is itself a mutex.
3. For each access, the enclosing function is scanned from its start to that line for active locks: RAII guards
   (`lock_guard`, `unique_lock`, `scoped_lock`, `shared_lock`, and wrappers whose type names a lock, such as
   `CAutoLock l(&m_cs)`) whose block has not closed, `.lock()` / `std::lock` not yet unlocked, and Win32
   `EnterCriticalSection` / `AcquireSRWLockExclusive/Shared` not yet released. Declarations of `std::atomic` mark the variable ⚛️; constructors and destructors are marked
   as such (usually no concurrent access yet).
4. If the same variable is accessed both with and without a lock, it reports **inconsistent locking**. A write under
   a `shared_lock` (a reader lock) is also flagged.

**Limits (labelled):** locks held by the *caller* are not visible. If `get_route_count()` is only ever called with
`route_mutex` already held, the ❌ BARE is a false alarm. The agent is told to check callers before asserting a race.

## `track_lock_order`: can these locks deadlock?

**Question:** are locks taken in a consistent order everywhere, or can two threads each hold one lock and wait for
the other?

**Method:**
1. ripgrep finds every file that takes a lock; ctags gives the functions in those files.
2. Each function body is walked line by line with the same lock recognition as above, remembering which locks are held
   at each point. Every time a lock B is taken while A is held, the pair **A → B** is recorded with its `file:line`.
3. **One call level:** when a function calls, while holding A, another function (on the same object) that takes B,
   that is also A → B, "via" the callee. This is how the test repository's inversion is found: `report()` holds
   `stats_mutex` and calls `drain()`, which takes `pool_mutex`.
4. All pairs form a graph; every **cycle** (A → B → A, up to four locks) is a potential deadlock, reported with the
   evidence for each direction.
5. It also reports a **non-recursive lock taken twice** (std mutexes and SRW locks; critical sections are re-entrant),
   and **locks held across blocking calls** (`send`, `recv`, `connect`, file I/O, `Sleep`, `WaitForSingleObject`, ...).

**Keeping false alarms down:** these rules came from running it on a 1.1-million-line production code base
(*SomeCPPRepo*) and checking every finding by hand:
- a lock taken in an `if` branch is not "held" in the `else` branch or after the block;
- `x.lock()` counts only as a statement: `if (auto p = weak.lock())` is `std::weak_ptr`, not a mutex;
- `Try*` acquisitions depend on their result and are not counted;
- wrapper types must name a lock (`SocketGuard` is not one); literals such as `true` are never a lock;
- calls on another object (`other.f()`, `ptr->f()`) are not followed, since that object has its own locks;
- a callee counts as "taking the lock again" only when it always does, not when it locks `if (acquireLock)`.

**Limits (labelled):** locks are matched by name (members qualified by class), one call level only, no aliasing (two
names for the same mutex), no lock hierarchies or runtime conditions. On SomeCPPRepo it scanned the 865 functions that
take locks in 12 seconds; the remaining findings were one genuine recursive SRW-lock acquisition and a short list of locks
held across blocking calls, all worth a look.

## `run_file_static_audit`: a real analyser

**Question:** what does a static analyser find in this file, and which findings are new?

**Method:** cppcheck with XML output, best-effort include paths, missing-include warnings suppressed, and MSVC mode for
Windows code (Chapter 8). If headers cannot be parsed because of an unknown macro, cppcheck is re-run without include
paths and the macro is named in the output, so you can pass a definition. Findings are mapped onto the diff and sorted
by severity; findings located inside headers are counted but omitted.

**Limits:** cppcheck sees one file at a time with partial headers, so it misses bugs that need whole-program knowledge
and may report a few false positives in macro-heavy code. Its findings on changed lines are nevertheless the strongest
evidence in a review.

## `review_changes`: the bundle

**Question:** what does a reviewer need to know about this diff?

**Method:** run `get_diff_scopes`, then, within the 16,000-character budget and for at most `max_symbols` symbols:
cppcheck on up to six changed source files (changed lines only), skeletons of changed functions (modified before new;
functions with no branches listed on one line), callers of modified functions and changed declarations, layout risks
of structs whose data members changed, blast radius of changed headers, locking of class members used by changed
functions (shown only when inconsistent), functions newly called by added lines, and a checklist generated from what
was found.

**Design choice:** it is a *starting point*. It shows enough of everything to decide where to look, and suggests the
exact follow-up calls. Depth comes from the individual tools.

## What the markers mean

| Marker | Meaning |
|---|---|
| ✏️ | on a line changed in the diff |
| 🔶 | inside a function changed in the diff |
| 🛑 / ↩ | early exit / final return |
| ⚠️ | something to check; often a heuristic |
| 🔒 / 🔓 | lock acquired / released |
| 📥 / 📤 | resource acquired / released |
| ❌ BARE | access with no lock and no atomic |
| 🆕 / 🗑️ / 🔁 / 🧱 | new / removed / signature changed / layout changed |

---

<!-- nav:bottom -->
| ⬅️ [A review, step by step](05-a-review-step-by-step.md) | 📚 [Documentation](../README.md) | [Semantic search](07-semantic-search.md) ➡️ |
|:---|:---:|---:|
<!-- /nav:bottom -->
