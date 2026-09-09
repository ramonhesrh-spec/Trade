# Steun/weerstand-zones Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HesPulse herkent zelf, puur uit de 4h candle-geschiedenis, waar
de prijs herhaaldelijk gekeerd is (steun/weerstand-zones), gebruikt dat om
de voorgestelde stop loss/take profit te verscherpen, telt het mee als
nieuwe score-factor, en toont het op de grafiek.

**Architecture:** Een pure detectiefunctie in `app/indicators.py` zoekt
lokale keerpunten (pivots) en clustert ze tot zones. Zones worden platte
kandidaat-niveaus voor de al bestaande, al geteste
`risk.compute_stop_take_from_levels` (geen nieuwe stop/take-selectielogica
nodig), en voeden een nieuwe fail-closed factor in
`compute_advanced_extra_factors`. De `/api/candles`-route en `coin.js`
tonen dezelfde zones als vlakke, doorzichtige blokken, in een eigen kleur
naast de bestaande community-niveau-zones.

**Tech Stack:** Python 3.11, pandas, FastAPI, Jinja2, vanilla JS,
TradingView Lightweight Charts v4.

**Spec:** `docs/superpowers/specs/2026-09-09-steun-weerstand-zones-design.md`

## Global Constraints

- Geen database-migratie: alles live berekend uit al opgehaalde
  candle-data, niets wordt opgeslagen (spec, Niet-doelen).
- `SR_PIVOT_WINDOW = 3`, `SR_ZONE_LOOKBACK = 100`,
  `SR_ZONE_CLUSTER_TOLERANCE_PCT = 0.005`, `SR_ZONE_MIN_TOUCHES = 2`,
  `SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE = 6.0` (spec, Sectie 1).
- Geen aparte steun/weerstand-classificatie: één zone-type, de rol
  (steun of weerstand) volgt uit de positie t.o.v. de huidige prijs, niet
  uit aparte detectielogica (spec, Niet-doelen).
- De swing-toets (`evaluate_level_watch`, `compute_stop_take_from_levels`
  voor community-niveaus in de swing-flow) blijft volledig ongewijzigd —
  dit plan raakt alleen het day-trading pad en de oefentrade-route (spec,
  Niet-doelen).
- `CONFIRM_THRESHOLD` blijft 60%. Van 10 naar 11 geavanceerde factoren,
  van 14 naar 15 totaal (spec, Sectie 3).
- `risk.compute_stop_take_from_levels` zelf wordt NIET aangepast: zones
  worden platte kandidaat-niveaus die deze al bestaande functie
  binnengaan, geen nieuwe selectielogica in `risk.py` (spec,
  Zelf-review).
- Dit project heeft geen pytest-suite en geen testmap in de repo (zie
  CLAUDE.md). Elke test in dit plan is een losstaand, wegwerpbaar script
  in de sessie-scratchpad-map, gedraaid met `python3 <pad>` — niet
  gecommit naar de repo. Vervang `<SCRATCHPAD>` hieronder door het pad
  dat je systeemprompt als scratchpad-directory noemt.

---

### Task 1: Zone-detectie en score-check (`app/indicators.py`)

**Files:**
- Modify: `app/indicators.py` (nieuwe dataclass, constanten en functies na `check_liquidity`/`check_volume_percentile`/de candlestick-patroonfuncties, vóór de `BASIC_CONFIRM_MIN_PASSED`-sectie)
- Test: `<SCRATCHPAD>/test_sr_zones.py`

**Interfaces:**
- Consumes: niets nieuws — alleen pandas, al geïmporteerd.
- Produces:
  - `SRZone` (dataclass: `price_low: float`, `price_high: float`, `touches: int`)
  - `detect_sr_zones(df: pd.DataFrame, lookback: int = SR_ZONE_LOOKBACK) -> list[SRZone]` — gebruikt door Task 2 (score + stop/take) en Task 3 (grafiek-API).
  - `check_sr_zone(direction: str, entry_price: float, atr: float, zones: list[SRZone]) -> tuple[str, bool, str]` — gebruikt door Task 2.

- [ ] **Step 1: Schrijf het testscript met de eerste falende asserties**

Maak `<SCRATCHPAD>/test_sr_zones.py`:

```python
import sys
sys.path.insert(0, "/home/user/Trade")

import random
import pandas as pd
from app import indicators

passed = failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  OK  {label}")
    else:
        failed += 1
        print(f"  FAIL {label}")


# --- detect_sr_zones: drie bewuste testen van hetzelfde niveau moeten één zone met 3 touches geven ---
random.seed(42)
touches_at = {10, 40, 70}
rows = []
for i in range(90):
    if i in touches_at:
        low = 100.0 + random.uniform(-0.05, 0.05)
        high = low + random.uniform(2, 4)
        open_ = high - 0.5
        close = high - 0.3
    else:
        low = 103.0 + random.uniform(0, 3)
        high = low + random.uniform(1, 3)
        open_ = low + 0.5
        close = low + 1.0
    rows.append({"open": open_, "high": high, "low": low, "close": close})
df = pd.DataFrame(rows)

zones = indicators.detect_sr_zones(df)
check("er is een zone rond 100.0 met 3 touches", any(z.price_low <= 100.05 and z.price_high >= 99.95 and z.touches == 3 for z in zones))
check("alle zones hebben minimaal SR_ZONE_MIN_TOUCHES touches", all(z.touches >= indicators.SR_ZONE_MIN_TOUCHES for z in zones))
check("elke zone se price_low <= price_high", all(z.price_low <= z.price_high for z in zones))

# --- detect_sr_zones: te weinig candles voor een pivot geeft geen crash, lege lijst ---
tiny_df = pd.DataFrame({"open": [1.0, 1.0], "high": [1.1, 1.1], "low": [0.9, 0.9], "close": [1.0, 1.0]})
zones_tiny = indicators.detect_sr_zones(tiny_df)
check("te weinig candles geeft lege lijst, geen crash", zones_tiny == [])

# --- check_sr_zone: zone binnen bereik aan de stop-kant ---
z = indicators.SRZone(price_low=95.5, price_high=95.8, touches=3)
name, ok, detail = indicators.check_sr_zone("long", 100.0, atr=2.0, zones=[z])
check("factornaam is 'Steun/weerstand'", name == "Steun/weerstand")
check("long: zone onder de entry binnen 6x ATR telt mee", ok)

name, ok, detail = indicators.check_sr_zone("short", 100.0, atr=2.0, zones=[z])
check("short: zone onder de entry (verkeerde kant) telt niet mee", not ok)

# --- check_sr_zone: zone te ver weg telt niet mee ---
z_far = indicators.SRZone(price_low=50.0, price_high=50.5, touches=5)
name, ok, detail = indicators.check_sr_zone("long", 100.0, atr=2.0, zones=[z_far])
check("zone verder dan 6x ATR telt niet mee", not ok)

# --- check_sr_zone: geen zones ---
name, ok, detail = indicators.check_sr_zone("long", 100.0, atr=2.0, zones=[])
check("geen zones: factor faalt met duidelijke reden", not ok and "geen zone" in detail)

print(f"\n=== {passed} geslaagd, {failed} gefaald ===")
sys.exit(1 if failed else 0)
```

- [ ] **Step 2: Run het script, bevestig `AttributeError`**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_sr_zones.py
```

- [ ] **Step 3: Implementeer `SRZone`, de constanten en `detect_sr_zones` in `app/indicators.py`**

Voeg toe na de bestaande candlestick-patroonfuncties (na `scan_candle_patterns`), vóór de `BASIC_CONFIRM_MIN_PASSED`-sectie:

```python
# Hoeveel candles aan elke kant moeten "lager" (voor een pivot-high) of
# "hoger" (voor een pivot-low) zijn, wil een candle als lokaal keerpunt
# tellen. 3 is streng genoeg om ruis (elke kleine schommeling) niet als
# keerpunt te zien, maar laat genoeg pivots over op de laatste 100
# candles om zinvol te kunnen clusteren.
SR_PIVOT_WINDOW = 3

# Hoeveel candles terug de zone-detectie meeneemt. Ruim genoeg voor
# meerdere testen van dezelfde zone, niet zo ruim dat een allang niet meer
# relevant niveau van maanden geleden nog meetelt.
SR_ZONE_LOOKBACK = 100

# Hoe dicht twee pivot-prijzen bij elkaar moeten liggen (als fractie van
# de prijs) om tot dezelfde zone te horen. Te klein: elke pivot wordt zijn
# eigen "zone" van 1 punt, nooit genoeg touches. Te groot: totaal
# ongerelateerde niveaus versmelten tot één onbruikbaar brede band.
SR_ZONE_CLUSTER_TOLERANCE_PCT = 0.005

# Minimaal aantal pivots in een cluster om als echte zone te tellen. Eén
# pivot is geen patroon, twee is het begin van "de prijs kwam hier al
# eerder terug".
SR_ZONE_MIN_TOUCHES = 2


@dataclass
class SRZone:
    price_low: float
    price_high: float
    touches: int


def detect_sr_zones(df: pd.DataFrame, lookback: int = SR_ZONE_LOOKBACK) -> list[SRZone]:
    """Vindt structurele steun/weerstand-zones in de laatste `lookback`
    candles: eerst lokale keerpunten (pivot-highs/-lows, een candle die
    hoger/lager is dan SR_PIVOT_WINDOW candles aan beide kanten), daarna
    geclusterd tot zones (pivots binnen SR_ZONE_CLUSTER_TOLERANCE_PCT van
    elkaar horen bij dezelfde zone). Een zone telt pas mee vanaf
    SR_ZONE_MIN_TOUCHES pivots. Geen aparte steun/weerstand-classificatie:
    dezelfde zone kan beide rollen spelen afhankelijk van de kant waar de
    prijs vandaan komt, dat wordt pas bij gebruik (risk.py, de score-
    factor) bepaald aan de hand van de huidige prijs."""
    window = df.tail(lookback).reset_index(drop=True)
    n = len(window)
    pivots: list[float] = []

    for i in range(SR_PIVOT_WINDOW, n - SR_PIVOT_WINDOW):
        high_i = window["high"].iloc[i]
        low_i = window["low"].iloc[i]
        left_highs = window["high"].iloc[i - SR_PIVOT_WINDOW:i]
        right_highs = window["high"].iloc[i + 1:i + SR_PIVOT_WINDOW + 1]
        if high_i > left_highs.max() and high_i > right_highs.max():
            pivots.append(float(high_i))
        left_lows = window["low"].iloc[i - SR_PIVOT_WINDOW:i]
        right_lows = window["low"].iloc[i + 1:i + SR_PIVOT_WINDOW + 1]
        if low_i < left_lows.min() and low_i < right_lows.min():
            pivots.append(float(low_i))

    if not pivots:
        return []

    pivots.sort()
    clusters: list[list[float]] = [[pivots[0]]]
    for price in pivots[1:]:
        cluster_high = clusters[-1][-1]
        if price <= cluster_high * (1 + SR_ZONE_CLUSTER_TOLERANCE_PCT):
            clusters[-1].append(price)
        else:
            clusters.append([price])

    return [
        SRZone(price_low=min(c), price_high=max(c), touches=len(c))
        for c in clusters
        if len(c) >= SR_ZONE_MIN_TOUCHES
    ]
```

- [ ] **Step 4: Run het script, bevestig dat de `detect_sr_zones`-asserties slagen en `check_sr_zone`-asserties nog falen op `AttributeError`**

- [ ] **Step 5: Implementeer `check_sr_zone` in `app/indicators.py`**

Voeg toe direct na `detect_sr_zones`:

```python
# Hoe ver een zone maximaal van de entry mag liggen (in ATR) om nog als
# kandidaat te tellen voor de stop/take-verfijning en deze factor. Een
# zone die zes keer de ATR verderop ligt is geen realistisch punt meer
# voor déze trade, ook al is de zone zelf sterk.
SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE = 6.0


def check_sr_zone(direction: str, entry_price: float, atr: float, zones: list[SRZone]) -> tuple[str, bool, str]:
    """Is er een bruikbare zone aan de stop-kant van de prijs (onder de
    entry bij long, erboven bij short) binnen SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE
    x ATR? Zelfde kant-bepaling als risk.compute_stop_take_from_levels
    gebruikt voor community-niveaus, hier toegepast op zelf-gedetecteerde
    zones. Geen aparte richting-afhankelijke detectie nodig: een zone is
    een zone, welke kant hem "steun" maakt hangt puur af van waar de
    entry-prijs zit."""
    direction = direction.lower()
    max_distance = SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE * atr
    edges = [edge for zone in zones for edge in (zone.price_low, zone.price_high)]

    if direction == "long":
        candidates = [e for e in edges if e < entry_price and entry_price - e <= max_distance]
    else:
        candidates = [e for e in edges if e > entry_price and e - entry_price <= max_distance]

    if not candidates:
        return ("Steun/weerstand", False, "geen zone dichtbij genoeg voor een bruikbaar niveau")

    nearest = max(candidates) if direction == "long" else min(candidates)
    distance_atr = abs(entry_price - nearest) / atr if atr else 0.0
    return ("Steun/weerstand", True, f"zone op {distance_atr:.1f}x ATR afstand")
```

- [ ] **Step 6: Run het volledige script, bevestig dat alle asserties slagen**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_sr_zones.py
```

Verwacht: `=== 9 geslaagd, 0 gefaald ===`.

- [ ] **Step 7: Commit**

```bash
git add app/indicators.py
git commit -m "Steun/weerstand-zone-detectie: pivots + clustering

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q"
```

---

### Task 2: Koppeling in `signal_processor.py` en `web/main.py`

**Files:**
- Modify: `app/signal_processor.py` (functie `compute_advanced_extra_factors`, en de aanroep ervan + stop/take-berekening in `process_day_trading_signal`)
- Modify: `web/main.py` (aanroep van `compute_advanced_extra_factors` in de `/coins/{symbol}/oefen`-route)
- Test: `<SCRATCHPAD>/test_sr_zones_pipeline.py`

**Interfaces:**
- Consumes: `indicators.detect_sr_zones`, `indicators.check_sr_zone`, `indicators.SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE` (Task 1). Bestaande `risk.compute_stop_take_from_levels` (ongewijzigd).
- Produces: `compute_advanced_extra_factors` krijgt een nieuwe signatuur —
  `async def compute_advanced_extra_factors(coin: str, direction: str, df, entry_price: float, atr: float, zones: list[indicators.SRZone]) -> list[tuple[str, bool, str]]`.
  Beide bestaande aanroepers (day-trading pipeline, oefentrade-route)
  moeten hierop aangepast worden — dat is expliciet onderdeel van deze
  taak, niet een taak ernaast.

- [ ] **Step 1: Pas de signatuur en body van `compute_advanced_extra_factors` aan in `app/signal_processor.py`**

Zoek de functie-declaratie:

```python
async def compute_advanced_extra_factors(coin: str, direction: str, df) -> list[tuple[str, bool, str]]:
```

Vervang door:

```python
async def compute_advanced_extra_factors(
    coin: str, direction: str, df, entry_price: float, atr: float, zones: list[indicators.SRZone],
) -> list[tuple[str, bool, str]]:
```

Voeg aan het einde van de functie (na het bestaande Liquiditeit-blok, vóór de `return factors`-regel) toe:

```python
    try:
        factors.append(indicators.check_sr_zone(direction, entry_price, atr, zones))
    except Exception:
        logger.exception("Steun/weerstand voor %s kon niet berekend worden", coin)
        factors.append(("Steun/weerstand", False, "kon niet berekend worden, telt als niet bevestigd"))
```

- [ ] **Step 2: Pas de aanroep en de stop/take-berekening aan in `process_day_trading_signal`**

Zoek (rond de plek waar `df`/`ind`/`swing_low`/`swing_high` berekend worden en waar `compute_stop_take_from_levels`/`compute_stop_take` aangeroepen worden):

```python
    df = await asyncio.to_thread(exchange.fetch_ohlcv, interp.coin)
    ind = indicators.compute_indicators(df)
    swing_low, swing_high = indicators.swing_levels(df)

    extra_factors = None
    if config.ENABLE_ADVANCED_FACTORS:
        extra_factors = await compute_advanced_extra_factors(interp.coin, interp.direction, df)

    confirmed, reason = indicators.confirms_direction(
        ind, interp.direction, extra_factors=extra_factors, include_advanced=config.ENABLE_ADVANCED_FACTORS,
    )
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

Vervang door:

```python
    df = await asyncio.to_thread(exchange.fetch_ohlcv, interp.coin)
    ind = indicators.compute_indicators(df)
    swing_low, swing_high = indicators.swing_levels(df)
    zones = indicators.detect_sr_zones(df)

    extra_factors = None
    if config.ENABLE_ADVANCED_FACTORS:
        extra_factors = await compute_advanced_extra_factors(
            interp.coin, interp.direction, df, ind.price, ind.atr, zones,
        )

    confirmed, reason = indicators.confirms_direction(
        ind, interp.direction, extra_factors=extra_factors, include_advanced=config.ENABLE_ADVANCED_FACTORS,
    )
    message_levels = [lvl["price_level"] for lvl in repo.list_source_levels_for_message(message_id)]
    zone_levels = [
        edge for zone in zones for edge in (zone.price_low, zone.price_high)
        if abs(edge - ind.price) <= indicators.SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE * ind.atr
    ]
    combined_levels = message_levels + zone_levels
    if combined_levels:
        stop_take = risk.compute_stop_take_from_levels(
            interp.direction, ind.price, ind.atr, combined_levels, swing_low=swing_low, swing_high=swing_high,
        )
    else:
        stop_take = risk.compute_stop_take(
            interp.direction, ind.price, ind.atr, swing_low=swing_low, swing_high=swing_high,
        )
```

`zones` wordt hier ONVOORWAARDELIJK berekend (niet achter `ENABLE_ADVANCED_FACTORS`), omdat de stop/take-verfijning voor iedereen moet werken, niet alleen als de uitgebreide factoren aan staan.

- [ ] **Step 3: Pas de aanroep aan in `web/main.py`'s `/coins/{symbol}/oefen`-route**

Zoek:

```python
    extra_factors = None
    if config.ENABLE_ADVANCED_FACTORS:
        extra_factors = await compute_advanced_extra_factors(symbol, direction, df)
```

Vervang door:

```python
    extra_factors = None
    if config.ENABLE_ADVANCED_FACTORS:
        zones = indicators.detect_sr_zones(df)
        extra_factors = await compute_advanced_extra_factors(symbol, direction, df, ind.price, ind.atr, zones)
```

Hier blijft `stop_take` (uit `_fetch_practice_trade_calc`, gebruikt de gewone `risk.compute_stop_take` zonder niveaus) bewust ongewijzigd: de spec scopet de stop/take-verfijning alleen op het day-trading pad, de oefentrade-route krijgt wel de nieuwe factor in de score (voor een consistente factor-lijst), maar geen aangepaste stop/take-berekening. `zones` hier is lokaal aan het `if`-blok, alleen nodig voor de factor-aanroep.

- [ ] **Step 4: Schrijf en run de integratietest**

Maak `<SCRATCHPAD>/test_sr_zones_pipeline.py`, naar het patroon van de
eerdere `test_candle_pattern_pipeline.py` uit deze sessie: tijdelijke DB,
`ENABLE_ADVANCED_FACTORS=true`, gemockte `exchange.fetch_ohlcv` voor
4h/1h/1d/BTC, `coinlist.ensure_coin_tracked` gemockt op `(True, False)`.
De candle-data bevat een bewuste 3-voudige test van eenzelfde niveau vlak
onder de laatste prijs, zodat zowel de factor als de stop/take-verfijning
aantoonbaar geraakt worden.

```python
import asyncio
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, "/home/user/Trade")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-sr-zones-pipeline-0123456789012345"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"
os.environ["ENABLE_ADVANCED_FACTORS"] = "true"

from app import config
config.DATABASE_PATH = db_path
config.ENABLE_ADVANCED_FACTORS = True

from app import db, repo, security, signal_processor, coinlist
from app.anthropic_interpret import Interpretation
from app.db import session as db_session

import random
import pandas as pd
import numpy as np

db.init_db()
repo.create_user("srzoneuser", security.hash_password("testpass123"), 10000.0, 1.0, "1")
repo.add_coin_if_new("SUIUSDT", "spot")

# Downtrend candles met een bewuste 3-voudige test van 0.640 (net onder de
# laatste prijs van ~0.65), zodat er een echte zone met 3 touches ontstaat
# vlak aan de stop-kant van een long.
random.seed(7)
n = 90
touches_at = {10, 40, 70}
rows = []
for i in range(n):
    if i in touches_at:
        low = 0.640 + random.uniform(-0.0005, 0.0005)
        high = low + random.uniform(0.004, 0.006)
        open_ = high - 0.001
        close = high - 0.0008
    else:
        low = 0.66 + random.uniform(0, 0.02)
        high = low + random.uniform(0.005, 0.015)
        open_ = low + 0.001
        close = low + 0.003
    rows.append({"open": open_, "high": high, "low": low, "close": close, "volume": 500000.0})
# Laatste candle: duidelijk boven de zone, zodat de zone een bruikbare
# stop-kandidaat is voor een long-signaal.
rows[-1] = {"open": 0.648, "high": 0.652, "low": 0.646, "close": 0.650, "volume": 500000.0}
fake_4h = pd.DataFrame(rows)

fake_1h = pd.DataFrame({
    "open": np.linspace(0.63, 0.65, 60), "high": np.linspace(0.64, 0.66, 60),
    "low": np.linspace(0.62, 0.64, 60), "close": np.linspace(0.63, 0.65, 60),
    "volume": np.full(60, 500000.0),
})
fake_daily = pd.DataFrame({
    "open": np.linspace(0.9, 0.65, 60), "high": np.linspace(0.91, 0.66, 60),
    "low": np.linspace(0.89, 0.64, 60), "close": np.linspace(0.9, 0.65, 60),
    "volume": np.full(60, 1_000_000.0),
})
fake_btc = pd.DataFrame({
    "open": np.linspace(65000, 60000, 60), "high": np.linspace(65100, 60100, 60),
    "low": np.linspace(64900, 59900, 60), "close": np.linspace(65000, 60000, 60),
    "volume": np.full(60, 100.0),
})


def fake_fetch_ohlcv(coin, timeframe="4h"):
    if coin.upper() == "BTC":
        return fake_btc
    if timeframe == "1h":
        return fake_1h
    if timeframe == "1d":
        return fake_daily
    return fake_4h


interp = Interpretation(coin="SUI", direction="long", category="day_trading", unclear=False)

with patch("app.signal_processor.exchange.fetch_ohlcv", side_effect=fake_fetch_ohlcv), \
     patch("app.signal_processor.exchange.fetch_24h_quote_volume", return_value=5_000_000.0), \
     patch.object(coinlist, "ensure_coin_tracked", return_value=(True, False)):
    message_id = repo.insert_message("test bericht SUI long", [], None)
    asyncio.run(signal_processor.process_day_trading_signal(message_id, interp))

with db_session() as conn:
    row = conn.execute("SELECT reason, stop_loss FROM signals ORDER BY id DESC LIMIT 1").fetchone()

assert row is not None, "geen signal-rij aangemaakt"
reason = row["reason"]
stop_loss = row["stop_loss"]
print(f"reason: {reason}")
print(f"stop_loss: {stop_loss}")
assert "Steun/weerstand" in reason, f"factor 'Steun/weerstand' ontbreekt: {reason}"
print("OK: 'Steun/weerstand' zit in de breakdown")
# De zone ligt rond 0.640-0.641; de stop moet daar vlak onder zitten
# (met de kleine ATR-buffer), niet op de losse 1.5x ATR fallback-afstand
# vanaf entry ~0.650.
assert 0.635 < stop_loss < 0.642, f"stop_loss {stop_loss} lijkt niet op de zone gebaseerd te zijn"
print("OK: stop_loss is verfijnd op basis van de gedetecteerde zone, niet de kale ATR-fallback")
```

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_sr_zones_pipeline.py
```

Verwacht: script eindigt met de laatste `print`-regel, geen traceback
vóór die regel (de Telegram-stap erna mag wél een `NetworkError` geven,
zie CLAUDE.md, dat is de bekende sandbox-beperking, geen testfout). Als
de stop_loss-assertie faalt omdat de fake candle-data een andere zone
oplevert dan verwacht: pas de fake-data of de assertie-marge aan zodat ze
overeenkomen met wat `detect_sr_zones` er daadwerkelijk uit haalt (print
`indicators.detect_sr_zones(fake_4h)` om te zien welke zones er echt
gevonden worden), verander niet de productielogica om de test te laten
slagen.

- [ ] **Step 5: Commit**

```bash
git add app/signal_processor.py web/main.py
git commit -m "Bedraad steun/weerstand-zones in score en stop/take-verfijning

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q"
```

---

### Task 3: `/api/candles/{symbol}` route

**Files:**
- Modify: `web/main.py` (route `api_candles`)
- Test: `<SCRATCHPAD>/test_api_candles_sr_zones.py`

**Interfaces:**
- Consumes: `indicators.detect_sr_zones` (Task 1).
- Produces: response-veld `sr_zones: list[{"price_low": float, "price_high": float, "touches": int}]`, gebruikt door Task 4 (`coin.js`).

- [ ] **Step 1: Lees de huidige route**

```bash
grep -n "async def api_candles" -A 25 /home/user/Trade/web/main.py
```

- [ ] **Step 2: Schrijf de falende test**

Maak `<SCRATCHPAD>/test_api_candles_sr_zones.py`, naar het patroon van de
eerdere `test_api_candles_patterns.py` uit deze sessie: tijdelijke DB,
`TestClient`, sessie-cookie, gemockte `exchange.fetch_ohlcv` met dezelfde
bewust 3-voudig geteste candle-reeks als Task 2's integratietest.

```python
import os, sys, tempfile
sys.path.insert(0, "/home/user/Trade")
sys.path.insert(0, "/home/user/Trade/web")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd); os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-api-candles-sr-zones-012345678901"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path
from app import db, repo, security

db.init_db()
uid = repo.create_user("apisrzoneuser", security.hash_password("testpass123"), 1000.0, 1.0, "1")

import main as web_main
from fastapi.testclient import TestClient
from unittest.mock import patch
import random
import pandas as pd

client = TestClient(web_main.app)
token = security.create_session_token(uid)
client.cookies.set("session", token)

random.seed(7)
n = 90
touches_at = {10, 40, 70}
rows = []
for i in range(n):
    if i in touches_at:
        low = 0.640 + random.uniform(-0.0005, 0.0005)
        high = low + random.uniform(0.004, 0.006)
        open_ = high - 0.001
        close = high - 0.0008
    else:
        low = 0.66 + random.uniform(0, 0.02)
        high = low + random.uniform(0.005, 0.015)
        open_ = low + 0.001
        close = low + 0.003
    rows.append({"open": open_, "high": high, "low": low, "close": close, "volume": 500000.0})
timestamps = pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC")
fake_df = pd.DataFrame(rows)
fake_df.insert(0, "timestamp", timestamps)

with patch("main.exchange.fetch_ohlcv", return_value=fake_df):
    resp = client.get("/api/candles/SUIUSDT")
assert resp.status_code == 200, resp.text
data = resp.json()
assert "sr_zones" in data, f"'sr_zones' ontbreekt in de response: {list(data.keys())}"
assert any(z["touches"] == 3 for z in data["sr_zones"]), f"geen zone met 3 touches gevonden: {data['sr_zones']}"
for z in data["sr_zones"]:
    assert set(z.keys()) == {"price_low", "price_high", "touches"}, z
    assert z["price_low"] <= z["price_high"]
print(f"OK: {len(data['sr_zones'])} zones teruggegeven, inclusief de verwachte 3-touches zone")
```

- [ ] **Step 3: Run de test, bevestig `AssertionError` op `'sr_zones'`**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_api_candles_sr_zones.py
```

- [ ] **Step 4: Implementeer het nieuwe veld**

Voeg toe in `api_candles`, na de bestaande `pattern_matches`/`patterns`-berekening, vóór de `return`-regel:

```python
    zones = indicators.detect_sr_zones(df)
    sr_zones = [
        {"price_low": z.price_low, "price_high": z.price_high, "touches": z.touches}
        for z in zones
    ]
```

En voeg `"sr_zones": sr_zones` toe aan de teruggegeven dict.

- [ ] **Step 5: Run de test, bevestig dat hij slaagt**

- [ ] **Step 6: Commit**

```bash
git add web/main.py
git commit -m "/api/candles: sr_zones-veld met herkende steun/weerstand-zones

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q"
```

---

### Task 4: Grafiek-weergave (`coin.js` + `coin.html` + `style.css`)

**Files:**
- Modify: `web/static/coin.js:39` (comment/scope, mirror van hoe `narrativeMarkers` al vroeg gedeclareerd wordt), `web/static/coin.js:79-99` (na de bestaande `zoneEls`/`positionZones`-declaraties), `web/static/coin.js:193-212` (in de fetch-callback, vóór `chart.timeScale().fitContent();`)
- Modify: `web/static/style.css` (nieuwe `.chart-zone-sr`-klasse, na de bestaande `.chart-zone`-klasse rond regel 1277-1287)
- Test: handmatige verificatie (zie Step 5) — grafiek-JS, geen server-route om te unit-testen; `<SCRATCHPAD>/test_api_candles_sr_zones.py` uit Task 3 bevestigt al dat de data-laag klopt.

**Interfaces:**
- Consumes: `data.sr_zones` uit `/api/candles/{symbol}` (Task 3).
- Produces: geen nieuwe interface voor latere tasks.

- [ ] **Step 1: Declareer `srZoneEls` op dezelfde plek als `narrativeMarkers` (`web/static/coin.js`, rond regel 37-39)**

Zoek de regel `let narrativeMarkers = [];` en voeg er direct na toe:

```javascript

  // Zelf-gedetecteerde steun/weerstand-zones (indicators.detect_sr_zones,
  // via het sr_zones-veld van /api/candles). Anders dan de community-
  // zoneGroups hieronder (al bekend uit sourceLevels vóór de fetch) bestaan
  // deze pas ná de fetch, dus srZoneEls wordt pas in de .then()-callback
  // gevuld — maar moet hier al gedeclareerd staan zodat positionZones()
  // (aangeroepen vanaf de eerste render) hem veilig kan itereren, ook
  // vóórdat de fetch klaar is (dan gewoon een lege lijst).
  let srZoneEls = [];
```

- [ ] **Step 2: Breid `positionZones()` uit om ook `srZoneEls` te positioneren**

Zoek de bestaande `positionZones()`-functie (rond regel 87-99):

```javascript
  function positionZones() {
    zoneEls.forEach(({ group, el }) => {
      const yHigh = candleSeries.priceToCoordinate(group.high);
      const yLow = candleSeries.priceToCoordinate(group.low);
      if (yHigh === null || yLow === null) {
        el.style.display = "none";
        return;
      }
      el.style.display = "block";
      el.style.top = `${yHigh}px`;
      el.style.height = `${Math.max(yLow - yHigh, 2)}px`;
    });
  }
```

Vervang door:

```javascript
  function positionZones() {
    zoneEls.forEach(({ group, el }) => {
      const yHigh = candleSeries.priceToCoordinate(group.high);
      const yLow = candleSeries.priceToCoordinate(group.low);
      if (yHigh === null || yLow === null) {
        el.style.display = "none";
        return;
      }
      el.style.display = "block";
      el.style.top = `${yHigh}px`;
      el.style.height = `${Math.max(yLow - yHigh, 2)}px`;
    });
    srZoneEls.forEach(({ zone, el }) => {
      const yHigh = candleSeries.priceToCoordinate(zone.price_high);
      const yLow = candleSeries.priceToCoordinate(zone.price_low);
      if (yHigh === null || yLow === null) {
        el.style.display = "none";
        return;
      }
      el.style.display = "block";
      el.style.top = `${yHigh}px`;
      el.style.height = `${Math.max(yLow - yHigh, 2)}px`;
    });
  }
```

- [ ] **Step 3: Bouw de zone-elementen in de fetch-callback (`web/static/coin.js`, vóór `chart.timeScale().fitContent();` rond regel 211)**

Zoek:

```javascript
      chart.timeScale().fitContent();
      positionZones();
```

Vervang door:

```javascript
      // Eén blok per zelf-gedetecteerde zone, in een eigen kleur
      // (chart-zone-sr) om ze te onderscheiden van de teal community-
      // niveau-zones hierboven. Sterkte (touches) als klein label op de
      // zone zelf, geen aparte lijst nodig zoals bij de candlestick-
      // patronen: een zone is als vlak al zichtbaar genoeg.
      srZoneEls = (data.sr_zones || []).map((zone) => {
        const el = document.createElement("div");
        el.className = "chart-zone-sr";
        el.innerHTML = `<span>${zone.touches}x getest</span>`;
        container.appendChild(el);
        return { zone, el };
      });

      chart.timeScale().fitContent();
      positionZones();
```

- [ ] **Step 4: Voeg de `.chart-zone-sr`-stijl toe aan `web/static/style.css`**

Zoek de bestaande `.chart-zone`/`.chart-zone span`-regels (rond regel
1277-1287) en voeg er direct na toe:

```css
/* Coin grafiek: zone-blok voor zelf-gedetecteerde steun/weerstand
   (indicators.detect_sr_zones) — eigen kleur (violet) om te onderscheiden
   van de teal community-niveau-zones hierboven. */
.chart-zone-sr {
  position: absolute; left: 0; right: 60px; pointer-events: none; min-height: 6px;
  background: rgba(167, 139, 250, 0.10); border-top: 1px dashed rgba(167, 139, 250, 0.5);
  border-bottom: 1px dashed rgba(167, 139, 250, 0.5);
}
.chart-zone-sr span {
  position: absolute; top: 2px; left: 8px; font-size: 11px; font-weight: 600;
  color: #a78bfa; background: rgba(10, 14, 15, 0.85); padding: 1px 6px;
  border-radius: 3px; white-space: nowrap; border: 1px solid var(--border-strong);
}
```

- [ ] **Step 5: Handmatige verificatie met Playwright**

Zelfde aanpak als bij de candlestick-patronen deze sessie: start de
server tegen een scratch-DB met `app.exchange.fetch_ohlcv` gemockt
in-process (`uvicorn.run` na `unittest.mock.patch`, niet via de
`uvicorn`-CLI, anders werkt de mock niet voor de live server), seed een
gebruiker en coin, navigeer met Playwright naar `/coins/<SYMBOL>`, en
maak een screenshot.

```python
# <SCRATCHPAD>/run_server_with_mock_sr.py
import sys
sys.path.insert(0, "/home/user/Trade")
from unittest.mock import patch
import random
import pandas as pd

random.seed(7)
n = 90
touches_at = {10, 40, 70}
rows = []
for i in range(n):
    if i in touches_at:
        low = 0.640 + random.uniform(-0.0005, 0.0005)
        high = low + random.uniform(0.004, 0.006)
        open_ = high - 0.001
        close = high - 0.0008
    else:
        low = 0.66 + random.uniform(0, 0.02)
        high = low + random.uniform(0.005, 0.015)
        open_ = low + 0.001
        close = low + 0.003
    rows.append({"open": open_, "high": high, "low": low, "close": close, "volume": 500000.0})
timestamps = pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC")
fake_df = pd.DataFrame(rows)
fake_df.insert(0, "timestamp", timestamps)

patcher = patch("app.exchange.fetch_ohlcv", return_value=fake_df)
patcher.start()

import uvicorn
uvicorn.run("web.main:app", host="127.0.0.1", port=8421)
```

Seed een scratch-DB (`db.init_db()`, `repo.create_user(...)`,
`repo.add_coin_if_new("SUIUSDT", "spot")`) met dezelfde
`DATABASE_PATH`/`JWT_SECRET`/`TELEGRAM_BOT_TOKEN` env vars als het
serverscript, start het script op de achtergrond, log in met een
sessie-cookie via `security.create_session_token`, navigeer naar
`http://127.0.0.1:8421/coins/SUIUSDT`, wacht tot `#chart-loading`
verdwenen is, maak een screenshot. Controleer: staat er een violet blok
rond prijs ~0.640 met het label "3x getest"? Blijft het bestaande teal
community-niveau-blok (indien aanwezig) er los naast staan, zonder
overlap-conflict in de layout? Sluit de server af na de check.

Als `cdn.jsdelivr.net` opnieuw onbereikbaar blijkt (bekende sandbox-
beperking van deze sessie, zie het candlestick-patronen-plan): dezelfde
workaround (npm-registry fetch + Playwright route-interceptie,
uitsluitend voor het testen, geen source-wijziging) is toegestaan en al
eerder succesvol gebruikt.

Kun je de server of Playwright niet aan de praat krijgen om een echte
reden (niet alleen "dit is lastig"): rapporteer DONE_WITH_CONCERNS met de
specifieke blokkade, verzin geen "ziet er goed uit" zonder screenshot.

- [ ] **Step 6: Commit**

```bash
git add web/static/coin.js web/static/style.css
git commit -m "Grafiek: zone-blokken voor zelf-gedetecteerde steun/weerstand

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q"
```

---

### Task 5: `scripts/backtest_factors.py` en `/uitleg`

**Files:**
- Modify: `scripts/backtest_factors.py` (binnen `evaluate_signal`, in het eerste `try`-blok, na de bestaande `Volume-percentiel`-regel)
- Modify: `web/templates/uitleg.html` (factor-grid en telwoorden)
- Test: handmatige inspectie (geen netwerktoegang in de sandbox voor `backtest_factors.py` zelf) + `<SCRATCHPAD>/test_uitleg_sr_zone_card.py` voor de template

**Interfaces:**
- Consumes: `indicators.detect_sr_zones`, `indicators.check_sr_zone` (Task 1).
- Produces: geen nieuwe interface — laatste inhoudelijke stap van dit deelproject.

- [ ] **Step 1: Werk `scripts/backtest_factors.py` bij**

Zoek in `evaluate_signal`, binnen het eerste `try`-blok, de regel:

```python
        _, vol_pct_ok, _ = indicators.check_volume_percentile(ind)
        results["Volume-percentiel"] = vol_pct_ok
```

Voeg er direct na toe (nog binnen hetzelfde `try`-blok):

```python
        zones = indicators.detect_sr_zones(df)
        _, sr_ok, _ = indicators.check_sr_zone(direction, ind.price, ind.atr, zones)
        results["Steun/weerstand"] = sr_ok
```

- [ ] **Step 2: Controleer dat het script nog importeert zonder fouten**

```bash
source /home/user/Trade/.venv/bin/activate && python3 -c "import scripts.backtest_factors"
```

- [ ] **Step 3: Werk `web/templates/uitleg.html` bij**

Zoek de kop en intro-tekst van de geavanceerde-factoren-sectie (bijgewerkt
deze sessie naar "tien"):

```html
  <h2>Tien extra factoren</h2>
  <p>Naast de vier factoren hierboven toetst HesPulse ook op tien extra
  factoren. Die tellen nu mee in elke melding.</p>
  {% else %}
  <h2>In de maak: tien extra factoren</h2>
  <p>Naast de vier factoren hierboven staat er een uitgebreidere toetsing
  klaar, maar die staat nog uit. Eerst wordt getoetst hoe streng de nieuwe
  regels in de praktijk uitpakken op eerdere signalen, voor ze meetellen in
  een echte melding.</p>
  {% endif %}
```

Vervang door (elf i.p.v. tien):

```html
  <h2>Elf extra factoren</h2>
  <p>Naast de vier factoren hierboven toetst HesPulse ook op elf extra
  factoren. Die tellen nu mee in elke melding.</p>
  {% else %}
  <h2>In de maak: elf extra factoren</h2>
  <p>Naast de vier factoren hierboven staat er een uitgebreidere toetsing
  klaar, maar die staat nog uit. Eerst wordt getoetst hoe streng de nieuwe
  regels in de praktijk uitpakken op eerdere signalen, voor ze meetellen in
  een echte melding.</p>
  {% endif %}
```

Voeg een nieuwe factor-kaart toe aan het `factor-grid` (na de bestaande
"Liquiditeit"-kaart, laatste kaart in de grid):

```html
    <div class="factor factor-preview">
      <h3>Steun/weerstand</h3>
      <p>Ligt er een zone binnen 6x ATR aan de stop-kant van de entry —
      een prijsniveau waar de markt zelf al minstens twee keer eerder
      keerde? Dezelfde zone verscherpt ook de voorgestelde stop loss en
      take profit.</p>
    </div>
```

Zoek de afsluitende alinea die het totaal aantal factoren en de drempel
noemt:

```html
  <div class="group-note">
    Bij de uitgebreide toetsing telt geen enkele factor apart als harde
    eis. Alle veertien factoren (de vier basisfactoren plus deze tien)
    tellen gezamenlijk mee, en minstens 60% moet kloppen. Zo blokkeert één
    marginale miss niet meteen een verder overtuigend signaal, en blijft
    precies zichtbaar welke factor(en) niet klopten.
  </div>
```

Vervang door (vijftien i.p.v. veertien, elf i.p.v. tien):

```html
  <div class="group-note">
    Bij de uitgebreide toetsing telt geen enkele factor apart als harde
    eis. Alle vijftien factoren (de vier basisfactoren plus deze elf)
    tellen gezamenlijk mee, en minstens 60% moet kloppen. Zo blokkeert één
    marginale miss niet meteen een verder overtuigend signaal, en blijft
    precies zichtbaar welke factor(en) niet klopten.
  </div>
```

- [ ] **Step 4: Schrijf en run een test die de bijgewerkte pagina controleert**

Maak `<SCRATCHPAD>/test_uitleg_sr_zone_card.py`, naar het patroon van de
eerdere `test_uitleg_candlepatroon_card.py`:

```python
import os, sys, tempfile
sys.path.insert(0, "/home/user/Trade")
sys.path.insert(0, "/home/user/Trade/web")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd); os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-uitleg-sr-zone-0123456789012345"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path
from app import db, repo, security

db.init_db()
uid = repo.create_user("uitlegsrzonetester", security.hash_password("testpass123"), 1000.0, 1.0, "1")

import main as web_main
from fastapi.testclient import TestClient

client = TestClient(web_main.app)
token = security.create_session_token(uid)
client.cookies.set("session", token)

resp = client.get("/uitleg")
assert resp.status_code == 200, resp.text
html = resp.text
for expected in ["elf extra factoren", "Steun/weerstand", "vijftien factoren"]:
    assert expected in html, f"'{expected}' ontbreekt op de uitleg-pagina"
    print(f"OK: '{expected}' staat op de pagina")
print("\nuitleg-pagina toont de bijgewerkte factorenlijst met Steun/weerstand.")
```

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_uitleg_sr_zone_card.py
```

- [ ] **Step 5: Commit**

```bash
git add scripts/backtest_factors.py web/templates/uitleg.html
git commit -m "Backtest + uitleg-pagina: steun/weerstand-factor toegevoegd

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q"
```

---

### Task 6: Volledige regressie en push

**Files:** geen wijzigingen — alleen verificatie.

**Interfaces:** geen — dit is de afsluitende controle van alle vorige tasks samen.

- [ ] **Step 1: Draai alle nieuwe testscripts uit dit plan opnieuw achter elkaar**

```bash
source /home/user/Trade/.venv/bin/activate
for f in test_sr_zones.py test_sr_zones_pipeline.py \
         test_api_candles_sr_zones.py test_uitleg_sr_zone_card.py; do
  echo "=== $f ==="
  python3 <SCRATCHPAD>/$f || echo "FAILED: $f"
done
```

Verwacht: elk script eindigt met zijn eigen "geslaagd"/"OK"-regel, geen
`FAILED`-regel in de output.

- [ ] **Step 2: Draai de bestaande regressietests van eerdere sessies/deelprojecten die de factorenset raken**

```bash
python3 <SCRATCHPAD>/test_factor_refinements.py
python3 <SCRATCHPAD>/test_advanced_factors_integration.py
python3 <SCRATCHPAD>/test_uitleg_page_factors.py
python3 <SCRATCHPAD>/test_candle_pattern_detectors.py
python3 <SCRATCHPAD>/test_candle_pattern_combined.py
python3 <SCRATCHPAD>/test_candle_pattern_pipeline.py
python3 <SCRATCHPAD>/test_api_candles_patterns.py
python3 <SCRATCHPAD>/test_uitleg_candlepatroon_card.py
```

Deze bevestigen dat het toevoegen van de steun/weerstand-factor de
eerdere twee deelprojecten (factor-verfijningen, candlestick-patronen)
niet breekt — `compute_advanced_extra_factors`'s signatuur is uitgebreid,
niet de bestaande factoren zelf.

- [ ] **Step 3: Importcontrole van alle gewijzigde modules**

```bash
python3 -c "
import app.indicators as indicators
import app.signal_processor as signal_processor
import scripts.backtest_factors as bf
print('alle gewijzigde modules importeren zonder fouten')
"
```

- [ ] **Step 4: Controleer de git-status en push**

```bash
git status --short
git log --oneline -10
git push -u origin claude/crypto-day-trading-alerts-5p8w6v
```

Verwacht: `git status --short` toont geen wijzigingen (alles uit Task 1-5
is al gecommit), de laatste 6-7 commits tonen de tasks uit dit plan, en
de push slaagt.
