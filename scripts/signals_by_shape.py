"""Waar zitten de verliezen van de scan-signalen? Splitst de afgeronde signalen die de scan zelf vond (geen
bericht) per trade_type en dan per stopafstand, per verhouding tussen take en stop, per richting en per coin:
aantal, winst, verlies, winrate en gemiddelde R (bruto: take telt als take/stop, stop als -1). Vervallen en open
signalen tellen niet mee. Alleen lezen.

Draai met: DATABASE_PATH=/opt/crypto-alerts/data/trading.db python3 scripts/signals_by_shape.py
Opties: --min-n 15 (kleinere groepen worden gemarkeerd), --fee-pct 0.03 (kosten per kant in procenten, voor de netto-kolom)

Lees de uitkomst met voorzichtigheid: groepen onder ongeveer 30 signalen zeggen weinig."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from app import db

STOP_BUCKETS = [0, 0.2, 0.4, 0.7, 1.2, 100]
RR_BUCKETS = [0, 1.2, 1.8, 2.5, 100]


def load() -> pd.DataFrame:
    with db.session() as conn:
        rows = conn.execute(
            """SELECT trade_type, coin, direction, auto_outcome, price, stop_loss, take_profit, created_at
               FROM signals WHERE is_practice = 0 AND message_id IS NULL
                 AND auto_outcome IN ('take_profit', 'stop_loss')
                 AND price IS NOT NULL AND stop_loss IS NOT NULL AND take_profit IS NOT NULL"""
        ).fetchall()
    df = pd.DataFrame([dict(r) for r in rows])
    if df.empty:
        return df
    risk = (df["price"] - df["stop_loss"]).abs()
    df = df[risk > 0].copy()
    df["stop_pct"] = (df["price"] - df["stop_loss"]).abs() / df["price"] * 100
    df["rr"] = (df["take_profit"] - df["price"]).abs() / (df["price"] - df["stop_loss"]).abs()
    df["win"] = df["auto_outcome"] == "take_profit"
    df["r_gross"] = df["rr"].where(df["win"], -1.0)
    return df


def line(label: str, g: pd.DataFrame, fee_pct: float, min_n: int) -> str:
    cost_r = (2 * fee_pct / g["stop_pct"]).mean()
    flag = "  (klein)" if len(g) < min_n else ""
    return (f"   {label:<22} n={len(g):<4} winst {int(g['win'].sum()):<3} verlies {int((~g['win']).sum()):<3} "
            f"winrate {g['win'].mean() * 100:>3.0f}%  bruto {g['r_gross'].mean():+.2f}R  netto {g['r_gross'].mean() - cost_r:+.2f}R{flag}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--min-n", type=int, default=15)
    p.add_argument("--fee-pct", type=float, default=0.03)
    a = p.parse_args()
    df = load()
    if df.empty:
        sys.exit("Geen afgeronde scan-signalen gevonden.")
    for trade_type, g in df.groupby("trade_type"):
        print(f"\n{trade_type}: {line('alles', g, a.fee_pct, a.min_n).strip()}")
        for title, col, buckets in (("per stopafstand (%)", "stop_pct", STOP_BUCKETS), ("per take/stop-verhouding", "rr", RR_BUCKETS)):
            print(f"  {title}")
            cut = pd.cut(g[col], buckets)
            for b, part in g.groupby(cut, observed=True):
                print(line(str(b), part, a.fee_pct, a.min_n))
        print("  per richting")
        for d, part in g.groupby("direction"):
            print(line(d, part, a.fee_pct, a.min_n))
        print("  per coin (alleen groepen met minstens min-n)")
        for c, part in g.groupby("coin"):
            if len(part) >= a.min_n:
                print(line(c, part, a.fee_pct, a.min_n))


if __name__ == "__main__":
    main()
