"""Beslislogica van een dagtrading-setup, los van database en netwerk: de
live pijplijn (signal_processor.process_day_trading_signal) en het meetraam
(app/replay) roepen exact dezelfde functie aan, zodat een resultaat uit het
raam geldt voor de code die live draait."""
from dataclasses import dataclass
from typing import Callable, Optional

from app import indicators, risk

# Onder deze verhouding is een setup geen goede trade meer, ongeacht hoeveel
# andere factoren wel kloppen — een niveau-gebaseerde stop
# (risk.compute_stop_take_from_levels) kan de verhouding laten zakken tot
# zijn eigen ondergrens van 1:1, dat is lager dan hier acceptabel is.
MIN_RISK_REWARD_RATIO = 2.0

# Focus op de strakste, preciestste entries: een signaal met een stop
# verder dan dit percentage van de entry af wordt niet gemeld, ongeacht
# hoe goed de rest van de setup is. Minder meldingen, en de meldingen die
# er nog wel zijn hebben een klein, beheersbaar risico per trade.
MAX_STOP_DISTANCE_PCT = 1.5


def stop_within_max_distance(entry_price: float, stop_loss: float) -> bool:
    """True als de stop-afstand tot de entry binnen MAX_STOP_DISTANCE_PCT
    ligt. Gedeelde check voor elk ATR-gebaseerd detectiepad (dagtrading,
    uitbraak, trendlijn, patroon) — zelfde precedent als
    MIN_RISK_REWARD_RATIO hierboven, nu op stopafstand in plaats van op
    risico/rendement. Smc gebruikt dit bewust niet: die stop ligt vast op
    de sweep-prijs, geen ATR, zie market_scanner.py::_complete_smc_setup."""
    if not entry_price:
        return False
    distance_pct = abs(entry_price - stop_loss) / entry_price * 100
    return distance_pct <= MAX_STOP_DISTANCE_PCT


@dataclass
class SetupEvaluation:
    confirmed: bool
    hard_gates_ok: bool
    pass_pct: float
    reason: str
    stop_loss: float
    take_profit: float
    nearest_sr_zone_price: Optional[float]
    suggested_entry_low: Optional[float]
    suggested_entry_high: Optional[float]
    sniper_entry_price: Optional[float]
    sniper_reason: Optional[str]
    risk_reward_ratio: float


def evaluate_day_trading_setup(
    direction: str, df, ind: indicators.Indicators, zones: list[indicators.SRZone],
    confirmation: tuple[bool, str, float, bool],
    zone_recently_failed: Callable[[float], bool], message_levels: list[float],
) -> SetupEvaluation:
    confirmed, reason, pass_pct, hard_gates_ok = confirmation
    swing_low, swing_high = indicators.swing_levels(df)

    # Dezelfde edges/kant-bepaling-logica als indicators.check_sr_zone gebruikt
    # intern, hier apart herhaald in plaats van check_sr_zone's eigen
    # (name, ok, detail)-vorm uit te breiden — dat zou die vorm inconsistent
    # maken met elke andere factor-functie, en de twee aanroepers van
    # check_sr_zone (signal_processor.py, scripts/backtest_factors.py) zouden dan
    # allebei aangepast moeten worden voor een waarde die alleen hier nodig is.
    edges = [edge for zone in zones for edge in (zone.price_low, zone.price_high)]
    if direction.lower() == "long":
        zone_candidates = [
            e for e in edges
            if e < ind.price and abs(ind.price - e) <= indicators.SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE * ind.atr
        ]
        nearest_sr_zone_price = max(zone_candidates) if zone_candidates else None
    else:
        zone_candidates = [
            e for e in edges
            if e > ind.price and abs(ind.price - e) <= indicators.SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE * ind.atr
        ]
        nearest_sr_zone_price = min(zone_candidates) if zone_candidates else None

    # Zelfde zone die de laatste keer al een stop loss veroorzaakte: een
    # nieuw signaal vlakbij diezelfde rand herhaalt vermoedelijk dezelfde
    # fout, dus telt hier mee als harde eis naast de andere confirms_direction-
    # uitkomst in plaats van als losse parallelle check.
    if nearest_sr_zone_price is not None and zone_recently_failed(nearest_sr_zone_price):
        hard_gates_ok = False
        confirmed = False
        reason += " | ✗ Zone recent gefaald: deze steun/weerstand-zone veroorzaakte de laatste 3 dagen al een stop loss"

    zone_levels = [
        edge for zone in zones for edge in (zone.price_low, zone.price_high)
        if abs(edge - ind.price) <= indicators.SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE * ind.atr
    ]
    combined_levels = message_levels + zone_levels
    if combined_levels:
        stop_take = risk.compute_stop_take_from_levels(
            direction, ind.price, ind.atr, combined_levels, swing_low=swing_low, swing_high=swing_high,
        )
    else:
        stop_take = risk.compute_stop_take(
            direction, ind.price, ind.atr, swing_low=swing_low, swing_high=swing_high,
        )

    # Een bruikbare entry-zone ligt tussen de huidige prijs en de stop
    # loss (in het voordeel van de trade: dichter bij de stop dan de
    # huidige prijs bij long is een BETERE, niet slechtere, entry — bij
    # short andersom), en is dus nooit voorbij de stop loss zelf. PUUR
    # informatief (product owner): telt nergens mee in sizing/journaal/
    # trackrecord, de live prijs (ind.price) blijft de echte entry overal
    # elders in de aanroeper.
    # Geclampt op ind.price: de favorable-filters hierboven toetsen alleen
    # de rand die het VERST van de live prijs af ligt, dus een zone die de
    # prijs zelf overlapt sluiten ze niet uit. Zonder de clamp zou de
    # getoonde range dan deels een "betere entry" adverteren die feitelijk
    # slechter is dan de huidige prijs.
    if direction.lower() == "long":
        favorable = [z for z in zones if stop_take.stop_loss < z.price_low < ind.price]
        best_zone = max(favorable, key=lambda z: z.price_high) if favorable else None
        suggested_entry_low = best_zone.price_low if best_zone else None
        suggested_entry_high = min(best_zone.price_high, ind.price) if best_zone else None
    else:
        favorable = [z for z in zones if ind.price < z.price_high < stop_take.stop_loss]
        best_zone = min(favorable, key=lambda z: z.price_low) if favorable else None
        suggested_entry_low = max(best_zone.price_low, ind.price) if best_zone else None
        suggested_entry_high = best_zone.price_high if best_zone else None

    sniper = indicators.find_sniper_entry_price(direction, df)
    sniper_entry_price, sniper_reason = sniper if sniper else (None, None)
    # Een sniper-prijs voorbij de stop loss is geen bruikbare entry-suggestie
    # meer (zie indicators.sniper_beyond_stop): instappen daar zou de trade
    # al ongeldig maken. Telt verderop hetzelfde als "geen sniper gevonden".
    if sniper_entry_price is not None and indicators.sniper_beyond_stop(
        direction, sniper_entry_price, stop_take.stop_loss,
    ):
        sniper_entry_price, sniper_reason = None, None

    # Harde eis: alleen melden bij een duidelijke sweep/stop-hunt-entry, niet
    # bij de kale live prijs. Zonder dit vuurde elk dagtrading-signaal op
    # ind.price, ongeacht of de prijs net een stop-hunt had of al een stuk
    # verder was gelopen dan een scherpe entry nog zou toestaan — bij een
    # grote positie (zie gesprek) is dat verschil geen rond-getal-ruis meer.
    # Zelfde vergelijking als market_scanner._complete_smc_setup's
    # entry_worse_than_sniper: bij long is een hogere prijs dan de sniper
    # een slechtere entry (je koopt verder boven de swept low), bij short
    # een lagere prijs een slechtere entry (je verkoopt verder onder de
    # swept high). Geen sniper gevonden telt ook als een te late/onduidelijke
    # entry, niet als "geen informatie dus toegestaan". Wie geen sniper-
    # entry kreeg, krijgt via level_check.py's proactieve sniper-trigger
    # alsnog een melding zodra er wél een duidelijke stop-hunt verschijnt.
    entry_worse_than_sniper = (
        sniper_entry_price is None
        or (direction.lower() == "short" and ind.price < sniper_entry_price)
        or (direction.lower() == "long" and ind.price > sniper_entry_price)
    )
    if entry_worse_than_sniper:
        hard_gates_ok = False
        confirmed = False
        if sniper_entry_price is None:
            reason += " | ✗ Sniper-entry: geen duidelijke stop-hunt gevonden binnen bereik"
        else:
            reason += (
                f" | ✗ Sniper-entry: prijs {ind.price:.4f} ligt niet meer aan de juiste kant "
                f"van de sniper-prijs {sniper_entry_price:.4f}"
            )

    risk_distance = abs(ind.price - stop_take.stop_loss)
    reward_distance = abs(stop_take.take_profit - ind.price)
    risk_reward_ratio = (reward_distance / risk_distance) if risk_distance else 0.0
    if risk_reward_ratio < MIN_RISK_REWARD_RATIO:
        hard_gates_ok = False
        confirmed = False
        reason += f" | ✗ Risico/rendement: {risk_reward_ratio:.1f} tegen 1, onder de ondergrens van {MIN_RISK_REWARD_RATIO}"
    if not stop_within_max_distance(ind.price, stop_take.stop_loss):
        hard_gates_ok = False
        confirmed = False
        stop_distance_pct = risk_distance / ind.price * 100 if ind.price else 0.0
        reason += f" | ✗ Stopafstand: {stop_distance_pct:.1f}% van entry, boven de ondergrens van {MAX_STOP_DISTANCE_PCT}%"

    return SetupEvaluation(
        confirmed=confirmed, hard_gates_ok=hard_gates_ok, pass_pct=pass_pct, reason=reason,
        stop_loss=stop_take.stop_loss, take_profit=stop_take.take_profit,
        nearest_sr_zone_price=nearest_sr_zone_price,
        suggested_entry_low=suggested_entry_low, suggested_entry_high=suggested_entry_high,
        sniper_entry_price=sniper_entry_price, sniper_reason=sniper_reason,
        risk_reward_ratio=risk_reward_ratio,
    )
