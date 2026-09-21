"""Periodieke check: is een factor de laatste tijd structureel minder
betrouwbaar dan zijn eigen historische gemiddelde? scripts/backtest_factors.py
berekent dit al eenmalig en handmatig; dit script draait dezelfde
berekening periodiek en waarschuwt zelf in plaats van dat iemand het
script moet onthouden te draaien.

Draai met: python3 scripts/factor_drift_check.py
Bedoeld voor een systemd-timer, zie deploy/crypto-factor-check.timer.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, repo
from scripts.backtest_factors import compute_factor_pass_rates  # hergebruik, niet dupliceren

FACTOR_DRIFT_LOOKBACK = 50
FACTOR_DRIFT_THRESHOLD_PP = 15.0


def run() -> None:
    db.init_db()
    rates = compute_factor_pass_rates(lookback=FACTOR_DRIFT_LOOKBACK)  # {factor_naam: (recente_pass_rate, historische_pass_rate)}
    for name, (recent, historical) in rates.items():
        if historical - recent >= FACTOR_DRIFT_THRESHOLD_PP:
            repo.create_notification(
                None, "factor_drift",
                f"Factor '{name}' wijkt af",
                f"Historisch {historical:.0f}% raak, laatste {FACTOR_DRIFT_LOOKBACK} signalen nog maar "
                f"{recent:.0f}%. Kan wijzen op een marktverandering.",
                None,
            )


if __name__ == "__main__":
    run()
