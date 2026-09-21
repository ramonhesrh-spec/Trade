# Puur Signalen Herziening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HesPulse herinrichten rond pure signalen: een kale, standaard "Signalen"-pagina na inloggen, alle journaal/portfolio/evaluatie-functionaliteit verhuisd naar een aparte "Mijn account"-pagina, een instelbare per-gebruiker bevestigingsdrempel, een volledig automatisch (prijsdata-gebaseerd) trackrecord zonder handmatige Genomen/Negeren-actie, en een ontrommelde, mobiel-eerste grafiek.

**Architecture:** `indicators.confirms_direction` gaat naast een boolean ook het kale gepoolde percentage teruggeven; dat percentage wordt één keer per signaal opgeslagen op `signals.pass_pct`, zodat elke gebruiker het achteraf tegen zijn eigen `users.confirm_threshold_pct` kan leggen zonder de technische berekening of de AI-uitleg opnieuw te hoeven draaien. Het trackrecord wordt losgekoppeld van `journal_entries.status`: een nieuwe periodieke check (naast de bestaande `level_check.py`) zet `signals.auto_outcome` zodra de live prijs het take-profit of de stop-loss van dat signaal raakt, voor élk signaal, niet alleen genomen trades. De site zelf splitst in twee routes: `/signalen` (nieuwe standaardpagina, kale lijst) en `/account` (alles wat nu op het dashboard staat).

**Tech Stack:** FastAPI, Jinja2, SQLite (via `app/db.py`), vanilla JS (`web/static/*.js`), Lightweight Charts.

**Spec:** Geen apart spec-document — tien onderwerpen zijn rechtstreeks in gesprek met de product owner doorgesproken en beantwoord (zie sessie van 2026-09-21); deze plan-inleiding draagt de besluiten zelf.

## Global Constraints

- Schemawijzigingen zijn altijd tweeledig: `CREATE TABLE IF NOT EXISTS` / kolom in `app/schema.sql` (voor een fris aangemaakte database) **en** een idempotente `ALTER TABLE ... ADD COLUMN` achter een `PRAGMA table_info`-check in `app/db.py:_migrate()` (voor een bestaande database). Een index op een kolom die `_migrate()` zelf toevoegt hoort ook in `_migrate()`, nooit in `schema.sql`.
- Alle databasetoegang loopt via `app/repo.py`, nergens anders raw SQL.
- Geen pytest-suite in dit project. Verificatie gebeurt met throwaway scripts tegen een scratch-database: `DATABASE_PATH=/tmp/scratch_puur_signalen.db python3 -c "..."`. Voor UI-taken: handmatige Playwright-verificatie tegen een lokale `uvicorn web.main:app --reload`-instantie.
- De twee harde eisen in `confirms_direction` (Uitgerektheid, BTC-trend) blijven voor iedereen hard, nooit per gebruiker instelbaar.
- Herbruikbare Jinja-fragmenten horen in `web/templates/_macros.html`, geïmporteerd als `macros`.
- Reversal-patroonherkenning (double top/bottom, head & shoulders) uit `scripts/research_reversal_patterns.py` wordt in dit plan **niet** aan de live toetsing gekoppeld — dat wacht op de historische validatie die de product owner apart op zijn VPS draait. Dit plan bevat alleen de per-coin-daggrafiek-basis die daar los van staat.
- Reviewer-checklist voor elke taak: geen "TBD"/lege functies, geen `sed`-loze copy-paste van code uit een andere taak, elke stap heeft echte, draaiende code.

---

## Overzicht taakvolgorde

1. Schema + migratie: drempel, percentage, automatische uitkomst
2. `confirms_direction` geeft percentage terug
3. Automatische signaal-uitkomst-detectie (trackrecord zonder handmatige actie)
4. Per-gebruiker bevestigde status + winrate op basis van eigen drempel
5. Drempel-instelling in de UI (Soepel/Normaal/Streng)
6. Nieuwe "Signalen"-pagina (standaard na login)
7. Nieuwe "Mijn account"-pagina (journaal/portfolio/evaluatie verhuisd)
8. Genomen/Negeren-knoppen weg uit de signalenkaart
9. Onboarding-checklist vereenvoudigen
10. Oefentrade-UI weg, losse positie-berekenaar blijft
11. Generieke portfolio/risicopercentage-sizing verwijderen
12. Coin-pagina: signalenlijst-sectie
13. Grafiek: alleen actueel signaal standaard, rest oproepbaar (mobiel-eerst)
14. Grafiek: oude lagen automatisch laten vervagen
15. Pushmelding-titel: "zelf gedetecteerd" weg
16. Periodieke zelfevaluatie van de factoren
17. Volledige regressie + push

---

### Task 1: Schema + migratie

**Files:**
- Modify: `app/schema.sql`
- Modify: `app/db.py`

**Interfaces:**
- Produces: kolommen `users.confirm_threshold_pct` (REAL, default 60.0), `users.confirm_threshold_set_at` (TEXT, nullable — NULL totdat de gebruiker bewust een drempel kiest, gebruikt door Task 9's onboarding-check), `signals.pass_pct` (REAL, nullable), `signals.hard_gates_ok` (INTEGER, default 1), `signals.auto_outcome` (TEXT, nullable, 'take_profit'/'stop_loss'), `signals.auto_outcome_at` (TEXT, nullable). Latere taken lezen/schrijven deze kolommen via `app/repo.py`.

- [ ] **Step 1: Kolommen toevoegen aan `schema.sql` voor een fris aangemaakte database**

In `app/schema.sql`, in de `users`-tabel (na `quiet_hours_end TEXT`):

```sql
    quiet_hours_end TEXT,
    -- Drempel (percentage) waarboven de gepoolde factoren voor DEZE
    -- gebruiker als "bevestigd" tellen. De twee harde eisen (Uitgerektheid,
    -- BTC-trend) blijven voor iedereen hard, dit percentage geldt alleen
    -- voor de rest. Standaard 60.0, gelijk aan de oude globale
    -- CONFIRM_THRESHOLD, zodat een bestaande gebruiker zonder wijziging
    -- exact hetzelfde gedrag ziet als voorheen.
    confirm_threshold_pct REAL NOT NULL DEFAULT 60.0,
    -- NULL totdat de gebruiker bewust op één van de drie drempel-knoppen
    -- klikt (Task 5). Los van confirm_threshold_pct zelf nodig, want de
    -- default (60.0) is numeriek gelijk aan de "Normaal"-stand, dus de
    -- waarde alleen kan "nog niet gekozen" niet van "bewust Normaal
    -- gekozen" onderscheiden. Voedt de onboarding-checklist (Task 9).
    confirm_threshold_set_at TEXT
);
```

In de `signals`-tabel (na `plain_explanation TEXT,`):

```sql
    plain_explanation TEXT,
    -- Kaal percentage gepoolde factoren dat raak was (bv. 68.0 voor 11 van
    -- 16), los van welke drempel een individuele gebruiker instelt. Elke
    -- gebruiker vergelijkt dit percentage zelf tegen zijn eigen
    -- confirm_threshold_pct, zodat de technische berekening en de
    -- AI-uitleg maar één keer per signaal hoeven te draaien.
    pass_pct REAL,
    -- Of de twee harde eisen (Uitgerektheid, BTC-trend) allebei klopten,
    -- los van pass_pct. Nodig omdat "technical_confirmed" al het EINDRESULTAAT
    -- op de globale drempel is; om een ANDERE (per-gebruiker) drempel tegen
    -- pass_pct te leggen moet los vaststaan of de harde eisen al dan niet
    -- geslaagd waren, ongeacht welke drempel je gebruikt.
    hard_gates_ok INTEGER NOT NULL DEFAULT 1,
    -- Automatisch, op prijsdata gebaseerd trackrecord: is de take-profit
    -- of de stop-loss van DIT signaal geraakt, ongeacht of een gebruiker
    -- het ooit als "genomen" markeerde. NULL zolang nog geen van beide
    -- geraakt is.
    auto_outcome TEXT,
    auto_outcome_at TEXT,
    created_at TEXT NOT NULL
);
```

- [ ] **Step 2: Idempotente migratie voor bestaande databases in `app/db.py`**

Open `app/db.py`, zoek de `_migrate()`-functie en de bestaande `PRAGMA table_info`-patronen daarin (bijvoorbeeld hoe `atr_avg20`/`adx` ooit aan `signals` zijn toegevoegd) en voeg ernaast toe:

```python
    cur.execute("PRAGMA table_info(users)")
    user_columns = {row[1] for row in cur.fetchall()}
    if "confirm_threshold_pct" not in user_columns:
        cur.execute(
            "ALTER TABLE users ADD COLUMN confirm_threshold_pct REAL NOT NULL DEFAULT 60.0"
        )
    if "confirm_threshold_set_at" not in user_columns:
        cur.execute("ALTER TABLE users ADD COLUMN confirm_threshold_set_at TEXT")

    cur.execute("PRAGMA table_info(signals)")
    signal_columns = {row[1] for row in cur.fetchall()}
    if "pass_pct" not in signal_columns:
        cur.execute("ALTER TABLE signals ADD COLUMN pass_pct REAL")
    if "hard_gates_ok" not in signal_columns:
        cur.execute("ALTER TABLE signals ADD COLUMN hard_gates_ok INTEGER NOT NULL DEFAULT 1")
    if "auto_outcome" not in signal_columns:
        cur.execute("ALTER TABLE signals ADD COLUMN auto_outcome TEXT")
    if "auto_outcome_at" not in signal_columns:
        cur.execute("ALTER TABLE signals ADD COLUMN auto_outcome_at TEXT")
        # Index hoort hier, niet in schema.sql: op het moment dat schema.sql
        # voor een NIEUWE database draait bestaat de kolom al, maar op een
        # bestaande database bestond hij een regel geleden nog niet.
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_signals_auto_outcome_pending "
            "ON signals(auto_outcome) WHERE auto_outcome IS NULL"
        )
```

Volg exact de plek en stijl van de bestaande `PRAGMA table_info`-blokken in die functie (zelfde `cur`-variabele, zelfde inspringing).

- [ ] **Step 3: Verifiëren tegen een scratch-database**

```bash
rm -f /tmp/scratch_puur_signalen.db
DATABASE_PATH=/tmp/scratch_puur_signalen.db python3 -c "
from app import db
db.init_db()
with db.session() as conn:
    cols_u = {r[1] for r in conn.execute('PRAGMA table_info(users)')}
    cols_s = {r[1] for r in conn.execute('PRAGMA table_info(signals)')}
    assert {'confirm_threshold_pct', 'confirm_threshold_set_at'} <= cols_u
    assert {'pass_pct', 'hard_gates_ok', 'auto_outcome', 'auto_outcome_at'} <= cols_s
print('schema ok')
"
```

Verwacht: `schema ok`, geen exceptie.

- [ ] **Step 4: Verifiëren dat de migratie ook op een database van vóór deze wijziging werkt**

```bash
DATABASE_PATH=/tmp/scratch_puur_signalen.db python3 -c "
from app import db
with db.session() as conn:
    conn.execute('ALTER TABLE users DROP COLUMN confirm_threshold_pct')
" 2>/dev/null || true
DATABASE_PATH=/tmp/scratch_puur_signalen.db python3 -c "
from app import db
db.init_db()
print('migratie herhaalbaar zonder fout')
"
```

(SQLite kent `DROP COLUMN` pas sinds 3.35; lukt de eerste stap niet, verwijder dan gewoon `/tmp/scratch_puur_signalen.db` en herhaal Step 3 twee keer achter elkaar — `_migrate()` moet de tweede keer niets meer doen en niet crashen.)

- [ ] **Step 5: Commit**

```bash
git add app/schema.sql app/db.py
git commit -m "Schema: confirm_threshold_pct, signals.pass_pct en auto_outcome"
```

---

### Task 2: `confirms_direction` geeft percentage terug

**Files:**
- Modify: `app/indicators.py:1161-1281` (functie `confirms_direction`)
- Modify: `app/signal_processor.py` (regels rond 721-723 en 749-798, waar `confirmed, reason = indicators.confirms_direction(...)` wordt aangeroepen en `signal_data` wordt opgebouwd)
- Modify: `app/market_scanner.py` (dezelfde aanroep, twee plekken)
- Modify: `app/repo.py` (insert_signal / equivalent, zodat `pass_pct` wordt opgeslagen)

**Interfaces:**
- Produces: `confirms_direction(...)` retourneert voortaan `tuple[bool, str, float, bool]` (`confirmed, breakdown, pass_pct, hard_gates_ok`) in plaats van `tuple[bool, str]`. `pass_pct` is `passed / len(other_factors) * 100`, altijd berekend ook als een harde eis al faalt. `hard_gates_ok` is `extension_ok and btc_trend_ok`, los van `pass_pct` — dit is wat Task 4's per-gebruiker vergelijking nodig heeft: de harde eisen blijven voor iedereen hard, ongeacht welke drempel een gebruiker instelt, dus moet apart van het percentage vaststaan.
- Consumes: niets nieuws, hergebruikt de bestaande `passed`/`other_factors`-berekening in de functie.

- [ ] **Step 1: Aanpassen `confirms_direction` in `app/indicators.py`**

Zoek de laatste regel van de functie:

```python
    confirmed = extension_ok and btc_trend_ok and (passed / len(other_factors)) >= CONFIRM_THRESHOLD
    return confirmed, breakdown
```

Vervang door:

```python
    pass_pct = (passed / len(other_factors)) * 100 if other_factors else 100.0
    hard_gates_ok = extension_ok and btc_trend_ok
    confirmed = hard_gates_ok and pass_pct >= CONFIRM_THRESHOLD * 100
    return confirmed, breakdown, pass_pct, hard_gates_ok
```

`CONFIRM_THRESHOLD` (0.6) blijft ongewijzigd bestaan als de globale standaardwaarde voor "Normaal", zie Task 5.

- [ ] **Step 2: Alle aanroepers aanpassen — `app/signal_processor.py`**

Zoek elke plek met `confirmed, reason = indicators.confirms_direction(` (er zijn er twee: één in `process_day_trading_signal`, één in `_fetch_practice_trade_calc`-achtige oefentrade-code als die nog bestaat vóór Task 10). Vervang telkens:

```python
    confirmed, reason = indicators.confirms_direction(
        ind, interp.direction, extra_factors=extra_factors, include_advanced=config.ENABLE_ADVANCED_FACTORS,
    )
```

door:

```python
    confirmed, reason, pass_pct, hard_gates_ok = indicators.confirms_direction(
        ind, interp.direction, extra_factors=extra_factors, include_advanced=config.ENABLE_ADVANCED_FACTORS,
    )
```

En voeg `"pass_pct": pass_pct, "hard_gates_ok": int(hard_gates_ok),` toe aan de `signal_data`-dict die later naar `repo.insert_signal`/de journaal-fanout gaat (naast de bestaande `"technical_confirmed": int(confirmed),`).

- [ ] **Step 3: Zelfde aanpassing in `app/market_scanner.py`**

Beide aanroepen van `process_day_trading_signal` in dit bestand gaan via dezelfde gedeelde functie uit Step 2, dus hier is geen losse aanpassing nodig — controleer wel of `market_scanner.py` zelf ergens rechtstreeks `confirms_direction` aanroept (los van `process_day_trading_signal`) en pas dat aanroeppatroon op dezelfde manier aan als Step 2, mocht dat zo zijn.

- [ ] **Step 4: `repo.insert_signal` slaat `pass_pct` en `hard_gates_ok` op**

Open `app/repo.py`, zoek de functie die een rij in `signals` invoegt (`insert_signal` of gelijknamig, gebruikt door `signal_data`). Voeg `pass_pct` en `hard_gates_ok` toe aan zowel de kolommenlijst als de parameterlijst van de `INSERT INTO signals (...)`-query, gevoed vanuit `data["pass_pct"]` en `data["hard_gates_ok"]`.

- [ ] **Step 5: Verifiëren met een throwaway script**

```bash
DATABASE_PATH=/tmp/scratch_puur_signalen.db python3 -c "
from app import indicators
ind = indicators.Indicators(
    price=100, rsi=50, macd=1, macd_signal=0.5, volume_ratio=1.5,
    ema9=101, ema21=99, atr=2, atr_avg20=2, adx=25,
)
confirmed, reason, pass_pct, hard_gates_ok = indicators.confirms_direction(ind, 'long')
print(confirmed, pass_pct, hard_gates_ok)
assert isinstance(pass_pct, float)
assert isinstance(hard_gates_ok, bool)
"
```

Verwacht: geen exceptie, `pass_pct` is een `float`, `hard_gates_ok` is een `bool`.

- [ ] **Step 6: Commit**

```bash
git add app/indicators.py app/signal_processor.py app/market_scanner.py app/repo.py
git commit -m "confirms_direction geeft gepoold percentage en harde-eisen-status terug"
```

---

### Task 3: Automatische signaal-uitkomst-detectie

**Files:**
- Modify: `app/repo.py`
- Modify: `app/level_check.py`

**Interfaces:**
- Consumes: `signals.stop_loss`, `signals.take_profit`, `signals.direction`, `signals.coin`, `signals.auto_outcome` (Task 1); de bestaande `_level_hit(direction, current_price, stop_loss, take_profit)` helper in `app/level_check.py:48-60`.
- Produces: `repo.list_unresolved_signals_with_levels() -> list[dict]` (kolommen: `id`, `coin`, `direction`, `stop_loss`, `take_profit`, `created_at`), `repo.mark_signal_auto_outcome(signal_id: int, outcome: str, occurred_at: str) -> None`. Nieuwe functie `level_check.check_signal_outcomes() -> None`, aangeroepen vanuit `run_all_checks()`.

- [ ] **Step 1: `repo.list_unresolved_signals_with_levels` toevoegen**

In `app/repo.py`, naast de bestaande `list_open_entries_with_levels`/`list_pending_entries_with_price`-functies:

```python
def list_unresolved_signals_with_levels() -> list[dict]:
    """Signalen (van elke gebruiker samen, want stop_loss/take_profit zijn
    per signaal gedeeld) waarvan nog niet vastgesteld is of de take-profit
    of de stop-loss al geraakt is. Dit voedt het volledig automatische
    trackrecord, los van of een gebruiker het signaal ooit als "genomen"
    markeerde."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT id, coin, direction, stop_loss, take_profit, created_at
               FROM signals
               WHERE auto_outcome IS NULL
                 AND stop_loss IS NOT NULL
                 AND take_profit IS NOT NULL
                 AND is_practice = 0"""
        ).fetchall()
        return [dict(row) for row in rows]


def mark_signal_auto_outcome(signal_id: int, outcome: str, occurred_at: str) -> None:
    with db.session() as conn:
        conn.execute(
            "UPDATE signals SET auto_outcome = ?, auto_outcome_at = ? WHERE id = ?",
            (outcome, occurred_at, signal_id),
        )
```

- [ ] **Step 2: `check_signal_outcomes` toevoegen aan `app/level_check.py`**

Voeg toe, na de bestaande `check_open_trades`-functie en vóór `check_pending_signals`:

```python
async def check_signal_outcomes() -> None:
    """Volledig automatisch trackrecord: voor elk signaal waarvan de
    uitkomst nog niet vaststaat, checkt dit of de live prijs inmiddels de
    take-profit of de stop-loss geraakt heeft. Onafhankelijk van of een
    gebruiker het signaal ooit als "genomen" markeerde — dit is precies
    waarom het trackrecord niet meer van een handmatige actie afhangt."""
    signals = repo.list_unresolved_signals_with_levels()
    logger.info("%d signalen zonder vastgestelde uitkomst om te checken", len(signals))

    coin_prices: dict[str, float] = {}
    for signal in signals:
        coin = signal["coin"]
        if coin not in coin_prices:
            try:
                coin_prices[coin] = await asyncio.to_thread(exchange.fetch_last_price, coin)
            except Exception:
                logger.exception("Kon geen live prijs ophalen voor %s, sla over", coin)
                coin_prices[coin] = None
        current_price = coin_prices[coin]
        if current_price is None:
            continue

        hit = _level_hit(signal["direction"], current_price, signal["stop_loss"], signal["take_profit"])
        if not hit:
            continue
        outcome = "take_profit" if hit == "take profit" else "stop_loss"
        repo.mark_signal_auto_outcome(signal["id"], outcome, db.now_iso())
        logger.info("Signaal %s (%s) automatisch afgesloten: %s", signal["id"], coin, outcome)
```

Voeg `check_signal_outcomes` toe aan `run_all_checks()`:

```python
async def run_all_checks() -> None:
    await check_open_trades()
    await check_signal_outcomes()
    await check_pending_signals()
    await check_swing_watches()
    await check_narratives()
```

- [ ] **Step 3: Verifiëren met een throwaway script tegen een scratch-database**

```bash
rm -f /tmp/scratch_puur_signalen.db
DATABASE_PATH=/tmp/scratch_puur_signalen.db python3 -c "
import asyncio
from unittest.mock import patch
from app import db, repo, level_check

db.init_db()
with db.session() as conn:
    conn.execute(
        '''INSERT INTO messages (received_at, raw_text, has_image, image_paths)
           VALUES (?, '', 0, '[]')''', (db.now_iso(),)
    )
    conn.execute(
        '''INSERT INTO signals (coin, direction, category, price, technical_confirmed,
               confidence, stop_loss, take_profit, created_at)
           VALUES ('BTC', 'long', 'day_trading', 100, 1, 'hoog vertrouwen', 95, 110, ?)''',
        (db.now_iso(),),
    )

with patch('app.exchange.fetch_last_price', return_value=111.0):
    asyncio.run(level_check.check_signal_outcomes())

with db.session() as conn:
    row = conn.execute('SELECT auto_outcome FROM signals WHERE coin = \"BTC\"').fetchone()
    assert row['auto_outcome'] == 'take_profit', row['auto_outcome']
print('automatische uitkomst-detectie ok')
"
```

Verwacht: `automatische uitkomst-detectie ok`.

- [ ] **Step 4: Commit**

```bash
git add app/repo.py app/level_check.py
git commit -m "Volledig automatisch trackrecord: signals.auto_outcome via level_check"
```

---

### Task 4: Per-gebruiker bevestigde status + winrate op eigen drempel

**Files:**
- Modify: `app/repo.py`

**Interfaces:**
- Consumes: `signals.pass_pct` (Task 2), `signals.auto_outcome` (Task 3), `users.confirm_threshold_pct` (Task 1).
- Produces: `repo.user_confirmed(pass_pct: float, hard_gates_ok: bool, threshold_pct: float) -> bool` (pure functie, geen databasetoegang), `repo.winrate_for_user(user_id: int) -> dict` (velden: `total`, `wins`, `losses`, `open`, `winrate_pct`).

- [ ] **Step 1: Pure hulpfunctie `user_confirmed`**

`signals.technical_confirmed` blijft bestaan als het GLOBALE resultaat op basis van de vaste `CONFIRM_THRESHOLD` (voor achterwaartse compatibiliteit met bestaande code die er nog naar kijkt), maar de per-gebruiker-weergave gebruikt deze nieuwe functie, die de in Task 1/2 al opgeslagen `hard_gates_ok`-kolom gebruikt. Voeg toe in `app/repo.py`:

```python
def user_confirmed(pass_pct: float, hard_gates_ok: bool, threshold_pct: float) -> bool:
    """Of een signaal voor DEZE gebruiker als bevestigd geldt: de twee
    harde eisen (al verwerkt in hard_gates_ok) blijven voor iedereen hard,
    alleen het percentage van de gepoolde factoren wordt per gebruiker
    tegen zijn eigen drempel gelegd."""
    return hard_gates_ok and pass_pct >= threshold_pct
```

- [ ] **Step 2: `winrate_for_user` toevoegen**

```python
def winrate_for_user(user_id: int) -> dict:
    """Winrate puur op basis van het automatische trackrecord: van de
    signalen die voor DEZE gebruiker (zijn eigen drempel) bevestigd waren
    en waarvan de uitkomst al vaststaat, hoeveel raakten take-profit."""
    with db.session() as conn:
        threshold = conn.execute(
            "SELECT confirm_threshold_pct FROM users WHERE id = ?", (user_id,)
        ).fetchone()["confirm_threshold_pct"]
        rows = conn.execute(
            """SELECT pass_pct, hard_gates_ok, auto_outcome
               FROM signals
               WHERE is_practice = 0 AND pass_pct IS NOT NULL"""
        ).fetchall()

    total = wins = losses = open_count = 0
    for row in rows:
        if not user_confirmed(row["pass_pct"], bool(row["hard_gates_ok"]), threshold):
            continue
        total += 1
        if row["auto_outcome"] == "take_profit":
            wins += 1
        elif row["auto_outcome"] == "stop_loss":
            losses += 1
        else:
            open_count += 1

    resolved = wins + losses
    winrate_pct = (wins / resolved * 100) if resolved else None
    return {"total": total, "wins": wins, "losses": losses, "open": open_count, "winrate_pct": winrate_pct}
```

- [ ] **Step 3: Verifiëren met een throwaway script**

```bash
DATABASE_PATH=/tmp/scratch_puur_signalen.db python3 -c "
from app import repo
assert repo.user_confirmed(70.0, True, 60.0) is True
assert repo.user_confirmed(50.0, True, 60.0) is False
assert repo.user_confirmed(90.0, False, 60.0) is False
print('user_confirmed ok')
"
```

Verwacht: `user_confirmed ok`.

- [ ] **Step 4: Commit**

```bash
git add app/repo.py
git commit -m "Per-gebruiker bevestigde status en winrate op basis van eigen drempel"
```

---

### Task 5: Drempel-instelling in de UI (Soepel/Normaal/Streng)

**Files:**
- Modify: `web/main.py`
- Modify: `web/templates/account.html` (bestaat pas na Task 7 — als deze taak vóór Task 7 wordt uitgevoerd, voeg het formulier toe aan het bestaande `dashboard.html`/instellingen-gedeelte en verhuis het mee in Task 7)
- Modify: `app/repo.py`

**Interfaces:**
- Consumes: `users.confirm_threshold_pct` (Task 1).
- Produces: `repo.update_confirm_threshold(user_id: int, threshold_pct: float) -> None`. Route `POST /instellingen/drempel`.

- [ ] **Step 1: `repo.update_confirm_threshold`**

```python
def update_confirm_threshold(user_id: int, threshold_pct: float) -> None:
    with db.session() as conn:
        conn.execute(
            "UPDATE users SET confirm_threshold_pct = ?, confirm_threshold_set_at = ? WHERE id = ?",
            (threshold_pct, db.now_iso(), user_id),
        )
```

- [ ] **Step 2: Route in `web/main.py`**

Volg het bestaande patroon van andere instellingen-routes (zoek `@app.post("/instellingen` in dit bestand voor de exacte vorm die dit project al gebruikt, bijvoorbeeld hoe `quiet_hours` wordt opgeslagen) en voeg toe:

```python
CONFIRM_THRESHOLD_PRESETS = {"soepel": 45.0, "normaal": 60.0, "streng": 75.0}


@app.post("/instellingen/drempel")
async def update_confirm_threshold_setting(
    preset: str = Form(...),
    user: dict = Depends(require_login),
):
    if preset not in CONFIRM_THRESHOLD_PRESETS:
        return RedirectResponse(url="/account", status_code=303)
    repo.update_confirm_threshold(user["id"], CONFIRM_THRESHOLD_PRESETS[preset])
    return RedirectResponse(url="/account", status_code=303)
```

- [ ] **Step 3: Formulier in de template**

Drie radio-knoppen of losse knoppen met het percentage zichtbaar, bijvoorbeeld:

```html
<form action="/instellingen/drempel" method="post" class="threshold-form">
  <p class="muted">Hoe streng moet een signaal zijn voordat je een melding krijgt?</p>
  {% for key, pct in {"soepel": 45, "normaal": 60, "streng": 75}.items() %}
  <button type="submit" name="preset" value="{{ key }}"
          class="threshold-option{% if user.confirm_threshold_pct == pct %} is-active{% endif %}">
    {{ key|capitalize }} ({{ pct }}%)
  </button>
  {% endfor %}
</form>
```

- [ ] **Step 4: Handmatige Playwright-verificatie**

Start `uvicorn web.main:app --reload` tegen een scratch-database, log in, klik elk van de drie knoppen, en controleer via `sqlite3 /tmp/scratch_puur_signalen.db "SELECT confirm_threshold_pct FROM users"` dat de waarde daadwerkelijk wijzigt.

- [ ] **Step 5: Commit**

```bash
git add web/main.py app/repo.py web/templates/
git commit -m "Instelbare bevestigingsdrempel: Soepel/Normaal/Streng"
```

---

### Task 6: Nieuwe "Signalen"-pagina

**Files:**
- Create: `web/templates/signalen.html`
- Modify: `web/main.py`
- Modify: `web/templates/_macros.html` (nieuwe macro `signal_card`)
- Modify: `web/templates/base.html` (navigatie: "Dashboard" wordt "Signalen" en wijst naar de nieuwe route; nieuwe link "Mijn account")

**Interfaces:**
- Consumes: `repo.user_confirmed`, `repo.winrate_for_user` (Task 4, alleen voor het aantal, niet voor detailweergave op deze pagina), bestaande signalen-query-functies in `web/main.py`/`app/repo.py` die al signalen per gebruiker ophalen (zoek de functie die de huidige dashboard-route gebruikt om `all_entries`/vergelijkbaar te vullen).
- Produces: route `GET /signalen`, macro `macros.signal_card(entry)` in `_macros.html`, gebruikt door zowel deze pagina als de coin-pagina in Task 12.

- [ ] **Step 1: Macro `signal_card` in `_macros.html`**

```jinja
{% macro signal_card(entry) %}
<div class="signal-card {{ 'is-confirmed' if entry.user_confirmed else 'is-rejected' }}">
  <div class="signal-card-head">
    <span class="coin-symbol">{{ entry.coin }}</span>
    <span class="direction {{ entry.direction }}">{{ entry.direction|upper }}</span>
    <span class="pass-pct">{{ "%.0f"|format(entry.pass_pct) }}%</span>
  </div>
  <div class="signal-card-levels">
    Entry {{ "%.4f"|format(entry.price) }} · Stop {{ "%.4f"|format(entry.stop_loss) }} ·
    Take profit {{ "%.4f"|format(entry.take_profit) }}
  </div>
</div>
{% endmacro %}
```

- [ ] **Step 2: Route `GET /signalen` in `web/main.py`**

Hergebruik de bestaande query die nu de dashboard-route voedt (zoek de functie/regel die `all_entries` of vergelijkbaar ophaalt voor de huidige `/dashboard`-route) maar sorteer op `pass_pct` aflopend in plaats van chronologisch, en bereken per rij `user_confirmed` via `repo.user_confirmed`:

```python
@app.get("/signalen", response_class=HTMLResponse)
async def signalen_page(request: Request, user: dict = Depends(require_login)):
    entries = repo.list_recent_signals_for_user(user["id"])  # bestaande of licht aan te passen query
    for entry in entries:
        entry["user_confirmed"] = repo.user_confirmed(
            entry["pass_pct"], bool(entry["hard_gates_ok"]), user["confirm_threshold_pct"]
        )
    entries.sort(key=lambda e: e["pass_pct"], reverse=True)
    return templates.TemplateResponse(
        "signalen.html", {"request": request, "user": user, "entries": entries}
    )
```

Bestaat er nog geen `repo.list_recent_signals_for_user`, voeg hem toe naar het patroon van de bestaande dashboard-query in `app/repo.py`, met `pass_pct` en `hard_gates_ok` in de SELECT.

- [ ] **Step 3: Template `signalen.html`**

```html
{% extends "base.html" %}
{% import "_macros.html" as macros %}
{% block content %}
<h1>Signalen</h1>
{% if not entries %}
<p class="muted">Nog geen signalen.</p>
{% endif %}
{% for entry in entries %}
{{ macros.signal_card(entry) }}
{% endfor %}
{% endblock %}
```

- [ ] **Step 4: Navigatie bijwerken in `base.html`**

Zoek `<a href="/dashboard">Dashboard</a>` (komt meerdere keren voor, o.a. in de coins-menu-structuur) en vervang de hoofdnavigatie-link door:

```html
<a href="/signalen">Signalen</a>
<a href="/account">Mijn account</a>
```

(De `/account`-route zelf komt in Task 7 — commit deze taak pas nadat Task 7 ook af is, of laat de link tijdelijk naar de bestaande `/dashboard` wijzen en werk hem in Task 7 bij, wat je zelf logischer vindt gegeven de volgorde waarin je werkt.)

- [ ] **Step 5: Handmatige Playwright-verificatie**

Start lokaal, log in, controleer dat `/signalen` een kale lijst toont gesorteerd op percentage, geen journaal/portfolio-elementen.

- [ ] **Step 6: Commit**

```bash
git add web/templates/signalen.html web/templates/_macros.html web/templates/base.html web/main.py app/repo.py
git commit -m "Nieuwe Signalen-pagina: kale lijst, gesorteerd op hoogste percentage"
```

---

### Task 7: Nieuwe "Mijn account"-pagina

**Files:**
- Create: `web/templates/account.html`
- Modify: `web/main.py`
- Modify: `web/templates/base.html` (navigatielink, zie Task 6 Step 4)

**Interfaces:**
- Consumes: alle context die de huidige `/dashboard`-route al opbouwt voor journaal, portfolio, winrate, evaluatie (behalve wat in Tasks 10/11 verwijderd wordt), plus `repo.winrate_for_user` (Task 4) voor het nieuwe automatische winrate-cijfer.
- Produces: route `GET /account`, die de bestaande `/dashboard`-route vervangt qua inhoud (dashboard.html's huidige content verhuist hierheen).

- [ ] **Step 1: Route `GET /account`**

Hernoem de bestaande dashboard-routefunctie in `web/main.py` (die nu op `/dashboard` hangt) niet weg, maar voeg een tweede decorator toe zodat dezelfde functie ook op `/account` reageert, of dupliceer de route-registratie naar de nieuwe padnaam, wat consistenter is met de rest van deze routetabel:

```python
@app.get("/account", response_class=HTMLResponse)
async def account_page(request: Request, user: dict = Depends(require_login)):
    # Exact dezelfde context-opbouw als de huidige dashboard-route (journaal,
    # portfolio, winrate — zie de bestaande functie voor de context-dict),
    # met winrate vervangen door repo.winrate_for_user(user["id"]) uit Task 4
    # in plaats van de oude, handmatige-status-gebaseerde berekening.
    ...
    context["winrate"] = repo.winrate_for_user(user["id"])
    return templates.TemplateResponse("account.html", {"request": request, **context})
```

Verwijder de oude `/dashboard`-route pas nadat `base.html` nergens meer naar `/dashboard` linkt (grep het hele project op `/dashboard` en vervang elke resterende verwijzing door `/signalen` of `/account`, afhankelijk van de context — bijvoorbeeld de `<a href="/dashboard" class="brand">`-logo-link in `base.html` wordt `/signalen`).

- [ ] **Step 2: Template `account.html`**

Kopieer de body van het huidige `dashboard.html` naar dit nieuwe bestand (behoud journaal-tabel, winrate-sectie, instellingen-formulieren inclusief het drempel-formulier uit Task 5), maar **laat het signalenoverzicht/de actie-sectie met individuele signalen weg** — die staat voortaan alleen op `/signalen`. Verwijder de evaluatie-kaart uit de zichtbare template (zie Task 11 voor de precieze afbakening tussen zichtbaar-weg en actief-blijvend).

- [ ] **Step 3: Handmatige Playwright-verificatie**

Log in, bezoek `/account`, controleer dat journaal en winrate zichtbaar zijn en dat er geen losse signalenlijst meer op deze pagina staat (die hoort nu bij `/signalen`).

- [ ] **Step 4: Commit**

```bash
git add web/templates/account.html web/main.py web/templates/base.html
git commit -m "Mijn account-pagina: journaal, portfolio en winrate los van de signalenlijst"
```

---

### Task 8: Genomen/Negeren-knoppen weg uit de signalenkaart

**Files:**
- Modify: `web/templates/_macros.html` (macro `signal_card` uit Task 6)
- Modify: `web/static/dashboard.js` (of het bestand dat de bestaande AJAX-trade-flow voor Genomen/Negeren afhandelt — zoek `/journal/{entry_id}/status` in `web/static/*.js`)

**Interfaces:**
- Consumes: `macros.signal_card` (Task 6).

- [ ] **Step 1: Knoppen verwijderen uit de macro**

Zorg dat `signal_card` in Task 6 sowieso al geen Genomen/Negeren-knoppen bevatte (dat was de opzet); grep de rest van het project op `/journal/{entry_id}/status` en `Genomen`/`Negeren` in templates om te controleren of er ELDERS nog een kopie van deze knoppen bestaat buiten de oude dashboard-signalenlijst (die met Task 7 al verhuisd/verwijderd is). Verwijder elke resterende losse instantie.

- [ ] **Step 2: Dode JS opruimen**

In `web/static/dashboard.js`, verwijder de event listeners en fetch-aanroepen die uitsluitend voor deze knoppen bestonden (zoek de functie die naar `/journal/{id}/status` post). Laat de route `POST /journal/{entry_id}/status` in `web/main.py` zelf ongemoeid staan — die kan nog dienen voor toekomstig gebruik vanaf `/account`, dit is puur het weghalen van de knop uit de signalenkaart.

- [ ] **Step 3: Handmatige Playwright-verificatie**

Bezoek `/signalen`, controleer dat er geen Genomen/Negeren-knoppen meer op een kaart staan en dat de browserconsole geen JS-fouten geeft door de verwijderde listeners.

- [ ] **Step 4: Commit**

```bash
git add web/templates/_macros.html web/static/dashboard.js
git commit -m "Genomen/Negeren-knoppen weg uit de signalenkaart, trackrecord is nu automatisch"
```

---

### Task 9: Onboarding-checklist vereenvoudigen

**Files:**
- Modify: `web/main.py:728-738` (de `onboarding`-dict)
- Modify: `web/templates/account.html` (of waar de checklist nu getoond wordt)

**Interfaces:**
- Consumes: `users.confirm_threshold_pct` (Task 1), bestaande `repo.list_push_subscriptions`.

- [ ] **Step 1: `onboarding`-dict aanpassen in `web/main.py`**

Vervang:

```python
    onboarding = {
        "push_enabled": bool(repo.list_push_subscriptions(user["id"])),
        "portfolio_set": user["portfolio_eur"] > 0,
        "first_alert_received": any(e["telegram_sent"] for e in all_entries),
    }
```

door:

```python
    onboarding = {
        "push_enabled": bool(repo.list_push_subscriptions(user["id"])),
        "threshold_chosen": user["confirm_threshold_set_at"] is not None,
    }
```

`confirm_threshold_set_at` (Task 1) is expres een apart tijdstip-veld naast `confirm_threshold_pct` zelf: de default van dat percentage (60.0) is numeriek gelijk aan de "Normaal"-knop, dus de waarde alleen kan "nog niet gekozen" niet van "bewust Normaal gekozen" onderscheiden. `repo.update_confirm_threshold` (Task 5) moet dit veld dus ook vullen — zorg dat Task 5's implementatie van die functie naast `confirm_threshold_pct` ook `confirm_threshold_set_at = ?` (met de huidige tijd) meeneemt in de UPDATE-query.

- [ ] **Step 2: Geen extra uitleg-tekst toevoegen**

Laat de checklist-weergave zelf (twee regels, aangevinkt of niet) ongewijzigd qua stijl — expliciet geen toelichtende alinea's toevoegen, dat was de uitdrukkelijke wens.

- [ ] **Step 3: Handmatige Playwright-verificatie**

Maak een nieuwe gebruiker aan via `scripts/create_user.py` tegen de scratch-database, log in, controleer dat de checklist twee items toont en dat "drempel gekozen" pas aanvinkt na een klik op Task 5's formulier.

- [ ] **Step 4: Commit**

```bash
git add web/main.py web/templates/
git commit -m "Onboarding-checklist teruggebracht tot push aan en drempel gekozen"
```

---

### Task 10: Oefentrade-UI weg, losse positie-berekenaar blijft

**Files:**
- Modify: `web/main.py` (route `POST /coins/{symbol}/oefen` verwijderen, `POST /coins/{symbol}/oefen-preview` blijft ongewijzigd staan)
- Modify: `web/templates/coin.html` (formulier voor het daadwerkelijk aanmaken van een oefentrade weg, live-rekenhulp-UI blijft)
- Modify: `web/static/coin.js` (JS die naar `/oefen` postte weg, JS voor `/oefen-preview` blijft, zie de bestaande `runPreview()`-functie)

**Interfaces:**
- Consumes: `/coins/{symbol}/oefen-preview` (ongewijzigd, geen Anthropic-aanroep).

- [ ] **Step 1: Route verwijderen uit `web/main.py`**

Verwijder de hele `@app.post("/coins/{symbol}/oefen")`-routefunctie (`create_practice_trade`, rond regel 1337-1364+ zoals eerder deze sessie gelezen). Laat `_fetch_practice_trade_calc` en `preview_practice_trade` (`/oefen-preview`) volledig ongewijzigd — die code blijft in de codebase, alleen niet meer aanroepbaar via een "aanmaken"-knop.

- [ ] **Step 2: Formulier in `coin.html` inkorten**

Zoek het `<form id="oefen-form">`-element (of vergelijkbaar) in `web/templates/coin.html`. Laat de invoervelden (richting, risicobedrag) en het live-resultaat (`#oefen-preview`) staan, verwijder de submit-knop die naar `/coins/{symbol}/oefen` postte en het bijbehorende `<form action="...">`-attribuut (vervang door een lege `<div>` met dezelfde velden, geen `<form>` nodig als er toch niets meer verstuurd wordt buiten de live-preview).

- [ ] **Step 3: JS opschonen in `web/static/coin.js`**

De bestaande `runPreview()`-functie en zijn `scheduleRunPreview()`/event listeners (regel 549-592 zoals eerder deze sessie gelezen) blijven exact zoals ze zijn — die praten al alleen met `/oefen-preview`. Verwijder alleen een eventuele submit-handler die naar `/coins/{symbol}/oefen` post, als die los van `runPreview()` bestaat.

- [ ] **Step 4: Handmatige Playwright-verificatie**

Bezoek een coin-pagina, vul de positie-berekenaar in, controleer dat de live-preview-tekst nog steeds verschijnt, en dat er geen knop meer is om een echte oefentrade aan te maken.

- [ ] **Step 5: Commit**

```bash
git add web/main.py web/templates/coin.html web/static/coin.js
git commit -m "Oefentrade-aanmaken van de site af, losse positie-berekenaar blijft"
```

---

### Task 11: Generieke portfolio/risicopercentage-sizing verwijderen

**Files:**
- Modify: `app/risk.py`
- Modify: `app/signal_processor.py` (waar de generieke sizing wordt aangeroepen voor een niet-evaluatie-gekoppelde trade)
- Modify: `web/templates/account.html` (portfolio/risicopercentage-instellingenformulier weg)
- Modify: `web/templates/account.html` of waar de evaluatie-kaart nu staat (evaluatie-kaart uit de zichtbare template, route/logica blijft)

**Interfaces:**
- Consumes: bestaande `risk.compute_position_size`, `risk.compute_eval_risk_eur` (evaluatie-specifiek, blijft ongewijzigd).
- Produces: geen nieuwe interfaces — dit is een verwijder-taak.

- [ ] **Step 1: Onderscheid vaststellen in `app/risk.py`**

Lees de functie die de generieke sizing doet (`risk_eur = user["portfolio_eur"] * user["risk_percent"] / 100` of vergelijkbaar, waarschijnlijk in `_resolve_signal_risk` of gelijknamig in `app/signal_processor.py`, niet per se in `risk.py` zelf) en de functie die de evaluatie-specifieke sizing doet (`compute_eval_risk_eur`, `compute_eval_daily_budget_remaining`). Verwijder ALLEEN het generieke pad; als een functie beide gevallen in één `if evaluation_id: ... else: ...`-blok afhandelt, verwijder alleen de `else`-tak en laat zien wat er gebeurt als er geen actieve evaluatie is (zie Step 2).

- [ ] **Step 2: Gedrag zonder actieve evaluatie**

Met de generieke sizing weg moet er een duidelijke, geen-halve-implementatie-keuze gemaakt worden voor een signaal bij een gebruiker zonder actieve evaluatie: toon het signaal met zijn entry/stop/take-profit zoals altijd, maar laat `risk_eur`/`position_size` op de journaalregel `NULL` in plaats van een berekend bedrag (de kolommen zijn al nullable, zie `schema.sql`). Pas de plek aan die nu `risk_eur = ...` toekent zodat die bij het ontbreken van een actieve evaluatie `None` toekent in plaats van de oude portfolio-berekening aan te roepen.

- [ ] **Step 3: UI-formulier weg uit `account.html`**

Verwijder het formulier waarmee `portfolio_eur`/`risk_percent` ingesteld worden uit `account.html`. Laat de kolommen zelf in `schema.sql`/de `users`-tabel ongewijzigd staan (geen migratie nodig om ze te verwijderen, ze worden gewoon niet meer gebruikt of getoond).

- [ ] **Step 4: Evaluatie-kaart uit de zichtbare template, bewaking blijft actief**

Verwijder het HTML-blok van de evaluatie-kaart/-sectie uit `account.html` (en verwijder de link naar de aparte `/evaluatie`-pagina uit de navigatie in `base.html`, als die er is). Laat de route `/evaluatie` zelf, `app/risk.py`'s dagbudget/drawdown-functies, en de aanroepen daarvan in `signal_processor.py` (die de positiegrootte van een evaluatie-gekoppelde trade begrenzen) volledig ongewijzigd en actief — dit is uitsluitend het weghalen van de zichtbare kaart en navigatielink, niet van de onderliggende bescherming.

- [ ] **Step 5: Handmatige Playwright-verificatie**

Controleer dat `/account` geen portfolio-formulier en geen evaluatie-kaart meer toont, dat de evaluatie-route zelf (rechtstreeks bezocht via URL) nog steeds werkt, en dat een testsignaal bij een gebruiker met een actieve evaluatie nog steeds correct begrensd wordt (herhaal een eerdere evaluatie-sizing-test uit de bestaande scratch-scripts van dit project, zie git log voor het patroon van de evaluatie-plan-taken).

- [ ] **Step 6: Commit**

```bash
git add app/risk.py app/signal_processor.py web/templates/
git commit -m "Generieke portfolio-sizing en zichtbare evaluatie-kaart weg, evaluatie-bewaking blijft actief"
```

---

### Task 12: Coin-pagina: signalenlijst-sectie

**Files:**
- Modify: `web/templates/coin.html`
- Modify: `web/main.py` (coin-pagina-route, waar `recent_signals`/`open_trades` al worden opgehaald)

**Interfaces:**
- Consumes: `macros.signal_card` (Task 6), bestaande `recent_signals`-context-variabele in de coin-pagina-route.

- [ ] **Step 1: Context uitbreiden in `web/main.py`**

Zoek de coin-pagina-routefunctie (waar `recent_signals`/`open_trades` al aan de template-context worden toegevoegd voor gebruik in `coin.js`). Voeg per signaal in `recent_signals` dezelfde `user_confirmed`-berekening toe als in Task 6, Step 2, zodat dezelfde macro hergebruikt kan worden:

```python
    for entry in recent_signals:
        entry["user_confirmed"] = repo.user_confirmed(
            entry["pass_pct"], bool(entry["hard_gates_ok"]), user["confirm_threshold_pct"]
        )
```

- [ ] **Step 2: Sectie toevoegen aan `coin.html`**

Voeg, onder de grafiek en boven of naast de bestaande patroonlijst (`#pattern-list`), een nieuwe sectie toe:

```html
<section class="coin-signals">
  <h2>Signalen voor {{ symbol }}</h2>
  {% if not recent_signals %}
  <p class="muted">Nog geen signalen voor deze coin.</p>
  {% endif %}
  {% for entry in recent_signals %}
  {{ macros.signal_card(entry) }}
  {% endfor %}
</section>
```

(`{% import "_macros.html" as macros %}` staat vermoedelijk al bovenaan `coin.html` voor andere macro's — hergebruik die import, voeg hem niet dubbel toe.)

- [ ] **Step 3: Handmatige Playwright-verificatie**

Bezoek een coin-pagina met bekende testsignalen in de scratch-database, controleer dat de nieuwe sectie leesbare signaalkaarten toont, consistent met de kaarten op `/signalen`.

- [ ] **Step 4: Commit**

```bash
git add web/templates/coin.html web/main.py
git commit -m "Coin-pagina toont recente signalen als leesbare lijst"
```

---

### Task 13: Grafiek — alleen actueel signaal standaard, rest oproepbaar (mobiel-eerst)

**Files:**
- Modify: `web/static/coin.js`
- Modify: `web/static/style.css`
- Modify: `web/templates/coin.html` (nieuw oproep-element)

**Interfaces:**
- Consumes: bestaande `zoneGroups`, `srZoneEls`, `data.trendlines`, `data.patterns` in `coin.js` (regels ~40-320 zoals eerder deze sessie gelezen).
- Produces: een globale JS-variabele/toggle `showAllLayers` (boolean, standaard `false`), functie `applyLayerVisibility()` die community-zones/SR-zones/trendlijnen/patroon-markers buiten het venster van het meest recente signaal verbergt tenzij `showAllLayers` waar is. Knop `#toggle-all-layers` in `coin.html`.

- [ ] **Step 1: Bepalen wat "bij het actuele signaal hoort"**

In de `.then((data) => { ... })`-callback in `coin.js` (na regel 195 zoals eerder gelezen), bepaal het venster van het meest recente signaal: `const latestSignal = recentSignals[0];` (bestaat al, `recentSignals` is al gesorteerd nieuwste eerst per de bestaande dashboard-conventie — controleer dit met een `console.log` tijdens handmatig testen als dat niet zo blijkt). Reken een simpel prijsvenster uit: `latestSignal ? [latestSignal.price - 3 * latestSignal.atr, latestSignal.price + 3 * latestSignal.atr] : null` (ATR moet meegegeven worden vanuit `web/main.py`'s coin-pagina-context in `recentSignals`, voeg `atr` toe aan de bestaande query/serialisatie als die er nog niet in zit).

- [ ] **Step 2: `applyLayerVisibility()` toevoegen**

```javascript
let showAllLayers = false;

function inActiveWindow(price) {
  if (!activeWindow) return true;
  return price >= activeWindow[0] && price <= activeWindow[1];
}

function applyLayerVisibility() {
  zoneEls.forEach(({ group, el }) => {
    el.style.display = showAllLayers || inActiveWindow((group.high + group.low) / 2) ? "" : "none";
  });
  srZoneEls.forEach(({ zone, el }) => {
    const mid = (zone.price_high + zone.price_low) / 2;
    el.style.display = showAllLayers || inActiveWindow(mid) ? "" : "none";
  });
  positionZones();
}
```

Roep `applyLayerVisibility()` aan direct na de bestaande `positionZones()`-aanroep aan het eind van de `.then()`-callback, en opnieuw in de click-handler van de nieuwe knop (Step 3).

- [ ] **Step 3: Knop in `coin.html` en click-handler**

```html
<button type="button" id="toggle-all-layers" class="layer-toggle">Alle niveaus tonen</button>
```

```javascript
const toggleBtn = document.getElementById("toggle-all-layers");
if (toggleBtn) {
  toggleBtn.addEventListener("click", () => {
    showAllLayers = !showAllLayers;
    toggleBtn.textContent = showAllLayers ? "Alleen actueel signaal" : "Alle niveaus tonen";
    applyLayerVisibility();
  });
}
```

- [ ] **Step 4: Mobiel-eerste styling in `style.css`**

```css
.layer-toggle {
  width: 100%;
  padding: 10px 14px;
  margin: 8px 0;
  border-radius: var(--radius-sm);
  border: 1px solid var(--border-interactive);
  background: var(--panel);
  color: var(--text-dim);
  font-size: 13px;
}
@media (min-width: 700px) {
  .layer-toggle { width: auto; }
}
```

(Volle breedte op mobiel — de primaire aanname — smaller op een breder scherm, niet andersom.)

- [ ] **Step 5: Handmatige Playwright-verificatie**

Bezoek een coin-pagina met meerdere community-zones op verschillende prijsniveaus, controleer dat standaard alleen de zone rond het actuele signaal zichtbaar is, en dat de knop de rest toont/verbergt. Test op een mobiel viewport (bijv. 390×844 in Playwright) dat de knop volle breedte heeft.

- [ ] **Step 6: Commit**

```bash
git add web/static/coin.js web/static/style.css web/templates/coin.html web/main.py
git commit -m "Grafiek toont standaard alleen het actuele signaal, rest oproepbaar"
```

---

### Task 14: Grafiek — oude lagen automatisch laten vervagen

**Files:**
- Modify: `web/static/coin.js`
- Modify: `web/static/style.css`

**Interfaces:**
- Consumes: `applyLayerVisibility()`, `zoneEls`, `srZoneEls` (Task 13).

- [ ] **Step 1: "Oud" definiëren voor een zelf-gedetecteerde zone**

Een `SRZone` heeft geen eigen tijdstip, alleen `touches`. Voor "hoe lang geleden voor het laatst geraakt" is een candle-index nodig die er nu niet is. Pragmatische, in lijn met de rest van dit project ("vereenvoudigde aanpak, bruikbare benadering", zie `check_divergence`'s eigen documentatie): een zone die niet binnen het venster van de laatste 20 candles van de opgehaalde data ligt (dus buiten het bereik van `data.candles.slice(-20)`'s prijsrange) telt als "oud". Bereken dit venster net als `activeWindow` in Task 13, Step 1, maar dan op de laatste 20 candles in plaats van rond het signaal:

```javascript
const recentCandles = data.candles.slice(-20);
const recentLow = Math.min(...recentCandles.map((c) => c.low));
const recentHigh = Math.max(...recentCandles.map((c) => c.high));
```

- [ ] **Step 2: Vervagen in plaats van hard verbergen**

Pas `applyLayerVisibility()` uit Task 13 aan zodat een laag buiten dit recente venster (en buiten `activeWindow`, en niet met `showAllLayers` opgeroepen) een `is-faded`-klasse krijgt in plaats van `display: none`:

```javascript
function applyLayerVisibility() {
  srZoneEls.forEach(({ zone, el }) => {
    const mid = (zone.price_high + zone.price_low) / 2;
    const relevant = showAllLayers || inActiveWindow(mid);
    const recent = mid >= recentLow && mid <= recentHigh;
    el.style.display = relevant || recent ? "" : "none";
    el.classList.toggle("is-faded", !relevant && recent);
  });
  positionZones();
}
```

- [ ] **Step 3: CSS voor `.is-faded`**

```css
.chart-zone-sr.is-faded { opacity: 0.25; }
```

- [ ] **Step 4: Handmatige Playwright-verificatie**

Controleer met een testcase die een oude en een recente zone bevat dat de oude zone vervaagt (lagere opacity) in plaats van volledig te verdwijnen, en dat "Alle niveaus tonen" hem weer volledig zichtbaar maakt.

- [ ] **Step 5: Commit**

```bash
git add web/static/coin.js web/static/style.css
git commit -m "Oude, niet meer relevante zones vervagen automatisch op de grafiek"
```

---

### Task 15: Pushmelding-titel — "zelf gedetecteerd" weg

**Files:**
- Modify: `app/market_scanner.py:94` en `app/market_scanner.py:174`

**Interfaces:**
- Consumes: `push_notify.coin_symbol`, bestaande `confidence`-variabele die op deze twee plekken al beschikbaar is (of, na Task 2, `pass_pct`).

- [ ] **Step 1: Titel-opbouw gelijktrekken**

Op beide plekken, vervang:

```python
            title = f"{push_notify.coin_symbol(coin)} {coin} {direction}, zelf gedetecteerd"
```

door dezelfde opbouw als een door-de-gebruiker-doorgestuurd signaal gebruikt (zoek de titel-opbouw in `app/signal_processor.py`'s `process_day_trading_signal`, rond `title = f"{push_notify.coin_symbol(interp.coin)} {interp.coin} {interp.direction}, {signal_data['confidence']}"`, en gebruik exact hetzelfde patroon):

```python
            title = f"{push_notify.coin_symbol(coin)} {coin} {direction}, {confidence}"
```

Controleer op beide plekken in `market_scanner.py` of een lokale `confidence`-variabele al bestaat op het punt waar deze titel wordt opgebouwd; zo niet, bereken hem net als in `signal_processor.py`: `confidence = "hoog vertrouwen" if confirmed else "laag vertrouwen"`.

- [ ] **Step 2: Verifiëren met een throwaway script**

```bash
grep -n "zelf gedetecteerd" app/market_scanner.py
```

Verwacht: geen output (de string komt niet meer voor in de titel-opbouw; een eventuele overblijvende `Zelf gedetecteerd door HesPulse`-tekst in `app/repo.py`'s `message_summary`-fallback is een ANDER, dashboard-gericht stuk tekst en blijft ongewijzigd).

- [ ] **Step 3: Commit**

```bash
git add app/market_scanner.py
git commit -m "Pushmelding voor zelf-gedetecteerde signalen toont vertrouwen i.p.v. 'zelf gedetecteerd'"
```

---

### Task 16: Periodieke zelfevaluatie van de factoren

**Files:**
- Create: `scripts/factor_drift_check.py`
- Create: `deploy/crypto-factor-check.service`
- Create: `deploy/crypto-factor-check.timer`
- Modify: `README.md` (nieuwe timer vermelden bij de andere systemd-timers)

**Interfaces:**
- Consumes: dezelfde historische-pass-rate-berekening als `scripts/backtest_factors.py` (hergebruik de functie die per factor een pass-rate teruggeeft, importeer die functie in plaats van de logica te dupliceren).
- Produces: `app.notifications`-rij (hergebruik `repo.create_notification`, zie het bestaande gebruik voor `"admin_error"` in `app/signal_processor.py`) bij een factor die structureel afwijkt.

- [ ] **Step 1: Drempel voor "structureel afwijkt" vaststellen**

Een factor die de afgelopen `FACTOR_DRIFT_LOOKBACK` (bijv. 50) signalen een pass-rate heeft die meer dan `FACTOR_DRIFT_THRESHOLD_PP` (bijv. 15 procentpunt) lager ligt dan zijn totale historische pass-rate, telt als afwijkend.

- [ ] **Step 2: Script schrijven**

```python
"""Periodieke check: is een factor de laatste tijd structureel minder
betrouwbaar dan zijn eigen historische gemiddelde? scripts/backtest_factors.py
berekent dit al eenmalig en handmatig; dit script draait dezelfde
berekening periodiek en waarschuwt zelf in plaats van dat iemand het
script moet onthouden te draaien.

Draai met: python3 scripts/factor_drift_check.py
Bedoeld voor een systemd-timer, zie deploy/crypto-factor-check.timer.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import repo
from scripts.backtest_factors import compute_factor_pass_rates  # hergebruik, niet dupliceren

FACTOR_DRIFT_LOOKBACK = 50
FACTOR_DRIFT_THRESHOLD_PP = 15.0


def run() -> None:
    rates = compute_factor_pass_rates()  # {factor_naam: (recente_pass_rate, historische_pass_rate)}
    for name, (recent, historical) in rates.items():
        if historical - recent >= FACTOR_DRIFT_THRESHOLD_PP:
            repo.create_notification(
                None, "factor_drift",
                f"Factor '{name}' wijkt af",
                f"Historisch {historical:.0f}% raak, laatste {FACTOR_DRIFT_LOOKBACK} signalen nog maar "
                f"{recent:.0f}%. Kan wijzen op een marktverandering.",
                None,
            )


if __name__ == "__main__":
    run()
```

Als `scripts/backtest_factors.py` geen losse, importeerbare functie `compute_factor_pass_rates` heeft (het is nu mogelijk één script zonder herbruikbare functie-indeling), refactor eerst de bestaande per-factor-berekening in dat script naar zo'n functie zodat dit nieuwe script hem kan hergebruiken in plaats van de berekening te kopiëren — dat is een losse, kleine sub-stap binnen deze taak, geen aparte taak.

- [ ] **Step 3: systemd-bestanden**

`deploy/crypto-factor-check.service` en `.timer`, exact naar het patroon van `deploy/crypto-health-check.service`/`.timer` (kopieer de structuur, pas `Description=` en `ExecStart=.../scripts/factor_drift_check.py` aan), met `OnCalendar=Sun *-*-* 21:00:00` (wekelijks, past niet in dezelfde minuut-grid als de andere timers, dus geen collision-commentaar nodig zoals bij `crypto-market-scan.timer`).

- [ ] **Step 4: Verifiëren met een throwaway script**

```bash
DATABASE_PATH=/tmp/scratch_puur_signalen.db python3 scripts/factor_drift_check.py
```

Verwacht: geen exceptie (met een lege scratch-database levert `compute_factor_pass_rates()` een lege dict op, dus geen waarschuwingen, geen crash).

- [ ] **Step 5: README bijwerken**

Voeg de nieuwe timer toe aan de sectie "Achtergrondprocessen met automatisch herstarten" in `README.md`, naar het patroon van de bestaande vermeldingen.

- [ ] **Step 6: Commit**

```bash
git add scripts/factor_drift_check.py scripts/backtest_factors.py deploy/crypto-factor-check.* README.md
git commit -m "Periodieke zelfevaluatie: waarschuwing bij een factor die structureel afwijkt"
```

---

### Task 17: Volledige regressie + push

**Files:** geen nieuwe, alleen verificatie.

- [ ] **Step 1: Grep-controle op resterende verwijzingen naar verwijderde routes**

```bash
grep -rn "/dashboard\"" web/ app/ | grep -v "\.pyc"
grep -rn "portfolio_eur\|risk_percent" web/templates/
grep -rn "coins/{symbol}/oefen\"" web/
```

Elke hit moet bewust zijn (bijv. `risk_percent` mag nog in `app/schema.sql`/`app/repo.py` staan als kolomnaam, maar niet meer in een zichtbaar formulier).

- [ ] **Step 2: Volledige scratch-database doorloop**

```bash
rm -f /tmp/scratch_puur_signalen.db
DATABASE_PATH=/tmp/scratch_puur_signalen.db python3 scripts/create_user.py
DATABASE_PATH=/tmp/scratch_puur_signalen.db uvicorn web.main:app --port 8001 &
sleep 2
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8001/signalen
curl -s -o /dev/null -w "%{http_code}\n" http://127.0.0.1:8001/account
kill %1
```

(De `/signalen` en `/account`-checks geven hier een redirect naar `/login` omdat er geen sessie is, verwacht `303`, geen `500`.)

- [ ] **Step 3: Handmatige Playwright-eindverificatie**

Doorloop met een echte login: `/signalen` (kale lijst, hoogste percentage bovenaan, geen Genomen/Negeren), `/account` (journaal, winrate, drempel-instelling, geen portfolio-formulier, geen evaluatie-kaart), een coin-pagina (signalenlijst-sectie, grafiek toont standaard alleen het actuele signaal, "Alle niveaus tonen" werkt, oude zones vervagen), en de positie-berekenaar (nog steeds werkend zonder aanmaak-knop).

- [ ] **Step 4: Push**

```bash
git push
```

