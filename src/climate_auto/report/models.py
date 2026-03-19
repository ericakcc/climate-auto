"""Pydantic models for report generation."""

from datetime import datetime

from pydantic import BaseModel, Field


class ChartImage(BaseModel):
    """A single chart image in the report."""

    relative_path: str
    description: str
    analysis: str = ""


class ReportSubsection(BaseModel):
    """A subsection within a report section (e.g. 'analysis', 'sounding')."""

    id: str
    title: str
    charts: list[ChartImage] = Field(default_factory=list)


class ReportSection(BaseModel):
    """A major report section (e.g. '1_review', '2_f24h')."""

    id: str
    title: str
    subsections: list[ReportSubsection] = Field(default_factory=list)


class ManifestSummary(BaseModel):
    """Summary of data availability for the report."""

    total_downloaded: int = 0
    total_in_report: int = 0
    missing_patterns: list[str] = Field(default_factory=list)


class ReportContext(BaseModel):
    """Full context for rendering a daily report template."""

    date: str
    generated_at: datetime = Field(default_factory=datetime.now)
    sections: list[ReportSection] = Field(default_factory=list)
    summary: ManifestSummary = Field(default_factory=ManifestSummary)
