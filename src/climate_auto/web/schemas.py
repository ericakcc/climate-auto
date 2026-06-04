"""Pydantic request/response models for the web editor API."""

from pydantic import BaseModel, Field


class DateInfo(BaseModel):
    """Summary of one data date and which artifacts already exist."""

    date: str
    has_report_dir: bool
    has_extractions: bool
    has_daily_report: bool


class DatesResponse(BaseModel):
    """List of available data dates (most recent first)."""

    dates: list[DateInfo]


class ExtractionBlock(BaseModel):
    """One editable extraction block plus its chart image, if any."""

    key: str
    text: str
    exists: bool
    image_url: str | None = None
    # "numeric" (computed field), "observation" (measured), or "vision" (LLM read).
    provenance: str = "vision"


class ExtractionsResponse(BaseModel):
    """All extraction blocks for a given date."""

    date: str
    blocks: list[ExtractionBlock]


class SaveExtractionsRequest(BaseModel):
    """Payload for persisting edited extraction blocks."""

    date: str
    blocks: list[ExtractionBlock]


class SaveResponse(BaseModel):
    """Result of saving extractions to disk."""

    path: str
    count: int


class RunRequest(BaseModel):
    """Payload to start a pipeline job (collect / extract / synthesize)."""

    date: str
    numeric: bool = False
    sources: list[str] | None = None


class JobStartedResponse(BaseModel):
    """Returned when a pipeline job has been accepted."""

    job_id: str


class JobStatusResponse(BaseModel):
    """Current job-runner status, for UI state recovery on reload."""

    running: bool
    job_id: str | None = None
    kind: str | None = None
    date: str | None = None


class ReportResponse(BaseModel):
    """Raw daily-report markdown plus the base for relative image links."""

    date: str
    markdown: str
    image_base: str = Field(
        description="URL prefix for resolving relative image links in the markdown."
    )
