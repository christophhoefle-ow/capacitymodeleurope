"""Datenverbindungen in die fertige Excel-Datei einbauen, damit 'Daten > Alle aktualisieren' die CSV-Dateien aus dem Internet lädt.

Umgesetzt als klassische Text-/CSV-Abfragen (Verbindungstyp 6, 'Aus Text/CSV (Legacy)') und, wie von Excel selbst erzeugt, als
BEREICHSABFRAGE: Die Abfragetabelle hängt am Blatt (nicht an einer Excel-Tabelle). Excel legt Text- und Webabfragen nie als Tabelle an;
die erste Fassung band sie an Tabellen und wurde von Excel als beschädigt gemeldet.

Grenzen (bitte beachten):
  * Nicht in Excel getestet; das XML ist gegen das Schema (ISO/IEC 29500) geprüft, ob Excel es annimmt, ist offen.
  * Klassische Textabfragen können keine Zugangsdaten mitschicken: Das Repository muss ÖFFENTLICH lesbar sein
    (raw.githubusercontent.com). Für ein privates Repository bleibt Power Query mit Token (Blatt Automatisierung).
  * Die Adresse steht in jeder Verbindung fest; sie wird beim Erzeugen eingetragen (--base-url, in der GitHub-Aktion automatisch).
"""
from __future__ import annotations

import re
import zipfile
from xml.sax.saxutils import quoteattr

from lxml import etree

MAIN = "http://schemas.openxmlformats.org/spreadsheetml/2006/main"
REL_NS = "http://schemas.openxmlformats.org/package/2006/relationships"
OFFICE_REL = "http://schemas.openxmlformats.org/officeDocument/2006/relationships"
REL_CONN = OFFICE_REL + "/connections"
REL_QT = OFFICE_REL + "/queryTable"
CT_CONN = "application/vnd.openxmlformats-officedocument.spreadsheetml.connections+xml"
CT_QT = "application/vnd.openxmlformats-officedocument.spreadsheetml.queryTable+xml"
PLACEHOLDER = "ORG/REPO"
_FIELD = {"text": "text", "number": "general", "date": "YMD"}      # Spaltentyp im Textimport


def connections_xml(specs, base_url: str) -> str:
    out = [f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<connections xmlns="{MAIN}">']
    for i, sp in enumerate(specs, 1):
        url = base_url.rstrip("/") + "/" + sp["file"]
        fields = "".join(f'<textField type="{_FIELD[kind]}"/>' for _, kind in sp["columns"])
        out.append(
            f'<connection id="{i}" name={quoteattr(sp["file"][:-4])} description={quoteattr("CSV aus dem Repository: " + sp["file"])} '
            f'type="6" refreshedVersion="6" background="1" saveData="1">'
            f'<textPr prompt="0" codePage="65001" sourceFile={quoteattr(url)} tab="0" comma="1" decimal="." thousands=",">'
            f'<textFields count="{len(sp["columns"])}">{fields}</textFields></textPr></connection>')
    out.append("</connections>")
    return "".join(out)


def query_table_xml(spec, conn_id: int) -> str:
    n = len(spec["columns"])
    fields = "".join(f'<queryTableField id="{k}" name={quoteattr(name)}/>' for k, (name, _) in enumerate(spec["columns"], 1))
    return (f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n'
            f'<queryTable xmlns="{MAIN}" name="ExternalData_{conn_id}" connectionId="{conn_id}" autoFormatId="16" applyNumberFormats="0" '
            f'applyBorderFormats="0" applyFontFormats="0" applyPatternFormats="0" applyAlignmentFormats="0" applyWidthHeightFormats="0" '
            f'adjustColumnWidth="0"><queryTableRefresh nextId="{n + 1}"><queryTableFields count="{n}">{fields}</queryTableFields>'
            f'</queryTableRefresh></queryTable>')


def _sheet_parts(files) -> dict:
    wb = etree.fromstring(files["xl/workbook.xml"])
    rels = {r.get("Id"): r.get("Target") for r in etree.fromstring(files["xl/_rels/workbook.xml.rels"])}
    out = {}
    for s in wb.find(f"{{{MAIN}}}sheets"):
        t = rels[s.get(f"{{{OFFICE_REL}}}id")].lstrip("/")
        out[s.get("name")] = t if t.startswith("xl/") else "xl/" + t
    return out


def inject(path: str, specs: list[dict], base_url: str) -> None:
    """Verbindungen, Abfragetabellen und Beziehungen in die xlsx-Datei schreiben (Datei wird ersetzt)."""
    zin = zipfile.ZipFile(path)
    files = {n: zin.read(n) for n in zin.namelist()}
    zin.close()
    sheets = _sheet_parts(files)
    for i, sp in enumerate(specs, 1):
        base = sheets[sp["sheet"]].rsplit("/", 1)[1]
        rels_name = f"xl/worksheets/_rels/{base}.rels"
        rel = f'<Relationship Id="rIdQT{i}" Type="{REL_QT}" Target="../queryTables/queryTable{i}.xml"/>'
        if rels_name in files:
            files[rels_name] = files[rels_name].decode("utf-8").replace("</Relationships>", rel + "</Relationships>").encode("utf-8")
        else:
            files[rels_name] = f'<?xml version="1.0" encoding="UTF-8" standalone="yes"?>\n<Relationships xmlns="{REL_NS}">{rel}</Relationships>'.encode("utf-8")
        files[f"xl/queryTables/queryTable{i}.xml"] = query_table_xml(sp, i).encode("utf-8")
    files["xl/connections.xml"] = connections_xml(specs, base_url).encode("utf-8")
    ct = files["[Content_Types].xml"].decode("utf-8")
    add = f'<Override PartName="/xl/connections.xml" ContentType="{CT_CONN}"/>' + "".join(
        f'<Override PartName="/xl/queryTables/queryTable{i}.xml" ContentType="{CT_QT}"/>' for i in range(1, len(specs) + 1))
    files["[Content_Types].xml"] = ct.replace("</Types>", add + "</Types>").encode("utf-8")
    rels = files["xl/_rels/workbook.xml.rels"].decode("utf-8")
    files["xl/_rels/workbook.xml.rels"] = rels.replace(
        "</Relationships>", f'<Relationship Id="rIdConnections" Type="{REL_CONN}" Target="connections.xml"/></Relationships>').encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", files.pop("[Content_Types].xml"))
        for name, data in files.items():
            z.writestr(name, data)


def patch_scatter_na_as_blank(path: str) -> int:
    """Streudiagramme: #NV wie leere Zellen behandeln (Lücke statt Verbindungslinie), Excel 2016 und neuer."""
    zin = zipfile.ZipFile(path)
    files = {n: zin.read(n) for n in zin.namelist()}
    zin.close()
    n = 0
    for name in list(files):
        if re.fullmatch(r"xl/charts/chart\d+\.xml", name) and b"scatterChart" in files[name]:
            x = files[name].decode("utf-8")
            m = re.search(r'<(c:)?dispBlanksAs val="gap"\s*/>', x)
            if m and "dispNaAsBlank" not in x:
                p = m.group(1) or ""
                ext = (f'<{p}extLst><{p}ext uri="{{56B9EC1D-385E-4148-901F-78D8002777C0}}" '
                       f'xmlns:c16r3="http://schemas.microsoft.com/office/drawing/2017/03/chart">'
                       f'<c16r3:dataDisplayOptions16><c16r3:dispNaAsBlank val="1"/></c16r3:dataDisplayOptions16></{p}ext></{p}extLst>')
                files[name] = (x[:m.end()] + ext + x[m.end():]).encode("utf-8")
                n += 1
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", files.pop("[Content_Types].xml"))
        for name, data in files.items():
            z.writestr(name, data)
    return n


def patch_map_charts(path: str) -> int:
    """Kartendiagramme absichern: kein automatischer Titel, Seitenverhaeltnis des Diagramms gesperrt.

    1. <autoTitleDeleted val="1"/>: Excel setzt sonst unter Umstaenden selbst einen Titel und verkleinert dafuer die Zeichenflaeche.
    2. <a:graphicFrameLocks noChangeAspect="1"/>: Zieht jemand das Diagramm groesser oder kleiner, bleibt Breite : Hoehe erhalten. Die Karte bleibt massstabsgetreu,
       weil die Zeichenflaeche das ganze Diagramm fuellt (siehe build.add_map).
    """
    zin = zipfile.ZipFile(path)
    files = {n: zin.read(n) for n in zin.namelist()}
    zin.close()
    n = 0
    for name in list(files):
        if re.fullmatch(r"xl/charts/chart\d+\.xml", name) and b"scatterChart" in files[name]:
            x = files[name].decode("utf-8")
            if "autoTitleDeleted" not in x:
                x, k = re.subn(r"<((?:\w+:)?)plotArea>", lambda m: f'<{m.group(1)}autoTitleDeleted val="1"/><{m.group(1)}plotArea>', x, count=1)
                n += k
                files[name] = x.encode("utf-8")
        if re.fullmatch(r"xl/drawings/drawing\d+\.xml", name):
            x = files[name].decode("utf-8")
            if "graphicFrameLocks" not in x:
                lock = '<a:graphicFrameLocks xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main" noChangeAspect="1"/>'
                x, k = re.subn(r"<((?:\w+:)?)cNvGraphicFramePr\s*/>", lambda m: f"<{m.group(1)}cNvGraphicFramePr>{lock}</{m.group(1)}cNvGraphicFramePr>", x)
                n += k
                files[name] = x.encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("[Content_Types].xml", files.pop("[Content_Types].xml"))
        for name, data in files.items():
            z.writestr(name, data)
    return n
