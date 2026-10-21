---
name: staticsight-cpp-review
description: Evidence-based review, change planning and investigation of C/C++ code using the StaticSight MCP server (ctags, GNU Global, ripgrep, cppcheck, git, a code graph, local semantic search). Use when asked to review C/C++ changes, a diff, a branch or a PR, when asked "what could break?", when checking the impact of changing a function, struct, header, macro or shared state, before and after editing C/C++ code, when investigating a hang, crash or log message, or when searching a repository by intent ("where do we …?").
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
   | Signature, return values, error codes, preconditions | `get_impact(symbol)` (callers several levels deep, entry points, tests); check every "⚠️ result ignored". `get_upstream_callers` for direct call sites only |
   | Everything about one function at once | `get_context_pack("Class::fn")` or `get_context_pack("file:line")` |
   | Can outside input or a thread reach it? | `find_entry_paths(symbol)`; `get_call_paths(from, to)` for one chain |
   | Virtual method or base class | `get_type_hierarchy(type)`: every override must follow |
   | Enum gained, lost or renamed a value | `find_switch_coverage(enum)`; section 12 of `review_changes` |
   | Paired or platform code (encode/decode, `_win`/`_posix`) | `find_counterparts(symbol)`; section 12 of `review_changes` |
   | Lines an earlier fix touched | `get_line_history(file, start, end)`; section 13 of `review_changes` |
   | Which tests to run, or is one missing | `find_related_tests(symbol)`; section 11 of `review_changes` |
   | Functions newly called by the diff (section 9) | `get_symbol_contract(symbol)`: honour `@pre`, `@warning`, MUST/NEVER, pairing rules |
   | Struct/class/union data members | `track_struct_risks(name)` |
   | Header, macro, inline, template, constant | `get_include_blast_radius(header)` |
   | Member/global touched by concurrent code | `track_state_mutations(symbol)` |
   | Locks added, removed or reordered; calls made while holding a lock; hangs | `track_lock_order()` (or `symbol=` one lock); section 8 of `review_changes` shows cycles for changed functions; `get_lock_graph(path_glob)` for the module's locking design |
   | Every modified .c/.cpp | `run_file_static_audit(file, only_changed_lines=true)`; rerun with `false` for large changes |
   | Symbol location | `get_symbol_definition(symbol)` |
   | Changed function may exist in copies elsewhere | `find_similar_code(file, line)`; section 10 of `review_changes` lists near-duplicates |
   | You know what code does but not its name | `semantic_search("…intent…")`, optionally with `language`, `path_glob` or `kind` |
3. **Verify before you report.** Findings carry IDs such as `F7a0cc5`. Run `verify_finding(id)` on each one you
   report, rule out what it lists, and cite the ID. A list that ends with `Next: get_more("P…")` has more items: fetch
   them when they matter to the verdict.
4. If caller/definition results say "ripgrep fallback", or a graph answer says the code graph is building, call
   `get_index_status` and mention the lower precision.
5. **Semantic search freshness:**
   - After the user pulled, switched branches or made large edits, call `refresh_semantic_index` once before searching.
   - If a semantic result says the index is stale or building, tell the user. Retry after `get_index_status` shows it is ready.
   - During the very first build only keyword results are available.

## While writing code

- Before editing a function: `plan_change(symbol, change="…")` lists every place to touch, the contract to keep, the
  tests to run and the risks.
- After each edit: `check_my_edit()` (only what changed since the previous check) finds leaks on exit paths, cppcheck
  errors, callers still using an old signature, switches missing a value and platform twins left behind. Fix or
  `verify_finding` what it reports before moving on.
- Before committing: `review_changes`.

## Investigating

- From a log line or error message: `find_log_origin("…the line…")`, then `get_context_pack` and `find_entry_paths`.
- A hang or deadlock: `get_lock_graph`, then `track_lock_order` on the module, then `find_entry_paths` for the threads.
- An unfamiliar area: `semantic_search`, `query_graph("members of X")`, `get_type_hierarchy`, `get_change_hotspots`.
- The MCP prompts `investigate_hang`, `investigate_incident`, `plan_refactor` and `onboard_me` give the full workflows.

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
  Graph answers narrow by class where the code says so (`C::f()`, calls inside `C`); `obj.f()` may still reach any `f`.
- Finding confidence: ❌ strong (cppcheck errors, stale callers, switch gaps with no `default:`), ⚠️ medium, ℹ️ weak.

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

- what is wrong, and the evidence (tool name + `file:line` + finding ID when there is one, verified)
- the impact (who or what breaks)
- a concrete fix
- whether it is heuristic and needs human confirmation

Do not invent findings the tools did not support; list open questions separately instead. End with a clear
verdict (e.g. "Not ready to merge: 2 blockers") and the single most important next step.

When the user wants to check a finding themselves, give the matching terminal command: every tool runs as
`staticsight tool <name> [args]` (for example `staticsight tool get_upstream_callers process_packet`) and prints exactly
what you received. StaticSight's documentation (`docs/cli-guide.md`, `docs/mcp-guide.md` in the StaticSight repository)
explains every command.
