"""Tests for storage management."""

from datetime import date
from pathlib import Path

from climate_auto.models import CollectionManifest, SourceName
from climate_auto.storage import (
    ensure_source_dir,
    get_date_dir,
    load_manifest,
    save_manifest,
)


def test_get_date_dir() -> None:
    result = get_date_dir(Path("/tmp/data"), date(2026, 3, 19))
    assert result == Path("/tmp/data/2026-03-19")


def test_ensure_source_dir(tmp_path: Path) -> None:
    result = ensure_source_dir(tmp_path, date(2026, 3, 19), SourceName.NCDR_ECMWF)
    assert result.exists()
    assert result == tmp_path / "2026-03-19" / "ncdr_ecmwf"


def test_save_and_load_manifest(tmp_path: Path) -> None:
    target_date = date(2026, 3, 19)
    manifest = CollectionManifest(date="2026-03-19")

    save_manifest(tmp_path, target_date, manifest)
    loaded = load_manifest(tmp_path, target_date)

    assert loaded is not None
    assert loaded.date == "2026-03-19"


def test_load_manifest_not_found(tmp_path: Path) -> None:
    result = load_manifest(tmp_path, date(2026, 1, 1))
    assert result is None
