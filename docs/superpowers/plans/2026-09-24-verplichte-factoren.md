# Verplichte factoren per gebruiker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Laat elke gebruiker specifieke technische factoren (van de 18
gepoolde factoren die `confirms_direction` toetst) persoonlijk verplicht
stellen: staat zo'n factor ✗ (of ontbreekt hij helemaal) in een signaal, dan
telt dat signaal voor deze gebruiker nooit als bevestigd, ongeacht zijn
percentage-drempel.

**Architecture:** Een nieuwe, per-gebruiker `user_required_factors`-tabel
plus drie repo-functies erbovenop. `repo.user_confirmed` (de bestaande
enkele-waarheidsbron voor "is dit bevestigd voor deze gebruiker", nu al op
vier plekken in vier bestanden aangeroepen) krijgt twee nieuwe optionele
parameters en logt een AND bovenop zijn bestaande percentage-vergelijking.
Een nieuwe parser leest de bestaande "✓ Naam: ... | ✗ Naam: ..."-
breakdown-tekst (`signals.reason`) om per factor te weten of hij ✓ stond,
✗ stond, of nooit gecheckt werd (fail-closed: nooit gecheckt telt als niet
voldaan). Elke aanroepplek haalt de vereiste factoren van de betrokken
gebruiker(s) batch-gewijs op vóór de vergelijking, nooit per rij.

**Tech Stack:** Python 3, FastAPI, Jinja2, SQLite (WAL-mode via
`app/db.py`), geen ORM — rauwe SQL via `app/repo.py`.

**Spec:** `docs/superpowers/specs/2026-09-24-verplichte-factoren-design.md`

## Global Constraints

- Alleen van toepassing op `trade_type in ("day_trading", "patroon")` —
  swing blijft altijd `required_factors` leeg/genegeerd, zijn bestaande
  "altijd bevestigd"-kortsluiting verandert niet.
- De drie bestaande harde eisen (Uitgerektheid, BTC-trend, Daily-trend)
  blijven universeel en NIET toggle-baar — ze staan niet in
  `TOGGLEABLE_FACTORS` en worden nergens in dit plan aangeraakt.
- Fail-closed: een verplichte factor die niet in `signals.reason`
  voorkomt telt als niet voldaan (`results.get(f, False)`, nooit
  `.get(f, True)`).
- Bestaande drie-parameter-aanroepen van `repo.user_confirmed` (zonder de
  twee nieuwe argumenten) moeten exact hetzelfde gedrag blijven vertonen
  — de twee nieuwe parameters zijn optioneel met default die het huidige
  gedrag reproduceert.
- Geen wijziging aan hoe het percentage zelf berekend wordt
  (`confirms_direction`), aan stop-loss/take-profit/positiegrootte, of
  aan enige weging per factor.
- App-conventie: `app/repo.py` is de enige plek met databasetoegang.
  Nieuwe tabellen: `CREATE TABLE IF NOT EXISTS` in `app/schema.sql`
  volstaat (geen `_migrate()`-guard nodig) — precedent `muted_coins`/
  `sr_zone_failures`, allebei brand-new tabellen zonder migratie-entry.
  Geen pytest-suite in dit project: verificatie via throwaway scripts
  tegen een scratch-database (`DATABASE_PATH=/tmp/scratch.db`), en
  handmatige Playwright-verificatie voor UI-wijzigingen.

---

## Task 1: Schema + TOGGLEABLE_FACTORS-constante

**Files:**
- Modify: `app/schema.sql` (nieuwe tabel, na de bestaande tabellen)
- Modify: `app/indicators.py:1126-1129` (nieuwe module-constante, tussen
  `RSI_OVERSOLD` en `def basic_factors`)
- Test: scratchpad-script, geen permanent testbestand

**Interfaces:**
- Produces: tabel `user_required_factors(id, user_id, factor_name,
  created_at)`, UNIQUE(user_id, factor_name), index op user_id.
  Module-constante `indicators.TOGGLEABLE_FACTORS: list[tuple[str, str]]`
  — 18 (naam, uitleg)-paren.

- [ ] **Step 1: Voeg de nieuwe tabel toe aan `app/schema.sql`**

Zoek de bestaande `muted_coins`-tabel (rond regel 166) als precedent en
voeg de nieuwe tabel ergens in het bestand toe, bijvoorbeeld direct erna:

```sql
CREATE TABLE IF NOT EXISTS user_required_factors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    factor_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, factor_name)
);
CREATE INDEX IF NOT EXISTS idx_user_required_factors_user ON user_required_factors(user_id);
```

Geen `_migrate()`-guard nodig: dit is een brand-new tabel, `CREATE TABLE
IF NOT EXISTS` bereikt zowel een verse als een bestaande database.

- [ ] **Step 2: Voeg `TOGGLEABLE_FACTORS` toe aan `app/indicators.py`**

Plaats dit tussen de bestaande `RSI_OVERSOLD = 25` (regel 1126) en
`def basic_factors` (regel 1129). Namen moeten LETTERLIJK overeenkomen
met wat `confirms_direction`/de losse `check_*`-functies als factornaam
in de breakdown-tekst zetten (elke naam hieronder is geverifieerd tegen
de exacte `return ("Naam", ok, detail)`-statements in `app/indicators.py`
en `app/signal_processor.py::compute_advanced_extra_factors`):

```python
# Alle 18 factoren die confirms_direction in de uitgebreide toetsing
# meeweegt (dus zonder Uitgerektheid, BTC-trend en Daily-trend — die
# drie zijn universele harde eisen, niet per gebruiker uit te zetten,
# zie docs/superpowers/specs/2026-09-24-verplichte-factoren-design.md).
# Enige bron van waarheid voor zowel de validatie in de opslaan-route
# (web/main.py::update_required_factors_setting) als de weergave op
# /account — een naam hier die niet letterlijk overeenkomt met wat een
# check-functie teruggeeft, betekent stilzwijgend "deze factor komt
# nooit voor in een breakdown, dus faalt altijd fail-closed" (zie
# repo.user_confirmed/_parse_factor_results).
TOGGLEABLE_FACTORS: list[tuple[str, str]] = [
    ("Trend", "EMA9 t.o.v. EMA21 volgt de richting van de trade"),
    ("Momentum", "MACD-lijn t.o.v. signaallijn volgt de richting"),
    ("RSI", "Niet al te extreem overbought/oversold tegen de richting in"),
    ("Volume", "Minstens gemiddeld handelsvolume, geen dunne markt"),
    ("Trendsterkte", "ADX sterk genoeg en wijst de juiste kant op"),
    ("Volatiliteit", "Prijsbeweging (ATR) trekt niet samen, markt leeft"),
    ("Volume-percentiel", "Huidig volume zit hoog genoeg t.o.v. recente historie"),
    ("RSI daily", "RSI op dagniveau bevestigt, niet extreem tegen de richting in"),
    ("Premium/discount", "Entry in de goedkope (long) of dure (short) helft van de recente range"),
    ("Premium/discount (dag)", "Zelfde, op dagniveau — een sterker signaal"),
    ("Liquidity sweep", "Recente stop-hunt (pen door een niveau, direct terug) in de goede richting"),
    ("Liquidity sweep (dag)", "Zelfde, op dagniveau"),
    ("1u bevestiging", "De trend op het 1-uur-timeframe bevestigt de richting"),
    ("RSI 1u", "RSI op 1 uur bevestigt, niet extreem"),
    ("Divergentie", "Geen waarschuwende afwijking tussen prijs en RSI"),
    ("Candlepatroon", "Een herkenbaar candlestick-patroon ondersteunt de richting"),
    ("Liquiditeit", "Genoeg 24u-handelsvolume om in en uit te kunnen zonder de prijs te bewegen"),
    ("Steun/weerstand", "Een bevestigde terugveer op een zelf-gedetecteerde zone"),
]
```

- [ ] **Step 3: Verifieer de tabel en de constante in een scratch-DB**

```bash
DATABASE_PATH=/tmp/scratch_task1.db python3 -c "
from app import db, indicators
db.init_db()
import sqlite3
conn = sqlite3.connect('/tmp/scratch_task1.db')
cols = [r[1] for r in conn.execute('PRAGMA table_info(user_required_factors)')]
assert cols == ['id', 'user_id', 'factor_name', 'created_at'], cols
assert len(indicators.TOGGLEABLE_FACTORS) == 18, len(indicators.TOGGLEABLE_FACTORS)
names = [n for n, _ in indicators.TOGGLEABLE_FACTORS]
assert 'Uitgerektheid' not in names and 'BTC-trend' not in names and 'Daily-trend' not in names
print('OK')
"
rm -f /tmp/scratch_task1.db
```

Expected: `OK` zonder AssertionError.

- [ ] **Step 4: Commit**

```bash
git add app/schema.sql app/indicators.py
git commit -m "Voeg user_required_factors-tabel en TOGGLEABLE_FACTORS-constante toe"
```

---

## Task 2: repo.py — CRUD voor verplichte factoren

**Files:**
- Modify: `app/repo.py` (drie nieuwe functies, plaats ze bijvoorbeeld
  direct vóór de `# Per-gebruiker bevestigde status en winrate`-sectie
  rond regel 2512, waar `user_confirmed` al staat — logisch verwant)

**Interfaces:**
- Consumes: tabel `user_required_factors` (Task 1).
- Produces: `list_required_factors(user_id: int) -> set[str]`,
  `list_required_factors_all_users() -> dict[int, set[str]]`,
  `set_required_factors(user_id: int, factor_names: list[str]) -> None`
  — gebruikt door Task 4-8.

- [ ] **Step 1: Voeg de drie functies toe aan `app/repo.py`**

```python
def list_required_factors(user_id: int) -> set[str]:
    """Alle factoren die deze gebruiker verplicht heeft gesteld."""
    with db.session() as conn:
        rows = conn.execute(
            "SELECT factor_name FROM user_required_factors WHERE user_id = ?",
            (user_id,),
        ).fetchall()
        return {row["factor_name"] for row in rows}


def list_required_factors_all_users() -> dict[int, set[str]]:
    """Batch-variant voor de marktscan-fanout en level_check.py: één query
    voor alle gebruikers tegelijk in plaats van één per gebruiker per
    signaal — zelfde 'één keer per cyclus, niet per rij'-discipline als
    pattern_winrate_stats()/winrate_stats() elders in dit bestand."""
    with db.session() as conn:
        rows = conn.execute("SELECT user_id, factor_name FROM user_required_factors").fetchall()
    result: dict[int, set[str]] = {}
    for row in rows:
        result.setdefault(row["user_id"], set()).add(row["factor_name"])
    return result


def set_required_factors(user_id: int, factor_names: list[str]) -> None:
    """Vervangt de hele set in één transactie (DELETE + INSERT): de
    instellingenpagina stuurt altijd de complete, actuele lijst, geen los
    toevoegen/verwijderen nodig."""
    with db.session() as conn:
        conn.execute("DELETE FROM user_required_factors WHERE user_id = ?", (user_id,))
        conn.executemany(
            "INSERT INTO user_required_factors (user_id, factor_name, created_at) VALUES (?, ?, ?)",
            [(user_id, name, db.now_iso()) for name in factor_names],
        )
```

- [ ] **Step 2: Scratch-DB round-trip test**

```bash
DATABASE_PATH=/tmp/scratch_task2.db python3 -c "
from app import db, repo
db.init_db()
uid = repo.create_user('testuser', 'hash', 1000.0, 1.0)

# Leeg bij start
assert repo.list_required_factors(uid) == set()
assert repo.list_required_factors_all_users() == {}

# Zetten en teruglezen
repo.set_required_factors(uid, ['Trend', 'RSI'])
assert repo.list_required_factors(uid) == {'Trend', 'RSI'}
assert repo.list_required_factors_all_users() == {uid: {'Trend', 'RSI'}}

# Vervangen (niet optellen) — oude selectie moet volledig weg zijn
repo.set_required_factors(uid, ['Volume'])
assert repo.list_required_factors(uid) == {'Volume'}

# Leegmaken
repo.set_required_factors(uid, [])
assert repo.list_required_factors(uid) == set()
print('OK')
"
rm -f /tmp/scratch_task2.db
```

Expected: `OK` zonder AssertionError.

- [ ] **Step 3: Commit**

```bash
git add app/repo.py
git commit -m "Voeg CRUD-functies voor per-gebruiker verplichte factoren toe"
```

---

## Task 3: repo.py — user_confirmed uitbreiden + _parse_factor_results

**Files:**
- Modify: `app/repo.py:2516-2524` (bestaande `user_confirmed`-functie
  vervangen, nieuwe `_parse_factor_results`-helper ervoor toevoegen)

**Interfaces:**
- Consumes: niets nieuws — puur een signature-uitbreiding van een
  bestaande functie.
- Produces: `user_confirmed(pass_pct, hard_gates_ok, threshold_pct,
  reason: str = "", required_factors: Optional[set[str]] = None) -> bool`
  (bestaande drie-parameter-aanroepen blijven werken, ongewijzigd
  gedrag). `_parse_factor_results(reason: str) -> dict[str, bool]` —
  gebruikt alleen intern door `user_confirmed`. Beide gebruikt door
  Task 4-7.

- [ ] **Step 1: Vervang de bestaande `user_confirmed`-functie**

De huidige functie (regel 2516-2524):

```python
def user_confirmed(pass_pct: Optional[float], hard_gates_ok: bool, threshold_pct: float) -> bool:
    """Of een signaal voor DEZE gebruiker als bevestigd geldt: de twee
    harde eisen (al verwerkt in hard_gates_ok) blijven voor iedereen hard,
    alleen het percentage van de gepoolde factoren wordt per gebruiker
    tegen zijn eigen drempel gelegd. pass_pct is None voor legacy-signalen
    (van vóór deze kolom bestond) en voor swing-signalen (die geen gepoold
    percentage hebben) - zo'n signaal telt nooit als bevestigd, ongeacht
    de drempel."""
    return bool(hard_gates_ok) and pass_pct is not None and pass_pct >= threshold_pct
```

wordt:

```python
def _parse_factor_results(reason: str) -> dict[str, bool]:
    """Zelfde breakdown-formaat als confirms_direction opbouwt
    ("✓ Trend: ... | ✗ Volume: ..."), maar dan ALLE voorkomende factoren
    met hun ✓/✗-status, niet alleen de gefaalde (vergelijk
    signal_processor._extract_failing_factors, die alleen de ✗'s
    teruggeeft en hier niet volstaat: fail-closed op afwezigheid vereist
    weten welke namen WEL voorkwamen, niet alleen welke faalden)."""
    results: dict[str, bool] = {}
    for part in reason.split(" | "):
        part = part.strip()
        if part[:1] in ("✓", "✗"):
            name = part[1:].split(":", 1)[0].strip()
            results[name] = part.startswith("✓")
    return results


def user_confirmed(
    pass_pct: Optional[float], hard_gates_ok: bool, threshold_pct: float,
    reason: str = "", required_factors: Optional[set[str]] = None,
) -> bool:
    """Of een signaal voor DEZE gebruiker als bevestigd geldt. Twee lagen:
    (1) de twee harde eisen (al verwerkt in hard_gates_ok) plus het
    percentage van de gepoolde factoren tegen de eigen drempel van de
    gebruiker — het bestaande gedrag, ongewijzigd als required_factors
    leeg of None is. pass_pct is None voor legacy-signalen (van vóór deze
    kolom bestond) en voor swing-signalen (die geen gepoold percentage
    hebben) - zo'n signaal telt nooit als bevestigd, ongeacht de drempel.
    (2) optioneel, bovenop laag 1: required_factors is de set factoren die
    DEZE gebruiker zelf verplicht heeft gesteld (zie
    list_required_factors) — staat er ook maar één van ✗, of komt hij
    helemaal niet voor in reason (fail-closed, nooit gecheckt telt als
    niet voldaan), dan telt het signaal voor deze gebruiker nooit als
    bevestigd, ongeacht het percentage. Alleen relevant voor day_trading/
    patroon-signalen; voor swing wordt required_factors simpelweg niet
    meegegeven door de aanroeper."""
    base_confirmed = bool(hard_gates_ok) and pass_pct is not None and pass_pct >= threshold_pct
    if not base_confirmed or not required_factors:
        return base_confirmed
    results = _parse_factor_results(reason)
    return all(results.get(f, False) for f in required_factors)
```

- [ ] **Step 2: Regressietest tegen de bestaande drie-parameter-aanroepen**

Dit is de belangrijkste stap van deze taak: bewijs dat bestaand gedrag
niet verandert, vóór je verder gaat.

```bash
DATABASE_PATH=/tmp/scratch_task3.db python3 -c "
from app import db, repo
db.init_db()

# Drie-parameter-aanroep (bestaand gedrag, zoals winrate_for_user vóór
# Task 7 en de andere drie call sites vóór hun eigen taak): identiek aan
# vóór deze wijziging.
assert repo.user_confirmed(70.0, True, 60.0) is True
assert repo.user_confirmed(50.0, True, 60.0) is False
assert repo.user_confirmed(70.0, False, 60.0) is False
assert repo.user_confirmed(None, True, 60.0) is False

# Nieuw: geen verplichte factoren (lege set of None) -> ongewijzigd gedrag
reason = '✓ Trend: EMA9 boven EMA21 | ✗ Volume: onder gemiddeld | ✓ RSI: RSI 55'
assert repo.user_confirmed(70.0, True, 60.0, reason=reason, required_factors=set()) is True
assert repo.user_confirmed(70.0, True, 60.0, reason=reason, required_factors=None) is True

# Verplichte factor die ✓ staat -> bevestigd blijft bevestigd
assert repo.user_confirmed(70.0, True, 60.0, reason=reason, required_factors={'Trend'}) is True

# Verplichte factor die ✗ staat -> nooit bevestigd, ook niet bij een hoog percentage
assert repo.user_confirmed(95.0, True, 60.0, reason=reason, required_factors={'Volume'}) is False

# Verplichte factor die helemaal niet in reason voorkomt -> fail-closed, nooit bevestigd
assert repo.user_confirmed(95.0, True, 60.0, reason=reason, required_factors={'Trendsterkte'}) is False

# Meerdere verplichte factoren: allemaal moeten kloppen (AND)
assert repo.user_confirmed(95.0, True, 60.0, reason=reason, required_factors={'Trend', 'RSI'}) is True
assert repo.user_confirmed(95.0, True, 60.0, reason=reason, required_factors={'Trend', 'Volume'}) is False

# _parse_factor_results zelf, losse check
parsed = repo._parse_factor_results(reason)
assert parsed == {'Trend': True, 'Volume': False, 'RSI': True}, parsed
print('OK')
"
rm -f /tmp/scratch_task3.db
```

Expected: `OK` zonder AssertionError.

- [ ] **Step 3: Commit**

```bash
git add app/repo.py
git commit -m "Breid user_confirmed uit met optionele per-gebruiker verplichte factoren"
```

---

## Task 4: web/main.py — _apply_user_confirmed threaden

**Files:**
- Modify: `web/main.py:203` (signalen_page, binnen `signalen_page`-route)
- Modify: `web/main.py:612-631` (`_apply_user_confirmed`-functie zelf)
- Modify: `web/main.py:1636` (coin_page-route, op `recent_signals`)

**Interfaces:**
- Consumes: `repo.list_required_factors(user_id) -> set[str]` (Task 2),
  `repo.user_confirmed(..., reason=..., required_factors=...)` (Task 3).
- Produces: `_apply_user_confirmed(entries, threshold_pct,
  required_factors)` — geen andere aanroepers dan deze twee routes (zie
  spec Component 3: dashboard en /account roepen deze functie NIET aan,
  daar blijft de bevestigd-vlag ongewijzigd afwezig).

- [ ] **Step 1: Werk `_apply_user_confirmed` zelf bij**

Huidige body (regel 612-631):

```python
def _apply_user_confirmed(entries: list[dict], threshold_pct: float) -> None:
    """Zet entry['user_confirmed'] per signaal, de echte trade-kans-vlag
    achter macros.signal_card's groene rand. Swing is altijd bevestigd
    (geen gepoold percentage, een echte terugveer op een bewaakt niveau).
    Dagtrading en patroon tellen pas als bevestigd zodra hun EIGEN
    percentage (pass_pct resp. success_rate/kansberekening) de drempel van
    deze gebruiker haalt — voorheen kreeg elk patroon-signaal hier
    onvoorwaardelijk True, dus een kansberekening van 30% kreeg dezelfde
    groene rand als een kansberekening van 90%, amper onderscheid tussen
    een echte kans en ruis. Moet NA _add_signal_context draaien: patroon se
    success_rate bestaat pas dan."""
    for entry in entries:
        if entry["trade_type"] == "swing":
            entry["user_confirmed"] = True
        elif entry["trade_type"] == "patroon":
            entry["user_confirmed"] = repo.user_confirmed(
                entry.get("success_rate"), bool(entry["hard_gates_ok"]), threshold_pct,
            )
        else:
            entry["user_confirmed"] = repo.user_confirmed(
                entry["pass_pct"], bool(entry["hard_gates_ok"]), threshold_pct,
            )
```

Wordt (nieuwe parameter `required_factors`, doorgegeven aan de twee
niet-swing takken, swing blijft ongewijzigd):

```python
def _apply_user_confirmed(entries: list[dict], threshold_pct: float, required_factors: set[str]) -> None:
    """Zet entry['user_confirmed'] per signaal, de echte trade-kans-vlag
    achter macros.signal_card's groene rand. Swing is altijd bevestigd
    (geen gepoold percentage, een echte terugveer op een bewaakt niveau) —
    required_factors is daar niet van toepassing (zie de spec), dus die
    tak geeft hem simpelweg niet door. Dagtrading en patroon tellen pas
    als bevestigd zodra hun EIGEN percentage (pass_pct resp. success_rate/
    kansberekening) de drempel van deze gebruiker haalt EN (als de
    gebruiker zelf factoren verplicht heeft gesteld) die factoren ✓ staan
    in de breakdown — voorheen kreeg elk patroon-signaal hier
    onvoorwaardelijk True, dus een kansberekening van 30% kreeg dezelfde
    groene rand als een kansberekening van 90%, amper onderscheid tussen
    een echte kans en ruis. Moet NA _add_signal_context draaien: patroon se
    success_rate bestaat pas dan."""
    for entry in entries:
        if entry["trade_type"] == "swing":
            entry["user_confirmed"] = True
        elif entry["trade_type"] == "patroon":
            entry["user_confirmed"] = repo.user_confirmed(
                entry.get("success_rate"), bool(entry["hard_gates_ok"]), threshold_pct,
                reason=entry.get("reason") or "", required_factors=required_factors,
            )
        else:
            entry["user_confirmed"] = repo.user_confirmed(
                entry["pass_pct"], bool(entry["hard_gates_ok"]), threshold_pct,
                reason=entry.get("reason") or "", required_factors=required_factors,
            )
```

- [ ] **Step 2: Werk de aanroep in `signalen_page` bij (regel 203)**

Huidig:

```python
    _apply_user_confirmed(entries, user["confirm_threshold_pct"])
```

Wordt (haal de verplichte factoren van deze gebruiker eenmalig op,
dezelfde plek als de bestaande `winrate = repo.winrate_stats(user["id"])`
een regel erboven):

```python
    required_factors = repo.list_required_factors(user["id"])
    _apply_user_confirmed(entries, user["confirm_threshold_pct"], required_factors)
```

- [ ] **Step 3: Werk de aanroep in `coin_page` bij (regel 1636)**

Huidig:

```python
    _apply_user_confirmed(recent_signals, user["confirm_threshold_pct"])
```

Wordt:

```python
    required_factors = repo.list_required_factors(user["id"])
    _apply_user_confirmed(recent_signals, user["confirm_threshold_pct"], required_factors)
```

- [ ] **Step 4: FastAPI TestClient-verificatie**

```bash
DATABASE_PATH=/tmp/scratch_task4.db python3 -c "
from app import db, repo
db.init_db()
uid = repo.create_user('testuser', 'x', 1000.0, 1.0)

signal_id = repo.insert_signal({
    'message_id': None, 'coin': 'BTC', 'direction': 'long',
    'category': 'day_trading', 'trade_type': 'day_trading',
    'price': 50000.0, 'rsi': 55.0, 'macd': 1.0, 'macd_signal': 0.5,
    'volume_ratio': 1.2, 'ema9': 50100.0, 'ema21': 50000.0, 'atr': 500.0,
    'atr_avg20': 480.0, 'adx': 20.0, 'technical_confirmed': 1,
    'pass_pct': 80.0, 'hard_gates_ok': 1, 'confidence': 'hoog vertrouwen',
    'reason': '✓ Trend: EMA9 boven EMA21 | ✗ Volume: onder gemiddeld | ✓ RSI: RSI 55',
    'stop_loss': 49000.0, 'take_profit': 52000.0, 'context_note': None,
    'is_practice': 0, 'plain_explanation': None,
})
entry_id = repo.create_journal_entry(signal_id, uid, 10.0)

entries = repo.list_signalen_for_user(uid)
assert len(entries) == 1

from web.main import _apply_user_confirmed
# Zonder verplichte factoren: percentage (80) boven drempel (60) -> bevestigd
_apply_user_confirmed(entries, 60.0, set())
assert entries[0]['user_confirmed'] is True

# Met een verplichte factor die ✗ staat: nooit bevestigd, ondanks het hoge percentage
_apply_user_confirmed(entries, 60.0, {'Volume'})
assert entries[0]['user_confirmed'] is False
print('OK')
"
rm -f /tmp/scratch_task4.db
```

Expected: `OK` zonder AssertionError.

- [ ] **Step 5: Commit**

```bash
git add web/main.py
git commit -m "Geef verplichte factoren door aan _apply_user_confirmed (/signalen, coin-pagina)"
```

---

## Task 5: signal_processor.py + market_scanner.py — pushmelding-gate

**Files:**
- Modify: `app/signal_processor.py:429-529` (`_fanout_confirmed_signal`)
- Modify: `app/market_scanner.py` (drie `fanout_confirmed_signal(...)`-
  aanroepen: rond regel 196-202, 347-353, 612-617)

**Interfaces:**
- Consumes: `repo.list_required_factors_all_users() -> dict[int,
  set[str]]` (Task 2), `repo.user_confirmed(..., reason=...,
  required_factors=...)` (Task 3).
- Produces: `_fanout_confirmed_signal(..., reason: str = "")` — nieuwe
  parameter, ook bereikbaar via de bestaande publieke alias
  `fanout_confirmed_signal` (regel 531: `fanout_confirmed_signal =
  _fanout_confirmed_signal`, geen aparte aanpassing nodig). Swing (via
  `run_swing_check`, regel 610-615) geeft `reason` niet mee — kansberekening
  is daar de sentinel `_KANSBEREKENING_NOT_APPLICABLE`, dus de push-gate
  slaat de user_confirmed-vergelijking toch over (`skip_this_user =
  skip_push`), `reason=""` blijft daar onschadelijk ongebruikt.

- [ ] **Step 1: Voeg de `reason`-parameter toe aan `_fanout_confirmed_signal`**

In `app/signal_processor.py`, de functiesignatuur (regel 429-435):

```python
async def _fanout_confirmed_signal(
    signal_id: int, coin: str, direction: str, entry_price: float,
    stop_loss: float, take_profit: float, premise_level: float, title: str,
    make_body: Callable[[float, float, bool], str],
    skip_push: bool = False,
    kansberekening=_KANSBEREKENING_NOT_APPLICABLE, hard_gates_ok: bool = True,
) -> None:
```

wordt:

```python
async def _fanout_confirmed_signal(
    signal_id: int, coin: str, direction: str, entry_price: float,
    stop_loss: float, take_profit: float, premise_level: float, title: str,
    make_body: Callable[[float, float, bool], str],
    skip_push: bool = False,
    kansberekening=_KANSBEREKENING_NOT_APPLICABLE, hard_gates_ok: bool = True,
    reason: str = "",
) -> None:
```

Voeg aan de docstring toe (na de bestaande alinea over `hard_gates_ok`,
rond regel 456-457):

```
    reason is de factor-breakdown-tekst van dit signaal (dezelfde
    "✓ Naam: ... | ✗ Naam: ..."-tekst als signals.reason), nodig om per
    gebruiker zijn eigen verplichte-factoren-eis te toetsen (zie
    repo.user_confirmed). Alleen relevant samen met kansberekening
    (patroon); bij de sentinel (swing) wordt hij simpelweg niet gebruikt.
```

- [ ] **Step 2: Haal de verplichte factoren batch-gewijs op, vóór de loop**

Zoek `for user in repo.list_users():` (regel 471) en voeg er vlak vóór
toe:

```python
    required_by_user = repo.list_required_factors_all_users()
    for user in repo.list_users():
```

- [ ] **Step 3: Geef de nieuwe argumenten door in de user_confirmed-aanroep**

Huidig (regel 511-514):

```python
        if kansberekening is _KANSBEREKENING_NOT_APPLICABLE:
            skip_this_user = skip_push
        else:
            skip_this_user = not repo.user_confirmed(kansberekening, hard_gates_ok, user["confirm_threshold_pct"])
```

wordt:

```python
        if kansberekening is _KANSBEREKENING_NOT_APPLICABLE:
            skip_this_user = skip_push
        else:
            skip_this_user = not repo.user_confirmed(
                kansberekening, hard_gates_ok, user["confirm_threshold_pct"],
                reason=reason, required_factors=required_by_user.get(user["id"], set()),
            )
```

- [ ] **Step 4: Geef `reason=factor_breakdown` mee vanuit `market_scanner.py`**

Drie call sites, elk al met een lokale `factor_breakdown`-variabele uit
`compute_full_confirmation` (zie de `_, factor_breakdown, factor_pass_pct,
factor_hard_gates_ok = await compute_full_confirmation(...)`-regel vlak
erboven in elke functie). Voeg in elk van de drie `await
fanout_confirmed_signal(...)`-aanroepen een regel toe:

Rond regel 196-202 (`_find_breakout_retest_candidate`):

```python
        await fanout_confirmed_signal(
            signal_id, coin, direction, ind.price, stop_take.stop_loss, stop_take.take_profit, premise_level,
            title=f"{push_notify.coin_symbol(coin)} {coin} {direction}, {pattern_label}",
            make_body=_breakout_body,
            kansberekening=kansberekening,
            hard_gates_ok=bool(factor_hard_gates_ok),
            reason=factor_breakdown,
        )
```

Rond regel 347-353 (`_find_trendline_retest_candidate`):

```python
        await fanout_confirmed_signal(
            signal_id, coin, direction, ind.price, stop_take.stop_loss, stop_take.take_profit, current_value,
            title=f"{push_notify.coin_symbol(coin)} {coin} {direction}, {pattern_label}",
            make_body=_trendline_body,
            kansberekening=kansberekening,
            hard_gates_ok=bool(factor_hard_gates_ok),
            reason=factor_breakdown,
        )
```

Rond regel 612-617 (`_find_chart_pattern_candidate`):

```python
        await fanout_confirmed_signal(
            signal_id, coin, match.direction, ind.price, stop_loss, take_profit, match.neckline,
            title=f"{push_notify.coin_symbol(coin)} {coin} {match.direction}, {match.name}",
            make_body=_pattern_body,
            kansberekening=kansberekening,
            hard_gates_ok=bool(factor_hard_gates_ok),
            reason=factor_breakdown,
        )
```

- [ ] **Step 5: Scratch-DB verificatie van de gate zelf**

Dit test rechtstreeks de kern-logica (`user_confirmed` met
`required_factors`) tegen realistische patroon-achtige waarden, zonder de
hele async marktscan-pipeline te hoeven draaien (die vereist live
Binance-data, niet beschikbaar in deze sandbox):

```bash
DATABASE_PATH=/tmp/scratch_task5.db python3 -c "
from app import db, repo
db.init_db()
uid_streng = repo.create_user('streng', 'x', 1000.0, 1.0)
repo.set_required_factors(uid_streng, ['Steun/weerstand'])
uid_los = repo.create_user('los', 'x', 1000.0, 1.0)

required_by_user = repo.list_required_factors_all_users()
reason = '✓ Trend: ... | ✗ Steun/weerstand: geen zone dichtbij genoeg | ✓ RSI: ...'
kansberekening = 75.0
hard_gates_ok = True
threshold = 60.0

for uid, verwacht_bevestigd in [(uid_streng, False), (uid_los, True)]:
    confirmed = repo.user_confirmed(
        kansberekening, hard_gates_ok, threshold,
        reason=reason, required_factors=required_by_user.get(uid, set()),
    )
    assert confirmed is verwacht_bevestigd, (uid, confirmed)
print('OK')
"
rm -f /tmp/scratch_task5.db
```

Expected: `OK` zonder AssertionError — de gebruiker met de verplichte
factor ✗ krijgt geen pushmelding ondanks 75% > zijn drempel van 60%, de
andere gebruiker (geen verplichte factoren) wel.

- [ ] **Step 6: Commit**

```bash
git add app/signal_processor.py app/market_scanner.py
git commit -m "Geef verplichte factoren door aan de pushmelding-gate voor patroon-signalen"
```

---

## Task 6: level_check.py — proactieve re-check

**Files:**
- Modify: `app/repo.py:1780-1793` (`list_pending_entries_with_price`'s
  SELECT, `s.reason AS reason` toevoegen)
- Modify: `app/level_check.py:184-213` (`check_pending_signals`)

**Interfaces:**
- Consumes: `repo.list_required_factors_all_users()` (Task 2),
  `repo.user_confirmed(..., reason=..., required_factors=...)` (Task 3).
- Produces: geen nieuwe publieke interface — dit is een bladfunctie
  (proactieve periodieke check), niets in latere taken hangt hiervan af.

- [ ] **Step 1: Voeg `reason` toe aan `list_pending_entries_with_price`'s SELECT**

In `app/repo.py`, de bestaande query (regel 1780-1793) — expliciete
kolomlijst, niet `SELECT s.*` (zie de waarschuwende comment op deze
functie: een kolom hier vergeten laat hem stilzwijgend verdwijnen).
Huidig:

```python
            """SELECT je.id AS id, je.user_id AS user_id,
                      s.coin AS coin, s.direction AS direction, s.price AS signal_price,
                      s.atr AS atr, s.confidence AS confidence, s.created_at AS signal_created_at,
                      s.message_id AS message_id,
                      s.suggested_entry_low AS suggested_entry_low,
                      s.suggested_entry_high AS suggested_entry_high,
                      s.sniper_entry_price AS sniper_entry_price,
                      s.auto_outcome AS auto_outcome,
                      s.trade_type AS trade_type, s.pattern_name AS pattern_name,
                      s.pass_pct AS pass_pct, s.hard_gates_ok AS hard_gates_ok,
                      u.username AS username, u.telegram_chat_id AS telegram_chat_id,
                      u.quiet_hours_start AS quiet_hours_start, u.quiet_hours_end AS quiet_hours_end,
                      u.confirm_threshold_pct AS confirm_threshold_pct
               FROM journal_entries je
               JOIN signals s ON s.id = je.signal_id
               JOIN users u ON u.id = je.user_id
               WHERE je.entry_price IS NULL AND je.exit_price IS NULL
                     AND je.status != 'genegeerd' AND je.level_alert_sent = 0
                     AND s.is_practice = 0"""
```

wordt (`s.reason AS reason,` toegevoegd, bijvoorbeeld direct na
`s.hard_gates_ok AS hard_gates_ok,`):

```python
            """SELECT je.id AS id, je.user_id AS user_id,
                      s.coin AS coin, s.direction AS direction, s.price AS signal_price,
                      s.atr AS atr, s.confidence AS confidence, s.created_at AS signal_created_at,
                      s.message_id AS message_id,
                      s.suggested_entry_low AS suggested_entry_low,
                      s.suggested_entry_high AS suggested_entry_high,
                      s.sniper_entry_price AS sniper_entry_price,
                      s.auto_outcome AS auto_outcome,
                      s.trade_type AS trade_type, s.pattern_name AS pattern_name,
                      s.pass_pct AS pass_pct, s.hard_gates_ok AS hard_gates_ok,
                      s.reason AS reason,
                      u.username AS username, u.telegram_chat_id AS telegram_chat_id,
                      u.quiet_hours_start AS quiet_hours_start, u.quiet_hours_end AS quiet_hours_end,
                      u.confirm_threshold_pct AS confirm_threshold_pct
               FROM journal_entries je
               JOIN signals s ON s.id = je.signal_id
               JOIN users u ON u.id = je.user_id
               WHERE je.entry_price IS NULL AND je.exit_price IS NULL
                     AND je.status != 'genegeerd' AND je.level_alert_sent = 0
                     AND s.is_practice = 0"""
```

- [ ] **Step 2: Haal de verplichte factoren batch-gewijs op in `check_pending_signals`**

In `app/level_check.py`, zoek de bestaande regel (190):

```python
    pattern_winrate = repo.pattern_winrate_stats()
```

en voeg er een regel aan toe:

```python
    pattern_winrate = repo.pattern_winrate_stats()
    required_by_user = repo.list_required_factors_all_users()
```

- [ ] **Step 3: Geef de nieuwe argumenten door in de drie-weg is_confirmed-branch**

Huidig (regel 205-212):

```python
        if entry["trade_type"] == "swing":
            is_confirmed = True
        elif entry["trade_type"] == "patroon":
            pattern_stats = pattern_winrate.get(entry["pattern_name"])
            success_rate = repo.pattern_kansberekening(entry["pass_pct"], pattern_stats)
            is_confirmed = repo.user_confirmed(success_rate, bool(entry["hard_gates_ok"]), entry["confirm_threshold_pct"])
        else:
            is_confirmed = repo.user_confirmed(entry["pass_pct"], bool(entry["hard_gates_ok"]), entry["confirm_threshold_pct"])
```

wordt (alleen de patroon- en "overig"-takken krijgen de nieuwe
argumenten, swing blijft ongewijzigd):

```python
        if entry["trade_type"] == "swing":
            is_confirmed = True
        elif entry["trade_type"] == "patroon":
            pattern_stats = pattern_winrate.get(entry["pattern_name"])
            success_rate = repo.pattern_kansberekening(entry["pass_pct"], pattern_stats)
            is_confirmed = repo.user_confirmed(
                success_rate, bool(entry["hard_gates_ok"]), entry["confirm_threshold_pct"],
                reason=entry["reason"] or "", required_factors=required_by_user.get(entry["user_id"], set()),
            )
        else:
            is_confirmed = repo.user_confirmed(
                entry["pass_pct"], bool(entry["hard_gates_ok"]), entry["confirm_threshold_pct"],
                reason=entry["reason"] or "", required_factors=required_by_user.get(entry["user_id"], set()),
            )
```

- [ ] **Step 4: Scratch-DB verificatie van de SELECT + gate**

```bash
DATABASE_PATH=/tmp/scratch_task6.db python3 -c "
from app import db, repo
db.init_db()
uid = repo.create_user('testuser', 'x', 1000.0, 1.0)
repo.set_required_factors(uid, ['Volume'])

signal_id = repo.insert_signal({
    'message_id': None, 'coin': 'BTC', 'direction': 'long',
    'category': 'day_trading', 'trade_type': 'day_trading',
    'price': 50000.0, 'rsi': 55.0, 'macd': 1.0, 'macd_signal': 0.5,
    'volume_ratio': 1.2, 'ema9': 50100.0, 'ema21': 50000.0, 'atr': 500.0,
    'atr_avg20': 480.0, 'adx': 20.0, 'technical_confirmed': 1,
    'pass_pct': 80.0, 'hard_gates_ok': 1, 'confidence': 'hoog vertrouwen',
    'reason': '✓ Trend: EMA9 boven EMA21 | ✗ Volume: onder gemiddeld',
    'stop_loss': 49000.0, 'take_profit': 52000.0, 'context_note': None,
    'is_practice': 0, 'plain_explanation': None,
})
repo.create_journal_entry(signal_id, uid, 10.0)

pending = repo.list_pending_entries_with_price()
assert len(pending) == 1
assert pending[0]['reason'] is not None and 'Volume' in pending[0]['reason']

required_by_user = repo.list_required_factors_all_users()
entry = pending[0]
is_confirmed = repo.user_confirmed(
    entry['pass_pct'], bool(entry['hard_gates_ok']), entry['confirm_threshold_pct'],
    reason=entry['reason'] or '', required_factors=required_by_user.get(entry['user_id'], set()),
)
assert is_confirmed is False, 'Volume staat ✗ en is verplicht, mag niet bevestigd zijn'
print('OK')
"
rm -f /tmp/scratch_task6.db
```

Expected: `OK` zonder AssertionError.

- [ ] **Step 5: Commit**

```bash
git add app/repo.py app/level_check.py
git commit -m "Geef verplichte factoren door aan level_check.py's proactieve re-check"
```

---

## Task 7: repo.py — winrate_for_user consistent maken

**Files:**
- Modify: `app/repo.py:2527-2565` (`winrate_for_user`)

**Interfaces:**
- Consumes: `list_required_factors(user_id)` (Task 2, bare aanroep
  binnen repo.py zelf, geen `repo.`-prefix nodig), `user_confirmed(...,
  reason=..., required_factors=...)` (Task 3, zelfde reden).
- Produces: geen signatuurwijziging — `winrate_for_user(user_id: int) ->
  dict` blijft exact hetzelfde, dus de enige aanroeper
  (`web/main.py:1016`, `"winrate": repo.winrate_for_user(user["id"])` in
  `account_page`) hoeft niet aangepast te worden.

- [ ] **Step 1: Werk de functie bij**

Huidig (regel 2527-2542):

```python
def winrate_for_user(user_id: int) -> dict:
    """Winrate puur op basis van het automatische trackrecord: van de
    signalen die voor DEZE gebruiker (zijn eigen drempel) bevestigd waren
    en waarvan de uitkomst al vaststaat, hoeveel raakten take-profit."""
    with db.session() as conn:
        user_row = conn.execute(
            "SELECT confirm_threshold_pct FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not user_row:
            raise ValueError(f"Onbekende gebruiker: {user_id}")
        threshold = user_row["confirm_threshold_pct"]
        rows = conn.execute(
            """SELECT pass_pct, hard_gates_ok, auto_outcome
               FROM signals
               WHERE is_practice = 0 AND pass_pct IS NOT NULL AND trade_type != 'patroon'"""
        ).fetchall()

    total = wins = losses = open_count = 0
    for row in rows:
        if not user_confirmed(row["pass_pct"], bool(row["hard_gates_ok"]), threshold):
            continue
```

wordt (SELECT krijgt `reason` erbij, `required_factors` eenmalig
opgehaald vóór de loop, meegegeven aan elke `user_confirmed`-aanroep):

```python
def winrate_for_user(user_id: int) -> dict:
    """Winrate puur op basis van het automatische trackrecord: van de
    signalen die voor DEZE gebruiker (zijn eigen drempel EN, als hij
    factoren verplicht heeft gesteld, die factoren) bevestigd waren en
    waarvan de uitkomst al vaststaat, hoeveel raakten take-profit. Zonder
    required_factors hier mee te wegen zou dit cijfer iets anders meten
    dan wat de gebruiker daadwerkelijk als melding krijgt (zie
    _fanout_confirmed_signal/_apply_user_confirmed, die het al wel
    meewegen)."""
    with db.session() as conn:
        user_row = conn.execute(
            "SELECT confirm_threshold_pct FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not user_row:
            raise ValueError(f"Onbekende gebruiker: {user_id}")
        threshold = user_row["confirm_threshold_pct"]
        rows = conn.execute(
            """SELECT pass_pct, hard_gates_ok, auto_outcome, reason
               FROM signals
               WHERE is_practice = 0 AND pass_pct IS NOT NULL AND trade_type != 'patroon'"""
        ).fetchall()

    required_factors = list_required_factors(user_id)
    total = wins = losses = open_count = 0
    for row in rows:
        if not user_confirmed(
            row["pass_pct"], bool(row["hard_gates_ok"]), threshold,
            reason=row["reason"] or "", required_factors=required_factors,
        ):
            continue
```

De rest van de functie (vanaf de `vervallen`-check tot de `return`)
blijft ongewijzigd.

- [ ] **Step 2: Scratch-DB scenario met twee afgeronde signalen**

```bash
DATABASE_PATH=/tmp/scratch_task7.db python3 -c "
from app import db, repo
db.init_db()
uid = repo.create_user('testuser', 'x', 1000.0, 1.0)
repo.set_required_factors(uid, ['Volume'])

def maak_signaal(reason, auto_outcome):
    sid = repo.insert_signal({
        'message_id': None, 'coin': 'BTC', 'direction': 'long',
        'category': 'day_trading', 'trade_type': 'day_trading',
        'price': 50000.0, 'rsi': 55.0, 'macd': 1.0, 'macd_signal': 0.5,
        'volume_ratio': 1.2, 'ema9': 50100.0, 'ema21': 50000.0, 'atr': 500.0,
        'atr_avg20': 480.0, 'adx': 20.0, 'technical_confirmed': 1,
        'pass_pct': 80.0, 'hard_gates_ok': 1, 'confidence': 'hoog vertrouwen',
        'reason': reason,
        'stop_loss': 49000.0, 'take_profit': 52000.0, 'context_note': None,
        'is_practice': 0, 'plain_explanation': None,
    })
    repo.mark_signal_auto_outcome(sid, auto_outcome, db.now_iso())
    return sid

# Verplichte factor 'Volume' staat ✓: telt mee als win
maak_signaal('✓ Trend: ... | ✓ Volume: boven gemiddeld', 'take_profit')
# Verplichte factor 'Volume' staat ✗: telt NIET mee, ook al is het ook een win
maak_signaal('✓ Trend: ... | ✗ Volume: onder gemiddeld', 'take_profit')

stats = repo.winrate_for_user(uid)
assert stats['total'] == 1, stats
assert stats['wins'] == 1, stats

# Zonder verplichte factoren: beide tellen mee
repo.set_required_factors(uid, [])
stats2 = repo.winrate_for_user(uid)
assert stats2['total'] == 2, stats2
assert stats2['wins'] == 2, stats2
print('OK')
"
rm -f /tmp/scratch_task7.db
```

Expected: `OK` zonder AssertionError.

- [ ] **Step 3: Commit**

```bash
git add app/repo.py
git commit -m "Weeg verplichte factoren mee in winrate_for_user"
```

---

## Task 8: UI — instellingenpagina op /account

**Files:**
- Modify: `web/templates/account.html` (nieuwe `<details>`-sectie, direct
  na de bestaande drempel-`<form>` rond regel 247-258)
- Modify: `web/main.py` (nieuwe route `POST /instellingen/factoren`, en
  `account_page`'s context-dict rond regel 1001-1028 uitbreiden)
- Modify: `web/static/style.css` (nieuwe `.factor-toggle`-regel, na de
  bestaande `.levels-form`-regels rond regel 1090)

**Interfaces:**
- Consumes: `indicators.TOGGLEABLE_FACTORS` (Task 1),
  `repo.list_required_factors(user_id)` / `repo.set_required_factors`
  (Task 2).
- Produces: niets dat latere taken nodig hebben — dit is de laatste
  functionele taak vóór de eindregressie.

- [ ] **Step 1: Voeg de nieuwe sectie toe aan `web/templates/account.html`**

Voeg dit toe direct na de bestaande drempel-`<form>` (na de sluitende
`</form>` op regel 258, vóór `</div></section>` op regel 259-260):

```html
    <details class="stats-collapse js-accordion" style="margin-top: 12px;">
      <summary class="stats-summary">Belangrijke factoren</summary>
      <p class="muted" style="margin: 8px 0 10px; font-size: 12.5px;">
        Vink een factor aan als die voor jou verplicht is: staat hij ✗ in een
        signaal, dan telt het voor jou nooit als bevestigd, ongeacht het
        percentage. Niet aangevinkt telt gewoon mee in het percentage zoals nu.
      </p>
      <form action="/instellingen/factoren" method="post" class="required-factors-form">
        {% for name, uitleg in toggleable_factors %}
        <label class="factor-toggle">
          <input type="checkbox" name="factoren" value="{{ name }}"{% if name in user_required_factors %} checked{% endif %}>
          <span class="factor-toggle-name">{{ name }}</span>
          <span class="muted factor-toggle-uitleg">{{ uitleg }}</span>
        </label>
        {% endfor %}
        <button type="submit">Opslaan</button>
      </form>
    </details>
```

- [ ] **Step 2: Voeg de nieuwe route toe aan `web/main.py`**

Plaats dit direct na de bestaande `update_confirm_threshold_setting`-route
(zoek `@app.post("/instellingen/drempel")`, rond regel 1756-1766):

```python
@app.post("/instellingen/factoren")
async def update_required_factors_setting(
    factoren: list[str] = Form([]),
    user: dict = Depends(require_login),
):
    # Nooit ruwe formulierinvoer direct opslaan: alleen namen uit de
    # vaste TOGGLEABLE_FACTORS-lijst zijn geldig, geknoei met het
    # formulier (of een verouderde factornaam) wordt stil genegeerd.
    valid_names = {name for name, _ in indicators.TOGGLEABLE_FACTORS}
    factoren = [f for f in factoren if f in valid_names]
    repo.set_required_factors(user["id"], factoren)
    return RedirectResponse(url="/account", status_code=303)
```

Controleer dat `indicators` en `RedirectResponse` al bovenaan
`web/main.py` geïmporteerd zijn (beide worden al elders in dit bestand
gebruikt, bijvoorbeeld door `update_confirm_threshold_setting` zelf) —
zo niet, voeg toe.

- [ ] **Step 3: Breid `account_page`'s context-dict uit**

In de `return templates.TemplateResponse(request, "account.html", {...})`
(regel 1001-1028), voeg twee regels toe, bijvoorbeeld direct na
`"advanced_factors_enabled": config.ENABLE_ADVANCED_FACTORS,` (regel
1006):

```python
        "advanced_factors_enabled": config.ENABLE_ADVANCED_FACTORS,
        "toggleable_factors": indicators.TOGGLEABLE_FACTORS,
        "user_required_factors": repo.list_required_factors(user["id"]),
```

- [ ] **Step 4: Voeg de CSS toe aan `web/static/style.css`**

Direct na de bestaande `.levels-hint`-regel (rond regel 1091):

```css
.factor-toggle {
  display: flex; align-items: flex-start; gap: 8px; padding: 5px 0;
  font-size: 12.5px; cursor: pointer;
}
.factor-toggle input { margin-top: 2px; flex: 0 0 auto; }
.factor-toggle-name { font-weight: 600; flex: 0 0 auto; }
.factor-toggle-uitleg { font-size: 11.5px; }
```

- [ ] **Step 5: FastAPI TestClient-verificatie van de route**

```bash
DATABASE_PATH=/tmp/scratch_task8.db python3 -c "
from app import db, repo
db.init_db()
uid = repo.create_user('testuser', 'x', 1000.0, 1.0)

from fastapi.testclient import TestClient
from web.main import app, SESSION_COOKIE
from app import security
client = TestClient(app)

# Login: zelfde cookie-mechanisme als web/main.py's eigen /login-route
# gebruikt (create_session_token + SESSION_COOKIE, zie web/main.py:267).
token = security.create_session_token(uid)
client.cookies.set(SESSION_COOKIE, token)

resp = client.post('/instellingen/factoren', data={'factoren': ['Trend', 'niet-bestaand']}, follow_redirects=False)
assert resp.status_code == 303, resp.status_code
saved = repo.list_required_factors(uid)
assert saved == {'Trend'}, saved

resp2 = client.get('/account')
assert resp2.status_code == 200
assert 'Trend' in resp2.text
print('OK')
"
rm -f /tmp/scratch_task8.db
```

Expected: `OK` zonder AssertionError.

- [ ] **Step 6: Handmatige Playwright-verificatie**

```bash
DATABASE_PATH=/tmp/scratch_playwright.db uvicorn web.main:app --port 8010 &
sleep 2
```

Open `/account` in een browser (via Playwright of handmatig), scroll naar
de nieuwe "Belangrijke factoren"-sectie, vink een factor aan, klik
Opslaan, herlaad de pagina en controleer dat de checkbox aangevinkt
blijft. Stop de server daarna (`kill %1` of het process-ID van uvicorn).

- [ ] **Step 7: Commit**

```bash
git add web/templates/account.html web/main.py web/static/style.css
git commit -m "Voeg instellingenpagina toe voor per-gebruiker verplichte factoren"
```

---

## Task 9: Volledige regressie + push

**Files:** geen wijzigingen, alleen verificatie.

- [ ] **Step 1: Draai Task 3's regressietest nogmaals tegen de volledige
  branch** (bewijst dat niets in Task 4-8 de bestaande drie-parameter-
  aanroepen alsnog heeft gebroken)

```bash
DATABASE_PATH=/tmp/scratch_final.db python3 -c "
from app import db, repo
db.init_db()
assert repo.user_confirmed(70.0, True, 60.0) is True
assert repo.user_confirmed(50.0, True, 60.0) is False
assert repo.user_confirmed(None, True, 60.0) is False
print('OK basisgedrag ongewijzigd')
"
```

- [ ] **Step 2: End-to-end scenario — kaart + pushmelding-gate stemmen overeen**

```bash
DATABASE_PATH=/tmp/scratch_final2.db python3 -c "
from app import db, repo
db.init_db()
uid = repo.create_user('testuser', 'x', 1000.0, 60.0)
repo.set_required_factors(uid, ['Volume'])

signal_id = repo.insert_signal({
    'message_id': None, 'coin': 'ETH', 'direction': 'short',
    'category': 'day_trading', 'trade_type': 'day_trading',
    'price': 3000.0, 'rsi': 45.0, 'macd': -1.0, 'macd_signal': -0.5,
    'volume_ratio': 0.8, 'ema9': 2990.0, 'ema21': 3000.0, 'atr': 30.0,
    'atr_avg20': 28.0, 'adx': 22.0, 'technical_confirmed': 1,
    'pass_pct': 90.0, 'hard_gates_ok': 1, 'confidence': 'hoog vertrouwen',
    'reason': '✓ Trend: EMA9 onder EMA21 | ✗ Volume: onder gemiddeld | ✓ RSI: RSI 45',
    'stop_loss': 3050.0, 'take_profit': 2900.0, 'context_note': None,
    'is_practice': 0, 'plain_explanation': None,
})
repo.create_journal_entry(signal_id, uid, 10.0)

from web.main import _apply_user_confirmed
entries = repo.list_signalen_for_user(uid)
required_factors = repo.list_required_factors(uid)
_apply_user_confirmed(entries, 60.0, required_factors)
assert entries[0]['user_confirmed'] is False, 'kaart moet niet-bevestigd tonen (Volume verplicht en staat fout)'

pending = repo.list_pending_entries_with_price()
required_by_user = repo.list_required_factors_all_users()
entry = pending[0]
is_confirmed = repo.user_confirmed(
    entry['pass_pct'], bool(entry['hard_gates_ok']), entry['confirm_threshold_pct'],
    reason=entry['reason'] or '', required_factors=required_by_user.get(entry['user_id'], set()),
)
assert is_confirmed is False, 'level_check-gate moet hetzelfde oordeel geven als de kaart'
print('OK: kaart en pushmelding-gate zijn consistent')
"
rm -f /tmp/scratch_final.db /tmp/scratch_final2.db
```

- [ ] **Step 3: Handmatige Playwright-smoketest**

Start de server tegen een scratch-DB (zie Task 8 Step 6), doorloop:
`/signalen` (badge + percentage nog zichtbaar, geen crash), coin-pagina
van een coin met signalen, `/account` (nieuwe sectie zichtbaar, winrate-
cijfer laadt zonder error). Stop de server na afloop.

- [ ] **Step 4: Push naar de branch**

```bash
git push -u origin claude/crypto-day-trading-alerts-5p8w6v
```
