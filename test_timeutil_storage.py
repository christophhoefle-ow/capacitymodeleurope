"""Tests: business days (23/24/25 hours) and storage of daily and log files."""
import tempfile
from pathlib import Path

import pandas as pd

from capmodel.aggregate import DAILY_COLUMNS
from capmodel.storage import days_to_fetch, read_daily, read_log, update_log, write_day
from capmodel.timeutil import business_day_hours, day_range


def test_business_day_has_23_24_or_25_hours():
    assert len(business_day_hours("2026-11-16")) == 24
    assert len(business_day_hours("2026-03-29")) == 23      # spring forward
    assert len(business_day_hours("2026-10-25")) == 25      # fall back


def test_day_range_is_inclusive():
    assert day_range("2026-11-14", "2026-11-16") == ["2026-11-14", "2026-11-15", "2026-11-16"]


def _row(day, key, util_sum, scenario="base_case"):
    return dict(day=day, scenario=scenario, key=key, tso="X", country="DE", element=key, names=key, eic=key, element_type="Line", substation_from="A",
                substation_to="B", hub_from="DE", hub_to="DE", voltage_kv=380.0, imax_a=2000.0, fmax_mw=1000.0, hours=24, util_sum=util_sum, util_max=0.5,
                hours_high=0, hours_overload=0, hours_binding=0)


def test_write_day_replaces_the_same_day_and_scenario_only():
    with tempfile.TemporaryDirectory() as d:
        write_day(d, "2026-11-01", pd.DataFrame([_row("2026-11-01", "A", 1.0)], columns=DAILY_COLUMNS))
        write_day(d, "2026-11-02", pd.DataFrame([_row("2026-11-02", "A", 2.0)], columns=DAILY_COLUMNS))
        write_day(d, "2026-11-01", pd.DataFrame([_row("2026-11-01", "A", 5.0)], columns=DAILY_COLUMNS))                          # replace
        write_day(d, "2026-11-01", pd.DataFrame([_row("2026-11-01", "A", 7.0, "worst_case")], columns=DAILY_COLUMNS))            # other scenario stays
        got = read_daily(d)
        assert len(got) == 3 and sorted(got["util_sum"]) == [2.0, 5.0, 7.0] and list(got.columns) == DAILY_COLUMNS
        assert sorted(p.name for p in Path(d).iterdir()) == ["2026-11-01.csv.gz", "2026-11-02.csv.gz"]            # one file per day


def test_unchanged_day_gives_identical_bytes_and_legacy_monthly_files_are_still_read():
    with tempfile.TemporaryDirectory() as d:
        df = pd.DataFrame([_row("2026-11-01", "A", 1.0)], columns=DAILY_COLUMNS)
        p = write_day(d, "2026-11-01", df)
        first = p.read_bytes()
        write_day(d, "2026-11-01", df)
        assert p.read_bytes() == first
        pd.DataFrame([_row("2026-10-30", "B", 3.0), _row("2026-11-01", "A", 99.0)], columns=DAILY_COLUMNS).to_csv(Path(d) / "2026-10.csv", index=False)   # legacy monthly file
        got = read_daily(d).set_index(["day", "key"])
        assert len(got) == 2 and got.loc[("2026-11-01", "A"), "util_sum"] == 1.0 and got.loc[("2026-10-30", "B"), "util_sum"] == 3.0     # per-day file wins


def test_days_to_fetch_skips_complete_and_fallback_days():
    with tempfile.TemporaryDirectory() as d:
        p = Path(d) / "log.csv"
        for day, st in (("2026-11-16", "complete"), ("2026-11-17", "incomplete"), ("2026-11-18", "fallback")):
            update_log(p, {"day": day, "hours_expected": 24, "hours_delivered": 24, "rows_core": 1, "status": st, "fetched_utc": "x"})
        todo = days_to_fetch("2026-11-19", 3, read_log(p))
        assert todo == ["2026-11-17", "2026-11-19"]
