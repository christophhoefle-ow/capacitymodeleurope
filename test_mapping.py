"""Tests: matching of JAO elements with the master data, monthly aggregation and master rows for other countries."""
import pandas as pd

from capmodel.mapping import (LINE_COLUMNS, TRAFO_COLUMNS, build_mapping, derive_substations, jao_master, latest_attributes, monthly_from_daily,
                              sgm_elements, sgm_master)


def _lines(rows):
    df = pd.DataFrame(rows, columns=["element_name", "eic", "tso", "substation_1", "substation_2", "type", "neighbor_country"]).reindex(columns=LINE_COLUMNS).fillna("")
    df["country"] = "DE"          # static extracts carry the country of their TSO
    return df


def _daily(rows):
    cols = ["day", "scenario", "key", "tso", "country", "element", "names", "eic", "element_type", "substation_from", "substation_to", "hub_from", "hub_to",
            "voltage_kv", "imax_a", "fmax_mw", "hours", "util_sum", "util_max", "hours_high", "hours_overload", "hours_binding"]
    return pd.DataFrame(rows, columns=cols)


def _d(day, key, name, util_sum, hours=24, **kw):
    base = dict(day=day, scenario="base_case", key=key, tso="AMPRION", country="DE", element=name, names=name, eic=key if not key.startswith("NAME|") else "",
                element_type="Line", substation_from="A", substation_to="B", hub_from="DE", hub_to="DE", voltage_kv=380.0, imax_a=2000.0, fmax_mw=1000.0,
                hours=hours, util_sum=util_sum, util_max=0.9, hours_high=1, hours_overload=0, hours_binding=0)
    base.update(kw)
    return base


SGM = _lines([("Alpha - Beta", "EIC-A", "AMPRION", "Alpha", "Beta", "Line", ""), ("Gamma - Delta", "", "50HERTZ", "Gamma", "Delta", "Line", "")])
SGM_EL = sgm_elements(SGM, pd.DataFrame(columns=TRAFO_COLUMNS))


def test_match_by_eic_then_name_then_unmatched():
    daily = _daily([_d("2026-11-01", "EIC-A", "Alpha - Beta", 10.0), _d("2026-11-01", "NAME|gamma - delta", "gamma - DELTA", 5.0),
                    _d("2026-11-01", "EIC-X", "Foreign line", 3.0)])
    m = build_mapping(daily, SGM_EL).set_index("jao_key")["match"].to_dict()
    assert m == {"EIC-A": "EIC", "NAME|gamma - delta": "name", "EIC-X": "unmatched"}


def test_match_by_substation_pair_when_eic_and_name_changed_and_parallel_systems_are_assigned_one_by_one():
    sgm_lines = _lines([("Alpha - Beta 1", "EIC-P1", "AMPRION", "Alpha", "Beta", "Line", ""), ("Alpha - Beta 2", "EIC-P2", "AMPRION", "Alpha", "Beta", "Line", "")])
    sgm_lines["voltage_kv"] = "380"
    el = sgm_elements(sgm_lines, pd.DataFrame(columns=TRAFO_COLUMNS))
    daily = _daily([_d("2026-11-01", "NEW-1", "Renamed A", 1.0, substation_from="Alpha", substation_to="Beta", voltage_kv=400.0),
                    _d("2026-11-01", "NEW-2", "Renamed B", 1.0, substation_from="Beta", substation_to="Alpha", voltage_kv=400.0),
                    _d("2026-11-01", "NEW-3", "Renamed C", 1.0, substation_from="Alpha", substation_to="Beta", voltage_kv=400.0)])
    m = build_mapping(daily, el).set_index("jao_key")
    assert m.loc["NEW-1", "match"] == "substations" and m.loc["NEW-2", "match"] == "substations" and m.loc["NEW-3", "match"] == "unmatched"     # only two systems exist
    assert {m.loc["NEW-1", "key"], m.loc["NEW-2", "key"]} == {"EIC-P1", "EIC-P2"}


def test_alias_has_priority():
    daily = _daily([_d("2026-11-01", "EIC-Z", "Something else", 1.0)])
    alias = pd.DataFrame({"jao_key": ["EIC-Z"], "sgm_key": ["EIC-A"], "remark": [""]})
    assert build_mapping(daily, SGM_EL, alias).iloc[0].to_dict() == {"key": "EIC-A", "jao_key": "EIC-Z", "match": "alias"}


def test_monthly_adds_days_and_takes_worst_value_of_duplicates():
    daily = _daily([_d("2026-11-01", "EIC-A", "Alpha - Beta", 10.0), _d("2026-11-02", "EIC-A", "Alpha - Beta", 12.0), _d("2026-12-01", "EIC-A", "Alpha - Beta", 1.0)])
    mon = monthly_from_daily(daily, SGM_EL).set_index("month")
    assert mon.loc["2026-11-01", "hours"] == 48 and mon.loc["2026-11-01", "util_sum"] == 22.0 and mon.loc["2026-12-01", "hours"] == 24


def test_jao_master_creates_line_and_transformer_rows_with_country_ends():
    daily = _daily([_d("2026-11-01", "EIC-X", "Cross line", 3.0, tso="APG", country="AT", hub_from="AT", hub_to="DE", substation_from="S1", substation_to="S2"),
                    _d("2026-11-01", "EIC-T", "Trafo 1", 3.0, tso="PSE", country="PL", element_type="PST", substation_from="S3", hub_from="PL", hub_to="PL")])
    lines, trafos = jao_master(latest_attributes(daily))
    ln, tr = lines.iloc[0], trafos.iloc[0]
    assert ln["type"] == "Tie-line" and ln["neighbor_country"] == "DE" and ln["country_1"] == "AT" and ln["country_2"] == "DE" and ln["source"] == "JAO"
    assert tr["type"] == "PST" and tr["country"] == "PL" and tr["substation"] == "S3" and list(trafos.columns) == TRAFO_COLUMNS


def test_sgm_master_marks_foreign_end_of_tie_line_and_substations_get_country():
    raw = _lines([("Dom 1", "E1", "AMPRION", "Aaa", "Bbb", "Line", ""), ("Tie 1", "E2", "AMPRION", "Bbb", "Zzz", "Tie-line", "CH")])
    trafos = pd.DataFrame([{"element_name": "T", "substation": "Aaa", "country": "DE", "type": "Transformer"}]).reindex(columns=TRAFO_COLUMNS).fillna("")
    lines, trafos = sgm_master(raw, trafos)
    tie = lines[lines["element_name"] == "Tie 1"].iloc[0]
    assert tie["country_1"] == "DE" and tie["country_2"] == "CH"
    subs = derive_substations(lines, trafos).set_index("substation")["country"].to_dict()
    assert subs == {"Aaa": "DE", "Bbb": "DE", "Zzz": "CH"}
