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
    if "adx" not in existing:
        conn.execute("ALTER TABLE signals ADD COLUMN adx REAL")
    if "atr_avg20" not in existing:
        conn.execute("ALTER TABLE signals ADD COLUMN atr_avg20 REAL")
    if "plain_explanation" not in existing:
        conn.execute("ALTER TABLE signals ADD COLUMN plain_explanation TEXT")
    if "trade_type" not in existing:
        conn.execute("ALTER TABLE signals ADD COLUMN trade_type TEXT NOT NULL DEFAULT 'day_trading'")

    # Moet NA de vijf ALTER TABLE-guards hierboven staan (niet ervoor): het
    # rebuild-blok hieronder selecteert is_practice/adx/atr_avg20/
    # plain_explanation/trade_type rechtstreeks uit de oude signals-tabel
    # (CREATE TABLE signals_new / INSERT ... SELECT), dus die kolommen
    # moeten al bestaan op een oude database die ze nog mist — anders
    # faalt de SELECT. De echte beperking is dat dit blok moet draaien
    # vóór elke instructie die een impliciete transactie opent (de PRAGMA
    # foreign_keys hieronder heeft daarna geen effect meer): ALTER TABLE
    # ... ADD COLUMN doet dat niet (Python's sqlite3-module opent alleen
    # impliciet een transactie vóór INSERT/UPDATE/DELETE/REPLACE), dus de
    # ALTER TABLE-guards hierboven mogen prima eerst draaien. signals_sql
    # is None op een gloednieuwe database (schema.sql zelf heeft dan al de
    # nullable variant, zie Step 1), dus dit hele blok is dan een no-op.
    signals_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'signals'"
    ).fetchone()
    if signals_sql and "message_id INTEGER NOT NULL" in signals_sql["sql"]:
        conn.execute("PRAGMA foreign_keys=OFF")
        # De vijf statements tot en met de drie CREATE INDEX-calls hieronder
        # zitten expliciet in één transactie: zonder dit commit sqlite3 elke
        # DDL-statement apart (Python's sqlite3-module auto-commit't vóór
        # elke DDL), dus een crash tussen DROP TABLE signals en de ALTER
        # TABLE RENAME zou de database zonder signals-tabel achterlaten
        # (data intact onder signals_new, maar handmatig herstel nodig) —
        # niet acceptabel op een productiedatabase met echte gebruikers en
        # echt geld. De PRAGMA's blijven bewust BUITEN dit blok: SQLite
        # negeert een PRAGMA foreign_keys-wijziging stilzwijgend zodra een
        # transactie al open staat.
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("""
            CREATE TABLE signals_new (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message_id INTEGER REFERENCES messages(id),
                coin TEXT NOT NULL,
                direction TEXT NOT NULL,
                category TEXT NOT NULL,
                price REAL,
                rsi REAL,
                macd REAL,
                macd_signal REAL,
                volume_ratio REAL,
                ema9 REAL,
                ema21 REAL,
                atr REAL,
                atr_avg20 REAL,
                adx REAL,
                technical_confirmed INTEGER NOT NULL DEFAULT 0,
                confidence TEXT NOT NULL,
                reason TEXT,
                stop_loss REAL,
                take_profit REAL,
                context_note TEXT,
                is_practice INTEGER NOT NULL DEFAULT 0,
                trade_type TEXT NOT NULL DEFAULT 'day_trading',
                plain_explanation TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO signals_new (
                id, message_id, coin, direction, category, price, rsi, macd,
                macd_signal, volume_ratio, ema9, ema21, atr, atr_avg20, adx,
                technical_confirmed, confidence, reason, stop_loss, take_profit,
                context_note, is_practice, trade_type, plain_explanation, created_at
            )
            SELECT
                id, message_id, coin, direction, category, price, rsi, macd,
                macd_signal, volume_ratio, ema9, ema21, atr, atr_avg20, adx,
                technical_confirmed, confidence, reason, stop_loss, take_profit,
                context_note, is_practice, trade_type, plain_explanation, created_at
            FROM signals
        """)
        conn.execute("DROP TABLE signals")
        conn.execute("ALTER TABLE signals_new RENAME TO signals")
        # Deze drie indexen staan ook gewoon in schema.sql (met dezelfde
        # IF NOT EXISTS), maar dat script draait via executescript() vóór
        # dit migratieblok — de DROP TABLE hierboven vernietigt een index
        # samen met zijn tabel, dus ze moeten hier, ná de rebuild, opnieuw
        # aangemaakt worden. Zonder dit blok verdwijnen ze stilzwijgend van
        # een bestaande database zodra deze migratie één keer draait.
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_coin ON signals(coin)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_coin_direction ON signals(coin, direction)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_message_id ON signals(message_id)")
        conn.execute("COMMIT")
        conn.execute("PRAGMA foreign_keys=ON")

    existing_messages = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
    if "discord_user_id" not in existing_messages:
        conn.execute("ALTER TABLE messages ADD COLUMN discord_user_id TEXT")
    if "message_summary" not in existing_messages:
        conn.execute("ALTER TABLE messages ADD COLUMN message_summary TEXT")
    if "price_at_receipt" not in existing_messages:
        conn.execute("ALTER TABLE messages ADD COLUMN price_at_receipt REAL")
    if "narrative_id" not in existing_messages:
        conn.execute("ALTER TABLE messages ADD COLUMN narrative_id INTEGER REFERENCES coin_narratives(id)")
    # Index hier aanmaken, nooit in schema.sql: dat script draait via
    # executescript() vóór deze migratie, dus op een bestaande database
    # zonder de kolom hierboven zou die CREATE INDEX meteen crashen omdat
    # de kolom er op dat moment nog niet is. IF NOT EXISTS maakt dit
    # onvoorwaardelijk hier zetten goedkoop en veilig, ook bij elke herstart.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_discord_user_id ON messages(discord_user_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_messages_narrative_id ON messages(narrative_id)")

    existing_source_levels = {row["name"] for row in conn.execute("PRAGMA table_info(source_levels)")}
    if "dismissed" not in existing_source_levels:
        conn.execute("ALTER TABLE source_levels ADD COLUMN dismissed INTEGER NOT NULL DEFAULT 0")

    existing_journal = {row["name"] for row in conn.execute("PRAGMA table_info(journal_entries)")}
    if "stop_loss_override" not in existing_journal:
        conn.execute("ALTER TABLE journal_entries ADD COLUMN stop_loss_override REAL")
    if "take_profit_override" not in existing_journal:
        conn.execute("ALTER TABLE journal_entries ADD COLUMN take_profit_override REAL")
    if "position_size_override" not in existing_journal:
        conn.execute("ALTER TABLE journal_entries ADD COLUMN position_size_override REAL")
    if "evaluation_id" not in existing_journal:
        conn.execute("ALTER TABLE journal_entries ADD COLUMN evaluation_id INTEGER REFERENCES prop_evaluations(id)")
    if "entry_time" not in existing_journal:
        conn.execute("ALTER TABLE journal_entries ADD COLUMN entry_time TEXT")
    if "position_size" not in existing_journal:
        conn.execute("ALTER TABLE journal_entries ADD COLUMN position_size REAL")
    # Index hier, nooit in schema.sql: op een bestaande database zonder de
    # kolom hierboven zou die CREATE INDEX meteen crashen, zie het
    # narrative_id-precedent verderop in dit bestand.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_evaluation_id ON journal_entries(evaluation_id)")

    existing_users = {row["name"] for row in conn.execute("PRAGMA table_info(users)")}
    if "quiet_hours_start" not in existing_users:
        conn.execute("ALTER TABLE users ADD COLUMN quiet_hours_start TEXT")
    if "quiet_hours_end" not in existing_users:
        conn.execute("ALTER TABLE users ADD COLUMN quiet_hours_end TEXT")
    if "confirm_threshold_pct" not in existing_users:
        conn.execute(
            "ALTER TABLE users ADD COLUMN confirm_threshold_pct REAL NOT NULL DEFAULT 60.0"
        )
    if "confirm_threshold_set_at" not in existing_users:
        conn.execute("ALTER TABLE users ADD COLUMN confirm_threshold_set_at TEXT")

    existing_signals = {row["name"] for row in conn.execute("PRAGMA table_info(signals)")}
    if "pass_pct" not in existing_signals:
        conn.execute("ALTER TABLE signals ADD COLUMN pass_pct REAL")
    if "hard_gates_ok" not in existing_signals:
        conn.execute("ALTER TABLE signals ADD COLUMN hard_gates_ok INTEGER NOT NULL DEFAULT 1")
    if "auto_outcome" not in existing_signals:
        conn.execute("ALTER TABLE signals ADD COLUMN auto_outcome TEXT")
    if "auto_outcome_at" not in existing_signals:
        conn.execute("ALTER TABLE signals ADD COLUMN auto_outcome_at TEXT")
    # Index hier aanmaken, nooit in schema.sql: op het moment dat schema.sql
    # voor een NIEUWE database draait bestaat de kolom al, maar op een
    # bestaande database bestond hij een regel geleden nog niet. IF NOT EXISTS
    # maakt dit onvoorwaardelijk hier zetten goedkoop en veilig, ook bij elke herstart.
    conn.execute(
        "CREATE INDEX IF NOT EXISTS idx_signals_auto_outcome_pending "
        "ON signals(auto_outcome) WHERE auto_outcome IS NULL"
    )

    existing_coins = {row["name"] for row in conn.execute("PRAGMA table_info(coins)")}
    if "note" not in existing_coins:
        conn.execute("ALTER TABLE coins ADD COLUMN note TEXT")
    if "last_scan_direction" not in existing_coins:
        conn.execute("ALTER TABLE coins ADD COLUMN last_scan_direction TEXT")
    if "last_scan_direction_count" not in existing_coins:
        conn.execute("ALTER TABLE coins ADD COLUMN last_scan_direction_count INTEGER NOT NULL DEFAULT 0")
    if "last_breakout_retest_key" not in existing_coins:
        conn.execute("ALTER TABLE coins ADD COLUMN last_breakout_retest_key TEXT")
    if "last_trendline_retest_key" not in existing_coins:
        conn.execute("ALTER TABLE coins ADD COLUMN last_trendline_retest_key TEXT")

    existing_prop_evaluations = {row["name"] for row in conn.execute("PRAGMA table_info(prop_evaluations)")}
    if "danger_alert_sent" not in existing_prop_evaluations:
        conn.execute("ALTER TABLE prop_evaluations ADD COLUMN danger_alert_sent INTEGER NOT NULL DEFAULT 0")


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
