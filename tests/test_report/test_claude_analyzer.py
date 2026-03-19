"""Tests for ClaudeAnalyzer: prompt building, response parsing, and error handling."""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from climate_auto.config import AnalyzerConfig
from climate_auto.report.models import ChartImage


def _make_mock_sdk(mock_query_fn: object = None) -> MagicMock:
    """Create a mock claude_agent_sdk module with optional query function."""
    mock_sdk = MagicMock()
    if mock_query_fn is not None:
        mock_sdk.query = mock_query_fn
    mock_sdk.ClaudeAgentOptions = MagicMock()
    return mock_sdk


# --- Prompt building ---


def test_build_batch_prompt_contains_all_paths() -> None:
    """Prompt includes every chart's relative_path and description."""
    from climate_auto.report.claude_analyzer import _build_batch_prompt

    charts = [
        (
            ChartImage(
                relative_path="1_review/analysis/500hPa.png", description="500hPa 分析"
            ),
            Path("/data/report/1_review/analysis/500hPa.png"),
        ),
        (
            ChartImage(
                relative_path="1_review/analysis/850hPa.png", description="850hPa 分析"
            ),
            Path("/data/report/1_review/analysis/850hPa.png"),
        ),
    ]

    prompt = _build_batch_prompt(charts, section_context="實況回顧")

    assert "實況回顧" in prompt
    assert "1_review/analysis/500hPa.png" in prompt
    assert "1_review/analysis/850hPa.png" in prompt
    assert "500hPa 分析" in prompt
    assert "850hPa 分析" in prompt
    assert "/data/report/1_review/analysis/500hPa.png" in prompt


def test_build_batch_prompt_no_section_context() -> None:
    """Prompt works without section context."""
    from climate_auto.report.claude_analyzer import _build_batch_prompt

    charts = [
        (
            ChartImage(relative_path="img.png", description="test"),
            Path("/data/img.png"),
        ),
    ]

    prompt = _build_batch_prompt(charts, section_context="")

    assert "圖片分析" in prompt
    assert "img.png" in prompt


# --- Response parsing ---


def test_parse_valid_json() -> None:
    """Correctly parses a valid JSON response."""
    from climate_auto.report.claude_analyzer import _parse_response

    text = '{"a/b.png": "高壓脊偏東", "c/d.png": "水氣充沛"}'
    result = _parse_response(text, ["a/b.png", "c/d.png"])

    assert result == {"a/b.png": "高壓脊偏東", "c/d.png": "水氣充沛"}


def test_parse_json_with_surrounding_text() -> None:
    """Extracts JSON even with surrounding text."""
    from climate_auto.report.claude_analyzer import _parse_response

    text = 'Here is my analysis:\n{"a.png": "分析結果"}\nDone!'
    result = _parse_response(text, ["a.png"])

    assert result == {"a.png": "分析結果"}


def test_parse_invalid_json_returns_empty() -> None:
    """Returns empty dict for invalid JSON."""
    from climate_auto.report.claude_analyzer import _parse_response

    result = _parse_response("not json at all", ["a.png"])
    assert result == {}


def test_parse_filters_unexpected_keys() -> None:
    """Only returns results for expected keys."""
    from climate_auto.report.claude_analyzer import _parse_response

    text = '{"a.png": "ok", "unexpected.png": "extra"}'
    result = _parse_response(text, ["a.png"])

    assert result == {"a.png": "ok"}


def test_parse_skips_non_string_values() -> None:
    """Skips entries where value is not a string."""
    from climate_auto.report.claude_analyzer import _parse_response

    text = '{"a.png": "ok", "b.png": 123}'
    result = _parse_response(text, ["a.png", "b.png"])

    assert result == {"a.png": "ok"}


def test_parse_no_braces_returns_empty() -> None:
    """Returns empty dict when no JSON braces found."""
    from climate_auto.report.claude_analyzer import _parse_response

    result = _parse_response("just text without braces", ["a.png"])
    assert result == {}


# --- Agent call (mocked) ---


@pytest.mark.asyncio
async def test_analyze_batch_maps_results() -> None:
    """Batch analysis correctly maps agent response to charts."""
    charts = [
        (
            ChartImage(relative_path="1_review/500.png", description="500hPa"),
            Path("/data/1_review/500.png"),
        ),
        (
            ChartImage(relative_path="1_review/850.png", description="850hPa"),
            Path("/data/1_review/850.png"),
        ),
    ]

    mock_message = MagicMock()
    mock_message.result = (
        '{"1_review/500.png": "高壓偏東", "1_review/850.png": "西南風明顯"}'
    )

    async def mock_query(**kwargs):
        yield mock_message

    mock_sdk = _make_mock_sdk(mock_query)
    with patch.dict(sys.modules, {"claude_agent_sdk": mock_sdk}):
        from climate_auto.report.claude_analyzer import ClaudeAnalyzer

        analyzer = ClaudeAnalyzer(AnalyzerConfig())
        results = await analyzer.analyze_batch(charts, "實況回顧")

    assert results == {
        "1_review/500.png": "高壓偏東",
        "1_review/850.png": "西南風明顯",
    }


@pytest.mark.asyncio
async def test_analyze_single_delegates_to_batch() -> None:
    """Single analyze() internally calls analyze_batch()."""
    chart = ChartImage(relative_path="img.png", description="test")
    image_path = Path("/data/img.png")

    mock_message = MagicMock()
    mock_message.result = '{"img.png": "分析結果"}'

    async def mock_query(**kwargs):
        yield mock_message

    mock_sdk = _make_mock_sdk(mock_query)
    with patch.dict(sys.modules, {"claude_agent_sdk": mock_sdk}):
        from climate_auto.report.claude_analyzer import ClaudeAnalyzer

        analyzer = ClaudeAnalyzer(AnalyzerConfig())
        result = await analyzer.analyze(chart, image_path)

    assert result == "分析結果"


@pytest.mark.asyncio
async def test_agent_error_returns_empty_dict() -> None:
    """Agent exception returns empty dict (graceful degradation)."""

    async def mock_query(**kwargs):
        raise RuntimeError("API error")
        yield  # noqa: F401 - make it an async generator

    mock_sdk = _make_mock_sdk(mock_query)
    with patch.dict(sys.modules, {"claude_agent_sdk": mock_sdk}):
        from climate_auto.report.claude_analyzer import ClaudeAnalyzer

        analyzer = ClaudeAnalyzer(AnalyzerConfig())
        charts = [
            (
                ChartImage(relative_path="img.png", description="test"),
                Path("/data/img.png"),
            ),
        ]
        results = await analyzer.analyze_batch(charts, "section")

    assert results == {}


@pytest.mark.asyncio
async def test_analyze_batch_empty_charts() -> None:
    """Empty chart list returns empty dict without calling agent."""
    mock_sdk = _make_mock_sdk()
    with patch.dict(sys.modules, {"claude_agent_sdk": mock_sdk}):
        from climate_auto.report.claude_analyzer import ClaudeAnalyzer

        analyzer = ClaudeAnalyzer(AnalyzerConfig())

    results = await analyzer.analyze_batch([], "section")
    assert results == {}
