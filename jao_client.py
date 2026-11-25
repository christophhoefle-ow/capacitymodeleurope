"""Schlanker Client für die JAO Publication Tool API (Core-Region).

Umgesetzt nach dem offiziellen "JAO Publication Tool – API Usage and Best Practice Guide"
(Version 1.0, September 2026):

  * Auswahl nur über FromUtc / ToUtc, ein Geschäftstag = 24 stündliche Anfragen
  * Anfragen strikt nacheinander, kurze Pause dazwischen (max. 100 Anfragen/Minute)
  * Antwort immer auf das Feld "rejected" prüfen (kann auch bei HTTP 200 true sein)
  * Bei Fehlern mit wachsender Wartezeit wiederholen (10 s, 20 s, 40 s, 80 s), 400er nie unverändert
  * Vor dem Abruf über den Monitoring-Endpunkt prüfen, ob der Tag "Received" ist
  * Seit 19.11.2026 gilt: Take darf höchstens 100.000 betragen

Nicht öffentlich dokumentiert und deshalb defensiv behandelt:
  * Feldnamen der Zeilen (Groß-/Kleinschreibung) -> wird beim Einlesen ignoriert
  * Aufbau der Monitoring-Antwort -> unbekannte Antworten gelten als "unbekannt", nicht als Fehler
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional

import pandas as pd
import requests

from .aggregate import rows_to_frame
from .timeutil import business_day_hours

log = logging.getLogger("capmodel.jao")


class JaoError(RuntimeError):
    """Allgemeiner Fehler beim Abruf."""


class JaoRejected(JaoError):
    """JAO hat die Anfrage abgelehnt (rejected = true)."""


def _fmt(ts) -> str:
    return pd.Timestamp(ts).tz_convert("UTC").strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _canon(text) -> str:
    """'Final Computation' und 'finalComputation' sollen gleich sein."""
    return re.sub(r"[\s_\-/]", "", str(text)).casefold()


def _entries(payload) -> list:
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("data", "Data", "items", "Items", "results", "Results"):
            if isinstance(payload.get(key), list):
                return payload[key]
    return []


class JaoClient:
    def __init__(self, base_url: str, dataset: str = "finalComputation", pause_s: float = 0.7,
                 timeout_s: float = 330, max_retries: int = 4, take: int = 100000,
                 backoff_base_s: float = 10.0, token: Optional[str] = None,
                 session: Optional[requests.Session] = None):
        self.base_url = base_url.rstrip("/")
        self.dataset = dataset
        self.pause_s = pause_s
        self.timeout_s = timeout_s
        self.max_retries = max_retries
        self.take = min(int(take), 100000)       # JAO-Obergrenze
        self.backoff_base_s = backoff_base_s
        self.session = session or requests.Session()
        self.session.headers.update({
            "Accept": "application/json",
            "Accept-Encoding": "gzip",            # spart laut JAO etwa den Faktor 8 an Datenmenge
            "User-Agent": "kapazitaetsmodell-pipeline/0.1",
        })
        if token:
            # Handbuch v2.0 (04/2023): 'Authorization: Bearer <Token> (Optional for now)' – bei Bedarf über das Secret JAO_API_TOKEN
            self.session.headers["Authorization"] = f"Bearer {token}"
        self._last_request = 0.0

    # ------------------------------------------------------------------ Basis
    def _get(self, path: str, params: dict) -> dict | list:
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None
        for attempt in range(self.max_retries + 1):
            wait = self.pause_s - (time.monotonic() - self._last_request)
            if wait > 0:
                time.sleep(wait)
            try:
                resp = self.session.get(url, params=params, timeout=self.timeout_s)
                self._last_request = time.monotonic()
            except (requests.Timeout, requests.ConnectionError) as exc:
                self._last_request = time.monotonic()
                last_error = exc
                log.warning("Netzwerkfehler (%s), Versuch %d/%d", exc.__class__.__name__, attempt + 1,
                            self.max_retries + 1)
            else:
                if resp.status_code == 200:
                    return resp.json()
                if resp.status_code in (400, 404):
                    # Anfrage ist falsch -> unverändert wiederholen bringt nichts
                    raise JaoError(f"HTTP {resp.status_code} für {path} {params}: {resp.text[:300]}")
                last_error = JaoError(f"HTTP {resp.status_code}: {resp.text[:200]}")
                log.warning("HTTP %s, Versuch %d/%d", resp.status_code, attempt + 1, self.max_retries + 1)
                retry_after = resp.headers.get("Retry-After")
                if retry_after and retry_after.isdigit():
                    time.sleep(min(int(retry_after), 120))
            if attempt < self.max_retries:
                time.sleep(self.backoff_base_s * (2 ** attempt))
        raise JaoError(f"Abruf nach {self.max_retries + 1} Versuchen gescheitert: {last_error}")

    # ------------------------------------------------------------- Monitoring
    def monitoring_status(self, tag: str) -> Optional[str]:
        """'received' | 'expected' | 'pending' | 'fallback' | None (unklar).

        Statuswerte laut Handbuch Kap. 6: Expected, Received, Pending sowie 'Spanning/DFP' (JAO hat für diese
        Stunden das Backup-Verfahren genutzt; die Domain-Seiten bleiben dann leer). Der Aufruf folgt dem Beispiel im
        JAO-Leitfaden (UTC-Mitternacht bis UTC-Mitternacht).
        """
        day = pd.Timestamp(tag)
        params = {"FromUtc": _fmt(day.tz_localize("UTC")),
                  "ToUtc": _fmt((day + pd.Timedelta(days=1)).tz_localize("UTC"))}
        try:
            payload = self._get("/system/monitoring", params)
        except JaoError as exc:
            log.warning("Monitoring nicht abrufbar (%s) – fahre ohne Monitoring fort", exc)
            return None
        statuses = []
        for e in _entries(payload):
            if not isinstance(e, dict):
                continue
            d = {str(k).lower(): v for k, v in e.items()}
            if _canon(d.get("page", "")) != _canon(self.dataset):
                continue
            stamp = next((str(d[k]) for k in ("businessday", "date", "day") if k in d), None)
            if stamp and not stamp.startswith(tag):
                continue
            statuses.append(_canon(d.get("status", "")))
        if not statuses:
            return None
        if any("spanning" in s or "dfp" in s for s in statuses):
            return "fallback"
        if "pending" in statuses:
            return "pending"
        if "expected" in statuses:
            return "expected"
        return "received" if all(s == "received" for s in statuses) else None

    def monitoring_received(self, tag: str) -> Optional[bool]:
        """Kurzform: True = komplett, False = noch nicht (oder Fallback), None = unklar."""
        status = self.monitoring_status(tag)
        if status is None:
            return None
        return status == "received"

    # ------------------------------------------------------------------ Daten
    def fetch_hour(self, start_utc) -> list[dict]:
        """Alle Zeilen einer Stunde (ganz Core, noch ungefiltert)."""
        start = pd.Timestamp(start_utc)
        params = {"FromUtc": _fmt(start), "ToUtc": _fmt(start + pd.Timedelta(hours=1))}
        path = f"/data/{self.dataset}"
        payload = self._get(path, params)
        if isinstance(payload, dict) and payload.get("rejected"):
            raise JaoRejected(f"JAO lehnt Anfrage ab: {payload.get('messages')}")
        rows = list(_entries(payload))
        total = payload.get("totalRows") if isinstance(payload, dict) else None
        if total is not None and len(rows) < int(total):
            # Teilantwort -> seitenweise nachladen (Skip/Take, Take höchstens 100.000)
            rows, skip = [], 0
            while skip < int(total):
                page_payload = self._get(path, {**params, "Skip": skip, "Take": self.take})
                if isinstance(page_payload, dict) and page_payload.get("rejected"):
                    raise JaoRejected(f"JAO lehnt Seitenabruf ab: {page_payload.get('messages')}")
                page = list(_entries(page_payload))
                if not page:
                    break
                rows.extend(page)
                skip += len(page)
            if len(rows) < int(total):
                raise JaoError(f"Unvollständige Stunde {start}: {len(rows)} von {total} Zeilen")
        return rows

    def fetch_day(self, tag: str, tsos, tz: str = "Europe/Berlin"):
        """Einen Geschäftstag abrufen.

        Rückgabe: (DataFrame der Zeilen der gewünschten ÜNB, erwartete Stunden, Stunden mit Daten)
        """
        hours = business_day_hours(tag, tz)
        frames, with_data = [], 0
        for h in hours:
            frame = rows_to_frame(self.fetch_hour(h), tsos, hour_utc=h)
            if not frame.empty:
                with_data += 1
                frames.append(frame)
        result = pd.concat(frames, ignore_index=True) if frames else rows_to_frame([], tsos)
        return result, len(hours), with_data
