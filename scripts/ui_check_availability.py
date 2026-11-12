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
EDIT_UNTIL = "אפשר להגיש ולערוך את ההגשה עד יום שלישי בשעה 22:00."

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
    chips: q('.chip').map((c) => c.textContent),
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
                expect(EDIT_UNTIL in p["bodyText"] and FREE_NOTICE in p["bodyText"], f"{vp}/{scheme}: edit-until sentence or free-text notice missing")
                expect(p["saveDisabled"] is True and "לפחות משמרת אחת" in p["help"], f"{vp}/{scheme}: empty form must not be submittable")
                record(vp, scheme, "form-empty", note="open window, nothing selected, submit disabled", expected=("/api/me",))
                if full:
                    # the shortcuts and single checkboxes
                    day_button(0, 0)
                    expect(probe()["checked"] == 2, f"{vp}: 'כל המשמרות' did not tick both shifts")
                    day_button(0, 1)
                    expect(probe()["checked"] == 0, f"{vp}: 'לא זמין/ה' did not clear the day")
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
                    settle(1.5)
                    p = probe()
                    expect("נשמרה" in p["note"] and any("הוגשה" in c for c in p["chips"]), f"{vp}: save not confirmed: {p['note']!r} {p['chips']}")
                    record(vp, scheme, "form-saved", note="saved confirmation")
                    # reload keeps it; editing then saving updates it
                    fresh(args.a, w, h, mobile, scheme, clear=False)
                    p = probe()
                    expect(p["checked"] == 5 and any("הוגשה" in c for c in p["chips"]), f"{vp}: saved submission not shown after reload: {p['checked']}")
                    day_button(4, 1)
                    expect("שלא נשמרו" in probe()["help"], f"{vp}: unsaved changes not indicated")
                    click("#btn-save")
                    settle(1.2)
                    expect(probe()["checked"] == 3, f"{vp}: update not saved")
                else:
                    day_button(0, 0)
                    set_text("בקשה קצרה")
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
                expect(p["hasForm"] and p["locked"] and p["saveDisabled"], f"{vp}/{scheme}: open form with locked summary expected")
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
