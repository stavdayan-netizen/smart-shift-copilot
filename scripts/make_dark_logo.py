"""Derive the dark-mode login logo from the approved full logo (development tool, not used at runtime).

    python scripts/make_dark_logo.py            # needs Pillow:  pip install pillow

Reads static/brand/full_transparent.png (the approved file, never modified) and writes static/brand/full_transparent_dark.png.

Nothing is redrawn. Every pixel keeps its position and its alpha (the star's edge pixels become opaque, see below). Only the colour of the DARK wordmark pixels and of the SLATE
tagline pixels is replaced by a light colour, so the letters, spacing and anti-aliasing are exactly the approved ones:

  * the icon (everything left of the gap at x < 560) is copied untouched, except the star: the approved icon's star is a transparent
    cut-out that shows white on the approved white-background version. On a dark card it would show the card colour, so the star's
    own pixels (the enclosed transparent area and its anti-aliased edge) are composited over white, which is exactly how the approved
    white-background logo renders them. The tiles and their colours are not touched;
  * the orange dots of the wordmark and the turquoise divider before the tagline are copied untouched (they are the saturated
    pixels of the text area);
  * every other opaque or anti-aliased pixel of the wordmark (rows 100-330) becomes the light wordmark colour, and of the
    tagline (rows 340-470) the light tagline colour.

tests/test_branding.py re-checks these guarantees on the committed files (alpha identical outside the star, tiles identical,
saturated text pixels identical, only the intended pixels changed).
"""
from __future__ import annotations

import colorsys
import sys
from pathlib import Path

from collections import deque

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


def star_pixels(src, w: int, h: int) -> set[tuple[int, int]]:
    """The star cut-out of the icon: transparent pixels that cannot be reached from the image border through transparent pixels,
    plus the anti-aliased pixels within 2 px of them."""
    transparent = lambda x, y: src[x, y][3] <= 10
    outside: set[tuple[int, int]] = set()
    queue = deque((x, y) for x in range(ICON_RIGHT_EDGE) for y in (0, h - 1) if transparent(x, y))
    queue.extend((x, y) for y in range(h) for x in (0, ICON_RIGHT_EDGE - 1) if transparent(x, y))
    outside.update(queue)
    while queue:
        x, y = queue.popleft()
        for nx, ny in ((x + 1, y), (x - 1, y), (x, y + 1), (x, y - 1)):
            if 0 <= nx < ICON_RIGHT_EDGE and 0 <= ny < h and (nx, ny) not in outside and transparent(nx, ny):
                outside.add((nx, ny))
                queue.append((nx, ny))
    core = {(x, y) for x in range(ICON_RIGHT_EDGE) for y in range(h) if transparent(x, y) and (x, y) not in outside}
    near = set()
    for (x, y) in core:
        for dx in range(-2, 3):
            for dy in range(-2, 3):
                nx, ny = x + dx, y + dy
                if 0 <= nx < ICON_RIGHT_EDGE and 0 <= ny < h and src[nx, ny][3] < 255:
                    near.add((nx, ny))
    return near


def main() -> int:
    im = Image.open(SRC).convert("RGBA")
    out = im.copy()
    src, dst = im.load(), out.load()
    w, h = im.size
    for (x, y) in star_pixels(src, w, h):
        r, g, b, a = src[x, y]
        k = a / 255
        dst[x, y] = (round(r * k + 255 * (1 - k)), round(g * k + 255 * (1 - k)), round(b * k + 255 * (1 - k)), 255)
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
