"""File storage management for downloaded weather data."""

import json
from datetime import date
from pathlib import Path

from loguru import logger

from climate_auto.models import CollectionManifest, SourceName


def get_date_dir(base_dir: Path, target_date: date) -> Path:
    """Get the data directory for a specific date.

    Args:
        base_dir: Base data directory.
        target_date: Target date.

    Returns:
        Path to the date-specific directory.
    """
    return base_dir / target_date.strftime("%Y-%m-%d")


def ensure_source_dir(base_dir: Path, target_date: date, source: SourceName) -> Path:
    """Create and return the directory for a specific source and date.

    Args:
        base_dir: Base data directory.
        target_date: Target date.
        source: Data source name.

    Returns:
        Path to the source-specific directory.
    """
    source_dir = get_date_dir(base_dir, target_date) / source.value
    source_dir.mkdir(parents=True, exist_ok=True)
    return source_dir


def save_manifest(
    base_dir: Path, target_date: date, manifest: CollectionManifest
) -> Path:
    """Save the collection manifest to disk.

    Args:
        base_dir: Base data directory.
        target_date: Target date.
        manifest: Collection manifest to save.

    Returns:
        Path to the saved manifest file.
    """
    manifest_path = get_date_dir(base_dir, target_date) / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.write_text(
        json.dumps(manifest.model_dump(mode="json"), ensure_ascii=False, indent=2)
    )
    logger.info("Manifest saved to {}", manifest_path)
    return manifest_path


def load_manifest(base_dir: Path, target_date: date) -> CollectionManifest | None:
    """Load an existing manifest if available.

    Args:
        base_dir: Base data directory.
        target_date: Target date.

    Returns:
        Loaded manifest or None if not found.
    """
    manifest_path = get_date_dir(base_dir, target_date) / "manifest.json"
    if manifest_path.exists():
        raw = json.loads(manifest_path.read_text())
        return CollectionManifest(**raw)
    return None
