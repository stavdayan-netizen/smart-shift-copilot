"""Real-browser checks for the manager's read-only "הגשות עובדים" tab.

    python scripts/ui_check_submissions.py --base http://localhost:8000 --manager-password ... \
        --employee-name "דנה" --employee-code XXXXX-XXXXX --out docs/ui-checks/submissions-tab [--expect-leave]

Per viewport (360, 390, 768, 1280) and colour scheme: the tab exists in the manager's navigation; the counts tiles add up
to one card per employee; a card expands and collapses, shows the exact shifts and the free text as plain text; the page
does not overflow; summaries are at least 44 px high; an employee has no such tab and cannot open the route. With
--expect-leave the instance was started with injected approved leave (tests only) and the leave badges must show.
Reuses the driver of scripts/ui_check.py. Use only against a local or test instance with fictional data.
"""
from __future__ import annotations

import argparse
import importlib.util
import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("ui_check", HERE / "ui_check.py")
ui = importlib.util.module_from_spec(spec)
spec.loader.exec_module(ui)

PROBE = r"""
(() => {
  const q = (s) => [...document.querySelectorAll(s)];
  const cards = q('.emp-card');
  return {
    hash: location.hash, h1: (document.querySelector('#main h1') || {}).textContent || '',
    navHas: q('#nav a').map((a) => a.getAttribute('data-route')),
    tiles: q('.stat').map((t) => [t.querySelector('.stat-l').textContent, parseInt(t.querySelector('.stat-n').textContent, 10)]),
    cards: cards.length, open: cards.filter((c) => c.open).length,
    statuses: cards.map((c) => c.dataset.status),
    summaryHeights: q('.emp-summary').map((s) => Math.round(s.getBoundingClientRect().height)),
    noticeText: (document.getElementById('subs-notice') || {}).innerText || '',
    noticeTop: Math.round((document.getElementById('subs-notice') || document.body).getBoundingClientRect().top),
    h1Bottom: Math.round((document.querySelector('#main h1') || document.body).getBoundingClientRect().bottom),
    tilesTop: Math.round((document.querySelector('.stat-grid') || document.body).getBoundingClientRect().top),
    badges: q('.badge').map((b) => b.textContent),
    navAccount: !!document.querySelector('#nav a[data-route=account]'),
    navLabelCentered: (() => { const a = document.querySelector('#nav a[data-route=submissions]'); if (!a) return null;
      const ic = a.querySelector('svg').getBoundingClientRect(), tx = a.querySelector('span').getBoundingClientRect();
      return { dx: Math.round(Math.abs((ic.left + ic.right) / 2 - (tx.left + tx.right) / 2)), align: getComputedStyle(a).textAlign }; })(),
    readOnlyText: document.body.innerText.includes('תצוגה לקריאה בלבד'),
    openCardDays: q('.emp-card[open] .emp-day').length,
    openCardRows: q('.emp-card[open] .emp-day').map((r) => { const n = r.querySelector('.emp-day-name').getBoundingClientRect(), s = r.querySelector('.emp-shifts').getBoundingClientRect();
      return { besideOrAligned: Math.abs(n.top - s.top) < 12 && (s.right <= n.left || s.left >= n.right), width: Math.round(r.getBoundingClientRect().width) }; }),
    openCardHasPrefs: q('.emp-card[open] h3').some((h) => h.textContent.includes('בקשות והעדפות')),
    detailText: cards.filter((c) => c.open).map((c) => c.querySelector('.emp-detail').innerText).join('\n'),
    htmlInFreeText: !!document.querySelector('.emp-detail .free-text b, .emp-detail .free-text script, .emp-detail .free-text img'),
  };
})()
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--out", default="docs/ui-checks/submissions-tab")
    ap.add_argument("--browser")
    ap.add_argument("--manager-name", default="manager")
    ap.add_argument("--manager-password", required=True)
    ap.add_argument("--employee-name", required=True)
    ap.add_argument("--employee-code", required=True)
    ap.add_argument("--expect-leave", action="store_true")
    ap.add_argument("--expect-notice", help="the exact notice text expected under the heading (depends on the instance clock)")
    args = ap.parse_args()
    exe = args.browser or next((p for p in ui.BROWSERS if Path(p).exists()), None) or shutil.which("chrome") or shutil.which("msedge")
    if not exe:
        print("no Chrome/Edge found; pass --browser", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    b = ui.Browser(exe)
    failures: list[str] = []
    checks = []

    def settle(s=0.6):
        b.pump(s)

    def check(cond, msg):
        if not cond:
            failures.append(msg)

    def login(name, code):
        b.js(f"(() => {{ document.getElementById('login-name').value = {json.dumps(name)}; document.getElementById('login-code').value = {json.dumps(code)}; document.getElementById('login-form').requestSubmit(); }})()", False)
        settle(1.4)

    try:
        for vp, w, h, mobile in ui.VIEWPORTS:
            for scheme in ui.SCHEMES:
                tag = f"{vp}/{scheme}"
                b.call("Emulation.setDeviceMetricsOverride", width=w, height=h, deviceScaleFactor=1, mobile=mobile)
                b.call("Emulation.setTouchEmulationEnabled", enabled=mobile)
                b.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
                b.call("Network.clearBrowserCookies")
                b.call("Page.navigate", url=args.base + "/")
                settle(1.2)
                login(args.manager_name, args.manager_password)
                p = b.js(PROBE)
                check("submissions" in p["navHas"], f"{tag}: the manager has no submissions tab ({p['navHas']})")
                b.js("location.hash = '#/submissions'", False)
                settle(1.2)
                p = b.js(PROBE)
                checks.append({"vp": vp, "scheme": scheme, **{k: p[k] for k in ("cards", "tiles", "statuses", "badges")}})
                check(p["h1"] == "הגשות עובדים", f"{tag}: heading is {p['h1']!r}")
                if args.expect_notice:
                    check(p["noticeText"].strip() == args.expect_notice, f"{tag}: notice is {p['noticeText']!r}")
                check(p["h1Bottom"] <= p["noticeTop"] < p["tilesTop"], f"{tag}: the notice must sit below the heading and above the counts ({p['h1Bottom']}, {p['noticeTop']}, {p['tilesTop']})")
                tiles = dict(p["tiles"])
                total, sub, miss = tiles.get("סה״כ עובדים"), tiles.get("הגישו"), tiles.get("טרם הגישו")
                exempt = tiles.get("פטורים מהגשה", 0)
                check(total == p["cards"] and total == sub + miss + exempt, f"{tag}: tiles {tiles} do not add up to {p['cards']} cards")
                check(p["statuses"].count("submitted") == sub and p["statuses"].count("missing") == miss and p["statuses"].count("exempt") == exempt, f"{tag}: card statuses disagree with the tiles")
                check(p["open"] == 0 and all(x >= 44 for x in p["summaryHeights"]), f"{tag}: cards start collapsed and summaries are >= 44 px: {p['summaryHeights']}")
                rank = {"missing": 0, "exempt": 1, "submitted": 2}
                check([rank[x] for x in p["statuses"]] == sorted(rank[x] for x in p["statuses"]) and p["statuses"][0] == "missing", f"{tag}: missing submissions must be listed first: {p['statuses']}")
                check(any(x == "טרם הוגשה זמינות" for x in p["badges"]) and any(x == "הוגשה זמינות" for x in p["badges"]), f"{tag}: badge texts are {sorted(set(p['badges']))}")
                check(not p["navAccount"], f"{tag}: the account link is still in the navigation")
                nl = p["navLabelCentered"]
                check(nl is not None and nl["dx"] <= 2 and nl["align"] == "center", f"{tag}: the submissions nav label is not centred under its icon: {nl}")
                check(not p["readOnlyText"], f"{tag}: the redundant read-only line is still shown")
                if args.expect_leave:
                    check(any("חופשה מאושרת לכל השבוע" in x for x in p["badges"]) and any(x.startswith("חופשה מאושרת:") for x in p["badges"]), f"{tag}: leave badges missing: {p['badges']}")
                    check(exempt >= 1, f"{tag}: no exempt employee counted")
                else:
                    check(not any("חופשה" in x for x in p["badges"]) and exempt == 0, f"{tag}: leave shown although no leave data exists: {p['badges']}")
                b.shot(out / f"{vp}-{scheme}-collapsed.jpg")
                # expand the first submitted card through a real click on its summary
                b.js("document.querySelector('.emp-card[data-status=submitted] summary').click()", False)
                settle(0.4)
                p = b.js(PROBE)
                check(p["open"] == 1 and "משמרות שהוגשו" in p["detailText"] and "–" in p["detailText"], f"{tag}: expanding did not show shifts: {p['detailText'][:80]!r}")
                check(p["openCardDays"] == 7 and all(r["besideOrAligned"] for r in p["openCardRows"]), f"{tag}: the seven day rows are not compact with the shifts beside each day: {p['openCardRows']}")
                check(p["openCardHasPrefs"], f"{tag}: an employee with preferences must show the preferences section")
                check(not p["htmlInFreeText"], f"{tag}: free text was rendered as HTML")
                b.js("document.querySelector('.emp-card[open]').scrollIntoView({block: 'start'})", False)
                settle(0.3)
                m = b.js(ui.MEASURE)
                check(not m["pageOverflowsX"] and not m["elementsWiderThanViewport"], f"{tag}: overflow {m['elementsWiderThanViewport'][:2]}")
                check(m["dir"] == "rtl" and m["lang"] == "he", f"{tag}: not rtl/he")
                b.shot(out / f"{vp}-{scheme}-expanded.jpg")
                b.js("document.querySelector('.emp-card[open] summary').click()", False)
                settle(0.3)
                check(b.js(PROBE)["open"] == 0, f"{tag}: the card did not collapse")
                # a submitted employee WITHOUT a free text: the preferences section must be hidden
                b.js("(() => { const c = [...document.querySelectorAll('.emp-card[data-status=submitted]')].find((x) => !x.querySelector('.free-text')); c.querySelector('summary').click(); })()", False)
                settle(0.3)
                p = b.js(PROBE)
                check(p["open"] == 1 and not p["openCardHasPrefs"], f"{tag}: an empty preferences section is still shown")
                b.js("document.querySelector('.emp-card[open] summary').click()", False)
                settle(0.2)
                errs = [e for e in b.console if "401" not in e]
                b.console.clear()
                check(not errs, f"{tag}: console errors {errs[:2]}")
                # an employee has no such tab and cannot open the route
                b.js("document.getElementById('user-btn').click()", False)
                settle(0.3)
                b.js("document.querySelectorAll('.user-menu-item')[1].click()", False)
                settle(1.0)
                login(args.employee_name, args.employee_code)
                p = b.js(PROBE)
                check("submissions" not in p["navHas"], f"{tag}: the employee sees the tab")
                b.js("location.hash = '#/submissions'", False)
                settle(0.8)
                check(b.js("location.hash") != "#/submissions", f"{tag}: the employee could open the route")
                b.console.clear()
    finally:
        b.close()
    (out / "results.json").write_text(json.dumps({"browser": exe, "base": args.base, "checks": checks, "failures": failures}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(checks)} viewport/scheme runs, {len(failures)} problem(s)")
    for f in failures:
        print(" -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
