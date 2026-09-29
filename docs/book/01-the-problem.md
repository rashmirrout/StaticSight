<!-- nav:top -->
📚 [Documentation](../README.md) › 📖 [The book](00-preface.md) › **Chapter 1: The problem**
<!-- /nav:top -->

# 1. The problem

## An AI reviewer with its eyes half closed

Ask an AI assistant in your editor: *"I changed `process_packet` in `router.cpp`. What could break?"* Without help, the
assistant sees the file in the active tab, perhaps a few neighbours, and whatever it remembers about C++ in general.
It will produce a fluent answer. It may even be right. But it is **guessing**, because the facts that decide the
answer are elsewhere:

- **Who calls `process_packet`**, and what do they do with its return value? The callers live in other files.
- **Which structs does the change touch**, and are those structs copied with `memcpy`, sent over a socket as raw
  bytes, or written to disk? That code is in other modules.
- **Which files include the header** you changed? A one-line edit to a widely used header can change the meaning
  of hundreds of translation units.
- **Which lock protects the member** you now write? The other accesses are in other functions.
- **What does the function you now call require?** Its contract (`@pre`, `@warning`, "MUST be paired with …") is in
  a header the assistant has not opened.

In a small project, the assistant might open those files itself. In a real C++ code base, with thousands of files,
macros, platform branches and generated code, it cannot read everything, and it does not know what to look for.

## Small changes, expensive bugs

The bugs that slip through C++ reviews are rarely dramatic. They are small and local-looking, and their cost shows up far
away. The test repository in this project plants six of the most common ones, all from real incidents:

1. **An early return that leaks.** A new `if (!p->is_encrypted) return -2;` is added *after* a `malloc`. The buffer
   is never freed on that path. Every rejected packet leaks memory.
2. **A struct that grows while it is sent as raw bytes.** A `checksum` field is added to `Packet`. The struct is
   `send()`-ed as `sizeof(Packet)` bytes and `memcpy`-ed into a write-ahead log. Every peer built from older code, and every
   existing log record, now reads garbage after the new field.
3. **A lock removed from a getter.** `get_route_count()` loses its `lock_guard`. It still compiles, and the tests still pass.
   It is a data race.
4. **A new method that writes shared state without the mutex.** `reset()` sets `route_count = 0` while other
   methods hold `route_mutex`.
5. **Callers that ignore a new error value.** `process_packet` can now return `-2`, but two of its three callers throw
   the result away.
6. **Two locks taken in opposite orders.** `rebalance()` takes the pool lock, then the stats lock. A new `report()`
   takes the stats lock and then calls `drain()`, which takes the pool lock. Two threads running these can deadlock,
   and nothing in `report()` itself mentions the pool lock.

None of these is visible in the diff alone. Each needs evidence from elsewhere in the repository: a control-flow path,
a list of call sites, the places a struct's bytes are used, the places a member is accessed and under which lock, the
order in which every function takes its locks.

## Why not just compile it?

The usual answer to "understand C++ precisely" is: use the compiler. Language servers such as clangd, and analysers
built on Clang, give exact types, overloads and call graphs. They need a working build first: a
`compile_commands.json` with the exact flags, include paths and defines for every file, and all generated headers in
place.

In many real repositories that is out of reach at review time:

- The code targets another platform (a Windows driver reviewed on Linux, firmware built with a cross-compile SDK).
- The build needs internal tools, signed packages or hours of time.
- The reviewer, or the AI agent, works in a fresh clone or a pull-request checkout that has never been built.
- The build system is a custom one that cannot produce a compilation database.

StaticSight starts from the opposite assumption: **the code cannot be compiled.** Everything it reports must come from
the source text and from tools that read source text. This is called *zero-compile*, and it is the first of the
principles in the next chapter.

## Why not let the agent search by itself?

Agents can run `grep`. But a raw search returns too much and says too little. `grep -rn process_packet` returns
declarations, comments, the definition and calls, with no indication of which function each call is in or whether its
result is used. Searching for `Packet` returns every mention, not the eight lines where its byte layout matters. The
agent spends its limited context window on noise, and still has to reason out the facts from fragments.

What the agent needs is **pre-digested evidence**: a short answer to a precise question, where each claim points to a
`file:line` that can be checked.

## What the evidence should look like

Here is the answer StaticSight gives to "who calls `process_packet`?" on the test repository:

```text
### 📞 UPSTREAM CALLERS: `process_packet`
Found 3 call sites in 2 files (source: GNU Global).
Returns `int`; ⚠️ 2 caller(s) ignore the result — check they tolerate new error values.

**`src/net/listener.cpp`**
1. L9 in `Listener::on_socket_read` — result used
   `int rc = router_->process_packet(&raw);`
2. L17 in `Listener::dispatch_batch` — ⚠️ result ignored
   `router_->process_packet(&batch[i]);`
**`tests/test_router.cpp`**
3. L6 in `test_drop_invalid` — ⚠️ result ignored
   `r.process_packet(&dummy);`
```

It has the properties a reviewer needs:
- **Precise:** it lists call sites only. Declarations, comments and a variable that happens to share the name are
  filtered out.
- **Contextual:** each call names its caller function and says whether the result is used.
- **Citable:** every line has a `file:line` the agent can quote and you can open.
- **Honest about its source:** "(source: GNU Global)". When the precise index is unavailable, it says "ripgrep
  fallback" instead.
- **Small:** a few hundred characters, not a wall of search results.

The agent can now write: "`src/net/listener.cpp:17` ignores the new `-2` result of `process_packet`; unencrypted
packets are dropped silently." That sentence is a finding, not a guess.

## The division of labour

This leads to the central idea of StaticSight:

> **The agent reasons. StaticSight provides facts.**

StaticSight does not try to be a reviewer. It never calls a language model and never decides whether code is good. It
answers narrow, well-defined questions about the repository, very fast and with evidence, and leaves judgement to
the agent (and to you).

The connection between the two is the **Model Context Protocol (MCP)**, an open standard for giving AI agents tools. An
MCP server announces tools with names, descriptions and parameters; the agent decides when to call them; the server
returns text. StaticSight is such a server. Chapter 10 and the [MCP guide](../mcp-guide.md) cover this in detail.

---

<!-- nav:bottom -->
| ⬅️ [Preface](00-preface.md) | 📚 [Documentation](../README.md) | [Principles](02-principles.md) ➡️ |
|:---|:---:|---:|
<!-- /nav:bottom -->
