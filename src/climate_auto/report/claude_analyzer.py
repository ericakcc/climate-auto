"""Claude Agent SDK-based chart analyzer for weather report generation."""

import json
from pathlib import Path

from loguru import logger

from climate_auto.config import AnalyzerConfig
from climate_auto.report.analyzer import BaseAnalyzer
from climate_auto.report.models import ChartImage

SYSTEM_PROMPT = """\
你是一位專業的氣象分析師，負責分析天氣圖並產生繁體中文的綜觀分析文字。

針對不同圖類的分析要點：
- **500hPa 高度場**：高壓脊/槽位置、5880 線位置與範圍、副熱帶高壓強度
- **850hPa 風場/水氣**：低層風向與風速、水氣輸送通道、暖溼空氣範圍
- **探空圖 (Sounding)**：CAPE/CIN 值、可降水量 (PW)、穩定度分析、逆溫層
- **雷達/降水**：降水分布型態、強度與移動方向、對流發展區域
- **衛星雲圖**：雲系分布、鋒面位置、對流雲團發展
- **MJO 相位圖**：目前 MJO 相位與振幅、未來演變趨勢

分析原則：
1. 每張圖的分析限制在 2-4 句，精簡扼要
2. 使用繁體中文
3. 聚焦於對台灣天氣有影響的特徵
4. 同一 section 內的圖表可互相參照，提供綜合判斷

你會收到一批天氣圖的路徑與描述，請使用 Read 工具逐一查看圖片後進行分析。
回傳格式必須是 JSON，key 為圖片的相對路徑，value 為分析文字。
"""


def _build_batch_prompt(
    charts: list[tuple[ChartImage, Path]],
    section_context: str = "",
) -> str:
    """Build the prompt for a batch of charts.

    Args:
        charts: List of (chart metadata, image absolute path) tuples.
        section_context: Section title for context.

    Returns:
        Formatted prompt string.
    """
    lines = [
        f"## Section: {section_context}" if section_context else "## 圖片分析",
        "",
        "請使用 Read 工具查看以下每張圖片，並進行氣象分析。",
        "",
    ]

    for i, (chart, image_path) in enumerate(charts, 1):
        lines.append(f"{i}. **{chart.description}**")
        lines.append(f"   - 相對路徑 (作為 JSON key): `{chart.relative_path}`")
        lines.append(f"   - 檔案位置: `{image_path}`")
        lines.append("")

    lines.extend(
        [
            "請以下列 JSON 格式回傳分析結果（不要包含 markdown code fence）：",
            "",
            "{",
        ]
    )
    for chart, _ in charts:
        lines.append(f'  "{chart.relative_path}": "分析文字...",')
    lines.append("}")

    return "\n".join(lines)


def _parse_response(text: str, expected_keys: list[str]) -> dict[str, str]:
    """Parse JSON response from agent output.

    Args:
        text: Raw text response from the agent.
        expected_keys: Expected chart relative_path keys.

    Returns:
        Mapping of chart relative_path to analysis text.
    """
    # Try to extract JSON from the response
    # Look for the outermost { ... } block
    start = text.find("{")
    end = text.rfind("}")
    if start == -1 or end == -1:
        logger.warning("No JSON object found in agent response")
        return {}

    json_str = text[start : end + 1]
    try:
        parsed = json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning("Failed to parse agent JSON response: {}", e)
        return {}

    if not isinstance(parsed, dict):
        logger.warning("Agent response is not a JSON object")
        return {}

    # Filter to only expected keys and ensure string values
    results: dict[str, str] = {}
    for key in expected_keys:
        if key in parsed and isinstance(parsed[key], str):
            results[key] = parsed[key]

    return results


class ClaudeAnalyzer(BaseAnalyzer):
    """Chart analyzer using Claude Agent SDK."""

    def __init__(self, config: AnalyzerConfig) -> None:
        """Initialize with analyzer configuration.

        Args:
            config: Analyzer configuration.
        """
        try:
            from claude_agent_sdk import ClaudeAgentOptions, query  # noqa: F401
        except ImportError as e:
            msg = (
                "claude-agent-sdk is required for LLM analysis. "
                "Install with: uv add --optional llm claude-agent-sdk"
            )
            raise ImportError(msg) from e
        self._config = config

    async def analyze(self, chart: ChartImage, image_path: Path) -> str:
        """Analyze a single chart image.

        Args:
            chart: Chart metadata.
            image_path: Absolute path to the image file.

        Returns:
            Analysis text for the chart.
        """
        results = await self.analyze_batch(
            [(chart, image_path)],
            section_context="",
        )
        return results.get(chart.relative_path, "")

    async def analyze_batch(
        self,
        charts: list[tuple[ChartImage, Path]],
        section_context: str = "",
    ) -> dict[str, str]:
        """Batch analyze charts in a single agent call.

        Args:
            charts: List of (chart metadata, image absolute path) tuples.
            section_context: Section title for context.

        Returns:
            Mapping of chart relative_path to analysis text.
        """
        if not charts:
            return {}

        from claude_agent_sdk import ClaudeAgentOptions, query

        prompt = _build_batch_prompt(charts, section_context)
        expected_keys = [chart.relative_path for chart, _ in charts]

        logger.info(
            "Analyzing {} charts for section '{}'",
            len(charts),
            section_context,
        )

        try:
            result_text = ""
            async for message in query(
                prompt=prompt,
                options=ClaudeAgentOptions(
                    system_prompt=SYSTEM_PROMPT,
                    model=self._config.model,
                    max_turns=self._config.max_turns,
                    allowed_tools=["Read"],
                    max_budget_usd=self._config.budget_limit_usd,
                    max_buffer_size=50 * 1024 * 1024,
                ),
            ):
                if hasattr(message, "result") and message.result:
                    result_text = message.result

            results = _parse_response(result_text, expected_keys)
            logger.info(
                "Got {} / {} analyses for section '{}'",
                len(results),
                len(charts),
                section_context,
            )
            return results

        except Exception as e:
            logger.error(
                "Agent call failed for section '{}': {}",
                section_context,
                e,
            )
            return {}
