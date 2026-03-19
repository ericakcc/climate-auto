"""Main report generator: discovery + analyzer + Jinja2 rendering."""

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


async def generate_report(
    base_dir: Path,
    target_date: date,
    analyzer: BaseAnalyzer | None = None,
) -> Path:
    """Generate a daily Markdown report from the report folder.

    Args:
        base_dir: Base data directory (e.g. ./data).
        target_date: Date for the report.
        analyzer: Optional chart analyzer. Uses no analysis if None.

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

    # Run analyzer on each section batch if provided
    if analyzer:
        for section in context.sections:
            batch: list[tuple[ChartImage, Path]] = []
            for subsection in section.subsections:
                for chart in subsection.charts:
                    image_path = report_dir / chart.relative_path
                    if image_path.exists():
                        batch.append((chart, image_path))
            if batch:
                results = await analyzer.analyze_batch(batch, section.title)
                for chart, _ in batch:
                    if chart.relative_path in results:
                        chart.analysis = results[chart.relative_path]

    # Render template
    env = _create_jinja_env()
    template = env.get_template("daily_report.md.j2")
    rendered = template.render(ctx=context)

    output_path = report_dir / "daily_report.md"
    output_path.write_text(rendered, encoding="utf-8")
    logger.info("Report generated: {}", output_path)

    # Generate DOCX report from the rendered Markdown
    from climate_auto.report.docx_exporter import generate_docx_from_markdown

    docx_path = generate_docx_from_markdown(output_path, report_dir)
    logger.info("DOCX report generated: {}", docx_path)

    return output_path
