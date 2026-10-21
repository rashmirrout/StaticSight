"""Finding IDs: every risk a tool reports gets a short, stable ID the agent can verify later.

IDs are deterministic (`F` + 6 hex of sha1 over kind, file, line and key), so the same issue gets the same ID on
every run and in both implementations. Findings recorded during one tool call are collected in a context variable;
the MCP wrapper returns them as structured content and `flush` persists them to `.staticsight/findings.json`.
"""

from __future__ import annotations

import contextvars
import hashlib
import json
from dataclasses import asdict, dataclass
from pathlib import Path

CONFIDENCE = ("strong", "medium", "weak")
_MAX_STORED = 2000


@dataclass
class Finding:
    id: str
    kind: str
    confidence: str
    path: str
    line: int
    symbol: str
    message: str
    function: str = ""


def as_dict(f: Finding) -> dict:
    return asdict(f)


_current: contextvars.ContextVar[list[Finding] | None] = contextvars.ContextVar("staticsight_findings", default=None)


def finding_id(kind: str, path: str, line: int, key: str) -> str:
    return "F" + hashlib.sha1(f"{kind}|{path}|{line}|{key}".encode()).hexdigest()[:6]


def begin() -> contextvars.Token:
    return _current.set([])


def end(token: contextvars.Token) -> list[Finding]:
    found = _current.get() or []
    _current.reset(token)
    return found


def record(kind: str, confidence: str, path: str, line: int, symbol: str, message: str, function: str = "") -> str:
    if confidence not in CONFIDENCE:
        raise ValueError(f"confidence must be one of {CONFIDENCE}")
    fid = finding_id(kind, path, line, symbol)
    bucket = _current.get()
    if bucket is not None and not any(f.id == fid for f in bucket):
        bucket.append(Finding(fid, kind, confidence, path, line, symbol, message, function))
    return fid


def make(kind: str, confidence: str, path: str, line: int, symbol: str, message: str, function: str = "") -> Finding:
    """A finding that is not added to the current call yet (callers de-duplicate, then `add`)."""
    return Finding(finding_id(kind, path, line, symbol), kind, confidence, path, line, symbol, message, function)


def add(f: Finding) -> None:
    bucket = _current.get()
    if bucket is not None and not any(x.id == f.id for x in bucket):
        bucket.append(f)


def _store(data_dir: Path) -> Path:
    return data_dir / "findings.json"


def load(data_dir: Path) -> dict[str, dict]:
    try:
        data = json.loads(_store(data_dir).read_text(encoding="utf-8"))
        return {f["id"]: f for f in data.get("findings", []) if isinstance(f, dict) and "id" in f}
    except (OSError, ValueError):
        return {}


def _line_text(root: Path, rel: str, line: int, cache: dict[str, list[str]]) -> str:
    if rel not in cache:
        try:
            cache[rel] = (root / rel).read_text(encoding="utf-8", errors="replace").splitlines()
        except OSError:
            cache[rel] = []
    lines = cache[rel]
    return lines[line - 1].strip() if 0 < line <= len(lines) else ""


def flush(root: Path, data_dir: Path, found: list[Finding], tool: str, args: dict) -> None:
    """Persist findings with what `verify_finding` needs: the tool call that produced them and the code line."""
    if not found:
        return
    known = load(data_dir)
    cache: dict[str, list[str]] = {}
    for f in found:
        known.pop(f.id, None)
        known[f.id] = {**asdict(f), "code": _line_text(root, f.path, f.line, cache), "tool": tool, "args": args}
    items = list(known.values())[-_MAX_STORED:]
    try:
        data_dir.mkdir(parents=True, exist_ok=True)
        tmp = _store(data_dir).with_suffix(".tmp")
        tmp.write_text(json.dumps({"version": 1, "findings": items}, indent=1), encoding="utf-8")
        tmp.replace(_store(data_dir))
    except OSError:
        pass


def lookup(data_dir: Path, fid: str) -> dict | None:
    return load(data_dir).get(fid.strip())
