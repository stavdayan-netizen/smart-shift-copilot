# UI checks: Shiftimizer branding

Real Edge (headless) via `scripts/ui_check_brand.py`, local instance, fictional data, 2026-11-17. Viewports 360, 390, 768, 1280 x light and
dark: **8 runs, 0 problems.** Checked: the approved full logo (with its tagline) loads at its native 1872x538 and fits the login card
(on a white plate in dark mode); the header shows the approved icon (32 px) and the name "Shiftimizer" for the manager and the employee;
the page title is "Shiftimizer"; every icon link, the apple-touch icon, the manifest and its icons answer 200; the old name is not visible;
no overflow, targets of at least 44 px, RTL, no console errors. `scripts/ui_check.py` (100 checks) and `scripts/ui_check_user_menu.py`
(8 runs) were re-run on this branch with 0 problems. Not covered: how the favicon and home-screen icon look in a real browser tab or on a
real phone's home screen (the files are the approved ones and are served), and screen readers.
