"""De laatste SMC-signalen met uitkomst, om te zien of verliezen een gemeenschappelijke oorzaak hebben: te kleine stop
(zou SMC_MIN_STOP_PCT ze tegengehouden hebben?), te lage take/stop-verhouding, uur van de dag, en hoe snel de uitkomst
kwam. Alleen lezen.

Draai met: DATABASE_PATH=/opt/crypto-alerts/data/trading.db python3 scripts/smc_recent.py --n 20"""
import argparse
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import config, db


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--n", type=int, default=20)
    a = p.parse_args()
    with db.session() as conn:
        rows = conn.execute(
            """SELECT id, coin, direction, created_at, price, stop_loss, take_profit, sniper_entry_price, auto_outcome, auto_outcome_at
               FROM signals WHERE trade_type = 'smc' AND is_practice = 0 ORDER BY created_at DESC LIMIT ?""", (a.n,)).fetchall()
    print(f"{'id':<5}{'coin':<6}{'richt.':<7}{'tijd (UTC)':<17}{'stop%':>7}{'take/stop':>10}{'uitkomst':>13}{'minuten':>9}  filter")
    wins = losses = blocked_losses = blocked_wins = 0
    for r in rows:
        risk = abs(r["price"] - r["stop_loss"])
        stop_pct = risk / r["price"] * 100 if r["price"] else 0
        rr = abs(r["take_profit"] - r["price"]) / risk if risk else 0
        minutes = ""
        if r["auto_outcome_at"] and r["created_at"]:
            minutes = f"{(datetime.fromisoformat(r['auto_outcome_at']) - datetime.fromisoformat(r['created_at'])).total_seconds() / 60:.0f}"
        blocked = stop_pct < config.SMC_MIN_STOP_PCT
        outcome = r["auto_outcome"] or "open"
        wins += outcome == "take_profit"
        losses += outcome == "stop_loss"
        blocked_wins += blocked and outcome == "take_profit"
        blocked_losses += blocked and outcome == "stop_loss"
        print(f"{r['id']:<5}{r['coin']:<6}{r['direction']:<7}{r['created_at'][5:16].replace('T', ' '):<17}{stop_pct:>7.2f}{rr:>10.1f}{outcome:>13}{minutes:>9}  "
              f"{'zou nu geblokkeerd zijn' if blocked else ''}")
    print(f"\nWinst {wins}, verlies {losses}. Door de stopregel (minimaal {config.SMC_MIN_STOP_PCT}%) geblokkeerd geweest: "
          f"{blocked_losses} verliezen en {blocked_wins} winsten.")


if __name__ == "__main__":
    main()
