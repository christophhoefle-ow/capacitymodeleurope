"""Tests: grid expansion layer (validation rules and the delivered data files)."""
from pathlib import Path

import pandas as pd

from capmodel.expansion import PROJECT_COLUMNS, SECTION_COLUMNS, validate

ROOT = Path(__file__).resolve().parents[1]


def _load():
    p = pd.read_csv(ROOT / "data" / "static" / "grid_expansion_projects.csv", dtype=str, keep_default_na=False)
    s = pd.read_csv(ROOT / "data" / "static" / "grid_expansion_sections.csv", dtype=str, keep_default_na=False)
    return p, s


def test_delivered_expansion_data_is_valid():
    p, s = _load()
    errors, warnings = validate(p, s)
    assert errors == [] and list(p.columns) == PROJECT_COLUMNS and list(s.columns) == SECTION_COLUMNS


def test_suedlink_sections_add_up_to_the_project_figures():
    p, s = _load()
    row = p[p["project_id"] == "BBPlG-03"].iloc[0]
    assert pd.to_numeric(s["length_km"]).sum() == float(row["length_km"]) == 693
    assert pd.to_numeric(s["built_km"]).sum() == float(row["built_km"]) == 72


def test_projects_cover_several_countries_and_both_scopes():
    p, _ = _load()
    countries = {c for v in p["countries"] for c in v.split(";")}
    assert {"DE", "BE", "CZ", "SK", "AT", "SI", "HU", "RO", "PL", "FR", "NL"} <= countries and {"national", "cross-border"} <= set(p["scope"])
    assert (p["plan_source"] != "").all() and (p["source_url"] != "").all() and (p["as_of"] != "").all()


def test_validation_catches_unknown_status_coordinates_and_progress():
    p, s = _load()
    p.loc[0, "status"] = "Dreaming"
    p.loc[1, "from_lat"] = "70"
    p.loc[2, "scope"] = "galactic"
    s.loc[0, "built_km"] = "999"
    errors, _ = validate(p, s)
    assert any("unknown status" in e for e in errors) and any("from_lat" in e for e in errors) and any("unknown scope" in e for e in errors) and any("sections: built_km" in e for e in errors)


def test_unknown_link_names_are_reported_as_warning():
    p, s = _load()
    _, warnings = validate(p, s, ["Isar"])
    assert any("link_from" in w for w in warnings)
