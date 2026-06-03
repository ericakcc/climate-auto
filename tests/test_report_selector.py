"""Tests for report folder selection."""

from datetime import date
from pathlib import Path

from climate_auto.report_selector import build_report_folder
from climate_auto.storage import get_date_dir


def test_build_report_folder_preserves_extractions(tmp_path: Path) -> None:
    """Human-edited extractions.md must survive a report-folder rebuild."""
    target_date = date(2026, 3, 19)
    report_dir = get_date_dir(tmp_path, target_date) / "report"
    report_dir.mkdir(parents=True)
    edited = report_dir / "extractions.md"
    edited.write_text("human-edited content", encoding="utf-8")

    build_report_folder(tmp_path, target_date)

    assert edited.exists()
    assert edited.read_text(encoding="utf-8") == "human-edited content"


def test_build_report_folder_clears_stale_charts(tmp_path: Path) -> None:
    """Stale chart subfolders from a previous run must be cleared."""
    target_date = date(2026, 3, 19)
    report_dir = get_date_dir(tmp_path, target_date) / "report"
    stale = report_dir / "1_review" / "analysis"
    stale.mkdir(parents=True)
    (stale / "old.gif").write_bytes(b"GIF89a")

    build_report_folder(tmp_path, target_date)

    assert not (report_dir / "1_review" / "analysis" / "old.gif").exists()
