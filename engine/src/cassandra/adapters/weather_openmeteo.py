"""Open-Meteo weather adapter -- free, no key. Uses the forecast endpoint
for today-or-future slates and the historical archive endpoint for past
slates (Open-Meteo's forecast API only serves a rolling near-term window;
backtests/fixtures need the archive API instead).

Needs venue lat/lon/game-time context, passed via
`fetch(..., venues=[{"venue_id": <raw MLB venue id, int>, "lat":..., "lon":..., "game_time_utc":...}, ...])`.
"""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any

import httpx

from cassandra.adapters.base import AdapterFetchResult, RawRecord, SourceAdapter
from cassandra.db.models.raw import RawWeatherObservation
from cassandra.identity_ids import mlb_venue_id

FORECAST_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"


class WeatherOpenMeteoAdapter(SourceAdapter):
    kind = "weather"
    source_name = "open_meteo"
    adapter_version = "0.1.0"
    raw_model = RawWeatherObservation

    def __init__(self, http_client: httpx.Client | None = None) -> None:
        self._client = http_client or httpx.Client(timeout=10.0)

    def fetch(self, *, slate_date: date, as_of: datetime | None = None, **kwargs: Any) -> AdapterFetchResult:
        fetched_at = datetime.now(UTC)
        venues: list[dict[str, Any]] = kwargs.get("venues") or []
        if not venues:
            return AdapterFetchResult(
                records=[],
                fetched_at=fetched_at,
                is_available=False,
                warnings=["No venues supplied -- nothing to fetch weather for"],
            )

        is_historical = slate_date < datetime.now(UTC).date()
        url = ARCHIVE_URL if is_historical else FORECAST_URL

        records: list[RawRecord] = []
        warnings: list[str] = []
        for venue in venues:
            mlb_id = venue["venue_id"]  # raw MLB venue id (int)
            venue_id = mlb_venue_id(mlb_id)  # our string identity id
            try:
                response = self._client.get(
                    url,
                    params={
                        "latitude": venue["lat"],
                        "longitude": venue["lon"],
                        "hourly": "temperature_2m,wind_speed_10m,wind_direction_10m",
                        "start_date": slate_date.isoformat(),
                        "end_date": slate_date.isoformat(),
                        "temperature_unit": "fahrenheit",
                        "wind_speed_unit": "mph",
                    },
                )
                response.raise_for_status()
                payload = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                warnings.append(f"Weather fetch failed for venue {venue_id}: {exc}")
                continue

            hourly = payload.get("hourly", {})
            times = hourly.get("time", [])
            game_time_utc: datetime | None = venue.get("game_time_utc")
            hour_index = _closest_hour_index(times, game_time_utc)
            if hour_index is None:
                warnings.append(f"No hourly weather data returned for venue {venue_id}")
                continue

            records.append(
                RawRecord(
                    fields={
                        "venue_id": venue_id,
                        "forecast_for": game_time_utc or datetime.fromisoformat(times[hour_index]),
                        "temp_f": hourly.get("temperature_2m", [None] * len(times))[hour_index],
                        "wind_mph": hourly.get("wind_speed_10m", [None] * len(times))[hour_index],
                        "wind_dir": _compass(
                            hourly.get("wind_direction_10m", [None] * len(times))[hour_index]
                        ),
                    },
                    observed_at=fetched_at,
                    payload={"hour": times[hour_index], "raw": payload},
                )
            )

        if not records:
            return AdapterFetchResult(
                records=[],
                fetched_at=fetched_at,
                is_available=False,
                warnings=warnings or ["No weather records produced"],
            )
        return AdapterFetchResult(records=records, fetched_at=fetched_at, warnings=warnings)


def _closest_hour_index(times: list[str], game_time_utc: datetime | None) -> int | None:
    if not times:
        return None
    if game_time_utc is None:
        return 0
    target_hour = game_time_utc.replace(minute=0, second=0, microsecond=0)
    best_idx, best_diff = None, None
    for i, t in enumerate(times):
        try:
            candidate = datetime.fromisoformat(t).replace(tzinfo=UTC)
        except ValueError:
            continue
        diff = abs((candidate - target_hour).total_seconds())
        if best_diff is None or diff < best_diff:
            best_idx, best_diff = i, diff
    return best_idx


def _compass(degrees: float | None) -> str | None:
    if degrees is None:
        return None
    directions = ["N", "NE", "E", "SE", "S", "SW", "W", "NW"]
    return directions[round(degrees / 45) % 8]
