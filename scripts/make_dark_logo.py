"""Derive the dark-mode login logo from the approved full logo (development tool, not used at runtime).

    python scripts/make_dark_logo.py            # needs Pillow:  pip install pillow

Reads static/brand/full_transparent.png (the approved file, never modified) and writes static/brand/full_transparent_dark.png.

Nothing is redrawn. Every pixel keeps its position and its alpha. Only the colour of the DARK wordmark pixels and of the SLATE
tagline pixels is replaced by a light colour, so the letters, spacing and anti-aliasing are exactly the approved ones:

  * the icon (everything left of the gap at x < 560) is copied untouched, including the star, which stays the transparent cut-out of
    the approved logo, so the dark card shows through it;
  * the orange dots of the wordmark and the turquoise divider before the tagline are copied untouched (they are the saturated
    pixels of the text area);
  * every other opaque or anti-aliased pixel of the wordmark (rows 100-330) becomes the light wordmark colour, and of the
    tagline (rows 340-470) the light tagline colour.

tests/test_branding.py re-checks these guarantees on the committed files (alpha identical everywhere, the whole icon identical,
saturated text pixels identical, only the intended text pixels changed).
"""
from __future__ import annotations

import colorsys
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "static" / "brand" / "full_transparent.png"
DST = ROOT / "static" / "brand" / "full_transparent_dark.png"

ICON_RIGHT_EDGE = 560        # the icon ends at x=523 and the wordmark starts at x=586
WORDMARK_ROWS = (100, 330)   # the wordmark spans rows 113-319
TAGLINE_ROWS = (340, 470)    # the tagline and its divider span rows 353-456
WORDMARK_COLOUR = (244, 249, 250)   # near-white
TAGLINE_COLOUR = (185, 205, 212)    # light slate: keeps the original's quieter second line
SATURATED = 0.60             # orange dots and the turquoise divider are well above this; navy, slate and grey fringes are below


def keep(pixel: tuple[int, int, int, int]) -> bool:
    r, g, b, a = pixel
    _, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
    return a > 0 and s >= SATURATED and v >= 0.35


def main() -> int:
    im = Image.open(SRC).convert("RGBA")
    out = im.copy()
    src, dst = im.load(), out.load()
    w, h = im.size
    for y in range(h):
        if WORDMARK_ROWS[0] <= y < WORDMARK_ROWS[1]:
            colour = WORDMARK_COLOUR
        elif TAGLINE_ROWS[0] <= y < TAGLINE_ROWS[1]:
            colour = TAGLINE_COLOUR
        else:
            continue
        for x in range(ICON_RIGHT_EDGE, w):
            p = src[x, y]
            if p[3] == 0 or keep(p):
                continue
            dst[x, y] = (*colour, p[3])
    out.save(DST, format="PNG", optimize=True)
    print(f"wrote {DST.relative_to(ROOT)} ({DST.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
