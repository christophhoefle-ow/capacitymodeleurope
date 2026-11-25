"""Automatic updates: map geodata, new network model, lights for the map outside Excel."""
import io

import pandas as pd

import conftest  # noqa: F401
from capmodel import geodata, lights
import update_sgm

# first rows of Georeferentiation_CORE-TSO_OSM.csv (Zenodo 10.5281/zenodo.13367535, version 0.2) as downloaded on 25.11.2026
DLR_HEAD = """,x,y,CORE-TSO_country,CORE-TSO_tso,OSM_id,OSM_type,OSM_name,OSM_country,OSM_voltage,OSM_operator,OSM_alt_name,Comments
Tauern,12.739733378696268,47.27759548453195,AT,APG,38868243.0,Polygon,Umspannwerk Tauern,AT,380000;220000,Austrian Power Grid AG,,
St. Peter,13.081870668673746,48.256519536727325,AT,APG,81540198.0,Polygon,Umspannwerk St. Peter,AT,380000,Austrian Power Grid AG,,
REPIQUAGE HOUFFALIZE 220kV,5.7982861,50.1499684,BE,ELIA,1292967364.0,Point,,BE,220000,,,Y-junction at 0.3 km from the station
St Peter,6.801901926183832,51.124931543129016,DE,Amprion GmbH,49577401.0,Polygon,Station Sankt Peter 220 kV,DE,220000;110000,RWE,,Multiple matches
Ohne Lage,,,DE,Amprion GmbH,,,,,,,,
"""


def test_dlr_table_is_read_in_its_published_layout():
    out = geodata.dlr_to_coordinates(pd.read_csv(io.StringIO(DLR_HEAD), dtype=str, keep_default_na=False))
    assert list(out.columns) == geodata.COORD_COLUMNS and len(out) == 4                      # the row without coordinates is dropped
    r = out.set_index(["substation", "country"])
    assert (r.loc[("Tauern", "AT"), "latitude"], r.loc[("Tauern", "AT"), "longitude"]) == (47.2776, 12.73973)
    assert r.loc[("St Peter", "DE"), "latitude"] == 51.12493 and r.loc[("St. Peter", "AT"), "latitude"] == 48.25652      # same name key, two countries, two places
    assert r.loc[("REPIQUAGE HOUFFALIZE 220kV", "BE"), "comment"].startswith("Y-junction")


def _square(x, y, d=1.0, n=40):
    side = [i * d / n for i in range(n)]
    return [[x + s, y] for s in side] + [[x + d, y + s] for s in side] + [[x + d - s, y + d] for s in side] + [[x, y + d - s] for s in side] + [[x, y]]


def test_borders_keep_the_countries_of_the_window_within_the_point_budget():
    gj = {"type": "FeatureCollection", "features": [
        {"type": "Feature", "properties": {"ISO_A2": "DE", "ADM0_A3": "DEU"}, "geometry": {"type": "Polygon", "coordinates": [_square(9, 50, 3)]}},
        {"type": "Feature", "properties": {"ISO_A2": "-99", "ISO_A2_EH": "FR", "ADM0_A3": "FRA"},                         # Natural Earth: ISO_A2 of France is -99
         "geometry": {"type": "MultiPolygon", "coordinates": [[_square(1, 45, 4)], [_square(-54, 4, 3)], [_square(9, 42, 0.05)]]}},   # mainland, French Guiana, a tiny island
        {"type": "Feature", "properties": {"ISO_A2": "-99", "ADM0_A3": "NOR"}, "geometry": {"type": "Polygon", "coordinates": [_square(8, 62, 3)]}},     # centre north of the window
        {"type": "Feature", "properties": {"ISO_A2": "LU"}, "geometry": {"type": "Polygon", "coordinates": [_square(6, 49.5, 0.3, n=3)]}}]}
    out = geodata.borders_from_geojson(gj, max_points=60)
    assert list(out.columns) == geodata.BORDER_COLUMNS and set(out["country"]) == {"DE", "FR", "LU"}
    assert out["ring"].nunique() == 3 and len(out) <= 60                                    # overseas ring and tiny island dropped, straight edges simplified
    for _ring, g in out.groupby("ring"):
        assert (g.iloc[0]["lon"], g.iloc[0]["lat"]) == (g.iloc[-1]["lon"], g.iloc[-1]["lat"]) and len(g) >= 4       # closed rings
    assert geodata.simplify([(0, 0), (1, 0.001), (2, 0), (2, 2)], 0.01) == [(0, 0), (2, 0), (2, 2)]


def test_new_network_model_is_only_adopted_if_plausible():
    assert update_sgm.pick_workbook(["doc/readme.pdf", "202609_Core Static Grid Model_10th release/Internal check.xlsx",
                                     "202609_Core Static Grid Model_10th release/202609_Core_Static_Grid_Model_External.xlsx"]).endswith("External.xlsx")
    assert update_sgm.pick_workbook(["readme.txt"]) is None
    old = {"lines": 2777, "transformers": 524, "substations": 1500, "tsos": {"APG", "RTE", "PSE"}}
    assert update_sgm.plausible(old, {"lines": 2800, "transformers": 530, "substations": 1510, "tsos": {"APG", "RTE", "PSE", "NEW"}}) == []
    bad = update_sgm.plausible(old, {"lines": 1200, "transformers": 530, "substations": 1510, "tsos": {"APG", "PSE"}})
    assert len(bad) == 2 and "lines" in bad[0] and "RTE" in bad[1]


def test_lights_follow_the_rules_of_the_excel_model():
    lines = pd.DataFrame({"element_name": ["A - B 1", "B - C 1", "C - D 1"], "eic": ["E1", "E2", ""], "substation_1": ["A", "B", "C"], "substation_2": ["B", "C", "D"]})
    trafos = pd.DataFrame({"element_name": ["TR D"], "eic": ["T1"], "substation": ["D"]})
    subs = pd.DataFrame({"substation": ["A", "B", "C", "D", "E"], "country": ["DE"] * 5})
    util = pd.DataFrame({"month": ["2026-10-01", "2026-11-01", "2026-11-01", "2026-11-01"], "key": ["E1", "E1", "E2", "T1"], "hours": [100, 100, 100, 50],
                         "hours_high": [0, 30, 4, 0], "hours_overload": [0, 20, 0, 0], "util_max": [0.7, 1.2, 0.85, 0.4]})
    conn = pd.DataFrame({"substation": ["C", "D", "E"], "connection_status": ["none", "", "available"], "feed_in_free_from_mw": ["", "0", ""], "feed_in_free_to_mw": ["", "500", ""]})
    ln, tr, sb = lights.compute(lines, trafos, subs, util, conn)
    assert list(ln["status"]) == ["Bottleneck", "Uncritical", "No data"] and list(tr["status"]) == ["Uncritical"]      # 20 of 200 hours overloaded = 10 % >= 5 %; 4 % high < 5 %
    got = sb.set_index("substation")
    assert list(got["light_grid"]) == ["Red", "Red", "Green", "Green", "Grey"]
    assert list(got["light_connection"]) == ["Grey", "Grey", "Red", "Amber", "Green"]        # status 'none'; 0 to 500 MW is amber; status 'available'
    assert list(got["light"]) == ["Red", "Red", "Red", "Amber", "Green"]                     # the worse of grid and connection
    assert got.loc["A", "util_max"] == 1.2 and "TSO: no connection capacity" in got.loc["C", "reason"]
    assert list(lights.compute(lines, trafos, subs, util, conn, {"use_connection": False})[2]["light"]) == ["Red", "Red", "Green", "Green", "Grey"]
    row = {"connection_status": "available", "status_feed_in": "none", "status_load": "", "load_free_from_mw": "500", "load_free_to_mw": "1000"}
    assert lights.connection_light(row, lights.DEFAULTS, "feed_in") == "Red" and lights.connection_light(row, lights.DEFAULTS, "load") == "Green"   # status of the direction overrides
