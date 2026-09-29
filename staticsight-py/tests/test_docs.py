"""The documentation's links resolve (docs/check_docs.py; CI also runs the documented commands)."""

import importlib.util

from .conftest import SHARED

_spec = importlib.util.spec_from_file_location("check_docs", SHARED.parent / "docs" / "check_docs.py")
check_docs = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(check_docs)


def test_every_documentation_link_resolves():
    assert check_docs.check_links() == []


def test_link_checker_catches_broken_links_and_anchors(tmp_path):
    (tmp_path / "a.md").write_text("# Title\n## 3. Make a `short` command\n[ok](b.md#hello-world) [x](missing.md) "
                                   "[y](b.md#nope) [z](#3-make-a-short-command) `[code](ignored.md)`\n"
                                   '<img src="b.md" alt="ok"> <img src="gone.png" alt="x">\n')
    (tmp_path / "b.md").write_text("## Hello, world!\n```bash\n# not a heading\n```\n")
    errors = check_docs.check_links([tmp_path / "a.md"])
    assert len(errors) == 3
    assert "broken link missing.md" in errors[0] and "missing anchor #nope" in errors[1]
    assert "broken link gone.png" in errors[2]


def test_documented_commands_are_found():
    cmds = [c for _, _, c in check_docs.documented_commands()]
    assert "staticsight doctor" in cmds and any(c.startswith("staticsight tool review_changes") for c in cmds)
    assert check_docs.expected_exit("staticsight tool x   # exit 2") == 2
    assert check_docs.expected_exit("staticsight doctor") == 0


def test_navigation_is_up_to_date():
    """Breadcrumbs, 'On this page' and previous/next links match the pages (python3 docs/make_nav.py)."""
    import subprocess
    import sys

    r = subprocess.run([sys.executable, str(SHARED.parent / "docs" / "make_nav.py"), "--check"], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
