"""Welke zones ziet de zone-radar op één coin en waarom wordt er geen kaart van? Alleen-lezen. Draai op de VPS: .venv/bin/python3 scripts/zone_look.py TIA"""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import exchange, zone_radar as zr  # noqa: E402


def fmt(v: float) -> str:
    return f"{v:.4f}" if abs(v) < 10 else f"{v:,.2f}"


def main(coin: str) -> None:
    now = pd.Timestamp.now(tz="UTC")
    zones, price = [], None
    for tf in zr.TFS:
        df = exchange.fetch_ohlcv(coin, timeframe=tf, limit=zr.FETCH_LIMIT_BY_TF[tf])
        zones += zr.active_zones(df, tf, now)
        if tf == zr.TFS[0]:
            price = float(df["close"].iloc[-1])
    print(f"{coin} nu {fmt(price)}, {len(zones)} actieve zones")
    for z in sorted(zones, key=lambda z: z.low):
        d = (price - z.high) / price * 100 if z.kind == "bull" else (z.low - price) / price * 100
        side = "onder" if d > 0 else "boven/in"
        print(f"  {z.tf} {'vraag' if z.kind == 'bull' else 'aanbod'} {fmt(z.low)}-{fmt(z.high)}  {abs(d):.1f}% {side} de koers")
    for d in ("long", "short"):
        plan = zr.plan_for(d, zones, price)
        print(f"{d}: " + (f"kaart, limiet {fmt(plan['limit'])}, stop {fmt(plan['stop_loss'])}, doel {fmt(plan['take_profit'])}, R:R {plan['rr']:.1f}" if plan else "geen kaart (geen eigen zone binnen 6%, geen tegenzone als doel, of minder dan 2R)"))


if __name__ == "__main__":
    main(sys.argv[1].upper())
