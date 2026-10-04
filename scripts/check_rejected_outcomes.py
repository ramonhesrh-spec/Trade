"""Eenmalige check: hadden de afgewezen autonome signalen alsnog winst
gegeven? Voor elk autonoom signaal sinds SINCE kijkt dit script op 5m-candles
of de prijs na het signaal eerst de stop of de take profit raakte, groepeert
per combinatie van harde eisen waarop het signaal afviel, en zet de
bevestigde signalen ernaast als vergelijking.

Meting vanaf de opgeslagen entry-prijs (de live prijs op het moment van het
signaal), niet vanaf een latere instap. Raken stop en take in dezelfde candle,
dan telt de stop (zelfde keuze als level_check._level_hit_in_candles).

Draai met: python3 scripts/check_rejected_outcomes.py [YYYY-MM-DD]
Alleen SELECT-queries en candle-opvragingen, raakt de database niet aan.
"""
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, exchange
from app.level_check import LEVEL_CHECK_CANDLE_TIMEFRAME, _level_hit_in_candles

SINCE = sys.argv[1] if len(sys.argv) > 1 else "2026-10-01"
HARD_GATES = ("Zone recent gefaald", "Sniper-entry", "Risico/rendement", "Stopafstand")
CANDLE_LIMIT = 1000


def failed_hard_gates(reason: str) -> tuple[str, ...]:
    failed = {part.split(":")[0] for part in (reason or "").split(" | ") if part.startswith("✗")}
    return tuple(g for g in HARD_GATES if f"✗ {g}" in failed)


def main() -> None:
    with db.session() as conn:
        rows = conn.execute(
            """SELECT id, coin, direction, price, stop_loss, take_profit, created_at,
                      technical_confirmed, reason
               FROM signals
               WHERE message_id IS NULL AND created_at >= ?
                 AND stop_loss IS NOT NULL AND take_profit IS NOT NULL
               ORDER BY created_at""",
            (SINCE,),
        ).fetchall()

    print(f"{len(rows)} autonome signalen sinds {SINCE} met stop en take\n")

    results: dict[str, dict[str, int]] = defaultdict(lambda: {"take profit": 0, "stop loss": 0, "geen": 0})
    detail_lines = []

    for row in rows:
        coin = row["coin"]
        since_ms = int(datetime.fromisoformat(row["created_at"]).timestamp() * 1000)
        try:
            candles = exchange.fetch_ohlcv(coin, timeframe=LEVEL_CHECK_CANDLE_TIMEFRAME, since=since_ms, limit=CANDLE_LIMIT)
        except Exception as exc:
            print(f"  signaal {row['id']} ({coin}): geen candles ({exc})")
            continue

        hit = _level_hit_in_candles(row["direction"], row["stop_loss"], row["take_profit"], candles)
        outcome = hit[0] if hit else "geen"

        if row["technical_confirmed"]:
            group = "BEVESTIGD (vergelijking)"
        else:
            gates = failed_hard_gates(row["reason"])
            group = "afgewezen: " + (" + ".join(gates) if gates else "alleen zachte factoren")
        results[group][outcome] += 1
        detail_lines.append(
            f"  {row['id']:>5} {coin:<6} {row['direction']:<5} {row['created_at'][:16]}  {outcome:<11} {group}"
        )

    print(f"{'groep':<70} {'TP':>4} {'SL':>4} {'open':>5} {'winrate':>8}")
    for group, r in sorted(results.items(), key=lambda kv: -sum(kv[1].values())):
        decided = r["take profit"] + r["stop loss"]
        rate = f"{r['take profit'] / decided * 100:.0f}%" if decided else "-"
        print(f"{group:<70} {r['take profit']:>4} {r['stop loss']:>4} {r['geen']:>5} {rate:>8}")

    print("\nPer signaal:")
    print("\n".join(detail_lines))
    print(
        "\nLees dit zo: winrate = TP / (TP + SL). 'open' = nog geen van beide geraakt. "
        "Lage aantallen zeggen weinig; kijk vooral of de afgewezen groepen duidelijk "
        "slechter of beter scoren dan de bevestigde."
    )


main()
