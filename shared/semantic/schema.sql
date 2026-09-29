-- StaticSight semantic index (shared by the Python and TypeScript implementations; either can build or query it).
-- Bump meta.schema_version in both implementations when this file changes; a mismatch triggers a rebuild.
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
-- One row per file seen by the indexer (indexed or skipped).
CREATE TABLE IF NOT EXISTS files (
  path     TEXT PRIMARY KEY,           -- workspace-relative, '/' separators
  size     INTEGER NOT NULL,
  mtime_ns TEXT NOT NULL,              -- text: nanosecond mtimes exceed JavaScript's safe integer range
  sha1     TEXT NOT NULL,              -- of the raw bytes
  language TEXT NOT NULL,
  status   TEXT NOT NULL,              -- 'indexed' | 'skipped:<reason>'
  chunks   INTEGER NOT NULL DEFAULT 0
);
-- One row per embedded chunk (a function/class/section/window).
CREATE TABLE IF NOT EXISTS chunks (
  id         INTEGER PRIMARY KEY,
  path       TEXT NOT NULL,
  start_line INTEGER NOT NULL,
  end_line   INTEGER NOT NULL,
  language   TEXT NOT NULL,
  kind       TEXT NOT NULL,            -- function | class | struct | section | window | file | ...
  symbol     TEXT NOT NULL,            -- qualified name or heading ('' for windows)
  signature  TEXT NOT NULL,
  part       INTEGER NOT NULL,         -- 0.. for long units split into windows
  text_hash  TEXT NOT NULL             -- sha1(model id + NUL + embedded text); key into vectors
);
CREATE INDEX IF NOT EXISTS chunks_path ON chunks(path);
CREATE INDEX IF NOT EXISTS chunks_hash ON chunks(text_hash);
-- Vectors are content-addressed, so moved or duplicated code is embedded once.
CREATE TABLE IF NOT EXISTS vectors (
  text_hash TEXT PRIMARY KEY,
  vector    BLOB NOT NULL              -- float32 little-endian, L2-normalised
);
