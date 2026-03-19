"""Data models for weather data collection."""

from datetime import datetime
from enum import Enum
from pathlib import Path

from pydantic import BaseModel, Field


class SourceName(str, Enum):
    """Available data source identifiers."""

    CWA_MARINE = "cwa_marine"
    CWA_MAIN = "cwa_main"
    CWA_UPPER = "cwa_upper"
    NCDR_ECMWF = "ncdr_ecmwf"
    NCDR_DWP = "ncdr_dwp"
    NCDR_CORRDIFF = "ncdr_corrdiff"
    BOM_MJO = "bom_mjo"


class DownloadStatus(str, Enum):
    """Status of a download attempt."""

    SUCCESS = "success"
    FAILED = "failed"
    SKIPPED = "skipped"
    NOT_AVAILABLE = "not_available"


class ProductInfo(BaseModel):
    """Describes a single product (image) to download."""

    source: SourceName
    name: str
    url: str
    filename: str
    description: str = ""


class DownloadResult(BaseModel):
    """Result of a single download attempt."""

    product: ProductInfo
    status: DownloadStatus
    file_path: Path | None = None
    file_size: int = 0
    http_status: int = 0
    error: str = ""
    downloaded_at: datetime = Field(default_factory=datetime.now)


class ScraperReport(BaseModel):
    """Summary report for a single scraper run."""

    source: SourceName
    total: int = 0
    success: int = 0
    failed: int = 0
    skipped: int = 0
    results: list[DownloadResult] = Field(default_factory=list)


class CollectionManifest(BaseModel):
    """Manifest tracking all downloads for a given date."""

    date: str
    collected_at: datetime = Field(default_factory=datetime.now)
    reports: list[ScraperReport] = Field(default_factory=list)
