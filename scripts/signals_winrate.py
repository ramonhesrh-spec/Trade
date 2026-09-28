"""Eenmalige telling: echt winpercentage van ALLE afgeronde signalen,
per trade_type (day_trading/patroon/swing/smc) en in totaal. Zelfde
methode als smc_winrate.py, nu niet gefilterd op één type. Automatisch
trackrecord op basis van auto_outcome (level_check.check_signal_outcomes),
niet afhankelijk van of een gebruiker de trade ooit als "genomen"
markeerde. Puur diagnostisch, geen wijziging aan het systeem. Draai dit
handmatig op de VPS."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from collections import Counter, defaultdict

from app import db

with db.session() as conn:
    rows = conn.execute(
        """SELECT trade_type, coin, direction, auto_outcome, created_at
           FROM signals
           WHERE is_practice = 0
           ORDER BY trade_type, created_at"""
    ).fetchall()

per_type: dict[str, Counter] = defaultdict(Counter)
per_type_coin: dict[str, Counter] = defaultdict(Counter)

for r in rows:
    t = r["trade_type"]
    outcome = r["auto_outcome"] or "open"
    per_type[t][outcome] += 1
    if outcome == "take_profit":
        per_type_coin[t][r["coin"]] += 1
    elif outcome == "stop_loss":
        per_type_coin[t][r["coin"]] -= 1

print(f"=== Winpercentage per trade_type ({len(rows)} signalen totaal, exclusief oefentrades) ===\n")

totaal_win = totaal_verlies = 0
for t in sorted(per_type):
    c = per_type[t]
    wins = c["take_profit"]
    losses = c["stop_loss"]
    open_count = c["open"]
    vervallen = c["vervallen"]
    resolved = wins + losses
    winrate = f"{wins / resolved * 100:.1f}%" if resolved else "n.v.t."
    totaal_win += wins
    totaal_verlies += losses
    print(f"{t:12s}  totaal {sum(c.values()):3d}  afgerond {resolved:3d}  win {wins:3d}  verlies {losses:3d}  "
          f"open {open_count:3d}  vervallen {vervallen:3d}  winpercentage {winrate}")
    if per_type_coin[t]:
        top = ", ".join(f"{coin}:{saldo:+d}" for coin, saldo in per_type_coin[t].most_common())
        print(f"             per coin: {top}")
    print()

totaal_resolved = totaal_win + totaal_verlies
totaal_winrate = f"{totaal_win / totaal_resolved * 100:.1f}%" if totaal_resolved else "n.v.t."
print(f"Alles samen: afgerond {totaal_resolved}, win {totaal_win}, verlies {totaal_verlies}, winpercentage {totaal_winrate}")
