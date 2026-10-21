-- StaticSight code graph (shared by the Python and TypeScript implementations; either can build or query it).
-- Built per file from Universal Ctags (definitions, class hierarchy) and comment/string-stripped source text (calls,
-- function references, includes). Calls are stored by callee NAME and resolved to definitions when queried, so a file
-- can be re-parsed alone without touching the rows of other files.
CREATE TABLE IF NOT EXISTS meta (
  key   TEXT PRIMARY KEY,
  value TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS files (
  path     TEXT PRIMARY KEY,
  size     INTEGER NOT NULL,
  mtime_ns TEXT NOT NULL,
  sha1     TEXT NOT NULL
);
-- One row per definition/declaration ctags reports (function, prototype, class, struct, union, enum, enumerator,
-- member, typedef, macro).
CREATE TABLE IF NOT EXISTS defs (
  path       TEXT NOT NULL,
  name       TEXT NOT NULL,     -- short name
  qualified  TEXT NOT NULL,     -- Class::name
  kind       TEXT NOT NULL,
  line       INTEGER NOT NULL,
  end_line   INTEGER NOT NULL,
  scope      TEXT NOT NULL,
  scope_kind TEXT NOT NULL,     -- class | struct | union | namespace | ...
  signature  TEXT NOT NULL,
  typeref    TEXT NOT NULL,
  inherits   TEXT NOT NULL,     -- comma-separated base classes
  properties TEXT NOT NULL      -- virtual, pure, override, static, ...
);
CREATE INDEX IF NOT EXISTS defs_name ON defs(name);
CREATE INDEX IF NOT EXISTS defs_path ON defs(path);
-- One row per call site or function reference inside a function body.
CREATE TABLE IF NOT EXISTS calls (
  path        TEXT NOT NULL,
  caller      TEXT NOT NULL,     -- qualified name of the enclosing function
  caller_line INTEGER NOT NULL,  -- its first line (disambiguates overloads)
  callee      TEXT NOT NULL,     -- short name called
  qualifier   TEXT NOT NULL,     -- `Class` in Class::f(), the object in obj.f() / p->f(), else ''
  how         TEXT NOT NULL,     -- call | member | qualified | ref (address taken) | thread (started as a thread/callback)
  line        INTEGER NOT NULL,
  code        TEXT NOT NULL,     -- the stripped source line (for result used / ignored)
  text        TEXT NOT NULL      -- the source line, clipped
);
CREATE INDEX IF NOT EXISTS calls_callee ON calls(callee);
CREATE INDEX IF NOT EXISTS calls_caller ON calls(caller);
CREATE INDEX IF NOT EXISTS calls_path ON calls(path);
CREATE TABLE IF NOT EXISTS includes (
  path   TEXT NOT NULL,
  line   INTEGER NOT NULL,
  target TEXT NOT NULL           -- as written between the quotes/brackets
);
CREATE INDEX IF NOT EXISTS includes_path ON includes(path);
