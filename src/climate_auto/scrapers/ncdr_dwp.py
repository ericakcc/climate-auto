"""NCDR DWP Watch scraper - AI weather model chart downloads."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from loguru import logger

from climate_auto.config import NcdrDwpConfig, NcdrDwpModelConfig
from climate_auto.downloader import download_batch
from climate_auto.models import DownloadResult, ProductInfo, SourceName
from climate_auto.scrapers.base import BaseScraper

_TW_TZ = timezone(timedelta(hours=8))


class NcdrDwpScraper(BaseScraper):
    """Scraper for NCDR DWP (Deep Weather Prediction) AI model charts."""

    source = SourceName.NCDR_DWP

    def __init__(
        self,
        config: NcdrDwpConfig,
        max_concurrent: int = 3,
        max_retries: int = 3,
        timeout: float = 30.0,
    ) -> None:
        self.config = config
        self.max_concurrent = max_concurrent
        self.max_retries = max_retries
        self.timeout = timeout

    async def _fetch_init_time(self, date_api_key: str) -> str | None:
        """Fetch the latest init time for a given model.

        Args:
            date_api_key: API key for the date list endpoint.

        Returns:
            Init time string (YYYYMMDDHH) or None.
        """
        url = f"{self.config.base_url}/php/list_realtime_date_csv?v={date_api_key}"
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                parts = resp.text.strip().split(",")
                if len(parts) >= 2:
                    return parts[1].strip()[:10]
            except httpx.RequestError as e:
                logger.error("Failed to fetch DWP date for {}: {}", date_api_key, e)
        return None

    def _build_url(
        self,
        model: NcdrDwpModelConfig,
        init_time: str,
        variable: str,
        forecast_hour: int,
    ) -> str:
        """Build image URL for a DWP model product.

        Args:
            model: Model configuration.
            init_time: Init time (YYYYMMDDHH).
            variable: Variable code.
            forecast_hour: Forecast hour.

        Returns:
            Full URL to the image.
        """
        yyyymm = init_time[:6]
        fhr = f"f{forecast_hour:04d}"

        # Compute valid time
        init_dt = datetime.strptime(init_time, "%Y%m%d%H").replace(tzinfo=_TW_TZ)
        valid_dt = init_dt + timedelta(hours=forecast_hour)
        valid_time = valid_dt.strftime("%Y%m%d%H")

        # AIFS has a different format: no valid_time suffix, 3-digit fhr
        if model.model_id == "AIFS":
            filename = f"AIFS{variable}_{init_time}_f{forecast_hour:03d}.gif"
            return (
                f"{self.config.base_url}{self.config.image_base}"
                f"/{model.directory}/{yyyymm}/{init_time}/{filename}"
            )

        filename = f"{model.prefix}_{variable}_{init_time}_{fhr}_{valid_time}.gif"
        return (
            f"{self.config.base_url}{self.config.image_base}"
            f"/{model.directory}/{yyyymm}/{init_time}/{filename}"
        )

    async def discover_products(self, target_date: date) -> list[ProductInfo]:
        """Discover DWP products for the given date.

        Args:
            target_date: Date to discover products for.

        Returns:
            List of product descriptors.
        """
        products: list[ProductInfo] = []

        for model in self.config.models:
            init_time = await self._fetch_init_time(model.date_api_key)
            if not init_time:
                logger.warning("Skipping DWP model {}: no init time", model.model_id)
                continue

            for var in self.config.variables:
                for fhr in self.config.forecast_hours:
                    url = self._build_url(model, init_time, var, fhr)
                    fname = url.split("/")[-1]
                    products.append(
                        ProductInfo(
                            source=self.source,
                            name=f"{model.prefix} {var} f{fhr:03d}",
                            url=url,
                            filename=fname,
                            description=f"{model.prefix} {var} +{fhr}h",
                        )
                    )

        return products

    async def download_products(
        self, products: list[ProductInfo], target_dir: Path
    ) -> list[DownloadResult]:
        """Download DWP products.

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
