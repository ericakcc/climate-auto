"""Single-job runner that bridges loguru output to Server-Sent Events.

Only one pipeline job (collect / extract / synthesize) runs at a time. While a
job runs, a per-job loguru sink forwards log records into an ``asyncio.Queue``,
which the SSE endpoint streams to the browser. The sink is always removed when
the job finishes, and a terminal ``done``/``error`` event is recorded so a late
or reconnecting client can still observe the outcome.
"""

import asyncio
import json
import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger

from climate_auto.web.schemas import JobStatusResponse

_HEARTBEAT_SECONDS = 15.0
_MAX_RECENT_JOBS = 16

CoroFactory = Callable[[], Awaitable[Any]]


class JobBusyError(RuntimeError):
    """Raised when a job is requested while another is already running."""


@dataclass
class JobRecord:
    """Bookkeeping for one pipeline job."""

    job_id: str
    kind: str
    date: str
    queue: asyncio.Queue = field(default_factory=asyncio.Queue)
    task: asyncio.Task | None = None
    done: bool = False
    terminal: dict | None = None


class JobManager:
    """Runs at most one pipeline job and streams its progress over SSE."""

    def __init__(self) -> None:
        self._current: JobRecord | None = None
        self._recent: dict[str, JobRecord] = {}

    @property
    def running(self) -> bool:
        """Whether a job is currently in progress."""
        return self._current is not None

    def status(self) -> JobStatusResponse:
        """Return the current runner status for UI recovery on reload."""
        if self._current is None:
            return JobStatusResponse(running=False)
        return JobStatusResponse(
            running=True,
            job_id=self._current.job_id,
            kind=self._current.kind,
            date=self._current.date,
        )

    async def start(self, kind: str, date: str, coro_factory: CoroFactory) -> str:
        """Start a job; raise JobBusyError if one is already running.

        Args:
            kind: Job kind ("collect" / "extract" / "synthesize").
            date: Target date string, for status reporting.
            coro_factory: Zero-arg async callable performing the work. Its
                return value (a dict, if any) becomes the ``done`` event data.

        Returns:
            The new job id.
        """
        if self._current is not None:
            raise JobBusyError("another job is already running")

        job_id = uuid.uuid4().hex
        record = JobRecord(job_id=job_id, kind=kind, date=date)
        # Claim the slot synchronously. This is the single-job guard: there is
        # no `await` between the check above and this assignment, so two
        # concurrent start() calls cannot both pass. Release the slot if setup
        # below fails, otherwise the manager would be wedged "busy" forever.
        self._current = record
        try:
            loop = asyncio.get_running_loop()
            sink_id = self._attach_sink(record.queue, loop, job_id)
            record.task = asyncio.create_task(self._run(record, coro_factory, sink_id))
        except Exception:
            self._current = None
            raise
        return job_id

    def _attach_sink(
        self, queue: asyncio.Queue, loop: asyncio.AbstractEventLoop, job_id: str
    ) -> int:
        """Attach a loguru sink that forwards this job's records to the queue."""

        def _sink(message: Any) -> None:
            record = message.record
            item = {
                "type": "log",
                "data": {
                    "level": record["level"].name,
                    "time": record["time"].strftime("%H:%M:%S"),
                    "text": record["message"],
                },
            }
            try:
                running = asyncio.get_running_loop()
            except RuntimeError:
                running = None
            if running is loop:
                queue.put_nowait(item)
            else:
                loop.call_soon_threadsafe(queue.put_nowait, item)

        return logger.add(
            _sink,
            level="INFO",
            format="{message}",
            filter=lambda r: r["extra"].get("job") == job_id,
        )

    async def _run(
        self, record: JobRecord, coro_factory: CoroFactory, sink_id: int
    ) -> None:
        terminal: dict
        try:
            # Run (and log any failure) inside the job's logging context so the
            # traceback is captured by the per-job sink and reaches the SSE feed.
            with logger.contextualize(job=record.job_id):
                try:
                    result = await coro_factory()
                    payload = result if isinstance(result, dict) else {}
                    terminal = {"type": "done", "data": payload}
                except Exception as exc:  # noqa: BLE001 - surfaced as an event
                    logger.exception("Job {} ({}) failed", record.job_id, record.kind)
                    terminal = {"type": "error", "data": {"message": str(exc)}}
        finally:
            logger.remove(sink_id)

        record.terminal = terminal
        record.done = True
        record.queue.put_nowait(terminal)
        record.queue.put_nowait(None)
        self._recent[record.job_id] = record
        self._prune_recent()
        self._current = None

    def _prune_recent(self) -> None:
        """Cap retained finished jobs so memory doesn't grow unbounded."""
        while len(self._recent) > _MAX_RECENT_JOBS:
            oldest = next(iter(self._recent))
            del self._recent[oldest]

    def _lookup(self, job_id: str) -> JobRecord | None:
        if self._current is not None and self._current.job_id == job_id:
            return self._current
        return self._recent.get(job_id)

    def exists(self, job_id: str) -> bool:
        """Whether the given job id is known (running or recently finished)."""
        return self._lookup(job_id) is not None

    async def stream(self, job_id: str) -> AsyncIterator[str]:
        """Yield SSE-formatted strings for the given job until it completes.

        Args:
            job_id: The job to stream.

        Yields:
            ``text/event-stream`` chunks (events and keep-alive comments).

        Raises:
            KeyError: If the job id is unknown.
        """
        record = self._lookup(job_id)
        if record is None:
            raise KeyError(job_id)

        queue = record.queue
        yield ": connected\n\n"

        # Hold a single pending get across heartbeats. Using asyncio.wait (not
        # wait_for) means a timeout does NOT cancel the get, so an item arriving
        # exactly at the heartbeat boundary is never dropped.
        pending: asyncio.Task | None = None
        try:
            while True:
                if pending is None and record.done and queue.empty():
                    # Reconnect after the queue was already drained: replay the
                    # terminal event so a late client still sees the outcome.
                    if record.terminal is not None:
                        yield _format_event(record.terminal)
                    break
                if pending is None:
                    pending = asyncio.ensure_future(queue.get())
                done, _ = await asyncio.wait({pending}, timeout=_HEARTBEAT_SECONDS)
                if pending not in done:
                    yield ": keep-alive\n\n"
                    continue
                item = pending.result()
                pending = None
                if item is None:
                    break
                yield _format_event(item)
        finally:
            if pending is not None:
                pending.cancel()


def _format_event(item: dict) -> str:
    """Render an event dict as an SSE message block."""
    data = json.dumps(item["data"], ensure_ascii=False)
    return f"event: {item['type']}\ndata: {data}\n\n"
