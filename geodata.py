"""Map geodata from open sources: exact substation positions (OpenStreetMap, matched by DLR) and country borders (Natural Earth).

Both are read automatically by scripts/update_geodata.py and stored as small static CSV files:
  data/static/coordinates_dlr_osm.csv   substation, latitude, longitude, country, tso, osm_name, comment
  data/static/borders.csv               country, ring, lon, lat   (one closed ring after the other)
"""
from __future__ import annotations

import pandas as pd

COORD_COLUMNS = ["substation", "latitude", "longitude", "country", "tso", "osm_name", "comment"]
BORDER_COLUMNS = ["country", "ring", "lon", "lat"]
WINDOW = (-12.0, 32.5, 35.5, 60.0)        # lon_min, lon_max, lat_min, lat_max: rings whose centre lies outside are not drawn (overseas territories, Scandinavia north of 60 N)
A3 = {"FRA": "FR", "NOR": "NO", "KOS": "XK", "DEU": "DE", "AUT": "AT", "BEL": "BE", "CZE": "CZ", "HRV": "HR", "HUN": "HU", "LUX": "LU", "NLD": "NL", "POL": "PL", "ROU": "RO",
      "SVN": "SI", "SVK": "SK", "CHE": "CH", "DNK": "DK", "ITA": "IT", "ESP": "ES", "GBR": "GB", "IRL": "IE", "PRT": "PT", "SRB": "RS", "BIH": "BA", "MNE": "ME", "MKD": "MK",
      "ALB": "AL", "BGR": "BG", "UKR": "UA", "MDA": "MD", "BLR": "BY", "LTU": "LT", "LVA": "LV", "RUS": "RU", "GRC": "GR", "SWE": "SE", "AND": "AD", "LIE": "LI", "TUR": "TR"}


# ----------------------------------------------------------------------------- substation positions
def dlr_to_coordinates(df: pd.DataFrame) -> pd.DataFrame:
    """Table 'Georeferentiation_CORE-TSO_OSM.csv' of the DLR dataset -> coordinates in the layout of data/static.

    Layout of the source (version 0.2, checked 25.11.2026): first column without header = substation name as in the JAO Static Grid Model, x = longitude, y = latitude,
    CORE-TSO_country, CORE-TSO_tso, OSM_id, OSM_type, OSM_name, OSM_country, OSM_voltage, OSM_operator, OSM_alt_name, Comments. Header names are matched without regard
    to case, so a renamed or reordered column in a later version does not break the import.
    """
    low = {str(c).strip().lower(): c for c in df.columns}
    name = df.columns[0] if str(df.columns[0]).lower().startswith("unnamed") or str(df.columns[0]).strip() == "" else low.get("name", low.get("substation", df.columns[0]))
    need = {"x": ("x", "lon", "longitude"), "y": ("y", "lat", "latitude"), "country": ("core-tso_country", "country"), "tso": ("core-tso_tso", "tso"),
            "osm_name": ("osm_name",), "comment": ("comments", "comment")}
    pick = {k: next((low[c] for c in cands if c in low), None) for k, cands in need.items()}
    if pick["x"] is None or pick["y"] is None:
        raise ValueError(f"longitude/latitude columns not found (columns: {list(df.columns)[:14]})")
    text = lambda key: df[pick[key]].fillna("").astype(str).str.strip() if pick[key] is not None else ""
    out = pd.DataFrame({"substation": df[name].fillna("").astype(str).str.strip(), "latitude": pd.to_numeric(df[pick["y"]], errors="coerce").round(5),
                        "longitude": pd.to_numeric(df[pick["x"]], errors="coerce").round(5), "country": text("country"), "tso": text("tso"),
                        "osm_name": text("osm_name"), "comment": text("comment")})
    if not isinstance(out["country"], str):
        out["country"] = out["country"].str.upper()
    out = out[(out["substation"] != "") & out["latitude"].between(34, 72) & out["longitude"].between(-25, 45)]
    return out.drop_duplicates(["substation", "country"]).reset_index(drop=True)[COORD_COLUMNS]


# ----------------------------------------------------------------------------- borders
def iso2(props: dict) -> str:
    """Two-letter country code of a Natural Earth feature. ISO_A2 is '-99' for France and Norway in several versions, so several properties are tried."""
    p = {str(k).lower(): v for k, v in props.items()}
    for key in ("iso_a2_eh", "iso_a2", "wb_a2"):
        v = str(p.get(key, "")).strip().upper()
        if len(v) == 2 and v.isalpha():
            return v
    for key in ("adm0_a3", "iso_a3_eh", "iso_a3", "sov_a3"):
        v = str(p.get(key, "")).strip().upper()
        if v in A3:
            return A3[v]
    return ""


def simplify(points: list, tol: float) -> list:
    """Douglas-Peucker: drop points that lie closer than tol (degrees) to the line between their neighbours; the ends stay."""
    if len(points) < 3:
        return list(points)
    keep = [False] * len(points)
    keep[0] = keep[-1] = True
    stack = [(0, len(points) - 1)]
    while stack:
        a, b = stack.pop()
        (x1, y1), (x2, y2) = points[a], points[b]
        dx, dy = x2 - x1, y2 - y1
        norm = (dx * dx + dy * dy) ** 0.5
        best, far = -1.0, None
        for i in range(a + 1, b):
            x, y = points[i]
            d = abs(dy * (x - x1) - dx * (y - y1)) / norm if norm else ((x - x1) ** 2 + (y - y1) ** 2) ** 0.5
            if d > best:
                best, far = d, i
        if far is not None and best > tol:
            keep[far] = True
            stack += [(a, far), (far, b)]
    return [p for p, k in zip(points, keep) if k]


def _area(ring: list) -> float:
    return abs(sum(x1 * y2 - x2 * y1 for (x1, y1), (x2, y2) in zip(ring, ring[1:]))) / 2


def borders_from_geojson(gj: dict, max_points: int = 4500, window: tuple = WINDOW, min_area: float = 0.02) -> pd.DataFrame:
    """Outer rings of the countries in the map window, simplified to a point budget (the Excel map draws every point with formulas).

    Kept: rings whose centre lies in the window; of each country the largest ring always, further rings (islands) from min_area (square degrees, about 150 km2).
    The tolerance of the simplification grows until the budget holds, so a finer source gives the same file size, only better shapes.
    """
    lo, hi, la, lb = window
    rings = []
    for feat in gj.get("features", []):
        code = iso2(feat.get("properties") or {})
        geom = feat.get("geometry") or {}
        polys = [geom.get("coordinates")] if geom.get("type") == "Polygon" else (geom.get("coordinates") or [] if geom.get("type") == "MultiPolygon" else [])
        own = []
        for poly in polys:
            if not poly or len(poly[0]) < 4:
                continue
            ring = [(float(p[0]), float(p[1])) for p in poly[0]]
            cx, cy = sum(p[0] for p in ring) / len(ring), sum(p[1] for p in ring) / len(ring)
            if lo <= cx <= hi and la <= cy <= lb and max(p[0] for p in ring) - min(p[0] for p in ring) <= 30:
                own.append(ring)
        if not code or not own:
            continue
        own.sort(key=_area, reverse=True)
        rings += [(code, r) for i, r in enumerate(own) if i == 0 or _area(r) >= min_area]
    if not rings:
        raise ValueError("no country ring inside the map window: is this the Natural Earth admin-0 countries file?")
    tol = 0.004
    while True:
        simple = []
        for code, r in rings:
            s = simplify(r, tol)
            if s[0] != s[-1]:
                s.append(s[0])
            simple.append((code, s if len(s) >= 4 else r[:1] + r[len(r) // 3:len(r) // 3 + 1] + r[2 * len(r) // 3:2 * len(r) // 3 + 1] + r[:1]))
        if sum(len(s) for _c, s in simple) <= max_points or tol > 0.5:
            break
        tol *= 1.35
    rows = [(code, i + 1, round(x, 4), round(y, 4)) for i, (code, s) in enumerate(simple) for x, y in s]
    return pd.DataFrame(rows, columns=BORDER_COLUMNS)
