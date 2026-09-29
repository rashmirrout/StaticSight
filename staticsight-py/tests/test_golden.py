"""Golden Markdown outputs shared with the TypeScript implementation (byte-for-byte parity)."""

import json
import os
from pathlib import Path

import pytest

from staticsight.server import TOOLS, safe_tool

from .conftest import SHARED

CASES = json.loads((SHARED / "golden" / "cases.json").read_text())
# STATICSIGHT_GOLDEN_DIR lets CI generate goldens with the machine's own engine versions (Python) and then
# require byte-for-byte parity from the TypeScript suite; by default the committed goldens are used.
GOLDEN_DIR = Path(os.environ.get("STATICSIGHT_GOLDEN_DIR") or (SHARED / "golden"))
FNS = {fn.__name__: safe_tool(fn) for fn in TOOLS}
UPDATE = os.environ.get("STATICSIGHT_UPDATE_GOLDEN") == "1"


@pytest.mark.parametrize("case", CASES, ids=[c["id"] for c in CASES])
async def test_golden(case, workspace):
    out = await FNS[case["tool"]](**case["args"])
    path = GOLDEN_DIR / f"{case['id']}.md"
    if UPDATE or not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes((out + "\n").encode("utf-8"))
    assert out + "\n" == path.read_bytes().decode("utf-8")
