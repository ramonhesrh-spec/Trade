"""Afspeel-engine voor dagtrading-signalen: stapt per tijdstip door de
geschiedenis en roept dezelfde beslislogica aan als de live scan
(signal_processor.full_confirmation_sync en setup_eval). Niet nagebootst:
de pre-checks van market_scanner.scan_market (cooldown, whiplash-rem,
maximum meldingen per cyclus). Elk rapport zegt dat."""
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from app import indicators, setup_eval
from app.replay.outcome import Outcome, resolve
from app.replay.view import ReplayData
from app.signal_processor import full_confirmation_sync

# Genoeg candles voor EMA21, MACD(26) en ADX(14) om betrouwbaar te zijn.
MIN_CANDLES = 60
# Zelfde venster en tolerantie als repo.recent_sr_zone_failure.
ZONE_FAILURE_WINDOW = pd.Timedelta(days=3)
ZONE_FAILURE_ATR_TOLERANCE = 0.5


@dataclass
class ReplaySignal:
    coin: str
    direction: str
    at: pd.Timestamp
    entry: float
    stop: float
    take: float
    confirmed: bool
    reason: str
    outcome: Optional[Outcome]
    nearest_sr_zone_price: Optional[float] = None


def _zone_recently_failed(failures, direction, zone_price, atr, now) -> bool:
    if not atr:
        return False
    return any(
        d == direction and now - ZONE_FAILURE_WINDOW <= failed_at <= now
        and abs(price - zone_price) <= ZONE_FAILURE_ATR_TOLERANCE * atr
        for d, price, failed_at in failures
    )


def replay_day_trading(
    coin: str, base: dict[str, pd.DataFrame], start: pd.Timestamp, end: pd.Timestamp,
    step: pd.Timedelta = pd.Timedelta(hours=1), max_age: pd.Timedelta = pd.Timedelta(days=1),
    fee_pct: float = 0.1, slippage_pct: float = 0.05,
) -> list[ReplaySignal]:
    signals: list[ReplaySignal] = []
    failures: list[tuple[str, float, pd.Timestamp]] = []
    open_signal: dict[str, ReplaySignal] = {}
    coin_candles = base[coin.upper()]

    t = start
    while t <= end:
        data = ReplayData(base, t)
        df = data.fetch_ohlcv(coin)
        if len(df) >= MIN_CANDLES:
            ind = indicators.compute_indicators(df)
            direction = "long" if ind.ema9 > ind.ema21 else "short"
            existing = open_signal.get(direction)
            if existing is not None and existing.outcome is not None and existing.outcome.exit_at <= t:
                existing = None
            if existing is None or not existing.confirmed:
                zones = indicators.detect_sr_zones(df)
                confirmation = full_confirmation_sync(coin, direction, df, ind, zones, True, data)
                evaluation = setup_eval.evaluate_day_trading_setup(
                    direction, df, ind, zones, confirmation,
                    lambda zone_price, d=direction, a=ind.atr, now=t: _zone_recently_failed(failures, d, zone_price, a, now),
                    [],
                )
                if existing is None or evaluation.confirmed:
                    signal = ReplaySignal(
                        coin=coin, direction=direction, at=t, entry=ind.price, stop=evaluation.stop_loss,
                        take=evaluation.take_profit, confirmed=evaluation.confirmed, reason=evaluation.reason,
                        outcome=resolve(direction, ind.price, evaluation.stop_loss, evaluation.take_profit,
                                        coin_candles, t, max_age, fee_pct, slippage_pct),
                        nearest_sr_zone_price=evaluation.nearest_sr_zone_price,
                    )
                    if (signal.outcome is not None and signal.outcome.result == "stop_loss"
                            and evaluation.nearest_sr_zone_price is not None):
                        failures.append((direction, evaluation.nearest_sr_zone_price, signal.outcome.exit_at))
                    if existing is not None:
                        signals.remove(existing)
                    signals.append(signal)
                    open_signal[direction] = signal
        t += step
    return signals
