<!-- nav:top -->
📚 [Documentation](../README.md) › 📖 [The book](00-preface.md) › **Chapter 7: Semantic search**
<!-- /nav:top -->

# 7. Semantic search

The review tools answer questions about names: "who calls `process_packet`?" Many questions in a review, or when
learning a code base, are about **meaning** instead: "where do we retry failed connections?", "is there another
function that copies packets like this one?" You don't know the name, so you can't grep for it. This chapter
explains how StaticSight answers such questions offline, and how it keeps the answer fresh without git hooks.
The practical guide is in [semantic-search/](../semantic-search/README.md).

## From text to numbers

An **embedding model** is a neural network that turns a piece of text into a fixed-length list of numbers, a
**vector**, such that texts with similar meanings get vectors that point in similar directions. StaticSight uses
`jina-embeddings-v2-base-code`, a model trained on code in about 30 programming languages and on English, which
produces 768 numbers per text.

The similarity of two vectors is measured by the **cosine**: 1.0 means the same direction (same meaning), around 0
means unrelated. If every vector is scaled to length 1 first, the cosine is just the sum of the products of their
numbers (a dot product), which computers do very fast.

So semantic search is, in essence:
1. Cut the repository into pieces (**chunks**) and compute a vector for each, once.
2. Compute a vector for the question.
3. Return the chunks whose vectors are closest to the question's.

The model runs locally with ONNX Runtime on the CPU: no GPU, no PyTorch, no server, no network after the first
download. The model file is pinned to an exact revision and verified with sha256.

## Cutting code into chunks

What counts as a "piece" matters a lot. A whole file mixes many ideas; a single line has too little meaning.
StaticSight uses the structure of the code:

- For languages Universal Ctags understands (C/C++, C#, Java, Python, Go, Rust, JavaScript/TypeScript, PowerShell,
  shell, about 35 in total): **one chunk per innermost function, method or class**, with the comment directly above it.
  The parts of a class or file between functions (fields, includes, `#define`s, globals) become "gap" chunks.
- Markdown: **one chunk per heading section**.
- Everything else (XML, JSON, YAML, INI, plain text): **windows** of lines.
- Anything longer than 1,200 characters is split into overlapping windows (2 lines of overlap), still labelled with the
  function's name.

Each chunk's text starts with a header, `path | kind name | signature`, followed by the code. The header helps: a
function called `retry_with_backoff` in `tools/retry.py` is easier to find for "retry" than its body alone.

Binary, minified and generated files, lock files, files over 512 KB, and everything ignored by `.gitignore` or
`.staticsightignore` are skipped.

## Storing the index

Vectors and metadata go into one SQLite file, `<repo>/.staticsight/semantic.db`, with four tables: `meta` (model and
version information), `files` (size, timestamp and hash of each file), `chunks` (location, kind, name, signature) and
`vectors`. Vectors are stored once per distinct text, keyed by a hash of the text: code that moves or is duplicated
is embedded only once. The index takes about 4.5 KB per chunk; a 3,000-file repository with 64,000 chunks takes
about 290 MB.

Python and TypeScript use the same schema and produce the same vectors (token ids are identical, and vectors differ by
less than 3 parts in 100 million), so either implementation can build the index and the other can query it.

## Ranking: meaning plus words

Pure semantic similarity has a weakness: an exact identifier such as `OpenSCManagerW` may mean little to the model, yet
it is exactly what the user typed. So every search runs two passes:

1. **Semantic:** the 60 chunks closest to the question's vector.
2. **Keyword:** the question's significant words searched with ripgrep over the same files.

The two ranked lists are combined with **reciprocal-rank fusion**: each result earns `1 / (60 + rank)` from the
semantic list and half that weight from the keyword list, and results are sorted by the sum. A result found by both
passes rises to the top. Finally, chunks of the same function are grouped, so each function appears once.

Every result shows its location, kind, name, score and how it was found (`semantic`, `keyword`, or `semantic+keyword`),
plus a short excerpt:

````text
1. `src/net/socket.cpp:9-12` — function `copy_packet` (cpp) · 0.76 · semantic+keyword
   ```cpp
    9 | void copy_packet(uint8_t* dst, const Packet& pkt) {
   10 |     std::memcpy(dst, &pkt,
   11 |                 sizeof(pkt));
   12 | }
   ```
````

`find_similar_code` uses the code region itself as the question (no keyword pass), and labels results with a cosine
of at least 0.92 as *near-duplicate* and at least 0.85 as *very similar*. `review_changes` uses it to add "Similar code
elsewhere" when a changed function has close twins: the same bug, or the same fix, may belong there too.

## Freshness without git hooks

An index that describes last week's code gives wrong answers with confidence. The usual fix is a git hook or a file
watcher; StaticSight uses neither, because both modify or monitor the user's environment. Instead, **every semantic
call checks for drift** before answering:

1. List the files (`rg --files`, milliseconds even for thousands of files) and compare each file's size and
   modification time with the index. Only files whose timestamp changed are read and hashed.
2. If up to 200 files changed, re-embed their changed chunks **now**, then answer. Content hashes mean that a file that
   was only touched, or a function that did not change, costs nothing.
3. If more changed (after a big pull), start a refresh **in the background** and answer from the current index, saying
   that it is stale.
4. If there is no index yet, start building it in the background and answer with keyword-only results meanwhile. Code
   files are embedded first, so the partial index is useful early.

The answer always states which case applied (`Index is up to date.`, `Refreshed before searching: …`, or a warning), so
the agent can tell the user how fresh the evidence is. A lock file with a heartbeat stops two processes from
refreshing the same index at once. From the command line, where a process exits after one answer, refreshes always
run in the foreground.

## Costs

| Operation | Measured |
|---|---|
| First build, 3,230 files, 64.6k chunks, 16-thread CPU | 54 minutes, in the background, peak 1.5 GB of memory |
| Refresh with no changes (3.3k files scanned) | 1.8 s |
| Scoring 64k chunks for one question | 10-20 ms |
| A fresh command-line search (loading model and index) | 3.5 s |

The first build is the only expensive step. The MCP server keeps model and index loaded, so repeated questions answer
in well under a second.

## What semantic search is not

Similarity is not proof. A high score means "this code talks about the same thing", not "this code has the bug". The
output ends with a reminder to verify, and the review skill tells the agent to confirm candidates with the precise
tools (callers, skeletons, audits) before asserting anything.

---

<!-- nav:bottom -->
| ⬅️ [The review tools in depth](06-review-tools-in-depth.md) | 📚 [Documentation](../README.md) | [Cross-platform](08-cross-platform.md) ➡️ |
|:---|:---:|---:|
<!-- /nav:bottom -->
