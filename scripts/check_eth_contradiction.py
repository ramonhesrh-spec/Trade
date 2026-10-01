"""Eenmalige check: waarom bleven de ETH long/short/long-signalen van de
laatste paar uur alle drie als 'open' op /signalen staan, terwijl
repo.auto_ignore_opposite_pending een oude tegenovergestelde, nog niet
genomen melding automatisch op status='genegeerd' hoort te zetten zodra
een nieuwe komt?

Toont per recent ETH day_trading/patroon/smc-signaal: wanneer gemaakt,
richting, message_id (None = autonoom, anders Discord-doorgestuurd), en
per gekoppelde journaalregel de status en of er een entry is ingevuld
(auto_ignore_opposite_pending raakt alleen entry_price IS NULL-rijen).

Draai met: python3 scripts/check_eth_contradiction.py
Alleen SELECT-queries, raakt de database niet aan.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db


def main() -> None:
    with db.session() as conn:
        signals = conn.execute(
            """SELECT id, coin, direction, trade_type, pattern_name, message_id,
                      auto_outcome, created_at
               FROM signals
               WHERE coin = 'ETH' AND is_practice = 0
                 AND trade_type IN ('day_trading', 'patroon', 'smc')
               ORDER BY created_at DESC LIMIT 15"""
        ).fetchall()

        print(f"Laatste {len(signals)} ETH day_trading/patroon/smc-signalen (nieuwste eerst):\n")
        for s in signals:
            bron = "Discord" if s["message_id"] is not None else "autonoom"
            print(f"signal {s['id']:5d}  {s['created_at']}  {s['direction']:5s}  "
                  f"trade_type={s['trade_type']:11s}  bron={bron:8s}  "
                  f"auto_outcome={s['auto_outcome']}")

            entries = conn.execute(
                """SELECT je.id, je.user_id, je.status, je.entry_price, je.dismissed_at, je.note
                   FROM journal_entries je WHERE je.signal_id = ?""",
                (s["id"],),
            ).fetchall()
            for e in entries:
                print(f"    journal {e['id']:5d}  user {e['user_id']}  status={e['status']:10s}  "
                      f"entry_price={e['entry_price']}  dismissed_at={e['dismissed_at']}  note={e['note']}")
            print()


if __name__ == "__main__":
    main()
