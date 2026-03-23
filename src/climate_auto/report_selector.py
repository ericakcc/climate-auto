"""Select and organize report-relevant files from downloaded data."""

import shutil
from datetime import date
from pathlib import Path

from loguru import logger

from climate_auto.storage import get_date_dir

# Mapping: report section -> (source_dir, filename glob pattern, target subfolder)
# Based on TACOCO discussion meeting report structure
REPORT_FILE_MAPPING: list[tuple[str, str, str, str]] = [
    # === Section 1: Daily review (當日回顧) ===
    # I. Analysis field (分析場)
    ("1_review/analysis", "ncdr_ecmwf", "ECMWF500_*_f000.gif", "500hPa analysis"),
    (
        "1_review/analysis",
        "ncdr_ecmwf",
        "ECMWF850mf_*_f000.gif",
        "850hPa wind & water vapor flux analysis",
    ),
    ("1_review/analysis", "ncdr_ecmwf", "ECMWF700_*_f000.gif", "700hPa analysis"),
    # II. Sounding (探空)
    (
        "1_review/sounding",
        "cwa_upper",
        "skewt_Taipei_*.gif",
        "Taipei sounding (Skew-T)",
    ),
    # III. Precipitation (降水熱區)
    ("1_review/precip", "cwa_main", "radar_*.png", "Radar composite"),
    ("1_review/precip", "cwa_main", "rainfall_*.jpg", "Accumulated rainfall"),
    # IV. Surface charts (地面天氣圖)
    ("1_review/surface", "cwa_upper", "surface_asia_*.gif", "Surface chart Asia"),
    ("1_review/surface", "cwa_upper", "surface_taiwan_*.gif", "Surface chart Taiwan"),
    # Upper-air CWA analysis charts
    ("1_review/upperair", "cwa_upper", "upperair_850hPa_*.gif", "CWA 850hPa analysis"),
    ("1_review/upperair", "cwa_upper", "upperair_700hPa_*.gif", "CWA 700hPa analysis"),
    ("1_review/upperair", "cwa_upper", "upperair_500hPa_*.gif", "CWA 500hPa analysis"),
    # === Section 2: f24h forecast (f24h預報再確認) ===
    ("2_f24h", "ncdr_ecmwf", "ECMWF500_*_f024.gif", "500hPa +24h forecast"),
    (
        "2_f24h",
        "ncdr_ecmwf",
        "ECMWF850mf_*_f024.gif",
        "850hPa wind & water vapor flux +24h",
    ),
    ("2_f24h", "ncdr_ecmwf", "ECMWF700_*_f024.gif", "700hPa +24h"),
    ("2_f24h", "ncdr_ecmwf", "dailyrn_*_1.png", "ECMWF daily rain day 1"),
    ("2_f24h", "ncdr_ecmwf", "dailyensrn_*_1_fdmx.png", "ECMWF ensemble rain day 1"),
    # === Section 3: f48h forecast (f48h預報場綜觀分析) ===
    # I. WPSH (太平洋高壓)
    ("3_f48h", "ncdr_ecmwf", "ECMWF500_*_f048.gif", "500hPa +48h forecast"),
    # II. Moisture transport & low-level wind
    (
        "3_f48h",
        "ncdr_ecmwf",
        "ECMWF850mf_*_f048.gif",
        "850hPa wind & water vapor flux +48h",
    ),
    ("3_f48h", "ncdr_ecmwf", "ECMWF700_*_f048.gif", "700hPa +48h"),
    ("3_f48h", "ncdr_ecmwf", "dailyrn_*_2.png", "ECMWF daily rain day 2"),
    ("3_f48h", "ncdr_ecmwf", "dailyensrn_*_2_fdmx.png", "ECMWF ensemble rain day 2"),
    # === MJO context ===
    (
        "4_context/mjo",
        "bom_mjo",
        "mjo_rmm.phase.Last40days.gif",
        "MJO RMM phase 40 days",
    ),
    (
        "4_context/mjo",
        "bom_mjo",
        "mjo_rmm.phase.Last90days.gif",
        "MJO RMM phase 90 days",
    ),
    ("4_context/mjo", "bom_mjo", "mjo_map_7.ps.png", "OLR anomaly 7-day"),
]


def build_report_folder(base_dir: Path, target_date: date) -> Path:
    """Copy report-relevant files into an organized report folder.

    Args:
        base_dir: Base data directory.
        target_date: Target date.

    Returns:
        Path to the report folder.
    """
    date_dir = get_date_dir(base_dir, target_date)
    report_dir = date_dir / "report"

    if report_dir.exists():
        shutil.rmtree(report_dir)

    copied = 0
    skipped = 0

    for target_subfolder, source_name, pattern, description in REPORT_FILE_MAPPING:
        source_dir = date_dir / source_name
        if not source_dir.exists():
            logger.debug("Source dir not found: {}", source_dir)
            skipped += 1
            continue

        matches = list(source_dir.glob(pattern))
        if not matches:
            logger.debug("No match for {} in {}", pattern, source_name)
            skipped += 1
            continue

        dest_dir = report_dir / target_subfolder
        dest_dir.mkdir(parents=True, exist_ok=True)

        for src_file in matches:
            dest_file = dest_dir / src_file.name
            shutil.copy2(src_file, dest_file)
            copied += 1
            logger.debug("Copied: {} -> {}", src_file.name, target_subfolder)

    logger.info(
        "Report folder built: {} files copied, {} patterns skipped -> {}",
        copied,
        skipped,
        report_dir,
    )
    return report_dir
