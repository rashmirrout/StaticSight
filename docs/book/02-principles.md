<!-- nav:top -->
📚 [Documentation](../README.md) › 📖 [The book](00-preface.md) › **Chapter 2: Principles**
<!-- /nav:top -->

# 2. Principles

StaticSight is shaped by a small number of rules. Most design decisions in later chapters follow directly from one of
them, so they are worth stating up front.

## 1. Zero-compile

**Assume the code cannot be built.** No `compile_commands.json`, no CMake, no build output, no generated headers.

This rules out compiler-based analysis and forces every tool to work from source text. The price is precision: without
a compiler, StaticSight cannot resolve overloads by type or expand every macro. The benefit is that it works on any
checkout, on any machine, in seconds, including code for another platform.

Where precision matters, StaticSight uses the most precise *text-level* tool available (a real parser such as
Universal Ctags, a real cross-reference index such as GNU Global, a real static analyser such as cppcheck) and
falls back to simpler methods only when those are missing.

## 2. Evidence, not opinion

**Every claim points to a place in the code.** Results are lists of `file:line` locations with the relevant line of code,
not summaries or verdicts. The agent turns evidence into judgement; StaticSight never claims that code is correct or
incorrect on its own authority.

A consequence: tools report what they found **and how they found it**. `(source: GNU Global)` versus `(source: ripgrep
fallback)`, "heuristic" notes on text-based analyses, "(operation within ±2 lines)" when a match is on a neighbouring
line. The agent can weigh the evidence accordingly.

## 3. The agent reasons; the server is fast and narrow

StaticSight contains no language model and makes no network calls (except for a one-time, opt-in download of the search
model). Each tool answers one precise question, in seconds, from local data. This keeps it predictable, cheap and
private: your code never leaves your machine through StaticSight.

## 4. Token economy

An AI agent has a limited context window, and everything a tool returns competes for it. So:

- Output is **concise Markdown**: headings, short lists, one evidence line per item.
- Lists are **capped** (15 items by default) and end with "…and N more", plus a hint on how to narrow the question.
- Each answer has a **character budget** (6,000 by default; 16,000 for the full review bundle). When an answer is cut,
  code fences are closed properly so the Markdown stays valid.
- Engines are asked for **structured output** (ctags and ripgrep JSON, cppcheck XML), parsed in code, and rendered
  compactly, instead of passing raw command output through.

## 5. Never crash, always explain

A tool call must never take the server down, and must never return a stack trace. Missing engines, timeouts, deleted
files, bad git refs, paths outside the repository and invalid arguments all come back as a short **error card**:

```text
### ❌ Invalid argument
`../../etc/passwd` is outside the workspace (WORKSPACE_ROOT).

💡 Only files inside WORKSPACE_ROOT can be inspected.
```

The 💡 hint tells the agent (or you) how to fix the situation, for example the exact command to install a missing
engine. Other tools keep working when one engine is missing: without GNU Global, callers come from ripgrep; without
cppcheck, only the static audit is unavailable.

## 6. No shell, and a fence around the repository

StaticSight runs other programs, and some of their arguments come from the agent, which may in turn be influenced
by the content it reads. So:

- Programs are started **directly, with an argument list**, never through a shell. There is no string that a shell
  could interpret, so there is nothing to inject.
- User-supplied values go after `--` where the tool supports it, symbols are validated as C++ identifiers, and
  regular expressions are escaped.
- Every file argument is resolved and must lie **inside the workspace**; symlinks that escape it are refused.
- Only real executables are run (on Windows, `.exe`/`.com` only, never `.bat`/`.cmd` wrappers that go through `cmd.exe`).

## 7. Nothing installs itself

StaticSight never installs software on its own. When an engine is missing, the answer says which one and how to install
it. The installers in `scripts/` are opt-in: they show a plan and ask before changing anything. The Python launcher's
`--install` shows the exact `pip` command and asks too.

## 8. Leave the repository clean

StaticSight writes only to its own data folder, `<repo>/.staticsight/` (the GNU Global database and the semantic index).
That folder contains its own `.gitignore` with `*`, so git ignores it without any edit to your `.gitignore`. It never
modifies source files, never installs git hooks and never changes git state.

## 9. Heuristics are labelled

Some useful questions cannot be answered exactly without a compiler: "which exits leak this allocation?", "is this
access under a lock?". StaticSight answers them with careful text analysis (comments and strings removed, brace depth
tracked) and **says so** in the output: `⚠️ heuristic (comment/string-stripped text + brace depth, not a compiler)`.
The agent is told, in the tool descriptions and in the review skill, to verify heuristic findings before asserting them.

## 10. One contract, two implementations

StaticSight exists twice, in Python and in TypeScript, so it can run wherever a team already has one of the two runtimes.
Both read the same tool catalogue (`shared/tool-spec.json`), and both must produce **byte-identical** output for the
same input. This is enforced by shared golden tests on Linux and Windows. Having two implementations is also a
powerful check: every disagreement found during development was a bug in one of them.

## 11. Identical on every OS

Everything above the thin platform layer is OS-independent. Paths in output always use `/`, file encodings are
normalised, and the same repository produces the same answer on Linux, macOS and Windows. Chapter 8 explains how.

## How the principles show up

| When you see… | It comes from principle… |
|---|---|
| `file:line` on every item | 2, evidence |
| "…and 23 more" | 4, token economy |
| `(source: ripgrep fallback)` | 2 and 5, honest degradation |
| `### ❌ … 💡 …` instead of an exception | 5, never crash |
| `⚠️ heuristic` | 9, labelled heuristics |
| `.staticsight/` with its own `.gitignore` | 8, clean repository |
| the same output from Python and Node | 10, one contract |

---

<!-- nav:bottom -->
| ⬅️ [The problem](01-the-problem.md) | 📚 [Documentation](../README.md) | [The engines](03-the-engines.md) ➡️ |
|:---|:---:|---:|
<!-- /nav:bottom -->
