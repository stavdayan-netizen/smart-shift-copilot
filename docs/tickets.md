# Tickets — Smart Shift Copilot

The GitHub Issues are the source of truth once created; this file is the planning summary. Board: **Smart Shift Copilot** (To do · In progress · Done). Labels: `phase-1`, `phase-2`, `enhancement`, `bug`, `documentation`. Phase 2 issues are deferred and stay in To do. Every ticket obeys `practice.md` (mobile-first DoD for UI, tests on SQLite and Postgres, structured logging, runbook, no unapproved scope). Nothing runs paid Anthropic calls without separate approval.

Legend: ★ essential for course submission · ◇ deferrable.

## Phase 1

**M0 Foundation ★**
1. **M0-1 Fork cleanup and baseline** — remove bakery domain code/data/tools/prompt, repoint `.railway/railway.ts` and docs to our fork, keep the instructor's tests green or adapted. Done when: app starts, suite passes, baseline result recorded.
2. **M0-2 Logging, Alembic, Postgres CI** — JSON logs with request IDs and redaction (planted-secret test), Alembic baseline migration, CI runs pytest on SQLite and Postgres.
3. **M0-3 Per-employee authentication** — scrypt-hashed codes, manager password from env, lockout and per-IP throttle, no user enumeration, `require_employee`/`require_manager`, route-inventory test, cross-employee denial tests, `auth_failed` logs.
4. **M0-4 Hebrew RTL mobile shell** — `lang=he dir=rtl`, mobile navigation, logical CSS, legal-compliance notice; 360/390/768/desktop checks recorded.

**M1 Availability ★**
5. **M1-1 Schema, seed and deadline service** — the 12 tables, 8 fictional employees, Morning/Evening × 2 staff, deadline function for Tuesday 22:00 Asia/Jerusalem and the submission-window function (opens at the earlier of publication of the preceding week's schedule and Thursday 22:00, closes Tuesday 22:00; DST-week and boundary tests), `clock.now()` with non-production override.
6. **M1-2 Availability form and API** (no shift-count preferences; at least one shift; 20 saves per hour; opening notice and "create and edit until Tuesday 22:00" statement) — exact Hebrew heading and notices, real dates, day shortcuts, min/max, free text, server-enforced window (rejected before it opens, locked after the deadline; the opening rule in `spec.md` section 4), audit/log events. Mobile DoD.

**M2 Copilot v1 ★ (course core)**
7. **M2-1 Agent loop adaptation with read-only tools** — manager-only chat, Hebrew prompt, `get_submission_status` and `get_availability`, `runs.tool_trace`, cost accounting (unknown model price is an error), model/effort from env (Sonnet 5.5 / high candidate), fake-model tests, eval cases written but **not run** without approval. Mobile chat check.

**D1 Deploy ★**
8. **D1 First Railway deploy** — needs owner approval before creating resources. Done when: public URL, `/health` 200, form usable on a real phone, rollback tried once.

**M3 Scheduling ★**
9. **M3-1 Manager dashboard** (including a warning when a submission window has opened while the preceding schedule is unpublished) — submission status, non-submitters, preferences, staffing requirement vs availability and gaps; usable at 360px.
10. **M3-2 Scheduling engine and validator** — deterministic greedy plus repair, independent validator, property tests for hard constraints, unfilled slots with reasons, facts in `schedules.run_json`.
11. **M3-3 Draft/publish and schedule views** — draft refused before the deadline, explicit publish confirmation (first publication of a week's schedule can open the next week's submission window early), draft vs published labels, day-by-day mobile view, employees see only their own shifts, audit rows.

**M4 Copilot v2 ★**
12. **M4-1 Scheduling tools and confirmed changes** — gaps, schedule, draft generation, replacements, explanations, `propose_change` and UI confirmation with re-validation; no write without confirmation. Evals (approval required to run).

**M5 Change requests**
13. **M5-1 Post-deadline change requests** — separate screen, structured items, pending/approved/rejected, approval re-validates and updates availability, conflicts with published shifts surfaced not auto-resolved, copy states it is not a cancellation.

**M6 Daily brief ◇**
14. **M6-1 Deterministic daily brief and cron** (including the same unpublished-preceding-schedule warning) — section titled `הגשת משמרות לשבוע הבא`, DB facts only, DST-safe schedule, idempotent via audit row.

**M7 Hardening ◇**
15. **M7-1 Evals baseline, runbook verification, final responsive pass** — spend approved first; each runbook entry marked verified or planned.

## Phase 2 (deferred; To do)
16. **P2-1 Automatic initial draft after the Tuesday deadline**
17. **P2-2 Employee administration (create, delete, freeze)**
18. **P2-3 Permanent employee profile settings**
19. **P2-4 Availability form restrictions from profile settings**

The instructor's bakery issue script was removed in M0-1; the GitHub issues are the source of truth.


## Added 2026-11-12: approved requirements and their placement (`spec.md` section 5a)
| Issue | Content | Depends on | Blocks / affects |
|---|---|---|---|
| **M5-2** Leave requests (#28) | Dates or ranges with optional reason; manager approves, rejects, proposes partial approval or alternative dates; employee acceptance; statuses incl. `ממתין לתשובת העובד`; full decision history; approved leave disabled in the form and excluded from scheduling | M1-2 (#6), M0-3 auth, audit | M3-1 (#9, report shows leave), M3-2 (#10, engine excludes leave), M3-4 (exemptions), M1-2 form (disabled dates seam) |
| **M3-4** Submission report and draft authorization (#29) | Report (submitted, missing, exempt, reopened); explicit authorization of draft generation with recorded override; draft and publish as separate approvals | M1-2, M3-1 (#9); exemptions from M5-2 | gates M3-2 (#10), M3-3 (#11), M4 (#12) |
| **M5-3** Reopen for one employee (#30) | Manager reopens one employee's form for a duration or exact closing time; audited; others unaffected | M1-2 (`enforce_window` seam), audit | M3-4 report ("reopened"), M5-1 change requests (an alternative route for late changes) |
