#!/usr/bin/env python3
"""semantic_query.py - learn how StaticSight's semantic search works, in ~150 lines of plain Python.

This is a teaching tool, not the product. It answers a question against an index that StaticSight already built
(`staticsight index build`), using only the SQLite file, the ONNX model and three packages. Read it top to bottom.

    pip install onnxruntime tokenizers numpy          # or run it with staticsight-py/.venv/bin/python

    python scripts/semantic_query.py "check if a windows service is installed"
    python scripts/semantic_query.py "retry after a failure" --repo /path/to/repo --top 10
    python scripts/semantic_query.py "parse the packet header" --explain    # show every step

What the real tools add on top (see docs/semantic-search/internals.md): keyword fusion (exact identifiers), grouping of long functions
split into several chunks, filters (language/kind/path), code excerpts, and automatic index refresh.
"""

from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
import sys
import time
from pathlib import Path

MODEL_NAME = "jina-code"
MODEL_REVISION = "516f4baf13dec4ddddda8631e019b5737c8bc250"  # pinned in shared/semantic/models.json


# --------------------------------------------------------------------------- step 0: find the files
def cache_dir() -> Path:
    """Same rule as StaticSight: STATICSIGHT_CACHE_DIR, else the per-user cache of the OS."""
    if os.environ.get("STATICSIGHT_CACHE_DIR"):
        return Path(os.environ["STATICSIGHT_CACHE_DIR"]).expanduser()
    if os.name == "nt":
        return Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local")) / "staticsight"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "staticsight"


def find_repo_root(start: Path) -> Path:
    """Same rule as StaticSight: the nearest folder at or above `start` holding `.staticsight/` or `.git`."""
    start = Path(os.path.realpath(start))
    for d in (start, *start.parents):
        if (d / ".staticsight").is_dir() or (d / ".git").exists():
            return d
    return start


def index_path(repo: Path) -> Path:
    """Default: `<repo>/.staticsight/semantic.db` (one index per clone). STATICSIGHT_DATA_DIR=cache (or a read-only
    repository) keeps it in the per-user cache, in a folder named after the sha1 of the repository's real path."""
    mode = os.environ.get("STATICSIGHT_DATA_DIR", "").strip() or "repo"
    in_repo = repo / ".staticsight" / "semantic.db"
    if mode == "repo" and in_repo.is_file():
        return in_repo
    if mode not in ("repo", "cache"):
        return Path(mode).expanduser() / "semantic.db"
    key = os.path.realpath(repo).replace("\\", "/")
    if os.name == "nt":
        key = key.casefold()
    cached = cache_dir() / hashlib.sha1(key.encode()).hexdigest()[:16] / "semantic.db"
    return cached if (mode == "cache" or cached.is_file()) else in_repo


def model_path() -> Path:
    return Path(os.environ.get("STATICSIGHT_EMBED_MODEL_DIR") or cache_dir() / "models" / MODEL_NAME / MODEL_REVISION)


def main() -> int:
    ap = argparse.ArgumentParser(description="Learn how StaticSight's semantic search works (standalone).")
    ap.add_argument("query", help="what the code does, in plain words")
    ap.add_argument("--repo", default=os.environ.get("WORKSPACE_ROOT", ""),
                    help="repository (default: WORKSPACE_ROOT, else found from the current folder)")
    ap.add_argument("--top", type=int, default=5, help="number of results")
    ap.add_argument("--db", help="explicit path to semantic.db (overrides --repo)")
    ap.add_argument("--model", help="explicit model folder (overrides the cache)")
    ap.add_argument("--explain", action="store_true", help="print what happens at every step")
    args = ap.parse_args()

    try:
        import numpy as np
        from tokenizers import Tokenizer

        # onnxruntime prints hardware-probe warnings straight to file descriptor 2 while importing; hide them.
        sys.stderr.flush()
        saved = os.dup(2)
        try:
            with open(os.devnull, "w") as null:
                os.dup2(null.fileno(), 2)
                import onnxruntime as ort
        finally:
            os.dup2(saved, 2)
            os.close(saved)
    except ImportError as exc:
        print(f"missing package: {exc.name}. Install with: python3 -m pip install -r requirements-semantic.txt", file=sys.stderr)
        return 1

    def say(msg: str) -> None:
        if args.explain:
            print(f"  · {msg}")

    repo = Path(args.repo) if args.repo else find_repo_root(Path.cwd())
    db_file = Path(args.db) if args.db else index_path(repo)
    model_dir = Path(args.model) if args.model else model_path()
    if not db_file.is_file():
        print(f"no index at {db_file}\nbuild it first: python3 staticsight.py --repo {repo} index build", file=sys.stderr)
        return 1
    if not (model_dir / "tokenizer.json").is_file():
        print(f"no model at {model_dir}\ndownload it first: staticsight model download", file=sys.stderr)
        return 1
    say(f"index: {db_file}")
    say(f"model: {model_dir}")

    # ----------------------------------------------------------------------- step 1: text -> token ids
    # The tokenizer splits text into sub-word pieces the model knows, e.g. "CreateFileW" -> "Create", "File", "W".
    tok = Tokenizer.from_file(str(model_dir / "tokenizer.json"))
    enc = tok.encode(args.query)
    ids = enc.ids[:512]  # StaticSight caps inputs at 512 tokens
    say(f"step 1 tokenize: {len(ids)} tokens -> {enc.tokens[:12]}{' …' if len(enc.tokens) > 12 else ''}")

    # ----------------------------------------------------------------------- step 2: token ids -> one vector
    # The ONNX model returns one 768-number vector per token; averaging them (mean pooling) gives one vector for the
    # whole text, and scaling it to length 1 (L2 normalisation) makes "dot product" equal "cosine similarity".
    ort.set_default_logger_severity(3)
    opts = ort.SessionOptions()
    opts.log_severity_level = 3
    onnx = next(p for p in (model_dir / "onnx/model_quantized.onnx", model_dir / "onnx/model.onnx") if p.is_file())
    t = time.time()
    session = ort.InferenceSession(str(onnx), opts, providers=["CPUExecutionProvider"])
    input_ids = np.array([ids], dtype=np.int64)
    hidden = session.run(None, {"input_ids": input_ids, "attention_mask": np.ones_like(input_ids)})[0]
    q = hidden[0].mean(axis=0)
    q = q / np.linalg.norm(q)
    say(f"step 2 embed: model output {hidden.shape} -> query vector of {q.shape[0]} numbers "
        f"(first 4: {[round(float(x), 3) for x in q[:4]]}) in {time.time() - t:.2f}s")

    # ----------------------------------------------------------------------- step 3: load the index
    # Every chunk (function, class, doc section, config window) was embedded the same way when the index was built.
    # Vectors are stored once per distinct text (content-addressed by text_hash) as float32 blobs.
    t = time.time()
    db = sqlite3.connect(f"file:{db_file}?mode=ro", uri=True)
    rows = db.execute(
        "SELECT c.path, c.start_line, c.end_line, c.language, c.kind, c.symbol, v.vector "
        "FROM chunks c JOIN vectors v ON v.text_hash = c.text_hash"
    ).fetchall()
    if not rows:
        print("the index is empty; run `staticsight index build`", file=sys.stderr)
        return 1
    matrix = np.frombuffer(b"".join(r[6] for r in rows), dtype="<f4").reshape(len(rows), -1)
    say(f"step 3 load: {len(rows)} chunks x {matrix.shape[1]} dims ({matrix.nbytes / 1e6:.0f} MB) in {time.time() - t:.2f}s")

    # ----------------------------------------------------------------------- step 4: compare and rank
    # One matrix-vector product gives the cosine similarity of the query with every chunk at once.
    t = time.time()
    scores = matrix @ q
    best = np.argsort(-scores)[: args.top]
    say(f"step 4 rank: scored {len(rows)} chunks in {(time.time() - t) * 1000:.0f} ms; showing top {args.top}")
    if args.explain:
        print()

    print(f'results for "{args.query}":')
    for i in best:
        path, start, end, language, kind, symbol = rows[i][:6]
        print(f"  {scores[i]:.2f}  {path}:{start}-{end}  {kind} {symbol}  ({language})")
    if args.explain:
        print("\n  Scores are cosine similarity: 1.0 = same meaning, ~0 = unrelated. Try rephrasing the question,")
        print("  searching for a concept instead of a name, or compare with: staticsight search \"<query>\"")
    return 0


if __name__ == "__main__":
    sys.exit(main())
