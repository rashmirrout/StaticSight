<!-- nav:top -->
📚 [Documentation](../README.md) › 📖 [The book](00-preface.md) › **Chapter 11: Limits and roadmap**
<!-- /nav:top -->

# 11. Limits and roadmap

The last chapter is about what StaticSight cannot do today, and what it could do next. Knowing the limits is part of
using the tool well; the roadmap shows where the evidence could go further.

## Known limits

**No type resolution.** Without a compiler, StaticSight does not know types. Overloads are grouped by name. The code
graph narrows calls by class where the source says so (`C::f()`, or a call inside a member of `C`), but `obj.f()` may
reach any method `f`, because the type of `obj` is unknown. Virtual dispatch is covered through the class hierarchy
(`get_type_hierarchy`, overrides in `get_impact`); calls through function-pointer tables, `std::function` members or
macros that build names are not found as callers. Functions passed to thread and callback APIs are followed.

**Macros.** Code generated or hidden by macros is partly invisible to ctags and to the text analyses. Heavy macro use
can hide braces (affecting skeletons) or calls (affecting callers). cppcheck may need definitions through
`STATICSIGHT_CPPCHECK_ARGS`.

**Lock analysis has a horizon.** `track_state_mutations` sees locks taken in the enclosing function only, not locks
held by callers. `track_lock_order` follows one call level and matches locks by name, so deeper call chains and
aliases (two names for one mutex) are not modelled.

**Function-local resource analysis.** Skeletons pair acquisitions and releases inside one function. Ownership passed to
helpers, smart pointers or out-parameters is not followed.

**Include resolution by name.** Build include paths are unknown, so includes are matched by path suffix; headers with
the same name in different folders produce a warning rather than a precise answer.

**One file at a time for cppcheck.** Whole-program bugs are out of its reach, and partial headers can cause a few false
positives.

**Semantic search is similarity, not proof.** It finds candidates; the precise tools confirm them. The first build of a
large repository takes time (about an hour for 3,000 files on a 16-thread CPU without AVX-512 VNNI), although it runs
in the background and code is indexed first.

**History by commit message.** `get_line_history`, `get_change_hotspots` and section 13 of `review_changes` recognise
bug fixes and reverts from commit subjects (fix, bug, revert, crash, leak, race, …). A fix committed as "update
parser" is not recognised.

**Completeness by name and folder.** Counterparts are found by naming pairs (encode/decode, …), platform folder and
file names (`_win`, `_posix`, …) and git co-change. Twins with unrelated names are left to `find_similar_code`.

Each limit is visible in the output where it matters (labels such as `heuristic`, `ripgrep fallback`, `locks held by
callers are not visible`), so the agent can say "unverified" instead of guessing.

## Roadmap

The next steps come from one observation: after "what changed and who is affected", the most expensive review misses
are about **intent** (why the change was made), **completeness** (what should have changed but didn't), **history**
(was this fixed before), **house rules**, and **trust** (how sure is each finding). The scenarios, labelled A to L,
and where they stand:

| | Scenario | Status |
|---|---|---|
| A | Regression archaeology | ✅ `get_line_history`, section 13 of `review_changes`, fixes in `plan_change` and `get_context_pack`. |
| B | Completeness | ✅ `find_switch_coverage`, `find_counterparts` (pairs, platform twins, co-change), `find_related_tests`, section 12 of `review_changes`, `check_my_edit`. Next: string tables, error-code maps, mocks. |
| C | Intent-aware review | Next: compare the pull request description, work item and commit messages with the diff. |
| D | Looks-safe changes | ✅ partly: overrides through `get_type_hierarchy`; stale callers of changed signatures in `check_my_edit`. Next: default arguments, overload changes, implicit conversions. |
| E | Interprocedural resources and locks | ✅ lock order through one call level, locks across blocking calls, `get_lock_graph`; project allocators in cppcheck. Next: deeper call chains, lambda captures. |
| F | Security flow | Next: untrusted lengths reaching `memcpy` or indexing, using `find_entry_paths` for exposure. |
| G | Compatibility and rollout | Next: wire, disk and ABI formats; config keys; telemetry schemas. |
| H | House rules | Next: a repository rules file plus learned idioms. |
| I | Risk triage for large diffs | ✅ `get_change_hotspots` (churn, fixes, fan-in); section 11 reach. Next: complexity. |
| J | Trust | ✅ finding IDs with confidence, `verify_finding`, structured content. Next: grouping by root cause. |
| K | Pull-request workflow | Next: inline pull-request comments, incremental re-review. |
| L | Measuring quality | ✅ `scripts/benchmark.py` and `scripts/eval_agent.py` (planted-bug tasks, optional agent runs). Next: tasks mined from reverted historical fixes, gates in CI. |

Deeper parsing (a tree-sitter C++ backend for exact structure, types of local variables for `obj.f()`) would sharpen
every graph answer while keeping the zero-compile principle.

The detailed direction now lives in [Future scope](../future-scope.md). Contributors should take implementation-sized
work from the [Contributor tracker](../contributor-tracker.md), which gives each item a stable ID, dependencies,
out-of-scope boundary, acceptance checks and an AI-ready task prompt.

## Contributing

StaticSight is open source. A change is complete when:
1. both implementations behave the same (add or update a golden case in `shared/golden/cases.json`);
2. the tool description in `shared/tool-spec.json` still tells the agent when to use the tool;
3. degraded paths (missing engine, bad input) return a helpful card;
4. `docs/` is updated and `docs/check_docs.py` passes.

Start with the repository's [contribution entry point](../../CONTRIBUTING.md) and
[Developer guide](../developer-guide.md), read [Architecture](04-architecture.md), then claim one Ready item from the
[Contributor tracker](../contributor-tracker.md).

---

This is the end of the book. Thank you for reading. The best way to understand StaticSight now is to run it: build the
test repository, ask your agent for a review, and compare its answer with the evidence from `staticsight tool …`.

---

<!-- nav:bottom -->
| ⬅️ [Using it with AI](10-using-it-with-ai.md) | 📚 [Documentation](../README.md) |   |
|:---|:---:|---:|
<!-- /nav:bottom -->
