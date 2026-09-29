"""Render the README banner and badges as PNG (docs/images/*.png).

PNG, not SVG: Azure DevOps does not render SVG images in repository Markdown; GitHub renders both.
Badges are drawn locally (no shields.io), so the docs show them offline and nothing is fetched from the internet.

Run: python3 docs/images/make_graphics.py   (needs Pillow: `pip install pillow`; a documentation-only tool)
Fonts: DejaVu Sans / Segoe UI / Helvetica are found automatically; override with FONT=/path/to/font.ttf.
"""

import os
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

HERE = Path(__file__).parent
SCALE = 2  # draw at 2x so text stays sharp on high-DPI screens; pages display at half size

_SANS = ["/usr/share/fonts/dejavu-sans-fonts/DejaVuSans.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
         "C:/Windows/Fonts/segoeui.ttf", "/System/Library/Fonts/Helvetica.ttc"]
_BOLD = ["/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
         "C:/Windows/Fonts/segoeuib.ttf", "/System/Library/Fonts/Helvetica.ttc"]
_MONO = ["/usr/share/fonts/dejavu-sans-mono-fonts/DejaVuSansMono.ttf",
         "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", "C:/Windows/Fonts/consola.ttf", "/System/Library/Fonts/Menlo.ttc"]


def font(cands: list[str], size: float) -> ImageFont.FreeTypeFont:
    for f in ([os.environ["FONT"]] if os.environ.get("FONT") else []) + cands:
        if os.path.exists(f):
            return ImageFont.truetype(f, size=round(size * SCALE))
    raise SystemExit("no TrueType font found; set FONT=/path/to/font.ttf")


# ------------------------------------------------------------------------------------------------ badges
BADGES = [  # file name, label, value, colour
    ("badge-python", "python", ">= 3.10", "#3776ab"),
    ("badge-node", "node", ">= 22.13", "#3c873a"),
    ("badge-linux", "platform", "Linux · macOS", "#e95420"),
    ("badge-windows", "platform", "Windows", "#0078d4"),
    ("badge-mcp", "protocol", "MCP · stdio", "#6f42c1"),
    ("badge-zero-compile", "C++", "zero-compile", "#00599c"),
    ("badge-license", "license", "MIT", "#2ea44f"),
    # "works with": plain text, no third-party logos
    ("works-copilot", "works with", "GitHub Copilot", "#24292f"),
    ("works-claude", "works with", "Claude Code", "#8a5a44"),
    ("works-cursor", "works with", "Cursor", "#1f1f1f"),
    ("works-windsurf", "works with", "Windsurf", "#0b6e69"),
    ("works-any-mcp", "works with", "any MCP client", "#6f42c1"),
]


def badge(name: str, label: str, value: str, colour: str) -> None:
    f = font(_SANS, 11)
    pad, h = 6 * SCALE, 20 * SCALE
    probe = ImageDraw.Draw(Image.new("RGB", (1, 1)))
    lw = int(probe.textlength(label, font=f)) + 2 * pad
    vw = int(probe.textlength(value, font=f)) + 2 * pad
    img = Image.new("RGBA", (lw + vw, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    r = 3 * SCALE
    d.rounded_rectangle([0, 0, lw + vw - 1, h - 1], radius=r, fill=colour)
    d.rounded_rectangle([0, 0, lw + r, h - 1], radius=r, fill="#555555")
    d.rectangle([lw, 0, lw + r, h - 1], fill=colour)
    for x, text in ((lw / 2, label), (lw + vw / 2, value)):
        d.text((x, h / 2 + SCALE), text, font=f, fill="#010101", anchor="mm")  # subtle shadow
        d.text((x, h / 2), text, font=f, fill="#ffffff", anchor="mm")
    img.save(HERE / f"{name}.png", optimize=True)


# ------------------------------------------------------------------------------------------------ banner
def banner() -> None:
    w, h = 900 * SCALE, 200 * SCALE
    img = Image.new("RGB", (w, h), "#0d1117")
    d = ImageDraw.Draw(img)
    top, bottom = (13, 17, 23), (22, 40, 70)  # vertical gradient, GitHub-dark to deep blue
    for y in range(h):
        t = y / (h - 1)
        d.line([(0, y), (w, y)], fill=tuple(round(a + (b - a) * t) for a, b in zip(top, bottom)))
    # the "eye": a lens over code lines
    cx, cy, r = 130 * SCALE, 100 * SCALE, 58 * SCALE
    mono = font(_MONO, 9)
    code = ["int Router::process(Packet* p) {", "  auto* buf = malloc(p->len);", "  if (!p->ok) return -2;",
            "  memcpy(buf, p, sizeof(Packet));", "  free(buf); return 0;", "}"]
    for i, line in enumerate(code):
        d.text((40 * SCALE, (52 + i * 16) * SCALE), line, font=mono, fill="#30405a")
    d.ellipse([cx - r, cy - r, cx + r, cy + r], fill="#0f1b2d", outline="#58a6ff", width=5 * SCALE)
    d.ellipse([cx - r + 10 * SCALE, cy - r + 10 * SCALE, cx + r - 10 * SCALE, cy + r - 10 * SCALE], outline="#1f6feb", width=2 * SCALE)
    d.line([cx + int(r * 0.72), cy + int(r * 0.72), cx + int(r * 1.35), cy + int(r * 1.35)], fill="#58a6ff", width=9 * SCALE)
    d.text((cx, cy - 8 * SCALE), "if (!p->ok)", font=font(_MONO, 10), fill="#ffa657", anchor="mm")
    d.text((cx, cy + 10 * SCALE), "return -2;", font=font(_MONO, 10), fill="#ff7b72", anchor="mm")
    x = 250 * SCALE
    d.text((x, 62 * SCALE), "StaticSight", font=font(_BOLD, 44), fill="#f0f6fc", anchor="ls")
    d.text((x, 102 * SCALE), "Zero-compile C++ review evidence for AI agents", font=font(_SANS, 18), fill="#c9d1d9", anchor="ls")
    d.text((x, 132 * SCALE), "ctags · GNU Global · ripgrep · cppcheck · git · local semantic search",
           font=font(_SANS, 13), fill="#8b949e", anchor="ls")
    d.text((x, 162 * SCALE), "MCP server + command line  ·  Linux · macOS · Windows  ·  Python & TypeScript",
           font=font(_SANS, 13), fill="#58a6ff", anchor="ls")
    img.save(HERE / "banner.png", optimize=True)


def main() -> None:
    banner()
    for b in BADGES:
        badge(*b)
    print("wrote banner.png and", len(BADGES), "badges")


if __name__ == "__main__":
    main()
