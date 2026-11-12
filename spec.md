# spec.md — Smart Shift Copilot

**Status: PLAN APPROVED (2026-11-11); nothing is implemented yet.** The repository still contains the instructor's Bakery Copilot code (see `README.md` → Implementation status). This spec is the contract for Phase 1. Owner decisions of 2026-11-11 are folded in and listed in §14.

Legend: **[APPROVED]** = stated by the owner in the project brief. **[PROPOSED]** = my recommendation, needs a yes/no. **[OPEN]** = unresolved question (collected in §14).

## 1. Purpose

A Hebrew-first, RTL, mobile-friendly web app that reduces the manual back-and-forth of building a weekly employee shift schedule for one small Israeli business. Employees submit weekly availability; the manager builds, adjusts and explains the schedule with a deterministic engine and an AI Copilot. [APPROVED]

It is a course MVP adapting the instructor's Bakery Copilot architecture (FastAPI + agent loop + tools + Postgres + Railway + daily digest) to a different business workflow, with room to grow into a product. One demonstration business, not multi-tenant. Fictional employees and data only. [APPROVED]

## 2. Users

| Role | Who | Device | Access |
|---|---|---|---|
| Employee | **8 fictional employees** | Smartphone first | Own availability, preferences, change requests, own published shifts only |
| Manager | 1 manager | Smartphone and desktop | Everything, plus the Copilot |

[APPROVED: two roles, employees primarily on phones, manager fully functional on mobile.] Per-employee authentication is approved in principle with protection against guessing, brute force and cross-employee access (`architecture.md` §7). "Employee" and "manager" are access roles only; there are no job roles or qualifications in the MVP.

## 3. Phase 1 scope [APPROVED]

1. Employee weekly availability form, preferred weekly shift range, optional free-text requests.
2. Server-enforced Tuesday 22:00 (Asia/Jerusalem) deadline; read-only form afterwards.
3. Post-deadline change requests with manager approve/reject and an audit trail.
4. Manager dashboard: submission status, who has not submitted, preferences, pending requests, staffing requirements, coverage gaps, draft vs published schedules, Copilot.
5. Deterministic scheduling and validation engine (hard constraints vs soft preferences).
6. Manager AI Copilot using the instructor's agent loop with constrained tools.
7. Daily manager brief (scheduled digest) grounded in database data.
8. Structured logging, mobile-first UI, tests and evals.

Out of Phase 1: everything in §10 (Phase 2) and §11 (exclusions).

## 4. Time model [APPROVED unless marked]

- Workweek starts **Sunday**. The form shows the real dates of the target week (Sunday–Saturday).
- Submission concerns the **next** workweek. Deadline = **Tuesday 22:00, Asia/Jerusalem**, the Tuesday that falls 5 days before the target Sunday. [APPROVED 2026-11-11]
- Deadline is stored as an absolute instant (UTC) computed with the IANA `Asia/Jerusalem` zone so DST changes are handled by the tz database, never by hand-written offsets. Enforced **on the server** on every write.
- **The submission window opens** at the **earlier** of: (a) the moment the manager **publishes the preceding week's schedule**, and (b) **Thursday 22:00, Asia/Jerusalem**, even if that schedule has not been published. It then **closes the following Tuesday at 22:00**, Asia/Jerusalem. [APPROVED 2026-11-11] In dates, for a target week starting on Sunday S: it closes on the Tuesday 5 days before S, and opens by the latest on the Thursday 10 days before S (that Thursday is 2 days after the preceding week's own Tuesday deadline).
  - *Example.* Availability for 22–28 Nov closes Tuesday 17 Nov at 22:00. If that schedule is published on Wednesday 18 Nov, submissions for 29 Nov–5 Dec open immediately. Otherwise they open no later than Thursday 19 Nov at 22:00. They close Tuesday 24 Nov at 22:00.
  - Before the window opens the form is not available and the server rejects submissions; the employee sees when it opens (publication of the preceding schedule, or Thursday 22:00 at the latest).
  - The opening instant is **derived**, not stored: it is a pure function of the target week and the first publication time of the preceding week's schedule. Publishing early opens the window; later re-publishing or edits never move it, and publication after Thursday 22:00 changes nothing.
  - The manager still **cannot generate a draft before the relevant deadline**; the preceding week's schedule can only be published after its own deadline and draft, so a window never opens before that deadline.
  - Not implemented yet: this belongs to the availability and deadline issues (#5, #6, #11), not to the UI shell.
- Before the deadline: employees create/edit/resubmit freely; latest values win; no manager approval; no snapshots or version history of the original submission.
- After the deadline: the form is read-only (employee sees own submission); changes go through a separate change request needing manager approval.
- The manager **cannot generate a draft before the deadline**. Server rejects it.

**Open questions about the opening rule (recommendations, not decisions)**
- The very first cycle has no preceding schedule: recommend that it opens by the Thursday 22:00 rule only (or by a seeded opening time for the demo).
- "Publishes" means the first publication of that week's schedule; recommend using the earliest `published_at`, so later superseding publications do not matter.
- A week whose preceding schedule is never published simply opens at Thursday 22:00; nothing else is needed.

## 5. Employee workflow

**Main form heading (exact):** `הגשת משמרות לשבוע הבא`

1. Sees the target week with real dates, the window state (not open yet, with when it opens / open, with the deadline countdown / closed) and the submission state (not submitted / submitted / locked) prominently.
2. For each day, selects the shifts they can work. Shift definitions are configurable data; the MVP demo uses **two shifts per day: בוקר (Morning) and ערב (Evening)**, with a default staffing requirement of **2 employees per shift**. No night shift in the MVP. [APPROVED 2026-11-11] Shift names, times and `required_staff` live in a small `shifts` table seeded by migration/seed script; there is no admin UI for them in Phase 1.
3. Per-day shortcuts (UI only, not availability states): **`כל המשמרות`** selects every shift that day; **`לא זמין/ה`** clears the day. Editing any single checkbox afterwards just changes the selection; the shortcut buttons never hold state of their own.
4. Separate section: **preferred minimum / maximum shifts per week.** Preferences, not guarantees. Notice (exact): `נשתדל להתחשב בהעדפותיך בעת הכנת הסידור, אך אין התחייבות למספר המשמרות המבוקש.` Validation: integers ≥ 0, min ≤ max, max ≤ number of available slots in the week (soft warning, not block) [PROPOSED].
5. Separate optional free-text field for personal requests. Notice (exact): `נשתדל להתחשב בבקשות ככל האפשר, בהתאם לצורכי העסק ולאילוצי השיבוץ, אך אין התחייבות שניתן יהיה להיענות לכולן.` Length cap [PROPOSED: 1,000 chars].
6. Submit → server validates → confirmation shown. Resubmit allowed until the deadline.
7. After the deadline: read-only view + a clearly reachable button to open a **change request**.
8. After the manager publishes: employee sees **only their own** assigned shifts.

### Change requests [APPROVED]
- Separate screen from the locked form. Structured: pick dates and shifts and the desired availability change (add / remove), plus optional explanation.
- Statuses: `pending`, `approved`, `rejected`. Manager decides; approval applies the change to active availability **subject to validation** (§7 hard constraints re-checked); rejection changes nothing.
- Full audit trail of request, decision, who, when.
- **A change request is about future availability. It is not cancellation of an assigned shift** and does not release the employee from a published shift. Approved availability changes that conflict with an already-published assignment are surfaced to the manager as a conflict; they never silently modify the schedule.

## 6. Manager workflow

Dashboard (mobile-usable): submission status for the target week; employees who have not submitted; each submission with preferences/requests; pending change requests; staffing requirements vs availability and coverage gaps; draft and published schedules (clearly labelled); Copilot access.

1. Before the deadline: monitor submissions. No draft generation.
2. After the deadline: request **draft generation** (button or Copilot). Result may be partial; uncovered shifts are listed explicitly.
3. Review, adjust (preferably via Copilot proposals, §8), then **explicitly approve and publish**. Publishing is never automatic. [APPROVED]
4. Post-publish changes are made only through validated, explicitly confirmed changes; unrelated assignments are never reshuffled.
5. Decide change requests (approve/reject) with the validation result visible.

Draft vs published are separate states with separate UI labels (`טיוטה` / `פורסם`). A published schedule is immutable except through confirmed, audited changes. [APPROVED; exact mechanism PROPOSED in architecture.md]

## 7. Scheduling rules

### Hard constraints [APPROVED minimum — nothing else is hard without approval]
- H1. No assignment outside the employee's **approved** availability (submitted + approved change requests).
- H2. No overlapping shifts for one employee (overlap computed from shift start/end times).
- H3. *(Role requirements: not applicable in the MVP. No roles or qualifications exist; the validator interface leaves room for them in Phase 2.)*
- H4. A schedule never silently violates mandatory staffing/scheduling constraints.
- H5. If full coverage is impossible, the uncovered slots are **reported explicitly** (partial proposal or declared infeasible). A valid-looking but invalid result is never produced.

### Soft preferences (best effort, never promised)
Preferred min/max weekly shifts; individual preferences; fair distribution; balance between employees. Free-text requests are **not** auto-converted to hard constraints; ambiguous or potentially critical ones are **flagged for the manager** instead of silently interpreted.

**No additional hard rules are introduced.** Not added: maximum consecutive days, minimum rest between shifts, legal-hours limits, overtime. 
> **Legal compliance notice.** The MVP does not implement Israeli employment-law requirements (weekly rest, daily/weekly hours limits, overtime, night-work rules, minors, etc.). Further implementation and legal review are required before any real-world production use. This must stay visible in `README.md` and the manager UI footer/about text. [APPROVED 2026-11-11]

### Facts preserved for explanations
Each engine run stores: inputs (availability snapshot hash), staffing requirements, assignments, unfilled slots with the reason class (`no_one_available`, `all_available_blocked_by_overlap`, …), per-employee counts vs preferences, and which preference(s) were unmet and why. The Copilot explains from these facts, never from inference.

## 8. Copilot (manager only)

Example questions are the six from the brief (missing submissions, uncovered shifts, build next week's schedule, why Dana got only two shifts, who can replace Michal Thursday evening, move Ron to Tuesday morning and find a replacement). The agent: understands the request → selects tools → retrieves data → uses deterministic validation → explains results and conflicts → asks focused clarifying questions → **requires explicit manager confirmation before modifying approved or published assignments.**

Rules:
- No arbitrary SQL. Only constrained, validated tools (`architecture.md` §Tools).
- Responses separate **facts** (from the DB), **computed results** (from the engine/validator) and **suggestions** (AI), visibly.
- Never invents availability, qualifications or reasons.
- Replacement suggestions mean "available and rule-valid", **not** consent of that employee. There is no replacement-approval workflow in Phase 1.
- The model cannot apply a modification itself; a manager UI action does (architecture.md §Confirmation).
- Copilot UI strings and replies are Hebrew.

## 9. Daily manager brief [APPROVED]

Scheduled digest adapted from the instructor's. Grounded only in database data; no invented issues; if nothing needs attention it says so. Contains a section titled exactly `הגשת משמרות לשבוע הבא` with: submitted count, non-submitters (names), time remaining to the deadline, insufficient availability for required shifts, pending change requests, coverage problems, and other changes needing attention. [PROPOSED: deterministic text, no model call — zero token cost and zero hallucination risk.]

## 10. Phase 2 (approved, NOT implemented, NOT to be built in Phase 1)

1. Automatic initial draft immediately after the Tuesday deadline (manager still approves; Phase 1 is manager-triggered).
2. Employee administration (manager only): create, delete, temporarily freeze employees; preserve historical records.
3. Permanent employee profile settings (manager-set; e.g. evenings only, nights only, role qualifications); employees cannot change them.
4. Availability form restrictions driven by those profile settings (ineligible shifts disabled).

Phase 1 does not pre-build any of these; the data model is kept simple enough that adding them later is an additive migration.

## 11. Explicit exclusions (deliberate product boundary)

Cancellation of published shifts, sickness reporting and no-show reporting are **handled by telephone with the manager and are intentionally outside the application** — not an unfinished feature. Also excluded: real WhatsApp integration; automatic publishing; replacement-employee approval workflow; multi-tenant/SaaS; payments; payroll.

## 12. Non-functional requirements

**Mobile-first (mandatory).** Employees mainly use phones; manager UI fully functional on mobile. Design mobile-first; test at 360, 390, 768 px and desktop; no unintended horizontal overflow; no wide tables (schedule = day-by-day cards on narrow screens); touch targets ≥ 44×44 px; responsive dialogs; chat readable on small screens; conflicts always visible; accessible labels. Process rule in `practice.md`.

**UI shell (M0-4, implemented).** One page, three views (login, manager, employee) with data-driven navigation that shows only working destinations. Light theme by default, dark by device preference; Heebo self-hosted (OFL); product name stays in English, everything else is Hebrew; Copilot replies render through a small safe Markdown renderer (paragraphs, bold, lists, tables; no HTML, links or images). Detail in `architecture.md` §3a; evidence in `docs/ui-checks/m0-4/`.

**Hebrew/RTL.** `<html lang="he" dir="rtl">`, logical CSS properties (`margin-inline-*`, not left/right), natural Hebrew copy, correct Sunday-first week, Hebrew day names, `Asia/Jerusalem` dates, isolated LTR runs for numbers/times where needed.

**Security.** Backend authorization on every endpoint; employees can never read another employee's availability/requests/preferences; manager-only operations protected server-side; secure cookie sessions; input validation; secrets only in env; no real personal data in the public repo.

**Logging.** Structured JSON logs and separate persistent audit records (`architecture.md` §Observability).

**Cost assumptions** (prices in `app/config.py`: Sonnet 5.5 $2/$10 per Mtok in/out, Opus 5.5 $4/$20, Haiku 5.5 $0.10/$0.50): one manager, tens of Copilot turns per day at most. With the instructor's cap mechanism (`DAILY_CAP_USD`, per-user hourly limit) retained, expected Anthropic spend is single-digit USD/month; Railway ≈ $4–6/month (instructor's estimate, to be re-measured). Model comparison runs need owner approval.

## 13. Acceptance criteria (Phase 1 "done" — checks a stranger can run)

Employee
1. Login as an employee; see `הגשת משמרות לשבוע הבא` with real Sunday–Saturday dates and the deadline.
2. Select shifts; `כל המשמרות` selects all of a day, `לא זמין/ה` clears it; toggling a single box afterwards behaves correctly.
3. Min/max preference and free text have their exact notices; min > max is rejected with a Hebrew message.
4. Resubmit before the deadline: latest values saved. Before the window opens a write is rejected (409); the window opens at the earlier of publication of the preceding week's schedule and Thursday 22:00 Asia/Jerusalem, and closes Tuesday 22:00 (tested with a clock override, including Israel DST weeks and the boundary second).
5. After the deadline (test with a clock override in non-production): form is read-only; a direct API write is rejected 403/409 server-side (not just UI).
6. DST: deadline computed correctly for target weeks around Israel's DST changes (unit-tested).
7. Change request: submit, see `pending`; manager approves → availability updates; reject → no change; both audited.
8. Employee A cannot fetch employee B's data (API tests for every endpoint).
9. Published schedule shows an employee only their own shifts.

Manager
10. Dashboard lists submitted/not submitted, preferences, pending requests, staffing gaps.
11. Draft generation before the deadline is rejected; after it, returns assignments + explicit uncovered slots; no assignment violates H1–H2 (property tests).
12. Infeasible input yields a partial/infeasible report, never an invalid schedule.
13. Publish requires explicit confirmation; draft vs published visibly distinct.
14. Copilot answers the six example questions via tools; a change request to the Copilot to modify a published assignment produces a *proposal* and does nothing until the manager confirms in the UI; an invalid proposal is refused with the violated rule.
15. Daily brief contains the exact section title and only database-backed facts; `POST /internal/digest` works with the cron secret.

Cross-cutting
16. All UI text Hebrew, RTL, mobile checks at 4 widths recorded in the PR (practice.md).
17. `pytest` green on SQLite **and** PostgreSQL in CI; no secret in repo (`git grep` checks); logs contain no tokens/free-text requests (test).
18. `/health` 200 on the deployed Railway URL; deployed app reachable and demo-able.
19. `python -m evals.run` meets the agreed baseline (value to be agreed after first run).

## 14. Decisions and remaining questions

**Approved by the owner on 2026-11-11**
- Deadline: Tuesday 22:00 Asia/Jerusalem for the workweek starting the following Sunday.
- 8 fictional employees; 2 shifts/day (Morning, Evening); default 2 staff per shift; no Night shift; no roles or qualifications in the demo.
- Shift definitions and staffing are configurable data, without an administration module.
- No additional hard scheduling rules; legal-compliance notice (§7) is mandatory.
- Free-text preference analysis is manager-triggered, not automatic.
- Daily digest is deterministic, no model calls initially.
- Per-employee authentication with brute-force and cross-employee protections.
- The Copilot (real agent tool use) is built early, read-only tools first (`ROADMAP.md`).
- No paid Anthropic calls until separately approved.

**Defaults I am applying unless told otherwise** (low risk, easy to reverse)
- An employee with no submission, or no available slots, is never scheduled (no approved availability = no assignment).
- A change request may add availability for any future slot; it never auto-assigns anyone, and conflicts with published shifts are shown to the manager.
- Copilot conversations are kept per manager (instructor's persistence); 90-day retention is manual in v1.
- Free-text request analysis is cached by text hash so repeats cost nothing.
