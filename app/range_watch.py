"""Range-watch: welke coins liggen nu in een geldige range (zelfde detector als het lab, app/replay/rangesweep.py), zodat je weet waar een sweep of
retest kan komen. Informatie, geen kans: geen richting, geen order, altijd ongetest. Eigen budget van RANGE_WATCH_MAX_PER_DAY stille pushes per
gebruiker per 24 uur, los van het kansbudget, zodat een setup nooit wegvalt omdat een watch dat opmaakte. Alleen de CEO zolang RANGE_SWEEP_PUBLIC uit
staat. Regels: docs/superpowers/plans/2026-10-16-range-sweep-strategie.md, taak 14.

Elke melding gaat één keer per range af: de rij in range_watches (gevonden) of de randmarkering (mark_range_watch_edge) wordt gezet vóór het
versturen, net als bij price_alerts. Een mislukte verzending komt dus niet terug, een herstart of dubbele cyclus meldt nooit dubbel."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from app import config, db, push_notify, push_policy, repo
from app.replay import rangesweep as rs, trendlab as tl

logger = logging.getLogger("range_watch")

EDGE_NEAR_ATR = 0.25
# Op 30m en 1u ontstaan tientallen ranges per dag; alleen de grotere geven een push "gevonden", de rest staat op de pagina.
PUSH_TFS = ("2h", "4h")
COINS = tl.LAB_COINS
TF_LABEL = {"30m": "30m", "1h": "1u", "2h": "2u", "4h": "4u"}
WATCH_URL = "/structuur#tab-ranges"
# Een range verandert alleen bij een gesloten candle van 30m of groter, en die sluiten op het hele en halve uur. Ranges zoeken we daarom alleen in
# de eerste minuten daarna (ruim boven de 5 minuten van de cyclus, zodat een gemiste cyclus niets kost); de koers bij de rand volgen we elke cyclus.
DETECT_WINDOW_MIN = 10
# Na een prik krijgt dezelfde range een ander eerste zwaaipunt met bijna dezelfde randen (zie de cooldown in rangesweep._sweep_setups): binnen
# deze afstand in ATR is het dezelfde range en geen nieuwe vondst.
SAME_RANGE_ATR = rs.CLUSTER_ATR
FETCH_LIMIT = 400        # 200 candles van 30m en 2u, genoeg voor een lookback van 120 plus de ATR; 1u en 4u idem


def current_ranges(frames: dict, now: pd.Timestamp) -> dict[str, Optional[rs.Range]]:
    """De range per timeframe op het laatste gesloten slot. De frames mogen candles bevatten die nog vormen: die vallen hier af."""
    out = {}
    for tf in rs.TFS:
        closed = rs.closed_only(frames[tf], now, tf)
        out[tf] = rs.range_series(closed, tf)[1][-1] if len(closed) else None
    return out


def edge_events(watch: dict, price: float) -> list[str]:
    near = EDGE_NEAR_ATR * watch["atr"]
    out = []
    if not watch.get("edge_high_at") and price >= watch["range_high"] - near:
        out.append("rand_high")
    if not watch.get("edge_low_at") and price <= watch["range_low"] + near:
        out.append("rand_low")
    return out


def events(watch: dict, price: float, rng_now: Optional[rs.Range]) -> list[str]:
    """rng_now: de range op dit moment die bij deze watch hoort, None als die er niet meer is."""
    if rng_now is None:
        return ["einde"]
    return edge_events(watch, price)


def should_push(kind: str, tf: str, sent_24h: int, budget: int) -> tuple[bool, str]:
    if kind == "gevonden" and tf not in PUSH_TFS:
        return False, "Ranges op 30m en 1u staan alleen op de pagina."
    # Plan: de rand-push geldt voor alle timeframes. Maar 30m en 1u leveren er tientallen per dag; zij laten de laatste plek vrij, anders is het
    # budget op voordat een 2u- of 4u-range gevonden wordt.
    if budget and tf not in PUSH_TFS and sent_24h >= budget - 1 and budget > 1:
        return False, f"Range-watch: budget van {budget} per 24 uur, de laatste plek is voor ranges op 2u en 4u, daarom geen push."
    if budget and sent_24h >= budget:
        return False, f"Range-watch: budget van {budget} per 24 uur bereikt, daarom geen push."
    return True, ""


def watch_body(coin: str, tf: str, rng: rs.Range, price: float) -> str:
    return "\n".join([f"Range {TF_LABEL[tf]}: {push_notify.fmt_price(rng.low)} tot {push_notify.fmt_price(rng.high)}",
                      f"{rng.high_touches} keer boven, {rng.low_touches} keer onder aangeraakt. Koers {push_notify.fmt_price(price)}.",
                      "Aan de randen kan een retest van een zone of een sweep komen. Nog ongetest, geen advies."])


def viewers() -> list[int]:
    return [u["id"] for u in repo.list_users()] if config.RANGE_SWEEP_PUBLIC else repo.list_ceo_user_ids()


async def _warn(watch_id: int, tf: str, kind: str, title: str, body: str, now: datetime) -> None:
    if kind == "gevonden" and tf not in PUSH_TFS:
        return
    since = (now - timedelta(hours=24)).isoformat()
    for uid in viewers():
        try:
            ok, why = should_push(kind, tf, repo.count_range_watch_pushes(uid, since), config.RANGE_WATCH_MAX_PER_DAY)
            if ok and push_policy.pause_minutes_left((repo.get_user(uid) or {}).get("push_paused_until"), now):
                # Zoals send_kans_push: wie pauzeert houdt na de pauze zijn volle budget, dus deze telt niet mee.
                ok, why = False, "Meldingen stonden op pauze, daarom geen push."
            repo.log_range_watch_push(uid, watch_id, kind, now.isoformat(), ok)
            if ok:
                await push_notify.send_push(uid, title, body, WATCH_URL, silent=True, tag=f"range-{watch_id}")
            else:
                repo.create_notification(uid, "range", title, f"{body}\n{why}", WATCH_URL)
        except Exception:
            logger.exception("Range-watchmelding %s naar gebruiker %s is mislukt", watch_id, uid)


def _same_range(a: dict, rng: rs.Range) -> bool:
    tol = SAME_RANGE_ATR * rng.atr
    return abs(a["range_high"] - rng.high) <= tol and abs(a["range_low"] - rng.low) <= tol


def _end(watch: dict, price: float) -> None:
    out = (price > watch["range_high"] + rs.CONTAIN_ATR * watch["atr"]) or (price < watch["range_low"] - rs.CONTAIN_ATR * watch["atr"])
    repo.set_range_watch_state(watch["id"], "gebroken" if out else "verlopen")


async def _edges(watch: dict, price: float, rng: Optional[rs.Range], coin: str, now: datetime, silent_seed: bool = False) -> None:
    for ev in edge_events(watch, price):
        if not repo.mark_range_watch_edge(watch["id"], ev.split("_")[1]) or silent_seed:
            continue
        edge = "bovenrand" if ev == "rand_high" else "onderrand"
        shown = rng or rs.Range(watch["tf"], pd.Timestamp(now), watch["range_high"], watch["range_low"], 0, 0, 0.0, 0.0, pd.Timestamp(watch["first_at"]), watch["atr"])
        await _warn(watch["id"], watch["tf"], ev, f"{coin} · Koers bij de {edge} ({TF_LABEL[watch['tf']]})", watch_body(coin, watch["tf"], shown, price), now)


async def _detect(coin: str, now: datetime) -> None:
    from app import exchange
    ts = pd.Timestamp(now)
    parts = []
    for tf in ("15m", "1h", "4h"):
        bars = await asyncio.to_thread(exchange.fetch_ohlcv, coin, timeframe=tf, limit=FETCH_LIMIT)
        parts.append(rs.closed_only(bars, ts, tf))
    cur = current_ranges(rs.build_frames(*parts), ts)
    price = await asyncio.to_thread(exchange.fetch_last_price, coin)
    everything = repo.list_range_watches(("actief", "gesweept", "gebroken", "verlopen"))
    # Een nieuwe coin start stil: anders komt elke bestaande range tegelijk als "gevonden" (en bij het aanzetten 20 coins tegelijk). De markering staat
    # in de instellingen, niet af te leiden uit de rijen: een coin zonder range zou anders bij zijn eerste echte range alsnog stil blijven.
    seeded_key = f"range_watch_seeded:{coin}"
    first_sight = db.get_setting(seeded_key) != "1"
    active = [w for w in everything if w["coin"] == coin and w["state"] == "actief"]
    for tf, r in cur.items():
        if r is None:
            continue
        wid, new = repo.upsert_range_watch({"coin": coin, "tf": tf, "range_high": r.high, "range_low": r.low, "first_at": r.first_at.isoformat(),
                                            "found_at": r.known_at.isoformat(), "atr": r.atr})
        if not new:
            continue
        prev = [w for w in active if w["tf"] == tf and w["id"] != wid and _same_range(w, r)]
        for w in prev:
            for edge in ("high", "low"):
                if w[f"edge_{edge}_at"]:
                    repo.mark_range_watch_edge(wid, edge)
            repo.set_range_watch_state(w["id"], "verlopen")
        if not prev and not first_sight:
            await _warn(wid, tf, "gevonden", f"{coin} · Range {TF_LABEL[tf]} gevonden", watch_body(coin, tf, r, price), now)
    for w in repo.list_range_watches(("actief",)):
        if w["coin"] != coin:
            continue
        r = cur.get(w["tf"])
        same = r if r is not None and r.first_at.isoformat() == w["first_at"] else None
        if same is None:
            _end(w, price)
        else:
            await _edges(w, price, same, coin, now, silent_seed=first_sight)
    if first_sight:
        db.set_setting(seeded_key, "1")


async def _follow(coin: str, watches: list[dict], now: datetime) -> None:
    from app import exchange
    price = await asyncio.to_thread(exchange.fetch_last_price, coin)
    for w in watches:
        await _edges(w, price, None, coin, now)


async def run(now: Optional[datetime] = None) -> None:
    """5-minutencyclus naast rule_live.scan(). Uit tenzij RANGE_WATCH_ENABLED."""
    if not config.RANGE_WATCH_ENABLED:
        return
    now = now or datetime.now(timezone.utc)
    now = now if now.tzinfo else now.replace(tzinfo=timezone.utc)
    detect = now.minute % 30 < DETECT_WINDOW_MIN
    active = repo.list_range_watches(("actief",))
    for coin in COINS:
        try:
            if detect:
                await _detect(coin, now)
            elif any(w["coin"] == coin for w in active):
                await _follow(coin, [w for w in active if w["coin"] == coin], now)
        except Exception:
            logger.exception("Range-watch voor %s is mislukt", coin)
    repo.beat("range_watch", f"{len(COINS)} coins gecontroleerd")
