"""Render docs/images/copilot-cli-usage.svg and .png: an illustrative Copilot CLI session using StaticSight.

Tool results shown are real StaticSight output on the fixture repo (shared/fixtures/make_fixture.py).
The PNG is what the README shows: Azure DevOps does not render SVG images in Markdown (GitHub does).

Run: python3 docs/images/make_usage_svg.py
The PNG needs Pillow (`pip install pillow`, a documentation-only tool) and a monospace TrueType font
(DejaVu Sans Mono, Consolas or Menlo; override with FONT=/path/to/font.ttf).
"""

import os
from pathlib import Path
from xml.sax.saxutils import escape

C = {"fg": "#c9d1d9", "dim": "#8b949e", "user": "#79c0ff", "tool": "#d2a8ff", "ok": "#3fb950",
     "warn": "#e3b341", "err": "#ff7b72", "head": "#ffa657", "prompt": "#3fb950"}

# (color, text) segments per line
LINES = [
    [("prompt", "~/src/cpp-sample (feature)"), ("dim", " $ "), ("fg", "copilot")],
    [],
    [("user", "> Review my changes. What did I miss, and could anything break?")],
    [],
    [("tool", "● staticsight-review_changes"), ("dim", "  base: merge-base with origin/main (7cd1f773cb)")],
    [("dim", "  └ 6 C/C++ files changed (+30 / -1) · cppcheck 1 error · 1 leak path · 2 ignored results · 1 lock cycle")],
    [("tool", "● staticsight-get_branch_skeleton"), ("dim", "  src/router.cpp  Router::process_packet")],
    [("dim", "  └ [L13] "), ("err", "RETURN -2  early exit; `buffer` (L11) not released on this path")],
    [("tool", "● staticsight-track_struct_risks"), ("dim", "  Packet")],
    [("dim", "  └ 4 sites: socket.cpp:6 send(...sizeof(Packet)), socket.cpp:9, wal.cpp:5, wal.cpp:9 memcpy")],
    [("tool", "● staticsight-track_state_mutations"), ("dim", "  route_count")],
    [("dim", "  └ "), ("warn", "Inconsistent locking: router.cpp:34 (read), router.cpp:38 (write) without route_mutex")],
    [("tool", "● staticsight-track_lock_order"), ("dim", "  (whole repository)")],
    [("dim", "  └ "), ("err", "Deadlock cycle: rebalance() takes pool→stats, report() takes stats→pool via drain()")],
    [("tool", "● staticsight-get_upstream_callers"), ("dim", "  process_packet")],
    [("dim", "  └ 3 call sites · listener.cpp:17 and test_router.cpp:6 ignore the int result")],
    [],
    [("head", "Blockers")],
    [("fg", " 1. src/router.cpp:13  new early `return -2` leaks `buffer` from malloc at L11")],
    [("dim", "    evidence: cppcheck memleak (CWE-401) on a changed line + skeleton. fix: free(buffer) before return,")],
    [("dim", "    or move the encryption check above the allocation.")],
    [("fg", " 2. src/net/packet.hpp:8  new `checksum` field changes sizeof(Packet); socket.cpp:6 sends raw bytes")],
    [("dim", "    and wal.cpp:5/9 memcpy it: wire and WAL formats break for older peers/records. fix: version the")],
    [("dim", "    format or serialize per field; add static_assert(sizeof(Packet) == ...).")],
    [("fg", " 3. src/router.cpp:34/38  get_route_count() lost its lock and reset() writes route_count bare,")],
    [("dim", "    while process_packet/reconfigure_routes hold route_mutex: data race. fix: take the lock.")],
    [("fg", " 4. src/net/conn_pool.cpp:31  report() holds stats_mutex while drain() takes pool_mutex: the reverse")],
    [("dim", "    of rebalance() (pool, then stats), so the two can deadlock; it also send()s while locked. fix: one order.")],
    [("head", "Major")],
    [("fg", " 5. listener.cpp:17 ignores process_packet() result; new -2 error path is silently dropped.")],
    [],
    [("err", "Verdict: not ready to merge (4 blockers). "), ("fg", "First fix the leak at router.cpp:13.")],
]

W, LH, PAD, TOP = 1060, 20, 20, 52
H = TOP + LH * len(LINES) + PAD


def main() -> None:
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" role="img" '
        'aria-label="Copilot CLI session using the StaticSight MCP tools to review C++ changes">',
        f'<rect width="{W}" height="{H}" rx="10" fill="#0d1117" stroke="#30363d"/>',
        f'<rect width="{W}" height="34" rx="10" fill="#161b22"/><rect y="24" width="{W}" height="10" fill="#161b22"/>',
        '<circle cx="20" cy="17" r="6" fill="#ff5f56"/><circle cx="40" cy="17" r="6" fill="#ffbd2e"/>'
        '<circle cx="60" cy="17" r="6" fill="#27c93f"/>',
        f'<text x="{W // 2}" y="22" text-anchor="middle" fill="#8b949e" font-family="sans-serif" font-size="13">'
        f"{TITLE}</text>",
        '<g font-family="ui-monospace,SFMono-Regular,Menlo,Consolas,monospace" font-size="13.5" xml:space="preserve">',
    ]
    for i, segs in enumerate(LINES):
        if not segs:
            continue
        y = TOP + i * LH
        spans = "".join(f'<tspan fill="{C[c]}">{escape(t)}</tspan>' for c, t in segs)
        out.append(f'<text x="{PAD}" y="{y}">{spans}</text>')
    out += ["</g>", "</svg>"]
    Path(__file__).with_name("copilot-cli-usage.svg").write_text("\n".join(out) + "\n", encoding="utf-8")
    render_png()


TITLE = "GitHub Copilot CLI + StaticSight MCP (illustrative; tool results are real fixture output)"
_MONO = ["/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "C:/Windows/Fonts/consola.ttf",
         "/System/Library/Fonts/Menlo.ttc", "/Library/Fonts/Menlo.ttc"]
_SANS = ["/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "C:/Windows/Fonts/segoeui.ttf", "/System/Library/Fonts/Helvetica.ttc"]


def _font(cands: list[str], size: float):
    from PIL import ImageFont

    for f in ([os.environ["FONT"]] if os.environ.get("FONT") else []) + cands:
        if os.path.exists(f):
            return ImageFont.truetype(f, size=round(size))
    return None


def render_png(scale: int = 2) -> None:
    """Same picture as the SVG, as a PNG at `scale`x for sharp text."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:
        print("Pillow not installed: SVG written, PNG skipped (pip install pillow)")
        return
    mono, sans = _font(_MONO, 13.5 * scale), _font(_SANS, 13 * scale)
    if mono is None or sans is None:
        print("no monospace/sans TrueType font found: PNG skipped (set FONT=/path/to/mono.ttf)")
        return
    k = scale
    img = Image.new("RGB", (W * k, H * k), "#0d1117")
    d = ImageDraw.Draw(img)
    d.rounded_rectangle([0, 0, W * k - 1, H * k - 1], radius=10 * k, fill="#0d1117", outline="#30363d", width=k)
    d.rounded_rectangle([0, 0, W * k - 1, 34 * k], radius=10 * k, fill="#161b22")
    d.rectangle([0, 24 * k, W * k - 1, 34 * k], fill="#161b22")
    for cx, col in ((20, "#ff5f56"), (40, "#ffbd2e"), (60, "#27c93f")):
        d.ellipse([(cx - 6) * k, 11 * k, (cx + 6) * k, 23 * k], fill=col)
    d.text((W * k // 2, 22 * k), TITLE, font=sans, fill=C["dim"], anchor="ms")
    for i, segs in enumerate(LINES):
        x = PAD * k
        y = (TOP + i * LH) * k
        for c, t in segs:
            d.text((x, y), t, font=mono, fill=C[c], anchor="ls")
            x += d.textlength(t, font=mono)
    out = Path(__file__).with_name("copilot-cli-usage.png")
    img.save(out, optimize=True)
    print(f"wrote {out.name} ({W * k}x{H * k})")


if __name__ == "__main__":
    main()
