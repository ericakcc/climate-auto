"""CLI entry point and orchestrator for daily weather data collection."""

from __future__ import annotations

import argparse
import asyncio
import sys
from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

from climate_auto.config import Settings, load_settings
from climate_auto.models import CollectionManifest, SourceName
from climate_auto.report.analyzer import BaseAnalyzer
from climate_auto.report.generator import generate_report
from climate_auto.report_selector import build_report_folder
from climate_auto.scrapers.base import BaseScraper
from climate_auto.scrapers.bom_mjo import BomMjoScraper
from climate_auto.scrapers.cwa_main import CwaMainScraper
from climate_auto.scrapers.cwa_marine import CwaMarineScraper
from climate_auto.scrapers.cwa_upper import CwaUpperAirScraper
from climate_auto.scrapers.ncdr_corrdiff import NcdrCorrdiffScraper
from climate_auto.scrapers.ncdr_dwp import NcdrDwpScraper
from climate_auto.scrapers.ncdr_ecmwf import NcdrEcmwfScraper
from climate_auto.storage import ensure_source_dir, save_manifest

_TW_TZ = timezone(timedelta(hours=8))

# (source_config_attr, factory). Factory receives (source_config, settings)
# and returns a BaseScraper. Sources whose config is None-typed (bom_mjo,
# cwa_upper) ignore the first argument.
_ScraperFactory = Callable[[object, Settings], BaseScraper]

_SCRAPER_REGISTRY: list[tuple[str, _ScraperFactory]] = [
    (
        "ncdr_ecmwf",
        lambda cfg, s: NcdrEcmwfScraper(
            cfg,
            max_concurrent=s.max_concurrent_downloads,
            max_retries=s.max_retries,
            timeout=s.request_timeout_seconds,
        ),
    ),
    (
        "ncdr_dwp",
        lambda cfg, s: NcdrDwpScraper(
            cfg,
            max_concurrent=s.max_concurrent_downloads,
            max_retries=s.max_retries,
            timeout=s.request_timeout_seconds,
        ),
    ),
    (
        "ncdr_corrdiff",
        lambda cfg, s: NcdrCorrdiffScraper(
            cfg,
            max_concurrent=s.max_concurrent_downloads,
            max_retries=s.max_retries,
            timeout=s.request_timeout_seconds,
        ),
    ),
    (
        "cwa_main",
        lambda cfg, s: CwaMainScraper(
            cfg,
            max_concurrent=s.max_concurrent_downloads,
            max_retries=s.max_retries,
            timeout=s.request_timeout_seconds,
        ),
    ),
    (
        "cwa_marine",
        lambda cfg, s: CwaMarineScraper(
            cfg,
            max_concurrent=s.max_concurrent_downloads,
            max_retries=s.max_retries,
            timeout=s.request_timeout_seconds,
        ),
    ),
    (
        "cwa_upper",
        lambda _cfg, s: CwaUpperAirScraper(
            max_concurrent=s.max_concurrent_downloads,
            max_retries=s.max_retries,
            timeout=s.request_timeout_seconds,
        ),
    ),
    (
        "bom_mjo",
        lambda _cfg, s: BomMjoScraper(
            max_concurrent=2,
            max_retries=s.max_retries,
            timeout=s.request_timeout_seconds,
        ),
    ),
]


def _build_scrapers(settings: Settings) -> list[BaseScraper]:
    """Build enabled scraper instances from settings.

    Args:
        settings: Application settings.

    Returns:
        List of enabled scraper instances.
    """
    scrapers: list[BaseScraper] = []
    for attr, factory in _SCRAPER_REGISTRY:
        cfg = getattr(settings.sources, attr)
        if getattr(cfg, "enabled", False):
            scrapers.append(factory(cfg, settings))
    return scrapers


async def run_collection(
    target_date: date,
    settings: Settings,
    sources: list[SourceName] | None = None,
    analyzer: BaseAnalyzer | None = None,
    dry_run: bool = False,
) -> CollectionManifest:
    """Run data collection for the given date.

    Args:
        target_date: Date to collect data for.
        settings: Application settings.
        sources: Optional list of specific sources to run. Runs all if None.
        analyzer: Optional LLM analyzer for chart interpretation.
        dry_run: If True, only discover products without downloading them.

    Returns:
        Collection manifest with results.
    """
    scrapers = _build_scrapers(settings)

    if sources:
        scrapers = [s for s in scrapers if s.source in sources]

    logger.info(
        "Starting {} for {} with {} scrapers",
        "dry-run" if dry_run else "collection",
        target_date,
        len(scrapers),
    )

    manifest = CollectionManifest(date=target_date.isoformat())

    async def _run_scraper(scraper: BaseScraper):
        target_dir = ensure_source_dir(settings.data_dir, target_date, scraper.source)
        try:
            if dry_run:
                products = await scraper.discover_products(target_date)
                logger.info(
                    "[{}] dry-run: would download {} products",
                    scraper.source.value,
                    len(products),
                )
                for p in products[:3]:
                    logger.info("[{}]   - {}", scraper.source.value, p.url)
                return None
            return await scraper.run(target_date, target_dir)
        except Exception as e:
            logger.error("[{}] Scraper failed: {}", scraper.source.value, e)
            return None

    results = await asyncio.gather(*[_run_scraper(s) for s in scrapers])

    if dry_run:
        logger.info("Dry-run complete; no files written, no report generated.")
        return manifest

    for report in results:
        if report:
            manifest.reports.append(report)

    save_manifest(settings.data_dir, target_date, manifest)

    total_success = sum(r.success for r in manifest.reports)
    total_failed = sum(r.failed for r in manifest.reports)
    total_skipped = sum(r.skipped for r in manifest.reports)
    logger.info(
        "Collection complete: {} success, {} failed, {} skipped",
        total_success,
        total_failed,
        total_skipped,
    )

    report_dir = build_report_folder(settings.data_dir, target_date)
    logger.info("Report folder: {}", report_dir)

    report_path = await generate_report(settings.data_dir, target_date, analyzer=analyzer)
    logger.info("Report generated: {}", report_path)

    return manifest


def _parse_sources(values: list[str]) -> list[SourceName]:
    """Parse --source CLI values into SourceName enums with a friendly error.

    Args:
        values: Raw source name strings from the CLI.

    Returns:
        List of validated SourceName values.
    """
    valid = {s.value for s in SourceName}
    parsed: list[SourceName] = []
    invalid: list[str] = []
    for v in values:
        if v in valid:
            parsed.append(SourceName(v))
        else:
            invalid.append(v)
    if invalid:
        valid_list = ", ".join(sorted(valid))
        raise SystemExit(f"Unknown source(s): {', '.join(invalid)}. Valid sources: {valid_list}")
    return parsed


def _configure_logging(settings: Settings, target_date: date, level: str) -> None:
    """Configure loguru sinks (stderr level + per-day rotating file).

    Args:
        settings: Application settings (for data_dir).
        target_date: Used to name the log file.
        level: stderr log level (DEBUG / INFO / WARNING).
    """
    logger.remove()
    logger.add(sys.stderr, level=level)
    log_dir = settings.data_dir / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    logger.add(log_dir / f"{target_date}.log", rotation="1 day", retention="30 days")


def main() -> None:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="TACOCO Weather Data Collector")
    parser.add_argument(
        "--date",
        type=str,
        default=None,
        help="Target date (YYYY-MM-DD). Defaults to today.",
    )
    parser.add_argument(
        "--config",
        type=str,
        default=None,
        help="Path to settings YAML file.",
    )
    parser.add_argument(
        "--source",
        type=str,
        nargs="*",
        default=None,
        help="Specific sources to run (e.g., ncdr_ecmwf cwa_main).",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        default=False,
        help="Skip data collection; generate report from existing data.",
    )
    parser.add_argument(
        "--analyze",
        action="store_true",
        default=False,
        help="Enable LLM chart analysis using Claude Agent SDK.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Discover products without downloading or generating a report.",
    )
    verbosity = parser.add_mutually_exclusive_group()
    verbosity.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        default=False,
        help="Enable DEBUG-level logging.",
    )
    verbosity.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        default=False,
        help="Only show WARNING-level logs and above.",
    )
    args = parser.parse_args()

    target_date = date.fromisoformat(args.date) if args.date else datetime.now(tz=_TW_TZ).date()

    config_path = Path(args.config) if args.config else Path("config/settings.yaml")
    settings = load_settings(config_path)

    sources = _parse_sources(args.source) if args.source else None

    log_level = "DEBUG" if args.verbose else "WARNING" if args.quiet else "INFO"
    _configure_logging(settings, target_date, log_level)

    analyzer: BaseAnalyzer | None = None
    if args.analyze or settings.analyzer.enabled:
        from climate_auto.report.claude_analyzer import ClaudeAnalyzer

        analyzer = ClaudeAnalyzer(settings.analyzer)
        logger.info("LLM analyzer enabled (model={})", settings.analyzer.model)

    if args.report_only:
        report_path = asyncio.run(
            generate_report(settings.data_dir, target_date, analyzer=analyzer)
        )
        logger.info("Report-only mode complete: {}", report_path)
    else:
        asyncio.run(
            run_collection(
                target_date,
                settings,
                sources,
                analyzer=analyzer,
                dry_run=args.dry_run,
            )
        )


if __name__ == "__main__":
    main()
