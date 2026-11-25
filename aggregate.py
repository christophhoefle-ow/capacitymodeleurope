"""Aggregation of hourly JAO rows into utilisation figures per network element.

Rules
  * utilisation of a row   = |Fref| / Fmax                      (only if Fmax > 0)
  * scenario 'base_case'   = only rows WITHOUT a contingency (n-0);  'worst_case' = all rows (n-1 included)
  * utilisation per hour   = maximum over all remaining rows of the same element (both directions)
  * per day and element    = hours, sum of the hourly values, maximum, hours >= 'high' threshold,
                             hours >= 'overload' threshold, hours with the JAO flag 'binding' (Presolved)

Why the SUM of the hourly values is stored: means cannot be combined over several days or months, sums can
(mean = sum / hours).
"""
from __future__ import annotations

import re
from typing import Iterable

import numpy as np
import pandas as pd

from .normalize import element_key, norm_eic, norm_text

SCENARIOS = ("base_case", "worst_case")
DAILY_COLUMNS = [
    "day", "scenario", "key", "tso", "country", "element", "names", "eic", "element_type",
    "substation_from", "substation_to", "hub_from", "hub_to", "voltage_kv", "imax_a", "fmax_mw",
    "hours", "util_sum", "util_max", "hours_high", "hours_overload", "hours_binding",
]
_TEXT_COLS = ["day", "scenario", "key", "tso", "country", "element", "names", "eic", "element_type",
              "substation_from", "substation_to", "hub_from", "hub_to"]

# According to the JAO handbook (v2.0, ch. 5.7/5.12) the domain pages also contain rows that do NOT describe a physical
# network element: elements with Imax = 9999 (Core / non-Core borders) and technical constraints
# (e.g. 'External Constraint BE_AL_export', 'NL_import', equality constraints).
IMAX_UNLIMITED = 9999
_TECH_NAME = re.compile(r"^\s*(external constraint|equality constraint)|^[a-z]{2}_(import|export)\s*$", re.I)
_BASECASE_NAMES = {"", "basecase", "base case", "n-0", "n0", "nan", "none"}


def is_base_case(contingency) -> bool:
    """Base case (n-0) = the row has no contingency name."""
    return norm_text(contingency).casefold() in _BASECASE_NAMES


def _to_float(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return np.nan


def rows_to_frame(raw_rows: Iterable[dict], tsos, hour_utc=None) -> pd.DataFrame:
    """Raw rows of the JAO API -> slim DataFrame.

    Field names are compared in lower case so that both the CSV spelling ('CneName') and JSON variants ('cneName') work.
    `tsos` is a dict {TSO name: country} (or just a list of names); only rows of these TSOs are kept.
    """
    tso_country = {norm_text(k).upper(): v for k, v in tsos.items()} if isinstance(tsos, dict) else {norm_text(t).upper(): "" for t in tsos}
    recs = []
    for raw in raw_rows:
        d = {str(k).lower(): v for k, v in raw.items()}
        tso = norm_text(d.get("tso")).upper()
        if tso not in tso_country:
            continue
        try:
            fmax = float(d.get("fmax"))
            fref = float(d.get("fref"))
        except (TypeError, ValueError):
            continue
        ts = hour_utc if hour_utc is not None else d.get("datetimeutc")
        presolved = str(d.get("presolved")).strip().lower() in ("true", "1", "yes")
        recs.append((ts, tso, tso_country[tso], d.get("cnename"), d.get("cneeic"), fmax, fref, _to_float(d.get("imax")),
                     _to_float(d.get("u")), presolved, norm_text(d.get("elementtype")), norm_text(d.get("substationfrom")),
                     norm_text(d.get("substationto")), norm_text(d.get("hubfrom")), norm_text(d.get("hubto")),
                     is_base_case(d.get("contname"))))
    cols = ["hour", "tso", "country", "name", "eic", "fmax", "fref", "imax", "u_kv", "presolved", "element_type",
            "sub_from", "sub_to", "hub_from", "hub_to", "base_case"]
    frame = pd.DataFrame(recs, columns=cols)
    if not frame.empty:
        frame["hour"] = pd.to_datetime(frame["hour"], utc=True)
    return frame


def _first_text(s: pd.Series) -> str:
    return next((x for x in s if isinstance(x, str) and x), "")


def daily_aggregate(frame: pd.DataFrame, day: str, util_high: float = 0.80, util_overload: float = 1.00,
                    scenario: str = "base_case") -> pd.DataFrame:
    """One daily file from all hourly rows of the day (one row per network element)."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}; expected one of {SCENARIOS}")
    if frame is None or frame.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    f = frame.copy()
    for c, default in (("imax", np.nan), ("u_kv", np.nan), ("presolved", False), ("base_case", True), ("country", ""),
                       ("element_type", ""), ("sub_from", ""), ("sub_to", ""), ("hub_from", ""), ("hub_to", "")):
        if c not in f:
            f[c] = default
    f["name"] = f["name"].map(norm_text)
    f["eic"] = f["eic"].map(norm_eic)
    f["key"] = [element_key(e, n) for e, n in zip(f["eic"], f["name"])]
    if scenario == "base_case":
        f = f[f["base_case"].astype(bool)]
    # exclude helper rows (see comment above); a missing Imax (NaN) is kept
    f = f[(f["fmax"] > 0) & ~(f["imax"] >= IMAX_UNLIMITED) & ~f["name"].str.match(_TECH_NAME)].copy()
    if f.empty:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    f["u"] = f["fref"].abs() / f["fmax"]
    # 1) per hour and element: the highest value ('binding' = at least one row of the hour with Presolved = TRUE)
    f["presolved"] = f["presolved"].astype(bool)
    hourly = f.groupby(["key", "hour"], as_index=False).agg(u=("u", "max"), fmax=("fmax", "min"), bind=("presolved", "max"))
    hourly["high"] = (hourly["u"] >= util_high).astype(int)
    hourly["over"] = (hourly["u"] >= util_overload).astype(int)
    stats = hourly.groupby("key", as_index=False).agg(
        fmax_mw=("fmax", "min"), hours=("u", "size"), util_sum=("u", "sum"), util_max=("u", "max"),
        hours_high=("high", "sum"), hours_overload=("over", "sum"), hours_binding=("bind", "sum"))
    # 2) descriptive fields: main name (most frequent) with its TSO, all name variants, further attributes
    cnt = f.groupby(["key", "name", "tso"]).size().reset_index(name="n")
    cnt = cnt.sort_values(["key", "n", "name", "tso"], ascending=[True, False, True, True])
    main = cnt.drop_duplicates("key")[["key", "name", "tso"]].rename(columns={"name": "element"})
    names = f.groupby("key")["name"].agg(lambda s: " | ".join(sorted({x for x in s if x}))).reset_index(name="names")
    attrs = f.groupby("key").agg(
        country=("country", _first_text), element_type=("element_type", _first_text), substation_from=("sub_from", _first_text),
        substation_to=("sub_to", _first_text), hub_from=("hub_from", _first_text), hub_to=("hub_to", _first_text),
        voltage_kv=("u_kv", "median"), imax_a=("imax", "median")).reset_index()
    out = stats.merge(main, on="key").merge(names, on="key").merge(attrs, on="key")
    out["eic"] = [k if not k.startswith("NAME|") else "" for k in out["key"]]
    out["day"] = day
    out["scenario"] = scenario
    for c in ("hours", "hours_high", "hours_overload", "hours_binding"):
        out[c] = out[c].astype(int)
    return out[DAILY_COLUMNS].sort_values("key").reset_index(drop=True)
