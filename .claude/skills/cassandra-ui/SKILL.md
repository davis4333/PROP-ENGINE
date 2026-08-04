---
name: cassandra-ui
description: Guidance for building or reviewing Cassandra's Next.js frontend (web/) — the approved Today/Ledger/Admin scope limit (ADR 0012), the near-black/violet-glow design language, and the evaluated/qualified/published three-tier transparency distinction (ADR 0002) that the Today page must keep visually distinct. Use when working in web/, discussing frontend pages or components, or reviewing UI/UX changes.
---

# Cassandra frontend (web/) guidance

## Sequencing gate — check this first

Per `docs/adr/0012-frontend-scope-and-sequencing.md`: the frontend is not
started until the backend vertical slice (ingestion → point-in-time
snapshot → feature/model → decision → ledger → grading) **and** the
`engine/tests/pit/` leakage suite are fully working and passing. If asked
to build frontend features while that isn't true yet, say so explicitly
before writing code — don't build ahead of a backend that doesn't exist,
since the pages are meant to render real API responses, not scaffolding
with mocked shapes that may not match what the engine actually produces.

Currently `web/` contains only the Next.js App Router scaffold
(`web/src/app/layout.tsx`, `page.tsx`, `globals.css`) — no real pages,
components, or API integration yet.

## Scope: exactly three pages, no more (ADR 0012)

Only **Today** (`/`), **Results Ledger** (`/ledger`), and **Admin**
(`/admin`) are approved for this vertical slice. The owner's wireframes
include All Projections, Player View, and Methodology pages — these are
explicitly deferred. Do not add a new route/page without checking with the
owner first; ADR 0012 reasons that the Today page alone already satisfies
the transparency principle (it shows every evaluated projection) without
needing the extra pages yet. Adding one anyway is scope creep against a
documented decision, not a neutral improvement.

## The three-tier transparency distinction must stay visually clear (ADR 0002)

The Today page is required to show the full **evaluated** set — every
projection row written for the slate, regardless of `decision` or
`decision_status` — not just the qualified or published subset. Within
that:

1. **Evaluated** — everything on the page. The full transparency record.
2. **Qualified** — `decision_status = 'QUALIFIED'` rows, visually
   highlighted (e.g. the "qualified plays" summary/`QualifiedPlaysCard`),
   but still shown inline with the rest, not extracted into a separate
   page that hides the others.
3. **Published** — rows with `published_at` set and not
   `is_late_publication`. Only these count toward Ledger aggregate
   stats/official track record.

A design that only renders qualified or published rows on Today, or that
computes Ledger win/loss aggregates from anything but published rows, is a
correctness bug, not a styling choice — it breaks the platform's core
transparency promise. Status badges must distinguish, per the handbook's
design system section: Qualified, Watchlist, No Play, Pending, Graded,
Void, Data Warning — and a late-published row must be visibly labeled as
late (ADR 0008), not folded silently into the normal published set.

## Design language

Per the handbook's Product Constitution and Frontend Design System
sections: near-black background, white primary text, violet/purple glow
accents, subtle circuit/constellation texture — "premium fintech-meets-
mythology" aesthetic, restrained rather than flashy. `web/src/app/
globals.css` already sets the base tone (`background-color: #09090b`,
`color: #fafafa`, `color-scheme: dark`) — extend that palette rather than
introducing a competing one. Use the existing approved Cassandra logo
as-is; do not redesign it when producing branded assets.

Communicate status without hype — no exclamation-heavy "HOT PICK" styling;
the tone is closer to a data/audit tool than a tout sheet, consistent with
the handbook's "premium fintech" framing and the platform's honest-grading
principle (losses are shown with the same visual weight as wins on the
Ledger page, never downplayed).

Tables must stay readable on mobile through prioritized columns and
expandable row details (handbook Frontend Design System) rather than
horizontal scrolling as the primary mobile pattern.

## Admin page specifics

`/admin` uses the ADR 0011 shared-secret placeholder auth
(`X-Admin-Secret` header) — when building this page's auth flow, treat it
visibly as a demo-only placeholder (e.g. don't design a polished "Sign In"
flow that implies real account security is behind it). It should surface:
source health tiles (from `source_health`), the 7-stage pipeline tracker
(`INGEST → VALIDATE → FREEZE → PROJECT → REVIEW → PUBLISH → GRADE`, from
`pipeline_runs`/`pipeline_run_stages`), warnings, current model version,
blocking issues, and the run-trigger controls for
`revalidate/regenerate/publish/grade` — each of which can fail with a
structured 409 state-guard error (ADR 0007) that the UI should render as a
specific, actionable message, not a generic error toast.

## Build priority

Per the handbook's build philosophy: "Backend/data/model integrity
receives 110% effort; frontend only needs to be polished and clear enough
to operate and compare results initially." Don't over-invest in frontend
polish at the expense of backend correctness review — if a task touches
both, the backend/data-integrity review (`cassandra-pit-audit`,
`cassandra-ledger-integrity`) takes priority.
