"""CLI entry point and orchestrator for daily weather data collection."""

from __future__ import annotations

import argparse
import asyncio
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from loguru import logger

from climate_auto.config import NumericalConfig, Settings, load_settings
from climate_auto.models import CollectionManifest, SourceName
from climate_auto.scrapers.base import BaseScraper
from climate_auto.scrapers.bom_mjo import BomMjoScraper
from climate_auto.scrapers.cwa_main import CwaMainScraper
from climate_auto.scrapers.cwa_marine import CwaMarineScraper
from climate_auto.scrapers.cwa_upper import CwaUpperAirScraper
from climate_auto.scrapers.ncdr_corrdiff import NcdrCorrdiffScraper
from climate_auto.scrapers.ncdr_dwp import NcdrDwpScraper
from climate_auto.scrapers.ncdr_ecmwf import NcdrEcmwfScraper
from climate_auto.report.analyzer import BaseAnalyzer
from climate_auto.report.generator import generate_report
from climate_auto.report_selector import build_report_folder
from climate_auto.storage import ensure_source_dir, save_manifest

_TW_TZ = timezone(timedelta(hours=8))


def _build_scrapers(settings: Settings) -> list[BaseScraper]:
    """Build enabled scraper instances from settings.

    Args:
        settings: Application settings.

    Returns:
        List of enabled scraper instances.
    """
    scrapers: list[BaseScraper] = []
    sources = settings.sources

    if sources.ncdr_ecmwf.enabled:
        scrapers.append(
            NcdrEcmwfScraper(
                sources.ncdr_ecmwf,
                max_concurrent=settings.max_concurrent_downloads,
                max_retries=settings.max_retries,
                timeout=settings.request_timeout_seconds,
            )
        )
    if sources.ncdr_dwp.enabled:
        scrapers.append(
            NcdrDwpScraper(
                sources.ncdr_dwp,
                max_concurrent=settings.max_concurrent_downloads,
                max_retries=settings.max_retries,
                timeout=settings.request_timeout_seconds,
            )
        )
    if sources.ncdr_corrdiff.enabled:
        scrapers.append(
            NcdrCorrdiffScraper(
                sources.ncdr_corrdiff,
                max_concurrent=settings.max_concurrent_downloads,
                max_retries=settings.max_retries,
                timeout=settings.request_timeout_seconds,
            )
        )
    if sources.cwa_main.enabled:
        scrapers.append(
            CwaMainScraper(
                sources.cwa_main,
                max_concurrent=settings.max_concurrent_downloads,
                max_retries=settings.max_retries,
                timeout=settings.request_timeout_seconds,
            )
        )
    if sources.cwa_marine.enabled:
        scrapers.append(
            CwaMarineScraper(
                sources.cwa_marine,
                max_concurrent=settings.max_concurrent_downloads,
                max_retries=settings.max_retries,
                timeout=settings.request_timeout_seconds,
            )
        )

    # CWA Upper-air (sounding, surface/upper charts) - always enabled
    scrapers.append(
        CwaUpperAirScraper(
            max_concurrent=settings.max_concurrent_downloads,
            max_retries=settings.max_retries,
            timeout=settings.request_timeout_seconds,
        )
    )

    # BOM MJO - always enabled
    scrapers.append(
        BomMjoScraper(
            max_concurrent=2,
            max_retries=settings.max_retries,
            timeout=settings.request_timeout_seconds,
        )
    )

    return scrapers


async def run_collection(
    target_date: date,
    settings: Settings,
    sources: list[SourceName] | None = None,
    analyzer: "BaseAnalyzer | None" = None,
    numerical: "NumericalConfig | None" = None,
) -> CollectionManifest:
    """Run data collection for the given date.

    Args:
        target_date: Date to collect data for.
        settings: Application settings.
        sources: Optional list of specific sources to run. Runs all if None.

    Returns:
        Collection manifest with results.
    """
    scrapers = _build_scrapers(settings)

    if sources:
        scrapers = [s for s in scrapers if s.source in sources]

    logger.info(
        "Starting collection for {} with {} scrapers",
        target_date,
        len(scrapers),
    )

    manifest = CollectionManifest(date=target_date.isoformat())

    # Run all scrapers concurrently
    async def _run_scraper(scraper: BaseScraper):
        target_dir = ensure_source_dir(settings.data_dir, target_date, scraper.source)
        try:
            return await scraper.run(target_date, target_dir)
        except Exception as e:
            logger.error("[{}] Scraper failed: {}", scraper.source.value, e)
            return None

    results = await asyncio.gather(*[_run_scraper(s) for s in scrapers])

    for report in results:
        if report:
            manifest.reports.append(report)

    save_manifest(settings.data_dir, target_date, manifest)

    # Print summary
    total_success = sum(r.success for r in manifest.reports)
    total_failed = sum(r.failed for r in manifest.reports)
    total_skipped = sum(r.skipped for r in manifest.reports)
    logger.info(
        "Collection complete: {} success, {} failed, {} skipped",
        total_success,
        total_failed,
        total_skipped,
    )

    # Build report folder with relevant files only
    report_dir = build_report_folder(settings.data_dir, target_date)
    logger.info("Report folder: {}", report_dir)

    # Generate Markdown report
    report_path = await generate_report(
        settings.data_dir,
        target_date,
        analyzer=analyzer,
        numerical=numerical,
        cwa_api_key=settings.cwa_api_key,
    )
    logger.info("Report generated: {}", report_path)

    return manifest


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
    analysis_group = parser.add_mutually_exclusive_group()
    analysis_group.add_argument(
        "--analyze",
        action="store_true",
        default=False,
        help="Run full LLM pipeline (extract + synthesize).",
    )
    analysis_group.add_argument(
        "--extract",
        action="store_true",
        default=False,
        help="Phase 1 only: extract chart info, save extractions.md. "
        "Edit the file, then run --synthesize.",
    )
    analysis_group.add_argument(
        "--synthesize",
        action="store_true",
        default=False,
        help="Phase 2 only: load extractions.md, synthesize diagnosis, "
        "render report.",
    )
    parser.add_argument(
        "--numeric",
        action="store_true",
        help="Enable the numeric (ECMWF) route: compute height/moisture/forecast-"
        "sounding fields and merge into extractions instead of reading those GIFs.",
    )
    args = parser.parse_args()

    # Determine target date
    if args.date:
        target_date = date.fromisoformat(args.date)
    else:
        target_date = datetime.now(tz=_TW_TZ).date()

    # Load settings
    config_path = Path(args.config) if args.config else Path("config/settings.yaml")
    settings = load_settings(config_path)

    # Parse sources
    sources = None
    if args.source:
        sources = [SourceName(s) for s in args.source]

    # Configure logging
    logger.add(
        settings.data_dir / "logs" / f"{target_date}.log",
        rotation="1 day",
        retention="30 days",
    )

    # Initialize analyzer if requested
    needs_analyzer = (
        args.analyze or args.extract or args.synthesize or settings.analyzer.enabled
    )
    analyzer = None
    if needs_analyzer:
        from climate_auto.report.claude_analyzer import ClaudeAnalyzer

        analyzer = ClaudeAnalyzer(settings.analyzer)
        logger.info("LLM analyzer enabled (model={})", settings.analyzer.model)

    # Numeric route: enable via --numeric flag or settings.numerical.enabled.
    numerical_cfg = settings.numerical
    if args.numeric:
        numerical_cfg = numerical_cfg.model_copy(update={"enabled": True})
    if numerical_cfg.enabled:
        logger.info("Numeric (ECMWF) route enabled (steps={})", numerical_cfg.steps)

    # --extract and --synthesize imply --report-only
    report_only = args.report_only or args.extract or args.synthesize

    if report_only:
        report_path = asyncio.run(
            generate_report(
                settings.data_dir,
                target_date,
                analyzer=analyzer,
                extract_only=args.extract,
                synthesize_only=args.synthesize,
                numerical=numerical_cfg,
                cwa_api_key=settings.cwa_api_key,
            )
        )
        logger.info("Report-only mode complete: {}", report_path)
    else:
        asyncio.run(
            run_collection(
                target_date,
                settings,
                sources,
                analyzer=analyzer,
                numerical=numerical_cfg,
            )
        )


if __name__ == "__main__":
    main()
