# Sniper entries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Til de bestaande liquidity-sweep-detectie (nu een verstopte, gepoolde factor) uit als een eigen, zichtbaar "sniper entry"-concept: een precieze prijs met een duidelijke reden, zichtbaar op de signaalkaart en in de pushmelding, plus een actieve proactieve trigger als de sweep pas na het eerste signaal gebeurt.

**Architecture:** Eén nieuwe, dunne functie in `indicators.py` (`find_sniper_entry_price`) hergebruikt de bestaande `_find_liquidity_sweep`-detectie en geeft een precieze prijs + leesbare reden terug in plaats van alleen een bool. Twee nieuwe kolommen op `signals` dragen dat door naar de signaalkaart. Vier signaal-aanmaakplekken (day trading + drie structurele marktscan-detectors) roepen de functie aan bij het bouwen van hun `signal_data`-dict en voegen een aparte regel toe aan hun pushtekst. `level_check.py`'s bestaande 15-minuten-cyclus krijgt een vierde, hoogste-prioriteit check die de sweep opnieuw probeert te vinden voor signalen die hem nog niet hadden bij aanmaak.

**Tech Stack:** Python 3, FastAPI, SQLite (via `app/db.py`/`app/repo.py`), Jinja2-templates, geen pytest-suite — verificatie via throwaway scripts tegen een scratch-database (zie CLAUDE.md).

**Spec:** `docs/superpowers/specs/2026-09-23-sniper-entries-design.md`

## Global Constraints

- De eerste melding blijft altijd op marktprijs komen — sniper is een aanvulling, nooit een vervanging (expliciet bevestigd door de gebruiker).
- Alleen de 4u-timeframe-sweep wordt sniper in v1. `check_daily_liquidity_sweep` blijft ongewijzigd een aparte, gepoolde factor.
- Geen wijziging aan stop-loss/take-profit/positiegrootte-berekening.
- Swing blijft buiten scope.
- Geen nieuwe SMC-detectielogica — puur zichtbaar maken en actief bewaken van wat `_find_liquidity_sweep` al detecteert.
- De sniper-uitleg moet altijd een duidelijke "waarom" bevatten (expliciete eis van de gebruiker), niet alleen een prijs of badge.
- Schema-wijzigingen zijn twee-delig: `CREATE TABLE`/kolomdefinitie in `schema.sql` (verse database) én een idempotente `ALTER TABLE ... ADD COLUMN` guard in `app/db.py::_migrate()` (bestaande database) — zie CLAUDE.md.
- Drie plekken in `repo.py` hebben elk hun eigen expliciete kolomlijst (geen `SELECT s.*`): `insert_signal`'s `fields`-lijst, `_JOURNAL_SELECT`, `list_pending_entries_with_price`. Een nieuwe kolom die in één daarvan vergeten wordt, valt stil weg zonder foutmelding — dit is al eerder misgegaan bij `suggested_entry_low/high`.
- Geen pytest-suite in dit project: elke test is een throwaway Python-script tegen `DATABASE_PATH=/tmp/.../scratch.db`, opgeruimd na afloop.
- Na elke commit die `app/*.py` raakt: `sudo systemctl restart crypto-bot` op de VPS nodig. Na elke commit die `web/*` raakt: `sudo systemctl restart crypto-web`.

---

## Task 1: `indicators.find_sniper_entry_price`

**Files:**
- Modify: `app/indicators.py` (nieuwe functie direct na `check_daily_liquidity_sweep`, rond regel 857)
- Test: throwaway script in de scratchpad-directory

**Interfaces:**
- Consumes: bestaande `_find_liquidity_sweep(window: pd.DataFrame, direction: str) -> Optional[Pivot]` (regel 795-826, ongewijzigd), bestaande `SR_ZONE_LOOKBACK` constante (regel 582).
- Produces: `find_sniper_entry_price(direction: str, df: pd.DataFrame) -> Optional[tuple[float, str]]` — `None` als er geen sweep is, anders `(price, reason)` met `price` de rauwe pivotprijs en `reason` een leesbare Nederlandse uitleg. Alle latere taken importeren en roepen precies deze functie aan.

- [ ] **Step 1: Schrijf het testscript (nog falend, functie bestaat nog niet)**

Maak `/tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/test_sniper_price.py`:

```python
import sys
sys.path.insert(0, "/home/user/Trade")

import pandas as pd
from app import indicators

N = indicators.SR_ZONE_LOOKBACK  # 100
W = indicators.SR_PIVOT_WINDOW    # 3


def _flat_df(n: int) -> pd.DataFrame:
    return pd.DataFrame({
        "open": [100.0] * n, "high": [101.0] * n, "low": [99.0] * n,
        "close": [100.0] * n, "volume": [1000.0] * n,
    })


def test_long_sweep_returns_price_and_reason():
    df = _flat_df(N)
    # Pivot-low op index 50: lager dan de W candles aan beide kanten.
    df.loc[50, ["low", "high", "close", "open"]] = [95.0, 99.5, 99.0, 99.0]
    # Laatste candle (index 99, binnen LIQUIDITY_SWEEP_RECENT_CANDLES=3):
    # pen duikt onder 95.0, sluit er weer boven -> sweep.
    df.loc[99, ["low", "high", "close", "open"]] = [94.0, 100.5, 96.0, 99.0]

    result = indicators.find_sniper_entry_price("long", df)

    assert result is not None, "verwachtte een sweep-treffer"
    price, reason = result
    assert price == 95.0, f"verwachtte sweep-prijs 95.0, kreeg {price}"
    assert "95.0000" in reason
    assert "bear trap" in reason
    print("OK: long sweep ->", result)


def test_short_sweep_returns_price_and_reason():
    df = _flat_df(N)
    # Pivot-high op index 50.
    df.loc[50, ["low", "high", "close", "open"]] = [100.5, 105.0, 101.0, 101.0]
    # Laatste candle: pen boven 105.0, sluit er weer onder -> sweep.
    df.loc[99, ["low", "high", "close", "open"]] = [99.5, 106.0, 104.0, 101.0]

    result = indicators.find_sniper_entry_price("short", df)

    assert result is not None
    price, reason = result
    assert price == 105.0, f"verwachtte sweep-prijs 105.0, kreeg {price}"
    assert "105.0000" in reason
    assert "bull trap" in reason
    print("OK: short sweep ->", result)


def test_no_sweep_returns_none():
    df = _flat_df(N)  # geen enkele pivot, dus zeker geen sweep
    assert indicators.find_sniper_entry_price("long", df) is None
    assert indicators.find_sniper_entry_price("short", df) is None
    print("OK: geen sweep -> None")


def test_uppercase_direction_works_too():
    df = _flat_df(N)
    df.loc[50, ["low", "high", "close", "open"]] = [95.0, 99.5, 99.0, 99.0]
    df.loc[99, ["low", "high", "close", "open"]] = [94.0, 100.5, 96.0, 99.0]
    assert indicators.find_sniper_entry_price("LONG", df) is not None
    print("OK: hoofdletters in direction werken ook (zelfde .lower() als check_liquidity_sweep)")


test_long_sweep_returns_price_and_reason()
test_short_sweep_returns_price_and_reason()
test_no_sweep_returns_none()
test_uppercase_direction_works_too()
print("ALLE TESTS GESLAAGD")
```

- [ ] **Step 2: Run het script, verwacht een AttributeError**

Run: `python3 /tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/test_sniper_price.py`
Expected: FAIL met `AttributeError: module 'app.indicators' has no attribute 'find_sniper_entry_price'`

- [ ] **Step 3: Implementeer de functie**

In `app/indicators.py`, direct na `check_daily_liquidity_sweep` (na regel 856-857):

```python
def find_sniper_entry_price(direction: str, df: pd.DataFrame) -> Optional[tuple[float, str]]:
    """Dunne laag over _find_liquidity_sweep: geeft de rauwe sweep-prijs en
    een leesbare "waarom is dit een sniper-entry"-uitleg terug, in plaats
    van de korte factor-detail-string die check_liquidity_sweep bouwt voor
    de gepoolde 16-factoren-toets. Zelfde window, zelfde detectie —
    check_liquidity_sweep zelf blijft ongewijzigd; dit is een aparte,
    op-maat-gemaakte laag eroverheen, specifiek voor sniper-gebruik
    (signal_processor.py, market_scanner.py, level_check.py). Alleen de
    4u-timeframe (df hier is altijd de 4u-candles), geen daily-variant in
    v1 — check_daily_liquidity_sweep blijft een aparte, gepoolde factor."""
    direction = direction.lower()
    window = df.tail(SR_ZONE_LOOKBACK).reset_index(drop=True)
    hit = _find_liquidity_sweep(window, direction)
    if hit is None:
        return None
    if direction == "long":
        reason = (
            f"Stop-hunt: prijs werd even onder {hit.price:.4f} geduwd en sloot er "
            "meteen weer boven — de klassieke bear trap, hier zaten net de stops van anderen."
        )
    else:
        reason = (
            f"Stop-hunt: prijs werd even boven {hit.price:.4f} geduwd en sloot er "
            "meteen weer onder — de klassieke bull trap, hier zaten net de stops van anderen."
        )
    return (hit.price, reason)
```

- [ ] **Step 4: Run het script opnieuw, verwacht succes**

Run: `python3 /tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/test_sniper_price.py`
Expected: `ALLE TESTS GESLAAGD`

- [ ] **Step 5: Commit**

```bash
cd /home/user/Trade
git add app/indicators.py
git commit -m "$(cat <<'EOF'
Sniper-entryprijs: dunne laag over de bestaande liquidity sweep-detectie

find_sniper_entry_price hergebruikt _find_liquidity_sweep en geeft een
precieze prijs + leesbare reden terug, in plaats van alleen een bool
zoals de bestaande gepoolde factor check_liquidity_sweep.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 2: Schema, migratie en repo.py-doorvoer

**Files:**
- Modify: `app/schema.sql` (regel ~239-241, `signals`-tabel)
- Modify: `app/db.py` (`_migrate()`, na het bestaande `existing_signals`-blok rond regel 197)
- Modify: `app/repo.py` — `insert_signal` (regel 951-958), `_JOURNAL_SELECT` (regel 1148-1186), `list_pending_entries_with_price` (regel 1758-1786)
- Test: throwaway script in de scratchpad-directory

**Interfaces:**
- Consumes: geen (pure schema/opslag-laag).
- Produces: `signals.sniper_entry_price REAL` en `signals.sniper_reason TEXT` (beide nullable), door te lezen via `repo.get_signal`, `_JOURNAL_SELECT`-gebaseerde queries (`entry["sniper_entry_price"]`, `entry["sniper_reason"]`) en `list_pending_entries_with_price` (`entry["sniper_entry_price"]` alleen). `repo.insert_signal(data)` accepteert voortaan `data["sniper_entry_price"]`/`data["sniper_reason"]` als optionele keys (ontbrekend key = `None`, zelfde patroon als bestaande optionele velden in die functie).

- [ ] **Step 1: Schema — nieuwe kolommen op `signals`**

In `app/schema.sql`, direct vóór `created_at TEXT NOT NULL` van de `signals`-tabel (na de bestaande `suggested_entry_high REAL,` op regel 241):

```sql
    -- Precieze liquidity-sweep-prijs (zie indicators.find_sniper_entry_price)
    -- op het moment van dit signaal: een stop-hunt van een eerdere
    -- pivot-low/-high, gevolgd door een close terug aan de goede kant —
    -- scherper en preciezer dan de brede suggested_entry_low/high-zone
    -- hierboven. NULL als er bij aanmaak geen sweep was (level_check.py
    -- probeert het dan later nog een keer, zie check_pending_signals).
    sniper_entry_price REAL,
    -- Leesbare "waarom is dit een sniper-entry"-uitleg bij sniper_entry_price
    -- hierboven, voor op de signaalkaart en in de pushmelding. NULL
    -- wanneer sniper_entry_price ook NULL is.
    sniper_reason TEXT,
```

- [ ] **Step 2: Migratie voor bestaande databases**

In `app/db.py::_migrate()`, in het bestaande `existing_signals`-blok (na de `if "pattern_name" not in existing_signals:` guard, vóór de `CREATE INDEX IF NOT EXISTS idx_signals_auto_outcome_pending`-regel — rond regel 196-197 van het huidige bestand):

```python
    if "sniper_entry_price" not in existing_signals:
        conn.execute("ALTER TABLE signals ADD COLUMN sniper_entry_price REAL")
    if "sniper_reason" not in existing_signals:
        conn.execute("ALTER TABLE signals ADD COLUMN sniper_reason TEXT")
```

- [ ] **Step 3: `repo.insert_signal` — nieuwe velden opslaan**

In `app/repo.py`, `insert_signal`'s `fields`-lijst (regel 952-958), toevoegen aan het einde:

```python
def insert_signal(data: dict) -> int:
    fields = [
        "message_id", "coin", "direction", "category", "price", "rsi", "macd",
        "macd_signal", "volume_ratio", "ema9", "ema21", "atr", "atr_avg20", "adx",
        "technical_confirmed", "pass_pct", "hard_gates_ok", "confidence", "reason", "stop_loss", "take_profit",
        "context_note", "is_practice", "plain_explanation", "trade_type", "nearest_sr_zone_price",
        "suggested_entry_low", "suggested_entry_high", "pattern_name",
        "sniper_entry_price", "sniper_reason",
    ]
```

(De rest van de functie — `values`, `placeholders`, de `INSERT`-statement — blijft ongewijzigd; die itereert al generiek over `fields`.)

- [ ] **Step 4: `_JOURNAL_SELECT` — beide velden doorgeven aan elke signaalkaart**

In `app/repo.py`, `_JOURNAL_SELECT` (regel 1148-1186), direct na de bestaande regel `s.suggested_entry_low AS suggested_entry_low, s.suggested_entry_high AS suggested_entry_high,` (regel 1179):

```python
        s.sniper_entry_price AS sniper_entry_price, s.sniper_reason AS sniper_reason,
```

- [ ] **Step 5: `list_pending_entries_with_price` — sniper-status doorgeven aan level_check.py**

In `app/repo.py`, `list_pending_entries_with_price` (regel 1758-1786), in de `SELECT`, direct na `s.suggested_entry_high AS suggested_entry_high,`:

```python
                      s.sniper_entry_price AS sniper_entry_price,
```

(Alleen de prijs, niet `sniper_reason` — Component 3/Task 5 hieronder berekent zijn eigen verse reden opnieuw, zie de spec.)

- [ ] **Step 6: Testscript — round-trip door de hele keten**

Maak `/tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/test_sniper_storage.py`:

```python
import os, sys
sys.path.insert(0, "/home/user/Trade")
DBPATH = "/tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/scratch_sniper.db"
if os.path.exists(DBPATH):
    os.remove(DBPATH)
os.environ["DATABASE_PATH"] = DBPATH

from app import db, repo, security

db.init_db()

user_id = repo.create_user("tester", security.hash_password("pw12345"), 1000.0, 1.0)

signal_id = repo.insert_signal({
    "message_id": None, "coin": "SOL", "direction": "long", "category": "day_trading",
    "price": 140.0, "technical_confirmed": 1, "pass_pct": 80.0, "hard_gates_ok": 1,
    "confidence": "hoog vertrouwen", "reason": "test", "stop_loss": 135.0, "take_profit": 150.0,
    "sniper_entry_price": 138.5,
    "sniper_reason": "Stop-hunt: prijs werd even onder 138.5000 geduwd en sloot er meteen weer boven.",
})
entry_id = repo.create_journal_entry(signal_id, user_id, risk_eur=10.0)

# insert_signal + get_signal
stored = repo.get_signal(signal_id)
assert stored["sniper_entry_price"] == 138.5
assert "Stop-hunt" in stored["sniper_reason"]
print("OK: insert_signal/get_signal bewaren beide velden")

# _JOURNAL_SELECT (via list_journal, gebruikt door dashboard/account/coin-pagina)
journal_rows = repo.list_journal(user_id)
assert len(journal_rows) == 1
assert journal_rows[0]["sniper_entry_price"] == 138.5
assert "bear trap" in journal_rows[0]["sniper_reason"] or "Stop-hunt" in journal_rows[0]["sniper_reason"]
print("OK: _JOURNAL_SELECT (list_journal) geeft beide velden door")

# list_signalen_for_user (/signalen-pagina, ook op _JOURNAL_SELECT gebaseerd)
signalen_rows = repo.list_signalen_for_user(user_id)
assert signalen_rows[0]["sniper_entry_price"] == 138.5
print("OK: list_signalen_for_user geeft sniper_entry_price door")

# list_pending_entries_with_price (level_check.py) — alleen de prijs nodig
pending_rows = repo.list_pending_entries_with_price()
assert len(pending_rows) == 1
assert pending_rows[0]["sniper_entry_price"] == 138.5
print("OK: list_pending_entries_with_price geeft sniper_entry_price door")

# Een signaal ZONDER sweep (geen sniper-velden meegegeven) moet gewoon NULL geven,
# niet crashen — insert_signal moet ontbrekende keys als None behandelen.
signal_id_2 = repo.insert_signal({
    "message_id": None, "coin": "ETH", "direction": "short", "category": "day_trading",
    "price": 2500.0, "technical_confirmed": 1, "pass_pct": 70.0, "hard_gates_ok": 1,
    "confidence": "hoog vertrouwen", "reason": "test", "stop_loss": 2550.0, "take_profit": 2400.0,
})
stored_2 = repo.get_signal(signal_id_2)
assert stored_2["sniper_entry_price"] is None
assert stored_2["sniper_reason"] is None
print("OK: ontbrekende sniper-velden in insert_signal worden NULL, geen crash")

os.remove(DBPATH)
print("ALLE TESTS GESLAAGD")
```

- [ ] **Step 7: Run het script, moet in één keer slagen (deze taak is pure plumbing, geen aparte fail-first-stap zinvol)**

Run: `python3 /tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/test_sniper_storage.py`
Expected: `ALLE TESTS GESLAAGD`

- [ ] **Step 8: Commit**

```bash
cd /home/user/Trade
git add app/schema.sql app/db.py app/repo.py
git commit -m "$(cat <<'EOF'
Sniper-entry: schema + migratie + doorvoer in de drie repo.py-kolomlijsten

Twee nieuwe nullable kolommen op signals (sniper_entry_price,
sniper_reason). Alle drie plekken in repo.py die hun eigen expliciete
kolomlijst bijhouden (insert_signal, _JOURNAL_SELECT,
list_pending_entries_with_price) krijgen ze erbij — zie de bestaande
waarschuwende comment boven _JOURNAL_SELECT, die precies deze valkuil al
eerder beschreef.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 3: `signal_processor.py` — dagtrading-signalen

**Files:**
- Modify: `app/signal_processor.py` — `signal_data`-opbouw (rond regel 964-993), pushtekst nieuw signaal (rond regel 1136-1145), pushtekst update-pad (rond regel 1259-1264)
- Test: throwaway script in de scratchpad-directory

**Interfaces:**
- Consumes: `indicators.find_sniper_entry_price(direction: str, df: pd.DataFrame) -> Optional[tuple[float, str]]` (Task 1). `df` is al in scope in `process_day_trading_signal` sinds regel 843.
- Produces: `signal_data["sniper_entry_price"]`/`signal_data["sniper_reason"]`, gelezen door zowel het nieuwe-signaal-pushpad als `_notify_signal_update` (die `message_data = signal_data` hergebruikt, geen aparte berekening nodig).

- [ ] **Step 1: Bereken sniper eenmalig bij het bouwen van `signal_data`**

In `app/signal_processor.py`, direct vóór de `signal_data = {` regel (regel 964), na de bestaande `suggested_entry_low`/`suggested_entry_high`-berekening (na regel 926):

```python
    sniper = indicators.find_sniper_entry_price(interp.direction, df)
    sniper_entry_price, sniper_reason = sniper if sniper else (None, None)
```

En in de `signal_data`-dict zelf (na de bestaande `"suggested_entry_high": suggested_entry_high,` op regel 984):

```python
        "sniper_entry_price": sniper_entry_price,
        "sniper_reason": sniper_reason,
```

- [ ] **Step 2: Pushtekst — nieuw signaal (regel ~1136-1145)**

Huidige code:

```python
            entry_zone_note = (
                f" · Mogelijk betere entry: {suggested_entry_low:.4f}–{suggested_entry_high:.4f}"
                if suggested_entry_low is not None else ""
            )
            body = (
                f"Entry {signal_data['price']:.4f} · Stop {effective_stop_loss:.4f} · "
                f"Take profit {effective_take_profit:.4f}{entry_zone_note}"
            )
```

Wordt:

```python
            entry_zone_note = (
                f" · Mogelijk betere entry: {suggested_entry_low:.4f}–{suggested_entry_high:.4f}"
                if suggested_entry_low is not None else ""
            )
            sniper_line = (
                f"\n🎯 Sniper: {signal_data['sniper_entry_price']:.4f} — {signal_data['sniper_reason']}"
                if signal_data.get("sniper_entry_price") is not None else ""
            )
            body = (
                f"Entry {signal_data['price']:.4f} · Stop {effective_stop_loss:.4f} · "
                f"Take profit {effective_take_profit:.4f}{entry_zone_note}{sniper_line}"
            )
```

- [ ] **Step 3: Pushtekst — update-pad in `_notify_signal_update` (regel ~1259-1267)**

Huidige code:

```python
            suggested_low = message_data.get("suggested_entry_low")
            suggested_high = message_data.get("suggested_entry_high")
            entry_zone_note = (
                f" · Mogelijk betere entry: {suggested_low:.4f}–{suggested_high:.4f}"
                if suggested_low is not None else ""
            )
            body = (
                f"Nieuwe prijs {message_data['price']:.4f} · Stop {message_data['stop_loss']:.4f} · "
                f"Take profit {message_data['take_profit']:.4f}{entry_zone_note}"
                if confirmed else
                f"Nieuwe prijs {message_data['price']:.4f} · nog geen sterke kans"
            )
```

Wordt:

```python
            suggested_low = message_data.get("suggested_entry_low")
            suggested_high = message_data.get("suggested_entry_high")
            entry_zone_note = (
                f" · Mogelijk betere entry: {suggested_low:.4f}–{suggested_high:.4f}"
                if suggested_low is not None else ""
            )
            sniper_line = (
                f"\n🎯 Sniper: {message_data['sniper_entry_price']:.4f} — {message_data['sniper_reason']}"
                if message_data.get("sniper_entry_price") is not None else ""
            )
            body = (
                f"Nieuwe prijs {message_data['price']:.4f} · Stop {message_data['stop_loss']:.4f} · "
                f"Take profit {message_data['take_profit']:.4f}{entry_zone_note}{sniper_line}"
                if confirmed else
                f"Nieuwe prijs {message_data['price']:.4f} · nog geen sterke kans"
            )
```

- [ ] **Step 4: Testscript — signal_data bevat sniper-velden, push-body ook**

Maak `/tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/test_signal_processor_sniper.py`:

```python
import os, sys
sys.path.insert(0, "/home/user/Trade")
DBPATH = "/tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/scratch_sp_sniper.db"
if os.path.exists(DBPATH):
    os.remove(DBPATH)
os.environ["DATABASE_PATH"] = DBPATH

import asyncio
import pandas as pd
from unittest.mock import patch
from app import db, repo, config

db.init_db()
config.ENABLE_ADVANCED_FACTORS = False  # niet relevant voor deze test, sneller

from app.anthropic_interpret import Interpretation
from app import signal_processor

user_id = repo.create_user("tester", "x", 1000.0, 1.0)
repo.add_push_subscription(user_id, "https://example.com/ep", "k", "a") if hasattr(repo, "add_push_subscription") else None

N = 100
df = pd.DataFrame({
    "open": [140.0] * N, "high": [141.0] * N, "low": [139.0] * N,
    "close": [140.0] * N, "volume": [1000.0] * N,
})
# Pivot-low + sweep op de laatste candle, zelfde opzet als Task 1's test.
df.loc[50, ["low", "high", "close", "open"]] = [135.0, 140.5, 139.0, 139.0]
df.loc[99, ["low", "high", "close", "open"]] = [134.0, 141.5, 136.0, 139.0]

interp = Interpretation(coin="SOL", direction="long", category="day_trading", unclear=False, reason="test")

with patch("app.exchange.fetch_ohlcv", return_value=df), \
     patch("app.signal_processor.explain.explain_signal", return_value="test uitleg"), \
     patch("app.push_notify.send_push", return_value=None) as mock_push:
    asyncio.run(signal_processor.process_day_trading_signal(None, interp, notify_on_update=False))

signals = repo.list_day_trading_signals_for_backtest(limit=10)
assert len(signals) == 1, signals
signal = signals[0]
print("signaal pass_pct:", signal.get("pass_pct"))

stored = repo.get_signal(signal["id"] if "id" in signal else None) if "id" in signal else None
# list_day_trading_signals_for_backtest geeft mogelijk geen id terug; haal via journaal op.
journal_rows = repo.list_journal(user_id)
assert len(journal_rows) == 1
entry = journal_rows[0]
print("sniper_entry_price:", entry["sniper_entry_price"])
print("sniper_reason:", entry["sniper_reason"])
assert entry["sniper_entry_price"] == 135.0, entry["sniper_entry_price"]
assert "bear trap" in entry["sniper_reason"]
print("OK: signal_data uit process_day_trading_signal bevat sniper-velden")

if mock_push.called:
    body = mock_push.call_args.args[2] if len(mock_push.call_args.args) > 2 else mock_push.call_args.kwargs.get("body", "")
    assert "🎯 Sniper: 135.0000" in body, body
    print("OK: pushtekst bevat de sniper-regel")
else:
    print("Geen push verstuurd (signaal waarschijnlijk niet bevestigd) — sniper-veld-check hierboven volstaat voor deze taak")

os.remove(DBPATH)
print("ALLE TESTS GESLAAGD")
```

- [ ] **Step 5: Run het script**

Run: `python3 /tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/test_signal_processor_sniper.py`
Expected: `ALLE TESTS GESLAAGD`. Als `process_day_trading_signal` faalt op een ontbrekende dagcandle-fetch (advanced factors uitgezet, dus dat zou niet nodig moeten zijn) of een andere afhankelijkheid, patch die aanroep er ook bij (`app.exchange.fetch_ohlcv` wordt zowel voor 4u als voor eventuele daily-candles gebruikt met een tweede positional/keyword-argument — controleer de exacte call-signature in `app/exchange.py` als de mock niet dekt wat er nodig is, en breid de `patch`-aanroep uit met `side_effect` dat op het tweede argument reageert).

- [ ] **Step 6: Commit**

```bash
cd /home/user/Trade
git add app/signal_processor.py
git commit -m "$(cat <<'EOF'
Sniper-entry bedraden in dagtrading-signalen (aanmaak + beide pushpaden)

signal_data krijgt sniper_entry_price/sniper_reason bij het bouwen (één
berekening, hergebruikt door zowel het nieuwe-signaal-pushpad als het
update-pad via _notify_signal_update). Beide pushteksten krijgen een
aparte regel als er een sweep is.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 4: `market_scanner.py` — de drie structurele detectors

**Files:**
- Modify: `app/market_scanner.py` — `_find_breakout_retest_candidate` (regel ~151-182), `_find_trendline_retest_candidate` (regel ~298-329), `_find_chart_pattern_candidate` (regel ~531-585)
- Test: throwaway script in de scratchpad-directory

**Interfaces:**
- Consumes: `indicators.find_sniper_entry_price(direction: str, df: pd.DataFrame) -> Optional[tuple[float, str]]` (Task 1). `df`/`direction`(of `match.direction`) zijn in alle drie `notify()`-closures al in scope.
- Produces: dezelfde `signal_data["sniper_entry_price"]`/`["sniper_reason"]`-keys als Task 3, plus een sniper-regel in `_breakout_body`/`_trendline_body`/`_pattern_body`.

- [ ] **Step 1: `_find_breakout_retest_candidate` — signal_data + `_breakout_body`**

In `app/market_scanner.py`, binnen `notify()` van `_find_breakout_retest_candidate`, direct vóór `signal_data = {` (regel 151):

```python
        sniper = indicators.find_sniper_entry_price(direction, df)
        sniper_entry_price, sniper_reason = sniper if sniper else (None, None)
```

In de `signal_data`-dict zelf, na `"suggested_entry_low": None, "suggested_entry_high": None,` (regel 162):

```python
            "sniper_entry_price": sniper_entry_price, "sniper_reason": sniper_reason,
```

`_breakout_body` (regel 181-182), van:

```python
        def _breakout_body(effective_stop_loss: float, effective_take_profit: float, stop_was_capped: bool) -> str:
            return f"Entry {ind.price:.4f} · Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}"
```

naar:

```python
        def _breakout_body(effective_stop_loss: float, effective_take_profit: float, stop_was_capped: bool) -> str:
            base = f"Entry {ind.price:.4f} · Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}"
            if sniper_entry_price is not None:
                base += f"\n🎯 Sniper: {sniper_entry_price:.4f} — {sniper_reason}"
            return base
```

- [ ] **Step 2: `_find_trendline_retest_candidate` — signal_data + `_trendline_body`**

Zelfde patroon, binnen `notify()` van `_find_trendline_retest_candidate`, direct vóór `signal_data = {` (regel 298):

```python
        sniper = indicators.find_sniper_entry_price(direction, df)
        sniper_entry_price, sniper_reason = sniper if sniper else (None, None)
```

In de `signal_data`-dict, na `"suggested_entry_low": None, "suggested_entry_high": None,` (regel 309):

```python
            "sniper_entry_price": sniper_entry_price, "sniper_reason": sniper_reason,
```

`_trendline_body` (regel 328-329), van:

```python
        def _trendline_body(effective_stop_loss: float, effective_take_profit: float, stop_was_capped: bool) -> str:
            return f"Entry {ind.price:.4f} · Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}"
```

naar:

```python
        def _trendline_body(effective_stop_loss: float, effective_take_profit: float, stop_was_capped: bool) -> str:
            base = f"Entry {ind.price:.4f} · Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}"
            if sniper_entry_price is not None:
                base += f"\n🎯 Sniper: {sniper_entry_price:.4f} — {sniper_reason}"
            return base
```

- [ ] **Step 3: `_find_chart_pattern_candidate` — signal_data + `_pattern_body`**

Binnen `notify()` van `_find_chart_pattern_candidate`, direct vóór `signal_data = {` (regel 531). Let op: hier heet de richting `match.direction`, niet `direction`:

```python
        sniper = indicators.find_sniper_entry_price(match.direction, df)
        sniper_entry_price, sniper_reason = sniper if sniper else (None, None)
```

In de `signal_data`-dict, na de bestaande `"suggested_entry_low": entry_options["retest_low"],` / `"suggested_entry_high": entry_options["retest_high"],` (regel 542-543):

```python
            "sniper_entry_price": sniper_entry_price, "sniper_reason": sniper_reason,
```

`_pattern_body` (regel 567-585), van:

```python
        def _pattern_body(effective_stop_loss: float, effective_take_profit: float, stop_was_capped: bool) -> str:
            retest_note = (
                f" · Retest {entry_options['retest_low']:.4f}–{entry_options['retest_high']:.4f}"
                if entry_options["retest_low"] is not None else ""
            )
            level_label = (
                f"Uitbraak {entry_options['breakout_level']:.4f}{retest_note}"
                if used_pattern_stop_take else f"Prijs {ind.price:.4f}"
            )
            return (
                f"{level_label} · "
                f"Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}"
            )
```

naar:

```python
        def _pattern_body(effective_stop_loss: float, effective_take_profit: float, stop_was_capped: bool) -> str:
            retest_note = (
                f" · Retest {entry_options['retest_low']:.4f}–{entry_options['retest_high']:.4f}"
                if entry_options["retest_low"] is not None else ""
            )
            level_label = (
                f"Uitbraak {entry_options['breakout_level']:.4f}{retest_note}"
                if used_pattern_stop_take else f"Prijs {ind.price:.4f}"
            )
            base = (
                f"{level_label} · "
                f"Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}"
            )
            if sniper_entry_price is not None:
                base += f"\n🎯 Sniper: {sniper_entry_price:.4f} — {sniper_reason}"
            return base
```

- [ ] **Step 4: Testscript — sniper-velden in alle drie de structurele signal_data-dicts**

Maak `/tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/test_market_scanner_sniper.py`. Dit test rechtstreeks de kern-logica (dezelfde aanpak als eerder deze sessie voor `find_forming_wedge`), niet de volledige `scan_market()`-cyclus (die vereist een live Binance-verbinding en is te zwaar voor deze taak):

```python
import sys
sys.path.insert(0, "/home/user/Trade")

import pandas as pd
from app import indicators

N = indicators.SR_ZONE_LOOKBACK  # 100
df = pd.DataFrame({
    "open": [140.0] * N, "high": [141.0] * N, "low": [139.0] * N,
    "close": [140.0] * N, "volume": [1000.0] * N,
})
df.loc[50, ["low", "high", "close", "open"]] = [135.0, 140.5, 139.0, 139.0]
df.loc[99, ["low", "high", "close", "open"]] = [134.0, 141.5, 136.0, 139.0]

# Exact dezelfde aanroep die nu in alle drie de notify()-closures van
# market_scanner.py staat.
sniper = indicators.find_sniper_entry_price("long", df)
sniper_entry_price, sniper_reason = sniper if sniper else (None, None)
assert sniper_entry_price == 135.0
assert "bear trap" in sniper_reason

def _breakout_body(effective_stop_loss, effective_take_profit, stop_was_capped, ind_price=140.0):
    base = f"Entry {ind_price:.4f} · Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}"
    if sniper_entry_price is not None:
        base += f"\n🎯 Sniper: {sniper_entry_price:.4f} — {sniper_reason}"
    return base

body = _breakout_body(130.0, 150.0)
assert "🎯 Sniper: 135.0000" in body, body
assert "bear trap" in body
print("OK: sniper-regel verschijnt correct in een make_body-achtige closure")
print("ALLE TESTS GESLAAGD")
```

- [ ] **Step 5: Run het script**

Run: `python3 /tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/test_market_scanner_sniper.py`
Expected: `ALLE TESTS GESLAAGD`

- [ ] **Step 6: Statische controle van de drie bewerkte functies**

Run: `python3 -c "import ast; ast.parse(open('/home/user/Trade/app/market_scanner.py').read()); print('syntax OK')"`
Expected: `syntax OK` (vangt een verkeerd inspringingsniveau of gemiste `sniper_entry_price`-variabele in een van de drie closures — deze taak wijzigt gecode op drie bijna-identieke plekken, een kopieerfout is de meest waarschijnlijke misser).

- [ ] **Step 7: Commit**

```bash
cd /home/user/Trade
git add app/market_scanner.py
git commit -m "$(cat <<'EOF'
Sniper-entry bedraden in de drie structurele marktscan-detectors

Uitbraak+terugtest, trendlijn+terugtest en patroon krijgen elk dezelfde
sniper_entry_price/sniper_reason-berekening en een sniper-regel in hun
eigen make_body-closure — deze drie bouwden voorheen geen enkele
entry-gerelateerde tekst in hun pushmelding, dit is de eerste.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 5: Signaalkaart — zichtbaar, duidelijk onderscheiden blok

**Files:**
- Modify: `web/templates/_macros.html` — `signal_card`-macro (regel 149-201)
- Modify: `web/static/style.css` — nieuwe `.signal-card-sniper`-klasse
- Test: FastAPI `TestClient`-script in de scratchpad-directory

**Interfaces:**
- Consumes: `entry.sniper_entry_price`/`entry.sniper_reason` uit een journal-rij (Task 2's `_JOURNAL_SELECT`), beschikbaar op elke pagina die `macros.signal_card(entry)` aanroept (dashboard, account, /signalen, coin-pagina).
- Produces: niets voor latere taken — dit is de laatste zichtbare laag van Component 2 uit de spec.

- [ ] **Step 1: Nieuw blok in `signal_card`, direct na het bestaande entry-zone-blok**

In `web/templates/_macros.html`, na de bestaande entry-zone-`{% if %}`/`{% elif %}`/`{% endif %}` (regel 174-182), vóór `{% if entry.reason %}` (regel 183):

```html
  {% if entry.sniper_entry_price is defined and entry.sniper_entry_price is not none %}
  <div class="signal-card-sniper">
    🎯 Sniper: {{ "%.4f"|format(entry.sniper_entry_price) }}
    <span class="sniper-reason">{{ entry.sniper_reason }}</span>
  </div>
  {% endif %}
```

- [ ] **Step 2: CSS — duidelijk onderscheiden van de rest van de kaart**

In `web/static/style.css`, direct na de bestaande `.signal-card-entry-zone`-regel (regel 561):

```css
.signal-card-sniper {
  margin-top: 6px;
  padding: 6px 10px;
  border-left: 3px solid var(--amber, #d9a441);
  background: rgba(217, 164, 65, 0.08);
  border-radius: 4px;
  font-size: 12.5px;
  font-weight: 600;
}
.signal-card-sniper .sniper-reason {
  display: block;
  margin-top: 2px;
  font-weight: 400;
  font-size: 12px;
  color: var(--text-muted, #9aa0a6);
}
```

Controleer eerst of `--amber` al bestaat als CSS-variabele in `style.css` (`grep -n "\-\-amber" web/static/style.css`); zo niet, gebruik een losstaande hexwaarde zoals hierboven getoond (`#d9a441`) zonder de `var(--amber, ...)`-fallback-syntax aan te passen — de fallback zorgt er sowieso voor dat dit correct rendert in beide gevallen, geen aparte stap nodig.

- [ ] **Step 3: Testscript — badge verschijnt op de gerenderde pagina, duidelijk anders dan de rest**

Maak `/tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/test_sniper_card.py`:

```python
import os, sys
sys.path.insert(0, "/home/user/Trade")
DBPATH = "/tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/scratch_sniper_card.db"
if os.path.exists(DBPATH):
    os.remove(DBPATH)
os.environ["DATABASE_PATH"] = DBPATH
os.environ["JWT_SECRET"] = "test-secret-thats-plenty-long-for-testing-purposes"

from app import db, repo, security

db.init_db()
user_id = repo.create_user("tester", security.hash_password("pw12345"), 1000.0, 1.0)

signal_id = repo.insert_signal({
    "message_id": None, "coin": "SOL", "direction": "long", "category": "day_trading",
    "price": 140.0, "technical_confirmed": 1, "pass_pct": 80.0, "hard_gates_ok": 1,
    "confidence": "hoog vertrouwen", "reason": "test", "stop_loss": 135.0, "take_profit": 150.0,
    "sniper_entry_price": 138.5,
    "sniper_reason": "Stop-hunt: prijs werd even onder 138.5000 geduwd en sloot er meteen weer boven — de klassieke bear trap.",
})
repo.create_journal_entry(signal_id, user_id, risk_eur=10.0)

from fastapi.testclient import TestClient
from web.main import app

client = TestClient(app)
client.post("/login", data={"username": "tester", "password": "pw12345"})

resp = client.get("/signalen")
assert resp.status_code == 200
html = resp.text
assert 'class="signal-card-sniper"' in html, "sniper-blok niet gevonden op /signalen"
assert "🎯 Sniper: 138.5000" in html
assert "bear trap" in html
print("OK: sniper-blok zichtbaar op /signalen")

resp = client.get("/coins/SOL")
assert resp.status_code == 200
assert 'class="signal-card-sniper"' in resp.text
print("OK: sniper-blok zichtbaar op de coin-pagina")

# Een signaal ZONDER sniper mag het blok niet tonen.
signal_id_2 = repo.insert_signal({
    "message_id": None, "coin": "ETH", "direction": "short", "category": "day_trading",
    "price": 2500.0, "technical_confirmed": 1, "pass_pct": 70.0, "hard_gates_ok": 1,
    "confidence": "hoog vertrouwen", "reason": "test", "stop_loss": 2550.0, "take_profit": 2400.0,
})
repo.create_journal_entry(signal_id_2, user_id, risk_eur=10.0)
resp = client.get("/coins/ETH")
assert 'class="signal-card-sniper"' not in resp.text, "sniper-blok mag niet verschijnen zonder sweep"
print("OK: geen sniper-blok als sniper_entry_price NULL is")

os.remove(DBPATH)
print("ALLE TESTS GESLAAGD")
```

- [ ] **Step 4: Run het script**

Run: `python3 /tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/test_sniper_card.py`
Expected: `ALLE TESTS GESLAAGD`

- [ ] **Step 5: Handmatige visuele check**

Start `uvicorn web.main:app --reload` tegen een scratch-database met een sniper-signaal (hergebruik het script hierboven zonder de laatste `os.remove`), open `/signalen` in een browser en bevestig dat het sniper-blok er visueel duidelijk anders uitziet dan zowel de gewone entry-zone-regel als de groene "trade kans"-badge — geen groen (dat betekent al iets anders, hogere kansberekening), een eigen kleur.

- [ ] **Step 6: Commit**

```bash
cd /home/user/Trade
git add web/templates/_macros.html web/static/style.css
git commit -m "$(cat <<'EOF'
Sniper-entry zichtbaar op de signaalkaart, met duidelijke "waarom"-uitleg

Eigen, opvallend blok op signal_card (amber, niet het bestaande groen van
een bevestigde kans) — prijs plus de volledige reden-tekst, niet alleen
een badge. Zichtbaar op elke pagina die signal_card gebruikt: dashboard,
account, /signalen, coin-pagina.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 6: `level_check.py` — het wachtmechanisme

**Files:**
- Modify: `app/level_check.py` — `check_pending_signals()` (regel 169-274)
- Test: throwaway script in de scratchpad-directory

**Interfaces:**
- Consumes: `indicators.find_sniper_entry_price(direction: str, df: pd.DataFrame) -> Optional[tuple[float, str]]` (Task 1), `entry["sniper_entry_price"]` uit `repo.list_pending_entries_with_price()` (Task 2), bestaande `repo.mark_level_alert_sent(entry_id: int) -> None`.
- Produces: geen nieuwe publieke interface — dit is de laatste laag (proactieve melding).

- [ ] **Step 1: Sniper-check toevoegen, met voorrang op de bestaande drie situaties**

In `app/level_check.py`, binnen `check_pending_signals()`, na de bestaande `coin_levels`-cache-declaratie (regel 180) en vóór de `for entry in entries:`-loop, een nieuwe cache toevoegen:

```python
    coin_sniper: dict[tuple[str, str], Optional[tuple[float, str]]] = {}
```

Binnen de loop, direct na de bestaande `in_entry_zone`-berekening (na regel 228, vóór de `signal_age`/`at_signal_level`-blok op regel 230):

```python
        sniper_hit: Optional[tuple[float, str]] = None
        if not in_entry_zone and entry["sniper_entry_price"] is None:
            cache_key = (coin, entry["direction"])
            if cache_key not in coin_sniper:
                try:
                    sniper_df = await asyncio.to_thread(exchange.fetch_ohlcv, coin)
                    coin_sniper[cache_key] = indicators.find_sniper_entry_price(entry["direction"], sniper_df)
                except Exception:
                    logger.exception("Kon geen candles ophalen voor sniper-check op %s, sla over", coin)
                    coin_sniper[cache_key] = None
            sniper_hit = coin_sniper[cache_key]
```

Vervolgens de bestaande gate en meldingslogica aanpassen. Huidige code (regel 230-273):

```python
        signal_age = datetime.now(timezone.utc) - datetime.fromisoformat(entry["signal_created_at"])
        at_signal_level = (
            not in_entry_zone
            and signal_age >= timedelta(minutes=PENDING_LEVEL_MIN_AGE_MINUTES)
            and entry["signal_price"] is not None
            and abs(current_price - entry["signal_price"]) <= entry["atr"] * PENDING_LEVEL_ATR_MULTIPLIER
        )

        matched_level = None
        if not in_entry_zone and not at_signal_level and entry["message_id"] is not None:
            cache_key = (entry["message_id"], coin)
            if cache_key not in coin_levels:
                coin_levels[cache_key] = repo.list_source_levels_for_message(entry["message_id"], coin)
            matched_level = _nearest_level(current_price, entry["atr"], coin_levels[cache_key])

        if not in_entry_zone and not at_signal_level and not matched_level:
            continue

        if in_entry_zone:
            level_line = f"Betere entry: {entry['suggested_entry_low']:.4f}–{entry['suggested_entry_high']:.4f}"
        elif matched_level:
            level_desc = f"{matched_level['price_level']}"
            if matched_level["pattern_name"]:
                level_desc += f" ({matched_level['pattern_name']})"
            level_line = f"Bron niveau: {level_desc}"
        else:
            level_line = f"Signaalniveau: {entry['signal_price']:.4f}"

        title = f"🔔 {push_notify.coin_symbol(coin)} {coin} {entry['direction'].upper()}"
        heading = "Terug in de betere-entry-zone" if in_entry_zone else "Terug bij een interessant niveau"
        body = f"{heading} ({entry['confidence']}) · {level_line} · Nu {current_price:.4f}"
        silent = push_notify.is_quiet_now(entry["quiet_hours_start"], entry["quiet_hours_end"])
        try:
            await push_notify.send_push(entry["user_id"], title, body, f"/coins/{coin}", silent=silent)
            logger.info("Niveau-seintje verstuurd naar %s voor %s", entry["username"], coin)
        except Exception:
            logger.exception("Niveau-seintje naar %s voor %s is mislukt", entry["username"], coin)
        repo.mark_level_alert_sent(entry["id"])
```

Wordt (nieuwe `sniper_hit`-gate vóór alles, `cache_key`-naam hieronder hernoemd naar `message_cache_key` om de botsing met de sniper-cache's eigen `cache_key` hierboven te vermijden):

```python
        signal_age = datetime.now(timezone.utc) - datetime.fromisoformat(entry["signal_created_at"])
        at_signal_level = (
            not in_entry_zone
            and sniper_hit is None
            and signal_age >= timedelta(minutes=PENDING_LEVEL_MIN_AGE_MINUTES)
            and entry["signal_price"] is not None
            and abs(current_price - entry["signal_price"]) <= entry["atr"] * PENDING_LEVEL_ATR_MULTIPLIER
        )

        matched_level = None
        if not in_entry_zone and sniper_hit is None and not at_signal_level and entry["message_id"] is not None:
            message_cache_key = (entry["message_id"], coin)
            if message_cache_key not in coin_levels:
                coin_levels[message_cache_key] = repo.list_source_levels_for_message(entry["message_id"], coin)
            matched_level = _nearest_level(current_price, entry["atr"], coin_levels[message_cache_key])

        if not in_entry_zone and sniper_hit is None and not at_signal_level and not matched_level:
            continue

        if sniper_hit is not None:
            sniper_price, sniper_reason = sniper_hit
            title = f"🎯 {push_notify.coin_symbol(coin)} {coin} {entry['direction'].upper()} — sniper-trigger geraakt"
            body = f"{sniper_price:.4f} · {sniper_reason} · Nu {current_price:.4f}"
        else:
            if in_entry_zone:
                level_line = f"Betere entry: {entry['suggested_entry_low']:.4f}–{entry['suggested_entry_high']:.4f}"
            elif matched_level:
                level_desc = f"{matched_level['price_level']}"
                if matched_level["pattern_name"]:
                    level_desc += f" ({matched_level['pattern_name']})"
                level_line = f"Bron niveau: {level_desc}"
            else:
                level_line = f"Signaalniveau: {entry['signal_price']:.4f}"
            title = f"🔔 {push_notify.coin_symbol(coin)} {coin} {entry['direction'].upper()}"
            heading = "Terug in de betere-entry-zone" if in_entry_zone else "Terug bij een interessant niveau"
            body = f"{heading} ({entry['confidence']}) · {level_line} · Nu {current_price:.4f}"

        silent = push_notify.is_quiet_now(entry["quiet_hours_start"], entry["quiet_hours_end"])
        try:
            await push_notify.send_push(entry["user_id"], title, body, f"/coins/{coin}", silent=silent)
            logger.info("Niveau-seintje verstuurd naar %s voor %s", entry["username"], coin)
        except Exception:
            logger.exception("Niveau-seintje naar %s voor %s is mislukt", entry["username"], coin)
        repo.mark_level_alert_sent(entry["id"])
```

- [ ] **Step 2: Testscript — sniper-trigger vuurt, heeft voorrang, vuurt daarna niet nogmaals**

Maak `/tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/test_level_check_sniper.py`:

```python
import os, sys
sys.path.insert(0, "/home/user/Trade")
DBPATH = "/tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/scratch_lc_sniper.db"
if os.path.exists(DBPATH):
    os.remove(DBPATH)
os.environ["DATABASE_PATH"] = DBPATH

import asyncio
import pandas as pd
from unittest.mock import patch
from app import db, repo

db.init_db()
user_id = repo.create_user("tester", "x", 1000.0, 1.0)
repo.ensure_coin_tracked("SOL") if hasattr(repo, "ensure_coin_tracked") else None

signal_id = repo.insert_signal({
    "message_id": None, "coin": "SOL", "direction": "long", "category": "day_trading",
    "price": 140.0, "atr": 2.0, "technical_confirmed": 1, "pass_pct": 80.0, "hard_gates_ok": 1,
    "confidence": "hoog vertrouwen", "reason": "test", "stop_loss": 135.0, "take_profit": 150.0,
    # Geen sniper bij aanmaak -> sniper_entry_price blijft NULL, level_check
    # moet dus zelf gaan zoeken.
})
repo.create_journal_entry(signal_id, user_id, risk_eur=10.0)

N = 100
sweep_df = pd.DataFrame({
    "open": [140.0] * N, "high": [141.0] * N, "low": [139.0] * N,
    "close": [140.0] * N, "volume": [1000.0] * N,
})
sweep_df.loc[50, ["low", "high", "close", "open"]] = [135.0, 140.5, 139.0, 139.0]
sweep_df.loc[99, ["low", "high", "close", "open"]] = [134.0, 141.5, 136.0, 139.0]

from app import level_check

with patch("app.exchange.fetch_last_price", return_value=140.0), \
     patch("app.exchange.fetch_ohlcv", return_value=sweep_df), \
     patch("app.push_notify.send_push", return_value=None) as mock_push:
    asyncio.run(level_check.check_pending_signals())

assert mock_push.called, "sniper-melding had moeten vuren"
title, body = mock_push.call_args.args[1], mock_push.call_args.args[2]
assert "sniper-trigger geraakt" in title
assert "135.0000" in body
assert "bear trap" in body
print("OK: sniper-trigger vuurt met de juiste tekst")

# level_alert_sent moet nu op 1 staan (dezelfde vlag als de andere drie situaties).
journal_rows = repo.list_journal(user_id)
assert len(journal_rows) == 1
# list_journal zelf geeft level_alert_sent niet door (niet in _JOURNAL_SELECT),
# dus rechtstreeks nagaan via list_pending_entries_with_price: die filtert er
# juist OP (level_alert_sent = 0), dus na het vuren hoort deze rij te verdwijnen.
still_pending = repo.list_pending_entries_with_price()
assert len(still_pending) == 0, "entry had uit de pending-lijst moeten verdwijnen na het vuren"
print("OK: level_alert_sent gezet, geen tweede melding in een volgende cyclus")

os.remove(DBPATH)
print("ALLE TESTS GESLAAGD")
```

- [ ] **Step 3: Run het script**

Run: `python3 /tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/test_level_check_sniper.py`
Expected: `ALLE TESTS GESLAAGD`. Als `repo.ensure_coin_tracked` niet bestaat (de `hasattr`-guard vangt dat af) of `create_user`/`insert_signal` een ander verplicht veld missen dan hierboven aangenomen, pas de testdata aan op basis van de foutmelding — de kern van de test (sniper vuurt, heeft voorrang, vuurt niet nogmaals) blijft ongewijzigd.

- [ ] **Step 4: Regressie op de drie bestaande situaties (niet stuk maken)**

Voeg aan hetzelfde testscript, vóór de `os.remove(DBPATH)`-regel, een tweede scenario toe zonder sweep (sniper_df zonder sweep-candle) om te bevestigen dat de bestaande "terug bij een interessant niveau"-melding nog steeds werkt wanneer er geen sniper-treffer is:

```python
# Scenario 2: geen sweep, wel terug bij het signaalniveau -> bestaande
# situatie moet nog steeds werken (deze taak mag geen regressie veroorzaken).
DBPATH2 = "/tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/scratch_lc_sniper2.db"
if os.path.exists(DBPATH2):
    os.remove(DBPATH2)
os.environ["DATABASE_PATH"] = DBPATH2
db.init_db()
user_id_2 = repo.create_user("tester2", "x", 1000.0, 1.0)
from datetime import datetime, timedelta, timezone
old_signal_id = repo.insert_signal({
    "message_id": None, "coin": "SOL", "direction": "long", "category": "day_trading",
    "price": 140.0, "atr": 2.0, "technical_confirmed": 1, "pass_pct": 80.0, "hard_gates_ok": 1,
    "confidence": "hoog vertrouwen", "reason": "test", "stop_loss": 135.0, "take_profit": 150.0,
})
repo.create_journal_entry(old_signal_id, user_id_2, risk_eur=10.0)
flat_df = pd.DataFrame({
    "open": [140.0] * N, "high": [141.0] * N, "low": [139.0] * N,
    "close": [140.0] * N, "volume": [1000.0] * N,
})  # geen pivots, dus zeker geen sweep

with patch("app.exchange.fetch_last_price", return_value=140.3), \
     patch("app.exchange.fetch_ohlcv", return_value=flat_df), \
     patch("app.push_notify.send_push", return_value=None) as mock_push_2:
    asyncio.run(level_check.check_pending_signals())

assert mock_push_2.called, "de bestaande signaalniveau-melding had moeten vuren"
title_2 = mock_push_2.call_args.args[1]
assert "sniper" not in title_2.lower(), "mag geen sniper-titel gebruiken zonder sweep"
print("OK: bestaande niveau-melding werkt nog steeds zonder sweep, geen regressie")
os.remove(DBPATH2)
```

- [ ] **Step 5: Run het uitgebreide script opnieuw**

Run: `python3 /tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/test_level_check_sniper.py`
Expected: `ALLE TESTS GESLAAGD`

- [ ] **Step 6: Commit**

```bash
cd /home/user/Trade
git add app/level_check.py
git commit -m "$(cat <<'EOF'
Sniper-entry: proactieve trigger in level_check.py als de sweep later komt

check_pending_signals() probeert voor een nog niet genomen signaal zonder
sniper bij aanmaak elke cyclus opnieuw of de sweep alsnog gebeurt (verse
candles, gecachet per coin+richting binnen de cyclus). Heeft voorrang op
de bestaande drie proactieve situaties, hergebruikt dezelfde
level_alert_sent-vlag (geen nieuwe kolom, geen dubbele melding).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 7: Volledige regressie en push

**Files:** geen wijzigingen — alleen verificatie.

**Interfaces:** geen.

- [ ] **Step 1: Alle scratch-testscripts uit Taak 1-6 opnieuw draaien, in volgorde**

```bash
cd /home/user/Trade
for f in test_sniper_price test_sniper_storage test_signal_processor_sniper test_market_scanner_sniper test_sniper_card test_level_check_sniper; do
  echo "=== $f ==="
  python3 "/tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/${f}.py" || echo "FAILED: $f"
done
```

Expected: elk script eindigt met `ALLE TESTS GESLAAGD`, geen `FAILED`-regel.

- [ ] **Step 2: Bestaande regressie — `scripts/backtest_factors.py` moet nog steeds draaien**

Run: `python3 scripts/backtest_factors.py --limit 20`
Expected: geen crash (dit script raakt `compute_advanced_extra_factors`/`confirms_direction` niet aan, maar loopt wel door `indicators.py` — een syntaxfout of een per-ongeluk gewijzigde functie-signature elders in dat bestand zou hier meteen zichtbaar worden).

- [ ] **Step 3: Volledige `ast.parse`-syntaxcheck op alle vijf bewerkte bestanden in één keer**

```bash
python3 -c "
import ast
for f in ['app/indicators.py', 'app/db.py', 'app/repo.py', 'app/signal_processor.py', 'app/market_scanner.py', 'app/level_check.py']:
    ast.parse(open(f).read())
    print(f, 'OK')
"
```

- [ ] **Step 4: Opruimen van de scratch-databases**

```bash
rm -f /tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/scratch_*.db*
```

- [ ] **Step 5: Push**

```bash
cd /home/user/Trade
git push -u origin claude/crypto-day-trading-alerts-5p8w6v
```

- [ ] **Step 6: Deploy-instructies voor de gebruiker (geen aparte commit, alleen communiceren)**

Na de push: `crypto-bot` herstarten (raakt `app/*.py`, de achtergrond-processen) én `crypto-web` herstarten (raakt `web/templates/_macros.html`/`web/static/style.css`):

```bash
cd /opt/crypto-alerts && git pull
sudo systemctl restart crypto-bot
sudo systemctl restart crypto-web
```

De nieuwe `sniper_entry_price`/`sniper_reason`-kolommen worden automatisch aangemaakt bij de eerste herstart van `crypto-bot` (via `db.init_db()`/`_migrate()`), geen los migratiescript nodig. Een sniper-trigger wordt pas zichtbaar zodra er een echte sweep gebeurt op een nieuw of nog wachtend signaal — niet met terugwerkende kracht op bestaande signalen van vóór de deploy.
