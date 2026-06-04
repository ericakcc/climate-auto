"""Assemble numeric weather extractions from ECMWF open-data forecast fields.

This is the "last mile" that plugs route (2) into the report pipeline. Instead
of the vision model reading the 500/700/850 hPa height-field and 850 hPa
water-vapour GIFs, :func:`build_numeric_extractions` fetches ECMWF open-data,
computes the same quantities numerically, and returns text blocks keyed for the
synthesis ``extractions`` dict — so they flow into the unified diagnosis and are
human-editable in ``extractions.md`` just like image extractions.

Charts with no free numeric source (radar, satellite, MJO, *today's observed*
sounding) are untouched and still read from images.

The formatters (``format_*``) are pure and unit-tested offline; only
:func:`build_numeric_extractions` does network I/O, and it degrades to ``{}`` on
any failure (missing extra, no connectivity, ECMWF archive gap).
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import TYPE_CHECKING

from loguru import logger

from climate_auto.report.sounding import SoundingIndices

if TYPE_CHECKING:  # pragma: no cover - typing only
    import xarray as xr

    from climate_auto.report.forecast import HeightFieldFeatures


def format_sounding_indices(idx: SoundingIndices) -> str:
    """Format forecast/observed sounding indices as a Traditional-Chinese block.

    Args:
        idx: Computed sounding indices.

    Returns:
        Multi-line text summary.
    """

    def _n(value: float | None, unit: str = "") -> str:
        return "n/a" if value is None else f"{value:.1f}{unit}"

    return (
        f"（數值計算，來源 {idx.source}，{idx.label}，{idx.valid_time:%Y-%m-%d %HZ}）\n"
        f"- 不穩定度：SBCAPE {_n(idx.sbcape, ' J/kg')}、CIN {_n(idx.sbcin, ' J/kg')}、"
        f"MUCAPE {_n(idx.mucape, ' J/kg')}\n"
        f"- 穩定度指數：LI {_n(idx.lifted_index)}、K {_n(idx.k_index)}、"
        f"SI {_n(idx.showalter_index)}、TT {_n(idx.total_totals)}\n"
        f"- 關鍵層：LCL {_n(idx.lcl_hpa, ' hPa')}、LFC {_n(idx.lfc_hpa, ' hPa')}、"
        f"EL {_n(idx.el_hpa, ' hPa')}\n"
        f"- 可降水量 PW {_n(idx.pw_mm, ' mm')}（{idx.n_levels} 層）"
    )


def format_height_features(feat: "HeightFieldFeatures") -> str:
    """Format 500 hPa height-field features as a Traditional-Chinese block.

    Args:
        feat: Extracted height-field features.

    Returns:
        Multi-line text summary.
    """
    lines = [
        f"（數值計算，{feat.level_hpa}hPa 高度場，{feat.valid_time:%Y-%m-%d %HZ}）",
    ]
    if feat.high_center_gpm is not None:
        lines.append(
            f"- 高壓中心：{feat.high_center_gpm:.0f} gpm，位於 "
            f"{feat.high_center_lat:.1f}N, {feat.high_center_lon:.1f}E"
        )
    if feat.ridge_lat_near_point is not None:
        lines.append(f"- 台灣經度附近脊線緯度：約 {feat.ridge_lat_near_point:.1f}N")
    for c in feat.contours:
        if not c.present:
            lines.append(f"- {c.gpm} 線：不在分析範圍內")
            continue
        cover = "涵蓋台灣" if c.covers_point else "未涵蓋台灣"
        lines.append(
            f"- {c.gpm} 線：最西伸至 {c.west_lon:.1f}E，緯度範圍 "
            f"{c.lat_min:.1f}–{c.lat_max:.1f}N，{cover}"
        )
    return "\n".join(lines)


def format_moisture_flux(da: "xr.DataArray", valid_time: datetime) -> str:
    """Format an 850 hPa moisture-flux field as a Traditional-Chinese block.

    Args:
        da: Moisture-flux magnitude field (lat/lon grid).
        valid_time: Field valid time.

    Returns:
        Multi-line text summary (domain mean/max and where the max sits).
    """
    import numpy as np

    vals = da.values
    lats = da["latitude"].values
    lons = da["longitude"].values
    i, j = np.unravel_index(np.nanargmax(vals), vals.shape)
    return (
        f"（數值計算，850hPa 水氣通量 q×風速，{valid_time:%Y-%m-%d %HZ}）\n"
        f"- 區域平均 {np.nanmean(vals):.1f}、最大 {np.nanmax(vals):.1f} "
        f"{da.attrs.get('units', '')}\n"
        f"- 最大值位於 {float(lats[i]):.1f}N, {float(lons[j]):.1f}E"
    )


# Taiwan box for precipitation hot-spot summaries (lat_min, lat_max, lon_min, lon_max).
TAIWAN_DOMAIN: tuple[float, float, float, float] = (21.0, 26.0, 119.0, 122.5)


def format_precip(
    da: "xr.DataArray",
    valid_time: datetime,
    point: tuple[float, float],
    domain: tuple[float, float, float, float] = TAIWAN_DOMAIN,
) -> str:
    """Format an accumulated-precipitation field as a Traditional-Chinese block.

    Args:
        da: Window precipitation field (mm) on the lat/lon grid.
        valid_time: End of the accumulation window.
        point: Reference point (lat, lon) — e.g. Taipei.
        domain: Box to summarise the hot-spot over (default Taiwan).

    Returns:
        Multi-line text summary (area max + where it sits + reference-point total).
    """
    import numpy as np

    lats = da["latitude"].values
    lons = da["longitude"].values
    lat_min, lat_max, lon_min, lon_max = domain
    lat_sel = (lats >= lat_min) & (lats <= lat_max)
    lon_sel = (lons >= lon_min) & (lons <= lon_max)
    if not lat_sel.any() or not lon_sel.any():
        return f"（數值計算，累積雨量，至 {valid_time:%Y-%m-%d %HZ}）\n- 分析範圍外，無資料"

    sub = da.values[np.ix_(lat_sel, lon_sel)]
    lats_d = lats[lat_sel]
    lons_d = lons[lon_sel]
    i, j = np.unravel_index(np.nanargmax(sub), sub.shape)
    ip = int(np.argmin(np.abs(lats - point[0])))
    jp = int(np.argmin(np.abs(lons - point[1])))
    return (
        f"（數值計算，台灣區域累積雨量，至 {valid_time:%Y-%m-%d %HZ}）\n"
        f"- 區域最大 {float(sub[i, j]):.1f} mm，位於 "
        f"{float(lats_d[i]):.1f}N, {float(lons_d[j]):.1f}E\n"
        f"- 參考點 ({point[0]:g}N,{point[1]:g}E) 累積 "
        f"{float(da.values[ip, jp]):.1f} mm"
    )


def format_level_humidity(
    level: int, mean_rh: float, point_rh: float, valid_time: datetime
) -> str:
    """Format a pressure-level relative-humidity summary block."""
    dry_wet = "偏乾" if mean_rh < 50 else ("偏濕" if mean_rh > 70 else "中性")
    return (
        f"（數值計算，{level}hPa 相對濕度，{valid_time:%Y-%m-%d %HZ}）\n"
        f"- 區域平均 RH {mean_rh:.0f}%（{dry_wet}）、台灣點 RH {point_rh:.0f}%"
    )


def _valid_time(target_date: date, run_time: int, step: int) -> datetime:
    """Compute the valid time for a run date/hour and forecast step."""
    base = datetime(
        target_date.year,
        target_date.month,
        target_date.day,
        run_time,
        tzinfo=timezone.utc,
    )
    return base + timedelta(hours=step)


def _step_label(step: int) -> str:
    """Human label for a forecast step (analysis vs f24/f48)."""
    return "分析場(f000)" if step == 0 else f"f{step:02d}h 預報"


def build_numeric_extractions(
    target_date: date,
    *,
    run_time: int = 0,
    steps: tuple[int, ...] = (0, 24, 48),
    point: tuple[float, float] | None = None,
    domain: tuple[float, float, float, float] | None = None,
    cwa_api_key: str | None = None,
    surface_stations: list[str] | None = None,
) -> dict[str, str]:
    """Fetch ECMWF open-data and build numeric extraction text blocks.

    Network I/O. Degrades gracefully: any failure (missing ``numerical`` extra,
    no connectivity, ECMWF archive gap for ``target_date``) logs a warning and
    yields ``{}`` so the report still renders from image extractions.

    Args:
        target_date: Report date; used as the ECMWF run date.
        run_time: Run hour (0/6/12/18).
        steps: Forecast steps to include (0 = analysis, then forecasts).
        point: Sounding point (lat, lon); defaults to Taipei.
        domain: Height-field analysis domain; defaults to East Asia.

    Returns:
        Mapping of ``numeric/<label>`` keys to formatted text blocks.
    """
    try:
        from climate_auto.report.forecast import (
            TAIPEI_LATLON,
            daily_precip_mm,
            fetch_ecmwf_pressure_levels,
            fetch_ecmwf_surface,
            forecast_sounding_indices,
            height_field_features,
            level_relative_humidity,
            moisture_flux_850,
            open_grib,
            open_pressure_levels,
        )
    except ImportError as exc:
        logger.warning("Numeric route unavailable (install 'numerical' extra): {}", exc)
        return {}

    pt = point or TAIPEI_LATLON
    extractions: dict[str, str] = {}

    with TemporaryDirectory() as tmp:
        logger.info(
            "Numeric route: downloading ECMWF pressure levels for steps {} "
            "(each download can take ~30s, no per-byte progress)",
            list(steps),
        )
        for step in steps:
            valid = _valid_time(target_date, run_time, step)
            label = _step_label(step)
            logger.info("Downloading ECMWF pressure levels: step {} ({})", step, label)
            try:
                grib = fetch_ecmwf_pressure_levels(
                    Path(tmp) / f"ec_{step}.grib2",
                    date=target_date.isoformat(),
                    time=run_time,
                    step=step,
                )
                ds = open_pressure_levels(grib)
            except Exception as exc:  # noqa: BLE001 - network/decoding/archive errors
                logger.warning("ECMWF fetch failed for step {}: {}", step, exc)
                continue
            logger.info("Computing numeric fields: step {} ({})", step, label)

            try:
                feat = height_field_features(
                    ds, valid, domain=domain or _default_domain()
                )
                extractions[f"numeric/{label}_500hPa高度場"] = format_height_features(
                    feat
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Height-field features failed (step {}): {}", step, exc)

            try:
                flux = moisture_flux_850(ds)
                extractions[f"numeric/{label}_850hPa水氣通量"] = format_moisture_flux(
                    flux, valid
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("Moisture flux failed (step {}): {}", step, exc)

            try:
                mean_rh, point_rh = level_relative_humidity(ds, 700, pt)
                extractions[f"numeric/{label}_700hPa相對濕度"] = format_level_humidity(
                    700, mean_rh, point_rh, valid
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("700hPa humidity failed (step {}): {}", step, exc)

            # Forecast soundings are meaningful for forecast steps (report 2-II/3-III).
            if step > 0:
                try:
                    idx = forecast_sounding_indices(ds, valid, lat=pt[0], lon=pt[1])
                    extractions[f"numeric/{label}_預報探空"] = format_sounding_indices(
                        idx
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning("Forecast sounding failed (step {}): {}", step, exc)

        # --- Daily precipitation (ECMWF tp), report 2-III / 3-IV ---
        logger.info("Numeric route: downloading ECMWF precipitation (tp)")
        tp_by_step: dict[int, object] = {}
        for step in steps:
            logger.info("Downloading ECMWF tp: step {}", step)
            try:
                grib = fetch_ecmwf_surface(
                    Path(tmp) / f"tp_{step}.grib2",
                    date=target_date.isoformat(),
                    time=run_time,
                    step=step,
                )
                tp_by_step[step] = open_grib(grib)
            except Exception as exc:  # noqa: BLE001
                logger.warning("ECMWF tp fetch failed for step {}: {}", step, exc)

        avail = sorted(tp_by_step)
        for start_step, end_step in zip(avail, avail[1:], strict=False):
            try:
                precip = daily_precip_mm(tp_by_step[end_step], tp_by_step[start_step])
                valid = _valid_time(target_date, run_time, end_step)
                key = f"numeric/{start_step}-{end_step}h_累積雨量"
                extractions[key] = format_precip(precip, valid, pt)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "Daily precip failed ({}-{}h): {}", start_step, end_step, exc
                )

    # --- Observed surface stations (CWA OpenData), report 1-IV ---
    if cwa_api_key and surface_stations:
        logger.info("Fetching CWA surface station observations: {}", surface_stations)
        try:
            from climate_auto.report.cwa import fetch_cwa_surface, format_station_obs

            obs = fetch_cwa_surface(cwa_api_key, surface_stations)
            if obs:
                extractions["numeric/地面測站觀測"] = format_station_obs(obs)
        except Exception as exc:  # noqa: BLE001 - network/key errors must not break report
            logger.warning("CWA surface obs failed: {}", exc)

    logger.info("Numeric extractions built: {} blocks", len(extractions))
    return extractions


def _default_domain() -> tuple[float, float, float, float]:
    """East-Asia domain default (kept here to avoid importing on degrade path)."""
    from climate_auto.report.forecast import EAST_ASIA_DOMAIN

    return EAST_ASIA_DOMAIN
