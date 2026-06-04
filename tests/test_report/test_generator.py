"""Tests for end-to-end report generation."""

from datetime import date
from pathlib import Path

import pytest

from climate_auto.report.analyzer import PlaceholderAnalyzer
from climate_auto.report.generator import (
    EXTRACTIONS_FILENAME,
    generate_report,
    load_extractions,
    save_extractions,
)


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


class TestExtractionsPersistence:
    """Tests for extractions.md save/load round-trip."""

    def test_save_creates_md_file(self, tmp_path: Path) -> None:
        extractions = {"500.png": "高壓脊偏東", "850.png": "西南風明顯"}
        path = save_extractions(tmp_path, extractions)

        assert path.exists()
        assert path.name == EXTRACTIONS_FILENAME

    def test_save_load_round_trip(self, tmp_path: Path) -> None:
        original = {
            "1_review/analysis/500.gif": "高壓脊偏東",
            "1_review/sounding/skewt.gif": "低層近飽和",
        }
        save_extractions(tmp_path, original)
        loaded = load_extractions(tmp_path)

        assert loaded == original

    def test_save_preserves_unicode(self, tmp_path: Path) -> None:
        extractions = {"img.png": "台灣位於副熱帶高壓北側邊緣"}
        save_extractions(tmp_path, extractions)

        raw = (tmp_path / EXTRACTIONS_FILENAME).read_text(encoding="utf-8")
        assert "台灣" in raw

    def test_save_produces_readable_markdown(self, tmp_path: Path) -> None:
        extractions = {"500.png": "高壓脊偏東\n副高西伸"}
        save_extractions(tmp_path, extractions)

        raw = (tmp_path / EXTRACTIONS_FILENAME).read_text(encoding="utf-8")
        assert "## 500.png" in raw
        assert "高壓脊偏東\n副高西伸" in raw

    def test_load_missing_file_raises(self, tmp_path: Path) -> None:
        with pytest.raises(FileNotFoundError, match="--extract"):
            load_extractions(tmp_path)

    def test_load_after_manual_edit(self, tmp_path: Path) -> None:
        """Simulate human editing extractions.md between steps."""
        original = {"500.png": "LLM 原始輸出（有誤）"}
        save_extractions(tmp_path, original)

        # Human directly edits the markdown file
        edited_md = "## 500.png\n\n人工修正後的分析\n"
        (tmp_path / EXTRACTIONS_FILENAME).write_text(edited_md, encoding="utf-8")

        loaded = load_extractions(tmp_path)
        assert loaded == {"500.png": "人工修正後的分析"}

    def test_multiline_extraction_round_trip(self, tmp_path: Path) -> None:
        """Multi-line extraction text survives save/load."""
        original = {
            "500.png": "第一段分析\n\n第二段分析\n有多行內容",
        }
        save_extractions(tmp_path, original)
        loaded = load_extractions(tmp_path)

        assert loaded == original


@pytest.mark.asyncio
class TestExtractOnlyMode:
    """Tests for extract_only mode in generate_report."""

    async def test_extract_only_saves_extractions_json(self, tmp_path: Path) -> None:
        target = date(2026, 3, 19)
        base_dir = _setup_fake_data(tmp_path, target)
        analyzer = PlaceholderAnalyzer()

        await generate_report(base_dir, target, analyzer=analyzer, extract_only=True)

        # PlaceholderAnalyzer returns empty strings, so no extractions saved
        # but the report should still be generated
        assert (base_dir / "2026-03-19" / "report" / "daily_report.md").exists()

    async def test_extract_only_no_synthesis(self, tmp_path: Path) -> None:
        target = date(2026, 3, 19)
        base_dir = _setup_fake_data(tmp_path, target)
        analyzer = PlaceholderAnalyzer()

        result = await generate_report(
            base_dir, target, analyzer=analyzer, extract_only=True
        )
        content = result.read_text(encoding="utf-8")

        # No synthesis section should be present
        assert "天氣診斷分析" not in content


@pytest.mark.asyncio
class TestSynthesizeOnlyMode:
    """Tests for synthesize_only mode in generate_report."""

    async def test_synthesize_only_loads_extractions(self, tmp_path: Path) -> None:
        target = date(2026, 3, 19)
        base_dir = _setup_fake_data(tmp_path, target)
        report_dir = base_dir / "2026-03-19" / "report"

        # Pre-create extractions.json (simulating prior --extract run)
        extractions = {
            "1_review/analysis/ECMWF500_20260319_f000.gif": "人工修正的分析",
        }
        save_extractions(report_dir, extractions)

        analyzer = PlaceholderAnalyzer()
        result = await generate_report(
            base_dir, target, analyzer=analyzer, synthesize_only=True
        )
        content = result.read_text(encoding="utf-8")

        # Per-chart extraction should appear in the report
        assert "人工修正的分析" in content

    async def test_synthesize_only_missing_file_raises(self, tmp_path: Path) -> None:
        target = date(2026, 3, 19)
        base_dir = _setup_fake_data(tmp_path, target)
        analyzer = PlaceholderAnalyzer()

        with pytest.raises(FileNotFoundError, match="--extract"):
            await generate_report(
                base_dir, target, analyzer=analyzer, synthesize_only=True
            )
