"""Risicomanagement: stop loss op echte marktstructuur (recente 4h swing
low/high, gedeeld, hetzelfde voor iedereen), take profit op basis van de
zo ontstane risicoafstand, en risicobedrag in euro's op basis van een eigen
portfoliobedrag per gebruiker."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
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

# Hoeveel keer het evaluatiesaldo een positie maximaal notional mag zijn,
# exact de hefboomlimiet van de echte Kraken Prop. Was voorheen alleen in
# web/main.py voor oefentrades, geldt nu voor elke evaluatie-gesizede trade.
MAX_EVAL_LEVERAGE = 5.0

# Reserveer bij het sizen van één trade ruimte voor nog dit aantal - 1
# volgende trades dezelfde dag/run, in plaats van in één klap het hele
# resterende budget op te souperen.
EVAL_BUDGET_TRADE_RESERVE = 3

# Onder dit percentage van het VOLLEDIGE dagbudget of de VOLLEDIGE
# drawdown-ruimte is verder sizen op de evaluatie zinloos: elke nieuwe
# trade zou toch nagenoeg nul risico mogen nemen.
EVAL_BUDGET_BLOCK_THRESHOLD_PCT = 5.0


def effective_day_start_balance(evaluation: dict) -> float:
    """Het saldo waar het dagverlies-budget vandaag tegen gemeten moet
    worden. De opgeslagen day_start_balance/day_start_date rollen pas over
    binnen evaluate_prop_progress, en die draait alleen bij het sluiten van
    een trade: staat de opgeslagen dag al achter op de huidige handelsdag,
    dan is er simpelweg nog niks gesloten sinds middernacht en begint de
    nieuwe dag bij het huidige saldo. Zonder deze correctie zou de eerste
    trade van een nieuwe dag nog tegen het uitgeputte budget van gisteren
    gesized (en dan onterecht geblokkeerd) worden. Op één plek, gedeeld door
    de sizing hieronder en de weergave in web/main.py:_build_eval_context."""
    if trading_day_label(datetime.now(timezone.utc)) != evaluation["day_start_date"]:
        return evaluation["current_balance"]
    return evaluation["day_start_balance"]


def compute_eval_daily_budget_remaining(evaluation: dict, open_risk_eur: float) -> float:
    """Wat er nog over is van het dagverlies-budget van de evaluatie: het
    toegestane dagverlies min wat vandaag al verloren is, min het risico
    dat al vaststaat in nog open evaluatie-trades (dat risico is nog niet
    in current_balance verwerkt, zie repo.total_open_risk_eur_for_evaluation)."""
    day_start_balance = effective_day_start_balance(evaluation)
    daily_loss_amount = day_start_balance * evaluation["max_daily_loss_pct"] / 100
    loss_so_far = max(0.0, day_start_balance - evaluation["current_balance"])
    return max(0.0, daily_loss_amount - loss_so_far - open_risk_eur)


def compute_eval_drawdown_budget_remaining(evaluation: dict, open_risk_eur: float) -> float:
    """Zelfde als compute_eval_daily_budget_remaining, maar tegen de
    nooit-resettende drawdown-ruimte (tier_amount, niet day_start_balance)."""
    drawdown_amount = evaluation["tier_amount"] * evaluation["max_drawdown_pct"] / 100
    drawdown_so_far = max(0.0, evaluation["tier_amount"] - evaluation["current_balance"])
    return max(0.0, drawdown_amount - drawdown_so_far - open_risk_eur)


def eval_sizing_blocked(evaluation: dict, open_risk_eur: float) -> bool:
    """True als het dagbudget of de drawdown-ruimte al zo goed als op is:
    dan heeft verder evaluatie-sizen geen zin meer, de trade valt terug op
    gewone portfolio-sizing en telt niet mee voor de evaluatie."""
    daily_budget = effective_day_start_balance(evaluation) * evaluation["max_daily_loss_pct"] / 100
    drawdown_budget = evaluation["tier_amount"] * evaluation["max_drawdown_pct"] / 100
    daily_remaining_pct = (
        compute_eval_daily_budget_remaining(evaluation, open_risk_eur) / daily_budget * 100
        if daily_budget else 0.0
    )
    drawdown_remaining_pct = (
        compute_eval_drawdown_budget_remaining(evaluation, open_risk_eur) / drawdown_budget * 100
        if drawdown_budget else 0.0
    )
    return (
        daily_remaining_pct < EVAL_BUDGET_BLOCK_THRESHOLD_PCT
        or drawdown_remaining_pct < EVAL_BUDGET_BLOCK_THRESHOLD_PCT
    )


def compute_eval_risk_eur(
    evaluation: dict, risk_percent: float, open_risk_eur: float,
    entry_price: float, stop_loss: float,
) -> float:
    """Risicobedrag voor één evaluatie-gesizede trade: het kleinste van de
    persoonlijke risk_percent-cap tegen het evaluatiesaldo, een derde van
    het resterend dagbudget, een derde van de resterende drawdown-ruimte,
    en de hefboomcap. Aanroeper checkt vooraf eval_sizing_blocked; deze
    functie zelf gaat er niet vanuit dat er nog voldoende budget is."""
    personal_cap = evaluation["current_balance"] * risk_percent / 100
    daily_share = compute_eval_daily_budget_remaining(evaluation, open_risk_eur) / EVAL_BUDGET_TRADE_RESERVE
    drawdown_share = compute_eval_drawdown_budget_remaining(evaluation, open_risk_eur) / EVAL_BUDGET_TRADE_RESERVE
    stop_distance = abs(entry_price - stop_loss)
    leverage_cap = (
        MAX_EVAL_LEVERAGE * evaluation["current_balance"] * stop_distance / entry_price
        if stop_distance > 0 and entry_price > 0 else float("inf")
    )
    return max(0.0, min(personal_cap, daily_share, drawdown_share, leverage_cap))


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


# Bij dit evaluatiesaldo (of hoger) wordt de stop loss niet meer ingeperkt:
# het maximum groeit dan naar STOP_CAP_MAX_PCT, wat in de praktijk geen
# enkele normale marktstructuur-stop meer raakt (die liggen vrijwel altijd
# onder de 5%).
STOP_CAP_REFERENCE_TIER = 10_000.0
# Bij een (bijna) nul zo groot gekozen evaluatie-tier (tier_amount, niet het
# live current_balance — de cap verandert dus NIET mee met winst/verlies
# binnen dezelfde evaluatie, alleen met de gekozen groottekeuze) mag de stop
# nog maar dit percentage van de entry-prijs zijn.
STOP_CAP_MIN_PCT = 0.01
# Vanaf STOP_CAP_REFERENCE_TIER (tier_amount): dit percentage, functioneel
# "geen grens".
STOP_CAP_MAX_PCT = 0.10


def eval_max_stop_pct(tier_amount: float) -> float:
    """Maximale stop-afstand als fractie van de entry-prijs, lineair
    oplopend van STOP_CAP_MIN_PCT (bij tier_amount 0) tot STOP_CAP_MAX_PCT
    (bij STOP_CAP_REFERENCE_TIER en hoger). Geen harde knip: een evaluatie
    net onder de referentie-tier krijgt bijna dezelfde ruimte als er net
    boven, in plaats van een plotselinge sprong."""
    fraction = min(max(tier_amount, 0.0) / STOP_CAP_REFERENCE_TIER, 1.0)
    return STOP_CAP_MIN_PCT + (STOP_CAP_MAX_PCT - STOP_CAP_MIN_PCT) * fraction


def apply_eval_stop_cap(
    direction: str, entry_price: float, stop_loss: float, take_profit: float, max_stop_pct: float,
) -> StopTake:
    """Trekt een te brede stop loss in tot max_stop_pct van de entry-prijs.
    Take profit schaalt evenredig mee, zodat de risk:reward-verhouding van
    de oorspronkelijke berekening exact behouden blijft (in plaats van een
    aparte doelberekening te herhalen, die bij een niveau-gebaseerd target
    andere aannames zou maken dan de oorspronkelijke keuze). Geen wijziging
    als de bestaande stop al binnen de grens valt — dit is een bovengrens,
    geen streefwaarde."""
    direction = direction.lower()
    max_distance = entry_price * max_stop_pct
    if direction == "long":
        current_distance = entry_price - stop_loss
        if current_distance <= max_distance or current_distance <= 0:
            return StopTake(stop_loss=stop_loss, take_profit=take_profit)
        scale = max_distance / current_distance
        reward_distance = take_profit - entry_price
        return StopTake(
            stop_loss=entry_price - max_distance,
            take_profit=entry_price + reward_distance * scale,
        )
    elif direction == "short":
        current_distance = stop_loss - entry_price
        if current_distance <= max_distance or current_distance <= 0:
            return StopTake(stop_loss=stop_loss, take_profit=take_profit)
        scale = max_distance / current_distance
        reward_distance = entry_price - take_profit
        return StopTake(
            stop_loss=entry_price + max_distance,
            take_profit=entry_price - reward_distance * scale,
        )
    else:
        raise ValueError(f"onbekende richting: {direction}")


def compute_risk_eur(portfolio_eur: float, risk_percent: float) -> float:
    return portfolio_eur * (risk_percent / 100.0)


# Round-trip handelsfee (open + sluiten) van een evaluatie-account, als
# fractie van de positiewaarde.
EVAL_TRADE_FEE_RATE = 0.0008
# Hefboom-/financieringskosten per dag dat een evaluatie-positie openstaat,
# als fractie van de positiewaarde.
EVAL_LEVERAGE_DAILY_RATE = 0.00033
# Voorzichtige aanname voor hoeveel dagen een trade openstaat, gebruikt om
# VOORAF (bij het bepalen van de positiegrootte) een hefboomkost in te
# schatten voor iets waarvan de werkelijke duur nog niet bekend is. Dit is
# een day-trading-systeem, de meeste trades zijn binnen een dag klaar; de
# WERKELIJKE kost wordt bij het sluiten opnieuw en exact berekend (zie
# repo.close_journal_trade), dus een te lage aanname hier wordt daar
# gecorrigeerd, niet stilzwijgend gemist.
EVAL_SIZING_DAYS_ASSUMPTION = 1.0


def compute_position_size(
    risk_eur: float, entry_price: float, stop_loss: float, cost_rate: float = 0.0,
) -> Optional[float]:
    """Hoeveel coin je koopt bij dit risicobedrag: risicobedrag gedeeld door
    de afstand tussen entry en stop loss, plus (voor evaluatie-trades) een
    kostenfractie van de positiewaarde die net zo goed "verlies" is als de
    pure prijsbeweging: fees en geschatte hefboomkosten. cost_rate is 0.0
    voor elke niet-evaluatie-trade (ongewijzigd gedrag). Geeft None als de
    stop-afstand nul is, wat niet zou moeten voorkomen maar voorkomt een
    deling door nul."""
    distance = abs(entry_price - stop_loss)
    if distance <= 0:
        return None
    return risk_eur / (distance + entry_price * cost_rate)


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


def compute_sltp_progress_pct(direction: str, price: float, stop_loss: float, take_profit: float) -> float:
    """Percentage (0-100) van waar de prijs nu zit tussen stop loss (0%) en
    take profit (100%). Zelfde berekening als de oude Telegram-tekstbalk
    gebruikte en de live voortgangsbalk op het dashboard, zodat beide
    altijd exact hetzelfde percentage tonen. Bij
    risk.py se standaard 1:2 risk:reward-ontwerp staat een gloednieuwe
    kans al op ongeveer 33%, dat is geen fout, dat is de ingebouwde
    verhouding tussen de stop-afstand en de doelafstand."""
    if direction == "long":
        span = take_profit - stop_loss
        pos = (price - stop_loss) / span if span else 0.0
    else:
        span = stop_loss - take_profit
        pos = (stop_loss - price) / span if span else 0.0
    return max(0.0, min(1.0, pos)) * 100
