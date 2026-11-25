#!/usr/bin/env python3
"""Build the Excel model (from data/processed and config) and refresh the Power Query files.

  python scripts/build_excel_model.py --out build/Capacity_Model_Core.xlsx --base-url https://raw.githubusercontent.com/<ORG>/<REPO>/main/data/processed/
  python scripts/build_excel_model.py --out build/Capacity_Model_Core_ohne_Verbindungen.xlsx --no-connections
"""
import argparse
import sys
from pathlib import Path

import _common as common
from capmodel.xl.build import build_workbook, write_m_files


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", default="build/Capacity_Model_Core.xlsx")
    ap.add_argument("--base-url", default=None, help="address of the CSV files (with trailing slash); default: placeholder ORG/REPO")
    ap.add_argument("--no-connections", action="store_true", help="do not build data connections (data as a snapshot only)")
    ap.add_argument("--country", default="All", help="start selection of the Dashboard: All or a country code (e.g. PL)")
    ap.add_argument("--tso", default="All", help="start selection of the Dashboard: All or a TSO")
    ap.add_argument("--view", default="Feed-in", choices=["Feed-in", "Withdrawal"], help="start selection of the Dashboard")
    ap.add_argument("--grey", default="Hide", choices=["Hide", "Show"], help="start selection: show substations without data on the map")
    a = ap.parse_args()
    out = Path(a.out)
    if not out.is_absolute():
        out = common.ROOT / out
    build_workbook(common.ROOT, out, base_url=a.base_url, connections=not a.no_connections,
                   preset={"country": a.country, "tso": a.tso, "view": a.view, "grey": a.grey})
    n = len(write_m_files(common.ROOT))
    kind = "without data connections" if a.no_connections else f"with data connections ({a.base_url or 'placeholder ORG/REPO: please pass --base-url'})"
    print(f"Model written: {out}  ({out.stat().st_size / 1e6:.1f} MB), {kind}; Power Query files: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
