"""Diagnose: waarom komt een live SMC-signaal niet terug in het raam? Toont het live
signaal, de bijbehorende rij uit smc_setups en wat het raam in de uren eromheen
beslist (trechtergebeurtenissen en eventuele replay-signalen). Alleen lezen.

Draai met:
DATABASE_PATH=/opt/crypto-alerts/data/trading.db /opt/crypto-alerts/.venv/bin/python3 \
    scripts/replay_smc_debug_signal.py --id 205
Opties: --hours-before 3 --hours-after 1"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd  # noqa: E402

from app import config, db  # noqa: E402
from app.replay import candles, smc_engine, smc_report  # noqa: E402

STEP_MINUTES = 5
OFFSET_MINUTES = 3


def _utc(value) -> pd.Timestamp:
    t = pd.Timestamp(value)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--id", type=int, required=True)
    p.add_argument("--hours-before", type=float, default=3)
    p.add_argument("--hours-after", type=float, default=1)
    a = p.parse_args()

    db_file = Path(config.DATABASE_PATH)
    if not db_file.exists():
        sys.exit(f"Database {db_file} bestaat niet. Zet DATABASE_PATH naar de echte database.")
    with db.session() as conn:
        live = conn.execute("SELECT * FROM signals WHERE id = ?", (a.id,)).fetchone()
        setup = conn.execute("SELECT * FROM smc_setups WHERE signal_id = ?", (a.id,)).fetchone()
    if live is None:
        sys.exit(f"Geen signaal met id {a.id}.")
    created = _utc(live["created_at"])
    coin = live["coin"]
    print(f"LIVE #{live['id']} {coin} {live['direction']} type={live['trade_type']} aangemaakt {created:%Y-%m-%d %H:%M}")
    print(f"  prijs {live['price']}  stop {live['stop_loss']}  take {live['take_profit']}")
    if setup is not None:
        print(f"  setup #{setup['id']}: zone {setup['zone_low']} tot {setup['zone_high']}  structuur {setup['structure_level']}  "
              f"sweep {setup['sweep_price']}  doel {setup['liquidity_target']}  atr {setup['atr']}")
        print(f"  setup gebouwd {setup['created_at']}  laatst bijgewerkt {setup['updated_at']}")
    else:
        print("  geen smc_setups-rij gekoppeld aan dit signaal")

    frame = candles.ensure_candles(coin, 1.1, refresh=False, timeframe="1m")
    window_start = created - pd.Timedelta(hours=a.hours_before)
    window_end = created + pd.Timedelta(hours=a.hours_after)
    cache_end = frame["timestamp"].iloc[-1]
    if not smc_report.cache_covers_until(cache_end, window_end):
        sys.exit(f"1m-cache eindigt op {cache_end}, voor {window_end}. Draai eerst replay_smc_compare_live.py met --refresh.")

    warm = smc_report.first_step(window_start - pd.Timedelta(days=1), STEP_MINUTES, OFFSET_MINUTES)
    events: list = []
    book = smc_engine.SmcBook()
    sigs = smc_engine.replay_smc(coin, {coin: frame}, frame, warm, window_end,
                                 pd.Timedelta(minutes=STEP_MINUTES), events=events, book=book)
    print(f"\nREPLAY {coin}: gebeurtenissen van {window_start:%Y-%m-%d %H:%M} tot {window_end:%Y-%m-%d %H:%M}")
    shown = [e for e in events if window_start <= e.at <= window_end and e.kind != "geen_structuurbreuk"]
    for e in shown:
        print(f"  {e.at:%m-%d %H:%M}  {str(e.direction):<6} {e.kind}  {e.detail}")
    if not shown:
        print("  (alleen geen_structuurbreuk in dit venster)")
    print("\nReplay-signalen in het venster:")
    near = [s for s in sigs if window_start <= s.at <= window_end]
    for s in near:
        print(f"  {s.at:%m-%d %H:%M} {s.direction} entry {s.entry:.5f} stop {s.stop:.5f} take {s.take:.5f}")
    if not near:
        print("  geen")
    print("\nSetups in het raam rond die tijd:")
    for r in book.all_setups():
        if _utc(r["created_at"]) <= window_end and _utc(r["updated_at"]) >= window_start - pd.Timedelta(hours=24):
            print(f"  #{r['id']} {r['direction']} zone {r['zone_low']:.5f}-{r['zone_high']:.5f} structuur {r['structure_level']:.5f} "
                  f"sweep {r['sweep_price']:.5f} gebouwd {r['created_at'][:16]} einde {r['ended_because'] or 'open/signaal'}")


if __name__ == "__main__":
    main()
