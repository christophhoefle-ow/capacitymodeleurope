#!/usr/bin/env python3
"""Download the ENTSO-E TYNDP 2024 project data (open copy, CC BY 4.0) and report its structure.

The TYNDP lists the transmission projects of all ENTSO-E members (177 transmission and 33 storage projects assessed in the 2024 cycle) with promoters, countries, status,
expected commissioning year and capacity. It is the backbone for the European grid expansion layer; the EU list of PCI/PMI marks the cross-border projects of common interest.
Mode default: download to data/raw/tyndp/ (git-ignored) and print files, tables and columns. Nothing else in the repository changes.

  python scripts/fetch_tyndp.py            # download and report
  python scripts/fetch_tyndp.py --offline  # only report on the file already in data/raw/tyndp/
"""
from __future__ import annotations

import argparse
import io
import sys
import zipfile
from pathlib import Path

import pandas as pd
import requests

import _common as common


def describe_zip(data: bytes) -> list[dict]:
    """Entries of a zip with size and, for CSV and Excel files, the columns of the first table."""
    out = []
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        for info in z.infolist():
            if info.is_dir():
                continue
            entry = {"name": info.filename, "bytes": info.file_size, "rows": None, "columns": []}
            low = info.filename.lower()
            try:
                if low.endswith(".csv"):
                    df = pd.read_csv(io.BytesIO(z.read(info)), low_memory=False)
                elif low.endswith((".xlsx", ".xls")):
                    df = pd.read_excel(io.BytesIO(z.read(info)))
                else:
                    df = None
                if df is not None:
                    entry["rows"], entry["columns"] = len(df), [str(c) for c in df.columns]
            except Exception as exc:                                  # noqa: BLE001 - report the file and go on
                entry["error"] = str(exc)
            out.append(entry)
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="do not download, report on the existing file")
    args = ap.parse_args()
    cfg = common.load_config()["sources"]["tyndp"]
    out = common.ROOT / "data" / "raw" / "tyndp"
    out.mkdir(parents=True, exist_ok=True)
    path = out / Path(cfg["cba_projects_url"]).name
    if not args.offline:
        try:
            r = requests.get(cfg["cba_projects_url"], timeout=180)
            r.raise_for_status()
            path.write_bytes(r.content)
        except Exception as exc:                                      # noqa: BLE001
            print(f"DOWNLOAD FAILED ({exc})")
            return 1
    if not path.exists():
        print("file missing")
        return 1
    entries = describe_zip(path.read_bytes())
    print(f"{path.name}: {path.stat().st_size / 1e6:.1f} MB, {len(entries)} files")
    for e in entries[:60]:
        print(f"  {e['name']}  {e['bytes']} bytes", f"| rows {e['rows']}" if e["rows"] is not None else "", "| columns:" if e["columns"] else "", ", ".join(e["columns"][:25]), e.get("error", ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
