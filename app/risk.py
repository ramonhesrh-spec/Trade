"""Risicomanagement: stop loss op echte marktstructuur (recente 4h swing
low/high, gedeeld, hetzelfde voor iedereen), take profit op basis van de
zo ontstane risicoafstand, en risicobedrag in euro's op basis van een eigen
portfoliobedrag per gebruiker."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

ATR_BUFFER_MULTIPLIER = 0.25  # ruimte onder/boven de swing, tegen een korte wick-stop
ATR_STOP_MULTIPLIER_FALLBACK = 1.5  # als er geen swing-data is
RISK_REWARD_RATIO = 2.0  # take profit op 2x de werkelijke stop-afstand


def trading_day_label(dt: datetime) -> str:
    """Het handelsdag-label (YYYY-MM-DD) voor een UTC-tijdstip, met dezelfde
    00:30 UTC-grens als Kraken's eigen dagverlies-reset: vóór 00:30 UTC
    hoort een tijdstip nog bij de vorige kalenderdag. Op precies deze ene
    plek geïmplementeerd, alle evaluatie-code hergebruikt hem in plaats van
    de grens ergens anders opnieuw te berekenen."""
    if dt.hour == 0 and dt.minute < 30:
        dt = dt - timedelta(days=1)
    return dt.date().isoformat()


@dataclass
class StopTake:
    stop_loss: float
    take_profit: float


@dataclass
class PropProgress:
    current_balance: float
    day_start_balance: float
    day_start_date: str
    status: str
    closed_reason: Optional[str]


def evaluate_prop_progress(evaluation: dict, result_eur: float, closed_at: datetime) -> PropProgress:
    """Verwerkt het resultaat van één aan een evaluatie-run gekoppelde
    trade: past het virtuele saldo aan, reset de dagverlies-referentie bij
    een nieuwe handelsdag, en bepaalt of de run daarmee geslaagd of
    mislukt is. Drawdown wordt vóór dagverlies gecheckt: een verlies dat
    allebei zou raken telt als de ernstigere, nooit-resettende drawdown-
    overtreding, niet als een dagverlies dat morgen weer op nul begint."""
    today_label = trading_day_label(closed_at)
    day_start_balance = evaluation["day_start_balance"]
    day_start_date = evaluation["day_start_date"]
    if today_label != day_start_date:
        day_start_balance = evaluation["current_balance"]
        day_start_date = today_label

    current_balance = evaluation["current_balance"] + result_eur
    tier_amount = evaluation["tier_amount"]

    status = "actief"
    closed_reason = None
    if current_balance <= tier_amount * (1 - evaluation["max_drawdown_pct"] / 100):
        status, closed_reason = "mislukt", "maximale drawdown geraakt"
    elif current_balance <= day_start_balance * (1 - evaluation["max_daily_loss_pct"] / 100):
        status, closed_reason = "mislukt", "maximaal dagverlies geraakt"
    elif current_balance >= tier_amount * (1 + evaluation["profit_target_pct"] / 100):
        status, closed_reason = "geslaagd", "winstdoel gehaald"

    return PropProgress(
        current_balance=current_balance, day_start_balance=day_start_balance,
        day_start_date=day_start_date, status=status, closed_reason=closed_reason,
    )


def compute_stop_take(
    direction: str, entry_price: float, atr: float,
    swing_low: Optional[float] = None, swing_high: Optional[float] = None,
) -> StopTake:
    """Stop loss net onder de recente 4h swing low bij een long (of net
    boven de swing high bij een short), met een kleine ATR-buffer zodat een
    korte wick niet meteen uitstopt. Valt terug op een vaste ATR-afstand als
    er geen bruikbare swing-data is. Take profit volgt de risk:reward
    verhouding op de zo ontstane, echte stop-afstand, niet op een losse
    vaste ATR-afstand."""
    direction = direction.lower()
    buffer = ATR_BUFFER_MULTIPLIER * atr

    if direction == "long":
        if swing_low is not None and swing_low < entry_price:
            stop_loss = swing_low - buffer
        else:
            stop_loss = entry_price - ATR_STOP_MULTIPLIER_FALLBACK * atr
        risk_distance = entry_price - stop_loss
        take_profit = entry_price + RISK_REWARD_RATIO * risk_distance
    elif direction == "short":
        if swing_high is not None and swing_high > entry_price:
            stop_loss = swing_high + buffer
        else:
            stop_loss = entry_price + ATR_STOP_MULTIPLIER_FALLBACK * atr
        risk_distance = stop_loss - entry_price
        take_profit = entry_price - RISK_REWARD_RATIO * risk_distance
    else:
        raise ValueError(f"onbekende richting: {direction}")

    return StopTake(stop_loss=stop_loss, take_profit=take_profit)


# Ondergrens op hoeveel een niveau-gebaseerde stop mag afwijken van de
# prijs, als fractie van de ATR. Kleiner dan dit: het niveau levert geen
# bruikbare stop op (te dichtbij, een piepklein verschil zou de
# positiegrootte absurd groot maken: risico gedeeld door een
# verwaarloosbare afstand). Val in dat geval terug op de gewone
# ATR-berekening.
MIN_LEVEL_STOP_DISTANCE_ATR_FRACTION = 0.5


def compute_stop_take_from_levels(
    direction: str, entry_price: float, atr: float, levels: list[float],
    swing_low: Optional[float] = None, swing_high: Optional[float] = None,
) -> StopTake:
    """Stop loss en take profit op basis van door de bron ingetekende
    niveaus (support/resistance), in plaats van pure marktstructuur/ATR.
    Welk niveau de stop is en welk het target, wordt bepaald door de
    positie van het niveau ten opzichte van de entry-prijs en de richting,
    nooit door een losse tekstlabel (pattern_name) te matchen: bij long is
    het dichtstbijzijnde niveau ONDER de prijs de stop-basis, het
    dichtstbijzijnde niveau ERBOVEN het target (bij short omgekeerd).

    Een niveau te dicht bij de prijs (kleiner dan
    MIN_LEVEL_STOP_DISTANCE_ATR_FRACTION x ATR) is geen bruikbare stop en
    valt terug op compute_stop_take voor de stop. Datzelfde geldt als er
    helemaal geen niveau aan de stop-kant van de prijs ligt. Een
    bruikbaar target-niveau blijft in dat geval WEL gebruikt: de stop en
    het target worden onafhankelijk van elkaar bepaald, een ontbrekend of
    te dichtbij stop-niveau is geen reden om ook een prima target-niveau
    weg te gooien."""
    direction = direction.lower()
    if direction not in ("long", "short"):
        raise ValueError(f"onbekende richting: {direction}")

    # Een niveau van 0 of negatief levert onzin op (een stop onder nul); de
    # plausibiliteitscheck bij het opslaan vangt dit alleen af als de live
    # prijs toen opgehaald kon worden.
    levels = [lvl for lvl in levels if lvl > 0]

    if direction == "long":
        stop_candidates = [lvl for lvl in levels if lvl < entry_price]
        target_candidates = [lvl for lvl in levels if lvl > entry_price]
        stop_level = max(stop_candidates) if stop_candidates else None
        target_level = min(target_candidates) if target_candidates else None
    else:
        stop_candidates = [lvl for lvl in levels if lvl > entry_price]
        target_candidates = [lvl for lvl in levels if lvl < entry_price]
        stop_level = min(stop_candidates) if stop_candidates else None
        target_level = max(target_candidates) if target_candidates else None

    min_distance = MIN_LEVEL_STOP_DISTANCE_ATR_FRACTION * atr
    use_level_stop = stop_level is not None and abs(entry_price - stop_level) >= min_distance

    if use_level_stop:
        buffer = ATR_BUFFER_MULTIPLIER * atr
        stop_loss = stop_level - buffer if direction == "long" else stop_level + buffer
    else:
        stop_loss = compute_stop_take(
            direction, entry_price, atr, swing_low=swing_low, swing_high=swing_high,
        ).stop_loss

    risk_distance = abs(entry_price - stop_loss)
    # Een target-niveau vlak naast de entry (bv. het niveau dat de
    # swing-watch net deed bevestigen) is geen bruikbaar doel: minimaal
    # 1:1 risk/reward, anders dezelfde ATR-gebaseerde fallback als
    # wanneer er helemaal geen target-niveau was.
    use_level_target = target_level is not None and abs(target_level - entry_price) >= risk_distance
    if use_level_target:
        take_profit = target_level
    elif direction == "long":
        take_profit = entry_price + RISK_REWARD_RATIO * risk_distance
    else:
        take_profit = entry_price - RISK_REWARD_RATIO * risk_distance

    return StopTake(stop_loss=stop_loss, take_profit=take_profit)


def compute_risk_eur(portfolio_eur: float, risk_percent: float) -> float:
    return portfolio_eur * (risk_percent / 100.0)


def compute_position_size(risk_eur: float, entry_price: float, stop_loss: float) -> Optional[float]:
    """Hoeveel coin je koopt bij dit risicobedrag: risicobedrag gedeeld door
    de afstand tussen entry en stop loss. Geeft None als die afstand nul is,
    wat niet zou moeten voorkomen maar voorkomt een deling door nul."""
    distance = abs(entry_price - stop_loss)
    if distance <= 0:
        return None
    return risk_eur / distance


def compute_unrealized_pnl(
    direction: str, entry_price: float, current_price: float,
    stop_loss: Optional[float], risk_eur: Optional[float],
) -> tuple[Optional[float], Optional[float]]:
    """Nog niet gerealiseerd resultaat van een open trade tegen de actuele
    prijs, dezelfde rekenwijze als bij het sluiten van een trade: het
    risicobedrag geschaald met hoe ver de prijs al bewogen is ten opzichte
    van de afstand tot de stop loss. Geeft (pnl_eur, pnl_pct), allebei None
    als er geen bruikbare stop-afstand is.

    pnl_pct is hier het percentage van het risicobedrag, niet de rauwe
    koersbeweging: naast een risicogewogen eurobedrag is de kale procentuele
    prijsbeweging een ander getal dat er niets mee te maken heeft, en dus
    misleidend om ernaast te tonen alsof het bij elkaar hoort."""
    direction = direction.lower()
    if direction == "long":
        risk_per_unit = entry_price - stop_loss if stop_loss else None
        move = current_price - entry_price
    else:
        risk_per_unit = stop_loss - entry_price if stop_loss else None
        move = entry_price - current_price

    pnl_eur = None
    if risk_eur and risk_per_unit and risk_per_unit > 0:
        pnl_eur = risk_eur * (move / risk_per_unit)

    pnl_pct = (pnl_eur / risk_eur * 100) if pnl_eur is not None and risk_eur else None
    return pnl_eur, pnl_pct
