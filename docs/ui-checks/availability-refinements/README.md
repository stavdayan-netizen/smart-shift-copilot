# UI checks: availability form refinements

Real Edge (headless) via `scripts/ui_check_availability.py` (three frozen-clock instances, fake model, fictional data), 2026-11-15.
Viewports 360, 390, 768, 1280 x light and dark: **44 checks, 0 problems.** Checked in addition to the usual overflow, 44 px target,
RTL and console checks: no status badges at the top; "טרם הוגשה" / "הוגשה · עודכנה …" sits in the submit bar; the single deadline
line with the real date ("יום שלישי, 17.11.26 בשעה 22:00 …"), no countdown; the new instruction and free-text example; the seven day
cards stacked one per row with "כל המשמרות" / "לא זמין/ה" beside the shift choices at every width; "לא זמין/ה" clears and disables the
day's shifts, shows an active state and toggles off on a second click; "כל המשמרות" resets it and selects both shifts; saving and
reloading keep working (a saved day without shifts shows as unavailable). The pure model is covered by tests/js/availability.test.js
(11 tests, run here in headless Edge via tests/js/run.html because node is not installed on this machine; CI runs them under node).
Not covered: a real phone, screen readers.
