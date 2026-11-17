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
    assert "<title>Shiftimizer</title>" in HTML
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
    assert s["app"]["name"] == "Shiftimizer"


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
    assert re.findall(r'id: "(\w+)"', manager) == ["assistant", "submissions"]      # "account" is reached from the user menu, not the navigation
    assert re.findall(r'id: "(\w+)"', employee) == ["availability"]
    assert "disabled" not in block and "soon" not in block.lower()
    assert "({ assistant: renderAssistant, submissions: renderSubmissions, availability: renderAvailability, account: renderAccount })" in APP_JS


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


def test_login_label_is_password_and_the_manager_hint_is_gone():
    s = _strings()
    assert s["login"]["code"] == "סיסמה" and "codeHint" not in s["login"]
    assert "למנהל/ת: כאן מזינים את הסיסמה" not in STRINGS_JS + HTML
    assert "login-code-hint" not in HTML


def test_manager_user_menu_markup_and_strings():
    assert re.search(r'<button[^>]+id="user-btn"', HTML) and 'id="user-menu"' in HTML and 'role="menu"' in HTML
    s = _strings()["account"]
    assert (s["title"], s["logout"]) == ("החשבון שלי", "התנתקות")
    js = (STATIC / "app.js").read_text(encoding="utf-8")
    assert "bindUserMenu()" in js and "T.role[state.user.role]" in js and 'role === "manager"' not in js.split("function setupUserMenu")[1].split("function openUserMenu")[0]  # both roles get it


def test_availability_refinements_copy():
    a = _strings()["availability"]
    assert a["closesAt"] == "ההגשה פתוחה עד {when}. אפשר לערוך את ההגשה עד למועד זה."
    assert a["daysHelp"] == "סמנו את המשמרות שבהן תוכלו לעבוד בכל יום."
    assert a["freeHelp"] == "למשל: העדפה למשמרות בוקר, מספר משמרות רצוי בשבוע או בקשות אישיות נוספות."
    for gone in ("stateOpen", "stateNotOpen", "stateClosed", "countdown"):
        assert gone not in a, gone                       # the top badges and the countdown were removed
    assert "chip(" not in APP_JS and 'id: "countdown"' not in APP_JS
    assert "submission-status" in APP_JS and "fmtDeadline" in APP_JS
    css = (STATIC / "styles.css").read_text(encoding="utf-8")
    assert "repeat(2, minmax(0, 1fr))" not in css.split(".day-grid")[1].split("}")[0] and ".day-grid { grid-template-columns" not in css.split("@media (min-width: 768px)")[1]


def test_submissions_tab_is_manager_only_read_only_and_uses_safe_rendering():
    s = _strings()
    assert s["nav"]["submissions"] == "הגשות עובדים" and s["submissions"]["title"] == "הגשות עובדים"
    code = _strip_js_comments(APP_JS)
    body = code.split("function renderSubmissions")[1].split("function renderAccount")[0]
    assert '"/api/submissions"' in body and '"POST"' not in body and '"PUT"' not in body and '"DELETE"' not in body   # one GET, nothing written
    assert "innerHTML" not in body and 'class: "free-text"' in body                                                   # free text is plain text
    assert "leave_dates" in body and "full_week_leave" in body                                                         # leave shows when the API sends it
    dest = APP_JS.split("const DESTINATIONS")[1].split("};")[0]
    assert 'id: "submissions"' in dest.split("employee:")[0] and 'id: "submissions"' not in dest.split("employee:")[1]


def test_submissions_notice_copy_and_placement():
    s = _strings()["submissions"]
    assert s["noticeOpen"] == "שימו לב: העובדים יכולים להגיש ולעדכן את זמינותם עד {when}. עד אז ההגשות המוצגות עשויות להשתנות."
    assert s["noticeClosed"] == "ההגשה לשבוע זה נסגרה ב{when}."
    code = _strip_js_comments(APP_JS)
    body = code.split("function drawSubmissions")[1].split("function renderAccount")[0]
    assert "body.replaceChildren(notice, head, tiles," in body                    # below the heading, above the counts
    assert "cy.closes_at" in body and "d.cycle" in body                                  # the deadline of the displayed report's own window


def test_account_is_not_in_the_navigation_but_stays_reachable_from_the_user_menu():
    block = re.search(r"const DESTINATIONS = \{(.*?)\n  \};", APP_JS, flags=re.S).group(1)
    assert 'id: "account"' not in block
    code = _strip_js_comments(APP_JS)
    assert 'wanted === "account"' in code and 'location.hash = "#/account"' in code      # the route survives; the menu item opens it
    assert "account: renderAccount" in code


def test_copilot_examples_and_submissions_card_copy():
    s = _strings()
    a, sub = s["assistant"], s["submissions"]
    assert (a["example1"], a["example2"], a["example3"]) == ("מי יכול לעבוד ערב ביום שני?", "כמה עובדים הגישו זמינות ליום שישי בבוקר?", "מהן ההעדפות האישיות שמיכל ציינה?")
    assert (sub["statusSubmitted"], sub["statusMissing"]) == ("הוגשה זמינות", "טרם הוגשה זמינות")
    assert "readOnly" not in sub and "noFree" not in sub and "תצוגה לקריאה בלבד" not in STRINGS_JS
    code = _strip_js_comments(APP_JS)
    body = code.split("function employeeCard")[1].split("function drawSubmissions")[0]
    assert "if (e.free_text)" in body and "S.freeTitle" in body                           # preferences only when there are some
    assert "weekDays.map" in body                                                           # all seven days, shifts beside each


def test_summary_cards_are_the_filters_with_the_requested_labels_and_order():
    s = _strings()["submissions"]
    assert (s["total"], s["submitted"], s["missing"], s["onLeave"]) == ("סה״כ עובדים", "הגישו", "טרם הגישו", "בחופשה")
    code = _strip_js_comments(APP_JS)
    body = code.split("function drawSubmissions")[1].split("function renderAccount")[0]
    assert 'const FILTER_CARDS = [["total", "total", "total"], ["submitted", "submitted", "ok"], ["missing", "missing", "missing"], ["leave", "onLeave", "leave"]]' in code
    assert 'el("button", { class: "stat stat-" + kind' in body and '"aria-pressed"' in body       # the cards are real buttons with a pressed state
    assert 'filter: "total"' in code                                                                # default: everyone
    assert "AM.filterEmployees(d.employees, subs.filter)" in body
    assert "emptyLeave" in body and "S.emptySubmitted" in body and "S.emptyMissing" in body       # an empty state for each filter
    assert 'class: "emp-updated"' in code and "e.updated_at" in code                                # last submission/update in the collapsed card
    assert "dataset.id" in body and "x.open = true" in body                                         # expanded cards survive refreshes and filter changes
    assert "setInterval(" in code.split("function renderSubmissions")[1].split("async function loadSubmissions")[0]   # the report refreshes itself while visible
    assert "subs.timer" in code.split("function stopAvailabilityTimer")[1].split("}")[0]            # and stops when the page is left


def test_filter_cards_are_four_in_a_row_on_desktop_and_two_by_two_on_mobile_with_a_visible_selected_state():
    mobile = CSS.split("@media (min-width: 768px)")[0]
    assert ".stat-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr));" in mobile
    assert "repeat(4, minmax(0, 1fr))" in CSS.split("@media (min-width: 768px)")[1].split(".emp-summary")[1].split("}")[0] or ".stat-grid { grid-template-columns: repeat(4, minmax(0, 1fr)); }" in CSS
    assert '.stat[aria-pressed="true"] { border-color: var(--accent); background: var(--accent-soft)' in CSS


def test_collapsed_card_timestamp_label_is_last_update():
    assert _strings()["submissions"]["updated"] == "עדכון אחרון: {when}"


# ------------------------------------------------------------------ every day needs an explicit choice (form)
def test_the_form_requires_a_choice_for_every_day_and_names_the_missing_days():
    a = _strings()["availability"]
    assert a["missingOne"] == "יש לבחור זמינות ב{day}" and a["missingMany"] == "יש לבחור זמינות בימים: {days}"
    assert a["notChosen"] == "לא נבחרה זמינות" and a["none"] == "לא זמין/ה"
    code = _strip_js_comments(APP_JS)
    assert "AM.missingDays(avail.sel, avail.off, avail.data.week.days)" in code.split("async function saveAvailability")[1].split("// ---- manager")[0]
    assert "unavailable_days: AM.unavailableList(avail.off, avail.data.week.days)" in code                      # the explicit days are sent
    assert "function flagMissingDays" in code and "scrollIntoView" in code and "first.focus(" in code            # scroll to and focus the first incomplete day
    assert 'card.classList.toggle("is-unset"' in code and 'card.classList.toggle("has-error"' in code            # three distinct day states
    assert "AM.offFromDays(" in code and "offFromSlots" not in code                                              # an empty day is never assumed unavailable
    assert "legacy-notice" in code                                                                               # older submissions explain which days need a choice
    # an incomplete form can still be submitted so the click explains it; only an over-long text or a clean form disables the button
    assert 'submit.disabled = avail.busy || probs.includes("text_too_long") || (!!d.submission && !dirty)' in code
    assert ".day-card.is-unset" in CSS and ".day-card.has-error" in CSS and "prefers-reduced-motion" in code
