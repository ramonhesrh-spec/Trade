"""Hoeveel kansen een dagcap tegenhield, als tekst voor de hartslag en Beheer. Zuiver; de telling zelf staat in de tabel cap_holds (repo).

Waarom: op 29 oktober 2026 hield de volle Structuur-cap de WLD-breuk tegen (status niet_gemeld) zonder dat iemand het zag. De CEO wil elke kans
zien en zelf kiezen; deze telling laat zien of een cap nog knelt. Een kans telt één keer per venster, ook als elke cyclus hem opnieuw ziet."""
from datetime import timedelta

# Dezelfde 24 uur als de caps zelf (count_..._since(now - 24 uur)).
WINDOW = timedelta(hours=24)
LABELS = {"structuur": "Structuur", "zone_radar": "Zone-radar", "zone_sweep": "Zone-sweep", "poc_radar": "POC-radar"}


def held_text(n: int, cap: int) -> str:
    if not n:
        return ""
    return f"{n} {'kans' if n == 1 else 'kansen'} tegengehouden door de dagcap van {cap}"


def with_held(detail: str, n: int, cap: int) -> str:
    return f"{detail}; {held_text(n, cap)}" if n else detail


def lines(counts: dict, caps: dict) -> list[dict]:
    return [{"label": label, "text": held_text(counts[k], caps.get(k, 0))} for k, label in LABELS.items() if counts.get(k)]
