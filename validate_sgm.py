#!/usr/bin/env python3
"""Plausibility checks of the static SGM extracts (data/static/sgm_lines_*.csv, sgm_transformers_*.csv).

Errors stop the pipeline (exit code 1), warnings are only reported. Run after every new SGM release.
"""
from __future__ import annotations

import sys

import pandas as pd

import _common as common
from capmodel.mapping import LINE_COLUMNS, TRAFO_COLUMNS
from capmodel.normalize import norm_eic

TYPES = {"Line", "Tie-line", "Internal tie-line"}
NUMERIC = {"lines": ["voltage_kv", "imax_fixed_a", "dlr_min_a", "dlr_max_a", "length_km"], "transformers": ["imax_min_a", "imax_max_a", "imax_fixed_a", "u_primary_kv"]}


def validate(lines: pd.DataFrame, trafos: pd.DataFrame):
    errors, warnings = [], []
    need = {"lines": [c for c in LINE_COLUMNS if c not in ("country_1", "country_2")], "transformers": TRAFO_COLUMNS}
    for name, df in (("lines", lines), ("transformers", trafos)):
        missing = [c for c in need[name] if c not in df.columns]
        if missing:
            errors.append(f"{name}: columns missing: {missing}")
            continue
        for c in NUMERIC[name]:
            bad = pd.to_numeric(df[c].replace("", pd.NA), errors="coerce")
            if int((bad.isna() & (df[c] != "")).sum()):
                errors.append(f"{name}: column {c} contains non-numeric values")
    if "type" in lines.columns and set(lines["type"]) - TYPES:
        errors.append(f"lines: unknown types {sorted(set(lines['type']) - TYPES)}")
    kv = pd.to_numeric(lines["voltage_kv"].replace("", pd.NA), errors="coerce")
    if int(kv.isna().sum()):
        warnings.append(f"lines: {int(kv.isna().sum())} rows without voltage (Smax stays empty)")
    key = lines["eic"].map(norm_eic) + "|" + lines["element_name"].str.strip().str.casefold()
    dup = int((key.duplicated(keep=False) & (lines["eic"].map(norm_eic) != "")).sum())
    if dup:
        warnings.append(f"lines: {dup} rows with identical EIC and name (possible duplicates)")
    no_eic = int((lines["eic"].map(norm_eic) == "").sum())
    if no_eic:
        warnings.append(f"lines: {no_eic} rows without EIC (matching by name only)")
    return errors, warnings


def main() -> int:
    st = common.ROOT / "data" / "static"
    lines = pd.concat([pd.read_csv(f, dtype=str, keep_default_na=False) for f in sorted(st.glob("sgm_lines_*.csv"))], ignore_index=True)
    trafos = pd.concat([pd.read_csv(f, dtype=str, keep_default_na=False) for f in sorted(st.glob("sgm_transformers_*.csv"))], ignore_index=True)
    errors, warnings = validate(lines, trafos)
    for w in warnings:
        print("WARNING:", w)
    for e in errors:
        print("ERROR:  ", e)
    print(f"{len(lines)} lines, {len(trafos)} transformers checked: {len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
