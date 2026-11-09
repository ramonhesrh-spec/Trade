"""Toetst of derivatenkenmerken (funding, open interest, taker, long/short) SMC-setups beter maken.
Gebruikt alleen de setups binnen de periode waarvoor data/derivs/*.csv bestaat (de API geeft ~30 dagen,
de verzamelaar bouwt het daarna op). Print per kenmerk n, winrate en R; een oordeel kan pas bij
minstens 30 trades per kant. Draai: python3 scripts/smc_derivs_check.py [pad-naar-setups-csv]"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import pandas as pd  # noqa: E402

from app import config, derivs  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402
from app.replay.derivs_features import features_at  # noqa: E402
from replay_smc_setup_analysis import build_table, summarize  # noqa: E402

MIN_N = 30


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("csv", nargs="?")
    p.add_argument("--rr", type=float, default=1.5)
    a = p.parse_args()
    path = Path(a.csv) if a.csv else sorted((Path(config.BASE_DIR) / "data" / "replay").glob("smc_setups_*_12m.csv"))[-1]
    setups = pd.read_csv(path)
    data = {c: pd.read_csv(derivs.cache_path(c), index_col="ts", parse_dates=["ts"])
            for c in setups["coin"].unique() if derivs.cache_path(c).exists()}
    if not data:
        sys.exit("Geen data/derivs/*.csv. Draai eerst: python3 -m app.derivs")
    setups = setups[setups["coin"].isin(data)]
    base = {c: candle_cache.load_candles(c, "1m") for c in setups["coin"].unique()}
    table, _ = build_table(setups, base, 0.02, 0.01, a.rr)
    rows = []
    for r in table.to_dict("records"):
        f = features_at(data[r["coin"]], r["at"], r["direction"])
        if f:
            rows.append({**r, **f})
    t = pd.DataFrame(rows)
    print(f"{len(t)} gevulde setups met derivatendata (periode {min(d.index.min() for d in data.values()):%Y-%m-%d} "
          f"tot {max(d.index.max() for d in data.values()):%Y-%m-%d}). Take {a.rr}R, kosten 0.06% per rondreis.")
    if t.empty:
        return
    print(f"Alle: {summarize(t, a.rr)}\n")
    for col, label in (("funding_vol", "funding aan de volle kant"), ("taker_in_richting", "taker-druk in richting"),
                       ("publiek_in_richting", "alle accounts in richting"), ("top_in_richting", "grote spelers in richting")):
        print(label)
        for val, g in t.groupby(col):
            flag = "" if len(g) >= MIN_N else "  (te klein)"
            print(f"   {str(val):<8} {summarize(g, a.rr)}{flag}")
    print("open interest 4u verandering")
    t = t.dropna(subset=["oi_4u_pct"])
    for lab, g in (("stijgt", t[t["oi_4u_pct"] > 0]), ("daalt", t[t["oi_4u_pct"] <= 0])):
        flag = "" if len(g) >= MIN_N else "  (te klein)"
        print(f"   {lab:<8} {summarize(g, a.rr)}{flag}")


if __name__ == "__main__":
    main()
