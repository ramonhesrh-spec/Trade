"""Waarom een kaart eindigde zonder vulling, in gewone woorden. Eén zuivere vertaling voor elke stand van Zone-radar, Zone-sweep, POC-radar en
Structuur, zodat Kansen, het anker van een melding en het Logboek hetzelfde zeggen. tests/test_basis_afsluiten.py leest elke stand uit de code en
eist hier een tekst. De termijnen komen uit de motoren zelf, geen tweede kopie."""
from app import poc_radar, zone_sweep
from app.replay import breakretest

KINDS = ("structuur", "zone_radar", "zone_sweep", "poc_radar")
LABELS = {"structuur": "Structuur", "zone_radar": "Zone-radar", "zone_sweep": "Zone-sweep", "poc_radar": "POC-radar"}


def _hours(td) -> int:
    return int(td.total_seconds() // 3600)


def _span(td) -> str:
    h = _hours(td)
    return f"{h // 24} dagen" if h >= 48 and h % 24 == 0 else f"{h} uur"


STRUCTURE_RETEST_HOURS = breakretest.RETEST_BARS * 30 // 60      # RETEST_BARS candles van 30m (structure_live.BAR)

# Standen op een kaart die de motor nog niet omzette: radar.setup_state en today.structure_state rekenen ze uit de koers (trade_plan.STATE_LABELS).
_SHOWN = {
    "door_zone": "De koers ging door de zone heen.",
    "ongeldig": "De koers raakte de stop voordat je limiet vulde.",
    "doel_geraakt": "Het doel werd gehaald voordat je limiet vulde.",
}

_TEXTS = {
    "structuur": {
        "expired": f"Na {STRUCTURE_RETEST_HOURS} uur niet gevuld: de koers kwam niet terug naar het niveau.",
        "verlopen": f"Na {STRUCTURE_RETEST_HOURS} uur niet gevuld: de koers kwam niet terug naar het niveau.",
        "niet_gemeld": "Niet gemeld: het maximum aantal meldingen per dag was bereikt.",
        "overgeslagen": "De stop lag bij de vulling te ver weg.",
        "geen_oordeel": "Niet gemeld.",
        "geen_plan": "Geen plan: te weinig ruimte tot het doel of de stop te ver weg.",
        "schaduw": "Stil gevolgd, zonder melding.",
    },
    "zone_radar": {
        "zone_weg": "De zone is gebroken of te oud geworden.",
    },
    "zone_sweep": {
        "verlopen": f"Na {_span(zone_sweep.TTL)} niet gevuld.",
        "weggelopen": "De koers liep weg naar het midden zonder je limiet te raken.",
        "stop_voor_vulling": "De koers ging voorbij de stop voordat je limiet vulde.",
    },
    "poc_radar": {
        "verlopen": f"Na {_span(poc_radar.TTL)} niet gevuld.",
    },
}


def text(kind: str, state: str) -> str:
    """De reden in één korte zin; een onbekende stand krijgt een neutrale zin in plaats van een technische naam."""
    return _TEXTS.get(kind, {}).get(state) or _SHOWN.get(state) or "Niet meer actief."
