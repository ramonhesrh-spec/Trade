"""Technische indicatoren op de 4 uur candle, vaste standaard timeframe."""
from dataclasses import dataclass

import pandas as pd
import ta


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


def compute_indicators(df: pd.DataFrame) -> Indicators:
    """Berekent RSI(14), MACD standaard, volume t.o.v. gemiddelde over 20
    candles, EMA9, EMA21 en ATR, op basis van een OHLCV DataFrame."""
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

    atr = ta.volatility.AverageTrueRange(high, low, close, window=14).average_true_range()

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
        atr=float(atr.iloc[last]),
    )


def ema_series(df: pd.DataFrame) -> tuple[list[float], list[float]]:
    """Volledige EMA9 en EMA21 reeksen, voor de candlestick grafiek."""
    close = df["close"]
    ema9 = ta.trend.EMAIndicator(close, window=9).ema_indicator()
    ema21 = ta.trend.EMAIndicator(close, window=21).ema_indicator()
    return ema9.tolist(), ema21.tolist()


def confirms_direction(ind: Indicators, direction: str) -> tuple[bool, str]:
    """Bepaalt of de technische data de richting uit het Discord bericht steunt.

    Vier factoren, elk met een duidelijke ✓ of ✗, zodat "hoog vertrouwen"
    geen zwarte doos is maar altijd naast de vier losse redenen staat:
    - trend: EMA9 t.o.v. EMA21 moet de richting volgen
    - momentum: MACD lijn t.o.v. signaallijn moet de richting volgen
    - RSI mag niet al extreem tegen de richting in zitten (overbought bij
      long, oversold bij short)
    - volume moet minstens gemiddeld zijn, anders is de beweging niet
      overtuigend

    "Hoog vertrouwen" betekent: alle vier factoren staan op ✓. Al is er
    maar één ✗, dan is het "laag vertrouwen", ook al zijn de andere drie
    wel gunstig.
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
    breakdown = " | ".join(f"{'✓' if ok else '✗'} {name}: {detail}" for name, ok, detail in factors)
    confirmed = all(ok for _, ok, _ in factors)
    return confirmed, breakdown
