#!/usr/bin/env python3
"""Keep the documentation honest: run the documented commands and check every link.

    python3 docs/check_docs.py                 # links + commands (Python implementation)
    python3 docs/check_docs.py --impl ts       # commands through the TypeScript implementation
    python3 docs/check_docs.py --links-only

Commands: every line starting with `staticsight ` (or `cd `) inside a ```bash block of the guides listed in GUIDES is
run from a fresh copy of the test repository (shared/fixtures/make_fixture.py). The expected exit code is 0 unless the
line ends with `# exit N`. The semantic commands use the deterministic test embedder, so no model is downloaded.

Links: every relative Markdown link in README.md and docs/**/*.md must point to an existing file, and every `#anchor`
to a heading in it (GitHub's anchor rules).

Standard library only.
"""

from __future__ import annotations

import argparse
import importlib.util
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DOCS = REPO / "docs"
GUIDES = ["docs/cli-guide.md", "docs/getting-started.md", "docs/semantic-search/manual-guide.md"]
SEMANTIC_WORDS = ("index", "search", "similar", "model", "semantic_search", "find_similar_code", "refresh_semantic_index")
FENCE = re.compile(r"^(`{3,}|~{3,})(.*)$")


# ------------------------------------------------------------------------------------------------ markdown helpers
def blocks(text: str):
    """Yield (language, start_line, lines) for every fenced code block."""
    lines = text.split("\n")
    i = 0
    while i < len(lines):
        m = FENCE.match(lines[i])
        if m:
            fence, lang = m.group(1), m.group(2).strip()
            j = i + 1
            while j < len(lines) and not (lines[j].startswith(fence[0] * len(fence)) and lines[j].strip() == fence[0] * len(fence)):
                j += 1
            yield lang, i + 1, lines[i + 1:j]
            i = j + 1
            continue
        i += 1


def prose(text: str, keep_inline: bool = False) -> str:
    """The text outside fenced code blocks (and outside inline code spans unless keep_inline)."""
    out, lines, i = [], text.split("\n"), 0
    while i < len(lines):
        m = FENCE.match(lines[i])
        if m:
            fence = m.group(1)
            i += 1
            while i < len(lines) and lines[i].strip() != fence[0] * len(fence):
                i += 1
            i += 1
            continue
        out.append(lines[i] if keep_inline else re.sub(r"`[^`]*`", "", lines[i]))
        i += 1
    return "\n".join(out)


def slug(heading: str) -> str:
    """GitHub's anchor for a heading: lower case, punctuation removed, spaces to hyphens."""
    h = re.sub(r"`([^`]*)`", r"\1", heading.strip().lower())
    h = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", h)
    h = re.sub(r"[^\w\- ]", "", h)
    return h.replace(" ", "-")


def anchors(path: Path) -> set[str]:
    seen: dict[str, int] = {}
    out: set[str] = set()
    for line in prose(path.read_text(encoding="utf-8"), keep_inline=True).split("\n"):
        m = re.match(r"^#{1,6}\s+(.*?)\s*#*\s*$", line)
        if not m:
            continue
        s = slug(m.group(1))
        n = seen.get(s, 0)
        seen[s] = n + 1
        out.add(s if n == 0 else f"{s}-{n}")
    return out


# ------------------------------------------------------------------------------------------------ link check
def check_links(files: list[Path] | None = None) -> list[str]:
    errors: list[str] = []
    files = files if files is not None else [REPO / "README.md", *sorted(DOCS.rglob("*.md"))]
    for f in files:
        text = prose(f.read_text(encoding="utf-8"))
        targets = [m.group(1) for m in re.finditer(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)", text)]
        targets += re.findall(r"""<(?:img|a)\b[^>]*?\b(?:src|href)=["']([^"']+)["']""", text)
        for target in targets:
            if re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                continue  # http:, https:, mailto:, ...
            path_part, _, anchor = target.partition("#")
            dest = (f.parent / path_part).resolve() if path_part else f
            rel = f.relative_to(REPO) if f.is_relative_to(REPO) else f
            if not dest.exists():
                errors.append(f"{rel}: broken link {target}")
                continue
            if anchor and dest.suffix == ".md" and anchor not in anchors(dest):
                errors.append(f"{rel}: missing anchor #{anchor} in {dest.name}")
    return errors


# ------------------------------------------------------------------------------------------------ command check
def documented_commands() -> list[tuple[str, int, str]]:
    """(guide, line number, command) for every runnable line, in document order."""
    out = []
    for guide in GUIDES:
        text = (REPO / guide).read_text(encoding="utf-8")
        for lang, start, lines in blocks(text):
            if lang != "bash":
                continue
            for k, line in enumerate(lines):
                s = line.strip()
                if s.startswith("staticsight ") or s == "staticsight" or s.startswith("cd "):
                    out.append((guide, start + k + 1, s))
    return out


def expected_exit(line: str) -> int:
    m = re.search(r"#\s*exit\s+(\d+)\s*$", line)
    return int(m.group(1)) if m else 0


def launcher(impl: str, python: str) -> list[str]:
    if impl == "ts":
        return ["node", str(REPO / "staticsight-ts" / "dist" / "server.js")]
    return [python, str(REPO / "staticsight.py")]


def semantic_available(python: str, impl: str) -> bool:
    if impl == "ts":
        return True
    code = "import importlib.util as u, sys; sys.exit(0 if u.find_spec('numpy') else 1)"
    return subprocess.run([python, "-c", code], capture_output=True).returncode == 0


def check_commands(impl: str, python: str, keep: bool) -> tuple[list[str], int]:
    tmp = Path(tempfile.mkdtemp(prefix="staticsight-docs-"))
    errors: list[str] = []
    ran = 0
    try:
        sys.path.insert(0, str(REPO / "shared" / "fixtures"))
        import make_fixture  # noqa: E402

        root = Path(make_fixture.build(tmp / "cpp-sample")).resolve()
        env = {k: v for k, v in os.environ.items() if k != "WORKSPACE_ROOT" and not k.startswith("STATICSIGHT_")}
        env.update({"STATICSIGHT_EMBED_MODEL": "test-hash", "STATICSIGHT_CACHE_DIR": str(tmp / "cache")})
        semantic_ok = semantic_available(python, impl)
        base = launcher(impl, python)
        for guide, lineno, line in documented_commands():
            where = f"{guide}:{lineno}"
            args = shlex.split(line, comments=True)
            if args[0] == "cd":
                continue  # handled below, relative to the previous command's folder
            if args == ["staticsight"] or args[1:2] in (["stdio"], ["sse"], ["streamable-http"]):
                continue  # starts the server; it would wait for a client
            if not semantic_ok and any(w in args[1:3] for w in SEMANTIC_WORDS):
                print(f"  skip (no numpy for {python}): {line}")
                continue
            cwd = _cwd_for(guide, lineno, root)
            proc = subprocess.run([*base, *args[1:]], cwd=cwd, env=env, capture_output=True, text=True,
                                  encoding="utf-8", errors="replace", timeout=300)
            ran += 1
            want = expected_exit(line)
            status = "ok  " if proc.returncode == want else "FAIL"
            print(f"  {status} [{proc.returncode}] {line}")
            if proc.returncode != want:
                tail = (proc.stderr or proc.stdout).strip().splitlines()[-3:]
                errors.append(f"{where}: `{line}` exited {proc.returncode}, expected {want}: " + " | ".join(tail))
    finally:
        if keep:
            print(f"  kept {tmp}")
        else:
            shutil.rmtree(tmp, ignore_errors=True)
    return errors, ran


def _cwd_for(guide: str, lineno: int, root: Path) -> Path:
    """The folder a documented command runs in: the fixture root, changed by earlier `cd` lines in the same block."""
    text = (REPO / guide).read_text(encoding="utf-8")
    for lang, start, lines in blocks(text):
        if lang != "bash" or not (start < lineno <= start + len(lines)):
            continue
        cwd = root
        for k, line in enumerate(lines):
            if start + k + 1 >= lineno:
                break
            s = line.strip()
            if s.startswith("cd "):
                cwd = (cwd / shlex.split(s, comments=True)[1]).resolve()
        return cwd
    return root


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--impl", choices=["py", "ts"], default="py", help="implementation that runs the commands")
    ap.add_argument("--python", default=sys.executable, help="Python used to run staticsight.py (default: this one)")
    ap.add_argument("--links-only", action="store_true")
    ap.add_argument("--keep", action="store_true", help="keep the temporary test repository")
    args = ap.parse_args()

    if args.impl == "py" and not args.links_only:
        probe = subprocess.run([args.python, "-c", "import importlib.util as u, sys; sys.exit(u.find_spec('mcp') is None)"],
                               capture_output=True)
        if probe.returncode != 0:
            print(f"error: the `mcp` package is not installed for {args.python}, so no documented command can run.\n"
                  f"  Install it:  {args.python} {REPO / 'staticsight.py'} --install --semantic\n"
                  f"  or use another Python:  --python /path/to/python   (or check links only: --links-only)",
                  file=sys.stderr)
            return 2
    print("Links:")
    errors = check_links()
    print(f"  {'ok' if not errors else f'{len(errors)} problem(s)'}")
    ran = 0
    if not args.links_only:
        print(f"Commands ({args.impl}):")
        cmd_errors, ran = check_commands(args.impl, args.python, args.keep)
        errors += cmd_errors
    for e in errors:
        print(f"ERROR {e}", file=sys.stderr)
    print(f"{'OK' if not errors else 'FAILED'}: {ran} command(s) run, {len(errors)} problem(s).")
    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
