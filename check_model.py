#!/usr/bin/env python3
"""Independent check of the Excel model: recompute status and traffic lights in pandas and compare them with the Excel results.

Usage: python scripts/check_model.py <xlsx with calculated values>   (e.g. recalculated with LibreOffice, or saved by Excel)
Checks: key, status and light of every line and transformer, grid light and highest utilization of every substation, the connection light per direction
(recomputed from the sheet D_Connection with src/capmodel/lights.py), the resulting light for feed-in and withdrawal, Dashboard KPI tiles.
"""
from __future__ import annotations

import sys
import warnings

import pandas as pd
from openpyxl import load_workbook

import _common as common  # noqa: F401  (sets sys.path)
from capmodel import lights
from capmodel.xl.build import LN, R0, SN, SZ, TN, last

warnings.filterwarnings("ignore")


def _param(wb, name):
    sheet, ref = wb.defined_names[name].attr_text.split("!")
    return wb[sheet][ref.replace("$", "")].value


def _key(eic, name):
    e = (eic or "").strip()
    return "NAME|" + " ".join(str(name).replace("\xa0", " ").split()) if (not e or "NOTAVAILABLE" in e.upper()) else e


def _status(hours, hh, ho, min_h, red, amber):
    if hours == 0:
        return "No data"
    if hours < min_h:
        return "Too little data"
    if ho / hours >= red:
        return "Bottleneck"
    return "Highly loaded" if hh / hours >= amber else "Uncritical"


def _table(ws, n, cols, keys):
    return {k: [ws[f"{cols.L(k)}{r}"].value for r in range(R0, R0 + n)] for k in keys}


def main(path: str) -> int:
    wb = load_workbook(path, data_only=True)
    # the row counts of the calculation sheets are part of the workbook: read them from the file (they grow with the data)
    SZ["lines"], SZ["trafos"], SZ["subs"] = (wb["Lines"].max_row - R0 + 1, wb["Transformers"].max_row - R0 + 1, wb["Substations"].max_row - R0 + 1)
    red, amber, min_h = _param(wb, "P_RedShare"), _param(wb, "P_AmberShare"), _param(wb, "P_MinHours")
    d_from, d_to = _param(wb, "P_From"), _param(wb, "P_To")
    du = pd.DataFrame([[c.value for c in row] for row in wb["D_Utilization"].iter_rows(min_row=R0, max_col=13)],
                      columns=["month", "key", "match", "tso", "element", "eic", "fmax", "hours", "util_sum", "util_max", "hh", "ho", "hb"]).dropna(subset=["key"])
    du["month"] = pd.to_datetime(du["month"])
    win = du[(du["month"] >= pd.Timestamp(d_from)) & (du["month"] <= pd.Timestamp(d_to))]
    agg = win.groupby("key").agg(hours=("hours", "sum"), hh=("hh", "sum"), ho=("ho", "sum"), umax=("util_max", "max")).to_dict("index")
    errors, notes = [], []

    def compare(sheet, cols, n, with_dup=False):
        ws = wb[sheet]
        t = _table(ws, n, cols, ["name", "eic", "key", "status", "light", "umax", "hours"])
        nrows = 0
        for i, name in enumerate(t["name"]):
            if not name:
                continue
            nrows += 1
            key = _key(t["eic"][i], name)
            a = agg.get(key, {"hours": 0, "hh": 0, "ho": 0, "umax": None})
            st = _status(a["hours"], a["hh"], a["ho"], min_h, red, amber)
            light = {"Bottleneck": "Red", "Highly loaded": "Amber", "Uncritical": "Green"}.get(st, "Grey")
            if t["key"][i] != key:
                errors.append(f"{sheet} row {R0 + i}: key {t['key'][i]!r} != {key!r}")
            if t["status"][i] != st or t["light"][i] != light:
                errors.append(f"{sheet} row {R0 + i} {name}: Excel {t['status'][i]}/{t['light'][i]}, expected {st}/{light}")
            if a["hours"] and abs((t["umax"][i] or 0) - a["umax"]) > 1e-6:
                errors.append(f"{sheet} row {R0 + i} {name}: max utilization {t['umax'][i]} != {a['umax']}")
        return nrows, t

    n_l, tl = compare("Lines", LN, last("lines") - R0 + 1)
    n_t, tt = compare("Transformers", TN, last("trafos") - R0 + 1)
    # substations: light of the grid = worst of the connected assessed elements
    ws = wb["Substations"]
    sub_ = _table(ws, last("subs") - R0 + 1, SN, ["sub", "lgrid", "umax", "ntype", "lf", "country"])
    lines_by_node, trafo_by_node = {}, {}
    ln = wb["Lines"]
    for i in range(len(tl["name"])):
        if tl["name"][i]:
            for k in ("sub1", "sub2"):
                node = ln[f"{LN.L(k)}{R0 + i}"].value
                if node:
                    lines_by_node.setdefault(node, set()).add(i)
    tr = wb["Transformers"]
    for i in range(len(tt["name"])):
        if tt["name"][i]:
            node = tr[f"{TN.L('sub')}{R0 + i}"].value
            if node:
                trafo_by_node.setdefault(node, []).append(i)
    n_s, counts = 0, {"Red": 0, "Amber": 0, "Green": 0, "Grey": 0}
    for i, node in enumerate(sub_["sub"]):
        if not node:
            continue
        n_s += 1
        sts, utils = [], []
        for j in lines_by_node.get(node, ()):
            if tl["status"][j] in ("Bottleneck", "Highly loaded", "Uncritical"):
                sts.append(tl["status"][j])
                utils.append(tl["umax"][j])
        for j in trafo_by_node.get(node, ()):
            if tt["status"][j] in ("Bottleneck", "Highly loaded", "Uncritical"):
                sts.append(tt["status"][j])
                utils.append(tt["umax"][j])
        exp = "Grey" if not sts else ("Red" if "Bottleneck" in sts else ("Amber" if "Highly loaded" in sts else "Green"))
        if sub_["lgrid"][i] != exp:
            errors.append(f"Substations row {R0 + i} {node}: grid light {sub_['lgrid'][i]} != {exp}")
        if utils and abs((sub_["umax"][i] or 0) - max(utils)) > 1e-6:
            errors.append(f"Substations row {R0 + i} {node}: highest utilization {sub_['umax'][i]} != {max(utils)}")
        if sub_["ntype"][i] == "Core node":
            counts[sub_["lf"][i]] = counts.get(sub_["lf"][i], 0) + 1
    # connection light per direction: the worse of the MW range and the status in words; then the light of the substation = the worse of grid and connection
    use, green_from, not_listed = _param(wb, "P_UseConnection"), _param(wb, "P_FreeGreenFrom"), _param(wb, "P_NotListed")
    dc = wb["D_Connection"]
    heads = [c.value for c in dc[4]]
    conn = {}
    for row in dc.iter_rows(min_row=R0, max_col=len(heads), values_only=True):
        if row[0]:
            conn.setdefault(row[0], dict(zip(heads, row)))
    listed_tsos = {r.get("tso") for r in conn.values()}
    sub2 = _table(ws, last("subs") - R0 + 1, SN, ["sub", "tso", "lgrid", "lcf", "lcw", "lf", "lw"])
    n_conn = 0
    for i, node in enumerate(sub2["sub"]):
        if not node:
            continue
        for direction, c_conn, c_light in (("feed_in", "lcf", "lf"), ("load", "lcw", "lw")):
            if use == "NO":
                exp = "Grey"
            elif node in conn:
                exp = lights.connection_light(conn[node], {"free_green_from": green_from}, direction)
            else:
                exp = "Red" if (not_listed == "RED" and sub2["tso"][i] in listed_tsos) else "Grey"
            if sub2[c_conn][i] != exp:
                errors.append(f"Substations row {R0 + i} {node}: connection light {direction} {sub2[c_conn][i]} != {exp}")
            if sub2[c_light][i] != lights.worst(sub2["lgrid"][i], exp):
                errors.append(f"Substations row {R0 + i} {node}: light {direction} {sub2[c_light][i]} != worse of grid {sub2['lgrid'][i]} and connection {exp}")
        n_conn += node in conn
    notes.append(f"connection: {len(conn)} rows in D_Connection, {n_conn} substations of the model with a statement of their TSO")
    # Dashboard tiles (default selection: Feed-in, All, All)
    d = wb["Dashboard"]
    if (d["B3"].value, d["D3"].value, d["F3"].value) == ("Feed-in", "All", "All"):
        tiles = [d["A7"].value, d["C7"].value, d["E7"].value, d["G7"].value]
        if tiles != [counts["Red"], counts["Amber"], counts["Green"], counts["Grey"]]:
            errors.append(f"Dashboard tiles {tiles} != {[counts[k] for k in ('Red', 'Amber', 'Green', 'Grey')]}")
    print(f"checked: {n_l} lines, {n_t} transformers, {n_s} substations; window {d_from:%m/%Y}-{d_to:%m/%Y}; lights (Core nodes, feed-in): {counts}")
    for note in notes:
        print("  ", note)
    for e in errors[:25]:
        print("  DEVIATION:", e)
    print("\nALL CHECKS PASSED" if not errors else f"\n{len(errors)} DEVIATION(S)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
