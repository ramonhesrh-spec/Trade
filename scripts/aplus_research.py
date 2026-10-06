"""A+ onderzoek op de 1m-candles in data/candles: sweeps van echte niveaus en van het 4-uurs zwaaipunt, tien vooraf vastgelegde
kenmerken, een score gekozen op de trainhelft en beoordeeld op de testhelft, met een permutatietoets (zie app/replay/aplus.py).
Draai: python3 scripts/aplus_research.py [--coins BTC,ETH,...] [--permutations 200] [--rebuild]
De dataset wordt bewaard in data/replay/aplus_dataset.csv zodat een tweede run direct klaar is."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config  # noqa: E402
from app.replay import aplus  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402

CACHE = Path(config.BASE_DIR) / "data" / "replay" / "aplus_dataset.csv"


def load_dataset(coins: list[str], rebuild: bool) -> pd.DataFrame:
    if CACHE.exists() and not rebuild:
        df = pd.read_csv(CACHE, parse_dates=["at"])
        if set(coins) <= set(df["coin"].unique()):
            return df[df["coin"].isin(coins)].reset_index(drop=True)
    parts = []
    for coin in coins:
        d = aplus.build_dataset(candle_cache.load_candles(coin, "1m"))
        d["coin"] = coin
        parts.append(d)
        print(f"{coin}: {len(d)} gebeurtenissen", flush=True)
    df = pd.concat(parts, ignore_index=True)
    CACHE.parent.mkdir(parents=True, exist_ok=True)
    df.to_csv(CACHE, index=False)
    return df


def fmt(x) -> str:
    return "   -  " if x is None or pd.isna(x) else f"{x:+.2f}"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--coins", default=",".join(config.BASE_COINS))
    p.add_argument("--permutations", type=int, default=200)
    p.add_argument("--rebuild", action="store_true")
    a = p.parse_args()
    df = load_dataset(a.coins.split(","), a.rebuild)
    cut = df["at"].quantile(0.7)
    print(f"\n{len(df)} gebeurtenissen, {df['at'].min():%Y-%m-%d} tot {df['at'].max():%Y-%m-%d}, splitsing op {cut:%Y-%m-%d}")
    print("Marktorder op de slotkoers van de sweepcandle, kosten 0,06% per rondreis, maximaal 3 uur vasthouden.")
    print("Mediaan stopafstand", f"{df['risk_pct'].median():.2f}%", "| soorten:", dict(df["kind"].value_counts()))
    print("\nBasis (alle gebeurtenissen), gemiddeld netto R:")
    for col in ("r1.5", "r2.0", "r3.0", "conf_r2.0"):
        s = df[col].dropna()
        print(f"   {col:<10} n={len(s):>6}  {s.mean():+.3f}R")

    print("\nKenmerken, take 2R. 'goed' is de vooraf vastgelegde kant van de mediaan van de trainhelft. Gemiddeld netto R per kant.")
    print(f"{'kenmerk':<15}{'drempel':>9}  {'train goed':>10}{'train slecht':>13}{'test goed':>11}{'test slecht':>12}   n (train goed/slecht, test goed/slecht)")
    for r in aplus.feature_table(df, "r2.0", cut):
        thr = "-" if r["threshold"] is None else f"{r['threshold']:.2f}"
        print(f"{r['feature']:<15}{thr:>9}  {fmt(r['train_good']):>10}{fmt(r['train_bad']):>13}{fmt(r['test_good']):>11}{fmt(r['test_bad']):>12}   "
              f"{r['train_n'][0]}/{r['train_n'][1]}, {r['test_n'][0]}/{r['test_n'][1]}")

    print(f"\nScore-regel: kenmerken en grens gekozen op de trainhelft, daarna beoordeeld op de testhelft. p = aandeel van {a.permutations} husselruns met een even goed testresultaat.")
    print(f"{'uitkomst':<11}{'kenmerken':<44}{'grens':>6}{'n train':>8}{'train R':>9}{'n test':>8}{'test R':>8}{'p':>7}")
    for col in ("r1.5", "r2.0", "r3.0", "conf_r2.0"):
        d = df.dropna(subset=[col]).reset_index(drop=True)
        c = d["at"].quantile(0.7)
        res = aplus.run_pipeline(d, col, c)
        if not res.min_score:
            print(f"{col:<11}{'geen kenmerk haalt de drempel in de trainhelft':<44}")
            continue
        pv = aplus.permutation_p(d, col, c, res, a.permutations)
        print(f"{col:<11}{','.join(res.chosen)[:43]:<44}{res.min_score:>6}{res.n_train:>8}{res.train_r:>+9.2f}{res.n_test:>8}{res.test_r:>+8.2f}{pv:>7.2f}")
    print("\nLees het zo: een regel telt pas als het testresultaat positief is, n_test minstens 100 en p onder 0,05. Zonder dat is het toeval.")


if __name__ == "__main__":
    main()
