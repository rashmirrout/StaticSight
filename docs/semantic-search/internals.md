<!-- nav:top -->
📚 [Documentation](../README.md) › [Semantic search](README.md) › **Internals**
<!-- /nav:top -->

# Semantic search internals

This is the reference for how semantic search is built: chunking, the model, ranking, storage, configuration and
performance. For day-to-day use read the [manual guide](manual-guide.md); for what happens inside a tool call read
[the MCP flow](mcp-flow.md).

<!-- nav:toc -->
**On this page:** [How it works](#how-it-works) · [Storage](#storage) · [Configuration](#configuration) · [Performance](#performance) · [Limitations](#limitations)
<!-- /nav:toc -->

## How it works

```
files ── rg --files (all files, .gitignore + excludes) ── classify (language, skip binary/minified/too-large/lock files)
  │
  ├─ structural languages (C/C++, C#, Java, Python, Go, Rust, JS/TS, PowerShell, shell, … ~35 via Universal Ctags)
  │     → one chunk per innermost function/method/class; container "gaps" (members, fields); file-level gaps
  │       (includes, #defines, globals); leading doc comments attached to their unit
  ├─ Markdown → one chunk per heading section
  └─ everything else (XML, JSON, YAML, INI, text, …) → line windows
  every chunk > 1200 chars → overlapping windows (2-line overlap), still labelled with the unit's name

chunk text = "path | kind qualified::name | signature" + body   ──►  embedding model  ──►  768-dim unit vector
                                                                        │
                                              SQLite (files, chunks, content-addressed vectors)
query ──► embed ──► cosine top-60 ─┐
query ──► keywords ──► rg ─────────┴─► reciprocal-rank fusion (keyword weight 0.5) ──► group by symbol ──► Markdown
```

- **Model:** `jinaai/jina-embeddings-v2-base-code` (Apache-2.0), int8 ONNX (162 MB). It is trained on code in ~30 languages plus
  English, with an 8k context (StaticSight caps chunks at 512 tokens). Revision `516f4baf…` is pinned and every file is
  sha256-verified. Inputs are mean-pooled over the attention mask, then L2-normalised.
- **Runtime:** ONNX Runtime on CPU: Python `onnxruntime` + `tokenizers`, Node `onnxruntime-node` + `@huggingface/tokenizers`.
  No PyTorch, no server, no GPU needed. Verified identical: token ids match exactly, and vectors differ by < 3e-8 between runtimes.
- **Hybrid ranking:** semantic similarity finds intent. The keyword pass (case-insensitive, over the same files) keeps
  exact identifiers such as `OpenSCManagerW` from being missed. Results are fused, so each result says `semantic`,
  `keyword` or `semantic+keyword`.
- **Scores** are cosine similarity (higher is closer). In `find_similar_code`, ≥ 0.92 is labelled near-duplicate and ≥ 0.85 very similar.

## Storage

- **Location:** `<repo>/.staticsight/semantic.db`, next to the GNU Global database (`GTAGS`, `GRTAGS`, `GPATH`). The folder
  holds its own `.gitignore` (`*`), so git never sees it and your `.gitignore` is never edited. Each clone or worktree
  therefore has its own index, and deleting the folder is always safe (it is rebuilt on demand).
- **Other locations:** `STATICSIGHT_DATA_DIR=cache` keeps the data in the per-user cache instead
  (`~/.cache/staticsight/<repo-hash>/`, `%LOCALAPPDATA%\staticsight\<repo-hash>\`); any other value is a folder that
  receives one `<repo-hash>` sub-folder per repository. A read-only repository, or a folder without `.git` that was not
  chosen explicitly, uses the per-user cache automatically. `index status` and `doctor` print where the
  data is and why. Indexes built by older versions in the per-user cache are moved into `.staticsight/` on first use.
- **Schema:** `shared/semantic/schema.sql`, with tables `meta`, `files`, `chunks` and `vectors` (float32 BLOBs keyed by
  `sha1(model + text)`). The index is rebuilt automatically when the schema version, model or chunker version changes.
- **Models:** stored once per user in `<cache>/models/<name>/<revision>/` and shared by all repositories and both
  implementations. The cache is `~/.cache/staticsight` (Linux/macOS, or `$XDG_CACHE_HOME/staticsight`) or
  `%LOCALAPPDATA%\staticsight` (Windows), or `STATICSIGHT_CACHE_DIR`.
- **Size:** about 4.5 KB per chunk: 3 KB of vector (768 × 4-byte floats) plus metadata and SQLite overhead. NMAgent's 64.6k chunks take 289 MB.

## Configuration

| Variable | Default | Meaning |
|---|---|---|
| `STATICSIGHT_DATA_DIR` | `repo` | `repo` = `<repo>/.staticsight/`; `cache` = per-user cache; anything else = a per-repository sub-folder of that folder. |
| `STATICSIGHT_EMBED_MODEL` | `jina-code` | Model from `shared/semantic/models.json` (`test-hash` is the deterministic test embedder). |
| `STATICSIGHT_EMBED_MODEL_DIR` | – | Use a pre-downloaded/offline model folder (any sentence-transformers ONNX export with `tokenizer.json`). |
| `STATICSIGHT_SEMANTIC_ALLOW_DOWNLOAD` | 1 | `0` forbids downloading the model (air-gapped machines). |
| `STATICSIGHT_SEMANTIC_AUTO_REFRESH` | 1 | `0` = never refresh automatically; results are marked stale. |
| `STATICSIGHT_SEMANTIC_AUTO_REFRESH_FILES` | 200 | Largest drift refreshed synchronously before answering; bigger drifts go to the background. |
| `STATICSIGHT_SEMANTIC_MAX_FILE_KB` | 512 | Larger files are skipped (listed in `get_index_status`). |
| `STATICSIGHT_EMBED_THREADS` | 0 (runtime default) | ONNX Runtime intra-op threads. The physical core count is often fastest. |
| `STATICSIGHT_EMBED_BATCH` | 16 | Chunks per inference batch (length-sorted, so padding is minimal). |
| `HF_ENDPOINT` | `https://huggingface.co` | Mirror for the model download. |
| `HTTPS_PROXY` | – | Proxy for the download. Python honours it; Node needs `NODE_USE_ENV_PROXY=1` as well. |

Skipped automatically: binary files (NUL bytes, known binary extensions), minified or generated files (very long lines,
`*.min.js`, `*.pb.*`, `*.designer.cs`, …), lock files (`package-lock.json`, `go.sum`, …), files over the size limit,
and everything ignored by `.gitignore`, `STATICSIGHT_EXCLUDES` or `.staticsightignore`.

## Performance

| Measurement | Result |
|---|---|
| Chunking NMAgent (3,230 indexable files, 12 languages, 64.6k chunks) | 4.3 s, before any embedding |
| Embedding throughput, CPU only | about 20 chunks/s on a 16-thread AMD EPYC 7763 VM with AVX2 and no VNNI. Faster on CPUs with AVX-512 VNNI or AVX-VNNI. |
| First full build (NMAgent, 3,230 files, 64.6k chunks, 63.7k unique vectors) | **54 min** (measured), in the background; peak memory 1.5 GB; index 289 MB. One-time; on CPUs with VNNI it is proportionally faster. |
| Refresh with no changes / after a small change | **1.8 s** (scan 3.3k files, hash only touched ones); 6 changed files re-embedded in a few seconds |
| Query | ~10-20 ms to score 64k chunks; a fresh CLI process takes **3.5 s** in total (loading the model and index). The MCP server keeps both loaded, so repeated queries return in well under a second. |

The first build embeds code files first, then docs, then config/XML/JSON. The partial index is searchable while the
build continues.

## Limitations

- Embeddings capture intent, not proof: verify results (the output says so).
- Languages Universal Ctags cannot bound (no end lines) fall back to line windows. They are still searchable, just less precisely labelled.
- UTF-16 files are decoded and searchable. ctags doesn't parse them, so they are chunked as windows.

---

<!-- nav:bottom -->
| ⬅️ [MCP flow](mcp-flow.md) | 📚 [Documentation](../README.md) | [Learn and experiment](experiments.md) ➡️ |
|:---|:---:|---:|
<!-- /nav:bottom -->
