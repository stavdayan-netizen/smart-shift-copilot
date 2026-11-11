# Smart Shift Copilot

A Hebrew-first, mobile-friendly, AI-assisted weekly shift scheduling app for one small Israeli business (course MVP, demo data only).

## Implementation status

**Planning phase (plan approved 2026-11-11). No Smart Shift features are implemented yet.** This repository is a fork of the instructor's [Bakery Copilot](https://github.com/MaceTenth/bakery-copilot). **M0-1 (issue #1) removed the bakery domain** (sales and invoice tools, datasets, invoice UI and image upload). What remains is the reusable infrastructure: FastAPI app, the Anthropic agent loop with an empty tool registry, conversation and run persistence, per-account login (M0-3: manager and employee roles, personal access codes, database-backed lockout, CSRF defence), rate and cost limits, a generic digest skeleton, fake-model tests, evals runner, CI and the Railway IaC file. M0-2 added structured JSON logging with request IDs and redaction, Alembic migrations, an append-only `audit_log` with an atomic audit writer, and a PostgreSQL CI job. The UI is a bare English placeholder chat, not the Hebrew UI. Nothing in "Planned features" below works today.

## Relationship to Bakery Copilot

We keep its architecture (FastAPI, Anthropic agent loop with constrained tools, conversation and run persistence, Postgres, Railway with a cron digest, rate limits and cost caps, tests and evals) and replace the domain: shifts, availability, a deterministic scheduling engine, and a manager-only Copilot. Remote `upstream` points to the instructor's repo for reference only.

## Planned features (Phase 1)

- MVP scenario: 8 fictional employees, Morning and Evening shifts, 2 staff per shift, no roles.
- Employee weekly availability form (`הגשת משמרות לשבוע הבא`), preferred shift range, free-text requests; Tuesday 22:00 Asia/Jerusalem server-enforced deadline.
- Post-deadline change requests with manager approval and audit trail.
- Manager dashboard: submissions, gaps, draft vs published schedules.
- Deterministic scheduling and validation engine; partial results reported honestly.
- Manager Copilot (Claude) with validated tools; changes need explicit manager confirmation.
- Daily manager brief. Structured logs. Mobile-first Hebrew RTL UI.

Approved for Phase 2 and explicitly excluded items: see [ROADMAP.md](ROADMAP.md). Cancellation, sickness and no-show are handled by phone, by design.

## Documents

[spec.md](spec.md) what · [architecture.md](architecture.md) how · [practice.md](practice.md) working agreement · [runbook.md](runbook.md) incidents · [ROADMAP.md](ROADMAP.md) phases · [docs/tickets.md](docs/tickets.md) proposed issues · [docs/deployment-plan.md](docs/deployment-plan.md) Railway plan · [CLAUDE.md](CLAUDE.md) instructions for Claude Code.

## Local setup (current baseline after M0-1 — will change in M0-2 to M0-4)

```bash
cp .env.example .env
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
alembic upgrade head            # the app no longer creates tables itself
uvicorn app.main:app --reload
```

Sign in at http://localhost:8000 as `MANAGER_NAME` with `MANAGER_PASSWORD` (set both in `.env`). Create a demo employee with `python -m app.users create "Noa Levi"`: the access code is printed once to your terminal and never stored (only its hash). `python -m app.users rotate "Noa Levi"` issues a new one.

Required environment variables (names only; values never committed): `APP_ENV`, `MANAGER_NAME`, `MANAGER_PASSWORD`, `APP_SECRET`, `DATABASE_URL`, `ANTHROPIC_API_KEY`, `MODEL`, `MODEL_EFFORT`, `DAILY_CAP_USD`, `TIMEZONE`, `CRON_SECRET`, `DIGEST_WEBHOOK_URL`, `LOG_LEVEL`, `SESSION_HOURS`, `CLIENT_IP_HEADER`, `ALLOWED_ORIGINS` (and `TEST_DATABASE_URL` for tests on PostgreSQL). For a keyless local run set `MODEL_PROVIDER=fake`. Planned changes are listed in `architecture.md` §10.

## User interface

Hebrew, right-to-left, mobile-first, light by default (dark follows the device). The product name stays in English; all other copy is Hebrew. Managers see the Copilot chat (still placeholder replies until issue #7) and their account page; employees see a placeholder home and their account page. Heebo is self-hosted under the SIL Open Font License (`static/fonts/`). Model replies are rendered by a small safe Markdown renderer. Evidence of the responsive checks: [docs/ui-checks/m0-4/](docs/ui-checks/m0-4/README.md); re-run them with `python scripts/ui_check.py --help`.

## Tests

`pytest -q` runs deterministic tests with a fake model (the Markdown renderer tests need node and are skipped without it; CI always runs them) (no key, no cost). `python -m evals.run` calls the real model and costs money; run only with owner approval. After M0-2 (2026-11-11, Windows, Python 3.12.10, SQLite, fake model): **101 passed** (SQLite); CI runs the same suite on SQLite and on PostgreSQL 16 (`TEST_DATABASE_URL`). PostgreSQL cannot be run on the development machine (no Docker/psql), so PostgreSQL results come from GitHub Actions.

## Deployment

Planned on Railway (web + PostgreSQL + digest cron); see [docs/deployment-plan.md](docs/deployment-plan.md). Not deployed yet; no Railway resources exist.

## Limitations

**Legal compliance is not implemented.** The MVP applies only availability and no-overlap rules; Israeli employment-law requirements (rest, hours, overtime and so on) need further implementation and legal review before any real-world use.

Single business, fictional data, no multi-tenant, no payroll or legal-hours engine, no WhatsApp, no employee cancellation flow.

## Credits and licence

Derived from the instructor's Bakery Copilot, which has **no licence file** in its repository. Forked for a course assignment; do not redistribute beyond the course without the instructor's permission.
