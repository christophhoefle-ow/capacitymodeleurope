"""Homonyms and aliases in the master data, and the map of the Excel model (regression test for the squeezed map)."""
import re
import tempfile
import zipfile
from pathlib import Path

import pandas as pd

import conftest  # noqa: F401
from capmodel import mapping
from capmodel.sgm import base_key, split_suffix
from capmodel.xl import build

ROOT = Path(__file__).resolve().parents[1]


def _lines(rows):
    cols = ["element_name", "tso", "substation_1", "substation_2", "type", "country", "neighbor_country", "country_1", "country_2"]
    return pd.DataFrame(rows, columns=cols)


def test_same_name_in_two_countries_becomes_two_nodes_and_border_substations_stay_one():
    lines = _lines([("Kronstorf - St. Peter 431", "APG", "Kronstorf", "St. Peter", "Line", "AT", "", "AT", "AT"),
                    ("Norf - St. Peter NORF W", "AMPRION", "Norf", "St Peter", "Line", "DE", "", "DE", "DE"),
                    ("St.Peter - Pirach 256", "APG", "St.Peter", "Pirach", "Tie-line", "AT", "DE", "AT", "DE"),
                    ("Diele - Meeden 380", "TENNETGMBH", "Diele", "Meeden", "Tie-line", "DE", "NL", "DE", "NL"),
                    ("Meeden - Eemshaven", "TENNETBV", "Meeden", "Eemshaven", "Line", "NL", "", "NL", "NL")])
    trafos = pd.DataFrame({"element_name": ["TR St. Peter 2"], "substation": ["St. Peter 2"], "country": ["AT"]})
    ln, tr, report = mapping.split_homonyms(lines, trafos)
    assert list(ln["substation_2"][:2]) == ["St. Peter (AT)", "St Peter (DE)"]
    assert ln.loc[2, "substation_1"] == "St.Peter (AT)" and ln.loc[2, "substation_2"] == "Pirach"            # the tie-line ends at the Austrian site
    assert list(ln["substation_2"][3:4]) == ["Meeden"] and ln.loc[4, "substation_1"] == "Meeden"              # a border substation is not a homonym
    assert tr.loc[0, "substation"] == "St. Peter (AT)"                                                         # busbar number dropped before the suffix
    assert {c for _n, c, _k in report} == {"AT", "DE"}
    assert split_suffix("St. Peter (AT)") == ("St. Peter", "AT") and split_suffix("Mole (La)") == ("Mole (La)", "") and base_key("St Peter (DE)") == "stpeter"


def test_typing_variants_are_merged_by_the_alias_list():
    lines = _lines([("Y-Metzingen HERBTG W", "AMPRION", "Herbentingen", "Metzingen", "Line", "DE", "", "DE", "DE")])
    trafos = pd.DataFrame({"element_name": ["TR"], "substation": ["Hanekenfaher E"], "country": ["DE"]})
    alias = pd.DataFrame({"alias": ["Herbentingen", "Hanekenfaher E"], "substation": ["Herbertingen", "Hanekenfaehr"], "note": ["", ""]})
    ln, tr, n = mapping.apply_substation_aliases(lines, trafos, alias)
    assert (ln.loc[0, "substation_1"], tr.loc[0, "substation"], n) == ("Herbertingen", "Hanekenfaehr", 2)


def test_map_charts_keep_their_proportions():
    """The plot area must fill the chart and the chart must have the ratio of the map units; otherwise Excel squeezes the map (bug of the first version)."""
    with tempfile.TemporaryDirectory() as tmp:
        out = build.build_workbook(ROOT, Path(tmp) / "model.xlsx", connections=False)
        z = zipfile.ZipFile(out)
        charts = [z.read(n).decode("utf-8") for n in z.namelist() if re.fullmatch(r"xl/charts/chart\d+\.xml", n)]
        drawings = [z.read(n).decode("utf-8") for n in z.namelist() if re.fullmatch(r"xl/drawings/drawing\d+\.xml", n)]
    assert len(charts) == 2 and len(drawings) == 2                                   # Dashboard and sheet Map
    for x in charts:
        lay = re.search(r"<plotArea><layout><manualLayout>(.*?)</manualLayout>", x)
        assert lay, "plot area without a layout: Excel would size it itself"
        assert all(f'<{k} val="{v}"' in lay.group(1) for k, v in (("layoutTarget", "inner"), ("x", "0"), ("y", "0"), ("w", "1"), ("h", "1")))
        assert '<autoTitleDeleted val="1"/>' in x and "<title>" not in x and "<legend>" not in x
        assert x.count('<delete val="1"/>') == 2                                     # both axes removed
    for d in drawings:
        cx, cy = map(int, re.search(r'<ext cx="(\d+)" cy="(\d+)"', d).groups())
        assert abs(cx / cy - build.MAP_W / build.MAP_H) < 0.01
        assert 'noChangeAspect="1"' in d
