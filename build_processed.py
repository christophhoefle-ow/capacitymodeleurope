#!/usr/bin/env python3
"""Create the Excel delivery files (data/processed/) from the daily files and the static master data.

Results (one CSV per landing sheet of the Excel model):
    master_lines.csv, master_transformers.csv, master_substations.csv   -> D_Lines, D_Transformers, D_Substations
    utilization_monthly.csv                                             -> D_Utilization
    grid_connection_tso.csv, occupancy_mastr.csv (headers only, phase 2) -> D_Connection, D_Occupancy
    meta.csv                                                            -> D_Meta
The master data = German SGM extract (data/static, complete network incl. elements without JAO data)
                + every other JAO element seen in the data (all Core countries; source 'JAO').
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone

import pandas as pd

import _common as common
from capmodel import __version__, connection
from capmodel.expansion import validate as validate_expansion
from capmodel.mapping import (MONTHLY_COLUMNS, apply_canonical, apply_substation_aliases, build_mapping, canonical_names, derive_substations, jao_master, latest_attributes, monthly_from_daily,
                              sgm_elements, sgm_master, split_homonyms)
from capmodel.storage import read_daily, read_log

log = logging.getLogger("build_processed")
SCHEMA_VERSION = "1"          # version of the CSV delivery contract (docs/DATA_CONTRACT.md); the Excel model checks it
H_CONNECTION = connection.COLUMNS
H_OCCUPANCY = ["substation", "occupied_feed_in_mw", "occupied_load_mw", "requested_feed_in_mw", "requested_load_mw", "as_of", "source"]


def _csv(df: pd.DataFrame, path) -> None:
    df.to_csv(path, index=False, lineterminator="\n", encoding="utf-8")


def main() -> int:
    common.setup_logging()
    cfg = common.load_config()
    ev, region = cfg["evaluation"], cfg["region"]
    proc, static, manual = common.path(cfg, "processed_dir"), common.ROOT / "data" / "static", common.ROOT / "data" / "manual"
    daily_all = read_daily(common.path(cfg, "daily_dir"))
    daily = daily_all[daily_all["scenario"] == ev["scenario"]]
    def read_static(pattern):
        files = sorted(f for f in static.glob(pattern) if not f.stem.endswith("_raw"))
        return pd.concat([pd.read_csv(f, dtype=str, keep_default_na=False) for f in files], ignore_index=True)

    # every file data/static/sgm_lines_<country or group>.csv (and sgm_transformers_*.csv) is part of the master data: drop in the extract of another country and it is used
    lines_sgm, trafos_sgm = sgm_master(read_static("sgm_lines_*.csv"), read_static("sgm_transformers_*.csv"))
    alias_file = manual / "alias_jao_sgm.csv"
    alias = pd.read_csv(alias_file, dtype=str, keep_default_na=False) if alias_file.exists() else None
    sgm = sgm_elements(lines_sgm, trafos_sgm)
    monthly = monthly_from_daily(daily, sgm, alias)
    mapping = build_mapping(daily, sgm, alias) if not daily.empty else pd.DataFrame(columns=["key", "jao_key", "match"])
    unmatched = set(mapping.loc[mapping["match"] == "unmatched", "jao_key"])
    attrs = latest_attributes(daily) if not daily.empty else daily
    jl, jt = jao_master(attrs[attrs["key"].isin(unmatched)]) if not daily.empty else (lines_sgm.iloc[0:0], trafos_sgm.iloc[0:0])
    jl = jl.sort_values(["country", "tso", "element_name"], key=lambda s: s.str.casefold()) if len(jl) else jl
    jt = jt.sort_values(["country", "tso", "element_name"], key=lambda s: s.str.casefold()) if len(jt) else jt
    lines, trafos = pd.concat([lines_sgm, jl], ignore_index=True), pd.concat([trafos_sgm, jt], ignore_index=True)
    sub_alias_file = manual / "substation_aliases.csv"
    sub_alias = pd.read_csv(sub_alias_file, dtype=str, keep_default_na=False) if sub_alias_file.exists() else None
    lines, trafos, n_alias = apply_substation_aliases(lines, trafos, sub_alias)        # typing variants of a name ('Herbentingen' = 'Herbertingen')
    lines, trafos, homonyms = split_homonyms(lines, trafos)                             # one node per site ('St. Peter (AT)' and 'St. Peter (DE)')
    for name, cc, k in homonyms:
        log.info("homonym split: %s (%s), %d elements", name, cc, k)
    lines, trafos = apply_canonical(lines, trafos, canonical_names(lines, trafos))      # one spelling per substation (Röhrsdorf = Roehrsdorf)
    subs = derive_substations(lines, trafos)
    _csv(lines, proc / "master_lines.csv")
    _csv(trafos, proc / "master_transformers.csv")
    _csv(subs, proc / "master_substations.csv")
    _csv(monthly, proc / "utilization_monthly.csv")
    exp_p = pd.read_csv(static / "grid_expansion_projects.csv", dtype=str, keep_default_na=False)
    exp_s = pd.read_csv(static / "grid_expansion_sections.csv", dtype=str, keep_default_na=False)
    exp_err, exp_warn = validate_expansion(exp_p, exp_s, subs["substation"])
    for w in exp_warn:
        log.warning("grid expansion: %s", w)
    if exp_err:
        raise SystemExit("grid expansion data invalid: " + "; ".join(exp_err))
    _csv(exp_p, proc / "grid_expansion.csv")
    _csv(exp_s, proc / "grid_expansion_sections.csv")
    # free connection capacity per substation: harvested automatically from the publications of the TSOs (scripts/fetch_connection_capacity.py ->
    # data/interim/connection/<source>.csv). Rows of data/manual/grid_connection_tso.csv, if any, come first and therefore win (corrections, operators without adapter).
    conn_dir = common.ROOT / "data" / "interim" / "connection"
    conn_files = [manual / "grid_connection_tso.csv"] + sorted(f for f in conn_dir.glob("*.csv") if f.name != "status.csv")
    conn_parts = [pd.read_csv(f, dtype=str, keep_default_na=False) for f in conn_files if f.exists()]
    conn_in = pd.concat(conn_parts, ignore_index=True) if conn_parts else pd.DataFrame(columns=H_CONNECTION)
    conn_out, conn_report = connection.normalise(conn_in, subs, {k.upper(): v for k, v in region["tsos"].items()})
    for name, finding in conn_report:
        log.warning("connection capacity: %s: %s", name, finding)
    _csv(conn_out, proc / "grid_connection_tso.csv")
    _csv(pd.DataFrame(conn_report, columns=["substation", "finding"]), manual / "grid_connection_report.csv")
    conn_status = pd.read_csv(conn_dir / "status.csv", dtype=str, keep_default_na=False) if (conn_dir / "status.csv").exists() else pd.DataFrame()
    conn_sources = "; ".join(f"{r.tso}: {r.rows} substations as of {r.as_of} ({r.status})" for r in conn_status.itertuples()) or "none"
    if not (proc / "occupancy_mastr.csv").exists():
        _csv(pd.DataFrame(columns=H_OCCUPANCY), proc / "occupancy_mastr.csv")
    log.info("master: %d lines (%d from JAO), %d transformers (%d from JAO), %d substations; utilization: %d rows, %d months",
             len(lines), len(jl), len(trafos), len(jt), len(subs), len(monthly), monthly["month"].nunique() if len(monthly) else 0)

    fetch_log = read_log(common.path(cfg, "fetch_log"))
    n_complete = int((fetch_log["status"] == "complete").sum()) if not fetch_log.empty else 0
    release = (manual / "sgm_release.txt").read_text(encoding="utf-8").strip() if (manual / "sgm_release.txt").exists() else "unknown"
    match = monthly["match"].value_counts().to_dict() if not monthly.empty else {}
    countries = sorted(daily["country"].unique()) if not daily.empty else []
    meta = [
        ("created_utc", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")),
        ("pipeline_version", __version__),
        ("git_commit", os.environ.get("GITHUB_SHA", "local")[:7]),
        ("region", region["name"]),
        ("scenario", ev["scenario"]),
        ("tsos_configured", len(region["tsos"])),
        ("countries_configured", len(set(region["tsos"].values()))),
        ("countries_in_data", ", ".join(countries)),
        ("data_from_day", daily["day"].min() if not daily.empty else ""),
        ("data_to_day", daily["day"].max() if not daily.empty else ""),
        ("days_with_data", daily["day"].nunique() if not daily.empty else 0),
        ("days_complete", n_complete),
        ("sgm_release", release),
        ("util_high", ev["util_high"]),
        ("util_overload", ev["util_overload"]),
        ("jao_dataset", cfg["jao"]["dataset"]),
        ("schema_version", SCHEMA_VERSION),
        ("expansion_projects", len(exp_p)),
        ("expansion_as_of", exp_p["as_of"].max()),
        ("match_alias", match.get("alias", 0)),
        ("match_eic", match.get("EIC", 0)),
        ("match_name", match.get("name", 0)),
        ("match_substations", match.get("substations", 0)),
        ("match_unmatched", match.get("unmatched", 0)),
        ("connection_sources", conn_sources),
        ("connection_rows", len(conn_out)),
        ("connection_findings", len(conn_report)),
        ("homonyms_split", len({n for n, _c, _k in homonyms})),
        ("substation_aliases_applied", n_alias),
    ]
    extra = manual / "meta_note.txt"
    if extra.exists() and n_complete == 0:      # the example note disappears as soon as the first complete day is loaded
        meta.append(("note", extra.read_text(encoding="utf-8").strip()))
    _csv(pd.DataFrame(meta, columns=["key", "value"]), proc / "meta.csv")
    log.info("meta.csv written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
