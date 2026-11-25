"""Automatic harvest of the connection-capacity publications of the TSOs (no hand-maintained table).

Why this is not a simple download: the EU rules (Regulation (EU) 2019/943, Article 50(4a)) oblige every TSO to publish the capacity available for new connections
per substation, but not in a common format. None of the German TSOs offers an interface. This module therefore reads what each operator actually publishes:

  capacitypedia   the directory of ENTSO-E and DSO Entity: one page per operator with the same fields (status of the publication, link, format, interface, update cycle).
                  Read for every Core TSO: gives the register of publications and shows when an operator changes its publication.
  pdf_status      a PDF table with one row per substation and a status in words (50Hertz: 'nicht überbucht', 'überbucht', 'belegt'). The MW classes of that PDF are
                  cell colours, not text; they are read as well when the colours of the legend can be matched, otherwise the status alone is delivered.
  table           an HTML table, a CSV or an Excel file with one row per substation (columns are found by their header words).

Every adapter returns rows in the columns of the data contract (capmodel.connection.COLUMNS). A source that fails keeps its last good file; the run reports it.
"""
from __future__ import annotations

import io
import re
from urllib.parse import urljoin

import pandas as pd
from lxml import html as lxml_html

from .connection import COLUMNS

_NUM = r"\d{1,3}(?:[.\s\u00a0]\d{3})*|\d+"


def _to_int(text: str) -> int:
    return int(re.sub(r"[.\s\u00a0]", "", text))


def class_to_range(label: str):
    """MW class in words -> (from, to): '< 500 MW' -> (0, 500), '500 – 1.000 MW' -> (500, 1000), '> 2.000 MW' -> (2000, 2000). None if no class is recognised."""
    t = str(label).replace("\u2013", "-").replace("\u2212", "-").replace("\u2014", "-")
    m = re.search(rf"({_NUM})\s*-\s*({_NUM})", t)
    if m:
        return _to_int(m.group(1)), _to_int(m.group(2))
    m = re.search(rf"(<|kleiner|unter|below|bis)\s*({_NUM})", t, re.I)
    if m:
        return 0, _to_int(m.group(2))
    m = re.search(rf"(>|gr(?:ö|oe)(?:ss|ß)er|(?:ü|ue)ber|above|ab)\s*({_NUM})", t, re.I)
    if m:
        return _to_int(m.group(2)), _to_int(m.group(2))
    return None


# ----------------------------------------------------------------------------- Capacitypedia (register of the publications)
REGISTER_FIELDS = {"status of publication": "publication_status", "link to website": "link", "accessibility": "accessibility", "spatial granularity": "granularity",
                   "operator voltage level scope": "voltage_scope", "information format": "format", "type of grid connection capacity information": "capacity_information",
                   "availability of api": "api", "update cycles": "update_cycle", "categories of grid users considered": "grid_users"}
REGISTER_COLUMNS = ["tso", "country", "publication_status", "link", "accessibility", "granularity", "voltage_scope", "format", "capacity_information", "api", "update_cycle",
                    "grid_users", "page", "fetched_utc"]


def parse_capacitypedia(page_html: str) -> dict:
    """Fields of an operator page of Capacitypedia: every table row with two cells is 'field | value'. The link is taken from the href, not from the link text."""
    out = {}
    doc = lxml_html.fromstring(page_html)
    for tr in doc.iter("tr"):
        cells = [c for c in tr if c.tag in ("td", "th")]
        if len(cells) != 2:
            continue
        key = " ".join(cells[0].text_content().split()).lower()
        if key not in REGISTER_FIELDS:
            continue
        value = " ".join(cells[1].text_content().split())
        if REGISTER_FIELDS[key] == "link":
            hrefs = [a.get("href") for a in cells[1].iter("a") if a.get("href", "").startswith("http")]
            value = hrefs[0] if hrefs else value
        out.setdefault(REGISTER_FIELDS[key], value)
    return out


# ----------------------------------------------------------------------------- links on a page
def find_links(page_html: str, base_url: str, pattern: str) -> list[str]:
    """All links of a page whose address or text matches the pattern (case-insensitive), absolute, in the order of the page. Also finds addresses inside scripts."""
    rx = re.compile(pattern, re.I)
    found = []
    try:
        doc = lxml_html.fromstring(page_html)
        for a in doc.iter("a"):
            href = a.get("href") or ""
            if href and (rx.search(href) or rx.search(a.text_content() or "")):
                found.append(urljoin(base_url, href))
    except Exception:                                                  # noqa: BLE001 - broken markup: fall back to the text search below
        pass
    for m in re.finditer(r"""["'(]((?:https?:)?/[^"'()\s]+?\.(?:pdf|csv|xlsx))["')]""", page_html.replace("\\/", "/"), re.I):       # addresses in scripts or JSON of the page
        if rx.search(m.group(1)):
            found.append(urljoin(base_url, m.group(1)))
    return list(dict.fromkeys(found))


def newest(links: list[str]) -> str | None:
    """The link with the latest date in its file name (YYYYMMDD or YYYY-MM-DD); without a date the first link of the page."""
    def stamp(u):
        m = re.search(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", u.rsplit("/", 1)[-1])
        return "".join(m.groups()) if m else ""
    return max(links, key=stamp) if links else None


def date_in_name(url: str) -> str:
    m = re.search(r"(20\d{2})[-_]?(\d{2})[-_]?(\d{2})", url.rsplit("/", 1)[-1])
    return "-".join(m.groups()) if m else ""


# ----------------------------------------------------------------------------- PDF with a status in words per substation (50Hertz)
def pdf_text(data: bytes) -> str:
    """Text of a PDF, line by line (pdfplumber keeps the cells of one table row on one line)."""
    import pdfplumber
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join((page.extract_text() or "") for page in pdf.pages)


def parse_status_text(text: str, status_map: dict, prefix: str = r"UW\s+") -> list[dict]:
    """Rows 'UW <name> <status>' from the text of the PDF. Two table halves stand side by side, so a line can hold two substations.

    status_map: words of the publication -> available | limited | none. Longer words are tried first ('nicht überbucht' before 'überbucht')."""
    words = sorted(status_map, key=len, reverse=True)
    rx = re.compile(rf"{prefix}(?P<name>.+?)\s+(?P<st>{'|'.join(re.escape(w) for w in words)})(?=\s+{prefix}|\s*$)", re.I)
    rows = []
    for line in text.splitlines():
        for m in rx.finditer(" ".join(line.split())):
            st = next(w for w in words if w.lower() == m.group("st").lower())
            rows.append({"substation": m.group("name").strip(), "status_text": st, "connection_status": status_map[st]})
    return rows


def pdf_color_classes(data: bytes, class_labels: list[str], names: list[str], prefix: str = "UW ") -> dict:
    """MW classes that the PDF shows as cell colours: {substation: [class in the feed-in column, class in the load column]} ('' = cell without a class colour).

    Method: the legend lists every class next to a coloured box; a box of such a colour in the row of a substation, right of its name, is a capacity cell.
    The feed-in column is the left one of the two capacity columns of a table half. Returns {} whenever the reading is not unambiguous (legend colours not found
    or not distinct, more than two capacity columns, only one column in use): the caller then delivers the status in words only. Nothing is guessed.
    """
    import pdfplumber
    white = ((1,), (1, 1, 1), (0, 0, 0, 0), (1.0,), (1.0, 1.0, 1.0))
    out = {}
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            words = page.extract_words()

            def colour(r):
                c = r.get("non_stroking_color")
                c = c if isinstance(c, (list, tuple)) else ([] if c is None else [c])
                return tuple(round(float(x), 2) for x in c)

            rects = [r for r in page.rects if r.get("fill", True) and colour(r) and colour(r) not in white and r["width"] > 3 and r["height"] > 3]
            if not rects or not words:
                continue
            lines: dict[int, list] = {}
            for w in words:
                lines.setdefault(round((w["top"] + w["bottom"]) / 2 / 4), []).append(w)
            legend, legend_ids = {}, set()
            for ws_ in lines.values():
                ws_ = sorted(ws_, key=lambda w: w["x0"])
                text = " ".join(w["text"] for w in ws_)
                lab = next((x for x in class_labels if class_to_range(x) is not None and class_to_range(x) == class_to_range(text)), None)
                if lab is None or len(text) > 30 or text.startswith(prefix.strip()):
                    continue
                mid = sum((w["top"] + w["bottom"]) / 2 for w in ws_) / len(ws_)
                near = [r for r in rects if r["top"] - 2 <= mid <= r["bottom"] + 2]
                if near:
                    box = min(near, key=lambda r: min(abs(r["x1"] - ws_[0]["x0"]), abs(r["x0"] - ws_[-1]["x1"])))
                    legend[colour(box)] = lab
                    legend_ids.add(id(box))
            if len(legend) < 2 or len(set(legend.values())) != len(legend):
                continue
            found = {}
            for name in names:
                first = (prefix + name).split()
                for ws_ in lines.values():
                    ws_ = sorted(ws_, key=lambda w: w["x0"])
                    texts = [w["text"] for w in ws_]
                    for i in range(len(texts) - len(first) + 1):
                        if texts[i:i + len(first)] != first:
                            continue
                        y = (ws_[i]["top"] + ws_[i]["bottom"]) / 2
                        x_from = ws_[i + len(first) - 1]["x1"]
                        nxt = [w["x0"] for w in ws_[i + len(first):] if w["text"] == prefix.strip()]
                        x_to = min(nxt) if nxt else page.width
                        cells = [(round(r["x0"] / 4) * 4, legend[colour(r)]) for r in rects
                                 if colour(r) in legend and id(r) not in legend_ids and r["top"] - 1 <= y <= r["bottom"] + 1 and x_from - 2 <= r["x0"] < x_to]
                        found[name] = (ws_[i]["x0"] < page.width / 2, cells)
            for half in (True, False):
                xs = sorted({x for h, cells in found.values() if h == half for x, _ in cells})
                if len(xs) != 2:                                       # one column or more than two: feed-in and load cannot be told apart
                    continue
                for name, (h, cells) in found.items():
                    if h == half:
                        by_x = dict(cells)
                        out[name] = [by_x.get(xs[0], ""), by_x.get(xs[1], "")]
    return out


def status_rows(rows: list[dict], tso: str, as_of: str, source_url: str, voltage: str = "", classes: dict | None = None, columns_x: list | None = None) -> pd.DataFrame:
    """Rows of the adapter in the columns of the data contract. classes (optional): {substation: [feed-in class, load class]} as text."""
    recs = []
    for r in rows:
        rec = {c: "" for c in COLUMNS}
        rec.update(substation=r["substation"], tso=tso, voltage_level=voltage, as_of=as_of, source_url=source_url, connection_status=r["connection_status"],
                   remark=f"switch bays: {r['status_text']}")
        for key, lab in zip(("feed_in", "load"), (classes or {}).get(r["substation"], [])):
            rng = class_to_range(lab) if lab else None
            if rng:
                rec[f"{key}_free_from_mw"], rec[f"{key}_free_to_mw"] = rng
        recs.append(rec)
    return pd.DataFrame(recs, columns=COLUMNS)


# ----------------------------------------------------------------------------- generic table (HTML, CSV, Excel)
SYNONYMS = {"substation": ("umspannwerk", "substation", "station", "standort", "netzknoten", "poste", "stacja", "rozvodna", "onderstation", "name"),
            "feed_in": ("einspeis", "rückspeis", "rueckspeis", "erzeug", "feed-in", "feed in", "generation", "injection", "production"),
            "load": ("last", "bezug", "entnahme", "verbrauch", "load", "demand", "offtake", "withdrawal", "consumption"),
            "status": ("status", "verfügbar", "verfuegbar", "eignung", "schaltfeld", "availability", "suitab"),
            "year": ("jahr", "inbetriebnahme", "year", "in-service", "verfügbar ab", "available from")}
STATUS_WORDS = [("none", ("nicht verfügbar", "nicht geeignet", "keine", "belegt", "ausgeschöpft", "erschöpft", "not available", "no capacity", "unavailable", "full")),
                ("limited", ("eingeschränkt", "begrenzt", "bedingt", "überbucht", "limited", "restricted", "partly", "partially")),
                ("available", ("verfügbar", "frei", "geeignet", "nicht überbucht", "available", "free", "suitable"))]


def status_from_words(text: str) -> str:
    """available | limited | none from the wording of a publication ('' if no known word appears). The negative and limiting words are tested first."""
    low = " ".join(str(text).lower().split())
    if "nicht überbucht" in low or "not overbooked" in low:
        return "available"
    return next((st for st, ws_ in STATUS_WORDS if any(w in low for w in ws_)), "")


def table_rows(df: pd.DataFrame, tso: str, as_of: str, source_url: str, columns: dict | None = None) -> pd.DataFrame:
    """One row per substation from a published table. Columns are found by header words (SYNONYMS) or named in the source configuration (columns: {field: header})."""
    heads = {str(c): " ".join(str(c).lower().split()) for c in df.columns}
    pick = {}
    for field, syn in SYNONYMS.items():
        if columns and columns.get(field):
            pick[field] = next((c for c, low in heads.items() if columns[field].lower() in low), None)
        else:
            pick[field] = next((c for c, low in heads.items() if any(s in low for s in syn)), None)
    if pick["substation"] is None:
        raise ValueError(f"no substation column found in the table (headers: {list(df.columns)[:12]})")
    recs = []
    for _, r in df.iterrows():
        name = " ".join(str(r[pick["substation"]]).split())
        if not name or name.lower() in ("nan", "none"):
            continue
        rec = {c: "" for c in COLUMNS}
        rec.update(substation=re.sub(r"^(UW|Umspannwerk|Station)\s+", "", name), tso=tso, as_of=as_of, source_url=source_url)
        for key in ("feed_in", "load"):
            if pick[key] is not None:
                val = str(r[pick[key]])
                rng = class_to_range(val)
                if rng is None and re.fullmatch(rf"\s*({_NUM})(?:[.,]\d+)?\s*(MW)?\s*", val):
                    rng = (_to_int(re.match(rf"\s*({_NUM})", val).group(1)),) * 2
                if rng:
                    rec[f"{key}_free_from_mw"], rec[f"{key}_free_to_mw"] = rng
        if pick["status"] is not None:
            rec["connection_status"] = status_from_words(r[pick["status"]])
            rec["remark"] = " ".join(str(r[pick["status"]]).split())[:120]
        if pick["year"] is not None:
            m = re.search(r"20\d{2}", str(r[pick["year"]]))
            rec["available_from_year"] = m.group(0) if m else ""
        recs.append(rec)
    return pd.DataFrame(recs, columns=COLUMNS)


# ----------------------------------------------------------------------------- page with one block per substation (TransnetBW)
_BLOCK_TAGS = {"p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "h5", "h6", "br", "tr", "td", "th", "section", "article", "header", "footer", "dl", "dt", "dd", "table",
               "label", "figure", "figcaption", "button", "summary", "details", "nav", "main", "aside", "form"}
_MONTHS = {"januar": 1, "februar": 2, "märz": 3, "maerz": 3, "april": 4, "mai": 5, "juni": 6, "juli": 7, "august": 8, "september": 9, "oktober": 10, "november": 11, "dezember": 12}


def page_lines(page_html: str) -> list[str]:
    """Visible text of a page, one line per block element (heading, list item, paragraph ...), in the order of the page. Scripts and styles are left out."""
    doc = lxml_html.fromstring(page_html)
    for bad in doc.xpath("//script|//style|//noscript|//template"):
        bad.drop_tree()
    for el in doc.iter():
        if isinstance(el.tag, str) and el.tag.lower() in _BLOCK_TAGS:
            el.text = "\n" + (el.text or "")
            el.tail = "\n" + (el.tail or "")
    return [" ".join(line.split()) for line in doc.text_content().split("\n") if line.strip()]


def stated_date(text: str) -> str:
    """Date a publication states for itself: 'zum 01. April 2026' / '01.04.2026' -> 2026-04-01, 'Stand 05/2026' or 'Stand April 2026' -> first of that month. '' if none."""
    m = re.search(r"\b(\d{1,2})\.\s*(" + "|".join(_MONTHS) + r")\s+(20\d{2})", text, re.I)
    if m:
        return f"{m.group(3)}-{_MONTHS[m.group(2).lower()]:02d}-{int(m.group(1)):02d}"
    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(20\d{2})\b", text)
    if m:
        return f"{m.group(3)}-{int(m.group(2)):02d}-{int(m.group(1)):02d}"
    m = re.search(r"Stand:?\s*(\d{1,2})/(20\d{2})", text, re.I)
    if m:
        return f"{m.group(2)}-{int(m.group(1)):02d}-01"
    m = re.search(r"Stand:?\s*(" + "|".join(_MONTHS) + r")\s+(20\d{2})", text, re.I)
    if m:
        return f"{m.group(2)}-{_MONTHS[m.group(1).lower()]:02d}-01"
    return ""


def _mw(value: str):
    """'500 – 1.000 MW' -> (500, 1000), '< 500 MW' -> (0, 500), '0 MW' -> (0, 0); None if the text holds no capacity."""
    rng = class_to_range(value)
    if rng:
        return rng
    m = re.fullmatch(rf"\s*({_NUM})\s*(MW)?\s*", value)
    return (_to_int(m.group(1)),) * 2 if m else None


def parse_station_blocks(lines: list[str], status_map: dict, heading: str = r"Umspannwerk\s+", strip: str = r"^(Schaltanlage|Umspannwerk)\s+",
                         feed_in: str = "einspeisekapazität", load: str = "lastkapazität") -> list[dict]:
    """Blocks 'status line, heading with the name, lines field: value' (map of TransnetBW). The status stands in the line BEFORE the heading of its substation.

    Raises ValueError if a substation without a connection possibility carries capacities: then status and heading no longer belong together the way this
    reader assumes (the page was rebuilt) and nothing may be delivered.
    """
    words = sorted(status_map, key=len, reverse=True)
    rx_head = re.compile(rf"^{heading}(.+)$", re.I)
    rows, pending, cur, orphans = [], "", None, []
    for line in lines:
        low = line.lower()
        st = next((w for w in words if low.endswith(w.lower()) and len(line) <= len(w) + 6), None)       # the status line holds the status only (plus a symbol)
        m = rx_head.match(line)
        if st is not None:
            pending, cur = st, None
        elif m and len(line) < 70:
            if not pending:
                orphans.append(line)                                      # a substation without a status before it
                cur = None
                continue
            cur = {"substation": re.sub(strip, "", m.group(1).strip(), flags=re.I), "status_text": pending, "connection_status": status_map[pending], "remark": []}
            rows.append(cur)
            pending = ""
        elif cur is None:
            if (feed_in in low or load in low) and ":" in line and _mw(line.partition(":")[2]):
                orphans.append(line)                                      # a capacity that belongs to no substation
        elif cur is not None:
            key, _, value = line.partition(":")
            k = key.lower()
            if feed_in in k and _mw(value):
                cur["feed_in"] = _mw(value)
            elif load in k and _mw(value):
                cur["load"] = _mw(value)
            elif k.startswith("spannungsebene") and value.strip():
                cur["voltage"] = value.strip()
            elif low.startswith("inbetriebnahme") and re.search(r"20\d{2}", line):
                cur["year"] = re.search(r"20\d{2}", line).group(0)
            elif k.startswith("anschlussart") and value.strip():
                cur["remark"].append("Anschlussart " + value.strip())
            elif low.startswith("temporär"):
                cur["remark"].append(line)
            elif len(line) > 80 or not value:
                cur = None                                                # running text: the block of this substation has ended
    bad = [r["substation"] for r in rows if r["connection_status"] == "none" and ("feed_in" in r or "load" in r)]
    if bad or orphans:
        raise ValueError(f"status, name and capacities do not fit together any more (the layout of the page has changed): "
                         f"'no connection' with capacities {bad[:4]}, lines without a substation {orphans[:4]}")
    return rows


def block_rows(rows: list[dict], tso: str, as_of: str, source_url: str) -> pd.DataFrame:
    recs = []
    for r in rows:
        rec = {c: "" for c in COLUMNS}
        rec.update(substation=r["substation"], tso=tso, voltage_level=r.get("voltage", ""), as_of=as_of, source_url=source_url, connection_status=r["connection_status"],
                   available_from_year=r.get("year", ""), remark="; ".join([r["status_text"]] + r.get("remark", [])))
        for key in ("feed_in", "load"):
            if key in r:
                rec[f"{key}_free_from_mw"], rec[f"{key}_free_to_mw"] = r[key]
        recs.append(rec)
    return pd.DataFrame(recs, columns=COLUMNS)


# ----------------------------------------------------------------------------- PDF with one text row per substation (Amprion)
def parse_text_rows(text: str, row_pattern: str, remark_rules: list | None = None, default_status: str = "available") -> list[dict]:
    """Rows of a text table: row_pattern is a regular expression with the groups name and, optionally, kv, year, remark.

    remark_rules: [[words in the remark, status for feed-in, status for load], ...] turn a remark of the operator into a status per direction
    ('Es sind ausschließlich Lastanschlüsse möglich.' -> feed-in none, load available). Every listed substation otherwise gets default_status.
    """
    rx = re.compile(row_pattern)
    rows = []
    for line in text.splitlines():
        m = rx.match(" ".join(line.split()))
        if not m:
            continue
        g = m.groupdict()
        row = {"substation": g["name"].strip(), "voltage": (g.get("kv") or "").strip() and f"{g['kv'].strip()} kV", "year": (g.get("year") or "").strip(),
               "remark": (g.get("remark") or "").strip(), "connection_status": default_status, "status_feed_in": "", "status_load": ""}
        for words, st_feed, st_load in remark_rules or []:
            if re.search(words, row["remark"], re.I):
                row["status_feed_in"], row["status_load"] = st_feed, st_load
                break
        rows.append(row)
    return rows


def text_rows(rows: list[dict], tso: str, as_of: str, source_url: str) -> pd.DataFrame:
    recs = []
    for r in rows:
        rec = {c: "" for c in COLUMNS}
        rec.update(substation=r["substation"], tso=tso, voltage_level=r["voltage"], as_of=as_of, source_url=source_url, connection_status=r["connection_status"],
                   available_from_year=r["year"], remark=r["remark"], status_feed_in=r["status_feed_in"], status_load=r["status_load"])
        recs.append(rec)
    return pd.DataFrame(recs, columns=COLUMNS)
