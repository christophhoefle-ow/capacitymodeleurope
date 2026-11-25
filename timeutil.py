"""Zeitrechnung: deutscher Geschäftstag <-> UTC-Stunden.

JAO veröffentlicht in UTC, ein Geschäftstag läuft aber von Mitternacht bis Mitternacht
deutscher Zeit. Im Winter ist das 23:00 UTC bis 23:00 UTC, im Sommer 22:00 bis 22:00 UTC.
An den Tagen der Zeitumstellung hat der Tag 23 bzw. 25 Stunden – das ergibt sich hier
automatisch aus der Zeitzonen-Rechnung.
"""
from __future__ import annotations

from datetime import date, timedelta

import pandas as pd


def business_day_hours(tag: str, tz: str = "Europe/Berlin") -> list[pd.Timestamp]:
    """Alle Stundenanfänge (UTC) des Geschäftstags `tag` (Format JJJJ-MM-TT)."""
    day = pd.Timestamp(tag)
    start = day.tz_localize(tz).tz_convert("UTC")
    end = (day + pd.Timedelta(days=1)).tz_localize(tz).tz_convert("UTC")
    return list(pd.date_range(start, end, freq="h", inclusive="left"))


def day_range(first: str, last: str) -> list[str]:
    """Alle Kalendertage von `first` bis `last` (einschließlich) als Texte JJJJ-MM-TT."""
    a, b = date.fromisoformat(first), date.fromisoformat(last)
    if b < a:
        raise ValueError(f"Enddatum {last} liegt vor Startdatum {first}")
    return [(a + timedelta(days=i)).isoformat() for i in range((b - a).days + 1)]


def today_local(tz: str = "Europe/Berlin") -> str:
    return pd.Timestamp.now(tz=tz).date().isoformat()
