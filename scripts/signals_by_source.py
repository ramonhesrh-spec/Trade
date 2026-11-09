"""Eenmalige telling: presteren signalen die uit een doorgestuurd Discord-bericht komen
(message_id gezet) beter dan signalen die de scan zelf vindt (message_id leeg)?
Per bron, trade_type en bevestigd of niet: aantal, winst, verlies, open, winrate en
gemiddelde R (bruto, zonder kosten; take telt als de afstand tot take gedeeld door de
stopafstand, stop als -1). Zelfde auto_outcome als signals_winrate.py. Alleen lezen.

Draai met: DATABASE_PATH=/opt/crypto-alerts/data/trading.db python3 scripts/signals_by_source.py"""
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db

with db.session() as conn:
    rows = conn.execute(
        """SELECT message_id, trade_type, technical_confirmed, auto_outcome, price, stop_loss, take_profit
           FROM signals WHERE is_practice = 0"""
    ).fetchall()

groups: dict[tuple, dict] = defaultdict(lambda: {"tp": 0, "sl": 0, "open": 0, "other": 0, "r": []})
for r in rows:
    source = "discord" if r["message_id"] is not None else "scan"
    g = groups[(source, r["trade_type"], "bevestigd" if r["technical_confirmed"] else "niet bevestigd")]
    outcome = r["auto_outcome"] or "open"
    risk = abs((r["price"] or 0) - (r["stop_loss"] or 0))
    if outcome == "take_profit" and risk > 0 and r["take_profit"] is not None:
        g["tp"] += 1
        g["r"].append(abs(r["take_profit"] - r["price"]) / risk)
    elif outcome == "stop_loss":
        g["sl"] += 1
        g["r"].append(-1.0)
    elif outcome == "open":
        g["open"] += 1
    else:
        g["other"] += 1

print(f"{'bron':<8}{'type':<13}{'status':<16}{'afgerond':>9}{'win':>5}{'verlies':>8}{'open':>6}{'overig':>7}{'winrate':>9}{'gem. R':>9}")
for (source, trade_type, status), g in sorted(groups.items()):
    done = g["tp"] + g["sl"]
    wr = f"{g['tp'] / done * 100:.0f}%" if done else "-"
    avg = f"{sum(g['r']) / len(g['r']):+.2f}" if g["r"] else "-"
    print(f"{source:<8}{trade_type:<13}{status:<16}{done:>9}{g['tp']:>5}{g['sl']:>8}{g['open']:>6}{g['other']:>7}{wr:>9}{avg:>9}")
