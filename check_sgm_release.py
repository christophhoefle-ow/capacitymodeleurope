#!/usr/bin/env python3
"""Prüft, ob JAO ein neues Core Static Grid Model (SGM) veröffentlicht hat.

Das SGM erscheint halbjährlich (Kennung JJJJ03 bzw. JJJJ09, z. B. '202603_..._9th release.zip').
Dieses Skript lädt NICHTS herunter und ändert KEINE Daten. Es meldet nur, ob die neueste Release
auf https://www.jao.eu/static-grid-model neuer ist als die in data/manual/sgm_release.txt vermerkte.
Der Workflow legt dann ein GitHub-Issue an – die eigentliche Übernahme prüft ein Mensch, weil sich
Spalten oder Schreibweisen ändern können.
"""
from __future__ import annotations

import os
import re
import sys
from urllib.parse import unquote, urljoin

import requests

import _common as common

SGM_PAGE = "https://www.jao.eu/static-grid-model"
_RELEASE_RE = re.compile(r"(?P<ym>\d{6})_Core.*?(?P<n>\d{1,2})(?:st|nd|rd|th)\s*release", re.I)


def find_latest_release(html: str, base: str = "https://www.jao.eu") -> dict | None:
    """Neueste (nicht als 'outdated' markierte) Release aus dem HTML der JAO-Seite."""
    hrefs = re.findall(r'href=["\']([^"\']+?\.zip)["\']', html, flags=re.I)
    hrefs += re.findall(r"\((https?://[^)\s]+?\.zip)\)", html, flags=re.I)   # Markdown-Links (Tests)
    best = None
    for href in hrefs:
        filename = unquote(href.rsplit("/", 1)[-1])
        if filename.lower().startswith("outdated"):
            continue
        m = _RELEASE_RE.search(filename)
        if not m:
            continue
        cand = {"release": int(m.group("n")), "ym": m.group("ym"), "filename": filename,
                "label": f"{m.group('ym')}, release {int(m.group('n'))}", "url": urljoin(base, href)}
        if best is None or cand["release"] > best["release"]:
            best = cand
    return best


def parse_label(text: str) -> int | None:
    """Release number from a note such as '202603, release 9' (older notes like '202603 - 9. Release' also work)."""
    m = re.search(r"release\s*(\d{1,2})|(\d{1,2})\.\s*release|(\d{1,2})(?:st|nd|rd|th)\s*release", text or "", re.I)
    return int(next(g for g in m.groups() if g)) if m else None


def main() -> int:
    html = requests.get(SGM_PAGE, timeout=60, headers={"User-Agent": "kapazitaetsmodell-pipeline/0.1"}).text
    latest = find_latest_release(html)
    if latest is None:
        print("FEHLER: Keine Release-Datei auf der JAO-Seite gefunden – Seitenaufbau geändert?")
        return 1
    known_file = common.ROOT / "data" / "manual" / "sgm_release.txt"
    known = parse_label(known_file.read_text(encoding="utf-8")) if known_file.exists() else None
    is_new = known is None or latest["release"] > known
    print(f"Bekannt: {known}. Release | Neueste auf JAO: {latest['label']} | neu: {is_new}")
    out = os.environ.get("GITHUB_OUTPUT")
    if out:
        with open(out, "a", encoding="utf-8") as fh:
            fh.write(f"new_release={'true' if is_new else 'false'}\nlabel={latest['label']}\nurl={latest['url']}\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
