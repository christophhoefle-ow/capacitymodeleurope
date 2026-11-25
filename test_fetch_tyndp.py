"""Tests: structure report of the TYNDP download."""
import io
import zipfile

import pandas as pd

from fetch_tyndp import describe_zip


def test_describe_zip_reports_csv_and_excel_tables_and_other_files():
    buf = io.BytesIO()
    xl = io.BytesIO()
    pd.DataFrame({"Investment": [1, 2], "Country": ["DE", "PL"]}).to_excel(xl, index=False)
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("projects.csv", "id,name,year\n1,A,2030\n2,B,2032\n")
        z.writestr("sheets/p.xlsx", xl.getvalue())
        z.writestr("readme.txt", "x")
    got = {e["name"]: e for e in describe_zip(buf.getvalue())}
    assert got["projects.csv"]["rows"] == 2 and got["projects.csv"]["columns"] == ["id", "name", "year"]
    assert got["sheets/p.xlsx"]["columns"] == ["Investment", "Country"] and got["readme.txt"]["rows"] is None
