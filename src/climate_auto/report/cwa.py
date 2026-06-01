"""CWA OpenData surface-station observation adapter (route 2, observed data).

Pulls *numeric* current surface observations (temperature, humidity, wind,
pressure, rainfall) from CWA OpenData ``O-A0001-001`` — the numeric basis for
the report's 1-IV surface section, instead of reading station plots.

Requires a CWA Authorization key (``CWA_API_KEY`` in ``.env``; see
``Settings.cwa_api_key``). This is a *current-hour snapshot*; intra-day time
series (e.g. sea-breeze onset timing) needs CODiS, which is not a simple API.

Network I/O lives in :func:`fetch_cwa_surface`; parsing/formatting are pure.
"""

from __future__ import annotations

from typing import Any

import httpx
from loguru import logger
from pydantic import BaseModel

_O_A0001 = "https://opendata.cwa.gov.tw/api/v1/rest/datastore/O-A0001-001"

# Default Taipei-basin stations of interest (matched against StationName).
TAIPEI_BASIN_STATIONS: list[str] = ["臺北", "板橋", "淡水", "新店", "汐止", "南港"]


class StationObs(BaseModel):
    """A single surface station's current observation (numeric)."""

    station_id: str
    station_name: str
    county: str | None = None
    obs_time: str | None = None
    temperature_c: float | None = None
    relative_humidity: float | None = None
    wind_dir_deg: float | None = None
    wind_speed_ms: float | None = None
    pressure_hpa: float | None = None
    precip_mm: float | None = None


def _num(value: Any) -> float | None:
    """Parse a CWA numeric string, mapping missing sentinels/trace to None/0.

    Args:
        value: Raw value from the API (string or number).

    Returns:
        Parsed float, 0.0 for trace ("T"), or None if missing/invalid.
    """
    if value is None:
        return None
    text = str(value).strip()
    if text in {"T", "t"}:  # trace precipitation
        return 0.0
    try:
        num = float(text)
    except ValueError:
        return None
    # CWA uses -99 / -990 / -99.0 etc. as missing markers.
    return None if num <= -90 else num


def _parse_station(raw: dict[str, Any]) -> StationObs:
    """Parse one ``records.Station`` entry into a :class:`StationObs`."""
    we = raw.get("WeatherElement", {})
    now = we.get("Now", {})
    geo = raw.get("GeoInfo", {})
    return StationObs(
        station_id=raw.get("StationId", ""),
        station_name=raw.get("StationName", ""),
        county=geo.get("CountyName"),
        obs_time=(raw.get("ObsTime") or {}).get("DateTime"),
        temperature_c=_num(we.get("AirTemperature")),
        relative_humidity=_num(we.get("RelativeHumidity")),
        wind_dir_deg=_num(we.get("WindDirection")),
        wind_speed_ms=_num(we.get("WindSpeed")),
        pressure_hpa=_num(we.get("AirPressure")),
        precip_mm=_num(now.get("Precipitation")),
    )


def fetch_cwa_surface(
    api_key: str,
    station_names: list[str] | None = None,
    *,
    timeout: float = 40.0,
) -> list[StationObs]:
    """Fetch current surface observations for stations matching given names.

    Args:
        api_key: CWA OpenData Authorization key.
        station_names: Substrings to match against ``StationName`` (defaults to
            :data:`TAIPEI_BASIN_STATIONS`). Empty list returns all stations.
        timeout: HTTP timeout in seconds.

    Returns:
        List of parsed :class:`StationObs` for the matched stations.

    Raises:
        httpx.HTTPStatusError: On a non-2xx response (e.g. 401 bad key).
    """
    wanted = TAIPEI_BASIN_STATIONS if station_names is None else station_names
    resp = httpx.get(
        _O_A0001,
        params={"Authorization": api_key, "format": "JSON"},
        timeout=timeout,
    )
    resp.raise_for_status()
    stations = resp.json().get("records", {}).get("Station", [])

    parsed = [_parse_station(s) for s in stations]
    if wanted:
        parsed = [
            obs for obs in parsed if any(name in obs.station_name for name in wanted)
        ]
    logger.info("CWA surface obs: {} stations matched", len(parsed))
    return parsed


def format_station_obs(obs_list: list[StationObs]) -> str:
    """Format station observations as a Traditional-Chinese block.

    Args:
        obs_list: Parsed station observations.

    Returns:
        Multi-line text summary (one line per station).
    """
    if not obs_list:
        return "（CWA 地面測站：無匹配站點資料）"

    time = next((o.obs_time for o in obs_list if o.obs_time), "")
    lines = [f"（數值觀測，CWA 地面測站，{time}）"]
    for o in obs_list:

        def _n(v: float | None, unit: str) -> str:
            return "n/a" if v is None else f"{v:g}{unit}"

        lines.append(
            f"- {o.station_name}：氣溫 {_n(o.temperature_c, '°C')}、"
            f"濕度 {_n(o.relative_humidity, '%')}、"
            f"風 {_n(o.wind_dir_deg, '°')}/{_n(o.wind_speed_ms, 'm/s')}、"
            f"氣壓 {_n(o.pressure_hpa, 'hPa')}、"
            f"時雨量 {_n(o.precip_mm, 'mm')}"
        )
    return "\n".join(lines)
