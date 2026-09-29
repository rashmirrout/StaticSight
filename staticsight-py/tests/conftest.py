import os
import sys
from pathlib import Path

import pytest

from staticsight.engines import ctags
from staticsight.indexer import get_indexer, reset_indexers
from staticsight.semantic.index import get_semantic_index, reset_semantic_indexes

REPO = Path(__file__).resolve().parents[2]
SHARED = REPO / "shared"
sys.path.insert(0, str(SHARED / "fixtures"))
import make_fixture  # noqa: E402


@pytest.fixture(scope="session")
def fixture_repo(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("fx") / "cpp-sample"
    return make_fixture.build(root)


@pytest.fixture(scope="session")
async def workspace(fixture_repo, tmp_path_factory):
    os.environ["WORKSPACE_ROOT"] = str(fixture_repo)
    os.environ["STATICSIGHT_CACHE_DIR"] = str(tmp_path_factory.mktemp("cache"))
    for k in ("STATICSIGHT_BASE_REF", "STATICSIGHT_MAX_RESULTS", "STATICSIGHT_MAX_CHARS", "STATICSIGHT_TIMEOUT"):
        os.environ.pop(k, None)
    os.environ["STATICSIGHT_EMBED_MODEL"] = "test-hash"  # deterministic, no download; identical in the TS suite
    for k in ("STATICSIGHT_SEMANTIC_AUTO_REFRESH", "STATICSIGHT_SEMANTIC_AUTO_REFRESH_FILES", "STATICSIGHT_EMBED_MODEL_DIR"):
        os.environ.pop(k, None)
    reset_indexers()
    reset_semantic_indexes()
    ctags.clear_cache()
    await get_indexer().start()
    assert get_indexer().state == "ready", get_indexer().status()
    await get_semantic_index().refresh()
    return fixture_repo
