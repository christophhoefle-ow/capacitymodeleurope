#!/usr/bin/env python3
"""Ingest the JAO Core Static Grid Model (all TSOs) and TSO files with coordinates into data/static/.

  python scripts/ingest_sgm.py 202603_Core_Static_Grid_Model_External.xlsx [--tso-coordinates Tennet_Static_Grid_Model.xlsx --label "TenneT SGM 03/2025"] [--release "202603, release 9"]

Writes: data/static/sgm_lines_core.csv, sgm_transformers_core.csv (all 16 TSOs, English headers, source SGM) and, if given, coordinates_<label>.csv.
Run again for every new SGM release (twice a year), then python scripts/build_processed.py and scripts/estimate_coordinates.py.
"""
from __future__ import annotations

import argparse
import re
import sys

import pandas as pd

import _common as common
from capmodel.mapping import LINE_COLUMNS, TRAFO_COLUMNS
from capmodel.sgm import display_name, node_key, read_lines, read_transformers, read_tso_coordinates


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("sgm", help="JAO Core Static Grid Model workbook (xlsx)")
    ap.add_argument("--tso-coordinates", help="TSO workbook with Longitude/Latitude columns (e.g. the TenneT static grid model)")
    ap.add_argument("--label", default="TSO file", help="source label for the coordinates")
    ap.add_argument("--release", help="release note stored in data/manual/sgm_release.txt")
    args = ap.parse_args()
    common.setup_logging()
    cfg = common.load_config()
    tso_country = cfg["region"]["tsos"]
    st = common.ROOT / "data" / "static"
    lines = read_lines(args.sgm, tso_country)
    names: dict[str, str] = {}
    for a, b in zip(lines["substation_1"], lines["substation_2"]):
        names.setdefault(node_key(a), display_name(a))
        names.setdefault(node_key(b), display_name(b))
    trafos = read_transformers(args.sgm, tso_country, names)
    lines[[c for c in LINE_COLUMNS if c not in ("country_1", "country_2")]].to_csv(st / "sgm_lines_core.csv", index=False, lineterminator="\n", encoding="utf-8")
    trafos[TRAFO_COLUMNS].to_csv(st / "sgm_transformers_core.csv", index=False, lineterminator="\n", encoding="utf-8")
    print(f"lines {len(lines)} ({(lines['type'] == 'Tie-line').sum()} cross-border tie-lines, {(lines['type'] == 'Internal tie-line').sum()} internal), transformers {len(trafos)}")
    print("lines per country:", lines["country"].value_counts().to_dict())
    print("substations:", len({node_key(x) for x in list(lines['substation_1']) + list(lines['substation_2']) + list(trafos['substation'])}))
    for old in ("sgm_lines_de.csv", "sgm_transformers_de.csv"):
        if (st / old).exists():
            (st / old).unlink()
            print("removed superseded", old)
    if args.tso_coordinates:
        co = read_tso_coordinates(args.tso_coordinates, args.label)
        slug = re.sub(r"[^a-z0-9]+", "_", args.label.casefold()).strip("_") or "tso"
        co.to_csv(st / f"coordinates_{slug}.csv", index=False, lineterminator="\n", encoding="utf-8")
        print(f"coordinates_{slug}.csv: {len(co)} substations with coordinates")
    if args.release:
        (common.ROOT / "data" / "manual" / "sgm_release.txt").write_text(args.release + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    sys.exit(main())
