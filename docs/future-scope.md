<!-- nav:top -->
📚 [Documentation](README.md) › **Future scope**
<!-- /nav:top -->

# Future scope

This is the strategic direction for StaticSight after the 33-tool release. It is intentionally broader than the
[contributor tracker](contributor-tracker.md): this page explains **why** an area matters and what success looks like;
the tracker splits that direction into small, testable changes a contributor can implement one at a time.

Last reviewed: **October 2, 2026**.

<!-- nav:toc -->
**On this page:** [Direction](#direction) · [Principles that future work must preserve](#principles-that-future-work-must-preserve) · [1. Historical-bug evaluation](#1-historical-bug-evaluation) · [2. Root-cause finding aggregation](#2-root-cause-finding-aggregation) · [3. Interprocedural ownership](#3-interprocedural-ownership) · [4. Deeper locking analysis](#4-deeper-locking-analysis) · [5. Error-contract propagation](#5-error-contract-propagation) · [6. Better type resolution without compiling](#6-better-type-resolution-without-compiling) · [7. Repository knowledge](#7-repository-knowledge) · [8. Review and CI integration](#8-review-and-ci-integration) · [9. Suppression and triage](#9-suppression-and-triage) · [10. Adoption and releases](#10-adoption-and-releases) · [11. Performance and observability](#11-performance-and-observability) · [12. Human finding explorer](#12-human-finding-explorer) · [Recommended delivery sequence](#recommended-delivery-sequence) · [Non-goals](#non-goals)
<!-- /nav:toc -->

## Direction

StaticSight does not need another broad batch of unrelated tools. Its next stage should make the evidence it already
collects:

1. **proven on real defects**, not only planted examples;
2. **quieter and more trustworthy**, by grouping independent evidence around one root cause;
3. **deeper across function boundaries**, especially for ownership, errors and locks;
4. **easier to adopt**, in a pull request, CI job or a new editor;
5. **measurably fast and stable** as repositories grow.

The three highest-value investments are:

| Priority | Theme | Outcome |
|---|---|---|
| P0 | Historical-bug evaluation | Reproducible evidence that the same agent finds more real bugs with StaticSight than without it |
| P0 | Finding aggregation and verification | One root-cause finding supported by cppcheck, skeleton, graph and history evidence, rather than duplicate symptoms |
| P1 | Interprocedural ownership, error and lock analysis | Review findings that cross function boundaries, where the most expensive C++ defects live |

## Principles that future work must preserve

Every future feature must keep the qualities that make StaticSight useful:

- **Zero compile:** no `compile_commands.json`, build, link step or generated `.so` is required.
- **Evidence before inference:** output names the exact `file:line`, engine and heuristic limit.
- **Local and private:** source code is not sent to an external service.
- **Two real implementations:** Python and TypeScript compute the answer independently and remain byte-identical.
- **Incremental by default:** an edit or `git pull` refreshes only what changed.
- **Token economy:** return the smallest useful proof; page long lists through `get_more`.
- **Graceful degradation:** a missing optional engine produces a labelled fallback, not a crash.
- **Measurable quality:** new analysis needs a fixture, golden cases and an evaluation task before promotional claims.
- **No tool proliferation without a workflow:** prefer strengthening `review_changes`, `check_my_edit` and existing
  evidence over adding several overlapping tools.

## 1. Historical-bug evaluation

### Goal

Evaluate StaticSight on real defects that were fixed in project history:

1. identify a bug-fix commit;
2. check out the parent (the vulnerable source);
3. give the agent the original symptom, issue title or affected area;
4. compare the same agent with and without StaticSight;
5. grade whether it found the root cause and the correct `file:line`.

### Measurements

- root-cause recall and false-positive rate;
- correct file and line;
- whether the recommendation matches the real fix;
- time and tokens to first useful evidence;
- tool calls and files read;
- results by finding kind: memory, locking, error handling, compatibility, completeness.

### Intended command

```text
python3 scripts/eval_history.py \
    --repo /path/to/repo \
    --fix-commit abc123 \
    --agent-cmd '…'
```

### Success

A versioned, reproducible report can support a claim such as:

> On N historical defects, the agent found X% of root causes with StaticSight and Y% without it.

## 2. Root-cause finding aggregation

Today one defect can appear as several findings:

- the branch skeleton sees a resource pending at an exit;
- cppcheck reports `memleak`;
- a contract says the allocation MUST pair with a release;
- history says an earlier leak fix touched the function.

These are independent proofs of **one** root cause. The future internal model should represent that:

```text
RootCauseFinding
├── stable id
├── title, severity and confidence
├── primary location and affected symbol
├── evidence[]             # tool, location, message, strength
├── related findings[]
├── affected paths[]
├── counter-evidence[]     # what could make the claim false
├── verification status
└── suppression status
```

The first public surface should be:

```text
explain_finding("F91ac20")
```

It should explain why the confidence is high, which tools agree and what remains heuristic. Later,
`review_changes` can group its report by root cause instead of by tool section.

## 3. Interprocedural ownership

Function-local resource pairing cannot decide whether this is safe:

```cpp
Buffer* p = allocate_buffer();
submit_request(p);  // borrowed, copied, or ownership transferred?
return;
```

StaticSight should infer lightweight ownership contracts from:

- comments: *takes ownership*, *borrowed*, *caller retains ownership*;
- allocate/release pairs and naming conventions;
- smart-pointer construction and `std::move`;
- returns, out parameters and assignment into members or containers;
- release calls in callees;
- annotations such as SAL;
- repeated safe usage elsewhere in the repository.

The analysis should distinguish:

- locally released;
- ownership transferred;
- borrowed;
- escaped to a member, global or container;
- returned to the caller;
- unresolved.

Candidate surfaces:

```text
get_ownership_contract(symbol)
trace_resource_lifecycle(file_path, line, max_depth=4)
```

## 4. Deeper locking analysis

`track_lock_order` follows one call level. A real deadlock may span several:

```text
A::f holds lock_a
  → B::g
    → C::h
      → acquires lock_b
```

The next lock model should:

- compute a cached lock summary per function;
- propagate held-lock sets through a bounded call graph;
- report the exact call chain that introduced each order edge;
- model callbacks invoked while holding a lock;
- recognise condition-variable waits, joins, `future.get()` and coroutine suspension;
- distinguish recursive and non-recursive locks;
- accept an optional repository lock hierarchy.

The state space must have explicit depth, path and node budgets. A result must say when a budget truncated it.

## 5. Error-contract propagation

StaticSight can already mark ignored results. It should eventually answer:

> `decode_msg` gained `-3`. Which callers assume only `0` and `-1`?

The analysis should recognise:

- documented and observed return values;
- call-site comparisons and `switch` statements;
- `SUCCEEDED` / `FAILED`, `HRESULT`, `NTSTATUS`, `errno`, `std::error_code`;
- exceptions and `noexcept`;
- retry, fatal and best-effort handling;
- signed error values stored in unsigned types;
- error-to-protocol or status mappings.

Candidate surfaces:

```text
get_error_contract(symbol)
find_unhandled_error_values(symbol)
trace_error_propagation(symbol, error="-3")
```

## 6. Better type resolution without compiling

Call resolution is deliberately conservative: `obj.f()` may reach any method named `f`. Precision can improve in
tiers without changing the zero-compile promise:

1. **Local declarations:** infer obvious types from `Router r`, `Router* p`, references, range-for variables and
   `std::make_unique<Client>()`.
2. **Local propagation:** follow simple assignments, aliases and `auto`.
3. **Optional syntax parser:** evaluate tree-sitter C++ for declarations, member calls, lambdas and captures.

Every edge should retain its resolution source:

```text
exact qualifier | inferred local type | class-context preference | name-only fallback
```

An optional parser must be benchmarked against the current engine for precision, speed, memory and packaging cost
before it becomes a dependency.

## 7. Repository knowledge

An optional `.staticsight.yml` could describe facts that source-only inference cannot know:

```yaml
modules:
  - name: network
    paths: ["src/net/**"]
    entry_points: ["run_server", "handle_request"]

ownership:
  allocators:
    - allocate: mem::zero_copy_allocate
      release: mem::release_buffer

locking:
  hierarchy: [session_mutex, route_mutex, stats_mutex]

sensitive_types: [Packet, WireHeader, PersistedRecord]
```

Rules must be additive and understandable. Invalid configuration should produce a precise diagnostic; absence of the
file must preserve today's behaviour.

## 8. Review and CI integration

StaticSight should produce stable machine-readable review artifacts:

```text
staticsight review --base origin/main --format json
staticsight review --base origin/main --format sarif --output staticsight.sarif
```

Future integrations can then:

- annotate GitHub or Azure DevOps pull requests;
- update an existing comment instead of posting duplicates;
- compare findings with a previous review;
- resolve a comment when a finding disappears;
- fail CI only for verified findings above a configured severity;
- keep heuristic medium or weak findings informational.

The core work is the report format and incremental finding diff. Platform-specific posting should sit on top of it.

## 9. Suppression and triage

Users need a way to record intentional risk without hiding it:

```cpp
// staticsight: ignore F123abc reason="ownership transferred to queue"
submit(buffer);
```

or:

```yaml
suppressions:
  - finding: F123abc
    reason: "Protected by the startup mutex held by the caller"
    expires: 2027-01-01
```

Requirements:

- a reason is mandatory;
- expiration is optional;
- matching uses finding kind, symbol and code context, not only a line number;
- stale suppressions are reported;
- structured output keeps suppressed findings with their status;
- `review_changes` omits them by default but can show them on request.

## 10. Adoption and releases

Potential improvements:

- publish Python packages to PyPI and TypeScript packages to npm;
- produce signed standalone binaries for Linux, Windows and macOS;
- generate MCP configuration:

  ```text
  staticsight configure vscode
  staticsight configure copilot
  staticsight configure cursor
  staticsight configure claude
  ```

- add `doctor --fix`, which prints an installation plan and asks before acting;
- add a diagnostic bundle containing versions, index metadata and logs, but never source code.

## 11. Performance and observability

Large repositories need explicit budgets:

| Operation | Initial budget |
|---|---:|
| Graph drift check (2,000 files) | < 200 ms |
| Incremental graph refresh (one file) | < 1 s |
| `get_impact`, depth 3 | < 2 s |
| `find_entry_paths`, depth 10 | < 5 s |
| `get_more` | < 50 ms |
| MCP initialization | < 1 s |
| One-shot non-semantic tool start | < 2 s |

A generated scale fixture should create thousands of files and a known call graph in CI. A trace mode should explain
where time went without changing normal MCP output:

```text
STATICSIGHT_TRACE=1 staticsight tool get_impact process_packet
```

```text
freshness        41 ms
resolve symbol    2 ms
caller BFS       37 ms
render            1 ms
total            81 ms
```

## 12. Human finding explorer

An optional static HTML report could show:

- findings grouped by root cause;
- call and entry paths;
- inheritance and lock graphs;
- include blast radius;
- history timeline;
- verified, suppressed and unresolved findings;
- evidence snippets and copyable terminal commands.

The report should consume the same structured findings as MCP. It must not become a second analysis implementation.

## Recommended delivery sequence

### Phase 1: prove and trust

1. Historical-bug evaluation.
2. Root-cause finding schema and evidence aggregation.
3. Suppression and triage.
4. Performance instrumentation and budgets.

### Phase 2: deepen C++ analysis

1. Error-contract extraction and propagation.
2. Interprocedural ownership.
3. Deeper lock propagation.
4. Local type inference; optional parser experiment.

### Phase 3: adoption

1. JSON and SARIF review reports.
2. Incremental re-review.
3. Repository rules.
4. Release packages, configuration generator and diagnostics.
5. Optional finding explorer.

## Non-goals

The roadmap does **not** turn StaticSight into:

- a compiler or replacement for clangd;
- a cloud service that uploads source;
- an autonomous code-review agent;
- a build-system configurator;
- a tool that fails CI on every heuristic warning.

StaticSight remains the evidence layer. The AI agent and the developer make the final judgement.

<!-- nav:bottom -->
| ⬅️ [Developer guide](developer-guide.md) | 📚 [Documentation](README.md) | [Contributor tracker](contributor-tracker.md) ➡️ |
|:---|:---:|---:|
<!-- /nav:bottom -->
