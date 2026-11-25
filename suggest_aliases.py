#!/usr/bin/env python3
"""Suggest matches for JAO elements without SGM partner -> data/manual/alias_suggestions.csv (a working aid only!).

Similar names can be different elements (e.g. east / west strand). Confirmed pairs go to data/manual/alias_jao_sgm.csv
(columns: jao_key, sgm_key, remark); suggestions are NEVER applied automatically.
"""
from __future__ import annotations

import difflib
import sys

import pandas as pd

import _common as common
from capmodel.mapping import sgm_elements
from capmodel.normalize import name_key


def main() -> int:
    proc, static = common.ROOT / "data" / "processed", common.ROOT / "data" / "static"
    mon = pd.read_csv(proc / "utilization_monthly.csv", dtype=str, keep_default_na=False)
    sgm = sgm_elements(pd.read_csv(static / "sgm_lines_de.csv", dtype=str, keep_default_na=False),
                       pd.read_csv(static / "sgm_transformers_de.csv", dtype=str, keep_default_na=False))
    german = {"50HERTZ", "AMPRION", "TENNETGMBH", "TRANSNETBW"}
    open_ = mon[(mon["match"] == "unmatched") & mon["tso"].isin(german)].drop_duplicates("key")
    names = {name_key(n): (k, n) for k, n in zip(sgm["sgm_key"], sgm["name"])}
    rows = []
    for _, r in open_.iterrows():
        best = difflib.get_close_matches(name_key(r["element"]), list(names), n=1, cutoff=0.6)
        sk, sname = names[best[0]] if best else ("", "")
        score = round(difflib.SequenceMatcher(None, name_key(r["element"]), best[0]).ratio(), 2) if best else 0
        rows.append((r["key"], r["element"], r["tso"], r["util_max"], sk, sname, score))
    out = pd.DataFrame(rows, columns=["jao_key", "jao_name", "tso", "util_max", "suggested_sgm_key", "suggested_sgm_name", "similarity"])
    out.sort_values("similarity", ascending=False).to_csv(common.ROOT / "data" / "manual" / "alias_suggestions.csv", index=False, lineterminator="\n", encoding="utf-8")
    print(f"{len(out)} German JAO elements without SGM partner; suggestions written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
