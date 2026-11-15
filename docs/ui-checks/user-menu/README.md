# UI checks: login copy and manager user menu

Real Edge (headless) via `scripts/ui_check_user_menu.py`, local instance with the fake model and fictional data, 2026-11-15.
Viewports 360, 390, 768, 1280 x light and dark: **8 runs, 0 problems.** Checked: login label "סיסמה" and no manager hint;
the manager's top-corner name opens a menu (name, role "מנהל/ת", "החשבון שלי", "התנתקות"); the menu stays inside the viewport,
items are at least 44 px high; Escape closes it and returns focus, an outside click closes it; the account item navigates;
the logout item signs out; for an employee the name stays plain text with no menu. Screenshots are in this folder.
Not covered: a real phone, screen readers.
