"""Shared utilities for scraper implementations."""

import httpx
from loguru import logger


async def fetch_init_time_csv(url: str, timeout: float = 30.0) -> str | None:
    """Fetch a NCDR-style date CSV endpoint and return the latest init time.

    NCDR's `list_realtime_date_csv` endpoints return a single line of the form
    `<key>,<YYYYMMDDHHMM>`. This helper fetches the URL and returns the first
    10 characters (`YYYYMMDDHH`) of the second field.

    Args:
        url: Full CSV endpoint URL.
        timeout: HTTP timeout in seconds.

    Returns:
        Init time string (`YYYYMMDDHH`), or None if the request failed or the
        response was malformed.
    """
    async with httpx.AsyncClient(timeout=timeout) as client:
        try:
            resp = await client.get(url)
            resp.raise_for_status()
        except httpx.RequestError as e:
            logger.error("Failed to fetch init time from {}: {}", url, e)
            return None

    parts = resp.text.strip().split(",")
    if len(parts) < 2:
        logger.warning("Unexpected init-time response from {}: {!r}", url, resp.text)
        return None
    return parts[1].strip()[:10]
