"""Base scraper abstract class."""

from abc import ABC, abstractmethod
from datetime import date
from pathlib import Path

from loguru import logger

from climate_auto.models import (
    DownloadResult,
    DownloadStatus,
    ProductInfo,
    ScraperReport,
    SourceName,
)


class BaseScraper(ABC):
    """Abstract base class for all weather data scrapers."""

    source: SourceName

    @abstractmethod
    async def discover_products(self, target_date: date) -> list[ProductInfo]:
        """Discover available products for the given date.

        Args:
            target_date: Date to discover products for.

        Returns:
            List of product descriptors.
        """

    @abstractmethod
    async def download_products(
        self, products: list[ProductInfo], target_dir: Path
    ) -> list[DownloadResult]:
        """Download discovered products.

        Args:
            products: Products to download.
            target_dir: Directory to save files.

        Returns:
            List of download results.
        """

    async def run(self, target_date: date, target_dir: Path) -> ScraperReport:
        """Execute the full scraping pipeline.

        Args:
            target_date: Date to collect data for.
            target_dir: Directory to save files.

        Returns:
            Report summarizing results.
        """
        logger.info("[{}] Starting collection for {}", self.source.value, target_date)

        products = await self.discover_products(target_date)
        logger.info("[{}] Discovered {} products", self.source.value, len(products))

        if not products:
            return ScraperReport(source=self.source)

        results = await self.download_products(products, target_dir)

        report = ScraperReport(
            source=self.source,
            total=len(results),
            success=sum(1 for r in results if r.status == DownloadStatus.SUCCESS),
            failed=sum(1 for r in results if r.status == DownloadStatus.FAILED),
            skipped=sum(
                1
                for r in results
                if r.status in (DownloadStatus.SKIPPED, DownloadStatus.NOT_AVAILABLE)
            ),
            results=results,
        )
        logger.info(
            "[{}] Done: {}/{} success, {} failed, {} skipped",
            self.source.value,
            report.success,
            report.total,
            report.failed,
            report.skipped,
        )
        return report
