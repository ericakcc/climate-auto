"""Tests for the pipeline run endpoints and SSE streaming."""

import asyncio
import json
from pathlib import Path

import httpx
import pytest

from climate_auto.report.analyzer import BaseAnalyzer, PlaceholderAnalyzer
from climate_auto.report.generator import save_extractions
from climate_auto.report.models import ChartImage
from climate_auto.web.app import build_app

_CONFIG_PATH = Path("config/settings.yaml")


class _GatedAnalyzer(BaseAnalyzer):
    """Analyzer whose synthesize blocks until a gate is released."""

    def __init__(self, gate: asyncio.Event) -> None:
        self.gate = gate

    async def extract_info(self, chart: ChartImage, image_path: Path) -> str:
        return ""

    async def synthesize(
        self, extractions: dict[str, str], charts: list[tuple[ChartImage, Path]]
    ) -> str:
        await self.gate.wait()
        return "diagnosis"


def _setup_report(data_dir: Path, date_str: str, *, with_extractions: bool) -> Path:
    report_dir = data_dir / date_str / "report"
    for sub, name in [
        ("1_review/analysis", "ECMWF500_f000.gif"),
        ("1_review/sounding", "skewt_Taipei.gif"),
    ]:
        d = report_dir / sub
        d.mkdir(parents=True, exist_ok=True)
        (d / name).write_bytes(b"GIF89a")
    if with_extractions:
        save_extractions(
            report_dir,
            {"1_review/analysis/ECMWF500_f000.gif": "ridge to the east"},
        )
    return report_dir


def _make_app(data_dir: Path, analyzer_factory):
    return build_app(
        config_path=_CONFIG_PATH, data_dir=data_dir, analyzer_factory=analyzer_factory
    )


def _client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    )


async def _drain_stream(ac: httpx.AsyncClient, job_id: str) -> list[dict]:
    events: list[dict] = []
    async with ac.stream("GET", f"/api/stream/{job_id}") as resp:
        assert resp.status_code == 200
        event_type = None
        async for line in resp.aiter_lines():
            if line.startswith("event:"):
                event_type = line[len("event:") :].strip()
            elif line.startswith("data:") and event_type is not None:
                events.append(
                    {"type": event_type, "data": json.loads(line[len("data:") :])}
                )
                event_type = None
    return events


@pytest.mark.asyncio
async def test_synthesize_runs_and_writes_report(tmp_path: Path) -> None:
    date_str = "2026-06-04"
    report_dir = _setup_report(tmp_path, date_str, with_extractions=True)
    app = _make_app(tmp_path, lambda s: PlaceholderAnalyzer())

    async with _client(app) as ac:
        start = await ac.post("/api/synthesize", json={"date": date_str})
        assert start.status_code == 200
        job_id = start.json()["job_id"]
        events = await asyncio.wait_for(_drain_stream(ac, job_id), timeout=10)

    done = [e for e in events if e["type"] == "done"]
    assert len(done) == 1
    assert "report_url" in done[0]["data"]
    assert (report_dir / "daily_report.md").is_file()


@pytest.mark.asyncio
async def test_extract_runs_to_completion(tmp_path: Path) -> None:
    date_str = "2026-06-04"
    _setup_report(tmp_path, date_str, with_extractions=False)
    app = _make_app(tmp_path, lambda s: PlaceholderAnalyzer())

    async with _client(app) as ac:
        start = await ac.post("/api/extract", json={"date": date_str})
        assert start.status_code == 200
        events = await asyncio.wait_for(
            _drain_stream(ac, start.json()["job_id"]), timeout=10
        )

    assert any(e["type"] == "done" for e in events)


@pytest.mark.asyncio
async def test_concurrent_run_returns_409(tmp_path: Path) -> None:
    date_str = "2026-06-04"
    _setup_report(tmp_path, date_str, with_extractions=True)
    gate = asyncio.Event()
    app = _make_app(tmp_path, lambda s: _GatedAnalyzer(gate))

    async with _client(app) as ac:
        first = await ac.post("/api/synthesize", json={"date": date_str})
        assert first.status_code == 200

        second = await ac.post("/api/extract", json={"date": date_str})
        assert second.status_code == 409

        gate.set()
        await asyncio.wait_for(_drain_stream(ac, first.json()["job_id"]), timeout=10)


@pytest.mark.asyncio
async def test_run_endpoints_reject_impossible_date(tmp_path: Path) -> None:
    app = _make_app(tmp_path, lambda s: PlaceholderAnalyzer())
    async with _client(app) as ac:
        for path in ("/api/collect", "/api/extract", "/api/synthesize"):
            resp = await ac.post(path, json={"date": "2026-13-45"})
            assert resp.status_code == 400, path


@pytest.mark.asyncio
async def test_stream_unknown_job_returns_404(tmp_path: Path) -> None:
    app = _make_app(tmp_path, lambda s: PlaceholderAnalyzer())

    async with _client(app) as ac:
        resp = await ac.get("/api/stream/does-not-exist")
        assert resp.status_code == 404


@pytest.mark.asyncio
async def test_synthesize_without_llm_extra_returns_clear_error(tmp_path: Path) -> None:
    date_str = "2026-06-04"
    _setup_report(tmp_path, date_str, with_extractions=True)

    def _broken_factory(settings):
        raise ImportError("claude-agent-sdk not installed")

    app = _make_app(tmp_path, _broken_factory)

    async with _client(app) as ac:
        resp = await ac.post("/api/synthesize", json={"date": date_str})

    assert resp.status_code == 400
    assert "llm" in resp.json()["detail"].lower()
