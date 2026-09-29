#!/usr/bin/env python3
"""Build the deterministic C++ fixture repository used by both test suites (any OS, no shell).

usage: python make_fixture.py <target-dir>

Layout: base commit (also refs/remotes/origin/main) -> feature commit (HEAD, branch "feature")
        + an unstaged edit and an untracked file (the "worktree" overlay).
The TypeScript suite implements the same manifest in staticsight-ts/test/helpers.ts.
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "cpp-sample"


def _copy_tree(src: Path, dst: Path) -> None:
    for f in sorted(src.rglob("*")):
        if f.is_file():
            out = dst / f.relative_to(src)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(f.read_bytes())  # byte-exact: keeps CRLF / BOM / UTF-16 files intact


def build(target: str | os.PathLike[str]) -> Path:
    target = Path(target)
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    ident = manifest["identity"]
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    empty_cfg = Path(tempfile.mkstemp(prefix="ss-gitcfg-")[1])
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": ident["name"], "GIT_AUTHOR_EMAIL": ident["email"], "GIT_AUTHOR_DATE": ident["date"],
        "GIT_COMMITTER_NAME": ident["name"], "GIT_COMMITTER_EMAIL": ident["email"], "GIT_COMMITTER_DATE": ident["date"],
        "GIT_CONFIG_GLOBAL": str(empty_cfg), "GIT_CONFIG_NOSYSTEM": "1",
    }

    def git(*args: str) -> None:
        subprocess.run(["git", *args], cwd=target, env=env, check=True, stdout=subprocess.DEVNULL)

    try:
        for step in manifest["steps"]:
            op = step["op"]
            if op == "init":
                git("init", "-q")
                git("symbolic-ref", "HEAD", f"refs/heads/{step['branch']}")
                for k, v in (("commit.gpgsign", "false"), ("core.autocrlf", "false"), ("core.eol", "lf"),
                             ("core.safecrlf", "false"), ("core.filemode", "false")):
                    git("config", k, v)
            elif op == "copy":
                _copy_tree(DATA / step["from"], target)
            elif op == "commit":
                git("add", "-A")
                git("commit", "-q", "--no-verify", "-m", step["message"])
            elif op == "ref":
                git("update-ref", step["name"], "HEAD")
            elif op == "checkout":
                git("checkout", "-q", "-b", step["branch"])
            else:
                raise ValueError(f"unknown fixture op {op!r}")
    finally:
        empty_cfg.unlink(missing_ok=True)
    return target


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        raise SystemExit(2)
    print(build(sys.argv[1]))
