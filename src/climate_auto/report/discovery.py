"""Discover chart images in the report folder and build ReportContext."""

from datetime import datetime
from pathlib import Path

from loguru import logger

from climate_auto.report.models import (
    ChartImage,
    ManifestSummary,
    ReportContext,
    ReportSection,
    ReportSubsection,
)
from climate_auto.report_selector import REPORT_FILE_MAPPING
from climate_auto.storage import load_manifest

# Section metadata: section_id -> (title, {subsection_id: title})
SECTION_METADATA: dict[str, tuple[str, dict[str, str]]] = {
    "1_review": (
        "當日回顧",
        {
            "analysis": "分析場",
            "sounding": "探空",
            "precip": "降水熱區",
            "surface": "地面天氣圖",
            "upperair": "高空分析圖",
        },
    ),
    "2_f24h": (
        "f24h 預報再確認",
        {},
    ),
    "3_f48h": (
        "f48h 預報場綜觀分析",
        {},
    ),
    "4_context": (
        "綜觀背景",
        {
            "mjo": "MJO",
        },
    ),
}


def _parse_target_subfolder(subfolder: str) -> tuple[str, str | None]:
    """Parse target_subfolder into (section_id, subsection_id).

    Args:
        subfolder: e.g. "1_review/analysis" or "2_f24h"

    Returns:
        Tuple of (section_id, subsection_id or None).
    """
    parts = subfolder.split("/", maxsplit=1)
    section_id = parts[0]
    subsection_id = parts[1] if len(parts) > 1 else None
    return section_id, subsection_id


def build_report_context(
    report_dir: Path,
    target_date: str,
    base_dir: Path | None = None,
    target_date_obj: "None | __import__('datetime').date" = None,
) -> ReportContext:
    """Scan the report directory and build a ReportContext.

    Args:
        report_dir: Path to the report/ folder.
        target_date: Date string for the report title.
        base_dir: Base data dir (for loading manifest summary).
        target_date_obj: Date object (for loading manifest).

    Returns:
        Populated ReportContext.
    """
    # Track sections and subsections in order
    sections_map: dict[str, dict[str, list[ChartImage]]] = {}
    section_order: list[str] = []
    subsection_order: dict[str, list[str]] = {}
    missing_patterns: list[str] = []
    total_in_report = 0

    for target_subfolder, _source_name, pattern, description in REPORT_FILE_MAPPING:
        section_id, subsection_id = _parse_target_subfolder(target_subfolder)

        # Track ordering
        if section_id not in sections_map:
            sections_map[section_id] = {}
            section_order.append(section_id)
            subsection_order[section_id] = []

        sub_key = subsection_id or "_root"
        if sub_key not in sections_map[section_id]:
            sections_map[section_id][sub_key] = []
            subsection_order[section_id].append(sub_key)

        # Find matching files
        scan_dir = report_dir / target_subfolder
        if not scan_dir.exists():
            logger.debug("Report subfolder not found: {}", scan_dir)
            missing_patterns.append(f"{target_subfolder}/{pattern}")
            continue

        matches = sorted(scan_dir.glob(pattern))
        if not matches:
            logger.debug("No match for {} in {}", pattern, scan_dir)
            missing_patterns.append(f"{target_subfolder}/{pattern}")
            continue

        for match in matches:
            rel_path = match.relative_to(report_dir)
            chart = ChartImage(
                relative_path=str(rel_path),
                description=description,
            )
            sections_map[section_id][sub_key].append(chart)
            total_in_report += 1

    # Build structured sections
    sections: list[ReportSection] = []
    for sec_id in section_order:
        sec_title, sub_titles = SECTION_METADATA.get(sec_id, (sec_id, {}))
        subsections: list[ReportSubsection] = []

        for sub_key in subsection_order[sec_id]:
            charts = sections_map[sec_id][sub_key]
            if not charts:
                continue
            if sub_key == "_root":
                sub_title = sec_title
            else:
                sub_title = sub_titles.get(sub_key, sub_key)
            subsections.append(
                ReportSubsection(id=sub_key, title=sub_title, charts=charts)
            )

        if subsections:
            sections.append(
                ReportSection(id=sec_id, title=sec_title, subsections=subsections)
            )

    # Manifest summary
    total_downloaded = 0
    if base_dir and target_date_obj:
        manifest = load_manifest(base_dir, target_date_obj)
        if manifest:
            total_downloaded = sum(r.success for r in manifest.reports)

    summary = ManifestSummary(
        total_downloaded=total_downloaded,
        total_in_report=total_in_report,
        missing_patterns=missing_patterns,
    )

    return ReportContext(
        date=target_date,
        generated_at=datetime.now(),
        sections=sections,
        summary=summary,
    )
