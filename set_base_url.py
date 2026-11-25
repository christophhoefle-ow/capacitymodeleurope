#!/usr/bin/env python3
"""Adresse der CSV-Dateien in einer fertigen Excel-Datei ändern (Datenverbindungen und Anzeige im Blatt Datenstand).

  python scripts/set_base_url.py Kapazitaetsmodell_DE_V3.xlsx https://raw.githubusercontent.com/<ORG>/<REPO>/main/data/processed/

Praktisch, wenn die Datei mit dem Platzhalter ORG/REPO erzeugt wurde. Die Datei wird an Ort und Stelle geändert (Sicherungskopie: .bak).
"""
import re
import shutil
import sys
import zipfile


def set_base_url(path: str, new_base: str) -> str:
    new_base = new_base.rstrip("/") + "/"
    z = zipfile.ZipFile(path)
    files = {n: z.read(n) for n in z.namelist()}
    z.close()
    con = files["xl/connections.xml"].decode("utf-8")
    m = re.search(r'sourceFile="([^"]*/)[^/"]+\.csv"', con)
    if not m:
        raise SystemExit("Keine Datenverbindung in der Datei gefunden (Variante ohne Verbindungen?)")
    old_base = m.group(1)
    for name, data in files.items():
        if name == "xl/connections.xml" or re.fullmatch(r"xl/worksheets/sheet\d+\.xml", name):
            files[name] = data.decode("utf-8").replace(old_base, new_base).encode("utf-8")
    shutil.copyfile(path, path + ".bak")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as out:
        out.writestr("[Content_Types].xml", files.pop("[Content_Types].xml"))
        for name, data in files.items():
            out.writestr(name, data)
    return old_base


if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit(__doc__)
    old = set_base_url(sys.argv[1], sys.argv[2])
    print(f"Adresse geändert: {old}  ->  {sys.argv[2]}")
