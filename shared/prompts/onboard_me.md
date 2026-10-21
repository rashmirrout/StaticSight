You are helping a developer understand an unfamiliar area of a C++ code base that may not compile locally. Use the
StaticSight tools to build an accurate map; cite `file:line` for everything. {area}

## Workflow
1. Find the area: `semantic_search` with a description of what it does, then `query_graph` with
   `definitions of NAME` or `members of CLASS` for the main types.
2. Structure: `get_type_hierarchy` for the main classes, `query_graph` with `includers of HEADER` for how widely
   the headers are used.
3. Entry points and flow: `find_entry_paths` for the central functions (which threads, callbacks and program
   entry points reach them), `get_impact` with `direction="callees"` for what they depend on.
4. Concurrency: `get_lock_graph` for the module's locks and who takes them.
5. Where the risk is: `get_change_hotspots` for the module (frequent changes and bug fixes) and
   `find_related_tests` for how well the central functions are tested.
6. For the two or three most important functions: `get_context_pack`.

## Reporting
Write a short guide: what the area does, its main types and how they relate, how requests or events flow through it
(entry point to effect, with `file:line`), its threads and locks, where it is fragile, and which tests cover it.
Finish with the five files to read first and why.
