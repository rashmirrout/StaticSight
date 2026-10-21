<!-- nav:top -->
📚 [Documentation](README.md) › **Contributor tracker**
<!-- /nav:top -->

# Contributor implementation tracker

Pick one item from this page, implement it in both languages, prove it with tests, and update its status in the same
pull request. The tasks are deliberately smaller than the themes in [Future scope](future-scope.md), so an AI coding
agent can investigate and implement one without silently expanding the scope.

Last reviewed: **October 2, 2026**.

<!-- nav:toc -->
**On this page:** [How to use this tracker](#how-to-use-this-tracker) · [Common quality bar](#common-quality-bar) · [AI implementation contract](#ai-implementation-contract) · [Ready queue](#ready-queue) · [Ready item definitions](#ready-item-definitions) · [Dependency backlog](#dependency-backlog) · [Research briefs](#research-briefs) · [Completion report template](#completion-report-template) · [Maintainer rules for the tracker](#maintainer-rules-for-the-tracker)
<!-- /nav:toc -->

## How to use this tracker

1. Choose an item whose status is **Ready** and whose dependencies are complete.
2. Open a **Roadmap implementation item** issue from
   [the issue template](../.github/ISSUE_TEMPLATE/roadmap-item.yml), or a draft pull request containing the item ID,
   for example `EVAL-001`.
3. Change its row to **In progress** and add your handle under Owner. One item per contributor at a time.
4. Copy the item's AI task into your coding agent, followed by the repository's
   [developer guide](developer-guide.md) and relevant source paths.
5. Keep the pull request inside the stated deliverables. New design decisions go into the issue before code.
6. Run the item's acceptance checks and the common completion checks.
7. Change the status to **Done** only in the pull request that implements it.

### Status values

| Status | Meaning |
|---|---|
| Ready | Bounded, dependencies complete, may be claimed |
| Research | Produce a design/experiment first; do not ship a dependency yet |
| Blocked | A named dependency is incomplete |
| In progress | Claimed by one contributor; Owner must be filled |
| Done | Merged implementation and tests |

### Size

| Size | Expected scope |
|---|---|
| S | One focused component, usually 1-3 days |
| M | Several components or both implementations, usually under a week |
| L | Multi-stage work: split it into smaller pull requests before implementation |

## Common quality bar

Every implementation item must satisfy all applicable checks:

- Python and TypeScript implement the behaviour independently; neither invokes the other.
- Tool output is byte-identical; add or update `shared/golden/cases.json`.
- New findings include stable IDs, confidence and `file:line`.
- Missing engines, invalid input and timeouts produce helpful Markdown cards.
- Source access stays inside `WORKSPACE_ROOT`; data writes stay in the StaticSight data directory.
- Large lists use the output budget and `get_more`.
- Add a fixture or generated case that proves the feature and a negative case that avoids a false positive.
- Update tool descriptions, prompts, skill guidance and docs when the agent's workflow changes.
- Run:

  ```text
  cd staticsight-py && uv run pytest -q
  cd ../staticsight-ts && npm test
  cd ../staticsight-py
  uv run python ../docs/check_docs.py
  uv run python ../docs/check_docs.py --impl ts
  uv run python ../scripts/parity_check.py /path/to/a/real/cpp/repo 12
  ```

## AI implementation contract

Use this preamble before the item-specific task:

```text
Implement tracker item <ID> only. Read docs/developer-guide.md, docs/future-scope.md and the item definition first.
Investigate existing patterns before editing. Python is the behavioural reference, but TypeScript must be a native
independent implementation with byte-identical output. Do not weaken tests, delegate one implementation to the other,
or add a compile requirement. Add positive, negative, degradation, golden and parity coverage required by the item.
Keep source reads inside WORKSPACE_ROOT and writes inside StaticSight's data folder. Run the item's acceptance checks
and the common quality checks. Report files changed, tests, performance and remaining heuristic limits.
```

The item task below should follow that preamble.

## Ready queue

| ID | Item | Theme | Size | Status | Dependencies | Owner |
|---|---|---|---:|---|---|---|
| EVAL-001 | Historical case schema and loader | Evaluation | S | Ready | — | — |
| FIND-001 | Root-cause finding data model | Trust | M | Ready | — | — |
| SUP-001 | Suppression file schema and diagnostics | Trust | M | Ready | — | — |
| PERF-001 | Per-tool timing trace | Performance | S | Ready | — | — |
| PERF-002 | Generated scale fixture | Performance | M | Ready | — | — |
| RULE-001 | `.staticsight.yml` loader and validation | Repository rules | M | Ready | — | — |
| DX-001 | MCP configuration generator | Adoption | M | Ready | — | — |

## Ready item definitions

### EVAL-001 — Historical case schema and loader

**Goal:** define how a historical bug is described, validate the file, and load it without checking out code yet.

**Deliverables**

- `shared/eval/history.schema.json`.
- A documented case format with: ID, repository, fix commit, optional parent, question, expected locations and
  keywords, finding category, and optional issue/commit text.
- `scripts/eval_history.py --validate CASES.json`.
- Clear diagnostics with a JSON path for missing or invalid fields.
- Three unit cases: valid, missing required field, invalid commit format.

**Out of scope:** cloning, checkout, running an agent, grading.

**Acceptance**

```text
python3 scripts/eval_history.py --validate shared/eval/history-sample.json
python3 scripts/eval_history.py --validate invalid.json   # exit 2, precise field error
```

**AI task**

```text
Implement EVAL-001. Design a minimal versioned JSON schema for historical bug cases and a standard-library loader and
validator in scripts/eval_history.py. Do not clone or run git yet. Include a sample and focused tests. Preserve the
existing shared/eval/tasks.json format; this is a separate historical-case format.
```

---

### FIND-001 — Root-cause finding data model

**Goal:** add an internal model that can group several current findings without changing any tool output yet.

**Deliverables**

- Shared design document or schema for `RootCauseFinding` and `Evidence`.
- Native Python and TypeScript types and deterministic JSON serialization.
- Fields: stable ID, title, severity, confidence, primary location, symbol, evidence, related finding IDs,
  counter-evidence, verification and suppression status.
- A deterministic grouping key specification.
- Unit and cross-language serialization tests.

**Out of scope:** grouping algorithms, `explain_finding`, changes to `review_changes`.

**Acceptance**

- The same fixture object serializes byte-identically in both languages.
- Unknown future fields can be ignored when reading a newer stored record.
- Current `Finding` JSON remains backward compatible.

**AI task**

```text
Implement FIND-001 as a data-model-only change. Do not alter Markdown or merge findings yet. Define the smallest
versioned model that can represent one root cause with several independent evidence records. Add native Python and
TypeScript serializers and byte-parity tests.
```

---

### SUP-001 — Suppression file schema and diagnostics

**Goal:** parse and validate suppressions, but do not apply them to findings yet.

**Deliverables**

- A versioned suppression section in `.staticsight.yml` or a documented separate file.
- Required `reason`; optional expiry; finding ID/kind/symbol/context matching fields.
- Parser in both implementations with the same normalized record.
- Diagnostics for missing reason, invalid date, unknown keys and duplicate entries.
- `staticsight suppressions validate` or an equivalent internal/test entry point.

**Out of scope:** hiding findings, inline source comments, stale suppression analysis.

**Acceptance**

- No configuration file preserves today's behaviour.
- Invalid configuration names the file, record and field.
- The repository source is never modified.

**AI task**

```text
Implement SUP-001: suppression schema, parser, normalization and validation only. Do not filter tool output yet. Use
the same records and error text in Python and TypeScript, and add Windows path/date tests.
```

---

### PERF-001 — Per-tool timing trace

**Goal:** explain where a tool spent time without changing stdout or MCP content.

**Deliverables**

- `STATICSIGHT_TRACE=1` emits stage timings to stderr.
- Common stages: freshness, engine/index work, analysis, rendering, total.
- Disabled mode has negligible overhead and no extra output.
- Python and TypeScript use the same labels and units.
- Sensitive source lines and arguments are not logged.

**Acceptance**

```text
STATICSIGHT_TRACE=1 staticsight tool get_impact process_packet
```

Stdout must remain byte-identical to the golden; stderr contains monotonic non-negative millisecond timings and
`total`.

**AI task**

```text
Implement PERF-001 with a request-local timing collector and stderr renderer. Instrument one graph tool, one engine
tool and one semantic tool through shared boundaries rather than tool-specific print statements. Prove stdout parity.
```

---

### PERF-002 — Generated scale fixture

**Goal:** create a deterministic large repository without storing thousands of generated files in git.

**Deliverables**

- `scripts/make_scale_fixture.py`.
- Options for file count, function count, calls, inheritance depth and include fan-out.
- A fixed seed and a manifest containing expected graph counts and known paths.
- Generated source compiles syntactically enough for ctags/rg/cppcheck, but no build is required.
- Tests for determinism and expected counts.

**Acceptance**

```text
python3 scripts/make_scale_fixture.py /tmp/scale --files 2000 --functions 50000 --calls 120000
```

Two runs with the same arguments produce identical file hashes and manifest.

**AI task**

```text
Implement PERF-002 as a standard-library generator. Make the graph shape deterministic and include known caller,
entry, hierarchy, lock and include scenarios so later performance gates can assert answers, not only timing.
```

---

### RULE-001 — `.staticsight.yml` loader and validation

**Goal:** introduce the optional repository-rules file with no behavioural rules yet.

**Deliverables**

- Versioned schema for modules, entry points, allocator pairs, lock hierarchy and sensitive types.
- Identical normalized data in Python and TypeScript.
- Helpful diagnostics for invalid YAML, unknown fields and values outside the workspace.
- `get_index_status` reports whether rules loaded and their path.
- No file means no output or behavioural change except a status line such as `repository rules: not configured`.

**Design decision:** prefer a small YAML dependency only if it can be packaged consistently in both implementations;
otherwise use a restricted documented subset or JSON. Record the decision in the PR.

**AI task**

```text
Implement RULE-001 as loading and validation only. Do not change call resolution, allocators or locking yet. Include
path-security tests, malformed input tests and byte-identical normalized JSON.
```

---

### DX-001 — MCP configuration generator

**Goal:** generate correct client configuration without asking users to hand-edit paths.

**Deliverables**

```text
staticsight configure vscode
staticsight configure copilot
staticsight configure cursor
staticsight configure claude
```

- Print to stdout by default; `--write PATH` only after confirmation (or `--yes`).
- Absolute executable/repository paths, Windows separators and JSON escaping.
- Refuse to overwrite an existing server entry unless `--force`.
- No network access.

**Acceptance:** golden configurations on Linux, Windows and paths containing spaces/non-ASCII characters.

**AI task**

```text
Implement DX-001 as deterministic config generation. Start with stdout-only generation for the four clients, then add
safe optional writing. Reuse the current launcher and --repo conventions; do not invent a new server command.
```

## Dependency backlog

These items become Ready when their dependencies are Done. Before implementation, move one into the Ready queue and
write a full item definition like the ones above.

| ID | Item | Size | Status | Dependencies |
|---|---|---:|---|---|
| EVAL-002 | Build a temporary pre-fix workspace from a local fix commit | M | Blocked | EVAL-001 |
| EVAL-003 | Run agent and baseline command templates on historical cases | M | Blocked | EVAL-002 |
| EVAL-004 | Historical metrics and Markdown/JSON report | M | Blocked | EVAL-003 |
| EVAL-005 | Optional CI regression gate for a pinned history corpus | M | Blocked | EVAL-004 |
| FIND-002 | Merge equivalent evidence into root-cause groups | M | Blocked | FIND-001 |
| FIND-003 | `explain_finding` MCP tool | M | Blocked | FIND-002 |
| FIND-004 | Group `review_changes` by root cause | L | Blocked | FIND-002, FIND-003 |
| SUP-002 | Apply suppressions to structured findings | M | Blocked | SUP-001, FIND-001 |
| SUP-003 | Inline suppression comments | M | Blocked | SUP-002 |
| SUP-004 | Report stale or expired suppressions | S | Blocked | SUP-002 |
| OWN-001 | Ownership vocabulary and contract extraction | M | Blocked | RULE-001 |
| OWN-002 | Cached ownership summary per function | M | Blocked | OWN-001 |
| OWN-003 | Bounded resource lifecycle tracing across calls | L | Blocked | OWN-002 |
| ERR-001 | Extract return/error contracts | M | Blocked | RULE-001 |
| ERR-002 | Find callers that do not handle a new error value | L | Blocked | ERR-001 |
| ERR-003 | Trace error propagation and mapping | L | Blocked | ERR-002 |
| LOCK-001 | Cached lock summary per function | M | Blocked | PERF-001 |
| LOCK-002 | Propagate lock order through bounded call paths | L | Blocked | LOCK-001 |
| LOCK-003 | Model waits, joins, futures, callbacks and coroutine suspension | L | Blocked | LOCK-002 |
| TYPE-001 | Infer local declared pointer/reference/value types | M | Blocked | PERF-002 |
| TYPE-002 | Narrow member-call graph edges with inferred local types | M | Blocked | TYPE-001 |
| TYPE-003 | Tree-sitter C++ precision/performance experiment | M | Research | PERF-002 |
| TYPE-004 | Optional parser adapter | L | Blocked | TYPE-003 decision |
| RULE-002 | Apply configured entry points, allocator pairs and sensitive types | M | Blocked | RULE-001 |
| RULE-003 | Check configured lock hierarchy | M | Blocked | RULE-001, LOCK-001 |
| REPORT-001 | Stable review JSON format | M | Blocked | FIND-001 |
| REPORT-002 | SARIF exporter | M | Blocked | REPORT-001 |
| REPORT-003 | Diff findings against a previous report | M | Blocked | REPORT-001 |
| REPORT-004 | PR comment adapters with update/de-duplication | L | Blocked | REPORT-003 |
| PERF-003 | Performance benchmark runner and JSON baselines | M | Blocked | PERF-001, PERF-002 |
| PERF-004 | CI performance regression budgets | M | Blocked | PERF-003 |
| DIAG-001 | `get_diagnostics` tool for indexes, fallbacks and slow calls | M | Blocked | PERF-001 |
| DX-002 | `doctor --fix` plan and confirmation flow | M | Blocked | DX-001 |
| DIST-001 | PyPI/npm release workflow and package smoke tests | M | Blocked | DX-001 |
| DIST-002 | Signed standalone binary experiment | L | Research | DIST-001 |
| MODEL-001 | Foundry Local / hosted embedding provider experiment | M | Research | — |
| UI-001 | Static HTML finding explorer consuming review JSON | L | Blocked | REPORT-001, FIND-003 |

## Research briefs

Research items produce a checked-in report and a decision; they do not silently add a dependency.

### TYPE-003 — Tree-sitter C++ experiment

Compare current parsing with tree-sitter on:

- member-call precision (`obj.f()`);
- lambdas and captures;
- macros and malformed/incomplete code;
- parse time and peak memory at 100, 2,000 and 10,000 files;
- Linux, Windows and macOS packaging;
- Python/TypeScript grammar parity.

Decision options: reject; use only for local type hints; optional backend; default backend. Include a migration and
fallback plan.

### DIST-002 — Standalone binary experiment

Build one Python and one TypeScript binary candidate. Measure size, startup, engine discovery, model loading, licensing,
code signing, Windows antivirus behaviour and whether shared files are packaged correctly. Do not choose a release
format until the report is reviewed.

### MODEL-001 — Microsoft Foundry embedding provider experiment

Compare three explicitly different security/deployment modes:

1. the current pinned local ONNX runtime;
2. a local Foundry Local embedding endpoint;
3. an Azure-hosted Foundry/OpenAI embedding deployment.

Measure query/index throughput, batching, cost, authentication, offline behavior, model/version pinning and the privacy
impact of sending source chunks to a service. The Foundry catalog includes embedding assets, but catalog assets may be
custom vLLM packages or hosted deployments rather than StaticSight-compatible ONNX directories. Do not add a catalog
name to `shared/semantic/models.json` unless the exact revision exposes the tokenizer + token-hidden-state ONNX contract
and immutable hashes required by the current loader.

Decision options: keep local ONNX only; add opt-in Foundry Local provider; add explicit remote provider; reject both.

## Completion report template

Use this in the pull request:

```text
Tracker item:
Scope delivered:
Files changed:
Behaviour before / after:
Heuristic limits:
Python tests:
TypeScript tests:
Golden cases:
Parity check:
Performance:
Docs:
Security/path/write review:
Deferred work:
```

## Maintainer rules for the tracker

- Keep at most 8-12 items Ready. Split or block the rest.
- Every Ready item needs explicit out-of-scope text and executable acceptance checks.
- Do not mark an L item Ready until it is split into independently mergeable S/M items.
- When design changes, update [Future scope](future-scope.md); when implementation changes, update this tracker.
- Completed items may move to a compact Done table after two releases; keep their IDs stable.

<!-- nav:bottom -->
| ⬅️ [Future scope](future-scope.md) | 📚 [Documentation](README.md) |   |
|:---|:---:|---:|
<!-- /nav:bottom -->
