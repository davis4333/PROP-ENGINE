# Cassandra Master Product & Engineering Handbook

**Version:** 1.0 handoff draft  
**Owner:** Tyler Davis  
**Product:** Cassandra / CassandraHits.com  
**Tagline:** DATA. MODELS. RESULTS.  
**Scope:** MLB player-prop platform, pitcher strikeouts first

> This document is the single source of truth for product direction, system architecture, data integrity, modeling, UI, operations, and Claude Code implementation. Confirmed decisions are separated from proposals and unresolved choices.

## How Claude Must Use This Handbook

1. Read `CLAUDE_START_HERE.md` first. 2. Do not infer missing product decisions. 3. Preserve immutable point-in-time records. 4. Implement one vertical slice at a time. 5. Never claim a feature is complete without tests and acceptance evidence.

## Confirmed Decisions

- **Product identity:** Cassandra / CassandraHits is an MLB player-prop analysis and prediction platform named after Cassandra, the prophet whose correct warnings were not believed.
- **Public tagline:** DATA. MODELS. RESULTS.
- **Primary objective:** Build the most accurate and trustworthy player-prop decision platform possible, optimized for the best chance of winning rather than the highest payout.
- **Initial sport:** MLB only until the system is proven and operationally reliable.
- **Initial market:** Pitcher strikeouts first; perfect one vertical before adding total bases, RBIs, and other markets.
- **Primary book/feed:** Underdog is the intended first public line source and the book Tyler expects to use.
- **Transparency:** Log every evaluated projection before first pitch, not only winning picks or recommended plays.
- **Grades:** Use win, loss, push, void, and no-play outcomes; never delete losses.
- **No forced action:** Sometimes the correct decision is No Play. The system must not manufacture daily picks.
- **Public growth plan:** Initially publish strong plays free, including on X, with a visible running record to prove performance before monetization.
- **Monetization:** After proof, introduce an affordable subscription around $15–$20/month while keeping enough public value to maintain trust.
- **Design language:** Near-black background, violet/purple glow accents, white text, subtle circuit and constellation details, premium fintech-meets-mythology aesthetic.
- **Logo handling:** Use the exact approved Cassandra logo; do not redesign it when creating branded assets.
- **Pre-launch product:** Simple, highly visual, usable interface before a complex full platform. Show all lines and projections while highlighting the best qualified plays.
- **Build philosophy:** Backend/data/model integrity receives 110% effort; frontend only needs to be polished and clear enough to operate and compare results initially.
- **Data integrity:** Backtests and historical features must use information knowable at the exact historical prediction timestamp. Future-data leakage invalidates results.
- **Learning:** The platform must grade outcomes, diagnose errors, monitor performance, and improve through controlled experiments and versioned model changes.
- **Workflow preference:** Visual system maps, workflows, mockups, and concrete examples come before dense technical prose.

## Product Constitution

- **Truth before marketing:** Cassandra must never imply certainty, guaranteed wins, or “locks.” Public claims must match measured evidence.
- **Point-in-time correctness:** Every feature used in a prediction must be traceable to a timestamped record available before the run cutoff.
- **Reproducibility:** Any historical or live projection must be reproducible from stored inputs, code version, model artifact, and configuration.
- **Immutable evidence:** Published projections and original source payloads are append-only. Corrections create new versions rather than overwriting history.
- **No-play is a product feature:** Declining weak or unsafe opportunities is core value, not a failure to produce content.
- **Separate prediction from presentation:** The engine produces structured facts; UI and language layers present them without altering the decision.
- **Vertical-slice development:** Complete pitcher strikeouts end-to-end before generalizing across prop markets.
- **Humans approve material changes:** Thresholds, feature definitions, grading policies, and model promotions require explicit change control.
- **Free proof before paywall:** Earn trust with transparent, verifiable performance before restricting premium value.
- **Visual-first operation:** The owner must be able to see where data came from, how the decision was made, and what failed.

## Unresolved Decisions

- **Exact Underdog acquisition method:** Confirm permitted, reliable method and legal/terms constraints before production ingestion.
- **Official MLB data vendors:** Select primary and backup providers for schedules, probable pitchers, lineups, pitch-level data, weather, umpire assignments, injuries and results.
- **Payout-specific decision math:** Finalize payout structures and break-even assumptions for each Underdog contest format.
- **Public confidence display:** Decide whether public users see probabilities, confidence tiers, edge ranges, or only simplified reasoning.
- **Which projections are public:** Decide whether all raw projections remain free forever or whether some analysis becomes premium after proof.
- **Initial authentication:** Determine whether pre-launch public pages are anonymous and admin is private, or whether user accounts launch immediately.
- **Hosting:** Choose between Replit for speed and a more conventional cloud stack after evaluating reliability, cost, scheduling, databases and observability.
- **Model family:** Establish baseline and compare interpretable statistical models, gradient boosting and other candidates; do not preselect the winner.
- **Minimum evidence before monetization:** Define sample size, calibration quality and live evaluation thresholds required before charging.
- **Public posting cadence:** Define exact timing and whether X posts are automatic or require human approval.

# Executive Vision

Cassandra is not a pick-selling page with selective screenshots. It is an evidence system that evaluates MLB player props, records what it knew at the time, produces a reproducible projection, decides whether the opportunity clears a defined threshold, publishes qualified plays, and grades every decision honestly. The long-term ambition is category leadership, but the immediate goal is narrower: prove one complete pitcher-strikeout vertical with clean data, dependable operations, and live results that survive scrutiny.

## Mission

- Build a trustworthy decision engine, not a hype-driven picks page.
- Earn public trust through verifiable, pregame records.
- Make every model output inspectable and reproducible.

**Required implementation contract**

- Inputs for mission must be explicitly typed and validated.
- Outputs for mission must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for mission must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of mission understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves mission works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Positioning

- Premium analytics presentation with plain-language explanations.
- Best-chance focus rather than lottery-ticket payout chasing.
- Free proof period followed by affordable subscription only after evidence.

**Required implementation contract**

- Inputs for positioning must be explicitly typed and validated.
- Outputs for positioning must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for positioning must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of positioning understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves positioning works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Customer

- Everyday bettors who want understandable evidence.
- Serious bettors who want complete lines, filters and audit history.
- Internal operator who needs a visual control room.

**Required implementation contract**

- Inputs for customer must be explicitly typed and validated.
- Outputs for customer must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for customer must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of customer understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves customer works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Value

- Centralize lines and context.
- Turn noisy information into disciplined decisions.
- Show when not to bet.
- Create a transparent performance record.

**Required implementation contract**

- Inputs for value must be explicitly typed and validated.
- Outputs for value must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for value must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of value understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves value works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Non-Goals

- No guaranteed wins.
- No launch with all sports.
- No untraceable black-box output.
- No selective deletion of losing history.

**Required implementation contract**

- Inputs for non-goals must be explicitly typed and validated.
- Outputs for non-goals must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for non-goals must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of non-goals understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves non-goals works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Success

- Reliable daily operation.
- Point-in-time audit passes.
- Calibrated live performance.
- Growing public trust and repeat usage.

**Required implementation contract**

- Inputs for success must be explicitly typed and validated.
- Outputs for success must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for success must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of success understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves success works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Decision History and Product Constitution

The project has evolved from a private two-leg strikeout protocol into a platform concept that can display all available lines and projections, publish daily qualified plays, maintain a public ledger, and eventually support an affordable subscription. The current direction replaces any earlier assumption that Cassandra should launch with every sport or every prop. The governing choice is depth before breadth.

## Confirmed Decisions

- Define confirmed decisions in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for confirmed decisions.
- Expose confirmed decisions visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for confirmed decisions.

**Required implementation contract**

- Inputs for confirmed decisions must be explicitly typed and validated.
- Outputs for confirmed decisions must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for confirmed decisions must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of confirmed decisions understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves confirmed decisions works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Principles

- Define principles in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for principles.
- Expose principles visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for principles.

**Required implementation contract**

- Inputs for principles must be explicitly typed and validated.
- Outputs for principles must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for principles must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of principles understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves principles works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Replaced Directions

- Define replaced directions in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for replaced directions.
- Expose replaced directions visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for replaced directions.

**Required implementation contract**

- Inputs for replaced directions must be explicitly typed and validated.
- Outputs for replaced directions must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for replaced directions must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of replaced directions understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves replaced directions works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Unresolved Items

- Define unresolved items in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for unresolved items.
- Expose unresolved items visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for unresolved items.

**Required implementation contract**

- Inputs for unresolved items must be explicitly typed and validated.
- Outputs for unresolved items must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for unresolved items must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of unresolved items understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves unresolved items works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Change Control

- Define change control in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for change control.
- Expose change control visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for change control.

**Required implementation contract**

- Inputs for change control must be explicitly typed and validated.
- Outputs for change control must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for change control must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of change control understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves change control works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Visual System Overview

The machine has five major zones: acquisition, point-in-time storage, projection, decision, and publication/learning. Deterministic code owns timestamps, joins, calculations, grading, and audit records. Statistical models own forecasting and uncertainty. Language AI may explain structured results and assist development but may not create facts, alter published history, or override safeguards.

## End-To-End Machine

- Define end-to-end machine in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for end-to-end machine.
- Expose end-to-end machine visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for end-to-end machine.

**Required implementation contract**

- Inputs for end-to-end machine must be explicitly typed and validated.
- Outputs for end-to-end machine must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for end-to-end machine must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of end-to-end machine understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves end-to-end machine works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Ai Placement

- Define AI placement in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for AI placement.
- Expose AI placement visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for AI placement.

**Required implementation contract**

- Inputs for AI placement must be explicitly typed and validated.
- Outputs for AI placement must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for AI placement must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of AI placement understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves AI placement works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Boundaries

- Define boundaries in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for boundaries.
- Expose boundaries visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for boundaries.

**Required implementation contract**

- Inputs for boundaries must be explicitly typed and validated.
- Outputs for boundaries must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for boundaries must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of boundaries understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves boundaries works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Daily Cycle

- Define daily cycle in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for daily cycle.
- Expose daily cycle visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for daily cycle.

**Required implementation contract**

- Inputs for daily cycle must be explicitly typed and validated.
- Outputs for daily cycle must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for daily cycle must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of daily cycle understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves daily cycle works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Failure Paths

- Define failure paths in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for failure paths.
- Expose failure paths visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for failure paths.

**Required implementation contract**

- Inputs for failure paths must be explicitly typed and validated.
- Outputs for failure paths must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for failure paths must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of failure paths understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves failure paths works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# User Experience and Pre-Launch UI

The first usable product should feel simple even when the backend is sophisticated. A user should immediately see slate status, qualified plays, every evaluated projection, and the complete public record. The admin should see data freshness, pipeline stages, warnings, model version, run controls, and the exact reason a prop was excluded.

## Audiences

- Define audiences in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for audiences.
- Expose audiences visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for audiences.

**Required implementation contract**

- Inputs for audiences must be explicitly typed and validated.
- Outputs for audiences must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for audiences must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of audiences understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves audiences works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Public Navigation

- Define public navigation in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for public navigation.
- Expose public navigation visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for public navigation.

**Required implementation contract**

- Inputs for public navigation must be explicitly typed and validated.
- Outputs for public navigation must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for public navigation must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of public navigation understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves public navigation works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Today Page

- Define today page in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for today page.
- Expose today page visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for today page.

**Required implementation contract**

- Inputs for today page must be explicitly typed and validated.
- Outputs for today page must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for today page must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of today page understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves today page works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## All Projections

- Define all projections in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for all projections.
- Expose all projections visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for all projections.

**Required implementation contract**

- Inputs for all projections must be explicitly typed and validated.
- Outputs for all projections must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for all projections must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of all projections understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves all projections works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Ledger

- Define ledger in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for ledger.
- Expose ledger visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for ledger.

**Required implementation contract**

- Inputs for ledger must be explicitly typed and validated.
- Outputs for ledger must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for ledger must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of ledger understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves ledger works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Player View

- Define player view in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for player view.
- Expose player view visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for player view.

**Required implementation contract**

- Inputs for player view must be explicitly typed and validated.
- Outputs for player view must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for player view must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of player view understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves player view works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Methodology

- Define methodology in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for methodology.
- Expose methodology visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for methodology.

**Required implementation contract**

- Inputs for methodology must be explicitly typed and validated.
- Outputs for methodology must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for methodology must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of methodology understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves methodology works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Admin

- Define admin in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for admin.
- Expose admin visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for admin.

**Required implementation contract**

- Inputs for admin must be explicitly typed and validated.
- Outputs for admin must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for admin must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of admin understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves admin works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Data Acquisition and Source Strategy

Every source must be registered with ownership, update cadence, expected latency, data license or terms status, schema, primary key, timestamp semantics, known failure modes, and backup plan. Source ingestion must preserve the original payload before normalization. Line data requires observation time, offered line, market, player, game, platform, payout context when available, and status.

## Source Registry

- Provider name and owner
- Data covered and grain
- Timestamp semantics
- Expected update cadence
- Terms/license status
- Fallback and outage behavior

**Required implementation contract**

- Inputs for source registry must be explicitly typed and validated.
- Outputs for source registry must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for source registry must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of source registry understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves source registry works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Lines

- Store every observation, not only latest
- Resolve player/game/market identity
- Track moves, suspensions and removals
- Preserve book/platform and payout context

**Required implementation contract**

- Inputs for lines must be explicitly typed and validated.
- Outputs for lines must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for lines must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of lines understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves lines works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Schedules

- Define schedules in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for schedules.
- Expose schedules visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for schedules.

**Required implementation contract**

- Inputs for schedules must be explicitly typed and validated.
- Outputs for schedules must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for schedules must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of schedules understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves schedules works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Players

- Define players in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for players.
- Expose players visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for players.

**Required implementation contract**

- Inputs for players must be explicitly typed and validated.
- Outputs for players must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for players must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of players understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves players works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Pitchers

- Define pitchers in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for pitchers.
- Expose pitchers visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for pitchers.

**Required implementation contract**

- Inputs for pitchers must be explicitly typed and validated.
- Outputs for pitchers must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for pitchers must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of pitchers understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves pitchers works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Lineups

- Define lineups in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for lineups.
- Expose lineups visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for lineups.

**Required implementation contract**

- Inputs for lineups must be explicitly typed and validated.
- Outputs for lineups must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for lineups must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of lineups understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves lineups works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Weather

- Define weather in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for weather.
- Expose weather visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for weather.

**Required implementation contract**

- Inputs for weather must be explicitly typed and validated.
- Outputs for weather must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for weather must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of weather understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves weather works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Umpires

- Define umpires in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for umpires.
- Expose umpires visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for umpires.

**Required implementation contract**

- Inputs for umpires must be explicitly typed and validated.
- Outputs for umpires must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for umpires must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of umpires understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves umpires works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Parks

- Define parks in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for parks.
- Expose parks visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for parks.

**Required implementation contract**

- Inputs for parks must be explicitly typed and validated.
- Outputs for parks must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for parks must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of parks understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves parks works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Results

- Define results in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for results.
- Expose results visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for results.

**Required implementation contract**

- Inputs for results must be explicitly typed and validated.
- Outputs for results must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for results must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of results understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves results works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Fallbacks

- Define fallbacks in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for fallbacks.
- Expose fallbacks visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for fallbacks.

**Required implementation contract**

- Inputs for fallbacks must be explicitly typed and validated.
- Outputs for fallbacks must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for fallbacks must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of fallbacks understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves fallbacks works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Point-in-Time Data Platform

Cassandra must be able to answer one question for every historical prediction: what information was actually available at that exact moment? Event time, source-published time, ingestion time, effective-from time, and correction time are separate concepts. Historical feature queries use as-of joins and reject records first observed after the prediction cutoff.

## Raw Storage

- Define raw storage in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for raw storage.
- Expose raw storage visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for raw storage.

**Required implementation contract**

- Inputs for raw storage must be explicitly typed and validated.
- Outputs for raw storage must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for raw storage must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of raw storage understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves raw storage works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Canonical Schemas

- Define canonical schemas in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for canonical schemas.
- Expose canonical schemas visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for canonical schemas.

**Required implementation contract**

- Inputs for canonical schemas must be explicitly typed and validated.
- Outputs for canonical schemas must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for canonical schemas must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of canonical schemas understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves canonical schemas works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Snapshots

- Define snapshots in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for snapshots.
- Expose snapshots visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for snapshots.

**Required implementation contract**

- Inputs for snapshots must be explicitly typed and validated.
- Outputs for snapshots must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for snapshots must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of snapshots understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves snapshots works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## As-Of Joins

- Join on information availability, not only event date
- Test boundary timestamps
- Retain records excluded by cutoff for audit

**Required implementation contract**

- Inputs for as-of joins must be explicitly typed and validated.
- Outputs for as-of joins must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for as-of joins must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of as-of joins understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves as-of joins works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Lineage

- Define lineage in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for lineage.
- Expose lineage visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for lineage.

**Required implementation contract**

- Inputs for lineage must be explicitly typed and validated.
- Outputs for lineage must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for lineage must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of lineage understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves lineage works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Freshness

- Define freshness in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for freshness.
- Expose freshness visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for freshness.

**Required implementation contract**

- Inputs for freshness must be explicitly typed and validated.
- Outputs for freshness must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for freshness must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of freshness understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves freshness works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Deduplication

- Define deduplication in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for deduplication.
- Expose deduplication visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for deduplication.

**Required implementation contract**

- Inputs for deduplication must be explicitly typed and validated.
- Outputs for deduplication must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for deduplication must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of deduplication understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves deduplication works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Corrections

- Define corrections in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for corrections.
- Expose corrections visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for corrections.

**Required implementation contract**

- Inputs for corrections must be explicitly typed and validated.
- Outputs for corrections must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for corrections must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of corrections understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves corrections works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Pitcher Strikeout Domain Model

Pitcher strikeouts are driven by strikeout ability, expected batters faced, pitch count and removal risk, opposing lineup contact behavior, handedness interactions, game context, and uncertainty about role. Cassandra should model strikeout opportunity and strikeout conversion rather than relying on a single recent-average number.

## Target Definition

- Define target definition in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for target definition.
- Expose target definition visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for target definition.

**Required implementation contract**

- Inputs for target definition must be explicitly typed and validated.
- Outputs for target definition must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for target definition must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of target definition understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves target definition works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Outs

- Define outs in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for outs.
- Expose outs visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for outs.

**Required implementation contract**

- Inputs for outs must be explicitly typed and validated.
- Outputs for outs must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for outs must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of outs understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves outs works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Pitch Count

- Define pitch count in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for pitch count.
- Expose pitch count visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for pitch count.

**Required implementation contract**

- Inputs for pitch count must be explicitly typed and validated.
- Outputs for pitch count must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for pitch count must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of pitch count understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves pitch count works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## K Rates

- Define K rates in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for K rates.
- Expose K rates visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for K rates.

**Required implementation contract**

- Inputs for K rates must be explicitly typed and validated.
- Outputs for K rates must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for K rates must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of K rates understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves K rates works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Opponent

- Define opponent in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for opponent.
- Expose opponent visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for opponent.

**Required implementation contract**

- Inputs for opponent must be explicitly typed and validated.
- Outputs for opponent must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for opponent must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of opponent understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves opponent works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Lineup

- Define lineup in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for lineup.
- Expose lineup visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for lineup.

**Required implementation contract**

- Inputs for lineup must be explicitly typed and validated.
- Outputs for lineup must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for lineup must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of lineup understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves lineup works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Handedness

- Define handedness in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for handedness.
- Expose handedness visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for handedness.

**Required implementation contract**

- Inputs for handedness must be explicitly typed and validated.
- Outputs for handedness must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for handedness must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of handedness understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves handedness works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Park

- Define park in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for park.
- Expose park visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for park.

**Required implementation contract**

- Inputs for park must be explicitly typed and validated.
- Outputs for park must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for park must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of park understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves park works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Weather

- Define weather in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for weather.
- Expose weather visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for weather.

**Required implementation contract**

- Inputs for weather must be explicitly typed and validated.
- Outputs for weather must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for weather must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of weather understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves weather works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Umpire

- Define umpire in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for umpire.
- Expose umpire visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for umpire.

**Required implementation contract**

- Inputs for umpire must be explicitly typed and validated.
- Outputs for umpire must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for umpire must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of umpire understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves umpire works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Rest

- Define rest in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for rest.
- Expose rest visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for rest.

**Required implementation contract**

- Inputs for rest must be explicitly typed and validated.
- Outputs for rest must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for rest must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of rest understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves rest works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Injury

- Define injury in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for injury.
- Expose injury visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for injury.

**Required implementation contract**

- Inputs for injury must be explicitly typed and validated.
- Outputs for injury must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for injury must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of injury understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves injury works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Feature Engineering Specification

All features belong to a registry with name, definition, grain, source, timestamp rule, missing-data behavior, code owner, version, and validation tests. Recent-form features must avoid arbitrary windows as the only view; use multiple horizons and shrink noisy samples toward stable baselines. Market-derived features are contextual inputs and must not create circular evaluation.

## Baseline Features

- Season and multi-year priors
- Recent weighted form
- Expected workload
- Opponent strikeout environment

**Required implementation contract**

- Inputs for baseline features must be explicitly typed and validated.
- Outputs for baseline features must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for baseline features must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of baseline features understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves baseline features works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Recent Form

- Define recent form in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for recent form.
- Expose recent form visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for recent form.

**Required implementation contract**

- Inputs for recent form must be explicitly typed and validated.
- Outputs for recent form must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for recent form must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of recent form understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves recent form works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Workload

- Define workload in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for workload.
- Expose workload visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for workload.

**Required implementation contract**

- Inputs for workload must be explicitly typed and validated.
- Outputs for workload must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for workload must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of workload understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves workload works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Matchup

- Define matchup in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for matchup.
- Expose matchup visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for matchup.

**Required implementation contract**

- Inputs for matchup must be explicitly typed and validated.
- Outputs for matchup must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for matchup must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of matchup understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves matchup works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Context

- Define context in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for context.
- Expose context visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for context.

**Required implementation contract**

- Inputs for context must be explicitly typed and validated.
- Outputs for context must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for context must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of context understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves context works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Market

- Define market in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for market.
- Expose market visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for market.

**Required implementation contract**

- Inputs for market must be explicitly typed and validated.
- Outputs for market must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for market must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of market understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves market works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Interaction Terms

- Define interaction terms in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for interaction terms.
- Expose interaction terms visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for interaction terms.

**Required implementation contract**

- Inputs for interaction terms must be explicitly typed and validated.
- Outputs for interaction terms must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for interaction terms must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of interaction terms understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves interaction terms works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Missingness

- Define missingness in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for missingness.
- Expose missingness visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for missingness.

**Required implementation contract**

- Inputs for missingness must be explicitly typed and validated.
- Outputs for missingness must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for missingness must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of missingness understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves missingness works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Feature Registry

- Define feature registry in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for feature registry.
- Expose feature registry visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for feature registry.

**Required implementation contract**

- Inputs for feature registry must be explicitly typed and validated.
- Outputs for feature registry must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for feature registry must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of feature registry understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves feature registry works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Modeling and Calibration

The first production benchmark should be simple enough to beat and explain. Candidate models compete through walk-forward evaluation, calibration, stability, and live operational performance—not only headline accuracy. The output should be a distribution or probability around each line, not merely a point estimate. Model disagreement is valuable information and can trigger No Play.

## Baselines

- Define baselines in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for baselines.
- Expose baselines visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for baselines.

**Required implementation contract**

- Inputs for baselines must be explicitly typed and validated.
- Outputs for baselines must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for baselines must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of baselines understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves baselines works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Candidate Models

- Define candidate models in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for candidate models.
- Expose candidate models visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for candidate models.

**Required implementation contract**

- Inputs for candidate models must be explicitly typed and validated.
- Outputs for candidate models must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for candidate models must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of candidate models understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves candidate models works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Ensembles

- Define ensembles in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for ensembles.
- Expose ensembles visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for ensembles.

**Required implementation contract**

- Inputs for ensembles must be explicitly typed and validated.
- Outputs for ensembles must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for ensembles must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of ensembles understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves ensembles works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Uncertainty

- Prediction intervals
- Model disagreement
- Role/lineup uncertainty
- Data-quality uncertainty

**Required implementation contract**

- Inputs for uncertainty must be explicitly typed and validated.
- Outputs for uncertainty must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for uncertainty must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of uncertainty understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves uncertainty works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Calibration

- Define calibration in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for calibration.
- Expose calibration visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for calibration.

**Required implementation contract**

- Inputs for calibration must be explicitly typed and validated.
- Outputs for calibration must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for calibration must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of calibration understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves calibration works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Segment Analysis

- Define segment analysis in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for segment analysis.
- Expose segment analysis visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for segment analysis.

**Required implementation contract**

- Inputs for segment analysis must be explicitly typed and validated.
- Outputs for segment analysis must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for segment analysis must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of segment analysis understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves segment analysis works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Explainability

- Define explainability in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for explainability.
- Expose explainability visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for explainability.

**Required implementation contract**

- Inputs for explainability must be explicitly typed and validated.
- Outputs for explainability must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for explainability must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of explainability understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves explainability works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Decision and No-Play Policy

A projection is not automatically a recommendation. The decision layer checks edge, calibration, uncertainty, model agreement, data quality, role stability, line age, and late-breaking context. Every rejection receives machine-readable reason codes. Thresholds are configuration with version history, not hidden magic numbers scattered through code.

## Edge

- Compare calibrated probability to break-even requirement
- Use conservative margin
- Record exact threshold version

**Required implementation contract**

- Inputs for edge must be explicitly typed and validated.
- Outputs for edge must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for edge must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of edge understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves edge works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Thresholds

- Define thresholds in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for thresholds.
- Expose thresholds visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for thresholds.

**Required implementation contract**

- Inputs for thresholds must be explicitly typed and validated.
- Outputs for thresholds must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for thresholds must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of thresholds understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves thresholds works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Uncertainty

- Prediction intervals
- Model disagreement
- Role/lineup uncertainty
- Data-quality uncertainty

**Required implementation contract**

- Inputs for uncertainty must be explicitly typed and validated.
- Outputs for uncertainty must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for uncertainty must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of uncertainty understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves uncertainty works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Conflict Rules

- Define conflict rules in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for conflict rules.
- Expose conflict rules visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for conflict rules.

**Required implementation contract**

- Inputs for conflict rules must be explicitly typed and validated.
- Outputs for conflict rules must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for conflict rules must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of conflict rules understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves conflict rules works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Late Changes

- Define late changes in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for late changes.
- Expose late changes visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for late changes.

**Required implementation contract**

- Inputs for late changes must be explicitly typed and validated.
- Outputs for late changes must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for late changes must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of late changes understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves late changes works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Watchlist

- Define watchlist in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for watchlist.
- Expose watchlist visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for watchlist.

**Required implementation contract**

- Inputs for watchlist must be explicitly typed and validated.
- Outputs for watchlist must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for watchlist must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of watchlist understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves watchlist works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Reason Codes

- Define reason codes in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for reason codes.
- Expose reason codes visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for reason codes.

**Required implementation contract**

- Inputs for reason codes must be explicitly typed and validated.
- Outputs for reason codes must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for reason codes must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of reason codes understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves reason codes works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Backtesting and Leakage Prevention

Backtesting is valid only when it recreates historical information availability. Random train/test splits are insufficient for time-dependent sports data. Use walk-forward evaluation, frozen historical cutoffs, realistic publication timing, and selection rules identical to live production. Audit for future lineups, corrected stats, final weather, postgame data, current roster states, and vendor revisions.

## Time Machine

- Reconstruct a historical run at a specific clock time
- Use archived source observations
- Fail closed when history is incomplete

**Required implementation contract**

- Inputs for time machine must be explicitly typed and validated.
- Outputs for time machine must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for time machine must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of time machine understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves time machine works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Walk-Forward

- Define walk-forward in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for walk-forward.
- Expose walk-forward visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for walk-forward.

**Required implementation contract**

- Inputs for walk-forward must be explicitly typed and validated.
- Outputs for walk-forward must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for walk-forward must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of walk-forward understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves walk-forward works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Cutoffs

- Define cutoffs in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for cutoffs.
- Expose cutoffs visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for cutoffs.

**Required implementation contract**

- Inputs for cutoffs must be explicitly typed and validated.
- Outputs for cutoffs must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for cutoffs must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of cutoffs understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves cutoffs works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Revisions

- Define revisions in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for revisions.
- Expose revisions visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for revisions.

**Required implementation contract**

- Inputs for revisions must be explicitly typed and validated.
- Outputs for revisions must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for revisions must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of revisions understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves revisions works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Survivorship

- Define survivorship in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for survivorship.
- Expose survivorship visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for survivorship.

**Required implementation contract**

- Inputs for survivorship must be explicitly typed and validated.
- Outputs for survivorship must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for survivorship must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of survivorship understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves survivorship works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Selection Bias

- Define selection bias in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for selection bias.
- Expose selection bias visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for selection bias.

**Required implementation contract**

- Inputs for selection bias must be explicitly typed and validated.
- Outputs for selection bias must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for selection bias must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of selection bias understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves selection bias works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Metrics

- Define metrics in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for metrics.
- Expose metrics visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for metrics.

**Required implementation contract**

- Inputs for metrics must be explicitly typed and validated.
- Outputs for metrics must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for metrics must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of metrics understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves metrics works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Audit Tests

- Define audit tests in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for audit tests.
- Expose audit tests visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for audit tests.

**Required implementation contract**

- Inputs for audit tests must be explicitly typed and validated.
- Outputs for audit tests must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for audit tests must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of audit tests understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves audit tests works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Live Projection Pipeline

Each slate run has a unique identifier, cutoff, configuration version, model version, source-status snapshot, and lifecycle state. Jobs are idempotent and safe to retry. A late line or lineup change creates an affected-item re-evaluation rather than silently replacing the original published record. Publication should default to human approval until reliability is proven.

## Run Orchestration

- Define run orchestration in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for run orchestration.
- Expose run orchestration visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for run orchestration.

**Required implementation contract**

- Inputs for run orchestration must be explicitly typed and validated.
- Outputs for run orchestration must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for run orchestration must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of run orchestration understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves run orchestration works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Idempotency

- Define idempotency in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for idempotency.
- Expose idempotency visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for idempotency.

**Required implementation contract**

- Inputs for idempotency must be explicitly typed and validated.
- Outputs for idempotency must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for idempotency must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of idempotency understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves idempotency works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Retries

- Define retries in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for retries.
- Expose retries visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for retries.

**Required implementation contract**

- Inputs for retries must be explicitly typed and validated.
- Outputs for retries must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for retries must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of retries understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves retries works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Partial Failures

- Define partial failures in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for partial failures.
- Expose partial failures visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for partial failures.

**Required implementation contract**

- Inputs for partial failures must be explicitly typed and validated.
- Outputs for partial failures must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for partial failures must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of partial failures understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves partial failures works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Approval

- Define approval in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for approval.
- Expose approval visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for approval.

**Required implementation contract**

- Inputs for approval must be explicitly typed and validated.
- Outputs for approval must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for approval must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of approval understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves approval works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Publication

- Define publication in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for publication.
- Expose publication visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for publication.

**Required implementation contract**

- Inputs for publication must be explicitly typed and validated.
- Outputs for publication must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for publication must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of publication understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves publication works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Reprojection

- Define reprojection in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for reprojection.
- Expose reprojection visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for reprojection.

**Required implementation contract**

- Inputs for reprojection must be explicitly typed and validated.
- Outputs for reprojection must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for reprojection must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of reprojection understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves reprojection works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Prediction Ledger and Grading

The ledger stores every evaluated prop with original line, direction or No Play, projection, uncertainty, reason codes, timestamp, model and feature versions, publication status, and final grade. Official stat corrections create a grading revision history. Public summaries must reconcile exactly to the underlying ledger.

## Immutable Record

- Define immutable record in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for immutable record.
- Expose immutable record visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for immutable record.

**Required implementation contract**

- Inputs for immutable record must be explicitly typed and validated.
- Outputs for immutable record must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for immutable record must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of immutable record understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves immutable record works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Official Results

- Define official results in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for official results.
- Expose official results visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for official results.

**Required implementation contract**

- Inputs for official results must be explicitly typed and validated.
- Outputs for official results must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for official results must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of official results understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves official results works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Pushes

- Define pushes in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for pushes.
- Expose pushes visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for pushes.

**Required implementation contract**

- Inputs for pushes must be explicitly typed and validated.
- Outputs for pushes must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for pushes must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of pushes understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves pushes works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Voids

- Define voids in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for voids.
- Expose voids visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for voids.

**Required implementation contract**

- Inputs for voids must be explicitly typed and validated.
- Outputs for voids must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for voids must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of voids understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves voids works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Stat Corrections

- Define stat corrections in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for stat corrections.
- Expose stat corrections visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for stat corrections.

**Required implementation contract**

- Inputs for stat corrections must be explicitly typed and validated.
- Outputs for stat corrections must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for stat corrections must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of stat corrections understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves stat corrections works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Public Record

- Define public record in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for public record.
- Expose public record visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for public record.

**Required implementation contract**

- Inputs for public record must be explicitly typed and validated.
- Outputs for public record must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for public record must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of public record understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves public record works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Reconciliation

- Define reconciliation in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for reconciliation.
- Expose reconciliation visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for reconciliation.

**Required implementation contract**

- Inputs for reconciliation must be explicitly typed and validated.
- Outputs for reconciliation must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for reconciliation must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of reconciliation understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves reconciliation works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Learning and Experimentation

Improvement occurs through measured experiments. Diagnose misses by category before changing the model. New models run in shadow mode against the production champion. Promotion requires predefined evidence, segment checks, calibration, operational reliability, and rollback readiness. The system must never train directly on its own public labels without preserving the true outcome target.

## Error Attribution

- Define error attribution in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for error attribution.
- Expose error attribution visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for error attribution.

**Required implementation contract**

- Inputs for error attribution must be explicitly typed and validated.
- Outputs for error attribution must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for error attribution must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of error attribution understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves error attribution works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Drift

- Define drift in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for drift.
- Expose drift visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for drift.

**Required implementation contract**

- Inputs for drift must be explicitly typed and validated.
- Outputs for drift must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for drift must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of drift understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves drift works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Retraining

- Define retraining in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for retraining.
- Expose retraining visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for retraining.

**Required implementation contract**

- Inputs for retraining must be explicitly typed and validated.
- Outputs for retraining must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for retraining must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of retraining understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves retraining works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Shadow Mode

- Define shadow mode in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for shadow mode.
- Expose shadow mode visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for shadow mode.

**Required implementation contract**

- Inputs for shadow mode must be explicitly typed and validated.
- Outputs for shadow mode must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for shadow mode must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of shadow mode understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves shadow mode works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Champion Challenger

- Define champion challenger in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for champion challenger.
- Expose champion challenger visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for champion challenger.

**Required implementation contract**

- Inputs for champion challenger must be explicitly typed and validated.
- Outputs for champion challenger must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for champion challenger must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of champion challenger understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves champion challenger works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Promotion

- Define promotion in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for promotion.
- Expose promotion visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for promotion.

**Required implementation contract**

- Inputs for promotion must be explicitly typed and validated.
- Outputs for promotion must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for promotion must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of promotion understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves promotion works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Rollback

- Define rollback in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for rollback.
- Expose rollback visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for rollback.

**Required implementation contract**

- Inputs for rollback must be explicitly typed and validated.
- Outputs for rollback must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for rollback must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of rollback understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves rollback works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# API and Backend Specification

APIs expose structured resources for slates, games, players, props, projections, decisions, ledger entries, results, model versions, source health, and admin runs. Use consistent identifiers, typed validation, pagination, explicit timestamps, and stable error envelopes. Public read endpoints and privileged admin mutation endpoints must be separated.

## Services

- Define services in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for services.
- Expose services visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for services.

**Required implementation contract**

- Inputs for services must be explicitly typed and validated.
- Outputs for services must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for services must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of services understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves services works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Endpoints

- Define endpoints in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for endpoints.
- Expose endpoints visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for endpoints.

**Required implementation contract**

- Inputs for endpoints must be explicitly typed and validated.
- Outputs for endpoints must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for endpoints must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of endpoints understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves endpoints works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Auth

- Define auth in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for auth.
- Expose auth visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for auth.

**Required implementation contract**

- Inputs for auth must be explicitly typed and validated.
- Outputs for auth must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for auth must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of auth understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves auth works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Permissions

- Define permissions in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for permissions.
- Expose permissions visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for permissions.

**Required implementation contract**

- Inputs for permissions must be explicitly typed and validated.
- Outputs for permissions must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for permissions must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of permissions understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves permissions works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Schemas

- Define schemas in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for schemas.
- Expose schemas visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for schemas.

**Required implementation contract**

- Inputs for schemas must be explicitly typed and validated.
- Outputs for schemas must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for schemas must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of schemas understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves schemas works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Pagination

- Define pagination in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for pagination.
- Expose pagination visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for pagination.

**Required implementation contract**

- Inputs for pagination must be explicitly typed and validated.
- Outputs for pagination must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for pagination must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of pagination understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves pagination works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Errors

- Define errors in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for errors.
- Expose errors visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for errors.

**Required implementation contract**

- Inputs for errors must be explicitly typed and validated.
- Outputs for errors must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for errors must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of errors understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves errors works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Versioning

- Define versioning in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for versioning.
- Expose versioning visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for versioning.

**Required implementation contract**

- Inputs for versioning must be explicitly typed and validated.
- Outputs for versioning must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for versioning must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of versioning understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves versioning works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Rate Limits

- Define rate limits in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for rate limits.
- Expose rate limits visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for rate limits.

**Required implementation contract**

- Inputs for rate limits must be explicitly typed and validated.
- Outputs for rate limits must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for rate limits must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of rate limits understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves rate limits works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Database Design

The database must preserve identity and history. Core entities include players, teams, games, markets, line observations, source records, snapshots, features, model artifacts, projection runs, projections, decisions, publications, results, grades, experiments, and audit events. Avoid mutable “current value only” tables for data that affects historical reconstruction.

## Entities

- Define entities in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for entities.
- Expose entities visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for entities.

**Required implementation contract**

- Inputs for entities must be explicitly typed and validated.
- Outputs for entities must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for entities must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of entities understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves entities works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Keys

- Define keys in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for keys.
- Expose keys visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for keys.

**Required implementation contract**

- Inputs for keys must be explicitly typed and validated.
- Outputs for keys must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for keys must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of keys understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves keys works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Indexes

- Define indexes in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for indexes.
- Expose indexes visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for indexes.

**Required implementation contract**

- Inputs for indexes must be explicitly typed and validated.
- Outputs for indexes must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for indexes must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of indexes understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves indexes works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Partitioning

- Define partitioning in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for partitioning.
- Expose partitioning visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for partitioning.

**Required implementation contract**

- Inputs for partitioning must be explicitly typed and validated.
- Outputs for partitioning must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for partitioning must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of partitioning understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves partitioning works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Retention

- Define retention in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for retention.
- Expose retention visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for retention.

**Required implementation contract**

- Inputs for retention must be explicitly typed and validated.
- Outputs for retention must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for retention must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of retention understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves retention works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Audit

- Define audit in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for audit.
- Expose audit visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for audit.

**Required implementation contract**

- Inputs for audit must be explicitly typed and validated.
- Outputs for audit must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for audit must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of audit understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves audit works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Migrations

- Define migrations in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for migrations.
- Expose migrations visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for migrations.

**Required implementation contract**

- Inputs for migrations must be explicitly typed and validated.
- Outputs for migrations must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for migrations must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of migrations understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves migrations works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Examples

- Define examples in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for examples.
- Expose examples visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for examples.

**Required implementation contract**

- Inputs for examples must be explicitly typed and validated.
- Outputs for examples must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for examples must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of examples understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves examples works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Frontend Design System

The visual language is premium, dark, clean, and restrained. Near-black surfaces, white primary text, violet accents, and subtle constellation/circuit texture support the Cassandra identity. The UI must communicate status without hype: Qualified, Watchlist, No Play, Pending, Graded, Void, and Data Warning. Tables remain readable on mobile through prioritized columns and expandable details.

## Brand

- Define brand in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for brand.
- Expose brand visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for brand.

**Required implementation contract**

- Inputs for brand must be explicitly typed and validated.
- Outputs for brand must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for brand must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of brand understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves brand works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Tokens

- Define tokens in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for tokens.
- Expose tokens visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for tokens.

**Required implementation contract**

- Inputs for tokens must be explicitly typed and validated.
- Outputs for tokens must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for tokens must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of tokens understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves tokens works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Components

- Define components in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for components.
- Expose components visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for components.

**Required implementation contract**

- Inputs for components must be explicitly typed and validated.
- Outputs for components must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for components must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of components understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves components works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Tables

- Define tables in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for tables.
- Expose tables visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for tables.

**Required implementation contract**

- Inputs for tables must be explicitly typed and validated.
- Outputs for tables must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for tables must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of tables understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves tables works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Badges

- Define badges in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for badges.
- Expose badges visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for badges.

**Required implementation contract**

- Inputs for badges must be explicitly typed and validated.
- Outputs for badges must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for badges must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of badges understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves badges works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## States

- Define states in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for states.
- Expose states visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for states.

**Required implementation contract**

- Inputs for states must be explicitly typed and validated.
- Outputs for states must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for states must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of states understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves states works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Responsive

- Define responsive in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for responsive.
- Expose responsive visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for responsive.

**Required implementation contract**

- Inputs for responsive must be explicitly typed and validated.
- Outputs for responsive must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for responsive must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of responsive understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves responsive works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Accessibility

- Define accessibility in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for accessibility.
- Expose accessibility visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for accessibility.

**Required implementation contract**

- Inputs for accessibility must be explicitly typed and validated.
- Outputs for accessibility must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for accessibility must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of accessibility understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves accessibility works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Copy Rules

- Define copy rules in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for copy rules.
- Expose copy rules visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for copy rules.

**Required implementation contract**

- Inputs for copy rules must be explicitly typed and validated.
- Outputs for copy rules must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for copy rules must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of copy rules understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves copy rules works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Admin Control Room

The admin console is an operating surface, not merely CRUD screens. It must show whether the slate is safe to publish. Operators need source health, staleness, unmatched entities, changed lines, missing lineups, projection failures, blocked props, model status, approval controls, grading reconciliation, and incident links.

## Health

- Define health in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for health.
- Expose health visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for health.

**Required implementation contract**

- Inputs for health must be explicitly typed and validated.
- Outputs for health must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for health must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of health understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves health works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Runs

- Define runs in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for runs.
- Expose runs visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for runs.

**Required implementation contract**

- Inputs for runs must be explicitly typed and validated.
- Outputs for runs must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for runs must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of runs understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves runs works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Warnings

- Define warnings in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for warnings.
- Expose warnings visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for warnings.

**Required implementation contract**

- Inputs for warnings must be explicitly typed and validated.
- Outputs for warnings must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for warnings must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of warnings understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves warnings works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Approvals

- Define approvals in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for approvals.
- Expose approvals visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for approvals.

**Required implementation contract**

- Inputs for approvals must be explicitly typed and validated.
- Outputs for approvals must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for approvals must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of approvals understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves approvals works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Publishing

- Define publishing in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for publishing.
- Expose publishing visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for publishing.

**Required implementation contract**

- Inputs for publishing must be explicitly typed and validated.
- Outputs for publishing must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for publishing must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of publishing understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves publishing works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Grading

- Define grading in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for grading.
- Expose grading visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for grading.

**Required implementation contract**

- Inputs for grading must be explicitly typed and validated.
- Outputs for grading must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for grading must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of grading understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves grading works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Diagnostics

- Define diagnostics in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for diagnostics.
- Expose diagnostics visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for diagnostics.

**Required implementation contract**

- Inputs for diagnostics must be explicitly typed and validated.
- Outputs for diagnostics must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for diagnostics must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of diagnostics understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves diagnostics works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Model Registry

- Define model registry in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for model registry.
- Expose model registry visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for model registry.

**Required implementation contract**

- Inputs for model registry must be explicitly typed and validated.
- Outputs for model registry must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for model registry must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of model registry understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves model registry works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Security, Privacy and Compliance

Use least privilege, managed secrets, protected admin access, dependency scanning, audit logging, and backups. Do not expose provider credentials or private model artifacts. Public language must include responsible-gambling framing and avoid guaranteed-return claims. Data collection methods must be reviewed against source terms and applicable law before production.

## Secrets

- Define secrets in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for secrets.
- Expose secrets visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for secrets.

**Required implementation contract**

- Inputs for secrets must be explicitly typed and validated.
- Outputs for secrets must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for secrets must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of secrets understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves secrets works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Access

- Define access in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for access.
- Expose access visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for access.

**Required implementation contract**

- Inputs for access must be explicitly typed and validated.
- Outputs for access must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for access must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of access understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves access works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Audit

- Define audit in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for audit.
- Expose audit visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for audit.

**Required implementation contract**

- Inputs for audit must be explicitly typed and validated.
- Outputs for audit must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for audit must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of audit understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves audit works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Dependency Security

- Define dependency security in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for dependency security.
- Expose dependency security visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for dependency security.

**Required implementation contract**

- Inputs for dependency security must be explicitly typed and validated.
- Outputs for dependency security must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for dependency security must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of dependency security understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves dependency security works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Terms

- Define terms in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for terms.
- Expose terms visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for terms.

**Required implementation contract**

- Inputs for terms must be explicitly typed and validated.
- Outputs for terms must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for terms must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of terms understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves terms works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Responsible Gambling

- Define responsible gambling in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for responsible gambling.
- Expose responsible gambling visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for responsible gambling.

**Required implementation contract**

- Inputs for responsible gambling must be explicitly typed and validated.
- Outputs for responsible gambling must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for responsible gambling must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of responsible gambling understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves responsible gambling works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Disclaimers

- Define disclaimers in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for disclaimers.
- Expose disclaimers visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for disclaimers.

**Required implementation contract**

- Inputs for disclaimers must be explicitly typed and validated.
- Outputs for disclaimers must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for disclaimers must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of disclaimers understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves disclaimers works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Testing and Quality Gates

A feature is complete only when tests demonstrate behavior. Required layers include unit tests for calculations, contract tests for providers, data-quality tests, snapshot/as-of tests, model reproducibility tests, leakage tests, API integration tests, browser flows, and release smoke tests. Golden fixtures should cover pushes, postponed games, pitcher changes, doubleheaders, stat corrections, and line movement.

## Unit

- Pure calculations and reason-code rules
- No network dependence
- Boundary and null cases

**Required implementation contract**

- Inputs for unit must be explicitly typed and validated.
- Outputs for unit must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for unit must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of unit understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves unit works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Integration

- Define integration in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for integration.
- Expose integration visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for integration.

**Required implementation contract**

- Inputs for integration must be explicitly typed and validated.
- Outputs for integration must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for integration must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of integration understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves integration works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Contract

- Define contract in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for contract.
- Expose contract visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for contract.

**Required implementation contract**

- Inputs for contract must be explicitly typed and validated.
- Outputs for contract must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for contract must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of contract understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves contract works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Data

- Define data in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for data.
- Expose data visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for data.

**Required implementation contract**

- Inputs for data must be explicitly typed and validated.
- Outputs for data must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for data must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of data understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves data works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Model

- Define model in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for model.
- Expose model visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for model.

**Required implementation contract**

- Inputs for model must be explicitly typed and validated.
- Outputs for model must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for model must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of model understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves model works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Backtest

- Define backtest in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for backtest.
- Expose backtest visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for backtest.

**Required implementation contract**

- Inputs for backtest must be explicitly typed and validated.
- Outputs for backtest must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for backtest must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of backtest understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves backtest works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Ui

- Define UI in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for UI.
- Expose UI visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for UI.

**Required implementation contract**

- Inputs for UI must be explicitly typed and validated.
- Outputs for UI must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for UI must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of UI understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves UI works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## End-To-End

- Define end-to-end in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for end-to-end.
- Expose end-to-end visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for end-to-end.

**Required implementation contract**

- Inputs for end-to-end must be explicitly typed and validated.
- Outputs for end-to-end must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for end-to-end must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of end-to-end understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves end-to-end works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Release

- Define release in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for release.
- Expose release visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for release.

**Required implementation contract**

- Inputs for release must be explicitly typed and validated.
- Outputs for release must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for release must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of release understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves release works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Observability and Incident Response

Every run emits structured logs and metrics tied to run, game, player, prop, source, and model identifiers. Dashboards track source freshness, job duration, failures, projection counts, No Play rates, publication counts, grading completeness, calibration, and drift. Incidents use severity levels, owner assignment, containment, recovery, and postmortem actions.

## Logs

- Define logs in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for logs.
- Expose logs visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for logs.

**Required implementation contract**

- Inputs for logs must be explicitly typed and validated.
- Outputs for logs must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for logs must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of logs understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves logs works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Metrics

- Define metrics in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for metrics.
- Expose metrics visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for metrics.

**Required implementation contract**

- Inputs for metrics must be explicitly typed and validated.
- Outputs for metrics must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for metrics must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of metrics understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves metrics works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Alerts

- Define alerts in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for alerts.
- Expose alerts visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for alerts.

**Required implementation contract**

- Inputs for alerts must be explicitly typed and validated.
- Outputs for alerts must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for alerts must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of alerts understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves alerts works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Dashboards

- Define dashboards in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for dashboards.
- Expose dashboards visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for dashboards.

**Required implementation contract**

- Inputs for dashboards must be explicitly typed and validated.
- Outputs for dashboards must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for dashboards must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of dashboards understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves dashboards works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Runbooks

- Define runbooks in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for runbooks.
- Expose runbooks visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for runbooks.

**Required implementation contract**

- Inputs for runbooks must be explicitly typed and validated.
- Outputs for runbooks must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for runbooks must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of runbooks understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves runbooks works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Severity

- Define severity in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for severity.
- Expose severity visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for severity.

**Required implementation contract**

- Inputs for severity must be explicitly typed and validated.
- Outputs for severity must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for severity must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of severity understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves severity works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Postmortems

- Define postmortems in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for postmortems.
- Expose postmortems visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for postmortems.

**Required implementation contract**

- Inputs for postmortems must be explicitly typed and validated.
- Outputs for postmortems must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for postmortems must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of postmortems understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves postmortems works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Deployment and Environments

Maintain local, preview, staging, and production environments with isolated data and secrets. Database migrations are reviewed, reversible where possible, and tested on staging. Scheduled jobs and workers must not depend on a developer laptop. Replit may accelerate the MVP, but architecture should avoid irreversible platform lock-in.

## Local

- Define local in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for local.
- Expose local visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for local.

**Required implementation contract**

- Inputs for local must be explicitly typed and validated.
- Outputs for local must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for local must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of local understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves local works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Preview

- Define preview in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for preview.
- Expose preview visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for preview.

**Required implementation contract**

- Inputs for preview must be explicitly typed and validated.
- Outputs for preview must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for preview must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of preview understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves preview works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Staging

- Define staging in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for staging.
- Expose staging visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for staging.

**Required implementation contract**

- Inputs for staging must be explicitly typed and validated.
- Outputs for staging must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for staging must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of staging understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves staging works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Production

- Define production in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for production.
- Expose production visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for production.

**Required implementation contract**

- Inputs for production must be explicitly typed and validated.
- Outputs for production must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for production must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of production understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves production works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Ci/Cd

- Define CI/CD in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for CI/CD.
- Expose CI/CD visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for CI/CD.

**Required implementation contract**

- Inputs for CI/CD must be explicitly typed and validated.
- Outputs for CI/CD must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for CI/CD must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of CI/CD understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves CI/CD works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Migrations

- Define migrations in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for migrations.
- Expose migrations visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for migrations.

**Required implementation contract**

- Inputs for migrations must be explicitly typed and validated.
- Outputs for migrations must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for migrations must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of migrations understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves migrations works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Backups

- Define backups in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for backups.
- Expose backups visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for backups.

**Required implementation contract**

- Inputs for backups must be explicitly typed and validated.
- Outputs for backups must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for backups must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of backups understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves backups works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Cost Controls

- Define cost controls in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for cost controls.
- Expose cost controls visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for cost controls.

**Required implementation contract**

- Inputs for cost controls must be explicitly typed and validated.
- Outputs for cost controls must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for cost controls must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of cost controls understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves cost controls works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Roadmap and Work Breakdown

The roadmap follows a vertical slice: foundation, strikeout data, strikeout model, decision and ledger, shadow/live proof, public MVP, and only then additional markets. Each phase has a demoable visual output so Tyler can see and question the machine before more code is added.

## Foundation

- Repository standards
- Environment configuration
- Core IDs and schemas
- Audit/event framework

**Required implementation contract**

- Inputs for foundation must be explicitly typed and validated.
- Outputs for foundation must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for foundation must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of foundation understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves foundation works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Strikeouts

- Define strikeouts in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for strikeouts.
- Expose strikeouts visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for strikeouts.

**Required implementation contract**

- Inputs for strikeouts must be explicitly typed and validated.
- Outputs for strikeouts must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for strikeouts must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of strikeouts understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves strikeouts works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Ledger

- Define ledger in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for ledger.
- Expose ledger visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for ledger.

**Required implementation contract**

- Inputs for ledger must be explicitly typed and validated.
- Outputs for ledger must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for ledger must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of ledger understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves ledger works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Proof

- Define proof in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for proof.
- Expose proof visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for proof.

**Required implementation contract**

- Inputs for proof must be explicitly typed and validated.
- Outputs for proof must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for proof must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of proof understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves proof works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Public Mvp

- Define public MVP in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for public MVP.
- Expose public MVP visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for public MVP.

**Required implementation contract**

- Inputs for public MVP must be explicitly typed and validated.
- Outputs for public MVP must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for public MVP must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of public MVP understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves public MVP works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Growth

- Define growth in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for growth.
- Expose growth visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for growth.

**Required implementation contract**

- Inputs for growth must be explicitly typed and validated.
- Outputs for growth must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for growth must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of growth understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves growth works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## New Markets

- Define new markets in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for new markets.
- Expose new markets visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for new markets.

**Required implementation contract**

- Inputs for new markets must be explicitly typed and validated.
- Outputs for new markets must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for new markets must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of new markets understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves new markets works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Claude Code Operating Instructions

Claude Code is the primary builder and must work from tasks with scope, files, requirements, tests, and acceptance criteria. It should inspect the repository before proposing changes, preserve existing working behavior, avoid sweeping rewrites without evidence, and produce a concise completion report with files changed, tests run, risks, and next recommended task.

## Read Order

- Start-here file
- Confirmed decisions
- Architecture
- Current phase spec
- Task acceptance criteria

**Required implementation contract**

- Inputs for read order must be explicitly typed and validated.
- Outputs for read order must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for read order must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of read order understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves read order works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Task Protocol

- Define task protocol in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for task protocol.
- Expose task protocol visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for task protocol.

**Required implementation contract**

- Inputs for task protocol must be explicitly typed and validated.
- Outputs for task protocol must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for task protocol must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of task protocol understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves task protocol works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Branching

- Define branching in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for branching.
- Expose branching visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for branching.

**Required implementation contract**

- Inputs for branching must be explicitly typed and validated.
- Outputs for branching must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for branching must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of branching understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves branching works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Definition Of Done

- Define definition of done in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for definition of done.
- Expose definition of done visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for definition of done.

**Required implementation contract**

- Inputs for definition of done must be explicitly typed and validated.
- Outputs for definition of done must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for definition of done must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of definition of done understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves definition of done works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Do-Not-Do List

- Define do-not-do list in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for do-not-do list.
- Expose do-not-do list visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for do-not-do list.

**Required implementation contract**

- Inputs for do-not-do list must be explicitly typed and validated.
- Outputs for do-not-do list must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for do-not-do list must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of do-not-do list understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves do-not-do list works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Handoff Format

- Define handoff format in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for handoff format.
- Expose handoff format visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for handoff format.

**Required implementation contract**

- Inputs for handoff format must be explicitly typed and validated.
- Outputs for handoff format must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for handoff format must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of handoff format understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves handoff format works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Appendices

Appendices provide the reusable contracts that stop future agents from improvising: glossary, status definitions, reason-code catalog, example JSON, database field dictionary, acceptance checklist, incident template, experiment template, model card, source card, and release checklist.

## Glossary

- Define glossary in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for glossary.
- Expose glossary visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for glossary.

**Required implementation contract**

- Inputs for glossary must be explicitly typed and validated.
- Outputs for glossary must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for glossary must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of glossary understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves glossary works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Schemas

- Define schemas in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for schemas.
- Expose schemas visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for schemas.

**Required implementation contract**

- Inputs for schemas must be explicitly typed and validated.
- Outputs for schemas must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for schemas must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of schemas understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves schemas works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Reason Codes

- Define reason codes in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for reason codes.
- Expose reason codes visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for reason codes.

**Required implementation contract**

- Inputs for reason codes must be explicitly typed and validated.
- Outputs for reason codes must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for reason codes must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of reason codes understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves reason codes works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Acceptance Criteria

- Define acceptance criteria in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for acceptance criteria.
- Expose acceptance criteria visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for acceptance criteria.

**Required implementation contract**

- Inputs for acceptance criteria must be explicitly typed and validated.
- Outputs for acceptance criteria must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for acceptance criteria must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of acceptance criteria understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves acceptance criteria works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Checklists

- Define checklists in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for checklists.
- Expose checklists visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for checklists.

**Required implementation contract**

- Inputs for checklists must be explicitly typed and validated.
- Outputs for checklists must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for checklists must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of checklists understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves checklists works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Decision Templates

- Define decision templates in explicit, testable terms.
- Assign data owner, code owner, version and acceptance criteria for decision templates.
- Expose decision templates visually in the admin or documentation where appropriate.
- Add failure behavior, monitoring and rollback rules for decision templates.

**Required implementation contract**

- Inputs for decision templates must be explicitly typed and validated.
- Outputs for decision templates must include timestamps, provenance, and version identifiers where applicable.
- Failure behavior for decision templates must be visible and must not silently degrade prediction quality.
- Tests must cover normal, missing, stale, duplicated, and contradictory cases.
- The owner-facing UI or report must make the status of decision templates understandable without reading source code.

**Acceptance evidence**

- A repeatable demonstration or fixture proves decision templates works.
- Automated tests pass in CI.
- Documentation and diagrams match the implemented behavior.
- No unresolved high-severity data-integrity warning remains.

## Section completion checklist

- [ ] Product behavior approved
- [ ] Data contracts documented
- [ ] Tests implemented
- [ ] Visual workflow updated
- [ ] Monitoring added
- [ ] Security reviewed
- [ ] Decision ledger updated

# Appendix A — Core Status and Reason Codes

- `DATA_STALE` — blocks or qualifies publication and must include human-readable detail.
- `DATA_MISSING` — blocks or qualifies publication and must include human-readable detail.
- `DATA_CONFLICT` — blocks or qualifies publication and must include human-readable detail.
- `ENTITY_UNMATCHED` — blocks or qualifies publication and must include human-readable detail.
- `LINE_MOVED` — blocks or qualifies publication and must include human-readable detail.
- `LINE_SUSPENDED` — blocks or qualifies publication and must include human-readable detail.
- `LINEUP_UNCONFIRMED` — blocks or qualifies publication and must include human-readable detail.
- `STARTER_UNCONFIRMED` — blocks or qualifies publication and must include human-readable detail.
- `ROLE_UNSTABLE` — blocks or qualifies publication and must include human-readable detail.
- `PITCH_LIMIT_RISK` — blocks or qualifies publication and must include human-readable detail.
- `WEATHER_RISK` — blocks or qualifies publication and must include human-readable detail.
- `MODEL_UNHEALTHY` — blocks or qualifies publication and must include human-readable detail.
- `MODEL_DISAGREEMENT` — blocks or qualifies publication and must include human-readable detail.
- `UNCERTAINTY_HIGH` — blocks or qualifies publication and must include human-readable detail.
- `EDGE_BELOW_THRESHOLD` — blocks or qualifies publication and must include human-readable detail.
- `MARKET_CONTEXT_INCOMPLETE` — blocks or qualifies publication and must include human-readable detail.
- `LATE_BREAKING_CHANGE` — blocks or qualifies publication and must include human-readable detail.
- `MANUAL_HOLD` — blocks or qualifies publication and must include human-readable detail.

# Appendix B — Example Projection Record

```json
{
  "projection_id": "proj_2026_08_04_example",
  "run_id": "run_2026_08_04_1100",
  "as_of": "2026-08-04T11:00:00-04:00",
  "sport": "MLB",
  "market": "pitcher_strikeouts",
  "player_id": "player_example",
  "game_id": "game_example",
  "line": 5.5,
  "projection_mean": 6.1,
  "probability_over": 0.61,
  "probability_under": 0.39,
  "decision": "OVER",
  "decision_status": "QUALIFIED",
  "reason_codes": [
    "EDGE_CLEARS_THRESHOLD"
  ],
  "model_version": "k-model-0.1.0",
  "feature_set_version": "k-features-0.1.0",
  "source_snapshot_id": "snapshot_example",
  "published_at": null,
  "grade": null
}
```

# Appendix C — Definition of Done

- Requirement linked to a confirmed decision or approved proposal.
- Implementation reviewed at the correct architectural boundary.
- Tests added and passing.
- Point-in-time behavior verified.
- Error and stale-data behavior visible.
- Admin view updated.
- Documentation and diagram updated.
- No secrets or unsafe data collection introduced.
- Change summarized for Tyler in plain language with a visual demonstration.
