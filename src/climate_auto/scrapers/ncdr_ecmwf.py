"""NCDR ECMWF Watch scraper - direct URL construction + batch download."""

from datetime import date
from pathlib import Path

import httpx
from loguru import logger

from climate_auto.config import NcdrEcmwfConfig
from climate_auto.downloader import download_batch
from climate_auto.models import DownloadResult, ProductInfo, SourceName
from climate_auto.scrapers.base import BaseScraper


class NcdrEcmwfScraper(BaseScraper):
    """Scraper for NCDR ECMWF Watch weather charts.

    Downloads ECMWF forecast charts (geopotential height, wind, moisture flux)
    at various pressure levels and forecast hours using direct URL construction.
    """

    source = SourceName.NCDR_ECMWF

    def __init__(
        self,
        config: NcdrEcmwfConfig,
        max_concurrent: int = 3,
        max_retries: int = 3,
        timeout: float = 30.0,
    ) -> None:
        self.config = config
        self.max_concurrent = max_concurrent
        self.max_retries = max_retries
        self.timeout = timeout

    async def _fetch_latest_init_time(self) -> str | None:
        """Fetch the latest available initialization time from the date API.

        Returns:
            Init time string (YYYYMMDDHH) or None if unavailable.
        """
        url = self.config.base_url + self.config.date_api
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            try:
                resp = await client.get(url)
                resp.raise_for_status()
                # Format: "CHART_ECMWF_FORECAST_0.25_date,202603181200"
                text = resp.text.strip()
                parts = text.split(",")
                if len(parts) >= 2:
                    # Take first 10 chars (YYYYMMDDHH)
                    init_time = parts[1].strip()[:10]
                    logger.info("Latest ECMWF init time: {}", init_time)
                    return init_time
            except httpx.RequestError as e:
                logger.error("Failed to fetch ECMWF date list: {}", e)
        return None

    def _build_chart_url(
        self, init_time: str, variable: str, forecast_hour: int
    ) -> str:
        """Build URL for an ECMWF chart image.

        Args:
            init_time: Initialization time (YYYYMMDDHH).
            variable: Variable code (e.g., "500", "850mf").
            forecast_hour: Forecast hour (e.g., 0, 24, 48).

        Returns:
            Full URL to the chart image.
        """
        yyyymm = init_time[:6]
        fhr = f"f{forecast_hour:03d}"
        filename = f"ECMWF{variable}_{init_time}_{fhr}.gif"
        return f"{self.config.base_url}{self.config.image_base}/{yyyymm}/{init_time}/{filename}"

    def _build_daily_rain_url(self, init_time: str, day: int) -> str:
        """Build URL for daily rainfall chart.

        Args:
            init_time: Initialization time (YYYYMMDDHH).
            day: Day number (1-9).

        Returns:
            Full URL to the daily rainfall image.
        """
        yyyymm = init_time[:6]
        filename = f"dailyrn_{init_time}_{day}.png"
        return f"{self.config.base_url}{self.config.image_base}/{yyyymm}/{init_time}/{filename}"

    def _build_ensemble_rain_url(self, init_time: str, day: int) -> str:
        """Build URL for ensemble rainfall chart.

        Args:
            init_time: Initialization time (YYYYMMDDHH).
            day: Day number (1-9).

        Returns:
            Full URL to the ensemble rainfall image.
        """
        yyyymm = init_time[:6]
        filename = f"dailyensrn_{init_time}_{day}_fdmx.png"
        return f"{self.config.base_url}{self.config.image_base}/{yyyymm}/{init_time}/{filename}"

    async def discover_products(self, target_date: date) -> list[ProductInfo]:
        """Discover ECMWF chart products for the given date.

        Args:
            target_date: Date to discover products for.

        Returns:
            List of product descriptors.
        """
        init_time = await self._fetch_latest_init_time()
        if not init_time:
            logger.error("Cannot discover ECMWF products: no init time available")
            return []

        products: list[ProductInfo] = []

        # Pressure level charts
        for var in self.config.variables:
            for fhr in self.config.forecast_hours:
                url = self._build_chart_url(init_time, var, fhr)
                products.append(
                    ProductInfo(
                        source=self.source,
                        name=f"ECMWF {var} f{fhr:03d}",
                        url=url,
                        filename=f"ECMWF{var}_{init_time}_f{fhr:03d}.gif",
                        description=f"ECMWF {var} hPa forecast +{fhr}h",
                    )
                )

        # Daily rainfall charts
        for day in self.config.daily_rain_days:
            rain_url = self._build_daily_rain_url(init_time, day)
            products.append(
                ProductInfo(
                    source=self.source,
                    name=f"Daily rain day {day}",
                    url=rain_url,
                    filename=f"dailyrn_{init_time}_{day}.png",
                    description=f"ECMWF deterministic daily rainfall day {day}",
                )
            )

            ens_url = self._build_ensemble_rain_url(init_time, day)
            products.append(
                ProductInfo(
                    source=self.source,
                    name=f"Ensemble rain day {day}",
                    url=ens_url,
                    filename=f"dailyensrn_{init_time}_{day}_fdmx.png",
                    description=f"ECMWF ensemble daily rainfall day {day}",
                )
            )

        return products

    async def download_products(
        self, products: list[ProductInfo], target_dir: Path
    ) -> list[DownloadResult]:
        """Download ECMWF products via direct HTTP.

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
