#!/usr/bin/env python3
"""Berechnete Werte in die Originaldatei übernehmen, ohne ihre Struktur anzutasten.

Warum: Der Generator schreibt Formeln ohne Ergebnis. Excel rechnet beim Öffnen selbst (fullCalcOnLoad), Vorschauen und die
geschützte Ansicht zeigen aber nur gespeicherte Werte. LibreOffice kann die Formeln berechnen, schreibt die Datei dabei jedoch neu
(Verbindungen und Diagramme würden umgeschrieben). Dieses Skript liest deshalb nur die Werte aus der von LibreOffice gespeicherten
Kopie und trägt sie in die Originaldatei ein.

  python scripts/add_cached_values.py ORIGINAL.xlsx VON_LIBREOFFICE_BERECHNET.xlsx AUSGABE.xlsx
"""
import re
import sys
import zipfile

from lxml import etree

M = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
R = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"


def sheet_parts(z):
    wb = etree.fromstring(z.read("xl/workbook.xml"))
    rels = {r.get("Id"): r.get("Target") for r in etree.fromstring(z.read("xl/_rels/workbook.xml.rels"))}
    out = {}
    for s in wb.find(f"{{{M}}}sheets"):
        t = rels[s.get(f"{{{R}}}id")].lstrip("/")
        out[s.get("name")] = t if t.startswith("xl/") else "xl/" + t
    return out


def formula_values(z, part):
    vals = {}
    for c in etree.fromstring(z.read(part)).iter(f"{{{M}}}c"):
        if c.find(f"{{{M}}}f") is None:
            continue
        v = c.find(f"{{{M}}}v")
        vals[c.get("r")] = (c.get("t"), "" if v is None or v.text is None else v.text)
    return vals


def main(raw, calc, out):
    zr, zc = zipfile.ZipFile(raw), zipfile.ZipFile(calc)
    pr, pc = sheet_parts(zr), sheet_parts(zc)
    new, n_set, n_miss = {}, 0, 0
    for name, part in pr.items():
        vals = formula_values(zc, pc[name])
        root = etree.fromstring(zr.read(part))
        for c in root.iter(f"{{{M}}}c"):
            if c.find(f"{{{M}}}f") is None:
                continue
            got = vals.get(c.get("r"))
            if got is None:
                n_miss += 1
                continue
            t, text = got
            for old in c.findall(f"{{{M}}}v"):
                c.remove(old)
            etree.SubElement(c, f"{{{M}}}v").text = text
            if t in ("str", "e", "b"):
                c.set("t", t)
            elif "t" in c.attrib:
                del c.attrib["t"]
            n_set += 1
        new[part] = etree.tostring(root, xml_declaration=True, encoding="UTF-8", standalone=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", zr.read("[Content_Types].xml"))
        for item in zr.infolist():
            if item.filename != "[Content_Types].xml":
                z.writestr(item.filename, new.get(item.filename, zr.read(item.filename)))
    print(f"{n_set} Formelergebnisse übernommen, {n_miss} ohne Gegenstück -> {out}")


if __name__ == "__main__":
    if len(sys.argv) != 4:
        sys.exit(__doc__)
    main(*sys.argv[1:])
