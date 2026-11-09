"""Welke instap past bij een snelle structuurbreuk? Legt vijf instapvormen naast elkaar op dezelfde breuken (zie app/replay/entry_variants.py).
Draai op de VPS, daar staan de 1m-candles:   .venv/bin/python3 scripts/entry_variants.py [--coins BTC,ETH,...] [--kosten 0.06]
De eerlijke maat is netto R per gezien breuk. Een variant telt pas als de marge boven 0 ligt in beide helften van de periode."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config, structure_review as sr  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402
from app.replay import entry_variants as ev  # noqa: E402


def line(c: dict) -> str:
    avg = f"{c['avg_per_fill']:+.2f}R" if c["avg_per_fill"] is not None else "-"
    risk = f"{c['median_risk_pct']:.2f}%" if c["median_risk_pct"] is not None else "-"
    return (f"{c['mode']:<8}{c['breaks']:>7}{c['filled']:>8}{c['fill_rate'] * 100:>7.0f}%{avg:>12}{c['total']:>+10.1f}R{c['per_break']:>+10.3f}R"
            f"   ({c['ci'][0]:+.3f} tot {c['ci'][1]:+.3f})  stop {risk}  {sr.verdict(c['breaks'], *c['ci'])}")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default=",".join(config.BASE_COINS))
    ap.add_argument("--kosten", type=float, default=config.TRACK_RECORD_COST_PCT)
    ap.add_argument("--jaren", type=float, default=0.5, help="hoeveel jaar 1m-candles er gedownload worden als de cache ontbreekt (kost minuten per coin)")
    a = ap.parse_args()
    parts = []
    for coin in a.coins.split(","):
        try:
            if not candle_cache.cache_path(coin, "1m").exists():
                print(f"{coin}: candles ophalen ({a.jaren} jaar), dit duurt even...", flush=True)
            frame = candle_cache.ensure_candles(coin, a.jaren, timeframe="1m")
        except Exception as exc:
            print(f"{coin}: geen candles ({exc})")
            continue
        rows = ev.run_variants(frame, a.kosten)
        if rows.empty:
            continue
        rows["coin"] = coin
        parts.append(rows)
        print(f"{coin}: {len(rows) // len(ev.MODES)} breuken", flush=True)
    if not parts:
        print("Geen data.")
        return
    rows = pd.concat(parts, ignore_index=True)
    cut = rows["at"].quantile(0.5)
    print(f"\n{rows['at'].min():%Y-%m-%d} tot {rows['at'].max():%Y-%m-%d}, kosten {a.kosten}% per rondreis. Stop minimaal {config.SMC_MIN_STOP_PCT}%.")
    header = f"{'variant':<8}{'breuken':>7}{'gevuld':>8}{'vul':>8}{'per trade':>12}{'totaal':>11}{'per breuk':>11}   95%-marge per breuk"
    for title, part in (("Alles", rows), ("Eerste helft", rows[rows["at"] < cut]), ("Tweede helft", rows[rows["at"] >= cut])):
        print(f"\n{title}\n{header}")
        for c in ev.compare(part):
            print(line(c))
    print("\nLees dit zo: per breuk telt ook de breuk zonder vulling mee, met 0R. Een variant die vaker vult maar per trade zwakker is, kan per breuk toch winnen.")
    print("Bij zoveel varianten zijn toevallige treffers normaal: vertrouw alleen een variant die in beide helften boven 0 zit.\n")


if __name__ == "__main__":
    main()
