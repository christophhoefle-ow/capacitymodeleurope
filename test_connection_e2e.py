"""The readers of the connection publications against a local web server: request, link search, PDF, page blocks and a page that needs a browser.

The pages and files are built from the real wording of the publications (tests/fixtures). This checks the whole chain except the operators' own servers.
"""
import http.server
import io
import tempfile
import threading
from pathlib import Path

import conftest  # noqa: F401
import fetch_connection_capacity as fcc
from test_harvest import LABELS, STATUS, _pdf_like_50hertz

FIX = Path(__file__).resolve().parent / "fixtures"


def _text_pdf(text: str) -> bytes:
    from reportlab.lib.pagesizes import A4, landscape
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf, pagesize=landscape(A4))
    c.setFont("Helvetica", 8)
    for i, line in enumerate(text.splitlines()):
        c.drawString(30, 560 - 13 * i, line)
    c.save()
    return buf.getvalue()


def _transnetbw_page() -> str:
    out, in_list = ["<html><body><nav><a href='/x'>Netzanschlusskarte</a></nav><main>"], False
    for line in (FIX / "transnetbw_netzanschlusskarte.txt").read_text(encoding="utf-8").splitlines():
        is_attr = ":" in line and line.split(":")[0] in ("Spannungsebene", "Inbetriebnahme Netzanschluss", "Anschlussart", "Verfügbare Einspeisekapazität", "Verfügbare Lastkapazität")
        is_attr = is_attr or line.startswith(("temporärer Anschluss", "Inbetriebnahme Netzanschluss voraussichtlich"))
        if is_attr and not in_list:
            out.append("<ul>")
            in_list = True
        if not is_attr and in_list:
            out.append("</ul>")
            in_list = False
        if is_attr:
            key, sep, val = line.partition(":")
            out.append(f"<li><strong>{key}{sep}</strong>{val}</li>")
        elif line.startswith("Umspannwerk "):
            out.append(f"<h3>{line}</h3>")
        elif line.endswith("verfügbar") and len(line) < 30:
            out.append(f"<div class='status'><span>{line}</span></div>")
        else:
            out.append(f"<p>{line}</p>")
    return "\n".join(out) + "</main><script>var s = 'Umspannwerk Skript';</script></body></html>"


def _site(root: Path) -> None:
    (root / "tbw").mkdir()
    (root / "tbw" / "karte.html").write_text(_transnetbw_page(), encoding="utf-8")
    (root / "amprion").mkdir()
    (root / "amprion" / "page.html").write_text('<html><body><a href="/amprion/Karte-ueber-potenzielle-Netzanschlussmoeglichkeiten-04.2026.pdf">Karte</a>'
                                                '<a href="/amprion/Ergaenzendes-Dokument-zu-potenziellen-Netzanschlussmoeglichkeiten-04.2026.pdf">Dokument</a></body></html>', encoding="utf-8")
    (root / "amprion" / "Ergaenzendes-Dokument-zu-potenziellen-Netzanschlussmoeglichkeiten-04.2026.pdf").write_bytes(_text_pdf((FIX / "amprion_ergaenzendes_dokument.txt").read_text(encoding="utf-8")))
    (root / "h50").mkdir()
    (root / "h50" / "page.html").write_text('<html><body><div id="app"></div><script>window.__DATA__ = {"files": ["\\/h50\\/20250301_umspannwerke_anschlussperspektiven.pdf", '
                                            '"\\/h50\\/20250824_umspannwerke_anschlussperspektiven.pdf"]};</script></body></html>', encoding="utf-8")
    for name in ("20250301_umspannwerke_anschlussperspektiven.pdf", "20250824_umspannwerke_anschlussperspektiven.pdf"):
        (root / "h50" / name).write_bytes(_pdf_like_50hertz())
    (root / "tennet").mkdir()
    (root / "tennet" / "page.html").write_text("""<html><body><h1>Netzanschlussanfragen</h1><p>Stand der Daten: 01.04.2026</p><div id="t"></div><script>
      document.getElementById("t").innerHTML = "<table><tr><th>Umspannwerk</th><th>Voraussichtliche Inbetriebnahme</th><th>Hinweis</th></tr>"
        + "<tr><td>UW Musterstadt</td><td>2031</td><td>nur Lastanschluss</td></tr><tr><td>Beispielhausen</td><td>ab 2034</td><td></td></tr><tr><td>Drittort</td><td>2032</td><td></td></tr></table>";
      </script></body></html>""", encoding="utf-8")


def _serve(root: Path):
    handler = lambda *a, **k: http.server.SimpleHTTPRequestHandler(*a, directory=str(root), **k)
    http.server.SimpleHTTPRequestHandler.log_message = lambda *a, **k: None
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return srv, f"http://127.0.0.1:{srv.server_address[1]}"


def test_readers_work_against_a_web_server():
    try:
        import pdfplumber  # noqa: F401
        import reportlab  # noqa: F401
    except ImportError:
        return
    with tempfile.TemporaryDirectory() as tmp:
        _site(Path(tmp))
        srv, base = _serve(Path(tmp))
        try:
            # TransnetBW: page with one block per substation
            df, info = fcc.adapter_page_blocks({"id": "transnetbw", "tso": "TRANSNETBW", "page": base + "/tbw/karte.html",
                                               "status_map": {"mittelfristig verfügbar": "available", "langfristig verfügbar": "limited", "nicht verfügbar": "none"}})
            assert len(df) == 52 and info["as_of"] == "2026-04-01" and info["with_mw"] == 1
            assert sorted(df["connection_status"].value_counts().items()) == [("available", 9), ("limited", 6), ("none", 37)]
            row = df.set_index("substation").loc["Birkenfeld"]
            assert (row["feed_in_free_from_mw"], row["feed_in_free_to_mw"], row["available_from_year"], row["voltage_level"]) == (1000, 1500, "2032", "380 kV")
            mapped = fcc.apply_name_map(df, {"name_map": {"Engslatt": "Engstlatt"}})
            assert "Engstlatt" in set(mapped["substation"]) and "Engslatt" not in set(mapped["substation"])
            # Amprion: the right PDF among the links of the page, text rows
            df, info = fcc.adapter_pdf_rows({"id": "amprion", "tso": "AMPRION", "page": base + "/amprion/page.html", "link_pattern": "Ergaenzendes-Dokument.{0,60}Netzanschluss", "browser": False,
                                            "row_pattern": r"^(?P<name>.+?)\s+(?P<kv>\d{3})\s*kV\s+(?P<city>.+?)\s+\((?P<n>n-\d)\)\s+(?P<year>20\d{2})(?:\s+(?P<remark>.+))?$",
                                            "remark_rules": [["ausschließlich Lastanschl", "none", "available"], ["Einspeisung.{0,40}reduziert", "limited", "available"]]})
            assert len(df) == 10 and info["url"].endswith("Ergaenzendes-Dokument-zu-potenziellen-Netzanschlussmoeglichkeiten-04.2026.pdf") and info["as_of"] == "2026-04-01"
            assert list(df.set_index("substation").loc["Clusorth", ["status_feed_in", "status_load", "available_from_year"]]) == ["none", "available", "2035"]
            # 50Hertz: the link stands only in a script of the page, the newest file wins, status in words and MW classes from the cell colours
            df, info = fcc.adapter_pdf_status({"id": "50hertz", "tso": "50HERTZ", "page": base + "/h50/page.html", "link_pattern": "umspannwerke.{0,40}anschluss", "browser": False,
                                              "status_map": STATUS, "class_labels": LABELS, "voltage_level": "380 kV"})
            assert info["url"].endswith("20250824_umspannwerke_anschlussperspektiven.pdf") and info["as_of"] == "2025-08-24" and info["with_mw"] == 1
            got = df.set_index("substation")
            assert got.loc["Förderstedt", "connection_status"] == "none" and (got.loc["Altdöbern", "feed_in_free_from_mw"], got.loc["Altdöbern", "load_free_to_mw"]) == (500, 500)
            # a source whose page is gone falls back to the last known address
            df, info = fcc.adapter_pdf_status({"id": "50hertz", "tso": "50HERTZ", "page": base + "/gone.html", "link_pattern": "x", "browser": False, "status_map": STATUS,
                                              "last_known_url": base + "/h50/20250301_umspannwerke_anschlussperspektiven.pdf"})
            assert len(df) == 6 and "last known address used" in info["detail"]
        finally:
            srv.shutdown()


def test_table_that_only_a_browser_shows_is_read_with_the_browser():
    """The table of this page is built by a script (as on pages with bot protection or client-side rendering): a plain request sees no table."""
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as pw:
            pw.chromium.launch().close()
    except Exception:                                                 # noqa: BLE001 - no browser on this machine: nothing to check
        return
    with tempfile.TemporaryDirectory() as tmp:
        _site(Path(tmp))
        srv, base = _serve(Path(tmp))
        try:
            src = {"id": "tennet", "tso": "TENNETGMBH", "page": base + "/tennet/page.html", "table_match": "Umspannwerk|Standort", "default_status": "available"}
            try:
                fcc.adapter_table({**src, "browser": False})
            except Exception:                                         # noqa: BLE001 - expected: without a browser the page has no table (the reader then switches to the browser)
                pass
            df, info = fcc.adapter_table({**src, "browser": True})
            assert list(df["substation"]) == ["Musterstadt", "Beispielhausen", "Drittort"] and list(df["available_from_year"]) == ["2031", "2034", "2032"]
            assert set(df["connection_status"]) == {"available"} and info["as_of"] == "2026-04-01" and "browser" in info["detail"]
        finally:
            srv.shutdown()
