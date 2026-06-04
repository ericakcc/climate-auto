"""Tests for the traversal-safe image path resolver."""

from pathlib import Path

from climate_auto.web.paths import safe_image_path


def _make_report_image(data_dir: Path, date_str: str, rel: str) -> Path:
    """Create a fake chart image under data_dir/{date}/report/{rel}."""
    target = data_dir / date_str / "report" / rel
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(b"GIF89a fake")
    return target


def test_safe_image_path_returns_resolved_path_for_existing_file(tmp_path: Path) -> None:
    expected = _make_report_image(
        tmp_path, "2026-06-04", "1_review/sounding/skewt.gif"
    )

    result = safe_image_path(tmp_path, "2026-06-04", "1_review/sounding/skewt.gif")

    assert result == expected.resolve()


def test_safe_image_path_rejects_parent_traversal(tmp_path: Path) -> None:
    secret = tmp_path / "2026-06-04" / "secret.txt"
    secret.parent.mkdir(parents=True, exist_ok=True)
    secret.write_text("nope")

    result = safe_image_path(tmp_path, "2026-06-04", "../secret.txt")

    assert result is None


def test_safe_image_path_rejects_absolute_path(tmp_path: Path) -> None:
    result = safe_image_path(tmp_path, "2026-06-04", "/etc/passwd")

    assert result is None


def test_safe_image_path_returns_none_for_missing_file(tmp_path: Path) -> None:
    (tmp_path / "2026-06-04" / "report").mkdir(parents=True)

    result = safe_image_path(tmp_path, "2026-06-04", "missing.gif")

    assert result is None


def test_safe_image_path_rejects_malformed_date(tmp_path: Path) -> None:
    _make_report_image(tmp_path, "2026-06-04", "chart.gif")

    result = safe_image_path(tmp_path, "2026/06/04", "chart.gif")

    assert result is None
