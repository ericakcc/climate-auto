"""Tests for report image discovery."""

from pathlib import Path

from climate_auto.report.discovery import (
    _parse_target_subfolder,
    build_report_context,
)


class TestParseTargetSubfolder:
    def test_with_subsection(self) -> None:
        assert _parse_target_subfolder("1_review/analysis") == (
            "1_review",
            "analysis",
        )

    def test_without_subsection(self) -> None:
        assert _parse_target_subfolder("2_f24h") == ("2_f24h", None)

    def test_nested_subsection(self) -> None:
        assert _parse_target_subfolder("4_context/mjo") == ("4_context", "mjo")


def _create_fake_report(tmp_path: Path) -> Path:
    """Create a minimal fake report directory with test images."""
    report_dir = tmp_path / "report"

    # Section 1: analysis
    analysis_dir = report_dir / "1_review" / "analysis"
    analysis_dir.mkdir(parents=True)
    (analysis_dir / "ECMWF500_20260319_f000.gif").write_bytes(b"GIF89a")
    (analysis_dir / "ECMWF850mf_20260319_f000.gif").write_bytes(b"GIF89a")

    # Section 1: sounding
    sounding_dir = report_dir / "1_review" / "sounding"
    sounding_dir.mkdir(parents=True)
    (sounding_dir / "skewt_Taipei_20260319.gif").write_bytes(b"GIF89a")

    # Section 2: f24h
    f24h_dir = report_dir / "2_f24h"
    f24h_dir.mkdir(parents=True)
    (f24h_dir / "ECMWF500_20260319_f024.gif").write_bytes(b"GIF89a")

    # Section 4: MJO
    mjo_dir = report_dir / "4_context" / "mjo"
    mjo_dir.mkdir(parents=True)
    (mjo_dir / "mjo_rmm.phase.Last40days.gif").write_bytes(b"GIF89a")

    return report_dir


class TestBuildReportContext:
    def test_discovers_charts(self, tmp_path: Path) -> None:
        report_dir = _create_fake_report(tmp_path)
        ctx = build_report_context(report_dir, "2026-03-19")

        # Should find sections 1_review, 2_f24h, 4_context
        section_ids = [s.id for s in ctx.sections]
        assert "1_review" in section_ids
        assert "2_f24h" in section_ids
        assert "4_context" in section_ids

    def test_groups_subsections(self, tmp_path: Path) -> None:
        report_dir = _create_fake_report(tmp_path)
        ctx = build_report_context(report_dir, "2026-03-19")

        review = next(s for s in ctx.sections if s.id == "1_review")
        sub_ids = [sub.id for sub in review.subsections]
        assert "analysis" in sub_ids
        assert "sounding" in sub_ids

    def test_chart_relative_paths(self, tmp_path: Path) -> None:
        report_dir = _create_fake_report(tmp_path)
        ctx = build_report_context(report_dir, "2026-03-19")

        review = next(s for s in ctx.sections if s.id == "1_review")
        analysis = next(sub for sub in review.subsections if sub.id == "analysis")
        paths = [c.relative_path for c in analysis.charts]
        assert "1_review/analysis/ECMWF500_20260319_f000.gif" in paths

    def test_missing_patterns_tracked(self, tmp_path: Path) -> None:
        report_dir = _create_fake_report(tmp_path)
        ctx = build_report_context(report_dir, "2026-03-19")

        # Many patterns from REPORT_FILE_MAPPING won't match
        assert len(ctx.summary.missing_patterns) > 0

    def test_total_in_report(self, tmp_path: Path) -> None:
        report_dir = _create_fake_report(tmp_path)
        ctx = build_report_context(report_dir, "2026-03-19")

        assert ctx.summary.total_in_report == 5

    def test_empty_report_dir(self, tmp_path: Path) -> None:
        report_dir = tmp_path / "report"
        report_dir.mkdir()
        ctx = build_report_context(report_dir, "2026-03-19")

        assert ctx.sections == []
        assert ctx.summary.total_in_report == 0
        assert len(ctx.summary.missing_patterns) == len(
            [
                m
                for m in __import__(
                    "climate_auto.report_selector", fromlist=["REPORT_FILE_MAPPING"]
                ).REPORT_FILE_MAPPING
            ]
        )
