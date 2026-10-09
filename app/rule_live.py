"""Proefmotor: één regel uit het strategie-lab (app/replay/trendlab.py) live, met de meelopende stop van het lab, alleen voor de CEO.

Spec fase 2 (docs/superpowers/specs/2026-10-09-hespulse-visie-en-plan-design.md, sectie 5 en 6): een regel die in het lab slaagde loopt als proef.
De live cijfers bewijzen niets (50 trades kunnen 0,1R niet aantonen), ze laten zien of de werkelijkheid van het lab afwijkt. Daarom alleen de CEO:
journaalregels en meldingen gaan naar hem, leerlingen zien de proef niet.

Detectie gebruikt dezelfde code als het lab (prepare en signals_for) op alleen gesloten candles. Het lab stapt in op de open van de candle na het
signaal; bij de melding is die nog niet bekend, dus het signaal draagt het slot van de signaalcandle als richtprijs. R rekent vanaf die richtprijs.
signals.stop_loss blijft de eerste stop (risico, R en kosten op Bewijs rekenen daarmee), de meelopende stop staat in rule_trades. Er is geen vast
doel (take_profit leeg): de 15-minutencheck van stop en doel laat deze soort daarom met rust en deze module zet zelf de uitkomst en de echte R."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import numpy as np
import pandas as pd

from app import config, push_notify, repo
from app.replay import trendlab as tl
from app import track_record
from app.track_record import _cost_r, signal_r

logger = logging.getLogger("rule_live")

RULE_VARIANT = "DON55_TREND"
RULE = RULE_VARIANT.lower()
COINS = tl.LAB_COINS
ENGINE_TYPES = (RULE,)       # regels uit het lab die een live motor hebben; de andere labvarianten tonen op Bewijs "Geen motor"
CEO_ONLY_TYPES = (RULE,)     # soorten die alleen de CEO ziet: geen journaal, kans, cijfers of activiteit voor leerlingen
MAX_NEGATIVE = 30            # spec sectie 5: een regel zet zichzelf uit na 30 negatieve afgeronde trades
FETCH_LIMIT = 1000           # het maximum van Binance per aanroep; de EMA van 200 heeft ruim aanloop nodig om op de labwaarde uit te komen
# Een candle van 4 uur verandert maar één keer per 4 uur. Alleen in het eerste halfuur na een slot ophalen; daarna is een melding ook te laat,
# want het lab stapt in op de open van de volgende candle. Ruim boven de 5 minuten van de cyclus, zodat een gemiste cyclus niets kost.
SCAN_WINDOW = pd.Timedelta(minutes=30)


def variant(name: str = RULE_VARIANT) -> tl.Variant:
    return next(v for v in tl.VARIANTS if v.name == name)


def stop_factors(v: tl.Variant) -> tuple[float, float]:
    """(k_stop, k_trail) zoals trendlab._trade ze kiest: de swing-families hebben eigen waarden, de rest de vaste."""
    return (v.k_stop, v.k_trail) if v.family.startswith("swing_") else (tl.TRAIL_K_STOP, tl.TRAIL_K)


def closed_only(df: pd.DataFrame, delta: pd.Timedelta, now: pd.Timestamp) -> pd.DataFrame:
    """De timestamp van een candle is zijn openmoment: gesloten is hij op timestamp + timeframe. De vormende candle valt zo weg."""
    return df[df["timestamp"] + delta <= now].reset_index(drop=True)


def detect(bars: pd.DataFrame, v: tl.Variant, htf_bars: Optional[pd.DataFrame] = None) -> Optional[dict]:
    """Een signaal op de laatste rij van bars (die gesloten moet zijn), of None. Stop op k_stop ATR van de richtprijs, zoals het lab."""
    if v.family == "sweep" or v.max_bars:
        raise ValueError(f"{v.name}: de proefmotor volgt alleen een meelopende stop zonder tijdslimiet")
    if v.htf and htf_bars is None:
        raise ValueError(f"{v.name} heeft 4u-candles nodig (htf_bars)")
    b = tl.prepare(bars)
    htf = tl.htf_trend(b, tl.prepare(htf_bars)) if v.htf else None
    last = len(b) - 1
    signs = [s for i, s in tl.signals_for(v, b, htf) if i == last]
    atr = float(b["atr"].iloc[last]) if last >= 0 else float("nan")
    if not signs or not np.isfinite(atr) or atr <= 0:
        return None
    entry = float(b["close"].iloc[last])
    return {"direction": "long" if signs[0] == 1 else "short", "entry": entry, "stop": entry - signs[0] * stop_factors(v)[0] * atr, "atr": atr}


def next_stop(direction: str, current_stop: float, bars_since_entry: pd.DataFrame, atr: float, k_trail: float = tl.TRAIL_K) -> float:
    """Chandelier zoals trendlab.exit_trail: k_trail ATR van het uiterste sinds de instap, alleen de gunstige kant op. Met een kolom atr telt de
    ATR per candle (zoals het lab), anders de vaste atr."""
    if bars_since_entry.empty:
        return current_stop
    a = bars_since_entry["atr"] if "atr" in bars_since_entry else atr
    if direction == "long":
        return float(max(current_stop, (bars_since_entry["high"].cummax() - k_trail * a).max()))
    return float(min(current_stop, (bars_since_entry["low"].cummin() + k_trail * a).min()))


def close_if_hit(signal: dict, bars: pd.DataFrame) -> Optional[tuple[float, str]]:
    """(R, uitkomst) bij de eerste candle die de huidige stop raakt, anders None. R rekent met het risico van de eerste stop; een gat door de stop
    vult op de open. R boven 0 telt als take_profit (de meelopende stop zette winst vast), anders stop_loss."""
    sign = 1 if signal["direction"] == "long" else -1
    stop, entry = signal["current_stop"], signal["price"]
    risk = abs(entry - signal["initial_stop"])
    for row in bars.itertuples():
        if (row.low <= stop) if sign == 1 else (row.high >= stop):
            op = getattr(row, "open", stop)
            fill = min(op, stop) if sign == 1 else max(op, stop)
            r = sign * (fill - entry) / risk
            return r, "take_profit" if r > 0 else "stop_loss"
    return None


def follow(trade: dict, closed: pd.DataFrame, forming: Optional[pd.DataFrame], k_trail: float,
           checked_until: Optional[pd.Timestamp] = None) -> tuple[float, Optional[tuple[float, str, pd.Timestamp]]]:
    """(stop, None) of (stop, (R, uitkomst, tijdstip)). Begint bij trade["current_stop"] en loopt de gesloten candles sinds de instap af zoals
    exit_trail: eerst toetsen tegen de stop van vóór die candle, dan de stop bijwerken. Candles tot en met checked_until zijn al verwerkt (de
    bewaarde stop bevat ze) en tellen alleen nog mee voor het uiterste sinds de instap. De vormende candle wordt alleen getoetst: de stop
    schuift pas op als een candle gesloten is."""
    stop = trade["current_stop"]
    for j in range(len(closed)):
        if checked_until is not None and closed["timestamp"].iloc[j] <= checked_until:
            continue
        hit = close_if_hit({**trade, "current_stop": stop}, closed.iloc[[j]])
        if hit:
            return stop, (*hit, closed["timestamp"].iloc[j])
        stop = next_stop(trade["direction"], stop, closed.iloc[: j + 1], trade["atr"], k_trail)
    if forming is not None and not forming.empty:
        hit = close_if_hit({**trade, "current_stop": stop}, forming.iloc[[0]])
        if hit:
            return stop, (*hit, forming["timestamp"].iloc[0])
    return stop, None


def for_viewer(rows: list[dict], ceo: bool) -> list[dict]:
    """Signaalrijen voor de cijfers die een gebruiker ziet: de proef telt alleen voor de CEO mee."""
    return rows if ceo else [r for r in rows if r["trade_type"] not in CEO_ONLY_TYPES]


def stop_moved(direction: str, old: float, new: float) -> bool:
    """Alleen een echte verschuiving de gunstige kant op: een paar bits verschil in de ATR geeft geen melding met dezelfde prijs."""
    step = (new - old) if direction == "long" else (old - new)
    return step > 1e-9 * abs(old)


def should_disable(closed_r_net: list[float]) -> bool:
    """closed_r_net oud naar nieuw. Uit als er minstens MAX_NEGATIVE afgeronde trades zijn en de laatste MAX_NEGATIVE samen netto negatief zijn."""
    last = closed_r_net[-MAX_NEGATIVE:]
    return len(last) >= MAX_NEGATIVE and sum(last) / len(last) < 0


def net_results(rows: list[dict], cost_pct: float) -> list[float]:
    """Netto R per afgeronde trade, oud naar nieuw. rows komen nieuwste eerst uit repo.list_type_results."""
    out = []
    for r in reversed(rows):
        gross = signal_r(r)
        if gross is not None:
            out.append(gross - _cost_r(r, cost_pct))
    return out


def fetch_bars(coin: str, timeframe: str, limit: int) -> pd.DataFrame:
    from app import exchange
    return exchange.fetch_ohlcv(coin, timeframe=timeframe, limit=limit)


def label(v: tl.Variant, proven: bool = False) -> str:
    """Soort in de melding; "in proef" valt weg zodra Bewijs de regel bewezen noemt, zodat melding en Bewijs elkaar niet tegenspreken."""
    return f"Trend {v.timeframe.replace('h', 'u')}" + ("" if proven else " in proef")


def live_results() -> list[float]:
    """Netto R van alle afgeronde trades van deze regel, oud naar nieuw."""
    return net_results(repo.list_type_results(RULE, 1_000_000), config.TRACK_RECORD_COST_PCT)


def is_proven(lab: Optional[dict], net: list[float]) -> bool:
    return track_record.rule_status(lab, net)["status"] == "Bewezen"


def tag(signal_id: int) -> str:
    """Eén lopende melding per trade: nieuw, stop verplaatst en gesloten vervangen elkaar."""
    return f"trend-{signal_id}"


async def _push_ceo(title: str, body: str, url: str, signal_id: int, kans: Optional[tuple[str, str]] = None) -> None:
    """Met kans (coin, richting) is het een nieuwe kans en gelden de pushregels; zonder is het een update en komt hij altijd."""
    for uid in repo.list_ceo_user_ids():
        user = repo.get_user(uid) or {}
        quiet = push_notify.is_quiet_now(user.get("quiet_hours_start"), user.get("quiet_hours_end"))
        try:
            if kans:
                await push_notify.send_kans_push(uid, kans[0], kans[1], title, body, url, silent=quiet, tag=tag(signal_id))
            else:
                await push_notify.send_push(uid, title, body, url, silent=quiet, tag=tag(signal_id))
        except Exception:
            logger.exception("Proefmelding %s naar gebruiker %s is mislukt", signal_id, uid)


async def _open_trade(coin: str, v: tl.Variant, sig: dict, entered_at: pd.Timestamp, proven: bool) -> None:
    direction, entry, stop = sig["direction"], sig["entry"], sig["stop"]
    k_trail = stop_factors(v)[1]
    # Geen schakel in de openbare ketting: /keten is zonder login en de proef is alleen voor de CEO.
    signal_id = repo.insert_signal({
        "message_id": None, "coin": coin, "direction": direction, "category": "day_trading", "trade_type": RULE, "pattern_name": v.name,
        "price": entry, "technical_confirmed": 1, "hard_gates_ok": 1, "confidence": "In proef", "stop_loss": stop, "take_profit": None,
        # Een tekst zonder " | ": de pagina's lezen reason, en het ✓/✗-format hoort bij gemeten kenmerken die deze regel niet heeft.
        "reason": f"In proef: {v.name}, meelopende stop op {k_trail:g} ATR", "pass_pct": None, "is_practice": 0,
        "plain_explanation": f"{label(v, proven)}: richtprijs {push_notify.fmt_price(entry)} is het slot van de signaalcandle, het lab stapt in op de open van de "
                             f"volgende. Geen vast doel, de stop loopt mee op {k_trail:g} ATR.",
    }, chain_it=False)
    # De signaalcandle is verwerkt; de instapcandle (entered_at) is de eerste die tegen de stop wordt getoetst.
    repo.insert_rule_trade(signal_id, RULE, coin, entered_at.isoformat(), stop, sig["atr"], (entered_at - pd.Timedelta(v.timeframe)).isoformat())
    for uid in repo.list_ceo_user_ids():
        repo.create_journal_entry(signal_id, uid, None)
    body = "\n".join([f"Richtprijs {push_notify.fmt_price(entry)} (slot van de signaalcandle, instap op de open van de volgende)",
                      f"Stop {push_notify.fmt_price(stop)} · geen vast doel, de stop loopt mee op {k_trail:g} ATR", push_notify.OPEN_PLAN_LINE])
    await _push_ceo(push_notify.alert_title(coin, direction, label(v, proven)), body, push_notify.signal_url(coin, signal_id), signal_id, kans=(coin, direction))
    logger.info("Proef %s: %s %s op %s, stop %s", RULE, coin, direction, entry, stop)


async def _scan_coin(coin: str, v: tl.Variant, delta: pd.Timedelta, now: pd.Timestamp, proven: bool) -> None:
    if repo.list_open_rule_trades(RULE, coin):
        return
    closed = closed_only(await asyncio.to_thread(fetch_bars, coin, v.timeframe, FETCH_LIMIT), delta, now)
    if len(closed) <= tl.WARMUP:
        return
    entered_at = closed["timestamp"].iloc[-1] + delta
    if repo.rule_trade_exists(RULE, coin, entered_at.isoformat()):
        return
    htf = closed_only(await asyncio.to_thread(fetch_bars, coin, "4h", FETCH_LIMIT), pd.Timedelta(hours=4), now) if v.htf else None
    sig = detect(closed, v, htf)
    if sig is not None:
        await _open_trade(coin, v, sig, entered_at, proven)


async def scan(now: Optional[datetime] = None) -> None:
    """Draait in de 5-minutencyclus; doet alleen iets in het eerste halfuur na het slot van een candle."""
    stamp = pd.Timestamp(now or datetime.now(timezone.utc))
    v = variant()
    delta = pd.Timedelta(v.timeframe)
    if stamp - stamp.floor(delta) > SCAN_WINDOW:
        return
    # Spec sectie 7: geen nieuwe regel live zonder lab-toets. Open trades volgt update_open gewoon verder.
    lab = repo.get_rule_lab(RULE)
    if not (lab or {}).get("lab_passes"):
        logger.info("Proef %s: geen geslaagde labtoets (scripts/strategy_lab.py --opslaan), geen nieuwe trades", RULE)
        return
    net = live_results()
    if should_disable(net):
        repo.notify_engine_disabled(label(v), f"De laatste {MAX_NEGATIVE} afgeronde trades zijn samen netto negatief. Zie Bewijs.")
        return
    proven = is_proven(lab, net)
    for coin in COINS:
        try:
            await _scan_coin(coin, v, delta, stamp, proven)
        except Exception:
            logger.exception("Proef %s voor %s is mislukt", RULE, coin)
    repo.beat(RULE, f"{len(COINS)} coins gecontroleerd")


async def _update_trade(t: dict, v: tl.Variant, delta: pd.Timedelta, now: pd.Timestamp, proven: bool) -> None:
    b = tl.prepare(await asyncio.to_thread(fetch_bars, t["coin"], v.timeframe, FETCH_LIMIT))
    is_closed = b["timestamp"] + delta <= now
    closed, forming = b[is_closed], b[~is_closed].head(1)
    entered = pd.Timestamp(t["entered_at"])
    since = closed[closed["timestamp"] >= entered].reset_index(drop=True)
    checked = pd.Timestamp(t["checked_until"])
    stop, hit = follow(t, since, forming, stop_factors(v)[1], checked_until=checked)
    if not stop_moved(t["direction"], t["current_stop"], stop):
        stop = t["current_stop"]
    last_closed = since["timestamp"].iloc[-1] if len(since) else checked
    def title_of(word: str) -> str:
        return push_notify.alert_title(t["coin"], t["direction"], f"{label(v, proven)} · {word}")
    url = push_notify.signal_url(t["coin"], t["signal_id"])
    if hit:
        r, outcome, _candle_at = hit
        # Het moment van vaststellen, nooit vóór de melding: een stop in de instapcandle heeft een candletijd van vóór "Gemeld".
        closed_at = max(now, pd.Timestamp(t["created_at"])).isoformat()
        repo.set_rule_progress(t["signal_id"], stop, max(last_closed, checked).isoformat())
        repo.set_trade_result(t["signal_id"], r, closed_at)
        repo.mark_signal_auto_outcome(t["signal_id"], outcome, closed_at)
        exit_price = t["price"] + (1 if t["direction"] == "long" else -1) * r * abs(t["price"] - t["initial_stop"])
        await _push_ceo(title_of("gesloten"), f"Stop geraakt, uitgang {push_notify.fmt_price(exit_price)}\nResultaat {r:+.2f}R bruto, de trade is klaar.",
                        url, t["signal_id"])
        logger.info("Proef %s: trade %s gesloten op %+.2fR", RULE, t["signal_id"], r)
        return
    if last_closed > checked:
        repo.set_rule_progress(t["signal_id"], stop, last_closed.isoformat())
    if stop != t["current_stop"]:
        locked = (1 if t["direction"] == "long" else -1) * (stop - t["price"]) / abs(t["price"] - t["initial_stop"])
        await _push_ceo(title_of("stop verplaatst"),
                        f"Zet je stop op {push_notify.fmt_price(stop)} (was {push_notify.fmt_price(t['current_stop'])})\n"
                        f"Daarmee ligt {locked:+.2f}R vast. Geen vast doel, de stop loopt mee.", url, t["signal_id"])


async def update_open(now: Optional[datetime] = None) -> None:
    """Draait in de 15-minutencheck (app/level_check.py): stop bijwerken, en sluiten als hij geraakt is. Updates en sluiten gaan altijd, buiten het budget."""
    stamp = pd.Timestamp(now or datetime.now(timezone.utc))
    v = variant()
    delta = pd.Timedelta(v.timeframe)
    trades = repo.list_open_rule_trades(RULE)
    if not trades:
        return
    proven = is_proven(repo.get_rule_lab(RULE), live_results())
    for t in trades:
        try:
            await _update_trade(t, v, delta, stamp, proven)
        except Exception:
            logger.exception("Proeftrade %s volgen is mislukt", t["signal_id"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from app import db
    db.init_db()
    asyncio.run(scan())
    asyncio.run(update_open())
