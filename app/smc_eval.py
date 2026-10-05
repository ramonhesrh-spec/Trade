"""Pure SMC-beslislogica (structuurbreuk + sweep + confluentiezone, afwijzing,
signaal-stop/doel): geen database, geen exchange, geen logging. Live
(market_scanner._check_smc_setup / _complete_smc_setup) en de replay-engine
roepen dezelfde functies aan, zodat ze niet uit elkaar kunnen lopen."""
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Optional

from app import config, indicators
from app.setup_eval import MIN_RISK_REWARD_RATIO


SMC_ZONE_SEARCH_LOOKBACK_30M = 60  # 30m-candles, ongeveer anderhalve dag

# Was een vast percentage (STOP_MARGIN_PCT 0.1%, TARGET_MARGIN_PCT 0.5%) van
# de prijs. Op een coin die op dat moment flink beweegt is 0.1% vaak maar
# een fractie van normale ruis binnen één candle — een SUI-trade (zie
# gesprek) werd zo op de stop gezet door een gewone tegenwiek, terwijl de
# structuurpremisse zelf klopte en de prijs er later alsnog heen liep. ATR
# van de 30m-candle op het moment van de structuurbreuk (dezelfde
# tijdshorizon als de breuk zelf) maakt de marge groter op een drukke coin
# en kleiner op een rustige, in plaats van overal hetzelfde vaste getal.
# Zelfde multiple (0.25) als risk.ATR_BUFFER_MULTIPLIER, om dezelfde reden:
# ruimte tegen een korte wiek, niet tegen een echte trendomkeer.
STOP_MARGIN_ATR_MULTIPLE = 0.25    # marge voorbij de sweep
TARGET_MARGIN_ATR_MULTIPLE = 0.25  # marge vóór de liquidity

# Fallback voor een setup die al "bouwend" stond vóór atr een kolom op
# smc_setups werd (zie market_scanner._complete_smc_setup) — niet meer gebruikt voor een
# nieuwe setup, blijft alleen staan zodat zo'n oude rij nog een geldig
# signaal kan opleveren in plaats van te crashen op een ontbrekende atr.
LEGACY_STOP_MARGIN_PCT = 0.1
LEGACY_TARGET_MARGIN_PCT = 0.5


def smc_stop_take_margins(setup: dict) -> tuple[float, float]:
    """(stop_margin, target_margin) in prijseenheden, nog zonder teken —
    de aanroeper bepaalt zelf aan welke kant van sweep_price/
    liquidity_target de marge moet. Eén plek voor deze fallback-logica in
    plaats van 'm drie keer te laten driften (hier, /smc-pagina preview in
    web/main.py, scripts/cleanup_stale_smc_setups.py)."""
    if setup["atr"] is not None:
        return STOP_MARGIN_ATR_MULTIPLE * setup["atr"], TARGET_MARGIN_ATR_MULTIPLE * setup["atr"]
    return (
        LEGACY_STOP_MARGIN_PCT / 100 * setup["sweep_price"],
        LEGACY_TARGET_MARGIN_PCT / 100 * setup["liquidity_target"],
    )

# Een bouwende setup die dit lang niet is opgelost (geraakt+afgewezen, of
# doorbroken zonder afwijzing) wordt als vervallen beschouwd. Zonder deze
# grens bleef een zone voor altijd "bouwend" staan zodra de prijs simpelweg
# wegliep in de gunstige richting zonder ooit terug te keren: het bestaande
# passed_without_rejection-oordeel signaleert alleen een mislukte kant
# (short: close boven de zone, long: eronder), niet "de koers is te ver weg
# om nog terug te keren". Zelfde 1-dag-grens als SIGNAL_MAX_AGE_DAYS in
# level_check.py voor een gewoon signaal.
SMC_SETUP_MAX_AGE_HOURS = 24


# Hoeveel ATR een candle voorbij de zone moet sluiten voordat een bouwende
# setup als 'doorbraak zonder afwijzing' ongeldig wordt gemaakt. Uit
# achteraf-onderzoek (scripts/check_dead_smc_setups.py, 1 okt): van de 25
# setups die hierdoor stierven, bleek de richting achteraf in 80% van de
# gevallen toch te kloppen — een candle die net over zone_high/zone_low
# sluit is meestal een gewone wiek, geen echte trendomkeer. Zelfde multiple
# en redenering als STOP_MARGIN_ATR_MULTIPLE hierboven. Geldt uitsluitend
# voor passed_without_rejection (de ongeldig-verklaring) — rejected (de
# entry-trigger) blijft bewust zonder marge, scherpe entries zijn het hele
# punt van deze detector.
ZONE_BREAK_BUFFER_ATR_MULTIPLE = 0.25


def last_candle_state(
    candle, zone_low: float, zone_high: float, direction: str, atr: Optional[float] = None,
) -> tuple[bool, bool, bool]:
    """Bepaalt voor één gesloten 15m-candle en één bouwende zone drie
    onafhankelijke toestanden: (in_zone, rejected, passed_without_rejection).
    in_zone: de candle raakte de zone (wick of volledige overlap).
    rejected: de candle raakte de zone EN sloot er weer buiten aan de
    kant die de setup ongeldig maakt voor voortzetting maar geldig maakt
    als entry-trigger (short: sluit onder zone_low, long: sluit boven
    zone_high) — dit is het moment waarop market_scanner._complete_smc_setup het
    signaal maakt. Zonder marge: een vroege, scherpe entry is het hele punt.
    passed_without_rejection: het SPIEGELBEELD van rejected, niet
    hetzelfde teken. Een short-zone ligt BOVEN de prijs die er van
    onderaf naartoe beweegt (na de bearish structuurbreuk) — 'voorbij
    zonder afwijzing' betekent dus dat de candle DOOR de top van de zone
    brak (close boven zone_high + ZONE_BREAK_BUFFER_ATR_MULTIPLE * atr)
    zonder ooit een rejectie-close onder zone_low te laten zien: de supply
    hield niet stand, de setup is achterhaald. Long is het spiegelbeeld
    (close onder zone_low - marge, door de bodem heen). Vóórdat de zone
    ooit bereikt is — bijvoorbeeld een short-setup waarvan de laatste close
    nog onder zone_low ligt, op weg naar boven — is dit nadrukkelijk GEEN
    'passed': met hetzelfde teken als rejected zou elke net aangemaakte,
    nog nooit geraakte setup de cyclus erna meteen weer weggegooid worden.
    atr=None (bv. een bouwende setup van vóór de atr-kolom) valt terug op
    geen marge, het oude gedrag."""
    in_zone = (
        zone_low <= candle["low"] <= zone_high
        or zone_low <= candle["high"] <= zone_high
        or (candle["low"] <= zone_low and candle["high"] >= zone_high)
    )
    rejected = in_zone and (
        (direction == "short" and candle["close"] < zone_low) or
        (direction == "long" and candle["close"] > zone_high)
    )
    buffer = ZONE_BREAK_BUFFER_ATR_MULTIPLE * atr if atr else 0.0
    passed_without_rejection = (
        (direction == "short" and candle["close"] > zone_high + buffer) or
        (direction == "long" and candle["close"] < zone_low - buffer)
    )
    return in_zone, rejected, passed_without_rejection


SMC_ENTRY_CANDLE_MINUTES = 15

# Hoeveel 15m-candles fase 1 hoogstens per bouwende setup beoordeelt: alle
# candles die sinds de vorige scan gesloten zijn. De scan draait elke 20
# minuten (deploy/crypto-market-scan.timer), dus er kunnen er twee sluiten
# tussen twee runs — alleen de allerlaatste bekijken sloeg zo één op de
# vier 15m-candles over, inclusief een afwijzing of doorbraak die precies
# daarop gebeurde. Begrensd (geen onbeperkte inhaalslag) zodat een
# afwijzing waar _complete_smc_setup geen geldige trade van kon maken niet
# elke volgende cyclus opnieuw als trigger terugkomt.
SMC_MAX_CANDLES_PER_CHECK = 2


def candles_since(closed_15m, since_iso: str) -> list:
    """Gesloten 15m-candles die NA since_iso sloten (updated_at: de
    sluittijd van de laatste candle waartegen de setup al beoordeeld is),
    oudste eerst, hoogstens
    SMC_MAX_CANDLES_PER_CHECK. Een candle die al sloot vóór de setup
    (opnieuw) gedefinieerd werd, heeft die zone nooit 'gezien' en mag hem
    dus ook niet afwijzen of ongeldig maken — dat werd bij het aanmaken al
    tegen de laatste gesloten candle getoetst."""
    since = datetime.fromisoformat(since_iso)
    close_times = closed_15m["timestamp"] + timedelta(minutes=SMC_ENTRY_CANDLE_MINUTES)
    fresh = closed_15m[close_times > since].tail(SMC_MAX_CANDLES_PER_CHECK)
    return [candle for _, candle in fresh.iterrows()]


def valid_stop_take(direction: str, entry_price: float, stop_loss: float, take_profit: float) -> bool:
    """Ligt de stop aan de verliezende en de take aan de winnende kant van de
    prijs waarop we melden? Patroongeometrie (of een prijs die sinds de
    doorbraak flink is doorgelopen) kan anders een omgekeerde stop/take
    opleveren, en die gaat ongecontroleerd de positiegrootte en de
    automatische trackrecord in."""
    if direction == "long":
        return stop_loss < entry_price < take_profit
    return take_profit < entry_price < stop_loss


@dataclass
class SmcCandidate:
    direction: str
    zone_low: float
    zone_high: float
    structure_level: float
    sweep_price: float
    liquidity_target: float
    atr: float


@dataclass
class SmcScan:
    # Richting van de laatst gevonden structuurbreuk, ook als er daarna geen
    # kandidaat overblijft: de aanroeper laat bestaande setups in de andere
    # richting vervallen zodra een breuk is gezien (zie _check_smc_setup).
    break_direction: Optional[str]
    candidate: Optional[SmcCandidate]
    skip_reason: Optional[str]
    detail: str = ""


def setup_expired(setup: dict, now: datetime) -> bool:
    created_at = datetime.fromisoformat(setup["created_at"])
    return (now - created_at).total_seconds() / 3600 > SMC_SETUP_MAX_AGE_HOURS


def judge_forming_setup(setup: dict, closed_15m) -> str:
    """Fase 1 van _check_smc_setup voor één bouwende setup: "rejected" zodra een
    candle sinds de vorige beoordeling de zone raakte en er weer buiten sloot
    (entry-trigger), "passed" zodra een candle er doorheen sloot zonder afwijzing
    (setup achterhaald), anders "open"."""
    for candle in candles_since(closed_15m, setup["updated_at"]):
        in_zone, rejected, passed_without_rejection = last_candle_state(
            candle, setup["zone_low"], setup["zone_high"], setup["direction"], atr=setup["atr"],
        )
        if rejected:
            return "rejected"
        # Geen extra in_zone-eis: de candle die door de zone heen sluit
        # heeft vrijwel altijd zelf een staart in de zone, en rejected en
        # passed_without_rejection sluiten elkaar al uit (close aan
        # tegenovergestelde kanten van de zone).
        if passed_without_rejection:
            return "passed"
    return "open"


def find_candidate(closed_30m, df_30m, closed_15m, last_candle) -> SmcScan:
    """Fase 2 van _check_smc_setup: zoekt een nieuwe structuurbreuk + sweep +
    confluentiezone + liquidity-doel op de gesloten candles. closed_30m is
    df_30m zonder de nog vormende laatste candle (zie _check_smc_setup)."""
    structure_break = indicators.find_structure_break(closed_30m)
    if structure_break is None:
        return SmcScan(None, None, "geen_structuurbreuk")
    direction = structure_break.direction
    # Op hetzelfde moment en dezelfde candle-set als de breuk zelf: de
    # volatiliteit die hier geldt, is die van de 30m-candle waarop de
    # structuur net brak, niet een latere, mogelijk heel andere ATR.
    atr = indicators.compute_indicators(closed_30m).atr

    sweep = indicators.find_liquidity_sweep_before_break(closed_30m, structure_break)
    if sweep is None:
        return SmcScan(direction, None, "geen_sweep")

    # Zonder deze afbakening zochten find_fair_value_gaps/find_order_blocks
    # los in de laatste ZONE_SEARCH_LOOKBACK (10 uur) 15m-candles, zonder
    # koppeling aan DEZE structuurbreuk. In een coin met meerdere bewegingen
    # in dezelfde richting binnen die 10 uur pakte find_confluence_zone dan
    # de eerste overlap die hij tegenkwam, ook als die uit een andere,
    # oudere beweging kwam dan de displacement die de structuur brak — een
    # afwijzing op zo'n zone bevestigt dan niets over de eigenlijke
    # sweep+breuk-premisse van deze setup. sweep.index wijst terug in
    # closed_30m (zelfde 0-based positie, zie find_liquidity_sweep_before_break),
    # dus de sweep-candle zijn eigen tijdstip is de ondergrens: de
    # displacement die de structuur brak begint per definitie niet vóór de
    # sweep die hem voedde.
    sweep_time = closed_30m["timestamp"].iloc[sweep.index]
    displacement_15m = closed_15m[closed_15m["timestamp"] >= sweep_time]

    fvgs = indicators.find_fair_value_gaps(displacement_15m, direction)
    order_blocks = indicators.find_order_blocks(displacement_15m, direction)
    zone = indicators.find_confluence_zone(fvgs, order_blocks)
    if zone is None:
        return SmcScan(direction, None, "geen_confluentiezone")
    zone_low, zone_high = zone

    # Liquidity-doel: de dichtstbijzijnde tegengestelde pivot die de prijs
    # sinds de breuk nog NIET geraakt heeft, op hetzelfde 30m-venster als
    # de structuurbreuk zelf (dezelfde bron als structure_level en
    # sweep_price, geen extra candle-fetch). Alleen "voorbij de zone" was
    # niet genoeg: de net gebroken pivot zelf, en elke oudere pivot waar de
    # doorbraak-beweging al doorheen liep, ligt ook voorbij de zone maar
    # die liquidity is al opgehaald — zo'n doel gaf een take profit aan de
    # verkeerde kant van de entry zodra de afwijzing eronder sloot. Hier
    # WEL inclusief de nog vormende 30m-candle (df_30m, niet closed_30m):
    # een niveau waar de prijs al doorheen handelde is opgehaald, of die
    # candle nu al gesloten is of niet.
    since_break = df_30m.iloc[structure_break.break_index:]
    if direction == "long":
        untouched_from = max(zone_high, float(since_break["high"].max()))
    else:
        untouched_from = min(zone_low, float(since_break["low"].min()))
    target_kind = "high" if direction == "long" else "low"
    target_pivots = [
        p for p in indicators._find_pivots(closed_30m)
        if p.kind == target_kind and (
            (direction == "long" and p.price > untouched_from) or
            (direction == "short" and p.price < untouched_from)
        )
    ]
    if not target_pivots:
        return SmcScan(direction, None, "geen_liquiditeitsdoel")
    liquidity_target_pivot = min(target_pivots, key=lambda p: abs(p.price - untouched_from))

    # De ATR-marge kan, net als het oude vaste percentage kon, groter zijn
    # dan de afstand tussen zone en sweep/liquidity-doel, of de rauwe sweep
    # kan zelf al binnen de zone liggen in plaats van eronder/erboven
    # (short/long) — in beide gevallen komt de stop of het doel dan aan de
    # verkeerde kant van de zone terecht. valid_stop_take zou zo'n setup
    # later toch afwijzen zodra de afwijzing binnenkomt, maar dan is de
    # "bouwt op"-melding al verstuurd voor een setup die nooit een geldig
    # signaal kon worden. Hier al overslaan voorkomt die dode melding.
    sign = 1 if direction == "short" else -1
    projected_stop_loss = sweep.price + sign * STOP_MARGIN_ATR_MULTIPLE * atr
    projected_take_profit = liquidity_target_pivot.price + sign * TARGET_MARGIN_ATR_MULTIPLE * atr
    stop_niet_voorbij_zone = (
        (direction == "short" and projected_stop_loss <= zone_high) or
        (direction == "long" and projected_stop_loss >= zone_low)
    )
    doel_niet_voorbij_zone = (
        (direction == "short" and projected_take_profit >= zone_low) or
        (direction == "long" and projected_take_profit <= zone_high)
    )
    if stop_niet_voorbij_zone or doel_niet_voorbij_zone:
        return SmcScan(
            direction, None, "stop_of_doel_binnen_zone",
            detail=f"stop {projected_stop_loss:.4f} / doel {projected_take_profit:.4f} (na marge) liggen niet voorbij de zone {zone_low:.4f}-{zone_high:.4f}",
        )

    # Een bouwende setup is pas zinvol zolang de koers nog naar de zone
    # moet terugtrekken (short: nog eronder, long: nog erboven). Zonder
    # deze eis kon fase 1 hierboven een setup opruimen omdat de koers door
    # de zone heen sloot, en maakte deze fase dezelfde zone in dezelfde
    # cyclus meteen weer aan met alert_sent=0 — een tweede 'bouwt op'-push
    # voor een zone die net ongeldig was geworden.
    last_close = float(last_candle["close"])
    if (direction == "short" and last_close >= zone_low) or (direction == "long" and last_close <= zone_high):
        return SmcScan(direction, None, "koers_al_in_zone")

    return SmcScan(direction, SmcCandidate(
        direction=direction, zone_low=zone_low, zone_high=zone_high,
        structure_level=structure_break.broken_pivot.price, sweep_price=sweep.price,
        liquidity_target=liquidity_target_pivot.price, atr=atr,
    ), None)


@dataclass
class SmcSignalDraft:
    entry_price: float
    stop_loss: float
    take_profit: float
    sniper_entry_price: Optional[float]
    sniper_reason: Optional[str]
    risk_reward_ratio: float


@dataclass
class SmcCompletion:
    signal: Optional[SmcSignalDraft]
    reject_reason: Optional[str]
    detail: str = ""


def evaluate_completion(setup: dict, df_15m, min_stop_pct: Optional[float] = None) -> SmcCompletion:
    """Stop en doel zijn structuur-gebaseerd (de sweep bepaalt de stop, de
    volgende liquidity het doel), alleen de marge eromheen gebruikt
    setup['atr'] (vastgezet bij het bouwen van de setup) in plaats van een
    vast percentage — zie STOP_MARGIN_ATR_MULTIPLE hierboven. sign is voor
    zowel stop als doel hetzelfde teken, dat is geen typefout: voor short
    ligt de stop BOVEN de geveegde high (verder van de entry af) en het doel
    ligt ook BOVEN de liquidity-low (dichter bij de entry, 'net vóór' het
    niveau) — voor long allebei eronder. Rekenvoorbeeld (short):
    sweep_price 2820, liquidity_target 2600 -> stop 2823, doel 2613.

    setup['atr'] is None voor een setup die al "bouwend" stond vóór de
    ATR-marge deze kolom kreeg (zie db._migrate) — valt dan terug op het
    oude vaste percentage (smc_stop_take_margins), puur om zo'n al bestaande
    rij niet alsnog te laten crashen; een nieuwe setup heeft hem altijd gezet."""
    direction = setup["direction"]
    sign = -1 if direction == "long" else 1
    stop_margin, target_margin = smc_stop_take_margins(setup)
    stop_loss = setup["sweep_price"] + stop_margin * sign
    take_profit = setup["liquidity_target"] + target_margin * sign
    entry_price = float(df_15m["close"].iloc[-1])

    # entry_price hierboven is de ACTUELE marktprijs op het moment dat dit
    # signaal gebouwd wordt, niet de prijs van de candle die de afwijzing
    # triggerde — daar zit altijd wat vertraging tussen (de marktscan draait
    # periodiek, niet precies op elke 15m-candle-close). Stop en doel liggen
    # vast op structuurniveaus sinds de setup bouwde, dus als de koers in die
    # tussentijd verder wegliep dan de sniper-prijs (dezelfde stop-hunt-prijs
    # die ook getoond wordt), is de entry al slechter dan de setup
    # veronderstelt — dat eet rechtstreeks in op het rendement zonder dat de
    # risk_reward_ratio-check hieronder dat per se opvangt (een kleine
    # verschuiving kan nog ruim boven de ondergrens blijven). Geen sniper
    # gevonden behandelen we hetzelfde als een te late entry: als het
    # stop-hunt-moment niet meer zichtbaar is binnen het zoekvenster, is de
    # kans klein dat dit nog een verse kans is.
    sniper = indicators.find_sniper_entry_price(direction, df_15m)
    sniper_entry_price, sniper_reason = sniper if sniper else (None, None)
    entry_worse_than_sniper = (
        sniper_entry_price is None
        or (direction == "short" and entry_price < sniper_entry_price)
        or (direction == "long" and entry_price > sniper_entry_price)
    )
    if entry_worse_than_sniper:
        return SmcCompletion(None, "entry_slechter_dan_sniper", detail=(
            f"entry {entry_price:.4f} ligt niet meer aan de juiste kant van de sniper-prijs "
            f"({f'{sniper_entry_price:.4f}' if sniper_entry_price is not None else 'geen sniper gevonden'}, {direction}), "
            "de koers is al verder bewogen dan de setup veronderstelt"
        ))

    # De entry_worse_than_sniper-poort hierboven toetst alleen entry_price
    # tegen de sniper-prijs, niet de sniper-prijs tegen de stop — die twee
    # kunnen nog steeds los van elkaar liggen (zie
    # indicators.sniper_beyond_stop). Puur voor de weergave: de melding zelf
    # blijft ongewijzigd, alleen een inconsistente sniper-regel op de kaart
    # wordt onderdrukt.
    if sniper_entry_price is not None and indicators.sniper_beyond_stop(direction, sniper_entry_price, stop_loss):
        sniper_entry_price, sniper_reason = None, None

    # Stop en doel liggen vast sinds de setup bouwde, de live prijs niet:
    # een afwijzing die al voorbij het doel sloot, of een prijs die sinds de
    # afwijzing boven de stop (short) uitliep, is geen trade meer. Geen
    # ATR-terugval zoals bij patroon — smc's hele premisse is structuur-
    # gebaseerde stop/doel, dan liever geen signaal.
    if not valid_stop_take(direction, entry_price, stop_loss, take_profit):
        return SmcCompletion(None, "stop_take_verkeerde_kant", detail=(
            f"stop {stop_loss:.4f} / doel {take_profit:.4f} liggen niet aan de juiste kant van entry {entry_price:.4f} ({direction})"
        ))

    # Een stop binnen de ruis van een minuutcandle is geen trade maar een muntworp met kosten: in het meetraam
    # won die groep 6% en verloor -0,73R bruto (zie config.SMC_MIN_STOP_PCT).
    min_stop = config.SMC_MIN_STOP_PCT if min_stop_pct is None else min_stop_pct
    stop_pct = abs(entry_price - stop_loss) / entry_price * 100
    if min_stop > 0 and stop_pct < min_stop:
        return SmcCompletion(None, "stop_te_dichtbij", detail=(
            f"stopafstand {stop_pct:.3f}% ligt onder de ondergrens van {min_stop}% "
            f"(stop {stop_loss:.4f} / entry {entry_price:.4f}, {direction})"
        ))

    # Geen stop_within_max_distance-toets hier, bewust anders dan de andere
    # drie detectoren: die grens (1,5%) is gebouwd voor ATR-gebaseerde
    # stops, waar een strakke stop een teken van precisie is. SMC's stop
    # ligt vast op de sweep-prijs (structuur, geen ATR) — die sweep zit op
    # veel coins verder dan 1,5% van de entry af, zonder dat de setup zelf
    # minder geldig is. De hergebruikte grens hield hierdoor structureel
    # goede SMC-setups tegen. De kwaliteitsborging zit al in de eigen
    # stappen hierboven (structuurbreuk, sweep vóór de breuk, confluence-
    # zone, stop/doel aan de juiste kant) en in de R:R-eis hieronder.

    # Zelfde ondergrens als het dagtrading-pad (signal_processor.py), zelfde
    # "geen signaal" in plaats van "signaal met lagere confidence" als
    # hierboven bij valid_stop_take: smc heeft geen pass_pct/hard_gates_ok
    # confidence-schaal om een zwakke verhouding in te laten wegen, dus een
    # setup die er niet aan voldoet mag geen signaal worden.
    risk_distance = abs(entry_price - stop_loss)
    reward_distance = abs(take_profit - entry_price)
    risk_reward_ratio = (reward_distance / risk_distance) if risk_distance else 0.0
    if risk_reward_ratio < MIN_RISK_REWARD_RATIO:
        return SmcCompletion(None, "risico_rendement_te_laag", detail=(
            f"risico/rendement {risk_reward_ratio:.2f} tegen 1 ligt onder de ondergrens van {MIN_RISK_REWARD_RATIO} "
            f"(stop {stop_loss:.4f} / doel {take_profit:.4f} / entry {entry_price:.4f}, {direction})"
        ))

    return SmcCompletion(SmcSignalDraft(
        entry_price, stop_loss, take_profit, sniper_entry_price, sniper_reason, risk_reward_ratio,
    ), None)
