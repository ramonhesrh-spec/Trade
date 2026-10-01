"""Eenmalige check: zijn verloren day_trading/patroon-trades vooral snel na
entry op de stop gesloten? Dat zou wijzen op een te krappe stop
(MAX_STOP_DISTANCE_PCT in app/signal_processor.py, nu 1,5%) die normale
ruis niet overleeft, los van of de richting klopte.

Alleen trade_type IN ('day_trading', 'patroon'): dat zijn de twee types
die door de MAX_STOP_DISTANCE_PCT-poort moeten (zie risk.py). swing en smc
vallen hierbuiten en worden hier niet meegeteld.

Draai met: python3 scripts/check_stop_timing.py
Alleen SELECT-queries, raakt de database niet aan.
"""
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db

STOPPED_OUT_TOLERANCE_PCT = 0.3  # exit_price binnen dit % van stop_loss = automatische stop-hit
FAST_STOP_MINUTES = 60  # "snel" = binnen dit aantal minuten na entry


def _parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def main() -> None:
    with db.session() as conn:
        rows = conn.execute(
            """SELECT je.entry_price, je.entry_time, je.exit_price, je.exit_time,
                      je.result_pct, s.stop_loss, s.take_profit, s.direction,
                      s.coin, s.trade_type
               FROM journal_entries je
               JOIN signals s ON s.id = je.signal_id
               WHERE je.status != 'genegeerd' AND s.is_practice = 0
                 AND s.trade_type IN ('day_trading', 'patroon')
                 AND je.entry_price IS NOT NULL AND je.exit_price IS NOT NULL
                 AND je.entry_time IS NOT NULL AND je.exit_time IS NOT NULL
                 AND s.stop_loss IS NOT NULL"""
        ).fetchall()

    losses = [r for r in rows if r["result_pct"] is not None and r["result_pct"] < 0]
    print(f"Gesloten day_trading/patroon-trades (geen oefen): {len(rows)}")
    print(f"Daarvan verlies: {len(losses)}")
    if not losses:
        print("Geen verlies-trades gevonden, niets te analyseren.")
        return

    stopped_out = []
    for r in losses:
        stop_distance_pct = abs(r["exit_price"] - r["stop_loss"]) / r["stop_loss"] * 100 if r["stop_loss"] else 999
        if stop_distance_pct <= STOPPED_OUT_TOLERANCE_PCT:
            stopped_out.append(r)

    print(f"Daarvan op de stop gesloten (exit binnen {STOPPED_OUT_TOLERANCE_PCT}% van stop_loss): {len(stopped_out)}")
    if not stopped_out:
        print("Geen van de verlies-trades sloot op de stop zelf (mogelijk vooral handmatig gesloten verlies).")
        return

    fast = []
    for r in stopped_out:
        try:
            minutes = (_parse(r["exit_time"]) - _parse(r["entry_time"])).total_seconds() / 60
        except ValueError:
            continue
        entry_stop_pct = abs(r["entry_price"] - r["stop_loss"]) / r["entry_price"] * 100 if r["entry_price"] else None
        fast.append((r["coin"], r["direction"], r["trade_type"], minutes, entry_stop_pct))

    fast.sort(key=lambda t: t[3])
    within = [t for t in fast if t[3] <= FAST_STOP_MINUTES]

    print(f"\nTijd tussen entry en stop-hit, op de stop gesloten trades (n={len(fast)}):")
    for coin, direction, trade_type, minutes, stop_pct in fast:
        stop_pct_str = f"{stop_pct:.2f}%" if stop_pct is not None else "?"
        print(f"  {coin:10s} {direction:5s} {trade_type:11s}  {minutes:7.1f} min na entry   stop-afstand {stop_pct_str}")

    print(f"\nBinnen {FAST_STOP_MINUTES} minuten op de stop: {len(within)} van {len(fast)} "
          f"({len(within) / len(fast) * 100:.0f}%)")
    if fast:
        avg_stop_pct = sum(t[4] for t in fast if t[4] is not None) / len([t for t in fast if t[4] is not None])
        print(f"Gemiddelde stop-afstand bij entry van deze trades: {avg_stop_pct:.2f}%")

    print(
        "\nHoog percentage snel = sterke aanwijzing dat de stop normale ruis niet overleeft.\n"
        "Laag percentage = de stop zelf is waarschijnlijk niet het probleem, oorzaak ligt elders."
    )


if __name__ == "__main__":
    main()
