"""Analyse op de CSV van scripts/replay_report.py, zonder nieuwe afspeelrun.
Drie vragen: (1) leveren bevestigde signalen meer op dan afgewezen? en welke
harde eis haalt winnaars of verliezers weg, (2) welke stopafstand en take-
verhouding past bij deze signalen (rooster, opnieuw gemeten op de 15m-candles),
(3) wint het tegenovergestelde van de richting? Alleen lezen, geen netwerk.

Draai met: python3 scripts/replay_analyze.py [pad-naar-csv]
Zonder pad pakt het script de nieuwste data/replay/day_trading_*_12m.csv.
Opties: --fee-pct 0.1 --slippage-pct 0.05 --max-age-hours 48

Lees de uitkomst met voorzichtigheid: kleine groepen (onder ongeveer 30
signalen) zeggen weinig, ook als de winrate er extreem uitziet."""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config  # noqa: E402
from app.replay import candles as candle_cache  # noqa: E402
from app.replay.outcome import resolve  # noqa: E402

HARD_GATES = ("Zone recent gefaald", "Sniper-entry", "Risico/rendement", "Stopafstand")
STOP_MULTIPLES = (1.0, 1.5, 2.0)
TAKE_RR = (1.0, 1.5, 2.0, 3.0)
BREAK_EVEN_NOTE = "break-even ligt bij 1/(1+RR): 50% bij 1R, 40% bij 1,5R, 33% bij 2R, 25% bij 3R"


def failed_gates(reason) -> tuple[str, ...]:
    parts = {p.split(":")[0] for p in str(reason or "").split(" | ") if p.startswith("✗")}
    return tuple(g for g in HARD_GATES if f"✗ {g}" in parts)


def stats(rows: pd.DataFrame, r_col: str = "r_net") -> dict:
    tp = int((rows["result"] == "take_profit").sum())
    sl = int((rows["result"] == "stop_loss").sum())
    n = len(rows)
    return {
        "n": n, "tp": tp, "sl": sl, "exp": n - tp - sl,
        "winrate": tp / (tp + sl) if tp + sl else None,
        "avg_r": float(rows[r_col].mean()) if n else None,
    }


def line(label: str, s: dict) -> str:
    wr = f"{s['winrate'] * 100:.0f}%" if s["winrate"] is not None else "-"
    avg = f"{s['avg_r']:+.2f}R" if s["avg_r"] is not None else "-"
    return f"{label:<46} n={s['n']:<4} TP={s['tp']:<3} SL={s['sl']:<3} verlopen={s['exp']:<3} winrate={wr:<5} gem.={avg}"


def remeasure(frame: pd.DataFrame, cache: dict, stop_mult: float, rr: float, mirror: bool,
              fee: float, slip: float, max_age: pd.Timedelta) -> pd.DataFrame:
    """Meet elk signaal opnieuw met stop = stop_mult x de oorspronkelijke afstand en
    take = rr x die nieuwe afstand. `mirror` draait de richting om."""
    out = []
    for row in frame.itertuples():
        risk0 = abs(row.entry - row.stop)
        if risk0 <= 0:
            continue
        direction = row.direction
        if mirror:
            direction = "short" if direction == "long" else "long"
        risk = risk0 * stop_mult
        sign = 1 if direction == "long" else -1
        stop = row.entry - sign * risk
        take = row.entry + sign * risk * rr
        o = resolve(direction, row.entry, stop, take, cache[row.coin], row.at, max_age, fee, slip)
        if o is not None:
            out.append({"result": o.result, "r_net": o.r_net, "r_gross": o.r_gross})
    return pd.DataFrame(out, columns=["result", "r_net", "r_gross"])


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("csv", nargs="?")
    p.add_argument("--fee-pct", type=float, default=0.1)
    p.add_argument("--slippage-pct", type=float, default=0.05)
    p.add_argument("--max-age-hours", type=float, default=48)
    a = p.parse_args()

    path = Path(a.csv) if a.csv else None
    if path is None:
        found = sorted((Path(config.BASE_DIR) / "data" / "replay").glob("day_trading_*_12m.csv"))
        if not found:
            sys.exit("Geen CSV gevonden in data/replay. Draai eerst scripts/replay_report.py --months 12.")
        path = found[-1]
    df = pd.read_csv(path)
    df["at"] = pd.to_datetime(df["at"], utc=True)
    df = df[df["result"].notna()].copy()
    df["confirmed"] = df["confirmed"].map(lambda v: str(v) == "True")
    print(f"{path.name}: {len(df)} signalen met uitkomst ({int(df['confirmed'].sum())} bevestigd)\n")

    print("1. Bevestigd tegen afgewezen (uitkomst zoals gemeten in het raam)")
    print(line("bevestigd", stats(df[df["confirmed"]])))
    rejected = df[~df["confirmed"]]
    print(line("afgewezen", stats(rejected)))
    print("\n   Afgewezen per combinatie van harde eisen")
    rejected = rejected.assign(gates=rejected["reason"].map(lambda r: " + ".join(failed_gates(r)) or "alleen zachte factoren"))
    for gates, part in sorted(rejected.groupby("gates"), key=lambda kv: -len(kv[1])):
        if len(part) >= 5:
            print("   " + line(gates, stats(part)))

    fee, slip, max_age = a.fee_pct, a.slippage_pct, pd.Timedelta(hours=a.max_age_hours)
    cache = {c: candle_cache.load_candles(c) for c in df["coin"].unique()}

    for title, subset in (("bevestigde signalen", df[df["confirmed"]]), ("alle signalen", df)):
        print(f"\n2. Rooster stop en take op {title} (n={len(subset)}). {BREAK_EVEN_NOTE}")
        print(f"   {'stop x':<8}{'take':<8}{'winrate':<9}{'gem. netto':<12}{'gem. bruto':<12}n")
        for sm in STOP_MULTIPLES:
            for rr in TAKE_RR:
                m = remeasure(subset, cache, sm, rr, False, fee, slip, max_age)
                s = stats(m)
                wr = f"{s['winrate'] * 100:.0f}%" if s["winrate"] is not None else "-"
                net = f"{m['r_net'].mean():+.2f}R" if len(m) else "-"
                gross = f"{m['r_gross'].mean():+.2f}R" if len(m) else "-"
                print(f"   {sm:<8}{rr:<8}{wr:<9}{net:<12}{gross:<12}{len(m)}")

        print(f"\n3. Omgekeerde richting op {title}, zelfde afstand en take-verhouding 2R")
        m = remeasure(subset, cache, 1.0, 2.0, True, fee, slip, max_age)
        print("   " + line("omgekeerd", stats(m)))


if __name__ == "__main__":
    main()
