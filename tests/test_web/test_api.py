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


def test_get_extractions_marks_provenance(client, data_dir: Path) -> None:
    report_dir = make_report_dir(data_dir, "2026-06-04")
    save_extractions(
        report_dir,
        {
            # numeric block re-keyed onto a chart path (computed, not vision)
            "1_review/analysis/ECMWF500_x_f000.gif": (
                "（數值計算，500hPa 高度場，2026-06-04 00Z）\n- 高壓中心：5915 gpm"
            ),
            # genuine vision reading of an image
            "1_review/surface/surface_taiwan.gif": "地面天氣圖顯示鋒面通過台灣北部。",
            # numeric-keyed forecast sounding
            "numeric/f24h 預報_預報探空": "（數值計算，來源 ECMWF-fc）\n- SBCAPE 63 J/kg",
            # CWA surface station observation
            "numeric/地面測站觀測": "（數值觀測，CWA 地面測站，2026-06-04）\n- 臺北 26°C",
        },
    )

    resp = client.get("/api/extractions", params={"date": "2026-06-04"})

    assert resp.status_code == 200
    prov = {b["key"]: b["provenance"] for b in resp.json()["blocks"]}
    assert prov["1_review/analysis/ECMWF500_x_f000.gif"] == "numeric"
    assert prov["1_review/surface/surface_taiwan.gif"] == "vision"
    assert prov["numeric/f24h 預報_預報探空"] == "numeric"
    assert prov["numeric/地面測站觀測"] == "observation"


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


def test_download_md_serves_as_attachment(client, data_dir: Path) -> None:
    report_dir = make_report_dir(data_dir, "2026-06-04")
    (report_dir / "daily_report.md").write_text("# Report")

    resp = client.get("/api/download", params={"date": "2026-06-04", "kind": "md"})

    assert resp.status_code == 200
    assert "attachment" in resp.headers["content-disposition"]
    assert "2026-06-04" in resp.headers["content-disposition"]


def test_download_docx_serves(client, data_dir: Path) -> None:
    report_dir = make_report_dir(data_dir, "2026-06-04")
    (report_dir / "daily_report.docx").write_bytes(b"PK\x03\x04 fake docx")

    resp = client.get("/api/download", params={"date": "2026-06-04", "kind": "docx"})

    assert resp.status_code == 200


def test_download_unknown_kind_returns_400(client, data_dir: Path) -> None:
    make_report_dir(data_dir, "2026-06-04")

    resp = client.get("/api/download", params={"date": "2026-06-04", "kind": "pdf"})

    assert resp.status_code == 400


def test_download_missing_file_returns_404(client, data_dir: Path) -> None:
    make_report_dir(data_dir, "2026-06-04")

    resp = client.get("/api/download", params={"date": "2026-06-04", "kind": "md"})

    assert resp.status_code == 404


def test_job_status_idle(client) -> None:
    resp = client.get("/api/job")

    assert resp.status_code == 200
    assert resp.json()["running"] is False


def test_index_serves_editor_page(client) -> None:
    resp = client.get("/")

    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]
    assert "Climate Auto" in resp.text
    assert 'id="app"' in resp.text


def test_static_editor_js_is_served(client) -> None:
    resp = client.get("/static/editor.js")

    assert resp.status_code == 200
