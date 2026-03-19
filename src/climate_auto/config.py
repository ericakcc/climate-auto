"""Configuration management using Pydantic Settings."""

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings


class BrowserConfig(BaseModel):
    """Playwright browser configuration."""

    headless: bool = True
    viewport_width: int = 1920
    viewport_height: int = 1080


class NcdrEcmwfConfig(BaseModel):
    """NCDR ECMWF Watch scraper configuration."""

    enabled: bool = True
    base_url: str = "https://watch.ncdr.nat.gov.tw"
    image_base: str = "/00_Wxmap/2F7_ECMWF_0.25deg"
    date_api: str = "/php/list_realtime_date_csv?v=CHART_ECMWF_FORECAST_0.25"
    variables: list[str] = Field(
        default=["500", "850", "850mf", "700", "200", "1000", "8530"]
    )
    forecast_hours: list[int] = Field(default=[0, 24, 48])
    daily_rain_days: list[int] = Field(default=[1, 2, 3])


class NcdrDwpModelConfig(BaseModel):
    """Configuration for a single DWP AI model."""

    model_id: str
    directory: str
    prefix: str
    date_api_key: str
    forecast_step: int = 12
    max_steps: int = 24


class NcdrDwpConfig(BaseModel):
    """NCDR DWP Watch scraper configuration."""

    enabled: bool = True
    base_url: str = "https://watch.ncdr.nat.gov.tw"
    image_base: str = "/00_Wxmap"
    variables: list[str] = Field(default=["500", "850", "QV850"])
    forecast_hours: list[int] = Field(default=[0, 24, 48])
    models: list[NcdrDwpModelConfig] = Field(
        default=[
            NcdrDwpModelConfig(
                model_id="ECGC",
                directory="2F13_EC_GRAPHCAST_0.25deg",
                prefix="EC_GRAPHCAST",
                date_api_key="CHART_ECMWF_FORECAST",
                max_steps=24,
            ),
            NcdrDwpModelConfig(
                model_id="ECMWF",
                directory="2F9_EC_PAUGU_0.25deg",
                prefix="EC_PANGU",
                date_api_key="CHART_ECMWF_FORECAST",
                max_steps=180,
            ),
            NcdrDwpModelConfig(
                model_id="AIFS",
                directory="2F17_EC_AIFS_0.25deg",
                prefix="AIFS",
                date_api_key="CHART_ECMWF_FORECAST",
                max_steps=30,
            ),
        ]
    )


class NcdrCorrdiffModelConfig(BaseModel):
    """Configuration for a single CorrDiff model."""

    name: str
    directory: str
    model_code: str


class NcdrCorrdiffConfig(BaseModel):
    """NCDR CorrDiff Watch scraper configuration."""

    enabled: bool = True
    base_url: str = "https://watch.ncdr.nat.gov.tw"
    image_base: str = "/00_Wxmap"
    date_api: str = "/wh/jn_corrdiff_date"
    parameters: list[str] = Field(default=["radar_wind", "tw_t2m", "sp", "rr"])
    forecast_hours: list[int] = Field(default=[0, 6, 12, 24, 48])
    models: list[NcdrCorrdiffModelConfig] = Field(
        default=[
            NcdrCorrdiffModelConfig(
                name="ECMWF",
                directory="2F14_ECMWF_CORRDIFF",
                model_code="ec",
            ),
            NcdrCorrdiffModelConfig(
                name="AIFS",
                directory="2F14_EC_AIFS_CORRDIFF",
                model_code="aifs",
            ),
        ]
    )


class CwaMainConfig(BaseModel):
    """CWA main website scraper configuration."""

    enabled: bool = True
    base_url: str = "https://www.cwa.gov.tw"
    satellite_types: list[str] = Field(default=["LCC_IR1_CR_2750", "LCC_TRGB_1000"])
    radar_prefix: str = "CV1_3600"


class CwaMarineConfig(BaseModel):
    """CWA NPD Marine model scraper configuration."""

    enabled: bool = True
    base_url: str = "https://npd.cwa.gov.tw"
    products: list[dict[str, str]] = Field(
        default=[
            {"model": "495", "domain": "496", "variable": "499"},
            {"model": "495", "domain": "496", "variable": "498"},
        ]
    )


class SourcesConfig(BaseModel):
    """All data source configurations."""

    ncdr_ecmwf: NcdrEcmwfConfig = Field(default_factory=NcdrEcmwfConfig)
    ncdr_dwp: NcdrDwpConfig = Field(default_factory=NcdrDwpConfig)
    ncdr_corrdiff: NcdrCorrdiffConfig = Field(default_factory=NcdrCorrdiffConfig)
    cwa_main: CwaMainConfig = Field(default_factory=CwaMainConfig)
    cwa_marine: CwaMarineConfig = Field(default_factory=CwaMarineConfig)


class Settings(BaseSettings):
    """Application settings."""

    data_dir: Path = Path("./data")
    timezone: str = "Asia/Taipei"
    max_retries: int = 3
    retry_delay_seconds: float = 2.0
    request_timeout_seconds: float = 30.0
    max_concurrent_downloads: int = 3
    browser: BrowserConfig = Field(default_factory=BrowserConfig)
    sources: SourcesConfig = Field(default_factory=SourcesConfig)


def load_settings(config_path: Path | None = None) -> Settings:
    """Load settings from YAML config file.

    Args:
        config_path: Path to YAML config file. Uses defaults if None.

    Returns:
        Loaded settings instance.
    """
    if config_path and config_path.exists():
        raw: dict[str, Any] = yaml.safe_load(config_path.read_text()) or {}
        return Settings(**raw)
    return Settings()
