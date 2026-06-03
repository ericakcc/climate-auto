"""Tests for the async image downloader."""

import asyncio
from pathlib import Path

import httpx
import pytest
import respx

from climate_auto.downloader import download_image
from climate_auto.models import DownloadStatus, ProductInfo, SourceName


def _product(url: str, filename: str) -> ProductInfo:
    return ProductInfo(
        source=SourceName.CWA_MAIN,
        name="test",
        url=url,
        filename=filename,
    )


@pytest.mark.asyncio
@respx.mock
async def test_download_image_write_failure_returns_failed(tmp_path: Path) -> None:
    url = "https://example.com/img.gif"
    respx.get(url).mock(return_value=httpx.Response(200, content=b"GIF89a\x00\x00"))

    # Make the destination path a directory so write_bytes raises OSError.
    (tmp_path / "img.gif").mkdir()

    async with httpx.AsyncClient() as client:
        result = await download_image(
            client,
            _product(url, "img.gif"),
            tmp_path,
            asyncio.Semaphore(1),
            max_retries=1,
        )

    assert result.status == DownloadStatus.FAILED
    assert "write" in result.error.lower()


@pytest.mark.asyncio
@respx.mock
async def test_download_image_success(tmp_path: Path) -> None:
    url = "https://example.com/ok.gif"
    respx.get(url).mock(return_value=httpx.Response(200, content=b"GIF89a\x01\x02\x03"))

    async with httpx.AsyncClient() as client:
        result = await download_image(
            client,
            _product(url, "ok.gif"),
            tmp_path,
            asyncio.Semaphore(1),
            max_retries=1,
        )

    assert result.status == DownloadStatus.SUCCESS
    assert (tmp_path / "ok.gif").read_bytes().startswith(b"GIF")
