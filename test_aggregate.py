"""Tests: aggregation of hourly JAO rows (scenario, thresholds, helper rows, units)."""
import pandas as pd

from capmodel.aggregate import DAILY_COLUMNS, daily_aggregate, is_base_case, rows_to_frame



def approx(x, tol=1e-9):
    class _A:
        def __eq__(self, other):
            return abs(other - x) <= tol
    return _A()


TSOS = {"AMPRION": "DE", "RTE": "FR"}


def _raw(hour, name, fref, fmax=1000.0, cont="", tso="AMPRION", eic="E1", imax=2000.0, presolved=False):
    return {"DateTimeUtc": hour, "Tso": tso, "CneName": name, "CneEic": eic, "Fmax": fmax, "Fref": fref, "Imax": imax, "U": 380.0,
            "Presolved": presolved, "ContName": cont, "ElementType": "Line", "SubstationFrom": "A", "SubstationTo": "B", "HubFrom": "DE", "HubTo": "DE"}


def _frame(rows):
    return rows_to_frame(rows, TSOS)


def test_base_case_detection():
    assert is_base_case("") and is_base_case(None) and is_base_case(float("nan")) and is_base_case("Basecase")
    assert not is_base_case("Lixhe - Gramme 380.11")


def test_utilization_is_fref_over_fmax_and_worst_direction():
    f = _frame([_raw("2026-11-16T00:00:00Z", "L1", 600.0), _raw("2026-11-16T00:00:00Z", "L1", -900.0)])
    out = daily_aggregate(f, "2026-11-16")
    assert len(out) == 1 and out.loc[0, "util_max"] == approx(0.9) and out.loc[0, "hours"] == 1


def test_base_case_ignores_outage_rows_worst_case_uses_them():
    rows = [_raw("2026-11-16T00:00:00Z", "L1", 500.0), _raw("2026-11-16T00:00:00Z", "L1", 1200.0, cont="Outage of X")]
    base = daily_aggregate(_frame(rows), "2026-11-16", scenario="base_case")
    worst = daily_aggregate(_frame(rows), "2026-11-16", scenario="worst_case")
    assert base.loc[0, "util_max"] == approx(0.5) and base.loc[0, "scenario"] == "base_case"
    assert worst.loc[0, "util_max"] == approx(1.2) and worst.loc[0, "hours_overload"] == 1


def test_element_with_outage_rows_only_is_not_part_of_the_base_case():
    out = daily_aggregate(_frame([_raw("2026-11-16T00:00:00Z", "L9", 1500.0, cont="Outage of X", eic="E9")]), "2026-11-16", scenario="base_case")
    assert out.empty and list(out.columns) == DAILY_COLUMNS


def test_hour_counts_and_sum_not_mean():
    rows = [_raw(f"2026-11-16T0{h}:00:00Z", "L1", f) for h, f in enumerate((500.0, 800.0, 1000.0, 1100.0))]
    out = daily_aggregate(_frame(rows), "2026-11-16", util_high=0.8, util_overload=1.0).iloc[0]
    assert out["hours"] == 4 and out["hours_high"] == 3 and out["hours_overload"] == 2
    assert out["util_sum"] == approx(3.4) and out["util_max"] == approx(1.1)


def test_helper_rows_are_excluded():
    rows = [_raw("2026-11-16T00:00:00Z", "External Constraint BE_AL_export", 100.0, eic=""), _raw("2026-11-16T00:00:00Z", "NL_import", 100.0, eic=""),
            _raw("2026-11-16T00:00:00Z", "Border element", 100.0, imax=9999.0, eic="E2"), _raw("2026-11-16T00:00:00Z", "Real", 100.0, eic="E3")]
    out = daily_aggregate(_frame(rows), "2026-11-16")
    assert list(out["eic"]) == ["E3"]


def test_only_configured_tsos_are_kept_and_country_is_set():
    f = _frame([_raw("2026-11-16T00:00:00Z", "L1", 1.0), _raw("2026-11-16T00:00:00Z", "L2", 1.0, tso="RTE", eic="E2"), _raw("2026-11-16T00:00:00Z", "L3", 1.0, tso="OTHER", eic="E3")])
    assert sorted(f["tso"]) == ["AMPRION", "RTE"] and dict(zip(f["tso"], f["country"])) == TSOS


def test_missing_eic_uses_name_key_and_trailing_blanks_are_ignored():
    rows = [_raw("2026-11-16T00:00:00Z", "Diefflen - Ensdorf ", 100.0, eic=""), _raw("2026-11-16T01:00:00Z", "Diefflen - Ensdorf", 100.0, eic="11TDNOTAVAILABLE")]
    out = daily_aggregate(_frame(rows), "2026-11-16")
    assert len(out) == 1 and out.loc[0, "key"] == "NAME|Diefflen - Ensdorf" and out.loc[0, "hours"] == 2


def test_unknown_scenario_is_rejected():
    try:
        daily_aggregate(_frame([_raw("2026-11-16T00:00:00Z", "L1", 1.0)]), "2026-11-16", scenario="n-2")
    except ValueError:
        return
    raise AssertionError("expected ValueError")
