"""Focus: welke soorten nog nieuwe kansen zoeken en melden. Eén bron van waarheid voor motoren, weergave en Bewijs.

Besluit van de CEO (oktober 2026, live cijfers uit scripts/winnaars.py): alleen Structuur A/B, Structuur C, de zone-radar en de zone-sweep (live, ongetest, op verzoek van de CEO zonder labrun) melden nog iets nieuws.
Alle andere soorten staan uit om ze later één voor één te verbeteren. Uitzetten is geen weggooien: de
code en de data blijven, open trades lopen door tot ze sluiten (level_check, rule_live.update_open, range_sweep_live.track/follow), en
ENGINE_FOCUS=false zet alles terug zoals het was. Geen database of netwerk hier; config wordt pas bij de aanroep gelezen, zodat een test hem kan zetten."""
from typing import Iterable, Optional

from app import config

FOCUS_TYPES = ("structuur", "structuur_c", "zone_radar", "zone_sweep")
LABELS = {"structuur": "Structuur A/B", "structuur_c": "Structuur C", "zone_radar": "Zone-radar", "zone_sweep": "Zone-sweep"}
# Wat een uitgezette motor in zijn hartslag zet (engine_heartbeat, scripts/push_diag.py) en in het log.
OFF_DETAIL = "uit door focus"


def active(focus_on: Optional[bool] = None) -> bool:
    return config.ENGINE_FOCUS if focus_on is None else focus_on


def is_focus(trade_type: Optional[str]) -> bool:
    return trade_type in FOCUS_TYPES


def engine_on(trade_type: str, enabled: bool = True, focus_on: Optional[bool] = None) -> bool:
    """Mag de motor van deze soort nieuwe kansen zoeken? Zijn eigen vlag (TREND_ENABLED enz.) gaat altijd voor; focus zet alleen verder uit."""
    return bool(enabled) and (not active(focus_on) or is_focus(trade_type))


def label(trade_type: str) -> str:
    if trade_type in LABELS:
        return LABELS[trade_type]
    from app.track_record import TYPE_LABELS      # pas hier: track_record trekt meer mee dan deze kleine module nodig heeft
    return TYPE_LABELS.get(trade_type, trade_type)


def split(rows: Iterable[dict], key: str = "trade_type", focus_on: Optional[bool] = None) -> tuple[list[dict], list[dict]]:
    """(focus, uitgezet) in de oorspronkelijke volgorde. Zonder focus staat alles vooraan: dan is er niets uitgezet. Er valt nooit iets weg."""
    rows = list(rows)
    if not active(focus_on):
        return rows, []
    return [r for r in rows if is_focus(r.get(key))], [r for r in rows if not is_focus(r.get(key))]
