# Autonome Marktscan Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HesPulse scant zelf, elk uur, de dynamische coinlijst op day-trading-kansen, zonder dat een gebruiker eerst een Discord-bericht hoeft door te sturen — met een noodrem, een weekoverzicht, een BTC-vlak-rem, een verlies-cooldown, een herhaald-verlies-waarschuwing en een sterkte-ranking bij meerdere gelijktijdige kansen.

**Architecture:** Eén nieuwe periodieke taak (`app/market_scanner.py`, systemd-timer elk uur) die voor elke coin in de bestaande dynamische lijst zelf een richting bepaalt (trend) en de bestaande `signal_processor.process_day_trading_signal()` hergebruikt — geen tweede fan-out-implementatie. `signals.message_id` wordt nullable zodat een autonoom signaal zonder brongbericht kan bestaan; overal waar dat veld gebruikt wordt komt een fallback.

**Tech Stack:** Python 3, FastAPI/Jinja2 (web), python-telegram-bot, ccxt (Binance), SQLite (stdlib `sqlite3`), geen pytest — scratch-DB-scripts, zie CLAUDE.md.

**Spec:** `docs/superpowers/specs/2026-09-14-autonome-marktscan-design.md`

## Global Constraints

- Scanfrequentie: elk uur (`OnCalendar=hourly`), niet elke 4 uur.
- Richting: `"long" if ind.ema9 > ind.ema21 else "short"` — dezelfde trendregel als `indicators.basic_factors`.
- Meldingsdrempel: ongewijzigd `indicators.BASIC_CONFIRM_MIN_PASSED = 3` (van de 4 basisfactoren). Geen aparte, strengere eis voor autonome signalen.
- Alleen een BEVESTIGDE (hoog vertrouwen) autonome kans krijgt een Telegram-melding. Een afwijzing wordt niet gemeld.
- Coins: `repo.list_coins()`, de bestaande dynamische lijst. Geen aparte, vaste lijst.
- `signals.message_id` wordt nullable. Alleen deze tabel — `message_coin_results`, `source_levels`, `swing_watches` blijven `message_id NOT NULL`.
- Geen tweede fan-out-implementatie: de scan roept `signal_processor.process_day_trading_signal()` aan, met `message_id=None`.
- Geen per-gebruiker aan/uit-instelling voor de scan; wel één systeembrede noodrem-vlag (`market_scan_enabled` in de bestaande `settings`-tabel, default `"1"`).
- `BTC_FLAT_EMA_GAP_ATR_MULTIPLE = 0.3` (nieuwe constante in `app/indicators.py`).
- `AUTO_SCAN_LOSS_COOLDOWN_HOURS = 12` (nieuwe constante in `app/market_scanner.py`).
- Herhaald-verlies-waarschuwing bij ≥ 3 verliezen op rij (`consecutive_autonomous_losses(..., limit=3)`).
- Geen database-migratie nodig buiten de `signals.message_id`-wijziging: alle andere uitbreidingen gebruiken bestaande tabellen (`settings`) of puur berekende/transiënte waarden.
- Verificatie via scratch-DB-scripts (`DATABASE_PATH=/tmp/xxx.db python3 -c "..."` of een los scriptbestand), zoals CLAUDE.md voorschrijft — er is geen pytest-suite in deze repo.

---

### Task 1: `signals.message_id` nullable + repo.py fallback

**Files:**
- Modify: `app/schema.sql:137-166` (signals table)
- Modify: `app/db.py` (`_migrate()`)
- Modify: `app/repo.py:770-786` (`list_recent_signals`)
- Modify: `app/repo.py:900-928` (`_JOURNAL_SELECT`)

**Interfaces:**
- Consumes: niets van eerdere taken (dit is Task 1).
- Produces: `signals.message_id` is nullable in zowel een verse database (via `schema.sql`) als een bestaande database (via `_migrate()`). Elke dict die via `_JOURNAL_SELECT` of `list_recent_signals` wordt opgebouwd bevat voortaan een `message_id`-sleutel (mogelijk `None`) en een `message_summary` die nooit `None` is (fallback `"Zelf gedetecteerd door HesPulse"`). Latere taken (2, 3, 9) bouwen hierop voort.

- [ ] **Step 1: schema.sql aanpassen**

In `app/schema.sql`, regel 137-166, verander de `signals`-tabel: haal `NOT NULL` weg bij `message_id`.

```sql
CREATE TABLE IF NOT EXISTS signals (
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
    -- 'day_trading' of 'swing': welk mechanisme dit signaal produceerde.
    -- Swing-signalen komen uit een bewaakt bron-niveau (zie swing_watches),
    -- hebben geen hoog/laag vertrouwen-label (nog niet gevalideerd op deze
    -- tijdshorizon) en worden apart geteld in winrate/journaal.
    trade_type TEXT NOT NULL DEFAULT 'day_trading',
    plain_explanation TEXT,
    created_at TEXT NOT NULL
);
```

**Waarom:** een autonoom, door de marktscan ontdekt signaal heeft geen doorgestuurd Discord-bericht. Dit is alleen voor een VERSE database genoeg (`CREATE TABLE IF NOT EXISTS` raakt een bestaande tabel nooit aan) — Step 2 doet hetzelfde voor een bestaande database.

- [ ] **Step 2: migratie in db.py voor bestaande databases**

SQLite staat geen `ALTER TABLE ... ALTER COLUMN` toe om een `NOT NULL`-constraint te verwijderen. De officiële SQLite-aanpak (zie sqlite.org "Making Other Kinds Of Table Schema Changes"): een nieuwe tabel met het gewenste schema, data overzetten, oude tabel droppen, nieuwe tabel hernoemen — met `PRAGMA foreign_keys=OFF` er omheen (anders weigert SQLite de `DROP TABLE` zolang `journal_entries.signal_id` er nog naar verwijst).

In `app/db.py`, voeg dit blok toe als de EERSTE regel in `_migrate()`, vóór de bestaande `existing = {row["name"] for row in conn.execute("PRAGMA table_info(signals)")}`-regel. Dit MOET als eerste, vóór elke andere DML-achtige aanroep in deze functie: `PRAGMA foreign_keys` heeft geen effect zodra er al een (impliciete) transactie open staat, en de eerste `INSERT`/`UPDATE` in deze functie zou Python's sqlite3-module er automatisch een laten beginnen.

```python
def _migrate(conn: sqlite3.Connection) -> None:
    """CREATE TABLE IF NOT EXISTS raakt geen bestaande tabel aan, dus een
    nieuwe kolom op een tabel die al bestaat moet hier expliciet bij. Elke
    migratie is idempotent: al aanwezig is geen probleem."""
    # Moet als allereerste in deze functie staan: PRAGMA foreign_keys heeft
    # geen effect zodra er al een transactie open staat, en zodra hieronder
    # een INSERT/UPDATE/DELETE draait begint Python's sqlite3-module er
    # automatisch een. signals_sql is None op een gloednieuwe database
    # (schema.sql zelf heeft dan al de nullable variant, zie Step 1), dus
    # dit hele blok is dan een no-op.
    signals_sql = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'signals'"
    ).fetchone()
    if signals_sql and "message_id INTEGER NOT NULL" in signals_sql["sql"]:
        conn.execute("PRAGMA foreign_keys=OFF")
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
        # Deze drie indexen bestonden op de oude tabel en verdwijnen mee met
        # de DROP TABLE hierboven; ze horen niet in schema.sql (die draait
        # via executescript() vóór dit migratieblok, dus IF NOT EXISTS zou
        # daar nooit meer opnieuw uitgevoerd worden op een bestaande db).
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_coin ON signals(coin)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_coin_direction ON signals(coin, direction)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_signals_message_id ON signals(message_id)")
        conn.execute("PRAGMA foreign_keys=ON")

    existing = {row["name"] for row in conn.execute("PRAGMA table_info(signals)")}
```

Laat de rest van `_migrate()` (de bestaande `if "is_practice" not in existing: ...` regels en alles daarna) ongewijzigd staan — alleen de `existing = {...}`-regel blijft, direct na het nieuwe blok.

- [ ] **Step 2b: migratie handmatig verifiëren tegen een scratch-database met bestaande data**

Schrijf `/tmp/claude_scratch/task1_migrate_check.py`:

```python
import os
os.environ["DATABASE_PATH"] = "/tmp/task1_migrate.db"
import sqlite3
from pathlib import Path
from app import config, db

# Simuleer een BESTAANDE database: schema met de OUDE NOT NULL-constraint,
# handmatig aangemaakt (niet via schema.sql, dat is nu al de nieuwe versie).
Path(config.DATABASE_PATH).unlink(missing_ok=True)
conn = sqlite3.connect(config.DATABASE_PATH)
conn.execute("""
    CREATE TABLE messages (
        id INTEGER PRIMARY KEY AUTOINCREMENT, raw_text TEXT NOT NULL, created_at TEXT NOT NULL
    )
""")
conn.execute("""
    CREATE TABLE signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id INTEGER NOT NULL REFERENCES messages(id),
        coin TEXT NOT NULL, direction TEXT NOT NULL, category TEXT NOT NULL,
        price REAL, rsi REAL, macd REAL, macd_signal REAL, volume_ratio REAL,
        ema9 REAL, ema21 REAL, atr REAL, atr_avg20 REAL, adx REAL,
        technical_confirmed INTEGER NOT NULL DEFAULT 0, confidence TEXT NOT NULL,
        reason TEXT, stop_loss REAL, take_profit REAL, context_note TEXT,
        is_practice INTEGER NOT NULL DEFAULT 0, trade_type TEXT NOT NULL DEFAULT 'day_trading',
        plain_explanation TEXT, created_at TEXT NOT NULL
    )
""")
conn.execute("CREATE TABLE journal_entries (id INTEGER PRIMARY KEY AUTOINCREMENT, signal_id INTEGER NOT NULL REFERENCES signals(id))")
conn.execute("INSERT INTO messages (raw_text, created_at) VALUES ('test bericht', '2026-01-01T00:00:00+00:00')")
conn.execute("""INSERT INTO signals (message_id, coin, direction, category, confidence, created_at)
                 VALUES (1, 'BTC', 'long', 'day_trading', 'hoog vertrouwen', '2026-01-01T00:00:00+00:00')""")
conn.execute("INSERT INTO journal_entries (signal_id) VALUES (1)")
conn.commit()
conn.close()

# init_db() draait schema.sql (raakt de bestaande signals-tabel niet aan
# via CREATE TABLE IF NOT EXISTS) en dan _migrate(), die de rebuild moet
# uitvoeren.
db.init_db()

with db.session() as c:
    row = c.execute("SELECT * FROM signals WHERE id = 1").fetchone()
    assert row["coin"] == "BTC", "bestaande rij (id=1) moet behouden blijven"
    assert row["message_id"] == 1, "message_id van de bestaande rij moet ongewijzigd blijven"
    je = c.execute("SELECT * FROM journal_entries WHERE signal_id = 1").fetchone()
    assert je is not None, "FK-koppeling journal_entries -> signals(id) moet intact blijven na de rebuild"

    # Nu moet een INSERT met message_id=NULL slagen (was voorheen NOT NULL).
    c.execute("""INSERT INTO signals (message_id, coin, direction, category, confidence, created_at)
                 VALUES (NULL, 'ETH', 'short', 'day_trading', 'hoog vertrouwen', '2026-01-01T00:00:00+00:00')""")
    new_row = c.execute("SELECT * FROM signals WHERE coin = 'ETH'").fetchone()
    assert new_row["message_id"] is None

    sql = c.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='signals'").fetchone()["sql"]
    assert "NOT NULL" not in sql.split("message_id")[1].split(",")[0], "message_id mag geen NOT NULL meer hebben"

    idx = {r["name"] for r in c.execute("SELECT name FROM sqlite_master WHERE type='index' AND tbl_name='signals'")}
    assert {"idx_signals_coin", "idx_signals_coin_direction", "idx_signals_message_id"} <= idx

# Nogmaals init_db() aanroepen moet een no-op zijn (idempotent), geen fout.
db.init_db()
print("Task 1 Step 2b: OK")
```

Run: `.venv/bin/python3 /tmp/claude_scratch/task1_migrate_check.py`
Expected: `Task 1 Step 2b: OK`, geen AssertionError, geen exception.

- [ ] **Step 3: repo.py — list_recent_signals**

In `app/repo.py`, regel 774-786, verander `list_recent_signals`:

```python
def list_recent_signals(coin: str, limit: int = 3) -> list[dict]:
    """Gedeelde, echte signalen voor deze coin, hetzelfde voor iedereen.
    Oefentrades zijn persoonlijk en horen hier niet tussen, anders lijkt
    een handmatige oefening net een echt signaal voor alle gebruikers.
    LEFT JOIN naar messages: een autonoom, door de marktscan ontdekt
    signaal heeft geen message_id, zie app/market_scanner.py."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT s.*,
                      COALESCE(mcr.message_summary, m.message_summary, 'Zelf gedetecteerd door HesPulse')
                          AS message_summary
               FROM signals s
               LEFT JOIN messages m ON m.id = s.message_id
               LEFT JOIN message_coin_results mcr ON mcr.message_id = s.message_id AND mcr.coin = s.coin
               WHERE s.coin = ? AND s.is_practice = 0 ORDER BY s.created_at DESC LIMIT ?""",
            (coin.upper(), limit),
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 4: repo.py — _JOURNAL_SELECT**

In `app/repo.py`, regel 900-928, verander `_JOURNAL_SELECT`: voeg `s.message_id AS message_id` toe aan de SELECT-lijst, en maak de JOIN naar `messages` een LEFT JOIN met dezelfde fallback:

```python
_JOURNAL_SELECT = """
    SELECT
        je.id AS id, je.signal_id AS signal_id, je.user_id AS user_id,
        je.risk_eur AS risk_eur, je.telegram_sent AS telegram_sent,
        je.status AS status, je.entry_price AS entry_price,
        je.entry_time AS entry_time, je.position_size AS position_size,
        je.exit_price AS exit_price, je.exit_time AS exit_time,
        je.result_eur AS result_eur, je.result_pct AS result_pct,
        je.note AS note,
        je.position_size_override AS position_size_override,
        je.evaluation_id AS evaluation_id,
        s.coin AS coin, s.direction AS direction, s.category AS category,
        s.trade_type AS trade_type,
        s.price AS price,
        s.message_id AS message_id,
        COALESCE(je.stop_loss_override, s.stop_loss) AS stop_loss,
        COALESCE(je.take_profit_override, s.take_profit) AS take_profit,
        s.stop_loss AS stop_loss_default, s.take_profit AS take_profit_default,
        s.confidence AS confidence, s.technical_confirmed AS technical_confirmed,
        s.rsi AS rsi, s.ema9 AS ema9, s.ema21 AS ema21,
        s.macd AS macd, s.macd_signal AS macd_signal, s.volume_ratio AS volume_ratio,
        s.atr_avg20 AS atr_avg20, s.adx AS adx,
        s.reason AS reason, s.context_note AS context_note, s.created_at AS created_at,
        s.is_practice AS is_practice, s.plain_explanation AS plain_explanation,
        COALESCE(mcr.message_summary, m.message_summary, 'Zelf gedetecteerd door HesPulse')
            AS message_summary
    FROM journal_entries je
    JOIN signals s ON s.id = je.signal_id
    LEFT JOIN messages m ON m.id = s.message_id
    LEFT JOIN message_coin_results mcr ON mcr.message_id = s.message_id AND mcr.coin = s.coin
"""
```

**Waarom `s.message_id AS message_id` erbij:** zonder deze kolom heeft geen enkele journal-dict toegang tot `message_id`, en kan Task 9 (het "Zelf gedetecteerd"-label) daar niet op filteren. Deze ene wijziging in `_JOURNAL_SELECT` bereikt automatisch elke plek die deze constante gebruikt (dashboard, coin-pagina, Telegram-callbacks — zoek zelf niet naar losse queries, `_JOURNAL_SELECT` is de enige bron).

- [ ] **Step 5: repo.py-wijzigingen verifiëren**

Schrijf `/tmp/claude_scratch/task1_repo_check.py`:

```python
import os
os.environ["DATABASE_PATH"] = "/tmp/task1_repo.db"
from pathlib import Path
from app import config, db, repo

Path(config.DATABASE_PATH).unlink(missing_ok=True)
db.init_db()

user_id = repo.create_user("task1user", "hash", 1000.0, 2.0, telegram_chat_id="1")
message_id = repo.insert_message("test bericht over BTC", [])

# Community-signaal (message_id gezet).
signal_id_a = repo.insert_signal({
    "message_id": message_id, "coin": "BTC", "direction": "long", "category": "day_trading",
    "price": 50000.0, "confidence": "hoog vertrouwen", "technical_confirmed": 1,
    "reason": "✓ Trend: ok | ✓ Momentum: ok | ✓ RSI: ok | ✓ Volume: ok",
})
# Autonoom signaal (message_id leeg).
signal_id_b = repo.insert_signal({
    "message_id": None, "coin": "ETH", "direction": "short", "category": "day_trading",
    "price": 3000.0, "confidence": "hoog vertrouwen", "technical_confirmed": 1,
    "reason": "✓ Trend: ok | ✓ Momentum: ok | ✓ RSI: ok | ✗ Volume: te laag",
})
repo.create_journal_entry(signal_id_a, user_id, 20.0)
repo.create_journal_entry(signal_id_b, user_id, 20.0)

recent_btc = repo.list_recent_signals("BTC")
assert recent_btc[0]["message_summary"] not in (None, ""), "community-signaal moet een echte message_summary hebben"

recent_eth = repo.list_recent_signals("ETH")
assert recent_eth[0]["message_summary"] == "Zelf gedetecteerd door HesPulse"
assert recent_eth[0]["message_id"] is None

entries = repo.list_journal(user_id, status=None)
by_coin = {e["coin"]: e for e in entries}
assert by_coin["BTC"]["message_id"] == message_id
assert by_coin["ETH"]["message_id"] is None
assert by_coin["ETH"]["message_summary"] == "Zelf gedetecteerd door HesPulse"

print("Task 1 Step 5: OK")
```

Run: `.venv/bin/python3 /tmp/claude_scratch/task1_repo_check.py`
Expected: `Task 1 Step 5: OK`

- [ ] **Step 6: commit**

```bash
git add app/schema.sql app/db.py app/repo.py
git commit -m "signals.message_id nullable: basis voor autonome signalen zonder brongbericht"
```

---

### Task 2: `process_day_trading_signal` accepteert `message_id=None` + `notify_on_update`

**Files:**
- Modify: `app/signal_processor.py` (`process_day_trading_signal`, `_notify_signal_update`-aanroep)

**Interfaces:**
- Consumes: Task 1's nullable `signals.message_id` en `_JOURNAL_SELECT`-uitbreiding.
- Produces: `process_day_trading_signal(message_id: int | None, interp: Interpretation, notify_on_update: bool = True) -> None`. Task 3 (de scanner) roept dit aan met `message_id=None, notify_on_update=False`. Het bestaande aanroeppad (`_process_one_coin` in `handle_message`) blijft ongewijzigd werken (`message_id` altijd een int, `notify_on_update` op zijn default `True`).

- [ ] **Step 1: signature en message-afhankelijke regels**

In `app/signal_processor.py`, zoek de functiedefinitie `async def process_day_trading_signal(message_id: int, interp: Interpretation) -> None:` (rond regel 668) en verander naar:

```python
async def process_day_trading_signal(
    message_id: int | None, interp: Interpretation, notify_on_update: bool = True,
) -> None:
```

Zoek de regel `message_levels = [lvl["price_level"] for lvl in repo.list_source_levels_for_message(message_id, interp.coin)]` (rond regel 703) en verander naar:

```python
    # Geen bericht (autonoom marktscan-signaal, zie app/market_scanner.py)
    # betekent geen bron-niveaus om mee te wegen — die komen altijd uit een
    # gedeeld screenshot. De SR-zone-niveaus (zone_levels, hieronder)
    # blijven wel gewoon meetellen, die komen niet uit een bericht.
    message_levels = (
        [lvl["price_level"] for lvl in repo.list_source_levels_for_message(message_id, interp.coin)]
        if message_id is not None else []
    )
```

- [ ] **Step 2: notify_on_update bij een al open signaal**

Zoek dit blok (rond regel 788-796):

```python
    existing = repo.find_open_signal(interp.coin, interp.direction)

    if existing:
        signal_id = existing["id"]
        repo.update_signal(signal_id, signal_data)
        logger.info("Signaal %s bijgewerkt (was al open voor %s %s), bevestigd=%s",
                    signal_id, interp.coin, interp.direction, confirmed)
        await _notify_signal_update(signal_id, signal_data)
        return
```

Verander de laatste twee regels naar:

```python
        if notify_on_update:
            await _notify_signal_update(signal_id, signal_data)
        return
```

**Waarom:** `repo.update_signal(...)` gebeurt ALTIJD (de database blijft actueel, zichtbaar op het dashboard), alleen de Telegram-melding wordt overgeslagen als `notify_on_update=False`. De marktscan roept met `notify_on_update=False` aan zodat een coin die hij elk uur opnieuw bevestigt niet elk uur een nieuw Telegram-bericht stuurt (zie spec, sectie "Wijzigingen aan bestaande code"). Een community-bericht (`_process_one_coin` → deze functie, ongewijzigde aanroep, dus `notify_on_update` op zijn default `True`) blijft altijd een update-melding sturen.

- [ ] **Step 3: verifiëren dat het bestaande community-pad ongewijzigd blijft werken**

Schrijf `/tmp/claude_scratch/task2_check.py`:

```python
import asyncio
import os
os.environ["DATABASE_PATH"] = "/tmp/task2.db"
from pathlib import Path
from unittest.mock import patch, AsyncMock
import pandas as pd

from app import config, db, repo
from app.anthropic_interpret import Interpretation
from app import signal_processor

Path(config.DATABASE_PATH).unlink(missing_ok=True)
db.init_db()

user_id = repo.create_user("task2user", "hash", 1000.0, 2.0, telegram_chat_id="1")
message_id = repo.insert_message("test bericht over BTC long", [])

n = 60
df = pd.DataFrame({
    "timestamp": pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC"),
    "open": [100.0 + i * 0.5 for i in range(n)],
    "high": [101.0 + i * 0.5 for i in range(n)],
    "low": [99.0 + i * 0.5 for i in range(n)],
    "close": [100.5 + i * 0.5 for i in range(n)],
    "volume": [1000.0] * n,
})

with patch("app.coinlist.ensure_coin_tracked", return_value=(True, False)), \
     patch("app.exchange.fetch_ohlcv", return_value=df), \
     patch("app.explain.explain_signal", return_value=""), \
     patch("app.chart_image.render_signal_chart", return_value=b""), \
     patch("app.telegram_notify.send_signal", new_callable=AsyncMock) as mock_send:
    interp = Interpretation(coin="BTC", direction="long", category="day_trading", unclear=False, reason="")
    asyncio.run(signal_processor.process_day_trading_signal(message_id, interp))

signal = repo.list_recent_signals("BTC")[0]
assert signal["message_id"] == message_id, "community-pad moet message_id nog steeds opslaan"
assert mock_send.await_count >= 1, "community-pad moet nog steeds een Telegram-melding sturen (regressie-check)"

# Tweede aanroep (zelfde coin/richting): existing-pad, notify_on_update
# default True -> moet een update-melding sturen.
with patch("app.coinlist.ensure_coin_tracked", return_value=(True, False)), \
     patch("app.exchange.fetch_ohlcv", return_value=df), \
     patch("app.explain.explain_signal", return_value=""), \
     patch("app.chart_image.render_signal_chart", return_value=b""), \
     patch("app.telegram_notify.send_signal_update", new_callable=AsyncMock) as mock_update:
    interp2 = Interpretation(coin="BTC", direction="long", category="day_trading", unclear=False, reason="")
    asyncio.run(signal_processor.process_day_trading_signal(message_id, interp2))
assert mock_update.await_count >= 1, "een tweede community-bericht over dezelfde coin/richting moet nog steeds updaten"

print("Task 2 Step 3: OK")
```

Run: `.venv/bin/python3 /tmp/claude_scratch/task2_check.py`
Expected: `Task 2 Step 3: OK`

- [ ] **Step 4: verifiëren dat `notify_on_update=False` de update-melding onderdrukt**

Schrijf `/tmp/claude_scratch/task2_notify_false_check.py`:

```python
import asyncio
import os
os.environ["DATABASE_PATH"] = "/tmp/task2b.db"
from pathlib import Path
from unittest.mock import patch, AsyncMock
import pandas as pd

from app import config, db, repo
from app.anthropic_interpret import Interpretation
from app import signal_processor

Path(config.DATABASE_PATH).unlink(missing_ok=True)
db.init_db()
user_id = repo.create_user("task2buser", "hash", 1000.0, 2.0, telegram_chat_id="1")

n = 60
df = pd.DataFrame({
    "timestamp": pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC"),
    "open": [100.0 + i * 0.5 for i in range(n)],
    "high": [101.0 + i * 0.5 for i in range(n)],
    "low": [99.0 + i * 0.5 for i in range(n)],
    "close": [100.5 + i * 0.5 for i in range(n)],
    "volume": [1000.0] * n,
})

with patch("app.coinlist.ensure_coin_tracked", return_value=(True, False)), \
     patch("app.exchange.fetch_ohlcv", return_value=df), \
     patch("app.explain.explain_signal", return_value=""), \
     patch("app.chart_image.render_signal_chart", return_value=b""), \
     patch("app.telegram_notify.send_signal", new_callable=AsyncMock):
    interp = Interpretation(coin="BTC", direction="long", category="day_trading", unclear=False, reason="")
    asyncio.run(signal_processor.process_day_trading_signal(None, interp, notify_on_update=False))

signal = repo.list_recent_signals("BTC")[0]
assert signal["message_id"] is None

with patch("app.coinlist.ensure_coin_tracked", return_value=(True, False)), \
     patch("app.exchange.fetch_ohlcv", return_value=df), \
     patch("app.explain.explain_signal", return_value=""), \
     patch("app.chart_image.render_signal_chart", return_value=b""), \
     patch("app.telegram_notify.send_signal_update", new_callable=AsyncMock) as mock_update:
    interp2 = Interpretation(coin="BTC", direction="long", category="day_trading", unclear=False, reason="")
    asyncio.run(signal_processor.process_day_trading_signal(None, interp2, notify_on_update=False))
assert mock_update.await_count == 0, "notify_on_update=False mag GEEN Telegram-update-bericht sturen"

signal_after = repo.list_recent_signals("BTC")[0]
assert signal_after["price"] == 100.5, "repo.update_signal moet wel gewoon draaien (database blijft actueel)"

print("Task 2 Step 4: OK")
```

Run: `.venv/bin/python3 /tmp/claude_scratch/task2_notify_false_check.py`
Expected: `Task 2 Step 4: OK`

- [ ] **Step 5: commit**

```bash
git add app/signal_processor.py
git commit -m "process_day_trading_signal: message_id optioneel + notify_on_update-vlag"
```

---

### Task 3: `indicators.btc_is_flat` + kernversie `app/market_scanner.py` + systemd

**Files:**
- Modify: `app/indicators.py` (nieuwe functie + constante)
- Create: `app/market_scanner.py`
- Create: `deploy/crypto-market-scan.service`
- Create: `deploy/crypto-market-scan.timer`

**Interfaces:**
- Consumes: Task 2's `process_day_trading_signal(message_id, interp, notify_on_update)`.
- Produces: `indicators.btc_is_flat(btc_ind: Indicators) -> bool`. `market_scanner.scan_market() -> None` (async), met een module-scope `AUTO_SCAN_LOSS_COOLDOWN_HOURS`-plek gereserveerd voor Task 5 (deze taak bouwt de kernversie zonder de 6 uitbreidingen — die komen in Taken 4-7 erbovenop, in dezelfde functie).

- [ ] **Step 1: indicators.py — btc_is_flat**

In `app/indicators.py`, direct na de bestaande constante `SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE = 6.0` (regel 607), voeg toe:

```python
# Hoe klein het verschil tussen EMA9 en EMA21 van BTC zelf moet zijn
# (genormaliseerd op zijn eigen ATR) om de markt als "zijwaarts, geen
# duidelijke richting" te beschouwen. Zelfde soort ATR-genormaliseerde
# marge als SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE hierboven, alleen dan voor
# "te dicht bij elkaar" in plaats van "te ver uit elkaar". Gebruikt door
# app/market_scanner.py om altcoin-signalering over te slaan zolang BTC
# zelf geen duidelijke trend heeft — zie de spec, sectie 3.
BTC_FLAT_EMA_GAP_ATR_MULTIPLE = 0.3
```

Direct na de functie `check_btc_trend` (regel 119-130), voeg toe:

```python
def btc_is_flat(btc_ind: Indicators) -> bool:
    """True als BTC zelf geen duidelijke trend heeft (EMA9 en EMA21 liggen
    te dicht bij elkaar, genormaliseerd op BTC's eigen ATR). Gebruikt door
    de autonome marktscan om altcoin-signalen deze cyclus over te slaan:
    bij een zijwaartse BTC-markt geven altcoin-signalen vaker valse
    uitslagen. BTC zelf blijft altijd meedoen, die kan niet circulair van
    zijn eigen trend afhangen."""
    if not btc_ind.atr:
        return False
    return abs(btc_ind.ema9 - btc_ind.ema21) < BTC_FLAT_EMA_GAP_ATR_MULTIPLE * btc_ind.atr
```

- [ ] **Step 2: btc_is_flat verifiëren (unit-test)**

Schrijf `/tmp/claude_scratch/task3_btc_flat_check.py`:

```python
from app import indicators

class FakeInd:
    def __init__(self, ema9, ema21, atr):
        self.ema9, self.ema21, self.atr = ema9, ema21, atr

# Verschil 0.2 * atr: ruim binnen de 0.3-drempel -> vlak.
assert indicators.btc_is_flat(FakeInd(ema9=100.2, ema21=100.0, atr=1.0)) is True
# Verschil 0.5 * atr: ruim buiten de drempel -> niet vlak.
assert indicators.btc_is_flat(FakeInd(ema9=100.5, ema21=100.0, atr=1.0)) is False
# atr=0 (edge case, mag niet crashen): nooit vlak (geen zinnige normalisatie mogelijk).
assert indicators.btc_is_flat(FakeInd(ema9=100.0, ema21=100.0, atr=0.0)) is False

print("Task 3 Step 2: OK")
```

Run: `.venv/bin/python3 /tmp/claude_scratch/task3_btc_flat_check.py`
Expected: `Task 3 Step 2: OK`

- [ ] **Step 3: app/market_scanner.py — kernversie**

Create `app/market_scanner.py`:

```python
"""Autonome marktscan: HesPulse ontdekt zelf een day-trading-kans, zonder
dat een gebruiker eerst een Discord-bericht doorstuurt. Draait elk uur via
een systemd-timer (zie deploy/crypto-market-scan.service en .timer), niet
elke 4 uur zoals de underlying candle-timeframe: de laatste 4u-candle is
bij Binance nog "in wording" totdat hij sluit, dus tussentijds checken
vangt een beweging eerder op. Zelfde soort redenering als level_check.py,
die ook vaker draait dan de candle zelf.

Voor elke coin in de bestaande dynamische lijst (repo.list_coins()) wordt
zelf een richting bepaald via de trend (EMA9 t.o.v. EMA21) en hergebruikt
process_day_trading_signal() de bestaande toetsings- en fan-out-logica —
geen tweede implementatie ernaast. Zie
docs/superpowers/specs/2026-09-14-autonome-marktscan-design.md.
"""
import asyncio
import logging

from app import exchange, indicators, repo
from app.anthropic_interpret import Interpretation
from app.signal_processor import process_day_trading_signal

logger = logging.getLogger("market_scanner")


async def scan_market() -> None:
    coins = repo.list_coins()
    logger.info("Marktscan gestart, %s coins in de dynamische lijst", len(coins))

    for coin_row in coins:
        coin = coin_row["symbol"]
        try:
            df = await asyncio.to_thread(exchange.fetch_ohlcv, coin)
            ind = indicators.compute_indicators(df)
            direction = "long" if ind.ema9 > ind.ema21 else "short"
            interp = Interpretation(
                coin=coin, direction=direction, category="day_trading", unclear=False, reason="",
            )
            await process_day_trading_signal(None, interp, notify_on_update=False)
        except Exception:
            # Eén coin die faalt (bijvoorbeeld een tijdelijke Binance-storing)
            # mag de rest van de scan niet blokkeren.
            logger.exception("Marktscan voor coin %s is mislukt, ga door met de volgende", coin)

    logger.info("Marktscan klaar")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(scan_market())
```

- [ ] **Step 4: systemd-bestanden**

Create `deploy/crypto-market-scan.service` (zelfde vorm als `deploy/crypto-level-check.service`):

```ini
[Unit]
Description=HesPulse - autonome marktscan, zelf kansen ontdekken zonder doorgestuurd bericht

[Service]
Type=oneshot
User=crypto
WorkingDirectory=/opt/crypto-alerts
EnvironmentFile=/opt/crypto-alerts/.env
ExecStart=/opt/crypto-alerts/.venv/bin/python3 -m app.market_scanner
```

Create `deploy/crypto-market-scan.timer`:

```ini
[Unit]
Description=Draai de HesPulse autonome marktscan elk uur

[Timer]
OnCalendar=hourly
Persistent=true

[Install]
WantedBy=timers.target
```

- [ ] **Step 5: scan_market() verifiëren met gemockte exchange-data**

Schrijf `/tmp/claude_scratch/task3_scan_check.py`:

```python
import asyncio
import os
os.environ["DATABASE_PATH"] = "/tmp/task3_scan.db"
from pathlib import Path
from unittest.mock import patch, AsyncMock
import pandas as pd

from app import config, db, repo
from app import market_scanner

Path(config.DATABASE_PATH).unlink(missing_ok=True)
db.init_db()

repo.add_coin_if_new("BTC", "BTC/USDT")
repo.add_coin_if_new("ETH", "ETH/USDT")

n = 60
# BTC: duidelijke opgaande trend (EMA9 > EMA21) EN de overige basisfactoren
# kloppen (RSI neutraal, MACD boven signaallijn omdat de trend recent is
# doorgezet, volume boven gemiddeld) -> verwacht een bevestigd signaal.
up_df = pd.DataFrame({
    "timestamp": pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC"),
    "open": [100.0 + i * 0.6 for i in range(n)],
    "high": [101.0 + i * 0.6 for i in range(n)],
    "low": [99.0 + i * 0.6 for i in range(n)],
    "close": [100.5 + i * 0.6 for i in range(n)],
    "volume": [2000.0] * (n - 5) + [4000.0] * 5,
})
# ETH: vlakke prijs, geen duidelijke trend, EMA9≈EMA21 -> geen bevestiging.
flat_df = pd.DataFrame({
    "timestamp": pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC"),
    "open": [100.0] * n, "high": [100.2] * n, "low": [99.8] * n,
    "close": [100.0] * n, "volume": [1000.0] * n,
})


def fake_fetch_ohlcv(coin, *args, **kwargs):
    return up_df if coin == "BTC" else flat_df


with patch("app.exchange.fetch_ohlcv", side_effect=fake_fetch_ohlcv), \
     patch("app.explain.explain_signal", return_value=""), \
     patch("app.chart_image.render_signal_chart", return_value=b""), \
     patch("app.telegram_notify.send_signal", new_callable=AsyncMock) as mock_send:
    asyncio.run(market_scanner.scan_market())

btc_signal = repo.list_recent_signals("BTC")[0]
assert btc_signal["message_id"] is None, "autonoom signaal moet message_id=NULL hebben"
assert btc_signal["technical_confirmed"] == 1, "BTC had een duidelijke trend + genoeg bevestigende factoren"

eth_signals = repo.list_recent_signals("ETH")
assert not eth_signals, "ETH zonder bevestiging mag GEEN signaal opleveren (geen Telegram bij afwijzing autonoom)"
assert mock_send.await_count >= 1, "de bevestigde BTC-kans moet wel een Telegram-melding gestuurd hebben"

print("Task 3 Step 5: OK")
```

Run: `.venv/bin/python3 /tmp/claude_scratch/task3_scan_check.py`
Expected: `Task 3 Step 5: OK`

Als dit faalt op de RSI/MACD-aannames van de synthetische data: pas `up_df`'s prijsreeks aan (bijvoorbeeld een langere, geleidelijkere stijging) totdat `indicators.confirms_direction` voor "long" minstens 3 van de 4 basisfactoren bevestigt — controleer dit desnoods eerst apart met `indicators.compute_indicators(up_df)` en `indicators.confirms_direction(ind, "long")` in een REPL, vóór je de scan-test opnieuw draait.

- [ ] **Step 6: verifiëren — dedup tegen een al open COMMUNITY-signaal (spec-testpunt 3)**

Een coin/richting die de scan wil signaleren, maar die al een open signaal heeft dat uit een ECHT doorgestuurd bericht komt (`message_id` niet None): de scan mag dit bestaande signaal bijwerken via `repo.find_open_signal`, maar NOOIT een tweede, dubbel signaal aanmaken. Dit is een ander scenario dan Task 2 Step 4 (dat test een AUTONOOM signaal dat zichzelf bijwerkt) — hier is het bestaande signaal juist community-afkomstig.

Schrijf `/tmp/claude_scratch/task3_dedup_community_check.py`:

```python
import asyncio
import os
os.environ["DATABASE_PATH"] = "/tmp/task3_dedup.db"
from pathlib import Path
from unittest.mock import patch, AsyncMock
import pandas as pd

from app import config, db, repo
from app import market_scanner

Path(config.DATABASE_PATH).unlink(missing_ok=True)
db.init_db()
user_id = repo.create_user("task3dedup", "hash", 1000.0, 2.0, telegram_chat_id="1")
repo.add_coin_if_new("BTC", "BTC/USDT")

# Een al open, bevestigd COMMUNITY-signaal voor BTC long (message_id gezet,
# nog niet genomen -> entry_price is None, dus find_open_signal ziet dit
# als open).
message_id = repo.insert_message("community bericht over BTC long", [])
community_signal_id = repo.insert_signal({
    "message_id": message_id, "coin": "BTC", "direction": "long", "category": "day_trading",
    "price": 95.0, "confidence": "hoog vertrouwen", "technical_confirmed": 1,
    "reason": "✓ Trend: ok | ✓ Momentum: ok | ✓ RSI: ok | ✓ Volume: ok",
})
repo.create_journal_entry(community_signal_id, user_id, 20.0)

n = 60
up_df = pd.DataFrame({
    "timestamp": pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC"),
    "open": [100.0 + i * 0.6 for i in range(n)],
    "high": [101.0 + i * 0.6 for i in range(n)],
    "low": [99.0 + i * 0.6 for i in range(n)],
    "close": [100.5 + i * 0.6 for i in range(n)],
    "volume": [2000.0] * (n - 5) + [4000.0] * 5,
})
with patch("app.exchange.fetch_ohlcv", return_value=up_df), \
     patch("app.explain.explain_signal", return_value=""), \
     patch("app.chart_image.render_signal_chart", return_value=b""), \
     patch("app.telegram_notify.send_signal", new_callable=AsyncMock), \
     patch("app.telegram_notify.send_signal_update", new_callable=AsyncMock):
    asyncio.run(market_scanner.scan_market())

all_btc_signals = repo.list_recent_signals("BTC", limit=10)
assert len(all_btc_signals) == 1, "de scan mag GEEN tweede signaal aanmaken naast het bestaande community-signaal"
assert all_btc_signals[0]["id"] == community_signal_id, "het bestaande community-signaal moet bijgewerkt zijn, niet vervangen"
assert all_btc_signals[0]["message_id"] == message_id, "message_id van het bijgewerkte signaal moet het community-bericht blijven, niet NULL worden"
assert all_btc_signals[0]["price"] == 100.5, "de prijs moet wel ververst zijn (repo.update_signal draait altijd)"

print("Task 3 Step 6: OK")
```

Run: `.venv/bin/python3 /tmp/claude_scratch/task3_dedup_community_check.py`
Expected: `Task 3 Step 6: OK`

- [ ] **Step 7: commit**

```bash
git add app/indicators.py app/market_scanner.py deploy/crypto-market-scan.service deploy/crypto-market-scan.timer
git commit -m "Autonome marktscan: kernversie, elk uur, hergebruikt process_day_trading_signal"
```

---

### Task 4: Noodrem (`market_scan_enabled`)

**Files:**
- Modify: `app/repo.py` (twee nieuwe dunne wrappers)
- Modify: `app/market_scanner.py` (`scan_market()` checkt de vlag als eerste stap)
- Modify: `web/main.py` (nieuwe route)
- Modify: `web/templates/dashboard.html` (knop bij de instellingen-sectie)

**Interfaces:**
- Consumes: Task 3's `market_scanner.scan_market()`.
- Produces: `repo.is_market_scan_enabled() -> bool`, `repo.set_market_scan_enabled(enabled: bool) -> None`. Geen latere taak consumeert dit direct.

- [ ] **Step 1: repo.py wrappers**

In `app/repo.py`, in de buurt van de andere korte, op zichzelf staande functies (bijvoorbeeld direct vóór `def list_coins():`), voeg toe:

```python
MARKET_SCAN_SETTING_KEY = "market_scan_enabled"


def is_market_scan_enabled() -> bool:
    """Noodrem voor de autonome marktscan (app/market_scanner.py): een
    systeembrede vlag in de bestaande settings-tabel, standaard aan.
    Geen per-gebruiker instelling, zie de spec."""
    return db.get_setting(MARKET_SCAN_SETTING_KEY, default="1") == "1"


def set_market_scan_enabled(enabled: bool) -> None:
    db.set_setting(MARKET_SCAN_SETTING_KEY, "1" if enabled else "0")
```

- [ ] **Step 2: market_scanner.py checkt de vlag als eerste stap**

In `app/market_scanner.py`, in `scan_market()`, direct na de docstring/voor `coins = repo.list_coins()`:

```python
async def scan_market() -> None:
    if not repo.is_market_scan_enabled():
        logger.info("Marktscan staat uit (noodrem), niets gedaan")
        return

    coins = repo.list_coins()
```

- [ ] **Step 3: route in web/main.py**

Zoek de bestaande route `@app.post("/coins/{symbol}/unmute")` in `web/main.py` (regel ~1471) als plaatsingsreferentie, en voeg er een vergelijkbare, eenvoudige form-post-en-redirect-route bij (geen JSON/fragment-swap nodig voor een zelden gebruikte noodrem-knop):

```python
@app.post("/settings/market_scan")
async def toggle_market_scan(enabled: str = Form(...), user: dict = Depends(require_login)):
    """Systeembrede noodrem voor de autonome marktscan (niet per gebruiker,
    zie de spec). Elke ingelogde gebruiker mag dit omzetten, net als bij
    de portfolio-instellingen hierboven — er is geen apart adminaccount in
    dit systeem."""
    repo.set_market_scan_enabled(enabled == "1")
    return RedirectResponse(url="/dashboard", status_code=303)
```

- [ ] **Step 4: knop in dashboard.html**

Zoek in `web/templates/dashboard.html` de sectie rond het portfolio-instellingenformulier (`action="/settings/portfolio"`) en voeg er direct na toe:

```html
<form action="/settings/market_scan" method="post" style="margin-top: 12px;">
  {% if market_scan_enabled %}
  <input type="hidden" name="enabled" value="0">
  <button type="submit" class="button-reset">Autonome marktscan uitzetten</button>
  <p class="muted" style="margin: 4px 0 0; font-size: 12.5px;">Nu aan: elk uur zoekt HesPulse zelf naar kansen, ook zonder doorgestuurd bericht.</p>
  {% else %}
  <input type="hidden" name="enabled" value="1">
  <button type="submit">Autonome marktscan aanzetten</button>
  <p class="muted" style="margin: 4px 0 0; font-size: 12.5px;">Nu uit: HesPulse reageert alleen nog op doorgestuurde berichten.</p>
  {% endif %}
</form>
```

Zoek de route `dashboard` in `web/main.py` en voeg `market_scan_enabled` toe aan de context die naar het template gaat (zoek de `return templates.TemplateResponse(...)`-aanroep aan het eind van de functie en voeg `"market_scan_enabled": repo.is_market_scan_enabled(),` toe aan de context-dict).

- [ ] **Step 5: verifiëren**

Schrijf `/tmp/claude_scratch/task4_check.py`:

```python
import asyncio
import os
os.environ["DATABASE_PATH"] = "/tmp/task4.db"
from pathlib import Path
from unittest.mock import patch

from app import config, db, repo
from app import market_scanner

Path(config.DATABASE_PATH).unlink(missing_ok=True)
db.init_db()

assert repo.is_market_scan_enabled() is True, "standaard aan"

repo.add_coin_if_new("BTC", "BTC/USDT")
repo.set_market_scan_enabled(False)
assert repo.is_market_scan_enabled() is False

with patch("app.exchange.fetch_ohlcv") as mock_fetch:
    asyncio.run(market_scanner.scan_market())
    assert mock_fetch.call_count == 0, "uitgezet -> geen enkele exchange-aanroep"

repo.set_market_scan_enabled(True)
assert repo.is_market_scan_enabled() is True

print("Task 4 Step 5: OK")
```

Run: `.venv/bin/python3 /tmp/claude_scratch/task4_check.py`
Expected: `Task 4 Step 5: OK`

Verifieer de dashboard-knop handmatig: start een lokale `uvicorn` tegen een scratch-DB (zelfde patroon als eerder deze sessie: een user aanmaken, sessietoken genereren, cookie meegeven), open `/dashboard`, controleer dat de knop met de juiste tekst verschijnt en na een klik de vlag omzet (`repo.is_market_scan_enabled()` in een losse REPL-check na de klik).

- [ ] **Step 6: commit**

```bash
git add app/repo.py app/market_scanner.py web/main.py web/templates/dashboard.html
git commit -m "Noodrem voor de autonome marktscan: dashboard-knop + settings-vlag"
```

---

### Task 5: BTC-vlak-rem + verlies-cooldown

**Files:**
- Modify: `app/repo.py` (`recent_autonomous_loss`)
- Modify: `app/market_scanner.py` (BTC eenmalig ophalen + per-coin cooldown-check)

**Interfaces:**
- Consumes: Task 3's `indicators.btc_is_flat`, Task 4's noodrem (deze taak bouwt in dezelfde `scan_market()`-functie verder, na de noodrem-check).
- Produces: `repo.recent_autonomous_loss(coin: str, direction: str, hours: int) -> bool`. Task 6 leunt op hetzelfde "autonoom + gesloten"-querypatroon.

- [ ] **Step 1: repo.py — recent_autonomous_loss**

In `app/repo.py`, in de buurt van `period_stats` (voor logische groepering rond journal-statistieken), voeg toe:

```python
def recent_autonomous_loss(coin: str, direction: str, hours: int) -> bool:
    """True als de laatst GESLOTEN journal-regel op een autonoom signaal
    (message_id IS NULL, zie app/market_scanner.py) voor deze coin+richting
    binnen `hours` uur geleden een verlies was. 'Gesloten' wordt hier,
    net als in period_stats, herkend aan exit_price IS NOT NULL (er is
    geen apart 'gesloten'-statusveld in dit schema). Gebruikt om de scan
    een afkoelperiode te geven na een verlies op dezelfde coin/richting,
    in plaats van elk uur opnieuw dezelfde whipsaw te melden."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with db.session() as conn:
        row = conn.execute(
            """SELECT je.result_eur AS result_eur
               FROM journal_entries je
               JOIN signals s ON s.id = je.signal_id
               WHERE s.coin = ? AND s.direction = ? AND s.message_id IS NULL
                     AND s.is_practice = 0 AND je.exit_price IS NOT NULL
               ORDER BY je.exit_time DESC LIMIT 1""",
            (coin.upper(), direction.lower()),
        ).fetchone()
    if not row or row["result_eur"] is None:
        return False
    # exit_time is niet in deze query meegenomen voor de cutoff-vergelijking
    # (die staat al impliciet in de ORDER BY ... LIMIT 1: dit is de MEEST
    # RECENTE sluiting). We moeten dus nog los checken of die recent genoeg
    # is; daarvoor exit_time apart ophalen was overbodig -- eenvoudiger: de
    # cutoff direct in de WHERE, zie de herziene query hieronder.
    return row["result_eur"] < 0
```

**Let op tijdens implementatie:** de docstring-comment hierboven signaleert zelf een fout in de eerste opzet (de cutoff wordt nergens gebruikt). Vervang de hele functie door deze correcte versie (met de cutoff in de WHERE-clause):

```python
def recent_autonomous_loss(coin: str, direction: str, hours: int) -> bool:
    """True als de laatst GESLOTEN journal-regel op een autonoom signaal
    (message_id IS NULL, zie app/market_scanner.py) voor deze coin+richting
    binnen `hours` uur geleden een verlies was. 'Gesloten' wordt hier,
    net als in period_stats, herkend aan exit_price IS NOT NULL (er is
    geen apart 'gesloten'-statusveld in dit schema). Gebruikt om de scan
    een afkoelperiode te geven na een verlies op dezelfde coin/richting,
    in plaats van elk uur opnieuw dezelfde whipsaw te melden."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with db.session() as conn:
        row = conn.execute(
            """SELECT je.result_eur AS result_eur
               FROM journal_entries je
               JOIN signals s ON s.id = je.signal_id
               WHERE s.coin = ? AND s.direction = ? AND s.message_id IS NULL
                     AND s.is_practice = 0 AND je.exit_price IS NOT NULL
                     AND je.exit_time >= ?
               ORDER BY je.exit_time DESC LIMIT 1""",
            (coin.upper(), direction.lower(), cutoff),
        ).fetchone()
    return bool(row and row["result_eur"] is not None and row["result_eur"] < 0)
```

Controleer dat `datetime`, `timedelta`, `timezone` al geïmporteerd zijn bovenaan `app/repo.py` (ze worden al gebruikt door `period_stats`/`coin_long_term_track_record`) — geen nieuwe import nodig.

- [ ] **Step 2: market_scanner.py — BTC eenmalig + cooldown per coin**

Herschrijf `app/market_scanner.py`'s `scan_market()` volledig naar:

```python
import asyncio
import logging

from app import exchange, indicators, repo
from app.anthropic_interpret import Interpretation
from app.signal_processor import process_day_trading_signal

logger = logging.getLogger("market_scanner")

# Twaalf van de vierentwintig scan-cycli per dag overslaan na een verlies
# op dezelfde coin+richting is een reële afkoelperiode zonder een kans
# dagenlang te blokkeren. Zie de spec, sectie 4.
AUTO_SCAN_LOSS_COOLDOWN_HOURS = 12


async def scan_market() -> None:
    if not repo.is_market_scan_enabled():
        logger.info("Marktscan staat uit (noodrem), niets gedaan")
        return

    coins = repo.list_coins()
    logger.info("Marktscan gestart, %s coins in de dynamische lijst", len(coins))

    btc_flat = False
    try:
        btc_df = await asyncio.to_thread(exchange.fetch_ohlcv, "BTC")
        btc_ind = indicators.compute_indicators(btc_df)
        btc_flat = indicators.btc_is_flat(btc_ind)
        if btc_flat:
            logger.info("BTC is zijwaarts deze cyclus, altcoin-signalering overgeslagen")
    except Exception:
        logger.exception("Kon BTC's eigen trend niet ophalen, ga verder zonder de vlak-check")

    for coin_row in coins:
        coin = coin_row["symbol"]
        if btc_flat and coin != "BTC":
            continue
        try:
            df = await asyncio.to_thread(exchange.fetch_ohlcv, coin)
            ind = indicators.compute_indicators(df)
            direction = "long" if ind.ema9 > ind.ema21 else "short"

            if repo.recent_autonomous_loss(coin, direction, AUTO_SCAN_LOSS_COOLDOWN_HOURS):
                logger.info("%s %s overgeslagen: recent verlies binnen de cooldown", coin, direction)
                continue

            interp = Interpretation(
                coin=coin, direction=direction, category="day_trading", unclear=False, reason="",
            )
            await process_day_trading_signal(None, interp, notify_on_update=False)
        except Exception:
            logger.exception("Marktscan voor coin %s is mislukt, ga door met de volgende", coin)

    logger.info("Marktscan klaar")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(scan_market())
```

- [ ] **Step 3: verifiëren — btc_is_flat integratie**

Schrijf `/tmp/claude_scratch/task5_btc_flat_integration_check.py`:

```python
import asyncio
import os
os.environ["DATABASE_PATH"] = "/tmp/task5_flat.db"
from pathlib import Path
from unittest.mock import patch, AsyncMock
import pandas as pd

from app import config, db, repo
from app import market_scanner

Path(config.DATABASE_PATH).unlink(missing_ok=True)
db.init_db()
repo.add_coin_if_new("BTC", "BTC/USDT")
repo.add_coin_if_new("ETH", "ETH/USDT")

n = 60
flat_df = pd.DataFrame({
    "timestamp": pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC"),
    "open": [100.0] * n, "high": [100.2] * n, "low": [99.8] * n,
    "close": [100.0] * n, "volume": [1000.0] * n,
})
# ETH heeft op zichzelf een prima setup (duidelijke trend, genoeg volume),
# maar mag deze cyclus NIET signaleren omdat BTC vlak is.
eth_up_df = pd.DataFrame({
    "timestamp": pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC"),
    "open": [100.0 + i * 0.6 for i in range(n)],
    "high": [101.0 + i * 0.6 for i in range(n)],
    "low": [99.0 + i * 0.6 for i in range(n)],
    "close": [100.5 + i * 0.6 for i in range(n)],
    "volume": [2000.0] * (n - 5) + [4000.0] * 5,
})


def fake_fetch_ohlcv(coin, *args, **kwargs):
    return flat_df if coin == "BTC" else eth_up_df


with patch("app.exchange.fetch_ohlcv", side_effect=fake_fetch_ohlcv), \
     patch("app.explain.explain_signal", return_value=""), \
     patch("app.chart_image.render_signal_chart", return_value=b""), \
     patch("app.telegram_notify.send_signal", new_callable=AsyncMock) as mock_send:
    asyncio.run(market_scanner.scan_market())

eth_signals = repo.list_recent_signals("ETH")
assert not eth_signals, "BTC vlak -> ETH mag deze cyclus geen signaal krijgen, ondanks een prima eigen setup"
assert mock_send.await_count == 0

print("Task 5 Step 3: OK")
```

Run: `.venv/bin/python3 /tmp/claude_scratch/task5_btc_flat_integration_check.py`
Expected: `Task 5 Step 3: OK`

- [ ] **Step 4: verifiëren — cooldown na verlies**

Schrijf `/tmp/claude_scratch/task5_cooldown_check.py`:

```python
import asyncio
import os
os.environ["DATABASE_PATH"] = "/tmp/task5_cooldown.db"
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch, AsyncMock
import pandas as pd

from app import config, db, repo
from app import market_scanner

Path(config.DATABASE_PATH).unlink(missing_ok=True)
db.init_db()
user_id = repo.create_user("task5user", "hash", 1000.0, 2.0, telegram_chat_id="1")
repo.add_coin_if_new("BTC", "BTC/USDT")

# Een gesloten, VERLIESGEVEND autonoom signaal voor BTC long, 2 uur geleden
# gesloten (binnen de 12-uurs cooldown).
signal_id = repo.insert_signal({
    "message_id": None, "coin": "BTC", "direction": "long", "category": "day_trading",
    "price": 100.0, "confidence": "hoog vertrouwen", "technical_confirmed": 1,
    "reason": "✓ Trend: ok | ✓ Momentum: ok | ✓ RSI: ok | ✓ Volume: ok",
})
entry_id = repo.create_journal_entry(signal_id, user_id, 20.0)
repo.update_journal_entry_entry_price(entry_id, user_id, 100.0, "2026-01-01T00:00:00+00:00") \
    if hasattr(repo, "update_journal_entry_entry_price") else None
recent_exit = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
with db.session() as conn:
    conn.execute(
        "UPDATE journal_entries SET entry_price = 100.0, exit_price = 95.0, exit_time = ?, result_eur = -10.0 WHERE id = ?",
        (recent_exit, entry_id),
    )

assert repo.recent_autonomous_loss("BTC", "long", 12) is True
assert repo.recent_autonomous_loss("BTC", "short", 12) is False, "andere richting mag niet meegeteld worden"

n = 60
up_df = pd.DataFrame({
    "timestamp": pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC"),
    "open": [100.0 + i * 0.6 for i in range(n)],
    "high": [101.0 + i * 0.6 for i in range(n)],
    "low": [99.0 + i * 0.6 for i in range(n)],
    "close": [100.5 + i * 0.6 for i in range(n)],
    "volume": [2000.0] * (n - 5) + [4000.0] * 5,
})
with patch("app.exchange.fetch_ohlcv", return_value=up_df), \
     patch("app.explain.explain_signal", return_value=""), \
     patch("app.chart_image.render_signal_chart", return_value=b""), \
     patch("app.telegram_notify.send_signal", new_callable=AsyncMock) as mock_send:
    asyncio.run(market_scanner.scan_market())
assert mock_send.await_count == 0, "BTC long moet overgeslagen worden binnen de cooldown, ondanks een prima setup"

# Buiten de cooldown (13 uur geleden): moet weer meegenomen worden.
old_exit = (datetime.now(timezone.utc) - timedelta(hours=13)).isoformat()
with db.session() as conn:
    conn.execute("UPDATE journal_entries SET exit_time = ? WHERE id = ?", (old_exit, entry_id))
assert repo.recent_autonomous_loss("BTC", "long", 12) is False

with patch("app.exchange.fetch_ohlcv", return_value=up_df), \
     patch("app.explain.explain_signal", return_value=""), \
     patch("app.chart_image.render_signal_chart", return_value=b""), \
     patch("app.telegram_notify.send_signal", new_callable=AsyncMock) as mock_send2:
    asyncio.run(market_scanner.scan_market())
assert mock_send2.await_count >= 1, "buiten de cooldown moet BTC weer gewoon gesignaleerd worden"

print("Task 5 Step 4: OK")
```

Run: `.venv/bin/python3 /tmp/claude_scratch/task5_cooldown_check.py`
Expected: `Task 5 Step 4: OK`

Als `repo.update_journal_entry_entry_price` niet bestaat (de `hasattr`-guard hierboven vangt dat al af): dat is prima, de directe `UPDATE journal_entries SET entry_price = ...` regel eronder zet de benodigde velden sowieso.

- [ ] **Step 5: commit**

```bash
git add app/repo.py app/market_scanner.py
git commit -m "Marktscan: rem bij zijwaartse BTC-markt + cooldown na verlies"
```

---

### Task 6: Herhaald-verlies-waarschuwing

**Files:**
- Modify: `app/repo.py` (`consecutive_autonomous_losses`)
- Modify: `app/signal_processor.py` (`repeated_loss_note` in `signal_data`)
- Modify: `app/telegram_notify.py` (`format_signal_message`)

**Interfaces:**
- Consumes: Task 5's `recent_autonomous_loss`-querypatroon (hergebruikt dezelfde "autonoom + gesloten"-aanpak).
- Produces: `repo.consecutive_autonomous_losses(coin: str, direction: str, limit: int = 3) -> int`. `signal_data["repeated_loss_note"]` (string of `None`), gebruikt in `format_signal_message`.

- [ ] **Step 1: repo.py — consecutive_autonomous_losses**

In `app/repo.py`, direct na `recent_autonomous_loss` (Task 5), voeg toe:

```python
def consecutive_autonomous_losses(coin: str, direction: str, limit: int = 3) -> int:
    """Hoeveel van de laatste `limit` GESLOTEN autonome journal-regels
    (message_id IS NULL) voor deze coin+richting op rij een verlies waren,
    nieuwste eerst geteld, stopt zodra een winst wordt tegengekomen (0 als
    de nieuwste al een winst is). Puur informatief — zie
    telegram_notify.format_signal_message's repeated_loss_note-regel — het
    signaal wordt hierdoor nooit onderdrukt, alleen gewaarschuwd."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT je.result_eur AS result_eur
               FROM journal_entries je
               JOIN signals s ON s.id = je.signal_id
               WHERE s.coin = ? AND s.direction = ? AND s.message_id IS NULL
                     AND s.is_practice = 0 AND je.exit_price IS NOT NULL
               ORDER BY je.exit_time DESC LIMIT ?""",
            (coin.upper(), direction.lower(), limit),
        ).fetchall()
    count = 0
    for row in rows:
        if row["result_eur"] is not None and row["result_eur"] < 0:
            count += 1
        else:
            break
    return count
```

- [ ] **Step 2: signal_processor.py — repeated_loss_note**

In `app/signal_processor.py`, zoek de regel `repeated_factor = None if confirmed else await asyncio.to_thread(_repeated_failing_factor, interp.coin)` (rond regel 729) en voeg er direct na toe:

```python
    # Alleen zinvol voor een AUTONOOM signaal (message_id is None): een
    # community-bericht heeft geen "herhaald patroon" in deze zin, dat is
    # een menselijke keuze elke keer opnieuw. Puur informatief, het signaal
    # wordt gewoon aangemaakt en gemeld zoals altijd — zie de spec, sectie 5.
    repeated_loss_note = None
    if message_id is None and confirmed:
        loss_streak = await asyncio.to_thread(
            repo.consecutive_autonomous_losses, interp.coin, interp.direction,
        )
        if loss_streak >= 3:
            repeated_loss_note = (
                f"📉 Dit zelf-gedetecteerde patroon verloor de laatste {loss_streak} keer op rij "
                f"bij {interp.coin}. Blijft een geldige kans, weeg dit wel mee."
            )
```

Zoek de `signal_data = { ... }`-dict (rond regel 741-761) en voeg een regel toe aan het einde, vóór de sluitende `}`:

```python
        "repeated_factor": repeated_factor,
        "repeated_loss_note": repeated_loss_note,
    }
```

- [ ] **Step 3: telegram_notify.py — format_signal_message**

In `app/telegram_notify.py`, in `format_signal_message` (rond regel 127-160), zoek de regel `if signal.get("context_note"):` en voeg er direct na toe:

```python
    if signal.get("context_note"):
        lines += ["", signal["context_note"]]
    if signal.get("repeated_loss_note"):
        lines += ["", signal["repeated_loss_note"]]
```

- [ ] **Step 4: verifiëren**

Schrijf `/tmp/claude_scratch/task6_check.py`:

```python
import asyncio
import os
os.environ["DATABASE_PATH"] = "/tmp/task6.db"
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch, AsyncMock
import pandas as pd

from app import config, db, repo, telegram_notify
from app.anthropic_interpret import Interpretation
from app import signal_processor

Path(config.DATABASE_PATH).unlink(missing_ok=True)
db.init_db()
user_id = repo.create_user("task6user", "hash", 1000.0, 2.0, telegram_chat_id="1")

now_iso = datetime.now(timezone.utc).isoformat()

# Drie verliezen op rij voor BTC long, autonoom (message_id=None).
loss_signal_ids = []
for i in range(3):
    sid = repo.insert_signal({
        "message_id": None, "coin": "BTC", "direction": "long", "category": "day_trading",
        "price": 100.0, "confidence": "hoog vertrouwen", "technical_confirmed": 1,
        "reason": "✓ Trend: ok | ✓ Momentum: ok | ✓ RSI: ok | ✓ Volume: ok",
    })
    eid = repo.create_journal_entry(sid, user_id, 20.0)
    with db.session() as conn:
        conn.execute(
            "UPDATE journal_entries SET entry_price = 100.0, exit_price = 95.0, exit_time = ?, result_eur = -10.0 WHERE id = ?",
            (now_iso, eid),
        )
    loss_signal_ids.append(sid)

assert repo.consecutive_autonomous_losses("BTC", "long", limit=3) == 3

# Eén winst ertussen (oudste van de drie wordt nu een winst) -> streak breekt.
with db.session() as conn:
    conn.execute(
        "UPDATE journal_entries SET result_eur = 10.0 WHERE signal_id = ?",
        (loss_signal_ids[0],),
    )
assert repo.consecutive_autonomous_losses("BTC", "long", limit=3) < 3

# Terug naar 3 verliezen, en nu de Telegram-tekst controleren via een echte
# process_day_trading_signal-aanroep (via de scanner-route: message_id=None).
with db.session() as conn:
    conn.execute("UPDATE journal_entries SET result_eur = -10.0 WHERE signal_id = ?", (loss_signal_ids[0],))

n = 60
up_df = pd.DataFrame({
    "timestamp": pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC"),
    "open": [100.0 + i * 0.6 for i in range(n)],
    "high": [101.0 + i * 0.6 for i in range(n)],
    "low": [99.0 + i * 0.6 for i in range(n)],
    "close": [100.5 + i * 0.6 for i in range(n)],
    "volume": [2000.0] * (n - 5) + [4000.0] * 5,
})
captured = {}


async def fake_send_signal(signal, chat_id, **kwargs):
    captured["signal"] = signal


with patch("app.coinlist.ensure_coin_tracked", return_value=(True, False)), \
     patch("app.exchange.fetch_ohlcv", return_value=up_df), \
     patch("app.explain.explain_signal", return_value=""), \
     patch("app.chart_image.render_signal_chart", return_value=b""), \
     patch("app.telegram_notify.send_signal", side_effect=fake_send_signal):
    interp = Interpretation(coin="BTC", direction="long", category="day_trading", unclear=False, reason="")
    asyncio.run(signal_processor.process_day_trading_signal(None, interp, notify_on_update=False))

assert captured["signal"]["repeated_loss_note"] is not None
assert "3 keer op rij" in captured["signal"]["repeated_loss_note"]
text = telegram_notify.format_signal_message(captured["signal"])
assert "verloor de laatste 3 keer op rij" in text

print("Task 6 Step 4: OK")
```

Run: `.venv/bin/python3 /tmp/claude_scratch/task6_check.py`
Expected: `Task 6 Step 4: OK`

- [ ] **Step 5: commit**

```bash
git add app/repo.py app/signal_processor.py app/telegram_notify.py
git commit -m "Waarschuwing bij herhaald verlies op een autonoom patroon, geen onderdrukking"
```

---

### Task 7: Sterkte-ranking bij meerdere gelijktijdige kansen

**Files:**
- Modify: `app/telegram_notify.py` (`send_scan_cycle_summary`)
- Modify: `app/market_scanner.py` (verzamelen + aan het eind versturen)

**Interfaces:**
- Consumes: Task 5's volledige `scan_market()`.
- Produces: `telegram_notify.send_scan_cycle_summary(ranked: list[dict], chat_id: str) -> None`. Geen latere taak consumeert dit.

- [ ] **Step 1: telegram_notify.py — send_scan_cycle_summary**

In `app/telegram_notify.py`, na `send_signal` (rond regel 275), voeg toe:

```python
def format_scan_cycle_summary(ranked: list[dict]) -> str:
    """`ranked` is een lijst dicts met coin/direction/reason, al gesorteerd
    van sterkste naar zwakste kans (zie market_scanner.scan_market()). Eén
    extra bericht per scan-cyclus, alleen als er 2 of meer nieuwe autonome
    kansen tegelijk ontstonden — een AANVULLING op de bestaande
    pending_count-regel in elk los signaalbericht (task #111), geen
    vervanging."""
    lines = ["🔎 MEERDERE ZELF-GEDETECTEERDE KANSEN DEZE RONDE", DIVIDER]
    for i, item in enumerate(ranked, start=1):
        strength = item["reason"].count("✓")
        lines.append(
            f"{i}. {_direction_emoji(item['direction'])} {_coin_label(item['coin'])} "
            f"· {_direction_label(item['direction'])} · {strength}/4 factoren"
        )
    lines += [DIVIDER, f"⚠️ {config.DISCLAIMER}"]
    return "\n".join(lines)


async def send_scan_cycle_summary(ranked: list[dict], chat_id: str) -> None:
    if not config.TELEGRAM_BOT_TOKEN or not chat_id:
        logger.warning("Telegram token of chat ID ontbreekt, scan-samenvatting niet verstuurd")
        return
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    text = format_scan_cycle_summary(ranked)
    await bot.send_message(chat_id=chat_id, text=text, disable_notification=False)
    logger.info("Scan-cyclus-samenvatting verstuurd naar chat %s (%s kansen)", chat_id, len(ranked))
```

Controleer dat `_direction_emoji`, `_direction_label`, `_coin_label` en `DIVIDER` al bestaan in dit bestand (ze worden al gebruikt door `format_signal_message`) — geen nieuwe helpers nodig.

- [ ] **Step 2: market_scanner.py — verzamelen en versturen**

Herschrijf `app/market_scanner.py`'s `scan_market()` (bouwt voort op Task 5's versie) naar:

```python
import asyncio
import logging

from app import exchange, indicators, repo, telegram_notify
from app.anthropic_interpret import Interpretation
from app.signal_processor import process_day_trading_signal

logger = logging.getLogger("market_scanner")

AUTO_SCAN_LOSS_COOLDOWN_HOURS = 12


async def scan_market() -> None:
    if not repo.is_market_scan_enabled():
        logger.info("Marktscan staat uit (noodrem), niets gedaan")
        return

    coins = repo.list_coins()
    logger.info("Marktscan gestart, %s coins in de dynamische lijst", len(coins))

    btc_flat = False
    try:
        btc_df = await asyncio.to_thread(exchange.fetch_ohlcv, "BTC")
        btc_ind = indicators.compute_indicators(btc_df)
        btc_flat = indicators.btc_is_flat(btc_ind)
        if btc_flat:
            logger.info("BTC is zijwaarts deze cyclus, altcoin-signalering overgeslagen")
    except Exception:
        logger.exception("Kon BTC's eigen trend niet ophalen, ga verder zonder de vlak-check")

    # Elke NIEUWE (niet: bijgewerkte) bevestigde autonome kans uit deze
    # cyclus, voor de sterkte-ranking hieronder. repo.find_open_signal()
    # vóór de aanroep bepaalt of dit een nieuw of een bestaand signaal
    # wordt -- zie de check hieronder, vóór process_day_trading_signal.
    new_confirmed_this_cycle: list[dict] = []

    for coin_row in coins:
        coin = coin_row["symbol"]
        if btc_flat and coin != "BTC":
            continue
        try:
            df = await asyncio.to_thread(exchange.fetch_ohlcv, coin)
            ind = indicators.compute_indicators(df)
            direction = "long" if ind.ema9 > ind.ema21 else "short"

            if repo.recent_autonomous_loss(coin, direction, AUTO_SCAN_LOSS_COOLDOWN_HOURS):
                logger.info("%s %s overgeslagen: recent verlies binnen de cooldown", coin, direction)
                continue

            was_open_before = repo.find_open_signal(coin, direction) is not None

            interp = Interpretation(
                coin=coin, direction=direction, category="day_trading", unclear=False, reason="",
            )
            await process_day_trading_signal(None, interp, notify_on_update=False)

            if not was_open_before:
                fresh = repo.list_recent_signals(coin, limit=1)
                if fresh and fresh[0]["message_id"] is None and fresh[0]["technical_confirmed"]:
                    new_confirmed_this_cycle.append(
                        {"coin": coin, "direction": direction, "reason": fresh[0]["reason"] or ""}
                    )
        except Exception:
            logger.exception("Marktscan voor coin %s is mislukt, ga door met de volgende", coin)

    if len(new_confirmed_this_cycle) >= 2:
        ranked = sorted(new_confirmed_this_cycle, key=lambda item: item["reason"].count("✓"), reverse=True)
        for user in repo.list_users():
            if not user["telegram_chat_id"]:
                continue
            try:
                await telegram_notify.send_scan_cycle_summary(ranked, chat_id=user["telegram_chat_id"])
            except Exception:
                logger.exception("Scan-cyclus-samenvatting voor gebruiker %s is mislukt", user["username"])

    logger.info("Marktscan klaar")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(scan_market())
```

**Waarom `was_open_before` vóór de aanroep bepaald wordt:** `process_day_trading_signal` kan een BESTAAND signaal bijwerken (via `find_open_signal`) in plaats van een nieuwe aan te maken — de ranking moet alleen kansen tonen die deze cyclus voor het EERST ontstonden, niet elke coin die toevallig nog steeds bevestigd is.

- [ ] **Step 3: verifiëren**

Schrijf `/tmp/claude_scratch/task7_check.py`:

```python
import asyncio
import os
os.environ["DATABASE_PATH"] = "/tmp/task7.db"
from pathlib import Path
from unittest.mock import patch, AsyncMock
import pandas as pd

from app import config, db, repo
from app import market_scanner

Path(config.DATABASE_PATH).unlink(missing_ok=True)
db.init_db()
user_id = repo.create_user("task7user", "hash", 1000.0, 2.0, telegram_chat_id="1")
for c in ["BTC", "ETH", "SOL"]:
    repo.add_coin_if_new(c, f"{c}/USDT")

n = 60
def make_up_df(volume_boost):
    return pd.DataFrame({
        "timestamp": pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC"),
        "open": [100.0 + i * 0.6 for i in range(n)],
        "high": [101.0 + i * 0.6 for i in range(n)],
        "low": [99.0 + i * 0.6 for i in range(n)],
        "close": [100.5 + i * 0.6 for i in range(n)],
        "volume": [2000.0] * (n - 5) + [volume_boost] * 5,
    })

dfs = {"BTC": make_up_df(6000.0), "ETH": make_up_df(4000.0), "SOL": make_up_df(4000.0)}


def fake_fetch_ohlcv(coin, *args, **kwargs):
    return dfs.get(coin, dfs["BTC"])


with patch("app.exchange.fetch_ohlcv", side_effect=fake_fetch_ohlcv), \
     patch("app.explain.explain_signal", return_value=""), \
     patch("app.chart_image.render_signal_chart", return_value=b""), \
     patch("app.telegram_notify.send_signal", new_callable=AsyncMock), \
     patch("app.telegram_notify.send_scan_cycle_summary", new_callable=AsyncMock) as mock_summary:
    asyncio.run(market_scanner.scan_market())

assert mock_summary.await_count == 1, "3 nieuwe bevestigde kansen in dezelfde cyclus -> precies 1 samenvattingsbericht"
ranked_arg = mock_summary.await_args.args[0]
assert len(ranked_arg) == 3
assert {"BTC", "ETH", "SOL"} == {item["coin"] for item in ranked_arg}

# Met maar één kwalificerende coin: geen extra bericht.
Path(config.DATABASE_PATH).unlink(missing_ok=True)
db.init_db()
repo.create_user("task7user2", "hash", 1000.0, 2.0, telegram_chat_id="1")
repo.add_coin_if_new("BTC", "BTC/USDT")
flat_df = pd.DataFrame({
    "timestamp": pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC"),
    "open": [100.0] * n, "high": [100.2] * n, "low": [99.8] * n,
    "close": [100.0] * n, "volume": [1000.0] * n,
})
repo.add_coin_if_new("ETH", "ETH/USDT")
def fake_fetch_ohlcv2(coin, *args, **kwargs):
    return dfs["BTC"] if coin == "BTC" else flat_df
with patch("app.exchange.fetch_ohlcv", side_effect=fake_fetch_ohlcv2), \
     patch("app.explain.explain_signal", return_value=""), \
     patch("app.chart_image.render_signal_chart", return_value=b""), \
     patch("app.telegram_notify.send_signal", new_callable=AsyncMock), \
     patch("app.telegram_notify.send_scan_cycle_summary", new_callable=AsyncMock) as mock_summary2:
    asyncio.run(market_scanner.scan_market())
assert mock_summary2.await_count == 0, "maar 1 kwalificerende coin -> geen samenvattingsbericht"

print("Task 7 Step 3: OK")
```

Run: `.venv/bin/python3 /tmp/claude_scratch/task7_check.py`
Expected: `Task 7 Step 3: OK`

- [ ] **Step 4: commit**

```bash
git add app/telegram_notify.py app/market_scanner.py
git commit -m "Sterkte-ranking bij meerdere gelijktijdige autonome kansen in dezelfde scan-cyclus"
```

---

### Task 8: Weekoverzicht in de periodieke samenvatting

**Files:**
- Modify: `app/repo.py` (`period_stats_auto_scan`)
- Modify: `app/periodic_summary.py`
- Modify: `app/telegram_notify.py` (`format_period_summary`, of de functie die daar het equivalent van is)

**Interfaces:**
- Consumes: geen eerdere taak direct (leunt puur op Task 1's `message_id IS NULL`-conventie).
- Produces: `repo.period_stats_auto_scan(user_id: int, since_iso: str) -> dict`, zelfde vorm als `period_stats`.

- [ ] **Step 1: format_period_summary vinden**

Zoek de functie die `send_period_summary` in `app/telegram_notify.py` gebruikt om de tekst op te bouwen (aangeroepen vanuit `app/periodic_summary.py:run()` als `telegram_notify.send_period_summary(stats, label, chat_id=...)`):

```bash
grep -n "def send_period_summary\|def format_period_summary" app/telegram_notify.py
```

Lees die functie volledig (`sed -n '<gevonden regel>,+40p' app/telegram_notify.py`) vóór je verder gaat met Step 3 — de exacte plek om de nieuwe regel in te voegen hangt af van de bestaande opbouw, die dit plan niet blind mag overschrijven.

- [ ] **Step 2: repo.py — period_stats_auto_scan**

In `app/repo.py`, direct na `period_stats`, voeg toe:

```python
def period_stats_auto_scan(user_id: int, since_iso: str) -> dict:
    """Zelfde vorm als period_stats hierboven, maar alleen voor autonome,
    door de marktscan ontdekte signalen (message_id IS NULL). Gebruikt
    voor de extra regel in de wekelijkse samenvatting (niet de
    maandelijkse) — zie de spec, sectie 2."""
    with db.session() as conn:
        signals_row = conn.execute(
            """SELECT COUNT(*) AS n
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.created_at >= ? AND s.is_practice = 0
                     AND s.message_id IS NULL""",
            (user_id, since_iso),
        ).fetchone()
        closed = conn.execute(
            """SELECT je.result_eur AS result_eur
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_time >= ? AND je.exit_price IS NOT NULL
                     AND s.is_practice = 0 AND je.evaluation_id IS NULL AND s.message_id IS NULL""",
            (user_id, since_iso),
        ).fetchall()
    wins = sum(1 for r in closed if r["result_eur"] is not None and r["result_eur"] > 0)
    return {
        "signal_count": signals_row["n"] or 0,
        "closed_count": len(closed),
        "wins": wins,
        "winrate_pct": (wins / len(closed) * 100) if closed else None,
    }
```

- [ ] **Step 3: telegram_notify.py — extra regel**

Voeg, in de functie die je in Step 1 gevonden hebt, direct vóór de disclaimer-regel (`f"⚠️ {config.DISCLAIMER}"` of vergelijkbaar) een blok toe dat alleen bij `period == "week"` en `auto_scan_stats["signal_count"] > 0` een regel toevoegt, in dezelfde stijl als de rest van dat bericht, bijvoorbeeld:

```python
    if auto_scan_stats and auto_scan_stats["signal_count"] > 0:
        winrate_txt = (
            f", winrate {auto_scan_stats['winrate_pct']:.0f}%"
            if auto_scan_stats["winrate_pct"] is not None else ""
        )
        lines += [
            "",
            f"🔎 HesPulse vond deze week zelf {auto_scan_stats['signal_count']} kansen "
            f"({auto_scan_stats['closed_count']} afgesloten{winrate_txt}).",
        ]
```

Geef de gevonden functie een nieuwe parameter `auto_scan_stats: Optional[dict] = None` (na de bestaande parameters), zodat de maandelijkse samenvatting (die deze parameter niet meegeeft) ongewijzigd blijft werken.

- [ ] **Step 4: periodic_summary.py — koppeling**

In `app/periodic_summary.py`, in `run()`, zoek:

```python
        stats = repo.period_stats(user["id"], since_iso)
        if stats["signal_count"] == 0 and stats["closed_count"] == 0:
            continue
        try:
            await telegram_notify.send_period_summary(stats, label, chat_id=user["telegram_chat_id"])
```

Verander naar:

```python
        stats = repo.period_stats(user["id"], since_iso)
        if stats["signal_count"] == 0 and stats["closed_count"] == 0:
            continue
        auto_scan_stats = repo.period_stats_auto_scan(user["id"], since_iso) if period == "week" else None
        try:
            await telegram_notify.send_period_summary(
                stats, label, chat_id=user["telegram_chat_id"], auto_scan_stats=auto_scan_stats,
            )
```

Geef ook `send_period_summary` zelf (niet alleen `format_period_summary`) dezelfde nieuwe `auto_scan_stats: Optional[dict] = None`-parameter, en geef die door aan de format-functie.

- [ ] **Step 5: verifiëren**

Schrijf `/tmp/claude_scratch/task8_check.py`:

```python
import os
os.environ["DATABASE_PATH"] = "/tmp/task8.db"
from datetime import datetime, timedelta, timezone
from pathlib import Path

from app import config, db, repo

Path(config.DATABASE_PATH).unlink(missing_ok=True)
db.init_db()
user_id = repo.create_user("task8user", "hash", 1000.0, 2.0, telegram_chat_id="1")

since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
now_iso = datetime.now(timezone.utc).isoformat()

message_id = repo.insert_message("community bericht", [])
community_signal = repo.insert_signal({
    "message_id": message_id, "coin": "BTC", "direction": "long", "category": "day_trading",
    "price": 100.0, "confidence": "hoog vertrouwen", "technical_confirmed": 1, "reason": "",
})
repo.create_journal_entry(community_signal, user_id, 20.0)

auto_signal_1 = repo.insert_signal({
    "message_id": None, "coin": "ETH", "direction": "long", "category": "day_trading",
    "price": 100.0, "confidence": "hoog vertrouwen", "technical_confirmed": 1, "reason": "",
})
auto_entry_1 = repo.create_journal_entry(auto_signal_1, user_id, 20.0)
with db.session() as conn:
    conn.execute(
        "UPDATE journal_entries SET entry_price = 100.0, exit_price = 110.0, exit_time = ?, result_eur = 10.0 WHERE id = ?",
        (now_iso, auto_entry_1),
    )

auto_signal_2 = repo.insert_signal({
    "message_id": None, "coin": "SOL", "direction": "short", "category": "day_trading",
    "price": 100.0, "confidence": "hoog vertrouwen", "technical_confirmed": 1, "reason": "",
})
repo.create_journal_entry(auto_signal_2, user_id, 20.0)

stats = repo.period_stats_auto_scan(user_id, since)
assert stats["signal_count"] == 2, "alleen de twee autonome signalen, niet het community-signaal"
assert stats["closed_count"] == 1
assert stats["wins"] == 1
assert stats["winrate_pct"] == 100.0

print("Task 8 Step 5: OK")
```

Run: `.venv/bin/python3 /tmp/claude_scratch/task8_check.py`
Expected: `Task 8 Step 5: OK`

Verifieer daarna handmatig (of met een kleine extra scratch-check) dat `python3 -m app.periodic_summary --period week` op deze scratch-DB de extra regel in de teruggegeven tekst bevat, en dat `--period month` dat NIET doet (de `auto_scan_stats`-parameter blijft daar `None`).

- [ ] **Step 6: commit**

```bash
git add app/repo.py app/telegram_notify.py app/periodic_summary.py
git commit -m "Weekoverzicht: aparte regel voor wat de autonome scan zelf vond"
```

---

### Task 9: "Zelf gedetecteerd"-label (Telegram + dashboard/coin-pagina)

**Files:**
- Modify: `app/telegram_notify.py` (`format_signal_message`)
- Modify: `web/templates/_macros.html` (`open_trade_body`)

**Interfaces:**
- Consumes: Task 1's `message_id`-kolom in elke `signal_data`/journal-dict.
- Produces: niets voor latere taken (dit is de laatste inhoudelijke taak vóór de eindregressie).

- [ ] **Step 1: telegram_notify.py**

In `app/telegram_notify.py`, in `format_signal_message` (rond regel 127-135), zoek:

```python
    lines = [
        f"{_direction_emoji(signal['direction'])} {_coin_label(signal['coin'])} · {_direction_label(signal['direction'])}",
        DIVIDER,
        f"🟢 {signal['confidence'].upper()}",
        "",
```

Verander naar:

```python
    lines = [
        f"{_direction_emoji(signal['direction'])} {_coin_label(signal['coin'])} · {_direction_label(signal['direction'])}",
        DIVIDER,
        f"🟢 {signal['confidence'].upper()}",
    ]
    if signal.get("message_id") is None:
        lines.append("🔎 Zelf gedetecteerd door HesPulse")
    lines.append("")
```

- [ ] **Step 2: dashboard.html en coin.html — label naast de vertrouwen-badge**

De badge zelf staat NIET in `_macros.html`'s `open_trade_body` (die bevat alleen `data-grid`, SL/TP-balk, PnL, formulieren) — de vertrouwen-badge staat in `web/templates/dashboard.html`, tweemaal, in het `.confidence-line`-blok vóór elke `{{ macros.open_trade_body(e) }}`-aanroep, en in `web/templates/coin.html` in de `.primary-card-head`.

In `web/templates/dashboard.html`, regel 92-94 (binnen de `{% for e in taken_entries %}`-lus):

```html
      <div class="confidence-line">
        <span class="badge {{ 'badge-hoog' if e.confidence == 'hoog vertrouwen' else 'badge-laag' }}">{{ e.confidence.split(" ")[0] }}</span>
        {% if e.message_id is none %}
        <span class="muted" style="font-size: 11px;" title="HesPulse ontdekte dit zelf, zonder doorgestuurd bericht">🔎 zelf gedetecteerd</span>
        {% endif %}
        {% if e.reason and e.trade_type != 'swing' %}<span class="confidence-ratio mono muted">{{ e.reason.count("✓") }}/{{ e.reason.split(" | ")|length }}</span>{% endif %}
```

Doe exact hetzelfde bij regel 121-122 (binnen de `{% for e in pending_entries %}`-lus, hetzelfde `.confidence-line`-patroon): voeg het `{% if e.message_id is none %}...{% endif %}`-blok direct na de vertrouwen-badge-`<span>` toe, vóór de `confidence-ratio`-regel.

Laat het derde voorkomen van dit patroon (rond regel 206, binnen de oefentrade-lus) ONGEWIJZIGD: een oefentrade krijgt altijd een eigen synthetisch "Handmatige oefentrade"-bericht (`web/main.py:create_practice_trade`, `message_id = repo.insert_message("Handmatige oefentrade", [])`), dus `e.message_id is none` is daar per constructie altijd False — het label zou daar nooit verschijnen, maar hoort er ook conceptueel niet thuis (een oefentrade is geen autonome marktkans).

In `web/templates/coin.html`, regel 79-81 (`.primary-card-head`):

```html
      <div class="primary-card-head">
        <span class="badge badge-{{ primary.direction }}">{{ primary.direction }}</span>
        {% if primary.message_id is none %}
        <span class="muted" style="font-size: 11px;" title="HesPulse ontdekte dit zelf, zonder doorgestuurd bericht">🔎 zelf gedetecteerd</span>
        {% endif %}
        {% if primary.reason and primary.trade_type != 'swing' %}<span class="confidence-ratio mono muted">{{ primary.reason.count("✓") }}/{{ primary.reason.split(" | ")|length }}</span>{% endif %}
        {% if open_trades %}<span class="badge badge-status">{{ primary.status }}</span>{% endif %}
      </div>
```

`primary` wordt bovenaan `coin.html` gezet met `{% set primary = open_trades[0] if open_trades else (recent_signals[0] if recent_signals else none) %}` (regel 54). Beide bronnen hebben na Task 1 een `message_id`-sleutel: `open_trades` komt uit een `_JOURNAL_SELECT`-query (Task 1 voegde daar `s.message_id AS message_id` expliciet aan toe) en `recent_signals` komt uit `repo.list_recent_signals(symbol)`, die met `SELECT s.*` werkt en dus `message_id` altijd al meegaf, ook vóór Task 1.

**Let op:** pas de exacte plaatsing aan op wat Step 2's grep daadwerkelijk oplevert — dit plan kan de exacte regel niet voorspellen zonder dat resultaat, maar het patroon (`{% if e.message_id is none %}...{% endif %}` direct naast de bestaande richting/vertrouwen-badge) is vast.

- [ ] **Step 3: verifiëren — Telegram-tekst**

Schrijf `/tmp/claude_scratch/task9_telegram_check.py`:

```python
from app import telegram_notify

base_signal = {
    "coin": "BTC", "direction": "long", "confidence": "hoog vertrouwen",
    "price": 100.0, "take_profit": 110.0, "stop_loss": 95.0,
    "reason": "✓ Trend: ok | ✓ Momentum: ok | ✓ RSI: ok | ✓ Volume: ok",
    "technical_confirmed": 1,
}

auto_text = telegram_notify.format_signal_message({**base_signal, "message_id": None})
assert "Zelf gedetecteerd door HesPulse" in auto_text

community_text = telegram_notify.format_signal_message({**base_signal, "message_id": 42})
assert "Zelf gedetecteerd door HesPulse" not in community_text

print("Task 9 Step 3: OK")
```

Run: `.venv/bin/python3 /tmp/claude_scratch/task9_telegram_check.py`
Expected: `Task 9 Step 3: OK`

- [ ] **Step 4: handmatige Playwright-verificatie — dashboard/coin-pagina**

Zelfde patroon als eerder deze sessie (zie de topbar-redesign-verificatie): een scratch-DB met een user, een autonoom signaal (`message_id=None`) én een community-signaal, beide met een open journal-entry, een sessietoken, een lokale `uvicorn` op een ongebruikte poort (bijvoorbeeld 8794, na `ps aux | grep uvicorn` om een botsing uit te sluiten), en Playwright die zowel `/dashboard` als `/coins/<coin>` bezoekt en met `page.locator(...)` controleert dat het label alleen bij het autonome signaal verschijnt.

- [ ] **Step 5: commit**

```bash
git add app/telegram_notify.py web/templates/_macros.html
git commit -m "Zichtbaar label: Zelf gedetecteerd door HesPulse, Telegram + dashboard/coin-pagina"
```

---

### Task 10: Volledige regressie, handmatige verificatie, push

**Files:** geen nieuwe, alleen verificatie.

**Interfaces:**
- Consumes: alle voorgaande taken.
- Produces: niets, dit is de afsluitende taak.

- [ ] **Step 1: mute-check en evaluatie-risico met message_id=None**

De bestaande fan-out in `process_day_trading_signal` (mute-check via `repo.is_coin_muted`, evaluatie-risico via `_resolve_signal_risk`) is in Taken 2-3 al impliciet meegetest via `notify_on_update`/dedup, maar niet expliciet voor het autonome pad. Schrijf `/tmp/claude_scratch/task10_muted_and_eval_check.py`:

```python
import asyncio
import os
os.environ["DATABASE_PATH"] = "/tmp/task10_muted.db"
from pathlib import Path
from unittest.mock import patch, AsyncMock
import pandas as pd

from app import config, db, repo
from app.anthropic_interpret import Interpretation
from app import signal_processor

Path(config.DATABASE_PATH).unlink(missing_ok=True)
db.init_db()
user_id = repo.create_user("task10user", "hash", 1000.0, 2.0, telegram_chat_id="1")
repo.mute_coin(user_id, "BTC")

n = 60
up_df = pd.DataFrame({
    "timestamp": pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC"),
    "open": [100.0 + i * 0.6 for i in range(n)],
    "high": [101.0 + i * 0.6 for i in range(n)],
    "low": [99.0 + i * 0.6 for i in range(n)],
    "close": [100.5 + i * 0.6 for i in range(n)],
    "volume": [2000.0] * (n - 5) + [4000.0] * 5,
})
with patch("app.coinlist.ensure_coin_tracked", return_value=(True, False)), \
     patch("app.exchange.fetch_ohlcv", return_value=up_df), \
     patch("app.explain.explain_signal", return_value=""), \
     patch("app.chart_image.render_signal_chart", return_value=b""), \
     patch("app.telegram_notify.send_signal", new_callable=AsyncMock) as mock_send:
    interp = Interpretation(coin="BTC", direction="long", category="day_trading", unclear=False, reason="")
    asyncio.run(signal_processor.process_day_trading_signal(None, interp, notify_on_update=False))

assert mock_send.await_count == 0, "gemute coin mag ook bij een AUTONOOM signaal geen Telegram-melding krijgen"
journal = repo.list_journal(user_id, status=None)
assert len(journal) == 1, "de logboekregel moet wel gewoon aangemaakt zijn, alleen de melding wordt overgeslagen"
assert journal[0]["message_id"] is None

print("Task 10 Step 1: OK")
```

Run: `.venv/bin/python3 /tmp/claude_scratch/task10_muted_and_eval_check.py`
Expected: `Task 10 Step 1: OK`

Controleer daarnaast handmatig, door de scratch-scripts van Task 2 (Step 3/4), Task 3 (Step 5/6) en Task 5 (Step 3/4) nog eenmaal achter elkaar te draaien op een verse scratch-DB, dat er geen enkele regressie is opgetreden nu alle taken samen in dezelfde `app/signal_processor.py`/`app/market_scanner.py` zitten (elke eerdere taak test zijn eigen stuk in isolatie; deze stap is de eerste keer dat alles samen, in de uiteindelijke bestandsvorm, gedraaid wordt).

- [ ] **Step 2: handmatige Playwright-verificatie — noodrem-knop**

Vervolg op Task 4 Step 5: in dezelfde lokale server, klik de noodrem-knop op `/dashboard`, herlaad de pagina, controleer dat de knoptekst wisselt en dat een navolgende `repo.is_market_scan_enabled()`-check (via een losse REPL of een `/api/`-debug-aanroep als die bestaat) de nieuwe waarde teruggeeft.

- [ ] **Step 3: volledige scan_market() end-to-end tegen een realistische scratch-DB**

Schrijf `/tmp/claude_scratch/task10_full_scan_check.py`: een scratch-DB met 3-4 coins, een gemengde synthetische dataset (één duidelijke long-trend met genoeg volume, één short-trend, één vlak, en BTC zelf met een duidelijke trend zodat de BTC-vlak-rem niet ongewenst alles blokkeert), draai `market_scanner.scan_market()` eenmaal, en controleer:
- de juiste coins kregen een signaal, de vlakke niet;
- elk nieuw signaal heeft `message_id IS NULL`;
- `telegram_notify.send_signal` is aangeroepen voor elke bevestigde kans;
- als er 2+ nieuwe bevestigde kansen waren, is `send_scan_cycle_summary` precies 1 keer per gebruiker aangeroepen.

Run: `.venv/bin/python3 /tmp/claude_scratch/task10_full_scan_check.py`
Expected: geen AssertionError.

- [ ] **Step 4: opruimen en pushen**

```bash
rm -rf /tmp/claude_scratch /tmp/task*.db
git status --short
git push -u origin claude/crypto-day-trading-alerts-5p8w6v
```

- [ ] **Step 5: deploy-notitie voor de product owner**

Vermeld in de afrondende samenvatting aan de gebruiker (niet in code): na deployment op de VPS moet, naast de gebruikelijke `systemctl restart crypto-bot crypto-web`, ook

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now crypto-market-scan.timer
```

gedraaid worden — dit is een NIEUWE timer, die bestaat nog niet op de VPS en wordt niet automatisch opgepikt door een `restart` van de bestaande services.
