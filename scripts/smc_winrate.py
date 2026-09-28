"""Eenmalige telling: echt winpercentage van alle afgeronde SMC-signalen
(trade_type='smc'), automatisch trackrecord op basis van auto_outcome
(zie level_check.check_signal_outcomes), niet afhankelijk van of een
gebruiker de trade ooit als "genomen" markeerde. Puur diagnostisch, geen
wijziging aan het systeem. Draai dit handmatig op de VPS."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collections import Counter

from app import db

with db.session() as conn:
    rows = conn.execute(
        """SELECT coin, direction, auto_outcome, created_at
           FROM signals
           WHERE trade_type = 'smc' AND is_practice = 0
           ORDER BY created_at"""
    ).fetchall()

wins = losses = open_count = vervallen = 0
per_coin = Counter()

print(f"=== SMC-trackrecord ({len(rows)} signalen totaal) ===\n")

for r in rows:
    uitkomst = r["auto_outcome"] or "open"
    print(f"  {r['created_at'][:16]}  {r['coin']:6s} {r['direction']:5s}  {uitkomst}")
    if r["auto_outcome"] == "take_profit":
        wins += 1
        per_coin[r["coin"]] += 1
    elif r["auto_outcome"] == "stop_loss":
        losses += 1
        per_coin[r["coin"]] -= 1
    elif r["auto_outcome"] == "vervallen":
        vervallen += 1
    else:
        open_count += 1

resolved = wins + losses
winrate = (wins / resolved * 100) if resolved else None

print(f"\nAfgerond: {resolved}  (win {wins} / verlies {losses})")
print(f"Winpercentage: {winrate:.1f}%" if winrate is not None else "Winpercentage: nog geen afgeronde trades")
print(f"Nog open: {open_count}  |  Vervallen: {vervallen}")

if per_coin:
    print("\nPer coin (win minus verlies):")
    for coin, saldo in per_coin.most_common():
        print(f"  {coin}: {saldo:+d}")
