"""Starlette application factory for the local web editor."""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import FileResponse
from starlette.routing import Mount, Route
from starlette.staticfiles import StaticFiles

from climate_auto.config import Settings, load_settings
from climate_auto.web import api
from climate_auto.web.jobs import JobManager

DEFAULT_CONFIG_PATH = Path("config/settings.yaml")
_WEB_DIR = Path(__file__).parent
_TEMPLATES_DIR = _WEB_DIR / "templates"
_STATIC_DIR = _WEB_DIR / "static"

AnalyzerFactory = Callable[[Settings], Any]


async def _index(request: Request) -> FileResponse:
    """Serve the single-page editor."""
    return FileResponse(_TEMPLATES_DIR / "editor.html", media_type="text/html")


def _default_analyzer_factory(settings: Settings) -> Any:
    """Build the real Claude analyzer (lazy import keeps the llm extra optional)."""
    from climate_auto.report.claude_analyzer import ClaudeAnalyzer

    return ClaudeAnalyzer(settings.analyzer)


def build_app(
    *,
    config_path: Path = DEFAULT_CONFIG_PATH,
    data_dir: Path | None = None,
    analyzer_factory: AnalyzerFactory | None = None,
) -> Starlette:
    """Create the editor's Starlette app.

    Args:
        config_path: Path to the settings YAML (loaded per request by run handlers).
        data_dir: Override the base data directory; defaults to ``Settings.data_dir``.
        analyzer_factory: Builds the analyzer from settings; defaults to the real
            Claude analyzer. Tests inject a placeholder.

    Returns:
        The configured Starlette application.
    """
    settings = load_settings(config_path)
    resolved_data_dir = (data_dir or settings.data_dir).resolve()

    routes = [
        Route("/", _index, methods=["GET"]),
        Mount("/static", StaticFiles(directory=_STATIC_DIR), name="static"),
        Route("/api/dates", api.list_dates, methods=["GET"]),
        Route("/api/extractions", api.get_extractions, methods=["GET"]),
        Route("/api/extractions", api.put_extractions, methods=["PUT"]),
        Route("/api/image", api.get_image, methods=["GET"]),
        Route("/api/report", api.get_report, methods=["GET"]),
        Route("/api/job", api.get_job, methods=["GET"]),
        Route("/api/collect", api.post_collect, methods=["POST"]),
        Route("/api/extract", api.post_extract, methods=["POST"]),
        Route("/api/synthesize", api.post_synthesize, methods=["POST"]),
        Route("/api/stream/{job_id}", api.stream, methods=["GET"]),
    ]

    app = Starlette(routes=routes)
    app.state.config_path = config_path
    app.state.data_dir = resolved_data_dir
    app.state.job_manager = JobManager()
    app.state.analyzer_factory = analyzer_factory or _default_analyzer_factory
    return app
