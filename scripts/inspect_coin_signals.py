"""Eenmalige diagnose: recente signalen voor één coin met hun volledige
stop/doel-niveaus en automatische uitkomst, om te controleren of
check_signal_outcomes/check_open_trades een geraakte stop loss of take
profit gemist heeft. Puur diagnostisch, geen wijziging aan het systeem.
Draai met: python3 scripts/inspect_coin_signals.py DOGE"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db

if len(sys.argv) != 2:
    print("Gebruik: python3 scripts/inspect_coin_signals.py <COIN>")
    sys.exit(1)

coin = sys.argv[1].upper()

with db.session() as conn:
    signals = conn.execute(
        """SELECT id, direction, trade_type, pattern_name, price, stop_loss, take_profit,
                  auto_outcome, auto_outcome_at, created_at
           FROM signals
           WHERE coin = ? AND is_practice = 0
           ORDER BY created_at DESC
           LIMIT 10""",
        (coin,),
    ).fetchall()

print(f"=== Laatste 10 signalen voor {coin} ===\n")
for s in signals:
    with db.session() as jconn:
        journal_rows = jconn.execute(
            """SELECT je.id, je.user_id, je.status, je.entry_price, je.exit_price
               FROM journal_entries je WHERE je.signal_id = ?""",
            (s["id"],),
        ).fetchall()
    print(
        f"signaal {s['id']} ({s['trade_type']}{'/' + s['pattern_name'] if s['pattern_name'] else ''}) "
        f"{s['direction']} sinds {s['created_at']}\n"
        f"  entry {s['price']}  stop {s['stop_loss']}  take {s['take_profit']}\n"
        f"  auto_outcome: {s['auto_outcome']}  (bepaald op {s['auto_outcome_at']})"
    )
    for j in journal_rows:
        print(f"    journaalregel {j['id']} gebruiker {j['user_id']}: status={j['status']}, entry={j['entry_price']}, exit={j['exit_price']}")
    print()
