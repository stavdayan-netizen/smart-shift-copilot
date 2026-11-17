"""Real-browser checks for the Shiftimizer branding (login logo, header icon and name, page title, favicons, manifest).

    python scripts/ui_check_brand.py --base http://localhost:8000 --manager-password ... \
        --employee-name "דנה" --employee-code XXXXX-XXXXX --out docs/ui-checks/branding

Per viewport (360, 390, 768, 1280) and colour scheme: the full approved logo (with its tagline) loads at its native 1872x538
on the login screen and fits without overflow; there is no plate behind it; in dark mode the browser chooses the derived light-wordmark file (wordmark pixels bright, star still white), in light mode the approved file as delivered; after login the header shows the approved
icon (loaded, 32 px) and the name "Shiftimizer" for the manager and the employee; the browser title is "Shiftimizer"; every icon
and manifest URL declared in the page answers 200; the old product name appears nowhere in the visible text; no console errors.
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

LOGIN_PROBE = r"""
(() => {
  const img = document.querySelector('.login-logo img'), plate = document.querySelector('.login-logo');
  const r = img.getBoundingClientRect(), vw = document.documentElement.clientWidth;
  // mean brightness of the opaque wordmark pixels (rows 113-319, right of the icon) of the file the browser actually chose
  const cv = document.createElement('canvas'); cv.width = img.naturalWidth; cv.height = img.naturalHeight;
  const cx = cv.getContext('2d'); cx.drawImage(img, 0, 0);
  const d = cx.getImageData(586, 113, 1200, 206).data; let sum = 0, n = 0;
  for (let i = 0; i < d.length; i += 4) if (d[i + 3] > 250 && !(d[i] > 200 && d[i + 2] < 120)) { sum += (d[i] + d[i + 1] + d[i + 2]) / 3; n++; }
  const star = cx.getImageData(405, 150, 1, 1).data;   // the centre of the star
  return { title: document.title, src: img.currentSrc, loaded: img.complete && img.naturalWidth === 1872 && img.naturalHeight === 538, alt: img.alt,
           width: Math.round(r.width), inside: r.left >= 0 && r.right <= vw, plateBg: getComputedStyle(plate).backgroundColor,
           wordmarkBrightness: Math.round(sum / Math.max(n, 1)), starAlpha: star[3], starRgb: [star[0], star[1], star[2]],
           text: document.body.innerText, dir: document.documentElement.dir };
})()
"""
APP_PROBE = r"""
(() => {
  const icon = document.querySelector('.appbar .brand-icon'), name = document.querySelector('.appbar .brand span');
  const r = icon.getBoundingClientRect();
  return { title: document.title, loaded: icon.complete && icon.naturalWidth === 64, size: Math.round(r.width), name: name.textContent,
           text: document.body.innerText, accent: getComputedStyle(document.documentElement).getPropertyValue('--accent').trim() };
})()
"""
LINKS = r"""
(async () => {
  const urls = [...document.querySelectorAll('link[rel~=icon], link[rel=apple-touch-icon], link[rel=manifest]')].map((l) => l.href);
  const out = [];
  for (const u of urls) { const r = await fetch(u); out.push([new URL(u).pathname, r.status]); }
  const m = await (await fetch(document.querySelector('link[rel=manifest]').href)).json();
  const icons = [];
  for (const i of m.icons) { const r = await fetch(i.src); icons.push([i.src, r.status]); }
  return { links: out, manifestName: m.name, icons };
})()
"""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--out", default="docs/ui-checks/branding")
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
    runs = []

    def check(cond, msg):
        if not cond:
            failures.append(msg)

    def settle(s=0.6):
        b.pump(s)

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
                settle(1.5)
                p = b.js(LOGIN_PROBE)
                m = b.js(ui.MEASURE)
                check(p["title"] == "Shiftimizer", f"{tag}: title is {p['title']!r}")
                check(p["loaded"] and "סידור עבודה חכם" in p["alt"], f"{tag}: the full logo did not load at its native size")
                check(p["inside"] and p["width"] >= 150, f"{tag}: logo width {p['width']} / outside the viewport")
                check(p["plateBg"] == "rgba(0, 0, 0, 0)", f"{tag}: the logo must sit directly on the card (no plate), background is {p['plateBg']}")
                if scheme == "dark":
                    check(p["src"].endswith("/static/brand/full_transparent_dark.png") and p["wordmarkBrightness"] > 200, f"{tag}: dark mode must use the light-wordmark file: {p['src']} brightness {p['wordmarkBrightness']}")
                    check(p["starAlpha"] == 255 and min(p["starRgb"]) > 240, f"{tag}: the star must stay white on the dark card: {p['starAlpha']} {p['starRgb']}")
                else:
                    check(p["src"].endswith("/static/brand/full_transparent.png") and p["wordmarkBrightness"] < 60, f"{tag}: light mode must use the approved file: {p['src']} brightness {p['wordmarkBrightness']}")
                check("Smart Shift" not in p["text"], f"{tag}: the old name is still visible on the login screen")
                check(not m["pageOverflowsX"] and not m["elementsWiderThanViewport"] and m["dir"] == "rtl", f"{tag}: login overflow/direction")
                check(not m["smallTargets"], f"{tag}: small targets on login {m['smallTargets'][:2]}")
                b.shot(out / f"{vp}-{scheme}-login.jpg")
                links = b.js(LINKS)
                check(all(s == 200 for _, s in links["links"]) and links["manifestName"] == "Shiftimizer" and all(s == 200 for _, s in links["icons"]), f"{tag}: icon/manifest URLs {links}")
                check({u for u, _ in links["links"]} >= {"/static/brand/favicon.ico", "/static/brand/icon_32.png", "/static/brand/icon_16.png", "/static/brand/icon_180_white.png", "/static/brand/manifest.json"}, f"{tag}: missing icon links {links['links']}")
                for role, (name, code) in (("manager", (args.manager_name, args.manager_password)), ("employee", (args.employee_name, args.employee_code))):
                    login(name, code)
                    a = b.js(APP_PROBE)
                    m = b.js(ui.MEASURE)
                    runs.append({"vp": vp, "scheme": scheme, "role": role, "accent": a["accent"]})
                    check(a["loaded"] and a["size"] == 32, f"{tag}/{role}: header icon not loaded at 32 px ({a['size']})")
                    check(a["name"] == "Shiftimizer", f"{tag}/{role}: header name is {a['name']!r}")
                    check(a["title"].endswith("Shiftimizer"), f"{tag}/{role}: page title is {a['title']!r}")
                    check("Smart Shift" not in a["text"], f"{tag}/{role}: the old name is still visible")
                    check(not m["pageOverflowsX"] and not m["elementsWiderThanViewport"] and not m["smallTargets"] and m["dir"] == "rtl", f"{tag}/{role}: overflow/targets {m['elementsWiderThanViewport'][:2]} {m['smallTargets'][:2]}")
                    errs = [e for e in b.console if "401" not in e]
                    b.console.clear()
                    check(not errs, f"{tag}/{role}: console errors {errs[:2]}")
                    b.shot(out / f"{vp}-{scheme}-{role}-app.jpg")
                    b.js("document.getElementById('user-btn').click()", False)
                    settle(0.3)
                    b.js("document.querySelectorAll('.user-menu-item')[1].click()", False)
                    settle(1.0)
    finally:
        b.close()
    (out / "results.json").write_text(json.dumps({"browser": exe, "base": args.base, "runs": runs, "failures": failures}, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"{len(ui.VIEWPORTS) * len(ui.SCHEMES)} viewport/scheme runs, {len(failures)} problem(s)")
    for f in failures:
        print(" -", f)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
