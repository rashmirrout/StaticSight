# Contributing to StaticSight

Thank you for improving StaticSight. The project keeps two independent implementations byte-identical, so the most
important contribution rule is: **one behaviour, two native implementations, one shared proof**.

## Start here

1. [Developer guide](docs/developer-guide.md) — create the Python virtual environment with `uv sync` (or `venv` +
   pip), install the TypeScript packages, run tests, update goldens and reproduce CI.
2. [Future scope](docs/future-scope.md) — the strategic direction and design principles.
3. [Contributor implementation tracker](docs/contributor-tracker.md) — small, dependency-ordered tasks with acceptance
   criteria and copy-ready AI prompts.
4. [Architecture](docs/book/04-architecture.md) and [Trust and testing](docs/book/09-trust-and-testing.md) — the layer
   boundaries and parity model.

## Pick work

- Choose a **Ready** item from the tracker.
- Claim it with the
  [Roadmap implementation item issue template](.github/ISSUE_TEMPLATE/roadmap-item.yml), or open a draft pull request
  with the item ID and add yourself as Owner in the tracker.
- Keep one tracker item per pull request. If the task grows, split it before adding more code.
- Research items produce a report and decision first; they do not add a dependency in the same pull request.

## Required before review

```text
cd staticsight-py && uv run pytest -q
cd ../staticsight-ts && npm test
cd ../staticsight-py
uv run python ../docs/check_docs.py
uv run python ../docs/check_docs.py --impl ts
```

For tool or graph changes, also run:

```text
uv run python ../scripts/parity_check.py /path/to/a/real/cpp/repo 12
```

See the tracker's common quality bar and completion-report template for the full checklist.

## Safety and scope

- Do not require a C++ build or `compile_commands.json`.
- Do not make one implementation call the other.
- Do not weaken a test to make parity pass.
- Do not read outside `WORKSPACE_ROOT` or write outside StaticSight's data directory.
- Do not send repository source to a network service.
- Label heuristics and degraded fallbacks honestly.

## Communication

Explain the user-visible problem first, then the design, evidence, limits and tests. Small, focused pull requests are
preferred over broad refactors.
