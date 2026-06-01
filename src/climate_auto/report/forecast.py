"""ECMWF open-data forecast adapter: numeric pressure-level fields & soundings.

Route (2), the same-day / same-week half (see ``docs/chart-recognition-research.md``).
Pulls ECMWF open-data forecast GRIB (issued 00/06/12/18Z, free, no key) and turns
it into numbers, instead of reading the 500/700/850 hPa height-field and
850 hPa water-vapour GIFs by eye:

  - :func:`extract_sounding_column` pulls a vertical column at a point and feeds
    it to the **same** MetPy pipeline as observed soundings
    (:func:`climate_auto.report.sounding.compute_indices`), giving forecast
    CAPE/CIN/PW for report sections 2-II / 3-III.
  - :func:`moisture_flux_850` computes 850 hPa water-vapour flux magnitude
    (q × wind) on the grid — the numeric basis for "水氣通量" instead of a
    filled-contour GIF.

Data-source notes:
  - ECMWF open-data keeps only the most recent ~4 days of runs (rolling, no deep
    archive). Fetches must target a recent real date.
  - GRIB decoding needs eccodes; we pin ``eccodes<2.41`` so its binary is loaded
    from ``ecmwflibs`` automatically (no DYLD_LIBRARY_PATH needed). Importing
    ``ecmwflibs`` before ``cfgrib`` is belt-and-braces for that.

All heavy deps (ecmwf-opendata, cfgrib, xarray, metpy) are imported lazily so the
package imports without the optional ``numerical`` extra.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING

from loguru import logger
from pydantic import BaseModel

from climate_auto.report.sounding import SoundingIndices, compute_indices

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd
    import xarray as xr

# East-Asia domain (lat_min, lat_max, lon_min, lon_max) for height-field analysis.
EAST_ASIA_DOMAIN: tuple[float, float, float, float] = (0.0, 50.0, 100.0, 160.0)

# Pressure levels (hPa) ECMWF open-data publishes that matter for soundings.
DEFAULT_LEVELS: list[int] = [
    1000,
    925,
    850,
    700,
    600,
    500,
    400,
    300,
    250,
    200,
    150,
    100,
]
# t=temperature(K), q=specific humidity(kg/kg), u/v=wind(m/s), gh=geopotential height(m).
DEFAULT_PARAMS: list[str] = ["t", "q", "u", "v", "gh"]

# Taipei/Banqiao sounding point (lat, lon) for forecast soundings.
TAIPEI_LATLON: tuple[float, float] = (25.0, 121.5)


def fetch_ecmwf_pressure_levels(
    target: Path,
    *,
    date: int | str = -1,
    time: int = 0,
    step: int = 0,
    levels: list[int] | None = None,
    params: list[str] | None = None,
) -> Path:
    """Download ECMWF open-data pressure-level forecast GRIB.

    Args:
        target: Output GRIB file path.
        date: Run date; ``-1`` = latest available run (ecmwf-opendata convention).
        time: Run hour (0/6/12/18).
        step: Forecast lead time in hours (e.g. 0, 24, 48).
        levels: Pressure levels in hPa (defaults to :data:`DEFAULT_LEVELS`).
        params: GRIB short names (defaults to :data:`DEFAULT_PARAMS`).

    Returns:
        Path to the downloaded GRIB file.
    """
    import ecmwflibs  # noqa: F401  ensures eccodes binary is locatable

    from ecmwf.opendata import Client

    client = Client(source="ecmwf")
    request = {
        "type": "fc",
        "date": date,
        "time": time,
        "step": step,
        "levtype": "pl",
        "levelist": levels or DEFAULT_LEVELS,
        "param": params or DEFAULT_PARAMS,
        "target": str(target),
    }
    logger.info(
        "ECMWF open-data retrieve: {}",
        {k: request[k] for k in ("date", "time", "step")},
    )
    client.retrieve(**request)
    return Path(target)


def open_grib(path: Path) -> "xr.Dataset":
    """Open any GRIB file as an xarray Dataset via cfgrib.

    Args:
        path: GRIB file path.

    Returns:
        Decoded Dataset (no ``.idx`` sidecar written).
    """
    import ecmwflibs  # noqa: F401

    import xarray as xr

    return xr.open_dataset(
        path,
        engine="cfgrib",
        backend_kwargs={"indexpath": ""},  # don't write .idx sidecar files
    )


def open_pressure_levels(path: Path) -> "xr.Dataset":
    """Open a pressure-level GRIB (t/q/u/v/gh on ``isobaricInhPa``)."""
    return open_grib(path)


def fetch_ecmwf_surface(
    target: Path,
    *,
    date: int | str = -1,
    time: int = 0,
    step: int = 0,
    params: list[str] | None = None,
) -> Path:
    """Download ECMWF open-data single-level (surface) forecast GRIB.

    Used for accumulated total precipitation (``tp``) to derive daily rainfall.

    Args:
        target: Output GRIB file path.
        date: Run date; ``-1`` = latest available run.
        time: Run hour (0/6/12/18).
        step: Forecast lead time in hours.
        params: GRIB short names (defaults to ``["tp"]``).

    Returns:
        Path to the downloaded GRIB file.
    """
    import ecmwflibs  # noqa: F401

    from ecmwf.opendata import Client

    client = Client(source="ecmwf")
    client.retrieve(
        type="fc",
        date=date,
        time=time,
        step=step,
        param=params or ["tp"],
        target=str(target),
    )
    return Path(target)


def daily_precip_mm(end_ds: "xr.Dataset", start_ds: "xr.Dataset") -> "xr.DataArray":
    """Compute accumulated precipitation between two forecast steps, in mm.

    ECMWF ``tp`` is accumulated from forecast start (metres of water), so the
    rainfall over a window is the difference of the two steps' ``tp`` × 1000.

    Args:
        end_ds: Surface Dataset at the later step (with ``tp``).
        start_ds: Surface Dataset at the earlier step (with ``tp``).

    Returns:
        2-D DataArray of window precipitation (mm) on the lat/lon grid.
    """
    precip = (end_ds["tp"] - start_ds["tp"]) * 1000.0
    precip.name = "daily_precip_mm"
    precip.attrs["units"] = "mm"
    return precip


def extract_sounding_column(
    ds: "xr.Dataset",
    lat: float,
    lon: float,
) -> "pd.DataFrame":
    """Extract a vertical sounding column at a point from a pressure-level Dataset.

    Converts ECMWF units to the sounding convention expected by
    :func:`compute_indices` (hPa / degC / knots) and derives dewpoint from
    specific humidity.

    Args:
        ds: Pressure-level Dataset (vars ``t`` [K], ``q`` [kg/kg], ``u``/``v``
            [m/s]; coord ``isobaricInhPa`` [hPa]).
        lat: Target latitude (degrees north).
        lon: Target longitude (degrees east).

    Returns:
        DataFrame with ``pressure``/``temperature``/``dewpoint``/``u_wind``/
        ``v_wind`` columns, sorted by decreasing pressure.
    """
    import metpy.calc as mpcalc
    import pandas as pd
    from metpy.units import units

    col = ds.sel(latitude=lat, longitude=lon, method="nearest")

    pressure = col["isobaricInhPa"].values * units.hPa
    temperature = (col["t"].values * units.kelvin).to("degC")
    spec_humidity = col["q"].values * units("kg/kg")
    # MetPy 1.7+ uses the 2-arg form (pressure, specific_humidity); the older
    # 3-arg form with temperature is deprecated.
    dewpoint = mpcalc.dewpoint_from_specific_humidity(pressure, spec_humidity).to(
        "degC"
    )

    frame = pd.DataFrame(
        {
            "pressure": pressure.m,
            "temperature": temperature.m,
            "dewpoint": dewpoint.m,
            "u_wind": (col["u"].values * units("m/s")).to("knot").m,
            "v_wind": (col["v"].values * units("m/s")).to("knot").m,
        }
    )
    return frame.sort_values("pressure", ascending=False).reset_index(drop=True)


def forecast_sounding_indices(
    ds: "xr.Dataset",
    valid_time: datetime,
    *,
    lat: float = TAIPEI_LATLON[0],
    lon: float = TAIPEI_LATLON[1],
    label: str | None = None,
) -> SoundingIndices:
    """Compute forecast-sounding indices from a forecast column (report 2-II/3-III).

    Args:
        ds: Pressure-level forecast Dataset.
        valid_time: The forecast valid time this column represents.
        lat: Sounding point latitude (default Taipei).
        lon: Sounding point longitude (default Taipei).
        label: Optional override label; defaults to the lat/lon point.

    Returns:
        Populated :class:`SoundingIndices` tagged ``source="ECMWF-fc"``.
    """
    df = extract_sounding_column(ds, lat, lon)
    return compute_indices(
        df,
        source="ECMWF-fc",
        label=label or f"{lat:g}N,{lon:g}E",
        valid_time=valid_time,
    )


class ContourExtent(BaseModel):
    """Extent of a single geopotential-height contour within the domain."""

    gpm: int
    present: bool
    west_lon: float | None = None
    lat_min: float | None = None
    lat_max: float | None = None
    covers_point: bool = False


class HeightFieldFeatures(BaseModel):
    """Synoptic features extracted numerically from a height field.

    Replaces visual reading of a 500 hPa height-field GIF (report 1-I/2-I/3-I):
    the subtropical-high centre, key contour extents (5880/5910 gpm ridge), and
    the ridge-axis latitude near a reference point.
    """

    level_hpa: int
    valid_time: datetime
    high_center_lat: float | None = None
    high_center_lon: float | None = None
    high_center_gpm: float | None = None
    ridge_lat_near_point: float | None = None
    contours: list[ContourExtent] = []


def height_field_features(
    ds: "xr.Dataset",
    valid_time: datetime,
    *,
    level: int = 500,
    domain: tuple[float, float, float, float] = EAST_ASIA_DOMAIN,
    point: tuple[float, float] = TAIPEI_LATLON,
    thresholds: tuple[int, ...] = (5880, 5910),
    ridge_band: tuple[float, float] = (15.0, 40.0),
) -> HeightFieldFeatures:
    """Extract synoptic height-field features numerically (report 1-I/2-I/3-I).

    Args:
        ds: Pressure-level Dataset containing ``gh`` (geopotential height, gpm).
        valid_time: Forecast/analysis valid time this field represents.
        level: Pressure level in hPa (default 500).
        domain: (lat_min, lat_max, lon_min, lon_max) to restrict analysis.
        point: Reference point (lat, lon) — e.g. Taiwan — for ridge/coverage.
        thresholds: Geopotential-height contours (gpm) to report extents for.

    Returns:
        Populated :class:`HeightFieldFeatures`.
    """
    import numpy as np

    gh = ds["gh"]
    if "isobaricInhPa" in gh.dims:
        gh = gh.sel(isobaricInhPa=level)
    lats = gh["latitude"].values
    lons = gh["longitude"].values
    lat_min, lat_max, lon_min, lon_max = domain

    lat_sel = (lats >= lat_min) & (lats <= lat_max)
    lon_sel = (lons >= lon_min) & (lons <= lon_max)
    lats_d = lats[lat_sel]
    lons_d = lons[lon_sel]
    vals = gh.values[np.ix_(lat_sel, lon_sel)]

    feats = HeightFieldFeatures(level_hpa=level, valid_time=valid_time)
    if vals.size == 0 or np.all(np.isnan(vals)):
        return feats

    # Subtropical-high centre: domain maximum of gh.
    i, j = np.unravel_index(np.nanargmax(vals), vals.shape)
    feats.high_center_lat = float(lats_d[i])
    feats.high_center_lon = float(lons_d[j])
    feats.high_center_gpm = float(vals[i, j])

    # Ridge-axis latitude at the longitude nearest the reference point. Restrict
    # to the subtropical band so we find the subtropical-high ridge, not the
    # equatorward edge where 500 hPa heights are also high.
    jp = int(np.argmin(np.abs(lons_d - point[1])))
    band = (lats_d >= ridge_band[0]) & (lats_d <= ridge_band[1])
    col = np.where(band, vals[:, jp], np.nan)
    if not np.all(np.isnan(col)):
        feats.ridge_lat_near_point = float(lats_d[int(np.nanargmax(col))])

    # gh at the reference point (nearest grid cell) for coverage checks.
    ip = int(np.argmin(np.abs(lats_d - point[0])))
    gh_at_point = float(vals[ip, jp])

    lat_grid, lon_grid = np.meshgrid(lats_d, lons_d, indexing="ij")
    for thr in thresholds:
        mask = vals >= thr
        if not mask.any():
            feats.contours.append(ContourExtent(gpm=thr, present=False))
            continue
        feats.contours.append(
            ContourExtent(
                gpm=thr,
                present=True,
                west_lon=float(lon_grid[mask].min()),
                lat_min=float(lat_grid[mask].min()),
                lat_max=float(lat_grid[mask].max()),
                covers_point=gh_at_point >= thr,
            )
        )
    return feats


def level_relative_humidity(
    ds: "xr.Dataset",
    level: int,
    point: tuple[float, float],
    domain: tuple[float, float, float, float] = EAST_ASIA_DOMAIN,
) -> tuple[float, float]:
    """Compute relative humidity (%) at a pressure level: domain mean & at a point.

    Numeric basis for the report's mid-level moisture comments (e.g. "700hPa
    水氣場較乾"), replacing visual reading of the 700 hPa field.

    Args:
        ds: Pressure-level Dataset with ``t`` (K) and ``q`` (kg/kg).
        level: Pressure level in hPa (e.g. 700).
        point: Reference point (lat, lon).
        domain: Box for the area mean.

    Returns:
        Tuple of (domain-mean RH %, point RH %).
    """
    import metpy.calc as mpcalc
    import numpy as np
    from metpy.units import units

    lev = ds.sel(isobaricInhPa=level)
    temperature = lev["t"].values * units.kelvin
    spec_humidity = lev["q"].values * units("kg/kg")
    rh = (
        mpcalc.relative_humidity_from_specific_humidity(
            level * units.hPa, temperature, spec_humidity
        )
        .to("percent")
        .magnitude
    )

    lats = lev["latitude"].values
    lons = lev["longitude"].values
    lat_min, lat_max, lon_min, lon_max = domain
    lat_sel = (lats >= lat_min) & (lats <= lat_max)
    lon_sel = (lons >= lon_min) & (lons <= lon_max)
    mean_rh = float(np.nanmean(rh[np.ix_(lat_sel, lon_sel)]))

    ip = int(np.argmin(np.abs(lats - point[0])))
    jp = int(np.argmin(np.abs(lons - point[1])))
    return mean_rh, float(rh[ip, jp])


def moisture_flux_850(ds: "xr.Dataset") -> "xr.DataArray":
    """Compute 850 hPa water-vapour flux magnitude (q × wind) on the grid.

    This is the numeric basis for the "水氣通量" field, replacing visual reading
    of a filled-contour GIF. Units: g kg⁻¹ m s⁻¹ (specific humidity in g/kg
    times wind speed in m/s).

    Args:
        ds: Pressure-level Dataset containing 850 hPa q/u/v.

    Returns:
        2-D DataArray of moisture-flux magnitude on the lat/lon grid.
    """
    import numpy as np

    lev = ds.sel(isobaricInhPa=850)
    speed = np.hypot(lev["u"], lev["v"])  # m/s
    flux = (lev["q"] * 1000.0) * speed  # g/kg * m/s
    flux.name = "moisture_flux_850"
    flux.attrs["units"] = "g kg-1 m s-1"
    return flux
