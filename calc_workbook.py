#!/usr/bin/env python3
"""Calculate the formulas of a workbook with LibreOffice and store the values in the file.

Why: the generator writes formulas without results. Excel calculates when it opens the file, but previews, Protected View and tools that read the file
(Power Automate, Python, SharePoint preview) only see stored values. LibreOffice calculates a copy; only its values are copied into the original file,
so connections and charts stay untouched.

  python scripts/calc_workbook.py build/Capacity_Model_Core.xlsx          # in place
Needs LibreOffice (soffice) on the PATH, e.g. sudo apt-get install libreoffice-calc.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main(path: str) -> int:
    src = Path(path).resolve()
    if shutil.which("soffice") is None:
        print("soffice not found: install LibreOffice (libreoffice-calc)")
        return 2
    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)
        work = tmp / "in" / src.name
        work.parent.mkdir()
        shutil.copy(src, work)
        out = tmp / "out"
        out.mkdir()
        subprocess.run(["soffice", "--headless", "--norestore", f"-env:UserInstallation=file://{tmp}/profile", "--convert-to", "xlsx:Calc MS Excel 2007 XML",
                        "--outdir", str(out), str(work)], check=True, timeout=3000, capture_output=True)
        calc = out / src.name
        if not calc.exists():
            print("LibreOffice produced no file")
            return 1
        merged = tmp / "merged.xlsx"
        subprocess.run([sys.executable, str(HERE / "add_cached_values.py"), str(src), str(calc), str(merged)], check=True)
        shutil.copy(merged, src)
    print(f"values stored in {src}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1]))
