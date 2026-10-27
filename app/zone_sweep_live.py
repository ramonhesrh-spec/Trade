"""Zone-sweep live: de detector van het lab (app/replay/zonesweep.py) op gesloten candles, elke 5 minuten in de SMC-snelcyclus
(market_scanner.scan_smc_fast), naast de range sweep en de zone-radar.

Ongetest, op uitdrukkelijk verzoek van de gebruiker (2026-10-27): de pre-registratie wil eerst een geslaagde labrun, de gebruiker koos voor live met
het label ongetest, zoals RANGE_SWEEP_UNTESTED. Alleen de drie vooraf vastgelegde varianten ZS_1H, ZS_2H en ZS_4H met de stop wick_025; niets
is afgesteld. De labrun (zs_*, zone_sweep_stop, zone_sweep) blijft de toets; Bewijs toont de live score apart.

Het systeem plaatst nooit een order. Drie stappen per cyclus:
  scan:   setups die op de laatst gesloten 1u-candle ontstonden, als kaart (app/zone_sweep.py) met één melding; dagcap en dode plannen stil.
  track:  wachtende limieten: gevuld wordt een gewoon signaal (trade_type 'zone_sweep', buiten de hash-keten), anders vervalt de kaart volgens de
          regels van het lab (24 uur, weggelopen, open voorbij de stop).
  follow: gevulde kaarten zonder doel: de meting tot de stop of 7 dagen en de referentie-uitgang (de R die Bewijs telt), zoals de range sweep.
          Met een doel beslist level_check de uitkomst op doel en stop."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from app import config, push_notify, range_sweep_live as rsl, repo
from app import zone_sweep as zsw
from app.replay import rangesweep as rs, stopquality as sq, trendlab as tl, zonesweep as zs, zonesweep_lab as zl

logger = logging.getLogger("zone_sweep_live")

TRADE_TYPE = zsw.TRADE_TYPE
COINS = tl.LAB_COINS
LIVE_VARIANTS = zsw.LIVE_VARIANTS
FRESH = rsl.FRESH
# Een setup ontstaat bij het slot van een 1u-candle; alleen kort daarna zoeken, dan hoeft de motor niet elke cyclus 20 coins op te halen.
SCAN_MINUTES = 20
M15 = pd.Timedelta(minutes=15)
ALL_STATES = ("waiting", "filled", "verlopen", "weggelopen", "stop_voor_vulling")


def viewers() -> list[int]:
    return [u["id"] for u in repo.list_users()] if config.ZONE_SWEEP_PUBLIC else repo.list_ceo_user_ids()


def card_url(setup_id: int) -> str:
    return f"/smc#radar-zsweep-{setup_id}"


def _tag(setup_id: int) -> str:
    return f"zone-sweep-{setup_id}"


def fresh_setups(frames: dict, v: zl.ZSVariant, now: pd.Timestamp) -> list[dict]:
    """Setups van dit moment, op alleen gesloten candles: een vormende candle mag de detectie niet laten zien wat bij het sluiten verdwijnt."""
    closed = {tf: rs.closed_only(df, now, tf) for tf, df in frames.items()}
    setups, _ = zs.find_setups(closed, v.tf, v.entry, v.htf)
    return [s for s in setups if now - FRESH < s["placed_at"] <= now]


async def _frames(coin: str, now: pd.Timestamp) -> tuple[dict, Optional[float]]:
    """De frames van de range sweep (dezelfde ophaling, in dezelfde cyclus uit de cache van range_sweep_live.fetch_bars) en de koers van nu: het
    slot van de 15m-candle die nog vormt."""
    parts, price = [], None
    for tf in ("15m", "1h", "4h"):
        bars = rsl._upto(await asyncio.to_thread(rsl.fetch_bars, coin, tf, rsl.FETCH_LIMIT), now)
        if tf == "15m" and len(bars):
            price = float(bars["close"].iloc[-1])
        parts.append(rs.closed_only(bars, now, tf))
    return rs.build_frames(*parts), price


async def _announce(card: dict) -> None:
    if not repo.mark_zone_sweep_alert_sent(card["id"]):
        return
    title = push_notify.alert_title(card["coin"], card["direction"], f"{zsw.LABEL} · ongetest")
    body = zsw.new_card_body(card)
    for uid in viewers():
        user = repo.get_user(uid) or {}
        quiet = push_notify.is_quiet_now(user.get("quiet_hours_start"), user.get("quiet_hours_end"))
        try:
            await push_notify.send_kans_push(uid, card["coin"], card["direction"], title, body, card_url(card["id"]), silent=quiet, tag=_tag(card["id"]))
        except Exception:
            logger.exception("Zone-sweep-melding %s naar gebruiker %s is mislukt", card["id"], uid)


async def _register(row: dict, price: Optional[float], now: pd.Timestamp) -> None:
    # Elke gemelde kaart telt voor de dagcap, ook een die later verviel: de melding ging al uit.
    capped = repo.count_zone_sweep_announced_since((now - zsw.TTL).isoformat()) >= config.ZONE_SWEEP_MAX_PER_DAY
    dead = not zsw.alive(row, price)
    # Stil boven de dagcap of bij een plan dat al voorbij stop of doel staat: de kaart wordt wel gevolgd, zoals het lab elke setup meet.
    row = {**row, "quiet": 1 if capped or dead else 0}
    setup_id = repo.insert_zone_sweep_setup(row, now.isoformat())
    if setup_id is None:
        return
    logger.info("Zone-sweep %s %s %s: kaart %s, doel %s%s", row["coin"], row["direction"], row["variant"], setup_id, row["take_profit"],
                " (stil: dagcap)" if capped else " (stil: plan al voorbij)" if dead else "")
    if not row["quiet"]:
        await _announce({**row, "id": setup_id})


async def scan(now: Optional[datetime] = None) -> None:
    if not config.ZONE_SWEEP_ENABLED:
        return
    stamp = rsl._utc(now)
    if stamp.minute >= SCAN_MINUTES:
        return
    variants = [v for v in zl.VARIANTS if v.name in LIVE_VARIANTS]
    for coin in COINS:
        try:
            frames, price = await _frames(coin, stamp)
            zones = None
            for v in variants:
                for s in fresh_setups(frames, v, stamp):
                    zones = zsw.zone_levels(frames, stamp) if zones is None else zones
                    await _register(zsw.card_row(coin, v.name, s, zones), price, stamp)
        except Exception:
            logger.exception("Zone-sweep voor %s is mislukt", coin)
    repo.beat("zone_sweep", f"{len(COINS)} coins gecontroleerd")


async def _fill(card: dict, entry: float, filled_at: pd.Timestamp) -> None:
    measure = None
    if card["take_profit"] is None:
        # Zonder doel meet de motor zelf, vanaf de candle vóór de vulling (zoals de range sweep): de vulcandle telt alleen tegen.
        measure = {"entry": entry, "stop": card["stop_loss"], "filled_at": filled_at.isoformat(), "checked_until": (filled_at - M15).isoformat()}
    uids = viewers()
    signal_id = repo.fill_zone_sweep_setup(card["id"], zsw.signal_row(card, entry), uids, measure)
    if signal_id is None:
        return
    logger.info("Zone-sweep %s %s gevuld op %s, stop %s, doel %s", card["coin"], card["direction"], entry, card["stop_loss"], card["take_profit"])
    title = push_notify.alert_title(card["coin"], card["direction"], f"{zsw.LABEL} gevuld")
    body = zsw.fill_body(card, entry)
    for uid in uids:
        user = repo.get_user(uid) or {}
        quiet = push_notify.is_quiet_now(user.get("quiet_hours_start"), user.get("quiet_hours_end"))
        try:
            await push_notify.send_kans_push(uid, card["coin"], card["direction"], title, body, push_notify.signal_url(card["coin"], signal_id),
                                             silent=quiet, tag=_tag(card["id"]))
        except Exception:
            logger.exception("Zone-sweep-vulling %s naar gebruiker %s is mislukt", card["id"], uid)


async def _track_one(card: dict, b15: pd.DataFrame, now: pd.Timestamp) -> None:
    placed, expires = pd.Timestamp(card["placed_at"]), pd.Timestamp(card["expires_at"])
    c = rsl._upto(b15, now)
    c = c[c["timestamp"] >= placed].reset_index(drop=True)
    mid = (card["range_high"] + card["range_low"]) / 2
    res = sq.simulate_fills(card["direction"], [(1.0, card["limit_price"])], card["stop_loss"], mid, c, 0)
    if res["filled"]:
        _w, price, m = res["filled"][0]
        await _fill(card, float(price), c["timestamp"].iloc[m])
    elif res["cancel"] in ("stop voor vulling", "weggelopen") or (res["cancel"] == "verlopen" and now >= expires):
        if repo.end_zone_sweep_setup(card["id"], rsl.CANCEL_STATE[res["cancel"]]):
            logger.info("Zone-sweep %s %s: %s", card["coin"], card["direction"], res["cancel"])


async def track(now: Optional[datetime] = None) -> None:
    """Draait ook als de motor uit staat: wat al gemeld is, wordt afgemaakt."""
    stamp = rsl._utc(now)
    cache: dict[str, pd.DataFrame] = {}
    for card in repo.list_zone_sweep_setups(("waiting",)):
        try:
            if card["coin"] not in cache:
                cache[card["coin"]] = await asyncio.to_thread(rsl.fetch_bars, card["coin"], "15m", rsl.TRACK_LIMIT)
            await _track_one(card, cache[card["coin"]], stamp)
        except Exception:
            logger.exception("Zone-sweep-kaart %s volgen is mislukt", card["id"])


async def follow(now: Optional[datetime] = None) -> None:
    stamp = rsl._utc(now)
    cache: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for t in repo.list_open_zone_sweep_trades():
        try:
            if t["coin"] not in cache:
                cache[t["coin"]] = (await asyncio.to_thread(rsl.fetch_bars, t["coin"], "15m", rsl.FETCH_LIMIT),
                                    await asyncio.to_thread(rsl.fetch_bars, t["coin"], "1h", rsl.FETCH_LIMIT))
            await rsl.follow_trade(t, *cache[t["coin"]], stamp, update=repo.update_zone_sweep_trade, label=zsw.LABEL, tag=_tag(t["setup_id"]),
                                   uids=viewers())
        except Exception:
            logger.exception("Zone-sweep-trade %s volgen is mislukt", t["signal_id"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from app import db
    db.init_db()
    asyncio.run(scan())
    asyncio.run(track())
    asyncio.run(follow())
