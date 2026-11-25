"""Automatic harvest of the connection-capacity publications: parsers against the real wording of the 50Hertz publication and against built examples."""
import io
from pathlib import Path

import pandas as pd

import conftest  # noqa: F401
from capmodel import connection, harvest

FIX = Path(__file__).resolve().parent / "fixtures"
STATUS = {"nicht überbucht": "available", "überbucht": "limited", "belegt": "none"}
LABELS = ["> 2.000 MW", "1.500 – 2.000 MW", "1.000 – 1.500 MW", "500 – 1.000 MW", "< 500 MW"]


def test_classes_in_words_become_ranges():
    assert harvest.class_to_range("< 500 MW") == (0, 500)
    assert harvest.class_to_range("500 – 1.000 MW") == (500, 1000)
    assert harvest.class_to_range("1.500 - 2.000 MW") == (1500, 2000)
    assert harvest.class_to_range("> 2.000 MW") == (2000, 2000)
    assert harvest.class_to_range("kleiner 500 MW") == (0, 500)
    assert harvest.class_to_range("belegt") is None


def test_50hertz_text_gives_22_substations_with_status():
    """Text of the publication of 24.08.2025 as the PDF delivers it: two table halves per line, legend lines must not become rows."""
    rows = harvest.parse_status_text((FIX / "50hertz_anschlussperspektiven.txt").read_text(encoding="utf-8"), STATUS)
    got = {r["substation"]: r["connection_status"] for r in rows}
    assert len(rows) == 22 and len(got) == 22
    assert got["Altdöbern"] == "available" and got["Altentreptow/Süd"] == "available"          # 'nicht überbucht' must not be read as 'überbucht'
    assert got["Bentwisch"] == "limited" and got["Parchim/Süd"] == "limited"
    assert got["Klostermansfeld"] == "none" and got["Wolmirstedt"] == "none"
    assert sorted(pd.Series(list(got.values())).value_counts().to_dict().items()) == [("available", 4), ("limited", 9), ("none", 9)]
    df = harvest.status_rows(rows, "50HERTZ", "2025-08-24", "https://example.org/x.pdf", "380 kV")
    assert list(df.columns) == connection.COLUMNS and (df["tso"] == "50HERTZ").all() and df["remark"].str.startswith("switch bays: ").all()


def _pdf_like_50hertz() -> bytes:
    """A PDF built like the 50Hertz table: two halves, MW classes as coloured cells, status in words, legend with coloured boxes."""
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas
    colours = {"> 2.000 MW": (0.0, 0.4, 0.2), "1.500 – 2.000 MW": (0.3, 0.7, 0.3), "1.000 – 1.500 MW": (0.7, 0.9, 0.4), "500 – 1.000 MW": (1.0, 0.9, 0.3), "< 500 MW": (1.0, 0.6, 0.2)}
    left = [("Altdöbern", "500 – 1.000 MW", "< 500 MW", "nicht überbucht"), ("Bentwisch", "", "1.000 – 1.500 MW", "überbucht"), ("Förderstedt", "> 2.000 MW", "", "belegt")]
    right = [("Klostermansfeld", "< 500 MW", "< 500 MW", "belegt"), ("Parchim/Süd", "", "", "überbucht"), ("Putlitz/Süd", "1.500 – 2.000 MW", "500 – 1.000 MW", "überbucht")]
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    c.setFont("Helvetica", 9)
    for x0, rows in ((40, left), (430, right)):
        for i, (name, feed, load, st) in enumerate(rows):
            y = 500 - 22 * i
            c.setFillColorRGB(0, 0, 0)
            c.drawString(x0, y, f"UW {name}")
            for k, lab in enumerate((feed, load)):
                if lab:
                    c.setFillColorRGB(*colours[lab])
                    c.rect(x0 + 130 + 60 * k, y - 5, 55, 16, stroke=0, fill=1)
            c.setFillColorRGB(0, 0, 0)
            c.drawString(x0 + 260, y, st)
    for i, (lab, rgb) in enumerate(colours.items()):
        y = 300 - 20 * i
        c.setFillColorRGB(*rgb)
        c.rect(40, y - 4, 30, 14, stroke=0, fill=1)
        c.setFillColorRGB(0, 0, 0)
        c.drawString(80, y, lab)
    c.save()
    return buf.getvalue()


def test_pdf_status_and_colour_classes_are_read_from_a_pdf():
    try:
        import pdfplumber  # noqa: F401
        import reportlab  # noqa: F401
    except ImportError:                                               # the PDF libraries are part of requirements.txt; without them this test has nothing to check
        return
    data = _pdf_like_50hertz()
    rows = harvest.parse_status_text(harvest.pdf_text(data), STATUS)
    assert {r["substation"]: r["connection_status"] for r in rows} == {"Altdöbern": "available", "Bentwisch": "limited", "Förderstedt": "none", "Klostermansfeld": "none",
                                                                       "Parchim/Süd": "limited", "Putlitz/Süd": "limited"}
    classes = harvest.pdf_color_classes(data, LABELS, [r["substation"] for r in rows])
    assert classes["Altdöbern"] == ["500 – 1.000 MW", "< 500 MW"]
    assert classes["Bentwisch"] == ["", "1.000 – 1.500 MW"] and classes["Förderstedt"] == ["> 2.000 MW", ""]      # the empty cell keeps its column
    assert classes["Putlitz/Süd"] == ["1.500 – 2.000 MW", "500 – 1.000 MW"] and classes["Parchim/Süd"] == ["", ""]
    df = harvest.status_rows(rows, "50HERTZ", "2025-08-24", "u", "380 kV", classes).set_index("substation")
    assert (df.loc["Altdöbern", "feed_in_free_from_mw"], df.loc["Altdöbern", "feed_in_free_to_mw"]) == (500, 1000)
    assert (df.loc["Bentwisch", "feed_in_free_from_mw"], df.loc["Bentwisch", "load_free_from_mw"], df.loc["Bentwisch", "load_free_to_mw"]) == ("", 1000, 1500)


def test_colour_classes_are_not_guessed_without_a_legend():
    try:
        import pdfplumber  # noqa: F401
        from reportlab.pdfgen import canvas
    except ImportError:
        return
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    c.drawString(40, 700, "UW Altdöbern nicht überbucht")
    c.setFillColorRGB(1, 0.6, 0.2)
    c.rect(200, 695, 50, 14, stroke=0, fill=1)
    c.save()
    assert harvest.pdf_color_classes(buf.getvalue(), LABELS, ["Altdöbern"]) == {}


def test_capacitypedia_page_gives_the_register_fields():
    page = """<html><body><h1>50Hertz</h1><h3>TSO - Germany</h3><table>
      <tr><td>Status of publication</td><td>Published</td></tr>
      <tr><td>Link to website</td><td><a href="https://www.50hertz.com/de/Vertragspartner/Netzkunden/Netzanschluss">Netzanschluss</a></td></tr>
      <tr><td>Spatial granularity</td><td>Nodal (substation)</td></tr><tr><td>Operator voltage level scope</td><td>380 kV</td></tr>
      <tr><td>Information format</td><td>Table</td></tr><tr><td>Availability of API</td><td>Not provided</td></tr><tr><td>Update Cycles</td><td>When needed</td></tr>
      <tr><td>Unknown field</td><td>x</td></tr><tr><td>one cell only</td></tr></table></body></html>"""
    got = harvest.parse_capacitypedia(page)
    assert got == {"publication_status": "Published", "link": "https://www.50hertz.com/de/Vertragspartner/Netzkunden/Netzanschluss", "granularity": "Nodal (substation)",
                   "voltage_scope": "380 kV", "format": "Table", "api": "Not provided", "update_cycle": "When needed"}


def test_links_are_found_in_markup_and_in_scripts_and_the_newest_wins():
    page = ('<a href="/files/20250301_umspannwerke_anschlussperspektiven.pdf">alt</a><a href="/files/tab.pdf">TAB</a>'
            '<script>var d = {"file": "\\/files\\/20250824_umspannwerke_anschlussperspektiven.pdf"}</script>')
    links = harvest.find_links(page, "https://www.example.org/de/netz", "umspannwerke.{0,40}anschluss")
    assert links == ["https://www.example.org/files/20250301_umspannwerke_anschlussperspektiven.pdf", "https://www.example.org/files/20250824_umspannwerke_anschlussperspektiven.pdf"]
    assert harvest.newest(links).endswith("20250824_umspannwerke_anschlussperspektiven.pdf") and harvest.date_in_name(harvest.newest(links)) == "2025-08-24"


def test_published_table_is_mapped_by_header_words():
    df = pd.DataFrame({"Umspannwerk": ["UW Musterstadt", "Beispielhausen", ""], "Freie Einspeisekapazität": ["500 – 1.000 MW", "< 500 MW", ""],
                       "Lastkapazität (MW)": ["250", "", ""], "Status": ["verfügbar", "nicht verfügbar", ""], "Inbetriebnahme": ["ab 2029", "", ""]})
    out = harvest.table_rows(df, "TENNETGMBH", "2026-11-01", "https://example.org").set_index("substation")
    assert list(out.index) == ["Musterstadt", "Beispielhausen"]
    assert (out.loc["Musterstadt", "feed_in_free_from_mw"], out.loc["Musterstadt", "feed_in_free_to_mw"], out.loc["Musterstadt", "load_free_from_mw"]) == (500, 1000, 250)
    assert out.loc["Musterstadt", "connection_status"] == "available" and out.loc["Beispielhausen", "connection_status"] == "none"
    assert out.loc["Musterstadt", "available_from_year"] == "2029"


def test_normalise_spells_names_like_the_model_and_reports_what_it_cannot_place():
    subs = pd.DataFrame({"substation": ["Parchim/Süd", "St. Peter (AT)", "St. Peter (DE)", "Röhrsdorf"], "country": ["DE", "AT", "DE", "DE"]})
    raw = pd.DataFrame({"substation": ["Parchim/Sued", "St. Peter", "Roehrsdorf", "Nirgendwo", "Parchim/Süd"], "tso": ["50HERTZ", "AMPRION", "50HERTZ", "50HERTZ", "50HERTZ"],
                        "connection_status": ["limited", "available", "kaputt", "none", "none"], "feed_in_free_from_mw": ["500", "", "x", "", ""], "feed_in_free_to_mw": ["1000", "", "", "", ""]})
    out, report = connection.normalise(raw, subs, {"50HERTZ": "DE", "AMPRION": "DE"})
    assert list(out["substation"]) == ["Parchim/Süd", "St. Peter (DE)", "Röhrsdorf", "Nirgendwo"]             # homonym resolved by the country of the TSO, duplicate dropped
    assert out.loc[2, "connection_status"] == "" and out.loc[2, "feed_in_free_from_mw"] == ""
    findings = " | ".join(f for _n, f in report)
    assert "unknown connection_status" in findings and "not a number" in findings and "no substation of this name" in findings and "more than once" in findings


def test_transnetbw_page_gives_status_year_and_mw_per_substation():
    """Text of the TransnetBW map as read on 25.11.2026 (52 substations): the status stands before the heading of its substation."""
    lines = (FIX / "transnetbw_netzanschlusskarte.txt").read_text(encoding="utf-8").splitlines()
    smap = {"mittelfristig verfügbar": "available", "langfristig verfügbar": "limited", "nicht verfügbar": "none"}
    rows = {r["substation"]: r for r in harvest.parse_station_blocks(lines, smap)}
    assert len(rows) == 52
    assert sorted(pd.Series([r["connection_status"] for r in rows.values()]).value_counts().items()) == [("available", 9), ("limited", 6), ("none", 37)]
    assert rows["Daxlanden"]["feed_in"] == (0, 0) and rows["Daxlanden"]["load"] == (500, 1000) and rows["Daxlanden"]["year"] == "2035"
    assert rows["Kork"]["year"] == "2032" and rows["Kork"]["feed_in"] == (1000, 1500)                 # the line without a colon is read as well
    assert "Obermooweiler" in rows and "feed_in" not in rows["Altlussheim"]
    assert harvest.stated_date(" ".join(lines)) == "2026-04-01"
    df = harvest.block_rows(list(rows.values()), "TRANSNETBW", "2026-04-01", "u").set_index("substation")
    assert (df.loc["Eichstetten", "feed_in_free_from_mw"], df.loc["Eichstetten", "load_free_to_mw"], df.loc["Eichstetten", "available_from_year"]) == (1500, 1000, "2032")
    assert "temporärer Anschluss bis 2045" in df.loc["Eichstetten", "remark"]


def test_station_blocks_refuse_a_page_whose_layout_has_changed():
    """If the status came AFTER the heading, substations without a connection would carry capacities: the reader must stop instead of delivering wrong lights."""
    lines = ["Umspannwerk A", "nicht verfügbar", "Umspannwerk B", "mittelfristig verfügbar", "Verfügbare Einspeisekapazität: 500 – 1.000 MW", "Umspannwerk C", "nicht verfügbar"]
    smap = {"mittelfristig verfügbar": "available", "nicht verfügbar": "none"}
    try:
        harvest.parse_station_blocks(lines, smap)
    except ValueError as exc:
        assert "layout" in str(exc)
    else:
        raise AssertionError("a shifted layout was accepted")


def test_page_lines_follow_the_blocks_of_the_page():
    page = ("<html><head><style>p{color:red}</style><script>var x = 'Umspannwerk Falsch';</script></head><body><div><span>🔴 nicht verfügbar</span><h3>Umspannwerk Beuren</h3></div>"
            "<div><span>🟢 mittelfristig verfügbar</span><h3>Umspannwerk <b>Kork</b></h3><ul><li><strong>Verfügbare Einspeisekapazität:</strong> 1.000 – 1.500 MW</li></ul></div></body></html>")
    assert harvest.page_lines(page) == ["🔴 nicht verfügbar", "Umspannwerk Beuren", "🟢 mittelfristig verfügbar", "Umspannwerk Kork", "Verfügbare Einspeisekapazität: 1.000 – 1.500 MW"]


def test_amprion_text_table_gives_year_and_status_per_direction():
    """Text of the Amprion PDF of April 2026: ten substations where a connection is expected to be feasible."""
    rx = r"^(?P<name>.+?)\s+(?P<kv>\d{3})\s*kV\s+(?P<city>.+?)\s+\((?P<n>n-\d)\)\s+(?P<year>20\d{2})(?:\s+(?P<remark>.+))?$"
    text = (FIX / "amprion_ergaenzendes_dokument.txt").read_text(encoding="utf-8")
    rows = harvest.parse_text_rows(text, rx, [["ausschließlich Lastanschl", "none", "available"], ["Einspeisung.{0,40}reduziert", "limited", "available"]])
    got = {r["substation"]: (r["year"], r["status_feed_in"], r["status_load"]) for r in rows}
    assert len(got) == 10 and got["Clusorth"] == ("2035", "none", "available") and got["Kötz"] == ("2035", "limited", "available") and got["Esch"] == ("2032", "", "")
    df = harvest.text_rows(rows, "AMPRION", harvest.stated_date(text), "u").set_index("substation")
    assert df.loc["Meppen", "connection_status"] == "available" and df.loc["Meppen", "status_feed_in"] == "none" and df.loc["Meppen", "voltage_level"] == "380 kV"
    assert harvest.stated_date(text) == "2026-04-01" and harvest.stated_date("Stand 05/2026") == "2026-05-01" and harvest.stated_date("kein Datum") == ""


def test_two_rows_for_one_substation_keep_the_one_with_capacities():
    subs = pd.DataFrame({"substation": ["Kuehmoos"], "country": ["DE"]})
    raw = pd.DataFrame({"substation": ["Kühmoos", "Kühmoos"], "tso": ["AMPRION", "TRANSNETBW"], "connection_status": ["available", "limited"],
                        "feed_in_free_from_mw": ["", "0"], "feed_in_free_to_mw": ["", "500"]})
    out, report = connection.normalise(raw, subs, {"AMPRION": "DE", "TRANSNETBW": "DE"})
    assert list(out["tso"]) == ["TRANSNETBW"] and out.loc[0, "substation"] == "Kuehmoos" and "AMPRION" in report[0][1]
