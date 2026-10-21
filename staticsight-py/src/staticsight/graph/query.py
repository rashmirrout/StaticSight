"""Queries over the code graph: resolve names to definitions, callers and callees, class hierarchy, entry points.

Resolution is by name (there is no compiler): a call `x.f()` can reach any `f`; `C::f()` and implicit calls from a
member of `C` are narrowed to `C` and its bases/derived classes. The TypeScript twin is src/graph/query.ts.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass

FUNC_KINDS = ("function", "prototype")
TYPE_KINDS = ("class", "struct", "union")
ENTRY_NAMES = frozenset({"main", "wmain", "_tmain", "WinMain", "wWinMain", "_tWinMain", "DllMain", "ServiceMain"})
_TEST_DIR = re.compile(r"(^|/)(tests?|unittests?|unit_tests?|test_\w+|\w+_tests?)/", re.I)
_TEST_FILE = re.compile(r"(^|/)(test_\w+|\w+_tests?|\w+Tests?)\.\w+$")


@dataclass(frozen=True)
class Fn:
    qualified: str
    name: str
    path: str
    line: int
    end: int
    kind: str
    scope: str
    scope_kind: str
    signature: str
    typeref: str
    properties: str

    @property
    def cls(self) -> str:
        """The enclosing class/struct/union ('' for free functions, also inside namespaces)."""
        return self.scope.rsplit("::", 1)[-1] if self.scope and self.scope_kind in TYPE_KINDS else ""

    @property
    def loc(self) -> str:
        return f"{self.path}:{self.line}"

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.qualified, self.path, self.line)

    @property
    def return_type(self) -> str:
        t = self.typeref
        return t[len("typename:"):] if t.startswith("typename:") else t


@dataclass(frozen=True)
class Call:
    path: str
    caller: str
    caller_line: int
    callee: str
    qualifier: str
    how: str
    line: int
    code: str
    text: str

    @property
    def caller_cls(self) -> str:
        """Last scope component of the caller (a class for methods; may be a namespace for free functions)."""
        return self.caller.rsplit("::", 2)[-2] if "::" in self.caller else ""

    @property
    def caller_key(self) -> tuple[str, str, int]:
        return (self.caller, self.path, self.caller_line)


_FN_COLS = "qualified, name, path, line, end_line, kind, scope, scope_kind, signature, typeref, properties"
_CALL_COLS = "path, caller, caller_line, callee, qualifier, how, line, code, text"


def is_test_path(path: str) -> bool:
    return bool(_TEST_DIR.search(path) or _TEST_FILE.search(path))


def split_symbol(symbol: str) -> tuple[str, str]:
    """'Router::process_packet()' -> ('Router', 'process_packet'); 'process_packet' -> ('', 'process_packet')."""
    s = symbol.strip().rstrip(")").rstrip("(").strip()
    if "::" in s:
        cls, _, short = s.rpartition("::")
        return cls.rsplit("::", 1)[-1], short
    return "", s


def _fns(rows) -> list[Fn]:
    return [Fn(*r) for r in rows]


def functions_named(db: sqlite3.Connection, symbol: str, definitions_first: bool = True) -> list[Fn]:
    """Function definitions (or, when none, prototypes) named `symbol`; `Class::name` narrows to that class."""
    cls, short = split_symbol(symbol)
    rows = _fns(db.execute(f"SELECT {_FN_COLS} FROM defs WHERE name=? AND kind IN ('function','prototype') "
                           "ORDER BY path, line, qualified", (short,)))
    if cls:
        rows = [f for f in rows if f.cls == cls] or [f for f in rows if f.scope.endswith(cls)]
    if definitions_first:
        defs = [f for f in rows if f.kind == "function"]
        if defs:
            return defs
    return rows


def all_named(db: sqlite3.Connection, name: str, kinds: tuple[str, ...]) -> list[Fn]:
    marks = ",".join("?" * len(kinds))
    return _fns(db.execute(f"SELECT {_FN_COLS} FROM defs WHERE name=? AND kind IN ({marks}) ORDER BY path, line, qualified",
                           (name, *kinds)))


def enclosing_function(db: sqlite3.Connection, path: str, line: int) -> Fn | None:
    rows = _fns(db.execute(f"SELECT {_FN_COLS} FROM defs WHERE path=? AND kind='function' AND line<=? AND end_line>=? "
                           "ORDER BY (end_line-line), line DESC, qualified", (path, line, line)))
    return rows[0] if rows else None


def function_at(db: sqlite3.Connection, qualified: str, path: str, line: int) -> Fn | None:
    rows = _fns(db.execute(f"SELECT {_FN_COLS} FROM defs WHERE qualified=? AND path=? AND line=? AND kind='function'",
                           (qualified, path, line)))
    return rows[0] if rows else None


# ------------------------------------------------------------------------------------------------ class hierarchy
def _bases_of(inherits: str) -> list[str]:
    out = []
    for part in inherits.split(","):
        part = re.sub(r"<.*>", "", part).strip()
        part = re.sub(r"^(public|protected|private|virtual)\s+", "", part).strip()
        if part:
            out.append(part.rsplit("::", 1)[-1])
    return out


def types_named(db: sqlite3.Connection, name: str) -> list[tuple[str, str, int, str, str]]:
    """(name, path, line, kind, inherits) of class/struct/union definitions named `name`."""
    return list(db.execute("SELECT name, path, line, kind, inherits FROM defs WHERE name=? AND kind IN "
                           "('class','struct','union') ORDER BY path, line", (name,)))


def bases(db: sqlite3.Connection, cls: str) -> list[str]:
    out: list[str] = []
    for _, _, _, _, inh in types_named(db, cls):
        for b in _bases_of(inh):
            if b not in out:
                out.append(b)
    return out


_derived_index: dict[int, tuple[int, dict[str, list[str]]]] = {}


def _derived_map(db: sqlite3.Connection) -> dict[str, list[str]]:
    """base class name -> derived class names, built in one scan and rebuilt when the graph changes."""
    key, stamp = id(db), db.total_changes
    hit = _derived_index.get(key)
    if hit is not None and hit[0] == stamp:
        return hit[1]
    idx: dict[str, list[str]] = {}
    for name, inh in db.execute("SELECT name, inherits FROM defs WHERE inherits<>'' AND kind IN ('class','struct','union') "
                                "ORDER BY name, path, line"):
        for b in _bases_of(inh):
            lst = idx.setdefault(b, [])
            if name not in lst:
                lst.append(name)
    _derived_index[key] = (stamp, idx)
    return idx


def derived(db: sqlite3.Connection, cls: str) -> list[str]:
    return list(_derived_map(db).get(cls, []))


def family(db: sqlite3.Connection, cls: str, limit: int = 50) -> set[str]:
    """cls with all its ancestors and descendants."""
    seen = {cls}
    todo = [cls]
    while todo and len(seen) < limit:
        c = todo.pop()
        for n in bases(db, c) + derived(db, c):
            if n not in seen:
                seen.add(n)
                todo.append(n)
    return seen


def overrides_of(db: sqlite3.Connection, fn: Fn) -> list[Fn]:
    """Same-name methods in derived classes (and base declarations) of a virtual method's class."""
    if not fn.cls:
        return []
    fam = family(db, fn.cls)
    out = [f for f in _fns(db.execute(f"SELECT {_FN_COLS} FROM defs WHERE name=? AND kind IN ('function','prototype') "
                                      "ORDER BY path, line, qualified", (fn.name,)))
           if f.cls in fam and f.cls != fn.cls]
    return out


# ------------------------------------------------------------------------------------------------ calls
def calls_to(db: sqlite3.Connection, name: str) -> list[Call]:
    return [Call(*r) for r in db.execute(f"SELECT {_CALL_COLS} FROM calls WHERE callee=? ORDER BY path, line, caller",
                                         (name,))]


def calls_from(db: sqlite3.Connection, fn: Fn) -> list[Call]:
    return [Call(*r) for r in db.execute(f"SELECT {_CALL_COLS} FROM calls WHERE caller=? AND path=? AND caller_line=? "
                                         "ORDER BY line, callee", (fn.qualified, fn.path, fn.line))]


def _type_names(db: sqlite3.Connection, cache: dict) -> set[str]:
    t = cache.get("__types__")
    if t is None:
        t = cache["__types__"] = {r[0] for r in db.execute(
            "SELECT DISTINCT name FROM defs WHERE kind IN ('class','struct','union')")}
    return t


def call_can_reach(db: sqlite3.Connection, c: Call, target: Fn, cache: dict) -> bool:
    """Could this call site invoke `target`? (by name, narrowed by class where the source says so)."""
    cls = target.cls
    if not cls:  # a free function, possibly in a namespace
        if c.how == "member":
            return False
        if c.how == "qualified" and c.qualifier:
            if target.scope and target.scope.rsplit("::", 1)[-1] == c.qualifier:
                return True
            return c.qualifier not in _type_names(db, cache)
        if c.how == "call" and c.caller_cls:
            # an unqualified call inside a member function prefers that class's own method of the same name
            return not any(f.cls == c.caller_cls for f in functions_named(db, c.callee, False))
        return True
    fam = cache.get(cls)
    if fam is None:
        fam = cache[cls] = family(db, cls)
    if c.how == "qualified":
        return c.qualifier in fam
    if c.how == "call":
        return c.caller_cls in fam
    return True


def callers_of(db: sqlite3.Connection, target: Fn, fam_cache: dict[str, set[str]]) -> list[Call]:
    return [c for c in calls_to(db, target.name) if call_can_reach(db, c, target, fam_cache)]


def resolve_call(db: sqlite3.Connection, c: Call, fam_cache: dict[str, set[str]]) -> list[Fn]:
    """In-repository functions a call site may invoke ([] = external, e.g. libc or an SDK)."""
    cands = functions_named(db, c.callee)
    return [f for f in cands if call_can_reach(db, c, f, fam_cache)]


TEST_MACROS = frozenset({"TEST", "TEST_F", "TEST_P", "TYPED_TEST", "TYPED_TEST_P", "TEST_CASE", "SCENARIO",
                         "BOOST_AUTO_TEST_CASE"})


def label(fn: Fn) -> str:
    """Display name; test macros keep their arguments (`TEST(Proto,RoundTrip)`) so tests are distinguishable."""
    return f"{fn.name}{fn.signature}" if fn.name in TEST_MACROS and fn.signature else fn.qualified


def caller_label(db: sqlite3.Connection, c: Call) -> str:
    return label(caller_fn(db, c)) if c.caller.rsplit("::", 1)[-1] in TEST_MACROS else c.caller


def caller_fn(db: sqlite3.Connection, c: Call) -> Fn:
    f = function_at(db, c.caller, c.path, c.caller_line)
    if f is not None:
        return f
    _, short = split_symbol(c.caller)
    scope = c.caller.rsplit("::", 1)[0] if "::" in c.caller else ""
    return Fn(c.caller, short, c.path, c.caller_line, c.caller_line, "function", scope, "", "", "", "")


def entry_kind(db: sqlite3.Connection, fn: Fn, thread_targets: set[str]) -> str:
    """'program' | 'thread' | 'test' | ''"""
    if fn.name in ENTRY_NAMES and not fn.cls:
        return "program"
    if fn.name in thread_targets:
        return "thread"
    if is_test_path(fn.path):
        return "test"
    return ""


def thread_targets(db: sqlite3.Connection) -> set[str]:
    return {r[0] for r in db.execute("SELECT DISTINCT callee FROM calls WHERE how='thread'")}


def module_of(path: str) -> str:
    parts = path.split("/")
    return "/".join(parts[:2]) if len(parts) > 2 else (parts[0] if len(parts) > 1 else ".")
