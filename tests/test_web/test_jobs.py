"""Tests for the single-job manager and its loguru -> SSE bridge."""

import asyncio
import json

import pytest
from loguru import logger

from climate_auto.web.jobs import JobBusyError, JobManager


def _parse_sse(chunks: list[str]) -> list[dict]:
    """Extract (event, data) pairs from raw SSE text chunks."""
    events: list[dict] = []
    for chunk in chunks:
        lines = chunk.strip().splitlines()
        event_type = None
        data = None
        for line in lines:
            if line.startswith("event:"):
                event_type = line[len("event:") :].strip()
            elif line.startswith("data:"):
                data = json.loads(line[len("data:") :].strip())
        if event_type is not None:
            events.append({"type": event_type, "data": data})
    return events


async def _drain(manager: JobManager, job_id: str) -> list[dict]:
    chunks = [chunk async for chunk in manager.stream(job_id)]
    return _parse_sse(chunks)


@pytest.mark.asyncio
async def test_concurrent_start_raises_job_busy() -> None:
    manager = JobManager()
    gate = asyncio.Event()

    async def _slow() -> dict:
        await gate.wait()
        return {}

    job_id = await manager.start("collect", "2026-06-04", _slow)
    assert manager.running is True

    with pytest.raises(JobBusyError):
        await manager.start("extract", "2026-06-04", _slow)

    gate.set()
    await _drain(manager, job_id)
    assert manager.running is False


@pytest.mark.asyncio
async def test_stream_emits_log_then_done() -> None:
    manager = JobManager()

    async def _work() -> dict:
        logger.info("hello world")
        return {"report_url": "/api/report?date=2026-06-04"}

    job_id = await manager.start("synthesize", "2026-06-04", _work)
    events = await _drain(manager, job_id)

    logs = [e for e in events if e["type"] == "log"]
    done = [e for e in events if e["type"] == "done"]
    assert any("hello world" in e["data"]["text"] for e in logs)
    assert len(done) == 1
    assert done[0]["data"] == {"report_url": "/api/report?date=2026-06-04"}


@pytest.mark.asyncio
async def test_stream_emits_error_on_exception() -> None:
    manager = JobManager()

    async def _boom() -> dict:
        raise ValueError("boom happened")

    job_id = await manager.start("extract", "2026-06-04", _boom)
    events = await _drain(manager, job_id)

    errors = [e for e in events if e["type"] == "error"]
    assert len(errors) == 1
    assert "boom happened" in errors[0]["data"]["message"]
    assert manager.running is False


@pytest.mark.asyncio
async def test_sink_is_removed_after_job_completes() -> None:
    manager = JobManager()
    baseline = len(logger._core.handlers)

    async def _work() -> dict:
        logger.info("during job")
        return {}

    job_id = await manager.start("collect", "2026-06-04", _work)
    await _drain(manager, job_id)

    assert len(logger._core.handlers) == baseline


@pytest.mark.asyncio
async def test_reconnect_after_completion_replays_terminal_event() -> None:
    manager = JobManager()

    async def _work() -> dict:
        return {"report_url": "/api/report?date=2026-06-04"}

    job_id = await manager.start("synthesize", "2026-06-04", _work)
    first = await _drain(manager, job_id)
    assert any(e["type"] == "done" for e in first)

    # A second stream (e.g. after a page reload) must still see the outcome,
    # not hang, even though the queue was already fully consumed.
    second = await asyncio.wait_for(_drain(manager, job_id), timeout=1.0)
    assert any(e["type"] == "done" for e in second)


@pytest.mark.asyncio
async def test_status_reflects_running_then_idle() -> None:
    manager = JobManager()
    gate = asyncio.Event()

    async def _slow() -> dict:
        await gate.wait()
        return {}

    job_id = await manager.start("extract", "2026-06-04", _slow)
    status = manager.status()
    assert status.running is True
    assert status.kind == "extract"
    assert status.date == "2026-06-04"

    gate.set()
    await _drain(manager, job_id)
    assert manager.status().running is False
