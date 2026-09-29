#!/usr/bin/env python3
"""StaticSight launcher for a plain clone: no uv, no virtual environment, no package install of StaticSight itself.

    python3 staticsight.py --install [--semantic] [--yes] [-- PIP_ARGS]   install the Python dependencies with pip
    python3 staticsight.py                                                run the MCP server (stdio)
    python3 staticsight.py doctor | index | search | similar | model | tool ...   command line (see: help)
    python3 staticsight.py --repo PATH COMMAND                            work on another repository

Only the standard library is used here, so this file can always explain what is missing.
"""

from __future__ import annotations

import importlib.util
import os
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
SRC = os.path.join(HERE, "staticsight-py", "src")
MIN_PY = (3, 10)


def _err(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _py() -> str:
    """How the user should call this interpreter in suggested commands."""
    exe = sys.executable or "python3"
    return f'"{exe}"' if " " in exe else exe


def _req(semantic: bool) -> str:
    return os.path.join(HERE, "requirements-semantic.txt" if semantic else "requirements.txt")


def _missing(semantic: bool) -> list[str]:
    mods = ["mcp"] + (["onnxruntime", "tokenizers", "numpy"] if semantic else [])
    return [m for m in mods if importlib.util.find_spec(m) is None]


def _pep668_help(semantic: bool) -> None:
    req = _req(semantic)
    venv = os.path.join(os.path.expanduser("~"), ".staticsight-venv")
    vpy = os.path.join(venv, "Scripts" if os.name == "nt" else "bin", "python")
    flag = " --semantic" if semantic else ""
    _err(
        "\nThis Python is managed by the operating system (PEP 668), so pip refuses to install into it.\n"
        "Pick one:\n"
        f"  1. (recommended) a private environment, used only by StaticSight:\n"
        f"       {_py()} -m venv {venv}\n"
        f"       {vpy} {os.path.join(HERE, 'staticsight.py')} --install{flag} --yes\n"
        f"     then use {vpy} instead of python3 (also in your MCP client configuration).\n"
        f"  2. install for your user only, overriding the protection:\n"
        f"       {_py()} -m pip install --user --break-system-packages -r {req}\n"
        f"  3. use your OS packages if they are recent enough (mcp >= 1.12 is rarely packaged)."
    )


def install(argv: list[str]) -> int:
    extra: list[str] = []
    if "--" in argv:
        extra = argv[argv.index("--") + 1 :]
        argv = argv[: argv.index("--")]
    semantic = "--semantic" in argv
    yes = "--yes" in argv or "-y" in argv
    req = _req(semantic)
    if importlib.util.find_spec("pip") is None:
        _err(f"pip is not available for {sys.executable}.\n"
             f"  Try: {_py()} -m ensurepip --upgrade   (or install your OS package, e.g. python3-pip)")
        return 1
    cmd = [sys.executable, "-m", "pip", "install", "-r", req, *extra]
    print("StaticSight will run:\n  " + " ".join(f'"{c}"' if " " in c else c for c in cmd), flush=True)
    if not yes:
        if not sys.stdin.isatty():
            _err("Not a terminal: add --yes to confirm.")
            return 1
        if input("Proceed? [y/N] ").strip().lower() not in ("y", "yes"):
            _err("Cancelled.")
            return 1
    proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, errors="replace")
    sys.stdout.write(proc.stdout)
    if proc.returncode != 0:
        if "externally-managed-environment" in proc.stdout:
            _pep668_help(semantic)
        else:
            _err(f"\npip failed (exit {proc.returncode}). See the output above.")
        return proc.returncode or 1
    print(f"\nDone. Next: {_py()} {os.path.join(HERE, 'staticsight.py')} doctor")
    return 0


def main() -> int:
    if sys.version_info < MIN_PY:
        _err(f"StaticSight needs Python {MIN_PY[0]}.{MIN_PY[1]} or newer; this is {sys.version.split()[0]} ({sys.executable}).")
        return 1
    argv = sys.argv[1:]
    if argv[:1] == ["--install"]:
        return install(argv[1:])
    missing = _missing(False)
    if missing:
        _err(f"StaticSight: missing Python package(s): {', '.join(missing)} (for {sys.executable}).\n"
             f"  Install:  {_py()} {os.path.join(HERE, 'staticsight.py')} --install\n"
             f"  or:       {_py()} -m pip install -r {_req(False)}")
        return 1
    if not os.path.isdir(SRC):
        _err(f"StaticSight: {SRC} not found; run this file from a complete clone of the repository.")
        return 1
    sys.path.insert(0, SRC)
    from staticsight.server import main as server_main

    sys.argv = [os.path.join(HERE, "staticsight.py"), *argv]
    server_main()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
