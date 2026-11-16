# UI checks: manager "הגשות עובדים" tab (refinement round)

Real Edge (headless) via `scripts/ui_check_submissions.py`, fake model, fresh SQLite database, fictional data, clock frozen on an open
window, 2026-11-17. Viewports 360, 390, 768, 1280 x light and dark: **8 runs, 0 problems.** Checked: the dated notice (exact text,
between the heading and the counts); employees with missing submissions listed first; badges "הוגשה זמינות" / "טרם הוגשה זמינות";
no "החשבון שלי" in the navigation (it stays in the user menu) and the "הגשות עובדים" label centred under its icon; no read-only line;
expanded cards show all seven days with the shifts beside each day (compact, wraps on narrow screens), the preferences section only when
the employee wrote something (free text with HTML shown as plain text); the page does not overflow; summaries are at least 44 px; an
employee has no such tab. `scripts/ui_check_user_menu.py` (8 runs), `scripts/ui_check_availability.py` (44 checks) and `scripts/ui_check.py`
(100 checks) were re-run on this branch with 0 problems (their older screenshots in this folder's siblings were not regenerated).
There is no leave data yet (Issue #28). Not covered: a real phone, screen readers.
