# ADR 0012 — Frontend scope limited to Today/Ledger/Admin, built last

**Status:** Decided

## Decision

Per plan-approval amendment #10: the Next.js frontend is limited to three
pages (Today, Results Ledger, Admin/Control Room) for this vertical
slice — All Projections, Player View, and Methodology pages from the
owner's wireframes are deferred (the Today page already shows every
evaluated projection, so the transparency principle is satisfied without
them yet).

Sequencing: the frontend is not started until the backend vertical slice
(ingestion → point-in-time snapshot → feature/model → decision →
ledger → grading) and the point-in-time leakage test suite are fully
working and passing. Phase 1 (this build) is backend foundation only — no
`web/` code is written yet.
