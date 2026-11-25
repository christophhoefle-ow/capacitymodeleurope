#!/usr/bin/env python3
"""Fetch JAO utilization data (all Core TSOs) and store it aggregated per day.

Examples
--------
Automatic operation (missing days of the last 7 days up to today):
    python scripts/fetch_jao.py
Catch up a period (this is where start and end date are set):
    python scripts/fetch_jao.py --from 2026-11-01 --to 2026-11-15
Only show what would happen:
    python scripts/fetch_jao.py --dry-run
Note: large catch-up runs (several months) should be agreed with JAO first and run outside the publication window
(morning, about 09-11 CET). Scenario (base case / worst case), TSOs and thresholds: config/config.yml.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timezone

import _common as common
from capmodel.aggregate import daily_aggregate
from capmodel.jao_client import JaoClient, JaoError
from capmodel.storage import days_to_fetch, read_log, update_log, write_day
from capmodel.timeutil import day_range, today_local

log = logging.getLogger("fetch_jao")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="first", help="first day (YYYY-MM-DD); default: automatic")
    ap.add_argument("--to", dest="last", help="last day (YYYY-MM-DD); default: today")
    ap.add_argument("--force", action="store_true", help="fetch complete days again")
    ap.add_argument("--max-days", type=int, default=31, help="protection against accidentally huge runs")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("-v", "--verbose", action="store_true")
    args = ap.parse_args()
    common.setup_logging(args.verbose)
    cfg = common.load_config()
    jao, ev, tsos = cfg["jao"], cfg["evaluation"], cfg["region"]["tsos"]
    daily_dir, log_path = common.path(cfg, "daily_dir"), common.path(cfg, "fetch_log")
    today = today_local(ev["timezone"])
    if args.first:
        days = day_range(args.first, args.last or today)
        if not args.force:
            done = read_log(log_path)
            complete = set(done.loc[done["status"] == "complete", "day"]) if not done.empty else set()
            days = [d for d in days if d not in complete]
    else:
        days = days_to_fetch(today, int(ev["lookback_days"]), read_log(log_path))
    if len(days) > args.max_days:
        log.error("%d days requested, %d allowed (--max-days). Abort.", len(days), args.max_days)
        return 2
    log.info("Days to process: %s | scenario: %s | TSOs: %d", ", ".join(days) if days else "none", ev["scenario"], len(tsos))
    if args.dry_run or not days:
        return 0
    base_url = os.environ.get("JAO_BASE_URL", jao["base_url"])    # override e.g. for tests
    client = JaoClient(base_url, jao["dataset"], jao["pause_seconds"], jao["timeout_seconds"], jao["max_retries"], jao["take"],
                       token=os.environ.get("JAO_API_TOKEN") or None)
    errors = 0
    for day in days:
        now = lambda: datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        try:
            if jao.get("require_monitoring_received", True):
                status = client.monitoring_status(day)
                if status == "fallback":
                    log.info("%s: JAO reports Spanning/DFP (backup procedure) - no domain data, not retried", day)
                    update_log(log_path, {"day": day, "hours_expected": "", "hours_delivered": 0, "rows_core": 0, "status": "fallback", "fetched_utc": now()})
                    continue
                if status in ("expected", "pending"):
                    log.info("%s: JAO reports '%s' - will be retried in the next run", day, status)
                    update_log(log_path, {"day": day, "hours_expected": "", "hours_delivered": 0, "rows_core": 0, "status": "waiting", "fetched_utc": now()})
                    continue
            frame, n_expected, n_hours = client.fetch_day(day, tsos, ev["timezone"])
            agg = daily_aggregate(frame, day, ev["util_high"], ev["util_overload"], ev["scenario"])
            if not agg.empty:
                write_day(daily_dir, day, agg)
            status = "complete" if (n_hours == n_expected and not agg.empty) else "incomplete"
            update_log(log_path, {"day": day, "hours_expected": n_expected, "hours_delivered": n_hours, "rows_core": len(frame), "status": status, "fetched_utc": now()})
            log.info("%s: %s (%d/%d hours, %d Core rows, %d network elements)", day, status, n_hours, n_expected, len(frame), len(agg))
        except JaoError as exc:
            errors += 1
            log.error("%s: fetch failed: %s", day, exc)
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
