-- Schema voor het crypto alertsysteem.

-- Gebruikers van het dashboard. Geen open registratie, accounts worden
-- toegevoegd via scripts/create_user.py. Iedereen ziet dezelfde signalen,
-- maar houdt zijn eigen logboek bij met een eigen portfolio en risico.
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    portfolio_eur REAL NOT NULL DEFAULT 0,
    risk_percent REAL NOT NULL DEFAULT 1.0,
    telegram_chat_id TEXT,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    has_image INTEGER NOT NULL DEFAULT 0,
    image_paths TEXT,
    coin TEXT,
    direction TEXT,
    category TEXT,
    unclear INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    processed_at TEXT
);

-- Bron niveaus, overgenomen uit Discord afbeeldingen. Altijd bewaard,
-- ongeacht categorie van het bericht.
CREATE TABLE IF NOT EXISTS source_levels (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id),
    coin TEXT NOT NULL,
    price_level REAL NOT NULL,
    pattern_name TEXT,
    source_label TEXT NOT NULL DEFAULT 'analyse Discord',
    created_at TEXT NOT NULL
);

-- Coins die genoemd zijn in verwerkte berichten, geeft een eigen
-- grafiekpagina in het dashboard.
CREATE TABLE IF NOT EXISTS coins (
    symbol TEXT PRIMARY KEY,
    market TEXT NOT NULL,
    added_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1
);

-- Verwerkte day trading signalen: gedeelde technische toetsing. Objectief,
-- hetzelfde voor iedereen die het dashboard gebruikt.
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id),
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
    technical_confirmed INTEGER NOT NULL DEFAULT 0,
    confidence TEXT NOT NULL,
    reason TEXT,
    stop_loss REAL,
    take_profit REAL,
    created_at TEXT NOT NULL
);

-- Eigen trade logboek per gebruiker en per signaal: eigen risicobedrag
-- (op basis van eigen portfolio), eigen status, eigen entry/exit en
-- notitie, en of de Telegram melding naar deze gebruiker is verstuurd.
CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL REFERENCES signals(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    risk_eur REAL,
    telegram_sent INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'nieuw',
    entry_price REAL,
    exit_price REAL,
    exit_time TEXT,
    result_eur REAL,
    result_pct REAL,
    note TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (signal_id, user_id)
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Voor het beperken van het aantal inlogpogingen, per gebruikersnaam.
CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    success INTEGER NOT NULL,
    ip_address TEXT
);
