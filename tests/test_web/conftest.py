"""Shared fixtures for web editor tests."""

from collections.abc import Callable
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from climate_auto.web.app import build_app

_CONFIG_PATH = Path("config/settings.yaml")


@pytest.fixture
def data_dir(tmp_path: Path) -> Path:
    """The base data directory used by the app under test."""
    return tmp_path


@pytest.fixture
def make_client(data_dir: Path) -> Callable[..., TestClient]:
    """Factory building a TestClient over an app rooted at the temp data dir."""

    def _make(analyzer_factory: Callable | None = None) -> TestClient:
        app = build_app(
            config_path=_CONFIG_PATH,
            data_dir=data_dir,
            analyzer_factory=analyzer_factory,
        )
        return TestClient(app)

    return _make


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    """A TestClient with no analyzer (sufficient for read-only endpoints)."""
    return make_client()


def make_report_dir(data_dir: Path, date_str: str) -> Path:
    """Create and return ``data_dir/{date}/report``."""
    report_dir = data_dir / date_str / "report"
    report_dir.mkdir(parents=True, exist_ok=True)
    return report_dir
