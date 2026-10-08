"""Vertrouwen uit bewijs: per soort kans een status die alleen uit afgeronde trades komt. Pure functies.
In proef  = minder dan PROVEN_N afgeronde trades: te weinig om iets te zeggen, de balk toont hoever we zijn.
Bewezen   = minstens PROVEN_N afgeronde trades en een positief netto resultaat per trade.
Negatief  = minstens PROVEN_N afgeronde trades en geen positief netto resultaat; de motor hoort uit te gaan (zie should_disable)."""
from typing import Optional

PROVEN_N = 50
FIRST_LOOK_N = 10          # eerder tonen we geen percentage: 3 van 5 zegt niets


def status(entry: Optional[dict]) -> dict:
    n = entry["resolved"] if entry else 0
    avg = entry.get("avg_net") if entry else None
    wins = entry["wins"] if entry else 0
    base = {"n": n, "wins": wins, "avg_net": avg, "target": PROVEN_N, "progress": min(1.0, n / PROVEN_N)}
    if n < PROVEN_N:
        state, label = "proef", "In proef"
    elif avg is not None and avg > 0:
        state, label = "bewezen", "Bewezen"
    else:
        state, label = "negatief", "Negatief"
    return {**base, "state": state, "label": label, "text": describe(base, state)}


def describe(s: dict, state: str) -> str:
    n, wins, avg = s["n"], s["wins"], s["avg_net"]
    if n == 0:
        return f"Nog geen afgeronde trades. Een oordeel komt na {PROVEN_N}."
    if n < FIRST_LOOK_N:
        return f"{n} afgeronde {'trade' if n == 1 else 'trades'}. Te weinig om iets te zeggen, een oordeel komt na {PROVEN_N}."
    total = avg * n if avg is not None else 0.0
    core = f"{n} trades, {wins} raakten het doel, netto {total:+.1f}R"
    if state == "proef":
        return f"{core}. Nog {PROVEN_N - n} trades tot een oordeel."
    return f"{core}, gemiddeld {avg:+.2f}R per trade."
