#!/usr/bin/env python3
"""Map geodata, fully automatic: exact substation positions and real country borders.

1. Positions: DLR-VE, 'Georeferentiation of CORE-TSO substations with OSM' (Zenodo 10.5281/zenodo.13367535, ODbL). The table lists the substations of the
   JAO Static Grid Model of all 13 countries with the position of the matching OpenStreetMap object -> data/static/coordinates_dlr_osm.csv
   (replaces the bundled excerpt coordinates_dlr_osm_excerpt.csv; the newest version of the Zenodo record is used if the record has one).
2. Borders: Natural Earth, admin 0 countries, 1:50m (public domain) -> data/static/borders.csv and borders_source.txt (the Excel map draws them).
Afterwards run: python scripts/build_processed.py, python scripts/estimate_coordinates.py (the GitHub action 'Update map geodata' does all of it).

  python scripts/update_geodata.py                 # download both and write the files
  python scripts/update_geodata.py --offline       # use the downloads already in data/raw/geodata/
Exit code 1 if a source failed; the files of that source then stay as they were.
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import sys
from datetime import date

import pandas as pd
import requests

import _common as common
from capmodel import geodata

log = logging.getLogger("geodata")
UA = {"User-Agent": "capacity-model-pipeline/0.3 (public data)"}


def zenodo_file(record: int, filename: str, fallback: str) -> tuple[str, str]:
    """(address of the file in the newest version of the record, version label). Falls back to the fixed address if the Zenodo API cannot be read."""
    try:
        meta = requests.get(f"https://zenodo.org/api/records/{record}/versions/latest", headers=UA, timeout=60)
        meta.raise_for_status()
        rec = meta.json()
        for f in rec.get("files", []):
            if f.get("key") == filename:
                link = (f.get("links") or {}).get("self") or f"https://zenodo.org/records/{rec['id']}/files/{filename}?download=1"
                return link, f"version {(rec.get('metadata') or {}).get('version', '?')}, record {rec.get('id')}"
    except Exception as exc:                                           # noqa: BLE001 - the fixed address of the checked version still works
        log.warning("Zenodo API not readable (%s): using the fixed address", exc)
    return fallback, f"record {record}"


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--offline", action="store_true", help="do not download, use data/raw/geodata/")
    args = ap.parse_args()
    common.setup_logging()
    cfg = common.load_config()["sources"]["geodata"]
    raw, static = common.ROOT / "data" / "raw" / "geodata", common.ROOT / "data" / "static"
    raw.mkdir(parents=True, exist_ok=True)
    failed = 0

    # --- 1 substation positions
    try:
        f, label = raw / cfg["dlr_file"], "local copy"
        if not args.offline:
            url, label = zenodo_file(int(cfg["dlr_record"]), cfg["dlr_file"], cfg["dlr_url"])
            r = requests.get(url, headers=UA, timeout=180)
            r.raise_for_status()
            f.write_bytes(r.content)
        coords = geodata.dlr_to_coordinates(pd.read_csv(f, dtype=str, keep_default_na=False))
        if len(coords) < int(cfg.get("dlr_min_rows", 1000)):
            raise RuntimeError(f"only {len(coords)} substations with coordinates, at least {cfg.get('dlr_min_rows', 1000)} expected")
        coords.to_csv(static / "coordinates_dlr_osm.csv", index=False, lineterminator="\n", encoding="utf-8")
        log.info("positions: %d substations (%s), per country %s", len(coords), label, coords["country"].value_counts().to_dict())
    except Exception as exc:                                           # noqa: BLE001
        failed += 1
        log.error("positions: %s (the previous file stays)", exc)

    # --- 2 country borders
    try:
        gj, used = None, ""
        if args.offline:
            files = sorted(raw.glob("*.geojson"))
            if not files:
                raise RuntimeError("no .geojson in data/raw/geodata/")
            gj, used = json.loads(files[0].read_text(encoding="utf-8")), files[0].name
        else:
            for url in cfg["borders_urls"]:
                try:
                    r = requests.get(url, headers=UA, timeout=240)
                    r.raise_for_status()
                    gj, used = json.load(io.BytesIO(r.content)), url
                    (raw / url.rsplit("/", 1)[-1]).write_bytes(r.content)
                    break
                except Exception as exc:                               # noqa: BLE001 - try the next address
                    log.warning("borders: %s: %s", url, exc)
            if gj is None:
                raise RuntimeError("none of the configured addresses could be read")
        borders = geodata.borders_from_geojson(gj, int(cfg.get("borders_max_points", 4500)))
        core = set(common.load_config()["region"]["tsos"].values())
        missing = sorted(core - set(borders["country"]))
        if missing:
            raise RuntimeError(f"Core countries without a border in the source: {missing}")
        borders.to_csv(static / "borders.csv", index=False, lineterminator="\n", encoding="utf-8")
        scale = "1:50m" if "50m" in used else ("1:110m" if "110m" in used else "")
        (static / "borders_source.txt").write_text(f"Natural Earth {scale} (public domain), simplified to {len(borders)} points, loaded {date.today().isoformat()}\n", encoding="utf-8")
        log.info("borders: %d countries, %d rings, %d points from %s", borders["country"].nunique(), borders["ring"].nunique(), len(borders), used)
    except Exception as exc:                                           # noqa: BLE001
        failed += 1
        log.error("borders: %s (the previous file stays)", exc)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
