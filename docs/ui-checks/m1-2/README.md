# UI checks: issue #6 (employee availability form)

What was actually run on 2026-11-12 with `scripts/ui_check_availability.py` (a real headless Microsoft Edge 157.0.4341.46, driven over the DevTools protocol; no packages needed), what it found, and what was **not** verified. Numbers come from `results.json`.

## How
- Three instances of the app on one disposable SQLite database with fictional seeded employees (`python -m app.seed`), each with a different frozen scheduling clock (`CLOCK_OVERRIDE`, non-production only):
  - **A** Monday 16 Nov 2026 12:00 (Asia/Jerusalem): the window for 22-28 Nov is open. The employee builds and saves a submission here.
  - **B** Wednesday 18 Nov 09:00: after the deadline, the next window is not open yet (opening notice + the locked previous submission).
  - **C** Sunday 22 Nov 12:00: the window for 29 Nov-5 Dec is open (a new form, last week's submission read-only below).
- Viewports 360x800 and 390x844 (mobile emulation, touch), 768x1024, 1280x800; light (default) and dark. A different seeded employee for each viewport and scheme, so every run starts with an empty form.
- Per screen it measures: `lang=he dir=rtl`, horizontal overflow (page **and** any element past either edge, since RTL overflow leaves through the left edge), every interactive target (a checkbox is tapped through its label row, which must be at least 44 x 44), Heebo loaded, the emulated colour scheme, and console errors (the anonymous session check's 401 on first load is expected and listed separately).
- It also asserts behaviour: the exact heading; seven day cards, 14 shortcut buttons, 14 checkboxes; the exact free-text notice and the "create and edit until Tuesday 22:00" sentence; an empty form cannot be submitted (button disabled, "select at least one shift" help); `כל המשמרות` ticks both shifts of a day and `לא זמין/ה` clears it; one checkbox edited after a shortcut is reflected exactly; text over 1,000 characters turns the counter red and disables saving; saving shows the confirmation and the "submitted" chip; the saved submission survives a reload; editing shows "unsaved changes" and updating saves; instance B shows the exact opening notice, no form and the locked summary; instance C shows the open form, a disabled submit and the locked summary.

## Results

| Viewport | Scheme | Checks | Page overflows sideways | Elements past an edge | Targets under 44 px | Unexpected console errors | `lang=he dir=rtl` | Heebo loaded |
|---|---|---|---|---|---|---|---|---|
| 360 | light | 6 | 0 | 0 | 0 | 0 | yes | yes |
| 360 | dark | 4 | 0 | 0 | 0 | 0 | yes | yes |
| 390 | light | 6 | 0 | 0 | 0 | 0 | yes | yes |
| 390 | dark | 4 | 0 | 0 | 0 | 0 | yes | yes |
| 768 | light | 6 | 0 | 0 | 0 | 0 | yes | yes |
| 768 | dark | 4 | 0 | 0 | 0 | 0 | yes | yes |
| 1280 | light | 6 | 0 | 0 | 0 | 0 | yes | yes |
| 1280 | dark | 4 | 0 | 0 | 0 | 0 | yes | yes |

**40 checks, 0 problems**, and every behavioural assertion above held. The browser-side logic (selection model, shortcuts, dirty tracking, counters, durations) additionally has 8 node tests (`tests/js/availability.test.js`), run in headless Edge here and under node in CI.

## What the checks changed
- The first run flagged the 24 px checkboxes as small targets. The real touch target is the whole 52 px label row, so the measurement now looks at the label for checkboxes (the script was wrong, not the form). Nothing else needed fixing.
- Screenshots for the "too long" and "filled" states are taken scrolled to the free-text field so the counter is visible.

## Screenshots (curated; the rest are reproducible with the script)
| | 360 | 390 | 768 | 1280 |
|---|---|---|---|---|
| Open, empty (submit disabled) | ![](360-light-form-empty.jpg) | ![](390-light-form-empty.jpg) | ![](768-light-form-empty.jpg) | ![](1280-light-form-empty.jpg) |
| Filled (selected days, text) | ![](360-light-form-filled.jpg) | ![](390-light-form-filled.jpg) | ![](768-light-form-filled.jpg) | ![](1280-light-form-filled.jpg) |
| Over 1,000 characters | ![](360-light-form-text-too-long.jpg) | ![](390-light-form-text-too-long.jpg) | ![](768-light-form-text-too-long.jpg) | ![](1280-light-form-text-too-long.jpg) |
| Saved | ![](360-light-form-saved.jpg) | ![](390-light-form-saved.jpg) | ![](768-light-form-saved.jpg) | ![](1280-light-form-saved.jpg) |
| Not open yet + locked summary | ![](360-light-not-open-with-locked.jpg) | ![](390-light-not-open-with-locked.jpg) | ![](768-light-not-open-with-locked.jpg) | ![](1280-light-not-open-with-locked.jpg) |
| Next week open + locked below | ![](360-light-open-next-week-with-locked.jpg) | ![](390-light-open-next-week-with-locked.jpg) | ![](768-light-open-next-week-with-locked.jpg) | ![](1280-light-open-next-week-with-locked.jpg) |
| Dark: empty | ![](360-dark-form-empty.jpg) | | | ![](1280-dark-form-empty.jpg) |
| Dark: saved | ![](360-dark-form-saved.jpg) | | | ![](1280-dark-form-saved.jpg) |
| Dark: not open | ![](360-dark-not-open-with-locked.jpg) | | | ![](1280-dark-not-open-with-locked.jpg) |

## NOT VERIFIED
- **Real devices and other browsers:** only Chromium (Edge) with device emulation; no physical iPhone or Android, no Safari or Firefox. `:has()` is used for the selected-row highlight (a recent-browser feature); the checkbox itself is always visible without it.
- **On-screen keyboard** behaviour with the sticky submit bar and the text area.
- **Screen readers:** labels, fieldset legends, live regions and the focus order were written for them but not listened to; only the Tab order of the login screen was exercised earlier.
- **The countdown refreshing across the deadline in a live session**, and the "closed while editing" message: covered by code review and the API tests (the boundary seconds), not by watching a real clock pass 22:00.
- **The 429 save limit and the 409 race message in the browser** (covered by API tests; the UI shows the server's Hebrew message).
- **Hebrew copy** reviewed by the author only, not by a native-speaker editor; the opening notice and the two statements are the owner's exact wording.
- Dark mode at 390 and 768 px was measured (see the table) but its screenshots are not committed; 320 px, print and 200 % zoom were not exercised.
