"""Proefmotor range sweep: dezelfde detector als het lab (app/replay/rangesweep.py) op gesloten candles, met de variant en stop die het lab koos
(rule_status 'range_sweep_stop'). Een setup wacht met een limiet op de zone; vult de limiet, dan wordt het een signaal (trade_type 'range_sweep')
zonder doel. Eerlijk over wat dit is: ongetest, alleen voor de CEO tot hij anders beslist, en een R op Bewijs die gemeten is bij een referentie-uitgang
(meelopende stop 3 ATR op 1u), niet bij jouw doel. Liquidaties hebben geen historie: hier staan ze als extra ✓/✗, buiten de score en buiten het lab.

Het systeem plaatst nooit een order. Alles hier is een melding met een plan; de limiet en de stop zet jij zelf.

Drie stappen, elk elke cyclus van 5 minuten (market_scanner):
  scan:   nieuwe setups, alleen als het lab de stopkwaliteit goedkeurde (de strenge toets op een voordeel is geen voorwaarde voor een proef).
  track:  wachtende limieten volgen: gevuld (signaal en melding), of vervallen (24 uur, weggelopen, stop voor vulling).
  follow: gevulde trades meten tot de stop of 7 dagen, en de referentie-uitgang (de R die Bewijs telt).
Elke melding gaat één keer af: de staat of de meting wordt vastgelegd vóór het versturen, dus een herstart of een dubbele cyclus meldt niets dubbel."""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

from app import chance_checks, config, push_notify, push_policy, range_watch, repo, structure_live
from app.replay import rangesweep as rs, rangesweep_lab as rl, stopquality as sq, trendlab as tl
from app.replay.lab import add_indicators

logger = logging.getLogger("range_sweep_live")

TRADE_TYPE = "range_sweep"
STOP_KEY, EDGE_KEY = "range_sweep_stop", "range_sweep"
COINS = tl.LAB_COINS
REF_HORIZON = pd.Timedelta(days=7)
TTL = pd.Timedelta(hours=24)
# Een setup ontstaat bij het slot van een candle; de motor draait elke 5 minuten (en alleen kort na een 15m-slot), dus 20 minuten dekt een gemiste cyclus
# zonder dat een oude setup uit het venster van 1000 candles nog eens als nieuw verschijnt.
FRESH = pd.Timedelta(minutes=20)
LIQ_FACTOR = 2.0
FETCH_LIMIT = 1000
TRACK_LIMIT = 400
CHART_BARS = 80
M15 = pd.Timedelta(minutes=15)
TF_LABEL = {"30m": "30m", "1h": "1u", "2h": "2u", "4h": "4u"}
FAMILY_LABEL = {"zone": "Zone-retest", "sweep": "Range sweep"}
GRADE_WORD = {"A": "sterk", "B": "redelijk", "C": "zwak"}
ALL_STATES = ("waiting", "niet_gemeld", "filled", "verlopen", "weggelopen", "stop_voor_vulling")
CANCEL_STATE = {"stop voor vulling": "stop_voor_vulling", "weggelopen": "weggelopen", "verlopen": "verlopen"}
CANCEL_TEXT = {"verlopen": "De limiet is niet binnen 24 uur geraakt: de order is verlopen. Geen trade, er is niets te doen.",
               "weggelopen": "De koers raakte het midden van de range zonder de limiet te raken. Geen trade, er is niets te doen.",
               "stop_voor_vulling": "De koers opende voorbij de stop zonder de limiet te raken. Geen trade, er is niets te doen."}
_R_KEYS = [f"reached_{k}r_at" for k in sq.R_LEVELS]
_MEASURE_KEYS = ["mae_r", "mfe_r", "stop_hit_at", "ref_stop", "ref_extreme", "ref_r", "ref_closed_at", "checked_until"] + _R_KEYS


def _utc(now) -> pd.Timestamp:
    ts = pd.Timestamp(now or datetime.now(timezone.utc))
    return ts.tz_localize("UTC") if ts.tzinfo is None else ts.tz_convert("UTC")


def _jsonable(o):
    return o.item() if hasattr(o, "item") else str(o)


def fmt_r(r: float) -> str:
    return f"{r:+.2f}".replace(".", ",") + "R"


def live_variant(lab_row: Optional[dict]) -> Optional[tuple[rl.RSVariant, str]]:
    """(variant, stopnaam) uit de rij van de toets op stopkwaliteit, of None. repo.get_rule_lab geeft de inhoud onder "summary"; "lab_json" blijft
    geldig voor een rij zoals de database hem bewaart. Een stop die de variant nooit toetste (of een onbekende variant) is een kapotte rij: geen motor."""
    if not lab_row or not lab_row.get("lab_passes"):
        return None
    data = lab_row.get("summary") or lab_row.get("lab_json") or {}
    data = json.loads(data) if isinstance(data, str) else data
    v = next((x for x in rl.VARIANTS if x.name == data.get("variant")), None)
    if v is None:
        return None
    stop = data.get("stop_name") or v.stops[0]
    return (v, stop) if stop in v.stops else None


def fresh_setups(frames: dict, v: rl.RSVariant, now: pd.Timestamp) -> list[dict]:
    """Setups van dit moment. Elk frame gaat hier nogmaals door closed_only: een aanroeper die een vormende candle meegeeft, mag de detectie niet
    laten zien wat bij het sluiten verdwijnt."""
    closed = {tf: rs.closed_only(df, now, tf) for tf, df in frames.items()}
    setups, _ = rs.find_setups(closed, v.tf, v.family, v.entry, v.confirm, v.htf)
    return [s for s in setups if now - FRESH < s["placed_at"] <= now]


def liquidation_check(direction: str, buckets: list[dict], t0, t1, baseline_buckets: list[dict]) -> dict:
    """Een prik omhoog liquideert shorts (short_usd), omlaag longs. ✓ als de som in het venster per uur minstens LIQ_FACTOR maal de mediaan per uur
    van de week ervoor is. Geen data is geen ✓: de stroom kan uit hebben gestaan."""
    col = "short_usd" if direction == "short" else "long_usd"
    t0, t1 = pd.Timestamp(t0), pd.Timestamp(t1)
    usd = float(sum(b[col] for b in buckets if t0 <= pd.Timestamp(b["bucket"]) < t1))
    hours = max(1.0, (t1 - t0) / pd.Timedelta(hours=1))
    per_hour: dict = {}
    for b in baseline_buckets:
        h = pd.Timestamp(b["bucket"]).floor("h")
        per_hour[h] = per_hour.get(h, 0.0) + b[col]
    base = float(np.median(list(per_hour.values()))) if per_hour else 0.0
    return {"usd": usd, "baseline": base, "ok": bool(usd > 0 and base > 0 and usd / hours >= LIQ_FACTOR * base)}


def alert_body(row: dict, price: Optional[float]) -> str:
    legs = json.loads(row["legs"])
    mid = (row["range_high"] + row["range_low"]) / 2
    opp = row["range_low"] if row["direction"] == "short" else row["range_high"]
    liq = json.loads(row.get("liq_json") or "{}")
    lim = " · ".join(f"Limiet {push_notify.fmt_price(p)}" + (f" ({w * 100:.0f}%)" if len(legs) > 1 else "") for w, p in legs)
    planned = sum(w * p for w, p in legs) / sum(w for w, _ in legs)
    lines = [lim, f"Stop {push_notify.fmt_price(row['stop'])} ({abs(planned - row['stop']) / planned * 100:.2f}%) · doel kies je zelf"]
    if row.get("zone_low") is not None and row.get("zone_high") is not None:
        lines.append(f"Zone {push_notify.fmt_price(row['zone_low'])} tot {push_notify.fmt_price(row['zone_high'])}"
                     + (f" · koers nu {push_notify.fmt_price(price)}" if price else ""))
    elif price:
        lines.append(f"Koers nu {push_notify.fmt_price(price)}")
    grade = f" ({GRADE_WORD[row['grade']]})" if row.get("grade") in GRADE_WORD else ""
    lines += [f"Referentie, geen doel: Midden {push_notify.fmt_price(mid)} · Overkant {push_notify.fmt_price(opp)}",
              f"{FAMILY_LABEL[row['family']]} {TF_LABEL[row['range_tf']]}, score {row['score']:.0f} van 100{grade}" + (" · liquidaties ✓" if liq.get("ok") else ""),
              "Ongetest: een proef, Bewijs toont de stopkwaliteit.", push_notify.OPEN_PLAN_LINE]
    return "\n".join(lines)


def _filled_legs(trade: dict) -> list[list]:
    raw = trade.get("legs_filled")
    return (json.loads(raw) if isinstance(raw, str) else raw) or []


def follow_step(trade: dict, candles: pd.DataFrame, atr15: np.ndarray) -> dict:
    """Werkt de meting en de referentie bij met de candles na checked_until. Zelfde regels als stopquality.measure: een candle die de stop en een
    R-niveau raakt telt als stop, een gat door de stop vult op de open, de referentie-stop schuift alleen de goede kant op. In de vulcandle (bij een
    split: tot en met de laatste vulling) telt alleen het nadeel, want de volgorde binnen de candle is onbekend en de positie is nog niet compleet."""
    short = trade["direction"] == "short"
    entry, stop = trade["entry"], trade["stop"]
    risk = abs(entry - stop)
    out = {k: trade[k] for k in _MEASURE_KEYS}
    filled_at, checked = pd.Timestamp(trade["filled_at"]), pd.Timestamp(trade["checked_until"])
    full_at = max([pd.Timestamp(leg[2]) for leg in _filled_legs(trade)], default=filled_at)
    for k, c in enumerate(candles.itertuples()):
        if c.timestamp <= checked or out["stop_hit_at"] or c.timestamp >= filled_at + REF_HORIZON:
            continue
        at = c.timestamp.isoformat()
        incomplete = c.timestamp <= full_at
        if not incomplete and out["ref_r"] is None and ((c.high >= out["ref_stop"]) if short else (c.low <= out["ref_stop"])):
            fill = max(c.open, out["ref_stop"]) if short else min(c.open, out["ref_stop"])
            out["ref_r"], out["ref_closed_at"] = ((entry - fill) if short else (fill - entry)) / risk, at
        if (c.high >= stop) if short else (c.low <= stop):
            fill = max(c.open, stop) if short else min(c.open, stop)
            out["stop_hit_at"], out["checked_until"] = at, at
            out["mae_r"] = max(out["mae_r"], ((fill - entry) if short else (entry - fill)) / risk)
            if out["ref_r"] is None:
                out["ref_r"], out["ref_closed_at"] = ((entry - fill) if short else (fill - entry)) / risk, at
            continue
        out["mae_r"] = max(out["mae_r"], ((c.high - entry) if short else (entry - c.low)) / risk)
        out["checked_until"] = at
        if incomplete:
            continue
        fav = ((entry - c.low) if short else (c.high - entry)) / risk
        out["mfe_r"] = max(out["mfe_r"], fav)
        for r in sq.R_LEVELS:
            if fav >= r and not out[f"reached_{r}r_at"]:
                out[f"reached_{r}r_at"] = at
        if out["ref_r"] is None and np.isfinite(atr15[k]):
            ext = min(out["ref_extreme"], c.low) if short else max(out["ref_extreme"], c.high)
            trail = ext + sq.TRAIL_K * atr15[k] if short else ext - sq.TRAIL_K * atr15[k]
            out["ref_extreme"], out["ref_stop"] = ext, (min(out["ref_stop"], trail) if short else max(out["ref_stop"], trail))
    return out


def viewers() -> list[int]:
    return range_watch.viewers()


def _upto(df: pd.DataFrame, now: pd.Timestamp) -> pd.DataFrame:
    """Candles die op `now` al open zijn. De beurs geeft nooit meer terug; de naad in de tests wel, en wat later komt mag nooit meetellen."""
    return df[df["timestamp"] < now].reset_index(drop=True)


async def _frames(coin: str, now: pd.Timestamp) -> dict:
    parts = []
    for tf in ("15m", "1h", "4h"):
        bars = await asyncio.to_thread(fetch_bars, coin, tf, FETCH_LIMIT)
        parts.append(rs.closed_only(bars, now, tf))
    return rs.build_frames(*parts)


def fetch_bars(coin: str, timeframe: str, limit: int) -> pd.DataFrame:
    from app import exchange
    return exchange.fetch_ohlcv(coin, timeframe=timeframe, limit=limit)


async def _tell(uid: int, title: str, body: str, url: str, tag: str) -> None:
    """Een gebeurtenis bij een bestaande kans (gevuld, stop geraakt, meting klaar): altijd een melding, buiten het kansbudget. send_push slaat een pauze
    stilletjes over; dan blijft de melding hier op de pagina staan, anders zou een gevulde limiet spoorloos zijn."""
    user = repo.get_user(uid) or {}
    if push_policy.pause_minutes_left(user.get("push_paused_until"), datetime.now(timezone.utc)):
        repo.create_notification(uid, "kans", title, f"{body}\nMeldingen stonden op pauze, daarom geen push.", url)
        return
    quiet = push_notify.is_quiet_now(user.get("quiet_hours_start"), user.get("quiet_hours_end"))
    await push_notify.send_push(uid, title, body, url, silent=quiet, tag=tag)


async def _tell_all(title: str, body: str, url: str, tag: str) -> None:
    for uid in viewers():
        try:
            await _tell(uid, title, body, url, tag)
        except Exception:
            logger.exception("Melding %s naar gebruiker %s is mislukt", tag, uid)


def _tag(setup_id: int) -> str:
    return f"range-sweep-{setup_id}"


def _setup_url(setup_id: int) -> str:
    return f"/structuur#{_tag(setup_id)}"


def _plan(frames: dict, v: rl.RSVariant, s: dict, stop: float) -> dict:
    """Wat de grafiek nodig heeft: de laatste candles van de range-timeframe en de zones die op dit moment actief zijn."""
    b = add_indicators(frames[v.tf]).reset_index(drop=True)
    idx = len(b) - 1
    zones = [{"low": z.low, "high": z.high, "from": b["timestamp"].iloc[z.ob_idx].isoformat(), "kind": z.kind}
             for z in rs.find_zones(b) if rs.zone_active(z, idx)]
    candles = [[c.timestamp.isoformat(), c.open, c.high, c.low, c.close] for c in b.tail(CHART_BARS).itertuples()]
    short = s["direction"] == "short"
    return {"tf": v.tf, "candles": candles, "zones": zones, "stop": stop, "mid": (s["range_high"] + s["range_low"]) / 2,
            "opp": s["range_low"] if short else s["range_high"]}


def _liquidations(coin: str, s: dict) -> dict:
    """Bij een sweep het venster van de prik, bij een zone-retest het uur vóór het plaatsen. Altijd ongetest: er is geen historie om tegen te meten."""
    t0, t1 = (s["sweep_at"], s["return_at"]) if s["family"] == "sweep" else (s["placed_at"] - pd.Timedelta(hours=1), s["placed_at"])
    rows = repo.list_liquidations(coin, (t0 - pd.Timedelta(days=7)).isoformat())
    base = [b for b in rows if pd.Timestamp(b["bucket"]) < t0]
    return liquidation_check(s["direction"], rows, t0, t1, base)


def _mark_watch(coin: str, s: dict) -> None:
    for w in repo.list_range_watches(("actief",)):
        if w["coin"] == coin and w["tf"] == s["tf"] and w["first_at"] == s["range_first_at"].isoformat():
            repo.set_range_watch_state(w["id"], "gesweept")


async def _announce(setup_id: int, row: dict, price: float) -> None:
    """Sterk (A) luid, redelijk (B) stil, zwak (C) pas een melding als de limiet vult. Nieuwe kans: de pushregels (budget, tegenstrijdig, pauze)."""
    if row["grade"] == "C":
        return
    title = push_notify.alert_title(row["coin"], row["direction"], f"{FAMILY_LABEL[row['family']]} wacht")
    body = alert_body(row, price)
    for uid in viewers():
        user = repo.get_user(uid) or {}
        quiet = push_notify.is_quiet_now(user.get("quiet_hours_start"), user.get("quiet_hours_end"))
        try:
            await push_notify.send_kans_push(uid, row["coin"], row["direction"], title, body, _setup_url(setup_id),
                                             silent=quiet if row["grade"] == "A" else True, tag=_tag(setup_id))
        except Exception:
            logger.exception("Setupmelding %s naar gebruiker %s is mislukt", setup_id, uid)


async def _register(coin: str, v: rl.RSVariant, stop_name: str, s: dict, frames: dict, now: pd.Timestamp, known: set) -> None:
    key = (coin, s["direction"], v.name, s["zone_at"].isoformat())
    if key in known:
        return
    stop = rs.final_stop(s, stop_name)
    reason, score = chance_checks.weighted_finish(chance_checks.range_sweep_checks(s["features"], v.tf))
    grade = chance_checks.grade_of(score)
    recent = repo.list_range_sweep_setups(("waiting", "filled"), since_iso=(now - TTL).isoformat())
    capped = len(recent) >= config.RANGE_SWEEP_MAX_PER_DAY
    row = {"coin": coin, "direction": s["direction"], "variant": v.name, "family": s["family"], "stop_name": stop_name, "range_tf": v.tf,
           "range_high": s["range_high"], "range_low": s["range_low"], "range_first_at": s["range_first_at"].isoformat(),
           "zone_low": s["zone_low"], "zone_high": s["zone_high"], "zone_at": s["zone_at"].isoformat(),
           "sweep_at": s["sweep_at"].isoformat() if s["sweep_at"] is not None else None, "extreme": s["extreme"],
           "placed_at": s["placed_at"].isoformat(), "legs": json.dumps([[w, p] for w, p in s["legs"]]), "stop": stop, "atr_t": s["atr_t"],
           "score": score, "grade": grade, "reason": reason, "features": json.dumps(s["features"], default=_jsonable),
           "liq_json": json.dumps(_liquidations(coin, s), default=_jsonable), "expires_at": (s["placed_at"] + TTL).isoformat(),
           "plan": json.dumps(_plan(frames, v, s, stop), default=_jsonable)}
    setup_id = repo.insert_range_sweep_setup(row)
    if setup_id is None:
        return
    known.add(key)
    # Een setup boven de dagcap blijft op de pagina staan en wordt gevolgd, maar er gaat niets uit.
    if capped:
        repo.set_range_sweep_setup_state(setup_id, "niet_gemeld")
    if s["family"] == "sweep":
        _mark_watch(coin, {**s, "tf": v.tf})
    logger.info("Range sweep %s %s %s: %s %s (%s)", coin, s["direction"], v.name, grade, "niet gemeld" if capped else "gemeld", score)
    if not capped:
        await _announce(setup_id, row, s["ref_price"])


async def scan(now: Optional[datetime] = None) -> None:
    """Nieuwe setups. Spec: geen nieuwe setups zonder geslaagde toets op stopkwaliteit; open trades volgt `follow` gewoon verder."""
    if not config.RANGE_SWEEP_ENABLED:
        return
    stamp = _utc(now)
    if stamp.minute % 15 >= 10:
        return
    choice = live_variant(repo.get_rule_lab(STOP_KEY))
    if choice is None:
        logger.info("Range sweep: geen geslaagde toets op stopkwaliteit (scripts/strategy_lab.py --opslaan), geen nieuwe setups")
        return
    v, stop_name = choice
    if structure_live.should_disable(repo.list_type_results(TRADE_TYPE, config.RANGE_SWEEP_MAX_NEGATIVE), config.RANGE_SWEEP_MAX_NEGATIVE):
        repo.notify_engine_disabled("Range sweep", f"De laatste {config.RANGE_SWEEP_MAX_NEGATIVE} afgeronde proeftrades zijn samen negatief bij de referentie-uitgang. Zie Bewijs.")
        return
    # Dezelfde zone na een herstart onder een iets ander plaatsingsmoment is dezelfde setup: de unieke sleutel van de tabel vangt alleen een identiek moment.
    known = {(r["coin"], r["direction"], r["variant"], r["zone_at"])
             for r in repo.list_range_sweep_setups(ALL_STATES, since_iso=(stamp - 3 * TTL).isoformat())}
    for coin in COINS:
        try:
            frames = await _frames(coin, stamp)
            for s in fresh_setups(frames, v, stamp):
                await _register(coin, v, stop_name, s, frames, stamp, known)
        except Exception:
            logger.exception("Range sweep voor %s is mislukt", coin)
    repo.beat("range_sweep", f"{len(COINS)} coins gecontroleerd")


def _legs_of(setup: dict) -> list[tuple[float, float]]:
    return [(float(w), float(p)) for w, p in json.loads(setup["legs"])]


def _entry_of(filled: list) -> float:
    weight = sum(leg[0] for leg in filled)
    return sum(leg[0] * leg[1] for leg in filled) / weight


async def _cancel(setup: dict, state: str) -> None:
    announced = setup["state"] == "waiting" and setup["grade"] in ("A", "B")
    repo.set_range_sweep_setup_state(setup["id"], state)
    logger.info("Range sweep %s %s: %s", setup["coin"], setup["direction"], state)
    if not announced:
        return
    title = push_notify.alert_title(setup["coin"], setup["direction"], f"{FAMILY_LABEL[setup['family']]} vervallen")
    for uid in viewers():
        repo.create_notification(uid, "kans", title, CANCEL_TEXT[state], _setup_url(setup["id"]))


async def _fill(setup: dict, filled: list[list], now: pd.Timestamp) -> None:
    entry = _entry_of(filled)
    first_at = min(pd.Timestamp(leg[2]) for leg in filled)
    fam = FAMILY_LABEL[setup["family"]]
    # Geen schakel in de openbare ketting: /keten is zonder login en de proef is alleen voor de CEO.
    signal_id = repo.insert_signal({
        "message_id": None, "coin": setup["coin"], "direction": setup["direction"], "category": "day_trading", "trade_type": TRADE_TYPE,
        "pattern_name": setup["variant"], "price": entry, "stop_loss": setup["stop"], "take_profit": None, "confidence": f"{fam} {setup['grade']}",
        "reason": setup["reason"], "pass_pct": setup["score"], "technical_confirmed": 1, "hard_gates_ok": 1, "is_practice": 0,
        "plain_explanation": f"{fam} {TF_LABEL[setup['range_tf']]}: limiet gevuld, stop voorbij de zone, doel kies je zelf."}, chain_it=False)
    # Eerst de staat, dan de rest: lukt het vervolg niet, dan volgt er geen tweede signaal bij de volgende cyclus.
    repo.set_range_sweep_setup_state(setup["id"], "filled", signal_id)
    repo.insert_range_sweep_trade(signal_id, setup["id"], json.dumps(filled), entry, setup["stop"], first_at.isoformat())
    repo.update_range_sweep_trade(signal_id, checked_until=(first_at - M15).isoformat())
    for uid in viewers():
        repo.create_journal_entry(signal_id, uid, None)
    mid = (setup["range_high"] + setup["range_low"]) / 2
    opp = setup["range_low"] if setup["direction"] == "short" else setup["range_high"]
    body = "\n".join([f"Limiet geraakt op {push_notify.fmt_price(entry)}, stop {push_notify.fmt_price(setup['stop'])}, doel kies je zelf",
                      f"Referentie, geen doel: Midden {push_notify.fmt_price(mid)} · Overkant {push_notify.fmt_price(opp)}",
                      "Stond jouw eigen limiet er, dan is die nu gevuld. Het systeem plaatst zelf nooit een order.", "Ongetest: een proef.", push_notify.OPEN_PLAN_LINE])
    await _tell_all(push_notify.alert_title(setup["coin"], setup["direction"], f"{fam} gevuld"), body, push_notify.signal_url(setup["coin"], signal_id), _tag(setup["id"]))
    logger.info("Range sweep %s %s gevuld op %s, stop %s", setup["coin"], setup["direction"], entry, setup["stop"])


def _more_legs(setup: dict, trade: dict, filled: list[list]) -> None:
    """De tweede order van een split vulde later. Het lab meet pas vanaf de laatste vulling, dus de meting begint daar opnieuw (de stop gold al eerder)."""
    entry = _entry_of(filled)
    last_at = max(pd.Timestamp(leg[2]) for leg in filled)
    repo.update_range_sweep_trade(trade["signal_id"], legs_filled=json.dumps(filled), entry=entry, ref_stop=trade["stop"], ref_extreme=entry, mfe_r=0.0,
                                  checked_until=(last_at - M15).isoformat(), **{k: None for k in _R_KEYS})
    repo.set_signal_price(trade["signal_id"], entry)
    logger.info("Range sweep %s: volgende order gevuld, instap nu %s", setup["coin"], entry)


async def _track_one(setup: dict, trade: Optional[dict], b15: pd.DataFrame, now: pd.Timestamp) -> None:
    placed, expires = pd.Timestamp(setup["placed_at"]), pd.Timestamp(setup["expires_at"])
    c = _upto(b15, now)
    c = c[c["timestamp"] >= placed].reset_index(drop=True)
    mid = (setup["range_high"] + setup["range_low"]) / 2
    res = sq.simulate_fills(setup["direction"], _legs_of(setup), setup["stop"], mid, c, 0)
    filled = [[w, p, c["timestamp"].iloc[m].isoformat()] for w, p, m in res["filled"]]
    if trade is not None:
        # Alleen zolang de meting nog open is en er geen uitkomst staat; een nieuwe vulling na de stop of de referentie verandert niets meer.
        if len(filled) > len(_filled_legs(trade)) and trade["stop_hit_at"] is None and trade["ref_r"] is None:
            _more_legs(setup, trade, filled)
        return
    if filled:
        await _fill(setup, filled, now)
    elif res["cancel"] in ("stop voor vulling", "weggelopen"):
        await _cancel(setup, CANCEL_STATE[res["cancel"]])
    elif res["cancel"] == "verlopen" and now >= expires:
        await _cancel(setup, "verlopen")


async def track(now: Optional[datetime] = None) -> None:
    """Wachtende limieten: gevuld wordt een signaal, anders vervalt de setup. Draait ook als de motor uit staat of de poort dicht is: wat al gemeld
    is, wordt afgemaakt."""
    stamp = _utc(now)
    trades = {t["setup_id"]: t for t in repo.list_open_range_sweep_trades()}
    todo = [(s, None) for s in repo.list_range_sweep_setups(("waiting", "niet_gemeld"))]
    for s in repo.list_range_sweep_setups(("filled",), since_iso=(stamp - TTL).isoformat()):
        t = trades.get(s["id"])
        if t is not None and len(_legs_of(s)) > len(_filled_legs(t)):
            todo.append((s, t))
    cache: dict[str, pd.DataFrame] = {}
    for s, t in todo:
        try:
            if s["coin"] not in cache:
                cache[s["coin"]] = await asyncio.to_thread(fetch_bars, s["coin"], "15m", TRACK_LIMIT)
            await _track_one(s, t, cache[s["coin"]], stamp)
        except Exception:
            logger.exception("Range sweep-limiet %s volgen is mislukt", s["id"])


async def _follow_trade(t: dict, b15: pd.DataFrame, b1h: pd.DataFrame, now: pd.Timestamp) -> None:
    cut = _upto(b15, now)
    closed = rs.closed_only(cut, now, "15m")
    forming = cut.iloc[len(closed):len(closed) + 1]
    h1 = add_indicators(rs.closed_only(_upto(b1h, now), now, "1h")).reset_index(drop=True)
    atr = sq.atr_on_15m(cut, h1)
    out = follow_step(t, closed, atr[:len(closed)])
    if not out["stop_hit_at"] and len(forming):
        # De vormende candle kan de stop al geraakt hebben; dat staat vast en hoeft niet op het slot te wachten. Alleen dan nemen we de uitkomst over:
        # anders zou checked_until voorbij een candle schuiven die nog niet klaar is.
        probe = follow_step({**t, **out}, forming, atr[len(closed):len(closed) + 1])
        if probe["stop_hit_at"]:
            out = probe
    lim = pd.Timestamp(t["filled_at"]) + REF_HORIZON
    finished = bool(out["stop_hit_at"])
    if not finished and now >= lim and pd.Timestamp(out["checked_until"]) >= lim - M15:
        finished = True
        if out["ref_r"] is None:
            last = closed[closed["timestamp"] < lim].iloc[-1]
            sign = -1 if t["direction"] == "short" else 1
            out["ref_r"], out["ref_closed_at"] = sign * (float(last["close"]) - t["entry"]) / abs(t["entry"] - t["stop"]), last["timestamp"].isoformat()
    new_stop = bool(out["stop_hit_at"]) and not t["stop_hit_at"]
    new_ref = out["ref_r"] is not None and t["ref_r"] is None
    if new_ref:
        # Eerst de uitkomst (een herhaalbare upsert), dan pas de meting: faalt de uitkomst, dan ziet de volgende cyclus de referentie nog als nieuw.
        # Het moment van vaststellen is nooit vóór de melding: een candletijd van vóór "Gemeld" zou de uitkomst voor de kans plaatsen.
        closed_at = max(now, pd.Timestamp(t["created_at"])).isoformat()
        repo.set_trade_result(t["signal_id"], out["ref_r"], closed_at)
        repo.mark_signal_auto_outcome(t["signal_id"], "take_profit" if out["ref_r"] > 0 else "stop_loss", closed_at)
    update = {k: out[k] for k in _MEASURE_KEYS}
    if finished:
        update["closed_at"] = now.isoformat()
    # Vastleggen vóór het versturen: een mislukte verzending komt niet terug, een herstart meldt niets dubbel.
    repo.update_range_sweep_trade(t["signal_id"], **update)
    fam = FAMILY_LABEL[t["family"]]
    url, tag = push_notify.signal_url(t["coin"], t["signal_id"]), _tag(t["setup_id"])
    if new_ref and out["ref_closed_at"] != out["stop_hit_at"]:
        await _tell_all(push_notify.alert_title(t["coin"], t["direction"], f"{fam} · meting klaar"),
                        f"Meting klaar: referentie-uitgang {fmt_r(out['ref_r'])}, jouw trade beslis je zelf\n"
                        "Dat is de R bij een meelopende stop van 3 ATR op 1u, niet bij jouw eigen doel.", url, tag)
    if new_stop:
        await _tell_all(push_notify.alert_title(t["coin"], t["direction"], f"{fam} · stop geraakt"),
                        f"Stop geraakt, {fmt_r(-out['mae_r'])}\nDe koers raakte de stop van dit plan. Wat je met jouw eigen order doet, beslis je zelf.", url, tag)
    if new_ref or new_stop:
        logger.info("Range sweep trade %s: stop %s, referentie %s", t["signal_id"], out["stop_hit_at"], out["ref_r"])


async def follow(now: Optional[datetime] = None) -> None:
    """Gevulde trades: de meting van de stop (tot de stop of 7 dagen) en de referentie-uitgang die Bewijs telt."""
    stamp = _utc(now)
    trades = repo.list_open_range_sweep_trades()
    cache: dict[str, tuple[pd.DataFrame, pd.DataFrame]] = {}
    for t in trades:
        try:
            if t["coin"] not in cache:
                cache[t["coin"]] = (await asyncio.to_thread(fetch_bars, t["coin"], "15m", FETCH_LIMIT), await asyncio.to_thread(fetch_bars, t["coin"], "1h", FETCH_LIMIT))
            await _follow_trade(t, *cache[t["coin"]], stamp)
        except Exception:
            logger.exception("Range sweep-trade %s volgen is mislukt", t["signal_id"])


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from app import db
    db.init_db()
    asyncio.run(scan())
    asyncio.run(track())
    asyncio.run(follow())
