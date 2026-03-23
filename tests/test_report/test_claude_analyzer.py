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


def test_system_prompt_850hpa_mentions_frontal_features() -> None:
    """SYSTEM_PROMPT guides 850hPa analysis toward frontal features."""
    from climate_auto.report.claude_analyzer import SYSTEM_PROMPT

    assert "水氣通量" in SYSTEM_PROMPT
    assert "鋒面" in SYSTEM_PROMPT


def test_system_prompt_excludes_skewt() -> None:
    """SYSTEM_PROMPT notes Skew-T is handled separately."""
    from climate_auto.report.claude_analyzer import SYSTEM_PROMPT

    assert "探空圖" in SYSTEM_PROMPT
    assert "另行處理" in SYSTEM_PROMPT


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


# --- Skew-T two-pass detection ---


def test_is_skewt_detects_skewt_by_path() -> None:
    """Identifies Skew-T charts by relative_path containing 'skewt'."""
    from climate_auto.report.claude_analyzer import _is_skewt

    chart = ChartImage(
        relative_path="1_review/sounding/skewt_Taipei_26031900.gif",
        description="Taipei sounding (Skew-T)",
    )
    assert _is_skewt(chart) is True


def test_is_skewt_detects_skewt_by_description() -> None:
    """Identifies Skew-T charts by description containing 'Skew-T'."""
    from climate_auto.report.claude_analyzer import _is_skewt

    chart = ChartImage(
        relative_path="1_review/sounding/sounding.gif",
        description="Taipei Skew-T diagram",
    )
    assert _is_skewt(chart) is True


def test_is_skewt_rejects_non_skewt() -> None:
    """Non-Skew-T charts return False."""
    from climate_auto.report.claude_analyzer import _is_skewt

    chart = ChartImage(
        relative_path="1_review/analysis/ECMWF500.gif",
        description="500hPa analysis",
    )
    assert _is_skewt(chart) is False


# --- Skew-T extraction prompt ---


def test_skewt_extraction_prompt_contains_cwa_format_guidance() -> None:
    """Extraction prompt includes CWA Skew-T format guidance."""
    from climate_auto.report.claude_analyzer import SKEWT_EXTRACTION_PROMPT

    assert "text_box" in SKEWT_EXTRACTION_PROMPT
    assert "layers" in SKEWT_EXTRACTION_PROMPT
    assert "wind" in SKEWT_EXTRACTION_PROMPT


def test_build_skewt_extraction_prompt_contains_path() -> None:
    """Extraction prompt includes the image file path."""
    from climate_auto.report.claude_analyzer import _build_skewt_extraction_prompt

    chart = ChartImage(
        relative_path="1_review/sounding/skewt_Taipei_26031900.gif",
        description="Taipei sounding (Skew-T)",
    )
    prompt = _build_skewt_extraction_prompt(chart, Path("/data/report/skewt.gif"))
    assert "/data/report/skewt.gif" in prompt
    assert "skewt_Taipei_26031900.gif" in prompt


# --- Skew-T analysis prompt ---


def test_skewt_analysis_prompt_loads_guide_content() -> None:
    """Analysis prompt dynamically loads guide and includes key rules."""
    from climate_auto.report.claude_analyzer import _load_skewt_analysis_prompt

    prompt = _load_skewt_analysis_prompt()
    # Content from skew-t-guide.md should be embedded
    assert "K-Index" in prompt
    assert "Lifted Index" in prompt
    assert "Total Totals" in prompt
    # Template task instructions should be present
    assert "逆溫" in prompt or "inversion" in prompt.lower()
    assert "600hPa" in prompt


def test_build_skewt_analysis_prompt_embeds_extracted_data() -> None:
    """Analysis prompt embeds the extracted JSON data."""
    from climate_auto.report.claude_analyzer import _build_skewt_analysis_prompt

    extracted = '{"text_box": {"T0": 18.2}, "layers": []}'
    prompt = _build_skewt_analysis_prompt("skewt.gif", extracted)
    assert "18.2" in prompt
    assert "skewt.gif" in prompt


# --- Skew-T two-pass integration ---


@pytest.mark.asyncio
async def test_analyze_batch_separates_skewt() -> None:
    """Batch analysis routes Skew-T charts to two-pass flow."""
    charts = [
        (
            ChartImage(relative_path="1_review/500.png", description="500hPa"),
            Path("/data/1_review/500.png"),
        ),
        (
            ChartImage(
                relative_path="1_review/sounding/skewt_Taipei.gif",
                description="Taipei sounding (Skew-T)",
            ),
            Path("/data/1_review/sounding/skewt_Taipei.gif"),
        ),
    ]

    call_count = 0

    async def mock_query(**kwargs):
        nonlocal call_count
        call_count += 1
        msg = MagicMock()
        if call_count == 1:
            # First call: regular batch for non-skewt
            msg.result = '{"1_review/500.png": "高壓偏東"}'
        elif call_count == 2:
            # Second call: skewt extraction
            msg.result = '{"text_box": {"T0": 18.2}, "layers": []}'
        else:
            # Third call: skewt analysis
            msg.result = (
                '{"1_review/sounding/skewt_Taipei.gif": "低層近飽和"}'
            )
        yield msg

    mock_sdk = _make_mock_sdk(mock_query)
    with patch.dict(sys.modules, {"claude_agent_sdk": mock_sdk}):
        from climate_auto.report.claude_analyzer import ClaudeAnalyzer

        analyzer = ClaudeAnalyzer(AnalyzerConfig())
        results = await analyzer.analyze_batch(charts, "當日回顧")

    assert results["1_review/500.png"] == "高壓偏東"
    assert results["1_review/sounding/skewt_Taipei.gif"] == "低層近飽和"
    assert call_count == 3  # regular batch + extraction + analysis
