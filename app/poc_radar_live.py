"""POC-radar live: de regels van app/poc_radar.py op de echte candles, in de SMC-snelcyclus (market_scanner.scan_smc_fast) na de zone-radar.

Live op uitdrukkelijk verzoek van de CEO (2026-10-28), zonder labrun: altijd ongetest, Bewijs toont de score. Het systeem plaatst nooit een order.
Per cyclus:
  track:  wachtende kaarten op 5m-candles: geraakt wordt een gewoon signaal (trade_type 'poc_radar', buiten de hash-keten, journaal en melding);
          haalde de koers eerst het doel, dan vervalt de kaart stil; na poc_radar.TTL vervalt hij ook.
  follow: gevulde kaarten zonder doel: de meting en de referentie-uitgang van de zone-sweep (range_sweep_live.follow_trade). Met een doel beslist
          level_check op doel en stop.
  scan:   één keer per uur per coin (de eerste cyclus na het uurslot): alleen de nieuwe 5m-candles ophalen, de POC van nieuw gesloten dagen en
          weken één keer berekenen en bewaren (poc_levels), de aanrakingen bijwerken, en dan per coin en richting hooguit één kaart.
De snelcyclus is elke 5 minuten een nieuw proces, dus alles wat de motor onthoudt staat in de database (poc_levels, poc_scans)."""
import asyncio
import logging
from datetime import datetime
from typing import Optional

import pandas as pd

from app import config, focus, poc, push_notify, range_sweep_live as rsl, repo
from app import poc_radar as pr
from app import zone_radar as zr
from app.replay import rangesweep as rs
from app.replay.lab import add_indicators

logger = logging.getLogger("poc_radar_live")

TRADE_TYPE = pr.TRADE_TYPE
FILL_LIMIT = 300
PAGE = 1000                        # het maximum van Binance per aanroep
M15 = pd.Timedelta(minutes=15)
ALL_STATES = ("waiting", "filled", "doel_geraakt", "verlopen")


def viewers() -> list[int]:
    return [u["id"] for u in repo.list_users()] if config.POC_RADAR_PUBLIC else repo.list_ceo_user_ids()


def card_url(setup_id: int) -> str:
    return f"/smc#radar-poc-{setup_id}"


def _tag(setup_id: int) -> str:
    return f"poc-radar-{setup_id}"


def _level(row: dict) -> poc.PocLevel:
    return poc.PocLevel(row["period"], pd.Timestamp(row["period_start"]), float(row["price"]),
                        pd.Timestamp(row["touched_at"]) if row.get("touched_at") else None)


def stored_levels(coin: str, now: pd.Timestamp) -> list[poc.PocLevel]:
    """De bewaarde niveaus van periodes in het venster."""
    since = (now.floor("D") - poc.LOOKBACK).isoformat()
    return [_level(r) for r in repo.list_poc_levels(coin, since)]


def samenval(coin: str, price: float, now: Optional[datetime] = None) -> Optional[bool]:
    """Kenmerk POC-samenval voor een kaart van de zone-radar of de zone-sweep: ligt `price` binnen 0,3% van een naakte POC? None als er voor deze
    coin nog niets gemeten is (geen poc_scans-rij): dan is het niet gemeten, niet 'nee'. Een fout kost alleen het kenmerk, nooit de kaart."""
    try:
        if repo.get_poc_scan(coin) is None:
            return None
        return poc.near(price, stored_levels(coin, rsl._utc(now)))
    except Exception:
        logger.exception("POC-samenval voor %s niet te lezen", coin)
        return None


def _fetch_5m(coin: str, since: pd.Timestamp, now: pd.Timestamp) -> pd.DataFrame:
    """De 5m-candles vanaf `since` tot nu, in pagina's van PAGE. Hooguit zoveel pagina's als het venster nodig heeft."""
    from app import exchange
    parts, start = [], since
    for _ in range(int((now - since) / poc.BAR) // PAGE + 2):
        df = exchange.fetch_ohlcv(coin, timeframe="5m", limit=PAGE, since=int(start.timestamp() * 1000))
        df = df[df["timestamp"] < now]
        if df.empty:
            break
        parts.append(df)
        start = pd.Timestamp(df["timestamp"].iloc[-1]) + poc.BAR
        if len(df) < PAGE or start >= now:
            break
    if not parts:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    return pd.concat(parts, ignore_index=True).drop_duplicates("timestamp").reset_index(drop=True)


def due(coin: str, now: pd.Timestamp) -> bool:
    row = repo.get_poc_scan(coin)
    return row is None or pd.Timestamp(row["scanned_at"]).floor("h") < now.floor("h")


def refresh(coin: str, now: pd.Timestamp) -> tuple[list[poc.PocLevel], Optional[float]]:
    """Haalt alleen wat nieuw is, bewaart nieuwe niveaus en aanrakingen, en geeft de niveaus in het venster en de koers van nu (het slot van de
    5m-candle die nog vormt)."""
    known_rows = repo.list_poc_levels(coin, (now.floor("D") - poc.LOOKBACK).isoformat())
    known = {poc.key_of(r["period"], pd.Timestamp(r["period_start"])) for r in known_rows}
    scan = repo.get_poc_scan(coin)
    checked = pd.Timestamp(scan["checked_until"]) if scan else None
    candles = _fetch_5m(coin, poc.fetch_from(now, known, checked), now)
    closed = poc.closed_only(candles, now)
    fresh = poc.new_levels(candles, now, known)
    repo.add_poc_levels(coin, [{"period": lv.period, "period_start": lv.start.isoformat(), "price": lv.price,
                                "touched_at": lv.touched_at.isoformat() if lv.touched_at is not None else None} for lv in fresh])
    for lv in (_level(r) for r in known_rows if not r["touched_at"]):
        hit = poc.first_touch(lv, closed)
        if hit is not None:
            repo.touch_poc_level(coin, lv.period, lv.start.isoformat(), hit.isoformat())
    if len(closed):
        repo.set_poc_scan(coin, pd.Timestamp(closed["timestamp"].iloc[-1]).isoformat(), now.isoformat())
    price = float(candles["close"].iloc[-1]) if len(candles) else None
    return stored_levels(coin, now), price


async def _scan_coin(coin: str, now: pd.Timestamp, waiting: list[dict]) -> list[dict]:
    levels, price = await asyncio.to_thread(refresh, coin, now)
    if not price or not levels:
        return []
    zones: list[zr.ZoneLevel] = []
    atr = None
    for tf in zr.TFS:
        # Dezelfde ophaling als de zone-sweep (range_sweep_live.fetch_bars, FETCH_LIMIT): die draait in hetzelfde kwartier na het uurslot, dus voor
        # zijn coins komen deze candles uit de cache.
        bars = rsl._upto(await asyncio.to_thread(rsl.fetch_bars, coin, tf, rsl.FETCH_LIMIT), now)
        zones += zr.active_zones(bars, tf, now)
        if tf == "1h":
            closed = rs.closed_only(bars, now, tf)
            atr = float(add_indicators(closed)["atr"].iloc[-1]) if len(closed) > 14 else None
    if not atr or not atr > 0:
        return []
    busy = {c["direction"] for c in waiting if c["coin"] == coin}
    return [{**p, "coin": coin, "distance": abs(p["limit_price"] - price) / price} for p in pr.plans(levels, zones, price, atr)
            if p["direction"] not in busy]


async def _announce(card: dict) -> None:
    if not repo.mark_poc_radar_alert_sent(card["id"]):
        return
    title = push_notify.alert_title(card["coin"], card["direction"], f"{pr.LABEL} · ongetest")
    body = pr.new_card_body(card)
    for uid in viewers():
        user = repo.get_user(uid) or {}
        quiet = push_notify.is_quiet_now(user.get("quiet_hours_start"), user.get("quiet_hours_end"))
        try:
            await push_notify.send_kans_push(uid, card["coin"], card["direction"], title, body, card_url(card["id"]), silent=quiet, tag=_tag(card["id"]))
        except Exception:
            logger.exception("POC-radar-melding %s naar gebruiker %s is mislukt", card["id"], uid)


async def scan(now: Optional[datetime] = None) -> None:
    if not config.POC_RADAR_ENABLED or not focus.engine_on(TRADE_TYPE):
        repo.beat("poc_radar", "uit" if not config.POC_RADAR_ENABLED else focus.OFF_DETAIL)
        return
    stamp = rsl._utc(now)
    waiting = repo.list_poc_radar_setups()
    coins = [c["symbol"] for c in repo.list_coins()]
    found, checked, failed = [], 0, 0
    for coin in coins:
        if not due(coin, stamp):
            continue
        try:
            found += await _scan_coin(coin, stamp, waiting)
            checked += 1
        except Exception:
            failed += 1
            logger.exception("POC-radar voor %s is mislukt", coin)
    since = (stamp - pd.Timedelta(hours=24)).isoformat()
    for plan in sorted(found, key=lambda p: (p["distance"], p["coin"], p["direction"])):
        if repo.count_poc_radar_setups_since(since) >= config.POC_RADAR_MAX_PER_DAY:
            logger.info("POC-radar: dagcap van %s kaarten bereikt, %s %s wacht", config.POC_RADAR_MAX_PER_DAY, plan["coin"], plan["direction"])
            break
        row = {**{k: v for k, v in plan.items() if k != "distance"}, "expires_at": (stamp + pr.TTL).isoformat()}
        setup_id = repo.insert_poc_radar_setup(row, stamp.isoformat())
        if setup_id is None:
            continue
        logger.info("POC-radar %s %s: kaart %s, %s op %s, doel %s", plan["coin"], plan["direction"], setup_id, plan["level_key"], plan["level"],
                    plan["take_profit"])
        await _announce({**row, "id": setup_id})
    if checked or failed:
        repo.beat("poc_radar", f"{checked} van {len(coins)} coins bijgewerkt" + (f", {failed} mislukt" if failed else ""))


async def _fill(card: dict, filled_at: pd.Timestamp) -> None:
    entry = card["limit_price"]
    measure = None
    if card["take_profit"] is None:
        # Zonder doel meet de motor zelf op 15m, vanaf de 15m-candle waarin de vulling viel: die telt alleen tegen (range_sweep_live.follow_step).
        measure = {"entry": entry, "stop": card["stop_loss"], "filled_at": filled_at.isoformat(),
                   "checked_until": (filled_at.floor("15min") - M15).isoformat()}
    uids = viewers()
    signal_id = repo.fill_poc_radar_setup(card["id"], pr.signal_row(card, entry), uids, measure)
    if signal_id is None:
        return
    logger.info("POC-radar %s %s gevuld op %s, stop %s, doel %s", card["coin"], card["direction"], entry, card["stop_loss"], card["take_profit"])
    title = push_notify.alert_title(card["coin"], card["direction"], f"{pr.LABEL} gevuld")
    body = pr.fill_body(card, entry)
    for uid in uids:
        user = repo.get_user(uid) or {}
        quiet = push_notify.is_quiet_now(user.get("quiet_hours_start"), user.get("quiet_hours_end"))
        try:
            await push_notify.send_kans_push(uid, card["coin"], card["direction"], title, body, push_notify.signal_url(card["coin"], signal_id),
                                             silent=quiet, tag=_tag(card["id"]))
        except Exception:
            logger.exception("POC-radar-vulling %s naar gebruiker %s is mislukt", card["id"], uid)


async def track(now: Optional[datetime] = None) -> None:
    """Draait ook als de motor uit staat: wat al gemeld is, wordt afgemaakt."""
    stamp = rsl._utc(now)
    waiting = repo.list_poc_radar_setups()
    for coin in sorted({c["coin"] for c in waiting}):
        try:
            bars = rsl._upto(await asyncio.to_thread(rsl.fetch_bars, coin, "5m", FILL_LIMIT), stamp)
        except Exception:
            logger.exception("5m-candles voor %s niet op te halen, POC-kaarten blijven wachten", coin)
            continue
        for card in (c for c in waiting if c["coin"] == coin):
            try:
                # Ook de candle die nog vormt: een aanraking is een vulling, ook vóór het slot. Alleen candles die na de kaart openden.
                after = bars[bars["timestamp"] >= pd.Timestamp(card["created_at"])]
                what, at = pr.walk(card["direction"], card["limit_price"], card["take_profit"], after)
                if what == "filled":
                    await _fill(card, pd.Timestamp(at))
                elif what == "doel_geraakt":
                    repo.end_poc_radar_setup(card["id"], "doel_geraakt")
                elif stamp >= pd.Timestamp(card["expires_at"]):
                    repo.end_poc_radar_setup(card["id"], "verlopen")
            except Exception:
                logger.exception("POC-kaart %s voor %s is niet verwerkt", card["id"], coin)


async def follow(now: Optional[datetime] = None) -> None:
    stamp = rsl._utc(now)
    cache: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for t in repo.list_open_poc_radar_trades():
        try:
            if t["coin"] not in cache:
                cache[t["coin"]] = (await asyncio.to_thread(rsl.fetch_bars, t["coin"], "15m", rsl.FETCH_LIMIT),
                                    await asyncio.to_thread(rsl.fetch_bars, t["coin"], "1h", rsl.FETCH_LIMIT))
            await rsl.follow_trade(t, *cache[t["coin"]], stamp, update=repo.update_poc_radar_trade, label=pr.LABEL, tag=_tag(t["setup_id"]),
                                   uids=viewers())
        except Exception:
            logger.exception("POC-radar-trade %s volgen is mislukt", t["signal_id"])


async def run(now: Optional[datetime] = None) -> None:
    """Eerst volgen wat er is, dan zoeken: een vulling in deze cyclus telt nog voordat er een nieuwe kaart bij komt."""
    for step in (track, follow, scan):
        try:
            await step(now)
        except Exception:
            logger.exception("POC-radar (%s) is mislukt", step.__name__)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from app import db
    db.init_db()
    asyncio.run(run())
