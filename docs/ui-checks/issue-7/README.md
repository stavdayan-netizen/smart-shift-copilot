# UI checks, issue #7 (Copilot chat)

Real Edge (headless) via `scripts/ui_check.py`, fake model, fresh SQLite database with fictional data, 2026-11-14.
Viewports 360, 390, 768 and 1280, light and dark: **100 checks, 0 problems** (no horizontal overflow, no targets under 44 px
where measured, RTL, Heebo loaded, no console errors, employee cannot open the assistant). Screenshots are in this folder;
the changed screen is `*-manager-assistant-empty.jpg` (new empty state with example questions).

Not covered: a real-model reply (no key, no paid calls) and a real phone.
Two script fixes were made: the employee-isolation check now asserts "not #/assistant" (employees land on the availability
form since M1-2, not #/home). The script still expects a fresh database: a second run against the same one fails at the send step.
