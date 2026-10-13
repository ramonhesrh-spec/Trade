"""Strategie-lab: toetst kosten-robuuste regels op 1u en 4u (zie app/replay/trendlab.py). Draai op de VPS, de candles zijn klein en snel op te halen:

  .venv/bin/python3 scripts/strategy_lab.py [--jaren 3] [--coins BTC,ETH,...] [--kosten 0.06] [--familie alle|kanteling|standaard] [--alleen-volledig] [--opslaan]

Een variant slaagt alleen als beide helften positief zijn, de marge boven 0 ligt en hij beter is dan willekeurige instappen met dezelfde uitgang.
Het aantal getoetste varianten staat in de uitvoer: hoe meer, hoe minder bijzonder een treffer is. Met --alleen-volledig tellen alleen coins mee die de hele periode bestaan (overlevingscontrole). Vertrouw alleen wat ook in de tweede helft overeind blijft."""
import argparse
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config, db, repo  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402
from app.replay import trendlab as tl  # noqa: E402

SUMMARY_KEYS = ("n", "avg", "ci", "week_ci", "train", "test", "placebo", "winrate", "gross", "median_risk_pct")
LAB_COINS = ",".join(tl.LAB_COINS)


def save_results(results, now_iso: str) -> int:
    """Slaat de uitkomst per variant met trades op; varianten zonder trades blijven ongemoeid."""
    db.init_db()
    saved = 0
    for v, r in results:
        if not r.get("n"):
            continue
        # tuples worden JSON-lijsten; numpy-getallen gaan via default=float in repo.set_rule_lab
        repo.set_rule_lab(v.name.lower(), bool(r["passes"]), {k: r.get(k) for k in SUMMARY_KEYS}, now_iso)
        saved += 1
    return saved


def select_variants(familie: str):
    if familie == "kanteling":
        return tuple(v for v in tl.VARIANTS if v.family == "kanteling")
    if familie == "standaard":
        return tuple(v for v in tl.VARIANTS if v.family != "kanteling")
    return tl.VARIANTS


def needed_timeframes(variants) -> list[str]:
    """Alleen de timeframes die de gekozen varianten gebruiken (plus 4u voor het trendfilter), zodat een kanteling-run geen 4u of 5m onnodig ophaalt."""
    need = {v.timeframe for v in variants} | {"4h" for v in variants if v.htf}
    return [tf for tf in ("5m", "15m", "1h", "4h") if tf in need]


def load_coin(coin: str, timeframes, jaren: float) -> dict[str, pd.DataFrame]:
    tfs = {}
    for tf in timeframes:
        try:
            tfs[tf] = candle_cache.ensure_candles(coin, jaren, timeframe=tf)
        except Exception as exc:
            print(f"{coin} {tf}: geen candles ({exc})", flush=True)
    print(f"{coin}: " + ", ".join(f"{len(tfs[tf])} candles van {tf}" for tf in tfs), flush=True)
    return tfs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--coins", default=LAB_COINS)
    ap.add_argument("--jaren", type=float, default=3.0)
    ap.add_argument("--kosten", type=float, default=config.TRACK_RECORD_COST_PCT)
    ap.add_argument("--familie", choices=("alle", "kanteling", "standaard"), default="alle", help="welke varianten: alle, alleen de kanteling of alleen de oudere")
    ap.add_argument("--alleen-volledig", action="store_true", help="alleen coins met candles over de volle periode (overlevingscontrole)")
    ap.add_argument("--opslaan", action="store_true", help="bewaar de uitkomst per regel in de database; zonder deze vlag schrijft het script niets")
    a = ap.parse_args()
    variants = select_variants(a.familie)
    timeframes = needed_timeframes(variants)
    coins = a.coins.split(",")

    # Coin voor coin: 5m over drie jaar is ~315k candles per coin, alle coins tegelijk in het geheugen past niet op de 4 GB van de VPS.
    keep: dict[str, list[str]] = {}
    if a.alleen_volledig:
        firsts: dict[str, dict[str, pd.DataFrame]] = {tf: {} for tf in timeframes}
        for coin in coins:
            for tf, df in load_coin(coin, timeframes, a.jaren).items():
                firsts[tf][coin] = df.head(1)
        for tf in timeframes:
            keep[tf] = tl.full_history(firsts[tf])
            print(f"{tf}: {len(keep[tf])} coins met volle historie", flush=True)

    parts: dict[str, list] = {v.name: [] for v in variants}
    plac: dict[str, list] = {v.name: [] for v in variants}
    for coin in coins:
        tfs = load_coin(coin, timeframes, a.jaren)
        for v in variants:
            if a.alleen_volledig and coin not in keep[v.timeframe]:
                continue
            bars = tfs.get(v.timeframe)
            if bars is None or len(bars) < tl.WARMUP + 50:
                continue
            htf_bars = tfs.get("4h") if v.htf else None
            if v.htf and (htf_bars is None or len(htf_bars) == 0):
                continue
            real = tl.run_variant(v, bars, a.kosten, htf_bars=htf_bars)
            if real.empty:
                continue
            real["coin"] = coin
            parts[v.name].append(real)
            plac[v.name].append(tl.placebo_variant(v, bars, real, a.kosten, htf_bars=htf_bars))
        del tfs

    results = []
    for v in variants:
        trades = pd.concat(parts[v.name], ignore_index=True) if parts[v.name] else pd.DataFrame()
        placebo = pd.concat(plac[v.name], ignore_index=True) if plac[v.name] else pd.DataFrame()
        results.append((v, tl.evaluate(trades, placebo)))

    print(f"\n{len(results)} varianten getoetst; bij zoveel toetsen is een toevallige treffer normaal.")
    print(f"Kosten {a.kosten}% per rondreis, {a.jaren} jaar, {len(coins)} coins\n")
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

    if a.opslaan:
        print(f"\n{save_results(results, datetime.now(timezone.utc).isoformat())} regels opgeslagen in de database.")


if __name__ == "__main__":
    main()
