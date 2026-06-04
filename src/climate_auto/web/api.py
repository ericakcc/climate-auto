"""HTTP handlers for the web editor API."""

import mimetypes
import re
from pathlib import Path
from urllib.parse import quote

from starlette.requests import Request
from starlette.responses import FileResponse, JSONResponse, Response

from climate_auto.report.generator import load_extractions, save_extractions
from climate_auto.web.paths import safe_image_path
from climate_auto.web.schemas import (
    DateInfo,
    DatesResponse,
    ExtractionBlock,
    ExtractionsResponse,
    ReportResponse,
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
    if not _DATE_RE.match(date_str):
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
                )
            )
    return JSONResponse(
        ExtractionsResponse(date=date_str, blocks=blocks).model_dump()
    )


async def put_extractions(request: Request) -> JSONResponse:
    """Persist edited extraction blocks back to extractions.md."""
    body = await request.json()
    req = SaveExtractionsRequest.model_validate(body)
    if not _DATE_RE.match(req.date):
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
    if not _DATE_RE.match(date_str):
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


async def get_job(request: Request) -> JSONResponse:
    """Return the current job-runner status."""
    manager = request.app.state.job_manager
    return JSONResponse(manager.status().model_dump())
