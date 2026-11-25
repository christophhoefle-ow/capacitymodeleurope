#!/usr/bin/env python3
"""One-off: split older monthly daily files (data/interim/daily/YYYY-MM.csv) into one compressed file per day (YYYY-MM-DD.csv.gz)."""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd

import _common as common
from capmodel.storage import _DTYPES, _ensure_columns, write_day


def main(daily_dir: str | None = None) -> int:
    d = Path(daily_dir) if daily_dir else common.path(common.load_config(), "daily_dir")
    n_files = n_days = 0
    for f in sorted(d.glob("????-??.csv")):
        df = _ensure_columns(pd.read_csv(f, dtype=_DTYPES, keep_default_na=False))
        for day, g in df.groupby("day"):
            write_day(d, day, g)
            n_days += 1
        f.unlink()
        n_files += 1
    print(f"{n_files} monthly file(s) split into {n_days} daily file(s) in {d}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else None))
