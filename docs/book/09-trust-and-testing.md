<!-- nav:top -->
📚 [Documentation](../README.md) › 📖 [The book](00-preface.md) › **Chapter 9: Trust and testing**
<!-- /nav:top -->

# 9. Trust and testing

A review tool is only useful if its answers can be trusted. This chapter explains how StaticSight earns that trust:
a test repository with known bugs, golden outputs shared by two implementations, tests that break the environment on
purpose, and documentation that is checked like code.

## A test repository with known answers

`shared/fixtures/` describes a small C++ project as **data**: the files of a base commit, a feature commit, and a
working tree on top, listed in `manifest.json`. `make_fixture.py` (Python) and `buildFixture` (TypeScript) turn it into a
real git repository, with fixed author dates so commit SHAs are identical on every machine. No shell is used, so it
builds the same way on Windows.

The feature branch plants the review bugs from Chapter 1:
- an early return that leaks a `malloc` buffer;
- a struct that gains a field while being `memcpy`'d, `send`'d and `sizeof`'d;
- a lock removed from a getter, and a new method writing shared state without the mutex;
- callers that ignore a new return value;
- two locks taken in opposite orders (one of them through a call), and a `send()` while a lock is held.

It also contains the traps a real repository has: a Win32 `HANDLE` leak with SAL annotations, decoys in comments and
strings (a `free(buf)` inside a comment must not count as a release), CRLF, UTF-8-with-BOM and UTF-16 files, an unstaged
edit, an untracked file, a Markdown design note, a Python helper and a YAML config for semantic search.

Because the bugs are known, the tests can check not only that tools run, but that they **find the right things and
nothing else**.

## Golden outputs

`shared/golden/cases.json` lists 40 tool calls on the test repository: every tool, several parameter combinations, and
error cases (a path outside the workspace, a deleted file, a line past the end of the file, a bad git ref, an invalid
symbol, an empty query). For each case, the exact expected Markdown is stored in `shared/golden/<case>.md`.

Both test suites run every case and compare the output **byte for byte** with the golden file. This catches:
- regressions: any change in output shows up as a diff in review;
- divergence between Python and TypeScript: they read the same golden files;
- OS differences: CI runs the suites on Linux and Windows.

When output changes on purpose, the goldens are regenerated from the Python implementation
(`STATICSIGHT_UPDATE_GOLDEN=1`), the diff is reviewed like code, and the TypeScript suite must then match.

The command line is tested against the same goldens: `staticsight tool NAME --json ARGS` must print exactly the golden
file, in both implementations. What you see in a terminal is provably what the agent receives.

## Parity, beyond goldens

Some behaviour cannot be captured in a golden file, so there are direct parity tests:
- the TypeScript server answers from a semantic index **built by Python**, byte for byte;
- tokenisation and embeddings match across the two ONNX runtimes (token ids identical, vectors within 3e-8);
- `tool --list`, `tool NAME --help` and every command-line error message are identical.

## Breaking things on purpose

Principle 5 says tools never crash. The *degradation* tests check it by removing engines:
`STATICSIGHT_DISABLE_ENGINES=global,gtags` makes StaticSight behave as if GNU Global were not installed, and the
tests assert that callers switch to the ripgrep fallback **and say so**, that cppcheck's absence produces an install
hint rather than an exception, and so on. Other tests cover timeouts, files deleted after indexing, symlinks that escape
the workspace, the old Exuberant Ctags, read-only repositories and missing Python packages (the launcher is run with `python -S`, which hides installed packages, and must
print the pip command).

## Structural tests

- **Specification:** every tool's name, parameters, defaults and description in code match `tool-spec.json`.
- **Protocol:** a real MCP client starts the server over stdio, as an editor would, lists the tools and calls them.
  The same test runs against the plain-Python launcher `staticsight.py`.
- **Boundary:** no OS-specific code outside `platform/` (Chapter 8).
- **Data folder:** `.staticsight/` is created with its `.gitignore`, `git status` stays clean, the repository is found
  from subfolders, a read-only repository falls back to the cache, and old cache indexes are migrated.
- **Dependencies:** `requirements.txt` and `requirements-semantic.txt` match `pyproject.toml`.

## Heuristics, labelled

Tests can prove that a heuristic behaves as designed on known code; they cannot make it a compiler. So the last line of
defence is honesty in the output: skeletons, lock analysis and struct-risk proximity matches carry a visible note
(`⚠️ heuristic …`, `locks held by callers are not visible`, `operation within ±2 lines`). The tool descriptions and the
review skill tell the agent to treat these as leads to verify, and to rank cppcheck findings on changed lines as the
strongest evidence.

## Documentation is tested too

The guides in `docs/` promise that commands work and outputs are real. `docs/check_docs.py` keeps that promise:
- it extracts every `staticsight …` command from the command-line and semantic-search guides, runs it against a fresh
  test repository, and checks the exit code;
- it checks that every relative link and `#anchor` in the documentation points to something that exists.

CI runs it on Linux and Windows, through both implementations, and the link check is also part of the Python test
suite. A renamed option or a moved page breaks the build rather than the reader's trust. CI also installs the
launcher's dependencies with plain `pip` (`staticsight.py --install --yes`) and runs it, so the no-uv path stays working.

## Running the tests

```text
cd staticsight-py && uv run pytest -q     # Python: units, platform, tools, semantic, goldens, CLI, degradation, protocol
cd staticsight-ts && npm test             # TypeScript: the same areas, the same goldens
python3 docs/check_docs.py                # the documentation check
```

CI (`.github/workflows/ci.yml` and `pipelines/azure-pipelines.yml`) runs all of this on Linux and Windows, installing
the engines with the project's own installers.

---

<!-- nav:bottom -->
| ⬅️ [Cross-platform](08-cross-platform.md) | 📚 [Documentation](../README.md) | [Using it with AI](10-using-it-with-ai.md) ➡️ |
|:---|:---:|---:|
<!-- /nav:bottom -->
