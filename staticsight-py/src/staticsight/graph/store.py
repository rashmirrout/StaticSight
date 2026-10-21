"""Code graph: definitions, calls, function references and includes of every C/C++ file, in `.staticsight/graph.db`.

Built per file from Universal Ctags (definitions, class hierarchy, virtual/override) and the comment/string-stripped
source (calls, function references, threads/callbacks, includes). Calls are stored by callee NAME and resolved to
definitions when queried, so a changed file is re-parsed alone. Freshness is checked on every use (no git hooks):
small drift is refreshed before answering, large drift or a first build of a big repository run in the background.
The TypeScript twin (src/graph/store.ts) builds identical rows.
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
import sqlite3
import time
from dataclasses import dataclass, field

from ..config import Config, load_config, workspace_data_dir
from ..core.cpp_text import strip_code
from ..core.errors import StaticSightError
from ..core.paths import decode_source, split_lines
from ..engines.ctags import Tag, ctags_for_files
from ..engines.git import head_sha
from ..engines.rg import rg_files
from ..engines.vector_store import IndexLock
from ..shared import shared_text

log = logging.getLogger("staticsight.graph")

GRAPH_VERSION = "2"
DEF_KINDS = frozenset({"function", "prototype", "class", "struct", "union", "enum", "enumerator", "member", "typedef",
                       "macro"})
NOT_CALLS = frozenset({
    "if", "for", "while", "switch", "return", "sizeof", "alignof", "decltype", "static_cast", "reinterpret_cast",
    "const_cast", "dynamic_cast", "catch", "throw", "noexcept", "defined", "static_assert", "typeid", "alignas",
    "assert", "new", "delete", "operator", "co_return", "co_await", "co_yield", "__attribute__", "__declspec",
})
# APIs that take a function to run later (thread start routines, callbacks, handlers)
THREAD_APIS = frozenset({
    "thread", "jthread", "async", "CreateThread", "_beginthreadex", "_beginthread", "QueueUserWorkItem",
    "CreateThreadpoolWork", "CreateThreadpoolTimer", "CreateThreadpoolWait", "TrySubmitThreadpoolCallback",
    "CreateTimerQueueTimer", "RegisterWaitForSingleObject", "SetTimer", "RegisterServiceCtrlHandler",
    "RegisterServiceCtrlHandlerW", "RegisterServiceCtrlHandlerA", "RegisterServiceCtrlHandlerEx",
    "RegisterServiceCtrlHandlerExW", "RegisterServiceCtrlHandlerExA", "pthread_create", "atexit", "signal",
})
_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_QUAL = re.compile(r"([A-Za-z_]\w*)\s*(?:<[^<>;]*>)?\s*::\s*$")
_OBJ = re.compile(r"([\w\])]+)\s*(?:\.|->)\s*$")
_DECL_BEFORE = re.compile(
    r"(?:^|[\s(,;{])(?!(?:return|else|throw|co_return|co_await|case|delete|new|goto)\b)[A-Za-z_][\w:]*(?:<[^()]*>)?"
    r"(?:\s+|\s*(?:\*+|&(?!&))\s*)$"
)
_THREAD_DECL = re.compile(r"\b(?:std::)?j?thread\s+\w+\s*([({])")
_ADDR = re.compile(r"&\s*((?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)\b(?!\s*(?:\(|\[|\.|->|::))")
_FN_ARG = re.compile(r"^&?\s*((?:[A-Za-z_]\w*::)*[A-Za-z_]\w*)$")
_INCLUDE = re.compile(r'^\s*#\s*include\s*[<"]([^>"]+)[>"]')
_ALLCAPS = re.compile(r"^[A-Z][A-Z0-9_]*$")
_RANK = {"thread": 0, "ref": 1, "qualified": 2, "member": 3, "call": 4}


@dataclass
class Drift:
    stats: dict[str, tuple[int, str]] = field(default_factory=dict)
    changed: list[str] = field(default_factory=list)
    deleted: list[str] = field(default_factory=list)

    @property
    def total(self) -> int:
        return len(self.changed) + len(self.deleted)


def _clip(text: str, n: int) -> str:
    text = text.rstrip()
    return text if len(text) <= n else text[: n - 1] + "…"


def _args(code: str, open_idx: int) -> list[str]:
    """Top-level arguments of the call whose '(' or '{' is at open_idx (single line)."""
    close = ")" if code[open_idx] == "(" else "}"
    depth, cur, out = 0, "", []
    for ch in code[open_idx:]:
        if ch in "([{":
            depth += 1
            if depth == 1:
                continue
        elif ch in ")]}":
            depth -= 1
            if depth == 0 and ch == close:
                out.append(cur)
                break
        elif ch == "," and depth == 1:
            out.append(cur)
            cur = ""
            continue
        cur += ch
    return [a.strip() for a in out if a.strip()]


def calls_in_line(code: str, fn_short: str) -> list[tuple[str, str, str]]:
    """(callee, qualifier, how) on one stripped line, in column order, one entry per callee (strongest `how`)."""
    found: list[tuple[int, str, str, str]] = []

    def add_fn_args(open_idx: int, col: int) -> None:
        for a in _args(code, open_idx):
            m = _FN_ARG.match(a)
            if m:
                parts = m.group(1).split("::")
                found.append((col, parts[-1], "::".join(parts[:-1]), "thread"))

    for m in _THREAD_DECL.finditer(code):
        add_fn_args(m.start(1), m.start())
    for m in _CALL.finditer(code):
        name = m.group(1)
        if name in NOT_CALLS or (len(name) > 1 and _ALLCAPS.match(name)):
            continue
        raw_before = code[: m.start()]
        before = raw_before.rstrip()
        if name in THREAD_APIS:
            add_fn_args(m.end() - 1, m.start())
        if before.endswith("::"):
            q = _QUAL.search(before)
            qual = q.group(1) if q else ""
            if qual == "std":
                continue
            found.append((m.start(), name, qual, "qualified"))
        elif before.endswith(".") or before.endswith("->"):
            o = _OBJ.search(before)
            found.append((m.start(), name, o.group(1) if o else "", "member"))
        else:
            if _DECL_BEFORE.search(raw_before) or before.endswith("operator"):
                continue
            if name == fn_short and not before:
                continue
            found.append((m.start(), name, "", "call"))
    for m in _ADDR.finditer(code):
        prev = code[: m.start()].rstrip()
        if prev and prev[-1] not in "(,={?:":
            continue  # binary `a & b`
        parts = m.group(1).split("::")
        found.append((m.start(), parts[-1], "::".join(parts[:-1]), "ref"))
    best: dict[str, tuple[int, str, str, str]] = {}
    for f in sorted(found, key=lambda f: (f[0], f[1], _RANK[f[3]])):
        cur = best.get(f[1])
        if cur is None or _RANK[f[3]] < _RANK[cur[3]]:
            best[f[1]] = (min(f[0], cur[0]) if cur else f[0], f[1], f[2], f[3])
    return [(f[1], f[2], f[3]) for f in sorted(best.values(), key=lambda f: (f[0], f[1]))]


def parse_file(path: str, lines: list[str], tags: list[Tag]) -> tuple[list[tuple], list[tuple], list[tuple]]:
    """Rows for one file: defs, calls, includes (pure function; identical in the TypeScript twin)."""
    stripped = strip_code(lines)
    defs = [(path, t.short_name, t.qualified, t.kind, t.line, t.end, t.scope, t.scope_kind, t.signature, t.typeref,
             t.inherits, t.properties) for t in tags if t.kind in DEF_KINDS]
    defs.sort(key=lambda r: (r[4], r[5], r[3], r[2]))
    calls: list[tuple] = []
    for t in sorted((t for t in tags if t.kind == "function"), key=lambda t: (t.line, t.end, t.qualified)):
        start = None
        for n in range(t.line, min(t.end, len(stripped)) + 1):
            c = stripped[n - 1].find("{")
            if c >= 0:
                start = (n, c)
                break
        if start is None:
            continue
        for n in range(start[0], min(t.end, len(stripped)) + 1):
            code = stripped[n - 1]
            if n == start[0]:
                code = " " * (start[1] + 1) + code[start[1] + 1:]
            if code.lstrip().startswith("#") or ("(" not in code and "&" not in code):
                continue
            for callee, qual, how in calls_in_line(code, t.short_name):
                calls.append((path, t.qualified, t.line, callee, qual, how, n, _clip(code.strip(), 300),
                              _clip(lines[n - 1].strip(), 200)))
    includes = []
    for i, ln in enumerate(lines):
        m = _INCLUDE.match(ln)
        if m:
            includes.append((path, i + 1, m.group(1)))
    return defs, calls, includes


class CodeGraph:
    def __init__(self, cfg: Config):
        self.cfg = cfg
        data_dir, _ = workspace_data_dir(cfg)
        self.db_path = data_dir / "graph.db"
        self._db: sqlite3.Connection | None = None
        self._task: asyncio.Task | None = None
        self.done = 0
        self.total = 0
        self.error = ""

    # ------------------------------------------------------------------ store
    @property
    def db(self) -> sqlite3.Connection:
        if self._db is None:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            db = sqlite3.connect(str(self.db_path), isolation_level=None, check_same_thread=False)
            db.execute("PRAGMA journal_mode=WAL")
            db.execute("PRAGMA synchronous=NORMAL")
            db.executescript(shared_text("graph/schema.sql"))
            ver = db.execute("SELECT value FROM meta WHERE key='version'").fetchone()
            if ver is not None and ver[0] != GRAPH_VERSION:
                # an older layout: recreate (the graph is always rebuilt from the sources)
                for t in ("defs", "calls", "includes", "files", "meta"):
                    db.execute(f"DROP TABLE IF EXISTS {t}")
                db.executescript(shared_text("graph/schema.sql"))
            self._db = db
        return self._db

    def meta(self) -> dict[str, str]:
        return {k: v for k, v in self.db.execute("SELECT key, value FROM meta")}

    def file_count(self) -> int:
        return self.db.execute("SELECT COUNT(*) FROM files").fetchone()[0]

    @property
    def exists(self) -> bool:
        return self.db_path.exists() and self.meta().get("version") == GRAPH_VERSION

    @property
    def building(self) -> bool:
        return self._task is not None and not self._task.done()

    # ------------------------------------------------------------------ drift
    async def drift(self) -> Drift:
        paths = await rg_files(self.cfg)
        d = Drift()
        root = self.cfg.workspace_root
        for p in paths:
            try:
                st = os.stat(root / p)
            except OSError:
                continue
            d.stats[p] = (st.st_size, str(st.st_mtime_ns))
        known = {r[0]: (r[1], r[2]) for r in self.db.execute("SELECT path, size, mtime_ns FROM files")}
        d.changed = sorted(p for p, st in d.stats.items() if known.get(p) != st)
        d.deleted = sorted(p for p in known if p not in d.stats)
        return d

    # ---------------------------------------------------------------- refresh
    async def refresh(self, full: bool = False) -> str:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        lock = IndexLock(self.db_path.with_suffix(".lock"))
        if not lock.acquire():
            return "another StaticSight process is refreshing the code graph"
        try:
            return await self._refresh(full, lock)
        finally:
            lock.release()

    async def _refresh(self, full: bool, lock: IndexLock) -> str:
        db = self.db
        if full:
            for t in ("defs", "calls", "includes", "files"):
                db.execute(f"DELETE FROM {t}")
        d = await self.drift()
        known = {r[0]: r[1] for r in db.execute("SELECT path, sha1 FROM files")}
        self.total, self.done = len(d.changed), 0
        parsed = 0
        root = self.cfg.workspace_root
        for i in range(0, len(d.changed), 100):
            batch = d.changed[i:i + 100]
            todo: list[tuple[str, list[str], str]] = []
            for p in batch:
                try:
                    data = (root / p).read_bytes()
                except OSError:
                    continue
                sha = hashlib.sha1(data).hexdigest()
                size, mtime = d.stats[p]
                if known.get(p) == sha:
                    db.execute("UPDATE files SET size=?, mtime_ns=? WHERE path=?", (size, mtime, p))
                    continue
                todo.append((p, split_lines(decode_source(data)), sha))
            tags = await ctags_for_files(self.cfg, [p for p, _, _ in todo]) if todo else {}
            rows = await asyncio.to_thread(
                lambda todo=todo, tags=tags: [(p, sha, parse_file(p, lines, tags.get(p, []))) for p, lines, sha in todo])
            db.execute("BEGIN")
            try:
                for p, sha, (defs, calls, incs) in rows:
                    for t in ("defs", "calls", "includes"):
                        db.execute(f"DELETE FROM {t} WHERE path=?", (p,))
                    db.executemany("INSERT INTO defs VALUES(?,?,?,?,?,?,?,?,?,?,?,?)", defs)
                    db.executemany("INSERT INTO calls VALUES(?,?,?,?,?,?,?,?,?)", calls)
                    db.executemany("INSERT INTO includes VALUES(?,?,?)", incs)
                    size, mtime = d.stats[p]
                    db.execute("INSERT OR REPLACE INTO files VALUES(?,?,?,?)", (p, size, mtime, sha))
                db.execute("COMMIT")
            except Exception:
                db.execute("ROLLBACK")
                raise
            parsed += len(rows)
            self.done = min(self.total, i + len(batch))
            lock.heartbeat()
        if d.deleted:
            db.execute("BEGIN")
            for p in d.deleted:
                for t in ("defs", "calls", "includes", "files"):
                    db.execute(f"DELETE FROM {t} WHERE path=?", (p,))
            db.execute("COMMIT")
        try:
            head = await head_sha(self.cfg)
        except StaticSightError:
            head = ""
        db.executemany("INSERT OR REPLACE INTO meta(key, value) VALUES(?, ?)",
                       [("version", GRAPH_VERSION), ("head", head), ("updated_at", str(int(time.time())))])
        return f"re-parsed {parsed} changed file(s), removed {len(d.deleted)}"

    def start_background(self, full: bool = False) -> bool:
        if self.building:
            return False
        self._task = asyncio.get_running_loop().create_task(self._background(full))
        return True

    async def _background(self, full: bool) -> None:
        try:
            await self.refresh(full)
            self.error = ""
        except StaticSightError as exc:
            self.error = exc.message
            log.warning("code graph refresh failed: %s", exc.message)
        except Exception as exc:  # background work must never crash the server
            self.error = repr(exc)
            log.exception("code graph refresh failed")

    async def wait_for_background(self) -> None:
        if self._task is not None:
            await asyncio.shield(self._task)

    def progress(self) -> str:
        return f"{self.done}/{self.total} files" if self.total else "starting"

    async def ensure_fresh(self) -> tuple[str, bool]:
        """Freshness policy for graph tools. Returns (note, usable)."""
        cfg = self.cfg
        for _ in range(100):  # the background build counts its files first (well under a second)
            if not (self.building and self.total == 0):
                break
            await asyncio.sleep(0.05)
        if self.building and self.total <= cfg.graph_auto_refresh_files:
            await self.wait_for_background()  # a small build finishes sooner than a retry would
        if self.building:
            return (f"⚠️ The code graph is being refreshed in the background ({self.progress()}); results may be "
                    "incomplete. Retry for the full picture.", self.exists and self.file_count() > 0)
        empty = not self.exists or self.file_count() == 0
        if not cfg.graph_auto_refresh:
            if empty:
                return "The code graph has not been built (automatic refresh is disabled): run `staticsight index build`.", False
            return "Code graph (automatic refresh disabled; may be stale).", True
        d = await self.drift()
        if d.total == 0:
            return f"Code graph up to date ({self.file_count()} files).", True
        if d.total <= cfg.graph_auto_refresh_files:
            summary = await self.refresh()
            return f"Code graph refreshed before answering: {summary}.", True
        self.start_background(full=empty)
        if empty:
            return (f"The code graph is being built for the first time in the background ({len(d.changed)} files). "
                    "Retry in a moment; `get_index_status` shows progress.", False)
        return (f"⚠️ {d.total} files changed since the code graph was built; a background refresh has started. "
                "Results come from the previous graph; retry for fresh results.", True)

    def status_lines(self) -> list[str]:
        if not self.building and not self.exists:
            return ["### 🕸️ CODE GRAPH", "- **State:** not built yet (built automatically on the first graph tool call)"]
        if self.building:
            state = f"building ({self.progress()})"
        else:
            m = self.meta()
            age = int(time.time()) - int(m.get("updated_at", "0") or 0)
            state = f"ready (last refresh {age}s ago, HEAD {m.get('head', '')[:10] or 'n/a'})"
        q = self.db.execute
        out = ["### 🕸️ CODE GRAPH", f"- **State:** {state}",
               f"- **Content:** {q('SELECT COUNT(*) FROM files').fetchone()[0]} files, "
               f"{q('SELECT COUNT(*) FROM defs').fetchone()[0]} definitions, "
               f"{q('SELECT COUNT(*) FROM calls').fetchone()[0]} calls and references, "
               f"{q('SELECT COUNT(*) FROM includes').fetchone()[0]} includes"]
        if self.error:
            out.append(f"- **Last error:** {self.error}")
        out.append(f"- **Database:** `{self.db_path}`")
        return out


_graphs: dict[str, CodeGraph] = {}


def get_graph(cfg: Config | None = None) -> CodeGraph:
    cfg = cfg or load_config()
    key = f"{cfg.workspace_root}|{cfg.cache_dir}|{cfg.data_dir_mode}"
    g = _graphs.get(key)
    if g is None:
        g = _graphs[key] = CodeGraph(cfg)
    else:
        g.cfg = cfg
    return g


def reset_graphs() -> None:
    for g in _graphs.values():
        if g._db is not None:
            g._db.close()
    _graphs.clear()
