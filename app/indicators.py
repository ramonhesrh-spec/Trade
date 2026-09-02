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

    Regels, eenvoudig en uitlegbaar:
    - trend: EMA9 t.o.v. EMA21 moet de richting volgen
    - momentum: MACD lijn t.o.v. signaallijn moet de richting volgen
    - RSI mag niet al extreem tegen de richting in zitten (overbought bij
      long, oversold bij short)
    - volume moet minstens gemiddeld zijn, anders is de beweging niet
      overtuigend
    """
    direction = direction.lower()
    reasons_against = []

    trend_up = ind.ema9 > ind.ema21
    momentum_up = ind.macd > ind.macd_signal

    if direction == "long":
        if not trend_up:
            reasons_against.append("EMA9 staat onder EMA21, geen opwaartse trend")
        if not momentum_up:
            reasons_against.append("MACD staat onder de signaallijn, geen opwaarts momentum")
        if ind.rsi >= 75:
            reasons_against.append(f"RSI staat op {ind.rsi:.0f}, overbought")
    elif direction == "short":
        if trend_up:
            reasons_against.append("EMA9 staat boven EMA21, geen neerwaartse trend")
        if momentum_up:
            reasons_against.append("MACD staat boven de signaallijn, geen neerwaarts momentum")
        if ind.rsi <= 25:
            reasons_against.append(f"RSI staat op {ind.rsi:.0f}, oversold")
    else:
        return False, f"onbekende richting: {direction}"

    if ind.volume_ratio < 1.0:
        reasons_against.append(
            f"volume ligt op {ind.volume_ratio:.2f}x het gemiddelde, onder gemiddeld"
        )

    if reasons_against:
        return False, "; ".join(reasons_against)
    return True, "trend, momentum en volume ondersteunen de richting"
