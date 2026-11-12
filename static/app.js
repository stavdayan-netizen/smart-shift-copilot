/* Smart Shift Copilot: the UI shell. It displays what the backend allows; authority stays on the server.
   Vanilla JS, no build step. Rules (checked by tests/test_ui_shell.py):
   - all copy comes from strings.js (window.T);
   - DOM is built with createElement/textContent; HTML strings are never assembled from data;
   - every state-changing request carries X-Requested-With (CSRF policy in app/security.py). */
(() => {
  "use strict";
  const T = window.T;
  const MD = window.SafeMarkdown;
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
      let detail = null;
      try { detail = (await res.json()).detail; } catch (_) { /* not JSON */ }
      const err = new ApiError(res.status, messageFor(res.status, detail, res.headers.get("Retry-After"), path));
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
    manager: [{ id: "assistant", label: "nav.assistant", icon: "sparkle" }, { id: "account", label: "nav.account", icon: "user" }],
    employee: [{ id: "home", label: "nav.home", icon: "home" }, { id: "account", label: "nav.account", icon: "user" }],
  };
  const destinations = () => DESTINATIONS[state.user.role] || DESTINATIONS.employee;

  function showApp() {
    show("app");
    $("appbar-name").textContent = state.user.name;
    renderNav();
    route();
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
    const id = allowed.includes(wanted) ? wanted : allowed[0];
    if (id !== wanted) history.replaceState(null, "", "#/" + id);
    state.route = id;
    $("nav").querySelectorAll("a").forEach((a) => {
      if (a.dataset.route === id) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
    });
    const main = $("main");
    main.replaceChildren();
    ({ assistant: renderAssistant, home: renderHome, account: renderAccount })[id](main);
    const h1 = main.querySelector("h1");
    if (h1) { h1.setAttribute("tabindex", "-1"); h1.focus({ preventScroll: true }); }
    document.title = get("nav." + (id === "assistant" ? "assistant" : id)) + " · " + T.app.name;
    main.scrollTop = 0;
  }

  // ---- employee home (placeholder until the availability form exists)
  function renderHome(main) {
    main.append(el("div", { class: "screen" },
      el("h1", { text: fmt(T.home.title, { name: state.user.name }) }),
      el("section", { class: "card" }, el("h2", { text: T.home.lead }), el("p", { class: "muted", text: T.home.body }))));
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
      el("p", { text: T.assistant.emptyBody })));
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
        announce(fmt(T.home.title, { name: state.user.name }));
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
    try { state.user = await api("/api/me", { quiet: true }); showApp(); }
    catch (_) { if (!state.user) showLogin(); }
  });
})();
