"""The Hebrew RTL UI shell (issue #4): structure, copy, RTL rules, accessibility tokens, fonts, safety.

These are the automated half of the mobile-first Definition of Done in practice.md. The visual half
(360 / 390 / 768 / 1280 px, light and dark, keyboard) is recorded by hand in docs/ui-checks/m0-4/.
"""
import json
import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import auth
from app.config import ROOT
from app.main import app
from app.users import create_employee

STATIC = Path(ROOT) / "static"
HTML = (STATIC / "index.html").read_text(encoding="utf-8")
CSS = (STATIC / "styles.css").read_text(encoding="utf-8")
APP_JS = (STATIC / "app.js").read_text(encoding="utf-8")
MD_JS = (STATIC / "markdown.js").read_text(encoding="utf-8")
STRINGS_JS = (STATIC / "strings.js").read_text(encoding="utf-8")
HEBREW = re.compile(r"[֐-׿]")
H = {"X-Requested-With": "shift-copilot"}


def _strings():
    marker = "window.T = {"
    body = "{" + STRINGS_JS[STRINGS_JS.index(marker) + len(marker):].strip().rstrip(";")
    return json.loads(body)


def _flatten(d, prefix=""):
    for k, v in d.items():
        if isinstance(v, dict):
            yield from _flatten(v, f"{prefix}{k}.")
        else:
            yield f"{prefix}{k}", v


def _strip_js_comments(src):
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    return re.sub(r"(?m)^\s*//.*$", "", src)


# ------------------------------------------------------------------ document structure
def test_page_is_hebrew_rtl_and_mobile_ready():
    assert re.search(r'<html[^>]*\blang="he"', HTML) and re.search(r'<html[^>]*\bdir="rtl"', HTML)
    assert 'name="viewport" content="width=device-width, initial-scale=1' in HTML
    assert 'name="color-scheme" content="light dark"' in HTML
    assert "<title>Smart Shift Copilot</title>" in HTML
    for landmark in ("<header", "<nav", "<main"):
        assert landmark in HTML
    assert 'class="skip"' in HTML and "<noscript>" in HTML and 'role="status"' in HTML


def test_no_inline_handlers_and_no_external_resources():
    assert not re.search(r"\son\w+\s*=", HTML), "inline event handlers"
    for name, src in (("html", HTML), ("css", CSS), ("app.js", APP_JS), ("markdown.js", MD_JS)):
        urls = [u for u in re.findall(r"https?://[^\s\"')]+", _strip_js_comments(src)) if "www.w3.org" not in u]
        assert urls == [], f"external URL in {name}: {urls}"
    assert re.findall(r'<script[^>]+src="([^"]+)"', HTML) == ["/static/strings.js", "/static/markdown.js", "/static/availability.js", "/static/app.js"]


def test_no_inline_styles_or_scripts_so_a_strict_csp_is_possible():
    """The UI is written so Content-Security-Policy `default-src 'self'` would work (the policy itself is a deployment task, #8)."""
    assert not re.search(r"\sstyle\s*=", HTML), "inline style attribute in index.html"
    assert not re.search(r"<script(?![^>]*\ssrc=)[^>]*>", HTML), "inline <script> in index.html"
    assert not re.search(r"<style", HTML)
    assert not re.search(r"style\s*:", _strip_js_comments(APP_JS)), "app.js builds inline style attributes"


def test_product_name_is_english_everywhere_it_appears():
    s = _strings()
    assert s["app"]["name"] == "Smart Shift Copilot"


# ------------------------------------------------------------------ copy
ALLOWED_LATIN = {"Smart", "Shift", "Copilot", "ANTHROPIC", "API", "KEY"}


def test_all_user_facing_copy_is_hebrew():
    for key, value in _flatten(_strings()):
        cleaned = re.sub(r"\{\w+\}", "", value)
        if key == "app.name":
            continue
        assert HEBREW.search(cleaned), f"{key} has no Hebrew: {value!r}"
        latin = set(re.findall(r"[A-Za-z]{2,}", cleaned)) - ALLOWED_LATIN
        assert not latin, f"{key} has English words {latin}"


def test_legal_notice_is_present_and_visible_in_the_account_screen():
    s = _strings()
    assert "דיני העבודה" in s["account"]["legal"] and "ייעוץ משפטי" in s["account"]["legal"]
    assert "account.legal" in HTML and "legalLink" in APP_JS and "showModal" in APP_JS


def test_every_copy_key_used_by_the_ui_exists():
    keys = {k for k, _ in _flatten(_strings())}
    used = set(re.findall(r'data-t(?:-aria-label)?="([\w.]+)"', HTML))
    used |= {f"{a}.{b}" for a, b in re.findall(r"\bT\.(\w+)\.(\w+)", APP_JS)}
    used |= set(re.findall(r'label: "(nav\.\w+)"', APP_JS))
    missing = sorted(u for u in used if u not in keys)
    assert missing == [], f"strings missing: {missing}"
    # T.role[state.user.role] is dynamic: both roles must exist
    assert {"role.manager", "role.employee"} <= keys


# ------------------------------------------------------------------ RTL rules
def _declarations(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@font-face\s*\{.*?\}", "", css, flags=re.S)
    for m in re.finditer(r"([\w-]+)\s*:\s*([^;{}]+);", css):
        yield m.group(1).strip(), m.group(2).strip()


def test_css_uses_logical_properties_only():
    physical = re.compile(r"^(margin|padding|border)-(left|right)(-\w+)?$|^border-(top|bottom)-(left|right)-radius$|^(left|right|float|clear)$")
    bad = []
    for prop, value in _declarations(CSS):
        if physical.match(prop):
            bad.append(f"{prop}: {value}")
        if prop == "text-align" and value in ("left", "right"):
            bad.append(f"{prop}: {value}")
        if prop in ("margin", "padding") and len(value.split()) == 4:
            v = value.split()
            if v[1] != v[3]:
                bad.append(f"{prop}: {value} (four values, left differs from right)")
        if "translateX" in value or "translate(" in value:
            bad.append(f"{prop}: {value} (direction-dependent transform)")
    assert bad == [], f"physical (non-RTL-safe) CSS: {bad}"


def test_mirrored_icons_are_flipped_in_rtl_only():
    assert re.search(r'\[dir="rtl"\]\s*\.flip-rtl\s*\{\s*transform:\s*scaleX\(-1\)', CSS)
    for name in ("send", "logout"):
        assert re.search(rf'icon\("{name}",\s*"flip-rtl"\)', APP_JS), f"{name} icon must flip in RTL"


def test_text_direction_is_automatic_for_user_and_model_text():
    assert 'dir: "auto"' in APP_JS
    assert MD_JS.count('"dir", "auto"') >= 1 or 'setAttribute("dir", "auto")' in MD_JS
    assert re.search(r'id="login-code"[^>]*\bclass="input ltr"', HTML)  # access codes are Latin


# ------------------------------------------------------------------ touch targets and layout
def _rule(selector):
    m = re.search(re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert m, f"no CSS rule for {selector}"
    return m.group(1)


def _px(value):
    tap = int(re.search(r"--tap:\s*(\d+)px", CSS).group(1))
    value = value.strip()
    return tap if value == "var(--tap)" else int(re.match(r"(\d+)px", value).group(1))


def test_touch_targets_are_at_least_44px():
    assert re.search(r"--tap:\s*44px", CSS)
    for selector in (".btn", ".nav a", ".history li button", ".input", ".tech summary"):
        decl = dict(re.findall(r"([\w-]+)\s*:\s*([^;]+);", _rule(selector)))
        size = _px(decl["min-block-size"])
        want = 32 if selector == ".tech summary" else 44  # a disclosure inside text; its row is also tappable
        assert size >= want, f"{selector} min-block-size {size}px"
    btn = dict(re.findall(r"([\w-]+)\s*:\s*([^;]+);", _rule(".btn")))
    assert _px(btn["min-inline-size"]) >= 44


def test_layout_is_mobile_first():
    widths = re.findall(r"@media \(([a-z-]+): (\d+)px\)", CSS)
    assert widths and all(kind == "min-width" for kind, _ in widths), "media queries must be min-width (mobile-first)"
    assert {int(w) for _, w in widths} >= {768, 1024}
    assert "100dvh" in CSS and "env(safe-area-inset-bottom)" in CSS
    assert "prefers-reduced-motion" in CSS and "prefers-color-scheme: dark" in CSS and "forced-colors" in CSS
    assert "overflow-wrap: anywhere" in CSS


def test_text_inputs_are_16px_so_ios_does_not_zoom():
    decl = dict(re.findall(r"([\w-]+)\s*:\s*([^;]+);", _rule(".input")))
    assert decl["font-size"].strip() == "1rem"


# ------------------------------------------------------------------ colour contrast (WCAG 2.x)
def _tokens(block):
    return dict(re.findall(r"--([\w-]+):\s*(#[0-9A-Fa-f]{6})\s*;", block))


def _blocks():
    light = re.search(r":root\s*\{(.*?)\n\}", CSS, flags=re.S).group(1)
    dark = re.search(r"prefers-color-scheme: dark\)\s*\{\s*:root\s*\{(.*?)\}\s*\}", CSS, flags=re.S).group(1)
    return _tokens(light), {**_tokens(light), **_tokens(dark)}


def _lum(hex_color):
    rgb = [int(hex_color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    lin = [c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4 for c in rgb]
    return 0.2126 * lin[0] + 0.7152 * lin[1] + 0.0722 * lin[2]


def contrast(a, b):
    la, lb = sorted((_lum(a), _lum(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


TEXT_PAIRS = [("ink", "bg"), ("ink", "surface"), ("ink", "surface-2"), ("muted", "bg"), ("muted", "surface"), ("muted", "surface-2"),
              ("accent-ink", "accent"), ("accent-ink", "accent-hover"), ("accent-text", "accent-soft"), ("ink", "accent-soft"),
              ("accent-text", "surface"), ("accent-text", "surface-2"), ("danger", "danger-soft"), ("danger", "surface")]
UI_PAIRS = [("focus", "bg"), ("focus", "surface"), ("accent", "surface"), ("accent", "bg")]


@pytest.mark.parametrize("scheme", [0, 1], ids=["light", "dark"])
def test_colour_contrast_meets_wcag_aa(scheme):
    tokens = _blocks()[scheme]
    low = [(a, b, round(contrast(tokens[a], tokens[b]), 2)) for a, b in TEXT_PAIRS if contrast(tokens[a], tokens[b]) < 4.5]
    low += [(a, b, round(contrast(tokens[a], tokens[b]), 2)) for a, b in UI_PAIRS if contrast(tokens[a], tokens[b]) < 3.0]
    assert low == [], f"contrast too low: {low}"


def test_light_is_default_and_palette_is_the_approved_one():
    light, _ = _blocks()
    assert light["bg"].upper() in ("#F6F3EE",) and light["surface"].upper() == "#FFFFFF"   # warm neutral, white cards
    r, g, b = (int(light["accent"][i:i + 2], 16) for i in (1, 3, 5))
    assert g > r and b > r - 10 and abs(g - b) < 60, "accent should be a muted teal / blue-green"
    assert "gradient" not in CSS and "neon" not in CSS


# ------------------------------------------------------------------ fonts
def test_heebo_is_self_hosted_with_its_licence():
    fonts = STATIC / "fonts"
    files = sorted(fonts.glob("*.woff2"))
    assert [f.name for f in files] == ["heebo-hebrew-wght-normal.woff2", "heebo-latin-wght-normal.woff2"]
    for f in files:
        assert f.read_bytes()[:4] == b"wOF2", f"{f.name} is not a woff2 file"
    assert sum(f.stat().st_size for f in files) < 120_000, "font budget exceeded"
    licence = (fonts / "OFL.txt").read_text(encoding="utf-8")
    assert "SIL OPEN FONT LICENSE Version 1.1" in licence and "Heebo Project Authors" in licence
    assert (fonts / "README.md").exists()
    for url in re.findall(r'url\("(/static/fonts/[^"]+)"\)', CSS):
        assert (STATIC / url.removeprefix("/static/")).exists(), url
    assert CSS.count("font-display: swap") == 2
    assert re.search(r'--font:\s*"Heebo",[^;]*sans-serif;', CSS)  # fallbacks if the font fails to load


def test_static_assets_are_served(client):
    for path in ("/static/styles.css", "/static/app.js", "/static/markdown.js", "/static/availability.js", "/static/strings.js",
                 "/static/fonts/heebo-hebrew-wght-normal.woff2", "/static/fonts/heebo-latin-wght-normal.woff2", "/static/fonts/OFL.txt"):
        assert client.get(path).status_code == 200, path
    page = client.get("/")
    assert page.status_code == 200 and 'lang="he"' in page.text and client.get("/openapi.json").status_code == 404


# ------------------------------------------------------------------ safety of the shell code
def test_no_unsafe_dom_or_code_execution_in_the_ui_code():
    banned = re.compile(r"innerHTML|outerHTML|insertAdjacentHTML|document\.write|\beval\s*\(|new\s+Function|setTimeout\(\s*[\"'`]|javascript:|srcdoc|\.html\(")
    for name in ("app.js", "markdown.js", "availability.js"):
        src = _strip_js_comments((STATIC / name).read_text(encoding="utf-8"))
        assert not banned.search(src), f"unsafe construct in {name}: {banned.search(src).group(0)}"


def test_every_request_goes_through_the_csrf_aware_helper():
    code = _strip_js_comments(APP_JS)
    assert code.count("fetch(") == 1 and '"X-Requested-With": "shift-copilot"' in code


def test_model_output_is_only_rendered_through_the_safe_renderer():
    code = _strip_js_comments(APP_JS)
    assert "MD.render(" in code
    assert "textContent = ev.text" not in code and "append(ev.text" not in code


def test_manager_and_employee_destinations_are_separate_and_only_implemented_ones():
    block = re.search(r"const DESTINATIONS = \{(.*?)\n  \};", APP_JS, flags=re.S).group(1)
    manager = re.search(r"manager: \[(.*?)\],\n", block, flags=re.S).group(1)
    employee = re.search(r"employee: \[(.*?)\],?\s*$", block, flags=re.S).group(1)
    assert re.findall(r'id: "(\w+)"', manager) == ["assistant", "account"]
    assert re.findall(r'id: "(\w+)"', employee) == ["availability", "account"]
    assert "disabled" not in block and "soon" not in block.lower()
    assert "({ assistant: renderAssistant, availability: renderAvailability, account: renderAccount })" in APP_JS


# ------------------------------------------------------------------ Hebrew API messages (authentication, session, authorization)
def _has_hebrew(r):
    detail = r.json()["detail"]
    return isinstance(detail, str) and HEBREW.search(detail)


def test_authentication_errors_are_hebrew(client, db):
    anon = TestClient(app, headers=H)
    wrong = anon.post("/api/login", json={"name": "Nobody", "code": "ZZZZZ-ZZZZZ"})
    assert wrong.status_code == 401 and wrong.json()["detail"] == auth.GENERIC_FAILURE and _has_hebrew(wrong)
    expired = anon.get("/api/me")
    assert expired.status_code == 401 and expired.json()["detail"] == auth.SIGN_IN_REQUIRED and _has_hebrew(expired)


def test_authorization_and_validation_errors_are_hebrew(client, db, logged_in):
    user, code = create_employee(db, "Hebrew Messages")
    emp = TestClient(app, headers=H)
    emp.post("/api/login", json={"name": user.name, "code": code})
    forbidden = emp.get("/api/stats")
    assert forbidden.status_code == 403 and _has_hebrew(forbidden)
    assert _has_hebrew(client.get("/api/conversations/999999/messages"))  # 404, not found
    empty = client.post("/api/chat", json={"message": "   "})
    assert empty.status_code == 400 and _has_hebrew(empty)


def test_lockout_and_csrf_messages_are_hebrew(client, db):
    user, _ = create_employee(db, "Hebrew Lock")
    last = None
    for _ in range(6):
        last = client.post("/api/login", json={"name": user.name, "code": "ZZZZZ-ZZZZZ"})
    assert last.status_code == 429 and _has_hebrew(last) and "retry-after" in last.headers
    blocked = TestClient(app).post("/api/login", json={"name": "x" * 3, "code": "y"})
    assert blocked.status_code == 403 and _has_hebrew(blocked)


def test_agent_user_facing_texts_are_hebrew():
    from app import agent

    assert HEBREW.search(agent.REFUSAL_TEXT)
    for exc in (RuntimeError("x"),):
        assert HEBREW.search(agent._friendly(exc))


# ------------------------------------------------------------------ the availability form's copy (spec.md section 5)
def test_the_form_uses_the_exact_approved_copy():
    a = _strings()["availability"]
    assert a["heading"] == "הגשת משמרות לשבוע הבא"
    assert a["openingNotice"] == "הגשת המשמרות לשבוע הבא תיפתח לאחר פרסום סידור העבודה לשבוע הקרוב, או ביום חמישי בשעה 22:00 – המוקדם מביניהם"
    assert a["freeNotice"] == "נשתדל להתחשב בבקשות ככל האפשר, בהתאם לצורכי העסק ולאילוצי השיבוץ, אך אין התחייבות שניתן יהיה להיענות לכולן."
    assert (a["all"], a["none"]) == ("כל המשמרות", "לא זמין/ה")
    assert "שלישי" in a["editUntil"] and "22:00" in a["editUntil"] and "ולערוך" in a["editUntil"]
    assert "1,000" not in a["counter"] and "{max}" in a["counter"]


def test_there_are_no_shift_count_preferences_in_the_ui_or_the_api_copy():
    for text in (STRINGS_JS, APP_JS):
        assert "pref_min" not in text and "pref_max" not in text
    assert "מינימום" not in STRINGS_JS and "מקסימום" not in STRINGS_JS
    assert "נשתדל להתחשב בהעדפותיך" not in STRINGS_JS   # the shift-count notice was removed with the fields


def test_the_form_has_no_manual_opening_or_change_request_button():
    forbidden = ("changeRequest", "change-request", "openSubmissions", "בקשת שינוי")
    assert not any(f in APP_JS for f in forbidden)
    assert "המשמרות שלי" not in STRINGS_JS     # employees see only their form and lock summary until schedules exist
