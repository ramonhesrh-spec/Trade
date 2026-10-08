"""Rejectie op een niveau live: dezelfde detector als het controlescript (app/replay/rejection.py), toegepast op de gesloten 30m-candles.
Een afwijzing wordt een gewoon signaal (trade_type 'rejectie'): instap op het slot van de candle, stop voorbij de uiterste prik, doelen op zwaaipunten.

Eerlijk over wat dit is: het patroon komt uit twee handgetekende trades (BTC short, CRV long) en is nog niet gemeten. De melding zegt ongetest,
Bewijs toont de score en de motor gaat vanzelf uit als de laatste REJECTION_MAX_NEGATIVE afgeronde signalen samen negatief zijn."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from app import config, push_notify, repo, smc_eval
from app.replay import rejection as rj

logger = logging.getLogger("rejection_live")
BAR = pd.Timedelta(minutes=30)
RECENT_BARS = 2          # alleen afwijzingen op de laatste twee gesloten candles; de cyclus draait elke 5 minuten


def recent_events(df: pd.DataFrame, now: pd.Timestamp) -> list[tuple]:
    """[(event, plan, afwijzende_candle_tijd)] voor de laatste gesloten candles."""
    closed = df[df["timestamp"] + BAR <= now].reset_index(drop=True)
    if len(closed) < 80:
        return []
    events = rj.find_rejections(closed)
    out = []
    for e in events[events["bar"] >= len(closed) - RECENT_BARS].itertuples():
        plan = rj.plan_for(e, closed, smc_eval.floor_stop)
        if plan:
            out.append((e, plan, closed["timestamp"].iloc[int(e.bar)]))
    return out


def facts(e) -> str:
    kind = "weerstand" if e.direction == rj.SHORT else "steun"
    how = "prikte erdoor en sloot terug" if e.swept else "raakte het en sloot ervan weg"
    vol = f", volume {e.vol_ratio:.1f}x gemiddeld" if e.vol_ratio == e.vol_ratio else ""
    return f"Niveau met {e.touches} aanrakingen ({kind}); de candle {how}{vol}."


async def _fire(coin: str, e, plan: dict) -> None:
    from app.signal_processor import fanout_confirmed_signal
    from app.structure_live import trade_tag
    direction, entry, stop = e.direction, plan["entry"], plan["stop"]
    targets_r = plan["targets_r"]
    take = plan["targets"][1] if len(plan["targets"]) > 1 else plan["targets"][0]
    narrative = f"Rejectie op een niveau: {facts(e)}"
    reason = f"Gemeten: {facts(e)} Het plan komt uit code: stop voorbij de uiterste prik, doelen op {'zwaaipunten' if plan['from_levels'] else 'een ladder van 1, 2 en 3R'}."
    signal_id = repo.insert_signal({
        "message_id": None, "coin": coin, "direction": direction, "category": "day_trading", "trade_type": "rejectie", "pattern_name": "Rejectie",
        "price": entry, "rsi": None, "macd": None, "macd_signal": None, "volume_ratio": None, "ema9": None, "ema21": None, "atr": None, "atr_avg20": None,
        "adx": None, "technical_confirmed": 1, "pass_pct": None, "hard_gates_ok": 1, "confidence": "Rejectie", "reason": reason,
        "stop_loss": stop, "take_profit": take, "context_note": None, "is_practice": 0, "plain_explanation": narrative, "suggested_entry_low": None,
        "suggested_entry_high": None, "sniper_entry_price": None, "sniper_reason": None,
    })
    rr = abs(take - entry) / abs(entry - stop)
    ladder = " · ".join(f"{push_notify.fmt_price(t)} ({r:g}R)" for t, r in zip(plan["targets"], targets_r))
    await fanout_confirmed_signal(
        signal_id, coin, direction, entry, stop, take, entry,
        title=push_notify.alert_title(coin, direction, "Rejectie"),
        make_body=lambda *_: push_notify.trade_body("Entry", entry, stop, take, rr, f"Doelen {ladder}", facts(e)),
        reason=reason, signal_type="rejectie", tag=trade_tag(signal_id),
    )


async def _check(coin: str, now: pd.Timestamp) -> None:
    from app import exchange
    df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, timeframe="30m", limit=300)
    since = (now - pd.Timedelta(hours=24)).isoformat()
    for e, plan, at in recent_events(df, now):
        # Sleutel op coin, kant en het uur van de candle: dezelfde afwijzing blijft een paar scans 'waar' en wordt maar één keer gemeld.
        if not repo.alert_once(f"rejectie:{coin}:{e.direction}:{at.isoformat()}"):
            continue
        if len(repo.list_recent_signals_of_type("rejectie", since)) >= config.REJECTION_MAX_PER_DAY:
            logger.info("Rejectie %s %s: dagmaximum bereikt, niet gemeld", coin, e.direction)
            continue
        try:
            await _fire(coin, e, plan)
        except Exception:
            logger.exception("Rejectie voor %s is niet gemeld", coin)


async def run(now: Optional[datetime] = None) -> None:
    """Draait in de SMC-snelcyclus."""
    if not config.REJECTION_ENABLED:
        return
    from app.structure_live import should_disable
    if should_disable(repo.list_type_results("rejectie", config.REJECTION_MAX_NEGATIVE), config.REJECTION_MAX_NEGATIVE):
        repo.notify_engine_disabled("Rejectie", f"De laatste {config.REJECTION_MAX_NEGATIVE} afgeronde signalen zijn samen negatief. Zie Bewijs.")
        return
    stamp = pd.Timestamp(now or datetime.now(timezone.utc))
    symbols = {c["symbol"] for c in repo.list_coins()}
    coins = [c for c in config.FIXED_COINS if c in symbols]
    for coin in coins:
        try:
            await _check(coin, stamp)
        except Exception:
            logger.exception("Rejectie-check voor %s is mislukt", coin)
    repo.beat("rejectie", f"{len(coins)} coins gecontroleerd")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from app import db
    db.init_db()
    asyncio.run(run())
