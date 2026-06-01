"""Tests for numeric-route wiring into the report generator (no network)."""

from pathlib import Path

from climate_auto.config import NumericalConfig
from climate_auto.report.generator import (
    _build_numeric_or_empty,
    _drop_replaced_charts,
    _numeric_key_for_chart,
    _remap_numeric_to_charts,
)
from climate_auto.report.models import ChartImage


def _charts() -> list[tuple[ChartImage, Path]]:
    names = [
        "1_review/analysis/ec_500_f000.gif",
        "1_review/analysis/ec_850mf_f000.gif",
        "1_review/sounding/taipei_skewt.gif",
        "2_f24h/ec_500_f024.gif",
        "1_review/precip/radar.gif",
    ]
    return [(ChartImage(relative_path=n, description=n), Path("/x") / n) for n in names]


def test_drop_replaced_charts_skips_matching_patterns() -> None:
    """Charts whose path matches a numeric-replacement pattern are removed."""
    kept = _drop_replaced_charts(_charts(), ["analysis/", "2_f24h/"])
    paths = [c.relative_path for c, _ in kept]

    # Analysis + f24h charts dropped (numeric replaces them); sounding/radar stay.
    assert "1_review/sounding/taipei_skewt.gif" in paths
    assert "1_review/precip/radar.gif" in paths
    assert all("analysis/" not in p and "2_f24h/" not in p for p in paths)
    assert len(kept) == 2


def test_drop_replaced_charts_no_patterns_keeps_all() -> None:
    """Empty pattern list is a no-op (safe default)."""
    charts = _charts()
    assert _drop_replaced_charts(charts, []) == charts


def test_build_numeric_or_empty_degrades_gracefully(monkeypatch) -> None:
    """A failure inside the numeric build degrades to an empty dict."""
    import climate_auto.report.numeric as numeric_mod

    def _boom(*_args, **_kwargs):
        raise RuntimeError("no network")

    # build_numeric_extractions itself swallows per-step errors, but guard the
    # whole call too: if the import-level helper raised, the report must survive.
    monkeypatch.setattr(numeric_mod, "build_numeric_extractions", _boom)

    cfg = NumericalConfig(enabled=True, steps=[0, 24])
    # _build_numeric_or_empty must swallow the error so the report still renders.
    result = _build_numeric_or_empty(__import__("datetime").date(2026, 6, 1), cfg)
    assert result == {}


def test_load_extractions_ignores_prose_headings_in_body(tmp_path) -> None:
    """A body containing its own '## heading' (no '/') is not split into a key."""
    from climate_auto.report.generator import (
        EXTRACTIONS_FILENAME,
        load_extractions,
        save_extractions,
    )

    original = {
        "1_review/surface/asia.gif": "前言\n\n## 地面天氣圖分析\n\n高壓 H1036。",
        "numeric/地面測站觀測": "板橋 27.5°C",
    }
    save_extractions(tmp_path, original)
    loaded = load_extractions(tmp_path)

    # Round-trips to the SAME two keys; the inner '## 地面天氣圖分析' stays in body.
    assert set(loaded) == set(original)
    assert "## 地面天氣圖分析" in loaded["1_review/surface/asia.gif"]
    assert (tmp_path / EXTRACTIONS_FILENAME).exists()


def test_numeric_key_for_chart_maps_var_and_step() -> None:
    """Chart filenames map to the right numeric block key (var + step)."""
    assert (
        _numeric_key_for_chart("1_review/analysis/ECMWF500_2026053112_f000.gif")
        == "numeric/分析場(f000)_500hPa高度場"
    )
    assert (
        _numeric_key_for_chart("2_f24h/ECMWF850mf_2026053112_f024.gif")
        == "numeric/f24h 預報_850hPa水氣通量"
    )
    assert (
        _numeric_key_for_chart("3_f48h/ECMWF700_2026053112_f048.gif")
        == "numeric/f48h 預報_700hPa相對濕度"
    )
    assert (
        _numeric_key_for_chart("2_f24h/dailyrn_2026053112_1.png")
        == "numeric/0-24h_累積雨量"
    )
    assert _numeric_key_for_chart("1_review/precip/radar.png") is None


def test_remap_numeric_attaches_to_replaced_chart_paths() -> None:
    """Matched numeric blocks move to chart-path keys; unmatched stay."""
    numeric = {
        "numeric/分析場(f000)_500hPa高度場": "HGT TEXT",
        "numeric/f24h 預報_預報探空": "SOUNDING TEXT",  # no chart → stays
        "numeric/地面測站觀測": "STATION TEXT",  # no chart → stays
    }
    replaced = {"1_review/analysis/ECMWF500_2026053112_f000.gif"}

    out = _remap_numeric_to_charts(numeric, replaced)

    # Height block re-keyed onto the chart's path (fills that section).
    assert out["1_review/analysis/ECMWF500_2026053112_f000.gif"] == "HGT TEXT"
    assert "numeric/分析場(f000)_500hPa高度場" not in out
    # Blocks without a chart keep their numeric/ key (synthesis only).
    assert out["numeric/f24h 預報_預報探空"] == "SOUNDING TEXT"
    assert out["numeric/地面測站觀測"] == "STATION TEXT"
