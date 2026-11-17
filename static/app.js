/* Shiftimizer: the UI shell. It displays what the backend allows; authority stays on the server.
   Vanilla JS, no build step. Rules (checked by tests/test_ui_shell.py):
   - all copy comes from strings.js (window.T);
   - DOM is built with createElement/textContent; HTML strings are never assembled from data;
   - every state-changing request carries X-Requested-With (CSRF policy in app/security.py). */
(() => {
  "use strict";
  const T = window.T;
  const MD = window.SafeMarkdown;
  const AM = window.AvailabilityModel;
  const $ = (id) => document.getElementById(id);
  const SVG_NS = "http://www.w3.org/2000/svg";
  const HEBREW = /[֐-׿]/;
  const state = { user: null, conversations: [], current: null, streaming: false, route: null, historyState: "idle" };

  // ---------------------------------------------------------------- helpers
  const fmt = (s, vars = {}) => s.replace(/\{(\w+)\}/g, (_, k) => (vars[k] === undefined ? "" : String(vars[k])));
  const get = (path) => path.split(".").reduce((o, k) => (o ? o[k] : undefined), T);

  function el(tag, attrs, ...children) {
    const node = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === false || v === null || v === undefined) continue;
      if (k === "class") node.className = v;
      else if (k === "text") node.textContent = v;
      else node.setAttribute(k, v === true ? "" : v);
    }
    for (const c of children.flat()) if (c !== null && c !== undefined) node.append(c);
    return node;
  }
  function icon(name, cls) {
    const svg = document.createElementNS(SVG_NS, "svg");
    svg.setAttribute("class", "icon" + (cls ? " " + cls : ""));
    svg.setAttribute("aria-hidden", "true");
    const use = document.createElementNS(SVG_NS, "use");
    use.setAttribute("href", "#i-" + name);
    svg.append(use);
    return svg;
  }
  function applyStrings(root = document) {
    root.querySelectorAll("[data-t]").forEach((n) => { n.textContent = get(n.dataset.t) || ""; });
    root.querySelectorAll("[data-t-aria-label]").forEach((n) => { n.setAttribute("aria-label", get(n.dataset.tAriaLabel) || ""); });
  }
  const announce = (msg) => { const live = $("live"); live.textContent = ""; setTimeout(() => { live.textContent = msg; }, 30); };
  const timeText = (iso) => {
    const d = iso ? new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z") : new Date();
    return d.toLocaleTimeString("he-IL", { hour: "2-digit", minute: "2-digit" });
  };
  const dateText = (iso) => {
    const d = new Date(iso.endsWith("Z") || iso.includes("+") ? iso : iso + "Z");
    return d.toLocaleDateString("he-IL", { day: "numeric", month: "short" });
  };

  // ---------------------------------------------------------------- API
  class ApiError extends Error {
    constructor(status, message) { super(message); this.status = status; }
  }
  function messageFor(status, detail, retryAfter, path) {
    if (status === 401) return path === "/api/login" ? T.login.wrong : T.login.expired;
    if (status === 429 && path === "/api/login") {
      const minutes = Math.max(1, Math.round((parseInt(retryAfter, 10) || 60) / 60));
      return fmt(T.login.blocked, { minutes });
    }
    if (typeof detail === "string" && HEBREW.test(detail)) return detail;  // server messages are Hebrew
    if (status === 403) return T.errors.forbidden;
    if (status === 422 || status === 400) return T.errors.invalid;
    if (status === 429) return T.errors.limit;
    return T.errors.generic;
  }
  async function request(path, options = {}) {
    let res;
    try {
      res = await fetch(path, {
        credentials: "same-origin",
        ...options,
        headers: { "Content-Type": "application/json", "X-Requested-With": "shift-copilot", ...(options.headers || {}) },
      });
    } catch (_) {
      throw new ApiError(0, T.errors.network);
    }
    return res;
  }
  async function api(path, options = {}) {
    const { quiet, ...fetchOptions } = options;
    const res = await request(path, fetchOptions);
    if (!res.ok) {
      let detail = null, errors = null;
      try { const body = await res.json(); detail = body.detail; errors = body.errors; } catch (_) { /* not JSON */ }
      const err = new ApiError(res.status, messageFor(res.status, detail, res.headers.get("Retry-After"), path));
      err.errors = Array.isArray(errors) ? errors : [];
      if (res.status === 401 && path !== "/api/login" && !quiet) showLogin(T.login.expired);
      throw err;
    }
    return res.status === 204 ? null : res.json();
  }

  // ---------------------------------------------------------------- views
  function show(view) {
    $("view-login").hidden = view !== "login";
    $("view-app").hidden = view !== "app";
  }
  function showLogin(message, kind = "error") {
    state.user = null; state.current = null; state.conversations = [];
    show("login");
    setNotice($("login-notice"), message, kind);
    const form = $("login-form"); form.reset(); setBusy(false);
    $("login-name").focus({ preventScroll: true });
  }
  function setNotice(box, message, kind = "error") {
    box.replaceChildren();
    box.hidden = !message;
    box.className = "notice " + (kind === "info" ? "notice-info" : "notice-error");
    if (message) box.append(icon(kind === "info" ? "info" : "alert"), el("span", { text: message }));
  }
  function setBusy(busy) {
    const b = $("login-submit");
    b.disabled = busy;
    b.replaceChildren(busy ? el("span", { class: "spinner", "aria-hidden": "true" }) : "", el("span", { text: busy ? T.login.submitting : T.login.submit }));
  }

  const DESTINATIONS = {
    manager: [{ id: "assistant", label: "nav.assistant", icon: "sparkle" }, { id: "submissions", label: "nav.submissions", icon: "calendar" }],
    employee: [{ id: "availability", label: "nav.availability", icon: "calendar" }],
  };
  const destinations = () => DESTINATIONS[state.user.role] || DESTINATIONS.employee;

  function showApp() {
    show("app");
    $("appbar-name").textContent = state.user.name;
    setupUserMenu();
    renderNav();
    route();
  }
  // The top-corner user menu (both roles): who is signed in, my account, sign out.
  function setupUserMenu() {
    const btn = $("user-btn"), menu = $("user-menu");
    closeUserMenu(false);
    btn.setAttribute("aria-haspopup", "menu"); btn.setAttribute("aria-expanded", "false"); btn.setAttribute("aria-controls", "user-menu");
    const item = (iconName, label, onClick, flip) => {
      const b = el("button", { class: "user-menu-item", type: "button", role: "menuitem" }, icon(iconName, flip), el("span", { text: label }));
      b.addEventListener("click", () => { closeUserMenu(false); onClick(); });
      return b;
    };
    menu.replaceChildren(
      el("div", { class: "user-menu-who" }, el("strong", { text: state.user.name }), el("span", { text: T.role[state.user.role] || "" })),
      item("user", T.account.title, () => { location.hash = "#/account"; }),
      item("logout", T.account.logout, doLogout, "flip-rtl"));
  }
  function openUserMenu() {
    const btn = $("user-btn"), menu = $("user-menu");
    menu.hidden = false; btn.setAttribute("aria-expanded", "true");
    const first = menu.querySelector(".user-menu-item"); if (first) first.focus();
  }
  function closeUserMenu(returnFocus) {
    const btn = $("user-btn"), menu = $("user-menu");
    if (!btn || !menu || menu.hidden) return;
    menu.hidden = true; btn.setAttribute("aria-expanded", "false");
    if (returnFocus) btn.focus();
  }
  function bindUserMenu() {
    const btn = $("user-btn"), menu = $("user-menu");
    btn.addEventListener("click", () => { if (menu.hidden) openUserMenu(); else closeUserMenu(true); });
    document.addEventListener("click", (e) => { if (!menu.hidden && !$("appbar-user").contains(e.target)) closeUserMenu(false); });
    $("appbar-user").addEventListener("keydown", (e) => {
      if (menu.hidden) return;
      const items = [...menu.querySelectorAll(".user-menu-item")], i = items.indexOf(document.activeElement);
      if (e.key === "Escape") { e.preventDefault(); closeUserMenu(true); }
      else if (e.key === "ArrowDown") { e.preventDefault(); items[(i + 1) % items.length].focus(); }
      else if (e.key === "ArrowUp") { e.preventDefault(); items[(i - 1 + items.length) % items.length].focus(); }
      else if (e.key === "Tab") closeUserMenu(false);
    });
  }
  function renderNav() {
    const nav = $("nav");
    nav.replaceChildren(...destinations().map((d) => {
      const a = el("a", { href: "#/" + d.id, "data-route": d.id }, icon(d.icon), el("span", { text: get(d.label) }));
      return a;
    }));
  }
  function route() {
    if (!state.user) return;
    const wanted = (location.hash || "").replace(/^#\//, "");
    const allowed = destinations().map((d) => d.id);
    const id = allowed.includes(wanted) || wanted === "account" ? wanted : allowed[0];   // "account" is reached from the user menu, not the navigation
    if (id !== wanted) history.replaceState(null, "", "#/" + id);
    state.route = id;
    $("nav").querySelectorAll("a").forEach((a) => {
      if (a.dataset.route === id) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    stopAvailabilityTimer();
    const main = $("main");
    main.replaceChildren();
    ({ assistant: renderAssistant, submissions: renderSubmissions, availability: renderAvailability, account: renderAccount })[id](main);
    const h1 = main.querySelector("h1");
    if (h1) { h1.setAttribute("tabindex", "-1"); h1.focus({ preventScroll: true }); }
    document.title = get("nav." + (id === "assistant" ? "assistant" : id)) + " · " + T.app.name;
    main.scrollTop = 0;
  }

  // ---- employee: the availability form (spec.md section 5)
  const avail = { data: null, sel: {}, off: {}, flagged: false, text: "", saved: { sel: {}, text: "" }, skew: 0, timer: null, inputs: {}, busy: false, notice: "", lost: false };
  const fmtDay = (iso) => new Intl.DateTimeFormat("he-IL", { weekday: "long", timeZone: "UTC" }).format(new Date(iso + "T00:00:00Z"));
  const fmtDate = (iso, year) => new Intl.DateTimeFormat("he-IL", { day: "numeric", month: "long", ...(year ? { year: "numeric" } : {}), timeZone: "UTC" }).format(new Date(iso + "T00:00:00Z"));
  const fmtWhen = (iso) => new Intl.DateTimeFormat("he-IL", { weekday: "long", day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "Asia/Jerusalem" }).format(new Date(iso));
  // "יום שלישי, 24.11.26 בשעה 22:00" (Asia/Jerusalem), built from parts so the order never depends on the browser's pattern
  const deadlineParts = (iso) => {
    const p = {};
    new Intl.DateTimeFormat("he-IL", { weekday: "long", day: "2-digit", month: "2-digit", year: "2-digit", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "Asia/Jerusalem" })
      .formatToParts(new Date(iso)).forEach((x) => { p[x.type] = x.value; });
    return p;
  };
  const fmtDeadline = (iso) => {
    const p = deadlineParts(iso);
    return `${p.weekday}, ${p.day}.${p.month}.${p.year} ${T.availability.atHour} ${p.hour}:${p.minute}`;
  };
  // the manager notice reads "יום שלישי, 24.11.26, בשעה 22:00" (with a comma after the date)
  const fmtDeadlineComma = (iso) => {
    const p = deadlineParts(iso);
    return `${p.weekday}, ${p.day}.${p.month}.${p.year}, ${T.availability.atHour} ${p.hour}:${p.minute}`;
  };
  const fmtStamp = (iso) => new Intl.DateTimeFormat("he-IL", { day: "numeric", month: "long", hour: "2-digit", minute: "2-digit", hourCycle: "h23", timeZone: "Asia/Jerusalem" }).format(new Date(iso));
  const weekRange = (start, end) => fmt(T.availability.week, { start: fmtDate(start), end: fmtDate(end, true) });

  function stopAvailabilityTimer() {
    if (subs.timer) { clearInterval(subs.timer); subs.timer = null; }
    if (avail.timer) { clearInterval(avail.timer); avail.timer = null; }
    window.onbeforeunload = null;
  }
  const isDirty = () => AM.isDirty(avail.sel, avail.text, avail.saved, avail.off);

  async function renderAvailability(main) {
    avail.inputs = {}; avail.notice = ""; avail.busy = false;
    const body = el("div", { class: "stack", id: "avail-body" }, el("p", { class: "muted", text: T.status.loading }));
    main.append(el("div", { class: "screen" }, el("h1", { text: T.availability.heading }), body));
    await loadAvailability(true);
  }

  async function loadAvailability(first) {
    const body = $("avail-body"); if (!body) return;
    try {
      const data = await api("/api/availability");
      avail.data = data;
      avail.skew = Date.parse(data.cycle.now) - Date.now();
      const mine = data.submission;
      avail.saved = { sel: AM.fromSlots(mine ? mine.slots : []), text: mine && mine.free_text ? mine.free_text : "", off: AM.offFromDays(mine ? mine.unavailable_days : []) };
      if (first || !isDirty() || !data.editable) { avail.sel = AM.fromSlots(mine ? mine.slots : []); avail.text = avail.saved.text; avail.off = AM.offFromDays(mine ? mine.unavailable_days : []); avail.flagged = false; }
      drawAvailability();
    } catch (e) {
      if (!$("avail-body")) return;
      const retry = el("button", { class: "btn", type: "button", text: T.availability.refresh });
      retry.addEventListener("click", () => loadAvailability(true));
      $("avail-body").replaceChildren(el("div", { class: "notice notice-error", role: "alert" }, icon("alert"), el("span", { text: e.message || T.availability.loadFailed })), retry);
    }
  }

  function statusCard(data) {
    const c = data.cycle, A = T.availability;
    const card = el("section", { class: "card status-card", "aria-label": A.stateTitle },
      el("p", { class: "week-range", text: weekRange(data.week.start, data.week.end) }));
    if (c.state === "open") {
      card.append(el("p", { id: "deadline-line", text: fmt(A.closesAt, { when: fmtDeadline(c.closes_at) }) }));
    } else {
      card.append(el("p", { text: A.openingNotice }), el("p", { class: "muted", text: fmt(A.latestOpen, { when: fmtWhen(c.latest_opens_at) }) }),
        el("p", { class: "muted", text: A.editUntil }));
    }
    if (avail.lost) { card.append(el("div", { class: "notice notice-error", role: "alert" }, icon("alert"), el("span", { text: A.closedWhileEditing }))); }
    return card;
  }

  function lockedCard(locked) {
    const A = T.availability, shifts = avail.data.shifts, sub = locked.submission;
    const byDay = {};
    sub.slots.forEach((s) => { (byDay[s.day] = byDay[s.day] || []).push(s.shift_id); });
    const list = el("ul", { class: "locked-days" }, Object.keys(byDay).sort().map((day) => {
      const names = byDay[day].map((id) => (shifts.find((x) => x.id === id) || { name: "" }).name);
      return el("li", {}, el("strong", { text: fmtDay(day) + ", " + fmtDate(day) }), " · ", names.join(", "));
    }));
    const card = el("section", { class: "card locked-card" }, el("h2", { text: A.lockedTitle }), el("p", { class: "muted", text: fmt(A.lockedWeek, { start: fmtDate(locked.week_start), end: fmtDate(locked.week_end, true) }) }), list);
    if ((sub.unavailable_days || []).length) card.append(el("p", { class: "muted", text: fmt(A.lockedUnavailable, { days: sub.unavailable_days.map(fmtDay).join(", ") }) }));
    if (sub.free_text) card.append(el("h3", { text: A.lockedRequests }), el("p", { class: "free-text", dir: "auto", text: sub.free_text }));
    card.append(el("div", { class: "notice notice-info" }, icon("info"), el("span", { text: A.lockedNote })));
    return card;
  }

  function drawAvailability() {
    const body = $("avail-body"); if (!body) return;
    const d = avail.data, A = T.availability;
    stopAvailabilityTimer();
    avail.inputs = {};
    body.replaceChildren(statusCard(d));
    if (!d.shifts.length) body.append(el("div", { class: "notice notice-error", role: "alert" }, icon("alert"), el("span", { text: A.noShifts })));
    else if (d.editable) body.append(...buildForm(d));
    if (d.locked_week) body.append(lockedCard(d.locked_week));
    startCloseWatch();
    syncForm();
  }

  // No countdown is shown, but the page still notices the deadline passing and reloads the locked state.
  function startCloseWatch() {
    const c = avail.data.cycle;
    if (c.state !== "open") return;
    const closes = Date.parse(c.closes_at);
    const tick = () => {
      const left = (closes - (Date.now() + avail.skew)) / 1000;
      if (left <= 0) { stopAvailabilityTimer(); avail.lost = isDirty(); loadAvailability(false); }
    };
    tick();
    avail.timer = setInterval(tick, 20000);
  }

  function buildForm(d) {
    const A = T.availability;
    const days = el("div", { class: "day-grid" });
    d.week.days.forEach((day) => {
      const name = fmtDay(day);
      const all = el("button", { class: "btn", type: "button", "aria-label": fmt(A.allAria, { day: name }) }, el("span", { text: A.all }));
      const none = el("button", { class: "btn", type: "button", "aria-label": fmt(A.noneAria, { day: name }) }, el("span", { text: A.none }));
      none.setAttribute("aria-pressed", "false"); none.dataset.role = "none"; all.dataset.role = "all";
      all.addEventListener("click", () => { const r = AM.selectAllDay(avail.sel, avail.off, day, d.shifts); avail.sel = r.sel; avail.off = r.off; syncForm(); });
      none.addEventListener("click", () => { const r = AM.toggleOff(avail.sel, avail.off, day); avail.sel = r.sel; avail.off = r.off; syncForm(); });
      const count = el("span", { class: "muted day-count", id: "count-" + day });
      const checks = d.shifts.map((sh) => {
        const input = el("input", { type: "checkbox", id: "chk-" + day + "-" + sh.id });
        input.addEventListener("change", () => { avail.sel = AM.toggle(avail.sel, day, sh.id, input.checked); syncForm(); });
        avail.inputs[AM.key(day, sh.id)] = input;
        return el("label", { class: "check", for: input.id }, input, el("span", { class: "check-text" }, el("span", { class: "check-name", text: sh.name }), el("span", { class: "check-time ltr", text: sh.start_time + "–" + sh.end_time })));
      });
      days.append(el("fieldset", { class: "day-card", id: "day-" + day },
        el("legend", { class: "sr-only", text: fmt(A.shiftsOf, { day: name }) }),
        el("div", { class: "day-head" }, el("h3", { text: name + ", " + fmtDate(day) }), count),
        el("div", { class: "day-body" }, el("div", { class: "checks" }, checks), el("div", { class: "shortcuts" }, all, none))));
    });
    const slotsError = el("div", { class: "notice notice-error", id: "slots-error", role: "alert", hidden: true });
    // A submission saved before every day needed a choice keeps its shifts; its empty days are not assumed to be anything.
    const unchosen = d.submission ? AM.missingDays(avail.saved.sel, avail.saved.off, d.week.days) : [];
    const legacy = unchosen.length ? el("div", { class: "notice notice-info", id: "legacy-notice" }, icon("info"), el("span", { text: fmt(A.legacyNotice, { days: unchosen.map(fmtDay).join(", ") }) })) : "";
    const daysCard = el("section", { class: "stack" }, el("h2", { text: A.daysTitle }), el("p", { class: "muted", text: A.daysHelp }), legacy, slotsError, days);

    const ta = el("textarea", { class: "input", id: "free-text", rows: "4", dir: "auto", "aria-describedby": "free-help free-notice free-count", maxlength: "5000" });
    ta.value = avail.text;
    ta.addEventListener("input", () => { avail.text = ta.value; syncForm(); });
    const textError = el("div", { class: "notice notice-error", id: "text-error", role: "alert", hidden: true });
    const freeCard = el("section", { class: "card stack" },
      el("h2", {}, A.freeTitle + " ", el("span", { class: "muted optional", text: A.freeOptional })),
      el("div", { class: "field" }, el("label", { for: "free-text", text: A.freeLabel }), el("span", { class: "hint", id: "free-help", text: A.freeHelp }), ta,
        el("span", { class: "hint counter", id: "free-count" })),
      el("div", { class: "notice notice-info", id: "free-notice" }, icon("info"), el("span", { text: A.freeNotice })), textError);
    avail.inputs.text = ta;

    const mine = d.submission;
    const status = el("p", { class: "submission-status" + (mine ? " done" : ""), id: "submission-status",
      text: mine ? fmt(A.submissionDone, { when: fmtStamp(mine.updated_at) }) : A.submissionNone });
    const msg = el("p", { class: "save-note", id: "save-note", role: "status" });
    const help = el("p", { class: "muted", id: "save-help" });
    const submit = el("button", { class: "btn btn-primary", type: "submit", id: "btn-save" });
    const bar = el("div", { class: "submit-bar" }, el("div", { class: "submit-text" }, status, msg, help), submit);
    const form = el("form", { class: "stack", id: "avail-form", novalidate: true }, daysCard, freeCard, bar,
      el("p", { class: "muted", id: "cannot-work", text: A.cannotWork }));
    form.addEventListener("submit", saveAvailability);
    return [form];
  }

  function syncForm() {
    if (!$("avail-form")) return;
    const d = avail.data, A = T.availability;
    d.week.days.forEach((day) => {
      const off = AM.isOff(avail.off, day);
      d.shifts.forEach((sh) => { const i = avail.inputs[AM.key(day, sh.id)]; if (i) { i.checked = AM.has(avail.sel, day, sh.id); i.disabled = off; } });
      const n = AM.countDay(avail.sel, day), node = $("count-" + day);
      if (node) node.textContent = off ? A.none : (n ? fmt(A.selectedCount, { n }) : A.notChosen);
      const card = $("day-" + day);
      if (card) {
        card.classList.toggle("has-selection", n > 0); card.classList.toggle("is-off", off); card.classList.toggle("is-unset", n === 0 && !off);
        const flagged = avail.flagged && n === 0 && !off;      // after a blocked save, the days still without a choice are marked
        card.classList.toggle("has-error", flagged); card.setAttribute("aria-invalid", flagged ? "true" : "false");
        const noneBtn = card.querySelector('[data-role="none"]'); if (noneBtn) { noneBtn.setAttribute("aria-pressed", off ? "true" : "false"); noneBtn.classList.toggle("is-active", off); }
      }
    });
    const len = AM.textLength(avail.text), counter = $("free-count");
    if (counter) { counter.textContent = fmt(A.counter, { n: len.toLocaleString("he-IL"), max: AM.TEXT_MAX.toLocaleString("he-IL") }); counter.classList.toggle("over", len > AM.TEXT_MAX); }
    const dirty = isDirty(), probs = AM.problems(avail.sel, avail.text), submit = $("btn-save");
    const missing = AM.missingDays(avail.sel, avail.off, d.week.days);
    if (avail.flagged) {                                    // keep the blocked-save message current while the employee fixes the days
      if (missing.length) showFieldError("slots-error", missingDaysMessage(missing)); else { avail.flagged = false; showFieldError("slots-error", ""); }
    }
    if (dirty) avail.notice = "";   // the "saved" message is about the previous version
    submit.replaceChildren(avail.busy ? el("span", { class: "spinner", "aria-hidden": "true" }) : "", el("span", { text: avail.busy ? A.saving : (d.submission ? A.update : A.save) }));
    // An incomplete form can still be submitted: the click explains which days are missing (and scrolls to the first).
    submit.disabled = avail.busy || probs.includes("text_too_long") || (!!d.submission && !dirty);
    const help = $("save-help");
    help.textContent = missing.length ? fmt(A.daysLeft, { n: missing.length }) : (AM.count(avail.sel) === 0 ? A.needOne : (dirty ? A.unsaved : ""));
    help.classList.toggle("dirty", dirty && !missing.length && AM.count(avail.sel) > 0);
    const left = d.limits.saves_left;
    if (left <= 5 && !avail.notice) help.textContent = (help.textContent ? help.textContent + " " : "") + fmt(A.savesLeft, { n: left });
    $("save-note").textContent = avail.notice;
    window.onbeforeunload = dirty ? (e) => { e.preventDefault(); e.returnValue = ""; } : null;
  }

  function showFieldError(id, message) {
    const box = $(id); if (!box) return;
    box.replaceChildren(); box.hidden = !message;
    if (message) box.append(icon("alert"), el("span", { text: message }));
  }

  const missingDaysMessage = (days) => days.length === 1
    ? fmt(T.availability.missingOne, { day: fmtDay(days[0]) })
    : fmt(T.availability.missingMany, { days: days.map(fmtDay).join(", ") });

  // A blocked save: name every day without a choice, mark those days, scroll to the first and move focus into it.
  function flagMissingDays(missing) {
    avail.flagged = true;
    syncForm();
    showFieldError("slots-error", missingDaysMessage(missing));
    const card = $("day-" + missing[0]);
    if (card) {
      const reduce = window.matchMedia && window.matchMedia("(prefers-reduced-motion: reduce)").matches;
      card.scrollIntoView({ block: "center", behavior: reduce ? "auto" : "smooth" });
      const first = card.querySelector("input:not(:disabled), button");
      if (first) first.focus({ preventScroll: true });
    }
  }

  async function saveAvailability(e) {
    e.preventDefault();
    if (avail.busy) return;
    showFieldError("slots-error", ""); showFieldError("text-error", ""); avail.notice = "";
    const missing = AM.missingDays(avail.sel, avail.off, avail.data.week.days);
    if (missing.length) { flagMissingDays(missing); return; }      // every day needs an explicit choice (the server checks it too)
    const probs = AM.problems(avail.sel, avail.text);
    if (probs.includes("no_slots")) { showFieldError("slots-error", T.availability.needOne); return; }
    avail.busy = true; syncForm();
    try {
      const data = await api("/api/availability", { method: "PUT", body: JSON.stringify({ week_start: avail.data.week.start, slots: AM.toSlots(avail.sel), unavailable_days: AM.unavailableList(avail.off, avail.data.week.days), free_text: avail.text.trim() ? avail.text : null }) });
      avail.data = data; avail.lost = false; avail.flagged = false;
      avail.saved = { sel: AM.fromSlots(data.submission.slots), text: data.submission.free_text || "", off: AM.offFromDays(data.submission.unavailable_days) };
      avail.sel = AM.fromSlots(data.submission.slots); avail.text = avail.saved.text;
      avail.off = AM.offFromDays(data.submission.unavailable_days);
      avail.notice = fmt(T.availability.saved, { when: fmtWhen(data.cycle.closes_at) });
      avail.busy = false;
      drawAvailability(); announce(avail.notice);
    } catch (err) {
      avail.busy = false;
      const fields = (err.errors || []);
      const slotMsg = fields.find((f) => f.field === "slots" || f.field === "days"), textMsg = fields.find((f) => f.field === "free_text");
      if (slotMsg || textMsg) { syncForm(); showFieldError("slots-error", slotMsg ? slotMsg.message : ""); showFieldError("text-error", textMsg ? textMsg.message : ""); }
      else if (err.status === 409) { await loadAvailability(false); avail.notice = ""; const b = $("avail-body"); if (b) b.prepend(el("div", { class: "notice notice-error", role: "alert" }, icon("alert"), el("span", { text: err.message }))); }
      else { avail.notice = ""; syncForm(); showFieldError("slots-error", err.message); }
    }
  }

  // ---- manager: read-only report of the target week's submissions ("הגשות עובדים"); the server allows managers only
  const dateRange = (r) => {
    if (r.start === r.end) return fmtDate(r.start);
    const a = new Date(r.start + "T00:00:00Z"), b = new Date(r.end + "T00:00:00Z");
    if (a.getUTCMonth() === b.getUTCMonth()) return a.getUTCDate() + "–" + fmtDate(r.end);
    return fmtDate(r.start) + " – " + fmtDate(r.end);
  };
  const leaveText = (dates) => AM.groupDates(dates).map(dateRange).join(", ");

  const subs = { filter: "total", data: null, timer: null };      // the selected status card survives refreshes and visits

  function renderSubmissions(main) {
    const S = T.submissions;
    const body = el("div", { class: "stack", id: "subs-body" }, el("p", { class: "muted", text: T.status.loading }));
    const refresh = el("button", { class: "btn", type: "button", id: "subs-refresh" }, el("span", { text: S.refresh }));
    refresh.addEventListener("click", () => loadSubmissions(true));
    main.append(el("div", { class: "screen" }, el("div", { class: "screen-head" }, el("h1", { text: S.title }), refresh), body));
    loadSubmissions(false);
    // The report stays current without a click: while this page is visible it refetches every minute (read-only, no AI call).
    subs.timer = setInterval(() => { if (document.visibilityState === "visible") loadSubmissions(false, true); }, 60000);
  }

  async function loadSubmissions(manual, silent) {
    const S = T.submissions, body = $("subs-body"), btn = $("subs-refresh");
    if (!body) return;
    if (btn && !silent) { btn.disabled = true; btn.querySelector("span").textContent = S.refreshing; }
    try {
      const data = await api("/api/submissions");      // a 401 (expired session) sends the manager to the login screen, also on a background refresh
      if (!$("subs-body")) return;
      drawSubmissions(data);
      if (manual) announce(S.title);
    } catch (e) {
      if (!$("subs-body") || silent) return;      // a failed background refresh keeps the last good report on screen
      const retry = el("button", { class: "btn", type: "button", text: S.retry });
      retry.addEventListener("click", () => loadSubmissions(true));
      $("subs-body").replaceChildren(el("div", { class: "notice notice-error", role: "alert" }, icon("alert"), el("span", { text: e.message || S.loadFailed })), retry);
    } finally {
      const b = $("subs-refresh"); if (b) { b.disabled = false; b.querySelector("span").textContent = S.refresh; }
    }
  }

  function badge(text, kind) { return el("span", { class: "badge badge-" + kind, text }); }

  const fmtDayParts = (iso) => {
    const p = {};
    new Intl.DateTimeFormat("he-IL", { weekday: "long", day: "2-digit", month: "2-digit", timeZone: "UTC" }).formatToParts(new Date(iso + "T00:00:00Z")).forEach((x) => { p[x.type] = x.value; });
    return { weekday: p.weekday, date: `${p.day}.${p.month}` };
  };

  function employeeCard(e, weekDays) {
    const S = T.submissions;
    const badges = el("span", { class: "badges" });
    badges.append(e.status === "submitted" ? badge(S.statusSubmitted, "ok") : e.status === "exempt" ? badge(S.statusExempt, "leave") : badge(S.statusMissing, "missing"));
    if (e.full_week_leave) badges.append(badge(S.leaveFull, "leave"));
    else if (e.leave_dates.length) badges.append(badge(fmt(S.leavePartial, { dates: leaveText(e.leave_dates) }), "leave"));
    if (e.updated_at) badges.append(el("span", { class: "emp-updated", text: fmt(S.updated, { when: fmtStamp(e.updated_at) }) }));   // last submission or update
    // name, status badge and last update form one compact group; the chevron stays at the far end
    const summary = el("summary", { class: "emp-summary" }, el("span", { class: "emp-main" }, el("span", { class: "emp-name" }, el("bdi", { text: e.name })), badges), el("span", { class: "emp-chevron", "aria-hidden": "true" }, icon("chevron")));
    const detail = el("div", { class: "emp-detail" });
    detail.append(el("h3", { text: S.shiftsTitle }));
    if (e.days.length || (e.unavailable_days || []).length) {
      // all seven days, each with its submitted shifts beside it (a dash for a day with none)
      const byDay = {}; e.days.forEach((d) => { byDay[d.date] = d.shifts; });
      const offDays = new Set(e.unavailable_days || []);
      detail.append(el("ul", { class: "emp-days" }, weekDays.map((day) => el("li", { class: "emp-day" },
        el("strong", { class: "emp-day-name" }, el("span", { class: "emp-day-w", text: fmtDayParts(day).weekday }), el("span", { class: "emp-day-d", text: fmtDayParts(day).date })),
        el("span", { class: "emp-shifts" }, (byDay[day] || []).length
          ? byDay[day].map((s) => el("span", { class: "emp-shift" }, el("span", { text: s.name }), " ", el("span", { class: "ltr", text: s.start_time + "–" + s.end_time })))
          : offDays.has(day) ? el("span", { class: "muted", text: S.dayUnavailable })      // explicitly "לא זמין/ה"
            : [el("span", { class: "muted", "aria-hidden": "true", text: "—" }), el("span", { class: "sr-only", text: S.noShiftsDay })])))));
    } else {
      detail.append(el("p", { class: "muted", text: e.status === "exempt" ? S.noShiftsExempt : S.noShifts }));
    }
    if (e.free_text) {      // the preferences section only exists when there is something to show
      detail.append(el("h3", { text: S.freeTitle }), el("p", { class: "free-text", dir: "auto", text: e.free_text }));
    }
    return el("details", { class: "emp-card", "data-status": e.status, "data-id": String(e.id) }, summary, detail);
  }

  // The four summary cards are the filters: one is selected at a time ("total" by default).
  const FILTER_CARDS = [["total", "total", "total"], ["submitted", "submitted", "ok"], ["missing", "missing", "missing"], ["leave", "onLeave", "leave"]];
  const filterCount = (c, key) => ({ total: c.total, submitted: c.submitted, missing: c.missing, leave: c.exempt })[key];

  function drawSubmissions(d) {
    const S = T.submissions, body = $("subs-body");
    const c = d.counts, cy = d.cycle;
    subs.data = d;
    const openIds = new Set([...document.querySelectorAll(".emp-card[open]")].map((x) => x.dataset.id));   // keep expanded cards across refreshes
    const tiles = el("div", { class: "stat-grid", role: "group", "aria-label": S.filterLabel, id: "subs-filters" },
      FILTER_CARDS.map(([key, label, kind]) => {
        const b = el("button", { class: "stat stat-" + kind, type: "button", "data-filter": key, "aria-pressed": String(subs.filter === key) },
          el("span", { class: "stat-n", text: String(filterCount(c, key)) }), el("span", { class: "stat-l", text: S[label] }));
        b.addEventListener("click", () => {
          subs.filter = key;
          tiles.querySelectorAll(".stat").forEach((x) => x.setAttribute("aria-pressed", String(x.dataset.filter === key)));
          drawSubmissionList();
          announce(fmt(S.showing, { label: S[label], n: filterCount(c, key) }));
        });
        return b;
      }));
    // The notice uses the closing time of the SAME window the report shows (the server picks the week and its window together).
    const notice = el("div", { class: "notice notice-info", id: "subs-notice", role: "note" }, icon("info"),
      el("span", { text: fmt(cy.state === "closed" ? S.noticeClosed : S.noticeOpen, { when: fmtDeadlineComma(cy.closes_at) }) }));
    const head = el("section", { class: "card status-card" },
      el("p", { class: "week-range", text: fmt(S.week, { start: fmtDate(d.week.start), end: fmtDate(d.week.end, true) }) }));
    body.replaceChildren(notice, head, tiles, el("div", { id: "subs-list" }));
    drawSubmissionList(openIds);
  }

  function drawSubmissionList(openIds) {
    const S = T.submissions, d = subs.data, host = $("subs-list");
    if (!d || !host) return;
    const keep = openIds || new Set([...document.querySelectorAll(".emp-card[open]")].map((x) => x.dataset.id));
    const rows = AM.filterEmployees(d.employees, subs.filter);
    const emptyText = !d.employees.length ? S.empty : ({ submitted: S.emptySubmitted, missing: S.emptyMissing, leave: S.emptyLeave })[subs.filter] || S.empty;
    host.replaceChildren(rows.length
      ? el("section", { class: "emp-list", "aria-label": S.list }, rows.map((e) => employeeCard(e, d.week.days)))
      : el("p", { class: "muted empty-state", id: "subs-empty", text: emptyText }));
    host.querySelectorAll(".emp-card").forEach((x) => { if (keep.has(x.dataset.id)) x.open = true; });
  }

  // ---- account (both roles)
  function renderAccount(main) {
    const logout = el("button", { class: "btn", type: "button", id: "btn-logout" }, icon("logout", "flip-rtl"), el("span", { text: T.account.logout }));
    logout.addEventListener("click", doLogout);
    const legal = el("button", { class: "btn btn-quiet", type: "button" }, icon("info"), el("span", { text: T.account.legalLink }));
    legal.addEventListener("click", () => $("dlg-legal").showModal());
    main.append(el("div", { class: "screen" },
      el("h1", { text: T.account.title }),
      el("section", { class: "card" },
        el("dl", { class: "kv" },
          el("dt", { text: T.account.name }), el("dd", { text: state.user.name, dir: "auto" }),
          el("dt", { text: T.account.role }), el("dd", { text: T.role[state.user.role] || "" })),
        logout),
      el("section", { class: "card" },
        el("h2", { text: T.account.about }),
        el("p", { class: "muted" }, el("span", { class: "ltr", text: T.app.name }), " · ", T.account.aboutBody),
        el("p", { class: "muted", text: T.app.demoNote }),
        el("div", { class: "mt" }, legal))));
  }
  async function doLogout() {
    const b = $("btn-logout");
    if (b) { b.disabled = true; b.querySelector("span").textContent = T.account.loggingOut; }
    try { await api("/api/logout", { method: "POST" }); } catch (_) { /* the cookie may already be gone */ }
    showLogin(T.login.loggedOut, "info");
    history.replaceState(null, "", location.pathname);
  }

  // ---- manager: the Copilot
  function renderAssistant(main) {
    const btnHistory = el("button", { class: "btn icon-btn", type: "button", id: "btn-history", "aria-label": T.assistant.history, "aria-expanded": "false", "aria-controls": "history" }, icon("history"));
    const btnNew = el("button", { class: "btn", type: "button", id: "btn-new" }, icon("plus"), el("span", { text: T.assistant.newChat }));
    const title = el("h1", { id: "chat-title", text: T.assistant.title });
    const messages = el("div", { class: "messages", id: "messages", role: "log", "aria-live": "polite", "aria-relevant": "additions" });
    const input = el("textarea", { class: "input", id: "input", rows: "1", dir: "auto", placeholder: T.assistant.placeholder, "aria-label": T.assistant.placeholder, maxlength: "4000" });
    const send = el("button", { class: "btn btn-primary icon-btn", type: "submit", id: "btn-send", "aria-label": T.assistant.send }, icon("send", "flip-rtl"));
    const composer = el("form", { class: "composer", id: "composer" }, input, send);
    const chatMain = el("section", { class: "chat-main", id: "chat-main" },
      el("div", { class: "chat-toolbar" }, btnHistory, title, btnNew), messages, composer);
    const close = el("button", { class: "btn btn-quiet icon-btn", type: "button", id: "btn-history-close", "aria-label": T.history.close }, icon("close"));
    const list = el("div", { id: "history-body", class: "contents" });
    const aside = el("aside", { class: "history", id: "history", "aria-label": T.history.title },
      el("header", {}, el("h2", { text: T.history.title }), close), list);
    const scrim = el("div", { class: "scrim", id: "scrim", hidden: true });
    main.append(el("div", { class: "chat" }, aside, scrim, chatMain));

    btnHistory.addEventListener("click", () => toggleHistory(true));
    close.addEventListener("click", () => toggleHistory(false));
    scrim.addEventListener("click", () => toggleHistory(false));
    aside.addEventListener("keydown", (e) => { if (e.key === "Escape") toggleHistory(false); });
    btnNew.addEventListener("click", newChat);
    composer.addEventListener("submit", onSend);
    input.addEventListener("input", autosize);
    if (!window.matchMedia("(pointer: coarse)").matches) {  // desktop: Enter sends; on phones Enter is a newline
      input.addEventListener("keydown", (e) => { if (e.key === "Enter" && !e.shiftKey && !e.isComposing) { e.preventDefault(); composer.requestSubmit(); } });
    }
    renderEmpty();
    loadHistory();
    if (state.current) openConversation(state.current);
  }
  const isNarrow = () => !window.matchMedia("(min-width: 1024px)").matches;
  function toggleHistory(open) {
    const aside = $("history"); if (!aside) return;
    aside.classList.toggle("is-open", open);
    $("scrim").hidden = !open;
    $("btn-history").setAttribute("aria-expanded", String(open));
    const inert = open && isNarrow();
    $("chat-main").toggleAttribute("inert", inert);
    if (open) $("btn-history-close").focus(); else if (isNarrow()) $("btn-history").focus();
  }
  function autosize() { const t = $("input"); t.style.blockSize = "auto"; t.style.blockSize = Math.min(t.scrollHeight + 2, 152) + "px"; }

  function renderEmpty() {
    $("messages").replaceChildren(el("div", { class: "empty" },
      el("div", { class: "empty-icon" }, icon("sparkle")),
      el("h2", { text: T.assistant.emptyTitle }),
      el("p", { text: T.assistant.emptyIntro }),
      el("ul", { class: "examples" }, [T.assistant.example1, T.assistant.example2, T.assistant.example3].map((q) => el("li", { text: q }))),
      el("p", { class: "muted", text: T.assistant.emptyNote })));
  }
  function newChat() {
    state.current = null;
    $("chat-title").textContent = T.assistant.title;
    renderEmpty(); renderHistory(); toggleHistory(false);
    $("input").focus();
  }

  async function loadHistory() {
    state.historyState = "loading"; renderHistory();
    try {
      state.conversations = await api("/api/conversations");
      state.historyState = "ready";
    } catch (e) { state.historyState = "error"; }
    renderHistory();
  }
  function renderHistory() {
    const body = $("history-body"); if (!body) return;
    if (state.historyState === "loading") { body.replaceChildren(el("p", { class: "state", text: T.history.loading })); return; }
    if (state.historyState === "error") {
      const retry = el("button", { class: "btn", type: "button", text: T.history.retry });
      retry.addEventListener("click", loadHistory);
      body.replaceChildren(el("div", { class: "state", role: "alert" }, el("span", { text: T.history.failed }), retry));
      return;
    }
    if (!state.conversations.length) { body.replaceChildren(el("p", { class: "state", text: T.history.empty })); return; }
    body.replaceChildren(el("ul", {}, state.conversations.map((c) => {
      const b = el("button", { type: "button", "aria-current": c.id === state.current ? "true" : false },
        el("span", { class: "history-title-text", dir: "auto", text: c.title || T.history.untitled }), el("small", { text: dateText(c.updated_at) }));
      b.addEventListener("click", () => { openConversation(c.id); toggleHistory(false); });
      return el("li", {}, b);
    })));
  }
  async function openConversation(id) {
    state.current = id;
    const conv = state.conversations.find((c) => c.id === id);
    $("chat-title").textContent = conv ? (conv.title || T.assistant.title) : T.assistant.title;
    renderHistory();
    const box = $("messages");
    box.replaceChildren(el("p", { class: "muted", text: T.status.loading }));
    try {
      const rows = await api(`/api/conversations/${id}/messages`);
      box.replaceChildren();
      rows.forEach((m) => addMessage(m.role, m.content, m.created_at));
      if (!rows.length) renderEmpty();
      box.scrollTop = box.scrollHeight;
    } catch (e) {
      const retry = el("button", { class: "btn", type: "button", text: T.status.retry });
      retry.addEventListener("click", () => openConversation(id));
      box.replaceChildren(el("div", { class: "notice notice-error", role: "alert" }, icon("alert"), el("span", { text: e.message })), retry);
    }
  }

  function addMessage(role, text, when) {
    const box = $("messages");
    const stamp = el("time", { text: timeText(when) });
    let wrapper, body;
    if (role === "user") {
      body = el("div", { class: "bubble", dir: "auto", text });
      wrapper = el("div", { class: "msg msg-user" }, el("div", { class: "msg-meta" }, el("span", { text: state.user.name, dir: "auto" }), stamp), body);
    } else {
      body = el("div", { class: "md" });
      body.append(MD.render(text, document, { tableLabel: T.assistant.tableLabel }));
      wrapper = el("article", { class: "msg msg-ai" }, el("div", { class: "msg-meta" }, icon("sparkle"), el("span", { text: T.assistant.who }), stamp), body);
    }
    box.append(wrapper);
    box.scrollTop = box.scrollHeight;
    return { wrapper, body };
  }

  async function onSend(e) {
    e.preventDefault();
    if (state.streaming) return;
    const input = $("input");
    const text = input.value.trim();
    if (!text) return;
    if ($("messages").querySelector(".empty")) $("messages").replaceChildren();
    input.value = ""; autosize();
    addMessage("user", text);
    const bot = addMessage("assistant", "");
    bot.body.replaceChildren(el("span", { class: "dots", role: "status", "aria-label": T.assistant.thinking }, el("i"), el("i"), el("i")));
    const details = el("details", { class: "tech", hidden: true }, el("summary", { text: T.assistant.details }));
    const list = el("ul"); details.append(list); bot.wrapper.append(details);
    const send = $("btn-send"); send.disabled = true; state.streaming = true;
    let full = "";
    const note = (t) => { list.append(el("li", { text: t })); details.hidden = false; };
    try {
      const res = await request("/api/chat", { method: "POST", body: JSON.stringify({ conversation_id: state.current, message: text }) });
      if (!res.ok) {
        let detail = null; try { detail = (await res.json()).detail; } catch (_) { /* ignore */ }
        if (res.status === 401) showLogin(T.login.expired);
        throw new ApiError(res.status, messageFor(res.status, detail, null, "/api/chat"));
      }
      const reader = res.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
      while (true) {
        const { value, done } = await reader.read(); if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx;
        while ((idx = buffer.indexOf("\n\n")) >= 0) {
          const raw = buffer.slice(0, idx); buffer = buffer.slice(idx + 2);
          const line = raw.split("\n").find((l) => l.startsWith("data: ")); if (!line) continue;
          const ev = JSON.parse(line.slice(6));
          if (ev.type === "meta") {
            state.current = ev.conversation_id;
            if (ev.title) $("chat-title").textContent = ev.title;
          } else if (ev.type === "text") {
            full += ev.text;
            bot.body.replaceChildren(MD.render(full, document, { tableLabel: T.assistant.tableLabel }));
            $("messages").scrollTop = $("messages").scrollHeight;
          } else if (ev.type === "tool") {
            note(`${ev.name} · ${ev.status === "start" ? T.assistant.toolStart : T.assistant.toolDone}`);
          } else if (ev.type === "done") {
            const u = ev.usage || {};
            note(fmt(T.assistant.tokens, { input: u.input_tokens || 0, output: u.output_tokens || 0, cost: (ev.cost_usd || 0).toFixed(4) }));
          } else if (ev.type === "error") {
            full += (full ? "\n\n" : "") + `**${T.assistant.errorPrefix}:** ${ev.message}`;
            bot.body.replaceChildren(MD.render(full, document, { tableLabel: T.assistant.tableLabel }));
          }
        }
      }
    } catch (err) {
      full += (full ? "\n\n" : "") + `**${T.assistant.errorPrefix}:** ${err.message}`;
      bot.body.replaceChildren(MD.render(full, document, { tableLabel: T.assistant.tableLabel }));
    } finally {
      if (!full) bot.body.replaceChildren();
      state.streaming = false; send.disabled = false;
      loadHistory();
    }
  }

  // ---------------------------------------------------------------- login form
  function wireLogin() {
    const toggle = $("login-toggle"), code = $("login-code");
    toggle.addEventListener("click", () => {
      const show = code.type === "password";
      code.type = show ? "text" : "password";
      toggle.setAttribute("aria-pressed", String(show));
      toggle.setAttribute("aria-label", show ? T.login.hideCode : T.login.showCode);
      toggle.replaceChildren(icon(show ? "eye-off" : "eye"));
    });
    $("login-form").addEventListener("submit", async (e) => {
      e.preventDefault();
      const name = $("login-name").value.trim(), secret = code.value;
      if (!name || !secret) { setNotice($("login-notice"), T.login.missing); (name ? code : $("login-name")).focus(); return; }
      setNotice($("login-notice"), ""); setBusy(true);
      try {
        state.user = await api("/api/login", { method: "POST", body: JSON.stringify({ name, code: secret }) });
        code.value = ""; code.type = "password";
        history.replaceState(null, "", location.pathname);
        showApp();
        announce(T.login.signedIn);
      } catch (err) {
        setNotice($("login-notice"), err.message); setBusy(false); code.focus();
      }
    });
  }

  // ---------------------------------------------------------------- boot
  window.addEventListener("hashchange", route);
  document.addEventListener("DOMContentLoaded", async () => {
    applyStrings();
    wireLogin();
    bindUserMenu();
    try { state.user = await api("/api/me", { quiet: true }); showApp(); }
    catch (_) { if (!state.user) showLogin(); }
  });
})();
