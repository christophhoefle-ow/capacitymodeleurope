"""Tests: country reference data, schematic outlines and the delivered substation coordinates."""
from pathlib import Path

import pandas as pd

from capmodel.countries import BBOX, LABEL, VIEW, inside
from capmodel.xl.outline import OUTLINES

ROOT = Path(__file__).resolve().parents[1]
CORE = ["AT", "BE", "CZ", "DE", "FR", "HR", "HU", "LU", "NL", "PL", "RO", "SI", "SK"]


def test_all_13_countries_have_view_label_box_and_closed_outline():
    for c in CORE:
        assert c in VIEW and c in LABEL and c in BBOX and c in OUTLINES, c
        assert OUTLINES[c][0] == OUTLINES[c][-1], f"{c}: outline not closed"
    assert "All" in VIEW


def test_outline_points_and_labels_lie_inside_the_country_box():
    for c in CORE:
        lon, lat = LABEL[c]
        assert inside(c, lat, lon), f"label of {c}"
        assert all(inside(c, la, lo, 0.8) for lo, la in OUTLINES[c]), f"outline of {c}"


def test_view_windows_are_valid_and_contain_the_label():
    for c in CORE:
        lo, hi, la, lb = VIEW[c]
        assert lo < hi and la < lb
        lon, lat = LABEL[c]
        assert lo <= lon <= hi and la <= lat <= lb, c
    a = VIEW["All"]
    assert all(a[0] <= LABEL[c][0] <= a[1] and a[2] <= LABEL[c][1] <= a[3] for c in CORE), "every country code must be visible in the All view"


def test_delivered_coordinates_are_inside_their_country_and_cover_most_substations():
    co = pd.read_csv(ROOT / "data" / "processed" / "substation_coordinates.csv", dtype=str, keep_default_na=False)
    subs = pd.read_csv(ROOT / "data" / "processed" / "master_substations.csv", dtype=str, keep_default_na=False)
    country = dict(zip(subs["substation"], subs["country"]))
    located = co[co["latitude"] != ""]
    bad = [n for n, la, lo in zip(located["substation"], located["latitude"], located["longitude"]) if not inside(country.get(n, ""), float(la), float(lo))]
    assert bad == [], bad
    core = subs[subs["country"].isin(CORE)]
    share = core["substation"].isin(set(located["substation"])).mean()
    assert share >= 0.95, share
