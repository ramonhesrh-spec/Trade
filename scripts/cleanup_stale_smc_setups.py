"""Eenmalige opschoning: past de twee regels uit de SMC-bugfix (verouderd
na 24 uur, doel dat door TARGET_MARGIN_PCT voorbij de zone belandt) met
terugwerkende kracht toe op setups die al vóór de fix zijn aangemaakt.
market_scanner._check_smc_setup bewaakt dit voortaan zelf voor nieuwe
setups, maar een rij die al in de database stond wordt daar nooit
opnieuw tegen getoetst. Puur diagnostisch/opruimend, geen wijziging aan
de detectielogica zelf. Draai dit handmatig op de VPS, één keer."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, repo
from app.market_scanner import SMC_SETUP_MAX_AGE_HOURS, TARGET_MARGIN_PCT

now = datetime.now(timezone.utc)
forming = repo.list_forming_smc_setups()
print(f"{len(forming)} bouwende SMC-setup(s) gevonden.\n")

invalidated = 0
for setup in forming:
    age_hours = (now - datetime.fromisoformat(setup["created_at"])).total_seconds() / 3600
    if age_hours > SMC_SETUP_MAX_AGE_HOURS:
        repo.invalidate_smc_setup(setup["id"])
        invalidated += 1
        print(f"  {setup['coin']} {setup['direction']}: {age_hours:.0f} uur oud, ongeldig gemaakt (verouderd)")
        continue

    target_sign = 1 if setup["direction"] == "short" else -1
    projected_take_profit = setup["liquidity_target"] * (1 + target_sign * TARGET_MARGIN_PCT / 100)
    doel_voorbij_zone = (
        (setup["direction"] == "short" and projected_take_profit >= setup["zone_low"])
        or (setup["direction"] == "long" and projected_take_profit <= setup["zone_high"])
    )
    if doel_voorbij_zone:
        repo.invalidate_smc_setup(setup["id"])
        invalidated += 1
        print(
            f"  {setup['coin']} {setup['direction']}: doel {projected_take_profit:.4f} ligt niet voorbij "
            f"de zone {setup['zone_low']:.4f}-{setup['zone_high']:.4f}, ongeldig gemaakt"
        )
    else:
        print(f"  {setup['coin']} {setup['direction']}: OK, blijft staan")

print(f"\n{invalidated} setup(s) ongeldig gemaakt van de {len(forming)}.")
