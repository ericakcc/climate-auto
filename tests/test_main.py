"""Smoke tests for the orchestrator (`run_collection`, scraper registry, CLI helpers)."""

from datetime import date
from pathlib import Path

import pytest
import respx
from httpx import Response

from climate_auto.config import Settings, SourcesConfig
from climate_auto.main import _build_scrapers, _parse_sources, run_collection
from climate_auto.models import SourceName


def _settings_with_only(tmp_path: Path, **enabled: bool) -> Settings:
    """Build a Settings instance with all sources disabled except the given ones."""
    sources = SourcesConfig()
    for src in (
        "ncdr_ecmwf",
        "ncdr_dwp",
        "ncdr_corrdiff",
        "cwa_main",
        "cwa_marine",
        "cwa_upper",
        "bom_mjo",
    ):
        getattr(sources, src).enabled = enabled.get(src, False)
    return Settings(data_dir=tmp_path, sources=sources)


def test_build_scrapers_respects_enabled_flag(tmp_path: Path) -> None:
    settings = _settings_with_only(tmp_path, ncdr_ecmwf=True, cwa_main=True)
    scrapers = _build_scrapers(settings)
    sources = {s.source for s in scrapers}
    assert sources == {SourceName.NCDR_ECMWF, SourceName.CWA_MAIN}


def test_build_scrapers_includes_optional_sources_when_enabled(tmp_path: Path) -> None:
    settings = _settings_with_only(tmp_path, bom_mjo=True, cwa_upper=True)
    scrapers = _build_scrapers(settings)
    sources = {s.source for s in scrapers}
    assert sources == {SourceName.BOM_MJO, SourceName.CWA_UPPER}


def test_build_scrapers_propagates_settings(tmp_path: Path) -> None:
    settings = _settings_with_only(tmp_path, ncdr_ecmwf=True)
    settings.max_retries = 7
    settings.max_concurrent_downloads = 9
    settings.request_timeout_seconds = 12.5
    [scraper] = _build_scrapers(settings)
    assert scraper.max_retries == 7
    assert scraper.max_concurrent == 9
    assert scraper.timeout == 12.5


def test_parse_sources_valid() -> None:
    parsed = _parse_sources(["ncdr_ecmwf", "cwa_main"])
    assert parsed == [SourceName.NCDR_ECMWF, SourceName.CWA_MAIN]


def test_parse_sources_invalid_raises_friendly_error() -> None:
    with pytest.raises(SystemExit) as exc:
        _parse_sources(["not_a_real_source"])
    msg = str(exc.value)
    assert "not_a_real_source" in msg
    assert "ncdr_ecmwf" in msg  # lists valid options


@pytest.mark.asyncio
@respx.mock
async def test_run_collection_dry_run_does_not_download(tmp_path: Path) -> None:
    """Dry-run should call discover but never write files or a manifest."""
    settings = _settings_with_only(tmp_path, ncdr_ecmwf=True)

    # ECMWF discover hits the date CSV endpoint once.
    respx.get(
        "https://watch.ncdr.nat.gov.tw/php/list_realtime_date_csv?v=CHART_ECMWF_FORECAST_0.25"
    ).mock(return_value=Response(200, text="CHART_ECMWF_FORECAST_0.25_date,202605091200"))

    manifest = await run_collection(date(2026, 5, 9), settings, dry_run=True)

    assert manifest.reports == []
    assert not (tmp_path / "2026-05-09" / "manifest.json").exists()
    # Source dir is created (ensure_source_dir runs) but should be empty.
    source_dir = tmp_path / "2026-05-09" / "ncdr_ecmwf"
    assert source_dir.exists()
    assert list(source_dir.iterdir()) == []
