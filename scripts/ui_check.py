"""Responsive and accessibility checks for the UI shell, run in a real Chromium browser (Chrome or Edge, headless).

Needs no Python packages: it starts the browser with a debugging port and talks to it over the DevTools
protocol with a tiny built-in WebSocket client. Used for the mobile-first Definition of Done (practice.md section 3).

    python scripts/ui_check.py --base http://localhost:8000 --out docs/ui-checks/m0-4 \
        --manager-name boss --manager-password ... --employee-name "Noa" --employee-code XXXXX-XXXXX

Per viewport (360x800, 390x844, 768x1024, 1280x800) and colour scheme (light, dark) it records, for each screen:
horizontal overflow, elements wider than the viewport, interactive elements smaller than 44px, page direction,
whether Heebo loaded, console errors, and a screenshot. It also exercises keyboard focus, the legal dialog, the
conversation history drawer, loading and error states, login/logout and manager/employee separation.
Run it against a fresh or disposable database: it makes a few deliberate wrong logins, and the app's login
lockout (5 per name, 20 per address) will start refusing a run that repeats too often within an hour.
Results go to <out>/results.json; screenshots to <out>/*.jpg. Use only against a local or test instance with fictional data.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import socket
import struct
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

VIEWPORTS = [("360", 360, 800, True), ("390", 390, 844, True), ("768", 768, 1024, False), ("1280", 1280, 800, False)]
SCHEMES = ["light", "dark"]
BROWSERS = [
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    "/usr/bin/google-chrome", "/usr/bin/chromium", "/usr/bin/chromium-browser",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]


# ---------------------------------------------------------------- minimal WebSocket client
class WebSocket:
    def __init__(self, host: str, port: int, path: str):
        self.sock = socket.create_connection((host, port), timeout=30)
        key = base64.b64encode(os.urandom(16)).decode()
        self.sock.sendall((f"GET {path} HTTP/1.1\r\nHost: {host}:{port}\r\nUpgrade: websocket\r\nConnection: Upgrade\r\n"
                           f"Sec-WebSocket-Key: {key}\r\nSec-WebSocket-Version: 13\r\n\r\n").encode())
        buf = b""
        while b"\r\n\r\n" not in buf:
            buf += self.sock.recv(1024)
        if b" 101 " not in buf.split(b"\r\n")[0]:
            raise RuntimeError("websocket handshake failed")
        self.rest = buf.split(b"\r\n\r\n", 1)[1]

    def _read(self, n: int) -> bytes:
        while len(self.rest) < n:
            chunk = self.sock.recv(65536)
            if not chunk:
                raise ConnectionError("browser closed the connection")
            self.rest += chunk
        out, self.rest = self.rest[:n], self.rest[n:]
        return out

    def send(self, text: str) -> None:
        data = text.encode()
        header = bytearray([0x81])
        n = len(data)
        if n < 126:
            header.append(0x80 | n)
        elif n < 65536:
            header += bytes([0x80 | 126]) + struct.pack(">H", n)
        else:
            header += bytes([0x80 | 127]) + struct.pack(">Q", n)
        mask = os.urandom(4)
        self.sock.sendall(bytes(header) + mask + bytes(b ^ mask[i % 4] for i, b in enumerate(data)))

    def recv(self) -> str:
        message = b""
        while True:
            b1, b2 = self._read(2)
            opcode, length = b1 & 0x0F, b2 & 0x7F
            if length == 126:
                length = struct.unpack(">H", self._read(2))[0]
            elif length == 127:
                length = struct.unpack(">Q", self._read(8))[0]
            payload = self._read(length)
            if opcode == 0x9:  # ping
                continue
            message += payload
            if b1 & 0x80:
                return message.decode()


class Browser:
    def __init__(self, exe: str):
        self.profile = tempfile.mkdtemp(prefix="ui-check-")
        with socket.socket() as s:
            s.bind(("127.0.0.1", 0))
            self.port = s.getsockname()[1]
        self.proc = subprocess.Popen([exe, "--headless=new", "--disable-gpu", "--no-first-run", "--hide-scrollbars=false",
                                      f"--remote-debugging-port={self.port}", f"--user-data-dir={self.profile}", "about:blank"],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.time() + 30
        target = None
        while time.time() < deadline and not target:
            try:
                tabs = json.load(urllib.request.urlopen(f"http://127.0.0.1:{self.port}/json/list", timeout=2))
                target = next((t for t in tabs if t.get("type") == "page"), None)
            except Exception:
                time.sleep(0.3)
        if not target:
            raise RuntimeError("could not start the browser")
        self.ws = WebSocket("127.0.0.1", self.port, "/" + target["webSocketDebuggerUrl"].split("/", 3)[3])
        self.next_id = 0
        self.console: list[str] = []
        for domain in ("Page", "Runtime", "Log", "Network"):
            self.call(f"{domain}.enable")

    def call(self, method: str, **params):
        self.next_id += 1
        mid = self.next_id
        self.ws.send(json.dumps({"id": mid, "method": method, "params": params}))
        while True:
            msg = json.loads(self.ws.recv())
            self._event(msg)
            if msg.get("id") == mid:
                if "error" in msg:
                    raise RuntimeError(f"{method}: {msg['error']}")
                return msg.get("result", {})

    def _event(self, msg: dict) -> None:
        m, p = msg.get("method"), msg.get("params", {})
        if m == "Runtime.exceptionThrown":
            self.console.append("exception: " + p["exceptionDetails"].get("text", "") + " " + str(p["exceptionDetails"].get("exception", {}).get("description", ""))[:200])
        elif m == "Runtime.consoleAPICalled" and p.get("type") in ("error", "assert"):
            self.console.append("console." + p["type"] + ": " + " ".join(str(a.get("value", a.get("description", ""))) for a in p.get("args", []))[:200])
        elif m == "Log.entryAdded" and p["entry"].get("level") == "error":
            self.console.append("log: " + p["entry"].get("text", "")[:200] + " " + p["entry"].get("url", ""))

    def js(self, expression: str, await_promise: bool = True):
        r = self.call("Runtime.evaluate", expression=expression, awaitPromise=await_promise, returnByValue=True)
        if "exceptionDetails" in r:
            raise RuntimeError("js error: " + json.dumps(r["exceptionDetails"])[:300])
        return r["result"].get("value")

    def pump(self, seconds: float) -> None:
        """Process events for a while (the page keeps running)."""
        self.ws.sock.settimeout(0.2)
        end = time.time() + seconds
        while time.time() < end:
            try:
                self._event(json.loads(self.ws.recv()))
            except (socket.timeout, TimeoutError):
                pass
        self.ws.sock.settimeout(30)

    def shot(self, path: Path) -> None:
        data = self.call("Page.captureScreenshot", format="jpeg", quality=72)["data"]
        path.write_bytes(base64.b64decode(data))

    def key(self, key: str, code: str, vk: int, modifiers: int = 0) -> None:
        for kind in ("keyDown", "keyUp"):
            self.call("Input.dispatchKeyEvent", type=kind, key=key, code=code, windowsVirtualKeyCode=vk, modifiers=modifiers)

    def close(self) -> None:
        try:
            self.call("Browser.close")
        except Exception:
            pass
        self.proc.terminate()
        shutil.rmtree(self.profile, ignore_errors=True)


# ---------------------------------------------------------------- measurements run inside the page
MEASURE = r"""
(() => {
  const vw = document.documentElement.clientWidth;
  const visible = (e) => { const r = e.getBoundingClientRect(); const s = getComputedStyle(e); return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none'; };
  const inScroller = (e) => !!e.closest('.md-table');
  const wide = [...document.querySelectorAll('body *')].filter((e) => visible(e) && !inScroller(e) && !e.closest('svg') && (e.getBoundingClientRect().right > vw + 1 || e.getBoundingClientRect().left < -1))  /* in RTL, overflow goes off the left edge and scrollWidth does not grow */
      .slice(0, 8).map((e) => e.tagName.toLowerCase() + '.' + (e.className && e.className.baseVal === undefined ? e.className : '') + ' L=' + Math.round(e.getBoundingClientRect().left) + ' R=' + Math.round(e.getBoundingClientRect().right));
  const interactive = [...document.querySelectorAll('a[href], button, input:not([type=hidden]), textarea, summary, select, [role=button], [tabindex]:not([tabindex="-1"])')].filter(visible);
  const small = interactive.map((e) => { const r = e.getBoundingClientRect(); return {el: e.tagName.toLowerCase() + (e.id ? '#' + e.id : '') + (e.className ? '.' + String(e.className).split(' ')[0] : ''), w: Math.round(r.width), h: Math.round(r.height)}; })
      .filter((x) => (x.h < 44 || x.w < 44) && !(x.el.startsWith('summary') && x.h >= 32) && !(x.el.startsWith('input') && x.w >= 44 && x.h >= 44));
  const fontLoaded = [...document.fonts].some((f) => f.family.replace(/"/g, '') === 'Heebo' && f.status === 'loaded');
  return {
    viewport: [innerWidth, innerHeight], scrollWidth: document.documentElement.scrollWidth, bodyScrollWidth: document.body.scrollWidth,
    pageOverflowsX: document.documentElement.scrollWidth > innerWidth + 1,
    elementsWiderThanViewport: wide, interactiveCount: interactive.length, smallTargets: small,
    dir: document.documentElement.dir, lang: document.documentElement.lang, title: document.title,
    heeboLoaded: fontLoaded, bodyFont: getComputedStyle(document.body).fontFamily.split(',')[0],
    scheme: matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light',
    bodyBg: getComputedStyle(document.body).backgroundColor,
    noAccessToManagerUI: !document.getElementById('composer'),
    activeElement: document.activeElement ? document.activeElement.tagName.toLowerCase() + (document.activeElement.id ? '#' + document.activeElement.id : '') : null,
  };
})()
"""


def run(args) -> int:
    exe = args.browser or next((b for b in BROWSERS if Path(b).exists()), None) or shutil.which("chrome") or shutil.which("msedge")
    if not exe:
        print("no Chrome/Edge found; pass --browser", file=sys.stderr)
        return 2
    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    b = Browser(exe)
    results: dict = {"browser": exe, "base": args.base, "checks": []}
    failures: list[str] = []

    def record(vp, scheme, name, shot=True, note="", expected=()):
        """`expected`: console messages that are the intended result of the step (a deliberate 401, going offline)."""
        m = b.js(MEASURE)
        m["errors"] = [e for e in b.console if not any(x in e for x in expected)]
        m["expectedErrors"] = [e for e in b.console if any(x in e for x in expected)]
        b.console.clear()
        m.update({"vp": vp, "scheme": scheme, "screen": name, "note": note})
        if shot:
            b.shot(out / f"{vp}-{scheme}-{name}.jpg")
        results["checks"].append(m)
        problems = []
        if m["pageOverflowsX"]:
            problems.append("page overflows horizontally")
        if m["elementsWiderThanViewport"]:
            problems.append("elements wider than viewport: " + ", ".join(m["elementsWiderThanViewport"][:3]))
        if m["smallTargets"]:
            problems.append("targets under 44px: " + str(m["smallTargets"][:4]))
        if m["dir"] != "rtl" or m["lang"] != "he":
            problems.append("page is not lang=he dir=rtl")
        if m["errors"]:
            problems.append("console errors: " + str(m["errors"][:2]))
        if m["scheme"] != scheme:
            problems.append("colour scheme emulation failed")
        if problems:
            failures.append(f"{vp}/{scheme}/{name}: " + "; ".join(problems))
        return m

    def settle(seconds=0.6):
        b.pump(seconds)

    def login(name, code):
        b.js(f"(() => {{ document.getElementById('login-name').value = {json.dumps(name)}; document.getElementById('login-code').value = {json.dumps(code)}; document.getElementById('login-form').requestSubmit(); }})()", False)
        settle(1.2)

    def fresh(vp_w, vp_h, mobile, scheme):
        b.call("Emulation.setDeviceMetricsOverride", width=vp_w, height=vp_h, deviceScaleFactor=1, mobile=mobile)
        b.call("Emulation.setTouchEmulationEnabled", enabled=mobile)
        b.call("Emulation.setEmulatedMedia", features=[{"name": "prefers-color-scheme", "value": scheme}])
        b.call("Network.clearBrowserCookies")
        b.call("Page.navigate", url=args.base + "/")
        settle(1.2)

    try:
        for vp, w, h, mobile in VIEWPORTS:
            for scheme in SCHEMES:
                full = scheme == "light" or vp in ("360", "1280")  # dark: the key screens at the narrowest and widest sizes
                fresh(w, h, mobile, scheme)
                record(vp, scheme, "login", expected=("/api/me",))  # the anonymous session check answers 401
                if full:
                    # keyboard: the skip link is first in the tab order and becomes visible with a focus ring;
                    # Tab from the name field reaches the code field
                    order = b.js("(() => { const f = [...document.querySelectorAll('a[href], button, input, textarea, select')].find((e) => e.tabIndex >= 0 && !e.closest('[hidden]')); return f.className; })()")
                    # the login name field is focused on load, so the skip link is one Shift+Tab away
                    b.js("document.getElementById('login-name').focus()", False)
                    b.key("Tab", "Tab", 9, modifiers=8)
                    skip = b.js("(() => { const s = document.querySelector('.skip'); const r = s.getBoundingClientRect(); return [document.activeElement === s, r.top >= 0 && r.width > 0, getComputedStyle(s).outlineStyle]; })()")
                    b.js("document.getElementById('login-name').focus()", False)
                    b.key("Tab", "Tab", 9)
                    after_name = b.js("document.activeElement.id")
                    results["checks"][-1]["keyboard"] = {"firstInDomOrder": order, "skipLinkVisibleOnFocus": skip, "tabFromName": after_name}
                    if order != "skip" or skip != [True, True, "solid"] or after_name != "login-code":
                        failures.append(f"{vp}/{scheme}: keyboard order problem {results['checks'][-1]['keyboard']}")
                    # empty submit and wrong code -> Hebrew errors
                    login("", "")
                    err = b.js("document.getElementById('login-notice').textContent")
                    record(vp, scheme, "login-missing-fields", note=err)
                    if scheme == "light":  # one deliberate wrong attempt per viewport keeps the run under the login lockout limits
                        login(args.manager_name, "wrong-code-for-check")
                        err = b.js("document.getElementById('login-notice').textContent")
                        record(vp, scheme, "login-wrong-code", note=err, expected=("/api/login",))
                    # loading state: slow network while signing in
                    b.call("Network.emulateNetworkConditions", offline=False, latency=1800, downloadThroughput=-1, uploadThroughput=-1)
                    b.js(f"(() => {{ document.getElementById('login-name').value = {json.dumps(args.employee_name)}; document.getElementById('login-code').value = {json.dumps(args.employee_code)}; document.getElementById('login-form').requestSubmit(); }})()", False)
                    settle(0.5)
                    record(vp, scheme, "login-loading", note="spinner while the request is slow")
                    b.call("Network.emulateNetworkConditions", offline=False, latency=0, downloadThroughput=-1, uploadThroughput=-1)
                    settle(3.0)
                else:
                    login(args.employee_name, args.employee_code)
                # employee shell
                m = record(vp, scheme, "employee-home", expected=("/api/login",) if (full and scheme == "light") else ())  # the deliberate wrong login above
                if m["noAccessToManagerUI"] is not True:
                    failures.append(f"{vp}/{scheme}: employee sees the manager UI")
                b.js("location.hash = '#/assistant'", False); settle(0.4)
                if b.js("location.hash") != "#/home":
                    failures.append(f"{vp}/{scheme}: employee could open #/assistant")
                b.js("location.hash = '#/account'", False); settle(0.4)
                record(vp, scheme, "employee-account")
                if full:
                    b.js("document.querySelector('#main .btn-quiet').click()", False); settle(0.4)
                    record(vp, scheme, "legal-dialog")
                    b.key("Escape", "Escape", 27); settle(0.3)
                    if b.js("document.getElementById('dlg-legal').open"):
                        failures.append(f"{vp}/{scheme}: Escape did not close the dialog")
                b.js("document.getElementById('btn-logout').click()", False); settle(1.0)
                if not b.js("!document.getElementById('view-login').hidden"):
                    failures.append(f"{vp}/{scheme}: logout did not return to the login screen")
                record(vp, scheme, "after-logout")
                # manager
                login(args.manager_name, args.manager_password)
                record(vp, scheme, "manager-assistant-empty")
                b.js("document.getElementById('btn-history') && getComputedStyle(document.getElementById('btn-history')).display !== 'none' && document.getElementById('btn-history').click()", False); settle(0.6)
                record(vp, scheme, "manager-history", note="drawer on narrow screens, column from 1024px")
                b.js("(() => { const b = [...document.querySelectorAll('#history li button')].find((x) => x.textContent.includes(%s)) || document.querySelector('#history li button'); if (b) b.click(); })()" % json.dumps(args.rich_conversation), False); settle(1.0)
                record(vp, scheme, "manager-conversation-rich", note="lists, table, mixed Hebrew/English, long text, HTML shown as text")
                if full:
                    # a table scrolls inside its own region and never widens the page
                    tw = b.js("(() => { const t = document.querySelector('.md-table'); return t ? [t.scrollWidth, t.clientWidth] : null; })()")
                    results["checks"][-1]["tableScroll"] = tw
                    injected = b.js("!document.querySelector('.md script, .md img, .md a, .bubble script, .bubble img')")
                    if not injected:
                        failures.append(f"{vp}/{scheme}: model HTML became real elements")
                    # send a message: streaming reply from the fake model
                    b.js("(() => { const t = document.getElementById('input'); t.value = 'בדיקה: hello **world**'; document.getElementById('composer').requestSubmit(); })()", False)
                    settle(1.2)
                    record(vp, scheme, "manager-after-send")
                    # error state: the network drops while history reloads, then the retry button works
                    b.call("Network.emulateNetworkConditions", offline=True, latency=0, downloadThroughput=-1, uploadThroughput=-1)
                    b.js("document.getElementById('btn-new').click()", False)
                    b.js("(() => { const t = document.getElementById('input'); t.value = 'offline test'; document.getElementById('composer').requestSubmit(); })()", False)
                    settle(1.2)
                    if h and w < 1024:
                        b.js("document.getElementById('btn-history').click()", False); settle(0.4)
                    record(vp, scheme, "manager-offline-error", note="send fails and history fails to reload", expected=("ERR_INTERNET_DISCONNECTED",))
                    b.call("Network.emulateNetworkConditions", offline=False, latency=0, downloadThroughput=-1, uploadThroughput=-1)
                    settle(0.5)
                b.js("location.hash = '#/account'", False); settle(0.5)
                record(vp, scheme, "manager-account")
        # the interface must stay usable if the custom font fails to load
        b.call("Network.setCacheDisabled", cacheDisabled=True)
        b.call("Network.setBlockedURLs", urls=["*.woff2"])
        fresh(360, 800, True, "light")
        m = record("360", "light", "login-font-fallback", note="Heebo blocked: system fallback fonts", expected=("woff2", "/api/me"))
        if m["heeboLoaded"]:
            failures.append("font blocking did not work; fallback was not exercised")
        login(args.manager_name, args.manager_password)
        b.js("(() => { const x = [...document.querySelectorAll('#history li button')].find((y) => y.textContent.includes(%s)); if (x) x.click(); })()" % json.dumps(args.rich_conversation), False)
        settle(1.0)
        record("360", "light", "manager-font-fallback", note="Heebo blocked: chat still fits", expected=("woff2",))
        b.call("Network.setBlockedURLs", urls=[])
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
    ap.add_argument("--base", default="http://localhost:8000")
    ap.add_argument("--out", default="docs/ui-checks/latest")
    ap.add_argument("--browser")
    ap.add_argument("--manager-name", default=os.environ.get("MANAGER_NAME", "manager"))
    ap.add_argument("--manager-password", default=os.environ.get("MANAGER_PASSWORD", ""))
    ap.add_argument("--rich-conversation", default="סיכום הגשות", help="text of the seeded conversation with rich Markdown")
    ap.add_argument("--employee-name", required=True)
    ap.add_argument("--employee-code", required=True)
    raise SystemExit(run(ap.parse_args()))
