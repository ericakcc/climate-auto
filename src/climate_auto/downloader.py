"""Async HTTP downloader with retry and concurrency control."""

import asyncio
from pathlib import Path

import httpx
from loguru import logger

from climate_auto.models import DownloadResult, DownloadStatus, ProductInfo


async def download_image(
    client: httpx.AsyncClient,
    product: ProductInfo,
    target_dir: Path,
    semaphore: asyncio.Semaphore,
    max_retries: int = 3,
    retry_delay: float = 2.0,
) -> DownloadResult:
    """Download a single image with retry logic.

    Args:
        client: httpx async client.
        product: Product info describing what to download.
        target_dir: Directory to save the file.
        semaphore: Concurrency limiter.
        max_retries: Maximum retry attempts.
        retry_delay: Base delay between retries (exponential backoff).

    Returns:
        Download result with status and metadata.
    """
    file_path = target_dir / product.filename

    async with semaphore:
        for attempt in range(max_retries):
            try:
                resp = await client.get(product.url)

                if resp.status_code == 404:
                    logger.debug("Not available (404): {}", product.filename)
                    return DownloadResult(
                        product=product,
                        status=DownloadStatus.NOT_AVAILABLE,
                        http_status=404,
                    )

                resp.raise_for_status()
                content = resp.content

                # Validate it's actually an image
                if not _is_image_content(content):
                    logger.warning("Non-image content for {}", product.filename)
                    return DownloadResult(
                        product=product,
                        status=DownloadStatus.FAILED,
                        http_status=resp.status_code,
                        error="Response is not image content",
                    )

                file_path.write_bytes(content)
                logger.debug(
                    "Downloaded: {} ({} bytes)", product.filename, len(content)
                )
                return DownloadResult(
                    product=product,
                    status=DownloadStatus.SUCCESS,
                    file_path=file_path,
                    file_size=len(content),
                    http_status=resp.status_code,
                )

            except httpx.HTTPStatusError as e:
                logger.warning(
                    "HTTP {} for {} (attempt {}/{})",
                    e.response.status_code,
                    product.filename,
                    attempt + 1,
                    max_retries,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (2**attempt))
            except httpx.RequestError as e:
                logger.warning(
                    "Request error for {} (attempt {}/{}): {}",
                    product.filename,
                    attempt + 1,
                    max_retries,
                    e,
                )
                if attempt < max_retries - 1:
                    await asyncio.sleep(retry_delay * (2**attempt))

    return DownloadResult(
        product=product,
        status=DownloadStatus.FAILED,
        error=f"Failed after {max_retries} attempts",
    )


async def download_batch(
    products: list[ProductInfo],
    target_dir: Path,
    max_concurrent: int = 3,
    max_retries: int = 3,
    retry_delay: float = 2.0,
    timeout: float = 30.0,
) -> list[DownloadResult]:
    """Download a batch of products concurrently.

    Args:
        products: List of products to download.
        target_dir: Directory to save files.
        max_concurrent: Maximum concurrent downloads.
        max_retries: Maximum retry attempts per download.
        retry_delay: Base delay between retries.
        timeout: HTTP request timeout in seconds.

    Returns:
        List of download results.
    """
    target_dir.mkdir(parents=True, exist_ok=True)
    semaphore = asyncio.Semaphore(max_concurrent)

    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        tasks = [
            download_image(
                client, product, target_dir, semaphore, max_retries, retry_delay
            )
            for product in products
        ]
        return await asyncio.gather(*tasks)


def _is_image_content(data: bytes) -> bool:
    """Check if data starts with known image magic bytes."""
    if len(data) < 4:
        return False
    # GIF87a, GIF89a
    if data[:3] == b"GIF":
        return True
    # PNG
    if data[:4] == b"\x89PNG":
        return True
    # JPEG
    if data[:2] == b"\xff\xd8":
        return True
    return False
