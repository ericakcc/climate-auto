"""NCDR CorrDiff Watch scraper - NVIDIA CorrDiff downscaling products."""

from datetime import date
from pathlib import Path

import httpx
from loguru import logger

from climate_auto.config import NcdrCorrdiffConfig
from climate_auto.downloader import download_batch
from climate_auto.models import DownloadResult, ProductInfo, SourceName
from climate_auto.scrapers.base import BaseScraper


class NcdrCorrdiffScraper(BaseScraper):
    """Scraper for NCDR CorrDiff AI downscaling products."""

    source = SourceName.NCDR_CORRDIFF

    def __init__(
        self,
        config: NcdrCorrdiffConfig,
        max_concurrent: int = 3,
        max_retries: int = 3,
        timeout: float = 30.0,
    ) -> None:
        self.config = config
        self.max_concurrent = max_concurrent
        self.max_retries = max_retries
        self.timeout = timeout

    async def _fetch_init_times(self) -> dict[str, str]:
        """Fetch latest init times for all CorrDiff models.

        Returns:
            Dict mapping model name to init time (YYYYMMDDHH).
        """
        url = self.config.base_url + self.config.date_api
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                # Returns: {"initial":"...","ecmwf":"...","aifs":"...","mpas":"..."}
                data: dict[str, str] = resp.json()
                logger.info("CorrDiff init times: {}", data)
                return data
            except httpx.RequestError as e:
                logger.error("Failed to fetch CorrDiff dates: {}", e)
        return {}

    def _build_url(
        self, directory: str, model_code: str, param: str, init_time: str, hour: int
    ) -> str:
        """Build image URL for a CorrDiff product.

        Args:
            directory: Model directory name.
            model_code: Model code (e.g., "ec", "aifs").
            param: Parameter name (e.g., "radar_wind").
            init_time: Init time (YYYYMMDDHH).
            hour: Forecast hour.

        Returns:
            Full URL to the image.
        """
        filename = f"corrdiff_{model_code}_{param}_{init_time}_{hour:03d}h.jpg"
        return (
            f"{self.config.base_url}{self.config.image_base}"
            f"/{directory}/{init_time}/{filename}"
        )

    async def discover_products(self, target_date: date) -> list[ProductInfo]:
        """Discover CorrDiff products.

        Args:
            target_date: Date to discover products for.

        Returns:
            List of product descriptors.
        """
        init_times = await self._fetch_init_times()
        if not init_times:
            return []

        products: list[ProductInfo] = []

        for model_cfg in self.config.models:
            # Map model name to init_times key
            key = model_cfg.model_code
            if key == "ec":
                key = "ecmwf"
            init_time = init_times.get(key)
            if not init_time:
                logger.warning("No init time for CorrDiff model {}", model_cfg.name)
                continue

            for param in self.config.parameters:
                for hour in self.config.forecast_hours:
                    url = self._build_url(
                        model_cfg.directory,
                        model_cfg.model_code,
                        param,
                        init_time,
                        hour,
                    )
                    fname = url.split("/")[-1]
                    products.append(
                        ProductInfo(
                            source=self.source,
                            name=f"CorrDiff {model_cfg.name} {param} f{hour:03d}",
                            url=url,
                            filename=fname,
                            description=f"CorrDiff {model_cfg.name} {param} +{hour}h",
                        )
                    )

        return products

    async def download_products(
        self, products: list[ProductInfo], target_dir: Path
    ) -> list[DownloadResult]:
        """Download CorrDiff products.

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
