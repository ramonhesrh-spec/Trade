"""Zelfcheck: controleert of alle systemd-onderdelen die HesPulse nodig
heeft (bot, dashboard, back-up, levensteken, niveau-check) echt actief en
enabled zijn.

Ontstaan naar aanleiding van een concrete fout: de niveau-check-timer en
de back-up/levensteken-timers bleken op de VPS nooit geïnstalleerd te zijn
geweest, zonder dat iemand dat opmerkte tot een gebruiker er zelf naar
vroeg. Dit script legt voortaan een admin-only notifications-rij vast
zodra iets ontbreekt, in plaats van te wachten tot iemand het toevallig
opmerkt. Wordt aangeroepen via een systemd timer, zie
deploy/crypto-health-check.service en .timer.
"""
import asyncio
import logging
import subprocess

from app import repo

logger = logging.getLogger("health_check")

UNITS = [
    "crypto-bot",
    "crypto-web",
    "crypto-backup.timer",
    "crypto-heartbeat.timer",
    "crypto-level-check.timer",
]


def _systemctl(*args: str) -> str:
    result = subprocess.run(["systemctl", *args], capture_output=True, text=True)
    return result.stdout.strip()


def check_units() -> list[str]:
    """Geeft een lijst met leesbare probleemregels terug, leeg als alle
    onderdelen in orde zijn."""
    problems = []
    for unit in UNITS:
        active = _systemctl("is-active", unit)
        if active != "active":
            problems.append(f"{unit}: status is '{active}', verwacht 'active'")
            continue
        enabled = _systemctl("is-enabled", unit)
        if enabled != "enabled":
            problems.append(f"{unit}: is niet enabled (status: '{enabled}'), overleeft een reboot niet")
    return problems


async def run() -> None:
    problems = check_units()
    if not problems:
        logger.info("Zelfcheck: alle %d systeemonderdelen zijn actief en enabled", len(UNITS))
        return

    logger.warning("Zelfcheck vond %d probleem/problemen: %s", len(problems), "; ".join(problems))
    try:
        repo.create_notification(
            None, "system_health", "HesPulse zelfcheck",
            "; ".join(problems), None,
        )
    except Exception:
        logger.exception("Kon zelfcheck-melding niet opslaan")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run())
