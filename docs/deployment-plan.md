# Deployment plan — Smart Shift Copilot

**Status: PLAN. No Railway resources exist. Nothing here has been run.** Companion to the instructor's `docs/deploy-railway.md` (full CLI/dashboard walkthrough, kept as reference) and `architecture.md` §10.

## Philosophy (from the instructor)
Plan first · test locally · CI as quality gate · secrets only in Variables · Postgres with persistent volume and backups · health check · documented rollback · watch cost and failures.

## Pre-deploy blockers
1. `.railway/railway.ts` still references `github("MaceTenth/bakery-copilot")` and project name `bakery-copilot` → change to our fork and `smart-shift-copilot` (part of M0).
2. Railway's GitHub app needs access to the fork (otherwise "repository not accessible").
3. Set `MANAGER_PASSWORD` (12+ chars) and `APP_SECRET` (32+ chars); the app refuses to start in production without them. Issue demo employee codes with `python -m app.users create` against the production database and keep them out of the repo. **Verify Railway's client-IP header before setting `CLIENT_IP_HEADER`** (see `architecture.md` section 7); until then the per-IP login limit stays off.
4. CI green on SQLite and Postgres.

## Target
- `web`: `uvicorn app.main:app --host 0.0.0.0 --port $PORT`, health `/health`, restart max 5.
- `Postgres` plugin + volume (alerts at 80/95/100%), backups enabled.
- `digest`: cron `30 4,5 * * *` UTC with an in-code Israel-local-time guard (DST-safe), `python -m app.digest`.
- Migration step: `alembic upgrade head` is now the prefix of the web start command in `.railway/railway.ts` (written in M0-2, not applied to any Railway project). It is idempotent, and `/health` fails if migrations are pending.
- Cost estimate (instructor's, to re-measure): Railway ≈ $4–6/month; Claude single-digit USD/month with caps.

## Sequence
1. **D1 (early deploy, after M2: availability form and read-only Copilot):** create Railway project, Postgres, `web`; set variables; `railway config plan` then `apply`; deploy; check `/health`; seed fictional data; employee form reachable on a phone.
2. `ANTHROPIC_API_KEY` is set only after the owner approves paid calls; add the `digest` service after M6.
3. Each later milestone deploys from `main` after PR merge; smoke test (`runbook.md` §17).

## Variables (names only)
See `architecture.md` §10. `CLOCK_OVERRIDE` is forbidden in production (startup check). Set `APP_ENV=production`, `TIMEZONE=Asia/Jerusalem`, `DAILY_CAP_USD` low (e.g. 2–3) until measured.

## Static assets
The UI loads nothing from other origins (fonts are self-hosted, no CDN scripts), so a strict Content-Security-Policy (`default-src 'self'`) is a candidate hardening step before real use; it is **not** configured yet and is tracked in the hardening issue (#15).

## Rollback
Deployments → previous green → Redeploy; migrations must be backward compatible one version (`runbook.md` §13, §15). Restore drill before demo day.

## Monitoring
Railway logs (JSON), `/health`, `/api/stats`, `runs` table cost, digest run records. Set a Railway usage alert.

## Approvals needed before executing
Creating Railway resources, adding `ANTHROPIC_API_KEY`, enabling spend, connecting GitHub to Railway.
