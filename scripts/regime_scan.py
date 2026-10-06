"""Splitst de ideeën uit de eerdere toetsen op regime (rustig, normaal, onrustig, op basis van BTC-volatiliteit) en kijkt naar zeldzame
crashes en pieken. Vraag: wisselt het teken per regime, zodat de optelsom nul lijkt maar elk deel iets doet? Zie app/replay/regime.py.
Draai: python3 scripts/regime_scan.py [--coins BTC,ETH,...]"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from app import config  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402
from app.replay import regime, scalp, sessions  # noqa: E402


def tstat(s: pd.Series) -> float:
    return float(s.mean() / (s.std(ddof=1) / np.sqrt(len(s)))) if len(s) > 5 and s.std(ddof=1) > 0 else float("nan")


def table(trades: pd.DataFrame, value: str, unit: str, label: str) -> None:
    print(f"\n{label}")
    print(f"{'variant':<24}{'regime':<10}{'n':>6}{'gemiddeld ' + unit:>14}{'t/dag':>8}")
    for variant, g in trades.groupby("variant"):
        for reg in ("rustig", "normaal", "onrustig"):
            sub = g[g["regime"] == reg]
            if len(sub) < 20:
                continue
            daily = sub.groupby(sub["at"].dt.floor("D"))[value].mean()
            print(f"{variant:<24}{reg:<10}{len(sub):>6}{sub[value].mean():>+14.2f}{tstat(daily):>8.1f}")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--coins", default=",".join(config.BASE_COINS))
    a = p.parse_args()
    coins = a.coins.split(",")
    frames = {c: candle_cache.load_candles(c, "1m") for c in coins}
    btc = frames.get("BTC") if "BTC" in frames else candle_cache.load_candles("BTC", "1m")
    ratio = regime.vol_ratio(btc)
    share = ratio.dropna().map(regime.label).value_counts(normalize=True).round(2).to_dict()
    print(f"Verdeling van de regimes over de periode: {share}")

    orb, sweep = [], []
    for c, f in frames.items():
        orb += sessions.orb_trades(c, f) + sessions.orb_trailing(c, f)
        sweep += sessions.sweep_trades(c, f)
        print(f"{c}: sessies klaar", flush=True)
    st = pd.DataFrame(orb + sweep)
    st["regime"] = regime.tag(st["at"], ratio).to_numpy()
    keep = st[((st["variant"].isin(["ORB mee", "ORB spiegel", "SWEEP fade", "SWEEP spiegel"])) & (st["rr"] == 2.0)) | (st["variant"].str.startswith("ORB trail"))]
    table(keep, "r_net", "R net", "Sessie-ideeën (RR 2 of meelopende stop), R na kosten:")

    aligned = scalp.align({**frames, "BTC": btc})
    index = aligned["BTC"].index
    cut = index[int(len(index) * 0.7)]
    sc = []
    for c in coins:
        if c == "BTC":
            continue
        t = scalp.run_coin(c, aligned, cut)
        t = t[t["test"].isin(["LEAD k=3 achterstand", "FADE uitputting", "FOLLOW uitputting"]) & (t["h"] == 10)]
        sc.append(t)
    sct = pd.concat(sc, ignore_index=True).rename(columns={"test": "variant"})
    sct["regime"] = regime.tag(sct["at"], ratio).to_numpy()
    table(sct, "gross_bp", "bp bruto", "Scalp-ideeën, 10 minuten, bruto bp (kosten 6 bp erbij):")

    events = regime.tail_events(btc)
    print(f"\nZeldzame uitschieters van BTC (minstens {2.5}% in een uur, één per 12 uur): {len(events)} gebeurtenissen.")
    print("Rendement daarna in procent, instap op de open van de volgende minuut. Een crash kopen is 'omhoog', een piek verkopen is het omgekeerde.")
    close, openp = btc["close"].to_numpy(), btc["open"].to_numpy()
    rows = []
    for e in events.itertuples():
        row = {"at": e.at, "move": e.move_pct}
        for label, mins in (("+1u", 60), ("+4u", 240), ("+24u", 1440)):
            j = e.i + mins
            row[label] = (close[j] / openp[e.i + 1] - 1) * 100 * (1 if e.move_pct < 0 else -1) if j < len(close) else np.nan
        rows.append(row)
    ev = pd.DataFrame(rows)
    print(ev.round(2).to_string(index=False))
    for label in ("+1u", "+4u", "+24u"):
        s = ev[label].dropna()
        print(f"  {label}: gemiddeld {s.mean():+.2f}% over {len(s)} gebeurtenissen, {np.mean(s > 0) * 100:.0f}% positief, t {tstat(s):.1f} (kosten 0,06%)")


if __name__ == "__main__":
    main()
