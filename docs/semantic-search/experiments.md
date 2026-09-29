<!-- nav:top -->
📚 [Documentation](../README.md) › [Semantic search](README.md) › **Learn and experiment**
<!-- /nav:top -->

# Learn and experiment

StaticSight is open source, and semantic search is small enough to understand completely. This page gives you three ways
to look inside: a standalone script that explains every step, SQL queries against the index, and experiments to try.

<!-- nav:toc -->
**On this page:** [1. scripts/semantic_query.py: semantic search in about 150 lines](#1-scriptssemantic_querypy-semantic-search-in-about-150-lines) · [2. Explore the index with SQL](#2-explore-the-index-with-sql) · [3. Things to try](#3-things-to-try) · [4. Read the source](#4-read-the-source)
<!-- /nav:toc -->

## 1. `scripts/semantic_query.py`: semantic search in about 150 lines

`scripts/semantic_query.py` answers a question from an existing index using only:
- the SQLite file;
- the ONNX model;
- `onnxruntime`, `tokenizers` and `numpy`.

It has no StaticSight imports, so you can read and change every step. It finds the index the same way StaticSight
does: `.staticsight/semantic.db` in the repository around the current folder, or `--repo PATH`, or `--db FILE`.

```text
cd /path/to/your/repo
python3 $SS_HOME/scripts/semantic_query.py "retry with backoff" --explain
```

Real output on the test repository:

```text
  · index: /tmp/cpp-sample/.staticsight/semantic.db
  · model: /root/.cache/staticsight/models/jina-code/516f4baf13dec4ddddda8631e019b5737c8bc250
  · step 1 tokenize: 5 tokens -> ['<s>', 'retry', 'Ġwith', 'Ġbackoff', '</s>']
  · step 2 embed: model output (1, 5, 768) -> query vector of 768 numbers (first 4: [0.006, 0.005, -0.062, 0.066]) in 0.45s
  · step 3 load: 48 chunks x 768 dims (0 MB) in 0.00s
  · step 4 rank: scored 48 chunks in 0 ms; showing top 1

results for "retry with backoff":
  0.82  tools/retry.py:6-7  function retry_with_backoff  (python)
```

And on NMAgent (3,230 files):

```text
  · step 1 tokenize: 9 tokens -> ['<s>', 'check', 'Ġif', 'Ġa', 'Ġwindows', 'Ġservice', 'Ġis', 'Ġinstalled', '</s>']
  · step 2 embed: model output (1, 9, 768) -> query vector of 768 numbers ...
  · step 3 load: 61944 chunks x 768 dims (190 MB) in 1.21s
  · step 4 rank: scored 61944 chunks in 18 ms; showing top 5
results for "check if a windows service is installed":
  0.68  src/V2NMAgent/Core/NetSetupWrapper.cpp:1485-1516  function CheckIfServiceStopped  (cpp)
  0.62  src/V2NMAgent/NmAgentPfCheck/inc/NMAgentPfCheckHelpers.h:191-205  function IsPFServiceRunning  (cpp)
```

What each step teaches:
1. **Tokenize.** The model reads sub-word tokens, not words (`Ġ` marks a leading space). Code identifiers split into
   pieces the model has seen in training, which is why `OpenSCManagerW`-style names still carry meaning.
2. **Embed.** The model outputs one vector per token; averaging them (mean pooling) and scaling to length 1 gives one
   vector for the whole question.
3. **Load.** The whole index is one matrix: one row per chunk. 62,000 chunks take 190 MB of memory as float32.
4. **Rank.** Because all vectors have length 1, the cosine similarity is just a dot product. Scoring every chunk is a
   single matrix-vector product, which takes milliseconds.

The script needs only the three packages: `python3 -m pip install -r requirements-semantic.txt`, or use the Python
that runs StaticSight.

## 2. Explore the index with SQL

The index is a normal SQLite file (schema in `shared/semantic/schema.sql`). Open it with the `sqlite3` shell or any
SQLite browser, from the repository root:

```text
sqlite3 .staticsight/semantic.db
```

Useful queries:

```sql
-- what is indexed, by language
SELECT language, COUNT(*) AS chunks FROM chunks GROUP BY language ORDER BY chunks DESC;

-- the biggest files, by number of chunks
SELECT path, COUNT(*) AS chunks FROM chunks GROUP BY path ORDER BY chunks DESC LIMIT 10;

-- how a file was cut into chunks
SELECT start_line, end_line, kind, symbol FROM chunks WHERE path = 'src/router.cpp' ORDER BY start_line;

-- how much space the vectors take
SELECT COUNT(*) AS vectors, SUM(LENGTH(vector)) / 1048576.0 AS mb FROM vectors;

-- files that were skipped, and why (binary, minified, too large, …)
SELECT path, status FROM files WHERE status LIKE 'skipped%';

-- index metadata: model, schema and chunker versions, last HEAD
SELECT key, value FROM meta;
```

Column names can be checked with `.schema` in the `sqlite3` shell. Don't edit the file while StaticSight is running;
deleting it is always safe (it is rebuilt).

## 3. Things to try

- **Rephrase the same question** three ways and compare the top results. Which words matter?
- **Search for a concept, not a name**: "free the buffer on every error path", "convert to network byte order".
- **Use `--top 20`** and watch where the scores drop. That drop is roughly where relevance ends.
- **Compare with `staticsight search`**, which adds the keyword pass, grouping, filters and excerpts. Find a question
  where keyword fusion rescues a result the model ranked low (exact API names are good candidates).
- **Try `similar` on a function you just fixed** to find its copy-paste twins. This is how `review_changes` finds
  "Similar code elsewhere".
- **Look at what gets embedded**: the index stores only a hash of each chunk's text, not the text. The embedded text
  is `path | kind name | signature` followed by the code, which is why file and function names help ranking. Rebuild
  that header for the top result from the `chunks` columns (`path`, `kind`, `symbol`, `signature`) and embed it alone
  with the script's model code to see how much the header contributes.
- **Measure**: time `staticsight index refresh` after touching one file, then after editing one function. Only
  the edited function is re-embedded.

## 4. Read the source

| To understand | Read |
|---|---|
| Which files are indexed and how they are classified | `staticsight-py/src/staticsight/semantic/files.py`, `shared/semantic/languages.json` |
| How files are cut into chunks | `staticsight-py/src/staticsight/semantic/chunker.py` |
| The model, download and verification | `staticsight-py/src/staticsight/engines/embedder.py`, `shared/semantic/models.json` |
| Storage | `staticsight-py/src/staticsight/engines/vector_store.py`, `shared/semantic/schema.sql` |
| Freshness and refresh | `staticsight-py/src/staticsight/semantic/index.py` (`ensure_fresh`, `refresh`) |
| Ranking and output | `staticsight-py/src/staticsight/semantic/search.py` |

The TypeScript twins are in `staticsight-ts/src/semantic/` and `staticsight-ts/src/engines/`, and produce identical output.

---

<!-- nav:bottom -->
| ⬅️ [Internals](internals.md) | 📚 [Documentation](../README.md) | [MCP tool reference](../MCP_TOOLS.md) ➡️ |
|:---|:---:|---:|
<!-- /nav:bottom -->
