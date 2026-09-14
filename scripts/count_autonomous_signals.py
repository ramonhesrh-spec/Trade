"""Eenmalige telling: hoeveel autonome marktscan-signalen (message_id IS
NULL) zijn er de afgelopen uren precies weggeschreven, per uur en per coin?
Puur diagnostisch, geen wijziging aan het systeem. Draai dit handmatig op
de VPS."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collections import Counter

from app import db

HOURS_BACK = 48

with db.session() as conn:
    rows = conn.execute(
        """SELECT coin, direction, technical_confirmed, created_at
           FROM signals
           WHERE message_id IS NULL
             AND created_at >= datetime('now', ?)
           ORDER BY created_at""",
        (f"-{HOURS_BACK} hours",),
    ).fetchall()

print(f"=== Autonome signalen (message_id IS NULL) in de laatste {HOURS_BACK} uur ===")
print(f"Totaal: {len(rows)}\n")

per_uur = Counter()
per_coin = Counter()
for r in rows:
    uur = r["created_at"][:13]  # YYYY-MM-DDTHH
    per_uur[uur] += 1
    per_coin[r["coin"]] += 1

print("Per scan-cyclus (uur):")
for uur, n in sorted(per_uur.items()):
    print(f"  {uur}:00  {n} signa{'a' if n == 1 else 'len'}")

print("\nPer coin:")
for coin, n in per_coin.most_common():
    print(f"  {coin}: {n}")

if rows:
    gemiddeld = len(rows) / max(len(per_uur), 1)
    print(f"\nGemiddeld {gemiddeld:.1f} nieuw(e) autonoom signaal/signalen per scan-cyclus "
          f"waarin er minstens één was.")

print("\nLet op: dit zijn nieuwe signalen (elk een Telegram-melding), niet updates van "
      "een al open signaal (die sturen geen melding, notify_on_update=False in "
      "market_scanner.py) en niet afwijzingen (die sturen sinds de laatste fix ook "
      "geen melding meer, notify_on_reject=False).")
