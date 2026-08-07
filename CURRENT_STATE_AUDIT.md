# Current State Audit

Updated at the end of the full vertical-slice MVP build. The repo started
completely empty (0 commits); every item below except the "Not real" and
"Provisional" sections is implemented, tested, and verified working
against real (not mocked) data during this build.

## What's real (implemented, tested, verified)

### Database

- Full Postgres schema (`engine/src/cassandra/db/models/`): identity
  (venues/teams/players/games), source registry + health, 9 `raw_*`
  immutable ingestion tables, snapshots (+ raw refs + data-quality
  findings), feature sets/values, the projection ledger, append-only
  grades, audit events, pipeline run/stage tracking.
- Three Alembic migrations, applying cleanly from an empty database
  (verified repeatedly this session, including a from-scratch rebuild
  immediately before this audit was written):
  1. `f4b13ecb5ad7` — initial schema + `REVOKE UPDATE, DELETE` on every
     immutable table.
  2. `d764bb3bb5c1` — corrects a gap found empirically during this build:
     the REVOKE-only design breaks for any table a foreign key
     *references* (Postgres requires `UPDATE` privilege for the
     `FOR KEY SHARE` row lock FK inserts need, even though the inserting
     role never intends to mutate the parent row). Grants `UPDATE` back
     and replaces real mutation-blocking with a `BEFORE UPDATE OR DELETE`
     trigger that unconditionally raises — still DB-enforced, not
     convention.
  3. `ee1a1af7126d` — closes a second gap found the same way: Postgres
     grants `TRUNCATE` to a table's owner by default, and `f4b13ecb5ad7`
     never revoked it. `TRUNCATE` doesn't fire row triggers, so REVOKE is
     the only available defense; confirmed it doesn't reopen the FK-lock
     problem.
- Immutability is enforced by Postgres itself for `raw_*`, `projections`,
  `grades`, `audit_events` — not just application convention.

### Ingestion

- 9 source adapters, all tested against real saved API responses (not
  synthetic fixtures): MLB schedule, probable pitchers, pitcher game
  logs, Open-Meteo weather, static park factors, a permanent umpire
  stub (`is_available=False` — see Provisional below), a manual/fixture
  lines importer, a real licensed-odds-vendor lines adapter, and MLB
  final box scores.
- **Fixed a severe, launch-blocking bug** in `adapters/probable_pitchers_mlb.py`
  found by an external repo audit (independently verified against the
  real code and a real MLB schedule fixture before acting on it, not
  trusted blindly): `is_confirmed` was computed as
  `status.abstractGameState != "Preview"` — every game is "Preview"
  until it starts, so this was `False` for essentially every normal
  pregame probable-pitcher listing. `decision/engine.py`'s
  `QUALITY_RISK_CODES` includes `STARTER_UNCONFIRMED`, which
  unconditionally downgrades `decision_status` to `UNCERTAIN`/`NO_PLAY`
  regardless of edge — so this silently forced **every pregame
  projection to NO_PLAY, no matter how strong the model's edge was**,
  since this platform went live. Real MLB schedule payloads have no
  separate pregame confirmation signal beyond the named probable-pitcher
  listing itself (verified against a real captured fixture) — a listed
  probable IS the correct, complete pregame signal, and the code was
  checking an unrelated field. Fixed to set `is_confirmed=True`
  whenever this adapter writes a row (which already only happens for a
  named, numeric-id probable pitcher); a genuine late scratch/swap is
  still caught correctly by the existing point-in-time versioned-
  ingestion mechanism, which never needed a separate confirmation flag
  to work.
- `adapters/lines_odds_api.py`: a real, licensed odds vendor (The Odds
  API — regulated US sportsbooks: FanDuel, Bovada, etc.), used for
  pitcher-strikeout lines when `ODDS_API_KEY` is configured
  (`orchestration/run_slate.py`'s `_ingest_lines()` falls back to
  `lines_manual` otherwise). Resolves the vendor's free-text player names
  against that slate's already-ingested confirmed starters (real
  `player_mlb_id`s via the `players` table) — a name with no match is
  silently skipped, never guessed at, matching every other adapter's
  "absence is a first-class outcome" contract. Filters events to the
  slate's own games' real start times (a small buffer either side, passed
  in as `game_start_times` by `orchestration/run_slate.py`) before
  requesting per-event odds (a metered call), not a blanket multi-day
  window — narrowed after a live audit found the original slate-date-based
  window could fetch odds for roughly 3 days' worth of MLB games on every
  single call. Prefers DraftKings when it's posted a given player's
  market, falling back to whichever other bookmaker has it. Logs and,
  below a low-quota threshold, surfaces a real warning for the vendor's
  remaining monthly-request balance (`x-requests-remaining` response
  header). The free tier is 500 requests/month — against that,
  `orchestration/run_slate.py` throttles the metered odds fetch itself
  (not the rest of the pipeline) to at most once per real calendar day
  regardless of how many times `run_slate()` is scheduled that day
  (`_odds_api_already_succeeded_today`, keyed off `SourceHealth`), added
  once the scheduler's multi-run-per-day cadence made a naive per-run
  fetch arithmetically impossible to sustain for a month on the free
  tier. Even at once/day, a full slate's worth of calls is close to the
  free tier's daily fair share (500/30 ≈ 16.6/day) — a paid tier is a
  real operating cost to budget for, not a hidden one. Tested against
  real captured responses (`tests/fixtures/odds_api/`) with respx (14
  unit tests, including the narrowed-window behavior), plus full
  `run_slate()` integration tests proving both the odds-API branch gets
  used when configured and the once-per-day throttle actually skips a
  second same-day call. **This is NOT Underdog's own DFS
  pick'em lines** — Underdog has no public/authorized API (see
  Provisional below); these are real regulated-sportsbook strikeout
  totals, a different but legitimate market. Runs *instead of* the
  manual adapter, never alongside it, specifically to avoid two sources
  disagreeing and tripping `check_line_conflict`'s DATA_CONFLICT finding
  on the same pitcher/game/market. Two real bugs found by a live
  multi-agent review (adversarial point-in-time audit + security review)
  are fixed and covered by regression tests: (1) two confirmed starters
  sharing an identical vendor-reported name previously collided silently
  in a plain dict, letting a real line get attached to the wrong
  `player_mlb_id`/`mlb_game_pk` with no warning — now detected up front
  and deliberately dropped (never guessed at) with an explicit warning;
  (2) `httpx.HTTPStatusError`'s own `str()` embeds the full request URL
  including the API key query parameter — warnings are now built from
  the status code/exception type only, never the raw exception string,
  since warnings flow into the append-only `audit_events` table, admin
  API responses, and deploy logs.
- Generic ingestion service + data-quality gate (stale/missing/conflict/
  market-incomplete checks), with source health tracking and an
  append-only audit trail.

### Point-in-time correctness

- `pit/asof.py`'s three primitives (`latest_as_of`, `all_as_of`,
  `latest_grouped_as_of`) are the sole gate for historical reads —
  `ingested_at` (real wall-clock write time) AND `observed_at` (source's
  claimed effective time) must both be `<= cutoff`.
- `pit/snapshot_builder.py` freezes a point-in-time view of a slate
  purely through those primitives; reruns at the same cutoff never
  mutate a prior snapshot.
- A dedicated adversarial leakage suite (`engine/tests/pit/`, 19 tests)
  tries to make the wrong (leaked) answer look attractive — a late
  "correction" that's the true latest, observed_at backdating in both
  directions, a starter swap arriving after cutoff, a sentinel value
  seeded directly into `raw_final_box_scores` for the exact player/game
  being projected — and asserts it's refused every time. `raw_final_box_scores`
  is structurally unreachable from `pit/`, `features/`, or `models/`
  (AST-verified, not just documented) — only `grading/` reads it, and
  only `game_status='Final'` rows.

### Features, model, decision

- Feature engineering (`features/`): expected batters faced and
  decay-weighted recent K-rate with documented fallback tiers
  (recent-weighted → season-average → league-default), park/weather
  adjustments, a `role_stability_flag` signal when a fallback tier was
  used.
- Baseline model (`k-model-0.1.0`, `models/baseline.py`): a deliberately
  simple, interpretable formula (not a trained model — the pre-comparison
  naive baseline the backlog calls for), strikeouts modeled as Poisson.
  The decision engine only ever calls the model through the
  `StrikeoutModel`/`StrikeoutDistribution` interface (ADR 0003) — no
  distribution family is hardcoded outside `models/`.
- Decision engine (`decision/engine.py`, `k-decision-0.2.0`): edge vs. a
  neutral 0.5 baseline (never called an "Underdog-implied probability" —
  ADR 0006), the full Appendix A reason-code catalog, OVER/UNDER/NO_PLAY
  × QUALIFIED/UNCERTAIN/HELD/REJECTED. **Known gap**: the version was
  `k-decision-0.1.0` from initial build through two real logic fixes
  (Phase 1D's integer-line push-probability correction, Phase 1F's
  missing-line/synthetic-edge correction) that changed what gets
  computed for real inputs — neither fix bumped the version at the time,
  which an audit later caught (see
  `docs/FINAL_COMPLETION_WORKLOG.md`). Bumped to `0.2.0` when found.
  Practical consequence: any projection published under
  `k-decision-0.1.0` cannot be distinguished as pre- or post-fix from
  `decision_policy_version` alone — both bugs and their fixes happened
  under that same version string, so ADR 0010's reproducibility
  guarantee is incomplete for that historical window specifically.
  Going forward, `0.1.0` will never be reused and every future logic
  change gets its own bump.

### Ledger and grading

- Append-only projection ledger (`ledger/service.py`): every publish is
  an INSERT; "current" is always `DISTINCT ON (logical_key) ORDER BY
  version DESC`, never a mutable flag (ADR 0002); reproducibility hash
  over snapshot + features + model/policy versions + git commit (ADR
  0010); late-publication flagging (ADR 0008). **Fixed a real gap**
  found by an external repo audit (independently verified before acting
  on it): `is_late_publication` was being correctly computed and stored,
  but "current" derivation ignored it entirely (`ORDER BY version DESC`
  with no regard for the flag) — a run that happened to land after a
  game's first pitch would have silently become that game's displayed
  official pick, overriding an honest pre-lock one, with the flag
  present on the row but never actually enforced anywhere.
  `current_projections_for_slate`/`recent_current_projections` now
  prefer the latest genuinely official (published, not late) version per
  logical_key, falling back to the latest version overall when nothing
  official exists yet for that key (so a game still hours out with only
  evaluated-not-yet-decided rows still shows something, per the
  transparency principle). This was a real, not hypothetical, gap: it's
  exactly what running the scheduler more than once a day (see below)
  would have made concretely worse rather than better if left unfixed.
- **Official publication freeze cutoff**: `is_late_publication` is now
  computed against `settings.publication_freeze_minutes_before_first_
  pitch` (default 15, configurable via `PUBLICATION_FREEZE_MINUTES_
  BEFORE_FIRST_PITCH`) minutes before the game's scheduled start, not the
  literal first-pitch moment — a publication landing inside that window
  is marked late even though it's genuinely still pregame, so an
  operator has a stable pick before the window closes rather than one
  that could keep changing up to the last minute. Same "provisional,
  configurable, not silently final" status as `decision_edge_threshold`
  (ADR 0008 updated; still explicitly not Tyler's confirmed operational
  number). Dedicated tests cover the new boundary (a publication inside
  the window but before first pitch is late; just outside it is
  official).
- **DEMO/BACKTEST/PAPER/LIVE record classification**: `projections.
  record_label` (migration `b09cb74d06a7`, `db/models/projection.py`'s
  `RECORD_LABELS`) defaults to `"LIVE"` on every write, requiring no
  change from the real pipeline (`orchestration/run_slate.py`); `scripts/
  seed_demo_slate.py`'s fixture-replay demo slate is the one caller that
  overrides it to `"DEMO"`, so a `make seed-demo` run against a real
  database can never be silently mistaken for a genuine live pick on any
  page that reads this table -- verified end to end (seeded a scratch
  database, confirmed all 20 written rows are `record_label='DEMO'`).
  Never hidden -- the transparency principle applies to every row
  regardless of label, same enforcement pattern as `is_late_publication`
  (excluded from official aggregates by readers, not by omission).
  `ProjectionOut.record_label` exposed via the API; `ProjectionsTable`
  badges any non-`LIVE` row on both Today and Ledger. `BACKTEST`/`PAPER`
  are in the CHECK constraint's allowed vocabulary (per the mission
  directive's explicit labeling requirement) but no code path writes them
  today -- the separate `historical/` subsystem never writes to
  `projections` at all (see its own `HISTORICAL_RECONSTRUCTION` labeling
  on its own frozen report files instead). Whether the live pipeline
  should default to `LIVE` vs `PAPER` during any beta/paper-tracking
  period is a real product decision for Tyler, not guessed at here.
- Honest, append-only grading (`grading/service.py`): WIN/LOSS/PUSH/VOID/
  NO_PLAY, only grades published projections against `Final` box scores
  (ADR 0007), idempotent (a correction — a later Final box score for the
  same outing — appends a new grade rather than duplicating or mutating).

### Orchestration, API, CLI

- `orchestration/run_slate.py`: `run_slate()` (INGEST → VALIDATE → FREEZE
  → PROJECT → REVIEW → PUBLISH, one call) and `grade_slate_run()`, both
  writing full `pipeline_runs`/`pipeline_run_stages` detail. Publishes a
  row for every confirmed starter, including ones with no market line
  (REJECTED/`MARKET_CONTEXT_INCOMPLETE`, `line=None`) — transparency
  holds even without a prop to grade.
- FastAPI app (`api/`): `GET /health`, `GET /api/today`, `GET /api/ledger`
  (+`/{projection_id}` history), `GET /api/admin/status`, `POST
  /api/admin/runs/{slate_date}/{run,grade}` — the admin routes gated by
  ADR 0011's shared-secret header.
- **Source-health semantics**: `SourceHealth.last_status` is now a real
  vocabulary (`HEALTHY`/`PENDING`/`DEGRADED`/`FAILED`/`DISABLED`/
  `QUOTA_LIMITED` — `db/models/sources.py`'s `SOURCE_HEALTH_STATES`),
  not a bare ok/unavailable flag. `AdapterFetchResult.unavailable_reason`
  lets an adapter say *why* it has no data — `umpire_stub` always reports
  `disabled` (permanent by design); `final_box_scores_mlb` reports
  `pending` when a game genuinely hasn't reached Final yet (not a
  fetch error); `lines_odds_api` reports `pending` when no confirmed
  starter has a posted prop yet, and `quota_limited` specifically on a
  429. Admin's blocking-issues check (`NEVER_BLOCKING_STATES`) is now
  keyed on this state, not a hardcoded per-adapter-name allowlist — a
  real bug class this closes: any future permanently-stub or
  legitimately-pending source gets the correct non-blocking treatment
  automatically, without needing another special case added to
  `admin.py`. Adapters that don't set a reason keep the old generic
  behavior (escalates from `DEGRADED` to `FAILED` after 3 consecutive
  failures). The frontend's `SourceHealthTile` shows a plain-English
  detail + implied recommended action per state.
- Typer CLI (`cassandra` console script): `ingest`, `snapshot`,
  `run-slate`, `grade`.
- Live-verified against the real MLB Stats API (not fixtures) for a
  real slate during this build: 30 real pitchers ingested (453 real
  game-log rows), correctly frozen/projected/published.
- `orchestration/scheduler.py`: an opt-in (`AUTO_SCHEDULER_ENABLED`,
  off by default) in-process background thread for long-running
  deployments (Replit's is the motivating case — `replit_start.sh` turns
  it on) so Today populates and recent slates get graded without a human
  running the CLI daily. `run_slate()` fires at each configured local
  hour in `AUTO_RUN_HOURS_LOCAL` (default `7,12,16` — morning/midday/
  pre-evening-game, not just once at a single fixed hour, so newly
  confirmed starters/updated lines/weather get picked up through the
  day); `grade_slate_run()` is re-attempted every poll tick across a
  trailing window since it's cheap and fully idempotent. One failing
  tick (a transient MLB API outage, one bad slate date) never blocks the
  others or kills the thread — each call is individually caught and
  logged. Wired into `api/main.py` via FastAPI's `lifespan`; confirmed
  empirically that `TestClient(app)` used without a `with` block (this
  repo's API test fixture) never triggers `lifespan`, so the scheduler
  never starts during tests regardless of the settings flag. Restart-
  safety is fully DB-derived, not in-memory: each tick counts real
  run_slate() successes on record for today
  (`_run_slate_success_count_today`) and compares against how many
  configured hours have already passed, so a redeploy can never trigger
  a redundant run (re-burning real, metered Odds API credits) just
  because in-process state reset to zero — this also means adding more
  daily run hours never risked losing the original once-per-day
  restart-safety property, it generalizes for free. Multiple daily runs
  are only safe to have added because of ledger/service.py's official-
  vs-late-publication precedence fix (below) — without it, a run that
  happened to land after a game's first pitch could have silently
  become that game's displayed "current" pick.
- **Live lineup ingestion adapter is real and implemented**:
  `adapters/lineups_mlb.py`'s `LineupMLBAdapter` (new `"lineup"` source
  kind, migration `d31a32076841`) fetches MLB's live-feed endpoint per
  game and writes one `raw_lineups` row per team once that team's
  batting order is posted (MLB typically posts 1-3 hours before first
  pitch; an unposted lineup is `unavailable_reason="pending"`, not a
  failure, same pattern as `final_box_scores_mlb.py`). Wired into
  `orchestration/run_slate.py`'s `ingest_slate()`. `pit/snapshot_
  builder.py` now resolves the OPPONENT's lineup (not the pitcher's own
  team's -- who a starting pitcher actually faces) via the same
  `latest_as_of()` two-condition cutoff gate every other raw table read
  uses, writes a `snapshot_raw_refs` entry when found, and surfaces
  `ingestion/quality_gate.py`'s new `check_lineup_confirmed()` finding
  (`LINEUP_UNCONFIRMED`, `warn` severity) -- wiring the reason code that
  had existed in the vocabulary since Phase 1 but was never backed by a
  real source. **Deliberately NOT added to `decision/engine.py`'s
  `QUALITY_RISK_CODES`**: MLB commonly hasn't posted a lineup at typical
  scheduler run times, so including it there would downgrade nearly
  every early-day evaluation to UNCERTAIN regardless of real edge -- a
  sweeping, unreviewed behavior change to how often anything shows
  QUALIFIED. The finding is still recorded and visible in every
  projection's `reason_codes` (transparency preserved), just not gating
  `decision_status` yet; whether/when it should is a real product
  decision for Tyler, documented as open rather than guessed at. Real,
  point-in-time-correct end-to-end test coverage: a dedicated adapter
  test suite, `check_lineup_confirmed` unit tests, and an integration
  test proving `build_snapshot()` resolves the correct opponent (not
  same-team) lineup using the real 2023-06-15 fixture slate.
- Admin's "Blocking Issues" panel (`api/routers/admin.py`) excludes
  `umpire_stub` (a permanent stand-in, always unavailable by design —
  see Provisional below) from ever being flagged as blocking; found live
  as a standing false alarm nobody could resolve, fixed with a
  regression test. **Not yet resolved, flagging rather than silently
  deciding:** `mlb_stats_api_final_box_scores` also shows as "failed"
  repeatedly on a live deployment before games go Final — expected
  behavior (the scheduler's `grade_slate_run()` re-attempts it every 15
  minutes, and box scores genuinely aren't available until a game
  finishes), not a bug, but it's currently indistinguishable from a real
  problem in the Admin UI. Whether this needs the same "never blocking"
  treatment, a smarter time-aware threshold, or is fine as-is is a real
  product call, not an engineering one.
- **Manual Underdog-line-import admin tool is real and implemented**:
  `ingestion/manual_line_import.py` (`preview_line_import`/
  `commit_line_import`) resolves pasted player-name + line entries
  against that slate's real confirmed probable pitchers -- same
  by-name-matching and ambiguous-name-collision handling
  `adapters/lines_odds_api.py`'s real odds-vendor integration uses, so a
  name that doesn't match or is ambiguous is reported, never guessed at.
  API: `POST /api/admin/lines/{slate_date}/{preview,import}` (same
  shared-secret gate as every other admin route). Writes real
  `raw_lines` rows via the standard `ingest_service.ingest()` path
  (source `lines_manual_admin_import`) -- append-only, audited, same as
  every other source; flags a same-day pre-existing line as an
  informational (non-blocking) possible duplicate. Admin page gained a
  "Manual Line Import" section (paste `Player Name, line, over_price,
  under_price` one per line, Preview before Import). Exists specifically
  because the pre-existing drop-folder mechanism
  (`adapters/lines_manual.py`) needs filesystem access to the running
  server, which an operator on a deployed Replit instance doesn't have --
  this is the same underlying `raw_lines` contract exposed as an admin
  action instead. Verified end-to-end in a real browser (Playwright)
  against a real running engine + seeded DB row, not just automated
  tests: login, slate-date entry, paste, Preview showing correct
  matched/unmatched, Import actually writing the row.
- **Phase 8 security hardening is real and implemented**: CORS is now a
  configurable allowlist (`config.py`'s `allowed_origins`/
  `allowed_origins_list`, `ALLOWED_ORIGINS` env var) instead of a
  hardcoded `"*"` -- the default is still `"*"`, which remains safe in
  the actual Replit deployment topology (the FastAPI engine binds
  `127.0.0.1`-only there; see `scripts/replit_start.sh`, so no browser
  can reach it cross-origin at all), but a real non-Replit/non-proxied
  deployment can now lock it down without a code change. `api/main.py`
  adds an HTTP middleware setting `X-Content-Type-Options: nosniff`,
  `X-Frame-Options: DENY`, and `Referrer-Policy:
  strict-origin-when-cross-origin` on every response, mirrored in
  `web/next.config.ts`'s `headers()` since the Next.js app -- not the
  loopback-only engine -- is the actually publicly-reachable surface in
  production. **Deliberately no CSRF-token mechanism**: ADR 0011's admin
  auth is a custom `X-Admin-Secret` HEADER, not a cookie-based session,
  so the classic CSRF vector (a browser auto-attaching credentials to a
  cross-origin request) doesn't apply here -- documented inline in
  `api/main.py` so this isn't silently reintroduced later as an
  unexplained gap. `api/deps.py`'s `require_admin()` now logs failed
  auth attempts (`logger.warning("admin auth failed: client=... path=...")`)
  for operational visibility, explicitly never logging the attempted
  secret value itself. Verified with real HTTP requests against both a
  production Next.js build and the FastAPI engine directly (`curl`,
  headers confirmed present on `/health` and a 404), not just unit
  tests.

### Historical backfill (2023-present)

See `docs/HISTORICAL_BACKFILL_DESIGN.md`, `docs/HISTORICAL_DATA_
DICTIONARY.md`, `docs/HISTORICAL_BACKFILL_RUNBOOK.md`, and
`docs/HISTORICAL_COVERAGE_REPORT.md` for full detail. Deliberately a
separate subsystem from the live pipeline above -- writes to its own
tables (`historical_pitcher_starts`, `historical_lineups`,
`backfill_runs`, `backfill_items`), never to the live `raw_*` tables,
and never read by `pit/asof.py`/`features/`/`models/`/`decision/`
(verified by an AST-based structural test, not just documented intent).

- **Real, resumable, idempotent** (`engine/src/cassandra/historical/
  backfill.py`): one schedule range call per season slice, one live-feed
  call per game, upsert-by-natural-key for both pitcher outcomes and
  lineups. Verified against the live MLB Stats API (not just mocks)
  before writing tests -- a real 15-game single-day run, a real
  415-game full-month run, and a proven instant no-op rerun of an
  already-completed range (zero new HTTP calls, zero duplicate rows).
- Found and fixed a real bug this way: schedule-discovery idempotency
  was originally keyed on season alone, so an early narrow-window
  discovery could silently "cover" (and permanently skip) a later wider
  request for the same season. Fixed by keying on the exact requested
  window; regression test added.
- CLI: `backfill-mlb`, `backfill-status`, `retry-backfill-failures`,
  `audit-historical-coverage`.
- Collects: schedule/games (all game types, classified via the new
  `games.game_type`/`games.season` columns), actual starters (from
  `pitching.gamesStarted`, explicitly NOT conflated with the live
  pipeline's pregame-confirmed-probable-pitcher concept --
  `pregame_starter_confirmation_captured` is always `False` on backfilled
  rows), full pitcher-outcome normalization, and starting lineups
  (labeled `HISTORICAL_ACTUAL`, since there's no trustworthy pregame-
  availability timestamp for them in the free API).
- **Training-dataset builder (`STRICT_LIVE_COMPATIBLE` tier) is real and
  implemented**: `historical/availability.py`'s `eligible_prior_starts()`
  (a pitcher's own prior Final starts, strictly before the target game's
  date -- the actual leakage gate) feeds `historical/dataset_builder.py`,
  which reuses `features/expected_bf.py`/`features/builders.py`'s exact
  decay-weighted computation functions (via a small duck-typed adapter,
  not a reimplementation -- made possible by widening those functions'
  parameter type to a structural `GameLogLike` protocol). CLI:
  `build-training-dataset`, `dataset-status`, `audit-training-dataset`,
  `export-training-dataset`. Output is a frozen, versioned gzipped-JSONL
  + JSON-manifest pair per build under `engine/data/training_datasets/`
  (gitignored -- regeneratable research artifact, not a new Postgres
  table). Covered by a dedicated leakage test suite
  (`engine/tests/integration/test_dataset_builder.py`) proving a row's
  features never draw on the target game itself or any later game.
  Verified against real backfill data: `cassandra build-training-dataset
  --seasons 2023` produced 4,860 real rows.
- **Baseline evaluation is real and implemented**:
  `historical/evaluation.py` runs the permanent, unmodified
  `k-model-0.1.0` against a frozen dataset and computes MAE, RMSE, mean
  bias, Poisson deviance, and calibration/Brier score at 6 illustrative
  half-integer thresholds (no real historical lines exist -- calibration
  compares the model's own predicted P(over) to realized frequency), plus
  a per-`recent_k_rate_tier` breakdown. CLI: `evaluate-baseline`. Every
  report is labeled `HISTORICAL_RECONSTRUCTION` and written to its own
  frozen file, never to `projections`/`grades`. Verified against real
  2023 backfill data: MAE 1.95 strikeouts, well-calibrated across all 6
  thresholds tested (see `docs/TRAINING_READINESS_REPORT.md` for the full
  numbers).
- **A Poisson-regression challenger + walk-forward validation are real
  and implemented**: `historical/challenger_poisson.py` fits a log-link
  Poisson GLM via IRLS (`fit_poisson_regression`) over the same reduced
  feature set the baseline uses, implementing `StrikeoutModel` so it's a
  drop-in for anything the baseline is (ADR 0003). Needs the new
  `training` extra (`numpy`; `pyproject.toml` -- kept out of the live
  pipeline's core dependencies, lazily imported in the CLI command so
  every other command keeps working if it's ever missing).
  `historical/walk_forward.py`'s `run_walk_forward_validation()` splits a
  dataset into expanding-window folds (never k-fold cross-validation,
  which would leak future data into past folds), fits a fresh challenger
  per fold, and evaluates both models against that fold's held-out rows
  -- the strictly-earlier-training-than-validation guarantee has its own
  dedicated test. CLI: `train-walk-forward-challenger`. **Verified
  against the complete 2023-2025 backfill (14,578 rows, 7 folds run): the
  challenger beat the baseline on every fold** -- aggregate MAE 1.866
  (challenger) vs. 1.917 (baseline), a consistent ~2.7% improvement that
  replicated as the dataset grew from an earlier 9,718-row partial run.
  See `docs/TRAINING_READINESS_REPORT.md` for the full per-fold numbers
  and explicit caveats (reduced feature set, one fold count, no
  significance test, no promotion mechanism exists). **No automatic
  promotion anywhere** --
  every report is `HISTORICAL_RECONSTRUCTION`-labeled and written to its
  own frozen file; nothing in this repository ever writes a challenger's
  predictions to `projections`/`grades`.
- **Historical weather and park factors are real and implemented (Phase
  4)**: `historical/backfill.py`'s `process_game_feed` captures
  `gameData.weather`/`gameData.venue` from the SAME MLB feed payload it
  already fetches per game (no new external calls) into
  `historical_weather_observations`
  (`db/models/historical.py`'s `HistoricalWeatherObservation`, migration
  `b8975f126305`) -- ground truth for that specific game (dome/roofed
  venues report MLB's own condition value, e.g. `"Dome"`, as-is). A
  dedicated `cassandra backfill-weather` pass (`process_weather_for_game`/
  `run_weather_backfill`, its own resumable `BackfillItem` domain)
  enriches games backfilled before this feature existed. Park factors are
  computed, not a static table: `historical/park_factors.py`'s
  `ParkFactorAccumulator` walks `historical_pitcher_starts` in a single
  chronological pass (venue K-rate ÷ league K-rate, clipped to
  `models/baseline.py`'s `PARK_ADJ_BOUNDS`), available only once a venue
  clears `MIN_BATTERS_FACED_FOR_PARK_FACTOR` (400) batters faced in its
  own strictly-prior history. Point-in-time-safe by construction (a
  row's own outcome is recorded into the accumulator only AFTER that
  row's own factor is read) -- verified by `tests/unit/test_park_factors.py`
  and a dedicated leakage test in `tests/integration/test_dataset_builder.py`.
  `features/builders.py`'s `compute_weather_adjustment` (the exact
  function the live pipeline calls) now takes a `WeatherLike` Protocol
  instead of the live-only `RawWeatherObservation` class (mirroring
  `expected_bf.py`'s existing `GameLogLike` pattern) so the historical
  dataset reuses identical adjustment logic rather than a parallel copy
  that could drift. `historical/dataset_builder.py`'s
  `EXCLUDED_FEATURE_GROUPS` no longer lists `park_factor`/`weather` --
  each row's `park_factor_available`/`weather_available` flags still
  honestly report whether THAT row actually resolved a value.
  `DATASET_BUILDER_VERSION` bumped to `0.2.0` (real output-schema change).
  Not yet done: re-running the walk-forward baseline-vs-challenger
  comparison with these two features wired into the challenger's own
  predictor set (`historical/challenger_poisson.py` still trains on the
  same reduced `expected_bf`/`recent_k_rate`/`rest_days` set it always
  has, deliberately matching the permanent baseline's inputs for a fair
  comparison) -- a real product/modeling decision, not an oversight.
- **Durable model artifacts + a model registry are real and implemented
  (Phase 3)**: `db/models/registry.py`'s `model_artifacts`/
  `model_registry_events` tables (migration `e076e6061a06`) -- append-only
  at the database grant level, same `cassandra_block_immutable_mutation`
  trigger + `REVOKE UPDATE, DELETE, TRUNCATE` pattern as `raw_*`/
  `projections`/`grades`/`audit_events`, verified empirically (a real
  UPDATE/DELETE/TRUNCATE attempt against either table fails). No mutable
  status column anywhere: `registry/service.py`'s `current_status()`
  always derives an artifact's status from its latest
  `model_registry_events` row, the same "current" pattern `projections`
  already uses (ADR 0002). `cassandra train-final-model --dataset-id
  ds_... --family poisson-regression --operator <name> [--register]`
  (`historical/train_final_model.py`) fits a FINAL (non-walk-forward)
  Poisson challenger on every eligible row of a frozen dataset, writes a
  durable artifact (coefficients, coefficient order, intercept,
  preprocessing/regularization rules, full training-dataset provenance,
  source git SHA, a reproducibility checksum, dependency versions,
  in-sample training metrics, and a pointer to its own
  `HISTORICAL_RECONSTRUCTION`-labeled evaluation report), then genuinely
  proves the round-trip: a separate committed transaction re-reads the
  row, reconstructs a model from it, and the command raises if either the
  reloaded coefficients or the reloaded model's re-evaluated metrics
  don't exactly match the original fit. Registers as `CANDIDATE` only
  with `--register`.
- **The registry is wired into the live decision engine and a human can
  actually promote/roll back a model (Phase 4)**: `run_slate()`'s PROJECT
  stage now calls `registry/service.py`'s `resolve_active_model()` --
  whichever artifact's latest registry event is `ACTIVE`, reconstructed
  via the new numpy-free `models/poisson_regression.py` (split out of
  `historical/challenger_poisson.py` specifically so the live pipeline
  never needs `numpy` installed), or the permanent, unmodified baseline
  whenever nothing is `ACTIVE` -- structurally guaranteed, not by
  convention. Every published projection's `model_version` is now the
  ACTUAL model that produced it (a specific artifact's
  `fitted_model_version`, not just the shared family-level code version)
  -- verified end to end against the real 2023-06-15 fixture slate.
  `cassandra promote-model --artifact-id ... --operator ...` atomically
  retires whatever was previously `ACTIVE` and activates the new one in
  the same transaction (refusing anything not currently
  `CANDIDATE`/`APPROVED`, or an unsupported `model_family`);  `cassandra
  rollback-model --operator ... --reason ...` retires the current
  `ACTIVE` artifact as `ROLLED_BACK` (falling back to the baseline by
  default, or reactivating a specific prior artifact via
  `--to-artifact-id`); `cassandra model-status` shows what's currently
  live plus recent registry history. **No automatic promotion anywhere**
  -- every one of these requires an explicit human `--operator` identity
  and none is reachable from any scheduled/automated code path.
  `SHADOW`/`APPROVED`/`REJECTED` remain schema-supported (`CHECK`
  constraint, full vocabulary) but unreached by any real code path -- no
  shadow-mode runner or approval-gate action exists yet. Also surfaced in
  Admin: `GET /api/admin/status`'s `active_model` field (null when
  nothing's promoted) and a new "Active Model" section on the Admin page
  showing the live model's provenance/training metrics/who activated it
  -- verified with real browser screenshots (Playwright), not just the
  automated test suite, in both the active-challenger and
  baseline-fallback states.
- **Not yet built**: a shadow-mode runner (evaluating a `CANDIDATE`
  against live slates without its predictions ever reaching
  `projections`/`grades`), negative-binomial/gradient-boosted challenger
  alternatives. See `docs/TRAINING_READINESS_REPORT.md` for the
  full "what's still not built" list. Also not yet collected/implemented
  (reported honestly, not silently omitted -- every dataset manifest/row
  records these as unavailable, and `audit-historical-coverage` surfaces
  them too): pitch-level/plate-appearance detail, opponent rolling
  strikeout context, player identity resolution for backfilled pitchers
  (so pitcher handedness isn't available), and the
  `RETROSPECTIVE_ENRICHED` tier (nothing enriched exists yet to build it
  from).
- **Backfill run status: complete.** The 2023-01-01-to-present backfill
  (`backfill_run_id=backfill_8aae900893d7`) finished with `status=
  completed`, 0 failed games across its entire run, and a small number
  of legitimate `skipped` games (not yet `Final` -- postponed/
  rescheduled or in-progress at the time of the last check). 2023-2025
  regular seasons are fully covered; 2026 is covered through its current
  point-in-time (the season is still being played). See
  `docs/HISTORICAL_COVERAGE_REPORT.md`/`cassandra audit-historical-
  coverage` for exact per-season counts. Still resumable going forward
  (`cassandra backfill-mlb --resume` with the same date range) to pick up
  new games as each day's slate reaches Final.

### Fixture demo slate

- A real historical slate (2023-06-15) with a hand-picked
  `lines_manual` drop file covering 4 of its 20 real probable starters,
  chosen so their *real recorded* outcomes deliberately produce a WIN, a
  LOSS, a PUSH, plus 16 other real starters correctly falling out as
  NO_PLAY (no line). `scripts/seed_demo_slate.py` (`make seed-demo`)
  replays it via saved real API fixtures (live network can't
  retroactively return `probablePitcher` for an already-`Final` game —
  confirmed empirically) and runs the real pipeline against a real
  Postgres database.

### Frontend

- Next.js App Router, TypeScript strict: Today (`/`), Results Ledger
  (`/ledger`), Admin (`/admin`) — the three pages ADR 0012 scopes this
  build to. Admin is gated by the same shared-secret header, entered
  client-side and proxied to the engine through Next.js's own origin
  (`next.config.ts` rewrite) rather than needing a second exposed port —
  works the same locally, in Docker Compose, and on a single-port host.
- Verified live end to end against the real seeded demo slate: screenshots
  captured of all three pages showing real projections, real WIN/LOSS/
  PUSH grades, real source health, and all 7 pipeline stages with real
  statuses.

### Tests, tooling, CI

- 204 engine + scripts tests (181 engine: unit, integration, API, the
  point-in-time leakage suite; 23 guardrails regression tests) — all
  passing on a freshly rebuilt database. (This count grows with the
  platform; verify against `make test-engine`/CI rather than treating
  this number as pinned.)
- Frontend: 15 Vitest component tests, 7 Playwright + axe accessibility
  tests, `next build` succeeds.
- `make verify` (lint, format-check, typecheck, `bandit` + `pip-audit`,
  `scripts/guardrails.py`, migrations-from-empty, the full test suite,
  frontend gate, build) passes clean end to end.
- `scripts/guardrails.py`: 23 regression tests, wired into CI and a
  Claude Code PreToolUse hook.
- CI (`.github/workflows/ci.yml`): engine job + web job, matching `make
  verify`'s checks.

## Provisional / deliberately stubbed (documented, not silent)

These are the handbook's own "unresolved" items, built behind clean
swappable seams rather than guessed at, per `CLAUDE.md`'s instruction not
to invent missing product decisions:

- **Umpire data**: permanent stub, always `is_available=False` — no
  reliable free source exists. Never blocks a decision (a deliberate
  WARN, excluded from `QUALITY_RISK_CODES`).
- **Underdog lines**: still no real Underdog integration, and Underdog's
  real acquisition method/ToS remains legally unresolved per the
  handbook — Underdog's own internal (undocumented, unauthorized) API was
  explicitly considered and rejected during this build; using it would be
  scraping in substance. Two real line sources exist instead:
  `adapters/lines_manual.py` (drop-folder, always available) and
  `adapters/lines_odds_api.py` (a real licensed vendor, The Odds API,
  when `ODDS_API_KEY` is set) — but the latter is regulated-sportsbook
  strikeout totals, not Underdog's own DFS pick'em lines. Getting actual
  Underdog data requires either a real partner/affiliate relationship
  with Underdog or continuing on sportsbook-vendor lines as a legitimate
  (if different) product direction — a business decision, not an
  engineering one.
- **Official paid MLB data**: free MLB Stats API used instead — no paid
  vendor integration exists.
- **Park factors**: a small static/seeded table
  (`adapters/park_factors_static.py`); only venue_id=2 (Camden Yards) is
  confirmed against a real vendor, the rest are common approximations.
  Unknown venues fall back to neutral with a visible warning.
- **Weather coordinates**: `orchestration/run_slate.py`'s
  `VENUE_COORDINATES` static lookup now covers all 30 current active-team
  home venues, sourced directly from MLB's own Stats API
  (`/api/v1/venues?hydrate=location`), not typed from memory — an unlisted
  venue (spring training, a neutral-site game) simply gets no weather
  record (a visible gap, not a guess). It's a static table, not a live
  lookup, so a relocation or new park requires regenerating it by hand.
  The forecast target time was also fixed to use each game's real
  `scheduled_start_utc` (keyed by the earliest game per venue) instead of
  the pipeline's run cutoff — previously the forecast was for "whenever
  the pipeline happened to run," not the actual game. Two known,
  documented (not silent) remaining gaps: a doubleheader's second game
  reuses the first game's forecast time (per-game weather keying would
  also require changing `pit/snapshot_builder.py`'s venue-only weather
  lookup); and the 8 dome/retractable-roof venues still get an outdoor
  forecast since no per-game roof-open/closed signal exists.
- **`DECISION_EDGE_THRESHOLD=0.05`**: an explicitly provisional constant
  (ADR 0005), not calibrated or business-approved.
- **Neutral 0.5 decision baseline**: never described as an
  "Underdog-implied probability" (ADR 0006) — real payout math is
  unresolved.
- **Opponent adjustment**: always neutral (1.0) in the baseline model —
  no opponent-lineup-contact-rate adapter exists yet; the feature field
  is kept explicit (not omitted) as a documented seam.
- **Admin auth**: a demo-only shared-secret header (ADR 0011), not
  production authentication. ADR 0011's own stated trigger for
  replacement ("must be replaced before any real deployment") has now
  been met — the admin routes are genuinely publicly reachable on the
  live deployment. Hardened, not replaced, after a live security review:
  `hmac.compare_digest` instead of `!=` (closes a timing side-channel),
  and a basic in-memory failed-attempt lockout (10 failures locks out an
  IP for 5 minutes) since there was previously no rate limiting at all
  over what may be a weak/guessable secret. A floor under the placeholder,
  not a fix for it being a placeholder — real auth is still unbuilt.
  **New**: `api/main.py`'s startup now refuses to boot at all in a real
  deployment (`REPLIT_DEPLOYMENT` env var present, or
  `PRODUCTION_MODE=true`) if `ADMIN_SHARED_SECRET` is missing, a known
  placeholder (`test`, `change-me-dev-only`, etc.), or under 16
  characters (`config.py`'s `admin_secret_is_weak`). **Action required
  before this deploys**: the live site's `ADMIN_SHARED_SECRET` is
  currently the placeholder value used for verification during this
  build — it must be rotated to a real, unique, high-entropy secret
  (e.g. `openssl rand -hex 32`) in Replit Secrets *before* pulling this
  change, or the next deploy will refuse to start by design.
- **Admin actions**: only `run` and `grade` are implemented. ADR 0007
  describes a richer revalidate/regenerate/publish state-guard split;
  that ADR's own status note marks it "Not yet implemented," deferred
  past this MVP.
- **Frontend scope**: Today/Ledger/Admin only (ADR 0012) — no All
  Projections, Player View, or Methodology pages.
- **Background scheduler**: `orchestration/scheduler.py` is a single
  in-process thread on a coarse poll interval, not a real cron/job queue
  — sufficient for one Repl/container, not for a multi-instance
  deployment (would double-run without a distributed lock). `07:00`
  local as the daily run hour is a reasonable-guess default, not a
  business-confirmed value.

## Verified against real infrastructure

- **Replit deployment**: `.replit`, `replit.nix`, and
  `scripts/replit_start.sh` were exercised against a live Replit account
  (external managed Postgres, both services running under
  `replit_start.sh`). Confirmed working: migrations applied cleanly,
  `make seed-demo`'s target script populated a real historical slate,
  Today/Ledger/Admin all rendered real data (Ledger showing the seeded
  2×WIN/1×LOSS/1×PUSH), and the Admin shared-secret gate worked. One real
  friction point found and fixed: managed Postgres providers (Neon,
  Supabase, Replit's own Postgres, Heroku-style hosts) hand out
  `postgresql://`/`postgres://` connection strings, but SQLAlchemy needs
  `postgresql+psycopg://` or it falls back to a driver this project
  doesn't install — `config.py`'s `Settings.database_url` now rewrites
  either scheme automatically, so a pasted-in connection string works
  without manual editing.
- **Reserved VM Deployment** (`cassandrahits.replit.app`), with the real
  odds vendor live: `AUTO_SCHEDULER_ENABLED` fired a real daily
  `run_slate()` against the live MLB Stats API and The Odds API,
  publishing real projections (some QUALIFIED, e.g. real DraftKings-
  preferred lines like Troy Melton 5.5, Emerson Hancock 4.5), and
  `grade_slate_run()` graded them once games went Final — all with no
  manual CLI trigger. Two real Replit-Nix-environment-specific startup
  bugs were found and fixed in `scripts/replit_start.sh`: the Nix
  `python312` package ships no `pip` (switched engine dependency
  install to `uv venv`/`uv pip install`, which doesn't need it), and
  `pnpm run dev -- --port 3000` did not reliably forward the port flag
  to Next.js 15 on Replit (switched to the `PORT` env var, which Next
  reads directly). A third, more serious issue was found in production
  and is **not yet confirmed fixed**: the deployed public URL's port
  routing pointed at the engine (`:8000`) instead of the frontend
  (`:3000`) — `/health` and `/api/today` worked, but `/`, `/ledger`, and
  `/admin` all returned the engine's own JSON 404 instead of the actual
  pages. This is a Replit Deployment networking/port-selection setting,
  not an application bug; `.replit`'s `[[ports]]` block already maps
  `3000 -> 80` correctly, but this deployment type appears to let the
  Replit UI's own port choice override that. Best-diagnosis fix applied
  (not yet reverified against the live deployment): the engine now binds
  `127.0.0.1:8000` instead of `0.0.0.0:8000` in `replit_start.sh` — it
  only needs to be reachable from the frontend on the same machine, and
  removing it from `0.0.0.0` takes it out of the running of any
  port-auto-detection Replit's deployment networking does across all
  listening interfaces. **Confirmed fixed**: redeployed at commit
  `144fd1e148678fafe0d8042b065247b3e7bc06c9` (2026-08-07, Phase 1-3
  changes) and reverified — `curl -sI https://cassandrahits.replit.app/`
  now returns `HTTP/2 200` / `content-type: text/html; charset=utf-8` /
  `x-powered-by: Next.js` (real frontend HTML, not the engine's JSON
  404), and `/api/today` returns valid JSON. Also confirmed on this same
  redeploy: `alembic upgrade head` applied `e076e6061a06` (Phase 3's
  model artifacts/registry migration) cleanly with `alembic check`
  reporting no drift; `GIT_COMMIT_SHA` was set and `curl
  http://127.0.0.1:8000/health` (loopback) returned it exactly
  (`"git_commit_sha": "144fd1e148678fafe0d8042b065247b3e7bc06c9"` --
  Phase 2B); and the startup log order was migrations → engine ready →
  frontend ready, as designed. **Not yet confirmed**: Phase 2A's actual
  failure-teardown behavior (the whole deployment going down if the
  engine crashes) -- this redeploy only exercised the normal, successful
  startup path, not a deliberately broken one (e.g. an unreachable
  DATABASE_URL). That specific scenario still needs a deliberate test
  against a non-production Repl before being called verified.
- **Confirmed on a second real redeploy**: commit
  `3f14eef3b9f27a49841e1c3c1fbb3c8f73269abf` (2026-08-07, Phase 4 --
  closing the self-learning loop) was deployed and verified by Tyler.
  `alembic upgrade head` applied `f18a2c4e9b31` (the `sequence` column on
  `model_registry_events`) cleanly with `alembic check` reporting no
  drift; `curl http://127.0.0.1:8000/health` (loopback) returned
  `{"status":"ok","git_commit_sha":"3f14eef3b9f27a49841e1c3c1fbb3c8f73269abf"}`;
  `curl -sI https://cassandrahits.replit.app/` returned `HTTP/2 200` /
  real frontend HTML; and `cassandra model-status` correctly reported
  `ACTIVE: permanent baseline (model_version=k-model-0.1.0)` with no
  registry events yet -- i.e. `resolve_active_model()`'s baseline
  fallback path is confirmed live and correct in production, since no
  challenger has been promoted yet. One real incident surfaced during
  this deploy and was fixed in this session immediately after: Replit's
  workspace file sync auto-committed the ~5MB pre-deploy backup dump
  (`cassandra-backup-<timestamp>.dump`, produced by the README's
  documented `pg_dump --format=custom` step) into git, diverging the
  local Replit clone from `origin/claude/repo-reset-jexzz6` and blocking
  a fast-forward pull. Tyler's Replit agent resolved the immediate
  problem with `git reset --hard origin/claude/repo-reset-jexzz6`
  (confirmed via `git fetch` from this session that the real GitHub
  remote was never polluted -- only the local Replit workspace
  diverged). Root cause: `.gitignore`'s pre-existing `backup_*.sql`
  pattern (added in Phase 2D) never matched the `.dump` extension or
  `cassandra-backup-` prefix the README instructs Tyler to actually
  produce -- a real gap introduced in an earlier phase of this build and
  not caught until it caused a live incident. Fixed by broadening
  `.gitignore` to a bare `*.dump` pattern, since any `.dump` file in this
  repo is a Postgres custom-format backup, never source code, regardless
  of its exact name. **Remaining risk this doesn't fully close**: this
  only prevents git from tracking a dump file that lands inside the
  repo's working directory -- it doesn't stop Tyler from running `pg_dump`
  with an output path inside the repo in the first place. The README's
  backup instructions should ideally write outside the repo tree
  entirely; that's a documentation follow-up, not a code change, and is
  not yet done.

## Not verified against real infrastructure this session

- **Docker Compose**: `docker-compose.yml` (postgres + engine + web) is
  validated via `docker compose config` (schema/interpolation check) and
  every constituent piece — Postgres, `uvicorn`, `next dev`/`next build`
  — was run and verified directly outside Docker (this sandboxed session
  has no Docker daemon available). The compose file itself has not been
  exercised with an actual `docker compose up`.
- **`scripts/replit_start.sh`'s deployment-mode process supervision**
  (Phase 2, `docs/FINAL_COMPLETION_WORKLOG.md`'s 2A entry): the frontend
  is now started as a second supervised background job instead of
  running in the foreground, with a `wait -n` + `kill -0` pair deciding
  which of the two died and tearing the other down, exiting non-zero so
  the whole deployment visibly fails instead of leaving the frontend
  serving alone against a dead engine. The bash logic itself was
  exercised standalone (two isolated sandbox scripts simulating "engine
  dies first" and "frontend dies first", both correctly identified which
  process died, killed the other via the trap, and propagated the
  correct exit code) and `bash -n` syntax-checked. **Partially confirmed
  on real infrastructure since**: the 2026-08-07 redeploy at
  `144fd1e148678fafe0d8042b065247b3e7bc06c9` (done by Tyler via Replit,
  reported back into this session) shows the intended HAPPY-path startup
  log order verbatim (`==> Applying database migrations` -> `==> Starting
  the engine API...` / `Application startup complete` -> `==> Dev server
  ...` / `Ready`) on a real Replit process, and the frontend is
  reachable on the public port with the engine correctly loopback-only.
  **Still not confirmed**: the actual FAILURE-teardown behavior --
  whether `wait -n`'s no-PID-argument form behaves as expected on
  Replit's real bash, and whether Replit's deployment platform actually
  treats a non-zero script exit as "unhealthy"/restart-eligible the way
  this fix assumes -- since this redeploy only exercised the successful
  startup path, never a deliberately broken one (e.g. an unreachable
  `DATABASE_URL`). That specific scenario still needs a deliberate test,
  ideally against a non-production Repl first.

## Not automatable from this session (need a human with repo admin)

Branch protection on `main`, Dependabot security alerts (separate from
the version-update PRs, which do activate automatically), and native
GitHub secret scanning all need to be toggled in GitHub's Settings UI by
someone with admin access. Full detail in
`docs/AI_ENGINEERING_CONTROLS.md`.

## Next smallest task (if continuing past this MVP)

Real Underdog line acquisition (pending a confirmed ToS-compliant
method), a paid/official MLB data vendor, umpire data, and Phase-4-scope
work (ADR 0007's fuller admin action state machine, calibrating
`DECISION_EDGE_THRESHOLD` against real backtested performance) are the
handbook's explicitly unresolved product decisions this build built
around rather than guessed at — each is a clean adapter/seam swap, not a
rearchitecture.

The model artifact + registry system (`db/models/registry.py`,
`registry/service.py`, `cassandra train-final-model`/`promote-model`/
`rollback-model`/`model-status`) is now fully wired into the live
pipeline (Phase 4 of `docs/FINAL_COMPLETION_WORKLOG.md`) — a human can
train, evaluate, register, promote, and roll back a real challenger,
with `run_slate()` actually serving whichever model is `ACTIVE` and the
permanent baseline as the structurally-guaranteed fallback. The natural
next slice from here: a shadow-mode runner that evaluates a `CANDIDATE`
against live slates without its predictions ever reaching
`projections`/`grades` (lets a human compare a challenger's real-world
behavior before promoting it, beyond what backtested walk-forward
validation already shows), and a second model family
(negative-binomial/gradient-boosted) to actually exercise
`SUPPORTED_LIVE_MODEL_FAMILIES`' multi-family design. None of this was
invented here — it's flagged as real, well-scoped future work, not
guessed at silently.
