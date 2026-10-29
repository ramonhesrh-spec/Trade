"""Zone-radar live: de rekenregels van app/zone_radar.py op de echte candles, elke 5 minuten in de SMC-snelcyclus.

Per cyclus eerst volgen, dan opruimen, dan ontdekken:
  1. Volgen: raakte de koers de limiet van een wachtende kaart, dan wordt het een gewoon signaal (trade_type 'zone_radar') met journaal, melding
     en uitkomst via level_check. Haalde de koers eerst het doel, dan vervalt de kaart stil.
  2. Opruimen: een kaart waarvan de zone niet meer actief is (doorbroken of te oud) vervalt stil.
  3. Ontdekken: per coin en richting hooguit één wachtende kaart, met één melding 'zet je limietorder klaar'. Dagcap op nieuwe kaarten.
Elke melding gaat via push_notify.send_kans_push (dagbudget, conflictregel, stille uren). Ongetest: Bewijs toont de score."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from app import chance_checks, config, market_context, poc_radar_live, repo
from app import zone_radar as zr

logger = logging.getLogger("zone_radar_live")
FILL_TF = "5m"
FILL_LIMIT = 300


def card_url(setup_id: int) -> str:
    return f"/smc#radar-zone-{setup_id}"


def new_card_body(card: dict) -> str:
    from app import push_notify
    zone = f"{zr.zone_text(card['direction'], card['tf'])} {push_notify.fmt_price(card['zone_low'])} tot {push_notify.fmt_price(card['zone_high'])}."
    target = f"Doel: {zr.target_text(card['direction'], card['target_tf'])}."
    limit = card["zone_high"] if card["direction"] == "long" else card["zone_low"]
    return push_notify.trade_body("Limietorder", limit, card["stop_loss"], card["take_profit"], card["rr"], zone, target,
                                  "Zet je limietorder klaar als je hem wilt. Ongetest.")


async def _push_new_card(card: dict) -> None:
    from app import push_notify
    if not repo.mark_zone_radar_alert_sent(card["id"]):
        return
    title = push_notify.alert_title(card["coin"], card["direction"], f"{zr.LABEL} · ongetest")
    body = new_card_body(card)
    for user in repo.list_users():
        quiet = push_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            await push_notify.send_kans_push(user["id"], card["coin"], card["direction"], title, body, card_url(card["id"]), silent=quiet,
                                             tag=f"zone-radar-{card['id']}")
        except Exception:
            logger.exception("Zone-radar-melding voor %s naar gebruiker %s is mislukt", card["coin"], user["username"])


def signal_row(card: dict) -> dict:
    limit = card["zone_high"] if card["direction"] == "long" else card["zone_low"]
    near = card.get("poc_near")
    reason, pass_pct = chance_checks.with_checks(f"Gemeten: actieve zone op {zr.TF_TEXT.get(card['tf'], card['tf'])}, R:R {card['rr']:.1f} vanaf de limiet.",
                                                 None if near is None else bool(near))
    narrative = (f"{zr.zone_text(card['direction'], card['tf'])} {card['zone_low']:.6g} tot {card['zone_high']:.6g}, limiet op de binnenrand {limit:.6g}. "
                 f"Doel de rand van de {zr.target_text(card['direction'], card['target_tf'])} op {card['take_profit']:.6g}. Ongetest.")
    return {
        "message_id": None, "coin": card["coin"], "direction": card["direction"], "category": "day_trading", "trade_type": zr.TRADE_TYPE,
        "pattern_name": zr.LABEL, "price": limit, "rsi": None, "macd": None, "macd_signal": None, "volume_ratio": None, "ema9": None, "ema21": None,
        "atr": None, "atr_avg20": None, "adx": None, "technical_confirmed": 1, "pass_pct": pass_pct, "hard_gates_ok": 1,
        "confidence": f"{zr.LABEL} (ongetest)", "reason": reason,
        "stop_loss": card["stop_loss"], "take_profit": card["take_profit"], "context_note": None, "is_practice": 0, "plain_explanation": narrative,
        "suggested_entry_low": card["zone_low"], "suggested_entry_high": card["zone_high"], "sniper_entry_price": None, "sniper_reason": None,
    }


async def _fill(card: dict) -> None:
    from app import push_notify
    from app.signal_processor import fanout_confirmed_signal
    from app.structure_live import trade_tag
    signal_id = repo.fill_zone_radar_setup(card["id"], signal_row(card))
    if signal_id is None:
        return
    direction = card["direction"]
    entry = card["zone_high"] if direction == "long" else card["zone_low"]
    await fanout_confirmed_signal(
        signal_id, card["coin"], direction, entry, card["stop_loss"], card["take_profit"], entry,
        title=push_notify.alert_title(card["coin"], direction, f"{zr.LABEL} gevuld"),
        make_body=lambda sl, tp_, _capped: push_notify.trade_body("Entry", entry, sl, tp_, card["rr"], "De koers is in de zone, je limiet is geraakt.", "Ongetest."),
        reason="", signal_type=zr.TRADE_TYPE, tag=trade_tag(signal_id),
    )


async def _track(waiting: list[dict]) -> None:
    from app import exchange
    for coin in sorted({c["coin"] for c in waiting}):
        try:
            df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, timeframe=FILL_TF, limit=FILL_LIMIT)
        except Exception:
            logger.exception("%s-candles voor %s niet op te halen, kaarten blijven wachten", FILL_TF, coin)
            continue
        for card in (c for c in waiting if c["coin"] == coin):
            # Ook de candle die nog vormt: een aanraking van de limiet is een vulling, ook vóór het slot. Alleen candles die na de kaart openden,
            # anders telt een prik van vóór de kaart als vulling.
            after = df[df["timestamp"] >= pd.Timestamp(card["created_at"])]
            what, _at = zr.walk(card["direction"], card["zone_high"] if card["direction"] == "long" else card["zone_low"], card["take_profit"], after)
            try:
                if what == "filled":
                    await _fill(card)
                elif what == "doel_geraakt":
                    repo.end_zone_radar_setup(card["id"], "doel_geraakt")
            except Exception:
                logger.exception("Zone-radar-kaart %s voor %s is niet verwerkt", card["id"], coin)


async def _zones(coin: str, now: pd.Timestamp) -> tuple[list[zr.ZoneLevel], Optional[float]]:
    from app import exchange
    zones, price = [], None
    for tf in zr.TFS:
        df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, timeframe=tf, limit=zr.FETCH_LIMIT_BY_TF[tf])
        zones += zr.active_zones(df, tf, now)
        if tf == zr.TFS[0] and len(df):
            price = float(df["close"].iloc[-1])      # de candle die nog vormt: zijn slot is de koers van nu
    return zones, price


async def _scan(coin: str, now: pd.Timestamp, waiting: list[dict]) -> list[dict]:
    """Ruimt vervallen kaarten op en geeft de nieuwe plannen terug; `run` kiest daaruit, zodat de volgorde van de coins niet bepaalt wie binnen de dagcap valt."""
    zones, price = await _zones(coin, now)
    keys = {z.key for z in zones}
    mine = [c for c in waiting if c["coin"] == coin]
    for card in mine:
        if card["zone_key"] not in keys:
            repo.end_zone_radar_setup(card["id"], "zone_weg")
    if not price:
        return []
    busy = {c["direction"] for c in mine if c["zone_key"] in keys}
    return [{**plan, "coin": coin, "distance": abs(plan["limit"] - price) / price} for plan in zr.plans(zones, price) if plan["direction"] not in busy]


def _context(coin: str, stamp: pd.Timestamp) -> dict:
    """De marktcontext bij het ontstaan van de kaart, om later op Bewijs te toetsen. Hij wordt pas na de keuze van het plan gelezen: de kaart zelf
    hangt er niet van af, en een fout hier kost alleen de stand, nooit de kaart."""
    try:
        latest = market_context.latest(repo.latest_market_context([coin])).get(coin, {})
        return market_context.snapshot(latest, stamp.to_pydatetime())
    except Exception:
        logger.exception("Marktcontext voor %s niet te lezen, kaart zonder stand", coin)
        return {}


async def run(now: Optional[datetime] = None) -> None:
    """Draait in de SMC-snelcyclus (market_scanner.scan_smc_fast)."""
    if not config.ZONE_RADAR_ENABLED:
        return
    stamp = pd.Timestamp(now or datetime.now(timezone.utc))
    await _track(repo.list_zone_radar_setups())
    waiting = repo.list_zone_radar_setups()
    coins = [c["symbol"] for c in repo.list_coins()]
    found: list[dict] = []
    for coin in coins:
        try:
            found += await _scan(coin, stamp, waiting)
        except Exception:
            logger.exception("Zone-radar voor %s is mislukt", coin)
    since = (stamp - pd.Timedelta(hours=24)).isoformat()
    for plan in sorted(found, key=lambda p: (p["distance"], p["coin"], p["direction"])):
        if repo.count_zone_radar_setups_since(since) >= config.ZONE_RADAR_MAX_PER_DAY:
            logger.info("Zone-radar: dagcap van %s kaarten bereikt, %s %s wacht", config.ZONE_RADAR_MAX_PER_DAY, plan["coin"], plan["direction"])
            break
        # POC-samenval pas na de keuze van het plan, net als de context: een kenmerk, nooit een filter.
        near = poc_radar_live.samenval(plan["coin"], plan["limit"], stamp)
        setup_id = repo.insert_zone_radar_setup({**{k: v for k, v in plan.items() if k != "distance"}, **_context(plan["coin"], stamp),
                                                 "poc_near": None if near is None else int(near)}, stamp.isoformat())
        if setup_id is None:
            continue
        logger.info("Zone-radar %s %s: kaart %s, %s %s-%s, R:R %.1f", plan["coin"], plan["direction"], setup_id, plan["tf"], plan["zone_low"], plan["zone_high"], plan["rr"])
        await _push_new_card({**plan, "id": setup_id})
    repo.beat("zone_radar", f"{len(coins)} coins gecontroleerd")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from app import db
    db.init_db()
    asyncio.run(run())
