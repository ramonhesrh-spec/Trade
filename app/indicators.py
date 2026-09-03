"""Technische indicatoren op de 4 uur candle, vaste standaard timeframe."""
from dataclasses import dataclass

import pandas as pd
import ta

# Vanaf welke ADX-waarde een trend sterk genoeg is om op te varen. Onder
# deze grens is de markt zijwaarts, en zijn EMA-kruisingen en MACD-signalen
# veel minder betrouwbaar (whipsaws).
ADX_MIN = 20.0

# Minimaal handelsvolume in de laatste 24 uur (in quote-valuta, meestal
# USDT) voor een hoog vertrouwen signaal. Een technisch perfecte setup op
# een illiquide coin is in de praktijk niet fatsoenlijk uit te voeren
# zonder forse slippage.
MIN_QUOTE_VOLUME_24H = 2_000_000.0


@dataclass
class Indicators:
    price: float
    rsi: float
    macd: float
    macd_signal: float
    volume_ratio: float
    ema9: float
    ema21: float
    atr: float
    atr_avg20: float
    adx: float


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

    adx = ta.trend.ADXIndicator(high, low, close, window=14).adx()

    volume_avg20 = volume.rolling(window=20).mean()
    volume_ratio = volume / volume_avg20

    last = -1
    return Indicators(
        price=float(close.iloc[last]),
        rsi=float(rsi.iloc[last]),
        macd=float(macd_line.iloc[last]),
        macd_signal=float(macd_signal_line.iloc[last]),
        volume_ratio=float(volume_ratio.iloc[last]),
        ema9=float(ema9.iloc[last]),
        ema21=float(ema21.iloc[last]),
        atr=float(atr_series.iloc[last]),
        atr_avg20=float(atr_avg20.iloc[last]),
        adx=float(adx.iloc[last]),
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


# Deze factoren meten allemaal in de kern hetzelfde ("is er een trend"),
# dus tellen ze niet als vier onafhankelijke stemmen. Eén afwijking in deze
# groep is toegestaan (3 van 4; bij een BTC-signaal zelf blijven er maar 3
# over, dan is dat 2 van 3), de rest van de factoren blijft hard vereist.
DIRECTION_GROUP = {"Trend", "Momentum", "1u bevestiging", "BTC-trend"}


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
    data nodig hebben). Trend, Momentum, 1u bevestiging en BTC-trend meten
    allemaal in de kern "is er een trend" en zijn dus geen vier
    onafhankelijke stemmen: in die groep mag één factor afwijken (zie
    DIRECTION_GROUP), de rest blijft allemaal hard vereist.

    Ontbreekt een extra check (bijvoorbeeld BTC-trend bij een BTC-signaal
    zelf), dan wordt hij simpelweg niet meegegeven en telt hij niet mee.
    """
    direction = direction.lower()
    trend_up = ind.ema9 > ind.ema21
    momentum_up = ind.macd > ind.macd_signal

    if direction == "long":
        trend_ok = trend_up
        trend_detail = "EMA9 boven EMA21" if trend_up else "EMA9 onder EMA21, geen opwaartse trend"
        momentum_ok = momentum_up
        momentum_detail = ("MACD boven signaallijn" if momentum_up
                            else "MACD onder signaallijn, geen opwaarts momentum")
        rsi_ok = ind.rsi < 75
        rsi_detail = f"RSI {ind.rsi:.0f}" if rsi_ok else f"RSI {ind.rsi:.0f}, overbought"
    elif direction == "short":
        trend_ok = not trend_up
        trend_detail = "EMA9 onder EMA21" if trend_ok else "EMA9 boven EMA21, geen neerwaartse trend"
        momentum_ok = not momentum_up
        momentum_detail = ("MACD onder signaallijn" if momentum_ok
                            else "MACD boven signaallijn, geen neerwaarts momentum")
        rsi_ok = ind.rsi > 25
        rsi_detail = f"RSI {ind.rsi:.0f}" if rsi_ok else f"RSI {ind.rsi:.0f}, oversold"
    else:
        return False, f"onbekende richting: {direction}"

    volume_ok = ind.volume_ratio >= 1.0
    volume_detail = f"volume {ind.volume_ratio:.2f}x gemiddeld" + ("" if volume_ok else ", onder gemiddeld")

    factors = [
        ("Trend", trend_ok, trend_detail),
        ("Momentum", momentum_ok, momentum_detail),
        ("RSI", rsi_ok, rsi_detail),
        ("Volume", volume_ok, volume_detail),
    ]

    if not include_advanced:
        breakdown = " | ".join(f"{'✓' if ok else '✗'} {name}: {detail}" for name, ok, detail in factors)
        confirmed = all(ok for _, ok, _ in factors)
        return confirmed, breakdown

    adx_ok = ind.adx >= ADX_MIN
    adx_detail = f"ADX {ind.adx:.0f}" + ("" if adx_ok else ", trend te zwak/zijwaarts")

    volatility_ok = ind.atr >= ind.atr_avg20
    volatility_detail = f"ATR {ind.atr:.4f}" + (
        " (stijgend)" if volatility_ok else f" onder het 20-candle gemiddelde ({ind.atr_avg20:.4f}), markt trekt samen"
    )
    factors += [
        ("Trendsterkte", adx_ok, adx_detail),
        ("Volatiliteit", volatility_ok, volatility_detail),
    ]
    if extra_factors:
        factors.extend(extra_factors)

    breakdown = " | ".join(f"{'✓' if ok else '✗'} {name}: {detail}" for name, ok, detail in factors)

    group = [(name, ok) for name, ok, _ in factors if name in DIRECTION_GROUP]
    rest = [ok for name, ok, _ in factors if name not in DIRECTION_GROUP]
    group_fails = sum(1 for _, ok in group if not ok)
    group_ok = group_fails <= 1 if group else True

    confirmed = group_ok and all(rest)
    return confirmed, breakdown
