"""Meet of de berichten uit de community een voorsprong geven. Alleen lezen.

1. Koersrichting: gaat de koers na een call vaker de kant van de call op dan terug, na 15 minuten, 1 uur, 4 uur en
   1 dag? Gemeten in procenten en in ATR-eenheden, ook met vertraging (zoals jouw melding later aankomt dan het
   bericht). Naast elke meting staat de ongerichte koersverandering over dezelfde momenten (de drift), als controle.
2. Trades: elke call als vaste trade (stop 1,5 x ATR, take 1R, 1,5R, 2R, maximaal 24 uur), bruto en netto in R.
3. Jouw keuzes: van de signalen die in je journaal staan, doen de genomen trades het beter dan de weggelaten?

Draai met: DATABASE_PATH=/opt/crypto-alerts/data/trading.db python3 -u scripts/replay_community.py
Opties: --min-calls 8 (coins met minder calls tellen niet mee) --fee-pct 0.02 --slippage-pct 0.01
        --delays 0,5,15,30 --since 2025-10-01

Alleen berichten met coin en richting long of short tellen. Alleen coins met 1m-candles in data/candles
(wordt gedownload voor coins met genoeg calls). Groepen onder ongeveer 30 calls zeggen weinig."""
import argparse
import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config, db  # noqa: E402
from app.replay import candles, lab  # noqa: E402

CALLS_SQL = """
SELECT m.id AS message_id, m.received_at AS at, COALESCE(r.coin, m.coin) AS coin,
       COALESCE(r.direction, m.direction) AS direction, COALESCE(r.category, m.category) AS category
FROM messages m LEFT JOIN message_coin_results r ON r.message_id = m.id
WHERE COALESCE(r.direction, m.direction) IN ('long', 'short') AND COALESCE(r.coin, m.coin) IS NOT NULL
  AND COALESCE(r.unclear, m.unclear) = 0
ORDER BY m.received_at"""


def _utc(value) -> pd.Timestamp:
    t = pd.Timestamp(value)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def mean_line(label: str, values: pd.Series) -> str:
    v = values.dropna()
    if len(v) < 2:
        return f"   {label:<10} n={len(v)}"
    se = v.std(ddof=1) / math.sqrt(len(v))
    return f"   {label:<10} n={len(v):<4} gemiddeld {v.mean():+.3f}  (t={v.mean() / se if se else 0:+.1f})  deel in de richting {(v > 0).mean() * 100:>3.0f}%"


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--min-calls", type=int, default=8)
    p.add_argument("--fee-pct", type=float, default=0.02)
    p.add_argument("--slippage-pct", type=float, default=0.01)
    p.add_argument("--delays", default="0,5,15,30")
    p.add_argument("--since", default=None)
    p.add_argument("--years-download", type=float, default=1.1)
    a = p.parse_args()
    delays = [int(d) for d in a.delays.split(",")]

    db_file = Path(config.DATABASE_PATH)
    if not db_file.exists():
        sys.exit(f"Database {db_file} bestaat niet. Zet DATABASE_PATH naar de echte database.")
    with db.session() as conn:
        calls = pd.DataFrame([dict(r) for r in conn.execute(CALLS_SQL).fetchall()])
        journal = pd.DataFrame([dict(r) for r in conn.execute(
            """SELECT j.user_id, j.status, j.entry_price, j.exit_price, j.result_pct, j.dismissed_at, s.auto_outcome, s.trade_type
               FROM journal_entries j JOIN signals s ON s.id = j.signal_id WHERE s.is_practice = 0""").fetchall()])
    if calls.empty:
        sys.exit("Geen berichten met coin en richting gevonden.")
    calls["at"] = calls["at"].map(_utc)
    calls["coin"] = calls["coin"].str.upper()
    calls = calls.drop_duplicates(["message_id", "coin"])
    if a.since:
        calls = calls[calls["at"] >= _utc(a.since)]
    print(f"{len(calls)} calls van {calls['at'].min():%Y-%m-%d} tot {calls['at'].max():%Y-%m-%d}")
    print("Per categorie: " + ", ".join(f"{k}={v}" for k, v in calls["category"].value_counts().items()))
    counts = calls["coin"].value_counts()
    keep = [c for c, n in counts.items() if n >= a.min_calls]
    print("Per coin: " + ", ".join(f"{c}={n}" for c, n in counts.items()))
    print(f"Meegenomen (minstens {a.min_calls} calls): {', '.join(keep) or 'geen'}\n")

    frames = {}
    for coin in keep:
        try:
            frames[coin] = candles.ensure_candles(coin, a.years_download, refresh=False, timeframe="1m")
        except Exception as e:  # coin niet op Binance of download mislukt
            print(f"{coin}: overgeslagen ({e})", flush=True)
    calls = calls[calls["coin"].isin(frames)]
    calls = calls[calls.apply(lambda c: c["at"] >= frames[c["coin"]]["timestamp"].iloc[0], axis=1)] if len(calls) else calls
    if calls.empty:
        sys.exit("Geen calls binnen het bereik van de candles.")

    control_cat = "oefening"
    real = calls[calls["category"] != control_cat]
    groups = [("echte calls (zonder oefening)", real), *[(f"categorie {c}", g) for c, g in real.groupby("category")],
              (f"controlegroep: categorie {control_cat}", calls[calls["category"] == control_cat])]
    print("1. Koersrichting na een call. 'verschil' = de call min het gemiddelde van dezelfde coin en richting op 30 willekeurige momenten.")
    print("   Een call telt maximaal één keer per coin en richting per 4 uur (opeenvolgende berichten zijn geen onafhankelijke metingen).\n")
    for label, subset in groups:
        subset = subset.sort_values("at")
        subset = subset[~(subset.groupby(["coin", "direction"])["at"].diff() < pd.Timedelta(hours=4))]
        if subset.empty:
            continue
        print(f"{label} (n={len(subset)}, {int((subset['direction'] == 'long').sum())} long, {int((subset['direction'] == 'short').sum())} short)")
        for delay in delays:
            frames_out = []
            for coin, g in subset.groupby("coin"):
                g = g.reset_index(drop=True)
                fr = lab.forward_returns(g, frames[coin], delay)
                if fr.empty:
                    continue
                ctl = lab.placebo_forward(g, frames[coin], delay)
                keyed = g.reset_index().rename(columns={"index": "idx"})[["idx", "at"]]
                fr = fr.merge(keyed, on="at", how="left").drop_duplicates("at").set_index("idx").join(ctl)
                frames_out.append(fr)
            if not frames_out:
                continue
            fr = pd.concat(frames_out, ignore_index=True)
            print(f"  vertraging {delay} min")
            for h in lab.FORWARD_HORIZONS:
                if f"pct_{h}" not in fr or f"ctl_{h}" not in fr:
                    continue
                diff = (fr[f"pct_{h}"] - fr[f"ctl_{h}"]).dropna()
                if len(diff) < 2:
                    continue
                se = diff.std(ddof=1) / math.sqrt(len(diff))
                half = len(diff) // 2
                order = fr.loc[diff.index].sort_values("at").index
                first, second = diff.loc[order[:half]].mean(), diff.loc[order[half:]].mean()
                print(f"   {h:>4} min  n={len(diff):<3} call {fr.loc[diff.index, f'pct_{h}'].mean():+.3f}%  controle {fr.loc[diff.index, f'ctl_{h}'].mean():+.3f}%  "
                      f"verschil {diff.mean():+.3f}% (t={diff.mean() / se if se else 0:+.1f}, {(diff > 0).mean() * 100:.0f}% positief)  "
                      f"eerste helft {first:+.3f}%, tweede helft {second:+.3f}%")
        print()

    fee, slip = a.fee_pct, a.slippage_pct
    print(f"2. Elke echte call als vaste trade (stop {lab.STOP_ATR} x ATR), kosten {2 * (fee + slip):.2f}% per rondreis")
    rows = []
    for delay in delays:
        for coin, g in real.groupby("coin"):
            rows += lab.trades_from_calls(coin, g, frames[coin], delay, fee, slip)
    trades = pd.DataFrame(rows)
    if trades.empty:
        print("   geen trades")
    else:
        for (delay, rr), g in trades.groupby(["delay", "rr"]):
            done = g[g["result"] != "expired"]
            wr = (done["result"] == "take_profit").mean() * 100 if len(done) else float("nan")
            print(f"   vertraging {delay:>2} min, take {rr}R: n={len(g):<4} winrate {wr:>3.0f}%  bruto {g['r_gross'].mean():+.2f}R  netto {g['r_net'].mean():+.2f}R")
        print("\n   Per categorie, vertraging 0, take 1,5R")
        for cat, g in trades[(trades["delay"] == delays[0]) & (trades["rr"] == 1.5)].groupby("category"):
            print(f"   {str(cat):<14} n={len(g):<4} bruto {g['r_gross'].mean():+.2f}R  netto {g['r_net'].mean():+.2f}R")
        print("\n   Per coin, vertraging 0, take 1,5R")
        for coin, g in trades[(trades["delay"] == delays[0]) & (trades["rr"] == 1.5)].groupby("coin"):
            print(f"   {coin:<14} n={len(g):<4} bruto {g['r_gross'].mean():+.2f}R  netto {g['r_net'].mean():+.2f}R")

    print("\n2b. Tijdstop: geen take, uitstap na een vaste tijd. De stop schaalt mee met de houdtijd: 1,5 x ATR x wortel(minuten / 15),")
    print("    zodat 1R telkens een gewone beweging over die houdtijd is. Een kleinere stop zou bij lange houdtijd bijna altijd raken.")
    hold_rows = []
    for delay in (delays[0], delays[min(2, len(delays) - 1)]):
        for hold in (60, 120, 240, 480, 1440):
            for coin, g in real.groupby("coin"):
                hold_rows += lab.trades_from_calls(coin, g, frames[coin], delay, fee, slip, rr_list=(1_000_000.0,), hold=pd.Timedelta(minutes=hold),
                                                   stop_atr=lab.STOP_ATR * math.sqrt(hold / 15))
    holds = pd.DataFrame(hold_rows)
    if not holds.empty:
        for cat in (None, "day_trading"):
            sub = holds if cat is None else holds[holds["category"] == cat]
            print(f"   {'alle echte calls' if cat is None else 'categorie ' + cat}")
            for (delay, hold), g in sub.groupby(["delay", "hold"]):
                print(f"     vertraging {delay:>2} min, uitstap na {hold:>4} min: n={len(g):<4} deel positief {(g['r_gross'] > 0).mean() * 100:>3.0f}%  "
                      f"bruto {g['r_gross'].mean():+.2f}R  netto {g['r_net'].mean():+.2f}R  mediaan netto {g['r_net'].median():+.2f}R")
    print("\n3. Jouw keuzes: genomen tegenover weggelaten signalen (zelfde automatische uitkomst per signaal)")
    if journal.empty:
        print("   geen journaalregels")
    else:
        journal["genomen"] = journal["entry_price"].notna()
        for (user, taken), g in journal.groupby(["user_id", "genomen"]):
            tp = int((g["auto_outcome"] == "take_profit").sum())
            sl = int((g["auto_outcome"] == "stop_loss").sum())
            wr = f"{tp / (tp + sl) * 100:.0f}%" if tp + sl else "-"
            closed = g[g["result_pct"].notna()]
            res = f"  eigen resultaat gemiddeld {closed['result_pct'].mean():+.2f}% over {len(closed)} gesloten" if len(closed) else ""
            print(f"   gebruiker {user} {'genomen' if taken else 'niet genomen':<13} n={len(g):<4} automatische uitkomst: winst {tp}, verlies {sl}, winrate {wr}{res}")


if __name__ == "__main__":
    main()
