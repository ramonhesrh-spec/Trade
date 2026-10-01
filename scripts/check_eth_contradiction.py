"""Eenmalige check, twee onderdelen.

1. Waarom bleven de ETH long/short/long-signalen van de laatste paar uur
   alle drie als 'open' op /signalen staan, terwijl
   repo.auto_ignore_opposite_pending een oude tegenovergestelde, nog niet
   genomen melding automatisch op status='genegeerd' hoort te zetten zodra
   een nieuwe komt?

2. Is de NEAR SHORT SMC-trade die op stop loss afsloot aangemaakt vóór of
   ná de SMC-sniper-fix van eerder deze sessie? Toont de laatste SMC-
   signalen met entry/stop/sniper, zodat we entry_worse_than_sniper zelf
   kunnen narekenen.

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

        print("\n--- Laatste 10 SMC-signalen (alle coins) ---\n")
        smc_signals = conn.execute(
            """SELECT id, coin, direction, price, stop_loss, take_profit, sniper_entry_price,
                      auto_outcome, created_at
               FROM signals
               WHERE trade_type = 'smc' AND is_practice = 0
               ORDER BY created_at DESC LIMIT 10"""
        ).fetchall()
        for s in smc_signals:
            entry, stop, sniper = s["price"], s["stop_loss"], s["sniper_entry_price"]
            if sniper is not None:
                direction = s["direction"].lower()
                worse = (
                    (direction == "short" and entry < sniper)
                    or (direction == "long" and entry > sniper)
                )
                check = "ZOU AFGEWEZEN MOETEN ZIJN" if worse else "juiste kant van sniper"
            else:
                check = "geen sniper_entry_price opgeslagen"
            print(f"signal {s['id']:5d}  {s['created_at']}  {s['coin']:6s} {s['direction']:5s}  "
                  f"entry={entry}  stop={stop}  sniper={sniper}  auto_outcome={s['auto_outcome']}  -> {check}")


if __name__ == "__main__":
    main()
