You are planning a refactor in a C++ code base that may not compile locally. Nothing should be edited until the
plan is complete and every affected place is known. Use the StaticSight tools and cite `file:line`. {symbol} {change}

## Workflow
1. `plan_change` on the function (describe the change in `change`): the ordered checklist of the definition,
   declarations, overrides, call sites by file, counterparts, header includers, tests and risks.
2. `get_impact` for callers several levels deep, and `get_type_hierarchy` if the function is virtual or the type
   is a base class.
3. `get_symbol_contract` for the obligations the refactor must keep (preconditions, ownership, pairing, locking).
4. If a struct or class layout changes: `track_struct_risks` (memcpy, sizeof, casts, network or disk I/O) and
   `get_include_blast_radius` for its header.
5. If locking changes: `get_lock_graph` and `track_lock_order` for the module.
6. `find_related_tests` for the tests to run, and to decide whether a test must be written first.
7. After each edit: `check_my_edit`, then `verify_finding` on anything it reports. Before committing:
   `review_changes`.

## Reporting
Produce the plan as ordered, small steps that each keep the code building and the tests passing, with every place
to change (`file:line`), the tests to run after each step, and the risks with how to check them. Call out anything
the tools cannot see (function pointers, macros, code generated at build time). End with a clear recommendation.
