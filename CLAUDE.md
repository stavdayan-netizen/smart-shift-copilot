# CLAUDE.md — Smart Shift Copilot

Before any change, read the authoritative files; do not duplicate their content here:

- `practice.md` — mandatory working agreement (git workflow, **mobile-first Definition of Done**, testing, logging, cost).
- `spec.md` — approved scope. Phase 1 only. Phase 2 and the exclusions (`spec.md` §10–11) must not be built.
- `architecture.md` — how and where. Planned vs implemented is marked; update it in the same commit as the code.
- `runbook.md` — add an entry for every new failure mode.
- `ROADMAP.md` — milestone order and what is essential.
- `docs/tickets.md` — the ticket list; work one ticket at a time.

Hard rules: no implementation without an approved ticket · never push to `main` (branch + PR) · never edit `.env` or print secrets · UI is Hebrew + RTL + mobile-first and is not done until checked at 360/390/768/desktop (say "NOT VERIFIED" for anything not actually checked) · the model never writes approved/published assignments (propose → deterministic validation → manager confirms in the UI) · no paid Anthropic calls or evals without owner approval · fictional data only · `main` stays deployable.
