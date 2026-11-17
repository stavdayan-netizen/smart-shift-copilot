"""Shiftimizer branding: only the approved kit files, exactly as delivered, wired into the shell; accessible colours."""
import hashlib
import json
import re

from app.config import ROOT

STATIC = ROOT / "static"
BRAND = STATIC / "brand"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "styles.css").read_text(encoding="utf-8")

# The files taken from "Shiftimizer_Final_Brand_Kit": full logo with its tagline, and the web icons. Never redraw or recolour them.
APPROVED = {"favicon.ico", "full_transparent.png", "icon_16.png", "icon_180_white.png", "icon_192.png", "icon_32.png", "icon_512.png", "icon_64.png"}


def test_the_brand_files_are_exactly_the_approved_ones_and_unmodified():
    sums = dict(reversed(line.split(" *", 1)) for line in (BRAND / "SHA256SUMS").read_text(encoding="utf-8").splitlines() if line.strip())
    assert set(sums) == APPROVED
    for name, digest in sums.items():
        assert hashlib.sha256((BRAND / name).read_bytes()).hexdigest() == digest, f"{name} differs from the approved asset"
    extra = {p.name for p in BRAND.iterdir()} - APPROVED - {"SHA256SUMS", "manifest.json", "DERIVED.md", "full_transparent_dark.png"}
    assert extra == set(), f"unexpected files in static/brand: {extra}"


def test_png_dimensions_are_the_approved_ones():
    def size(p):
        b = (BRAND / p).read_bytes()
        assert b[:8] == b"\x89PNG\r\n\x1a\n"
        return int.from_bytes(b[16:20], "big"), int.from_bytes(b[20:24], "big")

    assert size("full_transparent.png") == (1872, 538)
    assert [size(f"icon_{n}.png") for n in (16, 32, 64, 192, 512)] == [(n, n) for n in (16, 32, 64, 192, 512)]
    assert size("icon_180_white.png") == (180, 180)


def test_the_page_uses_the_brand_for_title_favicons_home_screen_and_header():
    assert "<title>Shiftimizer</title>" in HTML and "Smart Shift Copilot" not in HTML
    assert 'href="/static/brand/favicon.ico"' in HTML and 'sizes="32x32" href="/static/brand/icon_32.png"' in HTML
    assert 'rel="apple-touch-icon" href="/static/brand/icon_180_white.png"' in HTML and 'rel="manifest" href="/static/brand/manifest.json"' in HTML
    assert "favicon.svg" not in HTML and not (STATIC / "favicon.svg").exists()
    login = HTML.split('id="view-login"')[1].split("</section>")[0]
    assert 'src="/static/brand/full_transparent.png"' in login and "סידור עבודה חכם" in login      # the full logo, tagline included in the image
    assert 'srcset="/static/brand/full_transparent_dark.png" media="(prefers-color-scheme: dark)"' in login   # dark mode: the derived light-wordmark file
    assert ".login-logo { display: grid" in CSS and "background: #FFFFFF; border-radius: var(--radius-sm); padding: 10px 16px" not in CSS   # no white plate
    header = HTML.split('class="appbar"')[1].split("</header>")[0]
    assert 'src="/static/brand/icon_64.png"' in header and 'data-t="app.name"' in header
    assert "Smart Shift" not in (STATIC / "strings.js").read_text(encoding="utf-8")


def test_the_manifest_is_valid_and_points_at_the_approved_icons():
    m = json.loads((BRAND / "manifest.json").read_text(encoding="utf-8"))
    assert m["name"] == "Shiftimizer" and m["lang"] == "he" and m["dir"] == "rtl" and m["start_url"] == "/"
    assert {i["src"] for i in m["icons"]} == {"/static/brand/icon_192.png", "/static/brand/icon_512.png"}
    for i in m["icons"]:
        assert (STATIC / i["src"].removeprefix("/static/")).exists()


def test_brand_assets_are_served(client):
    for path, kind in (("/static/brand/favicon.ico", None), ("/static/brand/full_transparent.png", "image/png"), ("/static/brand/icon_180_white.png", "image/png"),
                       ("/static/brand/manifest.json", "json")):
        r = client.get(path)
        assert r.status_code == 200, path
        if kind:
            assert kind in r.headers["content-type"]


# ---- contrast: the brand colours must stay readable in both modes
def _lum(hexcolor):
    h = hexcolor.lstrip("#")
    c = [int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)]
    f = lambda v: v / 12.92 if v <= 0.03928 else ((v + 0.055) / 1.055) ** 2.4
    return 0.2126 * f(c[0]) + 0.7152 * f(c[1]) + 0.0722 * f(c[2])


def _contrast(a, b):
    hi, lo = sorted((_lum(a), _lum(b)), reverse=True)
    return (hi + 0.05) / (lo + 0.05)


def _tokens(block):
    return dict(re.findall(r"--([a-z0-9-]+):\s*(#[0-9A-Fa-f]{6})", block))


def test_accent_colours_meet_wcag_contrast_in_light_and_dark():
    light = _tokens(CSS.split("@media (prefers-color-scheme: dark)")[0])
    dark = {**light, **_tokens(CSS.split("@media (prefers-color-scheme: dark)")[1].split("* { box-sizing")[0])}
    for name, t in (("light", light), ("dark", dark)):
        assert _contrast(t["accent-ink"], t["accent"]) >= 4.5, f"{name}: button text on the accent"
        assert _contrast(t["accent-ink"], t["accent-hover"]) >= 4.5, f"{name}: button text on hover"
        assert _contrast(t["accent-text"], t["accent-soft"]) >= 4.5, f"{name}: accent text on its soft background"
        assert _contrast(t["accent-text"], t["surface"]) >= 4.5, f"{name}: accent text on cards"
        assert _contrast(t["accent-text"], t["bg"]) >= 4.5, f"{name}: accent text on the page"
        assert _contrast(t["accent"], t["surface"]) >= 3.0, f"{name}: accent as a UI border or control on cards"
        assert _contrast(t["ink"], t["accent-soft"]) >= 4.5, f"{name}: body text on soft accent areas"


# ---- the derived dark-mode logo: same pixels, only the dark text colours replaced (see static/brand/DERIVED.md)
def _png_rgba(path):
    """Minimal decoder for 8-bit RGBA, non-interlaced PNG files (enough for the logo; no imaging library needed)."""
    import struct
    import zlib

    data = path.read_bytes()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    pos, idat, ihdr = 8, b"", None
    while pos < len(data):
        n, kind = struct.unpack(">I4s", data[pos:pos + 8])
        body = data[pos + 8:pos + 8 + n]
        if kind == b"IHDR":
            ihdr = struct.unpack(">IIBBBBB", body)
        elif kind == b"IDAT":
            idat += body
        pos += 12 + n
    w, h, depth, ctype, _, _, interlace = ihdr
    assert (depth, ctype, interlace) == (8, 6, 0), "expected 8-bit RGBA, not interlaced"
    raw, stride, bpp = zlib.decompress(idat), w * 4, 4
    rows, prev = [], bytearray(stride)
    for y in range(h):
        f = raw[y * (stride + 1)]
        line = bytearray(raw[y * (stride + 1) + 1:(y + 1) * (stride + 1)])
        for i in range(stride):
            a = line[i - bpp] if i >= bpp else 0
            b = prev[i]
            c = prev[i - bpp] if i >= bpp else 0
            if f == 1:
                line[i] = (line[i] + a) & 255
            elif f == 2:
                line[i] = (line[i] + b) & 255
            elif f == 3:
                line[i] = (line[i] + ((a + b) >> 1)) & 255
            elif f == 4:
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                line[i] = (line[i] + (a if pa <= pb and pa <= pc else b if pb <= pc else c)) & 255
        rows.append(line)
        prev = line
    return w, h, rows


def test_the_dark_logo_is_the_approved_logo_with_only_the_dark_text_recoloured():
    import colorsys

    w, h, orig = _png_rgba(BRAND / "full_transparent.png")
    w2, h2, dark = _png_rgba(BRAND / "full_transparent_dark.png")
    assert (w, h) == (w2, h2) == (1872, 538)
    px = lambda rows, x, y: tuple(rows[y][x * 4:x * 4 + 4])
    wordmark, tagline = (244, 249, 250), (185, 205, 212)
    recoloured = 0
    for y in range(h):
        for x in range(w):
            o, d = px(orig, x, y), px(dark, x, y)
            if o == d:
                continue
            # the whole icon, the star's transparent cut-out included, is identical to the approved file
            assert x >= 560, f"icon pixel changed at {(x, y)}: {o} -> {d}"
            assert d[3] == o[3], f"text pixel alpha changed at {(x, y)}"
            assert d[:3] in (wordmark, tagline), f"text pixel recoloured to an unexpected colour at {(x, y)}"
            assert (d[:3] == wordmark) == (100 <= y < 330)
            recoloured += 1
    assert px(dark, 405, 150)[3] == 0 and px(orig, 405, 150)[3] == 0, "the star must stay a transparent cut-out"
    assert recoloured > 50000
    # the saturated pixels of the text area (orange dots, turquoise divider) are untouched
    kept = 0
    for y in range(100, 470):
        for x in range(560, w):
            o = px(orig, x, y)
            if o[3] > 200 and colorsys.rgb_to_hsv(*(c / 255 for c in o[:3]))[1] >= 0.6 and max(o[:3]) >= 90:
                assert px(dark, x, y) == o
                kept += 1
    assert kept > 3000


def test_the_dark_logo_colours_are_readable_on_the_dark_card():
    surface = _tokens(CSS.split("@media (prefers-color-scheme: dark)")[1].split("* { box-sizing")[0])["surface"]
    assert _contrast("#F4F9FA", surface) >= 7.0                  # wordmark
    assert _contrast("#B9CDD4", surface) >= 4.5                  # tagline
