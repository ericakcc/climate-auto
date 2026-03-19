"""Tests for end-to-end report generation."""

from datetime import date
from pathlib import Path

import pytest

from climate_auto.report.analyzer import PlaceholderAnalyzer
from climate_auto.report.generator import generate_report


def _setup_fake_data(tmp_path: Path, target_date: date) -> Path:
    """Create a fake data directory with report images."""
    date_dir = tmp_path / target_date.isoformat()
    report_dir = date_dir / "report"

    # Create some chart images
    for subfolder, filename in [
        ("1_review/analysis", "ECMWF500_20260319_f000.gif"),
        ("1_review/analysis", "ECMWF850_20260319_f000.gif"),
        ("1_review/sounding", "skewt_Taipei_20260319.gif"),
        ("2_f24h", "ECMWF500_20260319_f024.gif"),
        ("4_context/mjo", "mjo_rmm.phase.Last40days.gif"),
    ]:
        d = report_dir / subfolder
        d.mkdir(parents=True, exist_ok=True)
        (d / filename).write_bytes(b"GIF89a")

    return tmp_path


@pytest.mark.asyncio
class TestGenerateReport:
    async def test_generates_markdown_file(self, tmp_path: Path) -> None:
        target = date(2026, 3, 19)
        base_dir = _setup_fake_data(tmp_path, target)

        result = await generate_report(base_dir, target)

        assert result.exists()
        assert result.name == "daily_report.md"

    async def test_output_contains_expected_content(self, tmp_path: Path) -> None:
        target = date(2026, 3, 19)
        base_dir = _setup_fake_data(tmp_path, target)

        result = await generate_report(base_dir, target)
        content = result.read_text(encoding="utf-8")

        assert "TACOCO" in content
        assert "2026-03-19" in content
        assert "當日回顧" in content
        assert "![500hPa analysis]" in content

    async def test_with_placeholder_analyzer(self, tmp_path: Path) -> None:
        target = date(2026, 3, 19)
        base_dir = _setup_fake_data(tmp_path, target)

        analyzer = PlaceholderAnalyzer()
        result = await generate_report(base_dir, target, analyzer=analyzer)
        content = result.read_text(encoding="utf-8")

        assert "*待分析*" in content

    async def test_raises_if_no_report_dir(self, tmp_path: Path) -> None:
        target = date(2026, 3, 19)
        date_dir = tmp_path / target.isoformat()
        date_dir.mkdir(parents=True)
        # No report/ subfolder

        with pytest.raises(FileNotFoundError, match="Report directory not found"):
            await generate_report(tmp_path, target)

    async def test_report_in_correct_location(self, tmp_path: Path) -> None:
        target = date(2026, 3, 19)
        base_dir = _setup_fake_data(tmp_path, target)

        result = await generate_report(base_dir, target)

        expected = base_dir / "2026-03-19" / "report" / "daily_report.md"
        assert result == expected
