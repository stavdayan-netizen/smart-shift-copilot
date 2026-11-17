"""Responsive and accessibility checks for the employee availability form (issue #6), in a real Chromium browser.

The form depends on the scheduling clock, so this script needs THREE instances of the app on the same database,
each started with a different CLOCK_OVERRIDE (non-production only):

    A  2026-11-16T12:00:00+02:00   Monday: the window for 22-28 Nov is open (the employee saves a submission here)
    B  2026-11-18T09:00:00+02:00   Wednesday: after the deadline, the next window is not open yet (locked summary)
    C  2026-11-22T12:00:00+02:00   Sunday: the window for 29 Nov-5 Dec is open (new form, last week's summary below)

    python scripts/ui_check_availability.py --a http://localhost:8781 --b http://localhost:8782 --c http://localhost:8783 \
        --employee "דנה=XXXXX-XXXXX" ... (eight of them, from `python -m app.seed`) --out docs/ui-checks/m1-2

It reuses the browser driver and measurements of scripts/ui_check.py: per viewport (360, 390, 768, 1280) and scheme
(light, dark) it records overflow on both edges, interactive targets under 44 px, direction, Heebo, console errors
and screenshots, and it checks the form's behaviour: the exact heading and notices, the per-day shortcuts, the
selection counters, the zero-shift refusal, the 1,000-character counter, saving and editing, the not-open notice,
the locked summary and that the window-state texts are Hebrew. Use only against a disposable database with fictional data.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ui_check", HERE / "ui_check.py")
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)

HEADING = "הגשת משמרות לשבוע הבא"
OPENING = "הגשת המשמרות לשבוע הבא תיפתח לאחר פרסום סידור העבודה לשבוע הקרוב, או ביום חמישי בשעה 22:00 – המוקדם מביניהם"
FREE_NOTICE = "נשתדל להתחשב בבקשות ככל האפשר, בהתאם לצורכי העסק ולאילוצי השיבוץ, אך אין התחייבות שניתן יהיה להיענות לכולן."
EDIT_UNTIL = "אפשר להגיש ולערוך את ההגשה עד יום שלישי בשעה 22:00."   # shown while the window is not open
DEADLINE_A = "ההגשה פתוחה עד יום שלישי, 17.11.26 בשעה 22:00. אפשר לערוך את ההגשה עד למועד זה."
DEADLINE_C = "ההגשה פתוחה עד יום שלישי, 24.11.26 בשעה 22:00. אפשר לערוך את ההגשה עד למועד זה."
INSTRUCTION = "סמנו את המשמרות שבהן תוכלו לעבוד בכל יום."
FREE_HELP = "למשל: העדפה למשמרות בוקר, מספר משמרות רצוי בשבוע או בקשות אישיות נוספות."

PROBE = r"""
(() => {
  const q = (s) => [...document.querySelectorAll(s)];
  const txt = (s) => (document.querySelector(s) || {}).textContent || '';
  return {
    h1: txt('#main h1'),
    bodyText: (document.getElementById('avail-body') || {}).innerText || '',
    dayCards: q('.day-card').length,
    shortcutButtons: q('.shortcuts .btn').length,
    checkboxes: q('.check input').length,
    checked: q('.check input:checked').length,
    saveDisabled: (document.getElementById('btn-save') || {}).disabled,
    saveLabel: txt('#btn-save'),
    help: txt('#save-help'),
    note: txt('#save-note'),
    counter: txt('#free-count'),
    counterOver: !!document.querySelector('.counter.over'),
    chips: q('.chip').length,
    status: txt('#submission-status'),
    statusInBar: !!document.querySelector('.submit-bar #submission-status'),
    firstCardOff: !!document.querySelector('.day-card.is-off'),
    unsetCards: q('.day-card.is-unset').length, offCards: q('.day-card.is-off').length, errorCards: q('.day-card.has-error').map((c) => c.id),
    slotsError: (document.getElementById('slots-error') && !document.getElementById('slots-error').hidden) ? document.getElementById('slots-error').innerText : '',
    legacyNotice: txt('#legacy-notice'),
    focusedDay: (document.activeElement && document.activeElement.closest('.day-card')) ? document.activeElement.closest('.day-card').id : '',
    firstErrorInView: (() => { const c = document.querySelector('.day-card.has-error'); if (!c) return null; const r = c.getBoundingClientRect(); return r.top >= 0 && r.top < innerHeight; })(),
    dayCounts: q('.day-card .day-count').map((n) => n.textContent),
    layout: q('.day-card').map((c) => {
      const r = c.getBoundingClientRect(), k = c.querySelector('.checks').getBoundingClientRect(), s = c.querySelector('.shortcuts').getBoundingClientRect();
      return { top: Math.round(r.top), left: Math.round(r.left), width: Math.round(r.width), checksTop: Math.round(k.top), checksBottom: Math.round(k.bottom),
               shortcutsTop: Math.round(s.top), shortcutsLeft: Math.round(s.left), shortcutsRight: Math.round(s.right), checksLeft: Math.round(k.left), checksRight: Math.round(k.right) };
    }),
    locked: !!document.querySelector('.locked-card'),
    lockedText: txt('.locked-card'),
    hasForm: !!document.getElementById('avail-form'),
    firstDayCount: txt('#main .day-card .day-count'),
  };
})()
"""


def run(args) -> int:
    exe = args.browser or next((b for b in ui.BROWSERS if Path(b).exists()), None)
    if not exe:
        print("no Chrome/Edge found; pass --browser", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    b = ui.Browser(exe)
    results: dict = {"browser": exe, "checks": []}
    failures: list[str] = []

    def settle(seconds=0.6):
        b.pump(seconds)

    def js(expr, wait=True):
        return b.js(expr, wait)

    def probe():
        return js(PROBE)

    def record(vp, scheme, name, note="", expected=()):
        m = b.js(ui.MEASURE)
        m["errors"] = [e for e in b.console if not any(x in e for x in expected)]
        m["expectedErrors"] = [e for e in b.console if any(x in e for x in expected)]
        b.console.clear()
        m.update({"vp": vp, "scheme": scheme, "screen": name, "note": note, "probe": probe()})
        b.shot(out / f"{vp}-{scheme}-{name}.jpg")
        results["checks"].append(m)
        problems = []
        if m["pageOverflowsX"]:
            problems.append("page overflows horizontally")
        if m["elementsWiderThanViewport"]:
            problems.append("elements past an edge: " + ", ".join(m["elementsWiderThanViewport"][:3]))
        if m["smallTargets"]:
            problems.append("targets under 44px: " + str(m["smallTargets"][:4]))
        if m["dir"] != "rtl" or m["lang"] != "he":
            problems.append("not lang=he dir=rtl")
        if m["errors"]:
            problems.append("console errors: " + str(m["errors"][:2]))
        if m["scheme"] != scheme:
            problems.append("colour scheme emulation failed")
        if problems:
            failures.append(f"{vp}/{scheme}/{name}: " + "; ".join(problems))
        return m

    def expect(cond, message):
        if not cond:
            failures.append(message)

    def fresh(base, w, h, mobile, scheme, clear=True):
        b.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=mobile)
        b.call("Emulation.setTouchEmulationEnabled", enabled=mobile)
        b.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
        if clear:
            b.call("Network.clearBrowserCookies")
        b.call("Page.navigate", url=base + "/")
        settle(1.2)

    who = {"name": "", "code": ""}

    def login():
        js(f"(() => {{ document.getElementById('login-name').value = {json.dumps(who['name'])}; document.getElementById('login-code').value = {json.dumps(who['code'])}; document.getElementById('login-form').requestSubmit(); }})()", False)
        settle(1.6)

    def click(selector, nth=0):
        js(f"document.querySelectorAll({json.dumps(selector)})[{nth}].click()", False)
        settle(0.25)

    def day_button(day_index, which):
        """which: 0 = 'כל המשמרות', 1 = 'לא זמין/ה'"""
        js(f"document.querySelectorAll('.day-card')[{day_index}].querySelectorAll('.shortcuts .btn')[{which}].click()", False)
        settle(0.25)

    def finish_days():
        """Give every day without a choice the explicit choice 'לא זמין/ה' (the form refuses to save otherwise)."""
        js("document.querySelectorAll('.day-card.is-unset').forEach((c) => c.querySelector('[data-role=none]').click())", False)
        settle(0.3)

    def set_text(text):
        js(f"(() => {{ const t = document.getElementById('free-text'); t.value = {json.dumps(text)}; t.dispatchEvent(new Event('input', {{bubbles: true}})); }})()", False)
        settle(0.25)

    try:
        employees = [e.split("=", 1) for e in args.employee]
        iteration = 0
        for vp, w, h, mobile in ui.VIEWPORTS:
            for scheme in ui.SCHEMES:
                full = scheme == "light"
                who["name"], who["code"] = employees[iteration]   # a fresh employee each time, so every run starts with an empty form
                iteration += 1
                # ---- A: the window is open; build and save a submission for 22-28 Nov
                fresh(args.a, w, h, mobile, scheme)
                login()
                p = probe()
                expect(p["h1"] == HEADING, f"{vp}/{scheme}: heading is {p['h1']!r}")
                expect(p["dayCards"] == 7 and p["shortcutButtons"] == 14 and p["checkboxes"] == 14, f"{vp}/{scheme}: form structure {p}")
                expect(DEADLINE_A in p["bodyText"] and FREE_NOTICE in p["bodyText"], f"{vp}/{scheme}: the one-line deadline notice or the free-text notice is missing")
                expect(EDIT_UNTIL not in p["bodyText"] and "נותר:" not in p["bodyText"], f"{vp}/{scheme}: the old edit-until line or a countdown is still shown")
                expect(INSTRUCTION in p["bodyText"] and FREE_HELP in p["bodyText"], f"{vp}/{scheme}: instruction or free-text example is wrong")
                expect(p["chips"] == 0, f"{vp}/{scheme}: status badges are still shown")
                expect(p["statusInBar"] and p["status"] == "טרם הוגשה", f"{vp}/{scheme}: submission status next to the submit button is {p['status']!r}")
                lay = p["layout"]
                expect(len(lay) == 7 and all(lay[i]["top"] < lay[i + 1]["top"] and lay[i]["left"] == lay[0]["left"] and lay[i]["width"] == lay[0]["width"] for i in range(6)), f"{vp}/{scheme}: day cards are not stacked one per row")
                expect(all(c["shortcutsTop"] < c["checksBottom"] and (c["shortcutsRight"] <= c["checksLeft"] or c["shortcutsLeft"] >= c["checksRight"]) for c in lay), f"{vp}/{scheme}: 'כל המשמרות' / 'לא זמין/ה' are not beside the shift choices")
                expect(p["unsetCards"] == 7 and p["offCards"] == 0, f"{vp}/{scheme}: untouched days must be distinct from unavailable ones: {p['unsetCards']} untouched, {p['offCards']} unavailable")
                expect(set(p["dayCounts"]) == {"לא נבחרה זמינות"}, f"{vp}/{scheme}: untouched days must say so: {p['dayCounts']}")
                expect(p["saveDisabled"] is False and "נותרו 7" in p["help"], f"{vp}/{scheme}: the empty form can be submitted to get the explanation: {p['help']!r}")
                record(vp, scheme, "form-empty", note="open window, nothing chosen: every day untouched", expected=("/api/me",))
                click("#btn-save")
                settle(0.9)
                p = probe()
                expect(p["slotsError"].strip() == "יש לבחור זמינות בימים: יום ראשון, יום שני, יום שלישי, יום רביעי, יום חמישי, יום שישי, יום שבת", f"{vp}/{scheme}: the blocked save must name all seven days: {p['slotsError']!r}")
                expect(len(p["errorCards"]) == 7 and p["focusedDay"] == p["errorCards"][0] and p["firstErrorInView"], f"{vp}/{scheme}: all seven days marked, focus and scroll on the first: {p['errorCards']} {p['focusedDay']} {p['firstErrorInView']}")
                record(vp, scheme, "form-blocked-all-days", note="save blocked: the message names all seven days and every day is marked")
                if full:
                    # the shortcuts and single checkboxes
                    day_button(0, 0)
                    expect(probe()["checked"] == 2, f"{vp}: 'כל המשמרות' did not tick both shifts")
                    day_button(0, 1)
                    st = js("(() => { const c = document.querySelectorAll('.day-card')[0]; const n = c.querySelector('[data-role=none]'); return {checked: c.querySelectorAll('.check input:checked').length, disabled: [...c.querySelectorAll('.check input')].every((i) => i.disabled), pressed: n.getAttribute('aria-pressed'), active: n.classList.contains('is-active')}; })()")
                    expect(probe()["checked"] == 0 and st["checked"] == 0 and st["disabled"] and st["pressed"] == "true" and st["active"], f"{vp}: 'לא זמין/ה' must clear, disable and show an active state: {st}")
                    record(vp, scheme, "day-unavailable", note="'לא זמין/ה' active on the first day: shifts cleared and disabled")
                    day_button(0, 1)
                    st = js("(() => { const c = document.querySelectorAll('.day-card')[0]; const n = c.querySelector('[data-role=none]'); return {disabled: [...c.querySelectorAll('.check input')].some((i) => i.disabled), pressed: n.getAttribute('aria-pressed')}; })()")
                    expect(not st["disabled"] and st["pressed"] == "false", f"{vp}: a second click on 'לא זמין/ה' must switch it off and re-enable the shifts: {st}")
                    day_button(0, 1)
                    day_button(0, 0)
                    st = js("(() => { const c = document.querySelectorAll('.day-card')[0]; return {checked: c.querySelectorAll('.check input:checked').length, off: c.classList.contains('is-off')}; })()")
                    expect(st["checked"] == 2 and not st["off"], f"{vp}: 'כל המשמרות' must reset the unavailable state and select both shifts: {st}")
                    day_button(0, 1)
                    day_button(0, 1)
                    click(".day-card .check input", 0)
                    p = probe()
                    expect(p["checked"] == 1 and "1" in p["firstDayCount"], f"{vp}: single checkbox not reflected: {p['firstDayCount']!r}")
                    day_button(0, 0)
                    js("document.querySelectorAll('.day-card')[0].querySelectorAll('.check input')[1].click()", False)
                    settle(0.25)
                    expect(probe()["checked"] == 1, f"{vp}: unticking one shift after 'כל המשמרות' failed")
                    # too much text
                    set_text("בקשה ארוכה with English words. " * 40)
                    p = probe()
                    expect(p["counterOver"] and p["saveDisabled"], f"{vp}: counter over 1,000 must disable saving")
                    js("document.getElementById('free-text').scrollIntoView({block: 'center'})", False)
                    settle(0.3)
                    record(vp, scheme, "form-text-too-long", note="1,000 character limit exceeded (scrolled to the free-text field)")
                    set_text("מעדיפה משמרות בוקר, ויום חמישי חשוב לי שיהיה פנוי. thanks!")
                    day_button(2, 0)
                    day_button(4, 0)
                    js("document.getElementById('free-text').scrollIntoView({block: 'center'})", False)
                    settle(0.3)
                    record(vp, scheme, "form-filled", note="three days selected, free text entered (scrolled to the free-text field)")
                    click("#btn-save")
                    settle(0.9)
                    p = probe()
                    expect(p["slotsError"].startswith("יש לבחור זמינות ב") and p["status"] == "טרם הוגשה", f"{vp}: an incomplete form must not save: {p['slotsError']!r} {p['status']!r}")
                    expect(len(p["errorCards"]) == p["unsetCards"] and p["focusedDay"] == p["errorCards"][0] and p["firstErrorInView"], f"{vp}: the first incomplete day must be scrolled to and focused: {p['errorCards']} {p['focusedDay']}")
                    record(vp, scheme, "form-blocked-some-days", note="three days chosen, the others untouched: the message names the missing days and marks them")
                    finish_days()
                    p = probe()
                    expect(p["slotsError"] == "" and not p["errorCards"] and p["unsetCards"] == 0 and p["offCards"] == 4, f"{vp}: choosing the remaining days must clear the message: {p['slotsError']!r} {p['errorCards']} off={p['offCards']}")
                    click("#btn-save")
                    settle(1.5)
                    p = probe()
                    expect("נשמרה" in p["note"] and p["status"].startswith("הוגשה"), f"{vp}: save not confirmed: {p['note']!r} {p['status']!r}")
                    record(vp, scheme, "form-saved", note="saved confirmation")
                    # reload keeps it; editing then saving updates it
                    fresh(args.a, w, h, mobile, scheme, clear=False)
                    p = probe()
                    expect(p["checked"] == 5 and p["status"].startswith("הוגשה") and p["offCards"] == 4 and p["unsetCards"] == 0 and p["legacyNotice"] == "", f"{vp}: the saved selections (shifts and explicit unavailable days) must be restored: {p['checked']} off={p['offCards']} unset={p['unsetCards']} {p['status']!r}")
                    day_button(4, 1)
                    expect("שלא נשמרו" in probe()["help"], f"{vp}: unsaved changes not indicated")
                    click("#btn-save")
                    settle(1.2)
                    expect(probe()["checked"] == 3, f"{vp}: update not saved")
                else:
                    day_button(0, 0)
                    set_text("בקשה קצרה")
                    finish_days()
                    click("#btn-save")
                    settle(1.2)
                    record(vp, scheme, "form-saved")
                # ---- B: after the deadline, the next window is not open yet
                fresh(args.b, w, h, mobile, scheme, clear=False)
                p = probe()
                expect(not p["hasForm"] and OPENING in p["bodyText"], f"{vp}/{scheme}: not-open notice missing or form shown")
                expect(EDIT_UNTIL in p["bodyText"] and p["locked"] and "נעולה" in p["lockedText"], f"{vp}/{scheme}: locked summary or edit-until missing")
                record(vp, scheme, "not-open-with-locked", note="opening notice and the locked previous submission")
                # ---- C: the next window is open; last week's submission stays below as a read-only summary
                fresh(args.c, w, h, mobile, scheme, clear=False)
                p = probe()
                expect(p["hasForm"] and p["locked"] and p["unsetCards"] == 7 and "נותרו 7" in p["help"], f"{vp}/{scheme}: open form with locked summary and seven untouched days expected")
                expect(DEADLINE_C in p["bodyText"], f"{vp}/{scheme}: the deadline line for the next week is wrong")
                record(vp, scheme, "open-next-week-with-locked", note="new week form, previous week locked below")
                b.call("Network.clearBrowserCookies")
        results["failures"] = failures
    finally:
        (out / "results.json").write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
        b.close()
    print(f"{len(results['checks'])} checks, {len(failures)} problem(s)")
    for f in failures:
        print(" -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--a", required=True, help="instance with CLOCK_OVERRIDE 2026-11-16T12:00:00+02:00")
    ap.add_argument("--b", required=True, help="instance with CLOCK_OVERRIDE 2026-11-18T09:00:00+02:00")
    ap.add_argument("--c", required=True, help="instance with CLOCK_OVERRIDE 2026-11-22T12:00:00+02:00")
    ap.add_argument("--out", default="docs/ui-checks/m1-2")
    ap.add_argument("--browser")
    ap.add_argument("--employee", action="append", required=True, metavar="NAME=CODE",
                    help="eight times (one per viewport and scheme): a seeded employee and the code shown by `python -m app.seed`")
    raise SystemExit(run(ap.parse_args()))
