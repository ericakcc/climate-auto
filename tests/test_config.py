"""Tests for configuration loading."""

from pathlib import Path

from climate_auto.config import Settings, load_settings


def test_default_settings() -> None:
    s = Settings()
    assert s.data_dir == Path("./data")
    assert s.max_retries == 3
    assert s.sources.ncdr_ecmwf.enabled is True
    assert "500" in s.sources.ncdr_ecmwf.variables


def test_load_settings_default() -> None:
    s = load_settings(None)
    assert s.max_concurrent_downloads == 3


def test_load_settings_from_yaml(tmp_path: Path) -> None:
    config_file = tmp_path / "test_settings.yaml"
    config_file.write_text("max_retries: 5\nrequest_timeout_seconds: 60.0\n")
    s = load_settings(config_file)
    assert s.max_retries == 5
    assert s.request_timeout_seconds == 60.0


def test_ncdr_ecmwf_config_defaults() -> None:
    s = Settings()
    ecmwf = s.sources.ncdr_ecmwf
    assert ecmwf.base_url == "https://watch.ncdr.nat.gov.tw"
    assert "850mf" in ecmwf.variables
    assert 0 in ecmwf.forecast_hours
    assert 48 in ecmwf.forecast_hours
