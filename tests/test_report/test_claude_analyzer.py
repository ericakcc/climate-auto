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


def test_build_extraction_prompt_contains_path() -> None:
    """Extraction prompt includes chart path and description."""
    from climate_auto.report.claude_analyzer import _build_extraction_prompt

    chart = ChartImage(
        relative_path="1_review/analysis/500hPa.png",
        description="500hPa 分析",
    )
    prompt = _build_extraction_prompt(chart, Path("/data/report/500hPa.png"))

    assert "/data/report/500hPa.png" in prompt
    assert "500hPa 分析" in prompt


def test_build_synthesis_prompt_contains_all_extractions() -> None:
    """Synthesis prompt includes all chart extraction results."""
    from climate_auto.report.claude_analyzer import _build_synthesis_prompt

    extractions = {
        "1_review/500.png": "高壓脊偏東",
        "1_review/850.png": "西南風明顯",
        "2_f24h/500.png": "槽線東移",
    }
    prompt = _build_synthesis_prompt(extractions)

    assert "高壓脊偏東" in prompt
    assert "西南風明顯" in prompt
    assert "槽線東移" in prompt
    assert "1_review/500.png" in prompt
    assert "2_f24h/500.png" in prompt


# --- System prompts ---


def test_extraction_system_prompt_covers_chart_types() -> None:
    """Extraction system prompt includes guidance for different chart types."""
    from climate_auto.report.claude_analyzer import EXTRACTION_SYSTEM_PROMPT

    assert "500hPa" in EXTRACTION_SYSTEM_PROMPT
    assert "850hPa" in EXTRACTION_SYSTEM_PROMPT
    assert "水氣通量" in EXTRACTION_SYSTEM_PROMPT
    assert "鋒面" in EXTRACTION_SYSTEM_PROMPT


def test_synthesis_system_prompt_covers_analysis_structure() -> None:
    """Synthesis system prompt includes the analysis architecture."""
    from climate_auto.report.claude_analyzer import SYNTHESIS_SYSTEM_PROMPT

    assert "綜觀環境概述" in SYNTHESIS_SYSTEM_PROMPT
    assert "天氣回顧" in SYNTHESIS_SYSTEM_PROMPT
    assert "天氣展望" in SYNTHESIS_SYSTEM_PROMPT
    assert "關鍵提醒" in SYNTHESIS_SYSTEM_PROMPT


# --- Agent calls (mocked) ---


@pytest.mark.asyncio
async def test_extract_info_returns_text() -> None:
    """extract_info returns extracted information text."""
    chart = ChartImage(relative_path="500.png", description="500hPa")
    image_path = Path("/data/500.png")

    mock_message = MagicMock()
    mock_message.result = "高壓脊位於 130E 附近"

    async def mock_query(**kwargs):
        yield mock_message

    mock_sdk = _make_mock_sdk(mock_query)
    with patch.dict(sys.modules, {"claude_agent_sdk": mock_sdk}):
        from climate_auto.report.claude_analyzer import ClaudeAnalyzer

        analyzer = ClaudeAnalyzer(AnalyzerConfig())
        result = await analyzer.extract_info(chart, image_path)

    assert result == "高壓脊位於 130E 附近"


@pytest.mark.asyncio
async def test_extract_all_parallel() -> None:
    """extract_all processes multiple charts and returns all results."""
    charts = [
        (
            ChartImage(relative_path="500.png", description="500hPa"),
            Path("/data/500.png"),
        ),
        (
            ChartImage(relative_path="850.png", description="850hPa"),
            Path("/data/850.png"),
        ),
    ]

    async def mock_query(**kwargs):
        msg = MagicMock()
        prompt = kwargs.get("prompt", "")
        if "500hPa" in prompt:
            msg.result = "高壓脊偏東"
        else:
            msg.result = "西南風明顯"
        yield msg

    mock_sdk = _make_mock_sdk(mock_query)
    with patch.dict(sys.modules, {"claude_agent_sdk": mock_sdk}):
        from climate_auto.report.claude_analyzer import ClaudeAnalyzer

        analyzer = ClaudeAnalyzer(AnalyzerConfig())
        results = await analyzer.extract_all(charts)

    assert results == {"500.png": "高壓脊偏東", "850.png": "西南風明顯"}


@pytest.mark.asyncio
async def test_extract_all_logs_error_when_all_fail() -> None:
    """When every extraction is empty, extract_all logs an error and returns {}."""
    from loguru import logger

    charts = [
        (
            ChartImage(relative_path="500.png", description="500hPa"),
            Path("/data/500.png"),
        ),
        (
            ChartImage(relative_path="850.png", description="850hPa"),
            Path("/data/850.png"),
        ),
    ]

    async def mock_query(**kwargs):
        msg = MagicMock()
        msg.result = ""  # empty result => extraction failed
        yield msg

    messages: list[str] = []
    sink_id = logger.add(messages.append, level="ERROR", format="{message}")
    try:
        mock_sdk = _make_mock_sdk(mock_query)
        with patch.dict(sys.modules, {"claude_agent_sdk": mock_sdk}):
            from climate_auto.report.claude_analyzer import ClaudeAnalyzer

            analyzer = ClaudeAnalyzer(AnalyzerConfig())
            results = await analyzer.extract_all(charts)
    finally:
        logger.remove(sink_id)

    assert results == {}
    assert any("All" in m and "failed" in m for m in messages)


@pytest.mark.asyncio
async def test_synthesize_produces_diagnosis() -> None:
    """synthesize returns unified weather diagnosis."""
    extractions = {
        "500.png": "高壓脊偏東",
        "850.png": "西南風明顯",
    }
    charts = [
        (
            ChartImage(relative_path="500.png", description="500hPa"),
            Path("/data/500.png"),
        ),
        (
            ChartImage(relative_path="850.png", description="850hPa"),
            Path("/data/850.png"),
        ),
    ]

    mock_message = MagicMock()
    mock_message.result = "綜合分析：高壓脊偏東搭配西南風，台灣處於暖區。"

    async def mock_query(**kwargs):
        yield mock_message

    mock_sdk = _make_mock_sdk(mock_query)
    with patch.dict(sys.modules, {"claude_agent_sdk": mock_sdk}):
        from climate_auto.report.claude_analyzer import ClaudeAnalyzer

        analyzer = ClaudeAnalyzer(AnalyzerConfig())
        result = await analyzer.synthesize(extractions, charts)

    assert "高壓脊偏東" in result


@pytest.mark.asyncio
async def test_extract_info_error_returns_empty() -> None:
    """Agent exception returns empty string (graceful degradation)."""

    async def mock_query(**kwargs):
        raise RuntimeError("API error")
        yield  # noqa: F401 - make it an async generator

    mock_sdk = _make_mock_sdk(mock_query)
    with patch.dict(sys.modules, {"claude_agent_sdk": mock_sdk}):
        from climate_auto.report.claude_analyzer import ClaudeAnalyzer

        analyzer = ClaudeAnalyzer(AnalyzerConfig())
        chart = ChartImage(relative_path="img.png", description="test")
        result = await analyzer.extract_info(chart, Path("/data/img.png"))

    assert result == ""


@pytest.mark.asyncio
async def test_extract_all_empty_charts() -> None:
    """Empty chart list returns empty dict without calling agent."""
    mock_sdk = _make_mock_sdk()
    with patch.dict(sys.modules, {"claude_agent_sdk": mock_sdk}):
        from climate_auto.report.claude_analyzer import ClaudeAnalyzer

        analyzer = ClaudeAnalyzer(AnalyzerConfig())

    results = await analyzer.extract_all([])
    assert results == {}


@pytest.mark.asyncio
async def test_synthesize_empty_extractions() -> None:
    """Empty extractions returns empty string without calling agent."""
    mock_sdk = _make_mock_sdk()
    with patch.dict(sys.modules, {"claude_agent_sdk": mock_sdk}):
        from climate_auto.report.claude_analyzer import ClaudeAnalyzer

        analyzer = ClaudeAnalyzer(AnalyzerConfig())

    result = await analyzer.synthesize({}, [])
    assert result == ""


# --- Skew-T detection ---


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


# --- Skew-T prompts ---


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


def test_build_skewt_analysis_prompt_embeds_extracted_data() -> None:
    """Analysis prompt embeds the extracted JSON data."""
    from climate_auto.report.claude_analyzer import _build_skewt_analysis_prompt

    extracted = '{"text_box": {"T0": 18.2}, "layers": []}'
    prompt = _build_skewt_analysis_prompt("skewt.gif", extracted)
    assert "18.2" in prompt
    assert "skewt.gif" in prompt


# --- Skew-T two-pass integration ---


@pytest.mark.asyncio
async def test_extract_info_routes_skewt_to_two_pass() -> None:
    """Skew-T chart triggers two-pass extraction flow."""
    chart = ChartImage(
        relative_path="1_review/sounding/skewt_Taipei.gif",
        description="Taipei sounding (Skew-T)",
    )

    call_count = 0

    async def mock_query(**kwargs):
        nonlocal call_count
        call_count += 1
        msg = MagicMock()
        if call_count == 1:
            # Pass 1: data extraction
            msg.result = '{"text_box": {"T0": 18.2}, "layers": []}'
        else:
            # Pass 2: analysis
            msg.result = "低層近飽和，LCL 高度偏低"
        yield msg

    mock_sdk = _make_mock_sdk(mock_query)
    with patch.dict(sys.modules, {"claude_agent_sdk": mock_sdk}):
        from climate_auto.report.claude_analyzer import ClaudeAnalyzer

        analyzer = ClaudeAnalyzer(AnalyzerConfig())
        result = await analyzer.extract_info(chart, Path("/data/skewt_Taipei.gif"))

    assert "低層近飽和" in result
    assert call_count == 2
