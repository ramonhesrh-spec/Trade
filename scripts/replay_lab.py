"""Testbank voor instap-regels op 15m en 30m: speelt een bibliotheek van eenvoudige regels af
op 1m-candles van meerdere coins en rapporteert per regel en take (1R, 1,5R, 2R) het aantal trades
per jaar, de winrate en de verwachting in R, bruto en netto, op train (eerste 70%) en test (laatste 30%).
Alleen lezen. Eerst `scripts/replay_smc_report.py` of de download van 1m-candles moet gedraaid hebben.

Draai met: python3 -u scripts/replay_lab.py --months 12
Opties: --coins BTC,ETH --tf 15,30 --fee-pct 0.02 --slippage-pct 0.01 --rules uitbraak,pullback_trend
        --positioning   test de positioneringsregels (open interest, top-traders, takers, funding) in plaats van de candle-regels

Een regel heet `kandidaat` als netto in train en test positief is, er minstens 100 trades zijn en minstens
70% van de coins (met minstens 10 trades) netto positief is. Er worden veel varianten getest: een kandidaat is
een aanwijzing, geen bewijs. De regel `controle_willekeurig` hoort netto ongeveer minus de kosten te scoren."""
import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config  # noqa: E402
from app.replay import candles, lab, positioning  # noqa: E402


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--coins", default=",".join(config.FIXED_COINS))
    p.add_argument("--months", type=float, default=12)
    p.add_argument("--tf", default="15,30")
    p.add_argument("--rules", default=None)
    p.add_argument("--positioning", action="store_true",
                   help="voeg de positioneringsregels toe (open interest, top-traders, takers, funding) en download die data van data.binance.vision")
    p.add_argument("--fee-pct", type=float, default=0.02)
    p.add_argument("--slippage-pct", type=float, default=0.01)
    p.add_argument("--years-download", type=float, default=1.1)
    a = p.parse_args()
    coins = [c.strip().upper() for c in a.coins.split(",") if c.strip()]
    tfs = [int(t) for t in a.tf.split(",")]
    default_rules = list(lab.POSITIONING_RULES) + ["controle_willekeurig"] if a.positioning else [r for r in lab.RULES if r not in lab.POSITIONING_RULES]
    rules = [r.strip() for r in a.rules.split(",") if r.strip()] if a.rules else default_rules
    unknown = [r for r in rules if r not in lab.RULES]
    if unknown:
        sys.exit(f"Onbekende regel(s): {', '.join(unknown)}. Kies uit: {', '.join(lab.RULES)}")

    rows: list[dict] = []
    start = end = None
    for coin in coins:
        frame = candles.ensure_candles(coin, a.years_download, refresh=False, timeframe="1m")
        coin_end = frame["timestamp"].iloc[-1] - pd.Timedelta(days=1)
        coin_start = coin_end - pd.Timedelta(days=30 * a.months)
        start = coin_start if start is None else max(start, coin_start)
        end = coin_end if end is None else min(end, coin_end)
        pos = None
        if a.positioning:
            print(f"{coin}: positioneringsdata ophalen (kan enkele minuten duren)...", flush=True)
            pos = positioning.ensure_positioning(coin, coin_start - pd.Timedelta(days=40), coin_end)
            print(f"{coin}: {len(pos[0])} metingen, {len(pos[1])} fundingmomenten", flush=True)
        rows += lab.evaluate_coin(coin, frame, tfs, rules, coin_start, coin_end, a.fee_pct, a.slippage_pct, positioning=pos)
        print(f"{coin} klaar: {len(rows)} trades tot nu toe", flush=True)

    trades = pd.DataFrame(rows)
    if trades.empty:
        sys.exit("Geen trades gevonden.")
    summary = lab.summarize(trades, start, end)
    variants = len(summary)
    print(f"\nPeriode {start:%Y-%m-%d} tot {end:%Y-%m-%d}, {len(coins)} coins, kosten {2 * (a.fee_pct + a.slippage_pct):.2f}% per rondreis, "
          f"stop {lab.STOP_ATR} x ATR, maximaal {lab.MAX_HOLD}")
    print(f"{variants} varianten getest. Bij zoveel tests komen er per toeval een paar kandidaten uit; kijk naar hoeveel en hoe sterk.\n")
    shown = summary.sort_values("netto_test", ascending=False)
    fmt = {"per_jaar": "{:.0f}".format, "winrate": "{:.0%}".format, "bruto": "{:+.2f}".format, "netto": "{:+.2f}".format,
           "netto_train": "{:+.2f}".format, "netto_test": "{:+.2f}".format}
    print(shown.to_string(index=False, formatters=fmt))
    print(f"\nKandidaten: {int(summary['kandidaat'].sum())} van {variants}")

    out_dir = Path(config.BASE_DIR) / "data" / "replay"
    out_dir.mkdir(parents=True, exist_ok=True)
    out = out_dir / f"lab_{datetime.now():%Y-%m-%d_%H%M%S}_{len(coins)}coins_{a.months:g}m.csv"
    trades.to_csv(out, index=False)
    print(f"Trades opgeslagen in {out}")


if __name__ == "__main__":
    main()
