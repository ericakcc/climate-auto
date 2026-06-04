"""Main report generator: discovery + analyzer + Jinja2 rendering."""

import asyncio
import re
from datetime import date
from pathlib import Path

from jinja2 import Environment, FileSystemLoader
from loguru import logger

from climate_auto.report.analyzer import BaseAnalyzer
from climate_auto.report.discovery import build_report_context
from climate_auto.report.models import ChartImage
from climate_auto.storage import get_date_dir

_ROMAN_NUMERALS = [
    (1000, "M"),
    (900, "CM"),
    (500, "D"),
    (400, "CD"),
    (100, "C"),
    (90, "XC"),
    (50, "L"),
    (40, "XL"),
    (10, "X"),
    (9, "IX"),
    (5, "V"),
    (4, "IV"),
    (1, "I"),
]

EXTRACTIONS_FILENAME = "extractions.md"

# Suffixes that mark a bare-filename extraction key (vs a prose heading in a body).
_KEY_SUFFIXES = (".png", ".gif", ".jpg", ".jpeg", ".json", ".md")


def _looks_like_key(text: str) -> bool:
    """Whether a ``## `` heading is an extraction key, not body prose.

    Keys are chart relative paths or ``numeric/...`` (both contain "/"), or bare
    filenames ending in an image/data suffix.

    Args:
        text: The heading text after ``## ``.

    Returns:
        True if it should be treated as an extraction key.
    """
    return "/" in text or text.lower().endswith(_KEY_SUFFIXES)


def to_roman(n: int) -> str:
    """Convert an integer to a Roman numeral string.

    Args:
        n: Positive integer to convert.

    Returns:
        Roman numeral string.
    """
    if n <= 0:
        return str(n)
    result = ""
    for value, numeral in _ROMAN_NUMERALS:
        while n >= value:
            result += numeral
            n -= value
    return result


def _create_jinja_env() -> Environment:
    """Create a Jinja2 environment with custom filters."""
    templates_dir = Path(__file__).parent / "templates"
    env = Environment(
        loader=FileSystemLoader(str(templates_dir)),
        keep_trailing_newline=True,
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["roman"] = to_roman
    return env


def _collect_charts(
    context: "ReportContext",  # noqa: F821
    report_dir: Path,
) -> list[tuple[ChartImage, Path]]:
    """Collect all chart images with existing files from report context.

    Args:
        context: Report context with sections and charts.
        report_dir: Path to the report directory.

    Returns:
        List of (chart metadata, image absolute path) tuples.
    """
    all_charts: list[tuple[ChartImage, Path]] = []
    for section in context.sections:
        for subsection in section.subsections:
            for chart in subsection.charts:
                image_path = report_dir / chart.relative_path
                if image_path.exists():
                    all_charts.append((chart, image_path))
    return all_charts


async def run_extraction(
    analyzer: BaseAnalyzer,
    all_charts: list[tuple[ChartImage, Path]],
    report_dir: Path,
) -> dict[str, str]:
    """Run Phase 1: extract info from each chart and save to disk.

    Args:
        analyzer: Chart analyzer instance.
        all_charts: List of (chart metadata, image absolute path) tuples.
        report_dir: Path to the report directory (for saving extractions.md).

    Returns:
        Mapping of chart relative_path to extracted info text.
    """
    logger.info("Phase 1: Extracting info from {} charts", len(all_charts))
    extractions = await analyzer.extract_all(all_charts)
    logger.info(
        "Phase 1 complete: {} / {} extractions",
        len(extractions),
        len(all_charts),
    )

    save_extractions(report_dir, extractions)
    return extractions


def save_extractions(report_dir: Path, extractions: dict[str, str]) -> Path:
    """Save extraction results to Markdown file.

    Format: each chart is a ``## relative_path`` section followed by the
    extracted text.  This makes it easy for humans to read and edit.

    Args:
        report_dir: Path to the report directory.
        extractions: Mapping of chart relative_path to extracted info text.

    Returns:
        Path to the saved extractions.md file.
    """
    lines: list[str] = []
    for rel_path, text in extractions.items():
        lines.append(f"## {rel_path}")
        lines.append("")
        lines.append(text.strip())
        lines.append("")

    output_path = report_dir / EXTRACTIONS_FILENAME
    output_path.write_text("\n".join(lines), encoding="utf-8")
    logger.info("Extractions saved: {} ({} charts)", output_path, len(extractions))
    return output_path


def load_extractions(report_dir: Path) -> dict[str, str]:
    """Load extraction results from Markdown file.

    Parses ``## relative_path`` headers as keys and the text below each
    header as the extraction content.

    Args:
        report_dir: Path to the report directory.

    Returns:
        Mapping of chart relative_path to extracted info text.

    Raises:
        FileNotFoundError: If extractions.md does not exist.
    """
    input_path = report_dir / EXTRACTIONS_FILENAME
    if not input_path.exists():
        msg = (
            f"Extractions file not found: {input_path}\n"
            f"Run with --extract first to generate it."
        )
        raise FileNotFoundError(msg)

    content = input_path.read_text(encoding="utf-8")

    # A `## ` line is a key delimiter only if it *looks like a key*: chart paths
    # contain "/", "numeric/..." keys contain "/", and bare-filename keys end in
    # an image/data suffix. Prose headings inside an extraction body (e.g.
    # "## 地面天氣圖分析") match none of these, so they stay in the body instead
    # of being mis-parsed as new keys.
    data: dict[str, str] = {}
    current_key: str | None = None
    buf: list[str] = []

    def _flush() -> None:
        if current_key is not None:
            body = "\n".join(buf).strip()
            if body:
                data[current_key] = body

    for line in content.splitlines():
        match = re.match(r"^## (.+)$", line)
        if match and _looks_like_key(match.group(1).strip()):
            _flush()
            current_key = match.group(1).strip()
            buf = []
        elif current_key is not None:
            buf.append(line)
    _flush()

    logger.info("Extractions loaded: {} ({} charts)", input_path, len(data))
    return data


async def run_synthesis(
    analyzer: BaseAnalyzer,
    extractions: dict[str, str],
    all_charts: list[tuple[ChartImage, Path]],
) -> str:
    """Run Phase 2: synthesize all extractions into unified diagnosis.

    Args:
        analyzer: Chart analyzer instance.
        extractions: Mapping of chart relative_path to extracted info text.
        all_charts: All chart metadata with paths for reference.

    Returns:
        Unified weather diagnosis text.
    """
    if not extractions:
        return ""

    logger.info("Phase 2: Synthesizing weather diagnosis")
    synthesis = await analyzer.synthesize(extractions, all_charts)
    logger.info("Phase 2 complete")
    return synthesis


def _drop_replaced_charts(
    all_charts: list[tuple[ChartImage, Path]],
    patterns: list[str],
) -> list[tuple[ChartImage, Path]]:
    """Drop image charts whose path matches a numeric-replacement pattern.

    Charts covered by the numeric route are skipped here so the vision model
    never reads them.

    Args:
        all_charts: All (chart, path) tuples.
        patterns: relative_path substrings to drop.

    Returns:
        Filtered chart list.
    """
    if not patterns:
        return all_charts
    kept = [
        (chart, path)
        for chart, path in all_charts
        if not any(p in chart.relative_path for p in patterns)
    ]
    dropped = len(all_charts) - len(kept)
    if dropped:
        logger.info(
            "Numeric route replaces {} image chart(s); skipping vision", dropped
        )
    return kept


# Map ECMWF chart filename tokens → the numeric block that replaces them, so a
# replaced chart's section shows its numeric analysis instead of "待分析".
_NUMERIC_VAR_TOKENS = {
    "ECMWF500": "500hPa高度場",
    "ECMWF700": "700hPa相對濕度",
    "ECMWF850mf": "850hPa水氣通量",
}
_NUMERIC_STEP_TOKENS = {
    "f000": "分析場(f000)",
    "f024": "f24h 預報",
    "f048": "f48h 預報",
}


def _numeric_key_for_chart(relative_path: str) -> str | None:
    """Return the numeric-block key that corresponds to a chart path, if any.

    Args:
        relative_path: Chart path, e.g. ``2_f24h/ECMWF500_..._f024.gif``.

    Returns:
        The matching ``numeric/<step>_<var>`` key, or None if no mapping.
    """
    # Deterministic daily-rain charts: day 1 → 0-24h window, day 2 → 24-48h.
    if "dailyrn" in relative_path:
        if "_1." in relative_path:
            return "numeric/0-24h_累積雨量"
        if "_2." in relative_path:
            return "numeric/24-48h_累積雨量"
        return None

    var = next((v for k, v in _NUMERIC_VAR_TOKENS.items() if k in relative_path), None)
    step = next(
        (v for k, v in _NUMERIC_STEP_TOKENS.items() if k in relative_path), None
    )
    if var and step:
        return f"numeric/{step}_{var}"
    return None


def _remap_numeric_to_charts(
    numeric_extractions: dict[str, str],
    replaced_paths: set[str],
) -> dict[str, str]:
    """Re-key numeric blocks onto the chart paths they replace.

    A block that matches a replaced chart moves from its ``numeric/...`` key to
    that chart's ``relative_path`` key, so it populates the chart's section.
    Blocks with no corresponding chart (forecast soundings, precip, station obs)
    keep their ``numeric/...`` key and feed only the synthesis.

    Args:
        numeric_extractions: Numeric blocks keyed by ``numeric/...``.
        replaced_paths: relative_paths of charts dropped from vision.

    Returns:
        Numeric blocks with matched entries re-keyed to chart paths.
    """
    out = dict(numeric_extractions)
    for path in replaced_paths:
        key = _numeric_key_for_chart(path)
        if key and key in out:
            out[path] = out.pop(key)
    return out


def _build_numeric_or_empty(
    target_date: date,
    numerical: "NumericalConfig",  # noqa: F821
    cwa_api_key: str | None = None,
) -> dict[str, str]:
    """Build numeric extraction blocks from config, degrading to ``{}``.

    Args:
        target_date: Report date (used as the ECMWF run date).
        numerical: Numeric pipeline configuration.
        cwa_api_key: CWA OpenData key for the observed surface-station block.

    Returns:
        Mapping of numeric extraction keys to text (empty on any failure).
    """
    try:
        from climate_auto.report.numeric import build_numeric_extractions

        return build_numeric_extractions(
            target_date,
            run_time=numerical.run_time,
            steps=tuple(numerical.steps),
            point=(numerical.sounding_lat, numerical.sounding_lon),
            cwa_api_key=cwa_api_key,
            surface_stations=numerical.surface_stations,
        )
    except Exception as exc:  # noqa: BLE001 - numeric route must never break the report
        logger.warning("Numeric route failed; falling back to image-only: {}", exc)
        return {}


def _apply_extractions_to_context(
    context: "ReportContext",  # noqa: F821
    extractions: dict[str, str],
) -> None:
    """Write per-chart extraction text into chart.analysis fields.

    Args:
        context: Report context to update in-place.
        extractions: Mapping of chart relative_path to extracted info text.
    """
    for section in context.sections:
        for subsection in section.subsections:
            for chart in subsection.charts:
                if chart.relative_path in extractions:
                    chart.analysis = extractions[chart.relative_path]


async def generate_report(
    base_dir: Path,
    target_date: date,
    analyzer: BaseAnalyzer | None = None,
    *,
    extract_only: bool = False,
    synthesize_only: bool = False,
    numerical: "NumericalConfig | None" = None,  # noqa: F821
    cwa_api_key: str | None = None,
) -> Path:
    """Generate a daily Markdown report from the report folder.

    Modes:
      - Default (no analyzer): Render template with placeholder text.
      - extract_only: Run Phase 1, save extractions.md, render without synthesis.
      - synthesize_only: Load extractions.md, run Phase 2, render full report.
      - Full (analyzer, no flags): Phase 1 → save → Phase 2 → render.

    Args:
        base_dir: Base data directory (e.g. ./data).
        target_date: Date for the report.
        analyzer: Optional chart analyzer.
        extract_only: If True, only run Phase 1 extraction.
        synthesize_only: If True, load extractions and run Phase 2 only.

    Returns:
        Path to the generated daily_report.md file.
    """
    date_dir = get_date_dir(base_dir, target_date)
    report_dir = date_dir / "report"

    if not report_dir.exists():
        msg = f"Report directory not found: {report_dir}"
        raise FileNotFoundError(msg)

    logger.info("Building report context from {}", report_dir)
    context = build_report_context(
        report_dir=report_dir,
        target_date=target_date.isoformat(),
        base_dir=base_dir,
        target_date_obj=target_date,
    )

    use_numeric = bool(numerical and numerical.enabled)

    if analyzer:
        all_charts = _collect_charts(context, report_dir)

        if synthesize_only:
            # Numeric blocks (if any) were saved into extractions.md at --extract.
            extractions = load_extractions(report_dir)
            _apply_extractions_to_context(context, extractions)
            context.synthesis = await run_synthesis(analyzer, extractions, all_charts)

        else:
            # --extract or full: optionally compute numeric blocks and skip the
            # image charts the numeric route replaces, then run vision on the rest.
            numeric_extractions: dict[str, str] = {}
            if use_numeric:
                patterns = numerical.replace_chart_patterns
                if not patterns:
                    logger.warning(
                        "Numeric route enabled but replace_chart_patterns is "
                        "empty; numeric blocks won't replace any chart section"
                    )
                replaced_paths = {
                    chart.relative_path
                    for chart, _ in all_charts
                    if any(p in chart.relative_path for p in patterns)
                }
                all_charts = _drop_replaced_charts(all_charts, patterns)
                # ECMWF/CWA downloads block; keep them off the event loop so a
                # web server stays responsive (SSE heartbeats, other requests).
                numeric_extractions = await asyncio.to_thread(
                    _build_numeric_or_empty, target_date, numerical, cwa_api_key
                )
                # Attach each numeric block to the chart section it replaces, so
                # the section shows numbers instead of "待分析".
                numeric_extractions = _remap_numeric_to_charts(
                    numeric_extractions, replaced_paths
                )

            extractions = await analyzer.extract_all(all_charts) if all_charts else {}
            extractions.update(numeric_extractions)
            if extractions:
                save_extractions(report_dir, extractions)
                _apply_extractions_to_context(context, extractions)

            if not extract_only and extractions:
                context.synthesis = await run_synthesis(
                    analyzer, extractions, all_charts
                )

    # Render template
    env = _create_jinja_env()
    template = env.get_template("daily_report.md.j2")
    rendered = template.render(ctx=context)

    output_path = report_dir / "daily_report.md"
    output_path.write_text(rendered, encoding="utf-8")
    logger.info("Report generated: {}", output_path)

    # Generate DOCX report from the rendered Markdown (sync python-docx work;
    # run off the event loop so it doesn't block a web server).
    from climate_auto.report.docx_exporter import generate_docx_from_markdown

    docx_path = await asyncio.to_thread(
        generate_docx_from_markdown, output_path, report_dir
    )
    logger.info("DOCX report generated: {}", docx_path)

    return output_path
