"""Tests for the web editor read endpoints."""

from pathlib import Path

from climate_auto.report.generator import load_extractions, save_extractions

from .conftest import make_report_dir


def test_list_dates_returns_dirs_sorted_desc_with_flags(client, data_dir: Path) -> None:
    early = make_report_dir(data_dir, "2026-06-01")
    save_extractions(early, {"a.gif": "text"})
    make_report_dir(data_dir, "2026-06-03")
    (data_dir / "not-a-date").mkdir()

    resp = client.get("/api/dates")

    assert resp.status_code == 200
    dates = resp.json()["dates"]
    assert [d["date"] for d in dates] == ["2026-06-03", "2026-06-01"]
    first = next(d for d in dates if d["date"] == "2026-06-01")
    assert first["has_report_dir"] is True
    assert first["has_extractions"] is True


def test_get_extractions_builds_blocks_and_image_urls(client, data_dir: Path) -> None:
    report_dir = make_report_dir(data_dir, "2026-06-04")
    chart = report_dir / "1_review" / "sounding" / "skewt.gif"
    chart.parent.mkdir(parents=True)
    chart.write_bytes(b"GIF89a")
    save_extractions(
        report_dir,
        {
            "1_review/sounding/skewt.gif": "chart reading",
            "numeric/f24h_sounding": "SBCAPE 63 J/kg",
        },
    )

    resp = client.get("/api/extractions", params={"date": "2026-06-04"})

    assert resp.status_code == 200
    blocks = {b["key"]: b for b in resp.json()["blocks"]}
    chart_block = blocks["1_review/sounding/skewt.gif"]
    assert chart_block["exists"] is True
    assert chart_block["image_url"] is not None
    assert "skewt.gif" in chart_block["image_url"]
    numeric_block = blocks["numeric/f24h_sounding"]
    assert numeric_block["exists"] is False
    assert numeric_block["image_url"] is None


def test_get_extractions_missing_file_returns_empty_blocks(
    client, data_dir: Path
) -> None:
    make_report_dir(data_dir, "2026-06-04")

    resp = client.get("/api/extractions", params={"date": "2026-06-04"})

    assert resp.status_code == 200
    assert resp.json()["blocks"] == []


def test_get_extractions_missing_report_dir_returns_404(client) -> None:
    resp = client.get("/api/extractions", params={"date": "2026-06-04"})

    assert resp.status_code == 404


def test_save_then_load_extractions_round_trip(client, data_dir: Path) -> None:
    report_dir = make_report_dir(data_dir, "2026-06-04")
    payload = {
        "date": "2026-06-04",
        "blocks": [
            {"key": "a.gif", "text": "AAA", "exists": True},
            {"key": "b.gif", "text": "BBB", "exists": True},
        ],
    }

    resp = client.put("/api/extractions", json=payload)

    assert resp.status_code == 200
    assert resp.json()["count"] == 2
    loaded = load_extractions(report_dir)
    assert loaded == {"a.gif": "AAA", "b.gif": "BBB"}


def test_save_extractions_unknown_date_returns_404(client) -> None:
    payload = {
        "date": "2026-06-04",
        "blocks": [{"key": "a.gif", "text": "AAA", "exists": True}],
    }

    resp = client.put("/api/extractions", json=payload)

    assert resp.status_code == 404


def test_image_route_serves_gif_with_correct_mime(client, data_dir: Path) -> None:
    report_dir = make_report_dir(data_dir, "2026-06-04")
    (report_dir / "chart.gif").write_bytes(b"GIF89a")

    resp = client.get("/api/image", params={"date": "2026-06-04", "path": "chart.gif"})

    assert resp.status_code == 200
    assert resp.headers["content-type"] == "image/gif"


def test_image_route_rejects_path_traversal(client, data_dir: Path) -> None:
    make_report_dir(data_dir, "2026-06-04")
    (data_dir / "2026-06-04" / "secret.txt").write_text("nope")

    resp = client.get(
        "/api/image", params={"date": "2026-06-04", "path": "../secret.txt"}
    )

    assert resp.status_code == 404


def test_report_route_returns_markdown(client, data_dir: Path) -> None:
    report_dir = make_report_dir(data_dir, "2026-06-04")
    (report_dir / "daily_report.md").write_text("# Title\n\n![x](1_review/a.gif)")

    resp = client.get("/api/report", params={"date": "2026-06-04"})

    assert resp.status_code == 200
    body = resp.json()
    assert "# Title" in body["markdown"]
    assert "2026-06-04" in body["image_base"]


def test_report_route_missing_returns_404(client, data_dir: Path) -> None:
    make_report_dir(data_dir, "2026-06-04")

    resp = client.get("/api/report", params={"date": "2026-06-04"})

    assert resp.status_code == 404


def test_job_status_idle(client) -> None:
    resp = client.get("/api/job")

    assert resp.status_code == 200
    assert resp.json()["running"] is False
