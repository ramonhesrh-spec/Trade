"""Uitkomst van één signaal op de 15m-basis: eerst stop of eerst take profit,
of verlopen. Zelfde stop-eerst-keuze als level_check._level_hit_in_candles
als beide niveaus in dezelfde candle geraakt worden."""
from dataclasses import dataclass
from typing import Optional

import pandas as pd


@dataclass(frozen=True)
class Outcome:
    result: str  # "take_profit" | "stop_loss" | "expired"
    exit_at: pd.Timestamp
    exit_price: float
    r_gross: float
    r_net: float


def resolve(
    direction: str, entry: float, stop: float, take: float, candles: pd.DataFrame,
    signal_at: pd.Timestamp, max_age: pd.Timedelta, fee_pct: float = 0.1, slippage_pct: float = 0.05,
) -> Optional[Outcome]:
    """`candles` is het 15m-basisframe. Alleen candles die op of na
    `signal_at` beginnen en vóór `signal_at + max_age` tellen mee. Kosten
    (fee plus slippage, per kant) gaan er in R vanaf. Een verlopen signaal
    wordt tegen de slotprijs gemeten: wie het signaal nam zit dan nog in de
    trade. Geeft None als er geen candle in het venster ligt of de
    stopafstand nul is."""
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    window = candles[(candles["timestamp"] >= signal_at) & (candles["timestamp"] < signal_at + max_age)]
    if window.empty:
        return None

    cost_r = 2 * (fee_pct + slippage_pct) / 100 * entry / risk
    sign = 1 if direction == "long" else -1
    timestamps = list(window["timestamp"])
    highs = window["high"].to_numpy()
    lows = window["low"].to_numpy()

    for i in range(len(window)):
        stop_hit = lows[i] <= stop if sign == 1 else highs[i] >= stop
        take_hit = highs[i] >= take if sign == 1 else lows[i] <= take
        if stop_hit:
            return Outcome("stop_loss", timestamps[i], stop, -1.0, -1.0 - cost_r)
        if take_hit:
            gross = abs(take - entry) / risk
            return Outcome("take_profit", timestamps[i], take, gross, gross - cost_r)

    exit_price = float(window["close"].iloc[-1])
    gross = sign * (exit_price - entry) / risk
    return Outcome("expired", timestamps[-1], exit_price, gross, gross - cost_r)
