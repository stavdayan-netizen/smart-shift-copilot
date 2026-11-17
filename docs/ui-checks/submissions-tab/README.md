# UI checks: manager "הגשות עובדים" tab, clickable filter cards

Real Edge (headless) via `scripts/ui_check_submissions.py`, fake model, fresh SQLite database, fictional data, clock frozen on an open window,
2026-11-17. Viewports 360, 390, 768, 1280 x light and dark: **8 runs, 0 problems.** Checked: four cards in one row on desktop and a 2x2 grid
on mobile; the cards are buttons, "סה״כ עובדים" is selected by default and the selected card is visibly different; each filter shows exactly the
matching cards (and an empty state when none: with no leave data "בחופשה" is 0); the default order is submitted (newest update first, checked
against the API), then missing by name, then exempt; every submitted collapsed card shows "עדכון אחרון: ..." and no other card does; the selection
survives the refresh button; expandable cards, shifts beside each day, hidden empty preferences, the dated notice, no overflow, 44 px targets.
There is no leave data yet (Issue #28). Not covered: a real phone, screen readers.

Compact-layout round (2026-11-17): the check also verifies the header brand gap (6 px on desktop, 10 px on mobile, icon still 32 px); the collapsed card's name, status badge and last update form one group (one row on desktop, name + badge then the timestamp on mobile); and expanded cards use a fixed-width day/date column and a flexible shifts column, one row per day, aligned across all seven days, multiple shifts on one line from 390 px up.
