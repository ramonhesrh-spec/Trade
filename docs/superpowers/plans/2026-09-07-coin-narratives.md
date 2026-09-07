# Lopende verhalen per coin ("coin narratives") Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Groepeer lange-termijn Discord-berichten over dezelfde coin en
richting tot één doorlopend "narrative", met een bewerkte Telegram-melding
in plaats van losse, opeengestapelde alerts, en een expliciete melding
zodra een nieuw bericht een lopend verhaal tegenspreekt.

**Architecture:** Nieuwe tabel `coin_narratives` (één rij per lopend
verhaal per coin+richting) en `narrative_notifications` (welk
Telegram-bericht-ID hoort bij welk narrative voor welke gebruiker, zodat
een update dat bericht kan bewerken in plaats van een nieuwe sturen).
`signal_processor.evaluate_narrative` bepaalt bij elk `lange_termijn`-
bericht met een duidelijke richting of het een update, een tegenspraak, of
een nieuw verhaal is. Een periodieke 84-dagen-verval-check en een
narrative-bewuste versie van de bestaande day-trading context-note maken
het geheel af.

**Tech Stack:** Python (FastAPI/asyncio), SQLite, python-telegram-bot,
Jinja2, vanilla JS (LightweightCharts voor de coin-grafiek).

**Spec:** `docs/superpowers/specs/2026-09-07-coin-narratives-design.md`

## Global Constraints

- Schema-wijzigingen: nieuwe tabellen via `CREATE TABLE IF NOT EXISTS` in
  `app/schema.sql`; een nieuwe kolom op een bestaande tabel (`messages`)
  zowel in `schema.sql` (voor verse databases) als een idempotente
  `ALTER TABLE ... ADD COLUMN`, guarded door een `PRAGMA table_info`-check,
  in `app/db.py:_migrate()` (voor bestaande databases). Nooit alleen het
  een of het ander.
- Alle database-toegang loopt via `app/repo.py`. Geen losse SQL in
  `signal_processor.py`, `web/main.py`, of elders.
- Narratives raken `journal_entries`, `risk.py`, en positiegrootte niet:
  puur informatief/organisatorisch.
- Narratives en `swing_watches` blijven volledig gescheiden mechanismen;
  geen enkele taak in dit plan wijzigt `swing_watches`-code.
- 84 dagen verval-termijn: dezelfde waarde als
  `signal_processor.SWING_WATCH_MAX_AGE_DAYS`, voor consistentie (niet los
  herdefiniëren).
- Elke stap test tegen een scratch-SQLite-database
  (`DATABASE_PATH`-omgevingsvariabele), geen pytest-suite in dit project.
  Testscripts gebruiken plain `assert` + `print("OK: ...")`.
- Geen backfill van bestaande `messages`-rijen in dit plan.

---

### Task 1: Schema + migratie

**Files:**
- Modify: `app/schema.sql`
- Modify: `app/db.py`
- Test: `<scratchpad>/test_narrative_schema_migration.py`

**Interfaces:**
- Produces: tabellen `coin_narratives`, `narrative_notifications`;
  kolom `messages.narrative_id` (nullable INTEGER).

- [ ] **Step 1: Schrijf de migratie-test (simuleert een bestaande database)**

Maak `<scratchpad>/test_narrative_schema_migration.py`:

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

from app import config
config.DATABASE_PATH = db_path

# Simuleer een bestaande database van vóór deze feature: alleen de kale
# messages-tabel zonder narrative_id, en zonder de twee nieuwe tabellen.
conn = sqlite3.connect(db_path)
conn.execute("""
    CREATE TABLE messages (
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
        processed_at TEXT,
        discord_user_id TEXT,
        message_summary TEXT,
        price_at_receipt REAL
    )
""")
conn.execute(
    "INSERT INTO messages (received_at, raw_text) VALUES ('2026-01-01T00:00:00+00:00', 'oud bericht')"
)
conn.commit()
conn.close()

from app import db
db.init_db()

with sqlite3.connect(db_path) as conn:
    conn.row_factory = sqlite3.Row
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(messages)")}
    assert "narrative_id" in cols, f"narrative_id ontbreekt na migratie: {cols}"

    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "coin_narratives" in tables, "coin_narratives-tabel niet aangemaakt"
    assert "narrative_notifications" in tables, "narrative_notifications-tabel niet aangemaakt"

    # Het oude bericht bestaat nog en heeft narrative_id = NULL, geen crash.
    row = conn.execute("SELECT narrative_id FROM messages WHERE raw_text = 'oud bericht'").fetchone()
    assert row["narrative_id"] is None
print("OK: migratie voegt narrative_id toe aan messages en maakt beide nieuwe tabellen aan, op een bestaande database")

# Nogmaals draaien (idempotent) mag niet crashen.
db.init_db()
print("OK: migratie is idempotent, tweede keer draaien crasht niet")

print("ALLE NARRATIVE-SCHEMA-MIGRATIETESTS GESLAAGD")
```

- [ ] **Step 2: Run, verwacht een fout (kolom/tabellen bestaan nog niet)**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_narrative_schema_migration.py`
Expected: `AssertionError: narrative_id ontbreekt na migratie` (of een vergelijkbare eerste assert die faalt, afhankelijk van executievolgorde vóór de wijziging).

- [ ] **Step 3: Voeg de twee nieuwe tabellen toe aan `app/schema.sql`**

Voeg toe, direct na het bestaande `CREATE TABLE IF NOT EXISTS swing_watches`-blok en zijn indexen (zoek op `idx_swing_watches_coin` als ankerpunt, voeg hierna toe):

```sql
-- Eén rij per doorlopend "verhaal" over een coin: een reeks lange-termijn
-- berichten met dezelfde richting die bij elkaar horen. Zie
-- docs/superpowers/specs/2026-09-07-coin-narratives-design.md.
CREATE TABLE IF NOT EXISTS coin_narratives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin TEXT NOT NULL,
    direction TEXT NOT NULL,
    -- actief/tegengesproken/verlopen, zie de spec.
    status TEXT NOT NULL DEFAULT 'actief',
    message_count INTEGER NOT NULL DEFAULT 1,
    opened_at TEXT NOT NULL,
    last_update_at TEXT NOT NULL,
    closed_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_coin_narratives_coin_status ON coin_narratives(coin, status);

-- Welk Telegram-bericht-ID bij welk narrative hoort voor welke gebruiker:
-- nodig om een update te kunnen bewerken (bot.edit_message_text) in
-- plaats van een nieuwe melding te sturen. Eén regel per narrative+
-- gebruiker, bijgewerkt bij elke nieuwe melding voor dat narrative.
CREATE TABLE IF NOT EXISTS narrative_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    narrative_id INTEGER NOT NULL REFERENCES coin_narratives(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    telegram_message_id INTEGER NOT NULL,
    sent_at TEXT NOT NULL,
    UNIQUE(narrative_id, user_id)
);
```

Voeg de nieuwe kolom toe aan de bestaande `CREATE TABLE IF NOT EXISTS
messages`-definitie (zoek de regel `price_at_receipt REAL` — dat is de
laatste kolom vóór de sluitende `)`  — en voeg een komma plus de nieuwe
regel toe direct erna):

```sql
    price_at_receipt REAL,
    -- Welk lopend verhaal (coin_narratives) dit bericht opvolgt of start.
    -- NULL voor berichten zonder duidelijke lange-termijn richting, en
    -- voor alle berichten van vóór deze feature (geen backfill).
    narrative_id INTEGER REFERENCES coin_narratives(id)
);
```

- [ ] **Step 4: Voeg de migratie toe aan `app/db.py:_migrate()`**

Zoek het bestaande blok `existing_messages = {row["name"] for row in
conn.execute("PRAGMA table_info(messages)")}` en de `if` regels eronder
(voor `discord_user_id`, `message_summary`, `price_at_receipt`). Voeg
direct na de laatste `if "price_at_receipt" not in existing_messages:`
regel toe:

```python
    if "narrative_id" not in existing_messages:
        conn.execute("ALTER TABLE messages ADD COLUMN narrative_id INTEGER REFERENCES coin_narratives(id)")
```

(De `CREATE TABLE IF NOT EXISTS coin_narratives` uit `schema.sql` heeft op
dit punt altijd al gedraaid — `db.init_db()` voert eerst het hele
`schema.sql`-script uit en roept daarna pas `_migrate()` aan — dus de
tabel waar deze kolom naar verwijst bestaat gegarandeerd al, ook op een
bestaande database die nog nooit `coin_narratives` heeft gezien.)

- [ ] **Step 5: Run de test opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_narrative_schema_migration.py`
Expected: beide "OK:"-regels, eindigend met "ALLE NARRATIVE-SCHEMA-MIGRATIETESTS GESLAAGD".

- [ ] **Step 6: Commit**

```bash
git add app/schema.sql app/db.py
git commit -m "$(cat <<'EOF'
Schema: coin_narratives, narrative_notifications, messages.narrative_id

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: `app/repo.py` — CRUD voor narratives en notificaties

**Files:**
- Modify: `app/repo.py`
- Test: `<scratchpad>/test_narrative_repo.py`

**Interfaces:**
- Consumes: tabellen uit Task 1.
- Produces:
  - `get_active_narrative(coin: str) -> Optional[dict]`
  - `get_narrative(narrative_id: int) -> Optional[dict]`
  - `create_narrative(coin: str, direction: str, message_id: int) -> int`
  - `update_narrative_progress(narrative_id: int, message_id: int) -> None`
  - `close_narrative(narrative_id: int, status: str, closed_reason: str) -> None`
  - `list_active_narratives() -> list[dict]`
  - `list_narratives_for_coin(coin: str) -> list[dict]`
  - `list_narrative_messages(narrative_id: int) -> list[dict]`
  - `get_narrative_notification(narrative_id: int, user_id: int) -> Optional[dict]`
  - `upsert_narrative_notification(narrative_id: int, user_id: int, telegram_message_id: int) -> None`

- [ ] **Step 1: Schrijf de test**

Maak `<scratchpad>/test_narrative_repo.py`:

```python
import os
import sys
import tempfile

sys.path.insert(0, "/home/user/Trade")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-narrative-repo-0123456789"

from app import config
config.DATABASE_PATH = db_path

from app import db, repo

db.init_db()
uid = repo.create_user("narratest", "hash", 1000.0, 1.0, "111")


def make_message(coin: str, direction: str, text: str) -> int:
    with db.session() as conn:
        conn.execute(
            "INSERT INTO messages (received_at, raw_text, category, coin, direction, message_summary) "
            "VALUES (?, ?, 'lange_termijn', ?, ?, ?)",
            (db.now_iso(), text, coin, direction, text),
        )
        return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


# --- create_narrative + get_active_narrative + get_narrative ---
msg1 = make_message("TAO", "long", "eerste bericht")
narrative_id = repo.create_narrative("TAO", "long", msg1)
active = repo.get_active_narrative("TAO")
assert active is not None and active["id"] == narrative_id
assert active["status"] == "actief"
assert active["message_count"] == 1
fetched = repo.get_narrative(narrative_id)
assert fetched["coin"] == "TAO" and fetched["direction"] == "long"
print("OK: create_narrative maakt een actief narrative aan, get_active_narrative vindt het")

# --- messages.narrative_id gekoppeld ---
with db.session() as conn:
    row = conn.execute("SELECT narrative_id FROM messages WHERE id = ?", (msg1,)).fetchone()
    assert row["narrative_id"] == narrative_id
print("OK: create_narrative koppelt het bericht via messages.narrative_id")

# --- update_narrative_progress ---
msg2 = make_message("TAO", "long", "tweede bericht, zelfde richting")
repo.update_narrative_progress(narrative_id, msg2)
updated = repo.get_narrative(narrative_id)
assert updated["message_count"] == 2
with db.session() as conn:
    row = conn.execute("SELECT narrative_id FROM messages WHERE id = ?", (msg2,)).fetchone()
    assert row["narrative_id"] == narrative_id
print("OK: update_narrative_progress telt message_count op en koppelt het nieuwe bericht")

# --- close_narrative ---
repo.close_narrative(narrative_id, "tegengesproken", "test-reden")
closed = repo.get_narrative(narrative_id)
assert closed["status"] == "tegengesproken"
assert closed["closed_reason"] == "test-reden"
assert repo.get_active_narrative("TAO") is None
print("OK: close_narrative zet status en reden, get_active_narrative vindt niets meer")

# --- list_active_narratives ---
msg3 = make_message("TAO", "short", "derde bericht, nu short")
new_narrative_id = repo.create_narrative("TAO", "short", msg3)
msg4 = make_message("ETH", "long", "los bericht over ETH")
eth_narrative_id = repo.create_narrative("ETH", "long", msg4)
active_all = repo.list_active_narratives()
active_ids = {n["id"] for n in active_all}
assert new_narrative_id in active_ids and eth_narrative_id in active_ids
assert narrative_id not in active_ids  # die staat op tegengesproken
print("OK: list_active_narratives geeft alleen echt actieve narratives terug, over alle coins heen")

# --- list_narratives_for_coin ---
tao_narratives = repo.list_narratives_for_coin("TAO")
tao_ids_in_order = [n["id"] for n in tao_narratives]
assert tao_ids_in_order[0] == new_narrative_id, "het actieve narrative moet bovenaan staan"
assert narrative_id in tao_ids_in_order
print("OK: list_narratives_for_coin zet het actieve narrative bovenaan")

# --- list_narrative_messages ---
timeline = repo.list_narrative_messages(narrative_id)
assert [m["raw_text"] for m in timeline] == ["eerste bericht", "tweede bericht, zelfde richting"]
print("OK: list_narrative_messages geeft de berichten in volgorde van ontvangst")

# --- narrative_notifications ---
assert repo.get_narrative_notification(new_narrative_id, uid) is None
repo.upsert_narrative_notification(new_narrative_id, uid, 555)
first = repo.get_narrative_notification(new_narrative_id, uid)
assert first["telegram_message_id"] == 555
repo.upsert_narrative_notification(new_narrative_id, uid, 999)
second = repo.get_narrative_notification(new_narrative_id, uid)
assert second["telegram_message_id"] == 999, "upsert moet het bestaande bericht-ID bijwerken, niet dupliceren"
with db.session() as conn:
    count = conn.execute(
        "SELECT COUNT(*) AS n FROM narrative_notifications WHERE narrative_id = ? AND user_id = ?",
        (new_narrative_id, uid),
    ).fetchone()["n"]
    assert count == 1, f"upsert mag geen tweede rij aanmaken, kreeg {count}"
print("OK: narrative_notifications upsert bewerkt de bestaande rij in plaats van te dupliceren")

print("ALLE NARRATIVE-REPO-TESTS GESLAAGD")
```

- [ ] **Step 2: Run, verwacht een `AttributeError`**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_narrative_repo.py`
Expected: `AttributeError: module 'app.repo' has no attribute 'create_narrative'`

- [ ] **Step 3: Voeg de functies toe aan `app/repo.py`**

Plaats dit blok direct na de bestaande `list_recent_source_levels_without_watch`-functie (het einde van het swing-watches CRUD-blok), vóór `create_trendline`:

```python
def get_active_narrative(coin: str) -> Optional[dict]:
    """Het narrative met status 'actief' voor deze coin, ongeacht richting.
    Op elk moment hoort er hoogstens één te bestaan: een tegenspraak sluit
    het vorige altijd af vóór er een nieuwe wordt aangemaakt (zie
    signal_processor.evaluate_narrative)."""
    with db.session() as conn:
        row = conn.execute(
            "SELECT * FROM coin_narratives WHERE coin = ? AND status = 'actief' ORDER BY id DESC LIMIT 1",
            (coin.upper(),),
        ).fetchone()
        return dict(row) if row else None


def get_narrative(narrative_id: int) -> Optional[dict]:
    with db.session() as conn:
        row = conn.execute("SELECT * FROM coin_narratives WHERE id = ?", (narrative_id,)).fetchone()
        return dict(row) if row else None


def create_narrative(coin: str, direction: str, message_id: int) -> int:
    """Nieuw narrative, status 'actief', met dit bericht als eerste update."""
    now = db.now_iso()
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO coin_narratives (coin, direction, status, message_count, opened_at, last_update_at)
               VALUES (?, ?, 'actief', 1, ?, ?)""",
            (coin.upper(), direction.lower(), now, now),
        )
        narrative_id = cur.lastrowid
        conn.execute("UPDATE messages SET narrative_id = ? WHERE id = ?", (narrative_id, message_id))
        return narrative_id


def update_narrative_progress(narrative_id: int, message_id: int) -> None:
    """Koppelt een bericht als vervolg-update aan een bestaand narrative:
    telt message_count op, zet last_update_at bij op nu."""
    now = db.now_iso()
    with db.session() as conn:
        conn.execute(
            "UPDATE coin_narratives SET message_count = message_count + 1, last_update_at = ? WHERE id = ?",
            (now, narrative_id),
        )
        conn.execute("UPDATE messages SET narrative_id = ? WHERE id = ?", (narrative_id, message_id))


def close_narrative(narrative_id: int, status: str, closed_reason: str) -> None:
    with db.session() as conn:
        conn.execute(
            "UPDATE coin_narratives SET status = ?, closed_reason = ? WHERE id = ?",
            (status, closed_reason, narrative_id),
        )


def list_active_narratives() -> list[dict]:
    """Voor de periodieke verval-check (check_narratives): alle actieve
    narratives, over alle coins heen."""
    with db.session() as conn:
        rows = conn.execute("SELECT * FROM coin_narratives WHERE status = 'actief'").fetchall()
        return [dict(r) for r in rows]


def list_narratives_for_coin(coin: str) -> list[dict]:
    """Voor de coin-pagina: het actieve narrative (indien aanwezig)
    bovenaan, recente tegengesproken/verlopen narratives erna."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT * FROM coin_narratives WHERE coin = ?
               ORDER BY (status = 'actief') DESC, last_update_at DESC""",
            (coin.upper(),),
        ).fetchall()
        return [dict(r) for r in rows]


def list_narrative_messages(narrative_id: int) -> list[dict]:
    """De berichten van dit narrative, oudste eerst: de tijdlijn voor zowel
    de Telegram-melding als de coin-pagina-kaart."""
    with db.session() as conn:
        rows = conn.execute(
            "SELECT id, received_at, raw_text, message_summary FROM messages "
            "WHERE narrative_id = ? ORDER BY received_at ASC",
            (narrative_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_narrative_notification(narrative_id: int, user_id: int) -> Optional[dict]:
    with db.session() as conn:
        row = conn.execute(
            "SELECT * FROM narrative_notifications WHERE narrative_id = ? AND user_id = ?",
            (narrative_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def upsert_narrative_notification(narrative_id: int, user_id: int, telegram_message_id: int) -> None:
    """Onthoudt welk Telegram-bericht-ID de laatste melding van dit
    narrative was voor deze gebruiker, zodat een volgende update kan
    proberen dat bericht te bewerken. Overschrijft de vorige waarde in
    plaats van een tweede rij aan te maken."""
    with db.session() as conn:
        conn.execute(
            """INSERT INTO narrative_notifications (narrative_id, user_id, telegram_message_id, sent_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(narrative_id, user_id) DO UPDATE SET
                   telegram_message_id = excluded.telegram_message_id,
                   sent_at = excluded.sent_at""",
            (narrative_id, user_id, telegram_message_id, db.now_iso()),
        )
```

- [ ] **Step 4: Run de test opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_narrative_repo.py`
Expected: alle "OK:"-regels, eindigend met "ALLE NARRATIVE-REPO-TESTS GESLAAGD".

- [ ] **Step 5: Commit**

```bash
git add app/repo.py
git commit -m "$(cat <<'EOF'
repo.py: CRUD voor coin_narratives en narrative_notifications

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: `app/signal_processor.py` — matching-logica + wiring (met tijdelijke Telegram-stub)

**Files:**
- Modify: `app/signal_processor.py`
- Modify: `app/telegram_notify.py` (alleen de tijdelijke stub, verwijderd in Task 4)
- Test: `<scratchpad>/test_narrative_signal_processor.py`

**Interfaces:**
- Consumes: alle `repo.*narrative*`-functies uit Task 2.
- Produces:
  - `evaluate_narrative(message_id: int, coin: str, direction: str, message_summary: str) -> None`
  - Wiring in `handle_message`: voor `interp.category == "lange_termijn"` met `interp.direction in ("long", "short")` wordt `evaluate_narrative` aangeroepen in plaats van (het bestaande) `telegram_notify.send_long_term_message`. Voor elke andere combinatie (categorie `aandelen`, of een lange-termijn bericht zonder duidelijke richting) blijft het bestaande gedrag exact zoals het was.
- Tijdelijke stub (vervangen in Task 4): `telegram_notify.send_narrative_update(coin, direction, timeline, chat_id, existing_message_id, is_contradiction, contradicted_since=None, force_silent=False) -> int`.

- [ ] **Step 1: Voeg de tijdelijke stub toe aan `app/telegram_notify.py`**

Voeg toe aan het einde van het bestand:

```python
async def send_narrative_update(
    coin: str, direction: str, timeline: list[dict], chat_id: str,
    existing_message_id: Optional[int], is_contradiction: bool,
    contradicted_since: Optional[str] = None, force_silent: bool = False,
) -> int:
    """TIJDELIJKE STUB, vervangen in Task 4 door de echte implementatie
    (format_narrative_message + bot.send_message/edit_message_text). Dit
    is opzettelijk zo, geen fout: Task 3 test evaluate_narrative's
    matching-logica los van de Telegram-opmaak, en Task 4 heeft
    evaluate_narrative's afgeronde aanroep-conventie nodig om tegen te
    implementeren."""
    logger.info(
        "STUB send_narrative_update: %s %s naar chat %s (tegenspraak=%s, bestaand bericht-id=%s)",
        coin, direction, chat_id, is_contradiction, existing_message_id,
    )
    return (existing_message_id or 0) + 1
```

- [ ] **Step 2: Schrijf de test**

Maak `<scratchpad>/test_narrative_signal_processor.py`:

```python
import asyncio
import os
import sys
import tempfile

sys.path.insert(0, "/home/user/Trade")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-narrative-sigproc-0123456789"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path

from app import db, repo, signal_processor

db.init_db()
uid = repo.create_user("narrasig", "hash", 1000.0, 1.0, "222")


def make_message(coin: str, direction: str, text: str) -> int:
    with db.session() as conn:
        conn.execute(
            "INSERT INTO messages (received_at, raw_text, category, coin, direction, message_summary) "
            "VALUES (?, ?, 'lange_termijn', ?, ?, ?)",
            (db.now_iso(), text, coin, direction, text),
        )
        return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


# --- Geen actief narrative: nieuw narrative aanmaken ---
msg1 = make_message("TAO", "long", "eerste TAO analyse")
asyncio.run(signal_processor.evaluate_narrative(msg1, "TAO", "long", "eerste TAO analyse"))
active = repo.get_active_narrative("TAO")
assert active is not None and active["direction"] == "long" and active["message_count"] == 1
first_narrative_id = active["id"]
print("OK: eerste lange-termijn bericht over een coin start een nieuw, actief narrative")

# --- Zelfde richting: update van het bestaande narrative ---
msg2 = make_message("TAO", "long", "extra ingeschaald op TAO")
asyncio.run(signal_processor.evaluate_narrative(msg2, "TAO", "long", "extra ingeschaald op TAO"))
updated = repo.get_narrative(first_narrative_id)
assert updated["message_count"] == 2, f"verwacht 2 updates, kreeg {updated['message_count']}"
assert repo.get_active_narrative("TAO")["id"] == first_narrative_id, "moet hetzelfde narrative blijven, geen nieuw"
print("OK: een tweede bericht met dezelfde richting update het bestaande narrative, geen nieuw")

# --- Tegenovergestelde richting: tegenspraak, oud narrative sluit, nieuw ontstaat ---
msg3 = make_message("TAO", "short", "kale link, verkeerd geïnterpreteerd als short")
asyncio.run(signal_processor.evaluate_narrative(msg3, "TAO", "short", "kale link"))
old = repo.get_narrative(first_narrative_id)
assert old["status"] == "tegengesproken", f"verwacht 'tegengesproken', kreeg {old['status']}"
new_active = repo.get_active_narrative("TAO")
assert new_active is not None and new_active["id"] != first_narrative_id
assert new_active["direction"] == "short" and new_active["message_count"] == 1
print("OK: een bericht met de tegenovergestelde richting sluit het oude narrative af en start een nieuwe")

# --- Neutrale/onbekende richting doet niet mee ---
msg4 = make_message("TAO", "neutraal", "verdeeld bericht")
asyncio.run(signal_processor.evaluate_narrative(msg4, "TAO", "neutraal", "verdeeld bericht"))
still_active = repo.get_active_narrative("TAO")
assert still_active["id"] == new_active["id"] and still_active["message_count"] == 1, (
    "een 'neutraal'-bericht mag het lopende narrative niet aanraken"
)
print("OK: een bericht zonder long/short richting raakt het lopende narrative niet aan")

print("ALLE NARRATIVE-SIGNAL_PROCESSOR TESTS GESLAAGD")
```

- [ ] **Step 3: Run, verwacht een `AttributeError`**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_narrative_signal_processor.py`
Expected: `AttributeError: module 'app.signal_processor' has no attribute 'evaluate_narrative'`

- [ ] **Step 4: Voeg `evaluate_narrative` toe aan `app/signal_processor.py`**

Plaats dit blok direct na `evaluate_level_watch` (dus vóór `def
run_swing_check` als die ertussen staat is prima, zolang het na
`evaluate_level_watch` komt):

```python
async def evaluate_narrative(message_id: int, coin: str, direction: str, message_summary: str) -> None:
    """Aangeroepen voor elk lange_termijn-bericht met een duidelijke
    richting (long/short — 'neutraal' en een ontbrekende richting doen
    hier niet aan mee, net als bij _build_context_note). Bepaalt of dit
    bericht een update is van het lopende verhaal over deze coin, een
    tegenspraak daarvan, of het begin van een nieuw verhaal.

    Tegenspraak sluit het oude narrative expliciet af (status
    'tegengesproken') vóór er een nieuwe wordt aangemaakt: er hoort op elk
    moment hoogstens één actief narrative per coin te zijn, ongeacht welke
    richting."""
    if direction not in ("long", "short"):
        return

    active = repo.get_active_narrative(coin)
    if active is None:
        narrative_id = repo.create_narrative(coin, direction, message_id)
        await _send_narrative_notifications(narrative_id, is_new=True, is_contradiction=False)
        return

    if active["direction"] == direction:
        repo.update_narrative_progress(active["id"], message_id)
        await _send_narrative_notifications(active["id"], is_new=False, is_contradiction=False)
        return

    repo.close_narrative(
        active["id"], "tegengesproken",
        f"tegengesproken door een nieuw {direction}-narrative voor {coin}",
    )
    new_narrative_id = repo.create_narrative(coin, direction, message_id)
    await _send_narrative_notifications(
        new_narrative_id, is_new=True, is_contradiction=True, contradicted=active,
    )


async def _send_narrative_notifications(
    narrative_id: int, is_new: bool, is_contradiction: bool, contradicted: Optional[dict] = None,
) -> None:
    """Stuurt of bewerkt de narrative-melding voor elke gebruiker met een
    gekoppelde Telegram-chat. Een tegenspraak of het allereerste bericht
    van een narrative heeft nooit een bestaand bericht om te bewerken; een
    update probeert altijd eerst het vorige bericht te bewerken (zie
    telegram_notify.send_narrative_update voor de edit/verse-melding-
    afweging zelf)."""
    narrative = repo.get_narrative(narrative_id)
    timeline = repo.list_narrative_messages(narrative_id)
    contradicted_since = contradicted["opened_at"][:10] if contradicted else None

    for user in repo.list_users():
        if not user["telegram_chat_id"]:
            continue
        existing = None if is_new else repo.get_narrative_notification(narrative_id, user["id"])
        existing_message_id = existing["telegram_message_id"] if existing else None
        quiet = telegram_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            telegram_message_id = await telegram_notify.send_narrative_update(
                narrative["coin"], narrative["direction"], timeline, user["telegram_chat_id"],
                existing_message_id, is_contradiction, contradicted_since, force_silent=quiet,
            )
            repo.upsert_narrative_notification(narrative_id, user["id"], telegram_message_id)
        except Exception:
            logger.exception("Narrative-melding voor %s naar gebruiker %s is mislukt",
                              narrative["coin"], user["username"])
```

Controleer of `Optional` al geïmporteerd is bovenin `app/signal_processor.py`
(`from typing import Optional`); zo niet, voeg die import toe.

- [ ] **Step 5: Wijzig de wiring in `handle_message`**

Zoek dit blok (de `if interp.category != "day_trading":`-tak):

```python
        if message_summary:
            for user in repo.list_users():
                if not user["telegram_chat_id"]:
                    continue
                try:
                    await telegram_notify.send_long_term_message(
                        interp.coin, interp.direction, message_summary,
                        chat_id=user["telegram_chat_id"],
                    )
                except Exception:
                    logger.exception("Lange-termijn melding voor %s naar gebruiker %s is mislukt",
                                      interp.coin, user["username"])
        return
```

Vervang door:

```python
        if interp.category == "lange_termijn" and interp.direction in ("long", "short"):
            try:
                await evaluate_narrative(message_id, interp.coin, interp.direction, message_summary or "")
            except Exception:
                logger.exception("Narrative-evaluatie voor %s (bericht %s) is mislukt",
                                  interp.coin, message_id)
        elif message_summary:
            for user in repo.list_users():
                if not user["telegram_chat_id"]:
                    continue
                try:
                    await telegram_notify.send_long_term_message(
                        interp.coin, interp.direction, message_summary,
                        chat_id=user["telegram_chat_id"],
                    )
                except Exception:
                    logger.exception("Lange-termijn melding voor %s naar gebruiker %s is mislukt",
                                      interp.coin, user["username"])
        return
```

(Dit raakt alleen `lange_termijn`-berichten met een bekende long/short-
richting. Categorie `aandelen`, en elk lange-termijn bericht met richting
`neutraal` of leeg, blijven exact het bestaande `send_long_term_message`-
gedrag houden.)

- [ ] **Step 6: Run de test opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_narrative_signal_processor.py`
Expected: alle "OK:"-regels, eindigend met "ALLE NARRATIVE-SIGNAL_PROCESSOR TESTS GESLAAGD".

- [ ] **Step 7: Commit**

```bash
git add app/signal_processor.py app/telegram_notify.py
git commit -m "$(cat <<'EOF'
signal_processor.py: evaluate_narrative matching-logica + wiring

Update/tegenspraak/nieuw-narrative-logica voor lange-termijn berichten
met een duidelijke richting. telegram_notify.send_narrative_update is
hier nog een tijdelijke stub, vervangen in de volgende taak.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `app/telegram_notify.py` — de echte narrative-melding

**Files:**
- Modify: `app/telegram_notify.py`
- Test: `<scratchpad>/test_narrative_telegram.py`

**Interfaces:**
- Produces:
  - `format_narrative_message(coin: str, direction: str, timeline: list[dict], is_contradiction: bool, contradicted_since: Optional[str]) -> str`
  - `async def send_narrative_update(coin, direction, timeline, chat_id, existing_message_id, is_contradiction, contradicted_since=None, force_silent=False) -> int` — vervangt de tijdelijke stub uit Task 3, zelfde signatuur.

- [ ] **Step 1: Schrijf de test**

Maak `<scratchpad>/test_narrative_telegram.py`:

```python
import asyncio
import os
import sys

sys.path.insert(0, "/home/user/Trade")
os.environ["JWT_SECRET"] = "test-secret-narrative-tg-0123456789"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import telegram_notify

timeline = [
    {"received_at": "2026-09-07T05:55:14+00:00", "raw_text": "Lange termijn TAO gekocht", "message_summary": "Voor het eerst TAO ingekocht, meerdere technische redenen."},
    {"received_at": "2026-09-07T06:15:01+00:00", "raw_text": "Extra ingeschaald op TAO", "message_summary": "Extra TAO gekocht na een breakout-bevestiging."},
]

text = telegram_notify.format_narrative_message("TAO", "long", timeline, is_contradiction=False, contradicted_since=None)
assert "TAO" in text
assert "LONG" in text
assert "2 update" in text
assert "Voor het eerst TAO ingekocht" in text
assert "Extra TAO gekocht na een breakout" in text
assert "tegen" not in text.lower(), "geen tegenspraak-taal bij een normale update"
print("OK: format_narrative_message toont richting, aantal updates, en de volledige tijdlijn")

text_contradiction = telegram_notify.format_narrative_message(
    "TAO", "short", timeline[:1], is_contradiction=True, contradicted_since="2026-09-05",
)
assert "tegen" in text_contradiction.lower()
assert "2026-09-05" in text_contradiction
print("OK: format_narrative_message benoemt een tegenspraak expliciet, met de datum van het oude narrative")


class FakeSentMessage:
    def __init__(self, message_id):
        self.message_id = message_id


class FakeBot:
    def __init__(self, edit_should_fail=False):
        self.edit_should_fail = edit_should_fail
        self.sent = []
        self.edited = []

    async def send_message(self, chat_id, text, disable_notification=False, reply_markup=None):
        self.sent.append((chat_id, text))
        return FakeSentMessage(message_id=len(self.sent) + 1000)

    async def edit_message_text(self, chat_id, message_id, text):
        if self.edit_should_fail:
            raise RuntimeError("bericht te oud om te bewerken (gesimuleerd, >48u)")
        self.edited.append((chat_id, message_id, text))


fake_bot_ok = FakeBot(edit_should_fail=False)
telegram_notify.Bot = lambda token: fake_bot_ok

result_id = asyncio.run(telegram_notify.send_narrative_update(
    "TAO", "long", timeline, "chat-1", existing_message_id=1234, is_contradiction=False,
))
assert result_id == 1234, f"een gelukte edit moet hetzelfde bericht-id teruggeven, kreeg {result_id}"
assert fake_bot_ok.edited and fake_bot_ok.edited[0][1] == 1234
assert not fake_bot_ok.sent, "bij een gelukte edit mag er geen nieuw bericht verstuurd worden"
print("OK: send_narrative_update bewerkt het bestaande bericht als dat nog kan")

fake_bot_fail = FakeBot(edit_should_fail=True)
telegram_notify.Bot = lambda token: fake_bot_fail
result_id2 = asyncio.run(telegram_notify.send_narrative_update(
    "TAO", "long", timeline, "chat-1", existing_message_id=1234, is_contradiction=False,
))
assert result_id2 == 1001, f"een mislukte edit moet terugvallen op een verse melding, kreeg {result_id2}"
assert len(fake_bot_fail.sent) == 1
print("OK: send_narrative_update valt terug op een verse melding als bewerken niet meer kan")

fake_bot_contradiction = FakeBot(edit_should_fail=False)
telegram_notify.Bot = lambda token: fake_bot_contradiction
result_id3 = asyncio.run(telegram_notify.send_narrative_update(
    "TAO", "short", timeline[:1], "chat-1", existing_message_id=1234, is_contradiction=True,
    contradicted_since="2026-09-05",
))
assert not fake_bot_contradiction.edited, "een tegenspraak mag NOOIT een bestaand bericht bewerken"
assert len(fake_bot_contradiction.sent) == 1
print("OK: send_narrative_update stuurt bij een tegenspraak altijd een verse melding, nooit een edit")

print("ALLE NARRATIVE-TELEGRAM TESTS GESLAAGD")
```

- [ ] **Step 2: Run, verwacht een `AssertionError` (de stub geeft geen zinnige tekst/gedrag terug)**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_narrative_telegram.py`
Expected: `AttributeError: module 'app.telegram_notify' has no attribute 'format_narrative_message'`

- [ ] **Step 3: Verwijder de tijdelijke stub en implementeer de echte functies**

Verwijder de `send_narrative_update`-stub uit Task 3 volledig, en vervang
hem (op dezelfde plek, aan het eind van het bestand) door:

```python
def format_narrative_message(
    coin: str, direction: str, timeline: list[dict], is_contradiction: bool,
    contradicted_since: Optional[str],
) -> str:
    """Eén doorlopend verhaal per coin+richting, niet losse berichten per
    update: laat altijd de volledige, actuele stand zien (sinds wanneer,
    hoeveel updates, wat er tot nu toe gezegd is), niet alleen het
    nieuwste fragment."""
    lines = [
        f"{_direction_emoji(direction)} {_coin_label(coin)} · lange termijn verhaal",
        DIVIDER,
    ]
    if is_contradiction:
        opposite = "short" if direction == "long" else "long"
        when = f" van {contradicted_since}" if contradicted_since else ""
        lines.append(f"⚠️ Let op: dit spreekt je lopende {opposite}-analyse{when} tegen.")
        lines.append(DIVIDER)

    since = timeline[0]["received_at"][:10] if timeline else "-"
    count = len(timeline)
    lines.append(f"{_direction_label(direction)} · sinds {since} · {count} update{'s' if count != 1 else ''}")
    lines.append("")
    for entry in timeline:
        when = entry["received_at"][:10]
        text = entry["message_summary"] or entry["raw_text"]
        lines.append(f"• {when}: {text}")
    lines += [DIVIDER, f"⚠️ {config.DISCLAIMER}"]
    return "\n".join(lines)


async def send_narrative_update(
    coin: str, direction: str, timeline: list[dict], chat_id: str,
    existing_message_id: Optional[int], is_contradiction: bool,
    contradicted_since: Optional[str] = None, force_silent: bool = False,
) -> int:
    """Bewerkt de bestaande melding voor dit narrative als dat nog kan
    (binnen Telegrams eigen 48-uursgrens voor bewerken), anders (of bij een
    tegenspraak, die altijd apart moet opvallen) een verse melding. Geeft
    het bericht-ID terug dat de aanroeper moet onthouden voor de volgende
    update van dit narrative."""
    if not config.TELEGRAM_BOT_TOKEN or not chat_id:
        logger.warning("Telegram token of chat ID ontbreekt, narrative-melding niet verstuurd")
        return existing_message_id or 0

    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    text = format_narrative_message(coin, direction, timeline, is_contradiction, contradicted_since)

    if is_contradiction or existing_message_id is None:
        message = await bot.send_message(chat_id=chat_id, text=text, disable_notification=force_silent)
        return message.message_id

    try:
        await bot.edit_message_text(chat_id=chat_id, message_id=existing_message_id, text=text)
        return existing_message_id
    except Exception:
        logger.info(
            "Kon narrative-melding %s niet meer bewerken (waarschijnlijk >48u oud), verse melding gestuurd",
            existing_message_id,
        )
        message = await bot.send_message(chat_id=chat_id, text=text, disable_notification=force_silent)
        return message.message_id
```

- [ ] **Step 4: Run de test opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_narrative_telegram.py`
Expected: alle "OK:"-regels, eindigend met "ALLE NARRATIVE-TELEGRAM TESTS GESLAAGD".

- [ ] **Step 5: Draai `test_narrative_signal_processor.py` uit Task 3 opnieuw**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_narrative_signal_processor.py`
Expected: nog steeds alle "OK:"-regels — de stub-vervanging mag Task 3's
matching-logica niet breken. `send_narrative_update` faalt in dit scenario
stil op de ontbrekende echte Telegram-verbinding (geen `TELEGRAM_BOT_TOKEN`
die echt werkt), wat al opgevangen wordt door `_send_narrative_notifications`'s
eigen `except Exception: logger.exception(...)` — dat blijft ongewijzigd.

- [ ] **Step 6: Commit**

```bash
git add app/telegram_notify.py
git commit -m "$(cat <<'EOF'
telegram_notify.py: echte narrative-melding, bewerkt in plaats van gestapeld

Vervangt de tijdelijke stub uit signal_processor.py. Een update binnen
hetzelfde narrative bewerkt de vorige melding; lukt dat niet meer (ouder
dan Telegrams eigen bewerk-limiet) of is het een tegenspraak, dan gaat er
een verse melding uit.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: `app/signal_processor.py` — `_build_context_note` narrative-bewust maken

**Files:**
- Modify: `app/signal_processor.py`
- Test: `<scratchpad>/test_narrative_context_note.py`

**Interfaces:**
- Consumes: `repo.get_active_narrative` (Task 2).
- Produces: `_build_context_note(coin: str, direction: str) -> str` (zelfde
  signatuur en aanroepers als vandaag, nu narrative-gebaseerd).

- [ ] **Step 1: Schrijf de test**

Maak `<scratchpad>/test_narrative_context_note.py`:

```python
import os
import sys
import tempfile

sys.path.insert(0, "/home/user/Trade")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-narrative-context-0123456789"

from app import config
config.DATABASE_PATH = db_path

from app import db, repo, signal_processor

db.init_db()


def make_message(coin: str, direction: str) -> int:
    with db.session() as conn:
        conn.execute(
            "INSERT INTO messages (received_at, raw_text, category, coin, direction) "
            "VALUES (?, 'test', 'lange_termijn', ?, ?)",
            (db.now_iso(), coin, direction),
        )
        return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


# --- Geen narrative: lege context ---
assert signal_processor._build_context_note("NOCOIN", "long") == ""
print("OK: geen actief narrative geeft een lege context-note, geen crash")

# --- Zelfde richting: 'sluit aan' ---
msg = make_message("TAO", "long")
repo.create_narrative("TAO", "long", msg)
note_aligned = signal_processor._build_context_note("TAO", "long")
assert "sluit aan" in note_aligned.lower()
print("OK: een day-trading signaal in dezelfde richting als het actieve narrative krijgt een 'sluit aan'-tekst")

# --- Tegenovergestelde richting: expliciete waarschuwing ---
note_conflict = signal_processor._build_context_note("TAO", "short")
assert "let op" in note_conflict.lower() and "wijkt" in note_conflict.lower()
print("OK: een day-trading signaal tegen het actieve narrative in krijgt een expliciete waarschuwing")

# --- Een tegengesproken narrative telt niet meer mee als context ---
repo.close_narrative(repo.get_active_narrative("TAO")["id"], "tegengesproken", "test")
assert signal_processor._build_context_note("TAO", "long") == "", (
    "een tegengesproken narrative mag niet meer als 'actuele context' gelden"
)
print("OK: een tegengesproken of verlopen narrative telt niet meer mee voor de context-note")

print("ALLE NARRATIVE-CONTEXT-NOTE TESTS GESLAAGD")
```

- [ ] **Step 2: Run, verwacht dat de eerste assert al faalt of een andere fout geeft**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_narrative_context_note.py`
Expected: een fout op de "sluit aan"-assert (of eerder), omdat
`_build_context_note` nog op `repo.latest_long_term_direction` draait, die
niets weet van `coin_narratives`.

- [ ] **Step 3: Herschrijf `_build_context_note`**

Vervang de hele functie:

```python
def _build_context_note(coin: str, direction: str) -> str:
    """Zet dit signaal af tegen het meest recente lange termijn bericht over
    dezelfde coin. Verandert niets aan het hoog/laag vertrouwen label, dat
    blijft puur op de vier technische factoren gebaseerd, dit is extra
    achtergrond die meegaat in de melding."""
    latest = repo.latest_long_term_direction(coin)
    if not latest:
        return ""

    when = latest["received_at"][:10]
    if latest["direction"] == "neutraal":
        return (f"Let op: recente lange termijn analyse is verdeeld over deze coin, "
                f"geen duidelijke richting ({when}). Dit signaal staat op zichzelf.")
    if latest["direction"] == direction.lower():
        return f"Sluit aan bij recente lange termijn analyse ({direction}, {when})."
    return (f"Let op: recente lange termijn analyse wijst op "
            f"{latest['direction']}, dit signaal wijkt daarvan af ({when}).")
```

door:

```python
def _build_context_note(coin: str, direction: str) -> str:
    """Zet dit signaal af tegen het lopende lange-termijn narrative voor
    deze coin (zie evaluate_narrative). Verandert niets aan het hoog/laag
    vertrouwen label, dat blijft puur op de vier technische factoren
    gebaseerd, dit is extra achtergrond die meegaat in de melding.

    Alleen een narrative met status 'actief' telt mee: een tegengesproken
    of verlopen narrative is per definitie niet meer de actuele stand van
    zaken. Dit is bewust strenger dan de vorige versie (die simpelweg het
    allerlaatste lange-termijn bericht pakte, ongeacht of dat bericht zelf
    betrouwbaar was) — zie het TAO-incident in de spec."""
    active = repo.get_active_narrative(coin)
    if not active:
        return ""

    when = active["opened_at"][:10]
    if active["direction"] == direction.lower():
        return f"Sluit aan bij lopend lange termijn verhaal ({direction}, sinds {when})."
    return (f"Let op: lopend lange termijn verhaal wijst op "
            f"{active['direction']}, dit signaal wijkt daarvan af (sinds {when}).")
```

- [ ] **Step 4: Run de test opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_narrative_context_note.py`
Expected: alle "OK:"-regels, eindigend met "ALLE NARRATIVE-CONTEXT-NOTE TESTS GESLAAGD".

- [ ] **Step 5: Commit**

```bash
git add app/signal_processor.py
git commit -m "$(cat <<'EOF'
signal_processor.py: _build_context_note narrative-bewust maken

Was gebaseerd op simpelweg het allerlaatste lange-termijn bericht,
ongeacht of dat bericht zelf betrouwbaar was — exact de zwakte die het
TAO-incident blootlegde. Nu gebaseerd op het actieve narrative: een
tegengesproken of verlopen narrative telt niet meer mee als actuele
context.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: `app/level_check.py` — periodieke verval-check

**Files:**
- Modify: `app/level_check.py`
- Test: `<scratchpad>/test_narrative_expiry.py`

**Interfaces:**
- Consumes: `repo.list_active_narratives`, `repo.close_narrative` (Task 2);
  `signal_processor.SWING_WATCH_MAX_AGE_DAYS` (bestaand).
- Produces: `check_narratives() -> None`, gewired in `run_all_checks()`.

- [ ] **Step 1: Schrijf de test**

Maak `<scratchpad>/test_narrative_expiry.py`:

```python
import asyncio
import os
import sys
import tempfile
from datetime import datetime, timedelta, timezone

sys.path.insert(0, "/home/user/Trade")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-narrative-expiry-0123456789"

from app import config
config.DATABASE_PATH = db_path

from app import db, level_check, repo

db.init_db()


def make_message(coin: str) -> int:
    with db.session() as conn:
        conn.execute(
            "INSERT INTO messages (received_at, raw_text, category, coin, direction) "
            "VALUES (?, 'test', 'lange_termijn', ?, 'long')",
            (db.now_iso(), coin),
        )
        return conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]


# Vers narrative: mag niet verlopen.
fresh_msg = make_message("FRESH")
fresh_id = repo.create_narrative("FRESH", "long", fresh_msg)

# Oud narrative: langer dan 84 dagen geen update, moet verlopen.
old_msg = make_message("OLD")
old_id = repo.create_narrative("OLD", "long", old_msg)
old_iso = (datetime.now(timezone.utc) - timedelta(days=90)).isoformat()
with db.session() as conn:
    conn.execute("UPDATE coin_narratives SET last_update_at = ? WHERE id = ?", (old_iso, old_id))

asyncio.run(level_check.check_narratives())

assert repo.get_narrative(fresh_id)["status"] == "actief"
assert repo.get_narrative(old_id)["status"] == "verlopen"
print("OK: check_narratives laat een vers narrative actief en laat een oud narrative verlopen")

print("ALLE NARRATIVE-EXPIRY TESTS GESLAAGD")
```

- [ ] **Step 2: Run, verwacht een `AttributeError`**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_narrative_expiry.py`
Expected: `AttributeError: module 'app.level_check' has no attribute 'check_narratives'`

- [ ] **Step 3: Voeg `check_narratives` toe aan `app/level_check.py`**

Voeg toe na de bestaande `check_swing_watches`-functie, vóór `run_all_checks`:

```python
async def check_narratives() -> None:
    """Een narrative zonder nieuwe update in SWING_WATCH_MAX_AGE_DAYS dagen
    verloopt vanzelf. Geen prijs-afhankelijkheid zoals bij swing-watches,
    dus geen candle-fetch nodig: puur een leeftijdscheck."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=SWING_WATCH_MAX_AGE_DAYS)).isoformat()
    narratives = repo.list_active_narratives()
    expired = [n for n in narratives if n["last_update_at"] < cutoff]
    for n in expired:
        repo.close_narrative(n["id"], "verlopen", "geen nieuwe update binnen 84 dagen")
    if expired:
        logger.info("%d narrative(s) verlopen wegens inactiviteit", len(expired))
```

`SWING_WATCH_MAX_AGE_DAYS` staat al in de bestaande top-level import
`from app.signal_processor import (SWING_WATCH_MAX_AGE_DAYS,
_price_broke_through, _price_near_level, run_swing_check)` — hergebruik
die, geen nieuwe of lokale import nodig. De bestaande regel bovenin het
bestand is `from datetime import datetime, timezone` (geen `timedelta`):
wijzig die naar `from datetime import datetime, timedelta, timezone`.

Zoek daarna `run_all_checks` en voeg de nieuwe check toe ná de bestaande
`await check_swing_watches()`-regel:

```python
    await check_swing_watches()
    await check_narratives()
```

- [ ] **Step 4: Run de test opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_narrative_expiry.py`
Expected: de "OK:"-regel, eindigend met "ALLE NARRATIVE-EXPIRY TESTS GESLAAGD".

- [ ] **Step 5: Commit**

```bash
git add app/level_check.py
git commit -m "$(cat <<'EOF'
level_check.py: periodieke verval-check voor narratives

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Coin-pagina — "Lopend verhaal"-sectie

**Files:**
- Modify: `web/main.py`
- Modify: `web/templates/coin.html`
- Test: `<scratchpad>/test_narrative_coin_page.py`

**Interfaces:**
- Consumes: `repo.list_narratives_for_coin`, `repo.list_narrative_messages` (Task 2).

- [ ] **Step 1: Voeg de data toe aan `coin_page` in `web/main.py`**

Zoek de regel `active_swing_watches = repo.active_swing_watches_for_coin(symbol)`
in `coin_page` en voeg direct erna toe:

```python
    coin_narratives = repo.list_narratives_for_coin(symbol)
    for narrative in coin_narratives:
        narrative["timeline"] = repo.list_narrative_messages(narrative["id"])
```

Voeg aan de teruggegeven context-dict toe, na `"active_swing_watches":
active_swing_watches,`:

```python
        "coin_narratives": coin_narratives,
```

- [ ] **Step 2: Voeg de sectie toe aan `web/templates/coin.html`**

Zoek het bestaande `{% if active_swing_watches %}...{% endif %}`-blok (de
"Bewaakt niveau"-sectie) en voeg dit blok er direct NA toe:

```html
{% if coin_narratives %}
<details class="stats-collapse js-accordion" style="--i: 3">
  <summary class="stats-summary">
    <svg class="h2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
    <span>Lopend verhaal</span>
    <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6,9 12,15 18,9"/></svg>
  </summary>
  {% for narrative in coin_narratives %}
  <div class="long-term-item" style="{{ 'opacity: 0.6;' if narrative.status != 'actief' else '' }}">
    <span class="badge badge-{{ narrative.direction }}">{{ narrative.direction }}</span>
    <span class="badge badge-status">{{ narrative.status }}</span>
    <span class="muted mono" style="font-size: 11px;">sinds {{ narrative.opened_at[:10] }} · {{ narrative.message_count }} update{{ 's' if narrative.message_count != 1 else '' }}</span>
    {% if narrative.closed_reason %}<p class="muted" style="font-size: 11px; margin: 4px 0 0;">{{ narrative.closed_reason }}</p>{% endif %}
    {% for entry in narrative.timeline %}
    <p style="font-size: 12px; margin: 6px 0 0;">
      <span class="mono muted">{{ entry.received_at[:10] }}:</span>
      {{ entry.message_summary or entry.raw_text }}
    </p>
    {% endfor %}
  </div>
  {% endfor %}
</details>
{% endif %}
```

- [ ] **Step 3: Schrijf de test**

Maak `<scratchpad>/test_narrative_coin_page.py`:

```python
import os
import sys
import tempfile

sys.path.insert(0, "/home/user/Trade")
sys.path.insert(0, "/home/user/Trade/web")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-narrative-coinpage-0123456789"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path

from app import db, exchange, repo, security

db.init_db()
uid = repo.create_user("narracoinpage", security.hash_password("testpass123"), 1000.0, 1.0, "333")

exchange.market_exists = lambda coin: True
exchange.to_symbol = lambda coin: f"{coin.upper()}/USDT"
exchange.fetch_last_price = lambda coin: 100.0
repo.add_coin_if_new("TAO", "TAO/USDT")

with db.session() as conn:
    conn.execute(
        "INSERT INTO messages (received_at, raw_text, category, coin, direction, message_summary) "
        "VALUES (?, 'Lange termijn TAO gekocht', 'lange_termijn', 'TAO', 'long', 'Voor het eerst TAO ingekocht')",
        (db.now_iso(),),
    )
    msg_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]
repo.create_narrative("TAO", "long", msg_id)

import main as web_main
from fastapi.testclient import TestClient

client = TestClient(web_main.app)
token = security.create_session_token(uid)
client.cookies.set("session", token)

resp = client.get("/coins/TAO")
assert resp.status_code == 200, resp.status_code
assert "Lopend verhaal" in resp.text
assert "Voor het eerst TAO ingekocht" in resp.text
print("OK: coin-pagina toont een actief narrative met zijn tijdlijn")

repo.add_coin_if_new("ETH", "ETH/USDT")
resp2 = client.get("/coins/ETH")
assert "Lopend verhaal" not in resp2.text
print("OK: coin-pagina zonder narrative toont de sectie niet")

print("ALLE NARRATIVE-COIN-PAGINA TESTS GESLAAGD")
```

- [ ] **Step 4: Run, verwacht een gemiste assert (sectie bestaat nog niet)**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_narrative_coin_page.py`
Expected: `AssertionError: assert 'Lopend verhaal' in resp.text` (opgelost door Step 1-2 hierboven).

- [ ] **Step 5: Run opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_narrative_coin_page.py`
Expected: beide "OK:"-regels, eindigend met "ALLE NARRATIVE-COIN-PAGINA TESTS GESLAAGD".

- [ ] **Step 6: Commit**

```bash
git add web/main.py web/templates/coin.html
git commit -m "$(cat <<'EOF'
Coin-pagina: nieuwe sectie "Lopend verhaal"

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Grafiek — markeringen per narrative-update

**Files:**
- Modify: `web/main.py`
- Modify: `web/templates/coin.html`
- Modify: `web/static/coin.js`

**Interfaces:**
- Consumes: `coin_narratives` (context, al opgebouwd in Task 7).

Dit is een puur visuele toevoeging zonder eigen backend-testbaarheid
(client-side rendering op een canvas-achtige chart-library); verificatie
gebeurt handmatig in de browser zoals CLAUDE.md voorschrijft voor
UI-wijzigingen, niet via een scratch-DB-test.

- [ ] **Step 1: Geef de platte lijst berichten mee aan de template**

In `web/main.py`'s `coin_page`, voeg toe direct na het `coin_narratives`-blok
uit Task 7:

```python
    narrative_updates = [
        {"received_at": entry["received_at"], "direction": narrative["direction"]}
        for narrative in coin_narratives
        for entry in narrative["timeline"]
    ]
```

Voeg toe aan de teruggegeven context-dict, na `"coin_narratives":
coin_narratives,`:

```python
        "narrative_updates": narrative_updates,
```

- [ ] **Step 2: Geef de data door aan `coin.js` in `web/templates/coin.html`**

Zoek de regel `const trendlines = {{ trendlines | tojson }};` en voeg
direct erna toe:

```html
  const narrativeUpdates = {{ narrative_updates | tojson }};
```

- [ ] **Step 3: Voeg de marker-logica toe aan `web/static/coin.js`**

Voeg toe direct na de regel `const candleSeries = chart.addCandlestickSeries({`
's afsluitende `});` (dus vlak bij waar `candleSeries` voor het eerst
gedeclareerd wordt, zodat de variabele in dezelfde scope leeft als
`stopDrawing()` verderop in het bestand):

```javascript
  // Kleine gekleurde puntjes op het moment van elke lange-termijn
  // narrative-update, zodat een langere geschiedenis van berichten over
  // deze coin ook op de prijsgrafiek zelf te volgen is. Apart bijgehouden
  // (niet steeds opnieuw uit candleSeries gelezen) omdat stopDrawing()
  // verderop candleSeries.setMarkers([]) aanroept om zijn eigen tijdelijke
  // teken-marker weg te halen — die moet deze markers herstellen, niet
  // leegmaken.
  let narrativeMarkers = [];

  function nearestCandleTime(candles, unixSeconds) {
    let best = candles[0].time;
    let bestDiff = Math.abs(candles[0].time - unixSeconds);
    for (const c of candles) {
      const diff = Math.abs(c.time - unixSeconds);
      if (diff < bestDiff) { best = c.time; bestDiff = diff; }
    }
    return best;
  }
```

Voeg toe in de `fetch(\`/api/candles/${SYMBOL}\`)`-callback, direct vóór
`chart.timeScale().fitContent();`:

```javascript
      if (narrativeUpdates.length && data.candles.length) {
        narrativeMarkers = narrativeUpdates.map((u) => ({
          time: nearestCandleTime(data.candles, Math.floor(new Date(u.received_at).getTime() / 1000)),
          position: "aboveBar",
          color: u.direction === "long" ? "#33d69f" : "#f2685c",
          shape: "circle",
          text: u.direction === "long" ? "L" : "S",
        }));
        candleSeries.setMarkers(narrativeMarkers);
      }
```

Zoek tot slot `function stopDrawing()` en vervang de regel
`candleSeries.setMarkers([]);` door:

```javascript
      candleSeries.setMarkers(narrativeMarkers);
```

(De tijdelijke "punt 1"-marker tijdens het tekenen van een trendlijn moet
nog steeds verdwijnen zodra je stopt met tekenen, maar mag de
narrative-markeringen niet blijvend wegvegen — dit herstelt ze in plaats
van de lijst leeg te maken.)

- [ ] **Step 4: Handmatig verifiëren in de browser**

```bash
DATABASE_PATH=/tmp/narrative_ui_check.db JWT_SECRET=test-secret-narrative-ui-0123456789012345 \
  uvicorn web.main:app --reload
```

Maak via een Python-shell (of hergebruik `test_narrative_coin_page.py`'s
opzet) een gebruiker en een narrative met minstens twee tijdlijn-items voor
een coin, log in via de browser, open de coin-pagina, en controleer:
- De "Lopend verhaal"-sectie toont de juiste richting, datum, en
  tijdlijn-tekst.
- Op de prijsgrafiek staan gekleurde puntjes (groen voor long, rood voor
  short) rond de juiste candles.
- Klik op de teken-trendlijn-knop, teken een punt, klik nogmaals om te
  annuleren (of gebruik de eigen annuleerknop): de narrative-puntjes op de
  grafiek moeten na het annuleren nog steeds zichtbaar zijn, niet
  verdwenen.

- [ ] **Step 5: Commit**

```bash
git add web/main.py web/templates/coin.html web/static/coin.js
git commit -m "$(cat <<'EOF'
Grafiek: gekleurde markeringen per narrative-update

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
EOF
)"
```

---

## Self-Review

**Spec coverage:**
- Aanleiding/kernprobleem (geen samenhang tussen berichten) → Task 3
  (matching-logica). ✓
- `coin_narratives` + `messages.narrative_id` + `narrative_notifications`
  → Task 1. ✓
- Drie-takken matching (update/tegenspraak/nieuw) → Task 3. ✓
- Telegram: edit-binnen-48u / verse melding na falen / tegenspraak altijd
  apart → Task 4. ✓
- 84-dagen verval → Task 6. ✓
- Day-trading crossover via `_build_context_note` → Task 5. ✓
- Coin-pagina sectie → Task 7. ✓
- Grafiek-markeringen → Task 8. ✓
- Niet-doelen (geen backfill, geen wijziging risico/positiegrootte, blijft
  gescheiden van swing-watches) → geen enkele taak raakt
  `journal_entries`, `risk.py`, of `swing_watches`-code; geen backfill-taak
  opgenomen. ✓

**Placeholder scan:** geen "TBD"/"implement later"/ongeschreven testcode
gevonden bij het doorlopen van elke taak.

**Type-consistentie:** `evaluate_narrative(message_id, coin, direction,
message_summary)` (Task 3) wordt exact zo aangeroepen vanuit
`handle_message` (Task 3, Step 5). `send_narrative_update`'s signatuur is
identiek tussen de stub (Task 3) en de echte implementatie (Task 4), en
identiek aan hoe `_send_narrative_notifications` (Task 3) hem aanroept.
`repo.list_narratives_for_coin`/`list_narrative_messages` (Task 2) worden
met dezelfde namen en vorm gebruikt in Task 7 en Task 8. Geen kolom- of
functienaam wijkt af tussen de taak die hem definieert en de taken die hem
gebruiken.
