"""historical/park_factors.py's ParkFactorAccumulator -- pure logic, no DB
needed. The critical property under test: a game's own outcome (and any
later game's) must never be visible to its own park factor."""

from __future__ import annotations

from cassandra.historical.park_factors import (
    MIN_BATTERS_FACED_FOR_PARK_FACTOR,
    NEUTRAL_PARK_FACTOR,
    PARK_FACTOR_BOUNDS,
    ParkFactorAccumulator,
)

VENUE_A = 1
VENUE_B = 2


def test_no_history_at_all_reports_unavailable():
    acc = ParkFactorAccumulator()
    result = acc.park_factor_for(VENUE_A)
    assert result.available is False
    assert result.value == NEUTRAL_PARK_FACTOR
    assert result.venue_batters_faced == 0


def test_unknown_venue_reports_unavailable():
    acc = ParkFactorAccumulator()
    # Seed enough league history for some OTHER venue.
    for _ in range(5):
        acc.record_outcome(VENUE_B, MIN_BATTERS_FACED_FOR_PARK_FACTOR, 20)
    assert acc.park_factor_for(None).available is False
    assert acc.park_factor_for(999).available is False


def test_below_min_batters_faced_threshold_reports_unavailable():
    acc = ParkFactorAccumulator()
    acc.record_outcome(VENUE_A, MIN_BATTERS_FACED_FOR_PARK_FACTOR - 1, 50)
    result = acc.park_factor_for(VENUE_A)
    assert result.available is False
    assert result.value == NEUTRAL_PARK_FACTOR


def test_a_game_never_sees_its_own_outcome_in_its_own_park_factor():
    acc = ParkFactorAccumulator()
    # A different venue's history establishes a league-wide baseline rate
    # distinct from VENUE_A's -- without this, VENUE_A's own accumulated
    # stats WOULD BE the entire league total, making venue_rate/league_rate
    # trivially 1.0 regardless of what leaked in, which would make this
    # test unable to detect a real leak.
    acc.record_outcome(VENUE_B, 10_000, 2_000)  # 20% league baseline K rate
    # Enough prior history at VENUE_A, at that same 20% rate, to clear the
    # sample-size threshold.
    venue_k = int(MIN_BATTERS_FACED_FOR_PARK_FACTOR * 0.20)
    acc.record_outcome(VENUE_A, MIN_BATTERS_FACED_FOR_PARK_FACTOR, venue_k)

    before = acc.park_factor_for(VENUE_A)
    assert before.available is True
    assert before.value == 1.0  # matches the league rate so far -- neutral

    # This game's own huge outcome (way above the league rate) must not
    # affect the factor it itself was assigned -- `before` was already
    # read and asserted neutral above, before this call.
    acc.record_outcome(VENUE_A, 100, 100)  # 100% K rate, wildly non-neutral

    # A LATER game at the same venue DOES see that outcome folded in now --
    # proving record_outcome really did register it, just never for the
    # game that produced it.
    after = acc.park_factor_for(VENUE_A)
    assert after.value > before.value


def test_park_factor_is_clipped_to_the_bounds():
    acc = ParkFactorAccumulator()
    # League-wide: mostly a normal K rate at another venue.
    acc.record_outcome(VENUE_B, 10_000, 2_200)
    # VENUE_A: a wildly extreme K rate that would blow past the clip band
    # if left unclipped.
    acc.record_outcome(VENUE_A, MIN_BATTERS_FACED_FOR_PARK_FACTOR, MIN_BATTERS_FACED_FOR_PARK_FACTOR)

    result = acc.park_factor_for(VENUE_A)
    assert result.available is True
    lo, hi = PARK_FACTOR_BOUNDS
    assert lo <= result.value <= hi
    assert result.value == hi  # clipped at the upper bound


def test_record_outcome_ignores_rows_with_missing_fields():
    acc = ParkFactorAccumulator()
    acc.record_outcome(None, 20, 6)  # no venue -- must not corrupt league totals
    acc.record_outcome(VENUE_A, None, 6)  # no batters_faced
    acc.record_outcome(VENUE_A, 20, None)  # no strikeouts
    assert acc.park_factor_for(VENUE_A).venue_batters_faced == 0


def test_chronological_accumulation_only_sees_strictly_prior_games():
    """Simulates the dataset builder's actual usage: park_factor_for()
    called BEFORE record_outcome() for each row, in date order. 20 BF per
    game, MIN_BATTERS_FACED_FOR_PARK_FACTOR=400 -- the threshold clears
    only once 20 STRICTLY PRIOR games have been recorded (accumulated
    BEFORE this call), so the 21st game in the sequence is the first to
    see `available=True`; one extra game is included past that point to
    also prove it stays true, not just flips once."""
    acc = ParkFactorAccumulator()
    acc.record_outcome(VENUE_B, 10_000, 2_000)  # league baseline, a different venue

    seen_available_flags = []
    for _ in range(22):
        result = acc.park_factor_for(VENUE_A)
        seen_available_flags.append(result.available)
        acc.record_outcome(VENUE_A, 20, 4)

    assert seen_available_flags[0] is False
    assert seen_available_flags[-1] is True
    # Monotonic: once available, never flips back to unavailable within
    # this run (accumulated history only ever grows).
    first_true = seen_available_flags.index(True)
    assert all(seen_available_flags[first_true:])
