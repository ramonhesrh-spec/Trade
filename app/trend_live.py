"""Trend plus pullback live: dezelfde detector als de toets (app/replay/trendpullback.py), toegepast op de gesloten candles van de laatste dagen.
Een instap wordt een gewoon signaal (trade_type 'trend'): instap op het 5m-slot, stop onder de laatste 30 minuten, doel TREND_RR keer het risico.

Eerlijk over wat dit is: op een jaar candles en 7 coins gaf deze regel bruto +0,03R en netto -0,06R. Jij wilde hem live ervaren. Daarom altijd ongetest, alleen als stille
melding, maximaal TREND_MAX_PER_DAY per dag, en de melding noemt het gemeten cijfer. Bewijs telt de uitkomsten mee."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from app import config, push_notify, repo
from app.replay import trendpullback as tp
from app.replay.lab import add_indicators

logger = logging.getLogger("trend_live")
TIMEFRAMES = {"5m": (pd.Timedelta(minutes=5), 400), "15m": (pd.Timedelta(minutes=15), 300), "1h": (pd.Timedelta(hours=1), 200), "4h": (pd.Timedelta(hours=4), 150)}
RECENT = pd.Timedelta(minutes=15)
MEASURED_NOTE = "Gemeten op een jaar: -0,06R netto."


def closed_bars(df: pd.DataFrame, delta: pd.Timedelta, now: pd.Timestamp) -> pd.DataFrame:
    """Alleen gesloten candles, met de kolom close_time die de detector verwacht."""
    b = df[df["timestamp"] + delta <= now].copy().reset_index(drop=True)
    b["close_time"] = b["timestamp"] + delta
    return b


def recent_entries(b5: pd.DataFrame, b15: pd.DataFrame, b1h: pd.DataFrame, b4h: pd.DataFrame, now: pd.Timestamp) -> list[dict]:
    """Instappen op de laatste paar 5m-candles. De sleutel bevat het tijdstip van de impuls, niet de positie, want die schuift mee met het venster."""
    ent = tp.entries(add_indicators(b5), add_indicators(b15), b1h, b4h)
    out = []
    for e in ent[ent["at"] >= now - RECENT].itertuples():
        impulse_at = b15["timestamp"].iloc[int(e.impulse_id)]
        out.append({"direction": e.direction, "entry": e.entry, "stop": e.stop, "extreme": e.impulse_extreme, "at": e.at,
                    "key": f"{e.direction}:{impulse_at.isoformat()}"})
    return out


def levels(direction: str, entry: float, stop: float) -> Optional[tuple[float, float]]:
    risk_pct = abs(entry - stop) / entry * 100
    if not (tp.MIN_STOP_PCT <= risk_pct <= tp.MAX_STOP_PCT):
        return None
    sign = 1 if direction == "long" else -1
    return stop, entry + sign * abs(entry - stop) * config.TREND_RR


async def _fire(coin: str, e: dict, stop: float, take: float) -> None:
    from app.signal_processor import fanout_confirmed_signal
    direction, entry = e["direction"], e["entry"]
    reason = ("Trend op 4 uur en 1 uur, impuls op 15 minuten, pullback naar de zone en een bevestiging op 5 minuten. " + MEASURED_NOTE)
    signal_id = repo.insert_signal({
        "message_id": None, "coin": coin, "direction": direction, "category": "day_trading", "trade_type": "trend", "pattern_name": "Trend-pullback",
        "price": entry, "rsi": None, "macd": None, "macd_signal": None, "volume_ratio": None, "ema9": None, "ema21": None, "atr": None, "atr_avg20": None,
        "adx": None, "technical_confirmed": 1, "pass_pct": None, "hard_gates_ok": 1, "confidence": "Trend-pullback", "reason": reason,
        "stop_loss": stop, "take_profit": take, "context_note": None, "is_practice": 0, "plain_explanation": None, "suggested_entry_low": None,
        "suggested_entry_high": None, "sniper_entry_price": None, "sniper_reason": None,
    })
    repo.set_trend_signal(f"{coin}:{e['key']}", signal_id)
    rr = abs(take - entry) / abs(entry - stop)
    await fanout_confirmed_signal(
        signal_id, coin, direction, entry, stop, take, entry,
        title=push_notify.alert_title(coin, direction, "Trend-pullback"),
        make_body=lambda *_: push_notify.trade_body("Entry", entry, stop, take, rr, "Pullback in de trend, bevestigd op 5m.", MEASURED_NOTE),
        reason=reason, signal_type="trend",
    )


async def _check(coin: str, now: pd.Timestamp) -> None:
    from app import exchange
    frames = {}
    for name, (delta, limit) in TIMEFRAMES.items():
        df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, timeframe=name, limit=limit)
        frames[name] = closed_bars(df, delta, now)
    if min(len(f) for f in frames.values()) < 60:
        return
    for e in recent_entries(frames["5m"], frames["15m"], frames["1h"], frames["4h"], now):
        key = f"{coin}:{e['key']}"
        if not repo.insert_trend_entry(key, coin, e["direction"], e["at"].isoformat()):
            continue
        lv = levels(e["direction"], e["entry"], e["stop"])
        today = (now - pd.Timedelta(hours=24)).isoformat()
        if lv is None or repo.count_trend_since(today) >= config.TREND_MAX_PER_DAY:
            continue
        try:
            await _fire(coin, e, *lv)
        except Exception:
            logger.exception("Trend-signaal voor %s is niet gemeld", coin)


async def run(now: Optional[datetime] = None) -> None:
    """Draait in de SMC-snelcyclus."""
    if not config.TREND_ENABLED:
        return
    from app.structure_live import should_disable
    if should_disable(repo.list_type_results("trend", config.TREND_MAX_NEGATIVE), config.TREND_MAX_NEGATIVE):
        repo.notify_engine_disabled("Trend-pullback", f"De laatste {config.TREND_MAX_NEGATIVE} afgeronde signalen zijn samen negatief. Zie Bewijs.")
        return
    stamp = pd.Timestamp(now or datetime.now(timezone.utc))
    symbols = {c["symbol"] for c in repo.list_coins()}
    for coin in config.BASE_COINS:
        if coin not in symbols:
            continue
        try:
            await _check(coin, stamp)
        except Exception:
            logger.exception("Trend-check voor %s is mislukt", coin)
    repo.beat("trend", f"{len(config.BASE_COINS)} coins gecontroleerd")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from app import db
    db.init_db()
    asyncio.run(run())
