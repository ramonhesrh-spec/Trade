"""Speelt de dagtrading-beslislogica af over historische candles en
rapporteert winrate en verwachting in R per coin, kwartaal en train/test.
Alleen lezen: raakt de database niet aan.

Draai met: python3 scripts/replay_report.py --coins BTC,ETH --months 6
Opties: --step-minutes 60 --years-download 2 --refresh --workers 2
        --include-rejected --fee-pct 0.1 --slippage-pct 0.05 --max-age-hours 48

Eerste keer duurt het downloaden van de candles even. Reken op ongeveer 0,15 s
per stap: circa 10 minuten per coin per halfjaar bij stappen van 1 uur, dus
7 coins met --workers 2 ongeveer 35 tot 40 minuten."""
import argparse
import sys
from concurrent.futures import ProcessPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config  # noqa: E402
from app.replay import candles, engine, report  # noqa: E402

NOTES = (
    "niet nagebootst: de pre-checks van market_scanner.scan_market (cooldown, whiplash-rem, maximum meldingen per cyclus).",
    "benaderd: de lopende candle loopt hooguit 15 minuten achter op live; uitkomsten zijn op 15m-candles gemeten, stop gaat voor bij gelijke candle.",
    "niet nagebootst: de regel van scan_market dat een structureel kandidaat (zone, lijn, patroon) een generiek dagtrading-signaal onderdrukt, zolang de patroon- en smc-replay niet bestaan.",
    "benaderd: live ververst een open signaal elke cyclus en overschrijft stop, take en bevestiging; het raam bevriest het signaal bij de eerste bevestigde beoordeling.",
    "benaderd: een bestaand onbevestigd signaal wordt vervangen als een latere beoordeling wel bevestigd is (live is dat een update).",
)


def _run_one(args):
    coin, base, start, end, step, max_age, fee_pct, slippage_pct = args
    return engine.replay_day_trading(coin, base, start, end, step, max_age, fee_pct, slippage_pct)


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--coins", default=",".join(config.FIXED_COINS))
    p.add_argument("--months", type=float, default=6)
    p.add_argument("--step-minutes", type=int, default=60)
    p.add_argument("--years-download", type=float, default=2)
    p.add_argument("--refresh", action="store_true")
    p.add_argument("--workers", type=int, default=2)
    p.add_argument("--include-rejected", action="store_true")
    p.add_argument("--fee-pct", type=float, default=0.1)
    p.add_argument("--slippage-pct", type=float, default=0.05)
    p.add_argument("--max-age-hours", type=float, default=48)
    a = p.parse_args()

    coins = [c.strip().upper() for c in a.coins.split(",") if c.strip()]
    need = sorted(set(coins) | {"BTC"})
    base = {c: candles.ensure_candles(c, a.years_download, refresh=a.refresh) for c in need}
    for c, df in base.items():
        print(f"{c}: {len(df)} candles, {df['timestamp'].iloc[0]:%Y-%m-%d} tot {df['timestamp'].iloc[-1]:%Y-%m-%d}")

    end = min(df["timestamp"].iloc[-1] for df in base.values()) - pd.Timedelta(days=1)
    start = end - pd.Timedelta(days=30 * a.months)
    print(f"ENABLE_ADVANCED_FACTORS={config.ENABLE_ADVANCED_FACTORS}  run van {start:%Y-%m-%d} tot {end:%Y-%m-%d}\n")

    jobs = [(c, {c: base[c], "BTC": base["BTC"]}, start, end, pd.Timedelta(minutes=a.step_minutes), pd.Timedelta(hours=a.max_age_hours),
             a.fee_pct, a.slippage_pct) for c in coins]
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        signals = [s for result in pool.map(_run_one, jobs) for s in result]

    print(report.format_report(signals, confirmed_only=not a.include_rejected, notes=NOTES))

    out_dir = Path(config.BASE_DIR) / "data" / "replay"
    out_dir.mkdir(parents=True, exist_ok=True)
    # Tijd en looptijd in de naam, zodat een tweede run op dezelfde dag de eerste niet overschrijft.
    out = out_dir / f"day_trading_{datetime.now():%Y-%m-%d_%H%M}_{a.months:g}m.csv"
    rows = [{
        "coin": s.coin, "direction": s.direction, "at": s.at, "entry": s.entry, "stop": s.stop, "take": s.take,
        "confirmed": s.confirmed, "result": s.outcome.result if s.outcome else None,
        "r_net": s.outcome.r_net if s.outcome else None, "reason": s.reason,
    } for s in signals]
    pd.DataFrame(rows).to_csv(out, index=False)
    print(f"\nSignalen opgeslagen in {out}")


if __name__ == "__main__":
    main()
