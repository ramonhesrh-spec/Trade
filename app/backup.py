"""Dagelijkse back-up van de sqlite database naar een aparte locatie.
Wordt aangeroepen via een cron job of systemd timer, zie deploy/.
"""
import shutil
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from app import config


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
    return dest


def _cleanup_old_backups(keep: int) -> None:
    backups = sorted(Path(config.BACKUP_PATH).glob("trading_*.db"))
    for old in backups[:-keep]:
        old.unlink()


if __name__ == "__main__":
    dest = run_backup()
    print(f"Back-up gemaakt: {dest}")
