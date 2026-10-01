"""Eenmalige check: van de SMC-setups die zijn vervallen zonder ooit een
echt signaal te zijn geworden (geen afwijzing, of structuur draaide om),
klopte de onderliggende richting achteraf wel? Haalt per setup de echte
koersdata op vanaf het ontstaan en kijkt of de prijs het oorspronkelijke
liquidity-doel ooit raakte (zou take profit geraakt hebben als er
hypothetisch wél een entry was geweest), of juist averechts bewoog.

Draai met: python3 scripts/check_dead_smc_setups.py
Alleen SELECT op de database en live candle-ophaling bij de exchange,
raakt niets aan.
"""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, exchange


def main() -> None:
    with db.session() as conn:
        rows = conn.execute(
            """SELECT id, coin, direction, created_at, invalidated_at,
                      sweep_price, liquidity_target, zone_low, zone_high
               FROM smc_setups
               WHERE signal_id IS NULL AND invalidated_at IS NOT NULL
               ORDER BY created_at"""
        ).fetchall()

    print(f"{len(rows)} vervallen SMC-setups zonder ooit een signaal te zijn geworden.\n")

    target_reached = 0
    wrong_direction = 0
    neither = 0

    for r in rows:
        created = datetime.fromisoformat(r["created_at"])
        since_ms = int(created.timestamp() * 1000)
        try:
            df = exchange.fetch_ohlcv(r["coin"], timeframe="30m", limit=200, since=since_ms)
        except Exception as exc:
            print(f"  {r['coin']:10s} {r['direction']:5s}  kon candles niet ophalen: {exc}")
            continue
        if df.empty:
            print(f"  {r['coin']:10s} {r['direction']:5s}  geen candles beschikbaar vanaf {r['created_at']}")
            continue

        target = r["liquidity_target"]
        sweep = r["sweep_price"]
        if r["direction"] == "long":
            hit_target = (df["high"] >= target).any()
            hit_sweep_again = (df["low"] <= sweep).any()
        else:
            hit_target = (df["low"] <= target).any()
            hit_sweep_again = (df["high"] >= sweep).any()

        if hit_target:
            target_reached += 1
            oordeel = "DOEL GERAAKT (zou winst zijn geweest)"
        elif hit_sweep_again:
            wrong_direction += 1
            oordeel = "prijs ging terug voorbij de sweep (richting klopte niet)"
        else:
            neither += 1
            oordeel = "geen van beide (nog onderweg, of zijwaarts)"

        print(f"  {r['coin']:10s} {r['direction']:5s}  {r['created_at'][:16]}  -> {oordeel}")

    total = target_reached + wrong_direction + neither
    if total:
        print(f"\nVan {total} geanalyseerde dode setups:")
        print(f"  Doel geraakt (richting klopte): {target_reached} ({target_reached/total*100:.0f}%)")
        print(f"  Richting klopte niet: {wrong_direction} ({wrong_direction/total*100:.0f}%)")
        print(f"  Onduidelijk/nog onderweg: {neither} ({neither/total*100:.0f}%)")


if __name__ == "__main__":
    main()
