# Fonts

**Heebo** (variable weight 100–900), self-hosted so the app has no runtime dependency on an external font service.

- Files: `heebo-hebrew-wght-normal.woff2` (Hebrew and Hebrew punctuation) and `heebo-latin-wght-normal.woff2` (Latin, digits, symbols). Both are loaded through `unicode-range` in `static/styles.css`, so a browser downloads only the subsets a page uses (about 42 KB in total).
- Source: the `@fontsource-variable/heebo` npm package, version 5.2.8, fetched from `cdn.jsdelivr.net` on 2026-11-11; the files are the package's unmodified woff2 subsets of Heebo.
- Licence: SIL Open Font License 1.1 (`OFL.txt`, copyright 2014 The Heebo Project Authors, https://github.com/OdedEzer/heebo). The OFL permits bundling and redistributing the font with software, including commercial software, provided the copyright notice and licence text are kept (this folder) and the font is not sold on its own. No Reserved Font Name is declared in the notice.
- Fallbacks: `system-ui`, Segoe UI, Arial, Noto Sans Hebrew, sans-serif (see `--font` in `styles.css`), so the interface stays readable if the files fail to load. `font-display: swap` shows text immediately in the fallback.
- To update: replace both files from a newer package version, update this note and the size budget in `tests/test_ui_shell.py`.
