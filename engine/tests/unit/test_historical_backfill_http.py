"""historical/backfill.py's pure/HTTP-level logic -- date-range and season
enumeration, and the bounded-retry/backoff/jitter request helper -- tested
without a database (see tests/integration/test_historical_backfill.py for
the DB-touching idempotency/resumability/leakage-isolation tests)."""

from __future__ import annotations

from datetime import date

import httpx
import pytest
import respx

from cassandra.historical.backfill import (
    BackfillConfig,
    _request_with_retry,
    _season_window,
    enumerate_date_range,
    seasons_in_range,
)

# --- date-range enumeration --------------------------------------------


def test_enumerate_date_range_inclusive_single_day():
    assert enumerate_date_range(date(2023, 4, 3), date(2023, 4, 3)) == [date(2023, 4, 3)]


def test_enumerate_date_range_spans_multiple_days():
    result = enumerate_date_range(date(2023, 4, 1), date(2023, 4, 4))
    assert result == [date(2023, 4, 1), date(2023, 4, 2), date(2023, 4, 3), date(2023, 4, 4)]


def test_enumerate_date_range_rejects_end_before_start():
    with pytest.raises(ValueError, match="must not be after"):
        enumerate_date_range(date(2023, 4, 4), date(2023, 4, 1))


def test_seasons_in_range_single_season():
    assert seasons_in_range(date(2023, 3, 1), date(2023, 11, 1)) == [2023]


def test_seasons_in_range_spans_multiple_years():
    assert seasons_in_range(date(2023, 6, 1), date(2025, 6, 1)) == [2023, 2024, 2025]


def test_backfill_config_rejects_end_before_start():
    with pytest.raises(ValueError, match="must not be after"):
        BackfillConfig(start_date=date(2023, 6, 1), end_date=date(2023, 1, 1))


def test_season_window_clips_to_requested_range():
    # A season-spanning request should still clip to what was actually
    # asked for, not always return the full calendar year -- this is
    # exactly the distinction whose absence caused a real bug (an early
    # narrow-window discovery silently "covering" a later wider request
    # for the same season, fixed by keying backfill_items on the window,
    # not just the season -- see the integration tests).
    assert _season_window(2023, date(2023, 5, 1), date(2023, 5, 31)) == (date(2023, 5, 1), date(2023, 5, 31))
    assert _season_window(2023, date(2022, 6, 1), date(2024, 6, 1)) == (date(2023, 1, 1), date(2023, 12, 31))


# --- bounded retry / backoff / jitter -----------------------------------


@respx.mock
def test_request_with_retry_succeeds_on_first_try():
    route = respx.get("https://example.test/ok").mock(return_value=httpx.Response(200, json={"ok": True}))
    response = _request_with_retry(
        httpx.Client(), "https://example.test/ok", max_retries=3, request_delay=0.0
    )
    assert response is not None
    assert response.status_code == 200
    assert route.call_count == 1


@respx.mock
def test_request_with_retry_retries_429_then_succeeds(monkeypatch):
    monkeypatch.setattr("cassandra.historical.backfill._sleep_with_jitter", lambda _delay: None)
    route = respx.get("https://example.test/quota").mock(
        side_effect=[httpx.Response(429), httpx.Response(429), httpx.Response(200, json={"ok": True})]
    )
    response = _request_with_retry(
        httpx.Client(), "https://example.test/quota", max_retries=5, request_delay=0.0
    )
    assert response is not None
    assert response.status_code == 200
    assert route.call_count == 3


@respx.mock
def test_request_with_retry_retries_5xx_then_succeeds(monkeypatch):
    monkeypatch.setattr("cassandra.historical.backfill._sleep_with_jitter", lambda _delay: None)
    route = respx.get("https://example.test/flaky").mock(
        side_effect=[httpx.Response(503), httpx.Response(200, json={"ok": True})]
    )
    response = _request_with_retry(
        httpx.Client(), "https://example.test/flaky", max_retries=5, request_delay=0.0
    )
    assert response is not None
    assert route.call_count == 2


@respx.mock
def test_request_with_retry_gives_up_after_max_retries(monkeypatch):
    monkeypatch.setattr("cassandra.historical.backfill._sleep_with_jitter", lambda _delay: None)
    route = respx.get("https://example.test/down").mock(return_value=httpx.Response(500))
    response = _request_with_retry(
        httpx.Client(), "https://example.test/down", max_retries=3, request_delay=0.0
    )
    assert response is None
    assert route.call_count == 3


@respx.mock
def test_request_with_retry_does_not_retry_permanent_4xx():
    # A 404 will never succeed no matter how many times it's retried --
    # retrying it anyway would just waste calls against a free public API
    # this backfill is trying to be a conservative citizen of.
    route = respx.get("https://example.test/missing").mock(return_value=httpx.Response(404))
    response = _request_with_retry(
        httpx.Client(), "https://example.test/missing", max_retries=5, request_delay=0.0
    )
    assert response is None
    assert route.call_count == 1


@respx.mock
def test_request_with_retry_retries_transport_errors(monkeypatch):
    monkeypatch.setattr("cassandra.historical.backfill._sleep_with_jitter", lambda _delay: None)
    route = respx.get("https://example.test/timeout").mock(
        side_effect=[httpx.ConnectTimeout("boom"), httpx.Response(200, json={"ok": True})]
    )
    response = _request_with_retry(
        httpx.Client(), "https://example.test/timeout", max_retries=5, request_delay=0.0
    )
    assert response is not None
    assert route.call_count == 2
