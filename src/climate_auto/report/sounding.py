"""Sounding adapter: fetch radiosonde profiles and compute thermodynamic indices.

Route (2) of ``docs/chart-recognition-research.md``: replace error-prone Skew-T
GIF *reading* with deterministic numeric *computation* from the raw sounding
that the GIF was plotted from.

Data-source reality (verified 2026-06):
  - **CWA OpenData REST** does NOT expose raw sounding profiles in its free
    tier (only surface / sea-surface observations); ``O-B0075-001`` is sea
    surface, and the catalogue has no upper-air profile dataset. The CWA key is
    still useful for *numerical forecast fields* (gh/t/u/v/q) and surface obs.
  - **University of Wyoming** archive does NOT carry Taiwan stations
    (station 46692 returns zero records across whole months).
  - **NOAA IGRA2** DOES carry Taiwan soundings, but under different station
    ids than CWA's WMO codes, and with an NCEI processing lag (records
    currently end ~2023, so it is not a same-day source).

Therefore IGRA2 is the source for historical / backtest numeric soundings;
same-day operational soundings still require the GIF (or CWA's restricted HDPS
service). This module is source-agnostic on the compute side: any DataFrame
with ``pressure``/``temperature``/``dewpoint`` columns (degC, hPa) feeds
:func:`compute_indices`.

Heavy dependencies (metpy, siphon, pandas) are imported lazily so the package
imports cleanly without the optional ``numerical`` extra installed::

    uv add --optional numerical metpy siphon   # already in pyproject
    uv run --extra numerical python -c "from climate_auto.report.sounding import get_taiwan_sounding_indices"
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from loguru import logger
from pydantic import BaseModel

if TYPE_CHECKING:  # pragma: no cover - typing only
    import pandas as pd

# CWA Skew-T station id (see probe_sounding.py) → IGRA2 station id.
# Note the ids differ from CWA's WMO codes. Stations marked (hist) only have
# records up to the year shown in the IGRA2 station list — not operational.
CWA_TO_IGRA: dict[str, str] = {
    "46692": "TWM00058968",  # 台北/板橋 Taipei      (IGRA2: 1957–2023)
    "46699": "TWM00059362",  # 花蓮 Hualien          (IGRA2: 1973–2023)
    "46695": "TWM00058974",  # 彭佳嶼 Pengjiayu      (IGRA2: 2023 only)
    "46750": "TWM00046750",  # 屏東 Pingtung   (hist, IGRA2 ends 2012)
    "46734": "TWM00046734",  # 馬公 Makung     (hist, IGRA2 ends 2012)
    "46810": "TWM00046810",  # 東沙 Dongsha    (hist, IGRA2 ends 2012)
    "46780": "TWM00046780",  # 綠島 Ludao      (hist, IGRA2 ends 2012)
}


class SoundingIndices(BaseModel):
    """Thermodynamic indices computed from a sounding profile.

    Source-neutral so the same model serves observed soundings (IGRA2) and
    forecast soundings (a column pulled from ECMWF GRIB). All index fields are
    optional: a value is ``None`` when it could not be computed for the given
    profile (e.g. no LFC on a stable sounding).
    """

    source: str
    """Where the profile came from, e.g. "IGRA2" or "ECMWF-fc"."""
    label: str
    """Human-readable identifier, e.g. "46692/TWM00058968" or "Taipei 25N,121.5E"."""
    valid_time: datetime
    n_levels: int

    sbcape: float | None = None
    sbcin: float | None = None
    mucape: float | None = None
    mlcape: float | None = None
    lcl_hpa: float | None = None
    lfc_hpa: float | None = None
    el_hpa: float | None = None
    k_index: float | None = None
    lifted_index: float | None = None
    showalter_index: float | None = None
    total_totals: float | None = None
    pw_mm: float | None = None


def fetch_igra2_sounding(igra_id: str, when: datetime) -> "pd.DataFrame":
    """Fetch a single IGRA2 sounding profile via Siphon.

    Args:
        igra_id: IGRA2 station id (e.g. "TWM00058968" for Taipei).
        when: Sounding launch time in UTC (typically 00Z or 12Z).

    Returns:
        DataFrame with at least ``pressure`` (hPa), ``temperature`` (degC),
        ``dewpoint`` (degC), ``u_wind``/``v_wind`` (knot) columns.

    Raises:
        ValueError: If no sounding exists for the requested station/time.
    """
    from siphon.simplewebservice.igra2 import IGRAUpperAir

    df, _header = IGRAUpperAir.request_data(when, igra_id)
    logger.info(
        "IGRA2 sounding {} @ {:%Y-%m-%d %H}Z: {} levels", igra_id, when, len(df)
    )
    return df


def compute_indices(
    df: "pd.DataFrame",
    *,
    source: str,
    label: str,
    valid_time: datetime,
) -> SoundingIndices:
    """Compute thermodynamic indices from a sounding DataFrame using MetPy.

    Each index is computed independently so a single failure does not abort the
    rest. Source-agnostic: any DataFrame with pressure/temperature/dewpoint in
    hPa/degC works, whether observed (IGRA2) or a forecast model column (ECMWF).

    Args:
        df: Sounding profile (columns ``pressure``/``temperature``/``dewpoint``
            in hPa/degC, decreasing pressure not required).
        source: Profile origin tag, e.g. "IGRA2" or "ECMWF-fc".
        label: Human-readable identifier for the profile.
        valid_time: Sounding valid time.

    Returns:
        Populated :class:`SoundingIndices`.
    """
    import metpy.calc as mpcalc
    import numpy as np
    from metpy.units import units

    clean = df.dropna(subset=["pressure", "temperature", "dewpoint"]).copy()
    clean = clean.sort_values("pressure", ascending=False).drop_duplicates("pressure")

    p = clean["pressure"].to_numpy() * units.hPa
    temp = clean["temperature"].to_numpy() * units.degC
    dewp = clean["dewpoint"].to_numpy() * units.degC

    values: dict[str, float | None] = {}

    def _try(name: str, fn) -> None:
        try:
            result = float(fn())
            values[name] = None if np.isnan(result) else result
        except Exception as exc:  # noqa: BLE001 - MetPy raises varied errors
            logger.debug("Could not compute {}: {}", name, exc)
            values[name] = None

    parcel = mpcalc.parcel_profile(p, temp[0], dewp[0]).to("degC")

    _try("sbcape", lambda: mpcalc.surface_based_cape_cin(p, temp, dewp)[0].m)
    _try("sbcin", lambda: mpcalc.surface_based_cape_cin(p, temp, dewp)[1].m)
    _try("mucape", lambda: mpcalc.most_unstable_cape_cin(p, temp, dewp)[0].m)
    _try("mlcape", lambda: mpcalc.mixed_layer_cape_cin(p, temp, dewp)[0].m)
    _try("lcl_hpa", lambda: mpcalc.lcl(p[0], temp[0], dewp[0])[0].m)
    _try("lfc_hpa", lambda: mpcalc.lfc(p, temp, dewp)[0].m)
    _try("el_hpa", lambda: mpcalc.el(p, temp, dewp)[0].m)
    _try("k_index", lambda: mpcalc.k_index(p, temp, dewp).m)
    _try("lifted_index", lambda: mpcalc.lifted_index(p, temp, parcel)[0].m)
    _try("showalter_index", lambda: mpcalc.showalter_index(p, temp, dewp)[0].m)
    _try("total_totals", lambda: mpcalc.total_totals_index(p, temp, dewp).m)
    _try("pw_mm", lambda: mpcalc.precipitable_water(p, dewp).to("mm").m)

    return SoundingIndices(
        source=source,
        label=label,
        valid_time=valid_time,
        n_levels=len(clean),
        **values,
    )


def get_taiwan_sounding_indices(
    cwa_station: str,
    when: datetime,
) -> SoundingIndices:
    """Fetch a Taiwan sounding from IGRA2 and compute its indices.

    Convenience wrapper that maps a CWA Skew-T station id to its IGRA2 id,
    fetches the profile, and computes indices.

    Args:
        cwa_station: CWA station id (e.g. "46692" for Taipei). See
            :data:`CWA_TO_IGRA` for supported stations.
        when: Sounding launch time in UTC (00Z or 12Z).

    Returns:
        Populated :class:`SoundingIndices`.

    Raises:
        KeyError: If ``cwa_station`` has no known IGRA2 mapping.
        ValueError: If no sounding exists for the requested station/time.
    """
    if cwa_station not in CWA_TO_IGRA:
        msg = (
            f"No IGRA2 mapping for CWA station {cwa_station}; "
            f"known: {sorted(CWA_TO_IGRA)}"
        )
        raise KeyError(msg)

    igra_id = CWA_TO_IGRA[cwa_station]
    df = fetch_igra2_sounding(igra_id, when)
    return compute_indices(
        df, source="IGRA2", label=f"{cwa_station}/{igra_id}", valid_time=when
    )
