# Bewaakte niveaus voor lange-termijn signalen (swing watches) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Elk bericht met een opgeslagen bron-niveau (support/resistance uit een screenshot), ongeacht of de AI het als `day_trading` of `lange_termijn` classificeerde, wordt voortaan bewaakt tot de prijs er weer dichtbij komt. Op dat moment draait een volledige technische toets op daily én 4-uur candles, met een niveau-gebaseerde stop loss/take profit en positiegrootte, en een echte Telegram-actiemelding in plaats van een stille logregel.

**Architecture:** `signal_processor.evaluate_level_watch` maakt bij elk opgeslagen bron-niveau een `swing_watches`-regel aan en checkt direct of de prijs al dichtbij is. Zo niet, pakt `level_check.check_swing_watches()` (dezelfde 15-minuten timer als de bestaande level-check) hem later op. Zodra de prijs dichtbij komt, draait `signal_processor.run_swing_check`: daily + 4-uur factoren apart tonen (geen gecombineerd vertrouwenscijfer), niveau-gebaseerde SL/TP via een nieuwe `risk.compute_stop_take_from_levels` (met een harde ondergrens tegen absurde positiegroottes), journaalregel per gebruiker (`signals.trade_type = 'swing'`) en een niet-stille Telegram-melding die de bestaande Genomen/Negeren-knoppen hergebruikt.

**Tech Stack:** Python 3.11, FastAPI, SQLite (WAL), python-telegram-bot, ccxt/Binance, pandas/ta, Jinja2. Geen pytest in dit project — zie Global Constraints.

**Spec:** `docs/superpowers/specs/2026-09-06-swing-watches-design.md`

## Global Constraints

- **Geen pytest.** Dit project heeft geen testsuite en geen linter (zie CLAUDE.md). Verificatie gebeurt met stand-alone Python-scripts tegen een scratch-database (`DATABASE_PATH` env var naar een tijdelijk `.db`-bestand), met platte `assert`-statements en `print("OK: ...")`-regels. Elke teststap in dit plan volgt die stijl, niet `pytest tests/...`. Testscripts horen in de scratchpad-directory van de uitvoerende sessie (nooit in de git-repo committen), precies zoals elk ander testscript deze hele sessie al gedaan is.
- **Schema-migratie discipline (CLAUDE.md):** een NIEUWE tabel heeft alleen `CREATE TABLE IF NOT EXISTS` in `schema.sql` nodig. Een NIEUWE KOLOM op een BESTAANDE tabel heeft ALTIJD ook een idempotente `ALTER TABLE ... ADD COLUMN`, guarded door een `PRAGMA table_info`-check, in `app/db.py:_migrate()`. Een index op een kolom die pas door een migratie wordt toegevoegd hoort in `_migrate()`, nooit in `schema.sql`.
- **Database-toegang centraal via `app/repo.py`.** Geen losse SQL in `signal_processor.py`, `level_check.py`, `web/main.py` of scripts.
- **Elke stap die de database raakt, test zowel de VERSE-database-vorm (via `schema.sql`) als, waar een bestaande tabel een nieuwe kolom krijgt, de MIGRATIE-vorm (oude schema-vorm handmatig aanmaken met rauwe `sqlite3`, dan `db.init_db()` erover heen draaien).**
- **Na elke stap: de volledige bestaande regressie-testset (die je in de scratchpad van je sessie kunt terugvinden of opnieuw kunt schrijven volgens dit patroon) moet blijven slagen, niet alleen de nieuwe test.**
- **Geen vertrouwenspercentage voor swing-signalen.** Alleen losse ✓/✗ factoren tonen, nooit combineren tot één cijfer (zie spec, "Niet-doelen").
- **UI-scope van dit plan:** alleen de coin-pagina krijgt een nieuwe "Bewaakt niveau"-sectie. Winrate wordt apart berekend (`swing_winrate_stats`). Er komt geen aparte dashboard-sectie of journaal-tabel-herstructurering in dit plan; een swing-trade verschijnt gewoon tussen de normale open/historie-lijsten, zoals elke andere trade.

---

## Task 1: Schema en migratie — `swing_watches` tabel en `signals.trade_type`

**Files:**
- Modify: `app/schema.sql`
- Modify: `app/db.py:42-90` (`_migrate()`)
- Test: `<scratchpad>/test_swing_schema_migration.py`

**Interfaces:**
- Produces: tabel `swing_watches(id, message_id, source_level_id, coin, direction, status, created_at, checked_at)`. Kolom `signals.trade_type TEXT NOT NULL DEFAULT 'day_trading'`.

- [ ] **Step 1: Schrijf het testscript dat de MIGRATIE-vorm simuleert (oude schema, geen `trade_type`, geen `swing_watches`)**

Maak `<scratchpad>/test_swing_schema_migration.py` (vervang `<scratchpad>` door het pad uit je eigen sessie-instructies):

```python
import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, "/home/user/Trade")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-swing-schema-0123456789"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path

# --- Simuleer een BESTAANDE database van vóór deze feature: een oude
# signals-tabel zonder trade_type, en helemaal geen swing_watches-tabel. ---
conn = sqlite3.connect(db_path)
conn.execute("""
    CREATE TABLE signals (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        message_id INTEGER NOT NULL,
        coin TEXT NOT NULL,
        direction TEXT NOT NULL,
        category TEXT NOT NULL,
        confidence TEXT NOT NULL,
        is_practice INTEGER NOT NULL DEFAULT 0,
        created_at TEXT NOT NULL
    )
""")
conn.execute(
    "INSERT INTO signals (message_id, coin, direction, category, confidence, created_at) "
    "VALUES (1, 'BTC', 'long', 'day_trading', 'hoog vertrouwen', '2026-01-01T00:00:00+00:00')"
)
conn.commit()
conn.close()

from app import db

# --- init_db() moet dit oude schema bijwerken zonder de bestaande rij kwijt te raken. ---
db.init_db()

with db.session() as conn:
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(signals)")}
    assert "trade_type" in columns, f"trade_type ontbreekt na migratie, kolommen: {columns}"

    row = conn.execute("SELECT trade_type FROM signals WHERE id = 1").fetchone()
    assert row["trade_type"] == "day_trading", (
        f"bestaande rij moet de default 'day_trading' krijgen, kreeg {row['trade_type']!r}"
    )
    print("OK: signals.trade_type wordt via _migrate() toegevoegd met de juiste default")

    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "swing_watches" in tables, f"swing_watches-tabel ontbreekt, tabellen: {tables}"
    print("OK: swing_watches-tabel wordt aangemaakt op een bestaande database")

print("ALLE SCHEMA-MIGRATIETESTS GESLAAGD")
```

- [ ] **Step 2: Run het testscript, verwacht een AssertionError (de migratie bestaat nog niet)**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_schema_migration.py`
Expected: `AssertionError: trade_type ontbreekt na migratie`

- [ ] **Step 3: Voeg `trade_type` toe aan de `signals`-tabel in `app/schema.sql`**

In `app/schema.sql`, in de `CREATE TABLE IF NOT EXISTS signals (...)`-blok (regel 110-135), voeg de kolom toe vlak na `is_practice`:

```sql
    is_practice INTEGER NOT NULL DEFAULT 0,
    -- 'day_trading' of 'swing': welk mechanisme dit signaal produceerde.
    -- Swing-signalen komen uit een bewaakt bron-niveau (zie swing_watches),
    -- hebben geen hoog/laag vertrouwen-label (nog niet gevalideerd op deze
    -- tijdshorizon) en worden apart geteld in winrate/journaal.
    trade_type TEXT NOT NULL DEFAULT 'day_trading',
    plain_explanation TEXT,
```

(Dit vervangt de bestaande twee regels `is_practice INTEGER NOT NULL DEFAULT 0,` en `plain_explanation TEXT,` door deze drie regels, in dezelfde volgorde als ze al in het bestand staan.)

- [ ] **Step 4: Voeg de nieuwe `swing_watches`-tabel toe aan `app/schema.sql`**

Voeg dit toe direct na de `CREATE TABLE IF NOT EXISTS journal_entries (...)`-blok (na regel 159, vóór de `settings`-tabel):

```sql
-- Bewaakt een bron-niveau (support/resistance uit een screenshot) totdat
-- de prijs er weer dichtbij komt. Ongeacht of het onderliggende bericht
-- day_trading of lange_termijn was: elk bericht met een niveau krijgt een
-- watch. Geen migratie nodig, dit is een gloednieuwe tabel.
CREATE TABLE IF NOT EXISTS swing_watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id),
    source_level_id INTEGER NOT NULL REFERENCES source_levels(id),
    coin TEXT NOT NULL,
    direction TEXT NOT NULL,
    -- wachtend/bevestigd/vervallen/ongeldig, zie de spec.
    status TEXT NOT NULL DEFAULT 'wachtend',
    created_at TEXT NOT NULL,
    checked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_swing_watches_status ON swing_watches(status);
CREATE INDEX IF NOT EXISTS idx_swing_watches_coin ON swing_watches(coin);
```

- [ ] **Step 5: Voeg de migratie voor `signals.trade_type` toe aan `app/db.py:_migrate()`**

In `app/db.py`, in de `existing = {row["name"] for row in conn.execute("PRAGMA table_info(signals)")}`-sectie (regel 46-54), voeg toe na de `plain_explanation`-check:

```python
    if "plain_explanation" not in existing:
        conn.execute("ALTER TABLE signals ADD COLUMN plain_explanation TEXT")
    if "trade_type" not in existing:
        conn.execute("ALTER TABLE signals ADD COLUMN trade_type TEXT NOT NULL DEFAULT 'day_trading'")
```

- [ ] **Step 6: Run het testscript opnieuw, verwacht dat beide asserts slagen**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_schema_migration.py`
Expected: `ALLE SCHEMA-MIGRATIETESTS GESLAAGD`

- [ ] **Step 7: Commit**

```bash
git add app/schema.sql app/db.py
git commit -m "$(cat <<'EOF'
Schema: swing_watches tabel en signals.trade_type

Basis voor de bewaakte-niveaus feature (zie docs/superpowers/specs/
2026-09-06-swing-watches-design.md): elk bron-niveau kan voortaan een
eigen watch krijgen, en signalen worden gelabeld als 'day_trading' of
'swing' zodat winrate/journaal ze straks apart kunnen behandelen.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `app/repo.py` — trade_type, swing_watches CRUD, aparte winrate

**Files:**
- Modify: `app/repo.py`
- Test: `<scratchpad>/test_swing_repo.py`

**Interfaces:**
- Consumes: tabellen uit Task 1.
- Produces:
  - `insert_signal(data: dict) -> int` (bestaand, nu met `trade_type` support, default `"day_trading"`)
  - `create_swing_watch(message_id: int, source_level_id: int, coin: str, direction: str) -> int`
  - `get_swing_watch(watch_id: int) -> Optional[dict]` (velden: id, message_id, source_level_id, coin, direction, status, created_at, checked_at, price_level, pattern_name)
  - `list_watches_by_status(status: str) -> list[dict]` (zelfde velden)
  - `update_swing_watch_status(watch_id: int, status: str) -> None`
  - `active_swing_watches_for_coin(coin: str) -> list[dict]` (zelfde velden, alleen status='wachtend')
  - `list_source_levels_for_message(message_id: int) -> list[dict]`
  - `list_recent_source_levels_without_watch(since_iso: str) -> list[dict]` (velden: source_level_id, message_id, coin, price_level, pattern_name, direction)
  - `swing_winrate_stats(user_id: int) -> dict` (velden: total, wins, winrate, avg_result_eur, avg_result_pct)
  - `winrate_stats(user_id: int) -> dict` (bestaand, nu gefilterd op `trade_type = 'day_trading'`)
  - `_JOURNAL_SELECT` bevat nu ook `trade_type`

- [ ] **Step 1: Schrijf het testscript voor `insert_signal`'s trade_type-default**

Maak `<scratchpad>/test_swing_repo.py`:

```python
import os
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, "/home/user/Trade")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-swing-repo-0123456789"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path

from app import db, repo

db.init_db()
uid = repo.create_user("swingrepo", "hash", 1000.0, 1.0, "111")
now_iso = datetime.now(timezone.utc).isoformat()

with db.session() as conn:
    conn.execute(
        "INSERT INTO messages (received_at, raw_text, category, coin, direction) "
        "VALUES (?, 'test', 'day_trading', 'BTC', 'long')",
        (now_iso,),
    )
    msg_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

# --- insert_signal zonder trade_type moet 'day_trading' als default krijgen ---
sig_id_default = repo.insert_signal({
    "message_id": msg_id, "coin": "BTC", "direction": "long", "category": "day_trading",
    "confidence": "hoog vertrouwen", "reason": "EMA ✓", "is_practice": 0,
})
with db.session() as conn:
    row = conn.execute("SELECT trade_type FROM signals WHERE id = ?", (sig_id_default,)).fetchone()
assert row["trade_type"] == "day_trading", f"verwacht default 'day_trading', kreeg {row['trade_type']!r}"
print("OK: insert_signal zonder trade_type krijgt de default 'day_trading'")

# --- insert_signal met expliciete trade_type='swing' moet dat ook opslaan ---
sig_id_swing = repo.insert_signal({
    "message_id": msg_id, "coin": "BTC", "direction": "long", "category": "swing",
    "confidence": "niveau bevestigd", "reason": "Daily: ...", "is_practice": 0, "trade_type": "swing",
})
with db.session() as conn:
    row = conn.execute("SELECT trade_type FROM signals WHERE id = ?", (sig_id_swing,)).fetchone()
assert row["trade_type"] == "swing", f"verwacht 'swing', kreeg {row['trade_type']!r}"
print("OK: insert_signal met trade_type='swing' slaat dat correct op")

print("ALLE REPO-TESTS DEEL 1 GESLAAGD (meer volgt in latere stappen van dit plan)")
```

- [ ] **Step 2: Run, verwacht een fout (trade_type nog geen kolom in `fields`)**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_repo.py`
Expected: `sqlite3.OperationalError` of een assertion failure over trade_type.

- [ ] **Step 3: Voeg `trade_type` toe aan `insert_signal` in `app/repo.py`**

Vervang de bestaande `insert_signal`-functie (regel 373-388) door:

```python
def insert_signal(data: dict) -> int:
    fields = [
        "message_id", "coin", "direction", "category", "price", "rsi", "macd",
        "macd_signal", "volume_ratio", "ema9", "ema21", "atr", "atr_avg20", "adx",
        "technical_confirmed", "confidence", "reason", "stop_loss", "take_profit",
        "context_note", "is_practice", "plain_explanation", "trade_type",
    ]
    values = [
        data.get("is_practice", 0) if f == "is_practice"
        else data.get("trade_type", "day_trading") if f == "trade_type"
        else data.get(f)
        for f in fields
    ]
    placeholders = ", ".join("?" for _ in fields)
    with db.session() as conn:
        cur = conn.execute(
            f"""INSERT INTO signals ({", ".join(fields)}, created_at)
                VALUES ({placeholders}, ?)""",
            (*values, db.now_iso()),
        )
        return cur.lastrowid
```

- [ ] **Step 4: Run opnieuw, verwacht dat beide asserts uit Step 1 slagen**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_repo.py`
Expected: beide "OK:"-regels en "ALLE REPO-TESTS DEEL 1 GESLAAGD"

- [ ] **Step 5: Voeg `trade_type` toe aan `_JOURNAL_SELECT`**

In `app/repo.py`, in `_JOURNAL_SELECT` (rond regel 549), voeg toe direct na `s.category AS category,`:

```python
        s.coin AS coin, s.direction AS direction, s.category AS category,
        s.trade_type AS trade_type,
        s.price AS price,
```

- [ ] **Step 6: Voeg de swing_watches CRUD-functies toe**

Voeg dit toe in `app/repo.py`, direct na de bestaande `list_source_levels`-functie (na regel 160):

```python
_SWING_WATCH_SELECT = """
    SELECT sw.id AS id, sw.message_id AS message_id, sw.source_level_id AS source_level_id,
           sw.coin AS coin, sw.direction AS direction, sw.status AS status,
           sw.created_at AS created_at, sw.checked_at AS checked_at,
           sl.price_level AS price_level, sl.pattern_name AS pattern_name
    FROM swing_watches sw
    JOIN source_levels sl ON sl.id = sw.source_level_id
"""


def create_swing_watch(message_id: int, source_level_id: int, coin: str, direction: str) -> int:
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO swing_watches (message_id, source_level_id, coin, direction, status, created_at)
               VALUES (?, ?, ?, ?, 'wachtend', ?)""",
            (message_id, source_level_id, coin.upper(), direction.lower(), db.now_iso()),
        )
        return cur.lastrowid


def get_swing_watch(watch_id: int) -> Optional[dict]:
    with db.session() as conn:
        row = conn.execute(_SWING_WATCH_SELECT + "WHERE sw.id = ?", (watch_id,)).fetchone()
        return dict(row) if row else None


def list_watches_by_status(status: str) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(_SWING_WATCH_SELECT + "WHERE sw.status = ?", (status,)).fetchall()
        return [dict(r) for r in rows]


def update_swing_watch_status(watch_id: int, status: str) -> None:
    with db.session() as conn:
        conn.execute(
            "UPDATE swing_watches SET status = ?, checked_at = ? WHERE id = ?",
            (status, db.now_iso(), watch_id),
        )


def active_swing_watches_for_coin(coin: str) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            _SWING_WATCH_SELECT + "WHERE sw.coin = ? AND sw.status = 'wachtend' ORDER BY sw.created_at DESC",
            (coin.upper(),),
        ).fetchall()
        return [dict(r) for r in rows]


def list_source_levels_for_message(message_id: int) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM source_levels WHERE message_id = ?", (message_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_recent_source_levels_without_watch(since_iso: str) -> list[dict]:
    """Bron-niveaus van na `since_iso` die nog geen swing_watches-regel
    hebben, met de richting van hun eigen bericht erbij. Voor het eenmalige
    backfill-script (scripts/backfill_swing_watches.py). Alleen bruikbaar
    als het bericht zelf een duidelijke long/short richting had: 'neutraal'
    of leeg heeft geen kant om een niveau tegen te toetsen."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT sl.id AS source_level_id, sl.message_id AS message_id,
                      sl.coin AS coin, sl.price_level AS price_level, sl.pattern_name AS pattern_name,
                      m.direction AS direction
               FROM source_levels sl
               JOIN messages m ON m.id = sl.message_id
               LEFT JOIN swing_watches sw ON sw.source_level_id = sl.id
               WHERE sw.id IS NULL AND sl.created_at >= ? AND m.direction IN ('long', 'short')""",
            (since_iso,),
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 7: Schrijf de test voor de swing_watches CRUD-functies**

Voeg toe aan het einde van `<scratchpad>/test_swing_repo.py` (vóór de laatste `print`-regel, die je verplaatst naar helemaal onderaan):

```python
# --- swing_watches CRUD ---
with db.session() as conn:
    conn.execute(
        "INSERT INTO source_levels (message_id, coin, price_level, pattern_name, created_at) "
        "VALUES (?, 'ETH', 0.836, 'resistance', ?)",
        (msg_id, now_iso),
    )
    level_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

watch_id = repo.create_swing_watch(msg_id, level_id, "ETH", "long")
watch = repo.get_swing_watch(watch_id)
assert watch is not None
assert watch["status"] == "wachtend"
assert watch["price_level"] == 0.836
assert watch["pattern_name"] == "resistance"
print("OK: create_swing_watch + get_swing_watch geven de juiste velden terug, status 'wachtend'")

waiting = repo.list_watches_by_status("wachtend")
assert any(w["id"] == watch_id for w in waiting)
print("OK: list_watches_by_status('wachtend') bevat de nieuwe watch")

active_for_coin = repo.active_swing_watches_for_coin("ETH")
assert any(w["id"] == watch_id for w in active_for_coin)
print("OK: active_swing_watches_for_coin('ETH') bevat de nieuwe watch")

repo.update_swing_watch_status(watch_id, "bevestigd")
updated = repo.get_swing_watch(watch_id)
assert updated["status"] == "bevestigd"
assert updated["checked_at"] is not None
assert repo.active_swing_watches_for_coin("ETH") == []
print("OK: update_swing_watch_status zet status en checked_at, verdwijnt uit 'actief'")

levels_for_message = repo.list_source_levels_for_message(msg_id)
assert len(levels_for_message) == 1 and levels_for_message[0]["price_level"] == 0.836
print("OK: list_source_levels_for_message geeft alleen de niveaus van dit bericht")

# --- backfill-helper: een niveau zonder watch moet gevonden worden ---
with db.session() as conn:
    conn.execute(
        "INSERT INTO messages (received_at, raw_text, category, coin, direction) "
        "VALUES (?, 'test 2', 'lange_termijn', 'SOL', 'short')",
        (now_iso,),
    )
    msg2_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.execute(
        "INSERT INTO source_levels (message_id, coin, price_level, pattern_name, created_at) "
        "VALUES (?, 'SOL', 140.0, 'support', ?)",
        (msg2_id, now_iso),
    )

since_iso = "2020-01-01T00:00:00+00:00"
without_watch = repo.list_recent_source_levels_without_watch(since_iso)
assert any(lvl["coin"] == "SOL" and lvl["direction"] == "short" for lvl in without_watch)
assert not any(lvl["coin"] == "ETH" for lvl in without_watch), "ETH had al een watch, hoort er niet meer in"
print("OK: list_recent_source_levels_without_watch vindt alleen niveaus zonder watch")

print("ALLE REPO-TESTS DEEL 2 GESLAAGD")
```

- [ ] **Step 8: Run, verwacht een fout (functies bestaan nog niet)**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_repo.py`
Expected: `AttributeError: module 'app.repo' has no attribute 'create_swing_watch'`

- [ ] **Step 9: Run opnieuw na Step 6, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_repo.py`
Expected: alle "OK:"-regels, eindigend met "ALLE REPO-TESTS DEEL 2 GESLAAGD"

- [ ] **Step 10: Voeg `swing_winrate_stats` toe en filter `winrate_stats` op `trade_type`**

In `app/repo.py`, in de bestaande `winrate_stats`-functie, wijzig de WHERE-clause van:

```python
            """SELECT s.confidence AS confidence, je.result_eur AS result_eur,
                      je.risk_eur AS risk_eur
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL AND s.is_practice = 0""",
```

naar:

```python
            """SELECT s.confidence AS confidence, je.result_eur AS result_eur,
                      je.risk_eur AS risk_eur
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL AND s.is_practice = 0
                     AND s.trade_type = 'day_trading'""",
```

Voeg direct na `winrate_stats` toe:

```python
def swing_winrate_stats(user_id: int) -> dict:
    """Winrate en gemiddeld resultaat van gesloten swing-trades, apart van
    winrate_stats (day trading): andere tijdshorizon, ander risicoprofiel,
    en swing heeft geen hoog/laag vertrouwen-label om op te splitsen (geen
    vertrouwenscijfer zonder backtest op deze tijdshorizon, zie de spec)."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT je.result_eur AS result_eur, je.risk_eur AS risk_eur
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL
                     AND s.is_practice = 0 AND s.trade_type = 'swing'""",
            (user_id,),
        ).fetchall()
    total = len(rows)
    wins = len([r for r in rows if r["result_eur"] is not None and r["result_eur"] > 0])
    winrate = (wins / total * 100) if total else 0.0
    eur_values = [r["result_eur"] for r in rows if r["result_eur"] is not None]
    pct_values = [
        r["result_eur"] / r["risk_eur"] * 100
        for r in rows if r["result_eur"] is not None and r["risk_eur"]
    ]
    avg_eur = sum(eur_values) / len(eur_values) if eur_values else 0.0
    avg_pct = sum(pct_values) / len(pct_values) if pct_values else 0.0
    return {
        "total": total, "wins": wins, "winrate": round(winrate, 1),
        "avg_result_eur": round(avg_eur, 2), "avg_result_pct": round(avg_pct, 1),
    }
```

- [ ] **Step 11: Schrijf de test voor de winrate-scheiding**

Voeg toe aan het einde van `<scratchpad>/test_swing_repo.py`:

```python
# --- winrate_stats en swing_winrate_stats moeten elkaar niet vervuilen ---
def make_closed_trade(coin, direction, trade_type, confidence, result_eur, risk_eur=10.0):
    with db.session() as conn:
        conn.execute(
            "INSERT INTO messages (received_at, raw_text, category, coin, direction) "
            "VALUES (?, 'test', 'day_trading', ?, ?)",
            (now_iso, coin, direction),
        )
        m_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    sig_id = repo.insert_signal({
        "message_id": m_id, "coin": coin, "direction": direction, "category": trade_type,
        "confidence": confidence, "reason": "test", "is_practice": 0, "trade_type": trade_type,
    })
    entry_id = repo.create_journal_entry(sig_id, uid, risk_eur)
    with db.session() as conn:
        conn.execute(
            "UPDATE journal_entries SET entry_price = 100, exit_price = 110, "
            "exit_time = ?, result_eur = ?, status = 'gesloten' WHERE id = ?",
            (now_iso, result_eur, entry_id),
        )

make_closed_trade("BTC", "long", "day_trading", "hoog vertrouwen", 20.0)
make_closed_trade("ETH", "long", "swing", "niveau bevestigd", 50.0)

day_stats = repo.winrate_stats(uid)
swing_stats = repo.swing_winrate_stats(uid)
assert day_stats["hoog_vertrouwen"]["total"] == 1, (
    f"day trading winrate moet alleen de day_trading-trade tellen, kreeg {day_stats}"
)
assert swing_stats["total"] == 1 and swing_stats["wins"] == 1, (
    f"swing winrate moet alleen de swing-trade tellen, kreeg {swing_stats}"
)
print("OK: winrate_stats (day trading) en swing_winrate_stats vervuilen elkaar niet")

print("ALLE REPO-TESTS GESLAAGD")
```

(Verwijder de losstaande `print("ALLE REPO-TESTS DEEL 2 GESLAAGD")` van Step 7, die vervangt dit.)

- [ ] **Step 12: Run het volledige testscript, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_repo.py`
Expected: alle "OK:"-regels, eindigend met "ALLE REPO-TESTS GESLAAGD"

- [ ] **Step 13: Commit**

```bash
git add app/repo.py
git commit -m "$(cat <<'EOF'
repo.py: trade_type-ondersteuning en swing_watches CRUD

insert_signal en _JOURNAL_SELECT kennen nu trade_type. Nieuwe functies
voor het aanmaken, opvragen en bijwerken van bewaakte niveaus, en een
losse swing_winrate_stats zodat swing-trades de bestaande day-trading
winrate niet vervuilen (zie de spec).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: `app/risk.py` — niveau-gebaseerde stop loss/take profit

**Files:**
- Modify: `app/risk.py`
- Test: `<scratchpad>/test_swing_risk.py`

**Interfaces:**
- Consumes: niets nieuws (pure functie, geen database/netwerk).
- Produces: `compute_stop_take_from_levels(direction: str, entry_price: float, atr: float, levels: list[float], swing_low: Optional[float] = None, swing_high: Optional[float] = None) -> StopTake`

Dit is de financieel gevoeligste functie in dit plan: een niveau te dicht bij de prijs mag NOOIT een piepklein risico-verschil opleveren (zie de spec, "Het gevaarlijkste gat").

- [ ] **Step 1: Schrijf de tests, allemaal eerst (pure functie, geen I/O, geen scratch-database nodig)**

Maak `<scratchpad>/test_swing_risk.py`:

```python
import sys
sys.path.insert(0, "/home/user/Trade")

from app import risk

# --- Long, een bruikbaar niveau ruim onder de prijs, geen tweede niveau ---
# entry 100, atr 2, niveau op 95 (5 punten onder prijs, ruim boven de
# ondergrens van 0.5 x atr = 1). Geen niveau boven de prijs, dus take
# profit valt terug op 2x de zo ontstane risico-afstand.
result = risk.compute_stop_take_from_levels("long", entry_price=100.0, atr=2.0, levels=[95.0])
expected_stop = 95.0 - risk.ATR_BUFFER_MULTIPLIER * 2.0
assert abs(result.stop_loss - expected_stop) < 1e-9, f"verwacht stop {expected_stop}, kreeg {result.stop_loss}"
expected_risk_distance = 100.0 - expected_stop
expected_take = 100.0 + risk.RISK_REWARD_RATIO * expected_risk_distance
assert abs(result.take_profit - expected_take) < 1e-9, f"verwacht take {expected_take}, kreeg {result.take_profit}"
print("OK: long met alleen een support-niveau gebruikt dat niveau als stop, 2x-risico als target")

# --- Long, support én resistance allebei aanwezig: resistance wordt het target ---
result = risk.compute_stop_take_from_levels("long", entry_price=100.0, atr=2.0, levels=[95.0, 110.0])
assert abs(result.take_profit - 110.0) < 1e-9, f"verwacht take_profit op het niveau zelf (110), kreeg {result.take_profit}"
print("OK: long met support én resistance gebruikt de resistance zelf als take profit")

# --- Long, meerdere niveaus aan dezelfde kant: het DICHTSTBIJZIJNDE telt ---
result = risk.compute_stop_take_from_levels("long", entry_price=100.0, atr=2.0, levels=[80.0, 95.0])
expected_stop = 95.0 - risk.ATR_BUFFER_MULTIPLIER * 2.0
assert abs(result.stop_loss - expected_stop) < 1e-9, (
    f"verwacht de dichtstbijzijnde support (95) als stop, kreeg {result.stop_loss}"
)
print("OK: bij meerdere support-niveaus wordt het dichtstbijzijnde gebruikt als stop")

# --- HET GEVAARLIJKSTE GEVAL: niveau te dicht bij de prijs, moet terugvallen op ATR ---
# entry 100, atr 2, ondergrens is 0.5 x 2 = 1. Een niveau op 99.5 ligt daar
# ruim binnen (0.5 verschil < 1), dus dit MAG NOOIT als stop gebruikt worden.
fallback = risk.compute_stop_take("long", entry_price=100.0, atr=2.0, swing_low=None, swing_high=None)
result = risk.compute_stop_take_from_levels(
    "long", entry_price=100.0, atr=2.0, levels=[99.5], swing_low=None, swing_high=None,
)
assert abs(result.stop_loss - fallback.stop_loss) < 1e-9, (
    f"een niveau te dicht bij de prijs moet terugvallen op de gewone ATR-berekening, "
    f"verwacht stop {fallback.stop_loss} (fallback), kreeg {result.stop_loss}"
)
assert abs(result.stop_loss - 99.5) > 0.01, "de te-dichtbije 99.5 mag NOOIT direct als stop gebruikt worden"
print("OK: een niveau te dicht bij de prijs (< 0.5x ATR) valt terug op de gewone ATR-berekening")

# --- Geen enkel niveau aan de stop-kant, WEL een niveau aan de target-kant:
# de stop valt terug op ATR, maar het target-niveau moet niet zomaar
# weggegooid worden, dat is nog steeds bruikbare informatie. ---
result = risk.compute_stop_take_from_levels(
    "long", entry_price=100.0, atr=2.0, levels=[110.0, 120.0], swing_low=None, swing_high=None,
)
assert abs(result.stop_loss - fallback.stop_loss) < 1e-9, (
    "alleen niveaus BOVEN de prijs bij een long zijn geen bruikbare stop, moet terugvallen op ATR"
)
assert abs(result.take_profit - 110.0) < 1e-9, (
    f"het dichtstbijzijnde niveau BOVEN de prijs (110) moet wel als take_profit gebruikt worden, "
    f"ook al viel de stop terug op ATR, kreeg {result.take_profit}"
)
print("OK: een target-niveau blijft gebruikt als take profit, ook als de stop zelf op ATR terugvalt")

# --- Short: spiegelbeeld van long ---
result = risk.compute_stop_take_from_levels("short", entry_price=100.0, atr=2.0, levels=[105.0, 90.0])
expected_stop = 105.0 + risk.ATR_BUFFER_MULTIPLIER * 2.0
assert abs(result.stop_loss - expected_stop) < 1e-9, f"verwacht stop {expected_stop}, kreeg {result.stop_loss}"
assert abs(result.take_profit - 90.0) < 1e-9, f"verwacht take_profit op het niveau (90), kreeg {result.take_profit}"
print("OK: short gebruikt het niveau boven de prijs als stop, het niveau eronder als target")

# --- Onbekende richting geeft een duidelijke fout, geen stille verkeerde uitkomst ---
try:
    risk.compute_stop_take_from_levels("sideways", entry_price=100.0, atr=2.0, levels=[95.0])
    assert False, "had een ValueError moeten geven bij een onbekende richting"
except ValueError:
    print("OK: een onbekende richting geeft een ValueError, geen stille verkeerde berekening")

print("ALLE SWING-RISK TESTS GESLAAGD")
```

- [ ] **Step 2: Run, verwacht een `AttributeError` (de functie bestaat nog niet)**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_risk.py`
Expected: `AttributeError: module 'app.risk' has no attribute 'compute_stop_take_from_levels'`

- [ ] **Step 3: Implementeer `compute_stop_take_from_levels` in `app/risk.py`**

Voeg toe aan `app/risk.py`, na de bestaande `compute_stop_take`-functie (na regel 49), vóór `compute_risk_eur`:

```python
# Ondergrens op hoeveel een niveau-gebaseerde stop mag afwijken van de
# prijs, als fractie van de ATR. Kleiner dan dit: het niveau levert geen
# bruikbare stop op (te dichtbij, een piepklein verschil zou de
# positiegrootte absurd groot maken: risico gedeeld door een
# verwaarloosbare afstand). Val in dat geval terug op de gewone
# ATR-berekening.
MIN_LEVEL_STOP_DISTANCE_ATR_FRACTION = 0.5


def compute_stop_take_from_levels(
    direction: str, entry_price: float, atr: float, levels: list[float],
    swing_low: Optional[float] = None, swing_high: Optional[float] = None,
) -> StopTake:
    """Stop loss en take profit op basis van door de bron ingetekende
    niveaus (support/resistance), in plaats van pure marktstructuur/ATR.
    Welk niveau de stop is en welk het target, wordt bepaald door de
    positie van het niveau ten opzichte van de entry-prijs en de richting,
    nooit door een losse tekstlabel (pattern_name) te matchen: bij long is
    het dichtstbijzijnde niveau ONDER de prijs de stop-basis, het
    dichtstbijzijnde niveau ERBOVEN het target (bij short omgekeerd).

    Een niveau te dicht bij de prijs (kleiner dan
    MIN_LEVEL_STOP_DISTANCE_ATR_FRACTION x ATR) is geen bruikbare stop en
    valt terug op compute_stop_take voor de stop. Datzelfde geldt als er
    helemaal geen niveau aan de stop-kant van de prijs ligt. Een
    bruikbaar target-niveau blijft in dat geval WEL gebruikt: de stop en
    het target worden onafhankelijk van elkaar bepaald, een ontbrekend of
    te dichtbij stop-niveau is geen reden om ook een prima target-niveau
    weg te gooien."""
    direction = direction.lower()
    if direction not in ("long", "short"):
        raise ValueError(f"onbekende richting: {direction}")

    if direction == "long":
        stop_candidates = [lvl for lvl in levels if lvl < entry_price]
        target_candidates = [lvl for lvl in levels if lvl > entry_price]
        stop_level = max(stop_candidates) if stop_candidates else None
        target_level = min(target_candidates) if target_candidates else None
    else:
        stop_candidates = [lvl for lvl in levels if lvl > entry_price]
        target_candidates = [lvl for lvl in levels if lvl < entry_price]
        stop_level = min(stop_candidates) if stop_candidates else None
        target_level = max(target_candidates) if target_candidates else None

    min_distance = MIN_LEVEL_STOP_DISTANCE_ATR_FRACTION * atr
    use_level_stop = stop_level is not None and abs(entry_price - stop_level) >= min_distance

    if use_level_stop:
        buffer = ATR_BUFFER_MULTIPLIER * atr
        stop_loss = stop_level - buffer if direction == "long" else stop_level + buffer
    else:
        stop_loss = compute_stop_take(
            direction, entry_price, atr, swing_low=swing_low, swing_high=swing_high,
        ).stop_loss

    risk_distance = abs(entry_price - stop_loss)
    if target_level is not None:
        take_profit = target_level
    elif direction == "long":
        take_profit = entry_price + RISK_REWARD_RATIO * risk_distance
    else:
        take_profit = entry_price - RISK_REWARD_RATIO * risk_distance

    return StopTake(stop_loss=stop_loss, take_profit=take_profit)
```

- [ ] **Step 4: Run de tests opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_risk.py`
Expected: alle "OK:"-regels, eindigend met "ALLE SWING-RISK TESTS GESLAAGD"

- [ ] **Step 5: Commit**

```bash
git add app/risk.py
git commit -m "$(cat <<'EOF'
risk.py: niveau-gebaseerde stop loss/take profit voor swing-signalen

compute_stop_take_from_levels gebruikt een bron-niveau (support/
resistance) als stop/target op basis van zijn positie t.o.v. de prijs,
nooit op basis van vrije-tekst pattern_name. Een niveau te dicht bij de
prijs (< 0.5x ATR) valt terug op de bestaande ATR-berekening, dit
voorkomt een absurd grote positiegrootte door een piepklein
risico-verschil.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `app/indicators.py` — gedeelde factoren-extractie en daily-trend factor

**Files:**
- Modify: `app/indicators.py`
- Test: `<scratchpad>/test_swing_indicators.py`

**Interfaces:**
- Produces:
  - `basic_factors(direction: str, ind: Indicators) -> list[tuple[str, bool, str]]` (de vier bestaande basisfactoren, los van enige drempel-beslissing)
  - `check_daily_trend(direction: str, daily_ind: Indicators) -> tuple[str, bool, str]`
- Wijzigt bestaand gedrag: `confirms_direction` gebruikt nu `basic_factors` intern. **Het teruggegeven `(bool, str)`-resultaat van `confirms_direction` moet exact hetzelfde blijven als vóór deze refactor** — dit is een DRY-opschoning, geen gedragswijziging.

- [ ] **Step 1: Schrijf een regressietest die `confirms_direction`'s HUIDIGE gedrag vastlegt, vóór de refactor**

Maak `<scratchpad>/test_swing_indicators.py`:

```python
import sys
sys.path.insert(0, "/home/user/Trade")

from app.indicators import Indicators, confirms_direction, check_daily_trend, basic_factors

# Fixture: een duidelijk bevestigde long-opzet op de basisfactoren.
bullish = Indicators(
    price=100.0, rsi=60.0, macd=1.5, macd_signal=1.0, volume_ratio=1.2,
    ema9=105.0, ema21=100.0, atr=2.0, atr_avg20=2.0, adx=20.0,
)
# Fixture: duidelijk NIET bevestigd voor long (trend en momentum tegen).
bearish_for_long = Indicators(
    price=100.0, rsi=60.0, macd=0.5, macd_signal=1.0, volume_ratio=0.8,
    ema9=95.0, ema21=100.0, atr=2.0, atr_avg20=2.0, adx=20.0,
)

# --- Regressie: confirms_direction moet exact hetzelfde blijven geven ---
confirmed, reason = confirms_direction(bullish, "long")
assert confirmed is True, f"bullish fixture moet long bevestigen, kreeg confirmed={confirmed}, reason={reason}"
assert reason.count("✓") == 4, f"alle 4 basisfactoren moeten ✓ zijn in de bullish fixture, reason={reason}"
print("OK: confirms_direction bevestigt de bullish fixture nog steeds voor long (regressie)")

confirmed, reason = confirms_direction(bearish_for_long, "long")
assert confirmed is False, f"bearish fixture mag long niet bevestigen, kreeg confirmed={confirmed}"
print("OK: confirms_direction wijst de bearish fixture nog steeds af voor long (regressie)")

# --- Nieuw: basic_factors geeft dezelfde vier factoren los terug ---
factors = basic_factors("long", bullish)
assert len(factors) == 4, f"verwacht 4 basisfactoren, kreeg {len(factors)}"
names = [name for name, ok, detail in factors]
assert names == ["Trend", "Momentum", "RSI", "Volume"], f"verwachte namen/volgorde, kreeg {names}"
assert all(ok for name, ok, detail in factors), f"alle factoren moeten ok=True zijn voor de bullish fixture, {factors}"
print("OK: basic_factors geeft de 4 basisfactoren in dezelfde vorm als confirms_direction gebruikte")

# --- Nieuw: check_daily_trend, zelfde soort logica als check_1h_trend ---
daily_up = Indicators(
    price=100.0, rsi=50.0, macd=0.0, macd_signal=0.0, volume_ratio=1.0,
    ema9=105.0, ema21=100.0, atr=2.0, atr_avg20=2.0, adx=20.0,
)
name, ok, detail = check_daily_trend("long", daily_up)
assert name == "Daily-trend" and ok is True, f"daily EMA9>EMA21 moet long bevestigen, kreeg {(name, ok, detail)}"
name, ok, detail = check_daily_trend("short", daily_up)
assert ok is False, f"daily-trend omhoog mag short niet bevestigen, kreeg {(name, ok, detail)}"
print("OK: check_daily_trend bevestigt long bij een stijgende daily trend, short niet")

print("ALLE SWING-INDICATOR TESTS GESLAAGD")
```

- [ ] **Step 2: Run, verwacht een fout (`basic_factors`/`check_daily_trend` bestaan nog niet)**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_indicators.py`
Expected: `ImportError: cannot import name 'check_daily_trend'`

- [ ] **Step 3: Voeg `basic_factors` toe en laat `confirms_direction` het gebruiken**

In `app/indicators.py`, vervang de `confirms_direction`-functie (regel 200-260, tot en met de `factors = [...]`-lijst) door: eerst een nieuwe `basic_factors`-functie vóór `confirms_direction`, dan `confirms_direction` zelf ingekort.

Vervang het stuk vanaf `direction = direction.lower()` (regel 229) tot en met de `factors = [...]`-toewijzing (regel 260) door:

```python
def basic_factors(direction: str, ind: Indicators) -> list[tuple[str, bool, str]]:
    """De vier basisfactoren (trend, momentum, RSI, volume) als losse
    (naam, ok, detail) tuples, onafhankelijk van enige drempel-beslissing.
    Gebruikt door confirms_direction voor de day-trading toets, en door de
    swing-toets in signal_processor.py om dezelfde factoren te tonen op
    een andere tijdshorizon zonder een gecombineerd vertrouwensoordeel."""
    direction = direction.lower()
    trend_up = ind.ema9 > ind.ema21
    momentum_up = ind.macd > ind.macd_signal

    if direction == "long":
        trend_ok = trend_up
        trend_detail = "EMA9 boven EMA21" if trend_up else "EMA9 onder EMA21, geen opwaartse trend"
        momentum_ok = momentum_up
        momentum_detail = ("MACD boven signaallijn" if momentum_up
                            else "MACD onder signaallijn, geen opwaarts momentum")
        rsi_ok = ind.rsi < 75
        rsi_detail = f"RSI {ind.rsi:.0f}" if rsi_ok else f"RSI {ind.rsi:.0f}, overbought"
    elif direction == "short":
        trend_ok = not trend_up
        trend_detail = "EMA9 onder EMA21" if trend_ok else "EMA9 boven EMA21, geen neerwaartse trend"
        momentum_ok = not momentum_up
        momentum_detail = ("MACD onder signaallijn" if momentum_ok
                            else "MACD boven signaallijn, geen neerwaarts momentum")
        rsi_ok = ind.rsi > 25
        rsi_detail = f"RSI {ind.rsi:.0f}" if rsi_ok else f"RSI {ind.rsi:.0f}, oversold"
    else:
        raise ValueError(f"onbekende richting: {direction}")

    volume_ok = ind.volume_ratio >= 1.0
    volume_detail = f"volume {ind.volume_ratio:.2f}x gemiddeld" + ("" if volume_ok else ", onder gemiddeld")

    return [
        ("Trend", trend_ok, trend_detail),
        ("Momentum", momentum_ok, momentum_detail),
        ("RSI", rsi_ok, rsi_detail),
        ("Volume", volume_ok, volume_detail),
    ]
```

En laat `confirms_direction` beginnen met:

```python
    direction = direction.lower()
    if direction not in ("long", "short"):
        return False, f"onbekende richting: {direction}"
    factors = basic_factors(direction, ind)
```

(De rest van `confirms_direction` na de `factors = [...]`-lijst, dus alles vanaf de `if include_advanced:`-tak, blijft ongewijzigd staan.)

- [ ] **Step 4: Voeg `check_daily_trend` toe**

Voeg toe in `app/indicators.py`, direct na `check_1h_trend` (na regel 124):

```python
def check_daily_trend(direction: str, daily_ind: Indicators) -> tuple[str, bool, str]:
    """Structurele trend op de daily candle: bevestigt de langere-termijn
    richting waar een swing-opzet (bijvoorbeeld een weekly patroon) op
    steunt, onafhankelijk van wat de snellere 4-uur candle op dit moment
    laat zien. Zelfde soort check als check_1h_trend, andere
    tijdshorizon."""
    up_daily = daily_ind.ema9 > daily_ind.ema21
    wants_up = direction.lower() == "long"
    ok = up_daily if wants_up else not up_daily
    kant = "boven" if up_daily else "onder"
    detail = f"EMA9 {kant} EMA21 op daily" + ("" if ok else ", geen bevestiging op de dagcandle")
    return ("Daily-trend", ok, detail)
```

- [ ] **Step 5: Run de tests opnieuw, verwacht dat alles slaagt (inclusief de regressie-asserts)**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_indicators.py`
Expected: alle "OK:"-regels, eindigend met "ALLE SWING-INDICATOR TESTS GESLAAGD"

- [ ] **Step 6: Draai ook een bestaand scratch-scenario voor `confirms_direction` met `extra_factors`/`include_advanced=True` om de refactor breder te verifiëren**

Voeg toe aan het einde van `<scratchpad>/test_swing_indicators.py`, vóór de laatste print:

```python
# --- Regressie: de uitgebreide (advanced) toets moet ook ongewijzigd blijven ---
extra = [("BTC-trend", True, "BTC omhoog"), ("1u bevestiging", True, "ok"),
         ("Divergentie", True, "geen divergentie"), ("Liquiditeit", True, "genoeg volume")]
confirmed, reason = confirms_direction(bullish, "long", extra_factors=extra, include_advanced=True)
assert confirmed is True, f"volledig bevestigde uitgebreide toets moet True geven, kreeg {confirmed}, {reason}"
print("OK: confirms_direction met include_advanced=True werkt nog steeds na de refactor (regressie)")
```

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_indicators.py`
Expected: ook deze laatste "OK:"-regel slaagt.

- [ ] **Step 7: Commit**

```bash
git add app/indicators.py
git commit -m "$(cat <<'EOF'
indicators.py: basic_factors extractie + check_daily_trend

confirms_direction gebruikt nu de nieuwe basic_factors() intern (zelfde
gedrag, geregressietest), zodat de swing-toets in signal_processor.py
dezelfde vier basisfactoren kan hergebruiken op de daily/4-uur candle
zonder duplicatie. check_daily_trend is een nieuwe advanced factor
(zelfde soort check als check_1h_trend/check_btc_trend), voor day trading
en swing allebei.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `scripts/backtest_factors.py` — daily-trend meenemen in de backtest

**Files:**
- Modify: `scripts/backtest_factors.py`

**Interfaces:**
- Consumes: `indicators.check_daily_trend` (Task 4).

Dit maakt de nieuwe advanced factor uit Task 4 backtestbaar, zoals CLAUDE.md voorschrijft: "scripts/backtest_factors.py --limit 50 shows the historical pass rate of the optional advanced factors before turning them on." Zonder deze stap kan de operator de nieuwe factor niet beoordelen voor hij `ENABLE_ADVANCED_FACTORS=true` zet.

- [ ] **Step 1: Voeg `"1d"` toe aan de timeframe-uren-mapping**

In `scripts/backtest_factors.py`, in `_historical_df` (regel 36), wijzig:

```python
    tf_hours = {"1h": 1, "4h": 4}[timeframe]
```

naar:

```python
    tf_hours = {"1h": 1, "4h": 4, "1d": 24}[timeframe]
```

- [ ] **Step 2: Voeg de daily-trend meting toe aan `evaluate_signal`**

In `scripts/backtest_factors.py`, in `evaluate_signal` (na het bestaande BTC-trend blok, regel 82-90), voeg toe:

```python
    try:
        daily_df = _historical_df(coin, "1d", created_at, candles_needed=60)
        daily_ind = indicators.compute_indicators(daily_df)
        _, daily_ok, _ = indicators.check_daily_trend(direction, daily_ind)
        results["Daily-trend"] = daily_ok
    except Exception as exc:
        results["Daily-trend"] = None
        print(f"    (daily data mislukt: {exc})")
```

(60 candles is genoeg voor EMA21 op daily-niveau; 220, de standaard voor 4h, zou 220 dagen geschiedenis vragen die een net geforwarde coin vaak nog niet heeft.)

- [ ] **Step 3: Handmatig verifiëren dat het script nog draait**

Dit script praat met de live Binance-API en is niet zinvol te unittesten met een fixture; verifieer in plaats daarvan dat het zonder crash draait op een kleine steekproef:

Run: `source /home/user/Trade/.venv/bin/activate && python3 scripts/backtest_factors.py --limit 3`
Expected: output zonder Python-traceback, met een regel "Daily-trend: X/Y (Z%)" (of vergelijkbaar, in dezelfde tabel-vorm als de bestaande factoren) in de samenvatting. Als er nog geen dag-trading signalen in de lokale database staan, print het script dat er niets te backtesten is: dat is ook een geslaagde run (geen crash), niet een testfout.

- [ ] **Step 4: Commit**

```bash
git add scripts/backtest_factors.py
git commit -m "$(cat <<'EOF'
backtest_factors.py: daily-trend meenemen als backtestbare factor

Zonder dit kon de nieuwe check_daily_trend advanced factor niet
beoordeeld worden voor iemand ENABLE_ADVANCED_FACTORS aanzet, precies het
soort blinde-invoering dat dit script juist moet voorkomen.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: `app/signal_processor.py` — de bewaak-poort, de swing-toets, en day-trading met niveaus

**Files:**
- Modify: `app/signal_processor.py`
- Test: `<scratchpad>/test_swing_signal_processor.py`

**Interfaces:**
- Consumes: `repo.create_swing_watch/get_swing_watch/list_source_levels_for_message` (Task 2), `risk.compute_stop_take_from_levels` (Task 3), `indicators.basic_factors/check_daily_trend` (Task 4), `telegram_notify.send_swing_signal` (Task 8 — deze taak roept die functie al aan, Task 8 levert hem; zie opmerking onderaan).
- Produces:
  - Module-constanten `SWING_WATCH_ATR_MULTIPLIER = 0.5`, `SWING_WATCH_MAX_AGE_DAYS = 84`
  - `_price_near_level(current_price: float, level_price: float, atr: float) -> bool` (pure functie)
  - `_price_broke_through(direction: str, current_price: float, level_price: float, atr: float) -> bool` (pure functie)
  - `async def evaluate_level_watch(message_id: int, coin: str, direction: str, source_level_id: int, level_price: float) -> None`
  - `async def run_swing_check(watch_id: int) -> None`
  - Gewijzigd: `handle_message` roept `evaluate_level_watch` aan voor elk opgeslagen niveau, ongeacht categorie.
  - Gewijzigd: `process_day_trading_signal` gebruikt bron-niveaus van dit bericht voor SL/TP als die er zijn.
  - Gewijzigd: `compute_advanced_extra_factors` bevat nu ook de daily-trend check.

**Let op:** deze taak roept `telegram_notify.send_swing_signal` aan, die pas in Task 8 gebouwd wordt. Schrijf en test in deze taak alles TOT AAN het versturen van de Telegram-melding met een tijdelijke stub (zie Step 6), en vervang die stub pas in Task 8 door de echte aanroep. Zo blijft elke taak op zichzelf draaiend en testbaar, in de volgorde van dit plan.

- [ ] **Step 1: Schrijf de tests voor de twee pure functies eerst**

Maak `<scratchpad>/test_swing_signal_processor.py`:

```python
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/home/user/Trade")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-swing-sp-0123456789"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path

from app import db, exchange, repo, signal_processor

db.init_db()

# --- Pure functies: geen I/O, direct te testen ---
assert signal_processor._price_near_level(100.0, 100.4, atr=1.0) is True, "0.4 verschil bij atr=1 (marge 0.5) is dichtbij"
assert signal_processor._price_near_level(100.0, 102.0, atr=1.0) is False, "2.0 verschil bij atr=1 is niet dichtbij"
print("OK: _price_near_level gebruikt de 0.5x ATR-marge correct")

assert signal_processor._price_broke_through("long", current_price=98.0, level_price=100.0, atr=1.0) is True, (
    "long: 2.0 onder het niveau bij atr=1 (marge 0.5) is er krachtig doorheen"
)
assert signal_processor._price_broke_through("long", current_price=99.8, level_price=100.0, atr=1.0) is False, (
    "long: 0.2 onder het niveau is nog geen krachtige doorbraak"
)
assert signal_processor._price_broke_through("short", current_price=102.0, level_price=100.0, atr=1.0) is True, (
    "short: 2.0 boven het niveau is er krachtig doorheen"
)
print("OK: _price_broke_through herkent een krachtige doorbraak in de verkeerde richting")

print("ALLE SIGNAL_PROCESSOR SWING TESTS DEEL 1 GESLAAGD")
```

- [ ] **Step 2: Run, verwacht een `AttributeError`**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_signal_processor.py`
Expected: `AttributeError: module 'app.signal_processor' has no attribute '_price_near_level'`

- [ ] **Step 3: Voeg de constanten en pure functies toe aan `app/signal_processor.py`**

Voeg toe direct na de bestaande `REPEATED_IGNORE_MUTE_THRESHOLD`-constante (na regel 45):

```python
# Hoe dicht de prijs bij een bewaakt bron-niveau moet komen voordat de
# swing-toets draait, in ATR van de DAILY candle (de structurele
# tijdshorizon van zo'n niveau, zie de spec). Zelfde soort marge als
# level_check.PENDING_LEVEL_ATR_MULTIPLIER gebruikt voor day-trading
# pending-signalen.
SWING_WATCH_ATR_MULTIPLIER = 0.5

# Hoe lang een "wachtende" swing watch actief blijft zonder dat de prijs
# ooit dichtbij kwam, voor hij automatisch vervalt (12 weken).
SWING_WATCH_MAX_AGE_DAYS = 84


def _price_near_level(current_price: float, level_price: float, atr: float) -> bool:
    """Zuivere functie: is de prijs dichtbij genoeg om de volledige
    swing-toets te draaien."""
    return abs(current_price - level_price) <= SWING_WATCH_ATR_MULTIPLIER * atr


def _price_broke_through(direction: str, current_price: float, level_price: float, atr: float) -> bool:
    """Prijs is met een duidelijke marge (dezelfde ATR-marge) door het
    niveau heen gegaan in de verkeerde richting: bij long betekent dit
    onder het niveau, bij short erboven. Zo'n setup is ongeldig geworden."""
    margin = SWING_WATCH_ATR_MULTIPLIER * atr
    if direction.lower() == "long":
        return current_price < level_price - margin
    return current_price > level_price + margin
```

- [ ] **Step 4: Run opnieuw, verwacht dat deel 1 slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_signal_processor.py`
Expected: "ALLE SIGNAL_PROCESSOR SWING TESTS DEEL 1 GESLAAGD"

- [ ] **Step 5: Voeg `evaluate_level_watch` toe**

Voeg toe in `app/signal_processor.py`, direct vóór `def _build_context_note` (vóór regel 200):

```python
async def evaluate_level_watch(
    message_id: int, coin: str, direction: str, source_level_id: int, level_price: float,
) -> None:
    """Aangeroepen voor elk opgeslagen bron-niveau van een bericht, ongeacht
    categorie (day_trading of lange_termijn): maakt een swing_watches-regel
    aan en checkt meteen of de prijs nu al dichtbij genoeg is om door te
    gaan naar de volledige toets. Zo niet, blijft de watch "wachtend" en
    pakt level_check.check_swing_watches() hem later periodiek op."""
    if direction.lower() not in ("long", "short"):
        return  # "neutraal" heeft geen kant om een niveau tegen te toetsen
    watch_id = repo.create_swing_watch(message_id, source_level_id, coin, direction)
    try:
        daily_df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, "1d")
    except Exception:
        logger.exception("Kon daily data voor %s niet ophalen, watch %s blijft wachtend", coin, watch_id)
        return
    daily_ind = indicators.compute_indicators(daily_df)
    if _price_near_level(daily_ind.price, level_price, daily_ind.atr):
        await run_swing_check(watch_id)
```

- [ ] **Step 6: Voeg `run_swing_check` toe, met een tijdelijke stub voor de Telegram-melding**

Voeg toe direct na `evaluate_level_watch`:

```python
async def run_swing_check(watch_id: int) -> None:
    """Draait de volledige swing-toets voor een bewaakte watch: daily en
    4-uur factoren apart (geen gecombineerd vertrouwenscijfer), stop loss/
    take profit op basis van het bron-niveau, journaalregel en niet-stille
    Telegram-melding per gebruiker. Zet de watch op "bevestigd": hij wordt
    daarna nooit opnieuw getoetst, ook niet als de prijs er later nogmaals
    overheen gaat."""
    watch = repo.get_swing_watch(watch_id)
    if not watch or watch["status"] != "wachtend":
        return  # al bevestigd/vervallen/ongeldig, of een dubbele aanroep

    coin, direction = watch["coin"], watch["direction"]
    tracked, is_new_coin = await asyncio.to_thread(coinlist.ensure_coin_tracked, coin)
    if is_new_coin:
        await _notify_new_coin(coin)
    if not tracked:
        repo.update_swing_watch_status(watch_id, "ongeldig")
        return

    try:
        daily_df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, "1d")
        df_4h = await asyncio.to_thread(exchange.fetch_ohlcv, coin, "4h")
    except Exception:
        logger.exception("Kon candles voor swing-toets van %s niet ophalen, watch %s blijft wachtend",
                          coin, watch_id)
        return

    daily_ind = indicators.compute_indicators(daily_df)
    ind_4h = indicators.compute_indicators(df_4h)
    swing_low, swing_high = indicators.swing_levels(df_4h)

    daily_factors = indicators.basic_factors(direction, daily_ind)
    factors_4h = indicators.basic_factors(direction, ind_4h)

    stop_take = risk.compute_stop_take_from_levels(
        direction, ind_4h.price, ind_4h.atr, [watch["price_level"]],
        swing_low=swing_low, swing_high=swing_high,
    )

    reason = (
        "Daily: " + " | ".join(f"{'✓' if ok else '✗'} {name}: {detail}" for name, ok, detail in daily_factors)
        + "\n4 uur: " + " | ".join(f"{'✓' if ok else '✗'} {name}: {detail}" for name, ok, detail in factors_4h)
    )
    context_note = f"Bewaakt niveau: {watch['price_level']}"
    if watch["pattern_name"]:
        context_note += f" ({watch['pattern_name']})"

    signal_data = {
        "message_id": watch["message_id"], "coin": coin, "direction": direction,
        "category": "swing", "trade_type": "swing",
        "price": ind_4h.price, "rsi": ind_4h.rsi, "macd": ind_4h.macd,
        "macd_signal": ind_4h.macd_signal, "volume_ratio": ind_4h.volume_ratio,
        "ema9": ind_4h.ema9, "ema21": ind_4h.ema21, "atr": ind_4h.atr,
        "atr_avg20": ind_4h.atr_avg20, "adx": ind_4h.adx,
        "technical_confirmed": 1,
        "confidence": "niveau bevestigd",
        "reason": reason,
        "stop_loss": stop_take.stop_loss, "take_profit": stop_take.take_profit,
        "context_note": context_note,
        "is_practice": 0,
        "plain_explanation": None,
    }
    signal_id = repo.insert_signal(signal_data)

    for user in repo.list_users():
        risk_eur = risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"])
        entry_id = repo.create_journal_entry(signal_id, user["id"], risk_eur)
        if not user["telegram_chat_id"]:
            continue
        # Geen is_coin_muted-check hier: mute geldt bewust alleen voor
        # day-trading meldingen (zie de spec), een swing-melding is
        # zeldzaam en juist bedoeld om een grote kans nooit te missen.
        quiet = telegram_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            await telegram_notify.send_swing_signal(
                coin=coin, direction=direction, price=ind_4h.price,
                stop_loss=stop_take.stop_loss, take_profit=stop_take.take_profit,
                daily_factors=daily_factors, factors_4h=factors_4h,
                level_price=watch["price_level"], pattern_name=watch["pattern_name"],
                chat_id=user["telegram_chat_id"], entry_id=entry_id, force_silent=quiet,
            )
            repo.mark_journal_telegram_sent(entry_id)
        except Exception:
            logger.exception("Swing-melding voor %s naar gebruiker %s is mislukt", coin, user["username"])

    repo.update_swing_watch_status(watch_id, "bevestigd")
```

- [ ] **Step 7: Schrijf een tijdelijke stub voor `telegram_notify.send_swing_signal`, zodat deze taak los te testen is**

Voeg dit TIJDELIJK toe aan `app/telegram_notify.py` (Task 8 vervangt dit door de echte implementatie met de opgemaakte tekst en het toetsenbord):

```python
async def send_swing_signal(
    coin, direction, price, stop_loss, take_profit, daily_factors, factors_4h,
    level_price, pattern_name, chat_id, entry_id, force_silent=False,
):
    """TIJDELIJKE STUB, wordt in Task 8 vervangen door de echte
    implementatie (opgemaakt bericht + Genomen/Negeren-knoppen)."""
    logger.info("STUB send_swing_signal: %s %s naar chat %s", coin, direction, chat_id)
```

- [ ] **Step 8: Schrijf de test voor `run_swing_check` (via `evaluate_level_watch`, met een gemockte exchange)**

Voeg toe aan het einde van `<scratchpad>/test_swing_signal_processor.py`:

```python
import asyncio
import pandas as pd


def fake_ohlcv(price=100.0, atr_high=101.0, atr_low=99.0, candles=60):
    """Vlakke candle-reeks rond `price`, genoeg voor EMA21/ATR/ADX om te
    berekenen zonder een echte exchange-call."""
    rows = []
    for i in range(candles):
        rows.append({
            "timestamp": pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=candles - i),
            "open": price, "high": atr_high, "low": atr_low, "close": price, "volume": 1000.0,
        })
    return pd.DataFrame(rows)


uid = repo.create_user("swingsp", "hash", 1000.0, 1.0, "222")
now_iso = datetime.now(timezone.utc).isoformat()

with db.session() as conn:
    conn.execute(
        "INSERT INTO messages (received_at, raw_text, category, coin, direction) "
        "VALUES (?, 'RAY weekly double bottom', 'lange_termijn', 'RAY', 'long')",
        (now_iso,),
    )
    msg_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.execute(
        "INSERT INTO source_levels (message_id, coin, price_level, pattern_name, created_at) "
        "VALUES (?, 'RAY', 100.4, 'resistance', ?)",  # dichtbij de prijs van fake_ohlcv (100.0)
        (msg_id, now_iso),
    )
    level_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

exchange.market_exists = lambda coin: True
exchange.to_symbol = lambda coin: f"{coin.upper()}/USDT"
exchange.fetch_ohlcv = lambda coin, timeframe="4h", limit=200, since=None: fake_ohlcv()

# --- Prijs is meteen dichtbij: evaluate_level_watch moet direct doorschakelen naar bevestigd ---
asyncio.run(signal_processor.evaluate_level_watch(msg_id, "RAY", "long", level_id, 100.4))

watches = repo.list_watches_by_status("bevestigd")
assert len(watches) == 1, f"verwacht 1 bevestigde watch, kreeg {len(watches)}: {watches}"
print("OK: evaluate_level_watch bevestigt direct als de prijs al dichtbij is")

entries = repo.list_journal(uid, status=None, limit=10)
assert any(e["coin"] == "RAY" and e["trade_type"] == "swing" for e in entries), (
    f"verwacht een journaalregel met trade_type='swing' voor RAY, kreeg {entries}"
)
print("OK: run_swing_check maakt een journaalregel aan met trade_type='swing'")

# --- Prijs is VER weg: watch moet 'wachtend' blijven, geen journaalregel ---
with db.session() as conn:
    conn.execute(
        "INSERT INTO messages (received_at, raw_text, category, coin, direction) "
        "VALUES (?, 'SOL support', 'lange_termijn', 'SOL', 'long')",
        (now_iso,),
    )
    msg2_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.execute(
        "INSERT INTO source_levels (message_id, coin, price_level, pattern_name, created_at) "
        "VALUES (?, 'SOL', 500.0, 'support', ?)",  # ver van de prijs van fake_ohlcv (100.0)
        (msg2_id, now_iso),
    )
    sol_level_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

asyncio.run(signal_processor.evaluate_level_watch(msg2_id, "SOL", "long", sol_level_id, 500.0))
sol_watches = [w for w in repo.list_watches_by_status("wachtend") if w["coin"] == "SOL"]
assert len(sol_watches) == 1, f"verwacht dat de SOL-watch wachtend blijft, kreeg {sol_watches}"
print("OK: evaluate_level_watch laat de watch 'wachtend' als de prijs ver weg is")

print("ALLE SIGNAL_PROCESSOR SWING TESTS DEEL 2 GESLAAGD")
```

- [ ] **Step 9: Run, verwacht een fout (`evaluate_level_watch`/`run_swing_check` nog niet toegevoegd, of `list_journal` mist `trade_type`)**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_signal_processor.py`
Expected: eerst een `AttributeError`. Los die op door Step 5/6/7 hierboven daadwerkelijk toe te passen als dat nog niet gebeurd is.

- [ ] **Step 10: Run opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_signal_processor.py`
Expected: alle "OK:"-regels, eindigend met "ALLE SIGNAL_PROCESSOR SWING TESTS DEEL 2 GESLAAGD"

- [ ] **Step 11: Wire `evaluate_level_watch` in de bestaande bron-niveaus-opslag in `handle_message` (de universele poort)**

In `app/signal_processor.py`, in `handle_message`, in het bestaande blok dat bron-niveaus opslaat (regel 138-160), vervang de laatste regel:

```python
                repo.insert_source_level(message_id, interp.coin, level.price_level, level.pattern_name)
```

door:

```python
                source_level_id = repo.insert_source_level(
                    message_id, interp.coin, level.price_level, level.pattern_name,
                )
                await evaluate_level_watch(
                    message_id, interp.coin, interp.direction, source_level_id, level.price_level,
                )
```

Dit draait voor ELK bericht met een niveau, vóór de `if interp.category != "day_trading":`-vertakking, dus ongeacht categorie — precies de universele poort uit de spec.

- [ ] **Step 12: Gebruik bron-niveaus van dit bericht voor day-trading SL/TP als ze er zijn**

In `app/signal_processor.py`, in `process_day_trading_signal`, vervang:

```python
    stop_take = risk.compute_stop_take(
        interp.direction, ind.price, ind.atr, swing_low=swing_low, swing_high=swing_high,
    )
```

door:

```python
    message_levels = [lvl["price_level"] for lvl in repo.list_source_levels_for_message(message_id)]
    if message_levels:
        stop_take = risk.compute_stop_take_from_levels(
            interp.direction, ind.price, ind.atr, message_levels, swing_low=swing_low, swing_high=swing_high,
        )
    else:
        stop_take = risk.compute_stop_take(
            interp.direction, ind.price, ind.atr, swing_low=swing_low, swing_high=swing_high,
        )
```

- [ ] **Step 13: Voeg de daily-trend advanced factor toe aan `compute_advanced_extra_factors`**

In `app/signal_processor.py`, in `compute_advanced_extra_factors`, voeg toe na het bestaande BTC-trend blok (na regel 234):

```python
    try:
        daily_df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, "1d")
        daily_ind = indicators.compute_indicators(daily_df)
        factors.append(indicators.check_daily_trend(direction, daily_ind))
    except Exception:
        logger.exception("Daily-trend voor %s kon niet berekend worden", coin)
        factors.append(("Daily-trend", False, "kon niet opgehaald worden, telt als niet bevestigd"))
```

- [ ] **Step 14: Schrijf een integratietest voor Step 11 en 12 (de universele poort + day-trading met niveau)**

Voeg toe aan het einde van `<scratchpad>/test_swing_signal_processor.py`:

```python
# --- Integratietest: handle_message met een day_trading bericht MET
# bijgevoegd niveau maakt zowel een swing_watches-regel als een signaal
# met niveau-gebaseerde SL/TP aan. ---
from app import anthropic_interpret, coinlist

coinlist.ensure_coin_tracked = lambda coin: (True, False)
# signal_processor.py deed `from app.anthropic_interpret import interpret_message`
# (een directe naam-import): het monkeypatchen van
# anthropic_interpret.interpret_message zelf raakt die losse, al gebonden
# naam in signal_processor niet. Patch daarom signal_processor.interpret_message
# rechtstreeks, dat is de naam die _interpret_with_retry() ook echt aanroept.
signal_processor.interpret_message = lambda raw_text, image_paths=None: anthropic_interpret.Interpretation(
    coin="RAY", direction="long", category="day_trading", unclear=False,
    source_levels=[anthropic_interpret.SourceLevel(price_level=100.4, pattern_name="resistance")],
)

# handle_message roept dit aan via asyncio.to_thread(explain.summarize_message, ...),
# dat verwacht een gewone SYNCHRONE functie (to_thread voert 'm uit in een
# thread-pool en verwacht het echte resultaat terug, geen coroutine-object).
signal_processor.explain.summarize_message = lambda coin, raw_text: None

with db.session() as conn:
    conn.execute(
        "INSERT INTO messages (received_at, raw_text) VALUES (?, 'RAY door de weerstand, long hier')",
        (now_iso,),
    )
    day_msg_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

asyncio.run(signal_processor.handle_message(day_msg_id, "RAY door de weerstand, long hier", []))

day_trading_watches = [w for w in repo.list_watches_by_status("bevestigd") if w["message_id"] == day_msg_id]
assert len(day_trading_watches) == 1, (
    f"een day_trading bericht met een niveau moet OOK een swing_watches-regel krijgen, kreeg {day_trading_watches}"
)
print("OK: een day_trading bericht met een niveau krijgt ook een bewaakte watch (universele poort)")

with db.session() as conn:
    sig_row = conn.execute(
        "SELECT stop_loss, take_profit FROM signals WHERE message_id = ? AND trade_type = 'day_trading'",
        (day_msg_id,),
    ).fetchone()
assert sig_row is not None, "day_trading signaal met dit message_id ontbreekt"
# Het niveau (100.4) ligt boven de fake_ohlcv-prijs (100.0): moet als take_profit gebruikt zijn.
assert abs(sig_row["take_profit"] - 100.4) < 1e-6, (
    f"day trading signaal met een niveau erboven moet dat niveau als take_profit gebruiken, kreeg {dict(sig_row)}"
)
print("OK: process_day_trading_signal gebruikt het bron-niveau van dit bericht voor take_profit")

print("ALLE SIGNAL_PROCESSOR SWING TESTS GESLAAGD")
```

- [ ] **Step 15: Run het volledige testscript, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_signal_processor.py`
Expected: alle "OK:"-regels, eindigend met "ALLE SIGNAL_PROCESSOR SWING TESTS GESLAAGD"

- [ ] **Step 16: Commit**

```bash
git add app/signal_processor.py app/telegram_notify.py
git commit -m "$(cat <<'EOF'
signal_processor.py: de bewaak-poort, de swing-toets, niveaus bij day trading

evaluate_level_watch draait voortaan voor ELK bericht met een opgeslagen
bron-niveau, ongeacht categorie: dit was het daadwerkelijke gat achter de
gemiste RAY-kans (een niveau dat wel werd opgeslagen maar nooit meer
bekeken werd). run_swing_check doet de volledige toets zodra de prijs
dichtbij komt: daily + 4-uur factoren los, niveau-gebaseerde SL/TP, een
journaalregel per gebruiker (trade_type='swing'), niet-stille melding.
process_day_trading_signal gebruikt nu ook bron-niveaus van zijn eigen
bericht voor SL/TP als die er zijn, in plaats van altijd ATR.

telegram_notify.send_swing_signal is hier nog een tijdelijke stub, Task 8
van het implementatieplan vervangt hem door de echte melding.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `app/level_check.py` — periodieke check van wachtende watches

**Files:**
- Modify: `app/level_check.py`
- Test: `<scratchpad>/test_swing_level_check.py`

**Interfaces:**
- Consumes: `repo.list_watches_by_status/update_swing_watch_status` (Task 2), `signal_processor._price_near_level/_price_broke_through/run_swing_check/SWING_WATCH_MAX_AGE_DAYS` (Task 6).
- Produces: `async def check_swing_watches() -> None`, aangeroepen vanuit `run_all_checks()`.

- [ ] **Step 1: Voeg de benodigde imports toe aan `app/level_check.py`**

Bovenaan `app/level_check.py`, vervang:

```python
from app import config, exchange, repo
from app.telegram_notify import DIVIDER, _coin_label, _factor_link
```

door:

```python
from datetime import datetime, timezone

from app import config, exchange, indicators, repo
from app.signal_processor import (
    SWING_WATCH_MAX_AGE_DAYS, _price_broke_through, _price_near_level, run_swing_check,
)
from app.telegram_notify import DIVIDER, _coin_label, _factor_link
```

- [ ] **Step 2: Voeg `check_swing_watches` toe**

`app/level_check.py` importeert `asyncio` al bovenaan (regel 18), die aanroep is dus meteen bruikbaar. Voeg dit toe in `app/level_check.py`, na `check_pending_signals` (na regel 191), vóór `run_all_checks`:

```python
async def check_swing_watches() -> None:
    """Elke "wachtende" bewaakte niveau-watch: is de prijs nu dichtbij
    genoeg om de volledige swing-toets te draaien (run_swing_check), is de
    prijs juist met een duidelijke marge in de verkeerde richting door het
    niveau heen gegaan (ongeldig), of is de watch te lang zonder resultaat
    blijven wachten (vervallen)."""
    watches = repo.list_watches_by_status("wachtend")
    logger.info("%d wachtende swing-watches om te checken", len(watches))

    for watch in watches:
        coin = watch["coin"]
        try:
            daily_df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, "1d")
            daily_ind = indicators.compute_indicators(daily_df)
        except Exception:
            logger.exception("Kon daily data voor %s niet ophalen, watch %s blijft wachtend", coin, watch["id"])
            continue

        if _price_near_level(daily_ind.price, watch["price_level"], daily_ind.atr):
            await run_swing_check(watch["id"])
            continue

        if _price_broke_through(watch["direction"], daily_ind.price, watch["price_level"], daily_ind.atr):
            repo.update_swing_watch_status(watch["id"], "ongeldig")
            logger.info("Swing-watch %s (%s) ongeldig: prijs krachtig door het niveau heen", watch["id"], coin)
            continue

        created_at = datetime.fromisoformat(watch["created_at"])
        age_days = (datetime.now(timezone.utc) - created_at).days
        if age_days > SWING_WATCH_MAX_AGE_DAYS:
            repo.update_swing_watch_status(watch["id"], "vervallen")
            logger.info("Swing-watch %s (%s) vervallen na %s dagen zonder resultaat", watch["id"], coin, age_days)
```

- [ ] **Step 3: Wire `check_swing_watches` in `run_all_checks`**

In `app/level_check.py`, wijzig:

```python
async def run_all_checks() -> None:
    await check_open_trades()
    await check_pending_signals()
```

naar:

```python
async def run_all_checks() -> None:
    await check_open_trades()
    await check_pending_signals()
    await check_swing_watches()
```

- [ ] **Step 4: Schrijf de test**

Maak `<scratchpad>/test_swing_level_check.py`:

```python
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/home/user/Trade")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-swing-lc-0123456789"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path

from app import db, exchange, level_check, repo, signal_processor

db.init_db()

import asyncio
import pandas as pd


def fake_ohlcv_at(price):
    rows = []
    for i in range(60):
        rows.append({
            "timestamp": pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=60 - i),
            "open": price, "high": price + 1, "low": price - 1, "close": price, "volume": 1000.0,
        })
    return pd.DataFrame(rows)


now_iso = datetime.now(timezone.utc).isoformat()
old_iso = (datetime.now(timezone.utc) - timedelta(days=signal_processor.SWING_WATCH_MAX_AGE_DAYS + 1)).isoformat()


def make_watch(coin, direction, level_price, created_at):
    with db.session() as conn:
        conn.execute(
            "INSERT INTO messages (received_at, raw_text, category, coin, direction) "
            "VALUES (?, 'test', 'lange_termijn', ?, ?)",
            (now_iso, coin, direction),
        )
        msg_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
        conn.execute(
            "INSERT INTO source_levels (message_id, coin, price_level, pattern_name, created_at) "
            "VALUES (?, ?, ?, 'resistance', ?)",
            (msg_id, coin, level_price, now_iso),
        )
        level_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    watch_id = repo.create_swing_watch(msg_id, level_id, coin, direction)
    if created_at != now_iso:
        with db.session() as conn:
            conn.execute("UPDATE swing_watches SET created_at = ? WHERE id = ?", (created_at, watch_id))
    return watch_id

exchange.market_exists = lambda coin: True
exchange.to_symbol = lambda coin: f"{coin.upper()}/USDT"

# --- Watch A: prijs nu dichtbij, moet bevestigd worden ---
watch_a = make_watch("AAA", "long", 100.4, now_iso)
# --- Watch B: prijs krachtig door het niveau heen (long, ver onder het niveau), moet ongeldig worden ---
watch_b = make_watch("BBB", "long", 100.0, now_iso)
# --- Watch C: prijs ver weg maar nog niet te oud, moet wachtend blijven ---
watch_c = make_watch("CCC", "long", 500.0, now_iso)
# --- Watch D: prijs ver weg EN te oud, moet vervallen ---
watch_d = make_watch("DDD", "long", 500.0, old_iso)

prices = {"AAA": 100.4, "BBB": 90.0, "CCC": 100.0, "DDD": 100.0}
exchange.fetch_ohlcv = lambda coin, timeframe="4h", limit=200, since=None: fake_ohlcv_at(prices[coin])

asyncio.run(level_check.check_swing_watches())

assert repo.get_swing_watch(watch_a)["status"] == "bevestigd", "AAA moet bevestigd zijn (prijs dichtbij)"
print("OK: check_swing_watches bevestigt een watch waarvan de prijs dichtbij is")

assert repo.get_swing_watch(watch_b)["status"] == "ongeldig", "BBB moet ongeldig zijn (krachtig doorbroken)"
print("OK: check_swing_watches maakt een watch ongeldig bij een krachtige doorbraak")

assert repo.get_swing_watch(watch_c)["status"] == "wachtend", "CCC moet wachtend blijven (nog niet te oud)"
print("OK: check_swing_watches laat een niet-te-oude, nog-ver-weg watch wachtend")

assert repo.get_swing_watch(watch_d)["status"] == "vervallen", "DDD moet vervallen zijn (te oud)"
print("OK: check_swing_watches laat een te oude watch vervallen")

print("ALLE LEVEL_CHECK SWING TESTS GESLAAGD")
```

- [ ] **Step 5: Run, verwacht een fout als Step 1-3 nog niet zijn toegepast**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_level_check.py`
Expected: `AttributeError: module 'app.level_check' has no attribute 'check_swing_watches'` (los op door Step 1-3 hierboven toe te passen).

- [ ] **Step 6: Run opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_level_check.py`
Expected: alle "OK:"-regels, eindigend met "ALLE LEVEL_CHECK SWING TESTS GESLAAGD"

- [ ] **Step 7: Commit**

```bash
git add app/level_check.py
git commit -m "$(cat <<'EOF'
level_check.py: periodieke check van wachtende swing-watches

Dezelfde 15-minuten timer als de bestaande day-trading pending-check pakt
nu ook bewaakte bron-niveaus op: bevestigt zodra de prijs dichtbij komt,
maakt een watch ongeldig bij een krachtige doorbraak in de verkeerde
richting, en laat een watch na 12 weken zonder resultaat vervallen.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: `app/telegram_notify.py` — de echte swing-melding

**Files:**
- Modify: `app/telegram_notify.py`
- Test: `<scratchpad>/test_swing_telegram.py`

**Interfaces:**
- Produces:
  - `format_swing_message(coin: str, direction: str, price: float, stop_loss: float, take_profit: float, daily_factors: list[tuple[str, bool, str]], factors_4h: list[tuple[str, bool, str]], level_price: float, pattern_name: Optional[str]) -> str`
  - `async def send_swing_signal(coin: str, direction: str, price: float, stop_loss: float, take_profit: float, daily_factors: list[tuple[str, bool, str]], factors_4h: list[tuple[str, bool, str]], level_price: float, pattern_name: Optional[str], chat_id: str, entry_id: int, force_silent: bool = False) -> None` — vervangt de tijdelijke stub uit Task 6.

- [ ] **Step 1: Schrijf de test voor `format_swing_message`**

Maak `<scratchpad>/test_swing_telegram.py`:

```python
import os
import sys

sys.path.insert(0, "/home/user/Trade")
os.environ["JWT_SECRET"] = "test-secret-swing-tg-0123456789"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import telegram_notify

daily_factors = [("Trend", True, "EMA9 boven EMA21"), ("Momentum", False, "MACD onder signaallijn")]
factors_4h = [("Trend", True, "EMA9 boven EMA21"), ("RSI", True, "RSI 55")]

text = telegram_notify.format_swing_message(
    coin="RAY", direction="long", price=0.836, stop_loss=0.80, take_profit=0.90,
    daily_factors=daily_factors, factors_4h=factors_4h,
    level_price=0.836, pattern_name="resistance",
)

assert "RAY" in text
assert "Daily:" in text and "4 uur:" in text
assert "✓ Trend" in text and "✗ Momentum" in text
assert "vertrouwenspercentage" in text.lower(), "moet expliciet benoemen dat er geen vertrouwenscijfer is"
assert "0.836" in text or "0.8360" in text, "het bron-niveau zelf moet in het bericht staan"
print("OK: format_swing_message toont beide factor-sets los, zonder gecombineerd vertrouwenscijfer")

# Geen pattern_name meegegeven: mag niet crashen, en geen lege haakjes tonen.
text_no_pattern = telegram_notify.format_swing_message(
    coin="RAY", direction="short", price=0.836, stop_loss=0.90, take_profit=0.70,
    daily_factors=daily_factors, factors_4h=factors_4h,
    level_price=0.836, pattern_name=None,
)
assert "()" not in text_no_pattern, "geen lege haakjes als er geen patroonnaam is"
print("OK: format_swing_message werkt ook zonder patroonnaam")

print("ALLE TELEGRAM SWING TESTS GESLAAGD")
```

- [ ] **Step 2: Run, verwacht een `AttributeError`**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_telegram.py`
Expected: `AttributeError: module 'app.telegram_notify' has no attribute 'format_swing_message'`

- [ ] **Step 3: Verwijder de tijdelijke stub uit Task 6 en implementeer de echte functies**

In `app/telegram_notify.py`, verwijder de tijdelijke `send_swing_signal`-stub die Task 6 toevoegde, en vervang hem door dit (geplaatst na de bestaande `send_signal`-functie, vóór `send_signal_chart`):

```python
def format_swing_message(
    coin: str, direction: str, price: float, stop_loss: float, take_profit: float,
    daily_factors: list[tuple[str, bool, str]], factors_4h: list[tuple[str, bool, str]],
    level_price: float, pattern_name: Optional[str],
) -> str:
    """Melding voor een bevestigde swing-kans: de prijs is weer dichtbij
    een bewaakt bron-niveau gekomen. Factoren op twee tijdshorizons los
    getoond, geen gecombineerd vertrouwenscijfer: dat is nog niet
    gevalideerd voor deze tijdshorizon (zie de spec)."""
    niveau_label = f"{level_price:.4f}" + (f" ({pattern_name})" if pattern_name else "")
    lines = [
        f"{_direction_emoji(direction)} {_coin_label(coin)} · {_direction_label(direction)}",
        DIVIDER,
        "📐 BEWAAKT NIVEAU BEREIKT",
        "",
        f"💰 Prijs nu: {price:.4f}",
        f"📍 Niveau: {niveau_label}",
        f"🎯 Take profit: {take_profit:.4f}",
        f"🛑 Stop loss: {stop_loss:.4f}",
        _progress_bar(price, stop_loss, take_profit, direction),
        DIVIDER,
        "Daily:",
    ]
    for name, ok, detail in daily_factors:
        lines.append(f"{'✓' if ok else '✗'} {name}: {detail}")
    lines += ["", "4 uur:"]
    for name, ok, detail in factors_4h:
        lines.append(f"{'✓' if ok else '✗'} {name}: {detail}")
    lines += [
        "",
        "Geen vertrouwenspercentage: deze toets is nog niet gevalideerd op deze "
        "tijdshorizon, beoordeel de factoren hierboven zelf.",
        DIVIDER, f"⚠️ {config.DISCLAIMER}",
    ]
    return "\n".join(lines)


async def send_swing_signal(
    coin: str, direction: str, price: float, stop_loss: float, take_profit: float,
    daily_factors: list[tuple[str, bool, str]], factors_4h: list[tuple[str, bool, str]],
    level_price: float, pattern_name: Optional[str],
    chat_id: str, entry_id: int, force_silent: bool = False,
) -> None:
    """Niet-stille melding (tenzij de gebruiker in zijn eigen stille uren
    zit): een bevestigde swing-kans is zeldzaam en juist bedoeld om niet
    gemist te worden. Hergebruikt dezelfde Genomen/Negeren-knoppen als een
    day-trading melding, de callback-afhandeling maakt geen onderscheid."""
    if not config.TELEGRAM_BOT_TOKEN or not chat_id:
        logger.warning("Telegram token of chat ID ontbreekt, swing-melding niet verstuurd")
        return
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    text = format_swing_message(
        coin, direction, price, stop_loss, take_profit, daily_factors, factors_4h, level_price, pattern_name,
    )
    keyboard = _journal_action_keyboard(entry_id)
    await bot.send_message(chat_id=chat_id, text=text, disable_notification=force_silent, reply_markup=keyboard)
    logger.info("Swing-melding verstuurd voor %s %s naar chat %s", coin, direction, chat_id)
```

- [ ] **Step 4: Run de telegram-test opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_telegram.py`
Expected: alle "OK:"-regels, eindigend met "ALLE TELEGRAM SWING TESTS GESLAAGD"

- [ ] **Step 5: Draai het volledige `test_swing_signal_processor.py` uit Task 6 opnieuw, nu met de echte `send_swing_signal` in plaats van de stub**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_signal_processor.py`
Expected: nog steeds alle "OK:"-regels, eindigend met "ALLE SIGNAL_PROCESSOR SWING TESTS GESLAAGD" (de stub-vervanging mag Task 6's gedrag niet breken; `send_swing_signal` faalt in deze test stil door de ontbrekende echte Telegram-verbinding, wat `run_swing_check`'s `except Exception: logger.exception(...)` al opving — dat bleef ongewijzigd).

- [ ] **Step 6: Commit**

```bash
git add app/telegram_notify.py
git commit -m "$(cat <<'EOF'
telegram_notify.py: echte swing-melding met factoren op twee tijdshorizons

Vervangt de tijdelijke stub uit signal_processor.py. Toont daily- en
4-uur-factoren los, expliciet zonder gecombineerd vertrouwenscijfer, en
hergebruikt de bestaande Genomen/Negeren-knoppen zodat de callback-
afhandeling geen wijziging nodig heeft.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: Dashboard — "Bewaakt niveau" op de coin-pagina

**Files:**
- Modify: `web/main.py`
- Modify: `web/templates/coin.html`
- Test: `<scratchpad>/test_swing_coin_page.py`

**Interfaces:**
- Consumes: `repo.active_swing_watches_for_coin` (Task 2).

- [ ] **Step 1: Voeg `active_swing_watches` toe aan de context van `coin_page`**

In `web/main.py`, in `coin_page` (rond regel 812-830), voeg toe vlak vóór de `return templates.TemplateResponse(...)`:

```python
    active_swing_watches = repo.active_swing_watches_for_coin(symbol)
```

En voeg toe aan de teruggegeven context-dict, na `"is_muted": repo.is_coin_muted(user["id"], symbol),`:

```python
        "active_swing_watches": active_swing_watches,
```

- [ ] **Step 2: Voeg de "Bewaakt niveau"-sectie toe aan `web/templates/coin.html`**

In `web/templates/coin.html`, voeg dit blok toe direct na de `</div>` die de hero-sectie sluit (regel 117), vóór het bestaande `{% if long_term_messages %}`-blok (regel 119):

```html
{% if active_swing_watches %}
<details class="stats-collapse js-accordion" style="--i: 2">
  <summary class="stats-summary">
    <svg class="h2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="3"/></svg>
    <span>Bewaakt niveau</span>
    <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6,9 12,15 18,9"/></svg>
  </summary>
  <p class="muted" style="margin: 0 0 10px; font-size: 12px;">Wacht tot de prijs weer dichtbij dit niveau komt, dan volgt een volledige toets op daily en 4-uur candles.</p>
  <div class="long-term-list">
    {% for watch in active_swing_watches %}
    <div class="long-term-item">
      <span class="badge badge-{{ watch.direction if watch.direction in ('long', 'short') else 'status' }}">{{ watch.direction }}</span>
      <span class="muted mono" style="font-size: 11px;">sinds {{ watch.created_at[:10] }}</span>
      <p>Niveau: {{ watch.price_level }}{% if watch.pattern_name %} ({{ watch.pattern_name }}){% endif %}</p>
    </div>
    {% endfor %}
  </div>
</details>
{% endif %}
```

- [ ] **Step 3: Schrijf de test**

Maak `<scratchpad>/test_swing_coin_page.py`:

```python
import os
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, "/home/user/Trade")
sys.path.insert(0, "/home/user/Trade/web")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-swing-coinpage-0123456789"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path

from app import db, exchange, repo, security

db.init_db()
uid = repo.create_user("swingcoinpage", security.hash_password("testpass123"), 1000.0, 1.0, "333")

exchange.market_exists = lambda coin: True
exchange.to_symbol = lambda coin: f"{coin.upper()}/USDT"
exchange.fetch_last_price = lambda coin: 100.0
repo.add_coin_if_new("RAY", "RAY/USDT")

now_iso = datetime.now(timezone.utc).isoformat()
with db.session() as conn:
    conn.execute(
        "INSERT INTO messages (received_at, raw_text, category, coin, direction) "
        "VALUES (?, 'test', 'lange_termijn', 'RAY', 'long')",
        (now_iso,),
    )
    msg_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.execute(
        "INSERT INTO source_levels (message_id, coin, price_level, pattern_name, created_at) "
        "VALUES (?, 'RAY', 0.836, 'resistance', ?)",
        (msg_id, now_iso),
    )
    level_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
repo.create_swing_watch(msg_id, level_id, "RAY", "long")

import main as web_main
from fastapi.testclient import TestClient

client = TestClient(web_main.app)
token = security.create_session_token(uid)
client.cookies.set("session", token)

resp = client.get("/coins/RAY")
assert resp.status_code == 200, resp.status_code
assert "Bewaakt niveau" in resp.text
assert "0.836" in resp.text
assert "resistance" in resp.text
print("OK: coin-pagina toont een actief bewaakt niveau")

# --- Een coin zonder watch toont de sectie niet ---
repo.add_coin_if_new("ETH", "ETH/USDT")
resp2 = client.get("/coins/ETH")
assert "Bewaakt niveau" not in resp2.text
print("OK: coin-pagina zonder actieve watch toont de sectie niet")

print("ALLE COIN-PAGINA SWING TESTS GESLAAGD")
```

- [ ] **Step 4: Run, verwacht een fout of een gemiste assert als Step 1-2 nog niet zijn toegepast**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_coin_page.py`
Expected: `AssertionError: 'Bewaakt niveau' not in resp.text` (los op door Step 1-2 hierboven toe te passen)

- [ ] **Step 5: Run opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_coin_page.py`
Expected: alle "OK:"-regels, eindigend met "ALLE COIN-PAGINA SWING TESTS GESLAAGD"

- [ ] **Step 6: Commit**

```bash
git add web/main.py web/templates/coin.html
git commit -m "$(cat <<'EOF'
Coin-pagina: nieuwe sectie "Bewaakt niveau"

Een wachtende swing-watch was tot nu toe een onzichtbare achterkant-
status, precies zoals het lange-termijn-mechanisme dat voor de RAY-kans
was. Nu zie je op de coin-pagina dat er een niveau actief bewaakt wordt,
met richting en sinds wanneer.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Backfill-script voor bestaande, nog verse niveaus

**Files:**
- Create: `scripts/backfill_swing_watches.py`
- Test: `<scratchpad>/test_swing_backfill.py`

**Interfaces:**
- Consumes: `repo.list_recent_source_levels_without_watch`, `repo.create_swing_watch` (Task 2).

- [ ] **Step 1: Schrijf de test**

Maak `<scratchpad>/test_swing_backfill.py`:

```python
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/home/user/Trade")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-swing-backfill-0123456789"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path

from app import db, repo

db.init_db()
now_iso = datetime.now(timezone.utc).isoformat()
old_iso = (datetime.now(timezone.utc) - timedelta(days=200)).isoformat()

with db.session() as conn:
    # Vers niveau, geen watch: moet gebackfilld worden.
    conn.execute(
        "INSERT INTO messages (received_at, raw_text, category, coin, direction) "
        "VALUES (?, 'test vers', 'lange_termijn', 'RAY', 'long')",
        (now_iso,),
    )
    fresh_msg_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.execute(
        "INSERT INTO source_levels (message_id, coin, price_level, pattern_name, created_at) "
        "VALUES (?, 'RAY', 0.836, 'resistance', ?)",
        (fresh_msg_id, now_iso),
    )

    # Oud niveau (ouder dan de standaard lookback): moet NIET gebackfilld worden.
    conn.execute(
        "INSERT INTO messages (received_at, raw_text, category, coin, direction) "
        "VALUES (?, 'test oud', 'lange_termijn', 'OLDCOIN', 'long')",
        (old_iso,),
    )
    old_msg_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
    conn.execute(
        "INSERT INTO source_levels (message_id, coin, price_level, pattern_name, created_at) "
        "VALUES (?, 'OLDCOIN', 1.0, 'support', ?)",
        (old_msg_id, old_iso),
    )

result = subprocess.run(
    [sys.executable, "/home/user/Trade/scripts/backfill_swing_watches.py"],
    env={**os.environ}, capture_output=True, text=True,
)
assert result.returncode == 0, f"script crashte:\n{result.stdout}\n{result.stderr}"
print(result.stdout)

waiting = repo.list_watches_by_status("wachtend")
assert any(w["coin"] == "RAY" for w in waiting), f"vers RAY-niveau had gebackfilld moeten worden, kreeg {waiting}"
assert not any(w["coin"] == "OLDCOIN" for w in waiting), (
    f"oud OLDCOIN-niveau (200 dagen) had NIET gebackfilld moeten worden, kreeg {waiting}"
)
print("OK: backfill-script pakt alleen verse niveaus zonder watch op, status blijft 'wachtend'")

print("ALLE BACKFILL TESTS GESLAAGD")
```

- [ ] **Step 2: Run, verwacht een `FileNotFoundError`/non-zero returncode (het script bestaat nog niet)**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_backfill.py`
Expected: `AssertionError: script crashte` (het bestand ontbreekt nog)

- [ ] **Step 3: Maak `scripts/backfill_swing_watches.py`**

```python
"""Eenmalig: zet bestaande, nog verse bron-niveaus (support/resistance uit
een screenshot) die nog geen swing_watches-regel hebben, alsnog om in een
wachtende watch. Voor niveaus van vóór deze feature bestond, zodat een nog
relevante analyse niet voorgoed onbewaakt blijft.

Maakt nooit direct een "bevestigde" watch aan, ook niet als de prijs
toevallig al dichtbij staat op het moment van draaien: de eerstvolgende
periodieke check (level_check.check_swing_watches) pakt dat vanzelf op.

Draai met: python3 scripts/backfill_swing_watches.py [--days 84]
"""
import argparse
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import db, repo

DEFAULT_LOOKBACK_DAYS = 84  # zelfde als signal_processor.SWING_WATCH_MAX_AGE_DAYS


def main(days: int) -> None:
    db.init_db()
    since_iso = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    levels = repo.list_recent_source_levels_without_watch(since_iso)

    print(f"{len(levels)} bron-niveaus van de laatste {days} dagen zonder watch gevonden.")
    created = 0
    for lvl in levels:
        repo.create_swing_watch(lvl["message_id"], lvl["source_level_id"], lvl["coin"], lvl["direction"])
        created += 1
        print(f"  watch aangemaakt: {lvl['coin']} {lvl['direction']} @ {lvl['price_level']} "
              f"({lvl['pattern_name'] or 'geen patroonnaam'})")

    print(f"\nKlaar: {created} nieuwe watches aangemaakt, allemaal status 'wachtend'.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=DEFAULT_LOOKBACK_DAYS,
                         help="Hoeveel dagen terug te kijken (standaard: 84, zelfde als het verval van een watch)")
    args = parser.parse_args()
    main(args.days)
```

- [ ] **Step 4: Run de test opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_swing_backfill.py`
Expected: alle "OK:"-regels, eindigend met "ALLE BACKFILL TESTS GESLAAGD"

- [ ] **Step 5: Commit**

```bash
git add scripts/backfill_swing_watches.py
git commit -m "$(cat <<'EOF'
Backfill-script: bestaande verse niveaus alsnog bewaken

Eenmalig te draaien na deze deploy, zodat een analyse van vlak voor deze
feature niet voorgoed onbewaakt blijft. Maakt alleen 'wachtende' watches
aan, nooit direct 'bevestigd': de periodieke check pakt dat vanzelf op.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Task 11: Volledige regressie, opschonen, push

**Files:** geen nieuwe bestanden, alleen verificatie.

- [ ] **Step 1: Draai alle nieuwe testscripts uit dit plan nogmaals achter elkaar**

Run:
```bash
source /home/user/Trade/.venv/bin/activate
for f in test_swing_schema_migration test_swing_repo test_swing_risk test_swing_indicators \
         test_swing_signal_processor test_swing_level_check test_swing_telegram \
         test_swing_coin_page test_swing_backfill; do
  echo "=== $f ==="
  python3 "<scratchpad>/${f}.py" || echo "MISLUKT: $f"
done
```
Expected: geen "MISLUKT" regels.

- [ ] **Step 2: Draai de bestaande regressietests uit eerdere sessies opnieuw (voor zover ze nog in je scratchpad staan, anders overslaan)**

Deze zijn niet onderdeel van dit plan maar mogen niet stuk zijn gegaan door de wijzigingen hierboven, met name de tests rond `confirms_direction`, `winrate_stats`, `process_day_trading_signal` en de dashboard-/coin-pagina's uit eerdere features. Draai wat je van deze sessie nog hebt (bijvoorbeeld `test_heatmap.py`, `test_animations_render.py`, `test_confetti.py`, `test_volatility_breathing.py`, `test_migration_coins_note.py`, `test_message_summary.py`) op dezelfde manier:

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/<naam>.py` voor elk beschikbaar script.
Expected: geen nieuwe fouten ten opzichte van vóór dit plan (een reeds bekende, losstaande sandbox-netwerkfout naar Binance/Anthropic telt niet als regressie van dit plan, zie CLAUDE.md-context over de sandbox).

- [ ] **Step 3: Handmatige smoke-test van `run_swing_check`'s Telegram-tekst**

Run in een Python-shell (`python3 -i`, met dezelfde env-variabelen als de tests):
```python
from app import telegram_notify
print(telegram_notify.format_swing_message(
    "RAY", "long", 0.836, 0.80, 0.90,
    [("Trend", True, "EMA9 boven EMA21")], [("Trend", True, "EMA9 boven EMA21")],
    0.836, "resistance",
))
```
Expected: leesbare, volledige berichttekst zonder Python-fouten, met "Daily:", "4 uur:" en de zin over het ontbrekende vertrouwenspercentage.

- [ ] **Step 4: Push alle commits van dit plan**

```bash
git push origin claude/crypto-day-trading-alerts-5p8w6v
```

- [ ] **Step 5: Instructies voor de VPS-deploy (niet uit te voeren in deze sessie, alleen te documenteren voor de gebruiker)**

Na deze push moet op de VPS gedraaid worden:
```bash
cd /opt/crypto-alerts
git pull origin claude/crypto-day-trading-alerts-5p8w6v
sudo -u crypto .venv/bin/python3 scripts/backfill_swing_watches.py
sudo systemctl restart crypto-bot
sudo systemctl restart crypto-web
```
(`crypto-bot` bevat `signal_processor.py`/`level_check.py`/`telegram_notify.py`, `crypto-web` bevat `web/main.py`/`coin.html`: beide moeten herstarten. Overweeg `scripts/backtest_factors.py --limit 50` opnieuw te draaien voor de operator besluit `ENABLE_ADVANCED_FACTORS` (met de nieuwe daily-trend factor erin) aan te zetten of aan te laten staan.)

---

## Self-Review

**Spec coverage:**
- Architectuur (universele poort, directe + periodieke check) → Task 6, 7. ✓
- Niveau-gebaseerde risicoberekening met ondergrens en rolbepaling op prijspositie → Task 3. ✓
- Datamodel (`swing_watches`, `signals.trade_type`) → Task 1. ✓
- Winrate/journaal/risicogauge/correlatie/mute-scheiding → Task 2 (winrate), Task 6 (mute bewust weggelaten uit de swing-fanout); risicogauge (`total_open_risk_eur`) en correlatiewaarschuwing (`web/main.py` dashboard-route) filteren al niet op categorie, dus die tellen automatisch beide trade_types mee zonder codewijziging — geverifieerd tijdens het schrijven van dit plan, geen aparte taak nodig.
- Zichtbaarheid op het dashboard ("Bewaakt niveau") → Task 9. ✓
- Backfill → Task 10. ✓
- Foutafhandeling (ontbrekende data, te weinig geschiedenis, coin niet getrackt, meerdere niveaus, eenmalige melding per watch) → verspreid door Task 6/7, elke stap met een `try/except` die als "niet bevestigd" of "blijft wachtend" telt, nooit een crash.
- Daily-trend ook bij day trading als advanced factor, backtestbaar → Task 4, 5.
- Niveau-gebaseerde SL/TP ook bij day trading → Task 6, Step 12.

**Placeholder scan:** geen "TBD"/"implement later"/ongeschreven testcode gevonden bij het doorlopen van elke taak.

**Type-consistentie:** `StopTake` (risk.py), `Indicators`/`basic_factors`/`check_daily_trend` (indicators.py), `create_swing_watch`/`get_swing_watch`/`list_watches_by_status`/`update_swing_watch_status`/`active_swing_watches_for_coin` (repo.py) en `send_swing_signal`/`format_swing_message` (telegram_notify.py) gebruiken overal dezelfde namen en parameter-volgorde als waar ze voor het eerst gedefinieerd worden (Tasks 2, 3, 4, 8) en waar ze aangeroepen worden (Tasks 6, 7, 9).
