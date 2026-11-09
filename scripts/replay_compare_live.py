"""Controle van het meetraam: speelt een korte periode af en vergelijkt met
de echte autonome signalen uit de database. Alleen lezen.

Live wordt een open signaal elke cyclus ververst: created_at blijft de eerste
aanmaak (vaak nog onbevestigd) en technical_confirmed is de staat van de
LAATSTE verversing. Het raam bevriest een signaal bij de eerste bevestiging.
Een bevestigd live signaal telt daarom als teruggevonden als de replay voor
dezelfde coin en richting ergens in [created_at - 2 uur, volgende live rij van
die coin of --until] een bevestigde beoordeling had. De strikte dekking (een
bevestigd replay-signaal binnen 2 uur van created_at) staat er ter vergelijking
naast. Het criterium (minstens 70%) geldt voor de eerste figuur.
Replay-only signalen worden gerapporteerd maar tellen niet mee: de pre-checks
van scan_market (cooldown, whiplash-rem, limiet per cyclus) zijn niet nagebootst.
Alleen trade_type = 'day_trading', autonoom (message_id leeg), geen oefensignalen.

Draai met: python3 scripts/replay_compare_live.py --since 2026-10-01 --until 2026-10-05
--until is exclusief. --refresh haalt de candles opnieuw op (nodig als de cache
vóór --until eindigt).

Op de VPS staat de echte database niet in de dev-kloon: wijs hem aan met
DATABASE_PATH, anders stopt het script (er wordt geen lege database aangemaakt):
DATABASE_PATH=/opt/crypto-alerts/data/trading.db /opt/crypto-alerts/.venv/bin/python3 \
    scripts/replay_compare_live.py --since 2026-10-01 --until 2026-10-05"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config, db  # noqa: E402
from app.replay import candles, compare, engine  # noqa: E402

PASS_RATIO = 0.7


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--since", required=True)
    p.add_argument("--until", required=True)
    p.add_argument("--coins", default=",".join(config.FIXED_COINS))
    p.add_argument("--refresh", action="store_true")
    a = p.parse_args()
    start, end = pd.Timestamp(a.since, tz="UTC"), pd.Timestamp(a.until, tz="UTC")
    coins = [c.strip().upper() for c in a.coins.split(",")]

    db_file = Path(config.DATABASE_PATH)
    if not db_file.exists():
        sys.exit(f"Database {db_file} bestaat niet. Zet DATABASE_PATH naar de echte database "
                 "(op de VPS: DATABASE_PATH=/opt/crypto-alerts/data/trading.db).")
    with db.session() as conn:
        if conn.execute("SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'signals'").fetchone() is None:
            sys.exit(f"Database {db_file} heeft geen tabel 'signals'. Zet DATABASE_PATH naar de echte database "
                     "(op de VPS: DATABASE_PATH=/opt/crypto-alerts/data/trading.db).")
        live = conn.execute(
            """SELECT id, coin, direction, created_at, technical_confirmed FROM signals
               WHERE message_id IS NULL AND trade_type = 'day_trading' AND is_practice = 0
                 AND created_at >= ? AND created_at < ? ORDER BY created_at""",
            (a.since, a.until),
        ).fetchall()
    live_rows = [
        {"id": r["id"], "coin": r["coin"], "direction": r["direction"], "confirmed": bool(r["technical_confirmed"]),
         "at": pd.Timestamp(r["created_at"]).tz_convert("UTC")}
        for r in live if r["coin"] in coins
    ]

    base = {c: candles.ensure_candles(c, 2, refresh=a.refresh) for c in sorted(set(coins) | {"BTC"})}
    cache_end = min(df["timestamp"].iloc[-1] for df in base.values())
    if cache_end < end:
        sys.exit(f"De candle-cache eindigt op {cache_end:%Y-%m-%d %H:%M}, dat is vóór --until ({end:%Y-%m-%d}). "
                 "Draai opnieuw met --refresh (of kies een eerdere --until); er is geen oordeel gegeven.")
    trace: list[tuple] = []
    replayed = [s for coin in coins for s in engine.replay_day_trading(coin, base, start, end, trace=trace)]
    replay_rows = [{"coin": s.coin, "direction": s.direction, "at": s.at, "confirmed": s.confirmed} for s in replayed]

    live_confirmed = [r for r in live_rows if r["confirmed"]]
    found = [r for r in live_confirmed if compare.found_in_trace(r, live_rows, trace, end)]
    strict = [r for r in live_confirmed if compare.found_strict(r, replay_rows)]
    replay_confirmed = [r for r in replay_rows if r["confirmed"]]
    replay_in_live = [r for r in replay_confirmed if compare.found_strict(r, live_rows)]

    print(f"Live bevestigd: {len(live_confirmed)}, daarvan terug in replay: {len(found)}")
    print(f"Replay bevestigd: {len(replay_confirmed)}, daarvan ook live bevestigd: {len(replay_in_live)}")
    ratio = len(found) / len(live_confirmed) if live_confirmed else 0.0
    strict_ratio = len(strict) / len(live_confirmed) if live_confirmed else 0.0
    print(f"Dekking live in replay: {ratio:.0%} (criterium {PASS_RATIO:.0%})")
    print(f"Strikte dekking (bevestigd replay-signaal binnen 2 uur): {strict_ratio:.0%}")
    print("\nLive bevestigd en NIET teruggevonden:")
    for r in live_confirmed:
        if r not in found:
            print(f"  #{r['id']} {r['coin']} {r['direction']} {r['at']:%Y-%m-%d %H:%M}")
    print("\nReplay bevestigd en NIET live bevestigd:")
    for r in replay_confirmed:
        if r not in replay_in_live:
            print(f"  {r['coin']} {r['direction']} {r['at']:%Y-%m-%d %H:%M}")
    if not live_confirmed:
        print("\nGEEN LIVE SIGNALEN, niet te beoordelen")
    else:
        print("\nRESULTAAT:", "GESLAAGD" if ratio >= PASS_RATIO else "NIET GESLAAGD, het raam klopt nog niet")


if __name__ == "__main__":
    main()
