---
applyTo: "**/*.{c,cc,cpp,cxx,c++,h,hh,hpp,hxx,h++,inl,ipp,tpp}"
---

# Use StaticSight for C/C++ context

When the StaticSight MCP server is available (tools such as `review_changes`, `get_diff_scopes`,
`get_upstream_callers`, `get_branch_skeleton`, `track_struct_risks`, `get_include_blast_radius`,
`track_state_mutations`, `track_lock_order`, `run_file_static_audit`, `get_symbol_contract`; they may have a `staticsight-` prefix):

- Prefer these tools over guessing from open files or reading whole files. The repository may not compile.
- For reviews or "what could break?" questions, start with `review_changes`, then follow the `staticsight-cpp-review` skill.
- Before changing a function's signature, return values or error handling, call `get_upstream_callers`.
- Before changing a struct/class data member, call `track_struct_risks`. Before changing a header, call `get_include_blast_radius`.
- Before touching shared state or locks, call `track_state_mutations`; when adding or reordering locks, or calling other
  code while holding one, call `track_lock_order` to check for lock-order inversions.
- After editing a .c/.cpp file, run `run_file_static_audit(file, only_changed_lines=true)` and fix any new errors.
- To find code by intent in any language ("where do we …?"), use `semantic_search`; after a git pull or big edits,
  call `refresh_semantic_index` first. Use `find_similar_code` to check copy-paste twins of code you change.
- Cite evidence as `file:line`. Treat results marked heuristic as leads to verify, not proof.
