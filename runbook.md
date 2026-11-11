# runbook.md — when it breaks

**Status:** structure and incident list are written ahead of the code. Every entry is tagged **[EXISTS]** (works today in the instructor's code), **[PLANNED]** (depends on a feature or command not built yet) — do not treat PLANNED steps as verified. Remove tags as features land, and add an entry for every new failure mode (`practice.md` §6). Railway steps follow the instructor's runbook (`docs/deploy-railway.md` §6–§8).

Common first moves: Railway → service → **Deployments** / **Logs**; filter logs by `request_id` or `event`. `GET /health` shows `problems`.

Each entry: Symptoms · Signals · Diagnose · Recover · Verify · Rollback/escalate.

## 1. App will not start / health red [EXISTS]
- **Symptoms:** URL fails, deploy red. **Signals:** deploy logs; the `app_start` JSON line is missing (it shows `schema`: `current`, `pending` or `unknown`), startup `RuntimeError: Missing required variables in production`, or `/health` lists `schema: migrations pending`.
- **Diagnose:** last log lines; compare Variables with `.env.example`. **Recover:** set variable → redeploy; or Redeploy previous green deploy. **Verify:** `/health` 200, login works. **Escalate:** open a `bug` issue with log lines; fix forward via PR.

## 2. Railway deployment failure [EXISTS]
- Build logs (Railpack, `requirements.txt`, `.python-version`); "repository not accessible" → Railway GitHub app access; `railway config plan` drift (IaC still pointing at the instructor's repo is a **known pre-deploy blocker**). Recover: fix, or redeploy previous. Verify: `/health`, smoke test (§17). Rollback: Deployments → previous → Redeploy.

## 3. PostgreSQL connectivity [EXISTS; log events PLANNED]
- **Symptoms:** `/health` 503 with `db:`; 500s. **Diagnose:** `DATABASE_URL` is the reference `${{Postgres.DATABASE_URL}}`; Postgres service status/volume usage; PLANNED `db_error` events. **Recover:** fix reference, restart Postgres service if unhealthy. **Verify:** `/health`, a read endpoint. **Escalate:** restore from backup (§14) only after confirming data loss.

## 4. Authentication problems [EXISTS: per-account login]
- **Symptoms:** an employee cannot log in, the manager cannot log in, everyone is logged out, or a browser action returns 403 "Request blocked.".
- **Signals:** `auth_failed` (`reason`: `bad_credentials`, `no_valid_session`, `stale_session`, `unknown_user_in_session`, `bad_cron_secret`), `login_blocked` (`scope`: `name` and/or `ip`, `retry_after`), `forbidden`, `csrf_blocked` (`reason`), startup warnings `manager_login_disabled` and `ip_throttle_disabled`. Logs never contain names or codes; use `user_id` and the `request_id` the user can read from the `X-Request-ID` header.
- **Diagnose:**
  - *One employee:* 429 means locked (5 failures, 60 s then doubling up to 15 min); wait, or the employee is typing the wrong code. If the code is lost, rotate it. `python -m app.users list` shows whether the account has a code.
  - *Manager:* check `MANAGER_NAME` / `MANAGER_PASSWORD` in Variables (production needs 12+ characters; the app refuses to start without it). A changed `MANAGER_PASSWORD` takes effect at the next deploy and signs the manager out everywhere. The login name must match `MANAGER_NAME` exactly.
  - *Everyone logged out:* `APP_SECRET` changed (sessions are signed with it), or `SESSION_HOURS` passed (24 h by default).
  - *Everyone blocked by IP:* only when `CLIENT_IP_HEADER` is set and the header carries a shared proxy address; unset it (per-account limits still apply) and verify the header (`architecture.md` section 7).
  - *403 "Request blocked." in the browser:* the CSRF check. Cause is a missing `X-Requested-With` header (an old cached `app.js`), a different `Host`/`Origin` (custom domain or proxy rewriting Host: add the origin to `ALLOWED_ORIGINS`), or a genuine cross-site request.
- **Recover:** `python -m app.users rotate "Name"` against the target database (prints a new code once; hand it over out of band; this also signs that person out everywhere). Lockouts expire by themselves; there is no manual unlock in the MVP (a locked name has to wait out the delay, at most 15 minutes; rotating the code does not clear a lock).
- **Verify:** the person can log in; `GET /api/me` returns the right role; an `audit_log` row `user.code_rotated` exists for a rotation.
- **Escalate:** a burst of `login_blocked` / `auth_failed` for many names is guessing: leave the limits on, rotate the manager password and `APP_SECRET`, and review `audit_log`. A leaked code: rotate it and review that person's recent activity.

## 5. Employee submission failures [PLANNED]
- **Symptoms:** "הגשה נכשלה", 4xx/5xx on `PUT /api/availability`. **Signals:** `availability_submitted` absent; validation error type; 409 = deadline passed. **Diagnose:** is the week row present; employee id from session; payload dates inside the week. **Recover:** fix cause; employee resubmits (before deadline). If a legitimate submission was lost at the deadline boundary → manager decides (no silent reopen; use a change request). **Verify:** submission visible on manager dashboard. **Escalate:** repeated 500s → rollback.

## 6. Deadline / timezone errors [PLANNED]
- **Symptoms:** form locked early/late, DST week off by one hour. **Signals:** `deadline_state` events with computed `deadline_at` (UTC) and local time. **Diagnose:** `TIMEZONE` variable; container tz database present (`tzdata` in requirements); `CLOCK_OVERRIDE` must be unset in production (startup refuses it). **Recover:** fix config; if a week row has a wrong `deadline_at`, correct via a reviewed migration/script, never by hand. **Verify:** deadline unit tests incl. DST weeks; compare displayed deadline to Tuesday 22:00 Israel.

## 7. Schedule generation failure [PLANNED]
- **Symptoms:** draft request errors; **Signals:** `draft_generated` missing, `schedule_validation_failed`. **Diagnose:** before deadline (expected 409)? engine exception vs validator rejection (engine bug → output is withheld by design). **Recover:** retry; file a bug with the `schedules.run_json` (schedule id) and inputs hash (no personal text). **Verify:** draft generated, validator clean. **Escalate:** a validator rejection is a P1 bug; do not publish.

## 8. Unsatisfiable constraints / uncovered shifts [PLANNED]
- Not an outage. The result lists unfilled slots with reasons. Manager options: wait for/approve change requests, contact employees, accept gaps. Verify via `get_staffing_gaps`. Escalate only if the report contradicts the data (engine bug).

## 9. Agent / tool errors [PLANNED]
- **Symptoms:** Copilot replies with an error; tool chip fails. **Signals:** `tool_executed` status/error_type; `runs.tool_trace`; `runs.status='error'`. **Diagnose:** tool input validation failure vs DB error vs round limit (6). **Recover:** rephrase; fix bug via PR with an eval/test case. **Verify:** repeat the manager question. Never run ad-hoc SQL fixes; data fixes are reviewed scripts.

## 10. Anthropic API failures [EXISTS in SDK retry; events PLANNED]
- Check `status.anthropic.com`; `/health` `ANTHROPIC_API_KEY missing`; `runs.status='error'` and `error_type`. SDK retries 3×. Recover: wait; fix key. Verify: one Copilot turn. Hard-coded unsupported model/effort id → 400s: check `MODEL`/`MODEL_EFFORT`.

## 11. Rate limits and cost caps [EXISTS]
- `GET /api/stats`: spend vs `DAILY_CAP_USD`. Cap hit = working as designed; raise only with owner approval. PLANNED: `unknown_model_price` event means cost is being undercounted — add the model to the price table.

## 12. Scheduled digest failure [EXISTS for bakery digest; shift digest PLANNED]
- **Symptoms:** no morning brief. **Signals:** cron service run logs; PLANNED `digest_run` event + `digest_run` audit row; DST guard may skip a duplicate UTC run by design. **Diagnose:** cron expression, service variables (references to web), webhook URL. **Recover:** `POST /internal/digest` with `X-Cron-Secret`. **Verify:** brief contains the section `הגשת משמרות לשבוע הבא` and matches DB counts.

## 13. Database migrations [EXISTS: Alembic]
- **Symptoms:** deploy red at start (`alembic upgrade head` failed in the start command), `/health` 503 with `schema: migrations pending`, `migrations_pending` warning in logs, errors such as "no such table" or `UndefinedTable`.
- **Signals:** deploy log lines `Running upgrade 000x -> 000y`; `app_start.schema`; `db_error` events (they carry `error_type` only; the exception text is deliberately not logged, so read the deploy log of the failing `alembic` command for the SQL error).
- **Diagnose:** run `alembic current` and `alembic heads` against the production database (Railway shell or `railway run`). Pending = current is behind head. A failed revision leaves the database at the previous revision (PostgreSQL DDL is transactional).
- **Recover:** fix forward with a new revision through a PR; do not edit an applied revision and do not change the schema by hand. If the new code is already deployed against an old schema, redeploy the previous release (migrations are written to be backward compatible for one version).
- **Verify:** `/health` 200 with no `schema:` problem; `alembic current` shows `(head)`; `python -m pytest -q tests/test_migrations.py` green in CI.
- **Escalate:** a migration that dropped or rewrote data -> restore from backup (section 14) before anything else.

## 13a. Finding what happened to one request [EXISTS]
1. Every response carries `X-Request-ID`. Ask the user for it, or find it from the time and route in Railway logs (`event: "request"`).
2. Filter logs by that `request_id`: you see `request` (status, duration), and for chat `copilot_request`, `tool_executed`, `copilot_run` (model, tokens, cost) or `agent_error`/`unhandled_error` (with `error_type` and a message-free stack).
3. For a business change, the matching `audit_log` row carries the same `request_id`.
4. Logs never contain passwords, tokens, message text or employee free text; if you need the content, it is in the database (messages, audit_log), not the logs.

## 14. Backups and restoration [EXISTS (Railway); drill PLANNED]
- Railway Postgres → Backups → restore into a staging database first → point a staging deploy → verify (login, submissions, schedule) → then production in a quiet hour. **Practice the restore once before relying on it.**

## 15. Rollback [EXISTS]
- Deployments → previous green deploy → Redeploy. If a migration ran, check backward compatibility (§13) before rolling back; otherwise restore (§14) or fix forward.

## 16. A secret leaked [EXISTS, from instructor]
- Rotate first (Anthropic key, `APP_SECRET`, manager password, employee codes, `CRON_SECRET`), update Variables, redeploy, then clean Git history, open a `bug` issue.

## 17. Verification after any incident
1. `/health` 200. 2. Manager login + employee login. 3. Employee submission round-trip (before deadline) or read-only view (after). 4. Dashboard counts. 5. Draft generation (after deadline) clean. 6. One Copilot turn. 7. Logs show no repeating errors for 10 minutes. 8. Record the incident in this file.

## Contacts
Owner (cost and data decisions); Railway status `status.railway.com`; Anthropic status `status.anthropic.com`.
