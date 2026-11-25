#!/usr/bin/env python3
"""Download the open Core grid datasets (Zenodo) and report their structure.

Source: DLR-VE, 'Georeferentiation of CORE-TSO substations with OSM' (Zenodo 10.5281/zenodo.13367535, ODbL):
the substations, transformers and lines of the Core TSOs of 13 countries (from the JAO Static Grid Model) matched with OpenStreetMap objects, with coordinates.
Mode --check (default): download to data/raw/core_osm/ (git-ignored) and print files, rows, columns, countries and coordinate columns. Nothing else changes.
The structure report is the basis for the next step (dense network and exact substation positions for all countries).

  python scripts/fetch_core_grid.py            # download and report
  python scripts/fetch_core_grid.py --offline  # only report on files already in data/raw/core_osm/
"""
from __future__ import annotations

import argparse
import hashlib
import sys
from pathlib import Path

import pandas as pd
import requests

import _common as common

COORD_SYNONYMS = {"lat": ("lat", "latitude", "y"), "lon": ("lon", "lng", "longitude", "x"), "country": ("country", "cntry", "country_code"),
                  "voltage": ("voltage", "v_nom", "voltage_kv", "kv"), "name": ("name", "substation", "substation_name", "bus_id", "id")}


def describe(df: pd.DataFrame) -> dict:
    """Structure of a table: row count, columns and which columns look like coordinates, country, voltage and name."""
    low = {str(c).lower(): c for c in df.columns}
    found = {k: next((low[s] for s in syn if s in low), None) for k, syn in COORD_SYNONYMS.items()}
    countries = {}
    if found["country"] is not None:
        countries = df[found["country"]].astype(str).value_counts().head(20).to_dict()
    return {"rows": len(df), "columns": [str(c) for c in df.columns], "detected": found, "countries": countries}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="do not download, only report on existing files")
    args = ap.parse_args()
    cfg = common.load_config()["sources"]["core_osm"]
    out = common.ROOT / "data" / "raw" / "core_osm"
    out.mkdir(parents=True, exist_ok=True)
    errors = 0
    for name in cfg["files"]:
        path = out / name
        if not args.offline:
            url = f"https://zenodo.org/records/{cfg['zenodo_record']}/files/{name}?download=1"
            try:
                r = requests.get(url, timeout=120)
                r.raise_for_status()
                path.write_bytes(r.content)
            except Exception as exc:                                  # noqa: BLE001 - report and continue with the other files
                print(f"{name}: DOWNLOAD FAILED ({exc})")
                errors += 1
                continue
        if not path.exists():
            print(f"{name}: missing")
            errors += 1
            continue
        md5 = hashlib.md5(path.read_bytes()).hexdigest()
        try:
            info = describe(pd.read_csv(path, low_memory=False))
        except Exception as exc:                                      # noqa: BLE001
            print(f"{name}: not readable as CSV ({exc})")
            errors += 1
            continue
        print(f"\n{name}  md5 {md5}  rows {info['rows']}")
        print("  columns :", ", ".join(info["columns"][:40]))
        print("  detected:", {k: v for k, v in info["detected"].items() if v})
        if info["countries"]:
            print("  countries:", info["countries"])
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
