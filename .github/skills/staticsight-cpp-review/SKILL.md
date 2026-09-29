---
name: staticsight-cpp-review
description: Evidence-based review of C/C++ changes and code search using the StaticSight MCP server (ctags, GNU Global, ripgrep, cppcheck, git, local semantic search). Use when asked to review C/C++ changes, a diff, a branch or a PR, when asked "what could break?", when checking the impact of changing a function, struct, header, macro or shared state, or when searching a repository by intent ("where do we …?").
---

# StaticSight C++ review

StaticSight gives you zero-compile facts about the C/C++ workspace. You do the reasoning. Every claim in your
review must be backed by a StaticSight result, cited as `file:line`.

In Copilot CLI and VS Code the tools may appear with a server prefix, e.g. `staticsight-review_changes`.
If no StaticSight tools are available, tell the user to configure the MCP server (see the StaticSight README) and stop.

## Workflow

1. **Get the whole picture in one call:** `review_changes` (optionally `base_ref`, e.g. `HEAD~1`, `origin/main`).
   - The default base is the merge-base with `origin/main`, falling back to `origin/master`.
   - If the user means "my last commit", "staged changes" or a specific PR base, pass `base_ref`.
   - If the first section shows a huge diff (> 20 files), ask which area to focus on, or use `get_diff_scopes(path_glob=...)`.
2. **Drill down on every item the bundle raises.** Do not stop at the bundle; it is capped by a token budget.
   | Changed thing | Call |
   |---|---|
   | Function body | `get_branch_skeleton(file, symbol=...)`, then `get_enclosing_scope(file, line)` for the full code |
   | Signature, return values, error codes, preconditions | `get_upstream_callers(symbol)`; check every "⚠️ result ignored" |
   | Functions newly called by the diff (section 9) | `get_symbol_contract(symbol)`: honour `@pre`, `@warning`, MUST/NEVER, pairing rules |
   | Struct/class/union data members | `track_struct_risks(name)` |
   | Header, macro, inline, template, constant | `get_include_blast_radius(header)` |
   | Member/global touched by concurrent code | `track_state_mutations(symbol)` |
   | Locks added, removed or reordered; calls made while holding a lock; hangs | `track_lock_order()` (or `symbol=` one lock); section 8 of `review_changes` shows cycles for changed functions |
   | Every modified .c/.cpp | `run_file_static_audit(file, only_changed_lines=true)`; rerun with `false` for large changes |
   | Symbol location | `get_symbol_definition(symbol)` |
   | Changed function may exist in copies elsewhere | `find_similar_code(file, line)`; section 10 of `review_changes` lists near-duplicates |
   | You know what code does but not its name | `semantic_search("…intent…")`, optionally with `language`, `path_glob` or `kind` |
3. If caller/definition results say "ripgrep fallback", call `get_index_status` and mention the lower precision.
4. **Semantic search freshness:**
   - After the user pulled, switched branches or made large edits, call `refresh_semantic_index` once before searching.
   - If a semantic result says the index is stale or building, tell the user. Retry after `get_index_status` shows it is ready.
   - During the very first build only keyword results are available.

## Reading the output

- ✏️ = line changed in the diff; 🔶 = inside a changed function; 🛑 = early exit; ⚠️ = heuristic warning.
- `get_branch_skeleton`, the leak warnings and the lock analysis are **text heuristics** (comments and strings
  stripped, brace depth). Confirm with `get_enclosing_scope` before reporting them as fact.
- cppcheck `error` findings on ✏️ lines are the strongest evidence. If the audit notes an unknown macro, say that
  coverage is partial (the user can pass defines via `STATICSIGHT_CPPCHECK_ARGS`).
- "Inconsistent locking" means the same state is accessed with and without a lock. The tool cannot see locks
  held by callers, so check the callers before calling it a race.
- `semantic_search` / `find_similar_code` scores are cosine similarity (higher is closer). They find candidates by meaning:
  open the code (`get_enclosing_scope`) before claiming behaviour. "keyword" results matched words, not intent.
- `track_struct_risks` "nearby" hits mean the memory operation is within ±2 lines. Read the code to confirm
  it operates on that type.
- Callers are matched by name, so methods with the same name on other classes may appear. Discard unrelated ones.

## Checklist of small but costly issues

- Every allocation, lock, handle, open or acquire is released on **every** path, including new early returns and throws.
- Shared state is not read or written without the mutex that protects it elsewhere. No lock is held across I/O or callbacks.
- New error codes or exceptions are handled by all callers. No ignored results from functions whose contract changed.
- Preconditions (non-null, ranges, sizes), ownership transfer and thread-safety notes from doc comments are respected.
- const/noexcept/virtual/override/default-argument changes don't silently change overload resolution or ABI.
- Struct layout changes are safe for `sizeof`, `memcpy`/`memcmp`, casts, wire and disk formats. `static_assert`s are updated.
- Changed macros, inline functions and constants are acceptable for every includer.
- Integer width/signedness, overflow, narrowing, off-by-one in loops and bounds.
- Lifetime: dangling references/iterators, use-after-move, iterator invalidation.
- Exception safety: no partially updated state when something throws mid-function.
- Copy-paste twins: a bug fixed in one copy (found via `find_similar_code`) but not in the others.

## Reporting

Group findings by severity: **Blocker**, **Major**, **Minor**, **Nit**. For each finding give:

- what is wrong, and the evidence (tool name + `file:line`)
- the impact (who or what breaks)
- a concrete fix
- whether it is heuristic and needs human confirmation

Do not invent findings the tools did not support; list open questions separately instead. End with a clear
verdict (e.g. "Not ready to merge: 2 blockers") and the single most important next step.

When the user wants to check a finding themselves, give the matching terminal command: every tool runs as
`staticsight tool <name> [args]` (for example `staticsight tool get_upstream_callers process_packet`) and prints exactly
what you received. StaticSight's documentation (`docs/cli-guide.md`, `docs/mcp-guide.md` in the StaticSight repository)
explains every command.
