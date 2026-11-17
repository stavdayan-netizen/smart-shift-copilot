# UI checks: explicit choice for every day (employee availability form)

Real Edge (headless) via `scripts/ui_check_availability.py` (three frozen-clock instances, fake model, fictional data), 2026-11-17.
Viewports 360, 390, 768, 1280 x light and dark: **56 checks, 0 problems.** Checked: the empty form shows seven *untouched* days ("לא נבחרה זמינות",
dashed), distinct from "לא זמין/ה"; submitting it is blocked with "יש לבחור זמינות בימים: יום ראשון, ..., יום שבת" naming all seven days, every day is marked,
the page scrolls to the first and focus moves into it; with three days chosen the message names only the remaining days and nothing is saved; choosing
the rest ("לא זמין/ה") clears the message and the save succeeds; after a reload the shifts **and** the explicit unavailable days are restored; editing and
re-saving works; the next week's new form starts with seven untouched days. `scripts/ui_check_submissions.py` (8 runs x 3 variants) shows the explicit
"לא זמין/ה" days in the manager's expanded cards. Not covered: a real phone, screen readers.
