"""Controle van het meetraam: speelt een korte periode af en vergelijkt met
de echte autonome signalen uit de database. Klopt het raam, dan komen de
bevestigde live signalen grotendeels terug (zelfde coin, richting, binnen 2
uur). Alleen lezen.

Draai met: python3 scripts/replay_compare_live.py --since 2026-10-01 --until 2026-10-04
Slagingscriterium: minstens 70% van de bevestigde live signalen komt terug.
Replay-only signalen worden gerapporteerd maar tellen niet mee: de pre-checks
van scan_market zijn niet nagebootst."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config, db  # noqa: E402
from app.replay import candles, engine  # noqa: E402

TOLERANCE = pd.Timedelta(hours=2)
PASS_RATIO = 0.7


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--since", required=True)
    p.add_argument("--until", required=True)
    p.add_argument("--coins", default=",".join(config.FIXED_COINS))
    a = p.parse_args()
    start, end = pd.Timestamp(a.since, tz="UTC"), pd.Timestamp(a.until, tz="UTC")
    coins = [c.strip().upper() for c in a.coins.split(",")]

    with db.session() as conn:
        live = conn.execute(
            """SELECT id, coin, direction, created_at, technical_confirmed FROM signals
               WHERE message_id IS NULL AND trade_type = 'day_trading' AND created_at >= ? AND created_at < ?""",
            (a.since, a.until),
        ).fetchall()
    live = [dict(r, at=pd.Timestamp(r["created_at"]).tz_convert("UTC")) for r in live if r["coin"] in coins]

    base = {c: candles.ensure_candles(c, 2) for c in sorted(set(coins) | {"BTC"})}
    replayed = [s for coin in coins for s in engine.replay_day_trading(coin, base, start, end)]

    def match(item_coin, item_dir, item_at, others, confirmed_only):
        return [o for o in others if o["coin"] == item_coin and o["direction"] == item_dir
                and abs(o["at"] - item_at) <= TOLERANCE and (o["confirmed"] or not confirmed_only)]

    replay_rows = [{"coin": s.coin, "direction": s.direction, "at": s.at, "confirmed": s.confirmed} for s in replayed]
    live_rows = [{"coin": r["coin"], "direction": r["direction"], "at": r["at"], "confirmed": bool(r["technical_confirmed"])}
                 for r in live]

    live_confirmed = [r for r in live_rows if r["confirmed"]]
    found = [r for r in live_confirmed if match(r["coin"], r["direction"], r["at"], replay_rows, True)]
    replay_confirmed = [r for r in replay_rows if r["confirmed"]]
    replay_in_live = [r for r in replay_confirmed if match(r["coin"], r["direction"], r["at"], live_rows, True)]

    print(f"Live bevestigd: {len(live_confirmed)}, daarvan terug in replay: {len(found)}")
    print(f"Replay bevestigd: {len(replay_confirmed)}, daarvan ook live bevestigd: {len(replay_in_live)}")
    ratio = len(found) / len(live_confirmed) if live_confirmed else 0.0
    print(f"Dekking live in replay: {ratio:.0%} (criterium {PASS_RATIO:.0%})")
    print("\nLive bevestigd en NIET teruggevonden:")
    for r in live_confirmed:
        if r not in found:
            print(f"  {r['coin']} {r['direction']} {r['at']:%Y-%m-%d %H:%M}")
    print("\nReplay bevestigd en NIET live bevestigd:")
    for r in replay_confirmed:
        if r not in replay_in_live:
            print(f"  {r['coin']} {r['direction']} {r['at']:%Y-%m-%d %H:%M}")
    print("\nRESULTAAT:", "GESLAAGD" if ratio >= PASS_RATIO else "NIET GESLAAGD, het raam klopt nog niet")


if __name__ == "__main__":
    main()
