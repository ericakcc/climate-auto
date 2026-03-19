"""CWA NPD upper-air products scraper - sounding, surface charts, upper-air charts."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from loguru import logger

from climate_auto.downloader import download_batch
from climate_auto.models import DownloadResult, ProductInfo, SourceName
from climate_auto.scrapers.base import BaseScraper

_TW_TZ = timezone(timedelta(hours=8))

# Taipei sounding station (Banqiao)
_SOUNDING_STATIONS = {
    "46692": "Taipei",
    "46699": "Hualien",
}

# Surface weather chart types
_SURFACE_CHART_TYPES = {
    "103": "asia",
    "024": "taiwan",
}

# Upper-air analysis variables
_UPPER_AIR_VARIABLES = {
    "022": "925hPa",
    "001": "850hPa",
    "002": "700hPa",
    "003": "500hPa",
    "004": "300hPa",
    "005": "200hPa",
}


class CwaUpperAirScraper(BaseScraper):
    """Scraper for CWA NPD upper-air products.

    Downloads sounding plots (Skew-T), surface weather charts,
    and upper-air analysis charts from npd1.cwa.gov.tw.
    """

    source = SourceName.CWA_UPPER

    def __init__(
        self,
        max_concurrent: int = 3,
        max_retries: int = 3,
        timeout: float = 30.0,
    ) -> None:
        self.base_url = "https://npd1.cwa.gov.tw"
        self.image_base = "/NPD/irisme_data"
        self.max_concurrent = max_concurrent
        self.max_retries = max_retries
        self.timeout = timeout

    def _get_init_times(self) -> list[str]:
        """Get candidate init times (YYMMDDHH) for today's 00Z and 12Z.

        Returns:
            List of init time strings to try.
        """
        now = datetime.now(tz=_TW_TZ)
        candidates: list[str] = []
        for offset_hours in [0, 12, 24]:
            dt = now - timedelta(hours=offset_hours)
            for h in [12, 0]:
                ts = dt.replace(hour=h).strftime("%y%m%d%H")
                if ts not in candidates:
                    candidates.append(ts)
        return candidates

    async def discover_products(self, target_date: date) -> list[ProductInfo]:
        """Discover upper-air products.

        Args:
            target_date: Date to discover products for.

        Returns:
            List of product descriptors.
        """
        init_times = self._get_init_times()
        products: list[ProductInfo] = []

        # Find available init time by probing
        available_init: str | None = None
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for init_time in init_times:
                test_url = (
                    f"{self.base_url}{self.image_base}/Weather/SKEWT"
                    f"/SKW___000_{init_time}_46692.gif"
                )
                try:
                    resp = await client.head(test_url)
                    if resp.status_code == 200:
                        available_init = init_time
                        logger.info("Found CWA sounding init time: {}", init_time)
                        break
                except httpx.RequestError:
                    continue

        if not available_init:
            logger.warning("No CWA sounding init time found")
            return []

        # Skew-T sounding plots
        for station_id, station_name in _SOUNDING_STATIONS.items():
            url = (
                f"{self.base_url}{self.image_base}/Weather/SKEWT"
                f"/SKW___000_{available_init}_{station_id}.gif"
            )
            products.append(
                ProductInfo(
                    source=self.source,
                    name=f"Skew-T {station_name}",
                    url=url,
                    filename=f"skewt_{station_name}_{available_init}.gif",
                    description=f"Sounding plot for {station_name} ({station_id})",
                )
            )

        # Surface weather charts
        for chart_type, chart_name in _SURFACE_CHART_TYPES.items():
            url = (
                f"{self.base_url}{self.image_base}/Weather/ANALYSIS"
                f"/GRA___000_{available_init}_{chart_type}.gif"
            )
            products.append(
                ProductInfo(
                    source=self.source,
                    name=f"Surface chart {chart_name}",
                    url=url,
                    filename=f"surface_{chart_name}_{available_init}.gif",
                    description=f"Surface weather chart: {chart_name}",
                )
            )

        # Upper-air analysis charts
        for var_code, var_name in _UPPER_AIR_VARIABLES.items():
            url = (
                f"{self.base_url}{self.image_base}/Weather/HLANALYSIS"
                f"/GRA___000_{available_init}_{var_code}.gif"
            )
            products.append(
                ProductInfo(
                    source=self.source,
                    name=f"Upper-air {var_name}",
                    url=url,
                    filename=f"upperair_{var_name}_{available_init}.gif",
                    description=f"Upper-air analysis: {var_name}",
                )
            )

        return products

    async def download_products(
        self, products: list[ProductInfo], target_dir: Path
    ) -> list[DownloadResult]:
        """Download upper-air products.

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
