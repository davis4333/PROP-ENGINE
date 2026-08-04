# Demo slate: 2023-06-15

A real MLB slate, chosen because it's already covered by
`tests/fixtures/mlb_api/`'s saved API responses (schedule, weather,
Kikuchi's/Wells's/Nola's game logs, and two games' final live-feed box
scores). `scripts/seed_demo_slate.py` replays it end to end (ingest →
freeze → project → decide → publish, then grade) using these fixtures
via `respx`, so the demo is deterministic and offline -- no live network
call can retroactively serve `probablePitcher` data for a game that's
already `Final` (confirmed empirically), which is exactly why this can't
just be `cassandra run-slate 2023-06-15` against the live MLB Stats API.

`lines_2023-06-15.json` is a hand-picked, real-outcome-aware
`lines_manual` drop file covering 4 of the slate's 20 real probable
starters. The other 16 get no line and fall out as `NO_PLAY`/`REJECTED`
(`MARKET_CONTEXT_INCOMPLETE`) -- itself part of the demo, showing the
transparency principle (every evaluated projection is logged, not just
picks) without needing curated data for all of them.

The 4 chosen lines, against each pitcher's real recorded outcome that
day, deliberately produce one of each required grade:

| Pitcher | Game | Line | Model mean (real recent-starts data) | Decision | Actual K | Grade |
|---|---|---|---|---|---|---|
| Yusei Kikuchi (579328) | 717753 (TOR @ BAL) | 3.5 | ~4.9 | OVER, QUALIFIED | 7 | **WIN** |
| Tyler Wells (669330) | 717753 (TOR @ BAL) | 6.5 | ~6.2 | UNDER, QUALIFIED | 8 | **LOSS** |
| Aaron Nola (605400) | 717755 (PHI @ ARI) | 9.0 | ~7.6 | UNDER, QUALIFIED | 9 | **PUSH** |
| Ryne Nelson (669194) | 717755 (PHI @ ARI) | 5.5 | ~5.4 (league-default fallback -- no prior-start fixture for him) | UNDER, QUALIFIED | 5 | **WIN** |

Model means are the baseline Poisson model's real output against real
saved game-log data as of this session; re-derive with
`scripts/seed_demo_slate.py --dry-run` if the model formula changes.
