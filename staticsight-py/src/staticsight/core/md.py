"""Markdown helpers shared by all tools. Output is fed to an LLM, so everything here is about token economy."""

from __future__ import annotations

import contextvars
import hashlib
import json
from pathlib import Path
from typing import Iterable, Sequence

LINE_CLIP = 160
PAGE_SIZE = 40

# Where `truncate_list` stores the items it had to cut, so the agent can fetch them with `get_more`.
# Set by the tool wrapper for the duration of one call; unset (direct report calls) means no continuation.
pages_dir: contextvars.ContextVar[Path | None] = contextvars.ContextVar("staticsight_pages", default=None)


def clip(text: str, limit: int = LINE_CLIP) -> str:
    text = text.replace("\t", "    ").rstrip()
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def code_span(text: str) -> str:
    """Inline code that survives backticks inside the content."""
    text = clip(text.strip())
    if "`" in text:
        return f"`` {text} ``"
    return f"`{text}`"


def error_card(title: str, message: str, hint: str | None = None) -> str:
    out = f"### ❌ {title}\n{message}"
    if hint:
        out += f"\n\n💡 {hint}"
    return out


def truncate_list(items: Sequence[str], limit: int, noun: str = "results", hint: str = "",
                  header: Sequence[str] = ()) -> list[str]:
    """First `limit` items plus a note; the rest are saved for `get_more` (with `header`, e.g. a table header)."""
    if len(items) <= limit:
        return list(items)
    extra = len(items) - limit
    note = f"_…and {extra} more {noun}"
    note += f". {hint}" if hint else "."
    token = save_page(noun, list(items[limit:]), list(header))
    note += f" Next: `get_more(\"{token}\")`._" if token else "_"
    if header:
        note = "\n" + note  # a blank line ends the table, so the note is not read as a row
    return list(items[:limit]) + [note]


def page_token(noun: str, rest: Sequence[str]) -> str:
    return "P" + hashlib.sha1((noun + "\n" + "\n".join(rest)).encode("utf-8")).hexdigest()[:6]


def save_page(noun: str, rest: list[str], header: list[str] | None = None) -> str:
    d = pages_dir.get()
    if d is None:
        return ""
    token = page_token(noun, rest)
    try:
        d.mkdir(parents=True, exist_ok=True)
        (d / f"{token}.json").write_text(json.dumps({"noun": noun, "items": rest, "header": header or []}), encoding="utf-8")
        _prune(d)
    except OSError:
        return ""
    return token


MAX_PAGES = 500


def _prune(d: Path) -> None:
    """Keep the newest MAX_PAGES pages: tokens are only needed for the lists an agent is still reading."""
    try:
        files = list(d.glob("P*.json"))
        if len(files) <= MAX_PAGES:
            return
        files.sort(key=lambda f: f.stat().st_mtime_ns)
        for f in files[: len(files) - MAX_PAGES]:
            f.unlink(missing_ok=True)
    except OSError:
        pass


def load_page(token: str) -> tuple[str, list[str], list[str]] | None:
    d = pages_dir.get()
    t = token.strip()
    if d is None or not (len(t) == 7 and t[0] == "P" and all(c in "0123456789abcdef" for c in t[1:])):
        return None
    try:
        data = json.loads((d / f"{t}.json").read_text(encoding="utf-8"))
        return str(data["noun"]), [str(x) for x in data["items"]], [str(x) for x in data.get("header", [])]
    except (OSError, ValueError, KeyError, TypeError):
        return None


def numbered_code(lines: Sequence[str], start_line: int, mark: Iterable[int] = (), width: int | None = None) -> list[str]:
    marks = set(mark)
    last = start_line + len(lines) - 1
    width = width or len(str(max(last, 1)))
    out = []
    for i, text in enumerate(lines):
        n = start_line + i
        prefix = ">" if n in marks else " "
        out.append(f"{prefix}{str(n).rjust(width)} | {clip(text, 200)}")
    return out


def compress_ranges(numbers: Iterable[int], max_parts: int = 0) -> str:
    nums = sorted(set(numbers))
    if not nums:
        return ""
    parts: list[str] = []
    start = prev = nums[0]
    for n in nums[1:]:
        if n == prev + 1:
            prev = n
            continue
        parts.append(f"L{start}" if start == prev else f"L{start}-{prev}")
        start = prev = n
    parts.append(f"L{start}" if start == prev else f"L{start}-{prev}")
    if max_parts and len(parts) > max_parts:
        return ", ".join(parts[:max_parts]) + f", … (+{len(parts) - max_parts} more ranges)"
    return ", ".join(parts)


def enforce_budget(text: str, max_chars: int) -> str:
    """Cut at a line boundary under max_chars and keep code fences balanced."""
    if len(text) <= max_chars:
        return text
    cut = text.rfind("\n", 0, max_chars)
    if cut <= 0:
        cut = max_chars
    kept = text[:cut]
    if kept.count("```") % 2 == 1:
        kept += "\n```"
    return kept + f"\n\n_…output truncated at {max_chars} characters to protect the context budget. Narrow the query for more._"


def plural(n: int, word: str, suffix: str = "s") -> str:
    return f"{n} {word}{'' if n == 1 else suffix}"
