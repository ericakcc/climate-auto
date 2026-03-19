"""BOM MJO monitoring scraper - RMM phase diagrams and OLR charts."""

from datetime import date
from pathlib import Path

from climate_auto.models import DownloadResult, ProductInfo, SourceName
from climate_auto.scrapers.base import BaseScraper

_BOM_BASE = "https://www.bom.gov.au/clim_data/IDCKGEM000"

# Key MJO products
_MJO_PRODUCTS = [
    ("rmm.phase.Last40days.gif", "RMM phase 40 days"),
    ("rmm.phase.Last90days.gif", "RMM phase 90 days"),
    ("map_7.ps.png", "OLR anomaly 7-day"),
    ("olr_hovs_183_-15_15.ps.png", "OLR Hovmoller 183 days"),
    ("winds_hovs_u850_183_-15_15.ps.png", "U850 wind Hovmoller 183 days"),
]


class BomMjoScraper(BaseScraper):
    """Scraper for Australian BOM MJO monitoring products.

    Downloads RMM phase diagrams, OLR anomaly maps, and Hovmoller diagrams.
    Requires Referer header for access.
    """

    source = SourceName.BOM_MJO

    def __init__(
        self,
        max_concurrent: int = 2,
        max_retries: int = 3,
        timeout: float = 30.0,
    ) -> None:
        self.max_concurrent = max_concurrent
        self.max_retries = max_retries
        self.timeout = timeout

    async def discover_products(self, target_date: date) -> list[ProductInfo]:
        """Discover MJO products (static list).

        Args:
            target_date: Date to discover products for.

        Returns:
            List of product descriptors.
        """
        products: list[ProductInfo] = []
        for filename, description in _MJO_PRODUCTS:
            products.append(
                ProductInfo(
                    source=self.source,
                    name=description,
                    url=f"{_BOM_BASE}/{filename}",
                    filename=f"mjo_{filename}",
                    description=description,
                )
            )
        return products

    async def download_products(
        self, products: list[ProductInfo], target_dir: Path
    ) -> list[DownloadResult]:
        """Download MJO products with required Referer header.

        Args:
            products: Products to download.
            target_dir: Directory to save files.

        Returns:
            List of download results.
        """
        # BOM requires Referer header
        import asyncio

        import httpx

        from climate_auto.downloader import download_image

        target_dir.mkdir(parents=True, exist_ok=True)
        semaphore = asyncio.Semaphore(self.max_concurrent)
        headers = {"Referer": "https://www.bom.gov.au/climate/mjo/"}

        async with httpx.AsyncClient(
            timeout=self.timeout, follow_redirects=True, headers=headers
        ) as client:
            tasks = [
                download_image(
                    client,
                    product,
                    target_dir,
                    semaphore,
                    self.max_retries,
                )
                for product in products
            ]
            return await asyncio.gather(*tasks)
