"""Storage of the daily, monthly and log files (CSV, UTF-8, dot as decimal separator).

Layout: data/interim/daily/YYYY-MM-DD.csv.gz  one file per day, one row per network element and scenario.
A daily update only adds a new file - this keeps the Git history small.
"""
from __future__ import annotations

from datetime import date, timedelta
from pathlib import Path

import pandas as pd

from .aggregate import DAILY_COLUMNS, _TEXT_COLS

LOG_COLUMNS = ["day", "hours_expected", "hours_delivered", "rows_core", "status", "fetched_utc"]
_DTYPES = {c: str for c in _TEXT_COLS}


def _write_csv(df: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(path, index=False, lineterminator="\n", encoding="utf-8")


def _ensure_columns(df: pd.DataFrame) -> pd.DataFrame:
    """Older daily files without new columns get empty text / 0."""
    for c in DAILY_COLUMNS:
        if c not in df.columns:
            df[c] = "" if c in _TEXT_COLS else 0
    return df[DAILY_COLUMNS]


def read_daily(daily_dir) -> pd.DataFrame:
    """All daily files: one file per day (YYYY-MM-DD.csv.gz); older monthly files (YYYY-MM.csv) are still read, per-day files win on overlap."""
    d = Path(daily_dir)
    files = sorted(d.glob("????-??-??.csv.gz")) + sorted(d.glob("????-??.csv"))
    if not files:
        return pd.DataFrame(columns=DAILY_COLUMNS)
    parts = [_ensure_columns(pd.read_csv(f, dtype=_DTYPES, keep_default_na=False)) for f in files]
    return pd.concat(parts, ignore_index=True).drop_duplicates(["day", "scenario", "key"], keep="first").reset_index(drop=True)


def write_day(daily_dir, day: str, df: pd.DataFrame) -> Path:
    """Write the rows of one day into its own compressed file; existing rows of the same day and scenario are replaced.

    One file per day keeps the Git history small (a daily run only adds a new file) and the files small (about 100 KB per day for the whole Core region).
    The gzip header carries no time stamp, so an unchanged day gives byte-identical files.
    """
    path = Path(daily_dir) / f"{day}.csv.gz"
    if path.exists():
        old = _ensure_columns(pd.read_csv(path, dtype=_DTYPES, keep_default_na=False))
        scen = set(df["scenario"]) if not df.empty else set()
        df = pd.concat([old[~old["scenario"].isin(scen)], df], ignore_index=True)
    df = df[DAILY_COLUMNS].copy()
    for c, nd in (("fmax_mw", 3), ("util_sum", 6), ("util_max", 6), ("voltage_kv", 1), ("imax_a", 1)):
        df[c] = pd.to_numeric(df[c], errors="coerce").round(nd)
    path.parent.mkdir(parents=True, exist_ok=True)
    df.sort_values(["scenario", "key"]).to_csv(path, index=False, lineterminator="\n", encoding="utf-8", compression={"method": "gzip", "mtime": 0})
    return path


def read_log(path) -> pd.DataFrame:
    p = Path(path)
    if not p.exists():
        return pd.DataFrame(columns=LOG_COLUMNS)
    return pd.read_csv(p, dtype={"day": str, "status": str, "fetched_utc": str}, keep_default_na=False)


def update_log(path, entry: dict) -> None:
    log = read_log(path)
    log = log[log["day"] != entry["day"]]
    log = pd.concat([log, pd.DataFrame([entry])], ignore_index=True)[LOG_COLUMNS]
    _write_csv(log.sort_values("day"), Path(path))


def days_to_fetch(today: str, lookback_days: int, log: pd.DataFrame) -> list[str]:
    """Days of the last `lookback_days` days (up to and including today) that are not yet complete."""
    end = date.fromisoformat(today)
    # 'fallback' = JAO used the backup procedure (no domain data): do not try again
    complete = set(log.loc[log["status"].isin(["complete", "fallback"]), "day"]) if not log.empty else set()
    days = [(end - timedelta(days=i)).isoformat() for i in range(lookback_days, -1, -1)]
    return [d for d in days if d not in complete]
