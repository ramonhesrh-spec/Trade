"""Analyse op de CSV van scripts/replay_smc_report.py, zonder nieuwe afspeelrun.
Vragen: (1) hoe groot is de stopafstand in procenten en hoeveel van de uitkomst
zijn kosten, (2) verdient een bepaalde stopafstand, richting, uur of coin meer,
(3) wat blijft over na een ondergrens op de stopafstand. Kosten worden hier
opnieuw uit de bruto-R berekend, zodat je fee en slippage kunt wijzigen.
Alleen lezen, geen netwerk.

Draai met: python3 scripts/replay_smc_analyze.py [pad-naar-csv]
Zonder pad pakt het script de nieuwste data/replay/smc_*_12m.csv.
Opties: --fee-pct 0.1 --slippage-pct 0.05

Lees de uitkomst met voorzichtigheid: groepen onder ongeveer 30 signalen zeggen weinig."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config  # noqa: E402

RISK_BUCKETS = [0, 0.1, 0.2, 0.3, 0.5, 1.0, 100]
MIN_RISK_THRESHOLDS = (0.1, 0.2, 0.3, 0.5)


def with_costs(df: pd.DataFrame, fee: float, slip: float) -> pd.DataFrame:
    df = df.copy()
    df["risk_pct"] = (df["entry"] - df["stop"]).abs() / df["entry"] * 100
    df["rr"] = (df["take"] - df["entry"]).abs() / (df["entry"] - df["stop"]).abs()
    df["cost_r"] = 2 * (fee + slip) / df["risk_pct"]
    df["r_net2"] = df["r_gross"] - df["cost_r"]
    df["win"] = df["result"] == "take_profit"
    return df


def line(label: str, g: pd.DataFrame) -> str:
    if g.empty:
        return f"{label:<26} n=0"
    return (f"{label:<26} n={len(g):<4} winrate={g['win'].mean() * 100:>3.0f}%  bruto={g['r_gross'].mean():+.2f}R  "
            f"kosten={g['cost_r'].mean():.2f}R (mediaan {g['cost_r'].median():.2f}R)  netto={g['r_net2'].mean():+.2f}R  "
            f"netto mediaan={g['r_net2'].median():+.2f}R")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("csv", nargs="?")
    p.add_argument("--fee-pct", type=float, default=0.1)
    p.add_argument("--slippage-pct", type=float, default=0.05)
    a = p.parse_args()
    path = Path(a.csv) if a.csv else None
    if path is None:
        found = sorted((Path(config.BASE_DIR) / "data" / "replay").glob("smc_*_12m.csv"))
        if not found:
            sys.exit("Geen CSV in data/replay. Draai eerst scripts/replay_smc_report.py --months 12.")
        path = found[-1]
    df = pd.read_csv(path)
    df["at"] = pd.to_datetime(df["at"], utc=True)
    df = with_costs(df[df["result"].notna()], a.fee_pct, a.slippage_pct)
    print(f"{path.name}: {len(df)} signalen, kosten {2 * (a.fee_pct + a.slippage_pct):.2f}% per rondreis\n")

    print("Stopafstand in procenten van de entry (alle signalen)")
    print(df["risk_pct"].describe(percentiles=[.1, .25, .5, .75, .9]).round(3).to_string())
    print(f"Verhouding take/stop: mediaan {df['rr'].median():.2f}, gemiddeld {df['rr'].mean():.2f}\n")

    print("1. Per stopafstand")
    df["bucket"] = pd.cut(df["risk_pct"], RISK_BUCKETS)
    for b, g in df.groupby("bucket", observed=True):
        print("   " + line(str(b), g))

    print("\n2. Ondergrens op de stopafstand (signalen met kleinere stop vervallen)")
    print("   " + line("geen ondergrens", df))
    for t in MIN_RISK_THRESHOLDS:
        print("   " + line(f"stop >= {t}%", df[df["risk_pct"] >= t]))

    print("\n3. Per richting")
    for d, g in df.groupby("direction"):
        print("   " + line(d, g))

    print("\n4. Per uur (UTC, blokken van 4 uur)")
    df["blok"] = (df["at"].dt.hour // 4) * 4
    for b, g in df.groupby("blok"):
        print("   " + line(f"{b:02d}-{b + 4:02d}", g))

    print("\n5. Per coin")
    for c, g in df.groupby("coin"):
        print("   " + line(c, g))

    print("\n6. Per kwartaal, alleen stop >= 0,2%")
    big = df[df["risk_pct"] >= 0.2].copy()
    big["q"] = big["at"].dt.to_period("Q").astype(str)
    for q, g in big.groupby("q"):
        print("   " + line(q, g))


if __name__ == "__main__":
    main()
