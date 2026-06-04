"""Traversal-safe resolution of chart-image paths for the web editor."""

import re
from pathlib import Path

_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def safe_image_path(data_dir: Path, date_str: str, rel: str) -> Path | None:
    """Resolve a chart-image path, refusing anything outside the report dir.

    Args:
        data_dir: Base data directory (e.g. ``./data``).
        date_str: Report date, must match ``YYYY-MM-DD``.
        rel: Image path relative to ``data_dir/{date}/report``.

    Returns:
        The resolved absolute path if it is an existing file located inside
        ``data_dir/{date}/report``; otherwise ``None``.
    """
    if not _DATE_RE.match(date_str):
        return None

    base = (data_dir / date_str / "report").resolve()
    candidate = (base / rel).resolve()

    if not candidate.is_relative_to(base):
        return None
    if not candidate.is_file():
        return None
    return candidate
