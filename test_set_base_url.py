import sys
import tempfile
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from set_base_url import set_base_url  # noqa: E402


def test_base_url_is_replaced_in_connections_and_sheets():
    with tempfile.TemporaryDirectory() as d:
        p = f"{d}/t.xlsx"
        with zipfile.ZipFile(p, "w") as z:
            z.writestr("[Content_Types].xml", "<Types/>")
            z.writestr("xl/connections.xml", '<c><textPr sourceFile="https://raw.githubusercontent.com/ORG/REPO/main/data/processed/meta.csv"/></c>')
            z.writestr("xl/worksheets/sheet1.xml", "<x>https://raw.githubusercontent.com/ORG/REPO/main/data/processed/</x>")
        old = set_base_url(p, "https://raw.githubusercontent.com/firma/netz/main/data/processed")
        z = zipfile.ZipFile(p)
        assert old.endswith("ORG/REPO/main/data/processed/")
        assert b"firma/netz/main/data/processed/meta.csv" in z.read("xl/connections.xml")
        assert b"ORG/REPO" not in z.read("xl/worksheets/sheet1.xml")
        assert Path(p + ".bak").exists()
