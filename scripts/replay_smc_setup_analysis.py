"""Analyse van ALLE SMC-setups uit scripts/replay_smc_report.py (de smc_setups_*.csv),
ook die nooit een signaal werden. Elke setup krijgt één vaste trade (limietorder op
de zonerand, stop achter de sweep plus 0,25 ATR, take 1R, 1,5R, 2R of het
liquiditeitsdoel) en wordt nagespeeld op de 1m-candles. Daarna per kenmerk de
uitkomst op de eerste 70% (train) en de laatste 30% (test) van de tijd.
Alleen lezen, geen netwerk.

Draai met: python3 scripts/replay_smc_setup_analysis.py [pad-naar-csv]
Opties: --fee-pct 0.02 --slippage-pct 0.01 --rr 1.5

Lees de uitkomst met voorzichtigheid: een kenmerk telt pas als het in train EN test
dezelfde kant op wijst, met minstens 30 trades per helft. Veel kenmerken testen
geeft altijd een paar toevallige treffers."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402
from app.replay import smc_setups  # noqa: E402

MIN_N = 30


def build_table(setups: pd.DataFrame, base: dict, fee: float, slip: float, rr_main: float) -> tuple[pd.DataFrame, dict]:
    rows, counts = [], {"setups": len(setups), "onbruikbaar": 0, "niet_gevuld": 0, "gevuld": 0}
    for s in setups.to_dict("records"):
        sim = smc_setups.simulate_setup(s, base[s["coin"]], rr_list=tuple(sorted({1.0, 1.5, 2.0, rr_main})), fee_pct=fee, slippage_pct=slip)
        if sim is None:
            counts["onbruikbaar"] += 1
            continue
        if sim["status"] == "niet_gevuld":
            counts["niet_gevuld"] += 1
            continue
        counts["gevuld"] += 1
        row = {"coin": s["coin"], "direction": s["direction"], "at": pd.Timestamp(s["created_at"]),
               "was_signaal": pd.notna(s["signal_id"]), "risk_pct": sim["risk_pct"],
               "minuten_tot_fill": sim["minutes_to_fill"]}
        for key, o in sim["outcomes"].items():
            if o is not None:
                row[f"win_{key}"] = o.result == "take_profit"
                row[f"gross_{key}"] = o.r_gross
                row[f"net_{key}"] = o.r_net
        row.update(smc_setups.setup_features(s, base))
        rows.append(row)
    return pd.DataFrame(rows), counts


def summarize(g: pd.DataFrame, key) -> str:
    g = g[g[f"gross_{key}"].notna()]
    if g.empty:
        return "n=0"
    return (f"n={len(g):<4} winrate={g[f'win_{key}'].mean() * 100:>3.0f}%  bruto={g[f'gross_{key}'].mean():+.2f}R  "
            f"netto={g[f'net_{key}'].mean():+.2f}R")


def split_line(label: str, df: pd.DataFrame, key, cut: pd.Timestamp) -> str:
    train, test = df[df["at"] < cut], df[df["at"] >= cut]
    flag = "" if min(len(train), len(test)) >= MIN_N else "  (te klein)"
    return f"   {label:<22} train {summarize(train, key):<52} test {summarize(test, key)}{flag}"


def tertile(df: pd.DataFrame, col: str) -> pd.Series:
    return pd.qcut(df[col], 3, labels=["laag", "midden", "hoog"], duplicates="drop")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("csv", nargs="?")
    p.add_argument("--fee-pct", type=float, default=0.02)
    p.add_argument("--slippage-pct", type=float, default=0.01)
    p.add_argument("--rr", type=float, default=1.5, help="take-verhouding voor de kenmerkentabellen")
    p.add_argument("--min-risk-pct", type=float, default=0.0, help="alleen setups met minstens deze stopafstand (in procenten)")
    p.add_argument("--min-zone-pct", type=float, default=0.0, help="alleen setups met minstens deze zonegrootte (in procenten)")
    a = p.parse_args()
    path = Path(a.csv) if a.csv else None
    if path is None:
        found = sorted((Path(config.BASE_DIR) / "data" / "replay").glob("smc_setups_*_12m.csv"))
        if not found:
            sys.exit("Geen smc_setups_*.csv in data/replay. Draai eerst scripts/replay_smc_report.py --months 12.")
        path = found[-1]
    setups = pd.read_csv(path)
    base = {c: candle_cache.load_candles(c, "1m") for c in setups["coin"].unique()}
    table, counts = build_table(setups, base, a.fee_pct, a.slippage_pct, a.rr)
    if a.min_risk_pct or a.min_zone_pct:
        before = len(table)
        table = table[(table["risk_pct"] >= a.min_risk_pct) & (table["zone_pct"] >= a.min_zone_pct)].reset_index(drop=True)
        print(f"Filter: stopafstand minstens {a.min_risk_pct}% en zone minstens {a.min_zone_pct}%: {len(table)} van {before} gevulde setups over.")
    key = a.rr
    cut = table["at"].quantile(0.7)
    print(f"{path.name}: {counts['setups']} setups, gevuld {counts['gevuld']}, niet gevuld {counts['niet_gevuld']}, "
          f"onbruikbaar {counts['onbruikbaar']}. Kosten {2 * (a.fee_pct + a.slippage_pct):.2f}% per rondreis. "
          f"Splitsing train/test op {cut:%Y-%m-%d}\n")

    print("1. Alle gevulde setups, per take")
    for k in sorted({1.0, 1.5, 2.0, a.rr}) + [smc_setups.TARGET]:
        if f"gross_{k}" in table:
            print(f"   take {k!s:<10} {summarize(table, k)}")
    print(f"\n   Mediaan stopafstand {table['risk_pct'].median():.2f}%, mediaan tijd tot fill {table['minuten_tot_fill'].median():.0f} min")

    print(f"\n2. Setups die live een signaal werden tegenover de rest (take {key}R)")
    for flag, g in table.groupby("was_signaal"):
        print(f"   {'werd signaal' if flag else 'geen signaal':<22} {summarize(g, key)}")

    print(f"\n3. Per kenmerk, take {key}R. Train en test naast elkaar")
    for col, label in (("trend_4u", "4u-trend in richting"), ("trend_dag", "dagtrend in richting"),
                       ("trend_btc_4u", "BTC 4u in richting"), ("direction", "richting"), ("weekend", "weekend")):
        print(f" {label}")
        for val, g in table.groupby(col, dropna=False):
            print(split_line(str(val), g, key, cut))
    for col, label in (("sweepdiepte_atr", "sweepdiepte (ATR)"), ("zone_pct", "zonegrootte (%)"),
                       ("atr_pct", "volatiliteit (ATR %)"), ("risk_pct", "stopafstand (%)")):
        print(f" {label}")
        t = table.assign(_t=tertile(table, col))
        for val, g in t.groupby("_t", observed=True):
            lo, hi = g[col].min(), g[col].max()
            print(split_line(f"{val} ({lo:.2f} tot {hi:.2f})", g, key, cut))
    print(" tijdblok (UTC)")
    for b, g in table.groupby((table["uur"] // 6) * 6):
        print(split_line(f"{b:02d} tot {b + 6:02d}", g, key, cut))
    print(" coin")
    for c, g in table.groupby("coin"):
        print(split_line(c, g, key, cut))

    print(f"\n4. Combinatie: 4u- en dagtrend beide in richting, take {key}R")
    both = table[(table["trend_4u"] == True) & (table["trend_dag"] == True)]  # noqa: E712
    print(split_line("beide in richting", both, key, cut))
    rest = table.drop(both.index)
    print(split_line("de rest", rest, key, cut))


if __name__ == "__main__":
    main()
