"""HesPulse-model live: de regels van app/model.py op de echte candles, in de SMC-snelcyclus (market_scanner.scan_smc_fast) na de POC-radar.

Live direct op besluit van de CEO (2026-11-02), ongetest, voor iedereen. Het systeem plaatst nooit een order. Per cyclus:
  scan:  per coin de gesloten 4u-, 1u- en 15m-candles (range_sweep_live.fetch_bars, gedeelde cache) en de bewaarde POC-niveaus
         (poc_levels, van de POC-radar), dan model.scenarios. Een scenario hangt alleen af van candles vanaf zijn range, dus de nieuwe berekening
         geeft voor wat al vaststond hetzelfde; de motor bewaart alleen wat nieuw is (repo.sync_model_scenario) en een afgerond scenario
         verandert nooit meer. Moment A (scenario ontdekt) staat alleen in de app. Moment B (entry beschikbaar) is de ene luide melding
         (send_kans_push, kind 'entry': dagbudget, conflictregel en bundel per cyclus); stond de koers dan al door de limiet, dan is hij
         niet_vulbaar en komt er geen melding (geen marktorder).
  track: open limieten op 5m-candles die ná de publicatie openden (model.walk_fill): gevuld wordt een gewoon signaal 'hespulse_model' (journaal,
         stille melding via send_new_card); level_check beslist doel en stop. Vervallen na 6 uur, weggelopen, of context_weg bij een nieuwe
         4u-breuk. V1 (de vroege limiet op moment A, §6) wordt hier stil gevolgd in model_v1: geen melding, geen journaal, geen signaal."""
import asyncio
import logging
from datetime import datetime, timezone
from typing import Optional

import pandas as pd

from app import config, latency, model, model_card as mc, push_notify, range_sweep_live as rsl, repo

logger = logging.getLogger("model_live")

TRADE_TYPE = model.TRADE_TYPE
LIMIT = rsl.FETCH_LIMIT              # 1000 candles per timeframe: 15m is ruim 10 dagen, de langste levensduur van een range (60 candles van 4u)
FILL_LIMIT = 300                     # 5m: 25 uur; elke cyclus kijkt opnieuw, dus alleen wat sinds de vorige cyclus kwam moet erin zitten
TFS = ("4h", "1h", "15m")


def viewers() -> list[int]:
    """Besluit CEO 5 (2026-11-02): iedereen ziet het model."""
    return [u["id"] for u in repo.list_users()]


def _pocs(coin: str, now: pd.Timestamp):
    """De bewaarde POC-niveaus van de POC-radar; None als er voor deze coin nog niets gemeten is (POC-samenval is dan 'niet gemeten')."""
    from app import poc_radar_live
    if repo.get_poc_scan(coin) is None:
        return None
    return poc_radar_live.stored_levels(coin, now)


async def _frames(coin: str, now: pd.Timestamp) -> dict:
    out = {}
    for tf in TFS:
        out[tf] = rsl._upto(await asyncio.to_thread(rsl.fetch_bars, coin, tf, LIMIT), now)
    return out


async def _price(coin: str, now: pd.Timestamp) -> Optional[float]:
    b5 = rsl._upto(await asyncio.to_thread(rsl.fetch_bars, coin, "5m", FILL_LIMIT), now)
    return float(b5["close"].iloc[-1]) if len(b5) else None


def _iso(ts) -> str:
    return pd.Timestamp(ts).isoformat()


async def _announce_entry(row: dict, stamp: pd.Timestamp) -> None:
    """De ene luide melding per entry (besluit CEO 3), één keer (alert_sent)."""
    if not repo.mark_model_alert_sent(row["id"]):
        return
    timing = latency.timing(TRADE_TYPE, "entry", pd.Timestamp(row["entry_at"]), stamp)
    for uid in viewers():
        user = repo.get_user(uid) or {}
        quiet = push_notify.is_quiet_now(user.get("quiet_hours_start"), user.get("quiet_hours_end"))
        try:
            await push_notify.send_kans_push(uid, row["coin"], row["direction"], mc.entry_title(row), mc.entry_body(row), mc.card_url(row["id"]),
                                             silent=quiet, tag=mc.tag(row["id"]), timing=timing, kind="entry")
        except Exception as exc:
            logger.exception("Model-entry %s naar gebruiker %s is mislukt", row["id"], uid)
            push_notify.record_failure(uid, "kans", mc.card_url(row["id"]), exc)


async def sync(coin: str, scs: list[dict], stamp: pd.Timestamp, price: Optional[float]) -> dict:
    """Bewaart wat model.scenarios vond. Een scenario dat al voorbij was voordat de motor het zag (bij de eerste start, of na een storing), komt
    niet in de app: het was nooit live. Geeft tellers terug voor de hartslag."""
    counts = {"nieuw": 0, "entry": 0}
    seen = set()
    for sc in scs:
        seen.add(sc["range_id"])
        row = mc.row_of(coin, sc)
        stored = repo.get_model_scenario_by_range(coin, sc["range_id"])
        if stored is None:
            e = sc.get("entry")
            if sc["status"] in ("context_weg", "geen_pool") or (e and e["expires_at"] <= stamp):
                continue
            sid = repo.insert_model_scenario({**row, "status": "wacht_sweep", "detected_at": stamp.isoformat(), "updated_at": stamp.isoformat()})
            if sid is None:
                continue
            counts["nieuw"] += 1
            v1 = sc["v1"]
            repo.insert_model_v1(sid, {"coin": coin, "direction": sc["direction"], "limit_price": v1["limit"], "stop_loss": v1["stop"],
                                       "take_profit": v1["take"], "rr": v1["rr"], "placed_at": stamp.isoformat(),
                                       "state": "wacht" if v1["take"] is not None else "geen_doel"})
            stored = repo.get_model_scenario(sid)
        if stored["status"] in repo.MODEL_FINAL:
            continue
        publish = None
        if row["status"] == "afgerond" and sc.get("entry"):
            sign = 1 if sc["direction"] == "long" else -1
            vulbaar = None if price is None else bool((price - row["limit_price"]) * sign > 0)
            row.update({"price_at_publish": price, "vulbaar": None if vulbaar is None else int(vulbaar)})
            publish = stamp.isoformat()
        if repo.sync_model_scenario(stored["id"], row, entry_detected_at=publish):
            fresh = repo.get_model_scenario(stored["id"])
            if pd.Timestamp(fresh["expires_at"]) <= stamp:
                repo.end_model_entry(fresh["id"], "vervallen", fresh["expires_at"])
            elif fresh["vulbaar"] == 0:
                repo.end_model_entry(fresh["id"], "niet_vulbaar", stamp.isoformat())
            else:
                counts["entry"] += 1
                await _announce_entry(fresh, stamp)
    # Een lopend scenario dat de berekening niet meer ziet: zijn range viel uit het candlevenster (ouder dan 10 dagen), dus de bias is weg.
    for r in repo.list_model_scenarios(statuses=model.WAIT_STATES):
        if r["coin"] == coin and r["range_id"] not in seen:
            repo.end_model_scenario(r["id"], "context_weg", stamp.isoformat())
    return counts


async def scan(now: Optional[datetime] = None) -> None:
    if not config.HESPULSE_MODEL_ENABLED:
        repo.beat("hespulse_model", "uit")
        return
    stamp = rsl._utc(now)
    coins = [c["symbol"] for c in repo.list_coins()]
    checked, failed, new, entries = 0, 0, 0, 0
    for coin in coins:
        try:
            frames = await _frames(coin, stamp)
            scs = await asyncio.to_thread(model.scenarios, frames, stamp, _pocs(coin, stamp))
            counts = await sync(coin, scs, stamp, await _price(coin, stamp))
            new, entries, checked = new + counts["nieuw"], entries + counts["entry"], checked + 1
        except Exception:
            failed += 1
            logger.exception("HesPulse-model voor %s is mislukt", coin)
    repo.beat("hespulse_model", f"{checked} van {len(coins)} coins bekeken" + (f", {failed} mislukt" if failed else "")
              + f"; {new} nieuwe scenario's, {entries} entries")


async def _fill(row: dict, filled_at: pd.Timestamp, door: Optional[bool]) -> None:
    uids = viewers()
    signal_id = repo.fill_model_entry(row["id"], mc.signal_row(row), uids, filled_at.isoformat(), door)
    if signal_id is None:
        return
    logger.info("HesPulse-model %s %s gevuld op %s", row["coin"], row["direction"], row["limit_price"])
    timing = latency.timing(TRADE_TYPE, "vulling", filled_at + model.TF["5m"], datetime.now(timezone.utc))
    for uid in uids:
        try:
            # Stil (besluit CEO 3): de luide melding was bij de entry; de vulling staat op /meldingen.
            await push_notify.send_new_card(uid, row["coin"], row["direction"], mc.fill_title(row), mc.fill_body(row),
                                            push_notify.signal_url(row["coin"], signal_id), tag=mc.tag(row["id"]), timing=timing)
        except Exception as exc:
            logger.exception("Model-vulling %s naar gebruiker %s is mislukt", row["id"], uid)
            push_notify.record_failure(uid, "kans", mc.card_url(row["id"]), exc)


async def track(now: Optional[datetime] = None) -> None:
    """Draait ook als het model uit staat: wat al gemeld is, wordt afgemaakt."""
    stamp = rsl._utc(now)
    waiting = repo.list_model_scenarios(entry_states=("wacht",))
    v1 = repo.list_model_v1(("wacht", "gevuld"))
    for coin in sorted({r["coin"] for r in waiting} | {r["coin"] for r in v1}):
        try:
            b5 = rsl._upto(await asyncio.to_thread(rsl.fetch_bars, coin, "5m", FILL_LIMIT), stamp)
            breaks = model.break_times(rsl._upto(await asyncio.to_thread(rsl.fetch_bars, coin, "4h", LIMIT), stamp), stamp)
        except Exception:
            logger.exception("Candles voor %s niet op te halen, model-limieten blijven wachten", coin)
            continue
        for row in (r for r in waiting if r["coin"] == coin):
            try:
                res = model.walk_fill(row["direction"], row["limit_price"], row["take_profit"], pd.Timestamp(row["entry_detected_at"]),
                                      pd.Timestamp(row["expires_at"]), b5, breaks_at=breaks)
                if res["state"] == "gevuld":
                    await _fill(row, pd.Timestamp(res["at"]), res["door_limiet"])
                elif res["state"]:
                    repo.end_model_entry(row["id"], res["state"], _iso(res["at"]))
                elif stamp >= pd.Timestamp(row["expires_at"]):
                    repo.end_model_entry(row["id"], "vervallen", row["expires_at"])
            except Exception:
                logger.exception("Model-limiet %s voor %s is niet verwerkt", row["id"], coin)
        for v in (x for x in v1 if x["coin"] == coin):
            try:
                track_v1(v, b5, breaks, stamp)
            except Exception:
                logger.exception("V1 van scenario %s is niet verwerkt", v["scenario_id"])


def track_v1(v: dict, b5: pd.DataFrame, breaks: list, stamp: pd.Timestamp) -> None:
    """V1 (§6): geldig zolang het scenario leeft. Eindigt het scenario zonder vulling, dan vervalt hij op dat moment. Na de vulling: stop of
    doel op 5m (model.outcome), alleen hier bewaard."""
    if v["state"] == "wacht":
        ended = v.get("scenario_ended_at") if v.get("scenario_status") in repo.MODEL_FINAL else None
        res = model.walk_fill(v["direction"], v["limit_price"], v["take_profit"], pd.Timestamp(v["placed_at"]),
                              pd.Timestamp(ended) if ended else None, b5, breaks_at=breaks)
        if res["state"] == "gevuld":
            repo.update_model_v1(v["scenario_id"], state="gevuld", filled_at=_iso(res["at"]))
            v = {**v, "state": "gevuld", "filled_at": _iso(res["at"])}
        elif res["state"]:
            repo.update_model_v1(v["scenario_id"], state=res["state"], ended_at=_iso(res["at"]))
            return
    if v["state"] == "gevuld":
        out = model.outcome(v["direction"], v["limit_price"], v["stop_loss"], v["take_profit"], pd.Timestamp(v["filled_at"]), b5)
        if out["state"]:
            repo.update_model_v1(v["scenario_id"], state="klaar", outcome=out["state"], outcome_at=_iso(out["at"]), r_gross=out["r"],
                                 ambiguous=int(out["ambiguous"]), ended_at=_iso(out["at"]))


async def run(now: Optional[datetime] = None) -> None:
    """Eerst volgen wat er is, dan zoeken: een vulling in deze cyclus telt nog voordat er een nieuwe entry bij komt."""
    for step in (track, scan):
        try:
            await step(now)
        except Exception:
            logger.exception("HesPulse-model (%s) is mislukt", step.__name__)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from app import db
    db.init_db()
    asyncio.run(run())
