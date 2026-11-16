# UI checks: manager "הגשות עובדים" tab

Real Edge (headless) via `scripts/ui_check_submissions.py`, fake model, fresh SQLite database, fictional data, clock frozen on an
open window, 2026-11-16. Viewports 360, 390, 768, 1280 x light and dark: **8 runs, 0 problems.** Four of the eight employees
submitted (one with HTML and a script tag in the free text, shown as plain text). Checked: the tab exists for the manager and not
for an employee (who also cannot open the route); tiles add up to one card per employee; cards start collapsed, expand and collapse
with a real click, show exact shifts and times and the free text; summaries are at least 44 px high; no horizontal overflow; RTL; the dated notice sits below the heading and above the counts and shows the window's real closing date.
There is no leave data yet (Issue #28), so no leave appears here. `../submissions-tab-injected-leave/` is the same check with leave
injected by a test-only launcher to show the badges (one full-week exemption, partial leave with and without a submission).
Not covered: a real phone, screen readers.
