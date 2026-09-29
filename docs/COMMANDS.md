<!-- nav:top -->
📚 [Documentation](README.md) › **Raw commands**
<!-- /nav:top -->

# Raw commands run by StaticSight

This is every external command StaticSight runs, which CLI tool it uses, which MCP tools trigger it, and why.
The Python and TypeScript implementations run exactly the same commands.

<!-- nav:toc -->
**On this page:** [git](#git) · [Universal Ctags](#universal-ctags) · [ripgrep](#ripgrep) · [GNU Global](#gnu-global) · [cppcheck](#cppcheck) · [Semantic search](#semantic-search) · [Capability probes (no workspace access)](#capability-probes-no-workspace-access) · [Installer scripts (run only when you invoke them)](#installer-scripts-run-only-when-you-invoke-them) · [Tool → command matrix](#tool--command-matrix) · [<GLOBS>: file filters passed to ripgrep](#globs-file-filters-passed-to-ripgrep) · [Try them by hand](#try-them-by-hand)
<!-- /nav:toc -->

**How commands are run**
- Only the **platform layer** (`staticsight/platform/`, `src/platform/`) starts processes. The engine adapters
  (`engines/`) build the argument lists shown below; the tools never run commands directly. A test enforces this.
- Always as an argument list with **no shell** (`asyncio.create_subprocess_exec` / `child_process.spawn(shell: false)`),
  so there is no quoting and no shell injection.
- Executables are resolved by the platform layer:
  - Linux/macOS: `PATH` lookup (`shutil.which`).
  - Windows: only real `.exe`/`.com` files on `PATH`. `.cmd`/`.bat` shims are refused because they would need `cmd.exe`.
- Timeouts kill the whole process tree:
  - Linux/macOS: a new process group, then `killpg(SIGKILL)`.
  - Windows: `CREATE_NEW_PROCESS_GROUP | CREATE_NO_WINDOW` (no console flashes), then `taskkill /PID <pid> /T /F`.
- With `cwd = WORKSPACE_ROOT`, except the ctags run on a temporary old-file copy.
- Timeout: `STATICSIGHT_TIMEOUT` (default 20 s). cppcheck uses `STATICSIGHT_CPPCHECK_TIMEOUT` (60 s), and indexing
  allows 1800 s.
- Output is capped: stdout at 8 MB, then the process is stopped and results are marked truncated; stderr at 64 KB.
- User-supplied symbols are validated as C++ identifiers and placed after `--`. Regexes built from them are escaped.
- Paths printed by engines are normalised to `/` at the adapter boundary. ripgrep is asked for `/` directly with
  `--path-separator /`, so output is identical on Windows and Linux.
- `STATICSIGHT_DISABLE_ENGINES=global,gtags` makes StaticSight treat those engines as missing, for example to force
  the ripgrep fallback.
- Every command is **read-only** for your source files. The only writes are StaticSight's own data folder
  `<repo>/.staticsight/` (GNU Global database and semantic index; it ignores itself through its own `.gitignore`), and a
  temporary copy of an old file version, which is deleted right away. With `STATICSIGHT_DATA_DIR=cache`, or when the
  repository is read-only, the data folder is in the per-user cache instead (`~/.cache/staticsight/<hash>`,
  `%LOCALAPPDATA%\staticsight\<hash>`).

Placeholders: `<base>` diff base SHA · `<ref>` ref name · `<file>` workspace-relative path · `<sym>` identifier ·
`<GLOBS>` file filters (see the end of this page).

## git

| Command | Used by (MCP tools) | Purpose |
|---|---|---|
| `git -c core.quotepath=off rev-parse --git-dir` | `get_diff_scopes`, `review_changes`, `run_file_static_audit`, `get_branch_skeleton` | Check the workspace is a git repo (clear error if not). |
| `git rev-parse --verify --quiet <ref>^{commit}` | same | Check that `base_ref` (or `origin/main`, `origin/master`, `main`, `master`, `HEAD`) exists. |
| `git merge-base HEAD <ref>` | same | Find the fork point, so only *your* branch's changes are reviewed. |
| `git -c core.quotepath=off diff -U0 --no-color --no-ext-diff --no-textconv -M <base> -- [<file>]` | same | Committed + staged + unstaged changes vs the base, with zero context lines. Hunk headers give exact changed lines; `-M` detects renames. |
| `git -c core.quotepath=off ls-files --others --exclude-standard -z -- [<file>]` | same | Untracked (new, not yet added) files, which count as fully added. |
| `git show <base>:<old_path>` | `get_diff_scopes`, `review_changes` | Old version of a modified, renamed or deleted file. Used to detect removed symbols and signature changes (old → new). |

`get_branch_skeleton` and `run_file_static_audit` call the diff commands with `-- <file>` only to place the ✏️
markers. If git fails, they still work, just without markers.

## Universal Ctags

| Command | Used by | Purpose |
|---|---|---|
| `ctags --output-format=json --fields=+neKSZ --kinds-C++=+p --sort=no --language-force=C++ -f - <file> [<file> …]` | almost every tool | Parse C/C++ symbols without compiling: names, kinds, **start and end lines** (`n`,`e`), signatures (`S`), scopes (`Z`), and prototypes (`+p`). Used for scope lookup, enclosing functions, member lists and definitions. Up to 200 files per call; results are cached by file mtime and size. |
| same, on `<tmpdir>/old.<ext>` | `get_diff_scopes`, `review_changes` | Parse the old version of a file (from `git show`) to compare symbols and signatures. |

Flag meanings: `n` = line, `e` = end line, `K` = full kind name, `S` = signature, `Z` = scope with kind.
`--language-force=C++` also parses `.h`/`.c` as C++. `-f -` writes to stdout.

## ripgrep

| Command | Used by | Purpose |
|---|---|---|
| `rg --json --no-config --no-messages --path-separator / -w -F -C 2 <GLOBS> -e <sym> -- .` | `track_struct_risks` | Every whole-word reference to the type, plus 2 lines of context, so a `memcpy`/`sizeof` on the next line is caught. |
| `rg --json --no-config --no-messages --path-separator / <GLOBS> -e '^\s*#\s*include\s*["<]([^">]*/)?<escaped header>[">]' -- .` | `get_include_blast_radius`, `review_changes` | Find `#include` lines for a header (called again for each including header when following transitive includes). |
| `rg --json --no-config --no-messages --path-separator / -w -F <GLOBS> -e <sym> -- . \| <file>` | `track_state_mutations`, `review_changes` | Every access to a variable or member (whole repo, or one file). |
| `rg --json --no-config --no-messages --path-separator / -w -F -m 1 <GLOBS> -e <sym> -- .` | `get_symbol_definition`, `get_symbol_contract`, `get_upstream_callers`, `review_changes` | Find which files mention a symbol (first match per file, max 300 files). ctags then finds declarations and definitions in them. |
| `rg --json --no-config --no-messages --path-separator / <GLOBS> -e '\b<sym>\s*\(\|&\s*(?:\w+::)*<sym>\b' -- .` | `get_upstream_callers` (fallback) | Find call sites when GNU Global is not available. |
| `rg --json --no-config --no-messages --path-separator / <GLOBS> -e '<lock triggers>' -- .` | `track_lock_order`, `review_changes` | Find the files that take locks: std guards, `.lock();`, `std::lock`, `EnterCriticalSection`, `AcquireSRWLock*`, lock wrapper types. Those files are then parsed with ctags and walked line by line. |
| `rg --files --no-config --no-messages --path-separator / <GLOBS>` | indexer, `get_include_blast_radius` | List all C/C++ files: the file list for `gtags`, basename-collision detection, and translation-unit counts. |

`--json` gives structured match/context events, parsed natively. `-w` = whole word, `-F` = literal (no regex),
`-C 2` = context lines, `-m 1` = one match per file, `--no-config` ignores personal ripgrep settings.
ripgrep also respects `.gitignore`.

## GNU Global

| Command | Used by | Purpose |
|---|---|---|
| `gtags -f - <datadir>` (file list on stdin) | indexer (background at server start; before the first graph tool in `staticsight tool …`) | Build the symbol database for the first time in `<repo>/.staticsight/` (`GTAGSDBPATH`, `GTAGSROOT` set to the repo). |
| `gtags -i -f - <datadir>` | indexer (refresh after `STATICSIGHT_REINDEX_SECONDS`) | Incremental update of the database. |
| `gtags -i -f -` | indexer when `STATICSIGHT_GTAGS_IN_REPO=1` (deprecated) | Build or update `GTAGS` in the repository root. |
| `global -u` | indexer when the repo already has a `GTAGS` file | Incremental update of the existing in-repo database. |
| `global -xr -- <sym>` | `get_upstream_callers`, `review_changes` | All **references** (call sites) of a symbol, as `name line path text`. |
| `global -xd -- <sym>` | `get_symbol_definition`, `get_symbol_contract`, `get_upstream_callers`, `review_changes` | All **definitions** of a symbol. The callers tool uses them to learn the return type. |

Environment set for every GNU Global command: `GTAGSROOT=<workspace>`, `GTAGSDBPATH=<database dir>`,
and `GTAGSFORCECPP=1` so `.h` files are parsed as C++.

## cppcheck

| Command | Used by | Purpose |
|---|---|---|
| `cppcheck --xml --xml-version=2 --enable=warning,style,performance,portability --inline-suppr --language=c++ --std=c++17 --quiet --max-configs=4 --suppress=missingIncludeSystem --suppress=missingInclude --suppress=unmatchedSuppression --suppress=checkersReport [$STATICSIGHT_CPPCHECK_ARGS] -I<dir> … <file>` | `run_file_static_audit`, `review_changes` | Static analysis of one file without building it: leaks, null dereferences, bounds, uninitialised variables and more. Results arrive as XML on stderr. `-I` covers the file's folder, its parents, and nearby `include`/`inc`/`src` folders. `.c` files use `--language=c --std=c11`. |
| same **plus** `--library=windows --platform=win64 -D_WIN32 -D_MSC_VER=1930` | `run_file_static_audit`, `review_changes` (MSVC mode) | Added automatically when the file targets Windows: it includes `windows.h`-family headers, uses SAL annotations (`_In_`, `__out`, ...), or at least two Win32 types (`HRESULT`, `DWORD`, `HANDLE`, ...). Adds Windows API knowledge, e.g. `CreateFileW` without `CloseHandle` is reported as a resource leak. `STATICSIGHT_CPPCHECK_MSVC=0` disables it, `=1` forces it. |
| same, **without** the `-I` options | `run_file_static_audit` (automatic retry) | Used when the first run reports `unknownMacro`/`syntaxError` from included headers. The file itself is then still analysed. |

## Semantic search

| Command | Used by | Purpose |
|---|---|---|
| `rg --files --no-config --no-messages --path-separator / <excludes>` (no include globs) | semantic tools, drift check | List **every** non-ignored file for the language-agnostic semantic index. |
| `ctags --output-format=json --fields=+neKSZ --sort=no -f - <file> …` (no `--language-force`) | semantic indexer | Detect each file's language and get function/class boundaries for structural chunking. |
| `rg --json --no-config --no-messages --path-separator / -F -i -m 200 <excludes> -e <term> … -- .` | `semantic_search` | Keyword half of hybrid ranking (query terms, case-insensitive, all files). |
| `git rev-parse --verify --quiet HEAD^{commit}` | semantic indexer | Record the indexed HEAD (shown in `get_index_status`). |
| HTTPS `GET https://huggingface.co/jinaai/jina-embeddings-v2-base-code/resolve/<pinned revision>/<file>` (not a subprocess) | first use / `model download` | One-time model download, sha256-verified, into `<cache>/models/`. `HF_ENDPOINT` overrides the host; `STATICSIGHT_SEMANTIC_ALLOW_DOWNLOAD=0` forbids it. |

Embedding runs **in-process** through ONNX Runtime (`onnxruntime` / `onnxruntime-node`). No subprocess, no server, no network
after the download.

## Capability probes (no workspace access)

| Command | Used by | Purpose |
|---|---|---|
| `<engine> --version` for ctags, rg, git, cppcheck, global, gtags | `get_index_status`, `staticsight doctor`, first ctags use | Report the version of each engine. Results are cached per executable path. |
| `ctags --list-features` | same | Check that ctags supports **JSON** output. Exuberant Ctags (for example `scoop install ctags`) doesn't; StaticSight then explains how to install Universal Ctags instead of failing later. |

## Installer scripts (run only when you invoke them)

`scripts/install.sh` (Linux/macOS) and `scripts/install.ps1` (Windows) run the same probes, then, **after
confirmation**, the package-manager commands they print:

| Script | Package manager commands |
|---|---|
| `install.sh` | `apt-get install universal-ctags ripgrep cppcheck global git` · `tdnf/dnf install ctags ripgrep cppcheck git` · `brew install universal-ctags ripgrep cppcheck global git`. Where GNU Global isn't packaged, it downloads `global-6.6.14.tar.gz`, verifies its SHA-256, then runs `./configure && make && make install`. |
| `install.ps1` | `scoop bucket add extras` + `scoop install extras/universal-ctags ripgrep cppcheck global git` · `winget install --id UniversalCtags.Ctags / BurntSushi.ripgrep.MSVC / Cppcheck.Cppcheck / Git.Git` · `choco install universal-ctags ripgrep cppcheck git -y` |

Both scripts support `--check` / `-Check` (report only), `--dry-run` / `-DryRun` (print the plan), `--yes` / `-Yes` (for CI),
and `--no-global` / `-NoGlobal`.

## Tool → command matrix

| MCP tool | git | ctags | rg | global/gtags | cppcheck |
|---|:-:|:-:|:-:|:-:|:-:|
| `review_changes` | ✔ | ✔ | ✔ | ✔ | ✔ |
| `get_diff_scopes` | ✔ | ✔ | | | |
| `get_enclosing_scope` | | ✔ | | | |
| `get_branch_skeleton` | ✔ (markers only) | ✔ | | | |
| `get_upstream_callers` | | ✔ | ✔ | ✔ | |
| `get_symbol_definition` | | ✔ | ✔ | ✔ | |
| `get_symbol_contract` | | ✔ | ✔ | ✔ | |
| `track_struct_risks` | | ✔ | ✔ | | |
| `get_include_blast_radius` | | | ✔ | | |
| `track_state_mutations` | | ✔ | ✔ | | |
| `track_lock_order` | | ✔ | ✔ | | |
| `run_file_static_audit` | ✔ (markers only) | ✔ | | | ✔ |
| `semantic_search` | | ✔ | ✔ | | |
| `find_similar_code` | | ✔ | ✔ | | |
| `refresh_semantic_index` | ✔ (HEAD) | ✔ | ✔ | | |
| `get_index_status` | | | | (checks PATH only) | |

## `<GLOBS>`: file filters passed to ripgrep

- **Included:** `-g '*.c' -g '*.cc' -g '*.cpp' -g '*.cxx' -g '*.c++' -g '*.h' -g '*.hh' -g '*.hpp' -g '*.hxx' -g '*.h++' -g '*.inl' -g '*.ipp' -g '*.tpp' -g '*.tcc'`
- **Excluded:** `-g '!**/.git/**' -g '!**/build/**' -g '!**/out/**' -g '!**/third_party/**' -g '!**/external/**' -g '!**/node_modules/**' -g '!*.pb.h' -g '!*.pb.cc'`
- **Your additions:** patterns from `STATICSIGHT_EXCLUDES` and `.staticsightignore`, added as `-g '!<pattern>'`.

## Try them by hand

```bash
cd /path/to/cpp/repo
ctags --output-format=json --fields=+neKSZ --kinds-C++=+p --sort=no --language-force=C++ -f - src/router.cpp
rg --json --path-separator / -w -F -C 2 -e Packet -- . | head
GTAGSFORCECPP=1 gtags -f - /tmp/gtagsdb < <(rg --files -g '*.{c,cc,cpp,h,hpp}')
GTAGSROOT=$PWD GTAGSDBPATH=/tmp/gtagsdb global -xr -- process_packet
cppcheck --xml --xml-version=2 --enable=warning,style,performance,portability --quiet src/router.cpp
git diff -U0 --no-color -M "$(git merge-base HEAD origin/main)" --
```

---

<!-- nav:bottom -->
| ⬅️ [MCP tool reference](MCP_TOOLS.md) | 📚 [Documentation](README.md) | [Benchmarks](benchmarks.md) ➡️ |
|:---|:---:|---:|
<!-- /nav:bottom -->
