-- Schema voor het crypto alertsysteem.

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

-- Verwerkte day trading signalen, met technische toetsing, risico en
-- Telegram melding, plus mijn eigen trade administratie.
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
    risk_eur REAL,
    telegram_sent INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,

    status TEXT NOT NULL DEFAULT 'nieuw',
    entry_price REAL,
    exit_price REAL,
    exit_time TEXT,
    result_eur REAL,
    result_pct REAL,
    note TEXT
);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Voor het beperken van het aantal inlogpogingen.
CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempted_at TEXT NOT NULL,
    success INTEGER NOT NULL,
    ip_address TEXT
);
