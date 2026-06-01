"""Tests for the sounding numeric adapter (route 2)."""

from datetime import datetime

import pytest

from climate_auto.report.sounding import (
    CWA_TO_IGRA,
    SoundingIndices,
    get_taiwan_sounding_indices,
)


def test_cwa_to_igra_contains_taipei_and_hualien() -> None:
    """The Taiwan station mapping covers the main operational sounding sites."""
    assert CWA_TO_IGRA["46692"] == "TWM00058968"  # Taipei
    assert CWA_TO_IGRA["46699"] == "TWM00059362"  # Hualien


def test_get_taiwan_sounding_indices_unknown_station_raises() -> None:
    """An unmapped CWA station id fails fast before any network call."""
    with pytest.raises(KeyError, match="No IGRA2 mapping"):
        get_taiwan_sounding_indices("99999", datetime(2023, 7, 15, 0))


def _sample_profile():
    """Build a realistic multi-level sounding for compute tests.

    Imports pandas lazily so the module-level test collection does not require
    the optional ``numerical`` extra.
    """
    pd = pytest.importorskip("pandas")
    # Standard levels with plausible mid-summer Taipei-like values.
    return pd.DataFrame(
        {
            "pressure": [1000, 925, 850, 700, 500, 400, 300, 250, 200, 150],
            "temperature": [
                29.2,
                25.4,
                21.2,
                10.0,
                -6.0,
                -16.0,
                -34.0,
                -45.0,
                -55.0,
                -62.0,
            ],
            "dewpoint": [
                23.2,
                20.7,
                16.9,
                4.0,
                -15.0,
                -28.0,
                -50.0,
                -60.0,
                -70.0,
                -75.0,
            ],
            "u_wind": [-0.8, 0.0, -4.0, -6.0, -10.0, -12.0, -15.0, -18.0, -20.0, -22.0],
            "v_wind": [1.8, 2.0, 6.9, 8.0, 10.0, 12.0, 14.0, 16.0, 18.0, 20.0],
        }
    )


def test_compute_indices_returns_finite_stability_indices() -> None:
    """K-index and Total Totals are simple level formulas → must compute."""
    pytest.importorskip("metpy")
    from climate_auto.report.sounding import compute_indices

    df = _sample_profile()
    result = compute_indices(
        df,
        source="IGRA2",
        label="46692/TWM00058968",
        valid_time=datetime(2023, 7, 15, 0),
    )

    assert isinstance(result, SoundingIndices)
    assert result.n_levels == 10
    assert result.source == "IGRA2"
    assert "46692" in result.label
    # Hand-computed: K = (T850-T500)+Td850-(T700-Td700) = 38.1
    assert result.k_index == pytest.approx(38.1, abs=0.5)
    # Hand-computed: TT = (T850-T500)+(Td850-T500) = 50.1
    assert result.total_totals == pytest.approx(50.1, abs=0.5)
    # Precipitable water must be a positive, finite number for a moist profile.
    assert result.pw_mm is not None and result.pw_mm > 0


def test_compute_indices_serializes_to_dict() -> None:
    """The result model round-trips to a plain dict for prompt/template use."""
    pytest.importorskip("metpy")
    from climate_auto.report.sounding import compute_indices

    df = _sample_profile()
    result = compute_indices(
        df,
        source="IGRA2",
        label="46692/TWM00058968",
        valid_time=datetime(2023, 7, 15, 0),
    )
    payload = result.model_dump()

    assert payload["source"] == "IGRA2"
    assert payload["label"] == "46692/TWM00058968"
    assert "k_index" in payload
