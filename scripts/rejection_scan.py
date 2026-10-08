"""Toetst Rejectie op een niveau op de 1m-candles in data/candles (zie app/replay/rejection.py), met kosten, twee helften en een marge.
Draai op de VPS:   .venv/bin/python3 scripts/rejection_scan.py [--coins BTC,ETH,...] [--kosten 0.06]
Een soort telt pas als de marge boven 0 ligt in beide helften. Onder 20 trades krijgt een groep geen conclusie."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config, structure_review as sr  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402
from app.replay import rejection as rj  # noqa: E402


def line(label: str, values: list[float]) -> str:
    s = sr.summarize(values)
    if not s["n"]:
        return f"  {label:<24} geen trades"
    lo, hi = s["avg_ci"]
    return f"  {label:<24} n={s['n']:<5} winst {s['winrate'] * 100:3.0f}%  netto {s['total']:+8.1f}R  gemiddeld {s['avg']:+.3f}R ({lo:+.3f} tot {hi:+.3f})  {s['verdict']}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default=",".join(config.BASE_COINS))
    ap.add_argument("--kosten", type=float, default=config.TRACK_RECORD_COST_PCT)
    a = ap.parse_args()
    parts = []
    for coin in a.coins.split(","):
        try:
            frame = candle_cache.load_candles(coin, "1m")
        except Exception as exc:
            print(f"{coin}: geen candles ({exc}), draai eerst scripts/entry_variants.py die ze ophaalt")
            continue
        trades = rj.run(frame, a.kosten)
        trades["coin"] = coin
        parts.append(trades)
        print(f"{coin}: {len(trades)} afwijzingen", flush=True)
    if not parts:
        print("Geen data.")
        return
    t = pd.concat(parts, ignore_index=True).sort_values("at")
    cut = t["at"].quantile(0.5)
    print(f"\n{t['at'].min():%Y-%m-%d} tot {t['at'].max():%Y-%m-%d}, kosten {a.kosten}% per rondreis\n")
    for title, part in (("Alles", t), ("Eerste helft", t[t["at"] < cut]), ("Tweede helft", t[t["at"] >= cut])):
        print(title)
        print(line("alle afwijzingen", part["net"].tolist()))
        for d in ("short", "long"):
            print(line(f"{d}", part[part["direction"] == d]["net"].tolist()))
        for sweep in (True, False):
            print(line("prikte erdoor (sweep)" if sweep else "raakte en sloot weg", part[part["swept"] == sweep]["net"].tolist()))
        print()
    print("Lees dit zo: de marge tussen haakjes is het 95%-bereik van het gemiddelde per trade in R. Omvat ze 0, dan weten we het niet; ligt ze eronder, dan is het verlies gemeten.")


if __name__ == "__main__":
    main()
