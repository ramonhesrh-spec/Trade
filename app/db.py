"""Sqlite database helpers. Eén connectie per aanroep, WAL voor gelijktijdige
lezers (dashboard) en schrijvers (bot)."""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app import config

SCHEMA_PATH = Path(__file__).resolve().parent / "schema.sql"


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    Path(config.DATABASE_PATH).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DATABASE_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def session():
    conn = get_conn()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with session() as conn:
        conn.executescript(SCHEMA_PATH.read_text())
        _migrate(conn)


def _migrate(conn: sqlite3.Connection) -> None:
    """CREATE TABLE IF NOT EXISTS raakt geen bestaande tabel aan, dus een
    nieuwe kolom op een tabel die al bestaat moet hier expliciet bij. Elke
    migratie is idempotent: al aanwezig is geen probleem."""
    existing = {row["name"] for row in conn.execute("PRAGMA table_info(signals)")}
    if "is_practice" not in existing:
        conn.execute("ALTER TABLE signals ADD COLUMN is_practice INTEGER NOT NULL DEFAULT 0")


def get_setting(key: str, default: str = "") -> str:
    with session() as conn:
        row = conn.execute(
            "SELECT value FROM settings WHERE key = ?", (key,)
        ).fetchone()
        return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    with session() as conn:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )


if __name__ == "__main__":
    init_db()
    print(f"Database geinitialiseerd op {config.DATABASE_PATH}")
