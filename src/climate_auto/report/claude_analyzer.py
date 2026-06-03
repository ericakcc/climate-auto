"""Claude Agent SDK-based chart analyzer for weather report generation.

Architecture:
  Phase 1 (Extraction): Each chart gets its own agent call (parallel) to extract
    concise, precise meteorological information from the image.
  Phase 2 (Synthesis): A single agent receives ALL extracted information and
    produces a unified weather diagnosis considering cross-chart relationships.
"""

import asyncio
from pathlib import Path

from loguru import logger

from climate_auto.config import AnalyzerConfig
from climate_auto.report.analyzer import BaseAnalyzer
from climate_auto.report.models import ChartImage

# ---------------------------------------------------------------------------
# Phase 1: Per-chart extraction prompts
# ---------------------------------------------------------------------------

EXTRACTION_SYSTEM_PROMPT = """\
你是一位專業的氣象圖判讀員，負責從天氣圖中提取精確的氣象資訊。

你的任務是 **只做資訊提取，不做綜合診斷**。請精準描述圖片中看到的氣象特徵。

針對不同圖類的提取要點：
- **500hPa 高度場**：高壓脊/槽的確切位置與走向、5880 線位置與範圍、副熱帶高壓西伸脊點經度
- **850hPa 水氣通量**：低層風場方向與強度、水氣輸送帶位置與走向、是否有東北-西南走向的狹長水氣帶（鋒面特徵）、台灣與鋒面的相對位置
- **雷達/降水**：降水分布型態（層狀/對流）、強度分級、移動方向、對流發展區域的具體位置
- **衛星雲圖**：雲系類型與分布、鋒面雲帶位置、對流雲團發展情況、晴空區域
- **MJO 相位圖**：目前所在相位編號、振幅大小、過去軌跡趨勢、未來預測方向
- **地面天氣圖**：高低壓中心位置與強度、鋒面位置與類型、等壓線疏密

提取原則：
1. 精簡但精確，每張圖 3-5 句
2. 使用繁體中文
3. 重點描述客觀可見的特徵，不做預報推論
4. 標注具體的地理位置與數值

使用 Read 工具查看圖片後，直接回傳提取的資訊文字（純文字，不需要 JSON 格式）。
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

# ---------------------------------------------------------------------------
# Phase 2: Synthesis prompt
# ---------------------------------------------------------------------------

SYNTHESIS_SYSTEM_PROMPT = """\
你是一位資深的綜觀氣象分析師，負責根據所有天氣圖的提取資訊，撰寫完整的天氣診斷報告。

## 你的任務

你會收到所有天氣圖的提取資訊（包含不同時間段：當日回顧、未來 24/48 小時預報）。
請綜合所有資訊，撰寫一份完整的天氣診斷分析。

## 分析架構

請依照以下架構撰寫：

### 1. 綜觀環境概述
- 大尺度環流型態（高壓脊/槽位置、副熱帶高壓動態）
- 主要天氣系統（鋒面、低壓、高壓）的位置與移動趨勢

### 2. 當日天氣回顧
- 根據當日回顧的圖資，描述今日天氣實況
- 結合雷達、衛星、地面觀測與探空資料的綜合判斷

### 3. 未來天氣展望
- 24 小時預報：主要天氣系統演變、降水機率與區域
- 48 小時預報：中期趨勢與可能的天氣轉變
- 需注意的劇烈天氣潛勢

### 4. 關鍵提醒
- 最值得關注的天氣特徵（1-2 點）

## 撰寫原則
1. 使用繁體中文
2. 聚焦對台灣天氣的影響
3. 各圖資之間要交叉驗證與互相印證
4. 合理推論但標註不確定性
5. 全文約 300-500 字，精簡扼要
6. 直接回傳分析文字，不需要 JSON 格式或 markdown code fence
"""

_SKEWT_GUIDE_PATH = Path(__file__).parent / "references" / "skew-t-guide.md"


def _load_skewt_guide() -> str:
    """Load Skew-T reference guide content.

    Returns:
        Guide content string.
    """
    try:
        return _SKEWT_GUIDE_PATH.read_text(encoding="utf-8")
    except FileNotFoundError:
        logger.warning(
            "Skew-T guide not found at '{}', using minimal prompt",
            _SKEWT_GUIDE_PATH,
        )
        return "（參考檔案缺失，請根據氣象專業知識進行分析）"


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


def _build_extraction_prompt(chart: ChartImage, image_path: Path) -> str:
    """Build prompt for single chart information extraction.

    Args:
        chart: Chart metadata.
        image_path: Absolute path to the image file.

    Returns:
        Formatted prompt string.
    """
    return (
        f"請使用 Read 工具查看以下天氣圖並提取氣象資訊：\n\n"
        f"- **{chart.description}**\n"
        f"  - 檔案位置: `{image_path}`\n\n"
        f"請精確描述圖中可見的氣象特徵。"
    )


def _build_skewt_extraction_prompt(chart: ChartImage, image_path: Path) -> str:
    """Build prompt for Skew-T data extraction.

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
        relative_path: Chart relative path.
        extracted_data: JSON string from extraction pass.

    Returns:
        Formatted prompt string for analysis.
    """
    guide_content = _load_skewt_guide()
    return (
        f"你是一位專業的氣象分析師，根據已提取的探空數據進行低層大氣分析。\n\n"
        f"## 判讀規則參考\n\n{guide_content}\n\n"
        f"## 提取數據\n\n"
        f"以下是從探空圖 `{relative_path}` 提取的結構化數據：\n\n"
        f"```json\n{extracted_data}\n```\n\n"
        f"請根據上述數據與判讀規則，產生 3-5 句精簡扼要的繁體中文分析，"
        f"聚焦 600hPa 以下的低層大氣特徵。\n\n"
        f"分析須涵蓋：\n"
        f"1. 地面觀測與 LCL 高度代表的意義\n"
        f"2. 低層溫濕結構：飽和層/乾層位置、逆溫層有無\n"
        f"3. 穩定度指標的綜合解讀（讀取 text_box 中的指標數值並對照閾值表）\n"
        f"4. 風場垂直結構與平流特徵\n\n"
        f"直接回傳分析文字，不需要 JSON 格式。"
    )


def _build_synthesis_prompt(extractions: dict[str, str]) -> str:
    """Build prompt for the synthesis agent with all extracted information.

    Args:
        extractions: Mapping of chart relative_path to extracted info text.

    Returns:
        Formatted prompt string.
    """
    lines = [
        "以下是所有天氣圖的提取資訊，請綜合分析並撰寫天氣診斷報告。",
        "",
        "---",
        "",
    ]

    for rel_path, info in extractions.items():
        lines.append(f"### {rel_path}")
        lines.append("")
        lines.append(info)
        lines.append("")
        lines.append("---")
        lines.append("")

    lines.append("請根據以上所有資訊，撰寫完整的天氣診斷分析。")

    return "\n".join(lines)


async def _run_agent(
    prompt: str,
    system_prompt: str,
    model: str,
    max_turns: int,
    budget_limit_usd: float,
    allowed_tools: list[str] | None = None,
) -> str:
    """Run a single Claude agent call and return the result text.

    Args:
        prompt: User prompt.
        system_prompt: System prompt.
        model: Model identifier.
        max_turns: Maximum conversation turns.
        budget_limit_usd: Budget limit in USD.
        allowed_tools: List of allowed tools.

    Returns:
        Agent result text.
    """
    from claude_agent_sdk import ClaudeAgentOptions, query

    if allowed_tools is None:
        allowed_tools = []

    result_text = ""
    async for message in query(
        prompt=prompt,
        options=ClaudeAgentOptions(
            system_prompt=system_prompt,
            model=model,
            max_turns=max_turns,
            allowed_tools=allowed_tools,
            max_budget_usd=budget_limit_usd,
            max_buffer_size=50 * 1024 * 1024,
        ),
    ):
        if hasattr(message, "result") and message.result:
            result_text = message.result

    return result_text


class ClaudeAnalyzer(BaseAnalyzer):
    """Chart analyzer using Claude Agent SDK with two-phase architecture.

    Phase 1: Parallel per-chart extraction (each chart → independent agent call).
    Phase 2: Single synthesis agent receives all extractions → unified diagnosis.
    """

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

    async def extract_info(self, chart: ChartImage, image_path: Path) -> str:
        """Extract information from a single chart image.

        Routes Skew-T charts to the specialized two-pass extraction flow.

        Args:
            chart: Chart metadata.
            image_path: Absolute path to the image file.

        Returns:
            Extracted information text for the chart.
        """
        if _is_skewt(chart):
            return await self._extract_skewt(chart, image_path)
        return await self._extract_standard(chart, image_path)

    async def synthesize(
        self,
        extractions: dict[str, str],
        charts: list[tuple[ChartImage, Path]],
    ) -> str:
        """Synthesize all extracted chart information into a unified diagnosis.

        Args:
            extractions: Mapping of chart relative_path to extracted info text.
            charts: All chart metadata with paths for reference.

        Returns:
            Unified weather diagnosis text.
        """
        if not extractions:
            return ""

        prompt = _build_synthesis_prompt(extractions)

        logger.info(
            "Synthesizing weather diagnosis from {} chart extractions",
            len(extractions),
        )

        try:
            result = await _run_agent(
                prompt=prompt,
                system_prompt=SYNTHESIS_SYSTEM_PROMPT,
                model=self._config.model,
                max_turns=self._config.max_turns,
                budget_limit_usd=self._config.budget_limit_usd,
                allowed_tools=[],
            )

            if result:
                logger.info("Weather diagnosis synthesis complete")
            else:
                logger.warning("Synthesis returned empty result")

            return result

        except Exception as e:
            logger.error("Synthesis agent call failed: {}", e)
            return ""

    async def extract_all(
        self,
        charts: list[tuple[ChartImage, Path]],
    ) -> dict[str, str]:
        """Extract information from all charts in parallel.

        Args:
            charts: All chart metadata with image paths.

        Returns:
            Mapping of chart relative_path to extracted info text.
        """
        if not charts:
            return {}

        semaphore = asyncio.Semaphore(self._config.concurrency)

        async def _extract_with_limit(
            chart: ChartImage, image_path: Path
        ) -> tuple[str, str]:
            async with semaphore:
                logger.info("Extracting info from '{}'", chart.relative_path)
                try:
                    info = await self.extract_info(chart, image_path)
                    if info:
                        logger.info("Extraction complete for '{}'", chart.relative_path)
                    else:
                        logger.warning(
                            "Extraction returned empty for '{}'",
                            chart.relative_path,
                        )
                    return chart.relative_path, info
                except Exception as e:
                    logger.error(
                        "Extraction failed for '{}': {}",
                        chart.relative_path,
                        e,
                    )
                    return chart.relative_path, ""

        tasks = [_extract_with_limit(chart, image_path) for chart, image_path in charts]
        results = await asyncio.gather(*tasks)

        successful = {rel_path: info for rel_path, info in results if info}
        failed = len(results) - len(successful)
        if not successful:
            logger.error(
                "All {} chart extractions failed; report will have no LLM analysis",
                len(results),
            )
        elif failed:
            logger.warning("{}/{} chart extractions failed", failed, len(results))

        return successful

    # ------------------------------------------------------------------
    # Private extraction methods
    # ------------------------------------------------------------------

    async def _extract_standard(self, chart: ChartImage, image_path: Path) -> str:
        """Extract information from a standard (non-Skew-T) chart.

        Args:
            chart: Chart metadata.
            image_path: Absolute path to the image file.

        Returns:
            Extracted information text.
        """
        prompt = _build_extraction_prompt(chart, image_path)

        try:
            return await _run_agent(
                prompt=prompt,
                system_prompt=EXTRACTION_SYSTEM_PROMPT,
                model=self._config.model,
                max_turns=self._config.max_turns,
                budget_limit_usd=self._config.budget_limit_usd,
                allowed_tools=["Read"],
            )
        except Exception as e:
            logger.error(
                "Standard extraction failed for '{}': {}",
                chart.relative_path,
                e,
            )
            return ""

    async def _extract_skewt(self, chart: ChartImage, image_path: Path) -> str:
        """Two-pass Skew-T extraction: structured data then interpretation.

        Args:
            chart: Skew-T chart metadata.
            image_path: Absolute path to the image file.

        Returns:
            Analysis text combining extracted data and interpretation.
        """
        logger.info("Skew-T two-pass extraction for '{}'", chart.relative_path)

        # --- Pass 1: Structured data extraction ---
        extraction_prompt = _build_skewt_extraction_prompt(chart, image_path)
        try:
            extracted_text = await _run_agent(
                prompt=extraction_prompt,
                system_prompt=SKEWT_EXTRACTION_PROMPT,
                model=self._config.model,
                max_turns=self._config.max_turns,
                budget_limit_usd=self._config.budget_limit_usd,
                allowed_tools=["Read"],
            )

            if not extracted_text:
                logger.warning(
                    "Skew-T extraction returned empty for '{}'",
                    chart.relative_path,
                )
                return ""

            logger.info("Skew-T data extraction complete for '{}'", chart.relative_path)

        except Exception as e:
            logger.error(
                "Skew-T extraction failed for '{}': {}",
                chart.relative_path,
                e,
            )
            return ""

        # --- Pass 2: Meteorological analysis ---
        analysis_prompt = _build_skewt_analysis_prompt(
            chart.relative_path, extracted_text
        )
        try:
            analysis_text = await _run_agent(
                prompt=analysis_prompt,
                system_prompt="你是一位專業的氣象分析師。",
                model=self._config.model,
                max_turns=self._config.max_turns,
                budget_limit_usd=self._config.budget_limit_usd,
                allowed_tools=[],
            )

            if analysis_text:
                logger.info("Skew-T analysis complete for '{}'", chart.relative_path)
            else:
                logger.warning(
                    "Skew-T analysis returned empty for '{}'",
                    chart.relative_path,
                )

            return analysis_text

        except Exception as e:
            logger.error(
                "Skew-T analysis failed for '{}': {}",
                chart.relative_path,
                e,
            )
            return ""
