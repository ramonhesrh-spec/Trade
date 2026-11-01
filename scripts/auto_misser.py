"""Automatische missers: zoekt op alle vaste coins de grote omkeringen van de laatste uren (app/auto_misser.py: minstens 3 ATR op 1u binnen 24 uur,
vanaf een bevestigd swing-punt) en kijkt of een live motor er rond het begin (12 uur ervoor of erna) een kaart of signaal voor had. Zo niet, dan
geeft de misser-controle (scripts/misser_check.py) per motor de regel die weigerde. Elke beweging komt in de tabel auto_missers.

  .venv/bin/python3 scripts/auto_misser.py [--uren 24] [--coin BTC] [--droog]

--droog toont alleen en schrijft niets. Draait elke nacht via scripts/nacht_export.py. Dit is meting achteraf, geen advies."""
import argparse
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
from app import auto_misser as am, config, db, exchange, poc, repo  # noqa: E402

# 1u-candles: het venster, de langste beweging erna en ruimte voor de ATR (Wilder 14 heeft een lange aanloop).
FETCH_EXTRA = am.MAX_MOVE_HOURS + 200


def _safe(name: str, fn: Callable[[], str]) -> str:
    try:
        return fn()
    except Exception as exc:                       # één motor zonder data mag de andere redenen niet tegenhouden
        return f"{name}: niet te bepalen ({type(exc).__name__}: {exc})"


def structure_reason(coin: str, move: dict) -> str:
    import misser_check as mc
    at = pd.Timestamp(move["begin_at"])
    _, closed, idx = mc.window_for(coin, at)
    j = mc.judge(closed, idx, move["direction"])
    if len(j["breaks"]):
        return "structuur: breuk gezien in de 12 uur ervoor, maar geen kaart (geen plan, dagcap of het plan stond al voorbij)"
    return "structuur: geen breuk van lijn, range of laatste top/bodem in de 12 uur ervoor (Structuur meldt alleen breuk met terugkeer)"


def zone_sweep_reason(coin: str, move: dict) -> str:
    import misser_check as mc
    at = pd.Timestamp(move["begin_at"])
    res = mc.judge_zonesweep(mc.fetch_rangesweep(coin, at), at, move["direction"], window_hours=12, price=move["begin_price"])
    if res["engines"]:
        return "zone_sweep: een variant zag hem in de replay, maar live kwam er geen kaart (" + ", ".join(res["engines"]) + ")"
    return res["blocker"] or "zone_sweep: geen reden gevonden"


def zone_radar_reason(coin: str, move: dict) -> str:
    from app import zone_radar as zr
    at = pd.Timestamp(move["begin_at"])
    zones = []
    for tf in zr.TFS:
        bars = exchange.fetch_ohlcv(coin, timeframe=tf, limit=zr.FETCH_LIMIT_BY_TF[tf] + 48)
        zones += zr.active_zones(bars, tf, at)
    return am.zone_reason(move["direction"], zones, move["begin_price"])


def poc_radar_reason(coin: str, move: dict) -> str:
    from app import poc_radar_live
    at = pd.Timestamp(move["begin_at"])
    levels = [poc_radar_live._level(r) for r in repo.list_poc_levels(coin, (at.floor("D") - poc.LOOKBACK).isoformat())]
    return am.poc_reason(move["direction"], levels, move["begin_price"], at)


REASONS = {"structuur": structure_reason, "zone_radar": zone_radar_reason, "zone_sweep": zone_sweep_reason, "poc_radar": poc_radar_reason}


def reasons_for(coin: str, move: dict, reasons: Optional[dict] = None) -> dict:
    return {name: _safe(name, lambda fn=fn: fn(coin, move)) for name, fn in (reasons or REASONS).items()}


def run(coins: list[str], now: datetime, hours: float, fetch=None, reasons: Optional[dict] = None, save: bool = True) -> list[dict]:
    fetch = fetch or exchange.fetch_ohlcv
    out = []
    for coin in coins:
        try:
            bars = fetch(coin, timeframe=am.TF, limit=int(hours) + FETCH_EXTRA)
        except Exception as exc:
            print(f"{coin}: geen 1u-candles ({exc})")
            continue
        for move in am.find_moves(bars, now, hours):
            begin = pd.Timestamp(move["begin_at"])
            rows = repo.auto_misser_seen_rows(coin, (begin - am.SEEN_WINDOW).isoformat(), (begin + am.SEEN_WINDOW).isoformat())
            seen = am.seen_by(move, rows)
            row = {**move, "coin": coin, "seen_by": seen, "reasons": {} if seen else reasons_for(coin, move, reasons)}
            if save:
                repo.save_auto_misser(row, now.isoformat())
            out.append(row)
        if fetch is exchange.fetch_ohlcv:
            time.sleep(0.1)                         # zacht voor de beurs
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--uren", type=float, default=am.LOOKBACK_HOURS, help="bewegingen die in deze laatste uren eindigden (standaard 24)")
    ap.add_argument("--coin", action="append", help="alleen deze coin (mag vaker)")
    ap.add_argument("--droog", action="store_true", help="alleen tonen, niets opslaan")
    a = ap.parse_args()
    db.init_db()
    coins = [c.upper() for c in a.coin] if a.coin else list(config.FIXED_COINS)
    rows = run(coins, datetime.now(timezone.utc), a.uren, save=not a.droog)
    for r in rows:
        who = ", ".join(r["seen_by"]) if r["seen_by"] else "geen motor"
        print(f"{r['coin']} {r['direction']} {r['begin_at'][:16]} {r['size_atr']:.1f} ATR ({r['size_pct']:.1f}%): {who}")
        for reason in r["reasons"].values():
            print(f"    {reason}")
    print(f"\n{len(rows)} bewegingen, {len(am.unseen(rows))} door geen motor gezien" + (" (niet opgeslagen)" if a.droog else ""))


if __name__ == "__main__":
    main()
