"""Country reference data of the Core region for the map and for plausibility checks.

VIEW  : map window per country (lon_min, lon_max, lat_min, lat_max) used by the Excel map to zoom on the selected country ('All' = whole region).
BBOX  : generous bounding box of the country (a located substation must lie inside, otherwise its coordinate is rejected).
LABEL : position of the country code on the map.
"""
from __future__ import annotations

VIEW = {"All": (-5.6, 29.5, 41.8, 55.4), "AT": (9.3, 17.4, 46.2, 49.2), "BE": (2.4, 6.6, 49.4, 51.7), "CZ": (11.9, 19.0, 48.4, 51.2), "DE": (5.5, 15.5, 47.0, 55.2),
        "FR": (-5.4, 8.7, 41.9, 51.4), "HR": (13.3, 19.6, 42.2, 46.7), "HU": (15.8, 23.2, 45.6, 48.8), "LU": (5.6, 6.7, 49.3, 50.2), "NL": (3.0, 7.4, 50.6, 53.7),
        "PL": (13.9, 24.4, 49.0, 54.9), "RO": (20.0, 29.8, 43.4, 48.4), "SI": (13.3, 16.8, 45.3, 46.95), "SK": (16.7, 22.7, 47.6, 49.7)}
BBOX = {"AT": (9.5, 17.2, 46.3, 49.05), "BE": (2.5, 6.45, 49.45, 51.55), "CZ": (12.05, 18.9, 48.5, 51.1), "DE": (5.8, 15.1, 47.2, 55.1), "FR": (-5.2, 8.3, 41.3, 51.2),
        "HR": (13.4, 19.5, 42.35, 46.6), "HU": (16.1, 22.95, 45.7, 48.6), "LU": (5.7, 6.6, 49.4, 50.2), "NL": (3.3, 7.25, 50.7, 53.6), "PL": (14.1, 24.2, 49.0, 54.9),
        "RO": (20.2, 29.8, 43.6, 48.3), "SI": (13.3, 16.65, 45.4, 46.9), "SK": (16.8, 22.6, 47.7, 49.65), "CH": (5.9, 10.6, 45.8, 47.85), "DK": (8.0, 15.2, 54.5, 57.8),
        "RS": (18.8, 23.1, 42.2, 46.2), "UA": (22.0, 40.3, 44.3, 52.4), "BA": (15.7, 19.7, 42.5, 45.3), "NO": (4.0, 31.5, 57.5, 71.5)}
LABEL = {"AT": (14.0, 47.5), "BE": (4.6, 50.6), "CZ": (15.5, 49.8), "DE": (10.3, 51.1), "FR": (2.4, 46.7), "HR": (16.0, 45.2), "HU": (19.3, 47.2), "LU": (6.1, 49.75),
         "NL": (5.5, 52.3), "PL": (19.5, 52.0), "RO": (25.0, 45.9), "SI": (14.8, 46.1), "SK": (19.6, 48.75)}
# Additional zoom windows of the map (name: lon_min, lon_max, lat_min, lat_max). Add a row to get a new entry in the zoom list of the sheet Map.
REGIONS = {"DE North-West": (6.2, 10.9, 52.1, 55.1), "DE Rhine-Ruhr": (5.9, 8.9, 50.4, 52.2), "DE South-West": (6.8, 10.7, 47.4, 50.3),
           "DE South-East": (9.6, 13.9, 47.2, 50.6), "DE East": (10.3, 15.1, 50.2, 54.7), "Upper Rhine": (7.2, 9.7, 48.3, 50.1),
           "Emsland": (6.5, 8.9, 52.1, 53.8), "Benelux": (2.4, 7.3, 49.4, 53.6)}
FOUND = "Found substation"                 # zoom entry: window around the substation chosen in the sheet Map
FOUND_HALF = (2.3, 1.25)                   # half width (degrees of longitude) and half height (degrees of latitude) of that window
MARGIN = 0.15


def inside(country: str, lat: float, lon: float, margin: float = MARGIN) -> bool:
    """True if the coordinate lies inside the (generous) bounding box of the country; unknown countries are not checked."""
    if country not in BBOX:
        return True
    lo, hi, la, lb = BBOX[country]
    return lo - margin <= lon <= hi + margin and la - margin <= lat <= lb + margin
