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
- **850hPa 水氣通量**：利用水氣通量圖判斷低層風場與水氣輸送，重點關注華南至台灣至日本一帶是否有東北-西南走向的狹長水氣輸送帶（鋒面特徵），並指出台灣與鋒面的相對位置（如鋒面尾端南側、鋒面通過台灣北方海面等）
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

注意：探空圖 (Skew-T) 不會出現在此批次中，會另行處理。
"""

SKEWT_EXTRACTION_PROMPT = """\
你是一位專業的氣象圖判讀員，負責從 CWA（中央氣象署）的 Skew-T / Log-P 探空圖 GIF 中\
提取結構化數值資料。

## CWA Skew-T GIF 格式說明

- **藍色粗線**（右側）：環境溫度曲線
- **藍色粗線**（左側）：露點溫度曲線
- **綠色曲線**：乾絕熱線（斜率較小）與濕絕熱線（斜率較大、更接近垂直）
- **黃色斜紋底圖**：背景區塊
- **右上角文字框**：包含地面觀測值與穩定度指標
- **右側風標**：各層風向風速
- **Y 軸**：氣壓 (hPa)，對數刻度，由下往上遞減（1000→100 hPa）
- **X 軸**：溫度 (°C)，向右傾斜 45°
- **左上方標題**：STATION = 站號，TIME = 時間（YYMMDDHH 格式）

## 你的任務

使用 Read 工具查看圖片，**只做數值提取，不做分析判讀**。

提取以下內容並回傳 JSON：

```json
{
  "station": "站號",
  "time": "YYMMDDHH",
  "text_box": {
    "P0": "地面氣壓 (hPa)",
    "T0": "地面溫度 (°C)",
    "Td0": "地面露點 (°C)",
    "LCL": "抬升凝結高度 (hPa)",
    "LCL_km": "LCL 高度 (km)",
    "CCL": "對流凝結高度 (hPa)",
    "CCL_km": "CCL 高度 (km)",
    "T_LCL": "LCL 溫度 (°C)",
    "T_CCL": "CCL 溫度 (°C)",
    "K_index": "K 指數",
    "LI": "抬升指數",
    "SI": "Showalter 指數",
    "TT": "Total Totals",
    "SWEAT": "SWEAT 指數",
    "QPF": "預估降水量 (mm)"
  },
  "layers": [
    {
      "level": "surface / 925 / 850 / 700 / 600 hPa",
      "T_approx": "溫度近似值 (°C)，從藍色溫度曲線讀取",
      "Td_approx": "露點近似值 (°C)，從藍色露點曲線讀取",
      "T_Td_spread": "溫度-露點差 (°C)",
      "wind_dir": "風向（從風標判讀，如 SSW, NE）",
      "wind_speed_kt": "風速 (knot，從風標旗幟數判讀）"
    }
  ],
  "curve_features": {
    "saturated_layers": "飽和層（T 線與 Td 線重合區域）的氣壓範圍",
    "inversion_layers": "逆溫層（溫度隨高度增加）的氣壓範圍，若無則寫 'none'",
    "dry_intrusion": "明顯乾層（T-Td 急遽拉大）的氣壓範圍，若無則寫 'none'"
  }
}
```

重要：
- 數值請用數字，不要加單位文字
- 風標讀法：長線 = 10kt, 短線 = 5kt, 三角旗 = 50kt
- 讀取溫度時注意 X 軸是傾斜的（skewed），需沿等溫線方向讀取
- 若某項數值無法辨識，填 null
"""

_SKEWT_GUIDE_PATH = Path(__file__).parent / "references" / "skew-t-guide.md"

_SKEWT_ANALYSIS_TEMPLATE = """\
你是一位專業的氣象分析師，根據已提取的探空數據進行低層大氣分析。

## 判讀規則參考

{guide_content}

## 你的任務

根據以下提取的探空數據，產生 2-4 句精簡扼要的繁體中文分析，聚焦 600hPa 以下的低層大氣特徵。

分析須涵蓋：
1. 地面觀測與 LCL 高度代表的意義
2. 低層溫濕結構：飽和層/乾層位置、逆溫層有無
3. 穩定度指標的綜合解讀（讀取 text_box 中的指標數值並對照閾值表）
4. 風場垂直結構與平流特徵

回傳格式為 JSON：`{{"<relative_path>": "分析文字"}}`
不要包含 markdown code fence。
"""


def _load_skewt_analysis_prompt() -> str:
    """Load Skew-T analysis prompt with guide content from reference file.

    Returns:
        Assembled system prompt with embedded guide content.
    """
    try:
        guide_content = _SKEWT_GUIDE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning(
            "Skew-T guide not found at '{}', using minimal prompt",
            _SKEWT_GUIDE_PATH,
        )
        guide_content = "（參考檔案缺失，請根據氣象專業知識進行分析）"
    return _SKEWT_ANALYSIS_TEMPLATE.format(guide_content=guide_content)


def _is_skewt(chart: ChartImage) -> bool:
    """Check if a chart is a Skew-T sounding diagram.

    Args:
        chart: Chart metadata to check.

    Returns:
        True if chart is a Skew-T diagram.
    """
    path_lower = chart.relative_path.lower()
    desc_lower = chart.description.lower()
    return "skewt" in path_lower or "skew-t" in desc_lower


def _build_skewt_extraction_prompt(chart: ChartImage, image_path: Path) -> str:
    """Build prompt for Skew-T data extraction (Pass 1).

    Args:
        chart: Chart metadata.
        image_path: Absolute path to the image file.

    Returns:
        Formatted prompt string for extraction.
    """
    return (
        f"請使用 Read 工具查看以下探空圖並提取結構化數據：\n\n"
        f"- **{chart.description}**\n"
        f"  - 相對路徑: `{chart.relative_path}`\n"
        f"  - 檔案位置: `{image_path}`\n\n"
        f"請嚴格按照 system prompt 中定義的 JSON 格式回傳提取結果。\n"
        f"不要包含 markdown code fence，直接回傳 JSON。"
    )


def _build_skewt_analysis_prompt(relative_path: str, extracted_data: str) -> str:
    """Build prompt for Skew-T meteorological analysis (Pass 2).

    Args:
        relative_path: Chart relative path (used as JSON key).
        extracted_data: JSON string from extraction pass.

    Returns:
        Formatted prompt string for analysis.
    """
    return (
        f"以下是從探空圖 `{relative_path}` 提取的結構化數據：\n\n"
        f"```json\n{extracted_data}\n```\n\n"
        f"請根據上述數據與 system prompt 中的判讀規則，產生分析。\n"
        f'回傳格式：{{"{relative_path}": "分析文字"}}\n'
        f"不要包含 markdown code fence。"
    )


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
        """Batch analyze charts, routing Skew-T to two-pass flow.

        Args:
            charts: List of (chart metadata, image absolute path) tuples.
            section_context: Section title for context.

        Returns:
            Mapping of chart relative_path to analysis text.
        """
        if not charts:
            return {}

        # Separate Skew-T charts from other charts
        skewt_charts = [(c, p) for c, p in charts if _is_skewt(c)]
        other_charts = [(c, p) for c, p in charts if not _is_skewt(c)]

        results: dict[str, str] = {}

        # Process non-Skew-T charts with standard single-pass flow
        if other_charts:
            batch_results = await self._analyze_standard_batch(
                other_charts, section_context
            )
            results.update(batch_results)

        # Process Skew-T charts with two-pass flow
        for chart, image_path in skewt_charts:
            skewt_result = await self._analyze_skewt_two_pass(chart, image_path)
            if skewt_result:
                results[chart.relative_path] = skewt_result

        return results

    async def _analyze_standard_batch(
        self,
        charts: list[tuple[ChartImage, Path]],
        section_context: str = "",
    ) -> dict[str, str]:
        """Standard single-pass batch analysis for non-Skew-T charts.

        Args:
            charts: List of (chart metadata, image absolute path) tuples.
            section_context: Section title for context.

        Returns:
            Mapping of chart relative_path to analysis text.
        """
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

    async def _analyze_skewt_two_pass(
        self,
        chart: ChartImage,
        image_path: Path,
    ) -> str:
        """Two-pass Skew-T analysis: extraction then interpretation.

        Args:
            chart: Skew-T chart metadata.
            image_path: Absolute path to the image file.

        Returns:
            Analysis text, or empty string on failure.
        """
        from claude_agent_sdk import ClaudeAgentOptions, query

        logger.info("Skew-T two-pass analysis for '{}'", chart.relative_path)

        # --- Pass 1: Data extraction ---
        extraction_prompt = _build_skewt_extraction_prompt(chart, image_path)
        try:
            extracted_text = ""
            async for message in query(
                prompt=extraction_prompt,
                options=ClaudeAgentOptions(
                    system_prompt=SKEWT_EXTRACTION_PROMPT,
                    model=self._config.model,
                    max_turns=self._config.max_turns,
                    allowed_tools=["Read"],
                    max_budget_usd=self._config.budget_limit_usd,
                    max_buffer_size=50 * 1024 * 1024,
                ),
            ):
                if hasattr(message, "result") and message.result:
                    extracted_text = message.result

            if not extracted_text:
                logger.warning(
                    "Skew-T extraction returned empty for '{}'", chart.relative_path
                )
                return ""

            logger.info("Skew-T extraction complete for '{}'", chart.relative_path)

        except Exception as e:
            logger.error(
                "Skew-T extraction failed for '{}': {}", chart.relative_path, e
            )
            return ""

        # --- Pass 2: Meteorological analysis ---
        analysis_prompt = _build_skewt_analysis_prompt(
            chart.relative_path, extracted_text
        )
        skewt_analysis_prompt = _load_skewt_analysis_prompt()
        try:
            analysis_text = ""
            async for message in query(
                prompt=analysis_prompt,
                options=ClaudeAgentOptions(
                    system_prompt=skewt_analysis_prompt,
                    model=self._config.model,
                    max_turns=self._config.max_turns,
                    allowed_tools=[],
                    max_budget_usd=self._config.budget_limit_usd,
                    max_buffer_size=50 * 1024 * 1024,
                ),
            ):
                if hasattr(message, "result") and message.result:
                    analysis_text = message.result

            result = _parse_response(analysis_text, [chart.relative_path])
            analysis = result.get(chart.relative_path, "")

            if analysis:
                logger.info("Skew-T analysis complete for '{}'", chart.relative_path)
            else:
                logger.warning(
                    "Skew-T analysis parsing failed for '{}'", chart.relative_path
                )

            return analysis

        except Exception as e:
            logger.error("Skew-T analysis failed for '{}': {}", chart.relative_path, e)
            return ""
