"""Eenmalige opschoning: past de regels uit de SMC-bugfixes (verouderd na
24 uur, stop/doel die door STOP_MARGIN_PCT/TARGET_MARGIN_PCT niet voorbij
de zone belanden) met terugwerkende kracht toe op setups die al vóór de
fix zijn aangemaakt. market_scanner._check_smc_setup bewaakt dit voortaan
zelf voor nieuwe setups, maar een rij die al in de database stond wordt
daar nooit opnieuw tegen getoetst. Puur diagnostisch/opruimend, geen
wijziging aan de detectielogica zelf. Draai dit handmatig op de VPS,
elke keer opnieuw als er weer een verdachte setup gemeld wordt."""
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, repo
from app.market_scanner import SMC_SETUP_MAX_AGE_HOURS, STOP_MARGIN_PCT, TARGET_MARGIN_PCT

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

    sign = 1 if setup["direction"] == "short" else -1
    projected_stop_loss = setup["sweep_price"] * (1 + sign * STOP_MARGIN_PCT / 100)
    projected_take_profit = setup["liquidity_target"] * (1 + sign * TARGET_MARGIN_PCT / 100)
    stop_niet_voorbij_zone = (
        (setup["direction"] == "short" and projected_stop_loss <= setup["zone_high"])
        or (setup["direction"] == "long" and projected_stop_loss >= setup["zone_low"])
    )
    doel_niet_voorbij_zone = (
        (setup["direction"] == "short" and projected_take_profit >= setup["zone_low"])
        or (setup["direction"] == "long" and projected_take_profit <= setup["zone_high"])
    )
    if stop_niet_voorbij_zone or doel_niet_voorbij_zone:
        repo.invalidate_smc_setup(setup["id"])
        invalidated += 1
        print(
            f"  {setup['coin']} {setup['direction']}: stop {projected_stop_loss:.4f} / doel {projected_take_profit:.4f} "
            f"liggen niet voorbij de zone {setup['zone_low']:.4f}-{setup['zone_high']:.4f}, ongeldig gemaakt"
        )
    else:
        print(f"  {setup['coin']} {setup['direction']}: OK, blijft staan")

print(f"\n{invalidated} setup(s) ongeldig gemaakt van de {len(forming)}.")
