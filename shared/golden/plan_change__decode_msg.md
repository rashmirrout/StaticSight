### 🗺️ CHANGE PLAN: `decode_msg` (add a length parameter)
_Code graph up to date (28 files)._
**Target:** `decode_msg` (`src/net/proto.cpp:16`) · returns `int`

**Steps**
1. [ ] Edit the definition: `src/net/proto.cpp:16`
2. [ ] Update the declaration: `src/net/proto.hpp:6`
3. [ ] Update 1 call site in 1 file: `tests/test_proto.cpp` L9
4. [ ] Mirror the change in counterparts: `encode_msg` (`src/net/proto.cpp:5`)
5. [ ] Expect a rebuild of `src/net/proto.hpp` includers: 2 files include it directly (`get_include_blast_radius("src/net/proto.hpp")` for the full list)
6. [ ] Run the tests that reach it: `TEST(Proto,RoundTrip)` (`tests/test_proto.cpp:5`)

**Risks**
- 1 earlier fix touched it: `c945b10` fix: crash on null buffer in decode_msg. Do not undo it.
- 1 caller ignores the `int` result: new error values will go unnoticed there.

_After editing: `check_my_edit()` for a quick check, then `review_changes()` before committing._
