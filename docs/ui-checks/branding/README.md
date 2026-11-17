# UI checks: Shiftimizer branding

Real Edge (headless) via `scripts/ui_check_brand.py`, local instance, fictional data, 2026-11-17 (updated for the dark-mode login logo).
Viewports 360, 390, 768, 1280 x light and dark: **8 runs, 0 problems.** Checked: the logo loads at its native 1872x538 and fits the login
card with no plate behind it; in dark mode the browser chooses the derived light-wordmark file (wordmark pixels bright, the star a transparent cut-out as in the approved logo), in light mode the approved file as delivered; the header shows the approved icon (32 px) and "Shiftimizer" for the manager and
the employee; the page title; every icon link, the apple-touch icon, the manifest and its icons answer 200; the old name is not visible;
no overflow, targets of at least 44 px, RTL, no console errors. `scripts/ui_check.py` (100 checks) was re-run with 0 problems.
Not covered: how the favicon and home-screen icon look in a real browser tab or on a real phone, and screen readers.
