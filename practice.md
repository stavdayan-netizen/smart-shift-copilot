# practice.md — working agreement for all development (Claude Code and humans)

Adapted from the instructor's eight-step ticket loop. `CLAUDE.md` points here. **This file is mandatory.** If a task conflicts with it, `spec.md`, or `ROADMAP.md`, stop and ask.

## 1. Git workflow

- `main` is always deployable. Never commit or push to `main` directly; merge via PR with CI green.
- One ticket → one branch `<issue>-<slug>` (e.g. `7-availability-form`) → focused commits → one PR with the issue link.
- Remotes: `origin` = our fork (`stavdayan-netizen/smart-shift-copilot`); `upstream` = instructor's repo, read-only reference. Never push to `upstream`.
- Before opening a PR run the relevant tests (§5). PR body: what changed, test output, mobile/RTL checklist results (§3), docs touched, security note.
- **Do not implement anything not in an approved ticket / `spec.md` Phase 1.** Phase 2 and the exclusions in `spec.md` §11 are off limits. New ideas become a proposed issue, not code.
- Keep docs in the same commit as the code that changes them (`architecture.md`, `spec.md` §13 checks, `runbook.md`, `.env.example`, `ROADMAP.md` status).
- Per ticket: read the issue → restate in one line → 3–5 line plan (files + tests) → get approval → branch → smallest change → test → docs → commit → PR.

## 2. Never

- Edit `.env`, print/paste a secret, or commit one. Leak → rotate first, then clean history (`runbook.md`).
- Put real personal data in the repo. Demo data is fictional.
- Rely on hidden UI for authorization. Every manager route is protected server-side.
- Execute model-generated SQL; let the model write approved/published assignments.
- Change model, effort or system prompt without an eval run before and after (owner-approved spend).
- Run paid model comparisons or evals without owner approval.
- Skip a failing test, or mark UI work done without the §3 checks.

## 3. Mobile-first Definition of Done (every UI task)

1. Designed mobile-first (base CSS = phone; wider layouts via `min-width` queries).
2. Natural Hebrew copy; `lang="he" dir="rtl"`; logical CSS properties; numbers, times and dates render correctly in RTL.
3. Verified at **360, 390, 768 px and desktop** (≥ 1280).
4. No unintended horizontal overflow at any of them (`document.documentElement.scrollWidth <= innerWidth`).
5. Usable mobile navigation, forms, chat, dialogs and schedule views; no wide tables (day-by-day cards on narrow screens); touch targets ≥ 44×44 px; labels on controls; conflicts stay visible.
6. Pass visual and functional checks (browser pane or Chrome, screenshots or accessibility-tree checks, plus an automated overflow/viewport test where feasible).
7. Any check not actually performed is written in the PR as **"NOT VERIFIED: …"**.
8. A UI task is **incomplete** until the required checks pass or the owner accepts the listed gaps.

**Never claim visual testing was performed unless it was.** State the tool used and the widths covered.

## 4. Code quality and safety

- Every new behaviour has tests; failures are handled explicitly (no bare `except`, no silent fallbacks).
- Validate all inputs server-side (Pydantic, length caps, enum/range checks).
- Authorization tests for each new route: own data OK; another employee's data denied; employee → manager route denied.
- Every new route declares `require_user`, `require_employee` or `require_manager` (or is added to the allow-list in `tests/test_authorization.py` with a stated reason). Employee routes take the employee id from the session, never from the request, and load records with `owned_or_404`. State-changing JS requests send `X-Requested-With: shift-copilot`.
- Never log or audit an access code, password, session token or hash; accounts and codes are managed only through `python -m app.users`.
- Critical scheduling operations go through the deterministic validator. No silent changes to approved or published schedules; every such change writes an `audit_log` row.
- Deadline logic only through the deadline service and `clock.now()`; never compare dates ad hoc. Tests cover Israel DST transitions and the boundary second.

## 5. Tests

- **Deterministic tests** (`pytest -q`, model mocked, no network, no key): engine, validator (property tests: no output violates H1–H2), deadline/DST, auth matrix, API, tools, digest, log redaction. Must pass on SQLite **and** PostgreSQL (CI runs both).
- **Model-dependent evals** (`python -m evals.run`, real model, costs money): tool selection, Hebrew request interpretation, hard-constraint refusal, unavailable employee, ambiguity → clarification, preference explanations match stored facts, confirmation before modification, no fabricated data, cost/latency. Run only when prompt/tools/model change **and the owner approved the spend**; paste pass rate and tokens in the PR.
- Never mix them: evals are not part of the default test command.

## 6. Logging, audit, migrations and operations

**Operational logs** (`app/logging_setup.py`):
- Log with `log_event("name", key=value)` or `log_exception("name", exc)`. Never `print()` and never `logging.info(f"... {user_text}")`.
- Every new workflow gets named events (list in `architecture.md` §9). The request ID is added automatically.
- Never put passwords, codes, tokens, cookies, API keys, free-text requests, full messages or prompts in a log field. `redact()` is a safety net, not permission. Log lengths, ids and counts instead. Do not log exception messages (use `log_exception`).
- A test that plants a secret and a private sentence and checks the captured logs must keep passing; extend it when you add a workflow that handles private text.

**Audit records** (`app/audit.py`):
- Every critical business mutation (anything a manager or the manager's approval decides, or that changes what an employee sees about their shifts) writes an `audit_log` row **in the same transaction**: `with audited(db): <mutate>; record(...)`. Do not commit between the mutation and the audit row. A failing audit write must fail the mutation.
- Business facts are proved by `audit_log`, never by logs. Never copy audit payloads into logs.

**Migrations** (Alembic):
- Every change to a model or constraint is a new Alembic revision in `alembic/versions/`. Never edit an applied revision, and never create tables with `create_all`.
- Create it with `alembic revision --autogenerate -m "..."`, then read and fix the generated file by hand (names, defaults, data backfills, indexes).
- Migrations must be backward compatible with the previous release for one version (add first, remove later), because a rollback redeploys the old code against the new schema.
- `tests/test_migrations.py` fails if models and migrations disagree. CI also runs `alembic upgrade head` and `alembic check` on an empty PostgreSQL.
- Run on PostgreSQL before merge: CI runs the whole suite on SQLite and on PostgreSQL 16; both jobs must be green. PostgreSQL-only behaviour (constraints, partial indexes, transactions) cannot be verified on a machine without Postgres, so rely on CI, and say so in the PR when something was only checked on SQLite.

**Operations:**
- New failure mode → add a `runbook.md` entry in the same PR.
- New env var → add its name to `.env.example` and `architecture.md` §10 (names only).
- Verify an induced error can be diagnosed from logs alone (find it by `request_id`).

## 7. Cost management

- No unnecessary Anthropic calls; anything that can be deterministic is. Gate and cache free-text analysis.
- Every call records tokens and estimated cost in `runs`; an unknown model price is an error, not 0.
- Respect `DAILY_CAP_USD` and rate limits; do not raise them without owner approval.

## 8. Definition of Done (feature)

A ticket is done only when **every** item below is satisfied or explicitly listed in the PR as "NOT VERIFIED" with the owner's acceptance:

1. **Works** as the ticket's "Done when" says, and nothing outside approved scope was added.
2. **Mobile-first and Hebrew RTL** (§3) for any UI.
3. **Tests**: new deterministic tests pass on **SQLite and PostgreSQL** (CI shows both green). Appropriate model Evals are written for agent behaviour and run only with approved spend.
4. **Deterministic scheduling validation** applied to every scheduling operation; **no unauthorized schedule modification** (model never writes approved or published assignments; manager confirmation required; audit row written).
5. **Safe authentication and authorization**: server-side checks on every new route, cross-employee access tests, no secrets in code or logs.
6. **Structured operational logging** for the new workflow, request IDs, no sensitive data (log-redaction test still passes).
7. **Model usage and cost accounting**: every model call records model, effort, tokens and estimated cost in `runs`; limits respected; unknown model price fails loudly.
8. **Runbook** updated for any new failure mode; environment variable names added to `.env.example` and `architecture.md`.
9. **Docs synchronized** (`spec.md`, `architecture.md`, `ROADMAP.md`, README status) in the same PR.
10. Security implications reviewed in the PR description; CI green; PR approved by the owner before merge.

## 9. Local commands (planned; confirm when implemented)

```bash
cp .env.example .env                 # fill values; never commit
python -m venv .venv && . .venv/bin/activate && pip install -r requirements.txt
uvicorn app.main:app --reload        # http://localhost:8000
pytest -q                            # model mocked
alembic upgrade head                 # apply migrations (the app does not create tables)
python -m evals.run                  # costs money; owner approval required
python -m app.digest                 # print today's brief
```

Windows PowerShell 7: `py -3.12 -m venv .venv; .venv\Scripts\Activate.ps1`.
