<!-- nav:top -->
📚 [Documentation](../README.md) › 📖 [The book](00-preface.md) › **Chapter 8: Cross-platform**
<!-- /nav:top -->

# 8. Cross-platform

A lot of C++ that needs careful review is Windows code: services, drivers, agents built with MSVC. It is often
reviewed on Linux machines, in containers, or by agents running in the cloud. StaticSight therefore runs on Linux,
macOS and Windows, and gives **byte-identical answers** for the same repository on all of them. This chapter explains
how, and what it takes.

## One layer knows the OS

The whole design rests on a rule from Chapter 4: only the `platform/` layer may know which OS it runs on. It provides a
small interface:

| Operation | POSIX (Linux, macOS) | Windows |
|---|---|---|
| Find an executable | `PATH` lookup | `PATH` lookup, **only `.exe` and `.com`** |
| Start a process | direct exec, new process group | direct exec, new process group, no console window |
| Stop a process tree on timeout | signal the process group | `taskkill /PID <pid> /T /F` |
| Normalise a path for output | unchanged (`/`) | `\` → `/` |
| Compare paths | case-sensitive | case-insensitive |
| Per-user cache | `$XDG_CACHE_HOME/staticsight` or `~/.cache/staticsight` | `%LOCALAPPDATA%\staticsight` |
| Install hints | apt, dnf/tdnf, brew | winget, scoop, choco |

Everything above it (engines, tools, semantic search) is written once. Both test suites contain a *boundary test* that
fails if `sys.platform`, `os.name`, `process.platform`, subprocess calls or similar appear outside `platform/`.

The Windows implementation is also unit-tested **on Linux**: its path rules, case rules and executable lookup are
exercised through the `WindowsPlatform` class on every CI run, not only on Windows runners.

## Why only real executables on Windows

On Windows, package managers often install `.cmd` or `.bat` wrappers. Running those means running `cmd.exe`, whose
quoting rules differ from normal argument passing, which would re-introduce the shell-injection risk that Chapter 2
rules out. StaticSight therefore only runs real `.exe`/`.com` files and says so when it finds only a wrapper.

## Paths

Output paths always use `/`, relative to the workspace, on every OS. ripgrep is asked for `/` directly
(`--path-separator /`); every other engine's paths are normalised in its adapter. Input paths may use either
separator. On Windows, comparisons and `path_glob` matching are case-insensitive, like the file system; on Linux they
are case-sensitive. The per-repository key used for cache folders is computed from the real path, case-folded on Windows.

## Text encodings and line endings

MSVC projects often contain files that are not plain UTF-8:

- **UTF-8 with a BOM** (the byte-order mark `EF BB BF`): StaticSight removes it before analysis, so a `#include` on
  line 1 still matches `^\s*#\s*include`.
- **UTF-16** (little- or big-endian, with a BOM), common for resource and config headers: decoded to text. ctags
  does not parse UTF-16, so structure comes from the text analysis where possible, and semantic search indexes the file
  as windows.
- **CRLF line endings:** line numbers and text are identical to LF files.

The test repository contains each of these cases, and `shared/fixtures/.gitattributes` (`* -text`) prevents git from
changing their bytes on a Windows checkout, so the tests see the same bytes everywhere.

## MSVC-aware static analysis

cppcheck can model the Windows API, but it has to be told. When a file includes `windows.h`-family headers, uses SAL
annotations (`_In_`, `_Out_`, `__out`, …) or several Win32 types, StaticSight adds
`--library=windows --platform=win64 -D_WIN32 -D_MSC_VER=1930`. cppcheck then knows, for example, that a `HANDLE` from
`CreateFileW` must be closed, and reports `resourceLeak` on an error path that forgets `CloseHandle`. This works on any
host OS: Windows code reviewed on Linux gets the same findings. `STATICSIGHT_CPPCHECK_MSVC=0` turns it off, `=1`
forces it.

The skeleton tool's resource table also knows Win32 and COM pairs (`CreateFile*`/`CloseHandle`,
`OpenSCManager*`/`CloseServiceHandle`, `CoTaskMemAlloc`/`CoTaskMemFree`, `SysAllocString*`/`SysFreeString`,
`->Release()`), and treats `if (h == INVALID_HANDLE_VALUE)` as a failure check.

## Engines on Windows

| Engine | Recommended source | Watch out for |
|---|---|---|
| Universal Ctags | `winget install UniversalCtags.Ctags` or `scoop install extras/universal-ctags` | `scoop install ctags` gives Exuberant Ctags 5.8, without JSON; `doctor` detects it |
| ripgrep | `winget install BurntSushi.ripgrep.MSVC` | — |
| cppcheck | `winget install Cppcheck.Cppcheck` | the installer does not add it to `PATH`; `install.ps1` offers to |
| GNU Global | `scoop install global` | optional |
| git | `winget install Git.Git` | — |

`scripts/install.ps1` prefers scoop, then winget, then choco, shows its plan and asks before installing. After
installing, restart the editor: an MCP server inherits the editor's `PATH`.

## Two runtimes, one output

The Python and TypeScript implementations run on all three OSes too. Small differences between the languages had to
be neutralised to keep outputs byte-identical, for example:

- number formatting (`round(0.125, 2)` differs between Python and JavaScript; a shared rounding helper reproduces
  Python's rules, including `-0.00`);
- sorting with a stable, explicit key everywhere;
- nanosecond timestamps stored as text in SQLite, because they exceed JavaScript's safe integer range;
- identical tokenisation in the two ONNX runtimes (verified token by token).

## How it is verified

CI runs both test suites on Linux and on Windows. On each runner, the Python suite first generates golden outputs
with that machine's engine versions, and the TypeScript suite must match them byte for byte (Chapter 9). The committed
goldens, generated on Linux, are also compared as an informational check, which shows that the answers are the same
across operating systems when engine versions match.

---

<!-- nav:bottom -->
| ⬅️ [Semantic search](07-semantic-search.md) | 📚 [Documentation](../README.md) | [Trust and testing](09-trust-and-testing.md) ➡️ |
|:---|:---:|---:|
<!-- /nav:bottom -->
