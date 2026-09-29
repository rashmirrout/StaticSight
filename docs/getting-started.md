<!-- nav:top -->
📚 [Documentation](README.md) › **Getting started**
<!-- /nav:top -->

# Getting started

This page takes you from nothing to a first review, on Linux, macOS or Windows. You need no build of your C++
project, no uv and no virtual environment: a clone of StaticSight, a normal Python and a few command-line tools.

<!-- nav:toc -->
**On this page:** [What you need, and why](#what-you-need-and-why) · [1. Get StaticSight](#1-get-staticsight) · [2. Install everything with one script](#2-install-everything-with-one-script) · [3. Or install each piece by hand](#3-or-install-each-piece-by-hand) · [4. Check the setup](#4-check-the-setup) · [5. Make a short command](#5-make-a-short-command) · [6. Your first review from the terminal](#6-your-first-review-from-the-terminal) · [7. Connect your AI agent](#7-connect-your-ai-agent) · [8. Optional: semantic search](#8-optional-semantic-search) · [The TypeScript twin](#the-typescript-twin) · [Troubleshooting](#troubleshooting) · [Next](#next)
<!-- /nav:toc -->

The order is:
1. get StaticSight;
2. install everything with one script, **or**
3. install each piece by hand (every piece is explained);
4. check that everything is installed;
5. then use it, from a terminal or from your AI agent.

## What you need, and why

StaticSight never compiles your code. It reads the source with a few well-known command-line tools (the *engines*)
and runs on Python. Each piece has one job:

| Component | What StaticSight uses it for | Needed? |
|---|---|---|
| **git** | Finds what changed: diffs, changed lines, old versions of files, the base of your branch. | required |
| **Universal Ctags** (with JSON output) | Parses C/C++ without compiling: functions, classes, structs, their start and end lines and signatures. Almost every tool uses it. | required |
| **ripgrep** (`rg`) | Very fast text search with JSON output: struct layout risks, `#include` users, accesses to shared state, fallback for callers. | required |
| **cppcheck** | Static analysis without a build: leaks, null dereferences, out-of-bounds, uninitialised variables. | recommended |
| **GNU Global** (`gtags`, `global`) | A cross-reference database for precise, fast "who calls this / where is this defined". Without it StaticSight uses ripgrep and says so. | optional |
| **Python ≥ 3.10** | Runs StaticSight (`staticsight.py`). | required |
| Python package **`mcp`** | The official Model Context Protocol SDK. StaticSight's MCP server is built on it (FastMCP, stdio transport). The command line uses the same code, so it is needed for both. | required |
| Python package **`onnxruntime`** | Runs the embedding model on the CPU (no GPU, no PyTorch). | semantic search only |
| Python package **`tokenizers`** | Cuts text into the model's tokens exactly as the model was trained. | semantic search only |
| Python package **`numpy`** | Vector maths: averaging token vectors, normalising, cosine scores. | semantic search only |
| Embedding model **jina-code** (~165 MB) | Turns code and questions into vectors. Downloaded once per user, sha256-verified. | semantic search only |

The Python packages are listed, with their allowed versions, in two files at the root of StaticSight:

| File | Contents | Installs (with dependencies) |
|---|---|---|
| `requirements.txt` | `mcp[cli]>=1.12,<2` | about 35 packages, ~70 MB (`pydantic`, `anyio`, `httpx`, `starlette`, `uvicorn`, `jsonschema`, …; `[cli]` adds `typer`, `python-dotenv`) |
| `requirements-semantic.txt` | `requirements.txt` + `onnxruntime>=1.17`, `tokenizers>=0.15`, `numpy>=1.24` | ~245 MB in total (`onnxruntime` also pulls `protobuf`, `flatbuffers`, `packaging`; `tokenizers` pulls `huggingface-hub`) |

> 💡 **Prefer Node?** The TypeScript twin needs **Node ≥ 22.13** instead of Python (`cd staticsight-ts && npm install && npm run build`).
> Everything else on this page is the same. See [The TypeScript twin](#the-typescript-twin).

## 1. Get StaticSight

Clone it into any folder you like. The guides then refer to that folder as `SS_HOME`, so every command works
whatever location you chose. Set it right after cloning (it is just a shell variable for your convenience;
StaticSight itself does not read it):

```text
# Linux/macOS
git clone https://dev.azure.com/rashmiranjanrout/rrout/_git/StaticSight
export SS_HOME="$PWD/StaticSight"          # the full path of your clone, e.g. /home/alice/src/StaticSight
```

```powershell
# Windows PowerShell
git clone https://dev.azure.com/rashmiranjanrout/rrout/_git/StaticSight
$env:SS_HOME = "$PWD\StaticSight"          # e.g. C:\src\StaticSight
```

StaticSight lives **next to** your C++ repositories; nothing is copied into them. The only file you ever run is
`$SS_HOME/staticsight.py`, always by its full path.

## 2. Install everything with one script

The installer scripts check what is already there, show a plan, **ask before changing anything**, install what is
missing, and check again. They cover the engines, the Python packages and (optionally) the embedding model.

---

### 🐧 Linux and macOS: `scripts/install.sh`

<img src="images/badge-linux.png" alt="Linux and macOS" height="20">

```bash
$SS_HOME/scripts/install.sh --check              # report only, change nothing (exit 1 if something required is missing)
$SS_HOME/scripts/install.sh                      # show the plan, ask, install engines + Python packages
$SS_HOME/scripts/install.sh --with-semantic      # the same, plus semantic-search packages and the model
```

What it does, step by step:
1. **Engines:** installs the missing ones with your package manager (`apt-get`, `tdnf`, `dnf` or `brew`), using `sudo`
   when needed. Where GNU Global is not packaged (for example Azure Linux), it downloads the official source,
   verifies its sha256 and builds it into `/usr/local`.
2. **Python packages:** runs `python3 staticsight.py --install --yes` (with `--semantic` when asked), which calls
   `pip install -r requirements.txt` for that Python. If pip is not allowed to install there (an OS-managed Python,
   see [PEP 668](#linux-step-3-the-python-packages)), it does not force anything: it prints how to use a private environment
   and continues with the engines.
3. **Model** (with `--with-semantic`): runs `staticsight.py model download`.
4. **Re-checks** everything and prints the result.

| Option | Meaning |
|---|---|
| `--check` | Report only; exit code 1 if something required is missing. |
| `--dry-run` | Print the plan, change nothing. |
| `--yes` | Do not ask (for CI). |
| `--no-global` | Skip GNU Global. |
| `--with-semantic` | Also install `onnxruntime`, `tokenizers`, `numpy` and download the model. |
| `--python=PATH` | The Python that will run StaticSight (default `python3`), for example a virtual environment's `python`. |

Real `--check` output on a machine with all engines but no Python packages yet:

```text
StaticSight engines:
  OK   ctags     [required] Universal Ctags 6.1.0, Copyright (C) 2015-2023 Universal Ctags Team
  OK   rg        [required] ripgrep 13.0.0
  OK   git       [required] git version 2.45.4
  OK   cppcheck  [recommended] Cppcheck 2.18.3
  OK   global    [optional] global (GNU Global) 6.6.14
  OK   gtags     [optional] gtags (GNU Global) 6.6.14

Python packages (for python3):
  OK   python    [required] Python 3.12.9 (/usr/bin/python3)
  FAIL mcp       [required] not installed (runs the MCP server and the command line)
  WARN semantic  [optional] onnxruntime/tokenizers/numpy not installed (only needed for semantic search)
Result: something required is missing or unusable (FAIL)
```

and at the end of `install.sh --with-semantic --python=/tmp/sv/bin/python` (a fresh virtual environment):

```text
Python packages (for /tmp/sv/bin/python):
  OK   python    [required] Python 3.12.9 (/tmp/sv/bin/python)
  OK   mcp       [required] mcp 1.30.0
  OK   semantic  [optional] onnxruntime, tokenizers, numpy
Result: all required engines and packages OK
```

---

### 🪟 Windows: `scripts\install.ps1`

<img src="images/badge-windows.png" alt="Windows" height="20">

```powershell
& "$env:SS_HOME\scripts\install.ps1" -Check              # report only
& "$env:SS_HOME\scripts\install.ps1"                     # show the plan, ask, install engines + Python packages
& "$env:SS_HOME\scripts\install.ps1" -WithSemantic       # plus semantic-search packages and the model
```

If PowerShell refuses to run scripts ("running scripts is disabled on this system"), run it once with
`powershell -ExecutionPolicy Bypass -File "$env:SS_HOME\scripts\install.ps1"`.

What it does, step by step:
1. **Engines:** uses **scoop**, else **winget**, else **choco** (`-Manager` picks one). It installs **Universal** Ctags,
   never the old Exuberant Ctags. GNU Global is only available through scoop; it is optional.
2. **cppcheck PATH:** the winget/choco cppcheck installer does not add itself to `PATH`; the script offers to add
   `C:\Program Files\Cppcheck` to your user `PATH`.
3. **Python packages:** finds Python ≥ 3.10 (`py -3`, then `python`, then `python3`, or `-Python C:\path\python.exe`)
   and runs `staticsight.py --install --yes` with it.
4. **Model** (with `-WithSemantic`), then **re-checks** everything.

| Option | Meaning |
|---|---|
| `-Check` | Report only; exit code 1 if something required is missing. |
| `-DryRun` | Print the plan, change nothing. |
| `-Yes` | Do not ask. |
| `-NoGlobal` | Skip GNU Global. |
| `-WithSemantic` | Also the semantic-search packages and the model. |
| `-Python PATH` | The Python that will run StaticSight, e.g. a virtual environment's `python.exe`. |
| `-Manager scoop\|winget\|choco` | Force a package manager. |

The report has the same rows as on Linux (`StaticSight engines:` then `Python packages (for py -3):`).
> 🔄 **After installing, open a new terminal and restart your editor:** programs started earlier still have the old `PATH`.

## 3. Or install each piece by hand

Prefer to see and run every step yourself? Each component below has its install command and a way to verify it.
Pick your operating system.

---

### 🐧 Linux and macOS

<img src="images/badge-linux.png" alt="Linux and macOS" height="20">

#### Linux step 1: Python 3.10 or newer

| System | Command |
|---|---|
| Debian / Ubuntu | `sudo apt-get install python3 python3-pip python3-venv` |
| Fedora / RHEL | `sudo dnf install python3 python3-pip` |
| Azure Linux / Mariner | `sudo tdnf install python3 python3-pip` |
| macOS | `brew install python@3.12` |

Verify: `python3 --version` must print 3.10 or higher.

#### Linux step 2: the engines

| Engine | Debian / Ubuntu | Fedora / RHEL | Azure Linux / Mariner | macOS |
|---|---|---|---|---|
| git | `sudo apt-get install git` | `sudo dnf install git` | `sudo tdnf install git` | `brew install git` |
| Universal Ctags | `sudo apt-get install universal-ctags` | `sudo dnf install ctags` | `sudo tdnf install ctags` | `brew install universal-ctags` |
| ripgrep | `sudo apt-get install ripgrep` | `sudo dnf install ripgrep` | `sudo tdnf install ripgrep` | `brew install ripgrep` |
| cppcheck | `sudo apt-get install cppcheck` | `sudo dnf install cppcheck` | `sudo tdnf install cppcheck` | `brew install cppcheck` |
| GNU Global | `sudo apt-get install global` | `sudo dnf install global` | build from source (below) | `brew install global` |

GNU Global from source, where it is not packaged:

```bash
curl -LO https://ftp.gnu.org/pub/gnu/global/global-6.6.14.tar.gz && tar xzf global-6.6.14.tar.gz && cd global-6.6.14
./configure --prefix=/usr/local --disable-gtagscscope && make -j && sudo make install
```

(If a cross-compile SDK is set up in your shell, clear `CC`, `CFLAGS` and `LDFLAGS` first: `env -u CC -u CFLAGS -u LDFLAGS ./configure …`.)

Verify each engine:

| Command | Expect |
|---|---|
| `git --version` | any recent version |
| `ctags --version` | starts with **Universal Ctags** (not "Exuberant") |
| `ctags --list-features \| grep json` | prints `json` (StaticSight needs the JSON output) |
| `rg --version` | `ripgrep 13` or newer |
| `cppcheck --version` | `Cppcheck 2.x` |
| `global --version` and `gtags --version` | `GNU Global 6.x` |

#### Linux step 3: the Python packages

Install them for the Python that will run StaticSight:

```bash
python3 -m pip install -r $SS_HOME/requirements.txt              # mcp (required)
python3 -m pip install -r $SS_HOME/requirements-semantic.txt     # + onnxruntime, tokenizers, numpy (semantic search)
```

or one by one, if you want to see each:

```bash
python3 -m pip install "mcp[cli]>=1.12,<2"
python3 -m pip install "onnxruntime>=1.17" "tokenizers>=0.15" "numpy>=1.24"
```

`python3 $SS_HOME/staticsight.py --install [--semantic]` does the same, shows the exact pip command and asks first.

> ⚠️ **"error: externally-managed-environment" (PEP 668).** Recent Debian, Ubuntu and Fedora protect the system Python
> from pip. Don't force it; create a private environment used only by StaticSight (this is not a project venv you
> have to "enter"; you just call its `python`):
>
> ```text
> python3 -m venv ~/.staticsight-venv
> ~/.staticsight-venv/bin/python -m pip install -r $SS_HOME/requirements-semantic.txt
> ```
>
> From then on use `~/.staticsight-venv/bin/python` wherever this guide says `python3`, including in your MCP
> client configuration. (`pip install --user --break-system-packages …` also works, at your own risk.)

Verify: `python3 -c "import mcp; print('mcp ok')"` (and `python3 -c "import onnxruntime, tokenizers, numpy"` for semantic search).

#### Linux step 4 (optional): the embedding model

```bash
python3 $SS_HOME/staticsight.py model download
```

It goes to `~/.cache/staticsight/models/` (or `$XDG_CACHE_HOME/staticsight/models/`), once for all repositories.
Without this step, the first semantic search downloads it.

---

### 🪟 Windows

<img src="images/badge-windows.png" alt="Windows" height="20">

#### Windows step 1: Python 3.10 or newer

```powershell
winget install --id Python.Python.3.12 -e
```

This installs Python and the **`py` launcher**. Open a new terminal and verify with `py -3 --version`. On Windows,
use `py -3` wherever this guide says `python3`.

> ⚠️ **Watch out:** typing `python` on a fresh Windows may open the Microsoft Store instead (an "app execution alias"). Use `py -3`,
> or turn the alias off in *Settings → Apps → Advanced app settings → App execution aliases*.

#### Windows step 2: the engines

| Engine | winget | scoop |
|---|---|---|
| git | `winget install --id Git.Git -e` | `scoop install git` |
| Universal Ctags | `winget install --id UniversalCtags.Ctags -e` | `scoop bucket add extras` then `scoop install extras/universal-ctags` |
| ripgrep | `winget install --id BurntSushi.ripgrep.MSVC -e` | `scoop install ripgrep` |
| cppcheck | `winget install --id Cppcheck.Cppcheck -e`, then add `C:\Program Files\Cppcheck` to your `PATH` | `scoop install cppcheck` |
| GNU Global (optional) | not available | `scoop install global` |

> ⚠️ **Watch out:** `scoop install ctags` installs the old **Exuberant Ctags 5.8**, which has no JSON output and breaks every tool.
> Install **Universal** Ctags as shown. StaticSight's `doctor` detects the wrong one.
>
> ⚠️ **Watch out:** StaticSight runs only real `.exe` files, never `.cmd`/`.bat` wrappers (they would go through `cmd.exe`).

Add cppcheck to your user `PATH` (winget install only):

```powershell
[Environment]::SetEnvironmentVariable('Path', [Environment]::GetEnvironmentVariable('Path','User') + ';C:\Program Files\Cppcheck', 'User')
```

**Open a new terminal** (and restart your editor), then verify each engine with the same commands as on Linux:
`git --version`, `ctags --version` (must say *Universal Ctags*), `rg --version`, `cppcheck --version`, `global --version`.

#### Windows step 3: the Python packages

```powershell
py -3 -m pip install -r "$env:SS_HOME\requirements.txt"              # mcp (required)
py -3 -m pip install -r "$env:SS_HOME\requirements-semantic.txt"     # + onnxruntime, tokenizers, numpy
```

or `py -3 "$env:SS_HOME\staticsight.py" --install --semantic`. Windows has no PEP 668 restriction. If you prefer a
private environment anyway:

```powershell
py -3 -m venv "$HOME\.staticsight-venv"
& "$HOME\.staticsight-venv\Scripts\python.exe" -m pip install -r "$env:SS_HOME\requirements-semantic.txt"
```

Verify: `py -3 -c "import mcp; print('mcp ok')"`.

#### Windows step 4 (optional): the embedding model

```powershell
py -3 "$env:SS_HOME\staticsight.py" model download
```

It goes to `%LOCALAPPDATA%\staticsight\models\`, once for all repositories.

---

## 4. Check the setup

Two checks, from two angles:

| Check | Answers | Where to run it |
|---|---|---|
| `scripts/install.sh --check` / `install.ps1 -Check` | "Is everything **installed** on this machine?" | anywhere |
| `staticsight.py doctor` | "Can StaticSight **work on this repository**, with this Python?" (engines, packages, model, which repository, where its data will go) | inside your C++ repository |

Go to your C++ repository and run the doctor with the same Python your MCP client will use:

```text
cd /path/to/your/cpp/repo
python3 $SS_HOME/staticsight.py doctor                 # Windows: py -3 "$env:SS_HOME\staticsight.py" doctor
```

A healthy result (real output on Linux; your paths will differ):

```text
StaticSight doctor
Platform:  posix
Runtime:   Python 3.12.9 (/tmp/sv/bin/python), mcp 1.30.0
Workspace: /tmp/cpp-sample
  OK   git repository
Cache:     /root/.cache/staticsight (writable; models)
Data:      /tmp/cpp-sample/.staticsight (repository (not created yet); indexes)

Engines:
  OK   ctags     [required] Universal Ctags 6.1.0, Copyright (C) 2015-2023 Universal Ctags Team
       used for: scopes, signatures, skeletons (Universal Ctags with JSON)
  OK   rg        [required] ripgrep 13.0.0
       used for: fast text search: struct risks, includes, mutations, fallbacks
  OK   git       [required] git version 2.45.4
       used for: diffs, base refs, changed-line markers
  OK   cppcheck  [recommended] Cppcheck 2.18.3
       used for: run_file_static_audit
  OK   global    [optional] global (GNU Global) 6.6.14
       used for: precise callers/definitions (ripgrep fallback without it)
  OK   gtags     [optional] gtags (GNU Global) 6.6.14
       used for: builds the GNU Global index

Semantic search (optional):
  OK   packages  onnxruntime, tokenizers, numpy
  OK   model     jina-code@516f4baf13dec4ddddda8631e019b5737c8bc250 (/root/.cache/staticsight/models/jina-code/516f4baf13dec4ddddda8631e019b5737c8bc250)

Result: all required engines OK
```

What each line tells you:

| Line | Meaning |
|---|---|
| `Platform` | `posix` (Linux, macOS) or `windows`. |
| `Runtime` | The Python running StaticSight and its `mcp` version. Your MCP client must use **this same Python**. |
| `Workspace` | The repository StaticSight will analyse: the nearest folder above the current one with `.git` (or `.staticsight/`), so any subfolder works. `--repo PATH` picks another. |
| `git repository` | The diff tools need one. |
| `Cache` | Per-user folder for the embedding model, shared by all repositories. |
| `Data` | Where this repository's indexes (GNU Global, semantic) will go: `<repo>/.staticsight/`. It ignores itself (it holds a `.gitignore` with `*`), so `git status` stays clean. "not created yet" is normal before the first run. |
| `Engines` | Each engine, its version, and what it is used for. |
| `Semantic search` | The three packages and the model. |
| `Result` | Exit code 0 when all *required* engines work, 1 otherwise. |

On Windows the output has the same lines, with `Platform:  windows` and Windows paths
(`%LOCALAPPDATA%\staticsight` for the cache).

**When something is missing,** the line says so and gives the fix. Real output with cppcheck, GNU Global and the
semantic packages missing:

```text
  WARN cppcheck  [recommended] not found on PATH
       used for: run_file_static_audit
       fix: Install cppcheck (`apt-get install cppcheck`, `tdnf install cppcheck`, `brew install cppcheck`), or run `scripts/install.sh`.
  WARN global    [optional] not found on PATH
       used for: precise callers/definitions (ripgrep fallback without it)
       fix: Install GNU Global (`apt-get install global`, `brew install global`, or build from https://www.gnu.org/software/global/), or run `scripts/install.sh`.
...
Semantic search (optional):
  WARN packages  Python packages for semantic search are missing (numpy).
       fix: Install them (onnxruntime, tokenizers, numpy) with `python3 staticsight.py --install --semantic` from the StaticSight clone, or `pip install -r requirements-semantic.txt`.

Result: all required engines OK
```

`WARN` means StaticSight works with less (here: no static audit, callers via ripgrep, no semantic search). `FAIL`
marks a required engine; then `Result: missing or unusable required engines (see FAIL)` and exit code 1.

If the **`mcp` package** is missing, `doctor` cannot start at all. The launcher says so, with the command for the
exact Python you used:

```text
StaticSight: missing Python package(s): mcp (for /usr/bin/python3).
  Install:  /usr/bin/python3 /root/Overlake/src/StaticSight/staticsight.py --install
  or:       /usr/bin/python3 -m pip install -r /root/Overlake/src/StaticSight/requirements.txt
```

No C++ repository at hand? Build the one used in all examples:
`python3 $SS_HOME/shared/fixtures/make_fixture.py /tmp/cpp-sample && cd /tmp/cpp-sample`.

## 5. Make a short command

All guides write `staticsight …` as short for `python3 $SS_HOME/staticsight.py …`. Make it permanent once, so it
also works in new terminals (the lines are written with the real path of your clone):

```text
# Linux/macOS (zsh: use ~/.zshrc)
echo "export SS_HOME=\"$SS_HOME\"" >> ~/.bashrc
echo "alias staticsight='python3 $SS_HOME/staticsight.py'" >> ~/.bashrc
```

```powershell
# Windows PowerShell
Add-Content $PROFILE "`$env:SS_HOME = '$env:SS_HOME'"
Add-Content $PROFILE "function staticsight { py -3 '$env:SS_HOME\staticsight.py' @args }"
```

You can skip the alias and always type the full path instead; it is exactly the same program.

(Contributors using uv can also run `uv run staticsight …` inside `staticsight-py`; it is the same program.)

## 6. Your first review from the terminal

```bash
staticsight tool review_changes
```

This is exactly what an agent receives when it starts a review: every changed function, cppcheck findings on changed
lines, branch skeletons, caller impact, struct layout risks, header blast radius and lock consistency. Drill down with
the individual tools:

```bash
staticsight tool get_upstream_callers process_packet
```

```text
### 📞 UPSTREAM CALLERS: `process_packet`
Found 3 call sites in 2 files (source: GNU Global).
Returns `int`; ⚠️ 2 caller(s) ignore the result — check they tolerate new error values.

**`src/net/listener.cpp`**
1. L9 in `Listener::on_socket_read` — result used
   `int rc = router_->process_packet(&raw);`
2. L17 in `Listener::dispatch_batch` — ⚠️ result ignored
   `router_->process_packet(&batch[i]);`
**`tests/test_router.cpp`**
3. L6 in `test_drop_invalid` — ⚠️ result ignored
   `r.process_packet(&dummy);`
```

The first call in a repository builds the GNU Global index into `.staticsight/` (seconds for small repositories,
a few minutes for very large ones). The [command-line guide](cli-guide.md) covers every command.

## 7. Connect your AI agent

StaticSight speaks MCP over stdio: the client starts `python3 staticsight.py` and talks to it through stdin/stdout.

**VS Code / GitHub Copilot**: `.vscode/mcp.json` in the C++ repository:

```json
{
  "servers": {
    "staticsight": {
      "type": "stdio",
      "command": "python3",
      "args": ["/path/to/StaticSight/staticsight.py", "--repo", "${workspaceFolder}"]
    }
  }
}
```

**GitHub Copilot CLI**: `~/.copilot/mcp-config.json` (one entry for all repositories):

```json
{
  "mcpServers": {
    "staticsight": {
      "type": "local",
      "command": "python3",
      "args": ["/path/to/StaticSight/staticsight.py"],
      "tools": ["*"]
    }
  }
}
```

Replace `/path/to/StaticSight` with the full path of your clone (the value of `$SS_HOME`); JSON files cannot use
variables. Without `--repo`, StaticSight uses the repository around the folder the server was started in. Start Copilot CLI inside
your repository, or add `"--repo", "/path/to/repo"` to pin one.

**Claude Code**: `claude mcp add staticsight -- python3 $SS_HOME/staticsight.py --repo "$PWD"`

**Windows**: use `"command": "py"` with `"args": ["-3", "C:/path/to/StaticSight/staticsight.py", "--repo", "${workspaceFolder}"]`
(forward slashes, or `\\`, in JSON). With a virtual environment, `command` is that environment's `python`.

Then ask: *"Review my changes. What did I miss, and could anything break?"* The [MCP guide](mcp-guide.md) explains what
happens next, step by step.

## 8. Optional: semantic search

```bash
staticsight model download
staticsight index build
staticsight search "retry failed network calls" --top 3
```

See the [semantic search guide](semantic-search/manual-guide.md).

## The TypeScript twin

Everything above also works with Node ≥ 22.13: `cd staticsight-ts && npm install && npm run build`, then use
`node $SS_HOME/staticsight-ts/dist/server.js` wherever this guide uses `python3 $SS_HOME/staticsight.py`.
Both produce byte-identical output and share the same `.staticsight/` data.

## Troubleshooting

| Symptom | Fix |
|---|---|
| `StaticSight: missing Python package(s): mcp` | `python3 staticsight.py --install` with the same Python your client runs. |
| `externally-managed-environment` from pip | Use a private venv ([Linux step 3](#linux-step-3-the-python-packages)), then point `--python=` / your MCP config at its `python`. |
| `ctags ... has no JSON output` | You have Exuberant Ctags. Install Universal Ctags (see the Windows note above). |
| `cppcheck was not found on PATH` on Windows after winget | Add `C:\Program Files\Cppcheck` to `PATH` (`install.ps1` offers to), then restart the editor. |
| Tools report "not found" right after installing | The MCP server inherits the editor's `PATH`. Restart VS Code or Copilot CLI. |
| Callers say "ripgrep fallback" | GNU Global is missing or still indexing: `staticsight tool get_index_status`. |
| cppcheck: "could not fully parse (unknown macro X)" | Pass a definition: `STATICSIGHT_CPPCHECK_ARGS="-DX(a)="`. |
| Wrong repository analysed | Check `Workspace:` in `staticsight doctor`; pass `--repo PATH` in your MCP configuration. |
| Semantic search "not available … packages are missing" | `python3 staticsight.py --install --semantic` (Python) or `npm install` in `staticsight-ts` (Node ≥ 22.13). |
| A `.cmd`/`.bat` wrapper is ignored on Windows | StaticSight only runs real `.exe` files. Point `PATH` at the real executable. |

## Next

- [Command-line guide](cli-guide.md): every command, option and environment variable.
- [MCP guide](mcp-guide.md): how an agent uses StaticSight.
- [The book](book/00-preface.md): what StaticSight does, why, and how, from the beginning.

---

<!-- nav:bottom -->
|   | 📚 [Documentation](README.md) | [Command-line guide](cli-guide.md) ➡️ |
|:---|:---:|---:|
<!-- /nav:bottom -->
