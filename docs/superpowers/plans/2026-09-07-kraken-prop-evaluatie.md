# Kraken Prop evaluatie simulator Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Een virtuele Kraken Prop-achtige evaluatie toevoegen aan HesPulse, bovenop de bestaande oefentrade-functie, met dezelfde dagverlies-, drawdown- en winstdoel-regels, zodat een gebruiker kan testen of zijn discipline en signalen die zouden overleven voordat hij er geld aan uitgeeft.

**Architecture:** Een nieuwe tabel `prop_evaluations` houdt per gebruiker hoogstens één actieve run bij; een nieuwe, nullable `journal_entries.evaluation_id`-kolom koppelt oefentrades aan de run die op dat moment actief was. Alle rekenlogica (handelsdag-grens, drawdown/dagverlies/winstdoel-checks) zit in één pure functie in `risk.py`, zonder databasetoegang, zodat hij los van de rest te testen is. Het bestaande sluiten van een oefentrade triggert die functie en persisteert het resultaat via `repo.py`. De UI hergebruikt bestaande, aan echte waarden gekoppelde animatie-componenten (`risk-gauge`, `risk-pulse`, `flash-up`/`flash-down`, `heat-cell`) en voegt één nieuw, eenmalig geslaagd/mislukt-reveal toe via hetzelfde URL-vlag-patroon als de bestaande winst-confetti.

**Tech Stack:** Python 3, FastAPI, Jinja2, SQLite (WAL), vanilla JS/CSS (geen framework, geen GSAP — dit project gebruikt uitsluitend CSS-animaties en kleine class-toggles).

**Spec:** `docs/superpowers/specs/2026-09-07-kraken-prop-evaluatie-design.md`

## Global Constraints

- Schema-wijzigingen zijn tweedelig: nieuwe tabel via `CREATE TABLE IF NOT EXISTS` in `app/schema.sql`; nieuwe kolom op een bestaande tabel via schema.sql (fresh database) ÉN een idempotente `ALTER TABLE ... ADD COLUMN` met `PRAGMA table_info`-guard in `app/db.py:_migrate()` (bestaande database) — schema.sql alleen bereikt nooit een database die de tabel al heeft.
- Een index op een kolom die pas in `_migrate()` wordt toegevoegd hoort ook in `_migrate()` zelf, ná de kolom-ALTER, nooit in schema.sql.
- Databasetoegang uitsluitend via `app/repo.py`, nooit losse SQL elders.
- Een oefentrade (`signals.is_practice = 1`) mag nooit het echte `portfolio_eur` of de echte winrate-statistieken raken — dat blijft ongewijzigd. De evaluatie-boekhouding is een volledig aparte, virtuele laag bovenop die bestaande garantie.
- `max_daily_loss_pct` ligt vast op 3.0 (bevestigde Kraken-regel); `profit_target_pct` en `max_drawdown_pct` zijn door de gebruiker gekozen bij het starten (niet bevestigd per Kraken-tier).
- Handelsdag-grens: 00:30 UTC, exact zoals Kraken. Op precies één plek geïmplementeerd (`risk.trading_day_label`), nergens anders gedupliceerd.
- Geen pytest-suite in dit project: elke Python-wijziging krijgt een los testscript tegen een tijdelijke SQLite-database, met `assert` + `print("OK: ...")`.
- Decoratieve motion is altijd gekoppeld aan een echte, live waarde en respecteert `prefers-reduced-motion` — nooit puur decoratief. Hergebruik bestaande componenten (`risk-gauge`/`risk-mid`/`risk-high`, `risk-pulse`, `flash-up`/`flash-down`, `heat-cell`) waar mogelijk in plaats van nieuwe animaties te verzinnen; het enige nieuwe stukje CSS is het eenmalige geslaagd/mislukt-reveal, met een eindig aantal iteraties (geen `infinite`) en een `prefers-reduced-motion`-eindstaat.

---

### Task 1: `risk.py` — handelsdag-grens en de pure evaluatiefunctie

**Files:**
- Modify: `app/risk.py`
- Test: `<scratchpad>/test_risk_prop_progress.py`

**Interfaces:**
- Produces: `risk.trading_day_label(dt: datetime) -> str`, `risk.PropProgress` (dataclass met `current_balance: float, day_start_balance: float, day_start_date: str, status: str, closed_reason: Optional[str]`), `risk.evaluate_prop_progress(evaluation: dict, result_eur: float, closed_at: datetime) -> PropProgress`. `evaluation` is een dict met minimaal de sleutels `tier_amount`, `profit_target_pct`, `max_daily_loss_pct`, `max_drawdown_pct`, `current_balance`, `day_start_balance`, `day_start_date` — exact de kolomnamen van de `prop_evaluations`-tabel uit Task 2, zodat een `repo.get_active_evaluation(...)`-resultaat hier direct in past.

Dit is de kern-rekenlogica, zonder enige databasetoegang, zodat hij volledig met losse scenario's te testen is. Task 2 (schema + repo) hergebruikt `trading_day_label` voor zowel het aanmaken van een run als voor het groeperen van dagresultaten — vandaar dat deze taak eerst komt.

- [ ] **Step 1: Voeg de imports en de handelsdag-grens toe aan `app/risk.py`**

Bovenaan het bestand staat nu `from dataclasses import dataclass` en `from typing import Optional`. Voeg de datetime-import toe:

```python
from datetime import datetime, timedelta
```

Voeg toe, ergens na de bestaande constanten (`RISK_REWARD_RATIO = 2.0`):

```python
def trading_day_label(dt: datetime) -> str:
    """Het handelsdag-label (YYYY-MM-DD) voor een UTC-tijdstip, met dezelfde
    00:30 UTC-grens als Kraken's eigen dagverlies-reset: vóór 00:30 UTC
    hoort een tijdstip nog bij de vorige kalenderdag. Op precies deze ene
    plek geïmplementeerd, alle evaluatie-code hergebruikt hem in plaats van
    de grens ergens anders opnieuw te berekenen."""
    if dt.hour == 0 and dt.minute < 30:
        dt = dt - timedelta(days=1)
    return dt.date().isoformat()
```

- [ ] **Step 2: Voeg de `PropProgress`-dataclass en `evaluate_prop_progress` toe**

```python
@dataclass
class PropProgress:
    current_balance: float
    day_start_balance: float
    day_start_date: str
    status: str
    closed_reason: Optional[str]


def evaluate_prop_progress(evaluation: dict, result_eur: float, closed_at: datetime) -> PropProgress:
    """Verwerkt het resultaat van één aan een evaluatie-run gekoppelde
    trade: past het virtuele saldo aan, reset de dagverlies-referentie bij
    een nieuwe handelsdag, en bepaalt of de run daarmee geslaagd of
    mislukt is. Drawdown wordt vóór dagverlies gecheckt: een verlies dat
    allebei zou raken telt als de ernstigere, nooit-resettende drawdown-
    overtreding, niet als een dagverlies dat morgen weer op nul begint."""
    today_label = trading_day_label(closed_at)
    day_start_balance = evaluation["day_start_balance"]
    day_start_date = evaluation["day_start_date"]
    if today_label != day_start_date:
        day_start_balance = evaluation["current_balance"]
        day_start_date = today_label

    current_balance = evaluation["current_balance"] + result_eur
    tier_amount = evaluation["tier_amount"]

    status = "actief"
    closed_reason = None
    if current_balance <= tier_amount * (1 - evaluation["max_drawdown_pct"] / 100):
        status, closed_reason = "mislukt", "maximale drawdown geraakt"
    elif current_balance <= day_start_balance * (1 - evaluation["max_daily_loss_pct"] / 100):
        status, closed_reason = "mislukt", "maximaal dagverlies geraakt"
    elif current_balance >= tier_amount * (1 + evaluation["profit_target_pct"] / 100):
        status, closed_reason = "geslaagd", "winstdoel gehaald"

    return PropProgress(
        current_balance=current_balance, day_start_balance=day_start_balance,
        day_start_date=day_start_date, status=status, closed_reason=closed_reason,
    )
```

- [ ] **Step 3: Schrijf de test in de scratchpad-directory**

Maak `<scratchpad>/test_risk_prop_progress.py` (gebruik het echte scratchpad-pad, niet een letterlijke map genaamd `<scratchpad>`):

```python
import sys
from datetime import datetime, timezone
sys.path.insert(0, "/home/user/Trade")

from app import risk

# --- trading_day_label ---
assert risk.trading_day_label(datetime(2026, 9, 7, 12, 0, tzinfo=timezone.utc)) == "2026-09-07"
assert risk.trading_day_label(datetime(2026, 9, 7, 0, 29, tzinfo=timezone.utc)) == "2026-09-06"
assert risk.trading_day_label(datetime(2026, 9, 7, 0, 30, tzinfo=timezone.utc)) == "2026-09-07"
assert risk.trading_day_label(datetime(2026, 9, 7, 0, 0, tzinfo=timezone.utc)) == "2026-09-06"
print("OK: trading_day_label legt de 00:30 UTC-grens correct")

base_evaluation = {
    "tier_amount": 10000.0,
    "profit_target_pct": 8.0,
    "max_daily_loss_pct": 3.0,
    "max_drawdown_pct": 6.0,
    "current_balance": 10000.0,
    "day_start_balance": 10000.0,
    "day_start_date": "2026-09-07",
}

# 1. Normale winst, geen limiet geraakt, geen dagreset.
result = risk.evaluate_prop_progress(base_evaluation, 200.0, datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc))
assert result.status == "actief" and result.closed_reason is None
assert result.current_balance == 10200.0
assert result.day_start_balance == 10000.0 and result.day_start_date == "2026-09-07"
print("OK: normale winst blijft actief, geen dagreset")

# 2. Dagverlies exact geraakt (3% van 10000 = 300).
result = risk.evaluate_prop_progress(base_evaluation, -300.0, datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc))
assert result.status == "mislukt" and result.closed_reason == "maximaal dagverlies geraakt"
print("OK: exact op de dagverlieslimiet telt als geraakt")

# 3. Drawdown geraakt (6% van 10000 = 600); dit verlies zou ook het
# dagverlies raken (day_start_balance ligt hier lager, op 9800), maar de
# drawdown-check moet voorrang krijgen.
evaluation_far_in_day = dict(base_evaluation, current_balance=9800.0, day_start_balance=9800.0)
result = risk.evaluate_prop_progress(evaluation_far_in_day, -6000.0, datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc))
assert result.status == "mislukt" and result.closed_reason == "maximale drawdown geraakt"
print("OK: drawdown-check heeft voorrang op dagverlies-check")

# 4. Winstdoel exact gehaald (8% van 10000 = 800).
result = risk.evaluate_prop_progress(base_evaluation, 800.0, datetime(2026, 9, 7, 14, 0, tzinfo=timezone.utc))
assert result.status == "geslaagd" and result.closed_reason == "winstdoel gehaald"
print("OK: winstdoel exact gehaald telt als geslaagd")

# 5. Nieuwe handelsdag: day_start_balance reset naar het saldo van vóór
# dit resultaat, niet naar het nieuwe saldo erna.
evaluation_prev_day = dict(base_evaluation, current_balance=10200.0, day_start_balance=10000.0, day_start_date="2026-09-07")
result = risk.evaluate_prop_progress(evaluation_prev_day, -100.0, datetime(2026, 9, 8, 10, 0, tzinfo=timezone.utc))
assert result.day_start_date == "2026-09-08"
assert result.day_start_balance == 10200.0
assert result.current_balance == 10100.0
assert result.status == "actief"
print("OK: nieuwe handelsdag reset day_start_balance naar het saldo van vóór dit resultaat")

# 6. Grensgeval: 00:15 UTC hoort nog bij de vorige handelsdag, dus geen
# premature reset als day_start_date die vorige dag al is.
evaluation_same_day = dict(base_evaluation, day_start_date="2026-09-06")
result = risk.evaluate_prop_progress(evaluation_same_day, -50.0, datetime(2026, 9, 7, 0, 15, tzinfo=timezone.utc))
assert result.day_start_date == "2026-09-06"
assert result.day_start_balance == 10000.0
print("OK: 00:15 UTC hoort nog bij de vorige handelsdag, geen premature reset")

print("ALLE RISK.EVALUATE_PROP_PROGRESS TESTS GESLAAGD")
```

- [ ] **Step 4: Run, verwacht een `AttributeError` (functies bestaan nog niet)**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_risk_prop_progress.py`
Expected: `AttributeError: module 'app.risk' has no attribute 'trading_day_label'`, opgelost door Step 1-2.

- [ ] **Step 5: Run opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_risk_prop_progress.py`
Expected: alle 8 "OK:"-regels, eindigend met "ALLE RISK.EVALUATE_PROP_PROGRESS TESTS GESLAAGD".

- [ ] **Step 6: Commit**

```bash
git add app/risk.py
git commit -m "$(cat <<'EOF'
risk.py: pure evaluatiefunctie voor de Kraken Prop-simulatie

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

### Task 2: Schema + migratie + basis repo-CRUD voor `prop_evaluations`

**Files:**
- Modify: `app/schema.sql`
- Modify: `app/db.py`
- Modify: `app/repo.py`
- Test: `<scratchpad>/test_prop_evaluations_schema.py`

**Interfaces:**
- Consumes: `risk.trading_day_label` (Task 1).
- Produces: `repo.create_evaluation(user_id, tier_amount, profit_target_pct, max_drawdown_pct) -> int`, `repo.get_active_evaluation(user_id) -> Optional[dict]`, `repo.get_evaluation(evaluation_id) -> Optional[dict]`, `repo.list_evaluations_for_user(user_id) -> list[dict]`, `repo.update_evaluation_state(evaluation_id, current_balance, day_start_balance, day_start_date) -> None`, `repo.close_evaluation(evaluation_id, status, closed_reason) -> None`.

- [ ] **Step 1: Voeg de nieuwe tabel toe aan `app/schema.sql`**

Zoek de regel `CREATE TABLE IF NOT EXISTS settings (` en voeg er direct VÓÓR toe:

```sql
-- Eén virtuele Kraken Prop-achtige evaluatie: een gebruiker test zijn
-- eigen discipline en HesPulse's signalen tegen dezelfde dagverlies-,
-- drawdown- en winstdoel-regels als een echte evaluatie, zonder geld uit
-- te geven. Zie de spec voor de volledige regels. Hoogstens één rij per
-- gebruiker met status 'actief' (bewaakt door de webroute, niet door een
-- database-constraint, zelfde patroon als coin_narratives).
CREATE TABLE IF NOT EXISTS prop_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    tier_amount REAL NOT NULL,
    profit_target_pct REAL NOT NULL,
    max_daily_loss_pct REAL NOT NULL DEFAULT 3.0,
    max_drawdown_pct REAL NOT NULL,
    current_balance REAL NOT NULL,
    day_start_balance REAL NOT NULL,
    day_start_date TEXT NOT NULL,
    -- actief/geslaagd/mislukt/gestopt, zie de spec.
    status TEXT NOT NULL DEFAULT 'actief',
    closed_reason TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_prop_evaluations_user_status ON prop_evaluations(user_id, status);

```

- [ ] **Step 2: Voeg de kolom + migratie toe aan `app/db.py`**

Zoek in `_migrate()` het blok:

```python
    existing_journal = {row["name"] for row in conn.execute("PRAGMA table_info(journal_entries)")}
    if "stop_loss_override" not in existing_journal:
        conn.execute("ALTER TABLE journal_entries ADD COLUMN stop_loss_override REAL")
    if "take_profit_override" not in existing_journal:
        conn.execute("ALTER TABLE journal_entries ADD COLUMN take_profit_override REAL")
    if "position_size_override" not in existing_journal:
        conn.execute("ALTER TABLE journal_entries ADD COLUMN position_size_override REAL")
```

Voeg er direct na toe:

```python
    if "evaluation_id" not in existing_journal:
        conn.execute("ALTER TABLE journal_entries ADD COLUMN evaluation_id INTEGER REFERENCES prop_evaluations(id)")
    # Index hier, nooit in schema.sql: op een bestaande database zonder de
    # kolom hierboven zou die CREATE INDEX meteen crashen, zie het
    # narrative_id-precedent verderop in dit bestand.
    conn.execute("CREATE INDEX IF NOT EXISTS idx_journal_evaluation_id ON journal_entries(evaluation_id)")
```

- [ ] **Step 3: Voeg de repo-functies toe aan `app/repo.py`**

Voeg toe aan het einde van het bestand (na de laatste functie):

```python
# ---------------------------------------------------------------------------
# Kraken Prop-achtige evaluatie simulatie
# ---------------------------------------------------------------------------

def create_evaluation(
    user_id: int, tier_amount: float, profit_target_pct: float, max_drawdown_pct: float,
) -> int:
    """Nieuwe evaluatie-run, status 'actief', saldo begint op tier_amount.
    De aanroeper (web/main.py) controleert dat de gebruiker nog geen
    actieve run heeft — dezelfde verantwoordelijkheidsverdeling als
    evaluate_narrative's 'hoogstens één actief narrative per coin'."""
    now = db.now_iso()
    today_label = risk.trading_day_label(datetime.now(timezone.utc))
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO prop_evaluations
               (user_id, tier_amount, profit_target_pct, max_drawdown_pct,
                current_balance, day_start_balance, day_start_date, started_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, tier_amount, profit_target_pct, max_drawdown_pct,
             tier_amount, tier_amount, today_label, now),
        )
        return cur.lastrowid


def get_active_evaluation(user_id: int) -> Optional[dict]:
    with db.session() as conn:
        row = conn.execute(
            "SELECT * FROM prop_evaluations WHERE user_id = ? AND status = 'actief' ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def get_evaluation(evaluation_id: int) -> Optional[dict]:
    with db.session() as conn:
        row = conn.execute("SELECT * FROM prop_evaluations WHERE id = ?", (evaluation_id,)).fetchone()
        return dict(row) if row else None


def list_evaluations_for_user(user_id: int) -> list[dict]:
    """Geschiedenis voor het dashboard, nieuwste eerst."""
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM prop_evaluations WHERE user_id = ? ORDER BY started_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def update_evaluation_state(
    evaluation_id: int, current_balance: float, day_start_balance: float, day_start_date: str,
) -> None:
    with db.session() as conn:
        conn.execute(
            """UPDATE prop_evaluations
               SET current_balance = ?, day_start_balance = ?, day_start_date = ?
               WHERE id = ?""",
            (current_balance, day_start_balance, day_start_date, evaluation_id),
        )


def close_evaluation(evaluation_id: int, status: str, closed_reason: str) -> None:
    with db.session() as conn:
        conn.execute(
            "UPDATE prop_evaluations SET status = ?, closed_reason = ?, ended_at = ? WHERE id = ?",
            (status, closed_reason, db.now_iso(), evaluation_id),
        )
```

Voeg `risk` toe aan de imports bovenaan `app/repo.py` (nu `from app import config, db`):

```python
from app import config, db, risk
```

- [ ] **Step 4: Schrijf de test in de scratchpad-directory**

Maak `<scratchpad>/test_prop_evaluations_schema.py`:

```python
import os
import sys
import sqlite3
import tempfile

sys.path.insert(0, "/home/user/Trade")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-prop-eval-schema-0123456789012345"

from app import config
config.DATABASE_PATH = db_path

# Simuleer een database van vóór deze feature: journal_entries bestaat al,
# zonder evaluation_id, om de migratie zelf te toetsen.
conn = sqlite3.connect(db_path)
conn.execute("""
CREATE TABLE journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL,
    user_id INTEGER NOT NULL,
    risk_eur REAL,
    telegram_sent INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'nieuw',
    entry_price REAL, exit_price REAL, exit_time TEXT,
    result_eur REAL, result_pct REAL, note TEXT,
    level_alert_sent INTEGER NOT NULL DEFAULT 0, created_at TEXT NOT NULL,
    stop_loss_override REAL, take_profit_override REAL, position_size_override REAL
)
""")
conn.commit()
conn.close()

from app import db
db.init_db()

with db.session() as conn:
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(journal_entries)")}
    assert "evaluation_id" in cols, "evaluation_id kolom ontbreekt na migratie"
    indexes = {row["name"] for row in conn.execute("PRAGMA index_list(journal_entries)")}
    assert "idx_journal_evaluation_id" in indexes, f"index ontbreekt, gevonden: {indexes}"
    tables = {row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "prop_evaluations" in tables
print("OK: migratie voegt evaluation_id kolom + index toe op een bestaande database, en de nieuwe tabel bestaat")

db.init_db()
print("OK: migratie is idempotent (tweede run crasht niet)")

from app import repo, security
uid = repo.create_user("propevaluser", security.hash_password("testpass123"), 1000.0, 1.0, "777")

assert repo.get_active_evaluation(uid) is None
eval_id = repo.create_evaluation(uid, tier_amount=10000.0, profit_target_pct=8.0, max_drawdown_pct=6.0)
active = repo.get_active_evaluation(uid)
assert active is not None and active["id"] == eval_id
assert active["current_balance"] == 10000.0
assert active["day_start_balance"] == 10000.0
assert active["max_daily_loss_pct"] == 3.0
assert active["status"] == "actief"
print("OK: create_evaluation + get_active_evaluation")

fetched = repo.get_evaluation(eval_id)
assert fetched["tier_amount"] == 10000.0
print("OK: get_evaluation")

repo.update_evaluation_state(eval_id, current_balance=10200.0, day_start_balance=10200.0, day_start_date="2026-09-08")
refreshed = repo.get_evaluation(eval_id)
assert refreshed["current_balance"] == 10200.0
assert refreshed["day_start_date"] == "2026-09-08"
print("OK: update_evaluation_state")

repo.close_evaluation(eval_id, "geslaagd", "winstdoel gehaald")
closed = repo.get_evaluation(eval_id)
assert closed["status"] == "geslaagd"
assert closed["closed_reason"] == "winstdoel gehaald"
assert closed["ended_at"] is not None
assert repo.get_active_evaluation(uid) is None
print("OK: close_evaluation, en get_active_evaluation vindt daarna niks meer")

history = repo.list_evaluations_for_user(uid)
assert len(history) == 1 and history[0]["id"] == eval_id
print("OK: list_evaluations_for_user")

print("ALLE PROP_EVALUATIONS SCHEMA+REPO TESTS GESLAAGD")
```

- [ ] **Step 5: Run, verwacht een gemiste assert of `AttributeError`**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_prop_evaluations_schema.py`
Expected: faalt vóór Step 1-3, opgelost daarna.

- [ ] **Step 6: Run opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_prop_evaluations_schema.py`
Expected: alle 7 "OK:"-regels, eindigend met "ALLE PROP_EVALUATIONS SCHEMA+REPO TESTS GESLAAGD".

- [ ] **Step 7: Commit**

```bash
git add app/schema.sql app/db.py app/repo.py
git commit -m "$(cat <<'EOF'
Schema + repo: prop_evaluations tabel en basis-CRUD

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

### Task 3: `journal_entries` koppelen aan een evaluatie-run

**Files:**
- Modify: `app/repo.py`
- Test: `<scratchpad>/test_prop_eval_journal_wiring.py`

**Interfaces:**
- Consumes: `risk.trading_day_label` (Task 1), `repo.create_evaluation` (Task 2).
- Produces: `repo.create_journal_entry(signal_id, user_id, risk_eur, evaluation_id=None) -> int` (uitgebreide signatuur), `repo.close_journal_trade(entry_id, user_id, exit_price, exit_time) -> tuple[float, bool, Optional[int]]` (3-tuple in plaats van 2-tuple), `repo.list_evaluation_daily_results(evaluation_id) -> list[dict]` (elk item: `{"date": str, "value": float}`).

Dit is de enige taak die een bestaande, al gebruikte functie-signatuur wijzigt (`close_journal_trade`); de andere taken raken alleen nieuwe code. `close_journal_trade` heeft precies één aanroeper in de codebase (`web/main.py`'s `/journal/{entry_id}/close`-route), die in Task 4 wordt bijgewerkt.

- [ ] **Step 1: Voeg `evaluation_id` toe aan `_JOURNAL_SELECT`**

Zoek in `app/repo.py`:

```python
_JOURNAL_SELECT = """
    SELECT
        je.id AS id, je.signal_id AS signal_id, je.user_id AS user_id,
        je.risk_eur AS risk_eur, je.telegram_sent AS telegram_sent,
        je.status AS status, je.entry_price AS entry_price,
        je.exit_price AS exit_price, je.exit_time AS exit_time,
        je.result_eur AS result_eur, je.result_pct AS result_pct,
        je.note AS note,
        je.position_size_override AS position_size_override,
```

Voeg direct na `je.position_size_override AS position_size_override,` toe:

```python
        je.evaluation_id AS evaluation_id,
```

- [ ] **Step 2: Breid `create_journal_entry` uit met een optioneel `evaluation_id`**

Zoek:

```python
def create_journal_entry(signal_id: int, user_id: int, risk_eur: float) -> int:
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO journal_entries (signal_id, user_id, risk_eur, created_at)
               VALUES (?, ?, ?, ?)""",
            (signal_id, user_id, risk_eur, db.now_iso()),
        )
        return cur.lastrowid
```

Vervang door:

```python
def create_journal_entry(
    signal_id: int, user_id: int, risk_eur: float, evaluation_id: Optional[int] = None,
) -> int:
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO journal_entries (signal_id, user_id, risk_eur, created_at, evaluation_id)
               VALUES (?, ?, ?, ?, ?)""",
            (signal_id, user_id, risk_eur, db.now_iso(), evaluation_id),
        )
        return cur.lastrowid
```

- [ ] **Step 3: Laat `close_journal_trade` een 3-tuple teruggeven**

Zoek de laatste regel van `close_journal_trade`:

```python
    return result_eur, bool(entry["is_practice"])
```

Vervang door:

```python
    return result_eur, bool(entry["is_practice"]), entry["evaluation_id"]
```

Werk ook de docstring van de functie bij (was: `"""Sluit de trade af en geeft (result_eur, is_practice) terug, ...`) naar:

```python
    """Sluit de trade af en geeft (result_eur, is_practice, evaluation_id)
    terug: is_practice bepaalt of dit voor de winst-confetti telt,
    evaluation_id (kan None zijn) vertelt de caller of dit resultaat nog op
    een lopende evaluatie-simulatie moet worden bijgeschreven."""
```

- [ ] **Step 4: Voeg `list_evaluation_daily_results` toe**

Voeg toe direct na `close_evaluation` (Task 2):

```python
def list_evaluation_daily_results(evaluation_id: int) -> list[dict]:
    """Netto resultaat per handelsdag voor deze run, oudste eerst. Voedt de
    dag-stippen op het dashboard. Groepeert met risk.trading_day_label,
    dezelfde functie als evaluate_prop_progress gebruikt, zodat een trade
    nooit op een andere dag in de heatmap staat dan in de saldo-
    berekening zelf."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT exit_time, result_eur FROM journal_entries
               WHERE evaluation_id = ? AND exit_price IS NOT NULL
               ORDER BY exit_time""",
            (evaluation_id,),
        ).fetchall()
    daily: dict[str, float] = {}
    for row in rows:
        label = risk.trading_day_label(datetime.fromisoformat(row["exit_time"]))
        daily[label] = daily.get(label, 0.0) + (row["result_eur"] or 0.0)
    return [{"date": date, "value": value} for date, value in sorted(daily.items())]
```

- [ ] **Step 5: Schrijf de test in de scratchpad-directory**

Maak `<scratchpad>/test_prop_eval_journal_wiring.py`:

```python
import os
import sys
import tempfile

sys.path.insert(0, "/home/user/Trade")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-prop-eval-wiring-0123456789012345"

from app import config
config.DATABASE_PATH = db_path
from app import db, repo, security

db.init_db()

uid = repo.create_user("propwiringuser", security.hash_password("testpass123"), 1000.0, 1.0, "778")
eval_id = repo.create_evaluation(uid, tier_amount=10000.0, profit_target_pct=8.0, max_drawdown_pct=6.0)

with db.session() as conn:
    conn.execute("INSERT INTO messages (received_at, raw_text) VALUES (?, 'test')", (db.now_iso(),))
    msg_id = conn.execute("SELECT last_insert_rowid() AS id").fetchone()["id"]

def _insert_signal():
    return repo.insert_signal({
        "message_id": msg_id, "coin": "TAO", "direction": "long", "category": "oefening",
        "price": 100.0, "rsi": 50, "macd": 0, "macd_signal": 0, "volume_ratio": 1,
        "ema9": 100, "ema21": 100, "atr": 5, "atr_avg20": 5, "adx": 20,
        "technical_confirmed": 1, "confidence": "hoog vertrouwen", "reason": "test",
        "stop_loss": 90.0, "take_profit": 120.0, "context_note": None,
        "is_practice": 1, "plain_explanation": None,
    })

signal_id = _insert_signal()
entry_id = repo.create_journal_entry(signal_id, uid, risk_eur=100.0, evaluation_id=eval_id)
entry = repo.get_journal_entry(entry_id, uid)
assert entry["evaluation_id"] == eval_id
print("OK: create_journal_entry slaat evaluation_id op, _JOURNAL_SELECT geeft hem terug")

repo.update_journal_status(entry_id, uid, "genomen", entry_price=100.0)
result_eur, is_practice, returned_eval_id = repo.close_journal_trade(entry_id, uid, 110.0, db.now_iso())
assert is_practice is True
assert returned_eval_id == eval_id
print(f"OK: close_journal_trade geeft een 3-tuple terug, evaluation_id klopt (result_eur={result_eur})")

daily = repo.list_evaluation_daily_results(eval_id)
assert len(daily) == 1
assert daily[0]["value"] == result_eur
print("OK: list_evaluation_daily_results groepeert het resultaat op de juiste handelsdag")

# Een oefentrade zonder actieve evaluatie moet gewoon evaluation_id=None
# blijven, geen regressie voor de bestaande, ongekoppelde oefentrades.
signal_id2 = _insert_signal()
entry_id2 = repo.create_journal_entry(signal_id2, uid, risk_eur=100.0)
entry2 = repo.get_journal_entry(entry_id2, uid)
assert entry2["evaluation_id"] is None
print("OK: create_journal_entry zonder evaluation_id blijft None")

print("ALLE REPO-WIRING TESTS GESLAAGD")
```

- [ ] **Step 6: Run, verwacht een gemiste assert (evaluation_id ontbreekt nog)**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_prop_eval_journal_wiring.py`
Expected: `KeyError: 'evaluation_id'`, opgelost door Step 1-4.

- [ ] **Step 7: Run opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_prop_eval_journal_wiring.py`
Expected: alle 4 "OK:"-regels, eindigend met "ALLE REPO-WIRING TESTS GESLAAGD".

- [ ] **Step 8: Commit**

```bash
git add app/repo.py
git commit -m "$(cat <<'EOF'
repo.py: journal_entries koppelen aan een evaluatie-run

close_journal_trade geeft nu (result_eur, is_practice, evaluation_id)
terug in plaats van een 2-tuple; de enige aanroeper wordt in de
volgende taak bijgewerkt.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

### Task 4: `web/main.py` — routes bedraden

**Files:**
- Modify: `web/main.py`
- Test: `<scratchpad>/test_prop_eval_routes.py`

**Interfaces:**
- Consumes: `repo.get_active_evaluation`, `repo.create_evaluation`, `repo.close_evaluation`, `repo.get_evaluation`, `repo.update_evaluation_state`, `repo.list_evaluations_for_user`, `repo.list_evaluation_daily_results` (Task 2/3), `risk.evaluate_prop_progress`, `risk.trading_day_label` (Task 1), `repo.close_journal_trade`'s nieuwe 3-tuple return (Task 3).
- Produces: `POST /evaluatie/start`, `POST /evaluatie/stop`; dashboard-route (`GET /dashboard`) krijgt extra context-sleutels `active_evaluation`, `eval_history`, `eval_day_number`, `eval_daily_loss_used_pct`, `eval_drawdown_used_pct`, `eval_profit_progress_pct`, `eval_daily_results` (elk item `{"date": str, "value": float, "level": int}`); de bestaande `close_journal`-route krijgt de query-vlaggen `evaluatie_geslaagd=1` / `evaluatie_mislukt=1` / `eval_flash=up|down`, gebruikt door Task 5's client-side reveal.

- [ ] **Step 1: Werk de `/journal/{entry_id}/close`-route bij**

Zoek in `web/main.py`:

```python
@app.post("/journal/{entry_id}/close")
async def close_journal(
    entry_id: int,
    exit_price: float = Form(...),
    exit_time: str = Form(...),
    next: str = Form(""),
    user: dict = Depends(require_login),
):
    won = False
    try:
        result_eur, is_practice = repo.close_journal_trade(entry_id, user["id"], exit_price, exit_time)
        won = (not is_practice) and result_eur > 0
    except ValueError:
        # Geen eigen entry gevonden (niet van deze gebruiker, of nog geen
        # entry prijs ingevuld). Stil negeren, niets om te sluiten.
        pass
    target = _safe_next(next)
    if won:
        # Seintje voor de winst-confetti (base.html leest dit uit de URL na
        # een gewone navigatie, dashboard.js uit resp.url na een AJAX-swap).
        parts = urlsplit(target)
        query = urlencode(parse_qsl(parts.query) + [("closed_win", "1")])
        target = urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
    return RedirectResponse(url=target, status_code=303)
```

Vervang door:

```python
@app.post("/journal/{entry_id}/close")
async def close_journal(
    entry_id: int,
    exit_price: float = Form(...),
    exit_time: str = Form(...),
    next: str = Form(""),
    user: dict = Depends(require_login),
):
    won = False
    eval_flag = None
    eval_flash = None
    try:
        result_eur, is_practice, evaluation_id = repo.close_journal_trade(entry_id, user["id"], exit_price, exit_time)
        won = (not is_practice) and result_eur > 0
        if evaluation_id:
            active_eval = repo.get_evaluation(evaluation_id)
            # Een run die al eerder is afgesloten (door een andere trade,
            # of handmatig gestopt) is bevroren: dit resultaat telt niet
            # meer mee, zie de spec.
            if active_eval and active_eval["status"] == "actief":
                progress = risk.evaluate_prop_progress(active_eval, result_eur, datetime.now(timezone.utc))
                repo.update_evaluation_state(
                    evaluation_id, progress.current_balance, progress.day_start_balance, progress.day_start_date,
                )
                if progress.status != "actief":
                    repo.close_evaluation(evaluation_id, progress.status, progress.closed_reason)
                    eval_flag = "evaluatie_geslaagd" if progress.status == "geslaagd" else "evaluatie_mislukt"
                else:
                    eval_flash = "up" if result_eur > 0 else ("down" if result_eur < 0 else None)
    except ValueError:
        # Geen eigen entry gevonden (niet van deze gebruiker, of nog geen
        # entry prijs ingevuld). Stil negeren, niets om te sluiten.
        pass
    target = _safe_next(next)
    extra_query = []
    if won:
        extra_query.append(("closed_win", "1"))
    if eval_flag:
        extra_query.append((eval_flag, "1"))
    if eval_flash:
        extra_query.append(("eval_flash", eval_flash))
    if extra_query:
        # Seintje voor client-side reveals (base.html leest dit uit de URL
        # na een gewone navigatie, dashboard.js uit resp.url na een
        # AJAX-swap) — zelfde patroon als de bestaande winst-confetti.
        parts = urlsplit(target)
        query = urlencode(parse_qsl(parts.query) + extra_query)
        target = urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
    return RedirectResponse(url=target, status_code=303)
```

- [ ] **Step 2: Koppel de oefentrade-route aan een actieve evaluatie**

Zoek in `create_practice_trade`:

```python
    risk_eur = risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"])
    entry_id = repo.create_journal_entry(signal_id, user["id"], risk_eur)
    repo.update_journal_status(entry_id, user["id"], "genomen", entry_price=ind.price)
```

Vervang door:

```python
    active_eval = repo.get_active_evaluation(user["id"])
    risk_eur = risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"])
    entry_id = repo.create_journal_entry(
        signal_id, user["id"], risk_eur, evaluation_id=active_eval["id"] if active_eval else None,
    )
    repo.update_journal_status(entry_id, user["id"], "genomen", entry_price=ind.price)
```

- [ ] **Step 3: Voeg de nieuwe routes toe**

Voeg toe direct vóór de sectie `# Oefentrades: handmatig een richting kiezen ...` (dus vóór `@app.post("/coins/{symbol}/oefen")`):

```python
# ---------------------------------------------------------------------------
# Evaluatie simulatie: virtueel een Kraken Prop-achtige evaluatie naspelen
# met dezelfde dagverlies-, drawdown- en winstdoel-regels, gevoed door
# oefentrades die tijdens een actieve run genomen worden. Zie de spec voor
# het volledige ontwerp.
# ---------------------------------------------------------------------------

PROP_EVAL_TIERS = (5000.0, 10000.0, 25000.0, 50000.0, 100000.0, 200000.0)


@app.post("/evaluatie/start")
async def start_evaluation(
    tier_amount: float = Form(...),
    profit_target_pct: float = Form(...),
    max_drawdown_pct: float = Form(...),
    user: dict = Depends(require_login),
):
    if (
        tier_amount not in PROP_EVAL_TIERS
        or not (0 < profit_target_pct <= 50)
        or not (0 < max_drawdown_pct <= 50)
        or repo.get_active_evaluation(user["id"]) is not None
    ):
        # Ongeldige input of dubbele start (bv. twee tabbladen tegelijk):
        # stil negeren, het dashboard toont sowieso alleen het
        # startformulier als er nog geen actieve run is.
        return RedirectResponse(url="/dashboard", status_code=303)
    repo.create_evaluation(user["id"], tier_amount, profit_target_pct, max_drawdown_pct)
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/evaluatie/stop")
async def stop_evaluation(user: dict = Depends(require_login)):
    active = repo.get_active_evaluation(user["id"])
    if active:
        repo.close_evaluation(active["id"], "gestopt", "handmatig gestopt")
    return RedirectResponse(url="/dashboard", status_code=303)


```

- [ ] **Step 4: Voeg de dashboard-context toe**

Zoek in de `dashboard`-route (niet de coin-pagina) de regel aan het einde van de bestaande contextopbouw:

```python
    unclear_messages = repo.recent_unclear_messages() if is_admin else None
```

Voeg er direct na toe:

```python
    # Evaluatie simulatie: bij een net beëindigde run (geslaagd/mislukt)
    # is er geen actieve run meer om te tonen, maar de reveal-melding in de
    # URL vraagt om die laatste run toch één keer te laten zien in zijn
    # eindtoestand.
    active_evaluation = repo.get_active_evaluation(user["id"])
    eval_history = repo.list_evaluations_for_user(user["id"])
    eval_display = active_evaluation
    if not eval_display and (request.query_params.get("evaluatie_geslaagd") or request.query_params.get("evaluatie_mislukt")):
        eval_display = eval_history[0] if eval_history else None

    eval_day_number = None
    eval_daily_loss_used_pct = 0.0
    eval_drawdown_used_pct = 0.0
    eval_profit_progress_pct = 0.0
    eval_daily_results = []
    if eval_display:
        end_reference = (
            datetime.fromisoformat(eval_display["ended_at"]) if eval_display["ended_at"]
            else datetime.now(timezone.utc)
        )
        eval_day_number = (end_reference.date() - datetime.fromisoformat(eval_display["started_at"]).date()).days + 1

        daily_loss_amount = eval_display["day_start_balance"] * eval_display["max_daily_loss_pct"] / 100
        loss_so_far = max(0.0, eval_display["day_start_balance"] - eval_display["current_balance"])
        eval_daily_loss_used_pct = min(100.0, (loss_so_far / daily_loss_amount * 100) if daily_loss_amount else 0.0)

        drawdown_amount = eval_display["tier_amount"] * eval_display["max_drawdown_pct"] / 100
        drawdown_so_far = max(0.0, eval_display["tier_amount"] - eval_display["current_balance"])
        eval_drawdown_used_pct = min(100.0, (drawdown_so_far / drawdown_amount * 100) if drawdown_amount else 0.0)

        profit_amount = eval_display["tier_amount"] * eval_display["profit_target_pct"] / 100
        profit_so_far = max(0.0, eval_display["current_balance"] - eval_display["tier_amount"])
        eval_profit_progress_pct = min(100.0, (profit_so_far / profit_amount * 100) if profit_amount else 0.0)

        eval_daily_results = _build_eval_day_dots(repo.list_evaluation_daily_results(eval_display["id"]))
```

Voeg de teruggegeven context-sleutels toe aan de `TemplateResponse`-dict van `dashboard` (zoek `"unclear_messages": unclear_messages,` en voeg er na toe):

```python
        "eval_display": eval_display,
        "eval_history": eval_history,
        "eval_day_number": eval_day_number,
        "eval_daily_loss_used_pct": eval_daily_loss_used_pct,
        "eval_drawdown_used_pct": eval_drawdown_used_pct,
        "eval_profit_progress_pct": eval_profit_progress_pct,
        "eval_daily_results": eval_daily_results,
```

Voeg de helperfunctie toe boven de `dashboard`-route (bijvoorbeeld direct na `_build_heatmap_weeks`):

```python
def _build_eval_day_dots(daily_results: list[dict]) -> list[dict]:
    """Zelfde kleurintensiteit-formule als _build_heatmap_weeks, maar als
    platte rij in plaats van een week-rooster: één stip per handelsdag van
    de evaluatie-run, relatief aan de grootste dagwaarde in de reeks
    zelf."""
    max_abs = max((abs(d["value"]) for d in daily_results), default=0.0) or 1.0
    dots = []
    for d in daily_results:
        level = 0
        if d["value"]:
            level = min(3, max(1, round(abs(d["value"]) / max_abs * 3)))
            level = level if d["value"] > 0 else -level
        dots.append({"date": d["date"], "value": d["value"], "level": level})
    return dots
```

- [ ] **Step 5: Schrijf de test in de scratchpad-directory**

Maak `<scratchpad>/test_prop_eval_routes.py`:

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
os.environ["JWT_SECRET"] = "test-secret-prop-eval-routes-0123456789012345"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path

import pandas as pd

from app import db, exchange, repo, security

db.init_db()
uid = repo.create_user("proproutesuser", security.hash_password("testpass123"), 1000.0, 1.0, "779")


def fake_ohlcv(coin, timeframe="4h", limit=200, since=None):
    """Vlakke candle-reeks, genoeg voor EMA21/ATR/ADX om te berekenen
    zonder een echte exchange-call — zelfde patroon als eerder gebruikt
    voor de swing-watches-tests."""
    rows = []
    for i in range(60):
        rows.append({
            "timestamp": pd.Timestamp.now(tz="UTC") - pd.Timedelta(days=60 - i),
            "open": 100.0, "high": 101.0, "low": 99.0, "close": 100.0, "volume": 1000.0,
        })
    return pd.DataFrame(rows)


exchange.market_exists = lambda coin: True
exchange.to_symbol = lambda coin: f"{coin.upper()}/USDT"
exchange.fetch_last_price = lambda coin: 100.0
exchange.fetch_ohlcv = fake_ohlcv
repo.add_coin_if_new("TAO", "TAO/USDT")

import main as web_main
from fastapi.testclient import TestClient

client = TestClient(web_main.app)
token = security.create_session_token(uid)
client.cookies.set("session", token)

# --- start: ongeldige tier wordt genegeerd ---
resp = client.post("/evaluatie/start", data={"tier_amount": "999", "profit_target_pct": "8", "max_drawdown_pct": "6"})
assert repo.get_active_evaluation(uid) is None
print("OK: een niet-toegestaan tier-bedrag start geen run")

# --- start: geldige tier ---
resp = client.post("/evaluatie/start", data={"tier_amount": "10000", "profit_target_pct": "8", "max_drawdown_pct": "6"})
active = repo.get_active_evaluation(uid)
assert active is not None and active["tier_amount"] == 10000.0
print("OK: een geldig tier-bedrag start een run")

# --- start: dubbele start wordt genegeerd ---
resp = client.post("/evaluatie/start", data={"tier_amount": "25000", "profit_target_pct": "8", "max_drawdown_pct": "6"})
still_active = repo.get_active_evaluation(uid)
assert still_active["id"] == active["id"] and still_active["tier_amount"] == 10000.0
print("OK: een tweede start terwijl er al een actieve run is, verandert niks")

# --- oefentrade tijdens een actieve run wordt gekoppeld ---
resp = client.post(f"/coins/TAO/oefen", data={"direction": "long"})
entries = [e for e in repo.list_journal(uid, status=None) if e["coin"] == "TAO"]
assert len(entries) == 1
entry = entries[0]
assert entry["status"] == "genomen" and entry["entry_price"] is not None
raw_entry = repo.get_journal_entry(entry["id"], uid)
assert raw_entry["evaluation_id"] == active["id"]
print("OK: een oefentrade tijdens een actieve run krijgt evaluation_id gezet")

# --- sluiten met winst die het winstdoel haalt: reveal-vlag + status geslaagd ---
resp = client.post(
    f"/journal/{entry['id']}/close",
    data={"exit_price": "1000000", "exit_time": db.now_iso(), "next": "/dashboard"},
    follow_redirects=False,
)
assert resp.status_code == 303
location = resp.headers["location"]
assert "evaluatie_geslaagd=1" in location, location
closed_eval = repo.get_evaluation(active["id"])
assert closed_eval["status"] == "geslaagd"
print(f"OK: winst boven het winstdoel sluit de run af als geslaagd, redirect draagt de reveal-vlag ({location})")

# --- stop op een run die al gesloten is: geen effect, geen crash ---
client.post("/evaluatie/stop")
still_closed = repo.get_evaluation(active["id"])
assert still_closed["status"] == "geslaagd"
print("OK: stoppen zonder actieve run heeft geen effect")

# --- dashboard toont de zojuist beëindigde run in zijn eindtoestand ---
dash_resp = client.get("/dashboard", params={"evaluatie_geslaagd": "1"})
assert dash_resp.status_code == 200
assert "Evaluatie simulatie" in dash_resp.text
print("OK: dashboard rendert zonder fouten met de reveal-query aanwezig")

print("ALLE PROP-EVAL ROUTE TESTS GESLAAGD")
```

- [ ] **Step 6: Run, verwacht een fout (routes bestaan nog niet)**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_prop_eval_routes.py`
Expected: `404` op `/evaluatie/start` of een `AssertionError`, opgelost door Step 1-4.

- [ ] **Step 7: Run opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_prop_eval_routes.py`
Expected: alle 7 "OK:"-regels, eindigend met "ALLE PROP-EVAL ROUTE TESTS GESLAAGD".

- [ ] **Step 8: Commit**

```bash
git add web/main.py
git commit -m "$(cat <<'EOF'
web/main.py: routes voor de evaluatie simulatie

/evaluatie/start en /evaluatie/stop, koppeling van oefentrades aan een
actieve run, en verwerking van het resultaat bij het sluiten van een
gekoppelde trade inclusief de reveal-vlaggen voor de UI.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

### Task 5: Dashboard-sectie, CSS en het eenmalige reveal

**Files:**
- Modify: `web/templates/dashboard.html`
- Modify: `web/static/style.css`
- Modify: `web/templates/base.html`
- Modify: `web/static/dashboard.js`

**Interfaces:**
- Consumes: `eval_display`, `eval_history`, `eval_day_number`, `eval_daily_loss_used_pct`, `eval_drawdown_used_pct`, `eval_profit_progress_pct`, `eval_daily_results` (Task 4).

Puur UI, geen backend-testbaarheid voor de CSS-animatie zelf (client-side); Task 6 verifieert dit handmatig met Playwright. De structurele HTML/route-integratie hieronder kan wel met een korte scratch-test op tekstaanwezigheid (Step 5).

- [ ] **Step 1: Voeg de CSS toe aan `web/static/style.css`**

Voeg toe aan het einde van het bestand:

```css
/* Evaluatie-simulatie: hergebruikt .risk-gauge/.risk-gauge-fill volledig
   (zelfde gauge-grow-intro, zelfde vloeistof-shimmer). Alleen de
   winstdoel-balk krijgt een eigen variant, want hoger is hier beter, niet
   gevaarlijker: geen rood/amber-opbouw, altijd groen. */
.risk-gauge-fill.goal-fill { background: var(--green); }

.prop-eval-head {
  display: flex; justify-content: space-between; align-items: baseline;
  margin-bottom: 12px; font-size: 13px;
}
.prop-eval-days { display: flex; flex-wrap: wrap; gap: 3px; margin: 14px 0 4px; }
.prop-eval-stop { margin-top: 12px; }
.prop-eval-start { display: flex; flex-wrap: wrap; gap: 12px; align-items: flex-end; }
.prop-eval-start label { display: flex; flex-direction: column; gap: 4px; font-size: 12.5px; color: var(--muted); }

/* Eenmalig geslaagd/mislukt-moment: vuurt precies één keer via een
   URL-vlag die client-side wordt gelezen en meteen weer verwijderd
   (zelfde patroon als closed_win/fireConfetti hierboven in dit bestand),
   nooit als doorlopende animatie — animation-iteration-count is eindig. */
.eval-reveal-pass .risk-gauge-fill.goal-fill { animation: eval-pass-glow 700ms ease 3; }
@keyframes eval-pass-glow {
  0%, 100% { box-shadow: 0 0 0 rgba(51, 214, 159, 0); }
  50% { box-shadow: 0 0 20px rgba(51, 214, 159, 0.6); }
}
.eval-reveal-fail { animation: eval-fail-shake 480ms ease 1; }
@keyframes eval-fail-shake {
  0%, 100% { transform: translateX(0); }
  20% { transform: translateX(-6px); }
  40% { transform: translateX(6px); }
  60% { transform: translateX(-6px); }
  80% { transform: translateX(6px); }
}
@media (prefers-reduced-motion: reduce) {
  .eval-reveal-pass .risk-gauge-fill.goal-fill,
  .eval-reveal-fail { animation: none; }
}
```

- [ ] **Step 2: Voeg de sectie toe aan `web/templates/dashboard.html`**

Zoek de regel `<section class="summary-strip" style="--i: 0">` en het bijbehorende sluitende `</section>`, en voeg er direct NA toe:

```html
{% if eval_display %}
<section class="card {{ 'eval-reveal-pass' if eval_display.status == 'geslaagd' else ('eval-reveal-fail' if eval_display.status == 'mislukt' else '') }}" style="--i: 1" id="prop-eval-card">
  <h2><svg class="h2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2 2 7l10 5 10-5-10-5z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/></svg>Evaluatie simulatie</h2>
  <div class="prop-eval-head">
    <span class="muted">€{{ "%.0f"|format(eval_display.tier_amount) }} tier · dag {{ eval_day_number }}{% if eval_display.status != 'actief' %} · {{ eval_display.status }}{% endif %}</span>
    <span class="mono">€{{ "%.2f"|format(eval_display.current_balance) }}</span>
  </div>

  <div class="risk-gauge">
    <div class="risk-gauge-head"><span class="muted">Dagverlies opgebruikt</span><span class="mono">{{ "%.0f"|format(eval_daily_loss_used_pct) }}%</span></div>
    <div class="risk-gauge-bar">
      <div class="risk-gauge-fill {{ 'risk-high' if eval_daily_loss_used_pct >= 85 else ('risk-mid' if eval_daily_loss_used_pct >= 60 else '') }}"
           style="width: {{ [eval_daily_loss_used_pct, 100] | min }}%"></div>
    </div>
  </div>

  <div class="risk-gauge">
    <div class="risk-gauge-head"><span class="muted">Drawdown opgebruikt</span><span class="mono">{{ "%.0f"|format(eval_drawdown_used_pct) }}%</span></div>
    <div class="risk-gauge-bar">
      <div class="risk-gauge-fill {{ 'risk-high' if eval_drawdown_used_pct >= 85 else ('risk-mid' if eval_drawdown_used_pct >= 60 else '') }}"
           style="width: {{ [eval_drawdown_used_pct, 100] | min }}%"></div>
    </div>
  </div>

  <div class="risk-gauge">
    <div class="risk-gauge-head"><span class="muted">Winstdoel</span><span class="mono">{{ "%.0f"|format(eval_profit_progress_pct) }}%</span></div>
    <div class="risk-gauge-bar">
      <div class="risk-gauge-fill goal-fill" style="width: {{ [eval_profit_progress_pct, 100] | min }}%"></div>
    </div>
  </div>

  {% if eval_daily_results %}
  <div class="prop-eval-days">
    {% for day in eval_daily_results %}
    <span class="heat-cell heat-level-{{ day.level }}" title="{{ day.date }}: €{{ '%.2f'|format(day.value) }}"></span>
    {% endfor %}
  </div>
  {% endif %}

  {% if eval_display.status == 'actief' %}
  <form method="post" action="/evaluatie/stop" class="prop-eval-stop">
    <button type="submit" class="button-reset">Stoppen</button>
  </form>
  {% elif eval_display.closed_reason %}
  <p class="muted" style="font-size: 12px; margin-top: 10px;">{{ eval_display.closed_reason }}</p>
  {% endif %}
</section>
{% else %}
<section class="card" style="--i: 1">
  <h2><svg class="h2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2 2 7l10 5 10-5-10-5z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/></svg>Evaluatie simulatie</h2>
  <p class="muted">Test of je discipline en signalen een Kraken Prop-achtige evaluatie zouden overleven, zonder er geld aan uit te geven.</p>
  <form method="post" action="/evaluatie/start" class="prop-eval-start">
    <label>Bedrag
      <select name="tier_amount">
        <option value="5000">€5.000</option>
        <option value="10000" selected>€10.000</option>
        <option value="25000">€25.000</option>
        <option value="50000">€50.000</option>
        <option value="100000">€100.000</option>
        <option value="200000">€200.000</option>
      </select>
    </label>
    <label>Winstdoel % <input type="number" name="profit_target_pct" value="8" min="1" max="50" step="0.5" required></label>
    <label>Max drawdown % <input type="number" name="max_drawdown_pct" value="6" min="1" max="50" step="0.5" required></label>
    <button type="submit">Start evaluatie</button>
  </form>
</section>
{% endif %}

{% if eval_history %}
<details class="stats-collapse js-accordion" style="--i: 1">
  <summary class="stats-summary">
    <svg class="h2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="18" rx="2"/><line x1="3" y1="10" x2="21" y2="10"/></svg>
    <span>Evaluatie geschiedenis</span>
    <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6,9 12,15 18,9"/></svg>
  </summary>
  {% for run in eval_history %}
  <div class="long-term-item">
    <span class="badge badge-{{ 'long' if run.status == 'geslaagd' else ('short' if run.status == 'mislukt' else 'status') }}">{{ run.status }}</span>
    <span class="muted mono" style="font-size: 11px;">€{{ "%.0f"|format(run.tier_amount) }} · {{ run.started_at[:10] }}{% if run.ended_at %} tot {{ run.ended_at[:10] }}{% endif %}</span>
    {% if run.closed_reason %}<p class="muted" style="font-size: 11px; margin: 4px 0 0;">{{ run.closed_reason }}</p>{% endif %}
  </div>
  {% endfor %}
</details>
{% endif %}
```

- [ ] **Step 3: Voeg de client-side reveal toe aan `web/templates/base.html`**

Zoek het bestaande blok:

```javascript
    // Bij een gewone paginanavigatie (geen AJAX-swap, bv. vanaf de
    // coin-pagina) staat het seintje in de URL. Meteen weer verwijderen,
    // zodat verversen de confetti niet herhaalt.
    if (location.search.indexOf("closed_win=1") !== -1) {
      fireConfetti();
      var url = new URL(location.href);
      url.searchParams.delete("closed_win");
      history.replaceState(null, "", url.pathname + url.search + url.hash);
    }
```

Voeg er direct na toe (nog binnen dezelfde `(function () { ... })();`):

```javascript
    // Evaluatie-simulatie: eenmalig saldo-flits (winst/verlies) of een
    // geslaagd/mislukt-moment, zelfde eenmalig-vuur-patroon als de
    // confetti hierboven. De kaart zelf draagt de klasse die de CSS-
    // animatie triggert; de URL-vlag is puur het seintje, geen state.
    var evalCard = document.getElementById("prop-eval-card");
    if (evalCard && location.search.indexOf("eval_flash=") !== -1) {
      var flashUp = location.search.indexOf("eval_flash=up") !== -1;
      var balanceEl = evalCard.querySelector(".prop-eval-head .mono");
      if (balanceEl) balanceEl.classList.add(flashUp ? "flash-up" : "flash-down");
      var evalUrl = new URL(location.href);
      evalUrl.searchParams.delete("eval_flash");
      history.replaceState(null, "", evalUrl.pathname + evalUrl.search + evalUrl.hash);
    }
```

De grotere geslaagd/mislukt-reveal heeft geen aparte JS-trigger nodig: `dashboard.html` (Task 5, Step 2) zet de klasse `eval-reveal-pass`/`eval-reveal-fail` al server-side op de kaart zodra `eval_display.status` niet meer `'actief'` is, dus de CSS-animatie speelt vanzelf op de render die volgt op de redirect. Dat is precies één keer: een volgende paginaweergave (na de reveal) toont de run niet langer via `eval_display` (die valt terug op `active_evaluation`, en die is dan `None`), dus de klasse verschijnt niet opnieuw.

- [ ] **Step 4: Voeg dezelfde saldo-flits toe aan de AJAX-sluit-flow in `web/static/dashboard.js`**

Zoek:

```javascript
      // fetch volgt de 303-redirect zelf af: resp.url is de eindbestemming,
      // met ?closed_win=1 erin als het sluiten een echte winst was (zie
      // /journal/{id}/close). Die query komt hier nooit in de adresbalk,
      // dus alleen via resp.url te herkennen, niet via location.search.
      if (resp.url.indexOf("closed_win=1") !== -1 && window.HP && window.HP.confetti) {
        window.HP.confetti();
      }
```

Voeg er direct na toe:

```javascript
      if (resp.url.indexOf("eval_flash=") !== -1) {
        var evalCardAjax = document.getElementById("prop-eval-card");
        if (evalCardAjax) {
          var flashUpAjax = resp.url.indexOf("eval_flash=up") !== -1;
          var balanceElAjax = evalCardAjax.querySelector(".prop-eval-head .mono");
          if (balanceElAjax) balanceElAjax.classList.add(flashUpAjax ? "flash-up" : "flash-down");
        }
      }
```

De AJAX-sluit-flow ververst alleen `#open-nu-body`, niet de evaluatie-kaart zelf — een geslaagd/mislukt-reveal na een AJAX-sluiting verschijnt daarom pas bij de eerstvolgende volledige paginaweergave, niet meteen. Dat is acceptabel: de saldo-flits hierboven geeft al direct feedback, en de gebruiker ziet de reveal zodra hij het dashboard opnieuw laadt of naar een andere pagina en terug navigeert.

- [ ] **Step 5: Schrijf een korte structuur-test in de scratchpad-directory**

Maak `<scratchpad>/test_prop_eval_dashboard_html.py`:

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
os.environ["JWT_SECRET"] = "test-secret-prop-eval-dashboard-01234567890123"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path
from app import db, repo, security

db.init_db()
uid = repo.create_user("propdashuser", security.hash_password("testpass123"), 1000.0, 1.0, "780")

import main as web_main
from fastapi.testclient import TestClient

client = TestClient(web_main.app)
token = security.create_session_token(uid)
client.cookies.set("session", token)

resp = client.get("/dashboard")
assert resp.status_code == 200
assert "Evaluatie simulatie" in resp.text
assert "Start evaluatie" in resp.text
print("OK: dashboard toont het startformulier zonder actieve run")

repo.create_evaluation(uid, tier_amount=10000.0, profit_target_pct=8.0, max_drawdown_pct=6.0)
resp2 = client.get("/dashboard")
assert "Dagverlies opgebruikt" in resp2.text
assert "Drawdown opgebruikt" in resp2.text
assert "Winstdoel" in resp2.text
assert 'id="prop-eval-card"' in resp2.text
assert "Start evaluatie" not in resp2.text
print("OK: dashboard toont de statuskaart met een actieve run, geen startformulier meer")

print("ALLE PROP-EVAL DASHBOARD-HTML TESTS GESLAAGD")
```

- [ ] **Step 6: Run, verwacht een gemiste assert**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_prop_eval_dashboard_html.py`
Expected: `AssertionError` op "Evaluatie simulatie" (sectie bestaat nog niet), opgelost door Step 2.

- [ ] **Step 7: Run opnieuw, verwacht dat alles slaagt**

Run: `source /home/user/Trade/.venv/bin/activate && python3 <scratchpad>/test_prop_eval_dashboard_html.py`
Expected: beide "OK:"-regels, eindigend met "ALLE PROP-EVAL DASHBOARD-HTML TESTS GESLAAGD".

- [ ] **Step 8: Commit**

```bash
git add web/templates/dashboard.html web/static/style.css web/templates/base.html web/static/dashboard.js
git commit -m "$(cat <<'EOF'
Dashboard: evaluatie-sectie met hergebruikte animaties + eenmalig reveal

Hergebruikt risk-gauge/risk-mid/risk-high/flash-up/flash-down/heat-cell
voor de drie voortgangsbalken, de saldo-flits en de dag-stippen. Het
geslaagd/mislukt-moment is de enige nieuwe CSS, vuurt eenmalig via
dezelfde URL-vlag-aanpak als de bestaande winst-confetti.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

### Task 6: Handmatige visuele verificatie

**Files:**
- Geen codewijzigingen. Verificatie-only met Playwright, chromium op `/opt/pw-browsers/chromium` (al aanwezig, geen `playwright install`).

Voor CSS-animaties bestaat geen zinvolle geautomatiseerde test (canvas/animatie-gedrag, geen berekenbare output). Deze taak verifieert de vier eindtoestanden expliciet, plus `prefers-reduced-motion`, conform CLAUDE.md's UI-conventie.

- [ ] **Step 1: Start de app tegen een scratch-database**

```bash
DATABASE_PATH=/tmp/prop_eval_ui_check.db JWT_SECRET=test-secret-prop-eval-ui-0123456789012345 \
  uvicorn web.main:app --reload
```

- [ ] **Step 2: Maak een gebruiker en een actieve run met kleine marges**

Gebruik een Python-shell of een klein script (hergebruik het patroon uit `test_prop_eval_routes.py`) om:
1. Een gebruiker aan te maken.
2. Via `POST /evaluatie/start` een run te starten met `tier_amount=10000`, `profit_target_pct=8`, `max_drawdown_pct=6`.
3. In te loggen via de browser (JWT-cookie `session`, zie `security.create_session_token` + `page.context.add_cookies(...)`, of de echte login-flow).

- [ ] **Step 3: Normale voortgang**

Open `/dashboard`. Controleer:
- De statuskaart toont tier, dag-nummer, saldo, en drie balken (dagverlies, drawdown, winstdoel), allemaal op 0%.
- De winstdoel-balk is groen (`goal-fill`), de andere twee grijs/accentkleurig (nog geen `risk-mid`/`risk-high`).
- Maak een screenshot: `prop_eval_normal.png`.

- [ ] **Step 4: Spanning bij een naderende dagverlieslimiet**

Neem via de coin-pagina een oefentrade en sluit hem met een verlies dat de dagverlieslimiet tot ruim boven 85% opgebruikt zonder hem te raken (bijvoorbeeld €260 verlies op een €300-limiet = ~87%). Herlaad `/dashboard`. Controleer:
- De dagverlies-balk staat op `risk-high` (rood) en de kaart zelf pulseert zichtbaar (dezelfde `risk-pulse`-ademhaling als de bestaande risicogauge).
- Maak een screenshot: `prop_eval_tension.png`.

- [ ] **Step 5: Geslaagd-reveal**

Sluit een oefentrade met een winst die het winstdoel overschrijdt (bijvoorbeeld €900 winst op een €800-doel). Volg de redirect. Controleer:
- De URL bevat kortstondig `evaluatie_geslaagd=1` (voor de client-side cleanup het verwijdert) — controleer dit door de netwerk-respons te inspecteren, niet de uiteindelijke adresbalk.
- De winstdoel-balk toont een korte, groene gloed-puls (2 à 3 keer), die vanzelf stopt.
- Het statuslabel toont "geslaagd" en de reden ("winstdoel gehaald").
- Maak een screenshot ná de puls: `prop_eval_passed.png`.
- Herlaad de pagina nogmaals: de puls speelt NIET opnieuw (eenmalig).

- [ ] **Step 6: Mislukt-reveal**

Start een nieuwe run (`/evaluatie/start`), sluit een oefentrade met een verlies dat de drawdown-limiet raakt. Volg de redirect. Controleer:
- De kaart schudt kort (drie keer, onder de 500ms), stopt vanzelf.
- Het statuslabel toont "mislukt" en de reden ("maximale drawdown geraakt").
- Maak een screenshot ná de schudbeweging: `prop_eval_failed.png`.

- [ ] **Step 7: `prefers-reduced-motion` gecontroleerd**

Herhaal Step 4 t/m 6 met `page.emulate_media(reduced_motion="reduce")` vóór het laden van de pagina. Controleer bij elke stap:
- Geen enkele animatie speelt af (geen ademhaling, geen puls, geen schudbeweging).
- De eindstaat (volle/gedeeltelijke balk, definitief statuslabel) is meteen zichtbaar, identiek aan de staat ná de animatie in de vorige stappen.

- [ ] **Step 8: Rapporteer**

Vat kort samen: welke van de 4 eindtoestanden + de reduced-motion-controle zijn bevestigd, met de zes screenshots als bewijs. Geen commit nodig, dit is verificatie-only.

---

## Self-Review

**Spec coverage:**
- `prop_evaluations`-tabel + tweedelig schema/migratie-patroon → Task 2. ✓
- `journal_entries.evaluation_id` + index in `_migrate()` → Task 2. ✓
- 00:30 UTC handelsdag-grens, op precies één plek → Task 1 (`risk.trading_day_label`), hergebruikt in Task 2/3. ✓
- Drawdown → dagverlies → winstdoel volgorde → Task 1. ✓
- `repo.py` CRUD (create/get/list/update/close) → Task 2. ✓
- `close_journal_trade`'s 3-tuple + `create_journal_entry`'s `evaluation_id` + `list_evaluation_daily_results` → Task 3. ✓
- Bevroren run (resultaat na afsluiting telt niet meer mee) → expliciet gecheckt in Task 4, Step 1 (`if active_eval and active_eval["status"] == "actief"`). ✓
- `/evaluatie/start` (inclusief validatie + dubbele-start-check) en `/evaluatie/stop` → Task 4. ✓
- Oefentrade-koppeling aan een actieve run → Task 4, Step 2. ✓
- Dashboard-sectie met drie balken, dag-stippen, start/stop, geschiedenis → Task 5. ✓
- Visueel ontwerp: hergebruik van `risk-gauge`/`risk-mid`/`risk-high`/shimmer, `risk-pulse`, `flash-up`/`flash-down`, `heat-cell`, en het ene nieuwe eenmalige reveal → Task 5. ✓
- Niet-doelen (geen Kraken-koppeling, geen automatische signalen, één run tegelijk, geen wijziging aan `risk.py`'s echte positiegrootte/`portfolio_eur`/winrate) → geen enkele taak raakt die bestanden op een andere manier dan gelezen (`user["portfolio_eur"]`/`user["risk_percent"]` voor `risk.compute_risk_eur`, ongewijzigd); geen nieuwe automatische-signaal-koppeling; `get_active_evaluation` + de start-route's check garanderen één run. ✓

**Placeholder scan:** geen "TBD"/"implement later"/ongeschreven testcode gevonden bij het doorlopen van elke taak.

**Type-consistentie:** `evaluation`-dicts die Task 1's `evaluate_prop_progress` verwacht (`tier_amount`, `profit_target_pct`, `max_daily_loss_pct`, `max_drawdown_pct`, `current_balance`, `day_start_balance`, `day_start_date`) zijn exact de kolomnamen van Task 2's `prop_evaluations`-tabel, dus een `repo.get_evaluation(...)`-resultaat past er ongewijzigd in. `close_journal_trade`'s nieuwe 3-tuple-signatuur (Task 3) wordt in Task 4 op de enige aanroeper consistent toegepast. `list_evaluation_daily_results`'s itemvorm (`{"date": str, "value": float}`, Task 3) is exact wat Task 4's `_build_eval_day_dots` verwacht, die er zelf `level` aan toevoegt voordat de template (Task 5) het leest. Geen kolom- of functienaam wijkt af tussen de taak die hem definieert en de taken die hem gebruiken.
