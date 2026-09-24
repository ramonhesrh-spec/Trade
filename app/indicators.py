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

    last = -1
    # De laatste candle is bij Binance meestal nog "in wording" (nog niet
    # gesloten): zijn volume-tot-nu-toe vergelijken met het gemiddelde/de
    # laatste 20 VOLLEDIGE candles geeft bijna altijd een belachelijk lage
    # ratio/percentiel, los van de echte marktsituatie — vooral bij een
    # uurlijkse scan op een 4u-candle zit je 3 van de 4 keer middenin de
    # candle. Prijs/RSI/MACD/EMA gebruiken bewust wel de live, nog vormende
    # candle (dat is precies de bedoeling, je wil de actuele prijs), alleen
    # de twee volume-metingen kijken naar de laatst AFGESLOTEN candle om
    # dit scheeftrekken te voorkomen.
    has_closed_candle = len(volume) > 1
    volume_last_closed = -2 if has_closed_candle else last
    # Alles tot en met de laatst afgesloten candle (dus de nog vormende
    # laatste candle eruit als die er is), dan de laatste 20 daarvan.
    volume_percentile_window = (volume.iloc[:-1] if has_closed_candle else volume).tail(20)
    volume_percentile = volume_percentile_window.rank(pct=True) * 100

    return Indicators(
        price=float(close.iloc[last]),
        rsi=float(rsi.iloc[last]),
        macd=float(macd_line.iloc[last]),
        macd_signal=float(macd_signal_line.iloc[last]),
        volume_ratio=float(volume_ratio.iloc[volume_last_closed]),
        volume_percentile=float(volume_percentile.iloc[-1]),
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


def btc_is_flat(btc_ind: Indicators) -> bool:
    """True als BTC zelf geen duidelijke trend heeft (EMA9 en EMA21 liggen
    te dicht bij elkaar, genormaliseerd op BTC's eigen ATR). Gebruikt door
    de autonome marktscan om altcoin-signalen deze cyclus over te slaan:
    bij een zijwaartse BTC-markt geven altcoin-signalen vaker valse
    uitslagen. BTC zelf blijft altijd meedoen, die kan niet circulair van
    zijn eigen trend afhangen."""
    if not btc_ind.atr:
        return False
    return abs(btc_ind.ema9 - btc_ind.ema21) < BTC_FLAT_EMA_GAP_ATR_MULTIPLE * btc_ind.atr


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


def check_daily_rsi(direction: str, daily_ind: Indicators) -> tuple[str, bool, str]:
    """RSI-bevestiging op de dagcandle, naast RSI (4u) en RSI 1u: zelfde
    symmetrische oversold/overbought-check (zie RSI_OVERSOLD/RSI_OVERBOUGHT
    hierboven), nu op de langzaamste van de drie tijdshorizons. Hergebruikt
    daily_ind, die check_daily_trend hiernaast ook al gebruikt — geen
    extra candle-ophaal nodig."""
    direction = direction.lower()
    if direction == "long":
        ok = RSI_OVERSOLD < daily_ind.rsi < RSI_OVERBOUGHT
        if ok:
            detail = f"RSI {daily_ind.rsi:.0f} op daily"
        elif daily_ind.rsi >= RSI_OVERBOUGHT:
            detail = f"RSI {daily_ind.rsi:.0f} op daily, overbought op de dagcandle"
        else:
            detail = f"RSI {daily_ind.rsi:.0f} op daily, oversold op de dagcandle, geen bevestiging voor long"
    else:
        ok = RSI_OVERSOLD < daily_ind.rsi < RSI_OVERBOUGHT
        if ok:
            detail = f"RSI {daily_ind.rsi:.0f} op daily"
        elif daily_ind.rsi <= RSI_OVERSOLD:
            detail = f"RSI {daily_ind.rsi:.0f} op daily, oversold op de dagcandle"
        else:
            detail = f"RSI {daily_ind.rsi:.0f} op daily, overbought op de dagcandle, geen bevestiging voor short"
    return ("RSI daily", ok, detail)


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
    """Bullish/bearish engulfing op de signaal-candle: die candle slokt de
    vorige volledig op in tegengestelde richting, een klassiek
    omslagpatroon. Extra bevestiging op de candle zelf, naast de
    indicatoren die alleen naar prijs en gemiddelden kijken.

    Gebruikt de laatst AFGESLOTEN candle, niet de allerlaatste: zelfde
    reden als de Volume-factor in compute_indicators — de allerlaatste
    candle is meestal nog in wording, en een engulfing-vorm is per
    definitie een afgesloten-candle-patroon. Halverwege een candle kan de
    vorm nog compleet veranderen voor hij sluit."""
    direction = direction.lower()
    if len(df) < 3:
        return ("Candlepatroon", True, "te weinig candles om een patroon te beoordelen")

    last_closed = len(df) - 2
    prev = df.iloc[last_closed - 1]
    last = df.iloc[last_closed]
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
    zelf blijft ongewijzigd bestaan).

    Gebruikt de laatst AFGESLOTEN candle als signaal-candle, niet de
    allerlaatste: zelfde reden als check_candle_pattern hierboven — de
    allerlaatste candle is meestal nog in wording, en elk van deze
    patronen (engulfing, hamer, ster, doji) is per definitie een
    afgesloten-candle-vorm."""
    direction = direction.lower()
    last_index = len(df) - 2

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
    Elk element: {"index": int, "pattern": str, "direction": "bullish"|"bearish"}.

    Sluit de allerlaatste candle uit, net als check_candle_pattern_extended:
    die staat meestal nog niet vast, dus een patroon-marker daar op de
    grafiek zou een vorm tonen die zo weer kan verdwijnen."""
    start = max(0, len(df) - lookback)
    end = len(df) - 1
    found: list[dict] = []
    for i in range(start, end):
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
class Pivot:
    index: int
    price: float
    kind: str  # "high" of "low"


def _find_pivots(window: pd.DataFrame) -> list[Pivot]:
    """Lokale keerpunten in een candle-venster: een candle die hoger/lager
    is dan SR_PIVOT_WINDOW candles aan beide kanten. Gedeeld tussen
    detect_sr_zones (clustert op prijs, index niet nodig) en
    detect_trendlines (past een lijn door index+prijs), zodat de
    pivot-definitie één keer bestaat."""
    n = len(window)
    pivots: list[Pivot] = []
    for i in range(SR_PIVOT_WINDOW, n - SR_PIVOT_WINDOW):
        high_i = window["high"].iloc[i]
        low_i = window["low"].iloc[i]
        left_highs = window["high"].iloc[i - SR_PIVOT_WINDOW:i]
        right_highs = window["high"].iloc[i + 1:i + SR_PIVOT_WINDOW + 1]
        if high_i > left_highs.max() and high_i > right_highs.max():
            pivots.append(Pivot(index=i, price=float(high_i), kind="high"))
        left_lows = window["low"].iloc[i - SR_PIVOT_WINDOW:i]
        right_lows = window["low"].iloc[i + 1:i + SR_PIVOT_WINDOW + 1]
        if low_i < left_lows.min() and low_i < right_lows.min():
            pivots.append(Pivot(index=i, price=float(low_i), kind="low"))
    return pivots


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
    pivots = [p.price for p in _find_pivots(window)]

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

# Hoe klein het verschil tussen EMA9 en EMA21 van BTC zelf moet zijn
# (genormaliseerd op zijn eigen ATR) om de markt als "zijwaarts, geen
# duidelijke richting" te beschouwen. Zelfde soort ATR-genormaliseerde
# marge als SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE hierboven, alleen dan voor
# "te dicht bij elkaar" in plaats van "te ver uit elkaar". Gebruikt door
# app/market_scanner.py om altcoin-signalering over te slaan zolang BTC
# zelf geen duidelijke trend heeft — zie de spec, sectie 3.
BTC_FLAT_EMA_GAP_ATR_MULTIPLE = 0.3


# Hoeveel candles terug gekeken wordt om te bepalen of de prijs al een
# terugveer heeft laten zien, voor de bounce-check hieronder. Kort genoeg
# om alleen de actuele test van de zone te vangen, niet een willekeurige
# oudere candle.
SR_ZONE_BOUNCE_LOOKBACK = 5

# Hoe ver de prijs al minstens van zijn recente laagste/hoogste punt af
# moet zijn bewogen, in de handelsrichting en in ATR gemeten, om als
# bevestigde terugveer te tellen in plaats van "nog aan het vallen/
# stijgen richting de zone". Zelfde schaal als
# BREAKOUT_RETEST_TOLERANCE_ATR_MULTIPLE: geen twijfelachtig kleine
# reactie, een echte.
SR_ZONE_BOUNCE_MIN_REACTION_ATR_MULTIPLE = 0.3


def check_sr_zone(
    direction: str, entry_price: float, atr: float, zones: list[SRZone], df: pd.DataFrame,
) -> tuple[str, bool, str]:
    """Is er een bruikbare zone aan de stop-kant van de prijs (onder de
    entry bij long, erboven bij short) binnen SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE
    x ATR, ÉN heeft de prijs al een bevestigde terugveer laten zien sinds
    zijn recente laagste/hoogste punt? Zonder die tweede eis bevestigde
    deze factor al zodra de prijs toevallig dichtbij een zone stond, ook
    middenin een val naar die zone toe — het verschil tussen "bij steun"
    en "steun bevestigd". Zelfde kant-bepaling als
    risk.compute_stop_take_from_levels gebruikt voor community-niveaus,
    hier toegepast op zelf-gedetecteerde zones. Geen aparte richting-
    afhankelijke detectie nodig: een zone is een zone, welke kant hem
    "steun" maakt hangt puur af van waar de entry-prijs zit."""
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

    recent = df.tail(SR_ZONE_BOUNCE_LOOKBACK)
    if direction == "long":
        reaction_atr = (entry_price - float(recent["low"].min())) / atr if atr else 0.0
    else:
        reaction_atr = (float(recent["high"].max()) - entry_price) / atr if atr else 0.0

    if reaction_atr < SR_ZONE_BOUNCE_MIN_REACTION_ATR_MULTIPLE:
        return (
            "Steun/weerstand", False,
            f"zone op {distance_atr:.1f}x ATR afstand, maar nog geen bevestigde terugveer",
        )
    return ("Steun/weerstand", True, f"zone op {distance_atr:.1f}x ATR afstand, terugveer bevestigd")


def check_premium_discount(
    direction: str, entry_price: float, swing_low: float, swing_high: float,
) -> tuple[str, bool, str]:
    """Ligt de entry in de goedkope (discount) of dure (premium) helft van
    de recente swing-range (swing_levels, dezelfde die ook de stop-
    plaatsing bepaalt)? Long is sterker onder het midden (equilibrium),
    short erboven — de klassieke SMC-knip op 50%, geen marge: een long
    net onder equilibrium is nog altijd relatief goedkoop, een long er
    net boven is dat per definitie niet meer. Precies op equilibrium
    telt zowel long als short als ok — met echte prijzen een randgeval
    dat in de praktijk niet voorkomt, bewust niet apart afgehandeld."""
    direction = direction.lower()
    if swing_high == swing_low:
        return ("Premium/discount", False, "range te vlak om te bepalen")
    equilibrium = (swing_low + swing_high) / 2
    if direction == "long":
        ok = entry_price <= equilibrium
        kant = "discount" if ok else "premium"
    else:
        ok = entry_price >= equilibrium
        kant = "premium" if ok else "discount"
    detail = f"entry in {kant}-zone (equilibrium {equilibrium:.4f})"
    return ("Premium/discount", ok, detail)


def check_daily_premium_discount(
    direction: str, entry_price: float, daily_swing_low: float, daily_swing_high: float,
) -> tuple[str, bool, str]:
    """Zelfde check als check_premium_discount, maar op de swing-range van
    de dagcandle in plaats van 4u — een daily premium/discount-zone is een
    sterker signaal, dezelfde reden waarom Daily-trend naast de 4u-
    trendfactor bestaat. Precies op equilibrium telt zowel long als short
    als ok — met echte prijzen een randgeval dat in de praktijk niet
    voorkomt, bewust niet apart afgehandeld."""
    direction = direction.lower()
    if daily_swing_high == daily_swing_low:
        return ("Premium/discount (dag)", False, "range te vlak om te bepalen")
    equilibrium = (daily_swing_low + daily_swing_high) / 2
    if direction == "long":
        ok = entry_price <= equilibrium
        kant = "discount" if ok else "premium"
    else:
        ok = entry_price >= equilibrium
        kant = "premium" if ok else "discount"
    detail = f"entry in {kant}-zone op daily (equilibrium {equilibrium:.4f})"
    return ("Premium/discount (dag)", ok, detail)


# Hoeveel van de laatste candles gecontroleerd worden op een sweep van een
# eerdere pivot. Kort genoeg om alleen een verse sweep te vangen, niet een
# willekeurige oude pen-doorbraak die allang geen rol meer speelt — zelfde
# soort venster als SR_ZONE_BOUNCE_LOOKBACK, kleiner omdat een sweep per
# definitie een kortstondige gebeurtenis is (één candle, niet een
# meerdaagse terugveer).
LIQUIDITY_SWEEP_RECENT_CANDLES = 3


def _find_liquidity_sweep(window: pd.DataFrame, direction: str) -> Optional[Pivot]:
    """Gedeelde kernlogica voor check_liquidity_sweep en
    check_daily_liquidity_sweep: zoekt in `window` een pivot van de
    stop-kant (low voor long, high voor short) die door een van de
    laatste LIQUIDITY_SWEEP_RECENT_CANDLES candles met zijn pen doorbroken
    is, waarna diezelfde candle terugsloot aan de oorspronkelijke kant.
    Geeft de eerst passende treffer terug (nieuwste candle het eerst
    geprobeerd; bij meerdere geraakte pivots op dezelfde candle telt de
    volgorde van _find_pivots, niet per se de meest recente pivot), of
    None."""
    pivots = _find_pivots(window)
    kind = "low" if direction == "long" else "high"
    # Met de huidige constantes (SR_PIVOT_WINDOW == LIQUIDITY_SWEEP_RECENT_CANDLES)
    # sluit _find_pivots zelf al pivots binnen dit venster uit (zijn eigen
    # rechter bevestigingsvenster), dus dit filter is vandaag redundant —
    # blijft staan als expliciete garantie, mocht een van beide constantes
    # ooit onafhankelijk veranderen.
    cutoff = len(window) - LIQUIDITY_SWEEP_RECENT_CANDLES
    candidates = [p for p in pivots if p.kind == kind and p.index < cutoff]
    if not candidates:
        return None

    recent = window.tail(LIQUIDITY_SWEEP_RECENT_CANDLES)
    for _, candle in recent.iloc[::-1].iterrows():
        for p in candidates:
            if direction == "long":
                swept = candle["low"] < p.price and candle["close"] > p.price
            else:
                swept = candle["high"] > p.price and candle["close"] < p.price
            if swept:
                return p
    return None


def check_liquidity_sweep(direction: str, df: pd.DataFrame) -> tuple[str, bool, str]:
    """Liquidity sweep op de hoofd-timeframe (4u): is er, in de laatste
    LIQUIDITY_SWEEP_RECENT_CANDLES candles, een stop-hunt geweest van een
    eerdere pivot-low (long) of pivot-high (short), gevolgd door een close
    terug aan de goede kant? Andere invalshoek dan check_sr_zone: die kijkt
    naar een bevestigde terugveer over meerdere candles, dit naar één
    scherpe pen-doorbraak-en-terugsluiting. Bewust een andere naam dan
    check_liquidity (24u handelsvolume) — compleet ander concept, zie die
    functie zijn docstring."""
    direction = direction.lower()
    window = df.tail(SR_ZONE_LOOKBACK).reset_index(drop=True)
    hit = _find_liquidity_sweep(window, direction)
    if hit is None:
        return ("Liquidity sweep", False, "geen recente stop-hunt gevonden")
    return ("Liquidity sweep", True, f"stop-hunt van {hit.price:.4f}, candle sloot terug aan de goede kant")


def check_daily_liquidity_sweep(direction: str, daily_df: pd.DataFrame) -> tuple[str, bool, str]:
    """Zelfde check als check_liquidity_sweep, maar op de dagcandle — een
    sweep van een daily swing high/low is een sterker signaal, klassieke
    SMC-liquiditeit zit vaak juist op dagniveau (de meest voor de hand
    liggende stop-plek voor de meeste marktdeelnemers)."""
    direction = direction.lower()
    window = daily_df.tail(SR_ZONE_LOOKBACK).reset_index(drop=True)
    hit = _find_liquidity_sweep(window, direction)
    if hit is None:
        return ("Liquidity sweep (dag)", False, "geen recente stop-hunt op daily gevonden")
    return ("Liquidity sweep (dag)", True, f"stop-hunt op daily van {hit.price:.4f}, candle sloot terug aan de goede kant")


def find_sniper_entry_price(direction: str, df: pd.DataFrame) -> Optional[tuple[float, str]]:
    """Dunne laag over _find_liquidity_sweep: geeft de rauwe sweep-prijs en
    een leesbare "waarom is dit een sniper-entry"-uitleg terug, in plaats
    van de korte factor-detail-string die check_liquidity_sweep bouwt voor
    de gepoolde 16-factoren-toets. Zelfde window, zelfde detectie —
    check_liquidity_sweep zelf blijft ongewijzigd; dit is een aparte,
    op-maat-gemaakte laag eroverheen, specifiek voor sniper-gebruik
    (signal_processor.py, market_scanner.py, level_check.py). Alleen de
    4u-timeframe (df hier is altijd de 4u-candles), geen daily-variant in
    v1 — check_daily_liquidity_sweep blijft een aparte, gepoolde factor."""
    direction = direction.lower()
    window = df.tail(SR_ZONE_LOOKBACK).reset_index(drop=True)
    hit = _find_liquidity_sweep(window, direction)
    if hit is None:
        return None
    if direction == "long":
        reason = (
            f"Stop-hunt: prijs werd even onder {hit.price:.4f} geduwd en sloot er "
            "meteen weer boven — de klassieke bear trap, hier zaten net de stops van anderen."
        )
    else:
        reason = (
            f"Stop-hunt: prijs werd even boven {hit.price:.4f} geduwd en sloot er "
            "meteen weer onder — de klassieke bull trap, hier zaten net de stops van anderen."
        )
    return (hit.price, reason)


# Hoe ver de prijs nog voorbij een doorbroken zone mag zitten om "nu aan
# het terugtesten" te tellen (in ATR): zelfde soort ATR-genormaliseerde
# marge als BTC_FLAT_EMA_GAP_ATR_MULTIPLE.
BREAKOUT_RETEST_TOLERANCE_ATR_MULTIPLE = 0.3


def find_breakout_retest(
    df: pd.DataFrame, zones: list[SRZone], atr: float, direction: str,
) -> list[tuple[SRZone, int]]:
    """Voor elke zone: is er, op closing-prijs, een duidelijke uitbraak in
    de richting van de trade geweest, staat die uitbraak nog overeind (geen
    candle sindsdien weer terug over de andere kant van de zone gesloten),
    en zit de prijs nu weer dichtbij die zone? Bij long: de zone was
    weerstand, is doorbroken naar boven, en dient nu als steun voor de
    terugval. Bij short: precies omgekeerd, de zone was steun, is naar
    beneden doorbroken en dient nu als weerstand. Alleen de meest recente
    uitbraak per zone telt. Geeft (zone, candles_since_breakout) terug voor
    elke zone die nu een geldige terugtest is — het klassieke "uitbraak
    dan terugtest"-patroon, de sterkste van de zelf-gedetecteerde
    entry-opzetten."""
    closes = df["close"].reset_index(drop=True)
    current_price = closes.iloc[-1]
    hits = []
    for zone in zones:
        if direction == "long":
            broke = (closes.shift(1) <= zone.price_high) & (closes > zone.price_high)
            invalidate_level = zone.price_low
        else:
            broke = (closes.shift(1) >= zone.price_low) & (closes < zone.price_low)
            invalidate_level = zone.price_high

        breakout_indices = closes.index[broke]
        if len(breakout_indices) == 0:
            continue
        breakout_idx = breakout_indices[-1]
        since_breakout = closes.iloc[breakout_idx + 1:]
        if direction == "long":
            if (since_breakout < invalidate_level).any():
                continue
            near_zone = (
                zone.price_low <= current_price
                <= zone.price_high + BREAKOUT_RETEST_TOLERANCE_ATR_MULTIPLE * atr
            )
        else:
            if (since_breakout > invalidate_level).any():
                continue
            near_zone = (
                zone.price_low - BREAKOUT_RETEST_TOLERANCE_ATR_MULTIPLE * atr
                <= current_price <= zone.price_high
            )

        candles_since = len(closes) - 1 - breakout_idx
        if near_zone and candles_since > 0:
            hits.append((zone, candles_since))
    return hits


# Minimaal aantal pivots dat op de lijn moet liggen voor hij als echte
# trendlijn telt, niet toeval. Strenger dan SR_ZONE_MIN_TOUCHES (2): een
# schuine lijn door twee punten legt geen enkele relatie vast, een derde
# bevestigende pivot wel.
TRENDLINE_MIN_TOUCHES = 3

# Hoe dicht een pivot bij de kandidaat-lijn moet liggen (als fractie van
# de prijs) om als treffer op die lijn te tellen. Zelfde soort marge als
# SR_ZONE_CLUSTER_TOLERANCE_PCT, iets ruimer: een diagonale lijn door
# candle-pivots past nooit zo exact als een horizontaal cluster.
TRENDLINE_FIT_TOLERANCE_PCT = 0.01

# Minimale helling (in ATR per candle) wil een lijn als "diagonaal" tellen
# in plaats van als verkapte horizontale zone. Zonder dit zou een bijna
# vlakke lijn hetzelfde patroon als detect_sr_zones vinden, dubbel werk
# met een andere naam.
TRENDLINE_MIN_SLOPE_ATR_MULTIPLE = 0.05


@dataclass
class Trendline:
    kind: str  # "resistance" (verbindt pivot-highs) of "support" (pivot-lows)
    slope: float  # prijsverandering per candle-index binnen het venster
    intercept: float  # lijnwaarde bij index 0 van het venster
    touches: int
    last_index: int  # index van de meest recente (laatste) pivot op de lijn
    first_index: int  # index van de vroegste pivot op de lijn, voor de grafiek (begin van de getekende lijn)

    def value_at(self, index: int) -> float:
        return self.slope * index + self.intercept


def detect_trendlines(df: pd.DataFrame, atr: float) -> list[Trendline]:
    """Vindt maximaal twee diagonale trendlijnen (één weerstand door
    pivot-highs, één steun door pivot-lows) in de laatste SR_ZONE_LOOKBACK
    candles. Voor elk soort: alle paren pivots van dat soort vormen een
    kandidaat-lijn, tel per kandidaat hoeveel ANDERE pivots van hetzelfde
    soort binnen TRENDLINE_FIT_TOLERANCE_PCT van die lijn liggen, houd de
    lijn met de meeste treffers. Een lijn met te weinig treffers of een te
    vlakke helling wordt niet teruggegeven — geen kandidaat is dan ook
    geen fout, gewoon geen bruikbare lijn deze cyclus."""
    window = df.tail(SR_ZONE_LOOKBACK).reset_index(drop=True)
    pivots = _find_pivots(window)
    lines: list[Trendline] = []

    for kind, pivot_kind in [("resistance", "high"), ("support", "low")]:
        candidates = [p for p in pivots if p.kind == pivot_kind]
        if len(candidates) < TRENDLINE_MIN_TOUCHES:
            continue

        best: Optional[Trendline] = None
        for i in range(len(candidates)):
            for j in range(i + 1, len(candidates)):
                p1, p2 = candidates[i], candidates[j]
                if p1.index == p2.index:
                    continue
                slope = (p2.price - p1.price) / (p2.index - p1.index)
                intercept = p1.price - slope * p1.index

                inliers = [
                    p for p in candidates
                    if abs(p.price - (slope * p.index + intercept)) <= p.price * TRENDLINE_FIT_TOLERANCE_PCT
                ]
                if len(inliers) < TRENDLINE_MIN_TOUCHES:
                    continue
                if atr and abs(slope) < TRENDLINE_MIN_SLOPE_ATR_MULTIPLE * atr:
                    continue
                if best is None or len(inliers) > best.touches:
                    best = Trendline(
                        kind=kind, slope=slope, intercept=intercept,
                        touches=len(inliers),
                        last_index=max(p.index for p in inliers),
                        first_index=min(p.index for p in inliers),
                    )
        if best is not None:
            lines.append(best)

    return lines


def find_trendline_breakout_retest(
    df: pd.DataFrame, trendlines: list[Trendline], atr: float, direction: str,
) -> list[tuple[Trendline, int]]:
    """Zelfde patroon als find_breakout_retest: crossing-detectie op de
    laatste candle die van de verkeerde naar de goede kant van het niveau
    sloot, dan checken of dat sindsdien standhield — nu tegen een
    bewegende lijnwaarde in plaats van een vaste zone-grens. Werkt op
    hetzelfde geschoven venster (df.tail(SR_ZONE_LOOKBACK)) als
    detect_trendlines, zodat line.value_at(index) in beide functies
    dezelfde candle aanwijst. Alleen een uitbraak ná line.last_index
    telt: de lijn kan niet gebroken zijn vóór zijn eigen laatste
    bevestigende pivot. Geeft (lijn, candles_since_breakout) terug voor
    elke lijn die nu een geldige terugtest is."""
    window = df.tail(SR_ZONE_LOOKBACK).reset_index(drop=True)
    closes = window["close"]
    direction = direction.lower()
    hits: list[tuple[Trendline, int]] = []

    for line in trendlines:
        if (direction == "long") != (line.kind == "resistance"):
            continue

        line_values = pd.Series([line.value_at(i) for i in range(len(closes))])
        if direction == "long":
            broke = (closes.shift(1) <= line_values.shift(1)) & (closes > line_values)
        else:
            broke = (closes.shift(1) >= line_values.shift(1)) & (closes < line_values)

        breakout_indices = [idx for idx in closes.index[broke] if idx > line.last_index]
        if not breakout_indices:
            continue
        breakout_idx = breakout_indices[-1]
        since_breakout = closes.iloc[breakout_idx + 1:]
        since_line = line_values.iloc[breakout_idx + 1:]
        if direction == "long":
            if (since_breakout < since_line).any():
                continue
        else:
            if (since_breakout > since_line).any():
                continue

        last_index = len(closes) - 1
        last_close = closes.iloc[last_index]
        current_line_value = line.value_at(last_index)
        tolerance = BREAKOUT_RETEST_TOLERANCE_ATR_MULTIPLE * atr
        candles_since = last_index - breakout_idx
        if abs(last_close - current_line_value) <= tolerance and candles_since > 0:
            hits.append((line, candles_since))

    return hits


# Hoeveel keer de ATR de prijs maximaal van zijn EMA21 af mag staan
# (in de richting van de trade) voor de Uitgerektheid-factor in
# basic_factors hierboven. Boven deze grens is de beweging al voor een
# groot deel gelopen, chasen van een al uitgerekte coin is precies het
# gedrag dat deze factor moet tegenhouden.
EXTENSION_MAX_ATR_MULTIPLE = 3.0

# Basisversie: 3 van de 4 "klassieke" factoren (trend, momentum, RSI,
# volume) is genoeg, zoals eerder al bewust verzacht — alle 4 verplicht
# bleek te streng, één factor die nét mist (bijvoorbeeld volume op 0.97x
# in plaats van 1.0x) blokkeerde dan een verder overtuigend signaal
# volledig. Uitgerektheid (de vijfde factor) telt hier NIET in mee: die is
# een harde eis op zichzelf (zie confirms_direction), geen zachte 3-van-4
# zou een coin die al ver van zijn EMA21 af zit alsnog laten confirmen
# zolang de andere vier maar kloppen — precies het chasen dat deze factor
# moet tegenhouden.
BASIC_CONFIRM_MIN_PASSED = 3

# In de uitgebreide versie telt, op Uitgerektheid, BTC-trend en Daily-trend
# na (elk hun eigen harde eis, zie confirms_direction's docstring), geen
# andere factor apart als harde eis: met 21 factoren in totaal (5 basis +
# 16 uitgebreid) zou dat anders al snel één marginale miss (bijvoorbeeld
# volume op 0.89x in plaats van 1.0x) een verder overtuigend signaal
# volledig blokkeren, terwijl bijna alle andere factoren wel klopten.
# Minstens 60% van de OVERIGE factoren is hier de grens: is dat gehaald,
# dan is het een melding waard, en blijft het aan de gebruiker zelf om op
# basis van de zichtbare ✓/✗ per factor te beslissen of hij hem neemt. De
# factoren die hun eigen candle-data ophalen (BTC-trend, Daily-trend, RSI
# daily, Premium/discount (dag), Liquidity sweep (dag), 1u bevestiging, RSI
# 1u, Divergentie, Candlepatroon, Liquiditeit) tellen "fail-closed" mee:
# lukt het ophalen niet, dan telt de factor als niet gehaald in plaats van
# dat de melding daarop crasht of de factor overslaat, dus een tijdelijke
# ophaalfout kan in het slechtste geval meerdere factoren kosten (voor de
# daily-fetch in signal_processor.compute_advanced_extra_factors: RSI
# daily, Premium/discount (dag) en Liquidity sweep (dag) tegelijk —
# Daily-trend zelf heeft een eigen, aparte fetch in
# process_day_trading_signal).
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
    """De vijf basisfactoren (trend, momentum, RSI, volume, uitgerektheid)
    als losse (naam, ok, detail) tuples, onafhankelijk van enige
    drempel-beslissing. Gebruikt door confirms_direction voor de
    day-trading toets, en door de swing-toets in signal_processor.py om
    dezelfde factoren te tonen op een andere tijdshorizon zonder een
    gecombineerd vertrouwensoordeel."""
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

    # Hoe ver de prijs al van zijn EMA21 af staat, in ATR gemeten: een coin
    # die al ver boven (long) of onder (short) zijn EMA21 zit, is een
    # beweging die al voor een groot deel gelopen is. RSI alleen vangt dit
    # niet altijd op (een gestage stijging over veel candles kan makkelijk
    # onder de 75 blijven terwijl de coin toch al 10%+ hoger staat), dus
    # deze factor meet de uitgerektheid direct, los van RSI.
    extension_atr = (ind.price - ind.ema21) / ind.atr if direction == "long" else (ind.ema21 - ind.price) / ind.atr
    extension_ok = extension_atr <= EXTENSION_MAX_ATR_MULTIPLE
    extension_detail = f"{extension_atr:.1f}x ATR van EMA21" + (
        "" if extension_ok else ", beweging al te ver gelopen"
    )

    return [
        ("Trend", trend_ok, trend_detail),
        ("Momentum", momentum_ok, momentum_detail),
        ("RSI", rsi_ok, rsi_detail),
        ("Volume", volume_ok, volume_detail),
        ("Uitgerektheid", extension_ok, extension_detail),
    ]


def confirms_direction(
    ind: Indicators, direction: str, extra_factors: list[tuple[str, bool, str]] | None = None,
    include_advanced: bool = False, daily_trend_factor: tuple[str, bool, str] | None = None,
    daily_trend_hard_gate: bool = True,
) -> tuple[bool, str]:
    """Bepaalt of de technische data de richting uit het Discord bericht steunt.

    Basisversie (`include_advanced=False`, de standaard): vijf factoren,
    elk met een duidelijke ✓ of ✗. De eerste vier tellen zacht mee,
    minstens 3 van de 4 vereist (zie BASIC_CONFIRM_MIN_PASSED):
    - trend: EMA9 t.o.v. EMA21 moet de richting volgen
    - momentum: MACD lijn t.o.v. signaallijn moet de richting volgen
    - RSI mag niet al extreem tegen de richting in zitten, in geen van
      beide richtingen (overbought én oversold tellen tegen zowel long als
      short, zie RSI_OVERSOLD/RSI_OVERBOUGHT hierboven)
    - volume moet minstens gemiddeld zijn, anders is de beweging niet
      overtuigend

    De vijfde factor, uitgerektheid (de prijs mag niet al te ver, in ATR,
    van zijn EMA21 af staan — zie EXTENSION_MAX_ATR_MULTIPLE), telt NIET
    mee in die 3-van-4: die moet ALTIJD kloppen, los van hoeveel van de
    andere vier passen. Zonder die harde eis zou een coin die al fors
    gelopen is (bijvoorbeeld 10%+ in een paar uur) alsnog bevestigen zodra
    de andere vier toevallig kloppen — precies het chasen dat deze factor
    moet voorkomen. Deze harde eis geldt in BEIDE versies hieronder, niet
    alleen de basisversie: zonder dat zou de bescherming stilzwijgend
    verdwijnen zodra ENABLE_ADVANCED_FACTORS aanstaat.

    Uitgebreide versie (`include_advanced=True`, aan via
    config.ENABLE_ADVANCED_FACTORS): daar komen drie vaste factoren bij,
    trendsterkte (ADX), volatiliteit (ATR t.o.v. zijn eigen 20-candle
    gemiddelde) en volume-percentiel, plus wat er in `extra_factors`
    meegegeven wordt (BTC-trend, RSI daily, Premium/discount,
    Premium/discount (dag), Liquidity sweep, Liquidity sweep (dag), 1u
    bevestiging, RSI 1u, Divergentie, Candlepatroon, Liquiditeit,
    Steun/weerstand: elk een (naam, ok, detail) tuple, berekend buiten
    deze functie omdat ze andere data nodig hebben — zie
    signal_processor.compute_advanced_extra_factors). Daily-trend zelf komt
    niet via `extra_factors` binnen maar via het aparte `daily_trend_factor`-
    argument hieronder, dat geldt in beide versies.
    Bevestigd is hier een kwestie van hoeveel van de OVERIGE factoren
    (dus zonder Uitgerektheid, BTC-trend en Daily-trend, die alle drie hun
    eigen harde eis hebben, zie hieronder) in totaal kloppen (zie
    CONFIRM_THRESHOLD), niet van elke losse factor apart hard vereisen:
    bij 18 overige factoren samen (4 basis + 3 vast + 11 extra) blokkeert
    anders één marginale miss een verder overtuigend signaal.

    BTC-trend is, als hij aanwezig is, een tweede harde eis naast
    Uitgerektheid: staat BTC zelf duidelijk tegen de trade in, dan
    bevestigt een altcoin-signaal nooit, ongeacht hoeveel van de andere
    factoren toevallig kloppen — anders kon één BTC-short en één
    ETH-long tegelijk allebei "bevestigd" heten terwijl de markt duidelijk
    één kant op ging. Alleen van toepassing als BTC zelf een duidelijke
    trend heeft; signal_processor.compute_advanced_extra_factors laat de
    factor weg zodra `btc_is_flat` true is, zodat een altcoin die op
    eigen kracht uitbreekt tijdens een zijwaartse BTC niet onterecht
    geblokkeerd wordt.

    Daily-trend is, in BEIDE versies (basis en uitgebreid), een derde
    harde eis naast Uitgerektheid en (in de uitgebreide versie) BTC-trend:
    wijst de dagtrend van de coin zelf duidelijk tegen de trade in, dan
    bevestigt het signaal nooit, ongeacht hoeveel van de andere factoren
    toevallig kloppen — anders zou een dagtrading-signaal tegen de eigen
    grotere trend in alsnog "bevestigd" kunnen heten. Alleen van
    toepassing als de coin zelf een duidelijke dagtrend heeft;
    process_day_trading_signal laat de factor weg zodra `btc_is_flat` (die
    ondanks zijn naam coin-onafhankelijk is) true is voor de dagcandle,
    zodat een coin die vlak vóór een uitbraak consolideert niet onterecht
    geblokkeerd wordt.

    Ontbreekt een extra check (bijvoorbeeld BTC-trend bij een BTC-signaal
    zelf, of bij een vlakke BTC of vlakke dagtrend), dan wordt hij
    simpelweg niet meegegeven en telt hij niet mee, ook niet als harde
    eis.

    daily_trend_hard_gate=False (gebruikt door market_scanner voor een
    chart-patroon, zie signal_processor.compute_full_confirmation) zet
    Daily-trend om naar puur informatief: nog steeds zichtbaar als ✓/✗-regel,
    maar telt niet meer mee in hard_gates_ok. Een chart-patroon (top/bottom,
    head & shoulders, wedge, divergence) is per definitie een OMKEER-
    signaal — de premisse is juist dat de bestaande trend gaat draaien. Een
    dagtrend die nog de oude kant op wijst is dan geen zwakte van het
    signaal, dat is precies de situatie waarin een omkeerpatroon zijn werk
    doet. Eisen dat de dagtrend al is omgedraaid voor het patroon telt, zou
    het patroon pas bevestigen nadat de omkeer grotendeels al gebeurd is.
    Dagtrading (trend-volgend) en uitbraak/trendlijn-terugtest (kan beide
    kanten op t.o.v. de grotere trend) blijven de harde eis wel houden.
    """
    direction = direction.lower()
    if direction not in ("long", "short"):
        return False, f"onbekende richting: {direction}"
    factors = basic_factors(direction, ind)

    if not include_advanced:
        breakdown = " | ".join(f"{'✓' if ok else '✗'} {name}: {detail}" for name, ok, detail in factors)
        # Uitgerektheid is een harde eis, geen onderdeel van de 3-van-4-
        # telling op de andere vier (zie de docstring hierboven): zonder
        # deze scheiding zou een coin die al te ver gelopen is alsnog
        # bevestigen zolang trend/momentum/RSI/volume toevallig kloppen.
        extension_ok = next(ok for name, ok, _ in factors if name == "Uitgerektheid")
        core_passed = sum(1 for name, ok, _ in factors if ok and name != "Uitgerektheid")
        # 4 basic factors excluding Uitgerektheid
        pass_pct = (core_passed / 4) * 100
        # Daily-trend zit niet in basic_factors() (die kost geen extra
        # candle-fetch), dus wordt hier los toegevoegd aan de breakdown en
        # als harde eis meegewogen, net als Uitgerektheid hierboven.
        daily_trend_ok = daily_trend_factor[1] if daily_trend_factor is not None else True
        if daily_trend_factor is not None:
            breakdown += f" | {'✓' if daily_trend_factor[1] else '✗'} {daily_trend_factor[0]}: {daily_trend_factor[2]}"
        hard_gates_ok = extension_ok and (daily_trend_ok or not daily_trend_hard_gate)
        confirmed = hard_gates_ok and core_passed >= BASIC_CONFIRM_MIN_PASSED
        return confirmed, breakdown, pass_pct, hard_gates_ok

    # Zelfde harde eis als in de basisversie hierboven: zonder deze
    # extractie viel Uitgerektheid hier terug in de gewone percentage-
    # telling van alle 21 factoren samen, en kon een coin die al ver
    # voorbij EXTENSION_MAX_ATR_MULTIPLE zat alsnog bevestigen zolang
    # genoeg van de andere factoren toevallig klopten — precies het
    # chasen dat deze factor in de basisversie al voorkomt. De factor
    # blijft wel gewoon zichtbaar in de breakdown-tekst.
    extension_ok = next(ok for name, ok, _ in factors if name == "Uitgerektheid")

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
    if daily_trend_factor is not None:
        factors.append(daily_trend_factor)

    breakdown = " | ".join(f"{'✓' if ok else '✗'} {name}: {detail}" for name, ok, detail in factors)

    # BTC-trend is, net als Uitgerektheid, een harde eis als hij aanwezig
    # is (zie de docstring hierboven) — anders was BTC-trend maar 1 stem
    # tussen 15+ andere factoren en kon een altcoin-signaal alsnog
    # "bevestigd" heten terwijl BTC zelf duidelijk de andere kant op ging.
    # Afwezig (BTC-signaal zelf, of BTC vlak) telt hij simpelweg niet mee,
    # ook niet als harde eis — geen enkele False hier dus.
    btc_trend_ok = next((ok for name, ok, _ in factors if name == "BTC-trend"), True)
    # Daily-trend is, net als BTC-trend, een harde eis als hij aanwezig is
    # (zie de docstring hierboven) — de eigen dagtrend van de coin.
    daily_trend_ok = next((ok for name, ok, _ in factors if name == "Daily-trend"), True)

    # Uitgerektheid, BTC-trend en Daily-trend tellen niet mee in deze
    # telling (zie hierboven), anders dan alle andere factoren hier.
    other_factors = [f for f in factors if f[0] not in ("Uitgerektheid", "BTC-trend", "Daily-trend")]
    passed = sum(1 for _, ok, _ in other_factors if ok)
    pass_pct = (passed / len(other_factors)) * 100 if other_factors else 100.0
    hard_gates_ok = extension_ok and btc_trend_ok and (daily_trend_ok or not daily_trend_hard_gate)
    confirmed = hard_gates_ok and pass_pct >= CONFIRM_THRESHOLD * 100
    return confirmed, breakdown, pass_pct, hard_gates_ok
