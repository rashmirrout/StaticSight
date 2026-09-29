<!-- nav:top -->
📚 [Documentation](../README.md) › 📖 [The book](00-preface.md) › **Chapter 11: Limits and roadmap**
<!-- /nav:top -->

# 11. Limits and roadmap

The last chapter is about what StaticSight cannot do today, and what it could do next. Knowing the limits is part of
using the tool well; the roadmap shows where the evidence could go further.

## Known limits

**No type resolution.** Without a compiler, StaticSight does not know types. Overloads, and methods with the same
name on different classes, are grouped by name. Calls through function pointers, virtual dispatch, `std::function` or
macros that build names are not found as callers.

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

**No history.** StaticSight looks at the current diff and the current code. It does not yet know whether a line was
recently fixed, reverted or often changed.

Each limit is visible in the output where it matters (labels such as `heuristic`, `ripgrep fallback`, `locks held by
callers are not visible`), so the agent can say "unverified" instead of guessing.

## Roadmap

The next steps come from one observation: after "what changed and who is affected", the most expensive review misses
are about **intent** (why the change was made), **completeness** (what should have changed but didn't), **history**
(was this fixed before), **house rules**, and **trust** (how sure is each finding). The candidate scenarios, labelled A
to L:

| | Scenario | What it would add |
|---|---|---|
| A | Regression archaeology | Blame removed or modified lines; surface earlier bug-fix and revert commits and churn on the same code. |
| B | Completeness | Enum values vs `switch` and string tables; symmetric pairs (serialize/deserialize, open/close, register/unregister); `#ifdef` and platform twins; copy-paste clones (the first step, `find_similar_code`, exists); error-code mappings; mocks and function tables; tests that touch changed code. |
| C | Intent-aware review | Compare the pull request description, work item and commit messages with the actual diff: scope creep, missing acceptance criteria. |
| D | Looks-safe changes | Default arguments, `virtual`/`override` drift, overload resolution changes, header macros/inline/`constexpr`, implicit conversions. |
| E | Interprocedural resources and locks | *Started:* lock order (one call level), locks held across blocking calls and Win32 locks are available in `track_lock_order`. Next: deeper call chains, resource pairing across functions, lambda captures. |
| F | Security flow | Untrusted lengths reaching `memcpy` or indexing, size overflow, TOCTOU, unchecked `HRESULT`, focused on the diff. |
| G | Compatibility and rollout | Wire, disk and ABI formats; registry and config keys; telemetry schemas; feature flags; mixed-version upgrades. |
| H | House rules | A repository rules file plus learned idioms; flag deviations. |
| I | Risk triage for large diffs | Rank changes by fan-in, bug history, complexity and sensitive APIs. |
| J | Trust | A self-verification pass, confidence scores, de-duplication, grouping by root cause. |
| K | Pull-request workflow | Inline pull-request comments in a polite, inquisitive tone; incremental re-review; tracking of resolved threads; an author pre-push mode. |
| L | Measuring quality | A benchmark from reverted historical bug fixes plus seeded fixtures; recall, precision and cost gates in CI. |

The proposed order starts with **L** (measure before improving), then **A** (history), **B** (completeness) and
**J** (trust), then **C** and **K**, then D to I.

The proposed tools come in three phases. Each phase keeps the zero-compile principle:

1. **With the current engines** (git, ctags, ripgrep): a benchmark runner, line history, change hot spots, switch
   coverage, counterpart finding, related tests, and History and Completeness sections in `review_changes`.
2. **Verification and workflow:** a finding verifier with confidence, change-risk ranking (with a complexity tool
   such as lizard), mapping findings to pull-request threads, incremental review since a given commit.
3. **Deeper parsing:** a tree-sitter C++ backend for more precise structure, interprocedural resource pairs, a lock graph,
   override integrity, signature impact, untrusted-input tracing, house-rule checks (for example with semgrep), and
   contract surfaces (IDL, protobuf, registry, telemetry).

## Contributing

StaticSight is open source. A change is complete when:
1. both implementations behave the same (add or update a golden case in `shared/golden/cases.json`);
2. the tool description in `shared/tool-spec.json` still tells the agent when to use the tool;
3. degraded paths (missing engine, bad input) return a helpful card;
4. `docs/` is updated and `docs/check_docs.py` passes.

Start with [Getting started](../getting-started.md), read [Architecture](04-architecture.md), and run both test suites.

---

This is the end of the book. Thank you for reading. The best way to understand StaticSight now is to run it: build the
test repository, ask your agent for a review, and compare its answer with the evidence from `staticsight tool …`.

---

<!-- nav:bottom -->
| ⬅️ [Using it with AI](10-using-it-with-ai.md) | 📚 [Documentation](../README.md) |   |
|:---|:---:|---:|
<!-- /nav:bottom -->
