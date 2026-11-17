# Derived brand file

`full_transparent_dark.png` is the only file in this folder that is not a delivered kit file. It is derived from the approved
`full_transparent.png` by `scripts/make_dark_logo.py` (development tool, needs Pillow), because the approved wordmark and tagline are dark
and the kit contains no reversed version. It is shown only in dark mode (`<picture>` with `prefers-color-scheme: dark`); light mode uses
the approved file as delivered.

Nothing is redrawn: the glyph shapes, spacing, anti-aliasing and every pixel's alpha are the approved ones.
- Icon (all four tiles and the star): copied pixel for pixel. The star remains the transparent cut-out of the approved logo, so the card
  behind the logo shows through it.
- Wordmark: dark navy pixels become a near-white (`#F4F9FA`); the three orange dots are copied untouched.
- Tagline: slate pixels become a light slate (`#B9CDD4`); the turquoise divider is copied untouched.

`tests/test_branding.py` re-checks these guarantees on the committed files (the whole icon identical, alpha identical everywhere, only
text pixels recoloured). The approved originals and `SHA256SUMS` are unchanged.
