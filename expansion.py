"""Grid expansion layer: planned and under-construction transmission projects (BBPlG, north-south HVDC corridors).

Why: JAO publishes only lines in operation, so planned projects (SuedLink, Ventilus, cross-border interconnectors ...) are not visible in the utilization data.
One table for all of Europe (data/static/grid_expansion_projects.csv): national projects, cross-border interconnectors and offshore connections, each with countries, scope, status, source and date.
Sources by tier: ENTSO-E TYNDP and the EU list of PCI/PMI (all countries), national plans for detail (BNetzA, Elia, TenneT, RTE, PSE, APG ...). The section table (grid_expansion_sections.csv)
holds construction progress where a TSO publishes it. Coordinates are approximate places, lines are schematic.
"""
from __future__ import annotations

import pandas as pd

PROJECT_COLUMNS = ["project_id", "plan_id", "name", "corridor", "type", "tsos", "from_name", "from_lat", "from_lon", "to_name", "to_lat", "to_lon",
                   "link_from", "link_to", "capacity_mw", "voltage_kv", "length_km", "built_km", "status", "planned_year", "commissioning_note",
                   "as_of", "source_url", "remark", "countries", "scope", "plan_source"]
SECTION_COLUMNS = ["project_id", "section", "description", "length_km", "built_km", "tso", "state", "construction_start", "status_text", "as_of"]
STATUSES = ("Under construction", "Permitting", "Planning", "Listed", "In operation")      # Listed: named in a European plan (TYNDP, PCI list), stage not verified
SCOPES = ("national", "cross-border", "offshore")


def validate(projects: pd.DataFrame, sections: pd.DataFrame, substations=None):
    """Return (errors, warnings). Errors: missing columns, unknown status, coordinates outside Germany, built > length."""
    errors, warnings = [], []
    for name, df, cols in (("projects", projects, PROJECT_COLUMNS), ("sections", sections, SECTION_COLUMNS)):
        miss = [c for c in cols if c not in df.columns]
        if miss:
            errors.append(f"{name}: columns missing {miss}")
    if errors:
        return errors, warnings
    if projects["project_id"].duplicated().any():
        errors.append("projects: duplicate project_id")
    bad = sorted(set(projects["status"]) - set(STATUSES))
    if bad:
        errors.append(f"projects: unknown status {bad}")
    for c in ("from_lat", "to_lat"):
        v = pd.to_numeric(projects[c], errors="coerce")
        if ((v < 40) | (v > 60) | v.isna()).any():
            errors.append(f"projects: {c} outside 40-60 N")
    for c in ("from_lon", "to_lon"):
        v = pd.to_numeric(projects[c], errors="coerce")
        if ((v < -10) | (v > 35) | v.isna()).any():
            errors.append(f"projects: {c} outside 10 W to 35 E")
    bad_scope = sorted(set(projects["scope"]) - set(SCOPES))
    if bad_scope:
        errors.append(f"projects: unknown scope {bad_scope}")
    if (projects["countries"] == "").any():
        errors.append("projects: countries missing")
    length = pd.to_numeric(projects["length_km"].replace("", pd.NA), errors="coerce")
    built = pd.to_numeric(projects["built_km"].replace("", pd.NA), errors="coerce")
    if (built > length).any():
        errors.append("projects: built_km larger than length_km")
    sl = pd.to_numeric(sections["length_km"].replace("", pd.NA), errors="coerce")
    sb = pd.to_numeric(sections["built_km"].replace("", pd.NA), errors="coerce")
    if (sb > sl).any():
        errors.append("sections: built_km larger than length_km")
    for pid, g in sections.groupby("project_id"):
        row = projects[projects["project_id"] == pid]
        if row.empty:
            errors.append(f"sections: unknown project {pid}")
            continue
        pl, pb = pd.to_numeric(row["length_km"].iloc[0] or None, errors="coerce"), pd.to_numeric(row["built_km"].iloc[0] or None, errors="coerce")
        if pd.notna(pl) and abs(pd.to_numeric(g["length_km"], errors="coerce").sum() - pl) > 1.5:
            warnings.append(f"{pid}: section lengths ({pd.to_numeric(g['length_km'], errors='coerce').sum():.0f} km) differ from project length ({pl:.0f} km)")
        if pd.notna(pb) and abs(pd.to_numeric(g["built_km"], errors="coerce").sum() - pb) > 1.5:
            warnings.append(f"{pid}: built km of the sections differ from the project figure")
    if substations is not None:
        names = set(substations)
        for c in ("link_from", "link_to"):
            miss = sorted({v for v in projects[c] if v and v not in names})
            if miss:
                warnings.append(f"projects: {c} not found in master_substations: {miss}")
    return errors, warnings
