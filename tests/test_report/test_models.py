"""Tests for report Pydantic models."""

from datetime import datetime

from climate_auto.report.models import (
    ChartImage,
    ManifestSummary,
    ReportContext,
    ReportSection,
    ReportSubsection,
)


class TestChartImage:
    def test_create_minimal(self) -> None:
        chart = ChartImage(
            relative_path="1_review/analysis/ECMWF500.gif",
            description="500hPa analysis",
        )
        assert chart.relative_path == "1_review/analysis/ECMWF500.gif"
        assert chart.description == "500hPa analysis"
        assert chart.analysis == ""

    def test_create_with_analysis(self) -> None:
        chart = ChartImage(
            relative_path="1_review/analysis/ECMWF500.gif",
            description="500hPa analysis",
            analysis="High pressure dominates.",
        )
        assert chart.analysis == "High pressure dominates."


class TestReportSubsection:
    def test_create_with_charts(self) -> None:
        charts = [
            ChartImage(relative_path="a.gif", description="chart A"),
            ChartImage(relative_path="b.gif", description="chart B"),
        ]
        sub = ReportSubsection(id="analysis", title="分析場", charts=charts)
        assert sub.id == "analysis"
        assert len(sub.charts) == 2

    def test_empty_charts_default(self) -> None:
        sub = ReportSubsection(id="sounding", title="探空")
        assert sub.charts == []


class TestReportContext:
    def test_create_full(self) -> None:
        ctx = ReportContext(
            date="2026-03-19",
            sections=[
                ReportSection(
                    id="1_review",
                    title="當日回顧",
                    subsections=[
                        ReportSubsection(
                            id="analysis",
                            title="分析場",
                            charts=[
                                ChartImage(
                                    relative_path="1_review/analysis/test.gif",
                                    description="test",
                                )
                            ],
                        )
                    ],
                )
            ],
            summary=ManifestSummary(
                total_downloaded=10,
                total_in_report=5,
                missing_patterns=["1_review/sounding/skewt_*.gif"],
            ),
        )
        assert ctx.date == "2026-03-19"
        assert isinstance(ctx.generated_at, datetime)
        assert len(ctx.sections) == 1
        assert ctx.summary.total_in_report == 5
        assert len(ctx.summary.missing_patterns) == 1

    def test_serialization_roundtrip(self) -> None:
        ctx = ReportContext(date="2026-03-19")
        data = ctx.model_dump(mode="json")
        restored = ReportContext(**data)
        assert restored.date == ctx.date
