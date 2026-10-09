"""Strategie-lab: toetst kosten-robuuste regels op 1u en 4u (zie app/replay/trendlab.py). Draai op de VPS, de candles zijn klein en snel op te halen:

  .venv/bin/python3 scripts/strategy_lab.py [--jaren 3] [--coins BTC,ETH,...] [--kosten 0.06] [--alleen-volledig]

Een variant slaagt alleen als beide helften positief zijn, de marge boven 0 ligt en hij beter is dan willekeurige instappen met dezelfde uitgang.
Het aantal getoetste varianten staat in de uitvoer: hoe meer, hoe minder bijzonder een treffer is. Met --alleen-volledig tellen alleen coins mee die de hele periode bestaan (overlevingscontrole). Vertrouw alleen wat ook in de tweede helft overeind blijft."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402
from app.replay import trendlab as tl  # noqa: E402

LAB_COINS = "BTC,ETH,SOL,BNB,XRP,ADA,DOGE,AVAX,LINK,DOT,LTC,BCH,NEAR,ATOM,UNI,AAVE,SUI,INJ,APT,ARB"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default=LAB_COINS)
    ap.add_argument("--jaren", type=float, default=3.0)
    ap.add_argument("--kosten", type=float, default=config.TRACK_RECORD_COST_PCT)
    ap.add_argument("--alleen-volledig", action="store_true", help="alleen coins met candles over de volle periode (overlevingscontrole)")
    a = ap.parse_args()
    frames: dict[str, dict[str, pd.DataFrame]] = {}
    for coin in a.coins.split(","):
        frames[coin] = {}
        for tf in ("1h", "4h"):
            try:
                frames[coin][tf] = candle_cache.ensure_candles(coin, a.jaren, timeframe=tf)
            except Exception as exc:
                print(f"{coin} {tf}: geen candles ({exc})", flush=True)
        print(f"{coin}: {len(frames[coin].get('4h', []))} candles van 4u", flush=True)

    keep: dict[str, list[str]] = {}
    if a.alleen_volledig:
        for tf in ("1h", "4h"):
            keep[tf] = tl.full_history({c: tfs[tf] for c, tfs in frames.items() if tf in tfs})
            print(f"{tf}: {len(keep[tf])} coins met volle historie", flush=True)

    results = []
    for v in tl.VARIANTS:
        parts, plac = [], []
        for coin, tfs in frames.items():
            if a.alleen_volledig and coin not in keep[v.timeframe]:
                continue
            bars = tfs.get(v.timeframe)
            if bars is None or len(bars) < tl.WARMUP + 50:
                continue
            real = tl.run_variant(v, bars, a.kosten)
            if real.empty:
                continue
            real["coin"] = coin
            parts.append(real)
            plac.append(tl.placebo_variant(v, bars, real, a.kosten))
        trades = pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()
        placebo = pd.concat(plac, ignore_index=True) if plac else pd.DataFrame()
        results.append((v, tl.evaluate(trades, placebo)))

    print(f"\n{len(results)} varianten getoetst; bij zoveel toetsen is een toevallige treffer normaal.")
    print(f"Kosten {a.kosten}% per rondreis, {a.jaren} jaar, {len(frames)} coins\n")
    print(f"{'variant':<15}{'n':>6}{'win':>5}{'stop%':>7}{'bruto':>8}{'netto':>8}  {'95%-marge':<17}{'eerste':>8}{'tweede':>8}{'willek.':>9}  oordeel")
    for v, r in results:
        if not r.get("n"):
            print(f"{v.name:<15}  geen trades")
            continue
        ci = f"{r['ci'][0]:+.2f} tot {r['ci'][1]:+.2f}"
        tr, te = r["train"][1], r["test"][1]
        pl = r["placebo"]
        print(f"{v.name:<15}{r['n']:>6}{r['winrate'] * 100:>4.0f}%{r['median_risk_pct']:>7.1f}{r['gross']:>+8.2f}{r['avg']:>+8.2f}  {ci:<17}"
              f"{(f'{tr:+.2f}' if tr is not None else '-'):>8}{(f'{te:+.2f}' if te is not None else '-'):>8}{(f'{pl:+.2f}' if pl is not None else '-'):>9}  "
              f"{'SLAAGT' if r['passes'] else r['reason']}")
    best = [(v, r) for v, r in results if r.get("n") and r["passes"]]
    print(f"\n{len(best)} van {len(results)} varianten slagen. Bij {len(results)} toetsen is een toevallige treffer normaal: één geslaagde variant is nog geen bewijs.")
    for v, r in best:
        print(f"  {v.name}: gemiddelde winnaar {r['avg_win']:+.1f}R, beste trade {r['best']:+.1f}R. Controleer of dit niet aan één coin of één maand hangt.")


if __name__ == "__main__":
    main()
