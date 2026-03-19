"""CWA NPD Marine model scraper - ocean current & wave forecast charts."""

from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
from loguru import logger

from climate_auto.config import CwaMarineConfig
from climate_auto.downloader import download_batch
from climate_auto.models import DownloadResult, ProductInfo, SourceName
from climate_auto.scrapers.base import BaseScraper

_TW_TZ = timezone(timedelta(hours=8))

# Variable code mapping from probe results
_VARIABLE_NAMES = {
    "499": "current_uv",  # Surface current velocity
    "498": "sst",  # Sea surface temperature
}


class CwaMarineScraper(BaseScraper):
    """Scraper for CWA NPD marine model forecast charts.

    Uses the NPD API endpoints to discover available products
    and download forecast chart images.
    """

    source = SourceName.CWA_MARINE

    def __init__(
        self,
        config: CwaMarineConfig,
        max_concurrent: int = 3,
        max_retries: int = 3,
        timeout: float = 30.0,
    ) -> None:
        self.config = config
        self.max_concurrent = max_concurrent
        self.max_retries = max_retries
        self.timeout = timeout

    async def _fetch_product_info(
        self, client: httpx.AsyncClient, product_cfg: dict[str, str]
    ) -> list[dict[str, str]]:
        """Fetch available image paths from NPD API for a product config.

        Args:
            client: httpx async client.
            product_cfg: Product configuration with model/domain/variable IDs.

        Returns:
            List of dicts with 'url' and 'filename' keys.
        """
        try:
            resp = await client.post(
                f"{self.config.base_url}/NPD/common/get_irisme_data",
                data={
                    "model": product_cfg["model"],
                    "domain": product_cfg["domain"],
                    "variable": product_cfg["variable"],
                },
            )
            resp.raise_for_status()
            data = resp.json()
            # API returns list of image paths
            if isinstance(data, list) and data:
                return [{"path": item} for item in data if isinstance(item, str)]
            if isinstance(data, dict) and "data" in data:
                return [
                    {"path": item} for item in data["data"] if isinstance(item, str)
                ]
        except (httpx.RequestError, ValueError) as e:
            logger.error("Failed to fetch marine product info: {}", e)
        return []

    def _guess_init_times(self) -> list[str]:
        """Generate candidate init times to try.

        Returns:
            List of init time strings (YYMMDDHH) in 2-digit year format,
            ordered from most recent to oldest.
        """
        now = datetime.now(tz=_TW_TZ)
        candidates: list[str] = []
        for hours_back in [12, 24, 0, 36]:
            dt = now - timedelta(hours=hours_back)
            for h in [12, 0]:
                candidate = dt.replace(hour=h, minute=0, second=0)
                ts = candidate.strftime("%y%m%d%H")
                if ts not in candidates:
                    candidates.append(ts)
        return candidates

    async def discover_products(self, target_date: date) -> list[ProductInfo]:
        """Discover marine model products by probing candidate init times.

        Args:
            target_date: Date to discover products for.

        Returns:
            List of product descriptors.
        """
        products: list[ProductInfo] = []
        init_candidates = self._guess_init_times()

        # Variable URL segment mapping
        var_url_segment = {"499": "UV", "498": "T"}

        async with httpx.AsyncClient(timeout=self.timeout) as client:
            for init_time in init_candidates:
                # Probe with first forecast hour to see if this init time exists
                test_url = (
                    f"{self.config.base_url}/NPD/irisme_data/Oceangrf/OCM"
                    f"/{init_time}/WRF_tri_{init_time}_OCM_UV_000.gif"
                )
                try:
                    resp = await client.head(test_url)
                    if resp.status_code == 200:
                        logger.info("Found marine init time: {}", init_time)
                        # Build products for this init time
                        forecast_hours = list(range(0, 73, 3))
                        for product_cfg in self.config.products:
                            var_code = product_cfg["variable"]
                            var_name = _VARIABLE_NAMES.get(var_code, f"var{var_code}")
                            url_seg = var_url_segment.get(var_code, "UV")

                            for fhr in forecast_hours:
                                url = (
                                    f"{self.config.base_url}/NPD/irisme_data/Oceangrf/OCM"
                                    f"/{init_time}/WRF_tri_{init_time}_OCM_{url_seg}_{fhr:03d}.gif"
                                )
                                products.append(
                                    ProductInfo(
                                        source=self.source,
                                        name=f"Marine {var_name} f{fhr:03d}",
                                        url=url,
                                        filename=f"marine_{var_name}_{init_time}_f{fhr:03d}.gif",
                                        description=f"Marine {var_name} forecast +{fhr}h",
                                    )
                                )
                        return products
                except httpx.RequestError:
                    continue

        logger.warning("No available marine init time found")
        return products

    async def download_products(
        self, products: list[ProductInfo], target_dir: Path
    ) -> list[DownloadResult]:
        """Download marine model products.

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
