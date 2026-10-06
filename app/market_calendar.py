"""Voorspelbare momenten waar de markt zich vaak anders gedraagt: funding-resets, opening van de VS-beurs, maandelijkse
opties-expiry en macro-uitslagen (CPI, FOMC) uit data/macro_events.csv. Dit bestand vult de gebruiker zelf, ik verzin geen
datums: kolommen `at` (ISO, UTC) en `label`. Of een moment ook iets oplevert bepaalt de toets in
app/replay/strategy_scan.py, dit bestand levert alleen de tijden."""
import csv
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterator
from zoneinfo import ZoneInfo

from app import config

NEW_YORK = ZoneInfo("America/New_York")
MACRO_FILE = Path(config.BASE_DIR) / "data" / "macro_events.csv"
FUNDING_HOURS = (0, 8, 16)
# Dagen waarop de Amerikaanse beurs dicht is: dan is er geen opening. Alleen 2026, de lijst van NYSE; zie nyse.com/markets/hours-calendars.
US_MARKET_HOLIDAYS = {
    "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19", "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
}

LABELS = {
    "funding": "Funding-reset",
    "vs_open": "Opening VS-beurs",
    "opties_expiry": "Opties-expiry (maand)",
    "macro": "Macro-uitslag",
}


def _last_friday(year: int, month: int) -> datetime:
    first_next = datetime(year + (month == 12), month % 12 + 1, 1, tzinfo=timezone.utc)
    day = first_next - timedelta(days=1)
    return day - timedelta(days=(day.weekday() - 4) % 7)


def macro_moments() -> list[dict]:
    if not MACRO_FILE.exists():
        return []
    out = []
    with MACRO_FILE.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            try:
                at = datetime.fromisoformat(row["at"].strip())
            except (KeyError, ValueError):
                continue
            at = at if at.tzinfo else at.replace(tzinfo=timezone.utc)
            out.append({"at": at.astimezone(timezone.utc), "kind": "macro", "label": (row.get("label") or LABELS["macro"]).strip()})
    return out


def moments(start: datetime, end: datetime) -> list[dict]:
    """Alle momenten in [start, end], oplopend op tijd. start en end zijn tijdzone-bewust."""
    out = []
    day = start.astimezone(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(days=1)
    while day <= end:
        for h in FUNDING_HOURS:
            out.append({"at": day + timedelta(hours=h), "kind": "funding", "label": LABELS["funding"]})
        if day.weekday() < 5 and day.strftime("%Y-%m-%d") not in US_MARKET_HOLIDAYS:
            ny = datetime(day.year, day.month, day.day, 9, 30, tzinfo=NEW_YORK)
            out.append({"at": ny.astimezone(timezone.utc), "kind": "vs_open", "label": LABELS["vs_open"]})
        expiry = _last_friday(day.year, day.month).replace(hour=8)
        if expiry.date() == day.date():
            out.append({"at": expiry, "kind": "opties_expiry", "label": LABELS["opties_expiry"]})
        day += timedelta(days=1)
    out += macro_moments()
    return sorted((m for m in out if start <= m["at"] <= end), key=lambda m: m["at"])


def upcoming(now: datetime, hours: float = 24) -> list[dict]:
    return moments(now, now + timedelta(hours=hours))
