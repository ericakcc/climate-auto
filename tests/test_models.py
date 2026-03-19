"""Tests for data models."""

from climate_auto.models import (
    CollectionManifest,
    DownloadResult,
    DownloadStatus,
    ProductInfo,
    ScraperReport,
    SourceName,
)


def test_product_info_creation() -> None:
    p = ProductInfo(
        source=SourceName.NCDR_ECMWF,
        name="ECMWF 500 f000",
        url="https://example.com/img.gif",
        filename="test.gif",
    )
    assert p.source == SourceName.NCDR_ECMWF
    assert p.filename == "test.gif"


def test_download_result_success() -> None:
    p = ProductInfo(
        source=SourceName.NCDR_ECMWF,
        name="test",
        url="https://example.com/img.gif",
        filename="test.gif",
    )
    r = DownloadResult(
        product=p,
        status=DownloadStatus.SUCCESS,
        file_size=1024,
        http_status=200,
    )
    assert r.status == DownloadStatus.SUCCESS
    assert r.file_size == 1024


def test_scraper_report_counts() -> None:
    report = ScraperReport(
        source=SourceName.NCDR_ECMWF,
        total=10,
        success=8,
        failed=1,
        skipped=1,
    )
    assert report.total == 10
    assert report.success == 8


def test_manifest_serialization() -> None:
    manifest = CollectionManifest(date="2026-03-19")
    data = manifest.model_dump(mode="json")
    assert data["date"] == "2026-03-19"
    assert data["reports"] == []
    # Round-trip
    loaded = CollectionManifest(**data)
    assert loaded.date == manifest.date
