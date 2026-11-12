# UI checks: issue #4 (Hebrew RTL mobile-first shell)

What was actually run, on 2026-11-11, and what was not. Nothing below was inferred; every number comes from `results.json` produced by `scripts/ui_check.py`.

## How
- **Tool:** `python scripts/ui_check.py` drives a real Chromium browser (Microsoft Edge 157.0.4341.46, headless) over the DevTools protocol. It needs no Python packages. The built-in browser pane of this session could not be used (it was hidden and its tools timed out), so this script is the verification tool.
- **App under test:** a local instance (`APP_ENV=local`, fake model, SQLite, fictional users: a manager and one employee) seeded with a conversation of rich Markdown (lists, a wide 8-column table, mixed Hebrew and English, a very long line, a long unbroken URL, and raw `<script>`/`<img onerror>` text).
- **Viewports:** 360x800 and 390x844 (mobile emulation with touch), 768x1024 (tablet), 1280x800 (desktop). **Schemes:** light (default) with the full flow at all four sizes; dark with the full flow at 360 and 1280, and the main screens (8 checks) at 390 and 768.
- **Per screen it measures:** `lang="he" dir="rtl"`, horizontal overflow (page `scrollWidth` **and** any element past either edge, because in RTL overflow goes off the left edge and `scrollWidth` does not grow), every visible interactive element's size (must be at least 44 x 44; a `<summary>` disclosure inside text may be 32 px high), whether Heebo loaded, the emulated colour scheme, and browser console errors. Expected errors (the deliberate wrong login, the anonymous `401` of the session check, the offline step) are listed separately and not counted.
- **Flows exercised:** login; empty submit; wrong code; slow network (loading state); employee home and account; the legal dialog (and Escape closes it); logout; manager Copilot (empty state, history drawer or column, a conversation with rich Markdown, sending a message and receiving the streamed reply, going offline so send and history fail with their error states and retry); employee cannot open the manager route (`#/assistant` stays on `#/home`) and sees no chat UI; keyboard order (the skip link is one Shift+Tab from the name field and shows a focus ring; Tab from the name reaches the code field); Heebo blocked, to check the fallback fonts.

## Results

| Viewport | Scheme | Checks | Page overflows sideways | Elements past an edge | Targets under 44 px | Console errors | `lang=he dir=rtl` | Heebo loaded |
|---|---|---|---|---|---|---|---|---|
| 360 | light | 14 | 0 | 0 | 0 | 0 | yes | yes |
| 360 | dark | 13 | 0 | 0 | 0 | 0 | yes | yes |
| 390 | light | 14 | 0 | 0 | 0 | 0 | yes | yes |
| 390 | dark | 8 | 0 | 0 | 0 | 0 | yes | yes |
| 768 | light | 14 | 0 | 0 | 0 | 0 | yes | yes |
| 768 | dark | 8 | 0 | 0 | 0 | 0 | yes | yes |
| 1280 | light | 14 | 0 | 0 | 0 | 0 | yes | yes |
| 1280 | dark | 13 | 0 | 0 | 0 | 0 | yes | yes |
| 360 (Heebo blocked) | light | 2 | 0 | 0 | 0 | 0 | yes | no (fallback) |

100 checks, 0 problems. The wide table scrolls inside its own labelled, keyboard-focusable region (716 px of table in a 300 px region at 360) and never widens the page. Raw `<script>` and `<img onerror>` in the model text appear as text, never as elements. Navigation is a bottom bar under 768 px and a side rail on the inline-start (right) edge from 768 px; conversation history is a drawer under 1024 px and a column from 1024 px.

## Problems found by these checks and fixed in this PR
1. **RTL overflow the first measurement missed.** At 360 px the chat was 968 px wide (a grid column sized to its longest unwrapped child), pushed off the *left* edge. `scrollWidth` stayed at 360, so the first overflow metric passed. The check now also looks at each element's left edge, and the grids use `minmax(0, 1fr)` columns.
2. **A hang in the Markdown parser.** A line containing `|` followed by a line of dashes that was not a table made the paragraph loop consume nothing and spin forever (found by the fuzz test; it would have frozen the tab on such model output). Fixed with one shared table-start rule and a loop that always makes progress, plus a regression test.
3. **Bold rule.** `2 ** 3` was rendered as bold; bold now needs non-space next to the markers.
4. Smaller: login error clobbered by a generic "sign in" message, a focus ring on headings, the password toggle overlapping the typed code in the LTR field, a missing favicon request.

## Screenshots
A curated set is committed (light at every width; dark at 360 and 1280; loading and font-fallback). The rest are reproducible with the script.

| | 360 | 390 | 768 | 1280 |
|---|---|---|---|---|
| Login | ![](360-light-login.jpg) | ![](390-light-login.jpg) | ![](768-light-login.jpg) | ![](1280-light-login.jpg) |
| Wrong code (Hebrew error) | ![](360-light-login-wrong-code.jpg) | ![](390-light-login-wrong-code.jpg) | ![](768-light-login-wrong-code.jpg) | ![](1280-light-login-wrong-code.jpg) |
| Employee home | ![](360-light-employee-home.jpg) | ![](390-light-employee-home.jpg) | ![](768-light-employee-home.jpg) | ![](1280-light-employee-home.jpg) |
| Manager Copilot, empty | ![](360-light-manager-assistant-empty.jpg) | ![](390-light-manager-assistant-empty.jpg) | ![](768-light-manager-assistant-empty.jpg) | ![](1280-light-manager-assistant-empty.jpg) |
| History | ![](360-light-manager-history.jpg) | ![](390-light-manager-history.jpg) | ![](768-light-manager-history.jpg) | ![](1280-light-manager-history.jpg) |
| Rich Markdown, table, long text | ![](360-light-manager-conversation-rich.jpg) | ![](390-light-manager-conversation-rich.jpg) | ![](768-light-manager-conversation-rich.jpg) | ![](1280-light-manager-conversation-rich.jpg) |
| Legal dialog | ![](360-light-legal-dialog.jpg) | ![](390-light-legal-dialog.jpg) | ![](768-light-legal-dialog.jpg) | ![](1280-light-legal-dialog.jpg) |
| Offline error state | ![](360-light-manager-offline-error.jpg) | ![](390-light-manager-offline-error.jpg) | ![](768-light-manager-offline-error.jpg) | ![](1280-light-manager-offline-error.jpg) |
| Dark: login | ![](360-dark-login.jpg) | | | ![](1280-dark-login.jpg) |
| Dark: rich Markdown | ![](360-dark-manager-conversation-rich.jpg) | | | ![](1280-dark-manager-conversation-rich.jpg) |
| Dark: Copilot empty | ![](360-dark-manager-assistant-empty.jpg) | | | ![](1280-dark-manager-assistant-empty.jpg) |

Also: `360-light-login-loading.jpg` (spinner while signing in) and `360-light-manager-font-fallback.jpg` (Heebo blocked).

## NOT VERIFIED
- **Real devices.** No physical phone or tablet: iOS Safari (address-bar and `dvh` behaviour, input zoom, safe areas) and Android Chrome are untested. Mobile here is Chromium device emulation.
- **Other browsers.** Only Chromium (Edge) was run. Firefox and Safari rendering are untested.
- **Virtual keyboard.** How the composer behaves when the on-screen keyboard opens is untested.
- **Screen readers.** No NVDA, JAWS, VoiceOver or TalkBack run. What exists: landmarks, labels, `aria-current`, live regions, focus moves to the screen heading on navigation (verified in code and by the keyboard checks, not by listening).
- **Other widths.** 320 px and landscape phones were not measured.
- **Keyboard coverage.** Only the skip link, Tab order on login and Escape on the dialog were exercised; a complete Tab walk of every screen was not.
- **Colour contrast on rendered pixels.** Contrast is verified from the colour tokens (WCAG AA, light and dark, in `tests/test_ui_shell.py`), not measured on screenshots; text over the scrim and focus-ring contrast on every surface were not separately measured.
- **Hebrew copy** was reviewed by the author only, not by a native-speaker editor.
- **Print, high-contrast mode, zoom to 200 %, reduced motion** are handled in CSS but were not exercised.
