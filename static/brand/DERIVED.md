# Derived brand file

`full_transparent_dark.png` is the only file in this folder that is not a delivered kit file. It is derived from the approved
`full_transparent.png` by `scripts/make_dark_logo.py` (development tool, needs Pillow), because the approved wordmark and tagline are dark
and the kit contains no reversed version. It is shown only in dark mode (`<picture>` with `prefers-color-scheme: dark`); light mode uses
the approved file as delivered.

Nothing is redrawn: the glyph shapes, spacing and anti-aliasing are the approved pixels.
- Icon tiles: copied pixel for pixel.
- Star: the approved icon's star is a transparent cut-out that shows white on the approved white-background logo; its pixels are composited
  over white (what the white-background version shows), so it stays white on the dark card.
- Wordmark: dark navy pixels become a near-white (`#F4F9FA`), alpha unchanged; the three orange dots are copied untouched.
- Tagline: slate pixels become a light slate (`#B9CDD4`), alpha unchanged; the turquoise divider is copied untouched.

`tests/test_branding.py` re-checks these guarantees on the committed files. The approved originals and `SHA256SUMS` are unchanged.
