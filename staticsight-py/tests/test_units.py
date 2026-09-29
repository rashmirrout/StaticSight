from staticsight.core import md
from staticsight.core.cpp_text import extract_leading_comment, strip_code
from staticsight.engines.ctags import Tag, innermost
from staticsight.engines.git import parse_diff
from staticsight.tools.graph_gtags import _GLOBAL_LINE, classify_call, normalize_symbol
from staticsight.tools.state_mutation import _access_kind
from staticsight.engines.cppcheck import parse_cppcheck_xml
from staticsight.core.errors import InvalidArgument
import pytest


def test_strip_code_preserves_columns_and_blanks_comments_strings():
    src = ['int a = 1; // if (x) return;', 'const char* s = "if (y) { return; }";', "/* start", "return; */ int b;",
           "auto r = R\"(if (z) return;)\";", "int n = 1'000'000; char c = '{';"]
    out = strip_code(src)
    assert [len(x) for x in out] == [len(x) for x in src]
    assert "return" not in out[0] and "int a = 1;" in out[0]
    assert "return" not in out[1] and out[1].count('"') == 2
    assert out[2].strip() == "" and out[3].strip() == "int b;"
    assert "return" not in out[4]
    assert "{" not in out[5] and "1'000'000" in out[5]


def test_leading_comment_doxygen_and_line_comments():
    lines = ["/**", " * @brief Hi.", " * @pre x > 0", " */", "template <class T>", "int f(T x);", "", "// one", "// two", "void g();"]
    assert extract_leading_comment(lines, 5) == ["@brief Hi.", "@pre x > 0"]
    assert extract_leading_comment(lines, 9) == ["one", "two"]
    assert extract_leading_comment(["int x; ///< the x"], 0) == ["the x"]
    assert extract_leading_comment(["int y;", "int z;"], 1) == []


def test_parse_diff_hunks_renames_deletes():
    text = """diff --git a/a.cpp b/a.cpp
index 1..2 100644
--- a/a.cpp
+++ b/a.cpp
@@ -3,0 +4,2 @@ ctx
+x
+y
@@ -10 +11,0 @@
-z
diff --git a/old.h b/new.h
similarity index 90%
rename from old.h
rename to new.h
diff --git a/gone.cpp b/gone.cpp
deleted file mode 100644
--- a/gone.cpp
+++ /dev/null
@@ -1,2 +0,0 @@
-a
-b
diff --git a/img.png b/img.png
Binary files a/img.png and b/img.png differ
"""
    files = {f.path: f for f in parse_diff(text)}
    a = files["a.cpp"]
    assert a.added_lines == {4, 5} and a.removed_at == {11: 1} and (a.additions, a.deletions) == (2, 1)
    assert files["new.h"].status == "renamed" and files["new.h"].old_path == "old.h"
    assert files["gone.cpp"].status == "deleted" and files["gone.cpp"].deletions == 2
    assert files["img.png"].binary


def test_md_helpers():
    assert md.compress_ranges([1, 2, 3, 7, 9, 10]) == "L1-3, L7, L9-10"
    items = md.truncate_list([str(i) for i in range(20)], 15, "hits", "narrow it")
    assert len(items) == 16 and items[-1] == "_…and 5 more hits. narrow it_"
    text = "```cpp\n" + "x\n" * 100 + "```"
    cut = md.enforce_budget(text, 60)
    assert cut.count("```") % 2 == 0 and "truncated" in cut
    assert md.code_span("a`b") == "`` a`b ``"


def test_innermost_prefers_tightest_scope():
    tags = [Tag("ns", "namespace", 1, 100, "f"), Tag("C", "class", 5, 50, "f"), Tag("m", "function", 10, 20, "f", scope="C")]
    assert innermost(tags, 15).qualified == "C::m"
    assert innermost(tags, 30).name == "C"
    assert innermost(tags, 200) is None


def test_global_line_regex():
    m = _GLOBAL_LINE.match("process_packet     17 src/net/listener.cpp             router_->process_packet(&batch[i]);")
    assert m and m.group(2) == "17" and m.group(3) == "src/net/listener.cpp"


def test_classify_call():
    assert classify_call("    router_->process_packet(&x);", "process_packet") == "⚠️ result ignored"
    assert classify_call("    int rc = r.process_packet(&x);", "process_packet") == "result used"
    assert classify_call("    if (process_packet(&x) != 0) {", "process_packet") == "result used"
    assert classify_call("    (void)process_packet(&x);", "process_packet") == "result explicitly discarded"
    assert classify_call("    cb = &Router::process_packet;", "process_packet") == "referenced (address/callback)"


def test_access_kind():
    assert _access_kind("count = 1;", "count") == "write"
    assert _access_kind("count += 2;", "count") == "write"
    assert _access_kind("++this->count;", "count") == "write"
    assert _access_kind("if (count == 1)", "count") == "read"
    assert _access_kind("items.push_back(x);", "items") == "mutating call"
    assert _access_kind("foo(&count);", "count") == "address taken"


def test_normalize_symbol_rejects_injection():
    assert normalize_symbol("Router::process_packet") == "process_packet"
    assert normalize_symbol("f()") == "f"
    for bad in ("-rf", "a b", "x;rm", ""):
        with pytest.raises(InvalidArgument):
            normalize_symbol(bad)


def test_parse_cppcheck_xml():
    xml = """<?xml version="1.0"?><results version="2"><cppcheck version="2.18.3"/><errors>
<error id="memleak" severity="error" msg="Memory leak: b" cwe="401"><location file="src/a.cpp" line="13" column="1"/></error>
<error id="missingInclude" severity="information" msg="x"><location file="src/a.cpp" line="1"/></error>
<error id="nullPointer" severity="warning" msg="Null" cwe="476"><location file="src/b.h" line="3"/></error>
<error id="syntaxError" severity="error" msg="bad"><location file="src/a.cpp" line="2"/></error>
</errors></results>"""
    findings, elsewhere, version, parse_problem, _macros = parse_cppcheck_xml(xml, "src/a.cpp")
    assert [f.id for f in findings] == ["memleak"] and elsewhere == 1 and version == "2.18.3" and parse_problem


# ------------------------------------------------------------------------------------------------ lock recognition
def test_lock_events_match_the_shared_table():
    """shared/golden/lock_events.json: the same expectations run in the TypeScript suite."""
    import json

    from staticsight.core.locks import line_events

    from .conftest import SHARED

    for code, want in json.loads((SHARED / "golden" / "lock_events.json").read_text()):
        got = [[e.op, e.kind, list(e.mutexes), e.scoped] for e in line_events(code)]
        assert got == want, code


def test_lock_walker_branches_and_scopes():
    from staticsight.core.locks import LockWalker

    body = ["void f() {", "  if (x) {", "    a.lock();", "  } else {", "    a.lock();", "  }",
            "  { std::lock_guard<std::mutex> g(b); }", "  c.lock();", "}"]
    seen = []
    w = LockWalker()
    for n, code in enumerate(body, 1):
        w.step(code, n, lambda e, held: seen.append((e.mutexes, [h.mutexes for h in held])))
    # the else-branch lock does not see the if-branch one; `c` sees neither the branch locks nor the closed guard
    assert seen == [(("a",), []), (("a",), []), (("b",), []), (("c",), [])]


def test_guarded_acquisitions_are_conditional():
    from staticsight.tools.lock_order import _conditional

    body = ["void Helper(bool a) {", "  if (a) AcquireSRWLockExclusive(&m_lock);", "  if (b)", "    m.lock();",
            "  AcquireSRWLockShared(&m_lock);", "}"]
    assert _conditional(body, 2, body[1].index("Acquire"))
    assert _conditional(body, 4, body[3].index("m.lock"))
    assert not _conditional(body, 5, body[4].index("Acquire"))
