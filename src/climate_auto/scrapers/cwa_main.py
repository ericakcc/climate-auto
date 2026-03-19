"""CWA main website scraper - satellite, radar, rainfall charts."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path


from climate_auto.config import CwaMainConfig
from climate_auto.downloader import download_batch
from climate_auto.models import DownloadResult, ProductInfo, SourceName
from climate_auto.scrapers.base import BaseScraper

_TW_TZ = timezone(timedelta(hours=8))


class CwaMainScraper(BaseScraper):
    """Scraper for CWA main website weather imagery.

    Downloads satellite, radar, and rainfall preview images using
    known URL patterns.
    """

    source = SourceName.CWA_MAIN

    def __init__(
        self,
        config: CwaMainConfig,
        max_concurrent: int = 3,
        max_retries: int = 3,
        timeout: float = 30.0,
    ) -> None:
        self.config = config
        self.max_concurrent = max_concurrent
        self.max_retries = max_retries
        self.timeout = timeout

    async def discover_products(self, target_date: date) -> list[ProductInfo]:
        """Discover CWA weather image products.

        Args:
            target_date: Date to discover products for.

        Returns:
            List of product descriptors.
        """
        now = datetime.now(tz=_TW_TZ)
        products: list[ProductInfo] = []

        # Satellite preview images (always available)
        for sat_type in self.config.satellite_types:
            products.append(
                ProductInfo(
                    source=self.source,
                    name=f"Satellite {sat_type}",
                    url=f"{self.config.base_url}/Data/satellite/{sat_type}/{sat_type}_forPreview.jpg",
                    filename=f"satellite_{sat_type}_preview.jpg",
                    description=f"Satellite preview: {sat_type}",
                )
            )

        # Radar composite preview
        products.append(
            ProductInfo(
                source=self.source,
                name="Radar preview",
                url=f"{self.config.base_url}/Data/radar/CV1_TW_1000_forPreview.png",
                filename="radar_composite_preview.png",
                description="Radar composite preview image",
            )
        )

        # Try to get a timestamped radar image
        # Round down to nearest 10 minutes
        radar_time = now.replace(minute=(now.minute // 10) * 10, second=0)
        ts = radar_time.strftime("%Y%m%d%H%M")
        products.append(
            ProductInfo(
                source=self.source,
                name=f"Radar {ts}",
                url=f"{self.config.base_url}/Data/radar/{self.config.radar_prefix}_{ts}.png",
                filename=f"radar_{ts}.png",
                description=f"Radar composite at {ts}",
            )
        )

        # Rainfall preview
        products.append(
            ProductInfo(
                source=self.source,
                name="Rainfall preview",
                url=f"{self.config.base_url}/Data/rainfall/QZJ_forPreview.jpg",
                filename="rainfall_preview.jpg",
                description="Accumulated rainfall preview",
            )
        )

        # Temperature map
        products.append(
            ProductInfo(
                source=self.source,
                name="Temperature preview",
                url=f"{self.config.base_url}/Data/temperature/temp_forPreview.jpg",
                filename="temperature_preview.jpg",
                description="Temperature distribution preview",
            )
        )

        return products

    async def download_products(
        self, products: list[ProductInfo], target_dir: Path
    ) -> list[DownloadResult]:
        """Download CWA products.

        Args:
            products: Products to download.
            target_dir: Directory to save files.

        Returns:
            List of download results.
        """
        return await download_batch(
            products,
            target_dir,
            max_concurrent=self.max_concurrent,
            max_retries=self.max_retries,
            timeout=self.timeout,
        )
