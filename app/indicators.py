"""Technische indicatoren op de 4 uur candle, vaste standaard timeframe."""
import math
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import ta

# Vanaf welke ADX-waarde een trend sterk genoeg is om op te varen. Onder
# deze grens is de markt zijwaarts, en zijn EMA-kruisingen en MACD-signalen
# minder betrouwbaar (whipsaws). 15 in plaats van de klassieke 20-25: bij
# 20 filterde dit vrijwel alle signalen weg (zie scripts/backtest_factors.py),
# 15 laat een ontluikende trend nog meetellen in plaats van alleen een al
# bevestigde.
ADX_MIN = 15.0

# Hoeveel lager de ATR mag liggen dan zijn eigen 20-candle gemiddelde en nog
# als "niet duidelijk aan het samentrekken" tellen. Een harde eis van ATR
# >= gemiddelde is vrijwel een muntworp in een rustige markt; 10% marge
# voorkomt dat kleine, betekenisloze schommelingen de factor laten falen.
ATR_TOLERANCE = 0.9

# Minimaal handelsvolume in de laatste 24 uur (in quote-valuta, meestal
# USDT) voor een hoog vertrouwen signaal. Een technisch perfecte setup op
# een illiquide coin is in de praktijk niet fatsoenlijk uit te voeren
# zonder forse slippage.
MIN_QUOTE_VOLUME_24H = 2_000_000.0

# Ondergrens voor het volume-percentiel (t.o.v. de laatste 20 candles) om als
# bevestigend te tellen. 50 is het mediaan: het huidige volume moet minstens
# gemiddeld hoog staan binnen zijn eigen recente spreiding, niet alleen boven
# een simpel gemiddelde dat door een paar uitschieters vertekend kan zijn.
VOLUME_PERCENTILE_MIN = 50.0


@dataclass
class Indicators:
    price: float
    rsi: float
    macd: float
    macd_signal: float
    volume_ratio: float
    volume_percentile: float
    ema9: float
    ema21: float
    atr: float
    atr_avg20: float
    adx: float
    adx_pos: float
    adx_neg: float


def compute_indicators(df: pd.DataFrame) -> Indicators:
    """Berekent RSI(14), MACD standaard, volume t.o.v. gemiddelde over 20
    candles, EMA9, EMA21, ATR (plus het eigen 20-candle gemiddelde) en
    ADX(14), op basis van een OHLCV DataFrame."""
    close = df["close"]
    high = df["high"]
    low = df["low"]
    volume = df["volume"]

    rsi = ta.momentum.RSIIndicator(close, window=14).rsi()

    macd_indicator = ta.trend.MACD(close)
    macd_line = macd_indicator.macd()
    macd_signal_line = macd_indicator.macd_signal()

    ema9 = ta.trend.EMAIndicator(close, window=9).ema_indicator()
    ema21 = ta.trend.EMAIndicator(close, window=21).ema_indicator()

    atr_series = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()
    atr_avg20 = atr_series.rolling(window=20).mean()

    adx_indicator = ta.trend.ADXIndicator(high, low, close, window=14)
    adx = adx_indicator.adx()
    adx_pos = adx_indicator.adx_pos()
    adx_neg = adx_indicator.adx_neg()

    volume_avg20 = volume.rolling(window=20).mean()
    volume_ratio = volume / volume_avg20
    volume_percentile = volume.tail(20).rank(pct=True) * 100

    last = -1
    return Indicators(
        price=float(close.iloc[last]),
        rsi=float(rsi.iloc[last]),
        macd=float(macd_line.iloc[last]),
        macd_signal=float(macd_signal_line.iloc[last]),
        volume_ratio=float(volume_ratio.iloc[last]),
        volume_percentile=float(volume_percentile.iloc[last]),
        ema9=float(ema9.iloc[last]),
        ema21=float(ema21.iloc[last]),
        atr=float(atr_series.iloc[last]),
        atr_avg20=float(atr_avg20.iloc[last]),
        adx=float(adx.iloc[last]),
        adx_pos=float(adx_pos.iloc[last]),
        adx_neg=float(adx_neg.iloc[last]),
    )


def swing_levels(df: pd.DataFrame, lookback: int = 20) -> tuple[float, float]:
    """Recente swing low en swing high over de laatste `lookback` candles op
    de 4 uur candle. Gebruikt om een stop loss op echte marktstructuur te
    zetten (net onder de laatste 4h low bij een long), in plaats van een
    vaste ATR-afstand die niets zegt over waar de markt zelf steun of
    weerstand heeft laten zien."""
    window = df.tail(lookback)
    return float(window["low"].min()), float(window["high"].max())


def ema_series(df: pd.DataFrame) -> tuple[list[float], list[float]]:
    """Volledige EMA9 en EMA21 reeksen, voor de candlestick grafiek."""
    close = df["close"]
    ema9 = ta.trend.EMAIndicator(close, window=9).ema_indicator()
    ema21 = ta.trend.EMAIndicator(close, window=21).ema_indicator()
    return ema9.tolist(), ema21.tolist()


def check_btc_trend(direction: str, btc_ind: Indicators) -> tuple[str, bool, str]:
    """BTC's eigen trend als vijfde harde factor voor elke andere coin: een
    altcoin long tegen een dalende BTC in is een veel zwakkere trade dan
    dezelfde setup terwijl BTC meebeweegt. Niet van toepassing als het
    signaal zelf al over BTC gaat, dat zou alleen de bestaande trend-factor
    dubbel tellen."""
    btc_up = btc_ind.ema9 > btc_ind.ema21
    wants_up = direction.lower() == "long"
    ok = btc_up if wants_up else not btc_up
    richting = "omhoog" if btc_up else "omlaag"
    detail = f"BTC beweegt {richting}" + ("" if ok else ", tegen deze trade in")
    return ("BTC-trend", ok, detail)


def check_1h_trend(direction: str, ind_1h: Indicators) -> tuple[str, bool, str]:
    """Bevestiging op een tweede, snellere timeframe (1 uur naast de
    hoofd-timeframe van 4 uur). Onafhankelijk bewijs dat de richting ook op
    kortere termijn klopt, niet een extra indicator op dezelfde candle."""
    up_1h = ind_1h.ema9 > ind_1h.ema21
    wants_up = direction.lower() == "long"
    ok = up_1h if wants_up else not up_1h
    kant = "boven" if up_1h else "onder"
    detail = f"EMA9 {kant} EMA21 op 1u" + ("" if ok else ", nog geen bevestiging op de snellere timeframe")
    return ("1u bevestiging", ok, detail)


def check_1h_rsi(direction: str, ind_1h: Indicators) -> tuple[str, bool, str]:
    """RSI-bevestiging op 1 uur naast de RSI-check op de hoofd-timeframe van
    4 uur: dezelfde soort check als check_1h_trend, maar voor momentum-
    uitputting in plaats van trendrichting. Een 4-uur candle kan nog
    ruimte tonen terwijl de snellere timeframe al overbought/oversold
    staat.

    Symmetrisch sinds de RSI_OVERSOLD/RSI_OVERBOUGHT-wijziging in
    basic_factors: oversold telt nu ook tegen een long (niet alleen
    overbought), en overbought telt ook tegen een short (niet alleen
    oversold) — zelfde reden als daar, zie die docstring."""
    direction = direction.lower()
    if direction == "long":
        ok = RSI_OVERSOLD < ind_1h.rsi < RSI_OVERBOUGHT
        if ok:
            detail = f"RSI {ind_1h.rsi:.0f} op 1u"
        elif ind_1h.rsi >= RSI_OVERBOUGHT:
            detail = f"RSI {ind_1h.rsi:.0f} op 1u, overbought op de snellere timeframe"
        else:
            detail = f"RSI {ind_1h.rsi:.0f} op 1u, oversold op de snellere timeframe, geen bevestiging voor long"
    else:
        ok = RSI_OVERSOLD < ind_1h.rsi < RSI_OVERBOUGHT
        if ok:
            detail = f"RSI {ind_1h.rsi:.0f} op 1u"
        elif ind_1h.rsi <= RSI_OVERSOLD:
            detail = f"RSI {ind_1h.rsi:.0f} op 1u, oversold op de snellere timeframe"
        else:
            detail = f"RSI {ind_1h.rsi:.0f} op 1u, overbought op de snellere timeframe, geen bevestiging voor short"
    return ("RSI 1u", ok, detail)


def check_daily_trend(direction: str, daily_ind: Indicators) -> tuple[str, bool, str]:
    """Structurele trend op de daily candle: bevestigt de langere-termijn
    richting waar een swing-opzet (bijvoorbeeld een weekly patroon) op
    steunt, onafhankelijk van wat de snellere 4-uur candle op dit moment
    laat zien. Zelfde soort check als check_1h_trend, andere
    tijdshorizon."""
    up_daily = daily_ind.ema9 > daily_ind.ema21
    wants_up = direction.lower() == "long"
    ok = up_daily if wants_up else not up_daily
    kant = "boven" if up_daily else "onder"
    detail = f"EMA9 {kant} EMA21 op daily" + ("" if ok else ", geen bevestiging op de dagcandle")
    return ("Daily-trend", ok, detail)


def check_divergence(df: pd.DataFrame, direction: str, lookback: int = 20) -> tuple[str, bool, str]:
    """Waarschuwt voor RSI/prijs-divergentie: bij een long is een hogere
    prijstop met een lagere RSI-top een klassiek teken dat het momentum al
    afzwakt terwijl de prijs nog stijgt, een omkeer kan dichtbij zijn. Bij
    een short geldt het spiegelbeeld (lagere bodem, hogere RSI-bodem).

    Vereenvoudigde aanpak: de laatste `lookback` candles in twee helften
    verdeeld, de piek (long) of dal (short) van elke helft vergeleken in
    zowel prijs als RSI. Geen volwaardige zigzag/pivot-detectie, maar een
    bruikbare benadering op de tijdshorizon van dit systeem."""
    rsi_series = ta.momentum.RSIIndicator(df["close"], window=14).rsi()
    window_close = df["close"].tail(lookback).reset_index(drop=True)
    window_rsi = rsi_series.tail(lookback).reset_index(drop=True)

    mid = len(window_close) // 2
    if mid < 2:
        return ("Divergentie", True, "te weinig candles om divergentie te beoordelen")

    first_close, second_close = window_close.iloc[:mid], window_close.iloc[mid:]
    first_rsi, second_rsi = window_rsi.iloc[:mid], window_rsi.iloc[mid:]

    if direction.lower() == "long":
        first_idx, second_idx = first_close.idxmax(), second_close.idxmax()
        price_higher_high = second_close.max() > first_close.max()
        rsi_lower_high = window_rsi[second_idx] < window_rsi[first_idx]
        warning = price_higher_high and rsi_lower_high
        detail = "prijs zet een hogere top neer terwijl RSI juist zakt, momentum zwakt af" if warning \
            else "geen waarschuwende divergentie"
    else:
        first_idx, second_idx = first_close.idxmin(), second_close.idxmin()
        price_lower_low = second_close.min() < first_close.min()
        rsi_higher_low = window_rsi[second_idx] > window_rsi[first_idx]
        warning = price_lower_low and rsi_higher_low
        detail = "prijs zet een lagere bodem neer terwijl RSI juist stijgt, momentum zwakt af" if warning \
            else "geen waarschuwende divergentie"

    return ("Divergentie", not warning, detail)


def check_candle_pattern(df: pd.DataFrame, direction: str) -> tuple[str, bool, str]:
    """Bullish/bearish engulfing op de signaal-candle (de laatste, meest
    recente candle): die candle slokt de vorige volledig op in tegengestelde
    richting, een klassiek omslagpatroon. Extra bevestiging op de candle
    zelf, naast de indicatoren die alleen naar prijs en gemiddelden kijken."""
    direction = direction.lower()
    if len(df) < 2:
        return ("Candlepatroon", True, "te weinig candles om een patroon te beoordelen")

    prev = df.iloc[-2]
    last = df.iloc[-1]
    prev_bullish = prev["close"] > prev["open"]
    prev_bearish = prev["close"] < prev["open"]
    last_bullish = last["close"] > last["open"]
    last_bearish = last["close"] < last["open"]

    bullish_engulfing = (
        prev_bearish and last_bullish
        and last["open"] <= prev["close"] and last["close"] >= prev["open"]
    )
    bearish_engulfing = (
        prev_bullish and last_bearish
        and last["open"] >= prev["close"] and last["close"] <= prev["open"]
    )

    if direction == "long":
        ok = bullish_engulfing
        detail = "bullish engulfing op de signaal-candle" if ok else "geen bullish engulfing patroon"
    else:
        ok = bearish_engulfing
        detail = "bearish engulfing op de signaal-candle" if ok else "geen bearish engulfing patroon"

    return ("Candlepatroon", ok, detail)


def check_liquidity(quote_volume_24h: float, minimum: float = MIN_QUOTE_VOLUME_24H) -> tuple[str, bool, str]:
    """Handelsvolume van de laatste 24 uur, tegen een ondergrens. Een
    technisch perfecte setup op een dun verhandelde coin levert in de
    praktijk slippage op die de hele edge kan opeten."""
    ok = quote_volume_24h >= minimum
    volume_str = f"€{quote_volume_24h:,.0f}".replace(",", ".")
    detail = f"24u volume {volume_str}"
    if not ok:
        minimum_str = f"€{minimum:,.0f}".replace(",", ".")
        detail += f", onder de grens van {minimum_str}"
    return ("Liquiditeit", ok, detail)


def check_volume_percentile(ind: Indicators, minimum: float = VOLUME_PERCENTILE_MIN) -> tuple[str, bool, str]:
    """Volume als percentiel binnen de laatste 20 candles, naast de simpele
    Volume-factor die alleen tegen het gemiddelde toetst. Een volume dat nét
    boven het gemiddelde ligt (1.01x) kan alsnog laag zijn t.o.v. de recente
    spreiding als er een paar extreme uitschieters tussen zitten; het
    percentiel zet dezelfde meting relatief tegen zijn eigen recente
    verdeling af in plaats van tegen één gemiddelde."""
    ok = ind.volume_percentile >= minimum
    detail = f"volume in {ind.volume_percentile:.0f}e percentiel van de laatste 20 candles"
    if not ok:
        detail += f", onder de {minimum:.0f}e percentiel grens"
    return ("Volume-percentiel", ok, detail)


# Hoe lang de "staart" van een hamer/hangende man/vallende ster/omgekeerde
# hamer minimaal moet zijn t.o.v. het candle-lichaam, om als duidelijk
# patroon te tellen in plaats van een gewone candle met iets meer schaduw
# dan gemiddeld.
HAMMER_SHADOW_RATIO = 2.0

# Hoe klein de schaduw aan de ANDERE kant van het lichaam moet blijven
# (t.o.v. het lichaam zelf), zodat een candle met twee lange schaduwen
# (spinning top) niet per ongeluk als hamer of ster telt.
HAMMER_OPPOSITE_SHADOW_MAX_RATIO = 0.5

# Hoe klein het lichaam moet zijn t.o.v. de volledige candle-range
# (high - low) om als doji te tellen.
DOJI_BODY_MAX_RATIO = 0.1

# Relatieve tolerantie voor float-vergelijkingen in patroon-detectie. Bij
# berekende waarden (b.v. 90.65 - 90.6 = 0.05) kan floating-point
# afrondingsfouten ervoor zorgen dat een waarde net onder of boven het
# verwachte drempelpunt uit komt (0.05000000000001137 vs
# 0.04999999999999716). Een vaste absolute tolerantie (b.v. 1e-9) is
# onbruikbaar voor de vele tokens die dit systeem verwerkt: sub-cent coins
# en meme-tokens hebben OHLC-deltas van 1e-7 tot 1e-9, waar een absolute 1e-9
# tolerantie betekenisloos of zelfs schadelijk kan zijn. Een relatieve
# tolerantie schalen naar de grootte-orde van de getallen zelf en blijft dus
# nuttig over het hele bereik van mogelijke tokenprijs.
PATTERN_COMPARISON_TOLERANCE = 1e-9


def _geq_with_tolerance(a: float, b: float) -> bool:
    """Controleer of a >= b, met floating-point tolerantie. Gebruikt door
    patroon-detectie voor drempel-vergelijkingen."""
    return a >= b or math.isclose(a, b, rel_tol=PATTERN_COMPARISON_TOLERANCE, abs_tol=0)


def _leq_with_tolerance(a: float, b: float) -> bool:
    """Controleer of a <= b, met floating-point tolerantie. Gebruikt door
    patroon-detectie voor drempel-vergelijkingen."""
    return a <= b or math.isclose(a, b, rel_tol=PATTERN_COMPARISON_TOLERANCE, abs_tol=0)


def detect_single_candle_patterns(
    df: pd.DataFrame, index: int, ema9_series: list[float], ema21_series: list[float],
) -> list[tuple[str, str]]:
    """Hammer/Hanging Man/Shooting Star/Inverted Hammer/Doji op de candle
    op `index`, elk als (naam, richting) met richting 'bullish' of
    'bearish'. Hamer/ster-patronen zijn alleen zinvol als omkeersignaal ná
    een duidelijke trend, dus de trend vlak vóór de candle (ema9[index-1]
    t.o.v. ema21[index-1], dezelfde vergelijking als de basisfactor Trend)
    bepaalt welke kant elk patroon op wijst. Levert een lege lijst op bij
    te weinig voorafgaande candles, of als geen enkel patroon matcht. Een
    candle kan meerdere patronen tegelijk matchen bij grensgevallen (een
    lichaam van 0 met een lange onderstaart is zowel Hammer als Doji) —
    de aanroeper beslist wat daarmee gebeurt."""
    if index < 1 or index >= len(df):
        return []
    ema9_prev = ema9_series[index - 1]
    ema21_prev = ema21_series[index - 1]
    if ema9_prev != ema9_prev or ema21_prev != ema21_prev:  # NaN tijdens EMA-opwarmperiode
        return []

    row = df.iloc[index]
    open_, high, low, close = row["open"], row["high"], row["low"], row["close"]
    body = abs(close - open_)
    upper_shadow = high - max(open_, close)
    lower_shadow = min(open_, close) - low
    candle_range = high - low
    if candle_range <= 0:
        # open == high == low == close: een candle zonder enige range heeft
        # geen vorm om te herkennen. Zonder deze guard wordt elke drempel-
        # vergelijking hieronder triviaal waar (0 >= 0 / 0 <= 0) en matcht
        # zo'n candle Hammer, Inverted Hammer én Doji tegelijk — drie
        # tegenstrijdige patronen op één candle. Komt voor bij dun
        # verhandelde coins en bij een net geopende, nog vormende candle.
        return []

    trend_up = ema9_prev > ema21_prev
    trend_down = ema9_prev < ema21_prev

    patterns: list[tuple[str, str]] = []

    if _geq_with_tolerance(lower_shadow, body * HAMMER_SHADOW_RATIO) and _leq_with_tolerance(upper_shadow, body * HAMMER_OPPOSITE_SHADOW_MAX_RATIO):
        if trend_down:
            patterns.append(("Hammer", "bullish"))
        elif trend_up:
            patterns.append(("Hanging Man", "bearish"))

    if _geq_with_tolerance(upper_shadow, body * HAMMER_SHADOW_RATIO) and _leq_with_tolerance(lower_shadow, body * HAMMER_OPPOSITE_SHADOW_MAX_RATIO):
        if trend_up:
            patterns.append(("Shooting Star", "bearish"))
        elif trend_down:
            patterns.append(("Inverted Hammer", "bullish"))

    if _leq_with_tolerance(body, candle_range * DOJI_BODY_MAX_RATIO):
        if trend_up:
            patterns.append(("Doji", "bearish"))
        elif trend_down:
            patterns.append(("Doji", "bullish"))

    return patterns


def detect_star_pattern(df: pd.DataFrame, index: int) -> Optional[tuple[str, str]]:
    """Morning Star (bullish) of Evening Star (bearish) op de candles
    index-2, index-1, index. De buitenste twee candles moeten allebei een
    lichaam hebben dat minstens het 20-candle gemiddelde haalt (dezelfde
    soort vergelijking als ATR_TOLERANCE elders in dit bestand) — anders
    is dit geen sterpatroon maar drie gewone candles. None als er geen
    match is, of als index < 2."""
    if index < 2:
        return None

    bodies = (df["close"] - df["open"]).abs()
    history = bodies.iloc[:index - 1]
    if history.empty:
        return None
    body_avg20 = history.tail(20).mean()

    first = df.iloc[index - 2]
    middle = df.iloc[index - 1]
    last = df.iloc[index]

    first_body = abs(first["close"] - first["open"])
    first_range = first["high"] - first["low"]
    middle_range = middle["high"] - middle["low"]
    last_body = abs(last["close"] - last["open"])

    # Rejection guards: "te klein lichaam" / "te grote middencandle" moeten
    # alleen afwijzen bij een DUIDELIJK tekort, niet bij exact-op-de-grens.
    # Geschreven als "niet (>=/<=  met tolerantie)" zodat een waarde precies
    # op de drempel (of er met een floating-point-afrondingsfout net onder/
    # boven) wordt geaccepteerd in plaats van afgewezen — een tolerantie
    # hoort een grensgeval juist toelaten, niet strenger maken.
    if not _geq_with_tolerance(first_body, body_avg20) or not _geq_with_tolerance(last_body, body_avg20):
        return None
    if first_range > 0 and not _leq_with_tolerance(middle_range, first_range * (DOJI_BODY_MAX_RATIO * 3)):
        return None

    first_bearish = first["close"] < first["open"]
    first_bullish = first["close"] > first["open"]
    last_bullish = last["close"] > last["open"]
    last_bearish = last["close"] < last["open"]
    first_midpoint = (first["open"] + first["close"]) / 2

    # Midpoint-vergelijking blijft bewust strikt (geen tolerantie): dit is
    # de richtingsbevestiging zelf, niet een drempel met meetruis. Een close
    # exact op het midden is genuinely ambigu en moet niet als bevestiging
    # tellen, ook al is dat op een ronde prijs-grid best bereikbaar.
    if first_bearish and last_bullish and last["close"] > first_midpoint:
        return ("Morning Star", "bullish")
    if first_bullish and last_bearish and last["close"] < first_midpoint:
        return ("Evening Star", "bearish")
    return None


DEFAULT_PATTERN_SCAN_LOOKBACK = 100


def check_candle_pattern_extended(
    df: pd.DataFrame, direction: str, ema9_series: list[float], ema21_series: list[float],
) -> tuple[str, bool, str]:
    """Combineert de bestaande engulfing-check met de zeven nieuwe
    candlestick-patronen (Hammer, Hanging Man, Shooting Star, Inverted
    Hammer, Doji, Morning Star, Evening Star) tot dezelfde factor
    'Candlepatroon': matcht er
    minstens één patroon in de kant van `direction` op de laatste candle,
    dan is de factor gehaald. Vervangt de aanroep van check_candle_pattern
    in signal_processor.compute_advanced_extra_factors (check_candle_pattern
    zelf blijft ongewijzigd bestaan)."""
    direction = direction.lower()
    last_index = len(df) - 1

    _, engulfing_ok, engulfing_detail = check_candle_pattern(df, direction)
    if engulfing_ok:
        return ("Candlepatroon", True, engulfing_detail)

    matches = detect_single_candle_patterns(df, last_index, ema9_series, ema21_series)
    star = detect_star_pattern(df, last_index)
    if star:
        matches.append(star)

    wants_bullish = direction == "long"
    for name, pattern_direction in matches:
        if (pattern_direction == "bullish") == wants_bullish:
            return ("Candlepatroon", True, f"{name} op de signaal-candle")

    return (
        "Candlepatroon", False,
        "geen candlestick-patroon (engulfing, hamer, ster, doji) in de juiste richting op de signaal-candle",
    )


def scan_candle_patterns(
    df: pd.DataFrame, ema9_series: list[float], ema21_series: list[float],
    lookback: int = DEFAULT_PATTERN_SCAN_LOOKBACK,
) -> list[dict]:
    """Alle single-candle- en sterpatronen over de laatste `lookback`
    candles, ELK gevonden patroon (niet gefilterd op een verwachte
    richting — dit is voor weergave op de grafiek, niet voor de score).
    Elk element: {"index": int, "pattern": str, "direction": "bullish"|"bearish"}."""
    start = max(0, len(df) - lookback)
    found: list[dict] = []
    for i in range(start, len(df)):
        for name, pattern_direction in detect_single_candle_patterns(df, i, ema9_series, ema21_series):
            found.append({"index": i, "pattern": name, "direction": pattern_direction})
        star = detect_star_pattern(df, i)
        if star:
            found.append({"index": i, "pattern": star[0], "direction": star[1]})
    return found


# Hoeveel candles aan elke kant moeten "lager" (voor een pivot-high) of
# "hoger" (voor een pivot-low) zijn, wil een candle als lokaal keerpunt
# tellen. 3 is streng genoeg om ruis (elke kleine schommeling) niet als
# keerpunt te zien, maar laat genoeg pivots over op de laatste 100
# candles om zinvol te kunnen clusteren.
SR_PIVOT_WINDOW = 3

# Hoeveel candles terug de zone-detectie meeneemt. Ruim genoeg voor
# meerdere testen van dezelfde zone, niet zo ruim dat een allang niet meer
# relevant niveau van maanden geleden nog meetelt.
SR_ZONE_LOOKBACK = 100

# Hoe dicht twee pivot-prijzen bij elkaar moeten liggen (als fractie van
# de prijs) om tot dezelfde zone te horen. Te klein: elke pivot wordt zijn
# eigen "zone" van 1 punt, nooit genoeg touches. Te groot: totaal
# ongerelateerde niveaus versmelten tot één onbruikbaar brede band.
SR_ZONE_CLUSTER_TOLERANCE_PCT = 0.005

# Minimaal aantal pivots in een cluster om als echte zone te tellen. Eén
# pivot is geen patroon, twee is het begin van "de prijs kwam hier al
# eerder terug".
SR_ZONE_MIN_TOUCHES = 2


@dataclass
class SRZone:
    price_low: float
    price_high: float
    touches: int


def detect_sr_zones(df: pd.DataFrame, lookback: int = SR_ZONE_LOOKBACK) -> list[SRZone]:
    """Vindt structurele steun/weerstand-zones in de laatste `lookback`
    candles: eerst lokale keerpunten (pivot-highs/-lows, een candle die
    hoger/lager is dan SR_PIVOT_WINDOW candles aan beide kanten), daarna
    geclusterd tot zones (pivots binnen SR_ZONE_CLUSTER_TOLERANCE_PCT van
    elkaar horen bij dezelfde zone). Een zone telt pas mee vanaf
    SR_ZONE_MIN_TOUCHES pivots. Geen aparte steun/weerstand-classificatie:
    dezelfde zone kan beide rollen spelen afhankelijk van de kant waar de
    prijs vandaan komt, dat wordt pas bij gebruik (risk.py, de score-
    factor) bepaald aan de hand van de huidige prijs."""
    window = df.tail(lookback).reset_index(drop=True)
    n = len(window)
    pivots: list[float] = []

    for i in range(SR_PIVOT_WINDOW, n - SR_PIVOT_WINDOW):
        high_i = window["high"].iloc[i]
        low_i = window["low"].iloc[i]
        left_highs = window["high"].iloc[i - SR_PIVOT_WINDOW:i]
        right_highs = window["high"].iloc[i + 1:i + SR_PIVOT_WINDOW + 1]
        if high_i > left_highs.max() and high_i > right_highs.max():
            pivots.append(float(high_i))
        left_lows = window["low"].iloc[i - SR_PIVOT_WINDOW:i]
        right_lows = window["low"].iloc[i + 1:i + SR_PIVOT_WINDOW + 1]
        if low_i < left_lows.min() and low_i < right_lows.min():
            pivots.append(float(low_i))

    if not pivots:
        return []

    pivots.sort()
    clusters: list[list[float]] = [[pivots[0]]]
    for price in pivots[1:]:
        cluster_high = clusters[-1][-1]
        if price <= cluster_high * (1 + SR_ZONE_CLUSTER_TOLERANCE_PCT):
            clusters[-1].append(price)
        else:
            clusters.append([price])

    return [
        SRZone(price_low=min(c), price_high=max(c), touches=len(c))
        for c in clusters
        if len(c) >= SR_ZONE_MIN_TOUCHES
    ]


# Hoe ver een zone maximaal van de entry mag liggen (in ATR) om nog als
# kandidaat te tellen voor de stop/take-verfijning en deze factor. Een
# zone die zes keer de ATR verderop ligt is geen realistisch punt meer
# voor déze trade, ook al is de zone zelf sterk.
SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE = 6.0


def check_sr_zone(direction: str, entry_price: float, atr: float, zones: list[SRZone]) -> tuple[str, bool, str]:
    """Is er een bruikbare zone aan de stop-kant van de prijs (onder de
    entry bij long, erboven bij short) binnen SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE
    x ATR? Zelfde kant-bepaling als risk.compute_stop_take_from_levels
    gebruikt voor community-niveaus, hier toegepast op zelf-gedetecteerde
    zones. Geen aparte richting-afhankelijke detectie nodig: een zone is
    een zone, welke kant hem "steun" maakt hangt puur af van waar de
    entry-prijs zit."""
    direction = direction.lower()
    max_distance = SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE * atr
    edges = [edge for zone in zones for edge in (zone.price_low, zone.price_high)]

    if direction == "long":
        candidates = [e for e in edges if e < entry_price and entry_price - e <= max_distance]
    else:
        candidates = [e for e in edges if e > entry_price and e - entry_price <= max_distance]

    if not candidates:
        return ("Steun/weerstand", False, "geen zone dichtbij genoeg voor een bruikbaar niveau")

    nearest = max(candidates) if direction == "long" else min(candidates)
    distance_atr = abs(entry_price - nearest) / atr if atr else 0.0
    return ("Steun/weerstand", True, f"zone op {distance_atr:.1f}x ATR afstand")


# Basisversie: 3 van de 4 factoren is genoeg. Alle 4 verplicht bleek te
# streng, één factor die nét mist (bijvoorbeeld volume op 0.97x in plaats
# van 1.0x) blokkeerde dan een verder overtuigend signaal volledig. Bij 3
# van de 4 blijft welke factor(en) niet klopten zichtbaar in de meegestuurde
# uitleg, zodat de gebruiker zelf ziet waar de kans zwakker staat.
BASIC_CONFIRM_MIN_PASSED = 3

# In de uitgebreide versie telt geen enkele factor apart als harde eis: met
# 10 losse factoren blokkeert anders één marginale miss (bijvoorbeeld volume
# op 0.89x in plaats van 1.0x) een verder overtuigend signaal volledig,
# terwijl 9 van de 10 factoren wel klopten. Minstens 6 van de 10 (60%) is
# hier de grens: is dat gehaald, dan is het een melding waard, en blijft het
# aan de gebruiker zelf om op basis van de zichtbare ✓/✗ per factor te
# beslissen of hij hem neemt. Vier van deze 10 factoren (BTC-trend, 1u
# bevestiging, divergentie, liquiditeit) tellen "fail-closed" mee: lukt het
# ophalen van de data ervoor niet, dan telt de factor als niet gehaald in
# plaats van dat de melding daarop crasht of de factor overslaat, dus een
# tijdelijke ophaalfout kan in het slechtste geval één factor kosten.
CONFIRM_THRESHOLD = 0.6


# Grenzen voor de RSI-check in basic_factors/check_1h_rsi. Symmetrisch:
# oversold telt tegen een long, overbought telt tegen een short, niet
# alleen andersom. Eerdere versie liet oversold ongemoeid bij een long
# (de gedachte was: oversold + een net omslaande EMA/MACD is een klassieke
# instapkans) — maar RSI diep oversold op zowel 4u als 1u kan net zo goed
# betekenen dat de neergaande beweging nog niet echt gekeerd is en de
# EMA-kruising gewoon achterloopt. Bewuste, strengere keuze van de
# product owner: liever een gemiste kans dan hoog vertrouwen geven aan een
# long die tegen een nog actieve downtrend in gaat.
RSI_OVERBOUGHT = 75
RSI_OVERSOLD = 25


def basic_factors(direction: str, ind: Indicators) -> list[tuple[str, bool, str]]:
    """De vier basisfactoren (trend, momentum, RSI, volume) als losse
    (naam, ok, detail) tuples, onafhankelijk van enige drempel-beslissing.
    Gebruikt door confirms_direction voor de day-trading toets, en door de
    swing-toets in signal_processor.py om dezelfde factoren te tonen op
    een andere tijdshorizon zonder een gecombineerd vertrouwensoordeel."""
    direction = direction.lower()
    trend_up = ind.ema9 > ind.ema21
    momentum_up = ind.macd > ind.macd_signal

    if direction == "long":
        trend_ok = trend_up
        trend_detail = "EMA9 boven EMA21" if trend_up else "EMA9 onder EMA21, geen opwaartse trend"
        momentum_ok = momentum_up
        momentum_detail = ("MACD boven signaallijn" if momentum_up
                            else "MACD onder signaallijn, geen opwaarts momentum")
        rsi_ok = RSI_OVERSOLD < ind.rsi < RSI_OVERBOUGHT
        if rsi_ok:
            rsi_detail = f"RSI {ind.rsi:.0f}"
        elif ind.rsi >= RSI_OVERBOUGHT:
            rsi_detail = f"RSI {ind.rsi:.0f}, overbought"
        else:
            rsi_detail = f"RSI {ind.rsi:.0f}, oversold, geen bevestiging voor long"
    elif direction == "short":
        trend_ok = not trend_up
        trend_detail = "EMA9 onder EMA21" if trend_ok else "EMA9 boven EMA21, geen neerwaartse trend"
        momentum_ok = not momentum_up
        momentum_detail = ("MACD onder signaallijn" if momentum_ok
                            else "MACD boven signaallijn, geen neerwaarts momentum")
        rsi_ok = RSI_OVERSOLD < ind.rsi < RSI_OVERBOUGHT
        if rsi_ok:
            rsi_detail = f"RSI {ind.rsi:.0f}"
        elif ind.rsi <= RSI_OVERSOLD:
            rsi_detail = f"RSI {ind.rsi:.0f}, oversold"
        else:
            rsi_detail = f"RSI {ind.rsi:.0f}, overbought, geen bevestiging voor short"
    else:
        raise ValueError(f"onbekende richting: {direction}")

    volume_ok = ind.volume_ratio >= 1.0
    volume_detail = f"volume {ind.volume_ratio:.2f}x gemiddeld" + ("" if volume_ok else ", onder gemiddeld")

    return [
        ("Trend", trend_ok, trend_detail),
        ("Momentum", momentum_ok, momentum_detail),
        ("RSI", rsi_ok, rsi_detail),
        ("Volume", volume_ok, volume_detail),
    ]


def confirms_direction(
    ind: Indicators, direction: str, extra_factors: list[tuple[str, bool, str]] | None = None,
    include_advanced: bool = False,
) -> tuple[bool, str]:
    """Bepaalt of de technische data de richting uit het Discord bericht steunt.

    Basisversie (`include_advanced=False`, de standaard): vier factoren,
    elk met een duidelijke ✓ of ✗, allemaal vereist:
    - trend: EMA9 t.o.v. EMA21 moet de richting volgen
    - momentum: MACD lijn t.o.v. signaallijn moet de richting volgen
    - RSI mag niet al extreem tegen de richting in zitten (overbought bij
      long, oversold bij short)
    - volume moet minstens gemiddeld zijn, anders is de beweging niet
      overtuigend

    Uitgebreide versie (`include_advanced=True`, aan via
    config.ENABLE_ADVANCED_FACTORS): daar komen twee vaste factoren bij,
    trendsterkte (ADX) en volatiliteit (ATR t.o.v. zijn eigen 20-candle
    gemiddelde), plus wat er in `extra_factors` meegegeven wordt
    (BTC-trend, 1u bevestiging, divergentie, liquiditeit: elk een
    (naam, ok, detail) tuple, berekend buiten deze functie omdat ze andere
    data nodig hebben). Bevestigd is hier een kwestie van hoeveel van de
    factoren in totaal kloppen (zie CONFIRM_THRESHOLD), niet van elke losse
    factor apart hard vereisen: bij 10 factoren samen blokkeert anders één
    marginale miss een verder overtuigend signaal.

    Ontbreekt een extra check (bijvoorbeeld BTC-trend bij een BTC-signaal
    zelf), dan wordt hij simpelweg niet meegegeven en telt hij niet mee.
    """
    direction = direction.lower()
    if direction not in ("long", "short"):
        return False, f"onbekende richting: {direction}"
    factors = basic_factors(direction, ind)

    if not include_advanced:
        breakdown = " | ".join(f"{'✓' if ok else '✗'} {name}: {detail}" for name, ok, detail in factors)
        confirmed = sum(1 for _, ok, _ in factors if ok) >= BASIC_CONFIRM_MIN_PASSED
        return confirmed, breakdown

    strong_enough = ind.adx >= ADX_MIN
    direction_aligned = ind.adx_pos > ind.adx_neg if direction == "long" else ind.adx_neg > ind.adx_pos
    adx_ok = strong_enough and direction_aligned
    adx_detail = f"ADX {ind.adx:.0f}"
    if not strong_enough:
        adx_detail += ", trend te zwak/zijwaarts"
    elif not direction_aligned:
        adx_detail += ", trend sterk maar in de verkeerde richting"

    volatility_ok = ind.atr >= ind.atr_avg20 * ATR_TOLERANCE
    volatility_detail = f"ATR {ind.atr:.4f}" + (
        " (stijgend)" if volatility_ok else f" ruim onder het 20-candle gemiddelde ({ind.atr_avg20:.4f}), markt trekt samen"
    )
    factors += [
        ("Trendsterkte", adx_ok, adx_detail),
        ("Volatiliteit", volatility_ok, volatility_detail),
        check_volume_percentile(ind),
    ]
    if extra_factors:
        factors.extend(extra_factors)

    breakdown = " | ".join(f"{'✓' if ok else '✗'} {name}: {detail}" for name, ok, detail in factors)

    passed = sum(1 for _, ok, _ in factors if ok)
    confirmed = (passed / len(factors)) >= CONFIRM_THRESHOLD
    return confirmed, breakdown
