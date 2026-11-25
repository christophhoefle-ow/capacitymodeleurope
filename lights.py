"""Traffic lights in Python, with the same rules as the Excel model (sheets Lines, Transformers, Substations) and its default parameters.

Used for the map outside Excel (scripts/build_map.py). The Excel model stays the reference: scripts/check_model.py compares both sets of rules on every build.
"""
from __future__ import annotations

import pandas as pd

from .normalize import element_key

DEFAULTS = {"window_months": 3, "min_hours": 1, "red_share": 0.05, "amber_share": 0.05, "free_green_from": 100.0, "use_connection": True, "not_listed_red": False}
ORDER = {"Red": 3, "Amber": 2, "Green": 1, "Grey": 0}
STATUS_LIGHT = {"Bottleneck": "Red", "Highly loaded": "Amber", "Uncritical": "Green"}


def worst(*lights: str) -> str:
    return max(lights, key=lambda x: ORDER.get(x, 0)) if lights else "Grey"


def element_status(util: pd.DataFrame, p: dict) -> dict:
    """{key: (status, highest utilization)} over the evaluation window (the last window_months months with data)."""
    if util.empty:
        return {}
    months = sorted(util["month"].unique())[-int(p["window_months"]):]
    w = util[util["month"].isin(months)].copy()
    for c in ("hours", "hours_high", "hours_overload", "util_max"):
        w[c] = pd.to_numeric(w[c], errors="coerce").fillna(0)
    agg = w.groupby("key").agg(hours=("hours", "sum"), hh=("hours_high", "sum"), ho=("hours_overload", "sum"), umax=("util_max", "max"))
    out = {}
    for key, r in agg.iterrows():
        if r.hours == 0:
            continue
        st = "Too little data" if r.hours < p["min_hours"] else ("Bottleneck" if r.ho / r.hours >= p["red_share"] else ("Highly loaded" if r.hh / r.hours >= p["amber_share"] else "Uncritical"))
        out[key] = (st, float(r.umax))
    return out


def connection_light(row, p: dict, direction: str = "feed_in") -> str:
    """Light of one row of grid_connection_tso.csv for feed-in or load: the worse of the MW range and the status in words (as the Excel formula).
    The status of the direction (status_feed_in, status_load) overrides the general connection_status."""
    lo, hi = pd.to_numeric(row.get(f"{direction}_free_from_mw"), errors="coerce"), pd.to_numeric(row.get(f"{direction}_free_to_mw"), errors="coerce")
    mw = "" if pd.isna(lo) or pd.isna(hi) else ("Red" if hi <= 0 else ("Green" if lo >= p["free_green_from"] else "Amber"))
    own = str(row.get("status_feed_in" if direction == "feed_in" else "status_load", "") or "").strip().lower()
    st = {"available": "Green", "limited": "Amber", "none": "Red"}.get(own or str(row.get("connection_status") or "").strip().lower(), "")
    got = [x for x in (mw, st) if x]
    return worst(*got) if got else "Grey"


def compute(lines: pd.DataFrame, trafos: pd.DataFrame, subs: pd.DataFrame, util: pd.DataFrame, conn: pd.DataFrame | None = None, params: dict | None = None):
    """Returns (lines with status and utilization, substations with grid light, connection light, light (feed-in view), highest utilization, reason)."""
    p = {**DEFAULTS, **(params or {})}
    st = element_status(util, p)
    lines, trafos = lines.copy(), trafos.copy()
    for df in (lines, trafos):
        keys = [element_key(e, n) for e, n in zip(df["eic"], df["element_name"])]
        df["status"] = [st.get(k, ("No data", None))[0] for k in keys]
        df["util_max"] = [st.get(k, ("", None))[1] for k in keys]
    per: dict[str, list] = {}
    for s1, s2, s, u in zip(lines["substation_1"], lines["substation_2"], lines["status"], lines["util_max"]):
        for n in {s1, s2} - {""}:
            per.setdefault(n, []).append((s, u))
    for n, s, u in zip(trafos["substation"], trafos["status"], trafos["util_max"]):
        if n:
            per.setdefault(n, []).append((s, u))
    conn_by = {}
    if conn is not None and p["use_connection"]:
        conn_by = {r["substation"]: connection_light(r, p) for _, r in conn.iterrows()}
    rows = []
    for name, country in zip(subs["substation"], subs["country"]):
        assessed = [(s, u) for s, u in per.get(name, []) if s in STATUS_LIGHT]
        grid = worst(*[STATUS_LIGHT[s] for s, _u in assessed]) if assessed else "Grey"
        cl = conn_by.get(name, "Grey")
        umax = max((u for _s, u in assessed if u is not None), default=None)
        n_b, n_h = sum(s == "Bottleneck" for s, _u in assessed), sum(s == "Highly loaded" for s, _u in assessed)
        reason = (f"Bottleneck: {n_b} of {len(assessed)} assessed elements" if grid == "Red" else f"Highly loaded: {n_h} of {len(assessed)} assessed elements" if grid == "Amber"
                  else f"All {len(assessed)} assessed elements below the thresholds" if grid == "Green" else "No utilization data")
        if cl != "Grey":
            reason += {"Red": ", TSO: no connection capacity", "Amber": ", TSO: connection limited", "Green": ", TSO: connection available"}[cl]
        rows.append((name, country, grid, cl, worst(grid, cl), umax, reason))
    return lines, trafos, pd.DataFrame(rows, columns=["substation", "country", "light_grid", "light_connection", "light", "util_max", "reason"])
