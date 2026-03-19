"""Tests for Jinja2 template rendering and custom filters."""

from datetime import datetime

from climate_auto.report.generator import _create_jinja_env, to_roman
from climate_auto.report.models import (
    ChartImage,
    ManifestSummary,
    ReportContext,
    ReportSection,
    ReportSubsection,
)


class TestRomanFilter:
    def test_basic_numerals(self) -> None:
        assert to_roman(1) == "I"
        assert to_roman(2) == "II"
        assert to_roman(3) == "III"
        assert to_roman(4) == "IV"
        assert to_roman(5) == "V"
        assert to_roman(9) == "IX"
        assert to_roman(10) == "X"

    def test_zero_returns_string(self) -> None:
        assert to_roman(0) == "0"

    def test_negative_returns_string(self) -> None:
        assert to_roman(-1) == "-1"


class TestTemplateRendering:
    def _make_context(self, *, with_analysis: bool = False) -> ReportContext:
        chart = ChartImage(
            relative_path="1_review/analysis/test.gif",
            description="500hPa analysis",
            analysis="High pressure system." if with_analysis else "",
        )
        return ReportContext(
            date="2026-03-19",
            generated_at=datetime(2026, 3, 19, 10, 0),
            sections=[
                ReportSection(
                    id="1_review",
                    title="當日回顧",
                    subsections=[
                        ReportSubsection(id="analysis", title="分析場", charts=[chart])
                    ],
                )
            ],
            summary=ManifestSummary(total_downloaded=10, total_in_report=1),
        )

    def test_renders_title_and_date(self) -> None:
        env = _create_jinja_env()
        template = env.get_template("daily_report.md.j2")
        ctx = self._make_context()
        result = template.render(ctx=ctx)

        assert "TACOCO 天氣討論會 - 2026-03-19" in result
        assert "2026-03-19 10:00" in result

    def test_renders_section_headers(self) -> None:
        env = _create_jinja_env()
        template = env.get_template("daily_report.md.j2")
        ctx = self._make_context()
        result = template.render(ctx=ctx)

        assert "## 1. 當日回顧" in result
        assert "### I. 分析場" in result

    def test_renders_image_markdown(self) -> None:
        env = _create_jinja_env()
        template = env.get_template("daily_report.md.j2")
        ctx = self._make_context()
        result = template.render(ctx=ctx)

        assert "![500hPa analysis](1_review/analysis/test.gif)" in result

    def test_placeholder_when_no_analysis(self) -> None:
        env = _create_jinja_env()
        template = env.get_template("daily_report.md.j2")
        ctx = self._make_context(with_analysis=False)
        result = template.render(ctx=ctx)

        assert "*待分析*" in result

    def test_shows_analysis_when_provided(self) -> None:
        env = _create_jinja_env()
        template = env.get_template("daily_report.md.j2")
        ctx = self._make_context(with_analysis=True)
        result = template.render(ctx=ctx)

        assert "High pressure system." in result
        assert "*待分析*" not in result

    def test_renders_missing_patterns(self) -> None:
        env = _create_jinja_env()
        template = env.get_template("daily_report.md.j2")
        ctx = self._make_context()
        ctx.summary.missing_patterns = ["1_review/sounding/skewt_*.gif"]
        result = template.render(ctx=ctx)

        assert "缺少的資料" in result
        assert "`1_review/sounding/skewt_*.gif`" in result

    def test_no_missing_section_when_all_present(self) -> None:
        env = _create_jinja_env()
        template = env.get_template("daily_report.md.j2")
        ctx = self._make_context()
        ctx.summary.missing_patterns = []
        result = template.render(ctx=ctx)

        assert "缺少的資料" not in result
