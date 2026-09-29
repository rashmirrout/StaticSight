"""Platform layer: boundary rule + Windows/POSIX behaviour (the Windows logic is testable on any OS)."""

import os
import re
import sys
from pathlib import Path

import pytest

from staticsight import platform as plat
from staticsight.core.errors import ToolTimeout
from staticsight.core.paths import decode_source, matches_glob, read_lines
from staticsight.engines.gnu_global import parse_x_output
from staticsight.engines.rg import RgResult  # noqa: F401  (import check)
from staticsight.platform.posix import PosixPlatform
from staticsight.platform.windows import WindowsPlatform

SRC = Path(__file__).resolve().parents[1] / "src" / "staticsight"
FORBIDDEN = re.compile(
    r"\bsys\.platform\b|\bos\.name\b|platform\.system\(|^\s*import subprocess|^\s*from subprocess|create_subprocess|"
    r"os\.killpg|signal\.SIG|shutil\.which",
    re.M,
)


def test_os_specific_code_only_in_platform_package():
    offenders = []
    for p in SRC.rglob("*.py"):
        if "platform" in p.relative_to(SRC).parts[:1]:
            continue
        for m in FORBIDDEN.finditer(p.read_text(encoding="utf-8")):
            offenders.append(f"{p.relative_to(SRC)}: {m.group(0).strip()}")
    assert not offenders, "OS-specific code outside staticsight/platform/:\n" + "\n".join(offenders)


def test_detect_matches_host():
    expected = "windows" if sys.platform == "win32" else "posix"
    assert plat.detect().name == expected


def test_windows_path_normalisation_and_case():
    w = WindowsPlatform()
    assert w.to_posix(r"src\net\packet.hpp") == "src/net/packet.hpp"
    assert w.to_posix(r".\src\a.cpp") == "src/a.cpp"
    assert w.same_path("Src/Router.CPP", r"src\router.cpp")
    assert w.fnmatch("SRC/Net/a.cpp", "src/net/*")
    p = PosixPlatform()
    assert p.to_posix(r"odd\name.cpp") == r"odd\name.cpp"  # backslash is a legal POSIX file-name character
    assert not p.same_path("Src/a.cpp", "src/a.cpp")
    assert not p.fnmatch("SRC/a.cpp", "src/*")


def test_windows_executable_lookup_ignores_shell_shims(tmp_path, monkeypatch):
    (tmp_path / "rg.cmd").write_text("@echo off")
    (tmp_path / "ctags.exe").write_bytes(b"MZ")
    monkeypatch.setenv("PATH", str(tmp_path))
    w = WindowsPlatform()
    assert w.find_executable("ctags") == str(tmp_path / "ctags.exe")
    assert w.find_executable("rg") is None  # .cmd shims are refused (would need cmd.exe)


def test_windows_cache_dir_and_hints(monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", r"C:\Users\me\AppData\Local")
    assert str(WindowsPlatform().default_cache_dir()).endswith("staticsight")
    assert "UniversalCtags.Ctags" in WindowsPlatform().install_hint("ctags")
    assert "Exuberant" in WindowsPlatform().install_hint("ctags")


def test_glob_uses_platform_case_rules(monkeypatch):
    plat.use(WindowsPlatform())
    try:
        assert matches_glob("Src/Net/A.cpp", "src/net/*")
        assert matches_glob("src/net/a.cpp", r"src\net\*")
    finally:
        plat.use(None)
    plat.use(PosixPlatform())
    try:
        assert not matches_glob("Src/Net/A.cpp", "src/net/*")
    finally:
        plat.use(None)


def test_global_output_with_backslash_paths():
    plat.use(WindowsPlatform())
    try:
        hits = parse_x_output("process_packet      9 src\\net\\listener.cpp         int rc = f();\r\n")
    finally:
        plat.use(None)
    assert hits[0].path == "src/net/listener.cpp" and hits[0].line == 9


def test_decode_source_boms(tmp_path):
    body = "#include \"a.h\"\r\nint f() { return 1; }\r\n"
    (tmp_path / "u8.cpp").write_bytes(b"\xef\xbb\xbf" + body.encode())
    (tmp_path / "u16.cpp").write_bytes(b"\xff\xfe" + body.encode("utf-16-le"))
    (tmp_path / "u16be.cpp").write_bytes(b"\xfe\xff" + body.encode("utf-16-be"))
    for name in ("u8.cpp", "u16.cpp", "u16be.cpp"):
        assert read_lines(tmp_path / name) == ['#include "a.h"', "int f() { return 1; }"], name
    assert decode_source(b"\xff\xfeA\x00") == "A"


async def test_platform_run_timeout_kills_process():
    with pytest.raises(ToolTimeout):
        await plat.current().run(sys.executable, ["-c", "import time; time.sleep(30)"], cwd=os.getcwd(), timeout=1)


async def test_platform_run_output_cap():
    res = await plat.current().run(
        sys.executable, ["-c", "import sys; sys.stdout.write('x' * 200000)"], cwd=os.getcwd(), timeout=20, max_bytes=1000
    )
    assert res.truncated and len(res.stdout) == 1000


def test_doctor_cli_reports_and_exit_codes(workspace):
    import subprocess

    env = {**os.environ, "WORKSPACE_ROOT": str(workspace)}
    ok = subprocess.run([sys.executable, "-m", "staticsight.server", "doctor"], env=env, capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout + ok.stderr
    assert "OK   ctags" in ok.stdout and "all required engines OK" in ok.stdout
    bad = subprocess.run([sys.executable, "-m", "staticsight.server", "doctor"], capture_output=True, text=True,
                         env={**env, "STATICSIGHT_DISABLE_ENGINES": "rg,global"})
    assert bad.returncode == 1
    assert "FAIL rg" in bad.stdout and "WARN global" in bad.stdout and "fix:" in bad.stdout
