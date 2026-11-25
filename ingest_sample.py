#!/usr/bin/env python3
"""Load a manually downloaded JAO Final Computation export (CSV or XLSX) into the daily files (demo / test data).

Example: python scripts/ingest_sample.py path/to/finalComputation_2026-11-16_0000-0100.xlsx --day 2026-11-16
Note: exports that were opened in a German-locale Excel contain numbers scaled by 1e10 (dot read as thousands separator).
The script detects this (median Fmax above 1e6) and rescales Fmax, Fref, Imax, U.
"""
from __future__ import annotations

import argparse
import sys
from datetime import datetime, timezone

import pandas as pd

import _common as common
from capmodel.aggregate import daily_aggregate, rows_to_frame
from capmodel.storage import update_log, write_day


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("file")
    ap.add_argument("--day", required=True, help="business day (YYYY-MM-DD) the hours belong to")
    ap.add_argument("--hours-expected", type=int, default=24)
    args = ap.parse_args()
    common.setup_logging()
    cfg = common.load_config()
    ev, tsos = cfg["evaluation"], cfg["region"]["tsos"]
    df = pd.read_csv(args.file) if args.file.lower().endswith(".csv") else pd.read_excel(args.file)
    scale = 1.0
    if pd.to_numeric(df["Fmax"], errors="coerce").median() > 1e6:
        scale = 1e-10
        for c in ("Fmax", "Fref", "Imax", "U", "Ram"):
            df[c] = pd.to_numeric(df[c], errors="coerce") * scale
    rows = df.to_dict("records")
    frame = rows_to_frame(rows, tsos)
    hours = frame["hour"].nunique() if not frame.empty else 0
    agg = daily_aggregate(frame, args.day, ev["util_high"], ev["util_overload"], ev["scenario"])
    write_day(common.path(cfg, "daily_dir"), args.day, agg)
    update_log(common.path(cfg, "fetch_log"), {"day": args.day, "hours_expected": args.hours_expected, "hours_delivered": hours,
                                               "rows_core": len(frame), "status": "sample",
                                               "fetched_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")})
    print(f"scale {scale}; {len(rows)} raw rows, {len(frame)} rows of {frame['tso'].nunique()} TSOs, {hours} hour(s); "
          f"{len(agg)} elements ({ev['scenario']}); countries: {sorted(agg['country'].unique())}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
