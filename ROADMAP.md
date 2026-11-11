# ROADMAP.md

Status as of 2026-11-11: **plan approved; M0-1 (fork cleanup) is done and merged; M0-2 (logging, Alembic, PostgreSQL CI, audit log) is merged; M0-3 (per-employee auth) is in review; no Smart Shift feature is implemented.** The code is the instructor's infrastructure with the bakery domain removed. Per-issue detail: `docs/tickets.md`. Scope: `spec.md`.

## Phase 1 — MVP (approved)

MVP scenario: 8 fictional employees, two shifts per day (Morning, Evening), 2 staff per shift, no roles, no Night shift. No additional hard scheduling rules; legal employment compliance is **not** implemented (see `spec.md` §7).

Owner priority: **a real agent with real tool use comes early**, not a form app with a bolted-on chatbot. It starts read-only (M2) and gains scheduling tools after the engine exists (M4).

| Milestone | Content | Depends on | Essential for submission? |
|---|---|---|---|
| M0 Foundation | Fork cleanup + baseline, JSON logging, Alembic, Postgres CI job, per-employee auth, Hebrew RTL mobile shell | — | Yes |
| M1 Availability | 12-table schema + fictional seed, deadline service (tz/DST), employee availability form and API | M0 | Yes |
| M2 Copilot v1 | Adapted agent loop, Hebrew prompt, **read-only tools** over availability data, manager chat UI, tool trace, cost accounting, fake-model tests | M1 | **Yes (course core)** |
| **D1 Deploy** | First Railway deploy: web + Postgres, `/health` (needs owner approval to create resources) | M2 | Yes (needs a URL) |
| M3 Scheduling | Manager dashboard, scheduling engine + validator, draft/publish, schedule views | M1 | Yes |
| M4 Copilot v2 | Scheduling tools, explanations, replacements, propose → validate → manager confirms | M2, M3 | Yes |
| M5 Change requests | Post-deadline requests, manager decision, audit | M1, M3 | Required by spec; first to cut to a minimal flow |
| M6 Daily brief | Deterministic digest + cron | M1, M3 (M5 for pending counts) | Deferrable, small |
| M7 Hardening | Evals baseline (approved spend only), runbook verification, final 4-width responsive pass | all | Partial |

Smallest viable submission: **M0 + M1 + M2 + D1 + M3 + M4**. If time runs short: M5 reduced to create/approve/reject, M6 and full evals after.

## Phase 2 — approved, deferred, NOT started

1. Automatic initial draft right after the Tuesday deadline (manager still approves) — depends on M3.
2. Employee administration: create, delete, freeze/deactivate; preserve history — depends on M1.
3. Permanent employee profile settings (manager-set; employees cannot edit) — depends on 2.
4. Availability form restrictions from profile settings — depends on 3 and the M1 form.

Suggested order: 2 → 3 → 4 → 1. Also future work, not scheduled: legal employment-compliance rules and legal review before any real production use.

## Explicitly excluded (deliberate product boundary, not "unfinished")

- Employee self-service cancellation of published shifts, sickness reporting and no-show reporting through the app. All are handled by telephone with the manager.
- Real WhatsApp integration.
- Automatic publishing without manager approval.
- Replacement-employee approval workflow.
- Multi-tenant SaaS.
- Night shifts and job roles in the MVP.
