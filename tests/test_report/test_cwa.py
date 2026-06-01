"""Offline tests for the CWA surface-station adapter (parsing/formatting)."""

from climate_auto.report.cwa import StationObs, _parse_station, format_station_obs

_RAW = {
    "StationName": "板橋",
    "StationId": "466880",
    "ObsTime": {"DateTime": "2026-06-01T14:00:00+08:00"},
    "GeoInfo": {"CountyName": "新北市"},
    "WeatherElement": {
        "Now": {"Precipitation": "T"},  # trace → 0.0
        "WindDirection": "347.0",
        "WindSpeed": "3.9",
        "AirTemperature": "27.5",
        "RelativeHumidity": "72",
        "AirPressure": "1003.9",
        "GustInfo": {"PeakGustSpeed": "-99"},
    },
}


def test_parse_station_maps_fields_and_sentinels() -> None:
    """A raw station entry parses into typed values; trace → 0.0."""
    obs = _parse_station(_RAW)

    assert obs.station_name == "板橋"
    assert obs.county == "新北市"
    assert obs.temperature_c == 27.5
    assert obs.relative_humidity == 72.0
    assert obs.wind_speed_ms == 3.9
    assert obs.pressure_hpa == 1003.9
    assert obs.precip_mm == 0.0  # "T" trace


def test_parse_station_missing_sentinel_becomes_none() -> None:
    """CWA -99 missing markers parse to None, not -99."""
    raw = {
        "StationName": "X",
        "StationId": "X",
        "WeatherElement": {"AirTemperature": "-99", "RelativeHumidity": "-990"},
    }
    obs = _parse_station(raw)
    assert obs.temperature_c is None
    assert obs.relative_humidity is None


def test_format_station_obs_is_chinese_and_lists_stations() -> None:
    """Formatter lists each station with its numeric values."""
    obs = [
        StationObs(
            station_id="466880",
            station_name="板橋",
            obs_time="2026-06-01T14:00:00+08:00",
            temperature_c=27.5,
            relative_humidity=72.0,
            precip_mm=0.0,
        )
    ]
    text = format_station_obs(obs)
    assert "地面測站" in text
    assert "板橋" in text and "27.5" in text


def test_format_station_obs_empty() -> None:
    """No matched stations yields a clear placeholder, not a crash."""
    assert "無匹配" in format_station_obs([])
