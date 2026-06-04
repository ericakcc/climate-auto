"""HTTP handlers for the web editor API."""

import mimetypes
import re
from collections.abc import Awaitable, Callable
from datetime import date as date_cls
from pathlib import Path
from typing import Any
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response, StreamingResponse

from climate_auto.config import Settings, load_settings
from climate_auto.report.numeric import NUMERIC_MARKER, OBSERVATION_MARKER
from climate_auto.report.generator import (
    generate_report,
    load_extractions,
    save_extractions,
)
from climate_auto.web.jobs import JobBusyError
from climate_auto.web.paths import safe_image_path
from climate_auto.web.schemas import (
    DateInfo,
    DatesResponse,
    ExtractionBlock,
    ExtractionsResponse,
    JobStartedResponse,
    ReportResponse,
    RunRequest,
    SaveExtractionsRequest,
    SaveResponse,
)

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_EXTRACTIONS = "extractions.md"
_DAILY_REPORT = "daily_report.md"


def _data_dir(request: Request) -> Path:
    return request.app.state.data_dir


def _report_dir(request: Request, date_str: str) -> Path:
    return _data_dir(request) / date_str / "report"


def _image_url(date_str: str, key: str) -> str:
    return f"/api/image?date={date_str}&path={quote(key, safe='/')}"


def _provenance(key: str, text: str) -> str:
    """Classify a block as numeric / observation / vision.

    Numeric blocks the route re-keyed onto a chart path keep a leading marker
    in their text, so we cannot rely on the key prefix alone.

    Args:
        key: Extraction key (chart relative_path or ``numeric/...``).
        text: The extraction body.

    Returns:
        "numeric", "observation", or "vision".
    """
    head = text.lstrip()
    if head.startswith(OBSERVATION_MARKER):
        return "observation"
    if head.startswith(NUMERIC_MARKER) or key.startswith("numeric/"):
        return "numeric"
    return "vision"


async def list_dates(request: Request) -> JSONResponse:
    """List data dates (most recent first) with artifact-presence flags."""
    data_dir = _data_dir(request)
    infos: list[DateInfo] = []
    if data_dir.is_dir():
        for child in data_dir.iterdir():
            if not (child.is_dir() and _DATE_RE.match(child.name)):
                continue
            report_dir = child / "report"
            infos.append(
                DateInfo(
                    date=child.name,
                    has_report_dir=report_dir.is_dir(),
                    has_extractions=(report_dir / _EXTRACTIONS).is_file(),
                    has_daily_report=(report_dir / _DAILY_REPORT).is_file(),
                )
            )
    infos.sort(key=lambda d: d.date, reverse=True)
    return JSONResponse(DatesResponse(dates=infos).model_dump())


async def get_extractions(request: Request) -> JSONResponse:
    """Return the editable extraction blocks for a date."""
    date_str = request.query_params.get("date", "")
    if _parse_date(date_str) is None:
        return JSONResponse({"detail": "invalid date"}, status_code=400)

    report_dir = _report_dir(request, date_str)
    if not report_dir.is_dir():
        return JSONResponse({"detail": "report directory not found"}, status_code=404)

    blocks: list[ExtractionBlock] = []
    if (report_dir / _EXTRACTIONS).is_file():
        data_dir = _data_dir(request)
        for key, text in load_extractions(report_dir).items():
            has_image = safe_image_path(data_dir, date_str, key) is not None
            blocks.append(
                ExtractionBlock(
                    key=key,
                    text=text,
                    exists=has_image,
                    image_url=_image_url(date_str, key) if has_image else None,
                    provenance=_provenance(key, text),
                )
            )
    return JSONResponse(ExtractionsResponse(date=date_str, blocks=blocks).model_dump())


async def put_extractions(request: Request) -> JSONResponse:
    """Persist edited extraction blocks back to extractions.md."""
    body = await request.json()
    req = SaveExtractionsRequest.model_validate(body)
    if _parse_date(req.date) is None:
        return JSONResponse({"detail": "invalid date"}, status_code=400)

    report_dir = _report_dir(request, req.date)
    if not report_dir.is_dir():
        return JSONResponse({"detail": "report directory not found"}, status_code=404)

    extractions = {block.key: block.text for block in req.blocks}
    path = save_extractions(report_dir, extractions)
    return JSONResponse(
        SaveResponse(path=str(path), count=len(extractions)).model_dump()
    )


async def get_image(request: Request) -> Response:
    """Serve a chart image from within the date's report directory."""
    date_str = request.query_params.get("date", "")
    rel = request.query_params.get("path", "")
    resolved = safe_image_path(_data_dir(request), date_str, rel)
    if resolved is None:
        return JSONResponse({"detail": "not found"}, status_code=404)
    media_type = mimetypes.guess_type(resolved.name)[0] or "application/octet-stream"
    return FileResponse(resolved, media_type=media_type)


async def get_report(request: Request) -> JSONResponse:
    """Return the rendered daily-report markdown for client-side rendering."""
    date_str = request.query_params.get("date", "")
    if _parse_date(date_str) is None:
        return JSONResponse({"detail": "invalid date"}, status_code=400)

    report_path = _report_dir(request, date_str) / _DAILY_REPORT
    if not report_path.is_file():
        return JSONResponse({"detail": "report not found"}, status_code=404)
    markdown = report_path.read_text(encoding="utf-8")
    return JSONResponse(
        ReportResponse(
            date=date_str,
            markdown=markdown,
            image_base=f"/api/image?date={date_str}&path=",
        ).model_dump()
    )


_DOWNLOADS = {
    "md": ("daily_report.md", "text/markdown"),
    "docx": (
        "daily_report.docx",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    ),
}


async def download(request: Request) -> Response:
    """Serve the generated report file as a download attachment."""
    date_str = request.query_params.get("date", "")
    kind = request.query_params.get("kind", "")
    if _parse_date(date_str) is None:
        return JSONResponse({"detail": "invalid date"}, status_code=400)
    if kind not in _DOWNLOADS:
        return JSONResponse({"detail": "invalid kind"}, status_code=400)

    filename, media_type = _DOWNLOADS[kind]
    path = _report_dir(request, date_str) / filename
    if not path.is_file():
        return JSONResponse({"detail": "not found"}, status_code=404)
    return FileResponse(
        path,
        media_type=media_type,
        filename=f"daily_report_{date_str}.{kind}",
    )


async def get_job(request: Request) -> JSONResponse:
    """Return the current job-runner status."""
    manager = request.app.state.job_manager
    return JSONResponse(manager.status().model_dump())


def _load_run_settings(request: Request) -> Settings:
    """Load settings, forcing data_dir to the app's resolved data directory."""
    settings = load_settings(request.app.state.config_path)
    return settings.model_copy(update={"data_dir": request.app.state.data_dir})


async def _start_job(
    request: Request,
    kind: str,
    date_str: str,
    coro_factory: Callable[[], Awaitable[Any]],
) -> JSONResponse:
    manager = request.app.state.job_manager
    try:
        job_id = await manager.start(kind, date_str, coro_factory)
    except JobBusyError:
        return JSONResponse(
            {"detail": "another job is already running"}, status_code=409
        )
    return JSONResponse(JobStartedResponse(job_id=job_id).model_dump())


def _parse_date(date_str: str) -> date_cls | None:
    """Parse a strict YYYY-MM-DD date string, or None if malformed/invalid.

    Guards against format-valid but impossible dates (e.g. 2026-13-45) that
    would otherwise raise ValueError deep in a handler and surface as a 500.
    """
    if not _DATE_RE.match(date_str):
        return None
    try:
        return date_cls.fromisoformat(date_str)
    except ValueError:
        return None


async def post_collect(request: Request) -> JSONResponse:
    """Start a data-collection job."""
    req = RunRequest.model_validate(await request.json())
    target = _parse_date(req.date)
    if target is None:
        return JSONResponse({"detail": "invalid date"}, status_code=400)

    from climate_auto.main import run_collection
    from climate_auto.models import SourceName

    settings = _load_run_settings(request)
    numerical = settings.numerical
    if req.numeric:
        numerical = numerical.model_copy(update={"enabled": True})

    sources = None
    if req.sources:
        try:
            sources = [SourceName(s) for s in req.sources]
        except ValueError:
            return JSONResponse({"detail": "unknown source"}, status_code=400)

    async def _coro() -> dict:
        await run_collection(target, settings, sources=sources, numerical=numerical)
        return {}

    return await _start_job(request, "collect", req.date, _coro)


async def post_extract(request: Request) -> JSONResponse:
    """Start a Phase 1 extraction job."""
    return await _run_report_job(request, extract_only=True, kind="extract")


async def post_synthesize(request: Request) -> JSONResponse:
    """Start a Phase 2 synthesis job."""
    return await _run_report_job(request, synthesize_only=True, kind="synthesize")


async def _run_report_job(
    request: Request,
    *,
    kind: str,
    extract_only: bool = False,
    synthesize_only: bool = False,
) -> JSONResponse:
    req = RunRequest.model_validate(await request.json())
    target = _parse_date(req.date)
    if target is None:
        return JSONResponse({"detail": "invalid date"}, status_code=400)

    settings = _load_run_settings(request)
    try:
        analyzer = request.app.state.analyzer_factory(settings)
    except ImportError:
        return JSONResponse(
            {"detail": "LLM support not installed. Run: uv sync --extra llm"},
            status_code=400,
        )

    numerical = settings.numerical
    if req.numeric:
        numerical = numerical.model_copy(update={"enabled": True})

    async def _coro() -> dict:
        await generate_report(
            settings.data_dir,
            target,
            analyzer=analyzer,
            extract_only=extract_only,
            synthesize_only=synthesize_only,
            numerical=numerical,
            cwa_api_key=settings.cwa_api_key,
        )
        if synthesize_only:
            return {"report_url": f"/api/report?date={req.date}"}
        return {}

    return await _start_job(request, kind, req.date, _coro)


async def stream(request: Request) -> Response:
    """Stream a job's progress as Server-Sent Events."""
    job_id = request.path_params["job_id"]
    manager = request.app.state.job_manager
    if not manager.exists(job_id):
        return JSONResponse({"detail": "unknown job"}, status_code=404)
    return StreamingResponse(
        manager.stream(job_id),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
