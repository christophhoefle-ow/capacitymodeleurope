"""Free connection capacity per substation, as published by the TSOs.

Background: since the reform of the EU electricity market rules (Regulation (EU) 2019/943, Article 50(4a), as amended in 2024) every TSO has to publish the capacity
available for new connections with high spatial granularity and to update it at least monthly. The publications differ per operator: a table with MW classes
(50Hertz), free switch bays (Amprion), a map with a status (TenneT, TransnetBW). ENTSO-E and DSO Entity keep the directory of these publications (Capacitypedia).
None of the German TSOs offers an interface, so the values are maintained by hand in data/manual/grid_connection_tso.csv and checked here.

Two ways to fill a row:
  * MW ranges: feed_in_free_from_mw / feed_in_free_to_mw and load_free_from_mw / load_free_to_mw ('below 500 MW' = 0 to 500, 'above 2000 MW' = 2000 to 2000)
  * no MW published: connection_status = available | limited | none; status_feed_in / status_load if the operator tells the directions apart
"""
from __future__ import annotations

import pandas as pd

from .sgm import base_key, node_key

COLUMNS = ["substation", "tso", "voltage_level", "feed_in_free_from_mw", "feed_in_free_to_mw", "load_free_from_mw", "load_free_to_mw",
           "available_from_year", "as_of", "source_url", "remark", "connection_status", "status_feed_in", "status_load"]
STATUS_COLUMNS = ["connection_status", "status_feed_in", "status_load"]      # general status; the two others override it for one direction (feed-in, load)
NUMERIC = ["feed_in_free_from_mw", "feed_in_free_to_mw", "load_free_from_mw", "load_free_to_mw", "available_from_year"]
STATUSES = ("", "available", "limited", "none")


def normalise(df: pd.DataFrame, substations: pd.DataFrame, tso_country: dict | None = None):
    """Check the hand-maintained table and write the substation names the way the model spells them.

    Returns (table in the column order of the data contract, report rows [(substation, finding)]). A row whose name is not found stays in the table
    (the sheet Checks counts it), so nothing typed in is lost silently.
    """
    report: list[tuple[str, str]] = []
    df = df.copy()
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = ""
    df = df[COLUMNS].astype(str).apply(lambda s: s.str.strip())
    df = df[df["substation"] != ""].reset_index(drop=True)
    for col in STATUS_COLUMNS:
        df[col] = df[col].str.lower()
        bad = ~df[col].isin(STATUSES)
        for n, v in zip(df.loc[bad, "substation"], df.loc[bad, col]):
            report.append((n, f"unknown {col} {v!r} (allowed: available, limited, none): status removed"))
        df.loc[bad, col] = ""
    for c in NUMERIC:
        num = pd.to_numeric(df[c].replace("", pd.NA), errors="coerce")
        wrong = num.isna() & (df[c] != "")
        for n, v in zip(df.loc[wrong, "substation"], df.loc[wrong, c]):
            report.append((n, f"{c}: {v!r} is not a number: value removed"))
        df.loc[wrong, c] = ""
    for lo, hi in (("feed_in_free_from_mw", "feed_in_free_to_mw"), ("load_free_from_mw", "load_free_to_mw")):
        a, b = pd.to_numeric(df[lo].replace("", pd.NA), errors="coerce"), pd.to_numeric(df[hi].replace("", pd.NA), errors="coerce")
        for n in df.loc[(a > b).fillna(False), "substation"]:
            report.append((n, f"{lo} is larger than {hi}: check the range"))
        for n in df.loc[a.isna() != b.isna(), "substation"]:
            report.append((n, f"only one of {lo} and {hi} is filled: the model needs both bounds of the range"))
    # names as the model spells them: same name key; a name used in two countries is told apart by the country of the TSO
    exact = {node_key(s): s for s in substations["substation"]}
    by_base: dict[str, list[tuple[str, str]]] = {}
    for s, c in zip(substations["substation"], substations["country"]):
        by_base.setdefault(base_key(s), []).append((s, c))
    names = []
    for n, tso in zip(df["substation"], df["tso"]):
        hit = exact.get(node_key(n))
        if hit is None:
            cands = by_base.get(base_key(n), [])
            cc = (tso_country or {}).get(tso.upper(), "")
            same = [s for s, c in cands if c == cc]
            hit = same[0] if len(same) == 1 else (cands[0][0] if len(cands) == 1 else None)
        if hit is None:
            report.append((n, "no substation of this name in the model (check the spelling against the sheet Substations): row has no effect"))
        names.append(hit or n)
    df["substation"] = names
    # a substation listed twice (two operators share it, or a correction by hand): the row that says more wins (capacities in MW), otherwise the first one
    df["_info"] = sum((df[c] != "").astype(int) for c in ("feed_in_free_from_mw", "feed_in_free_to_mw", "load_free_from_mw", "load_free_to_mw"))
    df["_order"] = range(len(df))
    best = df.sort_values(["_info", "_order"], ascending=[False, True]).drop_duplicates("substation").index
    for n, t in zip(df.loc[~df.index.isin(best), "substation"], df.loc[~df.index.isin(best), "tso"]):
        report.append((n, f"listed more than once: the row of {t} is not used (the row with capacities in MW, otherwise the first one, counts)"))
    return df.loc[sorted(best), COLUMNS].reset_index(drop=True), report
