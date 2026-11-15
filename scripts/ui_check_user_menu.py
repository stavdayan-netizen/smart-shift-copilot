"""Real-browser checks for the login copy and the manager user menu (ui/login-copy-and-user-menu).

    python scripts/ui_check_user_menu.py --base http://localhost:8000 --manager-password ... \
        --employee-name "דנה" --employee-code XXXXX-XXXXX --out docs/ui-checks/user-menu

Per viewport (360, 390, 768, 1280) and colour scheme it checks: the login field label is "סיסמה" and the manager hint is
gone; the manager's top-corner name opens a menu with the name, the role, "החשבון שלי" and "התנתקות"; the menu stays inside
the viewport and its items are at least 44 px; Escape and an outside click close it and Escape returns focus; the account
item navigates and closes; the logout item signs out; the employee gets the same menu (name, role "עובד/ת", account, sign out); the login intro is the new sentence.
Reuses the browser driver of scripts/ui_check.py. Use only against a local or test instance with fictional data.
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

MENU_PROBE = r"""
(() => {
  const menu = document.getElementById('user-menu'), btn = document.getElementById('user-btn');
  const r = menu.getBoundingClientRect(), vw = document.documentElement.clientWidth;
  const items = [...menu.querySelectorAll('.user-menu-item')];
  return {
    hidden: menu.hidden, expanded: btn.getAttribute('aria-expanded'),
    left: Math.round(r.left), right: Math.round(r.right), vw,
    insideViewport: r.left >= 0 && r.right <= vw,
    itemLabels: items.map((i) => i.textContent.trim()),
    itemHeights: items.map((i) => Math.round(i.getBoundingClientRect().height)),
    who: (menu.querySelector('.user-menu-who') || {}).innerText || '',
    focusInMenu: menu.contains(document.activeElement),
    focusOnButton: document.activeElement === btn,
    hash: location.hash,
    btnHeight: Math.round(btn.getBoundingClientRect().height),
  };
})()
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--out", default="docs/ui-checks/user-menu")
    ap.add_argument("--browser")
    ap.add_argument("--manager-name", default="manager")
    ap.add_argument("--manager-password", required=True)
    ap.add_argument("--employee-name", required=True)
    ap.add_argument("--employee-code", required=True)
    args = ap.parse_args()
    exe = args.browser or next((p for p in ui.BROWSERS if Path(p).exists()), None) or shutil.which("chrome") or shutil.which("msedge")
    if not exe:
        print("no Chrome/Edge found; pass --browser", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    b = ui.Browser(exe)
    failures: list[str] = []
    results = []

    def settle(s=0.5):
        b.pump(s)

    def check(cond, msg):
        if not cond:
            failures.append(msg)

    def login(name, code):
        b.js(f"(() => {{ document.getElementById('login-name').value = {json.dumps(name)}; document.getElementById('login-code').value = {json.dumps(code)}; document.getElementById('login-form').requestSubmit(); }})()", False)
        settle(1.2)

    def click(sel):
        b.js(f"document.querySelector({json.dumps(sel)}).click()", False)
        settle(0.4)

    def key(k):
        b.call("Input.dispatchKeyEvent", type="keyDown", key=k, code=k)
        b.call("Input.dispatchKeyEvent", type="keyUp", key=k, code=k)
        settle(0.3)

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
                # login screen copy
                label = b.js("document.querySelector('label[for=login-code]').textContent.trim()")
                check(label == "סיסמה", f"{tag}: login label is {label!r}")
                check(b.js("!document.body.innerText.includes('כאן מזינים את הסיסמה')"), f"{tag}: the manager hint is still on the login screen")
                check(b.js("!document.getElementById('login-code-hint')"), f"{tag}: login-code-hint element still exists")
                b.shot(out / f"{vp}-{scheme}-login.jpg")
                # manager menu
                login(args.manager_name, args.manager_password)
                check(b.js("document.getElementById('view-app').hidden === false"), f"{tag}: manager login failed")
                p = b.js(MENU_PROBE)
                check(p["hidden"] and p["expanded"] == "false", f"{tag}: menu should start closed")
                check(p["btnHeight"] >= 44, f"{tag}: user button is {p['btnHeight']}px high")
                b.shot(out / f"{vp}-{scheme}-manager-closed.jpg")
                click("#user-btn")
                p = b.js(MENU_PROBE)
                results.append({"viewport": vp, "scheme": scheme, **p})
                check(not p["hidden"] and p["expanded"] == "true", f"{tag}: menu did not open")
                check(p["itemLabels"] == ["החשבון שלי", "התנתקות"], f"{tag}: items are {p['itemLabels']}")
                check(args.manager_name in p["who"] and "מנהל/ת" in p["who"], f"{tag}: who block is {p['who']!r}")
                check(p["insideViewport"], f"{tag}: menu leaves the viewport ({p['left']}..{p['right']} of {p['vw']})")
                check(all(x >= 44 for x in p["itemHeights"]), f"{tag}: item heights {p['itemHeights']}")
                check(p["focusInMenu"], f"{tag}: focus did not move into the menu")
                b.shot(out / f"{vp}-{scheme}-manager-menu-open.jpg")
                key("ArrowDown")
                key("Escape")
                p = b.js(MENU_PROBE)
                check(p["hidden"] and p["focusOnButton"], f"{tag}: Escape should close and return focus (hidden={p['hidden']}, focusOnButton={p['focusOnButton']})")
                click("#user-btn")
                b.js("document.getElementById('main').click()", False)
                settle(0.3)
                check(b.js(MENU_PROBE)["hidden"], f"{tag}: an outside click should close the menu")
                click("#user-btn")
                b.js("document.querySelectorAll('.user-menu-item')[0].click()", False)
                settle(0.6)
                p = b.js(MENU_PROBE)
                check(p["hash"] == "#/account" and p["hidden"], f"{tag}: account item: hash {p['hash']}, hidden {p['hidden']}")
                click("#user-btn")
                b.js("document.querySelectorAll('.user-menu-item')[1].click()", False)
                settle(1.0)
                check(b.js("document.getElementById('view-login').hidden === false"), f"{tag}: logout item did not return to the login screen")
                # employee: the same menu, with the employee's name and role
                login(args.employee_name, args.employee_code)
                click("#user-btn")
                p = b.js(MENU_PROBE)
                check(not p["hidden"] and p["itemLabels"] == ["החשבון שלי", "התנתקות"], f"{tag}: employee menu items {p['itemLabels']}")
                check(args.employee_name in p["who"] and "עובד/ת" in p["who"], f"{tag}: employee who block is {p['who']!r}")
                check(p["insideViewport"] and all(x >= 44 for x in p["itemHeights"]), f"{tag}: employee menu geometry {p['left']}..{p['right']}/{p['vw']} {p['itemHeights']}")
                b.shot(out / f"{vp}-{scheme}-employee-menu-open.jpg")
                key("Escape")
                click("#user-btn")
                b.js("document.querySelectorAll('.user-menu-item')[0].click()", False)
                settle(0.6)
                check(b.js(MENU_PROBE)["hash"] == "#/account", f"{tag}: employee account item did not navigate")
                click("#user-btn")
                b.js("document.querySelectorAll('.user-menu-item')[1].click()", False)
                settle(1.0)
                check(b.js("document.getElementById('view-login').hidden === false"), f"{tag}: employee logout item did not return to login")
                intro = b.js("(document.querySelector('#view-login p') || {}).textContent || ''")
                check("הזינו את שם המשתמש והסיסמה שלכם כדי להיכנס למערכת." in b.js("document.getElementById('view-login').innerText"), f"{tag}: login intro text is wrong")
                errs = list(b.console)
                b.console.clear()
                check(not [x for x in errs if "401" not in x], f"{tag}: console errors {errs[:2]}")
    finally:
        b.close()
    (out / "results.json").write_text(json.dumps({"browser": exe, "base": args.base, "results": results, "failures": failures}, indent=1, ensure_ascii=False), encoding="utf-8")
    print(f"{len(ui.VIEWPORTS) * len(ui.SCHEMES)} viewport/scheme runs, {len(failures)} problem(s)")
    for f in failures:
        print(" -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
