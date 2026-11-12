# architecture.md — Smart Shift Copilot

**Status: PLANNED design.** Unless a line says "exists today (instructor code)", nothing here is implemented. Baseline = the instructor's Bakery Copilot as forked (commit `2a6691f`). Keep this file current in the same commit as any architectural change.

## 1. Baseline: what exists today (instructor code, inspected)

*Update after M0-1: the bakery tools, datasets, invoice UI and image upload are removed. The table below describes the reusable infrastructure that remains; the `Tools` row now has an empty registry, and `Digest` content is generic. The `users` table and shared-password login are still in place until M0-3.*

| Area | Today (bakery) | File |
|---|---|---|
| API | FastAPI, one service serving API and static UI | `app/main.py` |
| Agent loop | `run_turn`: save user msg → build context → stream model → run tools (max 6 rounds) → persist once → one `runs` row; `ModelClient` protocol with `FakeModelClient` for tests | `app/agent.py` |
| Model | Anthropic SDK streaming, `output_config.effort`, server-side fallbacks, retries 3 | `app/agent.py` |
| Tools | JSON-schema list + `execute(name, input, db, user_id)` dispatcher, results truncated | `app/tools/registry.py` |
| Auth | **Per-account login with roles, DB-backed lockout, CSRF defence (implemented in M0-3)**; was one shared password + typed name | `app/auth.py`, `app/passwords.py`, `app/throttle.py`, `app/security.py`, `app/users.py` |
| DB | SQLAlchemy 2, `create_all` + `schema_version`; SQLite local, Postgres on Railway | `app/db.py` |
| Limits & cost | per-user hourly limit, daily USD cap, price table, per-run cost | `app/limits.py`, `app/costs.py`, `app/config.py` |
| Digest | Deterministic text from DB; `python -m app.digest` cron + `POST /internal/digest` (`X-Cron-Secret`) | `app/digest.py` |
| Tests/evals | pytest with fake model; real-model evals with history CSV | `tests/`, `evals/` |
| CI | pytest on PR/push; evals if secret set | `.github/workflows/ci.yml` |
| Railway | IaC `railway.ts`: web + digest cron + Postgres, `/health` | `.railway/railway.ts` |
| UI | **Hebrew RTL, mobile-first shell (implemented in M0-4)**: plain HTML/CSS/JS, no build step, no external requests; was LTR English | `static/` |
| Logging | **Structured JSON logs, request IDs, redaction (implemented in M0-2)**; was `print()` only | `app/logging_setup.py` |
| Migrations | **Alembic (implemented in M0-2)**; was `create_all` | `alembic/`, `app/migrations.py` |

Gaps relative to this project (after M0-3: logging, migrations and per-account auth are done): no RTL/Hebrew, bakery-specific tools/prompt/seed/digest. `cost_usd()` returns **0.0 silently for a model missing from the price table** — must become a loud failure/log (see §11).

## 2. Target architecture

```
 Phone / desktop browser (Hebrew, RTL)              Railway project
 ┌──────────────────────────┐        ┌─────────────────────────────────────────────┐
 │ static/ (HTML+CSS+JS)    │ HTTPS  │ web service (FastAPI)                       │
 │  employee: form, request │───────▶│  auth/roles ─ deadline service (tz)         │
 │  manager: dashboard,     │◀───────│  availability · requests · schedule APIs    │
 │   schedule, Copilot chat │  SSE   │  scheduling engine (pure Python, no I/O)    │
 └──────────────────────────┘        │  agent loop ─ tool registry (validated)     │──▶ Anthropic API
                                     │  logging (JSON) · audit writer              │
                                     └───────────────┬─────────────────────────────┘
                                                     │ SQLAlchemy (Alembic migrations)
                                     ┌───────────────▼─────────────┐   ┌────────────────────────┐
                                     │ PostgreSQL (Railway plugin, │◀──│ digest cron service    │
                                     │ volume + backups)           │   │ python -m app.digest   │
                                     └─────────────────────────────┘   └────────────────────────┘
```

One web service (as the instructor decided: UI+API together, ~15 users), one Postgres, one cron service. No queue, no cache, no separate frontend build.

## 3. Responsibilities

- **Browser**: rendering, local UX (day shortcuts, countdown display from server-provided deadline), no authority. Hidden buttons are never authorization.
- **Backend**: all authority — identity, role checks, deadline enforcement, validation, scheduling, audit, cost limits.
- **Engine**: pure functions over plain data; no DB, no clock, no model. Easy to property-test.
- **Agent**: translates manager language into tool calls and explains results. Cannot write approved/published data directly.

## 3a. UI shell (implemented in M0-4)

- **Files:** `static/index.html` (skeleton, icon sprite, login and legal dialog), `styles.css` (tokens, components, layout), `app.js` (views, routing, API helper), `strings.js` (all copy), `markdown.js` (safe renderer), `fonts/` (Heebo woff2 + OFL licence), `favicon.svg`. No framework, bundler or CDN; the page makes no request to any other origin.
- **Views and roles:** login, then one shell. The role from `/api/me` picks the destinations: manager = Copilot + account, employee = home placeholder + account. Only working destinations are listed, so there are no disabled tabs. Hash routes outside the role's list fall back to its first destination. This is presentation only: every endpoint still enforces its role on the server (section 7). The bundle is the same for both roles.
- **Navigation:** bottom bar under 768 px, a rail on the inline-start edge from 768 px (right edge in RTL). Copilot history is a drawer (focus moves into it, the rest is made `inert`, Escape closes) under 1024 px and a column from 1024 px. After each route change focus moves to the screen heading, and a live region announces login.
- **RTL and Hebrew:** `<html lang="he" dir="rtl">`; CSS uses logical properties only (a test rejects `left/right`, `margin-left` and similar); direction-bearing icons (send, logout) are mirrored with `[dir=rtl] .flip-rtl`; user and model text blocks use `dir="auto"`; the access-code field is LTR. All copy is in `strings.js`, gender-neutral where possible; user-facing server messages (login, lockout, session, forbidden, not found, limits, agent errors) are Hebrew; `/health`, the CLI and the cron endpoint stay English because operators read them.
- **Theme:** warm neutral background (`#F6F3EE`), white cards, muted teal accent (`#2B7A78`), one calm shadow, no gradients, a small sparkle icon marks the AI. Dark mode follows `prefers-color-scheme` (default stays light). Colours are tokens in `:root`; `tests/test_ui_shell.py` computes WCAG contrast for every text/background pair in both schemes (AA) and fails below 4.5:1 (3:1 for UI accents and focus rings).
- **Typography:** Heebo variable (100-900), self-hosted woff2 subsets (Hebrew 12 KB, Latin 30 KB) loaded with `unicode-range` and `font-display: swap`; SIL OFL 1.1, licence and provenance in `static/fonts/`. Fallback stack: system-ui, Segoe UI, Arial, Noto Sans Hebrew, sans-serif (checked with Heebo blocked). Base size 16 px, line height 1.6; inputs are 16 px so iOS does not zoom.
- **Touch and accessibility:** every interactive control is at least 44 x 44 px (tokens + test + measured in the browser); visible focus rings; skip link; landmarks; `aria-current` on navigation; labelled controls; reduced-motion and forced-colors rules.
- **Secure Markdown (`markdown.js`):** supports paragraphs, `**bold**`, bullet and numbered lists and pipe tables, nothing else. A pure parser produces blocks; a builder creates elements from a fixed allow-list (`p strong br ul ol li table thead tbody tr th td div`) with fixed attributes only (`dir class role tabindex aria-label scope`) and inserts text with `createTextNode`. There is no `innerHTML`, no link or image handling, so `<script>`, `<img onerror>` and `javascript:` stay inert text (a lint test forbids `innerHTML`, `eval` and friends in the UI code; node tests include a 3,000-input fuzz run; input is capped at 20,000 characters). Tables sit in a labelled, keyboard-scrollable region so a wide table never widens the page.
- **Verification:** automated (`tests/test_ui_shell.py`, `tests/js/markdown.test.js` run in CI under node) plus `scripts/ui_check.py`, a dependency-free Chromium driver that measures overflow (both edges, because RTL overflow leaves through the left edge and `scrollWidth` does not grow), target sizes, direction, fonts and console errors at 360, 390, 768 and 1280 px in light and dark and records screenshots (`docs/ui-checks/m0-4/`).

## 4. Database schema (planned; PostgreSQL production, SQLite for fast local tests)

**Implemented in M1-1 (migration `0003`):** `shifts` (name unique, `start_time`, `end_time`, `sort_order`, `required_staff` >= 0, `start_time <> end_time`), `availability_submissions` (one per user and week, optional `pref_min`/`pref_max` with `0 <= min <= max`, optional `free_text` of at most 1,000 characters enforced by a CHECK, `submitted_at`, `updated_at`) and `availability_slots` (unique per submission, day and shift; deleted with the submission). `week_start` is always a Sunday, checked in `app/cycle.py` rather than in the database because the portable SQL differs. Shift times are wall-clock times in Asia/Jerusalem; **an `end_time` at or before the `start_time` means the shift ends on the next calendar day**, so Evening 16:00-00:00 is eight hours ending at midnight (`app/shifts.py` turns a shift and a day into a real UTC interval, across DST). Shifts are rows, not code: the seed (`python -m app.seed`) inserts missing demo shifts and never changes an existing one. SQLite does not enforce foreign keys or `ON DELETE CASCADE`, so the ORM deletes a submission's slots itself; PostgreSQL also has the cascade.

**Implemented so far (migrations `0001`, `0002`):** `users` (now with `access_role`, `code_hash`, `token_version`), `conversations`, `messages`, `runs` (the instructor's tables), `audit_log` and `login_throttle`. Decision in M0-3: the table stays named `users` (renaming to `employees` is deferred to M1-1 if still wanted), and lockout state lives in the small `login_throttle` table (keyed by HMACs of the attempted name or client address) instead of `failed_attempts`/`locked_until` columns on the user row, so unknown names are throttled exactly like real ones. Everything else in the table below is planned for M0-3 and M1-1. The schema is owned by Alembic: the app no longer calls `create_all`, and a test fails if a model differs from the migrations.

**Simplified from the first proposal (~18 tables) to 12 application tables** (+ Alembic's `alembic_version`). Rule used: keep a table when it carries integrity constraints, security, audit, or agent-usage data; fold it into a JSON column or derive it when it only holds a small blob that is always read together with its parent; defer it when it only serves a deferred feature.

All timestamps are naive UTC (instructor convention, `utcnow()`); week and shift dates are `Date`; conversion to Israel time happens at the edges with `zoneinfo`. Weeks are identified by their Sunday `week_start` date, with no `weeks` table. Migrations: **Alembic from the first schema commit**. Every multi-row write (submit, approve, generate, publish, confirm) is one transaction.

| # | Table | Key / constraints | Purpose |
|---|---|---|---|
| 1 | `employees` | id; `name` unique; `access_role` ('employee' or 'manager'); `code_hash` (scrypt); `failed_attempts`, `locked_until` | Login identity and the 8 demo staff in one table (replaces `users`). Lockout fields give per-account brute-force protection. |
| 2 | `shifts` | id; `name`; `start_time`; `end_time`; `sort`; `required_staff` (CHECK >= 0) | Shift definition **and** staffing requirement in one row (Morning/Evening, 2 each). Configurable by seed/migration; no admin UI. |
| 3 | `availability_submissions` | (`employee_id`,`week_start`) unique; `pref_min`,`pref_max` (CHECK 0 <= min <= max); `free_text`; `flags_json`; `submitted_at`,`updated_at` | One per employee per week. `flags_json` holds manager-triggered free-text analysis (with a text hash), labelled as an AI suggestion. |
| 4 | `availability_slots` | (`submission_id`,`date`,`shift_id`) unique | Active availability, one row per slot. Approved change requests insert/delete rows here; `audit_log` records the delta. |
| 5 | `change_requests` | id; `employee_id`; `week_start`; `items_json` (validated list of {date, shift, add/remove}); `note`; `status` ('pending'/'approved'/'rejected'); `decided_by`,`decided_at`,`decision_note`; `created_at` | Post-deadline requests with structured items. |
| 6 | `schedules` | id; `week_start`; `status` ('draft'/'published'/'superseded'); `run_json` (inputs hash, unfilled slots + reasons, per-employee counts vs preferences, unmet preferences); `generated_at`; `published_at`,`published_by`; partial UNIQUE: one `published` per week | Engine facts live on the schedule (replaces `schedule_runs`); explanations use them. |
| 7 | `assignments` | (`schedule_id`,`date`,`shift_id`,`employee_id`) unique; `source` ('engine'/'manager_change') | |
| 8 | `proposals` | id; `schedule_id`; `payload_json`; `validation_json`; `status` ('pending'/'confirmed'/'expired'/'rejected'); `created_by`; `expires_at` | Copilot-proposed changes awaiting a manager's UI confirmation. Security-critical; kept. |
| 9 | `audit_log` | id; `at`; `actor_id`; `action`; `entity`; `entity_id`; `before_json`,`after_json` | Append-only business record (post-deadline changes and decisions, draft, publish, confirmed changes, digest runs). Distinct from operational logs. |
| 10 | `conversations` | as instructor | Manager's Copilot chats. |
| 11 | `messages` | as instructor | |
| 12 | `runs` | as instructor + `effort`, `error_type`, `tool_trace` (JSON list of {tool, status, duration_ms, error_type}) | One row per model turn: tokens, cost, status, tools. Replaces a separate `tool_executions` table without losing per-tool tracking. |

**Removed or folded, with reason**
- `weeks`: derived from `week_start` plus a pure deadline function. No stored deadline that could drift.
- `staffing_requirements` and `shift_definitions`: merged into `shifts`.
- `change_request_items`: now `items_json` (always read with its request; validated by Pydantic).
- `schedule_runs`: now `schedules.run_json`.
- `request_flags`: now `availability_submissions.flags_json`.
- `tool_executions`: now `runs.tool_trace`.
- `digest_runs`: now an `audit_log` row (`action='digest_run'`), also used for idempotence.
- `schema_version`: replaced by `alembic_version`.
- Job roles and role requirements: not needed (no roles in the MVP).

**Deliberately kept despite the count:** `proposals` (no model writes without it), `audit_log`, `runs` with cost fields, the unique/CHECK constraints, and `availability_slots` as a real table (a JSON blob would lose uniqueness and make coverage queries database-specific).

Because approved changes mutate `availability_slots`, the original submitted availability is not retained separately after a change. This matches the approved decision that no original-submission snapshots are required; the change request plus the `audit_log` before/after values record every change.

**Local DB choice:** SQLite for the default fast loop (`pytest`, as the instructor), **plus a mandatory Postgres job in CI** (GitHub Actions `services: postgres`) that runs the same suite and `alembic upgrade head`. Use only portable SQL types (`JSON`, no `JSONB`-specific operators). Partial unique indexes, CHECKs and transaction behaviour are therefore exercised on Postgres before every merge.

## 5. Scheduling engine

Location: `app/scheduling/` (pure Python; `engine.py`, `validate.py`, `models.py` dataclasses). Input: slots to staff (date × shift × `required_staff`), effective availability, shift times, preferences. Output: assignments, unfilled slots with reasons, per-employee stats, and a violation list from the validator.

**Recommendation: deterministic greedy construction + bounded local-search repair; no OR-Tools in the MVP.** Rationale: 8 employees × 14 slots (7 days × 2 shifts) is tiny; hard constraints (availability, overlap) are simple; the goal is explainability and reliability. A solver adds a native dependency (build risk on Railpack), harder-to-explain results, and no visible benefit at this size.

Algorithm sketch:
1. Build slots; compute per-slot candidate sets from availability (H1).
2. Process slots **most-constrained-first** (fewest candidates), tie-break by (date, shift, id) → fully deterministic.
3. For each slot choose the candidate maximising a score: below-`pref_min` first, then fewest current assignments (fairness), never exceeding `pref_max` unless no one else can fill the slot (soft constraint relaxed *and recorded*), skipping overlaps (H2). No other hard rules exist (see `spec.md` §7 legal notice).
4. Repair pass: for each unfilled slot try single swaps/chains of bounded depth; stop at a fixed iteration cap.
5. Anything still unfilled is reported with a reason class. Never filled with an ineligible person.
6. **Independent validator** re-checks the final result against H1–H5 from raw inputs; engine output is rejected (logged, error returned) if the validator finds a violation. The validator is also the gate for every Copilot-proposed change.

Upgrade path (documented, not built): if evals/property tests show systematic poor fairness or false "unfilled", introduce OR-Tools CP-SAT behind the same input/output dataclasses. Decision criterion: >N% of seeded scenarios where brute-force/solver finds more coverage than greedy.

Change handling: edits go through `validate_change(schedule, change)` which only re-validates the touched assignments plus affected employees — **no global re-run**, so unrelated assignments cannot move.

## 6. Agent loop and tools

Reuse `run_turn` structure (persist user msg → context → stream → tool rounds ≤ 6 → persist once → `runs` row), `ModelClient` seam and fake model for tests. Changes: Hebrew system prompt (`app/prompts/system.md`, with today's date, target week, deadline state injected from data), manager-only access, `runs.tool_trace`, structured logs, loud missing-price handling.

Model config (env, never hard-coded in logic): `MODEL`, `MODEL_EFFORT`. Initial candidate **`claude-sonnet-5-5` with effort `high`** — the model id already exists in the instructor's price table and fallback list; support for `high` effort must be verified against current API docs at implementation time (the instructor code passes `output_config.effort` of low|medium|high). Haiku (`claude-haiku-5-5`) only for later evaluation on simple tasks. No paid calls during planning.

**Build order (owner priority): the real agent comes early.** M2 delivers the adapted loop with *read-only* tools over the availability data (`get_submission_status`, `get_availability`) end to end: manager chat UI, persistence, cost accounting, fake-model tests. Scheduling tools (`get_staffing_gaps`, `get_schedule`, `generate_draft_schedule`, `find_replacements`, `explain_assignment_count`, `propose_change`) are added in M5 once the engine exists. No paid model call happens until the owner separately approves it; until then everything runs against the fake model.

Tools (all read-only unless stated; every input validated with a schema; every tool re-checks the caller is a manager; no free-form SQL anywhere):

| Tool | Kind | Returns |
|---|---|---|
| `get_submission_status(week)` | read | submitted / not submitted lists, counts, deadline, time left |
| `get_availability(week, employee?)` | read | effective availability (+ pending requests) |
| `get_staffing_gaps(week, source: availability\|schedule)` | read | required vs available/assigned per slot |
| `get_schedule(week, status)` | read | assignments, unfilled slots |
| `list_change_requests(status?)` | read | structured items |
| `explain_assignment_count(week, employee)` | read | stored engine facts: prefs vs result, unmet reasons |
| `find_replacements(week, date, shift, exclude)` | read | employees available **and** rule-valid (not consent) |
| `analyze_requests(week, employee?)` | read+AI | flagged free-text items, labelled suggestion; cached by text hash |
| `generate_draft_schedule(week)` | write(draft only) | runs engine; refuses before deadline; replaces existing *draft* only |
| `propose_change(schedule, change)` | write(proposal only) | validator verdict + `proposal_id`; **modifies no assignment** |

Not exposed to the model: publish, approve/reject change requests, apply proposal, any delete. Those are authenticated UI calls by the manager.

### Confirmation design
`propose_change` stores a `proposals` row (payload + validation result + expiry). The chat UI renders it as a card showing the exact diff and any violations. Only `POST /api/proposals/{id}/confirm` (manager session, CSRF-safe JSON, re-validates at confirm time against current data) mutates assignments and writes the audit entry. The model cannot confirm, so a prompt-injected employee free-text cannot cause a write. Employee free text reaching the model is wrapped as quoted data and labelled untrusted in the prompt; tools never take instructions from it.

## 7. Authentication and authorization

**Implemented in M0-3** (`app/auth.py`, `app/passwords.py`, `app/throttle.py`, `app/security.py`, `app/users.py`).

### Accounts and credentials
- One `users` table for the manager and the employees: `access_role` ('employee' or 'manager', CHECK constraint), `code_hash`, `token_version`. **No self-registration**: accounts are created by an operator with `python -m app.users create "Name"` (employees) or, for the manager, from `MANAGER_NAME` / `MANAGER_PASSWORD` at startup (`ensure_manager`, audited).
- **Employee access code:** random, 10 characters from a 32-symbol alphabet without look-alikes (about 50 bits), shown as `XXXXX-XXXXX`, shown once on the operator's terminal and never logged, audited or stored. Stored as a salted scrypt hash (`scrypt$N$r$p$salt$hash`). Typing is forgiving (case, spaces, dashes).
- **Manager password:** from the environment; hashed with the same scrypt scheme into the manager's row at startup. In production the app refuses to start without `MANAGER_PASSWORD` (12+ characters) and `APP_SECRET` (32+ characters). A changed password is picked up at the next start, bumps `token_version` (signing the manager out everywhere) and is audited. Locally, a missing password disables manager login.
- **Rotating a code** (`python -m app.users rotate "Name"`) issues a new code, bumps `token_version` and writes an audit row. Old sessions stop working immediately.

### Login and session flow
1. `POST /api/login {name, code}`. Checks the name and per-IP locks first (429 with `Retry-After`), then verifies the code with scrypt. An unknown or malformed name is verified against a dummy hash, so the work and the answer are the same as for a wrong code: always `401 "Wrong name or access code."`.
2. On success the name's failure counter is cleared and a signed cookie `shift_session` (`user_id|token_version|expiry`, HMAC-SHA256 under `APP_SECRET`) is set: httponly, SameSite=Lax, Secure in production, 24 hours (`SESSION_HOURS`), no Domain.
3. Every request re-reads the user row: the **role always comes from the database, never from the cookie**, and a `token_version` mismatch (rotated code or changed manager password) is a 401. Logout clears the cookie; a stolen cookie stays valid until it expires or the code is rotated (limitation).

### Lockout and rate limiting (database-backed)
- Table `login_throttle(key, failures, locked_until, updated_at)`; keys are HMACs of the normalised attempted name (`name:`) or the client address (`ip:`), so no names or addresses are stored. Counters are incremented atomically in SQL (`UPDATE ... RETURNING`), commit immediately, and are shared by every process and survive restarts.
- **Per name** (real or not): 5 failures lock it for 60 s, doubling with each further failure up to 15 min. A success resets it. Counters older than 1 hour are forgotten; idle rows older than 1 day are purged.
- **Per IP:** 20 failures lock the address for 5 minutes (doubling to 15). The client address is the socket peer unless `CLIENT_IP_HEADER` names a header, in which case the **last** entry of that header (the one our own proxy appended) is used. Client-supplied forwarding headers are never trusted by default. **In production the per-IP limit is off unless `CLIENT_IP_HEADER` is set** (a startup warning says so), because behind a proxy every user shares one address and a single attacker could lock everyone out.
- **Verified vs unverified Railway assumptions (checked 2026-11-11 against Railway's documentation and community threads; nothing deployed):** Railway documents `X-Real-IP` as the client address header. Railway staff say the edge overwrites `X-Real-IP` and `X-Forwarded-For`, but the public docs do not state this, staff statements about which `X-Forwarded-For` entry is trustworthy contradict each other, and several 2026 reports describe CDN addresses appearing instead of client addresses. **Unverified.** Before setting `CLIENT_IP_HEADER` in production (for example `x-real-ip`), test against the real deployment: send a spoofed header and confirm it is replaced, and confirm the value is the true client address. Until then only the per-name limit protects production, with these consequences: an attacker rotating random names is not rate limited beyond the cost of each scrypt check, and an attacker can keep the manager's login locked by repeatedly guessing (the manager's existing session is unaffected).

### Authorization (backend)
- Dependencies `require_user`, `require_employee`, `require_manager` (`app/auth.py`). Every route outside a short allow-list must declare one; a test inspects the route table and fails otherwise. Allow-list: `GET /`, `GET /health`, `POST /api/login`, `POST /api/logout`, `POST /internal/digest` (authenticated by `X-Cron-Secret`), plus static files. `/openapi.json` and the docs pages are disabled.
- The Copilot, conversations and stats routes are **manager-only**; `/api/me` is for any signed-in user. Answers: no session 401, wrong role 403, someone else's record 404.
- **Employee data isolation:** employee routes use `require_employee` and take the employee id from the session, never from a request parameter, and load records through `owned_or_404(obj, user)`, so another person's record looks nonexistent. `tests/test_authorization.py` holds the route matrix (anonymous / employee / manager over every route) and a reference test of the pattern; M1-2 must reuse it for the availability endpoints.
- Preserved: the agent loop, tools, usage limits and cost accounting are unchanged; only the entry points moved behind `require_manager`.

### CSRF
Policy for every state-changing request (not GET/HEAD/OPTIONS; `/internal/digest` is exempt, it uses no cookie): (1) the custom header `X-Requested-With: shift-copilot` is required, which a cross-origin page cannot send without a CORS preflight, and the app never sends CORS headers; (2) `Sec-Fetch-Site: cross-site` is refused; (3) if `Origin` is present its host must equal `Host` (or be listed in `ALLOWED_ORIGINS`), `Origin: null` is refused; (4) a request with no `Origin` is accepted only because it carries the header (non-browser clients). The cookie is also SameSite=Lax, and `/api/*` responses are `Cache-Control: no-store`. Known limits: the scheme is not compared (TLS ends at the proxy); if CORS is ever enabled this policy must be revisited; the `Host` header is assumed to reach the app unchanged by Railway's proxy (if it did not, browser POSTs would fail closed and `ALLOWED_ORIGINS` is the escape hatch).

## 8. Data flows

- **Submit availability**: employee → `PUT /api/availability` → auth → load week → window check (`opens_at <= now < closes_at`, see the submission-window function below) else 409 → validate (dates within week, shifts exist, min≤max) → transaction: upsert submission + replace slots → audit + log → 200.
- **Change request**: after deadline only (before deadline: UI directs to the form) → creates `pending` + items → manager decision → transaction: status, audit, and effective-availability recomputation → conflicts with published assignments surfaced, nothing moved.
- **Draft**: manager → `POST /api/weeks/{week_start}/draft` → `now ≥ deadline(week_start)` else 409 → engine → validator → save draft with `run_json` → response with unfilled list.
- **Publish**: manager confirmation → transaction: validate draft again, supersede previous published, set published, audit.
- **Copilot turn**: as instructor, plus proposal confirmation flow above.
- **Digest**: cron → `python -m app.digest` → queries → text (+ webhook) → `audit_log` row (`digest_run`).

**Submission window (implemented in M1-1, approved 2026-11-11 and 2026-11-12).** A pure function `submission_window(week_start, preceding_published_at) -> (opens_at, closes_at)` in the deadline module: `closes_at` = Tuesday 22:00 Asia/Jerusalem, 5 days before `week_start`; `opens_at` = `min(preceding_published_at, Thursday 22:00 Asia/Jerusalem, 10 days before week_start)`, where `preceding_published_at` is the earliest `published_at` among the `published`/`superseded` schedules of `week_start - 7 days` (none for the first cycle, so the Thursday rule applies; approved 2026-11-12: there is no manual opening workflow). Both instants are computed with `zoneinfo` (DST-safe) and derived on demand; nothing about the window is stored. Availability writes require `opens_at <= now < closes_at`. The dashboard, Copilot tools and daily brief use the same function. Draft generation still requires `now >= closes_at` of the target week. Only the *first* publication of a week's schedule counts (the earliest `published_at`); republications, corrections and approved modifications never move the opening time, a late publication does not change an already-open window, and the Tuesday deadline is never extended automatically. Unapproved drafts are never exposed to employees. The dashboard and the daily brief warn when a window opened while the preceding schedule is unpublished (a query over the same function, no stored state). Publishing a schedule (M3-3) is what can open the next window early, so the M1 form first ships with the Thursday rule alone and M3-3 adds the publication trigger.

Implementation: `app/cycle.py` (pure rules: `submission_window`, `window_state`, `target_window`, `require_open`; Asia/Jerusalem fixed, never the `TIMEZONE` setting; windows are open for `opens_at <= now < closes_at`; a first-publication time earlier than the preceding deadline, which the real flow cannot produce, is raised to that deadline so windows never overlap), `app/cycle_service.py` (glue: `status_payload` behind the read-only `GET /api/cycle`, `enforce_window` which returns 409 with a Hebrew message and logs `window_rejected`, and `first_publication_of`, the seam to the schedule tables that returns None until M3-3), `app/clock.py` and `app/shifts.py`. The availability write API that calls `enforce_window` is issue #6.

Time source: a single `clock.now()` function (`app/clock.py`); `CLOCK_OVERRIDE` (an ISO-8601 instant **with** a UTC offset) freezes it, **only when `APP_ENV != production`** (the application refuses to start otherwise). The clock is frozen, not ticking, so the web and cron services agree exactly. Only the scheduling cycle uses it: logs, rate limits, sessions and cost accounting keep the real time (a test enforces that), and `/health` and `app_start` show `clock: override` while it is on.

## 9. Observability

**Implemented in M0-2.** Operational logging lives in `app/logging_setup.py`; the business audit record lives in `app/audit.py` and the `audit_log` table. They are deliberately separate.

### Operational logs (diagnosis; best effort; stdout, collected by Railway)
- One JSON object per line: `ts` (UTC, ms), `level`, `event`, `request_id` (when inside a request), plus event-specific safe fields. Third-party and uvicorn log lines are wrapped in the same JSON shape (`event: "log"`); uvicorn's access log is replaced by our own `request` event.
- **Request ID:** a pure-ASGI middleware creates one per request (or reuses a caller-supplied `X-Request-ID` only if it matches `[A-Za-z0-9._-]{8,64}`), returns it as the `X-Request-ID` response header, and stores it in a context variable so every log line and every audit row written during the request carries it. This is the correlation ID: one request id links the `request`, `copilot_request`, `tool_executed`, `copilot_run` and `audit_recorded` lines of one user action.
- **Events implemented now:** `app_start`, `app_stop`, `request` (method, route template, status, duration_ms), `auth_failed` (reason only), `health_failed`, `db_error`, `migrations_pending`, `unhandled_error`, `copilot_request` (user id, conversation id, message length), `tool_executed` (tool, status, duration_ms, error_type), `copilot_run` (status, model, effort, tokens, estimated cost, tool calls, duration), `agent_error`, `digest_run`, `audit_recorded`, and from M0-3: `login_succeeded`, `login_blocked`, `forbidden`, `csrf_blocked`, `user_created`, `user_code_rotated`, `manager_login_disabled`, `ip_throttle_disabled`, and from M1-1: `window_rejected` (week, state), `seed_run` (counts only, never codes) and `clock_override_active`. Audit actions added: `shift.created` (and `user.created` for each seeded employee).
- **Events planned with their features** (names reserved): `availability_submitted`, `deadline_state`, `change_request_created/decided`, `draft_generated`, `schedule_validation_failed`, `schedule_published`, `anthropic_retry/failure` (the SDK retries internally today, so only the final failure is visible as `agent_error`), `unknown_model_price`.
- **Redaction (`redact()`):** keys named like credentials (`password`, `token`, `cookie`, `authorization`, `api_key`, `*_secret`, `code`, ...) become `[redacted]`; private text keys (`message`, `prompt`, `content`, `free_text`, `note`, ...) are reduced to their length; strings are scrubbed for `sk-ant-...`, bearer tokens and `session=...` pairs and truncated at 500 characters. Token *counts* (`input_tokens`) are not secrets and are kept.
- **Exceptions** are logged as `error_type` plus a message-free stack (`file:line in function`). The exception message is never logged, because database errors embed SQL parameters and could carry employee data.
- **Never logged:** passwords, access codes, API keys, cookies or session tokens, free-text requests, full user messages, full prompts, employee personal details beyond numeric ids. Tests plant a password, a session token and a private sentence and assert none appears in captured logs.
- `LOG_LEVEL` (default `INFO`) sets the level. Logs are not a system of record: Railway rotates them.

### Audit records (business record; durable; database)
- `audit_log` rows: `at`, `actor_id`, `action`, `entity`, `entity_id`, `request_id`, `before_json`, `after_json`. Append-only: the ORM refuses updates and deletes. (A database-level trigger or role grant is not added yet; see limitations in the PR.)
- **Atomic with the change.** `audit.record()` adds the row to the *caller's* transaction and flushes it; it never commits. `with audited(db): ... record(...)` commits the mutation and its audit row together, or rolls both back. If writing the audit row fails, the exception propagates and the mutation is rolled back. A block that finishes without any audit row raises `AuditMissing` and is rolled back, so a critical mutation cannot succeed silently.
- Payloads may contain business text (it is the record) but credentials are always redacted. Payloads are **never** copied into operational logs: the log gets only `audit_recorded` with the audit id, action, entity and entity id.
- Use it for every critical mutation in later issues (post-deadline changes, change-request decisions, draft, publish, confirmed schedule changes, digest runs).

## 10. Railway and environment

Services (extending instructor's `railway.ts`, to be edited at implementation — currently still references `MaceTenth/bakery-copilot`, **must** point at the fork before any deploy): `web` (uvicorn, `/health`), `digest` (cron), `Postgres` + volume with backups. Rationale kept from the instructor: Railpack, no Dockerfile, IaC file, secrets only in Variables.

Digest scheduling vs DST: Railway cron is UTC. Proposed: one cron expression `30 4,5 * * *` (runs at 04:30 and 05:30 UTC) and `app.digest` exits immediately unless local time in `Asia/Jerusalem` is 07:30±30 min and no `digest_run` audit row exists today. Costs seconds per day.

Variables (names only): `APP_ENV, APP_SECRET, MANAGER_NAME, MANAGER_PASSWORD (implemented in M0-3; replaces APP_PASSWORD), CLIENT_IP_HEADER (empty = per-IP login limit off in production), ALLOWED_ORIGINS (normally empty), SESSION_HOURS (default 24), DATABASE_URL, ANTHROPIC_API_KEY, MODEL, MODEL_EFFORT, MAX_TOKENS, HISTORY_LIMIT, RATE_LIMIT_PER_HOUR, DAILY_CAP_USD, TIMEZONE, CRON_SECRET, DIGEST_WEBHOOK_URL, LOG_LEVEL (implemented), TEST_DATABASE_URL (tests only), CLOCK_OVERRIDE (non-prod only), MODEL_PROVIDER (tests: fake)`. `.env.example` lists names without values.

Deployment plan: `docs/deployment-plan.md`. Early deploy target (D1): after the availability form and the read-only Copilot work (M1 + M2 in `ROADMAP.md`).

## 11. Security boundaries

Trust boundaries: browser→API (untrusted input, validated with Pydantic, length caps); API→DB (ORM only); API→model (employee free text is untrusted data; the model has only constrained tools); cron→API (`X-Cron-Secret`). Principle: the model proposes, deterministic code validates, a human confirms. Cost brakes: per-manager rate limit, daily cap, max 6 tool rounds, free-text analysis cached and on demand. Fix on adoption: unknown model in the price table must raise/log `unknown_model_price` rather than recording cost 0.

## 12. Decisions and trade-offs

| Decision | Reason | Revisit if |
|---|---|---|
| Keep single-service FastAPI + static UI | instructor-proven, cheapest, enough for 15 users | multi-tenant / public |
| Per-employee access codes with lockout, not a shared password | privacy separation is a requirement; approved with brute-force protection | SSO needed |
| Greedy + repair, validator separate, no OR-Tools | simple, explainable, deterministic | coverage quality evals fail |
| Model proposes, UI confirms | prompt-injection and hallucination safety | — |
| Deterministic digest (no model call) | grounded, free, reliable | managers want prose summaries (then Haiku, evaluated) |
| 12 tables, JSON columns for small blobs | simplest maintainable schema without losing integrity, audit or usage tracking | a JSON field needs querying or constraints |
| Alembic from day one | schema will change many times; production data soon | — |
| SQLite dev + Postgres CI job | fast loop and PG fidelity | Docker everywhere → Postgres locally |
| No history snapshots of submissions | approved product decision; audit covers post-deadline changes only | — |
| Plain JS/CSS UI, no framework | no build step on Railpack; instructor baseline | UI complexity outgrows it (schedule view, chat, forms are manageable) |
