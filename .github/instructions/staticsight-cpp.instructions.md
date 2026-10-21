---
applyTo: "**/*.{c,cc,cpp,cxx,c++,h,hh,hpp,hxx,h++,inl,ipp,tpp}"
---

# Use StaticSight for C/C++ context

When the StaticSight MCP server is available (tools such as `review_changes`, `check_my_edit`, `plan_change`,
`get_impact`, `get_context_pack`, `get_upstream_callers`, `get_branch_skeleton`, `track_struct_risks`,
`get_include_blast_radius`, `track_state_mutations`, `track_lock_order`, `run_file_static_audit`,
`get_symbol_contract`, `verify_finding`; they may have a `staticsight-` prefix):

- Prefer these tools over guessing from open files or reading whole files. The repository may not compile.
- For reviews or "what could break?" questions, start with `review_changes`, then follow the `staticsight-cpp-review` skill.
- Before changing a function, call `plan_change(symbol, change=…)`; for its signature, return values or error
  handling, `get_impact` shows callers several levels deep. `get_context_pack` gives everything about one function in one call.
- Before changing a struct/class data member, call `track_struct_risks`. Before changing a header, call `get_include_blast_radius`.
- Before touching shared state or locks, call `track_state_mutations`; when adding or reordering locks, or calling other
  code while holding one, call `track_lock_order` to check for lock-order inversions.
- After each edit, run `check_my_edit()` and fix what it reports (leaks on exit paths, cppcheck errors, callers with
  the old signature, missing switch cases, platform twins left unchanged).
- Before reporting a finding that has an ID (like `F7a0cc5`), run `verify_finding` on it.
- To find code by intent in any language ("where do we …?"), use `semantic_search`; after a git pull or big edits,
  call `refresh_semantic_index` first. Use `find_similar_code` to check copy-paste twins of code you change.
- Cite evidence as `file:line`. Treat results marked heuristic as leads to verify, not proof.
