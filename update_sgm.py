#!/usr/bin/env python3
"""Adopt a new release of the JAO Core Static Grid Model automatically (no manual download).

JAO publishes the model twice a year as a ZIP on https://www.jao.eu/static-grid-model. This script
  1. finds the newest release on that page and compares it with data/manual/sgm_release.txt,
  2. downloads the ZIP and takes the workbook of the model,
  3. reads it into data/static (scripts/ingest_sgm.py) and checks it (scripts/validate_sgm.py),
  4. compares it with the release in use: lines, transformers, substations and TSOs must not shrink by more than 10 %, no TSO may disappear,
  5. rebuilds the delivery files and the substation locations.
If a check fails, the previous files are put back and the script ends with exit code 3: nothing changes and the GitHub action opens an issue.
A summary for the log and the issue is written to data/manual/sgm_update_report.txt.

  python scripts/update_sgm.py                                    # adopt the newest release if it is newer than the one in use
  python scripts/update_sgm.py --force                            # adopt it again
  python scripts/update_sgm.py --zip FILE --label "202609, release 10"   # use a ZIP that is already on disk
"""
from __future__ import annotations

import argparse
import io
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

import pandas as pd
import requests

import _common as common
import check_sgm_release as rel
from capmodel.sgm import node_key
from validate_sgm import validate

STATIC = ("sgm_lines_core.csv", "sgm_transformers_core.csv")
MIN_SHARE = 0.90


def pick_workbook(names: list[str]) -> str | None:
    """The model workbook inside the ZIP: an .xlsx whose name mentions the grid model; documentation and internal versions are skipped."""
    xlsx = [n for n in names if n.lower().endswith(".xlsx") and not n.rsplit("/", 1)[-1].startswith("~$")]
    good = [n for n in xlsx if "static" in n.lower() or "grid" in n.lower() or "sgm" in n.lower()]
    good = [n for n in good if "internal" not in n.lower()] or good
    return (sorted(good, key=len) or sorted(xlsx, key=len) or [None])[0]


def counts(static: Path) -> dict:
    """Size of the extract in data/static: lines, transformers, substations (spelling-independent) and the set of TSOs."""
    if not all((static / f).exists() for f in STATIC):
        return {"lines": 0, "transformers": 0, "substations": 0, "tsos": set()}
    ln = pd.read_csv(static / STATIC[0], dtype=str, keep_default_na=False)
    tr = pd.read_csv(static / STATIC[1], dtype=str, keep_default_na=False)
    nodes = {node_key(x) for x in list(ln["substation_1"]) + list(ln["substation_2"]) + list(tr["substation"]) if x}
    return {"lines": len(ln), "transformers": len(tr), "substations": len(nodes), "tsos": set(ln["tso"]) | set(tr["tso"])}


def plausible(old: dict, new: dict) -> list[str]:
    """Reasons not to adopt the new release (empty list = fine)."""
    problems = [f"{k}: {new[k]} in the new release, {old[k]} in use (more than 10 % fewer)" for k in ("lines", "transformers", "substations") if old[k] and new[k] < MIN_SHARE * old[k]]
    gone = sorted(old["tsos"] - new["tsos"])
    if gone:
        problems.append(f"TSOs missing in the new release: {gone}")
    if not new["lines"]:
        problems.append("the new release contains no lines")
    return problems


def run(script: str, *args: str) -> None:
    subprocess.run([sys.executable, str(common.ROOT / "scripts" / script), *args], check=True)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="adopt the newest release even if it is already in use")
    ap.add_argument("--zip", help="ZIP file on disk (no download)")
    ap.add_argument("--label", help="release label for --zip, e.g. '202609, release 10'")
    args = ap.parse_args()
    common.setup_logging()
    static, manual = common.ROOT / "data" / "static", common.ROOT / "data" / "manual"
    report = manual / "sgm_update_report.txt"
    if args.zip:
        data, label = Path(args.zip).read_bytes(), args.label or Path(args.zip).stem
    else:
        latest = rel.find_latest_release(requests.get(rel.SGM_PAGE, timeout=60, headers={"User-Agent": "capacity-model-pipeline/0.3"}).text)
        if latest is None:
            report.write_text("No release file found on the JAO page: has the page changed?\n", encoding="utf-8")
            print(report.read_text(encoding="utf-8"))
            return 3
        known_file = manual / "sgm_release.txt"
        known = rel.parse_label(known_file.read_text(encoding="utf-8")) if known_file.exists() else None
        if known is not None and latest["release"] <= known and not args.force:
            print(f"up to date: release {known} is in use, newest on the JAO page is {latest['label']}")
            return 0
        label = latest["label"]
        r = requests.get(latest["url"], timeout=300, headers={"User-Agent": "capacity-model-pipeline/0.3"})
        r.raise_for_status()
        data = r.content
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            name = pick_workbook(z.namelist())
            if name is None:
                report.write_text(f"Release {label}: no Excel workbook in the ZIP ({z.namelist()[:10]})\n", encoding="utf-8")
                print(report.read_text(encoding="utf-8"))
                return 3
            book = tmp / Path(name).name
            book.write_bytes(z.read(name))
        backup = tmp / "backup"
        backup.mkdir()
        for f in [static / n for n in STATIC] + [manual / "sgm_release.txt"]:
            if f.exists():
                shutil.copy(f, backup / f.name)
        old = counts(static)
        problems = []
        try:
            run("ingest_sgm.py", str(book), "--release", label)
            ln = pd.read_csv(static / STATIC[0], dtype=str, keep_default_na=False)
            tr = pd.read_csv(static / STATIC[1], dtype=str, keep_default_na=False)
            errors, warnings = validate(ln, tr)
            problems += [f"validation: {e}" for e in errors]
            new = counts(static)
            problems += plausible(old, new)
        except Exception as exc:                                       # noqa: BLE001 - any failure of the import counts as 'do not adopt'
            problems.append(f"import failed: {exc.__class__.__name__}: {exc}")
            new, warnings = {"lines": 0, "transformers": 0, "substations": 0, "tsos": set()}, []
        if problems:
            for f in backup.iterdir():
                shutil.copy(f, (manual if f.name == "sgm_release.txt" else static) / f.name)
            report.write_text(f"Release {label} was NOT adopted, the release in use stays:\n" + "\n".join(f"- {p}" for p in problems) + "\n", encoding="utf-8")
            print(report.read_text(encoding="utf-8"))
            return 3
    run("build_processed.py")
    run("estimate_coordinates.py")
    lines = [f"Release {label} adopted automatically.",
             f"- lines {old['lines']} -> {new['lines']}, transformers {old['transformers']} -> {new['transformers']}, substations {old['substations']} -> {new['substations']}, TSOs {len(new['tsos'])}"]
    lines += [f"- note: {w}" for w in warnings]
    lines.append("- to review when convenient: data/manual/coordinates_report.csv (new substations without an exact position), python scripts/suggest_aliases.py (renamed elements)")
    report.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(report.read_text(encoding="utf-8"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
