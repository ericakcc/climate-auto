"""Tests for the ECMWF forecast adapter (route 2, same-day half).

These validate the column-extraction and compute logic on a synthetic
pressure-level Dataset — no GRIB decoding, eccodes, or network required. Live
ECMWF open-data fetch + cfgrib decode must be verified in a real-dated
environment (open-data keeps only ~4 days of runs).
"""

from datetime import datetime

import pytest

from climate_auto.report.forecast import TAIPEI_LATLON


def _synthetic_pl_dataset():
    """Build a synthetic ECMWF-like pressure-level Dataset over a small grid.

    Specific humidity is derived from a target dewpoint via MetPy so that
    :func:`extract_sounding_column` should round-trip the dewpoint back.
    """
    np = pytest.importorskip("numpy")
    xr = pytest.importorskip("xarray")
    pytest.importorskip("metpy")
    import metpy.calc as mpcalc
    from metpy.units import units

    levels = np.array([1000, 925, 850, 700, 500, 300])
    temp_c = np.array([29.2, 25.4, 21.2, 10.0, -6.0, -34.0])
    dew_c = np.array([23.2, 20.7, 16.9, 4.0, -15.0, -50.0])

    pressure = levels * units.hPa
    q = mpcalc.specific_humidity_from_dewpoint(pressure, dew_c * units.degC).magnitude
    t_k = (temp_c * units.degC).to("kelvin").magnitude

    lats = np.array([24.5, 25.0, 25.5])
    lons = np.array([121.0, 121.5, 122.0])

    def grid(profile):
        return np.broadcast_to(
            profile[:, None, None], (len(levels), lats.size, lons.size)
        ).copy()

    # Geopotential height: standard per-level base + a NE-corner bump that mimics
    # a subtropical high (peak ~5930 gpm at 500 hPa over 25.5N,122E).
    base_gh = {1000: 100, 925: 760, 850: 1500, 700: 3150, 500: 5850, 300: 9650}
    gh_base = np.array([base_gh[int(lev)] for lev in levels])
    bump = 40.0 * (lats[:, None] - 24.5) + 40.0 * (lons[None, :] - 121.0)
    gh = gh_base[:, None, None] + bump[None, :, :]

    dims = ["isobaricInhPa", "latitude", "longitude"]
    return (
        xr.Dataset(
            {
                "t": (dims, grid(t_k)),
                "q": (dims, grid(q)),
                "u": (dims, grid(np.full(levels.size, 5.0))),
                "v": (dims, grid(np.full(levels.size, 5.0))),
                "gh": (dims, gh),
            },
            coords={"isobaricInhPa": levels, "latitude": lats, "longitude": lons},
        ),
        dew_c,
        levels,
    )


def test_extract_sounding_column_roundtrips_dewpoint() -> None:
    """A column pulled at Taipei recovers the dewpoint used to build q."""
    pytest.importorskip("metpy")
    from climate_auto.report.forecast import extract_sounding_column

    ds, dew_c, levels = _synthetic_pl_dataset()
    df = extract_sounding_column(ds, *TAIPEI_LATLON)

    assert list(df.columns) == [
        "pressure",
        "temperature",
        "dewpoint",
        "u_wind",
        "v_wind",
    ]
    # Sorted by decreasing pressure, all levels present.
    assert df["pressure"].is_monotonic_decreasing
    assert len(df) == len(levels)
    # Dewpoint round-trips within ~1 degC (q derived from these dewpoints).
    assert df["dewpoint"].to_numpy() == pytest.approx(dew_c, abs=1.0)
    # Wind: 5 m/s components → ~9.7 kt each.
    assert df["u_wind"].iloc[0] == pytest.approx(9.7, abs=0.3)


def test_forecast_sounding_indices_tagged_and_computed() -> None:
    """Forecast column flows through the shared MetPy pipeline."""
    pytest.importorskip("metpy")
    from climate_auto.report.forecast import forecast_sounding_indices

    ds, _dew_c, levels = _synthetic_pl_dataset()
    result = forecast_sounding_indices(ds, datetime(2026, 6, 1, 0))

    assert result.source == "ECMWF-fc"
    assert "121.5E" in result.label
    assert result.n_levels == len(levels)
    # K-index is a simple level formula → must compute on this moist profile.
    assert result.k_index is not None
    assert result.pw_mm is not None and result.pw_mm > 0


def test_moisture_flux_850_is_positive_grid() -> None:
    """850 hPa moisture flux magnitude is a positive 2-D field with units."""
    np = pytest.importorskip("numpy")
    pytest.importorskip("metpy")
    from climate_auto.report.forecast import moisture_flux_850

    ds, _dew_c, _levels = _synthetic_pl_dataset()
    flux = moisture_flux_850(ds)

    assert flux.dims == ("latitude", "longitude")
    assert flux.attrs["units"] == "g kg-1 m s-1"
    assert bool(np.all(flux.values > 0))


def test_height_field_features_finds_high_and_contours() -> None:
    """500 hPa feature extraction locates the high and 5880/5910 ridge extents."""
    pytest.importorskip("numpy")
    from climate_auto.report.forecast import height_field_features

    ds, _dew_c, _levels = _synthetic_pl_dataset()
    feat = height_field_features(ds, datetime(2026, 6, 1, 0), level=500)

    assert feat.level_hpa == 500
    # High centre is the NE corner (25.5N, 122E), ~5930 gpm.
    assert feat.high_center_gpm == pytest.approx(5930, abs=2)
    assert feat.high_center_lat == pytest.approx(25.5, abs=0.01)
    assert feat.high_center_lon == pytest.approx(122.0, abs=0.01)
    assert feat.ridge_lat_near_point is not None

    by_gpm = {c.gpm: c for c in feat.contours}
    assert by_gpm[5880].present is True
    assert by_gpm[5910].present is True
    # Taipei point (~5890) is above 5880 but below 5910.
    assert by_gpm[5880].covers_point is True
    assert by_gpm[5910].covers_point is False


def test_level_relative_humidity_700() -> None:
    """700 hPa RH (mean & point) is a plausible percentage for the moist profile."""
    pytest.importorskip("metpy")
    from climate_auto.report.forecast import level_relative_humidity

    ds, _dew_c, _levels = _synthetic_pl_dataset()
    mean_rh, point_rh = level_relative_humidity(ds, 700, TAIPEI_LATLON)

    # 700 hPa profile is T=10C, Td=4C → RH roughly 60–75%.
    assert 40.0 < mean_rh < 100.0
    assert 40.0 < point_rh < 100.0


def _synthetic_surface_tp(total_m: float):
    """Build a synthetic surface Dataset with accumulated tp (metres)."""
    np = pytest.importorskip("numpy")
    xr = pytest.importorskip("xarray")
    lats = np.array([21.0, 23.0, 25.0, 25.5])
    lons = np.array([119.0, 120.0, 121.5, 122.0])
    vals = np.full((lats.size, lons.size), total_m)
    vals[1, 1] = total_m * 2  # a hot-spot at 23N, 120E
    return xr.Dataset(
        {"tp": (["latitude", "longitude"], vals)},
        coords={"latitude": lats, "longitude": lons},
    )


def test_daily_precip_mm_differences_accumulated_tp() -> None:
    """Daily rainfall is the tp difference × 1000 (m → mm), with a hot-spot."""
    np = pytest.importorskip("numpy")
    from climate_auto.report.forecast import daily_precip_mm

    da = daily_precip_mm(_synthetic_surface_tp(0.05), _synthetic_surface_tp(0.0))

    assert da.attrs["units"] == "mm"
    assert float(np.nanmax(da.values)) == pytest.approx(100.0, abs=0.1)  # hot-spot
    assert float(da.values[0, 0]) == pytest.approx(50.0, abs=0.1)  # baseline


def test_format_precip_reports_hotspot_and_point() -> None:
    """Precip formatter reports the Taiwan-domain max and the reference point."""
    pytest.importorskip("numpy")
    from climate_auto.report.forecast import daily_precip_mm
    from climate_auto.report.numeric import format_precip

    da = daily_precip_mm(_synthetic_surface_tp(0.05), _synthetic_surface_tp(0.0))
    txt = format_precip(da, datetime(2026, 6, 1, 0), (25.0, 121.5))

    assert "累積雨量" in txt
    assert "100.0 mm" in txt  # hot-spot max
    assert "50.0 mm" in txt  # reference-point total


def test_format_blocks_are_chinese_text() -> None:
    """Formatters produce non-empty Traditional-Chinese summaries."""
    pytest.importorskip("metpy")
    from climate_auto.report.forecast import (
        forecast_sounding_indices,
        height_field_features,
        moisture_flux_850,
    )
    from climate_auto.report.numeric import (
        format_height_features,
        format_moisture_flux,
        format_sounding_indices,
    )

    ds, _dew_c, _levels = _synthetic_pl_dataset()
    when = datetime(2026, 6, 1, 0)

    h = format_height_features(height_field_features(ds, when))
    s = format_sounding_indices(forecast_sounding_indices(ds, when))
    m = format_moisture_flux(moisture_flux_850(ds), when)

    assert "高度場" in h and "gpm" in h
    assert "ECMWF-fc" in s and "CAPE" in s
    assert "水氣通量" in m
