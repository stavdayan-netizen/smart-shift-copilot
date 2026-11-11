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
| Auth | One shared password + typed name, HMAC-signed cookie (httponly, lax, secure in prod) | `app/auth.py` |
| DB | SQLAlchemy 2, `create_all` + `schema_version`; SQLite local, Postgres on Railway | `app/db.py` |
| Limits & cost | per-user hourly limit, daily USD cap, price table, per-run cost | `app/limits.py`, `app/costs.py`, `app/config.py` |
| Digest | Deterministic text from DB; `python -m app.digest` cron + `POST /internal/digest` (`X-Cron-Secret`) | `app/digest.py` |
| Tests/evals | pytest with fake model; real-model evals with history CSV | `tests/`, `evals/` |
| CI | pytest on PR/push; evals if secret set | `.github/workflows/ci.yml` |
| Railway | IaC `railway.ts`: web + digest cron + Postgres, `/health` | `.railway/railway.ts` |
| UI | Plain HTML/CSS/JS, **LTR, English**, one `@media (max-width: 900px)` | `static/` |
| Logging | **`print()` only** — no structured logging | — |
| Migrations | **None** (`create_all`) | — |

Gaps relative to this project: no structured logs, no migrations, no per-user identity, no RTL/Hebrew, bakery-specific tools/prompt/seed/digest. `cost_usd()` returns **0.0 silently for a model missing from the price table** — must become a loud failure/log (see §11).

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

## 4. Database schema (planned; PostgreSQL production, SQLite for fast local tests)

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

Instructor model (shared password + typed name) cannot separate employees' private data, so it must change. **Approved in principle (2026-11-11); design:** a personal access code per employee (random, 8+ characters from a non-ambiguous alphabet, issued out of band, stored scrypt-hashed, constant-time compare) and a manager password from env. Protections: per-account lockout with growing delay after repeated failures (`failed_attempts`, `locked_until`), a per-IP throttle, identical error text and comparable timing for unknown name vs wrong code (no user enumeration), `auth_failed` log events (never the submitted code), and codes the manager can rotate. Sessions: keep the HMAC signed cookie, adding `access_role` to the payload; httponly, SameSite=Lax, Secure in production; session lifetime to be revisited for shared phones (instructor default 72h). A FastAPI dependency `require_employee` / `require_manager` on every route; employee routes derive the employee id **from the session, never from a request parameter**. No self-registration. Tests: parametrised "employee A → employee B resource → 403/404" over all routes; a route-inventory test fails if a route lacks an auth dependency (allow-list: `/health`, login, static).

## 8. Data flows

- **Submit availability**: employee → `PUT /api/availability` → auth → load week → `now < deadline_at` else 409 → validate (dates within week, shifts exist, min≤max) → transaction: upsert submission + replace slots → audit + log → 200.
- **Change request**: after deadline only (before deadline: UI directs to the form) → creates `pending` + items → manager decision → transaction: status, audit, and effective-availability recomputation → conflicts with published assignments surfaced, nothing moved.
- **Draft**: manager → `POST /api/weeks/{week_start}/draft` → `now ≥ deadline(week_start)` else 409 → engine → validator → save draft with `run_json` → response with unfilled list.
- **Publish**: manager confirmation → transaction: validate draft again, supersede previous published, set published, audit.
- **Copilot turn**: as instructor, plus proposal confirmation flow above.
- **Digest**: cron → `python -m app.digest` → queries → text (+ webhook) → `audit_log` row (`digest_run`).

Time source: a single `clock.now()` function; a `CLOCK_OVERRIDE` variable honored **only when `APP_ENV != production`** to test the deadline on the demo.

## 9. Observability

Python `logging` with a JSON formatter (stdout → Railway logs), a middleware assigning `request_id` (also returned as `X-Request-ID`, copied into agent/tool logs as `correlation_id`). Fields: `ts, level, event, request_id, actor_id (numeric), week_id, duration_ms, error_type`, plus `model, effort, tokens, cost_usd` for model calls. Events: `app_start/app_stop, auth_failed, availability_submitted, deadline_state, change_request_created/decided, draft_generated, schedule_validation_failed, schedule_published, copilot_request, tool_selected/tool_executed, agent_error, anthropic_retry/failure, db_error, digest_run, health_failed`.
**Never logged:** passwords, codes, API keys, cookies/tokens, free-text requests (log length/hash only), employee personal details beyond numeric ids, full prompts. A redaction filter + a test that scans captured logs for planted secrets/free text. **Operational logs ≠ audit**: logs are best-effort and rotate on Railway; `audit_log` and `runs` (with `tool_trace`) are database records.

## 10. Railway and environment

Services (extending instructor's `railway.ts`, to be edited at implementation — currently still references `MaceTenth/bakery-copilot`, **must** point at the fork before any deploy): `web` (uvicorn, `/health`), `digest` (cron), `Postgres` + volume with backups. Rationale kept from the instructor: Railpack, no Dockerfile, IaC file, secrets only in Variables.

Digest scheduling vs DST: Railway cron is UTC. Proposed: one cron expression `30 4,5 * * *` (runs at 04:30 and 05:30 UTC) and `app.digest` exits immediately unless local time in `Asia/Jerusalem` is 07:30±30 min and no `digest_run` audit row exists today. Costs seconds per day.

Variables (names only): `APP_ENV, APP_SECRET, MANAGER_PASSWORD (replaces APP_PASSWORD), DATABASE_URL, ANTHROPIC_API_KEY, MODEL, MODEL_EFFORT, MAX_TOKENS, HISTORY_LIMIT, RATE_LIMIT_PER_HOUR, DAILY_CAP_USD, TIMEZONE, CRON_SECRET, DIGEST_WEBHOOK_URL, LOG_LEVEL, CLOCK_OVERRIDE (non-prod only), MODEL_PROVIDER (tests: fake)`. `.env.example` lists names without values.

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
