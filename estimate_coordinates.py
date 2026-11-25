#!/usr/bin/env python3
"""Determine substation locations for ALL countries -> data/processed/substation_coordinates.csv (sheet D_Coordinates).

Ranking per substation:
  1. data/manual/coordinates_manual.csv   exact values entered by hand; override everything
  2. data/static/coordinates_*.csv        exact values from published datasets:
       files WITHOUT a column 'country'  = coordinates published by a TSO (e.g. the TenneT static grid model)
       files WITH a column 'country'     = OpenStreetMap positions matched to the JAO names (DLR dataset, Zenodo 10.5281/zenodo.13367535, ODbL);
                                           written by scripts/update_geodata.py. coordinates_dlr_osm.csv (complete) replaces the bundled excerpt.
  3. data/manual/coordinate_anchors.csv   approximate place of the same-named locality (general knowledge, unchecked)
  4. SGM grid: estimate from line lengths and topology (src/capmodel/geo.py), exact positions and anchors hold the layout in place
  5. all other substations: mean position of the located neighbours (schematic, with a small deterministic offset)
A located substation must lie inside the bounding box of its country (src/capmodel/countries.py), otherwise the position is rejected.
Reports: data/manual/coordinates_report.csv (removed anchors, ambiguous names, rejected positions) and coordinates_line_check.csv (long lines = suspicious anchors).
"""
from __future__ import annotations

import argparse
import math
import sys
import zlib
from collections import defaultdict

import pandas as pd

import _common as common
from capmodel import geo
from capmodel.countries import inside
from capmodel.sgm import base_key, node_key, split_suffix

CLASS = [(25, "estimated (error mostly below 25 km)"), (50, "estimated (error mostly below 50 km)"), (1e9, "estimated (uncertain, above 50 km possible)")]
ANCHOR, NEIGHBOR = "anchor (approx., unchecked)", "estimated from neighbors (schematic)"
EXACT_MANUAL = ("exact (manual)", "data/manual/coordinates_manual.csv")
EXACT_TSO = ("exact (TSO data, rounded)", "coordinates published by the TSO, rounded to about 1 km (data/static/coordinates_*.csv)")
EXACT_OSM = ("exact (OpenStreetMap)", "OpenStreetMap position matched to the JAO name (DLR-VE, Zenodo 10.5281/zenodo.13367535, ODbL)")


def load_static_coordinates(static_dir):
    """Published coordinates in data/static: returns (tso, osm).

    tso: {node key: (lat, lon)} from files without a column 'country' (a TSO lists its own substations, the name alone identifies them).
    osm: {(node key, country): (lat, lon)} from files with a column 'country' (names repeat between countries, e.g. 'St. Peter' in AT and DE).
    The complete file coordinates_dlr_osm.csv (written by scripts/update_geodata.py) replaces the bundled excerpt coordinates_dlr_osm_excerpt.csv.
    """
    tso, osm = {}, {}
    files = sorted(static_dir.glob("coordinates_*.csv"))
    if any(f.name == "coordinates_dlr_osm.csv" for f in files):
        files = [f for f in files if f.name != "coordinates_dlr_osm_excerpt.csv"]
    for f in files:
        df = pd.read_csv(f, dtype={"substation": str, "country": str}, keep_default_na=False)
        lat, lon = pd.to_numeric(df["latitude"], errors="coerce"), pd.to_numeric(df["longitude"], errors="coerce")
        ok = lat.notna() & lon.notna() & (df["substation"].str.strip() != "")
        if "country" in df.columns:
            for n, c, la, lo in zip(df.loc[ok, "substation"], df.loc[ok, "country"], lat[ok], lon[ok]):
                osm.setdefault((node_key(n), c.strip().upper()), (float(la), float(lo)))
        else:
            for n, la, lo in zip(df.loc[ok, "substation"], lat[ok], lon[ok]):
                tso.setdefault(node_key(n), (float(la), float(lo)))
    return tso, osm


def match_osm(names, country, osm):
    """Model substation -> OSM position. Rule: same name key and same country; otherwise the name key alone if it stands for ONE place
    (all entries within 2 km), so that a substation listed by the TSO of the neighbouring country is found as well. Homonyms in different places are skipped."""
    by_key = {}
    for (k, _c), pos in osm.items():
        by_key.setdefault(k, []).append(pos)
    out = {}
    for n in names:
        k, cc = base_key(n), split_suffix(n)[1] or country.get(n, "")
        if (k, cc) in osm:
            out[n] = osm[(k, cc)]
        elif not split_suffix(n)[1] and k in by_key and all(km(by_key[k][0], q) <= 2.0 for q in by_key[k]):
            out[n] = by_key[k][0]
    return out


def km(a, b):
    la1, lo1, la2, lo2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((la2 - la1) / 2) ** 2 + math.cos(la1) * math.cos(la2) * math.sin((lo2 - lo1) / 2) ** 2
    return 12742 * math.asin(math.sqrt(h))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--if-needed", action="store_true", help="only run if there are substations without an entry in substation_coordinates.csv (daily pipeline: saves about two minutes)")
    args = ap.parse_args()
    proc, man = common.ROOT / "data" / "processed", common.ROOT / "data" / "manual"
    if args.if_needed and (proc / "substation_coordinates.csv").exists():
        known = set(pd.read_csv(proc / "substation_coordinates.csv", dtype=str, keep_default_na=False)["substation"])
        new = set(pd.read_csv(proc / "master_substations.csv", dtype=str, keep_default_na=False)["substation"]) - known
        if not new:
            print("no new substations: locations unchanged")
            return 0
        print(f"{len(new)} new substation(s): determining locations")
    mlines = pd.read_csv(proc / "master_lines.csv", dtype=str, keep_default_na=False)
    mtraf = pd.read_csv(proc / "master_transformers.csv", dtype=str, keep_default_na=False)
    subs = pd.read_csv(proc / "master_substations.csv", dtype=str, keep_default_na=False)
    country = dict(zip(subs["substation"], subs["country"]))
    anchors_df = pd.read_csv(man / "coordinate_anchors.csv", dtype={"substation": str})
    manual_df = pd.read_csv(man / "coordinates_manual.csv", dtype={"substation": str})
    names = list(subs["substation"])
    by_key = lambda df: {node_key(r.substation): (float(r.latitude), float(r.longitude)) for r in df.itertuples()}
    a_key, m_key = by_key(anchors_df), by_key(manual_df)
    t_key, osm_key = load_static_coordinates(common.ROOT / "data" / "static")
    # outside sources know the plain name: 'St. Peter (AT)' is looked up as 'St. Peter', the country check below rejects the site of the other country
    ok_cc = lambda n, pos: inside(split_suffix(n)[1], pos[0], pos[1]) if split_suffix(n)[1] else True
    anchor_all = {n: a_key[base_key(n)] for n in names if base_key(n) in a_key and ok_cc(n, a_key[base_key(n)])}
    exact_manual = {n: m_key[k] for n in names for k in (node_key(n), base_key(n)) if k in m_key and ok_cc(n, m_key[k])}
    # OpenStreetMap (matched by name AND country) ranks above the TSO files: a TSO file is rounded to about 1 km and unreliable for substations of
    # neighbouring operators (TenneT file 03/2025: 'Stalldorf' 50 km, 'Hradec' 81 km away from the OpenStreetMap position of the substation)
    exact_osm = {n: p for n, p in match_osm(names, country, osm_key).items() if n not in exact_manual}
    tso_hit = {n: t_key[base_key(n)] for n in names if base_key(n) in t_key and not split_suffix(n)[1]}       # a name used in two countries cannot be told apart by a TSO file
    exact_tso = {n: p for n, p in tso_hit.items() if n not in exact_manual and n not in exact_osm}
    tso_differs = sorted(((n, km(p, exact_osm[n])) for n, p in tso_hit.items() if n in exact_osm and km(p, exact_osm[n]) > 5), key=lambda x: -x[1])
    exact_all = {**exact_tso, **exact_osm, **exact_manual}

    def exact_row(n):
        label = EXACT_MANUAL if n in exact_manual else (EXACT_OSM if n in exact_osm else EXACT_TSO)
        return (*exact_all[n], *label)
    report, result = [], {}

    # --- stage 1: SGM grid of all TSOs (topology + line lengths); exact positions and checked anchors are fixed points
    sgm_l, sgm_t = mlines[mlines["source"] == "SGM"], mtraf[mtraf["source"] == "SGM"]
    nodes = sorted({n for n in set(sgm_l["substation_1"]) | set(sgm_l["substation_2"]) | set(sgm_t["substation"]) if n}, key=str.casefold)
    nodeset = set(nodes)
    guessed = {a: c for a, c in anchor_all.items() if a in nodeset}
    exact = {a: c for a, c in exact_all.items() if a in nodeset}
    edges = geo.edge_table(sgm_l)
    # a name that joins two sites must not take part in the estimate (it would pull two regions together), even if its own position is exact
    amb_all = {n for n, _ in geo.find_ambiguous_nodes(nodes, edges, {**guessed, **exact})}
    ambiguous = amb_all - set(exact)
    edges2 = edges[~edges["u"].isin(amb_all) & ~edges["v"].isin(amb_all)]
    kept, removed = geo.clean_anchors(nodes, edges2, {a: c for a, c in guessed.items() if a not in amb_all})
    anchors = {**kept, **{a: c for a, c in exact.items() if a not in amb_all}}
    est, alpha, _ = geo.estimate_positions(nodes, edges2, anchors)
    e = est.set_index("substation")
    for n in nodes:
        if n in exact:
            result[n] = exact_row(n)
        elif n in e.index and bool(e.loc[n, "anchor"]):
            result[n] = (e.loc[n, "latitude"], e.loc[n, "longitude"], ANCHOR, "place of the same-named locality")
        elif n in e.index:
            cls = next(t for lim, t in CLASS if e.loc[n, "anchor_distance_km"] <= lim)
            result[n] = (e.loc[n, "latitude"], e.loc[n, "longitude"], cls, "estimate from line lengths and grid topology")
    report += [(n, "Ambiguous name: probably joins different sites (same name at several operators?)") for n in sorted(ambiguous)]
    report += [(n, "Check: position from a TSO file, but the connected lines do not fit one site (same name for two sites, or a wrong coordinate)")
               for n in sorted(amb_all & set(exact_tso))]
    report += [(n, f"TSO file differs from OpenStreetMap by {d:.0f} km: OpenStreetMap position used") for n, d in tso_differs]
    report += [(n, f"Anchor removed: does not fit the line lengths ({k} violations); check coordinate or name mix-up") for n, k in removed]

    # --- stage 2: anchors / exact values of all other substations
    for n in subs["substation"]:
        if n in result or n in ambiguous:
            continue
        if n in exact_all:
            result[n] = exact_row(n)
        elif n in anchor_all:
            result[n] = (*anchor_all[n], ANCHOR, "place of the same-named locality")

    # --- plausibility: inside the country
    for n, (lat, lon, acc, src) in list(result.items()):
        if not inside(country.get(n, ""), float(lat), float(lon)):
            report.append((n, f"Position rejected: ({float(lat):.2f}, {float(lon):.2f}) is outside {country.get(n, '?')}; check the anchor"))
            del result[n]

    # --- stage 3: neighbour estimate for the rest
    adj = defaultdict(set)
    for a, b in zip(mlines["substation_1"], mlines["substation_2"]):
        if a and b and a != b:
            adj[a].add(b)
            adj[b].add(a)
    for _ in range(8):
        new = {}
        for n in subs["substation"]:
            if n in result or n in ambiguous:
                continue
            nb = [(float(result[m][0]), float(result[m][1])) for m in adj[n] if m in result]
            if not nb:
                continue
            lat, lon = sum(p[0] for p in nb) / len(nb), sum(p[1] for p in nb) / len(nb)
            ang, r = (zlib.crc32(n.encode("utf-8")) % 360) * math.pi / 180, (14 if len(nb) == 1 else 5)
            lat, lon = lat + r * math.cos(ang) / 111.0, lon + r * math.sin(ang) / (111.0 * math.cos(math.radians(lat)))
            if inside(country.get(n, ""), lat, lon):
                new[n] = (lat, lon, NEIGHBOR, "mean position of the located neighbours (JAO lines)")
        if not new:
            break
        result.update(new)

    rows = []
    for n in subs["substation"]:
        if n in result:
            rows.append((n, round(float(result[n][0]), 4), round(float(result[n][1]), 4), result[n][2], result[n][3]))
        else:
            why = "ambiguous (name probably joins several sites)" if n in ambiguous else "no location (no anchor and no located neighbour)"
            rows.append((n, "", "", why, ""))
    out = pd.DataFrame(rows, columns=["substation", "latitude", "longitude", "accuracy", "source"])
    out.to_csv(proc / "substation_coordinates.csv", index=False, lineterminator="\n", encoding="utf-8")
    pd.DataFrame(report, columns=["substation", "finding"]).to_csv(man / "coordinates_report.csv", index=False, lineterminator="\n", encoding="utf-8")

    # --- long lines between located substations = suspicious positions
    pos = {n: (float(v[0]), float(v[1])) for n, v in result.items()}
    long_ = []
    for r in mlines.itertuples():
        if r.substation_1 in pos and r.substation_2 in pos:
            d = km(pos[r.substation_1], pos[r.substation_2])
            length = pd.to_numeric(r.length_km, errors="coerce")
            trusted = all(result[x][2] in (EXACT_OSM[0], EXACT_MANUAL[0]) for x in (r.substation_1, r.substation_2))
            # the air distance cannot exceed the length of the line. Not checked for tie-lines (each TSO lists only its own part of the line) and where both
            # ends are known exactly: there a short length is a property of the source (RTE lists sections), not a wrong position
            too_long = (not trusted) and r.type == "Line" and pd.notna(length) and length > 1 and d > 1.25 * length + 15
            if d > 200 or too_long:
                why = "air distance above the line length" if too_long else "longer than 200 km"
                long_.append((r.element_name, r.substation_1, r.substation_2, r.country, r.source, round(d), "" if pd.isna(length) else round(float(length)), why,
                              result[r.substation_1][2], result[r.substation_2][2]))
    pd.DataFrame(long_, columns=["element", "from", "to", "country", "source", "km", "length_km", "finding", "accuracy_from", "accuracy_to"]).sort_values("km", ascending=False).to_csv(
        man / "coordinates_line_check.csv", index=False, lineterminator="\n", encoding="utf-8")
    cov = out.assign(country=out["substation"].map(country), located=out["latitude"] != "").groupby("country")["located"].agg(["sum", "count"])
    print("located / total per country:", {c: f"{int(r['sum'])}/{int(r['count'])}" for c, r in cov.iterrows()})
    print(f"{len(out)} substations: {int(cov['sum'].sum())} located | rejected/removed: {sum('rejected' in f or 'removed' in f for _, f in report)} | lines > 200 km: {len(long_)} | alpha {alpha:.2f}")
    for _, f in report:
        if "rejected" in f:
            print("  REJECTED:", _, f[:110])
    return 0


if __name__ == "__main__":
    sys.exit(main())
