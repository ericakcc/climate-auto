"""Tests for NCDR ECMWF scraper."""

from climate_auto.config import NcdrEcmwfConfig
from climate_auto.scrapers.ncdr_ecmwf import NcdrEcmwfScraper


def test_build_chart_url() -> None:
    config = NcdrEcmwfConfig()
    scraper = NcdrEcmwfScraper(config)
    url = scraper._build_chart_url("2026031812", "500", 24)
    assert url == (
        "https://watch.ncdr.nat.gov.tw/00_Wxmap/2F7_ECMWF_0.25deg"
        "/202603/2026031812/ECMWF500_2026031812_f024.gif"
    )


def test_build_daily_rain_url() -> None:
    config = NcdrEcmwfConfig()
    scraper = NcdrEcmwfScraper(config)
    url = scraper._build_daily_rain_url("2026031812", 2)
    assert url == (
        "https://watch.ncdr.nat.gov.tw/00_Wxmap/2F7_ECMWF_0.25deg"
        "/202603/2026031812/dailyrn_2026031812_2.png"
    )


def test_build_ensemble_rain_url() -> None:
    config = NcdrEcmwfConfig()
    scraper = NcdrEcmwfScraper(config)
    url = scraper._build_ensemble_rain_url("2026031812", 3)
    assert url == (
        "https://watch.ncdr.nat.gov.tw/00_Wxmap/2F7_ECMWF_0.25deg"
        "/202603/2026031812/dailyensrn_2026031812_3_fdmx.png"
    )
