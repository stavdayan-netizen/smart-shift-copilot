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

## 5. Employee submission failures [EXISTS: the availability form and API]
- **Symptoms:** a save fails in the form (a red message), the form shows "not open" when the employee expects it open, or an employee reports a submission that is missing.
- **Signals:** `window_rejected` (week, `not_open` or `closed`), `availability_submitted` (counts only), `auth_failed`/`forbidden`, `request` events with status 409, 422, 429 or 5xx and the `request_id` the employee can read from the `X-Request-ID` response header; `audit_log` rows `availability.submitted` (week, number of slots, has free text; never the content).
- **Diagnose:**
  - *409:* the week's window is not open or has closed. Check `GET /api/cycle` (section 6): opening is the first publication of the preceding schedule or Thursday 22:00 Asia/Jerusalem at the latest; closing is Tuesday 22:00. A frozen test clock (`CLOCK_OVERRIDE`) can explain surprises on non-production instances.
  - *422:* content rules: at least one shift, days inside the week, at most 1,000 characters of free text. The message names the field.
  - *429:* more than 20 saves in an hour; the message and `Retry-After` say when to retry. Failed saves do not count. `AVAILABILITY_SAVES_PER_HOUR` changes the limit.
  - *"No shifts defined":* run `python -m app.seed` (section 6a).
  - *Saved but not visible to the manager:* look for the audit row of that employee and week; the dashboard (issue #9) reads the same table.
  - *500 on save:* a failing audit write or a database error rolls the whole save back (nothing half-saved); find it by `request_id` (`unhandled_error`, `db_error`).
- **Recover:** fix the cause; the employee resubmits while the window is open. After the deadline nothing reopens it automatically; the manager decides (change requests and per-employee reopening are approved but not built yet, `spec.md` section 5a). Never edit submissions by hand in the database.
- **Verify:** the employee's GET shows the submission; one new audit row exists; the manager sees it.
- **Rollback/escalate:** repeated 5xx on save after a deploy: roll back the deploy; migration `0004` is backward compatible for one version (it only drops columns the previous code never used).

## 6. Deadline / timezone errors [EXISTS: rules, clock and status endpoint; the availability form that uses them is #6]
- **Symptoms:** the window shows open or closed at the wrong time, a DST week is an hour off, the status says `not_open` when the manager expects it open, or every date looks stuck.
- **Signals:** `GET /api/cycle` (signed in) returns `state`, `opens_at`, `closes_at` (Asia/Jerusalem with offset) and `clock_overridden`; `window_rejected` log events (week, state); `/health` and the `app_start` event show `clock: override` when the clock is frozen.
- **Diagnose:**
  - *Clock frozen by mistake:* `clock_overridden: true` or `clock: override` means `CLOCK_OVERRIDE` is set. It is refused when `APP_ENV=production`, so this can only happen on a non-production deployment. Unset it and redeploy.
  - *Opens late:* a window opens at Thursday 22:00 Asia/Jerusalem at the latest, or at the first publication of the preceding week's schedule if that is earlier. Until schedules exist (M3) only the Thursday rule applies. `opens_early_on_publication` says whether a publication could still open it early.
  - *Wrong hour:* the cycle rules are fixed to Asia/Jerusalem and ignore the `TIMEZONE` variable (which only affects the daily spend limit and the digest). Check the host's `tzdata` (the `tzdata` package is a dependency). Compare `closes_at` with Tuesday 22:00 local for the week; around the two Israel DST changes (late March, late October) the UTC offset differs between Thursday and Tuesday, which is correct.
  - *409 on a write:* the week's window is not open (`not_open`) or has closed. Nothing extends the Tuesday deadline automatically; a late change goes through a change request (M5).
- **Recover:** fix configuration and redeploy; data is never edited by hand. If a legitimate submission was refused at the boundary, the manager decides (a change request), the rule is not bent.
- **Verify:** `GET /api/cycle` shows the expected week and times; `python -m pytest -q tests/test_cycle.py` passes in CI.
- **Escalate:** a computed deadline that is not Tuesday 22:00 local is a P1 bug in `app/cycle.py`.

## 6a. Seeding the fictional demo data [EXISTS]
- `python -m app.seed` creates the two demo shifts and eight fictional employees if missing; re-running creates nothing and never changes an existing shift's settings. In production it needs `--confirm-fictional`. Access codes are printed once to the terminal: store them out of band; they cannot be shown again (`python -m app.users rotate "Name"` issues a new one).
- **Failures:** "migrations pending" or `UndefinedTable` means run `alembic upgrade head` first. A name clash with the manager's `MANAGER_NAME` stops the manager bootstrap, not the seed. To change a shift's time or staffing, update the `shifts` row through a reviewed script or migration; the seed will not.

## 7. Schedule generation failure [PLANNED]
- **Symptoms:** draft request errors; **Signals:** `draft_generated` missing, `schedule_validation_failed`. **Diagnose:** before deadline (expected 409)? engine exception vs validator rejection (engine bug → output is withheld by design). **Recover:** retry; file a bug with the `schedules.run_json` (schedule id) and inputs hash (no personal text). **Verify:** draft generated, validator clean. **Escalate:** a validator rejection is a P1 bug; do not publish.

## 8. Unsatisfiable constraints / uncovered shifts [PLANNED]
- Not an outage. The result lists unfilled slots with reasons. Manager options: wait for/approve change requests, contact employees, accept gaps. Verify via `get_staffing_gaps`. Escalate only if the report contradicts the data (engine bug).

## 9. Agent / tool errors [EXISTS: two read-only tools; `runs.tool_names`, `tool_executed` log]
- Tool status `bad_input` is the model asking for an unknown employee or a non-Sunday week: normal, the model corrects itself. Status `error` is a bug: find it with the request id. `unknown_model_price` in the logs means `MODEL` is not in the price table, so costs are recorded as 0 and the daily cap is blind: fix `PRICES_PER_MTOK`.
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
