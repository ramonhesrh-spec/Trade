# Entry-zone structuurbevestiging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** De "terug in de betere-entry-zone"-pushmelding in `app/level_check.py` wacht voortaan op een 15m-afwijzingscandle voordat hij afgaat, in plaats van meteen te vuren zodra de live prijs toevallig terug in de voorgestelde zone staat.

**Architecture:** Eén nieuwe, pure functie `_entry_zone_rejection_seen` bepaalt of een candle-reeks een afwijzing van de zone laat zien (zelfde logica als de SMC-detector al gebruikt). De bestaande `in_entry_zone`-berekening in `check_pending_signals()` wordt in twee stappen geknipt: een ruwe prijscheck (ongewijzigd) poort een nieuwe, per-coin gecachte 15m-candle-fetch die door die functie gehaald wordt. Geen schemawijziging, geen nieuwe state.

**Tech Stack:** Python 3, pandas (candle-DataFrames), bestaande `app.exchange`/`app.push_notify`/`app.repo`-modules, SQLite via `app.db` voor scratch-DB-tests.

**Spec:** `docs/superpowers/specs/2026-09-30-entry-zone-structuurbevestiging-design.md`

## Global Constraints

- `app/repo.py` is de enige plek die de database aanraakt — niet van toepassing hier, deze wijziging voegt geen databasetoegang toe en raakt geen schema.
- Geen pytest-suite in dit project: verifieer met throwaway scripts tegen een scratch-database (`DATABASE_PATH=/tmp/scratch.db`), nooit met `pytest`.
- Alleen **gesloten** candles tellen mee voor de structuurbevestiging (laatste candle van een `exchange.fetch_ohlcv`-respons is nog vormend en valt weg met `.iloc[:-1]`).
- Terugkijkperiode: `ENTRY_ZONE_CONFIRM_LOOKBACK_CANDLES = 8` gesloten 15m-candles (2 uur), timeframe `ENTRY_ZONE_CONFIRM_TIMEFRAME = "15m"`. Vaste periode, geen bijgehouden status, geen schemawijziging.
- Commit-berichten eindigen met:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
  ```
- Code-commentaar en commit-berichten in het Nederlands, informele stijl, consistent met de rest van `app/level_check.py` (why-comments, geen what-comments).
- VPS-deploy na de laatste push: `cd /opt/crypto-alerts && sudo -u crypto git pull origin claude/crypto-day-trading-alerts-5p8w6v`, daarna `sudo systemctl restart crypto-level-check.timer`.

---

### Task 1: `_entry_zone_rejection_seen` schrijven + losse functietest

**Files:**
- Modify: `app/level_check.py` (nieuwe constantes + nieuwe functie, toevoegen na de bestaande `_nearest_level`-functie die eindigt op regel 200, vóór `async def check_pending_signals()` op regel 203)
- Test: scratchpad-script, geen vast pad in de repo (throwaway, zie Testen-conventie hierboven)

**Interfaces:**
- Produces: `ENTRY_ZONE_CONFIRM_TIMEFRAME: str`, `ENTRY_ZONE_CONFIRM_LOOKBACK_CANDLES: int`, `_entry_zone_rejection_seen(direction: str, zone_low: float, zone_high: float, candles) -> bool` — `candles` is een pandas DataFrame met kolommen `open`/`high`/`low`/`close`/`timestamp` (zelfde vorm als overal elders in dit bestand, zie `exchange.fetch_ohlcv`'s eigen contract). Gebruikt door Task 2.

- [ ] **Step 1: Lees de exacte plek waar de nieuwe code komt**

Open `app/level_check.py` en bevestig dat regel 200 eindigt met de laatste regel van `_nearest_level` (`return min(within_range, key=lambda lvl: abs(current_price - lvl["price_level"]))`) en regel 203 begint met `async def check_pending_signals() -> None:`. Als de regelnummers inmiddels verschoven zijn (bijvoorbeeld door een eerdere, niet-gerelateerde wijziging), zoek de functies op naam op in plaats van op regelnummer.

- [ ] **Step 2: Voeg de constantes en de functie toe**

Voeg dit toe direct na `_nearest_level` (vóór `async def check_pending_signals`):

```python
# Timeframe + terugkijkperiode voor de structuurbevestiging van de
# betere-entry-zone hieronder: een candle moet de zone geraakt hebben EN
# aan de gunstige kant weer gesloten zijn voordat de melding afgaat, niet
# alleen "de live prijs staat er toevallig". Zelfde afwijzingslogica als
# market_scanner._smc_last_candle_state, hier toegepast op de gewone
# suggested_entry_low/high van een dagtradingsignaal in plaats van een
# SMC-zone. Vaste terugkijkperiode, geen bijgehouden status: zelfde
# aanpak als LEVEL_CHECK_CANDLE_TIMEFRAME/LOOKBACK hierboven, voor
# dezelfde reden (eenvoud, geen migratie, geen vergeten-reset-risico).
ENTRY_ZONE_CONFIRM_TIMEFRAME = "15m"
ENTRY_ZONE_CONFIRM_LOOKBACK_CANDLES = 8  # 2 uur, gesloten candles


def _entry_zone_rejection_seen(direction: str, zone_low: float, zone_high: float, candles) -> bool:
    """True zodra minstens één candle in `candles` de zone raakte (wick of
    volledige overlap) EN aan de gunstige kant weer sloot (long: close
    boven zone_high, short: eronder). `candles` moet alleen gesloten
    candles bevatten — de aanroeper filtert de nog vormende laatste candle
    er al uit, zie check_pending_signals."""
    for _, candle in candles.iterrows():
        touched = (
            zone_low <= candle["low"] <= zone_high
            or zone_low <= candle["high"] <= zone_high
            or (candle["low"] <= zone_low and candle["high"] >= zone_high)
        )
        if not touched:
            continue
        if direction == "long" and candle["close"] > zone_high:
            return True
        if direction == "short" and candle["close"] < zone_low:
            return True
    return False
```

- [ ] **Step 3: Importcheck**

```bash
cd /home/user/Trade && python3 -c "import app.level_check; print('import OK')"
```

Verwacht: `import OK`, geen `SyntaxError`/`ImportError`.

- [ ] **Step 4: Schrijf en draai een losse functietest (geen scratch-DB nodig)**

Maak `/tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/test_entry_zone_rejection.py` (of het equivalente scratchpad-pad van de uitvoerende sessie — zoek dat pad op via de eigen omgevingsinstructies als dit exacte pad niet bestaat) met:

```python
import sys
sys.path.insert(0, "/home/user/Trade")

import pandas as pd
from app.level_check import _entry_zone_rejection_seen

def make_candle(o, h, l, c):
    return {"timestamp": None, "open": o, "high": h, "low": l, "close": c, "volume": 100.0}

zone_low, zone_high = 100.0, 105.0

# Long: candle raakt de zone en sluit erboven -> afwijzing gezien
rejecting_long = pd.DataFrame([
    make_candle(106, 107, 104, 106),  # raakt niet
    make_candle(104, 106.5, 99.5, 106.2),  # raakt de zone (low 99.5 < zone_high), sluit boven zone_high
])
assert _entry_zone_rejection_seen("long", zone_low, zone_high, rejecting_long) is True

# Long: candle raakt de zone maar sluit ERIN of eronder -> geen afwijzing
not_rejecting_long = pd.DataFrame([
    make_candle(103, 104, 101, 102),  # raakt de zone, sluit binnenin, geen afwijzing
])
assert _entry_zone_rejection_seen("long", zone_low, zone_high, not_rejecting_long) is False

# Short: candle raakt de zone en sluit eronder -> afwijzing gezien
rejecting_short = pd.DataFrame([
    make_candle(99, 105.5, 98.5, 99.2),  # raakt de zone (high 105.5 > zone_low), sluit onder zone_low
])
assert _entry_zone_rejection_seen("short", zone_low, zone_high, rejecting_short) is True

# Geen enkele candle raakt de zone -> geen afwijzing, ongeacht richting
never_touches = pd.DataFrame([
    make_candle(110, 111, 109, 110.5),
])
assert _entry_zone_rejection_seen("long", zone_low, zone_high, never_touches) is False
assert _entry_zone_rejection_seen("short", zone_low, zone_high, never_touches) is False

print("Alle checks geslaagd.")
```

Run:

```bash
cd /home/user/Trade && python3 /tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/test_entry_zone_rejection.py
```

Expected: `Alle checks geslaagd.`, geen `AssertionError`.

- [ ] **Step 5: Commit**

```bash
cd /home/user/Trade
git add app/level_check.py
git commit -m "$(cat <<'EOF'
_entry_zone_rejection_seen: afwijzingslogica voor de betere-entry-zone

Eerste stap van de entry-zone-structuurbevestiging (zie
docs/superpowers/specs/2026-09-30-entry-zone-structuurbevestiging-design.md):
een losse, pure functie die bepaalt of een 15m-candle-reeks een echte
afwijzing van de zone laat zien, zelfde logica als de SMC-detector
(_smc_last_candle_state) al gebruikt. Nog niet aangesloten op
check_pending_signals, dat is de volgende taak.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

### Task 2: Wiring in `check_pending_signals` + drie scratch-DB-scenario's

**Files:**
- Modify: `app/level_check.py` (de `in_entry_zone`-berekening op regel 271-275, en de cache-declaraties op regel 220-223 — regelnummers gelden vóór Task 1's wijziging, dus tel de 27 nieuwe regels uit Task 1 erbij op, of zoek op de letterlijke code hieronder)
- Test: scratchpad-script (throwaway, scratch-database)

**Interfaces:**
- Consumes: `_entry_zone_rejection_seen(direction, zone_low, zone_high, candles) -> bool`, `ENTRY_ZONE_CONFIRM_TIMEFRAME`, `ENTRY_ZONE_CONFIRM_LOOKBACK_CANDLES` uit Task 1.
- Produces: gewijzigd gedrag van `check_pending_signals()` — geen nieuwe publieke namen.

- [ ] **Step 1: Vind de exacte bestaande code**

Zoek in `app/level_check.py` naar:

```python
        in_entry_zone = (
            entry["suggested_entry_low"] is not None
            and entry["suggested_entry_high"] is not None
            and entry["suggested_entry_low"] <= current_price <= entry["suggested_entry_high"]
        )
```

Dit staat direct na het blok dat `current_price` bepaalt en vóór het commentaarblok dat begint met `# Sniper-trigger heeft voorrang op de resterende twee situaties`.

- [ ] **Step 2: Voeg de nieuwe cache toe aan de bestaande cache-declaraties**

Zoek:

```python
    coin_prices: dict[str, float] = {}
    coin_levels: dict[tuple[int, str], list[dict]] = {}
    coin_sniper: dict[tuple[str, str], Optional[tuple[float, str]]] = {}
    coin_directions: dict[str, set[str]] = {}
```

Voeg een regel toe, zodat het blok wordt:

```python
    coin_prices: dict[str, float] = {}
    coin_levels: dict[tuple[int, str], list[dict]] = {}
    coin_sniper: dict[tuple[str, str], Optional[tuple[float, str]]] = {}
    coin_directions: dict[str, set[str]] = {}
    coin_entry_zone_candles: dict[str, object] = {}
```

- [ ] **Step 3: Vervang de `in_entry_zone`-berekening**

Vervang het blok uit Step 1 door:

```python
        # Ruwe prijscheck blijft de poort (ongewijzigd sinds eerder): geen
        # minimumleeftijd nodig, de entry-zone wordt bewust geclampt om
        # nooit de prijs op het moment van berekenen te bevatten (zie
        # signal_processor.py), dus een match hier is altijd echte
        # beweging richting een betere prijs, nooit "nog niet weg geweest"
        # zoals bij een vers signaal. Maar de ruwe prijscheck alleen was
        # niet genoeg: signaal 418 (ETH long) stuurde deze melding zodra de
        # prijs terugkwam in de zone en viel er binnen 20 minuten dwars
        # doorheen. in_entry_zone is daarom pas True als een 15m-candle
        # ook echt een afwijzing van de zone laat zien (zelfde logica als
        # de SMC-detector), niet alleen "de prijs staat er toevallig".
        raw_in_entry_zone = (
            entry["suggested_entry_low"] is not None
            and entry["suggested_entry_high"] is not None
            and entry["suggested_entry_low"] <= current_price <= entry["suggested_entry_high"]
        )
        in_entry_zone = False
        if raw_in_entry_zone:
            if coin not in coin_entry_zone_candles:
                try:
                    df = await asyncio.to_thread(
                        exchange.fetch_ohlcv, coin, timeframe=ENTRY_ZONE_CONFIRM_TIMEFRAME,
                        limit=ENTRY_ZONE_CONFIRM_LOOKBACK_CANDLES + 1,  # +1: laatste candle is nog vormend
                    )
                    coin_entry_zone_candles[coin] = df.iloc[:-1]
                except Exception:
                    logger.exception("Kon geen candles ophalen voor zone-bevestiging op %s, sla over", coin)
                    coin_entry_zone_candles[coin] = None
            candles = coin_entry_zone_candles[coin]
            if candles is not None:
                in_entry_zone = _entry_zone_rejection_seen(
                    entry["direction"], entry["suggested_entry_low"], entry["suggested_entry_high"], candles,
                )
```

Niets anders in de functie verandert: de sniper-trigger-check, `at_signal_level`, `matched_level`, de "geen van de vier situaties, sla over"-poort, de tegenstrijdig-signaal-check, en het title/body/heading-blok blijven precies zoals ze nu zijn — die lezen allemaal gewoon de nieuwe `in_entry_zone`-waarde, geen andere aanpassing nodig.

- [ ] **Step 4: Importcheck**

```bash
cd /home/user/Trade && python3 -c "import app.level_check; print('import OK')"
```

Expected: `import OK`.

- [ ] **Step 5: Schrijf het scratch-DB-testscript**

Maak `/tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/test_entry_zone_confirmation.py` (zelfde scratchpad-conventie als Task 1) met:

```python
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/home/user/Trade")

os.environ["DATABASE_PATH"] = "/tmp/scratch_entry_zone.db"
db_path = Path(os.environ["DATABASE_PATH"])
if db_path.exists():
    db_path.unlink()

import pandas as pd  # noqa: E402

from app import db, level_check, repo  # noqa: E402

db.init_db()
user_id = repo.create_user("entryzonetest", "hash", 1000.0, 1.0)


def make_candle(ts, o, h, l, c):
    return {"timestamp": ts, "open": o, "high": h, "low": l, "close": c, "volume": 100.0}


base = datetime.now(timezone.utc) - timedelta(hours=3)
zone_low, zone_high = 100.0, 105.0

# Scenario's candle-reeksen (9 candles: 8 gesloten + 1 nog vormende laatste,
# want de code haalt LOOKBACK+1 op en gooit de laatste weg).
no_rejection_candles = pd.DataFrame(
    [make_candle(base + timedelta(minutes=15 * i), 102, 104, 101, 102.5) for i in range(9)]
)

wrong_side_close_candles = pd.DataFrame(
    [make_candle(base + timedelta(minutes=15 * i), 102, 104, 99, 101) for i in range(8)]
    + [make_candle(base + timedelta(minutes=15 * 8), 101, 102, 100, 101.5)]  # nog vormend, telt niet mee
)

rejection_candles = pd.DataFrame(
    [make_candle(base + timedelta(minutes=15 * i), 102, 104, 101, 102.5) for i in range(6)]
    + [make_candle(base + timedelta(minutes=15 * 6), 102, 106.5, 99, 106.2)]  # raakt zone, sluit erboven
    + [make_candle(base + timedelta(minutes=15 * 7), 106, 107, 105.5, 106.5)]  # nog vormend, telt niet mee
)


def make_signal_and_entry(coin: str) -> int:
    signal_id = repo.insert_signal({
        "coin": coin, "direction": "long", "category": "day_trading", "trade_type": "day_trading",
        "price": 110.0, "stop_loss": 95.0, "take_profit": 130.0,
        "suggested_entry_low": zone_low, "suggested_entry_high": zone_high,
        "technical_confirmed": 1, "confidence": "hoog", "hard_gates_ok": 1, "reason": "test",
    })
    entry_id = repo.create_journal_entry(signal_id, user_id, 10.0)
    return entry_id


async def run_scenario(coin: str, candles: pd.DataFrame, live_price: float):
    push_calls = []

    async def fake_send_push(*args, **kwargs):
        push_calls.append(args)

    entry_id = make_signal_and_entry(coin)

    with patch("app.level_check.exchange.fetch_last_price", side_effect=lambda c: live_price), \
         patch("app.level_check.exchange.fetch_ohlcv", side_effect=lambda c, **kw: candles), \
         patch("app.level_check.push_notify.send_push", side_effect=fake_send_push):
        await level_check.check_pending_signals()

    with db.session() as conn:
        row = conn.execute("SELECT level_alert_sent FROM journal_entries WHERE id = ?", (entry_id,)).fetchone()
    return len(push_calls), row["level_alert_sent"]


print("=== Scenario 1: prijs in zone, geen afwijzingsclose ===")
push_count, alert_sent = asyncio.run(run_scenario("SCEN1", no_rejection_candles, 102.5))
print(f"pushmeldingen: {push_count}, level_alert_sent: {alert_sent}")
assert push_count == 0, "zonder afwijzing had geen melding verstuurd mogen worden"
assert alert_sent == 0, "level_alert_sent had 0 moeten blijven, zodat volgende cyclus opnieuw gekeken wordt"
print("OK\n")

print("=== Scenario 2: prijs in zone, echte afwijzingsclose binnen 2 uur ===")
push_count, alert_sent = asyncio.run(run_scenario("SCEN2", rejection_candles, 102.5))
print(f"pushmeldingen: {push_count}, level_alert_sent: {alert_sent}")
assert push_count == 1, "met een afwijzing had de melding verstuurd moeten worden"
assert alert_sent == 1, "level_alert_sent had gezet moeten worden"
print("OK\n")

print("=== Scenario 3: candle raakt de zone maar sluit aan de verkeerde kant ===")
push_count, alert_sent = asyncio.run(run_scenario("SCEN3", wrong_side_close_candles, 102.5))
print(f"pushmeldingen: {push_count}, level_alert_sent: {alert_sent}")
assert push_count == 0, "een close binnen/onder de zone is geen afwijzing, geen melding verwacht"
assert alert_sent == 0
print("OK\n")

print("Alle scenario's geslaagd.")
```

- [ ] **Step 6: Draai het testscript**

```bash
cd /home/user/Trade && rm -f /tmp/scratch_entry_zone.db && python3 /tmp/claude-0/-home-user-Trade/508ce90b-a6fe-5f5d-8450-3e33783001c5/scratchpad/test_entry_zone_confirmation.py
```

Expected output eindigt met `Alle scenario's geslaagd.`, geen `AssertionError` of Traceback. Als scenario 1 of 3 een melding verstuurt terwijl dat niet verwacht is, of scenario 2 juist geen melding verstuurt: controleer eerst of `ENTRY_ZONE_CONFIRM_LOOKBACK_CANDLES + 1` en `.iloc[:-1]` in de wiring kloppen (Step 3) voordat je de testcandles aanpast — de candle-reeksen hierboven zijn met opzet zo gebouwd dat de laatste candle van elke reeks NOOIT de afwijzing zelf bevat, om precies deze fout te vangen.

- [ ] **Step 7: Ruim het scratch-databasebestand op**

```bash
rm -f /tmp/scratch_entry_zone.db
```

- [ ] **Step 8: Commit**

```bash
cd /home/user/Trade
git add app/level_check.py
git commit -m "$(cat <<'EOF'
Entry-zone-melding wacht op 15m-structuurbevestiging voor het afgaat

Sluit de entry-zone-structuurbevestiging aan op check_pending_signals:
in_entry_zone is nu pas True als een gesloten 15m-candle de voorgestelde
entry-zone raakte EN aan de gunstige kant weer sloot
(_entry_zone_rejection_seen, vorige commit), niet meer alleen "de live
prijs staat er toevallig". Candle-fetch gebeurt alleen als de ruwe
prijscheck al klopt en wordt gecachet per coin binnen de cyclus, zelfde
patroon als de bestaande coin_prices/coin_sniper-caches. De overige drie
situaties (sniper-trigger, signaalniveau, bron niveau) en de melding-tekst
blijven ongewijzigd.

Getest met een scratch-database en drie candle-scenario's: geen afwijzing
(geen melding), een echte afwijzingsclose (melding + level_alert_sent),
en een close aan de verkeerde kant van de zone (geen melding).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

### Task 3: Volledige regressie, review, push, VPS-deploy

**Files:**
- Geen nieuwe wijzigingen verwacht — deze taak verifieert Task 1+2 samen en rondt af.

**Interfaces:**
- Consumes: alles uit Task 1 en Task 2.
- Produces: niets nieuws; eindstaat is een gepushte branch en een draaiende VPS.

- [ ] **Step 1: Draai de bestaande stop/take-candle-test opnieuw (bewijst dat Task 1+2 die logica niet raakten)**

Deze test bestond al eerder deze sessie (commit `2110340`, "Stop/take-check op candle-hoog/laag"). Herbouw hem kort met dezelfde structuur als hierboven, gericht op `check_open_trades` en `check_signal_outcomes` in plaats van `check_pending_signals`, met een scratch-database en een gemockte `exchange.fetch_ohlcv` die een candle-reeks met een korte wick door een stop heen teruggeeft. Bevestig dat:
- `check_signal_outcomes` een signaal met zo'n wick nog steeds als `stop_loss` markeert.
- `check_open_trades` nog steeds een pushmelding stuurt en `level_alert_sent` zet voor een open trade met zo'n wick.

Als je het exacte eerdere testscript niet meer hebt: `git show 2110340 -- app/level_check.py` laat de wijziging zien waarop dit gedrag gebaseerd is, gebruik dat als referentie voor de candle-vorm.

Run met dezelfde `DATABASE_PATH=/tmp/scratch.db`-conventie. Expected: geen `AssertionError`.

- [ ] **Step 2: Bekijk de volledige diff**

```bash
cd /home/user/Trade && git diff a15c2c5 -- app/level_check.py
```

(`a15c2c5` is de laatste commit vóór dit plan begon — als dat de HEAD van vóór Task 1 niet blijkt te zijn, gebruik `git log --oneline app/level_check.py | head -5` om de juiste basis-commit te vinden.)

Controleer: alleen de twee wijzigingen uit Task 1 (nieuwe constantes + functie) en Task 2 (cache + `in_entry_zone`-blok) zitten in de diff, niets anders in `check_pending_signals` of elders in het bestand is aangeraakt.

- [ ] **Step 3: Push**

```bash
cd /home/user/Trade && git push -u origin claude/crypto-day-trading-alerts-5p8w6v
```

- [ ] **Step 4: Geef VPS-deploy-instructies**

Twee losse commando's (niet combineren met `&&` in één plak-actie als eerder deze sessie tot verminkte commando's leidde):

```bash
cd /opt/crypto-alerts && sudo -u crypto git pull origin claude/crypto-day-trading-alerts-5p8w6v
```

Daarna:

```bash
sudo systemctl restart crypto-level-check.timer
```

- [ ] **Step 5: Bevestig bij de gebruiker**

Meld kort: welke twee commits gepusht zijn, dat de bestaande stop/take-regressie nog klopt, en dat de VPS herstart moet worden met de twee commando's hierboven om het live te krijgen.

## Self-Review (uitgevoerd tijdens het schrijven van dit plan)

1. **Spec-dekking:** alle vier onderdelen van de spec (bevestigingslogica, terugkijkperiode zonder schemawijziging, wiring, "wat niet verandert") staan in Task 1+2. Het testplan uit de spec (3 scenario's + losse functietest) staat expliciet in Task 1 Step 4 en Task 2 Step 5.
2. **Placeholder-scan:** geen TBD/TODO; elke stap bevat de letterlijke code of het letterlijke commando.
3. **Typeconsistentie:** `_entry_zone_rejection_seen(direction, zone_low, zone_high, candles)` heeft in Task 1 (definitie) en Task 2 (aanroep) dezelfde parameternamen en -volgorde. `ENTRY_ZONE_CONFIRM_TIMEFRAME`/`ENTRY_ZONE_CONFIRM_LOOKBACK_CANDLES` worden in Task 1 gedefinieerd en in Task 2 ongewijzigd hergebruikt.
