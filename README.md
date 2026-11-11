# Smart Shift Copilot

A Hebrew-first, mobile-friendly, AI-assisted weekly shift scheduling app for one small Israeli business (course MVP, demo data only).

## Implementation status

**Planning phase (plan approved 2026-11-11). No Smart Shift features are implemented yet.** This repository is a fork of the instructor's [Bakery Copilot](https://github.com/MaceTenth/bakery-copilot); the application code is still the bakery app (sales questions and invoice logging, English, LTR). The planning documents describe the intended product. Nothing in "Planned features" below works today.

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

## Local setup (current bakery baseline — will change in M0)

```bash
cp .env.example .env
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
uvicorn app.main:app --reload
```

Required environment variables (names only; values never committed): `APP_ENV`, `APP_PASSWORD`, `APP_SECRET`, `DATABASE_URL`, `ANTHROPIC_API_KEY`, `MODEL`, `MODEL_EFFORT`, `DAILY_CAP_USD`, `TIMEZONE`, `CRON_SECRET`, `DIGEST_WEBHOOK_URL`. Planned changes are listed in `architecture.md` §10.

## Tests

`pytest -q` runs deterministic tests with a fake model (no key, no cost). `python -m evals.run` calls the real model and costs money; run only with owner approval. Baseline of the unmodified instructor code in this fork (2026-11-11, Windows, Python 3.12.10, SQLite, fake model): **38 passed in 2.19 s**. PostgreSQL was not exercised (no Postgres CI job yet, see M0-2).

## Deployment

Planned on Railway (web + PostgreSQL + digest cron); see [docs/deployment-plan.md](docs/deployment-plan.md). Not deployed yet; no Railway resources exist.

## Limitations

**Legal compliance is not implemented.** The MVP applies only availability and no-overlap rules; Israeli employment-law requirements (rest, hours, overtime and so on) need further implementation and legal review before any real-world use.

Single business, fictional data, no multi-tenant, no payroll or legal-hours engine, no WhatsApp, no employee cancellation flow.

## Credits and licence

Derived from the instructor's Bakery Copilot, which has **no licence file** in its repository. Forked for a course assignment; do not redistribute beyond the course without the instructor's permission.
