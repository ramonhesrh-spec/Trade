"""Orderflow-onderzoek: dezelfde sweeps als scripts/aplus_research.py, maar met kenmerken uit het taker-volume van Binance futures
(wie nam agressief). Haalt eerst per coin de taker-volumes op (een jaar, enkele minuten per coin, daarna in de cache).
Zelfde procedure: kenmerken met vooraf vastgelegde richting, score gekozen op de trainhelft, beoordeeld op de testhelft, permutatietoets.
Draai: python3 scripts/flow_research.py [--coins BTC,ETH,...] [--permutations 200] [--rebuild]"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config  # noqa: E402
from app.replay import aplus, flow  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402

CACHE = Path(config.BASE_DIR) / "data" / "replay" / "aplus_flow_dataset.csv"


def load_dataset(coins: list[str], rebuild: bool) -> pd.DataFrame:
    if CACHE.exists() and not rebuild:
        df = pd.read_csv(CACHE, parse_dates=["at"])
        if set(coins) <= set(df["coin"].unique()):
            return df[df["coin"].isin(coins)].reset_index(drop=True)
    parts = []
    for coin in coins:
        frame = candle_cache.load_candles(coin, "1m")
        print(f"{coin}: taker-volume ophalen ({frame['timestamp'].iloc[0]:%Y-%m-%d} tot {frame['timestamp'].iloc[-1]:%Y-%m-%d})...", flush=True)
        flow_1m = flow.ensure_flow(coin, frame["timestamp"].iloc[0], frame["timestamp"].iloc[-1] + pd.Timedelta(minutes=1))
        d = aplus.build_dataset(frame, flow_1m=flow_1m)
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
    df = df.dropna(subset=aplus.FLOW_HYPOTHESES).reset_index(drop=True)
    cut = df["at"].quantile(0.7)
    print(f"\n{len(df)} gebeurtenissen met taker-volume, {df['at'].min():%Y-%m-%d} tot {df['at'].max():%Y-%m-%d}, splitsing op {cut:%Y-%m-%d}")
    print("Basis, gemiddeld netto R:", ", ".join(f"{c} {df[c].dropna().mean():+.3f}" for c in ("r1.5", "r2.0", "r3.0", "conf_r2.0")))

    print("\nOrderflow-kenmerken, take 2R. Gemiddeld netto R per kant van de mediaan van de trainhelft.")
    print(f"{'kenmerk':<15}{'drempel':>9}  {'train goed':>10}{'train slecht':>13}{'test goed':>11}{'test slecht':>12}   n (train goed/slecht, test goed/slecht)")
    for r in aplus.feature_table(df, "r2.0", cut, aplus.FLOW_HYPOTHESES):
        print(f"{r['feature']:<15}{r['threshold']:>9.2f}  {fmt(r['train_good']):>10}{fmt(r['train_bad']):>13}{fmt(r['test_good']):>11}{fmt(r['test_bad']):>12}   "
              f"{r['train_n'][0]}/{r['train_n'][1]}, {r['test_n'][0]}/{r['test_n'][1]}")

    for label, hyps in (("alleen orderflow", aplus.FLOW_HYPOTHESES), ("orderflow en candle-kenmerken", aplus.HYPOTHESES + aplus.FLOW_HYPOTHESES)):
        print(f"\nScore-regel met {label}. p = aandeel van {a.permutations} husselruns met een even goed testresultaat.")
        print(f"{'uitkomst':<11}{'kenmerken':<44}{'grens':>6}{'n train':>8}{'train R':>9}{'n test':>8}{'test R':>8}{'p':>7}")
        for col in ("r1.5", "r2.0", "r3.0", "conf_r2.0"):
            d = df.dropna(subset=[col]).reset_index(drop=True)
            c = d["at"].quantile(0.7)
            res = aplus.run_pipeline(d, col, c, hyps=hyps)
            if not res.min_score:
                print(f"{col:<11}{'geen kenmerk haalt de drempel in de trainhelft':<44}")
                continue
            pv = aplus.permutation_p(d, col, c, res, a.permutations, hyps=hyps)
            print(f"{col:<11}{','.join(res.chosen)[:43]:<44}{res.min_score:>6}{res.n_train:>8}{res.train_r:>+9.2f}{res.n_test:>8}{res.test_r:>+8.2f}{pv:>7.2f}")
    print("\nLees het zo: een regel telt pas als het testresultaat positief is, n_test minstens 100 en p onder 0,05. Zonder dat is het toeval.")


if __name__ == "__main__":
    main()
