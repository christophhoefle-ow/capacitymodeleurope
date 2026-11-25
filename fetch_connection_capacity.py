#!/usr/bin/env python3
"""Fetch the connection-capacity publications of the TSOs, fully automatic (no hand-maintained table).

1. Register: the operator pages of Capacitypedia (ENTSO-E and DSO Entity) for every Core TSO -> data/processed/connection_publications.csv
   (what each TSO publishes, where, in which format, with or without interface, how often).
2. Values per substation: every source of config/connection_sources.yml -> data/interim/connection/<id>.csv in the columns of the data contract.
   scripts/build_processed.py then writes data/processed/grid_connection_tso.csv (sheet D_Connection of the Excel model).
A source that cannot be read keeps its last good file and is reported in data/interim/connection/status.csv; the script then ends with exit code 1
so that the GitHub action can raise an issue. Nothing is guessed: a row is only written if the publication says so.

  python scripts/fetch_connection_capacity.py                 # everything
  python scripts/fetch_connection_capacity.py --only 50hertz  # one source
  python scripts/fetch_connection_capacity.py --no-register   # skip the directory
"""
from __future__ import annotations

import argparse
import io
import logging
import re
import sys
import time
from datetime import datetime, timezone
from urllib.parse import urljoin

import pandas as pd
import requests
import yaml
from lxml import html as lxml_html

import _common as common
from capmodel import harvest
from capmodel.connection import COLUMNS

log = logging.getLogger("connection")
UA = {"User-Agent": "capacity-model-pipeline/0.3 (public data, one request per page)"}
STATUS_COLUMNS = ["id", "tso", "adapter", "status", "rows", "with_mw", "as_of", "url", "detail", "fetched_utc"]


BROWSER_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36"


def get(url: str, binary: bool = False, timeout: int = 90):
    r = requests.get(url, headers=UA, timeout=timeout)
    r.raise_for_status()
    if binary:
        return r.content
    if "charset" not in r.headers.get("content-type", "").lower():      # a server that names no character set: requests would read umlauts as Latin-1
        try:
            return r.content.decode("utf-8")
        except UnicodeDecodeError:
            r.encoding = r.apparent_encoding
    return r.text


def get_rendered(url: str, timeout_ms: int = 60000) -> str:
    """Page as a browser shows it (headless Chromium via Playwright): for pages that build their content with scripts or turn away plain requests.
    Needs 'pip install playwright' and 'playwright install chromium' (the GitHub action installs both)."""
    from playwright.sync_api import sync_playwright
    with sync_playwright() as pw:
        browser = pw.chromium.launch()
        try:
            page = browser.new_page(user_agent=BROWSER_UA, locale="de-DE")
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=20000)
            except Exception:                                          # noqa: BLE001 - a page that keeps loading: take what is there
                pass
            return page.content()
        finally:
            browser.close()


def get_page(src: dict) -> tuple[str, str]:
    """(html, how it was read). Plain request first; the browser if the source asks for it (browser: true) or the plain request is refused."""
    if not src.get("browser"):
        try:
            return get(src["page"]), "request"
        except Exception as exc:                                       # noqa: BLE001
            log.warning("%s: plain request failed (%s), trying the browser", src["id"], exc)
    return get_rendered(src["page"]), "browser"


def apply_name_map(df: pd.DataFrame, src: dict) -> pd.DataFrame:
    """Names of the publication that the model spells differently (name_map of the source: publication -> model)."""
    nm = {str(k).casefold(): v for k, v in (src.get("name_map") or {}).items()}
    df["substation"] = [nm.get(str(n).casefold(), n) for n in df["substation"]]
    return df


def now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")


# ----------------------------------------------------------------------------- register (Capacitypedia)
def operator_pages(country_html: str, country_url: str) -> list[tuple[str, str]]:
    """(name, address) of the operator pages linked on a country page of the directory."""
    doc = lxml_html.fromstring(country_html)
    path = country_url.rstrip("/").split("/capacitypedia/")[1]
    out = []
    for a in doc.iter("a"):
        href = urljoin(country_url, a.get("href") or "")
        if re.fullmatch(rf".*/capacitypedia/{re.escape(path)}/[^/#?]+", href):
            out.append((" ".join(a.text_content().split()), href))
    return list(dict.fromkeys(out))


def fetch_register(cfg: dict, tso_country: dict) -> tuple[pd.DataFrame, list[str]]:
    rows, problems = [], []
    for country, tsos in cfg["operators"].items():
        url = f"{cfg['base'].rstrip('/')}/{country}"
        try:
            pages = operator_pages(get(url), url)
        except Exception as exc:                                       # noqa: BLE001
            problems.append(f"directory page {country}: {exc}")
            continue
        for tso, words in tsos.items():
            cands = [(n, u) for n, u in pages if any(w in n.lower() or w in u.rsplit("/", 1)[-1].lower() for w in words)]
            hit = None
            for name, page in cands:
                time.sleep(float(cfg.get("pause_seconds", 1.0)))
                try:
                    text = get(page)
                except Exception as exc:                               # noqa: BLE001
                    problems.append(f"{tso}: {page}: {exc}")
                    continue
                if len(cands) == 1 or any(re.match(r"TSO\s*[-\u2013]", line) for line in harvest.page_lines(text)):      # an operator can have a TSO and a DSO page (Creos): the page says 'TSO - country'
                    hit = (page, harvest.parse_capacitypedia(text))
                    break
            if hit is None:
                rows.append({"tso": tso, "country": tso_country.get(tso, ""), "publication_status": "no page in the directory", "page": url, "fetched_utc": now()})
            else:
                rows.append({"tso": tso, "country": tso_country.get(tso, ""), **hit[1], "page": hit[0], "fetched_utc": now()})
    listed = {r["tso"] for r in rows}
    rows += [{"tso": t, "country": c, "publication_status": "no page in the directory", "page": cfg["base"], "fetched_utc": now()} for t, c in tso_country.items() if t not in listed]
    return pd.DataFrame(rows).reindex(columns=harvest.REGISTER_COLUMNS).fillna("").sort_values(["country", "tso"]), problems


# ----------------------------------------------------------------------------- adapters
def find_pdf(src: dict) -> tuple[str | None, list, str]:
    """Address of the PDF of a source: the newest matching link on its page (plain request, then browser), otherwise the last known address."""
    note, links = "", []
    for how in ((get,) if src.get("browser") is False else (get, get_rendered)):
        try:
            links = [u for u in harvest.find_links(how(src["page"]), src["page"], src["link_pattern"]) if u.lower().split("?")[0].endswith(".pdf")]
        except Exception as exc:                                       # noqa: BLE001
            note += f"page not readable with {how.__name__} ({exc.__class__.__name__}); "
        if links:
            break
    return harvest.newest(links) or src.get("last_known_url"), links, note


def adapter_pdf_rows(src: dict) -> tuple[pd.DataFrame, dict]:
    """PDF with one text row per substation (Amprion: substations where a connection is expected to be feasible)."""
    url, links, note = find_pdf(src)
    if not url:
        raise RuntimeError(note + "no link to the PDF found on the page and no last known address configured")
    if url not in links:
        note += "link not found on the page: last known address used; "
    text = harvest.pdf_text(get(url, binary=True))
    rows = harvest.parse_text_rows(text, src["row_pattern"], src.get("remark_rules"), src.get("default_status", "available"))
    as_of = harvest.stated_date(text) or harvest.date_in_name(url) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    return harvest.text_rows(rows, src["tso"], as_of, url), {"url": url, "as_of": as_of, "detail": (note + "status per substation and direction, earliest year").strip(), "with_mw": 0}


def adapter_page_blocks(src: dict) -> tuple[pd.DataFrame, dict]:
    """Page with one block per substation: status, name, capacities as text (TransnetBW)."""
    html, how = get_page(src)
    lines = harvest.page_lines(html)
    rows = harvest.parse_station_blocks(lines, src["status_map"])
    as_of = harvest.stated_date(" ".join(lines)) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    df = harvest.block_rows(rows, src["tso"], as_of, src["page"])
    return df, {"url": src["page"], "as_of": as_of, "detail": f"status and MW classes per substation (read by {how})", "with_mw": int((df["feed_in_free_from_mw"].astype(str) != "").any())}


def adapter_pdf_status(src: dict) -> tuple[pd.DataFrame, dict]:
    url, links, note = find_pdf(src)
    if not url:
        raise RuntimeError(note + "no link to the PDF found on the page and no last known address configured")
    if url not in links:
        note += "link not found on the page: last known address used; "
    data = get(url, binary=True)
    rows = harvest.parse_status_text(harvest.pdf_text(data), src["status_map"])
    classes = {}
    if src.get("class_labels"):
        try:
            classes = harvest.pdf_color_classes(data, src["class_labels"], [r["substation"] for r in rows])
        except Exception as exc:                                       # noqa: BLE001 - the colours are an extra; the status in words is the delivery
            note += f"MW classes not read ({exc.__class__.__name__}); "
    as_of = harvest.date_in_name(url) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    df = harvest.status_rows(rows, src["tso"], as_of, url, src.get("voltage_level", ""), classes)
    with_mw = int((df["feed_in_free_from_mw"].astype(str) != "").sum() + (df["load_free_from_mw"].astype(str) != "").sum() > 0)
    return df, {"url": url, "as_of": as_of, "detail": (note + ("status and MW classes" if with_mw else "status in words (MW classes are cell colours: not read)")).strip(), "with_mw": with_mw}


def adapter_table(src: dict) -> tuple[pd.DataFrame, dict]:
    page, how = get_page(src)
    url, frames = src["page"], []
    if src.get("link_pattern"):
        url = harvest.newest(harvest.find_links(page, src["page"], src["link_pattern"]))
        if not url:
            raise RuntimeError("no link matching link_pattern on the page")
        raw = get(url, binary=True)
        frames = [pd.read_excel(io.BytesIO(raw), dtype=str)] if url.lower().endswith((".xlsx", ".xls")) else [pd.read_csv(io.BytesIO(raw), dtype=str, sep=None, engine="python")]
    else:
        frames = pd.read_html(io.StringIO(page), match=src.get("table_match", ".+"))
    as_of = harvest.date_in_name(url) or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    as_of = harvest.stated_date(" ".join(harvest.page_lines(page))) or as_of
    df = pd.concat([harvest.table_rows(f.astype(str), src["tso"], as_of, url, src.get("columns")) for f in frames], ignore_index=True)
    if src.get("default_status"):                                      # a table that lists only sites where a connection is possible
        df.loc[df["connection_status"] == "", "connection_status"] = src["default_status"]
    return df, {"url": url, "as_of": as_of, "detail": f"{len(frames)} table(s), read by {how}", "with_mw": int((df["feed_in_free_from_mw"] != "").any() or (df["load_free_from_mw"] != "").any())}


ADAPTERS = {"pdf_status": adapter_pdf_status, "pdf_rows": adapter_pdf_rows, "page_blocks": adapter_page_blocks, "table": adapter_table}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", help="id of one source")
    ap.add_argument("--no-register", action="store_true", help="do not read the directory (Capacitypedia)")
    args = ap.parse_args()
    common.setup_logging()
    cfg = yaml.safe_load((common.ROOT / "config" / "connection_sources.yml").read_text(encoding="utf-8"))
    tso_country = {k.upper(): v for k, v in common.load_config()["region"]["tsos"].items()}
    out_dir = common.ROOT / "data" / "interim" / "connection"
    out_dir.mkdir(parents=True, exist_ok=True)
    failed = 0
    if not args.no_register and not args.only:
        try:
            reg, problems = fetch_register(cfg["directory"], tso_country)
            for p_ in problems:
                log.warning("directory: %s", p_)
            if (reg["link"] != "").any():                             # only replace the register if the directory could be read at all
                reg.to_csv(common.ROOT / "data" / "processed" / "connection_publications.csv", index=False, lineterminator="\n", encoding="utf-8")
                log.info("register: %d TSOs, %d with a publication page", len(reg), int((reg["link"] != "").sum()))
            else:
                failed += 1
                log.error("directory not readable: register unchanged")
        except Exception as exc:                                       # noqa: BLE001
            failed += 1
            log.error("directory: %s", exc)
    status_file = out_dir / "status.csv"
    status = pd.read_csv(status_file, dtype=str, keep_default_na=False) if status_file.exists() else pd.DataFrame(columns=STATUS_COLUMNS)
    for src in cfg.get("sources") or []:
        if not src.get("enabled", True) or (args.only and src["id"] != args.only):
            continue
        entry = {"id": src["id"], "tso": src["tso"], "adapter": src["adapter"], "fetched_utc": now()}
        try:
            df, info = ADAPTERS[src["adapter"]](src)
            df = apply_name_map(df, src)
            if not src.get("verified", True):
                info["detail"] = "reader not yet verified on the real publication; " + info["detail"]
            if len(df) < int(src.get("min_rows", 1)):
                raise RuntimeError(f"only {len(df)} rows read, at least {src.get('min_rows', 1)} expected: layout of the publication changed?")
            df[COLUMNS].to_csv(out_dir / f"{src['id']}.csv", index=False, lineterminator="\n", encoding="utf-8")
            entry.update(status="ok", rows=len(df), **info)
            log.info("%s: %d substations, as of %s (%s)", src["id"], len(df), info["as_of"], info["detail"])
        except Exception as exc:                                       # noqa: BLE001 - one source must not stop the others
            failed += 1
            old = status[status["id"] == src["id"]]
            kept = (out_dir / f"{src['id']}.csv").exists()
            entry.update(status="failed, last good file kept" if kept else "failed, no data", rows=old["rows"].iloc[0] if len(old) else 0, with_mw=old["with_mw"].iloc[0] if len(old) else 0,
                         as_of=old["as_of"].iloc[0] if len(old) else "", url=old["url"].iloc[0] if len(old) else src.get("page", ""), detail=f"{exc.__class__.__name__}: {exc}"[:300])
            log.error("%s: %s", src["id"], entry["detail"])
        status = pd.concat([status[status["id"] != src["id"]], pd.DataFrame([entry])], ignore_index=True)
    status.reindex(columns=STATUS_COLUMNS).fillna("").sort_values("id").to_csv(status_file, index=False, lineterminator="\n", encoding="utf-8")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
