"""Dagelijkse back-up van de sqlite database naar een aparte locatie.
Wordt aangeroepen via een cron job of systemd timer, zie deploy/.

Naast de lokale kopie op de VPS zelf (in BACKUP_PATH) wordt de back-up ook
naar een externe locatie gestuurd via rsync over SSH, als BACKUP_REMOTE is
ingesteld in .env. Zonder die externe kopie ben je bij schijfschade op de
VPS alsnog alles kwijt, lokale back-ups helpen dan niet. Zie de README
voor hoe je dit instelt.
"""
import logging
import sqlite3
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from app import config

logger = logging.getLogger("backup")


def run_backup() -> Path:
    Path(config.BACKUP_PATH).mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    dest = Path(config.BACKUP_PATH) / f"trading_{timestamp}.db"

    source = sqlite3.connect(config.DATABASE_PATH)
    backup_conn = sqlite3.connect(dest)
    with backup_conn:
        source.backup(backup_conn)
    backup_conn.close()
    source.close()

    _cleanup_old_backups(keep=30)
    _push_offsite(dest)
    return dest


def _cleanup_old_backups(keep: int) -> None:
    backups = sorted(Path(config.BACKUP_PATH).glob("trading_*.db"))
    for old in backups[:-keep]:
        old.unlink()


def _push_offsite(dest: Path) -> None:
    if not config.BACKUP_REMOTE:
        logger.info("BACKUP_REMOTE niet ingesteld, back-up blijft alleen lokaal op de VPS")
        return
    try:
        subprocess.run(
            ["rsync", "-az", "--timeout=30", str(dest), config.BACKUP_REMOTE],
            check=True, capture_output=True, text=True, timeout=60,
        )
        logger.info("Back-up naar externe locatie gestuurd: %s", config.BACKUP_REMOTE)
    except Exception:
        logger.exception("Back-up naar externe locatie is mislukt, lokale kopie staat er nog wel")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    dest = run_backup()
    print(f"Back-up gemaakt: {dest}")
