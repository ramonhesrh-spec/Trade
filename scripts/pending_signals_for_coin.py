"""Eenmalige diagnose: alle nog niet genomen (pending, niet genegeerd)
signalen voor één coin, ongeacht gebruiker, om te zien of er
tegenstrijdige open signalen naast elkaar bestaan (bv. long én short
tegelijk) en waarom auto_ignore_opposite_pending die combinatie niet al
heeft opgeruimd. Puur diagnostisch, geen wijziging aan het systeem.
Draai met: python3 scripts/pending_signals_for_coin.py PLUME"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db

if len(sys.argv) != 2:
    print("Gebruik: python3 scripts/pending_signals_for_coin.py <COIN>")
    sys.exit(1)

coin = sys.argv[1].upper()

with db.session() as conn:
    rows = conn.execute(
        """SELECT s.id AS signal_id, s.direction, s.trade_type, s.pattern_name,
                  s.created_at, s.price, s.stop_loss, s.take_profit,
                  je.id AS journal_id, je.user_id, je.status, je.level_alert_sent
           FROM journal_entries je
           JOIN signals s ON s.id = je.signal_id
           WHERE s.coin = ? AND je.entry_price IS NULL AND je.status != 'genegeerd' AND s.is_practice = 0
           ORDER BY s.created_at""",
        (coin,),
    ).fetchall()

print(f"=== Nog niet genomen signalen voor {coin} ({len(rows)}) ===\n")
for r in rows:
    print(
        f"  signal {r['signal_id']} ({r['trade_type']}{'/' + r['pattern_name'] if r['pattern_name'] else ''}) "
        f"{r['direction']:5s} sinds {r['created_at'][:16]} — entry {r['price']} stop {r['stop_loss']} take {r['take_profit']} "
        f"— journaalregel {r['journal_id']} (gebruiker {r['user_id']}, status {r['status']}, niveau-alert al gestuurd: {bool(r['level_alert_sent'])})"
    )

directions = {r["direction"] for r in rows}
if len(directions) > 1:
    print(f"\nLet op: {coin} heeft tegelijk pending signalen in {len(directions)} richtingen ({', '.join(sorted(directions))}).")
