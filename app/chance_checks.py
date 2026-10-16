"""Gemeten kenmerken per kans, in dezelfde ✓/✗-vorm als de oude technische factoren: elk kenmerk is een feit dat bij het melden gemeten werd
(volume, trend, aantal aanrakingen, ruimte tot het doel), geen schatting. Het percentage telt alleen hoeveel kenmerken kloppen.

Eerlijk over wat het niet is: het onderzoek (scripts/breakretest_scan.py, scripts/trendpullback_scan.py) liet zien dat deze kenmerken op een jaar
candles geen stabiele voorspeller van winst waren. Daarom komt de score als beschrijving op de kaart en wordt hij per kans bewaard (pass_pct):
Bewijs kan zo tonen of een hogere score ook echt vaker wint, in plaats van dat wij het aannemen."""
import json
from typing import Optional

from app.replay.rangesweep import AGE_MIN

Check = tuple[str, bool]


def finish(checks: list[Check]) -> tuple[str, float]:
    """(reason in ' | '-vorm met ✓/✗, percentage dat klopt). De template-macro reason_factors leest precies deze vorm."""
    reason = " | ".join(("✓ " if ok else "✗ ") + label for label, ok in checks)
    return reason, 100.0 * sum(1 for _, ok in checks if ok) / len(checks)


def structure_checks(features: Optional[dict], plan: dict, grade: Optional[str]) -> list[Check]:
    f = features or {}
    r_list = plan.get("targets_r") or []
    return [
        ("Volume van de breuk minstens 1,5x gemiddeld", float(f.get("vol_ratio", 0)) >= 1.5),
        ("Mee met de trend (EMA21 boven EMA200 voor long)", bool(f.get("with_trend"))),
        ("Lijn of range minstens 3 keer aangeraakt", int(f.get("touches", 0)) >= 3),
        ("Structuur minstens 12 candles lang", int(f.get("span", 0)) >= 12),
        ("Doelen liggen op zwaaipunten", bool(plan.get("from_levels"))),
        ("Tweede doel minstens 2R ver", len(r_list) > 1 and r_list[1] >= 2.0),
        ("De CEO keurt goed (A of B)", grade in ("A", "B")),
    ]


def parse_features(raw: Optional[str]) -> dict:
    try:
        return json.loads(raw) if raw else {}
    except (TypeError, ValueError):
        return {}


def trend_checks(direction: str, entry: float, stop: float, extreme: float) -> list[Check]:
    risk = abs(entry - stop)
    sign = 1 if direction == "long" else -1
    room = sign * (extreme - entry) / risk if risk else 0.0
    risk_pct = risk / entry * 100 if entry else 0.0
    return [
        ("Trend op 4 uur en 1 uur wijst dezelfde kant op", True),
        ("Top van de impuls minstens 1,5R verder dan de instap", room >= 1.5),
        ("Stopafstand tussen 0,3% en 1,5% (niet krap, niet ruim)", 0.3 <= risk_pct <= 1.5),
    ]


def script_checks(direction: str, entry: float, stop: float, take: float, bias: Optional[str]) -> list[Check]:
    risk = abs(entry - stop)
    rr = abs(take - entry) / risk if risk else 0.0
    risk_pct = risk / entry * 100 if entry else 0.0
    return [
        ("R:R minstens 2", rr >= 2.0),
        ("Stopafstand minstens 0,3%", risk_pct >= 0.3),
        ("Richting past bij de bias van het script", bias == direction),
    ]


def smc_checks(rr: float, risk_pct: float, has_sniper: bool, warning: bool) -> list[Check]:
    return [
        ("Structuurbreuk en sweep op 30m gezien", True),
        ("Afwijzing in de zone op 15m", not warning),
        ("R:R minstens 2", rr >= 2.0),
        ("Stopafstand minstens 0,3%", risk_pct >= 0.3),
        ("Sniper-prijs gevonden", has_sniper),
    ]


WeightedCheck = tuple[str, bool, int]
GRADE_A, GRADE_B = 80.0, 60.0


def range_sweep_checks(f: dict, tf: str) -> list[WeightedCheck]:
    """Onze lezing van "Range 40% order block 60%" (docs/onderzoek/range-sweep/preregistratie.md): 40 punten voor de range, 60 voor de zone.
    Elk kenmerk is gemeten bij het plaatsen van de order. Het lab en Bewijs tonen per graad of een hoge score een betere stop geeft; aangenomen wordt het niet."""
    age_min = AGE_MIN[tf]
    return [
        ("Beide randen minstens 4 keer aangeraakt", min(int(f["touches_high"]), int(f["touches_low"])) >= 4, 10),
        ("Breedte tussen 4 en 10 ATR", 4.0 <= float(f["width_atr"]) <= 10.0, 10),
        (f"Range minstens {age_min} candles oud", int(f["age_bars"]) >= age_min, 10),
        ("Schone randen (spreiding hooguit 0,25 ATR)", float(f["edge_spread_atr"]) <= 0.25, 10),
        ("Echte tegenkaars vlak voor de beweging", bool(f["ob_opposite"]), 15),
        ("Sterke beweging weg van de zone (minstens 1,5 ATR)", float(f["displacement_atr"]) >= 1.5, 15),
        ("Zone vers (hooguit één eerdere aanraking)", bool(f["zone_fresh"]), 15),
        ("Zone dun (hooguit 1,5 ATR)", float(f["zone_atr"]) <= 1.5, 15),
    ]


def weighted_finish(checks: list[WeightedCheck]) -> tuple[str, float]:
    """Zelfde reason-vorm als finish, maar de score telt punten in plaats van het aandeel kenmerken."""
    reason = " | ".join(("✓ " if ok else "✗ ") + label for label, ok, _ in checks)
    return reason, float(sum(w for _, ok, w in checks if ok)) * 100.0 / sum(w for _, _, w in checks)


def grade_of(score: float) -> str:
    return "A" if score >= GRADE_A else "B" if score >= GRADE_B else "C"
