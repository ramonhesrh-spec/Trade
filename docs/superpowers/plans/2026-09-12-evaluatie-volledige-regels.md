# Evaluatie: volledige regels op echte trade-kansen — Implementatieplan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Zodra een gebruiker een actieve Kraken Prop-evaluatie heeft, sizen
en tellen echte Discord-signalen (en oefentrades) daarop mee, binnen
dagverlies/drawdown, inclusief fees en hefboomkosten — in plaats van dat de
evaluatie alleen losstaand via handmatige oefentrades werkt.

**Architecture:** Vier nieuwe pure functies in `app/risk.py` bepalen hoeveel
risico een trade mag nemen (kleinste van persoonlijke cap, dagbudget-aandeel,
drawdown-aandeel, hefboomcap) en of evaluatie-sizing voor nu geblokkeerd is.
`app/signal_processor.py` en de oefentrade-routes in `web/main.py` roepen
deze aan in plaats van de kale `portfolio_eur x risk_percent`-berekening
zodra er een actieve evaluatie is. Twee nieuwe kolommen op `journal_entries`
(`entry_time`, `position_size`) maken het mogelijk om bij het sluiten van
een evaluatie-trade de werkelijke fee- en hefboomkosten te verrekenen op
basis van hoe lang de trade daadwerkelijk openstond.

**Tech Stack:** Python, FastAPI, SQLite (via `app/db.py`), geen nieuwe
dependencies.

**Spec:** `docs/superpowers/specs/2026-09-12-evaluatie-volledige-regels-design.md`

## Global Constraints

- Alleen voor trades met een `evaluation_id` (dus alleen zolang de
  gebruiker een actieve evaluatie heeft) verandert er iets aan sizing/fees.
  Zonder actieve evaluatie: exact het bestaande `portfolio_eur x
  risk_percent`-gedrag, geen enkele regressie toegestaan.
- Stop loss/take profit-berekening zelf (`compute_stop_take`,
  `compute_stop_take_from_levels`) verandert niet.
- Hoogstens één actieve evaluatie per gebruiker blijft de aanname (bestaande
  beperking, niet aangepast in dit plan).
- Database-toegang alleen via `app/repo.py`, nooit losse SQL elders.
  Schrijfacties via `app/db.py:session()`.
- Schema-wijzigingen altijd op twee plekken: `app/schema.sql` (`CREATE
  TABLE IF NOT EXISTS`, voor nieuwe databases) én een idempotente `ALTER
  TABLE` in `app/db.py:_migrate()` achter een `PRAGMA table_info`-check
  (voor bestaande databases).
- Constanten exact: `EVAL_BUDGET_TRADE_RESERVE = 3`,
  `EVAL_TRADE_FEE_RATE = 0.0008`, `EVAL_LEVERAGE_DAILY_RATE = 0.00033`,
  `EVAL_SIZING_DAYS_ASSUMPTION = 1.0`, `MAX_EVAL_LEVERAGE = 5.0` (verhuist
  van `web/main.py` naar `app/risk.py`), blokkade-drempel `5.0` (procent
  van het volledige dagbudget/drawdown-budget).

---

### Task 1: Schema + migratie — `entry_time` en `position_size` op journal_entries

**Files:**
- Modify: `app/schema.sql` (CREATE TABLE journal_entries, rond regel 172)
- Modify: `app/db.py` (`_migrate()`, rond regel 79-87)
- Modify: `app/repo.py` (`_JOURNAL_SELECT`, rond regel 901-928)
- Test: `/tmp/claude-0/-home-user-Trade/*/scratchpad/test_task1_schema.py` (scratch, niet gecommit)

**Interfaces:**
- Produces: `journal_entries.entry_time TEXT` (NULL-baar), `journal_entries.position_size REAL` (NULL-baar), beide leesbaar via elke `repo`-functie die `_JOURNAL_SELECT` gebruikt (dus ook `get_journal_entry`, gebruikt door latere taken).

- [ ] **Step 1: Kolommen toevoegen aan schema.sql**

In `app/schema.sql`, de bestaande `CREATE TABLE IF NOT EXISTS journal_entries`
(rond regel 172-191):

```python
old = '''CREATE TABLE IF NOT EXISTS journal_entries (
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
    level_alert_sent INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    stop_loss_override REAL,
    take_profit_override REAL,
    position_size_override REAL,
    UNIQUE (signal_id, user_id)
);'''
new = '''CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL REFERENCES signals(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    risk_eur REAL,
    telegram_sent INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'nieuw',
    entry_price REAL,
    entry_time TEXT,
    exit_price REAL,
    exit_time TEXT,
    result_eur REAL,
    result_pct REAL,
    note TEXT,
    level_alert_sent INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    stop_loss_override REAL,
    take_profit_override REAL,
    position_size_override REAL,
    position_size REAL,
    UNIQUE (signal_id, user_id)
);'''
```

Let op: deze tabel-definitie staat verderop in het bestand ook nog een
keer met `evaluation_id` erbij (de kolom die de kraken-prop-evaluatie-
deelproject heeft toegevoegd via `_migrate()`, NIET via schema.sql, want
die kwam later dan de oorspronkelijke tabel). Zoek de ENIGE
`CREATE TABLE IF NOT EXISTS journal_entries`-definitie in het bestand
(er is er maar één) en vervang die zoals hierboven.

- [ ] **Step 2: Migratie toevoegen in db.py**

In `app/db.py`, in `_migrate()`, direct na de bestaande
`existing_journal`-checks (rond regel 79-87):

```python
old = '''    existing_journal = {row["name"] for row in conn.execute("PRAGMA table_info(journal_entries)")}
    if "stop_loss_override" not in existing_journal:
        conn.execute("ALTER TABLE journal_entries ADD COLUMN stop_loss_override REAL")
    if "take_profit_override" not in existing_journal:
        conn.execute("ALTER TABLE journal_entries ADD COLUMN take_profit_override REAL")
    if "position_size_override" not in existing_journal:
        conn.execute("ALTER TABLE journal_entries ADD COLUMN position_size_override REAL")
    if "evaluation_id" not in existing_journal:
        conn.execute("ALTER TABLE journal_entries ADD COLUMN evaluation_id INTEGER REFERENCES prop_evaluations(id)")'''
new = '''    existing_journal = {row["name"] for row in conn.execute("PRAGMA table_info(journal_entries)")}
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
        conn.execute("ALTER TABLE journal_entries ADD COLUMN position_size REAL")'''
```

- [ ] **Step 3: Beide kolommen leesbaar maken via _JOURNAL_SELECT**

In `app/repo.py`, `_JOURNAL_SELECT` (rond regel 901-928):

```python
old = '''        je.status AS status, je.entry_price AS entry_price,
        je.exit_price AS exit_price, je.exit_time AS exit_time,'''
new = '''        je.status AS status, je.entry_price AS entry_price,
        je.entry_time AS entry_time, je.position_size AS position_size,
        je.exit_price AS exit_price, je.exit_time AS exit_time,'''
```

- [ ] **Step 4: Test — fresh database heeft beide kolommen, migratie op bestaande database is idempotent**

```python
# /tmp/claude-0/-home-user-Trade/*/scratchpad/test_task1_schema.py
import os
os.environ["DATABASE_PATH"] = "/tmp/task1_scratch.db"
if os.path.exists("/tmp/task1_scratch.db"):
    os.remove("/tmp/task1_scratch.db")

from app import db

db.init_db()
with db.session() as conn:
    cols = {row["name"] for row in conn.execute("PRAGMA table_info(journal_entries)")}
assert "entry_time" in cols, "entry_time ontbreekt op een verse database"
assert "position_size" in cols, "position_size ontbreekt op een verse database"

# Migratie nogmaals draaien (simuleert een herstart tegen een bestaande database) moet niet crashen
db.init_db()
with db.session() as conn:
    cols_again = {row["name"] for row in conn.execute("PRAGMA table_info(journal_entries)")}
assert cols == cols_again

print("Task 1: OK")
```

Run: `DATABASE_PATH=/tmp/task1_scratch.db python3 /tmp/.../test_task1_schema.py`
Expected: `Task 1: OK`, geen exceptions.

- [ ] **Step 5: Commit**

```bash
git add app/schema.sql app/db.py app/repo.py
git commit -m "Schema: entry_time en position_size op journal_entries voor evaluatie-fees"
```

---

### Task 2: risk.py — dagbudget/drawdown-resterend en sizing-formule

**Files:**
- Modify: `app/risk.py`
- Test: scratch script

**Interfaces:**
- Consumes: niets nieuws uit eerdere taken (pure functies, geen database).
- Produces: `MAX_EVAL_LEVERAGE: float`, `EVAL_BUDGET_TRADE_RESERVE: int`,
  `compute_eval_daily_budget_remaining(evaluation: dict, open_risk_eur: float) -> float`,
  `compute_eval_drawdown_budget_remaining(evaluation: dict, open_risk_eur: float) -> float`,
  `compute_eval_risk_eur(evaluation: dict, risk_percent: float, open_risk_eur: float, entry_price: float, stop_loss: float) -> float`,
  `eval_sizing_blocked(evaluation: dict, open_risk_eur: float) -> bool`.
  Alle vier verwachten `evaluation` als een dict met minstens de sleutels
  `current_balance`, `day_start_balance`, `max_daily_loss_pct`,
  `tier_amount`, `max_drawdown_pct` (exact de kolomnamen van
  `prop_evaluations`, wat `repo.get_active_evaluation` teruggeeft).

- [ ] **Step 1: Nieuwe constanten en functies in risk.py**

Voeg toe in `app/risk.py`, direct ná de bestaande
`MIN_LEVEL_STOP_DISTANCE_ATR_FRACTION`-constante en vóór
`compute_stop_take_from_levels` (of eender welke plek boven aan het bestand
na de bestaande constanten — de exacte positie maakt niet uit, wel dat het
vóór het eerste gebruik staat):

```python
# Hoeveel keer het evaluatiesaldo een positie maximaal notional mag zijn,
# exact de hefboomlimiet van de echte Kraken Prop. Was voorheen alleen in
# web/main.py voor oefentrades, geldt nu voor elke evaluatie-gesizede trade.
MAX_EVAL_LEVERAGE = 5.0

# Reserveer bij het sizen van één trade ruimte voor nog dit aantal - 1
# volgende trades dezelfde dag/run, in plaats van in één klap het hele
# resterende budget op te souperen.
EVAL_BUDGET_TRADE_RESERVE = 3

# Onder dit percentage van het VOLLEDIGE dagbudget of de VOLLEDIGE
# drawdown-ruimte is verder sizen op de evaluatie zinloos: elke nieuwe
# trade zou toch nagenoeg nul risico mogen nemen.
EVAL_BUDGET_BLOCK_THRESHOLD_PCT = 5.0


def compute_eval_daily_budget_remaining(evaluation: dict, open_risk_eur: float) -> float:
    """Wat er nog over is van het dagverlies-budget van de evaluatie: het
    toegestane dagverlies min wat vandaag al verloren is, min het risico
    dat al vaststaat in nog open evaluatie-trades (dat risico is nog niet
    in current_balance verwerkt, zie repo.total_open_risk_eur_for_evaluation)."""
    daily_loss_amount = evaluation["day_start_balance"] * evaluation["max_daily_loss_pct"] / 100
    loss_so_far = max(0.0, evaluation["day_start_balance"] - evaluation["current_balance"])
    return max(0.0, daily_loss_amount - loss_so_far - open_risk_eur)


def compute_eval_drawdown_budget_remaining(evaluation: dict, open_risk_eur: float) -> float:
    """Zelfde als compute_eval_daily_budget_remaining, maar tegen de
    nooit-resettende drawdown-ruimte (tier_amount, niet day_start_balance)."""
    drawdown_amount = evaluation["tier_amount"] * evaluation["max_drawdown_pct"] / 100
    drawdown_so_far = max(0.0, evaluation["tier_amount"] - evaluation["current_balance"])
    return max(0.0, drawdown_amount - drawdown_so_far - open_risk_eur)


def eval_sizing_blocked(evaluation: dict, open_risk_eur: float) -> bool:
    """True als het dagbudget of de drawdown-ruimte al zo goed als op is:
    dan heeft verder evaluatie-sizen geen zin meer, de trade valt terug op
    gewone portfolio-sizing en telt niet mee voor de evaluatie."""
    daily_budget = evaluation["day_start_balance"] * evaluation["max_daily_loss_pct"] / 100
    drawdown_budget = evaluation["tier_amount"] * evaluation["max_drawdown_pct"] / 100
    daily_remaining_pct = (
        compute_eval_daily_budget_remaining(evaluation, open_risk_eur) / daily_budget * 100
        if daily_budget else 0.0
    )
    drawdown_remaining_pct = (
        compute_eval_drawdown_budget_remaining(evaluation, open_risk_eur) / drawdown_budget * 100
        if drawdown_budget else 0.0
    )
    return (
        daily_remaining_pct < EVAL_BUDGET_BLOCK_THRESHOLD_PCT
        or drawdown_remaining_pct < EVAL_BUDGET_BLOCK_THRESHOLD_PCT
    )


def compute_eval_risk_eur(
    evaluation: dict, risk_percent: float, open_risk_eur: float,
    entry_price: float, stop_loss: float,
) -> float:
    """Risicobedrag voor één evaluatie-gesizede trade: het kleinste van de
    persoonlijke risk_percent-cap tegen het evaluatiesaldo, een derde van
    het resterend dagbudget, een derde van de resterende drawdown-ruimte,
    en de hefboomcap. Aanroeper checkt vooraf eval_sizing_blocked; deze
    functie zelf gaat er niet vanuit dat er nog voldoende budget is."""
    personal_cap = evaluation["current_balance"] * risk_percent / 100
    daily_share = compute_eval_daily_budget_remaining(evaluation, open_risk_eur) / EVAL_BUDGET_TRADE_RESERVE
    drawdown_share = compute_eval_drawdown_budget_remaining(evaluation, open_risk_eur) / EVAL_BUDGET_TRADE_RESERVE
    stop_distance = abs(entry_price - stop_loss)
    leverage_cap = (
        MAX_EVAL_LEVERAGE * evaluation["current_balance"] * stop_distance / entry_price
        if stop_distance > 0 and entry_price > 0 else float("inf")
    )
    return max(0.0, min(personal_cap, daily_share, drawdown_share, leverage_cap))
```

- [ ] **Step 2: Test met concrete cijfers**

```python
# scratchpad/test_task2_risk.py
import sys
sys.path.insert(0, "/home/user/Trade")
from app import risk

# Evaluatie: 10.000 tier, 3% dagverlies, 6% drawdown, nog geen verlies vandaag.
evaluation = {
    "current_balance": 10_000.0, "day_start_balance": 10_000.0,
    "max_daily_loss_pct": 3.0, "tier_amount": 10_000.0, "max_drawdown_pct": 6.0,
}

# compute_eval_daily_budget_remaining: 3% van 10.000 = 300, geen verlies, geen open risico.
assert risk.compute_eval_daily_budget_remaining(evaluation, 0.0) == 300.0

# compute_eval_drawdown_budget_remaining: 6% van 10.000 = 600.
assert risk.compute_eval_drawdown_budget_remaining(evaluation, 0.0) == 600.0

# eval_sizing_blocked: ruim boven de 5%-drempel, dus niet geblokkeerd.
assert risk.eval_sizing_blocked(evaluation, 0.0) is False

# compute_eval_risk_eur: risk_percent 1% van 10.000 = 100 (personal_cap).
# daily_share = 300 / 3 = 100. drawdown_share = 600 / 3 = 200.
# entry 100, stop 98 (afstand 2): leverage_cap = 5 * 10000 * 2 / 100 = 1000.
# Kleinste van (100, 100, 200, 1000) = 100.
risk_eur = risk.compute_eval_risk_eur(evaluation, risk_percent=1.0, open_risk_eur=0.0, entry_price=100.0, stop_loss=98.0)
assert risk_eur == 100.0, risk_eur

# Met al 250 open risico: dagbudget resterend = 300 - 0 - 250 = 50, gedeeld door 3 = 16.67.
# Dat is nu de kleinste (kleiner dan de 100 personal_cap), dus de trade wordt sterk verkleind.
risk_eur_with_open = risk.compute_eval_risk_eur(evaluation, risk_percent=1.0, open_risk_eur=250.0, entry_price=100.0, stop_loss=98.0)
assert abs(risk_eur_with_open - 50.0 / 3) < 0.01, risk_eur_with_open

# Na 285 verlies vandaag (dagbudget 300): resterend 15, dat is 5% van 300 exact —
# ONDER de 5%-drempel telt als geblokkeerd (strikt kleiner dan), dus 15/300*100=5.0 zelf blokkeert nog niet.
evaluation_near_limit = {**evaluation, "current_balance": 10_000.0 - 285.0}
assert risk.eval_sizing_blocked(evaluation_near_limit, 0.0) is False  # exact op de drempel, niet eronder

# Na 296 verlies: resterend 4, dat is 4/300*100 = 1.33% — wel geblokkeerd.
evaluation_over_limit = {**evaluation, "current_balance": 10_000.0 - 296.0}
assert risk.eval_sizing_blocked(evaluation_over_limit, 0.0) is True

print("Task 2: OK")
```

Run: `python3 scratchpad/test_task2_risk.py`
Expected: `Task 2: OK`.

- [ ] **Step 3: Commit**

```bash
git add app/risk.py
git commit -m "risk.py: sizing-formule en budget-blokkade voor evaluatie-trades"
```

---

### Task 3: risk.py — compute_position_size met cost_rate (fees/hefboomkosten bij sizing)

**Files:**
- Modify: `app/risk.py`
- Test: scratch script

**Interfaces:**
- Consumes: niets van Task 2.
- Produces: `EVAL_TRADE_FEE_RATE: float`, `EVAL_LEVERAGE_DAILY_RATE: float`,
  `EVAL_SIZING_DAYS_ASSUMPTION: float`,
  `compute_position_size(risk_eur, entry_price, stop_loss, cost_rate: float = 0.0) -> Optional[float]`
  (bestaande functie, uitgebreid met een NIEUWE optionele parameter,
  default `0.0` behoudt het bestaande gedrag voor elke bestaande aanroep).

- [ ] **Step 1: cost_rate-parameter toevoegen**

In `app/risk.py`:

```python
old = '''def compute_position_size(risk_eur: float, entry_price: float, stop_loss: float) -> Optional[float]:
    """Hoeveel coin je koopt bij dit risicobedrag: risicobedrag gedeeld door
    de afstand tussen entry en stop loss. Geeft None als die afstand nul is,
    wat niet zou moeten voorkomen maar voorkomt een deling door nul."""
    distance = abs(entry_price - stop_loss)
    if distance <= 0:
        return None
    return risk_eur / distance'''
new = '''# Round-trip handelsfee (open + sluiten) van een evaluatie-account, als
# fractie van de positiewaarde.
EVAL_TRADE_FEE_RATE = 0.0008
# Hefboom-/financieringskosten per dag dat een evaluatie-positie openstaat,
# als fractie van de positiewaarde.
EVAL_LEVERAGE_DAILY_RATE = 0.00033
# Voorzichtige aanname voor hoeveel dagen een trade openstaat, gebruikt om
# VOORAF (bij het bepalen van de positiegrootte) een hefboomkost in te
# schatten voor iets waarvan de werkelijke duur nog niet bekend is. Dit is
# een day-trading-systeem, de meeste trades zijn binnen een dag klaar; de
# WERKELIJKE kost wordt bij het sluiten opnieuw en exact berekend (zie
# repo.close_journal_trade), dus een te lage aanname hier wordt daar
# gecorrigeerd, niet stilzwijgend gemist.
EVAL_SIZING_DAYS_ASSUMPTION = 1.0


def compute_position_size(
    risk_eur: float, entry_price: float, stop_loss: float, cost_rate: float = 0.0,
) -> Optional[float]:
    """Hoeveel coin je koopt bij dit risicobedrag: risicobedrag gedeeld door
    de afstand tussen entry en stop loss, plus (voor evaluatie-trades) een
    kostenfractie van de positiewaarde die net zo goed "verlies" is als de
    pure prijsbeweging: fees en geschatte hefboomkosten. cost_rate is 0.0
    voor elke niet-evaluatie-trade (ongewijzigd gedrag). Geeft None als de
    stop-afstand nul is, wat niet zou moeten voorkomen maar voorkomt een
    deling door nul."""
    distance = abs(entry_price - stop_loss)
    if distance <= 0:
        return None
    return risk_eur / (distance + entry_price * cost_rate)'''
```

- [ ] **Step 2: Test — bestaand gedrag ongewijzigd + fee verkleint positiegrootte**

```python
# scratchpad/test_task3_position_size.py
import sys
sys.path.insert(0, "/home/user/Trade")
from app import risk

# Regressie: bestaande aanroepen zonder cost_rate blijven exact hetzelfde resultaat geven.
assert risk.compute_position_size(100.0, 50.0, 49.0) == 100.0  # 100 / 1

# Met cost_rate: entry 50, distance 1, cost_rate = 0.0008 + 0.00033 = 0.00113.
# 100 / (1 + 50 * 0.00113) = 100 / 1.0565 = 94.65...
cost_rate = risk.EVAL_TRADE_FEE_RATE + risk.EVAL_LEVERAGE_DAILY_RATE * risk.EVAL_SIZING_DAYS_ASSUMPTION
size_with_fee = risk.compute_position_size(100.0, 50.0, 49.0, cost_rate=cost_rate)
size_without_fee = risk.compute_position_size(100.0, 50.0, 49.0)
assert size_with_fee < size_without_fee, "fee moet de positie verkleinen, niet vergroten"
expected = 100.0 / (1.0 + 50.0 * cost_rate)
assert abs(size_with_fee - expected) < 1e-9

# Afstand nul blijft None geven, met of zonder cost_rate.
assert risk.compute_position_size(100.0, 50.0, 50.0) is None
assert risk.compute_position_size(100.0, 50.0, 50.0, cost_rate=0.001) is None

print("Task 3: OK")
```

Run: `python3 scratchpad/test_task3_position_size.py`
Expected: `Task 3: OK`.

- [ ] **Step 3: Commit**

```bash
git add app/risk.py
git commit -m "risk.py: compute_position_size houdt rekening met fees/hefboomkosten (cost_rate)"
```

---

### Task 4: repo.py — position_size opslaan bij aanmaken, entry_time bij nemen

**Files:**
- Modify: `app/repo.py` (`create_journal_entry`, `update_journal_status`, rond regel 931-940 en 1038-1051)
- Test: scratch script

**Interfaces:**
- Consumes: `_JOURNAL_SELECT` inclusief `entry_time`/`position_size` uit Task 1.
- Produces: `create_journal_entry(signal_id, user_id, risk_eur, evaluation_id=None, position_size=None) -> int`
  (nieuwe optionele parameter `position_size`), `update_journal_status`
  zet voortaan óók `entry_time` zodra `entry_price` wordt meegegeven (geen
  signatuurwijziging, geen enkele aanroeper hoeft aangepast).

- [ ] **Step 1: create_journal_entry krijgt position_size-parameter**

```python
old = '''def create_journal_entry(
    signal_id: int, user_id: int, risk_eur: float, evaluation_id: Optional[int] = None,
) -> int:
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO journal_entries (signal_id, user_id, risk_eur, created_at, evaluation_id)
               VALUES (?, ?, ?, ?, ?)""",
            (signal_id, user_id, risk_eur, db.now_iso(), evaluation_id),
        )
        return cur.lastrowid'''
new = '''def create_journal_entry(
    signal_id: int, user_id: int, risk_eur: float,
    evaluation_id: Optional[int] = None, position_size: Optional[float] = None,
) -> int:
    """position_size is de daadwerkelijk gebruikte positiegrootte (na alle
    caps en, voor evaluatie-trades, de fee-aanpassing in
    risk.compute_position_size). Opgeslagen zodat close_journal_trade bij
    het sluiten precies dezelfde positiegrootte gebruikt voor de
    fee-verrekening, in plaats van een losse herberekening die uit de pas
    kan lopen met wat er werkelijk gesized is."""
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO journal_entries (signal_id, user_id, risk_eur, created_at, evaluation_id, position_size)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (signal_id, user_id, risk_eur, db.now_iso(), evaluation_id, position_size),
        )
        return cur.lastrowid'''
```

- [ ] **Step 2: update_journal_status zet entry_time samen met entry_price**

```python
old = '''def update_journal_status(
    entry_id: int, user_id: int, status: str, entry_price: Optional[float] = None,
) -> None:
    with db.session() as conn:
        if entry_price is not None:
            conn.execute(
                "UPDATE journal_entries SET status = ?, entry_price = ? WHERE id = ? AND user_id = ?",
                (status, entry_price, entry_id, user_id),
            )
        else:
            conn.execute(
                "UPDATE journal_entries SET status = ? WHERE id = ? AND user_id = ?",
                (status, entry_id, user_id),
            )'''
new = '''def update_journal_status(
    entry_id: int, user_id: int, status: str, entry_price: Optional[float] = None,
) -> None:
    """Zet entry_time altijd samen met entry_price: het moment waarop een
    trade daadwerkelijk genomen wordt, nodig om bij het sluiten de
    werkelijke hefboomkosten van een evaluatie-trade te berekenen (zie
    close_journal_trade). Geen aparte parameter: elke bestaande aanroeper
    die al entry_price meegeeft omdat de trade genomen wordt, krijgt dit
    gratis mee."""
    with db.session() as conn:
        if entry_price is not None:
            conn.execute(
                """UPDATE journal_entries SET status = ?, entry_price = ?, entry_time = ?
                   WHERE id = ? AND user_id = ?""",
                (status, entry_price, db.now_iso(), entry_id, user_id),
            )
        else:
            conn.execute(
                "UPDATE journal_entries SET status = ? WHERE id = ? AND user_id = ?",
                (status, entry_id, user_id),
            )'''
```

- [ ] **Step 3: Test**

```python
# scratchpad/test_task4_repo.py
import os
os.environ["DATABASE_PATH"] = "/tmp/task4_scratch.db"
if os.path.exists("/tmp/task4_scratch.db"):
    os.remove("/tmp/task4_scratch.db")

from app import db, repo

db.init_db()
user_id = repo.create_user("test4", "wachtwoord123", 1000.0, 1.0, None)
message_id = repo.insert_message("test", [])
repo.mark_message_processed(message_id, "BTC", "long", "day_trading", False, note=None)
signal_id = repo.insert_signal({
    "message_id": message_id, "coin": "BTC", "direction": "long",
    "category": "day_trading", "price": 100.0, "rsi": 50.0, "macd": 0.0,
    "macd_signal": 0.0, "volume_ratio": 1.0, "ema9": 100.0, "ema21": 100.0,
    "atr": 1.0, "atr_avg20": 1.0, "adx": 25.0, "technical_confirmed": 1,
    "confidence": "hoog vertrouwen", "reason": "test", "stop_loss": 98.0,
    "take_profit": 104.0, "context_note": None, "is_practice": 0,
    "plain_explanation": None,
})

entry_id = repo.create_journal_entry(signal_id, user_id, risk_eur=20.0, position_size=10.0)
entry = repo.get_journal_entry(entry_id, user_id)
assert entry["position_size"] == 10.0, entry["position_size"]
assert entry["entry_time"] is None, "nog niet genomen, dus nog geen entry_time"

repo.update_journal_status(entry_id, user_id, "genomen", entry_price=99.0)
entry_after = repo.get_journal_entry(entry_id, user_id)
assert entry_after["entry_time"] is not None, "entry_time moet gezet zijn zodra entry_price gezet wordt"

print("Task 4: OK")
```

Run: `DATABASE_PATH=/tmp/task4_scratch.db python3 scratchpad/test_task4_repo.py`
Expected: `Task 4: OK`.

- [ ] **Step 4: Commit**

```bash
git add app/repo.py
git commit -m "repo.py: create_journal_entry slaat position_size op, update_journal_status zet entry_time"
```

---

### Task 5: repo.py — fee/hefboomkosten verrekenen bij close_journal_trade

**Files:**
- Modify: `app/repo.py` (`close_journal_trade`, rond regel 1220-1265)
- Test: scratch script

**Interfaces:**
- Consumes: `entry["position_size"]`, `entry["entry_time"]` uit Task 1+4;
  `risk.EVAL_TRADE_FEE_RATE`, `risk.EVAL_LEVERAGE_DAILY_RATE` uit Task 3.
- Produces: `close_journal_trade` trekt bij een evaluatie-trade
  (`evaluation_id is not None`) de werkelijke fee- en hefboomkosten af van
  `result_eur` vóórdat dat bedrag wordt opgeslagen en bij de evaluatie
  wordt meegeteld. Signatuur en return-type ongewijzigd:
  `close_journal_trade(entry_id, user_id, exit_price, exit_time) -> tuple[float, bool, Optional[int]]`.

- [ ] **Step 1: Fee/hefboomkosten aftrekken in close_journal_trade**

`app/repo.py` importeert bovenaan al `from datetime import datetime,
timedelta, timezone` en `from app import config, db, risk` — beide nodig
voor deze stap zijn al aanwezig, geen nieuwe import nodig.

```python
old = '''    if risk_per_unit and risk_per_unit > 0:
        move = (exit_price - entry_price) if direction == "long" else (entry_price - exit_price)
        result_eur = risk_eur * (move / risk_per_unit)
    else:
        result_eur = risk_eur * (result_pct / 100)

    with db.session() as conn:'''
new = '''    if risk_per_unit and risk_per_unit > 0:
        move = (exit_price - entry_price) if direction == "long" else (entry_price - exit_price)
        result_eur = risk_eur * (move / risk_per_unit)
    else:
        result_eur = risk_eur * (result_pct / 100)

    # Fees en hefboomkosten van een Kraken Prop-achtig evaluatie-account
    # gelden alleen voor trades die aan een evaluatie hangen; een gewone
    # portfolio-trade kent dit systeem niet en result_eur blijft daar
    # ongewijzigd, exact het bestaande gedrag.
    if entry["evaluation_id"] is not None:
        notional_eur = (entry["position_size"] or 0.0) * entry_price
        trade_fee_eur = notional_eur * risk.EVAL_TRADE_FEE_RATE
        days_held = 0.0
        if entry["entry_time"]:
            days_held = max(
                0.0,
                (datetime.fromisoformat(exit_time) - datetime.fromisoformat(entry["entry_time"])).total_seconds() / 86400,
            )
        leverage_cost_eur = notional_eur * risk.EVAL_LEVERAGE_DAILY_RATE * days_held
        result_eur -= (trade_fee_eur + leverage_cost_eur)

    with db.session() as conn:'''
```

- [ ] **Step 2: Test — concreet dagen-scenario**

```python
# scratchpad/test_task5_close.py
import os
os.environ["DATABASE_PATH"] = "/tmp/task5_scratch.db"
if os.path.exists("/tmp/task5_scratch.db"):
    os.remove("/tmp/task5_scratch.db")

from datetime import datetime, timedelta, timezone
from app import db, repo

db.init_db()
user_id = repo.create_user("test5", "wachtwoord123", 10_000.0, 1.0, None)
eval_id = repo.create_evaluation(user_id, tier_amount=10_000.0, profit_target_pct=8.0, max_drawdown_pct=6.0)

message_id = repo.insert_message("test", [])
repo.mark_message_processed(message_id, "BTC", "long", "day_trading", False, note=None)
signal_id = repo.insert_signal({
    "message_id": message_id, "coin": "BTC", "direction": "long",
    "category": "day_trading", "price": 100.0, "rsi": 50.0, "macd": 0.0,
    "macd_signal": 0.0, "volume_ratio": 1.0, "ema9": 100.0, "ema21": 100.0,
    "atr": 1.0, "atr_avg20": 1.0, "adx": 25.0, "technical_confirmed": 1,
    "confidence": "hoog vertrouwen", "reason": "test", "stop_loss": 98.0,
    "take_profit": 104.0, "context_note": None, "is_practice": 0,
    "plain_explanation": None,
})

# Positie: 50 stuks a 100 = 5000 notional. risk_eur = 50 * (100-98) = 100.
entry_id = repo.create_journal_entry(signal_id, user_id, risk_eur=100.0, evaluation_id=eval_id, position_size=50.0)
entry_time = datetime.now(timezone.utc) - timedelta(days=2)
repo.update_journal_status(entry_id, user_id, "genomen", entry_price=100.0)
# entry_time hierboven is net op "nu" gezet door update_journal_status; voor een
# betrouwbaar dagen-scenario zetten we 'm hier expliciet 2 dagen terug.
with db.session() as conn:
    conn.execute("UPDATE journal_entries SET entry_time = ? WHERE id = ?", (entry_time.isoformat(), entry_id))

exit_time = datetime.now(timezone.utc).isoformat()
result_eur, is_practice, evaluation_id = repo.close_journal_trade(entry_id, user_id, exit_price=104.0, exit_time=exit_time)

# Zonder fees: move = 4, risk_per_unit = 2, result_eur = 100 * (4/2) = 200 (2x risk, take profit geraakt).
# notional = 50 * 100 = 5000. trade_fee = 5000 * 0.0008 = 4.0.
# days_held ~ 2.0 (kleine afwijking door test-timing is ok). leverage_cost = 5000 * 0.00033 * 2 = 3.3.
# Verwacht result_eur ~ 200 - 4.0 - 3.3 = 192.7, met wat marge voor de exacte dagen-telling.
assert 190.0 < result_eur < 195.0, result_eur
assert evaluation_id == eval_id

print(f"Task 5: OK (result_eur={result_eur:.2f})")
```

Run: `DATABASE_PATH=/tmp/task5_scratch.db python3 scratchpad/test_task5_close.py`
Expected: `Task 5: OK (result_eur=...)` binnen de asserted range.

- [ ] **Step 3: Regressietest — niet-evaluatie-trade blijft ongewijzigd**

```python
# Zelfde script, extra check: een journal_entry ZONDER evaluation_id
entry_id_no_eval = repo.create_journal_entry(signal_id, user_id, risk_eur=100.0, position_size=50.0)
repo.update_journal_status(entry_id_no_eval, user_id, "genomen", entry_price=100.0)
result_eur_no_eval, _, evaluation_id_none = repo.close_journal_trade(
    entry_id_no_eval, user_id, exit_price=104.0, exit_time=datetime.now(timezone.utc).isoformat(),
)
assert evaluation_id_none is None
assert result_eur_no_eval == 200.0, "geen evaluatie gekoppeld, dus geen fee-aftrek, exact 2x risk"
print("Task 5 regressie: OK")
```

- [ ] **Step 4: Commit**

```bash
git add app/repo.py
git commit -m "repo.py: close_journal_trade verrekent werkelijke fees/hefboomkosten voor evaluatie-trades"
```

---

### Task 6: signal_processor.py — echte signalen koppelen aan de evaluatie

**Files:**
- Modify: `app/signal_processor.py` (dagtrading-fanout rond regel 758-810, swing-fanout rond regel 455-474)
- Test: scratch integratietest met gemockte exchange

**Interfaces:**
- Consumes: `repo.get_active_evaluation(user_id)`,
  `repo.total_open_risk_eur_for_evaluation(evaluation_id)`,
  `risk.eval_sizing_blocked`, `risk.compute_eval_risk_eur`,
  `risk.compute_position_size(..., cost_rate=...)`,
  `repo.create_journal_entry(..., evaluation_id=..., position_size=...)`
  — allemaal uit Taken 2-4.
- Produces: een real-world signaal voor een gebruiker met een actieve,
  niet-geblokkeerde evaluatie krijgt voortaan `evaluation_id` gezet op zijn
  `journal_entries`-rij en is gesized volgens `risk.compute_eval_risk_eur`
  in plaats van `risk.compute_risk_eur(portfolio_eur, risk_percent)`.

- [ ] **Step 1: Nieuwe helper _resolve_signal_risk in signal_processor.py**

Eén gedeelde helper voor beide fanout-plekken (dagtrading en swing),
zodat de evaluatie-logica maar op één plek staat:

```python
def _resolve_signal_risk(
    user: dict, entry_price: float, stop_loss: float,
) -> tuple[float, Optional[int], Optional[float]]:
    """Risicobedrag, evaluation_id (of None) en cost_rate (voor
    compute_position_size) voor één signaal aan één gebruiker. Gebruikt de
    actieve evaluatie als sizing-basis zodra die er is en er nog voldoende
    budget is; valt anders terug op het bestaande portfolio_eur x
    risk_percent-gedrag, exact ongewijzigd."""
    active_eval = repo.get_active_evaluation(user["id"])
    if active_eval:
        open_risk_eur = repo.total_open_risk_eur_for_evaluation(active_eval["id"])
        if not risk.eval_sizing_blocked(active_eval, open_risk_eur):
            risk_eur = risk.compute_eval_risk_eur(
                active_eval, user["risk_percent"], open_risk_eur, entry_price, stop_loss,
            )
            cost_rate = risk.EVAL_TRADE_FEE_RATE + risk.EVAL_LEVERAGE_DAILY_RATE * risk.EVAL_SIZING_DAYS_ASSUMPTION
            return risk_eur, active_eval["id"], cost_rate
    return risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"]), None, 0.0
```

Plaats deze functie boven `handle_message` of vlak boven de eerste van de
twee plekken die 'm gebruiken (bijvoorbeeld direct boven de functie die de
swing-fanout doet, rond regel 400-410 — zoek de functie-definitie die de
`for user in repo.list_users():`-lus rond regel 455 bevat).

- [ ] **Step 2: Swing-fanout gebruiken (rond regel 455-457)**

```python
old = '''    for user in repo.list_users():
        risk_eur = risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"])
        entry_id = repo.create_journal_entry(signal_id, user["id"], risk_eur)
        if not user["telegram_chat_id"]:
            continue'''
new = '''    for user in repo.list_users():
        risk_eur, evaluation_id, cost_rate = _resolve_signal_risk(user, ind_4h.price, stop_take.stop_loss)
        position_size = risk.compute_position_size(risk_eur, ind_4h.price, stop_take.stop_loss, cost_rate=cost_rate)
        entry_id = repo.create_journal_entry(
            signal_id, user["id"], risk_eur, evaluation_id=evaluation_id, position_size=position_size,
        )
        if not user["telegram_chat_id"]:
            continue'''
```

- [ ] **Step 3: Dagtrading-fanout gebruiken (rond regel 770-786)**

Let op: hier wordt `position_size` vandaag pas ná `create_journal_entry`
berekend (alleen voor de Telegram-melding, niet opgeslagen). Dat verandert:
`position_size` wordt nu VOOR `create_journal_entry` berekend en
meegegeven, zodat de kolom uit Task 1 gevuld wordt.

```python
old = '''        risk_eur = risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"])
        entry_id = repo.create_journal_entry(signal_id, user["id"], risk_eur)

        if not user["telegram_chat_id"]:
            logger.info("Gebruiker %s heeft geen telegram_chat_id, geen melding verstuurd",
                        user["username"])
            continue

        if muted:
            # De logboekregel bestaat al (hierboven aangemaakt): trackrecord
            # en dashboard-cijfers blijven kloppen, alleen de Telegram-melding
            # zelf wordt overgeslagen, dat is precies wat "uitzetten" betekent.
            logger.info("Coin %s is gemute voor gebruiker %s, geen Telegram-melding verstuurd",
                        interp.coin, user["username"])
            continue

        position_size = risk.compute_position_size(risk_eur, ind.price, stop_take.stop_loss) if confirmed else None'''
new = '''        risk_eur, evaluation_id, cost_rate = _resolve_signal_risk(user, ind.price, stop_take.stop_loss)
        position_size = (
            risk.compute_position_size(risk_eur, ind.price, stop_take.stop_loss, cost_rate=cost_rate)
            if confirmed else None
        )
        entry_id = repo.create_journal_entry(
            signal_id, user["id"], risk_eur, evaluation_id=evaluation_id, position_size=position_size,
        )

        if not user["telegram_chat_id"]:
            logger.info("Gebruiker %s heeft geen telegram_chat_id, geen melding verstuurd",
                        user["username"])
            continue

        if muted:
            # De logboekregel bestaat al (hierboven aangemaakt): trackrecord
            # en dashboard-cijfers blijven kloppen, alleen de Telegram-melding
            # zelf wordt overgeslagen, dat is precies wat "uitzetten" betekent.
            logger.info("Coin %s is gemute voor gebruiker %s, geen Telegram-melding verstuurd",
                        interp.coin, user["username"])
            continue'''
```

Een niet-bevestigd signaal (`confirmed == False`) heeft geen bruikbare
`stop_take.stop_loss` als executeerbare trade, maar `_resolve_signal_risk`
wordt hier toch vóór de `confirmed`-check aangeroepen (voor de
evaluatie-sizing zelf maakt bevestigd/afgewezen niets uit, dat bepaalt
alleen of er een `position_size` getoond wordt). Dit is bewust ongewijzigd
gedrag: `risk_eur` werd ook vóór dit plan altijd berekend, ongeacht
`confirmed`.

- [ ] **Step 4: Integratietest — evaluatie-koppeling met gemockte exchange**

```python
# scratchpad/test_task6_integration.py
import os
os.environ["DATABASE_PATH"] = "/tmp/task6_scratch.db"
os.environ.setdefault("ENABLE_ADVANCED_FACTORS", "false")
if os.path.exists("/tmp/task6_scratch.db"):
    os.remove("/tmp/task6_scratch.db")

import asyncio
from unittest.mock import patch
import numpy as np
import pandas as pd
from app import db, repo, signal_processor
from app.anthropic_interpret import Interpretation

db.init_db()
user_id = repo.create_user("test6", "wachtwoord123", 5000.0, 2.0, "123456")
eval_id = repo.create_evaluation(user_id, tier_amount=10_000.0, profit_target_pct=8.0, max_drawdown_pct=6.0)

# Duidelijke uptrend zodat confirms_direction("long", ...) True teruggeeft
# (EMA9 > EMA21, RSI in een neutrale zone, MACD boven signaal, voldoende
# volume) — 60 4h-candles is ruim genoeg voor alle indicatoren in
# app/indicators.py om een stabiele waarde te hebben.
n = 60
closes = np.linspace(90, 110, n)
df = pd.DataFrame({
    "open": closes, "high": closes + 1, "low": closes - 1, "close": closes,
    "volume": [1000.0] * n,
}, index=pd.date_range("2026-01-01", periods=n, freq="4h"))

with patch("app.exchange.market_exists", return_value=True), \
     patch("app.exchange.to_symbol", return_value="BTC/EUR"), \
     patch("app.exchange.fetch_ohlcv", return_value=df):
    interp = Interpretation(
        coin="BTC", direction="long", category="day_trading", unclear=False,
        reason="", source_levels=[],
    )
    message_id = repo.insert_message("test signaal", [])
    asyncio.run(signal_processor._process_one_coin(message_id, "test signaal", interp))

entries = repo.list_journal(user_id)
assert len(entries) == 1, entries
entry = entries[0]
assert entry["evaluation_id"] == eval_id, "moet aan de actieve evaluatie gekoppeld zijn"
assert entry["position_size"] is not None

print(f"Task 6: OK (risk_eur={entry['risk_eur']:.2f}, confirmed={entry['technical_confirmed']}, evaluation_id={entry['evaluation_id']})")
```

Als `confirmed` hier `0` uitkomt (de synthetische candles halen de
technische toetsing niet), is `position_size` `None` (zie Step 3's
`if confirmed else None`) en faalt de laatste assert met opzet — pas dan
de synthetische reeks aan (bijvoorbeeld een langere, sterkere uptrend) tot
`indicators.confirms_direction("long", ind, ...)` `True` teruggeeft; dat
is een test-databug, geen productiecodebug. De koppeling aan de evaluatie
(`entry["evaluation_id"] == eval_id`) geldt overigens ONGEACHT `confirmed`
— dat is precies wat Step 3 hierboven bewust zo bouwt (risk_eur en
evaluation_id worden altijd bepaald, position_size alleen bij een
bevestigde kans).

Run: `DATABASE_PATH=/tmp/task6_scratch.db python3 scratchpad/test_task6_integration.py`
Expected: `Task 6: OK (...)`.

- [ ] **Step 5: Commit**

```bash
git add app/signal_processor.py
git commit -m "signal_processor.py: echte signalen sizen en tellen mee op een actieve evaluatie"
```

---

### Task 7: web/main.py — oefentrades gelijk trekken

**Files:**
- Modify: `web/main.py` (`_resolve_practice_risk_eur` rond regel 1076-1104
  vervalt, `MAX_EVAL_LEVERAGE`-constante rond regel 1003 vervalt,
  oefen-preview-route rond regel 1107-1145, oefentrade-aanmaakroute rond
  regel 1150-1203)

**Interfaces:**
- Consumes: `risk.MAX_EVAL_LEVERAGE`, `risk.eval_sizing_blocked`,
  `risk.compute_eval_risk_eur`, `risk.compute_position_size(...,
  cost_rate=...)` uit Taken 2-3.
- Produces: beide oefentrade-routes gebruiken dezelfde evaluatie-sizing-
  functies als echte signalen; `manual_risk_eur` (handmatige invoer) wordt
  nu ook gecapt door de dagbudget/drawdown-grenzen, niet alleen door de
  hefboomcap.

- [ ] **Step 1: MAX_EVAL_LEVERAGE-constante verwijderen**

```python
old = '''MAX_EVAL_LEVERAGE = 5.0'''
new = ''  # verwijderd, verhuisd naar app/risk.py in Task 2'''
```

Zoek de exacte regel (`grep -n "^MAX_EVAL_LEVERAGE" web/main.py`) en
verwijder 'm; elders in het bestand die nu `MAX_EVAL_LEVERAGE` gebruiken
verwijzen voortaan naar `risk.MAX_EVAL_LEVERAGE` (zie Step 2).

- [ ] **Step 2: _resolve_practice_risk_eur vervangen door een gedeelde helper**

```python
old = '''def _resolve_practice_risk_eur(
    user: dict, active_eval: Optional[dict], manual_risk_eur: Optional[float],
    entry_price: float, stop_loss: float,
) -> tuple[float, Optional[str], bool, Optional[float]]:
    """Risicobedrag voor een oefentrade: handmatige invoer gaat voor de
    automatische berekening op basis van je echte portefeuille (die heeft
    geen relatie met het saldo van een lopende evaluatie-run). Bij een
    actieve evaluatie wordt het resultaat bovendien gecapt op
    MAX_EVAL_LEVERAGE x het evaluatiesaldo, exact de regel van de echte
    Kraken Prop. Geeft (risk_eur, notitie-of-None, is-gecapt, max-toegestaan-of-None)."""
    computed_risk_eur = (
        manual_risk_eur if manual_risk_eur is not None
        else risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"])
    )
    leverage_note = None
    capped = False
    max_risk_eur = None
    if active_eval:
        stop_distance = abs(entry_price - stop_loss)
        if stop_distance > 0 and entry_price > 0:
            max_risk_eur = MAX_EVAL_LEVERAGE * active_eval["current_balance"] * stop_distance / entry_price
            if computed_risk_eur > max_risk_eur > 0:
                capped = True
                leverage_note = (
                    f"Systeem: risico verlaagd van €{computed_risk_eur:.2f} naar €{max_risk_eur:.2f} "
                    f"om binnen de {MAX_EVAL_LEVERAGE:.0f}x hefboomlimiet van de evaluatie te blijven."
                )
                computed_risk_eur = max_risk_eur
    return computed_risk_eur, leverage_note, capped, max_risk_eur'''
new = '''def _resolve_practice_risk_eur(
    user: dict, active_eval: Optional[dict], manual_risk_eur: Optional[float],
    entry_price: float, stop_loss: float,
) -> tuple[float, Optional[str], bool, Optional[float], float]:
    """Risicobedrag voor een oefentrade, en cost_rate voor de fee-aanpassing
    van compute_position_size (Task 3). Zonder actieve evaluatie: exact
    zoals bij een echt signaal zonder evaluatie, handmatige invoer of
    portfolio_eur x risk_percent, geen fees. Met actieve evaluatie: dezelfde
    dagbudget/drawdown/hefboom-grenzen als een echt signaal
    (risk.compute_eval_risk_eur), en handmatige invoer wordt daar nu OOK
    door gecapt, niet alleen door de hefboomlimiet. Geeft (risk_eur,
    notitie-of-None, is-gecapt, max-toegestaan-of-None, cost_rate)."""
    if not active_eval:
        computed_risk_eur = (
            manual_risk_eur if manual_risk_eur is not None
            else risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"])
        )
        return computed_risk_eur, None, False, None, 0.0

    open_risk_eur = repo.total_open_risk_eur_for_evaluation(active_eval["id"])
    if risk.eval_sizing_blocked(active_eval, open_risk_eur):
        leverage_note = "Systeem: dagbudget of drawdown-ruimte van je evaluatie is (bijna) op, deze oefentrade telt niet mee."
        computed_risk_eur = manual_risk_eur if manual_risk_eur is not None else 0.0
        return computed_risk_eur, leverage_note, True, 0.0, 0.0

    max_risk_eur = risk.compute_eval_risk_eur(
        active_eval, user["risk_percent"], open_risk_eur, entry_price, stop_loss,
    )
    cost_rate = risk.EVAL_TRADE_FEE_RATE + risk.EVAL_LEVERAGE_DAILY_RATE * risk.EVAL_SIZING_DAYS_ASSUMPTION
    requested_risk_eur = manual_risk_eur if manual_risk_eur is not None else max_risk_eur
    capped = requested_risk_eur > max_risk_eur > 0
    computed_risk_eur = min(requested_risk_eur, max_risk_eur) if max_risk_eur > 0 else requested_risk_eur
    leverage_note = (
        f"Systeem: risico verlaagd van €{requested_risk_eur:.2f} naar €{computed_risk_eur:.2f} "
        f"om binnen de regels van je evaluatie te blijven."
    ) if capped else None
    return computed_risk_eur, leverage_note, capped, max_risk_eur, cost_rate'''
```

Deze functie retourneert nu 5 waarden in plaats van 4 (`cost_rate`
toegevoegd) — beide aanroepers (Step 3 en Step 4) moeten mee-updaten.

- [ ] **Step 3: oefen-preview-route (rond regel 1107-1145)**

```python
old = '''    _df, ind, stop_take = await _fetch_practice_trade_calc(symbol, direction)
    active_eval = repo.get_active_evaluation(user["id"])
    used_risk_eur, leverage_note, capped, max_risk_eur = _resolve_practice_risk_eur(
        user, active_eval, manual_risk_eur, ind.price, stop_take.stop_loss,
    )
    position_size = risk.compute_position_size(used_risk_eur, ind.price, stop_take.stop_loss)
    notional_eur = (position_size * ind.price) if position_size else None'''
new = '''    _df, ind, stop_take = await _fetch_practice_trade_calc(symbol, direction)
    active_eval = repo.get_active_evaluation(user["id"])
    used_risk_eur, leverage_note, capped, max_risk_eur, cost_rate = _resolve_practice_risk_eur(
        user, active_eval, manual_risk_eur, ind.price, stop_take.stop_loss,
    )
    position_size = risk.compute_position_size(used_risk_eur, ind.price, stop_take.stop_loss, cost_rate=cost_rate)
    notional_eur = (position_size * ind.price) if position_size else None'''
```

- [ ] **Step 4: oefentrade-aanmaakroute (rond regel 1150-1203)**

```python
old = '''    active_eval = repo.get_active_evaluation(user["id"])
    manual_risk_eur = _parse_optional_float(risk_eur)
    computed_risk_eur, leverage_note, _capped, _max_risk_eur = _resolve_practice_risk_eur(
        user, active_eval, manual_risk_eur, ind.price, stop_take.stop_loss,
    )

    entry_id = repo.create_journal_entry(
        signal_id, user["id"], computed_risk_eur, evaluation_id=active_eval["id"] if active_eval else None,
    )
    repo.update_journal_status(entry_id, user["id"], "genomen", entry_price=ind.price)
    if leverage_note:
        repo.update_journal_note(entry_id, user["id"], leverage_note)'''
new = '''    active_eval = repo.get_active_evaluation(user["id"])
    manual_risk_eur = _parse_optional_float(risk_eur)
    computed_risk_eur, leverage_note, _capped, _max_risk_eur, cost_rate = _resolve_practice_risk_eur(
        user, active_eval, manual_risk_eur, ind.price, stop_take.stop_loss,
    )
    position_size = risk.compute_position_size(computed_risk_eur, ind.price, stop_take.stop_loss, cost_rate=cost_rate)

    entry_id = repo.create_journal_entry(
        signal_id, user["id"], computed_risk_eur,
        evaluation_id=active_eval["id"] if active_eval else None, position_size=position_size,
    )
    repo.update_journal_status(entry_id, user["id"], "genomen", entry_price=ind.price)
    if leverage_note:
        repo.update_journal_note(entry_id, user["id"], leverage_note)'''
```

- [ ] **Step 5: Handmatige Playwright-verificatie**

Start de webserver tegen een scratch-database met een actieve evaluatie
en test via een browser:

```bash
DATABASE_PATH=/tmp/task7_manual.db uvicorn web.main:app --reload --port 8001
```

Maak (via `scripts/create_user.py` of een los scratch-script) een
gebruiker met een actieve evaluatie aan, log in, open een coin-pagina, en
maak een oefentrade aan. Controleer:
1. Het risicobedrag op het oefentrade-formulier verandert zichtbaar
   tegenover een gebruiker ZONDER actieve evaluatie (kleiner, door de
   dagbudget-deling).
2. Na het aanmaken staat de trade op het dashboard met een zichtbaar
   risicobedrag, geen crash, geen `None`-waarden in de UI.
3. Zet de evaluatie's `current_balance` in de database handmatig dicht bij
   de dagverlies-drempel (bijvoorbeeld via een scratch-script met
   `repo`-functies) en herhaal: het formulier moet nu de
   "dagbudget (bijna) op"-notitie tonen.

- [ ] **Step 6: Commit**

```bash
git add web/main.py
git commit -m "web/main.py: oefentrades gebruiken dezelfde evaluatie-sizing-formule als echte signalen"
```

---

### Task 8: Zichtbaarheid — Telegram-bericht en dashboard

**Files:**
- Modify: `app/telegram_notify.py` (`format_signal_message`, rond regel 124-151; nieuwe helperfuncties naast `_open_risk_line`, rond regel 75-77)
- Modify: `app/signal_processor.py` (dagtrading-fanout, `signal_data`-dict die aan `send_signal` wordt doorgegeven, rond regel 803-808)
- Modify: `web/main.py` (`_build_eval_context`, rond regel 255-330)
- Test: scratch script voor de telegram-formatter, handmatige controle van het dashboard

**Interfaces:**
- Consumes: `risk.EVAL_BUDGET_TRADE_RESERVE` uit Task 2.
- Produces: `format_signal_message` toont een regel met het aandeel van het
  dagbudget als `signal.get("eval_budget_pct")` gezet is, en een blokkade-
  regel als `signal.get("eval_blocked_note")` gezet is. `_build_eval_context`
  geeft een extra sleutel `eval_next_trade_budget_eur` terug.

- [ ] **Step 1: Nieuwe regel-helpers in telegram_notify.py**

```python
old = '''def _open_risk_line(open_risk_pct: float) -> str:
    marker = "⚠️" if open_risk_pct >= OPEN_RISK_WARNING_PCT else "📊"
    return f"{marker} Dit zou je totale open risico op {open_risk_pct:.1f}% van je portfolio brengen."'''
new = '''def _open_risk_line(open_risk_pct: float) -> str:
    marker = "⚠️" if open_risk_pct >= OPEN_RISK_WARNING_PCT else "📊"
    return f"{marker} Dit zou je totale open risico op {open_risk_pct:.1f}% van je portfolio brengen."


def _eval_budget_line(risk_eur: float, eval_budget_pct: float) -> str:
    return f"🎯 Evaluatie: risico €{risk_eur:.2f} — {eval_budget_pct:.0f}% van je resterende dagbudget."


def _eval_blocked_line(note: str) -> str:
    return f"⛔ {note}"'''
```

- [ ] **Step 2: format_signal_message toont de nieuwe regels**

```python
old = '''    if signal.get("open_risk_pct") is not None:
        lines += ["", _open_risk_line(signal["open_risk_pct"])]'''
new = '''    if signal.get("open_risk_pct") is not None:
        lines += ["", _open_risk_line(signal["open_risk_pct"])]
    if signal.get("eval_budget_pct") is not None:
        lines += ["", _eval_budget_line(signal["risk_eur"], signal["eval_budget_pct"])]
    if signal.get("eval_blocked_note"):
        lines += ["", _eval_blocked_line(signal["eval_blocked_note"])]'''
```

- [ ] **Step 3: signal_processor.py vult eval_budget_pct/eval_blocked_note**

In de dagtrading-fanout, waar `_resolve_signal_risk` nu al wordt
aangeroepen (Task 6, Step 3), voeg de weergave-info toe vóór
`send_signal` wordt aangeroepen:

```python
old = '''        risk_eur, evaluation_id, cost_rate = _resolve_signal_risk(user, ind.price, stop_take.stop_loss)
        position_size = (
            risk.compute_position_size(risk_eur, ind.price, stop_take.stop_loss, cost_rate=cost_rate)
            if confirmed else None
        )
        entry_id = repo.create_journal_entry(
            signal_id, user["id"], risk_eur, evaluation_id=evaluation_id, position_size=position_size,
        )'''
new = '''        risk_eur, evaluation_id, cost_rate = _resolve_signal_risk(user, ind.price, stop_take.stop_loss)
        position_size = (
            risk.compute_position_size(risk_eur, ind.price, stop_take.stop_loss, cost_rate=cost_rate)
            if confirmed else None
        )
        entry_id = repo.create_journal_entry(
            signal_id, user["id"], risk_eur, evaluation_id=evaluation_id, position_size=position_size,
        )

        eval_budget_pct = None
        eval_blocked_note = None
        active_eval_for_display = repo.get_active_evaluation(user["id"])
        if active_eval_for_display and evaluation_id is not None:
            open_risk_eur_display = repo.total_open_risk_eur_for_evaluation(evaluation_id)
            daily_remaining = risk.compute_eval_daily_budget_remaining(active_eval_for_display, open_risk_eur_display)
            trade_budget = daily_remaining / risk.EVAL_BUDGET_TRADE_RESERVE if daily_remaining else 0.0
            eval_budget_pct = (risk_eur / trade_budget * 100) if trade_budget else 0.0
        elif active_eval_for_display and evaluation_id is None:
            eval_blocked_note = "Dagbudget of drawdown-ruimte van je evaluatie is (bijna) op, deze trade telt niet mee voor je evaluatie."'''
```

- [ ] **Step 4: signal_data-dict aan send_signal geeft de nieuwe velden door**

```python
old = '''            await telegram_notify.send_signal(
                {
                    **signal_data, "risk_eur": risk_eur, "position_size": position_size,
                    "open_risk_pct": open_risk_pct, "pending_count": pending_count,
                },
                chat_id=user["telegram_chat_id"], force_silent=force_silent, entry_id=entry_id,
            )'''
new = '''            await telegram_notify.send_signal(
                {
                    **signal_data, "risk_eur": risk_eur, "position_size": position_size,
                    "open_risk_pct": open_risk_pct, "pending_count": pending_count,
                    "eval_budget_pct": eval_budget_pct, "eval_blocked_note": eval_blocked_note,
                },
                chat_id=user["telegram_chat_id"], force_silent=force_silent, entry_id=entry_id,
            )'''
```

- [ ] **Step 5: _build_eval_context toont het budget voor de volgende trade**

```python
old = '''        eval_daily_loss_remaining_eur = max(0.0, daily_loss_amount - loss_so_far)'''
new = '''        eval_daily_loss_remaining_eur = max(0.0, daily_loss_amount - loss_so_far)
        eval_next_trade_budget_eur = eval_daily_loss_remaining_eur / risk.EVAL_BUDGET_TRADE_RESERVE'''
```

En in de `return`-dict van `_build_eval_context` (zoek de sleutel
`"eval_daily_loss_remaining_eur"` verderop in dezelfde functie, rond
regel 320-330), voeg `"eval_next_trade_budget_eur": eval_next_trade_budget_eur,`
toe als nieuwe sleutel. Initialiseer `eval_next_trade_budget_eur = None`
bovenaan de functie naast de andere `eval_*`-initialisaties (rond regel
267-272), zodat de sleutel ook bestaat als er geen `eval_display` is.

Toon dit op de `/evaluatie`-pagina (`web/templates/evaluatie.html`): zoek
waar `eval_daily_loss_remaining_eur` al getoond wordt en voeg er een
regel aan toe, bijvoorbeeld:

```html
<p>Volgende trade krijgt ongeveer €{{ "%.2f"|format(eval_next_trade_budget_eur) }} risicobudget.</p>
```

Alleen tonen als `eval_next_trade_budget_eur is not none` (Jinja2), naast
de bestaande conditionele blokken in dat template.

- [ ] **Step 6: Test — telegram-formatter**

```python
# scratchpad/test_task8_telegram.py
import sys
sys.path.insert(0, "/home/user/Trade")
from app import telegram_notify

signal = {
    "direction": "long", "coin": "BTC", "confidence": "hoog vertrouwen",
    "price": 100.0, "take_profit": 104.0, "stop_loss": 98.0,
    "reason": "✓ Trend: ok | ✓ Momentum: ok", "risk_eur": 42.0,
    "eval_budget_pct": 8.0, "eval_blocked_note": None,
}
message = telegram_notify.format_signal_message(signal)
assert "8%" in message and "dagbudget" in message.lower(), message

signal_blocked = {**signal, "eval_budget_pct": None, "eval_blocked_note": "test blokkade"}
message_blocked = telegram_notify.format_signal_message(signal_blocked)
assert "test blokkade" in message_blocked

print("Task 8: OK")
```

Run: `python3 scratchpad/test_task8_telegram.py`
Expected: `Task 8: OK`.

- [ ] **Step 7: Commit**

```bash
git add app/telegram_notify.py app/signal_processor.py web/main.py web/templates/evaluatie.html
git commit -m "Telegram + dashboard: tonen welk deel van het evaluatie-dagbudget een trade gebruikt"
```

---

### Task 9: Volledige regressie, handmatige Playwright-check en push

**Files:** geen nieuwe wijzigingen, alleen verificatie.

- [ ] **Step 1: Alle scratch-tests van Taken 1-8 opnieuw draaien tegen een verse database**

```bash
rm -f /tmp/task_all_scratch.db
DATABASE_PATH=/tmp/task_all_scratch.db python3 scratchpad/test_task1_schema.py
DATABASE_PATH=/tmp/task_all_scratch.db python3 scratchpad/test_task2_risk.py
DATABASE_PATH=/tmp/task_all_scratch.db python3 scratchpad/test_task3_position_size.py
DATABASE_PATH=/tmp/task_all_scratch.db python3 scratchpad/test_task4_repo.py
DATABASE_PATH=/tmp/task_all_scratch.db python3 scratchpad/test_task5_close.py
DATABASE_PATH=/tmp/task_all_scratch.db python3 scratchpad/test_task6_integration.py
python3 scratchpad/test_task8_telegram.py
```

Expected: elk script eindigt met zijn eigen `OK`-regel, geen enkele
exception.

- [ ] **Step 2: Regressie op het BESTAANDE gedrag (geen actieve evaluatie)**

Draai een scratch-scenario zonder evaluatie aan te maken (dus
`repo.get_active_evaluation` geeft `None`) door dezelfde stappen als in
Task 6's integratietest, maar zonder `repo.create_evaluation` aan te
roepen. Controleer dat `entry["evaluation_id"] is None` en dat
`entry["risk_eur"]` exact gelijk is aan
`risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"])` —
dit bewijst dat gebruikers zonder evaluatie helemaal niets van dit plan
merken.

- [ ] **Step 3: Handmatige Playwright-verificatie**

Herhaal Task 7 Step 5's scenario, plus:
1. Vergelijk het Telegram-testbericht (via de bestaande
   voorbeeldmelding-knop op het dashboard, of een los script dat
   `telegram_notify.format_signal_message` direct aanroept) met en zonder
   `eval_budget_pct` gezet.
2. Sluit een oefentrade die aan een evaluatie hangt en controleer op de
   `/evaluatie`-pagina dat het saldo na sluiten lager uitvalt dan het
   pure prijs-resultaat (de fee/hefboomkosten zijn zichtbaar verwerkt).

- [ ] **Step 4: Push**

```bash
git log --oneline -12
git push -u origin claude/crypto-day-trading-alerts-5p8w6v
```
