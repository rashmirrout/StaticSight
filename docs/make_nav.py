#!/usr/bin/env python3
"""Write the navigation frame of every guide and book chapter: breadcrumb, "On this page", previous/next.

    python3 docs/make_nav.py           # rewrite the navigation blocks
    python3 docs/make_nav.py --check   # exit 1 if a page's navigation is out of date (used by the tests)

The blocks sit between HTML comment markers (<!-- nav:top -->, <!-- nav:toc -->, <!-- nav:bottom -->), so the
tool is idempotent and hand-written text is never touched. Standard library only.
"""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

DOCS = Path(__file__).resolve().parent
sys.path.insert(0, str(DOCS))
from check_docs import prose, slug  # noqa: E402

GUIDES = [  # reading order, with short titles
    ("getting-started.md", "Getting started"),
    ("cli-guide.md", "Command-line guide"),
    ("mcp-guide.md", "MCP guide"),
    ("semantic-search/README.md", "Semantic search"),
    ("semantic-search/manual-guide.md", "Manual guide"),
    ("semantic-search/mcp-flow.md", "MCP flow"),
    ("semantic-search/internals.md", "Internals"),
    ("semantic-search/experiments.md", "Learn and experiment"),
    ("MCP_TOOLS.md", "MCP tool reference"),
    ("COMMANDS.md", "Raw commands"),
    ("benchmarks.md", "Benchmarks"),
]
BOOK = sorted(p.name for p in (DOCS / "book").glob("[0-9][0-9]-*.md"))
TOC_MIN_SECTIONS = 4
MARK = {k: (f"<!-- nav:{k} -->", f"<!-- /nav:{k} -->") for k in ("top", "toc", "bottom")}


def rel(src: str, dst: str) -> str:
    return Path(os.path.relpath(DOCS / dst, (DOCS / src).parent)).as_posix()


def h1(page: str) -> str:
    for line in prose((DOCS / page).read_text(encoding="utf-8"), keep_inline=True).split("\n"):
        if line.startswith("# "):
            return line[2:].strip()
    return page


def sections(page: str) -> list[tuple[str, str]]:
    out = []
    for line in prose((DOCS / page).read_text(encoding="utf-8"), keep_inline=True).split("\n"):
        if line.startswith("## "):
            title = line[3:].strip()
            out.append((re.sub(r"`([^`]*)`", r"\1", title), slug(title)))
    return out


def crumbs(page: str) -> str:
    parts = [f"📚 [Documentation]({rel(page, 'README.md')})"]
    if page.startswith("semantic-search/") and page != "semantic-search/README.md":
        parts.append(f"[Semantic search]({rel(page, 'semantic-search/README.md')})")
    if page.startswith("book/"):
        parts.append(f"📖 [The book]({rel(page, 'book/00-preface.md')})" if page != "book/00-preface.md" else "📖 The book")
    title = dict(GUIDES).get(page) or re.sub(r"^(\d+)\. ", r"Chapter \1: ", h1(page))
    parts.append(f"**{title}**")
    return " › ".join(parts)


def footer(page: str, order: list[tuple[str, str]]) -> str:
    names = [p for p, _ in order]
    i = names.index(page)
    left = f"⬅️ [{order[i - 1][1]}]({rel(page, order[i - 1][0])})" if i > 0 else ""
    right = f"[{order[i + 1][1]}]({rel(page, order[i + 1][0])}) ➡️" if i + 1 < len(order) else ""
    middle = f"📚 [Documentation]({rel(page, 'README.md')})"
    return "| " + " | ".join([left or " ", middle, right or " "]) + " |\n|:---|:---:|---:|"


def set_block(text: str, key: str, body: str, where: str) -> str:
    start, end = MARK[key]
    block = f"{start}\n{body}\n{end}"
    if start in text:
        return re.sub(re.escape(start) + r".*?" + re.escape(end), lambda _: block, text, count=1, flags=re.S)
    lines = text.split("\n")
    if where == "top":
        return block + "\n\n" + text
    if where == "bottom":
        return text.rstrip("\n") + "\n\n---\n\n" + block + "\n"
    # after the first paragraph that follows the H1
    i = next(k for k, ln in enumerate(lines) if ln.startswith("# "))
    k = i + 1
    while k < len(lines) and not lines[k].strip():
        k += 1
    while k < len(lines) and lines[k].strip():
        k += 1
    return "\n".join(lines[:k] + ["", block] + lines[k:])


def render(page: str, order: list[tuple[str, str]]) -> str:
    text = (DOCS / page).read_text(encoding="utf-8")
    if page.startswith("book/"):  # the footer replaces the old hand-written "Next:" lines
        text = re.sub(r"\n+Next: \[[^\]]*\]\([^)]*\)\.\n*$", "\n", text)
        text = re.sub(r"\n+Back to the \[documentation index\]\([^)]*\)\.\n*$", "\n", text)
    text = set_block(text, "top", crumbs(page), "top")
    secs = sections(page)
    if not page.startswith("book/") and len(secs) >= TOC_MIN_SECTIONS:
        toc = "**On this page:** " + " · ".join(f"[{t}](#{a})" for t, a in secs)
        text = set_block(text, "toc", toc, "toc")
    return set_block(text, "bottom", footer(page, order), "bottom")


def main() -> int:
    check = "--check" in sys.argv
    book = [(f"book/{n}", re.sub(r"^\d+\. ", "", h1(f"book/{n}"))) for n in BOOK]
    stale = []
    for order in (GUIDES, book):
        for page, _ in order:
            new = render(page, order)
            if new != (DOCS / page).read_text(encoding="utf-8"):
                stale.append(page)
                if not check:
                    (DOCS / page).write_text(new, encoding="utf-8")
    if check and stale:
        print("navigation out of date (run python3 docs/make_nav.py):", ", ".join(stale))
        return 1
    print(("up to date" if check else f"updated {len(stale)} page(s)"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
