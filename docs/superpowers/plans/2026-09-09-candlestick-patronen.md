# Candlestick-patronen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HesPulse herkent zelf vijf nieuwe candlestick-patronen (Hammer,
Hanging Man, Shooting Star, Inverted Hammer, Doji, Morning Star, Evening
Star) naast de bestaande engulfing, laat ze meetellen in de bestaande
factor "Candlepatroon", en toont ze zichtbaar op de coin-grafiek met een
marker en een lijst eronder.

**Architecture:** Pure detectiefuncties in `app/indicators.py` (geen
database, geen netwerk) leveren `(naam, richting)`-tuples op basis van een
candle-index plus de al berekende EMA9/EMA21-reeksen. Eén samenvoegende
functie combineert ze met de bestaande engulfing-check tot de bestaande
factor "Candlepatroon" (score-pad); een aparte scanfunctie levert alle
gevonden patronen over een venster op (grafiek-pad). De `/api/candles`-
route en `coin.js` tonen dat venster als markers + lijst.

**Tech Stack:** Python 3.11, pandas, FastAPI, Jinja2, vanilla JS,
TradingView Lightweight Charts v4.

**Spec:** `docs/superpowers/specs/2026-09-09-candlestick-patronen-design.md`

## Global Constraints

- Geen database-migratie: alle patroondetectie is live berekend uit al
  opgehaalde candle-data, niets wordt opgeslagen (spec, Niet-doelen).
- `HAMMER_SHADOW_RATIO = 2.0`, `HAMMER_OPPOSITE_SHADOW_MAX_RATIO = 0.5`,
  `DOJI_BODY_MAX_RATIO = 0.1`, `DEFAULT_PATTERN_SCAN_LOOKBACK = 100` (spec,
  Sectie 1).
- De bestaande factor "Candlepatroon" blijft één factor; het totaal van 10
  geavanceerde / 14 totale factoren en `CONFIRM_THRESHOLD = 0.6` blijven
  ongewijzigd (spec, Niet-doelen).
- De bestaande `check_candle_pattern` (engulfing) blijft ongewijzigd
  bestaan als losse functie; geen dubbele engulfing-logica (spec,
  Zelf-review).
- `candleSeries.setMarkers()` in `coin.js` VERVANGT de volledige
  markerlijst bij elke aanroep. Patroon-markers en narrative-markers
  moeten daarom altijd samen in één array staan vóór een `setMarkers()`-
  aanroep (spec, Sectie 4, en Zelf-review).
- Dit project heeft geen pytest-suite en geen testmap in de repo (zie
  CLAUDE.md). Elke test in dit plan is een losstaand, wegwerpbaar script
  in de sessie-scratchpad-map, gedraaid met `python3 <pad>` tegen een
  tijdelijke SQLite-DB waar nodig — niet gecommit naar de repo. Vervang
  `<SCRATCHPAD>` hieronder door het pad dat je systeemprompt als
  scratchpad-directory noemt.
- Patroonnamen blijven in het internationale vaktermen-Engels (Hammer,
  Hanging Man, Shooting Star, Inverted Hammer, Doji, Morning Star, Evening
  Star), consistent met de bestaande "bullish/bearish engulfing" (spec,
  Sectie 1).

---

### Task 1: Single-candle- en sterpatroon-detectoren

**Files:**
- Modify: `app/indicators.py` (nieuwe constanten en functies na `check_liquidity`/`check_volume_percentile`, vóór de `BASIC_CONFIRM_MIN_PASSED`-sectie; imports bovenaan uitbreiden met `from typing import Optional`)
- Test: `<SCRATCHPAD>/test_candle_pattern_detectors.py`

**Interfaces:**
- Consumes: niets nieuws — alleen pandas/`ta` die al geïmporteerd zijn.
- Produces:
  - `detect_single_candle_patterns(df: pd.DataFrame, index: int, ema9_series: list[float], ema21_series: list[float]) -> list[tuple[str, str]]`
  - `detect_star_pattern(df: pd.DataFrame, index: int) -> Optional[tuple[str, str]]`
  - Beide gebruikt door Task 2 en Task 3.

- [ ] **Step 1: Schrijf het testscript met de eerste falende asserties**

Maak `<SCRATCHPAD>/test_candle_pattern_detectors.py`:

```python
import sys
sys.path.insert(0, "/home/user/Trade")

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


def make_df(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


# --- Hammer: lange onderstaart, klein lichaam bovenin, na een downtrend ---
rows = [{"open": 100 - i * 0.5, "high": 100 - i * 0.5 + 0.2, "low": 100 - i * 0.5 - 0.2, "close": 100 - i * 0.5 - 0.1} for i in range(20)]
rows.append({"open": 90.5, "high": 90.65, "low": 85.0, "close": 90.6})  # lange onderstaart, klein lichaam boven
df_hammer = make_df(rows)
ema9 = [90.0] * 19 + [88.0, 87.0]
ema21 = [92.0] * 19 + [92.0, 91.0]  # ema9 < ema21 vlak voor de candle: downtrend
patterns = indicators.detect_single_candle_patterns(df_hammer, 20, ema9, ema21)
check("Hammer herkend na downtrend", ("Hammer", "bullish") in patterns)

# --- Hanging Man: zelfde vorm, na een uptrend ---
ema9_up = [92.0] * 19 + [93.0, 94.0]
ema21_up = [90.0] * 19 + [90.0, 90.5]  # ema9 > ema21: uptrend
patterns = indicators.detect_single_candle_patterns(df_hammer, 20, ema9_up, ema21_up)
check("Hanging Man herkend na uptrend (zelfde candle-vorm)", ("Hanging Man", "bearish") in patterns)

# --- Shooting Star: lange bovenstaart, klein lichaam onderin, na uptrend ---
rows2 = [{"open": 100 + i * 0.5, "high": 100 + i * 0.5 + 0.2, "low": 100 + i * 0.5 - 0.2, "close": 100 + i * 0.5 + 0.1} for i in range(20)]
rows2.append({"open": 109.5, "high": 115.0, "low": 109.35, "close": 109.4})  # lange bovenstaart, klein lichaam onder
df_star = make_df(rows2)
patterns = indicators.detect_single_candle_patterns(df_star, 20, ema9_up, ema21_up)
check("Shooting Star herkend na uptrend", ("Shooting Star", "bearish") in patterns)

patterns = indicators.detect_single_candle_patterns(df_star, 20, ema9, ema21)
check("Inverted Hammer herkend na downtrend (zelfde candle-vorm)", ("Inverted Hammer", "bullish") in patterns)

# --- Doji: open ~= close, richting afhankelijk van voorafgaande trend ---
rows3 = list(rows)
rows3[-1] = {"open": 90.0, "high": 90.5, "low": 89.5, "close": 90.02}
df_doji = make_df(rows3)
patterns = indicators.detect_single_candle_patterns(df_doji, 20, ema9_up, ema21_up)
check("Doji na uptrend telt als bearish", ("Doji", "bearish") in patterns)
patterns = indicators.detect_single_candle_patterns(df_doji, 20, ema9, ema21)
check("Doji na downtrend telt als bullish", ("Doji", "bullish") in patterns)

# --- Geen trendcontext: te weinig candles ervoor ---
patterns = indicators.detect_single_candle_patterns(df_hammer, 0, ema9, ema21)
check("index 0 levert lege lijst (geen candle ervoor voor trendcontext)", patterns == [])

# --- Gewone candle zonder lange schaduw of klein lichaam: geen match ---
# Fris opgebouwd (niet `rows` hergebruikt, die is intussen 21 elementen
# met de hamer op index 20) zodat index 20 hier de nieuwe, gewone candle is.
rows4 = [{"open": 100 - i * 0.5, "high": 100 - i * 0.5 + 0.2, "low": 100 - i * 0.5 - 0.2, "close": 100 - i * 0.5 - 0.1} for i in range(20)]
rows4.append({"open": 90.0, "high": 91.0, "low": 89.0, "close": 90.8})
df_normal = make_df(rows4)
patterns = indicators.detect_single_candle_patterns(df_normal, 20, ema9, ema21)
check("gewone candle levert geen patroon op", patterns == [])

print(f"\n=== {passed} geslaagd, {failed} gefaald ===")
sys.exit(1 if failed else 0)
```

- [ ] **Step 2: Run het script en bevestig dat het faalt op `AttributeError`**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_candle_pattern_detectors.py
```

Verwacht: `AttributeError: module 'app.indicators' has no attribute 'detect_single_candle_patterns'`.

- [ ] **Step 3: Implementeer `detect_single_candle_patterns` in `app/indicators.py`**

Voeg toe na `check_volume_percentile` (aan het einde van de bestaande
`check_*`-functies, vóór de `BASIC_CONFIRM_MIN_PASSED`-constante):

```python
# Hoe lang de "staart" van een hamer/hangende man/vallende ster/omgekeerde
# hamer minimaal moet zijn t.o.v. het candle-lichaam, om als duidelijk
# patroon te tellen in plaats van een gewone candle met iets meer schaduw
# dan gemiddeld.
HAMMER_SHADOW_RATIO = 2.0

# Hoe klein de schaduw aan de ANDERE kant van het lichaam moet blijven
# (t.o.v. het lichaam zelf), zodat een candle met twee lange schaduwen
# (spinning top) niet per ongeluk als hamer of ster telt.
HAMMER_OPPOSITE_SHADOW_MAX_RATIO = 0.5

# Hoe klein het lichaam moet zijn t.o.v. de volledige candle-range
# (high - low) om als doji te tellen.
DOJI_BODY_MAX_RATIO = 0.1


def detect_single_candle_patterns(
    df: pd.DataFrame, index: int, ema9_series: list[float], ema21_series: list[float],
) -> list[tuple[str, str]]:
    """Hammer/Hanging Man/Shooting Star/Inverted Hammer/Doji op de candle
    op `index`, elk als (naam, richting) met richting 'bullish' of
    'bearish'. Hamer/ster-patronen zijn alleen zinvol als omkeersignaal ná
    een duidelijke trend, dus de trend vlak vóór de candle (ema9[index-1]
    t.o.v. ema21[index-1], dezelfde vergelijking als de basisfactor Trend)
    bepaalt welke kant elk patroon op wijst. Levert een lege lijst op bij
    te weinig voorafgaande candles, of als geen enkel patroon matcht. Een
    candle kan meerdere patronen tegelijk matchen bij grensgevallen (een
    lichaam van 0 met een lange onderstaart is zowel Hammer als Doji) —
    de aanroeper beslist wat daarmee gebeurt."""
    if index < 1 or index >= len(df):
        return []
    ema9_prev = ema9_series[index - 1]
    ema21_prev = ema21_series[index - 1]
    if ema9_prev != ema9_prev or ema21_prev != ema21_prev:  # NaN tijdens EMA-opwarmperiode
        return []

    row = df.iloc[index]
    open_, high, low, close = row["open"], row["high"], row["low"], row["close"]
    body = abs(close - open_)
    upper_shadow = high - max(open_, close)
    lower_shadow = min(open_, close) - low
    candle_range = high - low

    trend_up = ema9_prev > ema21_prev
    trend_down = ema9_prev < ema21_prev

    patterns: list[tuple[str, str]] = []

    if lower_shadow >= body * HAMMER_SHADOW_RATIO and upper_shadow <= body * HAMMER_OPPOSITE_SHADOW_MAX_RATIO:
        if trend_down:
            patterns.append(("Hammer", "bullish"))
        elif trend_up:
            patterns.append(("Hanging Man", "bearish"))

    if upper_shadow >= body * HAMMER_SHADOW_RATIO and lower_shadow <= body * HAMMER_OPPOSITE_SHADOW_MAX_RATIO:
        if trend_up:
            patterns.append(("Shooting Star", "bearish"))
        elif trend_down:
            patterns.append(("Inverted Hammer", "bullish"))

    if body <= candle_range * DOJI_BODY_MAX_RATIO:
        if trend_up:
            patterns.append(("Doji", "bearish"))
        elif trend_down:
            patterns.append(("Doji", "bullish"))

    return patterns
```

- [ ] **Step 4: Run het script opnieuw, bevestig dat de eerste 8 asserties slagen en de rest nog faalt op `AttributeError` voor `detect_star_pattern`**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_candle_pattern_detectors.py
```

- [ ] **Step 5: Breid het testscript uit met Morning Star / Evening Star asserties**

Voeg toe vóór de `print(f"\n=== ...")`-regel:

```python
# --- Morning Star: grote bearish candle, kleine indecisie-candle, grote bullish candle ---
base = [{"open": 100.0, "high": 100.3, "low": 99.7, "close": 100.1} for _ in range(20)]
base.append({"open": 100.0, "high": 100.2, "low": 95.0, "close": 95.5})   # grote bearish candle
base.append({"open": 95.4, "high": 95.6, "low": 95.2, "close": 95.45})    # kleine indecisie-candle
base.append({"open": 95.6, "high": 100.5, "low": 95.5, "close": 100.2})   # grote bullish candle, sluit boven midden 1e candle
df_morning = make_df(base)
result = indicators.detect_star_pattern(df_morning, 22)
check("Morning Star herkend", result == ("Morning Star", "bullish"))

# --- Evening Star: spiegelbeeld ---
base2 = [{"open": 100.0, "high": 100.3, "low": 99.7, "close": 100.1} for _ in range(20)]
base2.append({"open": 95.5, "high": 100.2, "low": 95.3, "close": 100.0})  # grote bullish candle
base2.append({"open": 100.1, "high": 100.3, "low": 99.9, "close": 100.05})
base2.append({"open": 99.9, "high": 100.0, "low": 95.0, "close": 95.3})   # grote bearish candle, sluit onder midden 1e candle
df_evening = make_df(base2)
result = indicators.detect_star_pattern(df_evening, 22)
check("Evening Star herkend", result == ("Evening Star", "bearish"))

# --- Geen sterpatroon bij een gewone reeks ---
flat = [{"open": 100.0 + i * 0.01, "high": 100.2 + i * 0.01, "low": 99.9 + i * 0.01, "close": 100.05 + i * 0.01} for i in range(25)]
df_flat = make_df(flat)
result = indicators.detect_star_pattern(df_flat, 22)
check("geen sterpatroon bij vlakke candles", result is None)

result = indicators.detect_star_pattern(df_morning, 1)
check("index < 2 levert None op", result is None)
```

- [ ] **Step 6: Run het script, bevestig dat het faalt op `AttributeError` voor `detect_star_pattern`**

- [ ] **Step 7: Implementeer `detect_star_pattern` in `app/indicators.py`**

Voeg toe direct na `detect_single_candle_patterns`:

```python
def detect_star_pattern(df: pd.DataFrame, index: int) -> Optional[tuple[str, str]]:
    """Morning Star (bullish) of Evening Star (bearish) op de candles
    index-2, index-1, index. De buitenste twee candles moeten allebei een
    lichaam hebben dat minstens het 20-candle gemiddelde haalt (dezelfde
    soort vergelijking als ATR_TOLERANCE elders in dit bestand) — anders
    is dit geen sterpatroon maar drie gewone candles. None als er geen
    match is, of als index < 2."""
    if index < 2:
        return None

    bodies = (df["close"] - df["open"]).abs()
    history = bodies.iloc[:index - 1]
    if history.empty:
        return None
    body_avg20 = history.tail(20).mean()

    first = df.iloc[index - 2]
    middle = df.iloc[index - 1]
    last = df.iloc[index]

    first_body = abs(first["close"] - first["open"])
    first_range = first["high"] - first["low"]
    middle_range = middle["high"] - middle["low"]
    last_body = abs(last["close"] - last["open"])

    if first_body < body_avg20 or last_body < body_avg20:
        return None
    if first_range > 0 and middle_range > first_range * (DOJI_BODY_MAX_RATIO * 3):
        return None

    first_bearish = first["close"] < first["open"]
    first_bullish = first["close"] > first["open"]
    last_bullish = last["close"] > last["open"]
    last_bearish = last["close"] < last["open"]
    first_midpoint = (first["open"] + first["close"]) / 2

    if first_bearish and last_bullish and last["close"] > first_midpoint:
        return ("Morning Star", "bullish")
    if first_bullish and last_bearish and last["close"] < first_midpoint:
        return ("Evening Star", "bearish")
    return None
```

Voeg ook `from typing import Optional` toe aan de imports bovenaan
`app/indicators.py` (na `from dataclasses import dataclass`).

- [ ] **Step 8: Run het volledige script, bevestig dat alle asserties slagen**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_candle_pattern_detectors.py
```

Verwacht: `=== 12 geslaagd, 0 gefaald ===`.

- [ ] **Step 9: Commit**

```bash
git add app/indicators.py
git commit -m "Nieuwe candlestick-patroondetectoren: hamer, ster, doji

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q"
```

---

### Task 2: `check_candle_pattern_extended` en `scan_candle_patterns`

**Files:**
- Modify: `app/indicators.py` (nieuwe functies direct na `detect_star_pattern`)
- Test: `<SCRATCHPAD>/test_candle_pattern_combined.py`

**Interfaces:**
- Consumes: `detect_single_candle_patterns`, `detect_star_pattern` (Task 1), bestaande `check_candle_pattern` (engulfing, ongewijzigd).
- Produces:
  - `check_candle_pattern_extended(df: pd.DataFrame, direction: str, ema9_series: list[float], ema21_series: list[float]) -> tuple[str, bool, str]` — gebruikt door Task 3.
  - `scan_candle_patterns(df: pd.DataFrame, ema9_series: list[float], ema21_series: list[float], lookback: int = DEFAULT_PATTERN_SCAN_LOOKBACK) -> list[dict]` (elk element `{"index": int, "pattern": str, "direction": str}`) — gebruikt door Task 4 (`/api/candles`).

- [ ] **Step 1: Schrijf het testscript met falende asserties**

Maak `<SCRATCHPAD>/test_candle_pattern_combined.py`:

```python
import sys
sys.path.insert(0, "/home/user/Trade")

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


def make_df(rows):
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"])


# Downtrend gevolgd door een hamer op de laatste candle.
rows = [{"open": 100 - i * 0.5, "high": 100 - i * 0.5 + 0.2, "low": 100 - i * 0.5 - 0.2, "close": 100 - i * 0.5 - 0.1} for i in range(20)]
rows.append({"open": 90.5, "high": 90.65, "low": 85.0, "close": 90.6})
df = make_df(rows)
ema9 = [90.0] * 19 + [88.0, 87.0]
ema21 = [92.0] * 19 + [92.0, 91.0]

name, ok, detail = indicators.check_candle_pattern_extended(df, "long", ema9, ema21)
check("Hammer telt mee voor long via check_candle_pattern_extended", ok and "Hammer" in detail)
check("factornaam blijft 'Candlepatroon'", name == "Candlepatroon")

name, ok, detail = indicators.check_candle_pattern_extended(df, "short", ema9, ema21)
check("Hammer telt niet mee voor short (verkeerde richting)", not ok)

# Geen enkel patroon: gewone candles.
flat = [{"open": 100.0 + i * 0.01, "high": 100.2 + i * 0.01, "low": 99.9 + i * 0.01, "close": 100.1 + i * 0.01} for i in range(25)]
df_flat = make_df(flat)
ema9_flat = [100.0] * 25
ema21_flat = [100.0] * 25
name, ok, detail = indicators.check_candle_pattern_extended(df_flat, "long", ema9_flat, ema21_flat)
check("geen patroon: factor faalt met duidelijke reden", not ok and "candlestick-patroon" in detail)

# scan_candle_patterns vindt de hamer terug in het venster.
found = indicators.scan_candle_patterns(df, ema9, ema21, lookback=100)
check("scan_candle_patterns vindt de Hammer op index 20", any(p["index"] == 20 and p["pattern"] == "Hammer" for p in found))

# lookback beperkt het venster.
found_small = indicators.scan_candle_patterns(df, ema9, ema21, lookback=1)
check("kleine lookback laat oudere candles buiten beschouwing (alleen laatste candle gescand)", len(found_small) <= 1 or all(p["index"] == 20 for p in found_small))

print(f"\n=== {passed} geslaagd, {failed} gefaald ===")
sys.exit(1 if failed else 0)
```

- [ ] **Step 2: Run het script, bevestig `AttributeError`**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_candle_pattern_combined.py
```

- [ ] **Step 3: Implementeer beide functies in `app/indicators.py`**

Voeg toe direct na `detect_star_pattern`:

```python
DEFAULT_PATTERN_SCAN_LOOKBACK = 100


def check_candle_pattern_extended(
    df: pd.DataFrame, direction: str, ema9_series: list[float], ema21_series: list[float],
) -> tuple[str, bool, str]:
    """Combineert de bestaande engulfing-check met de vijf nieuwe
    candlestick-patronen tot dezelfde factor 'Candlepatroon': matcht er
    minstens één patroon in de kant van `direction` op de laatste candle,
    dan is de factor gehaald. Vervangt de aanroep van check_candle_pattern
    in signal_processor.compute_advanced_extra_factors (check_candle_pattern
    zelf blijft ongewijzigd bestaan)."""
    direction = direction.lower()
    last_index = len(df) - 1

    _, engulfing_ok, engulfing_detail = check_candle_pattern(df, direction)
    if engulfing_ok:
        return ("Candlepatroon", True, engulfing_detail)

    matches = detect_single_candle_patterns(df, last_index, ema9_series, ema21_series)
    star = detect_star_pattern(df, last_index)
    if star:
        matches.append(star)

    wants_bullish = direction == "long"
    for name, pattern_direction in matches:
        if (pattern_direction == "bullish") == wants_bullish:
            return ("Candlepatroon", True, f"{name} op de signaal-candle")

    return (
        "Candlepatroon", False,
        "geen candlestick-patroon (engulfing, hamer, ster, doji) in de juiste richting op de signaal-candle",
    )


def scan_candle_patterns(
    df: pd.DataFrame, ema9_series: list[float], ema21_series: list[float],
    lookback: int = DEFAULT_PATTERN_SCAN_LOOKBACK,
) -> list[dict]:
    """Alle single-candle- en sterpatronen over de laatste `lookback`
    candles, ELK gevonden patroon (niet gefilterd op een verwachte
    richting — dit is voor weergave op de grafiek, niet voor de score).
    Elk element: {"index": int, "pattern": str, "direction": "bullish"|"bearish"}."""
    start = max(0, len(df) - lookback)
    found: list[dict] = []
    for i in range(start, len(df)):
        for name, pattern_direction in detect_single_candle_patterns(df, i, ema9_series, ema21_series):
            found.append({"index": i, "pattern": name, "direction": pattern_direction})
        star = detect_star_pattern(df, i)
        if star:
            found.append({"index": i, "pattern": star[0], "direction": star[1]})
    return found
```

- [ ] **Step 4: Run het script, bevestig dat alle asserties slagen**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_candle_pattern_combined.py
```

Verwacht: `=== 6 geslaagd, 0 gefaald ===`.

- [ ] **Step 5: Commit**

```bash
git add app/indicators.py
git commit -m "check_candle_pattern_extended + scan_candle_patterns

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q"
```

---

### Task 3: Koppeling in `signal_processor.py`

**Files:**
- Modify: `app/signal_processor.py:540-544` (binnen `compute_advanced_extra_factors`)
- Test: `<SCRATCHPAD>/test_candle_pattern_pipeline.py`

**Interfaces:**
- Consumes: `indicators.check_candle_pattern_extended`, `indicators.ema_series` (beide al bestaand/Task 2).
- Produces: geen nieuwe interface — vervangt alleen de aanroep binnen een bestaande functie. Het gedrag dat Task 4 (backtest) en de rest van de pipeline zien: factor "Candlepatroon" in de reason-breakdown van elk signaal met `ENABLE_ADVANCED_FACTORS=true`.

- [ ] **Step 1: Lees de huidige exacte context**

```bash
sed -n '535,546p' /home/user/Trade/app/signal_processor.py
```

Verwacht die 5 regels exact zoals hieronder (als de nummering is
opgeschoven door eerdere wijzigingen, zoek op de tekst
`check_candle_pattern` in plaats van het regelnummer):

```python
    try:
        factors.append(indicators.check_candle_pattern(df, direction))
    except Exception:
        logger.exception("Candlepatroon voor %s kon niet berekend worden", coin)
        factors.append(("Candlepatroon", False, "kon niet berekend worden, telt als niet bevestigd"))
```

- [ ] **Step 2: Vervang de aanroep**

```python
    try:
        ema9_series, ema21_series = indicators.ema_series(df)
        factors.append(indicators.check_candle_pattern_extended(df, direction, ema9_series, ema21_series))
    except Exception:
        logger.exception("Candlepatroon voor %s kon niet berekend worden", coin)
        factors.append(("Candlepatroon", False, "kon niet berekend worden, telt als niet bevestigd"))
```

- [ ] **Step 3: Schrijf en run de integratietest**

Maak `<SCRATCHPAD>/test_candle_pattern_pipeline.py`, naar het patroon van
het eerder deze sessie gebruikte `test_advanced_factors_integration.py`
(zelfde soort setup: tijdelijke DB, `ENABLE_ADVANCED_FACTORS=true`,
gemockte `exchange.fetch_ohlcv` voor 4h/1h/1d/BTC, `coinlist.ensure_coin_tracked`
gemockt op `(True, False)`):

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
os.environ["JWT_SECRET"] = "test-secret-candle-pattern-pipeline-01234567890"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"
os.environ["ENABLE_ADVANCED_FACTORS"] = "true"

from app import config
config.DATABASE_PATH = db_path
config.ENABLE_ADVANCED_FACTORS = True

from app import db, repo, security, signal_processor, coinlist
from app.anthropic_interpret import Interpretation
from app.db import session as db_session

import pandas as pd
import numpy as np

db.init_db()
repo.create_user("candlepipelineuser", security.hash_password("testpass123"), 10000.0, 1.0, "1")
repo.add_coin_if_new("SUIUSDT", "spot")

# Downtrend candles die eindigen in een duidelijke hamer, zodat de nieuwe
# candlestick-patronen (niet alleen engulfing) de factor kunnen halen.
n = 80
closes = [0.90 - i * 0.003 for i in range(n - 1)] + [0.643]
opens = [c + 0.003 for c in closes[:-1]] + [0.638]
opens[-1] = 0.638
closes[-1] = 0.643
highs = [max(o, c) + 0.001 for o, c in zip(opens, closes)]
highs[-1] = 0.645
lows = [min(o, c) - 0.001 for o, c in zip(opens, closes)]
lows[-1] = 0.60  # lange onderstaart -> Hammer
volumes = [500000.0] * n
fake_4h = pd.DataFrame({"open": opens, "high": highs, "low": lows, "close": closes, "volume": volumes})

fake_1h = pd.DataFrame({
    "open": np.linspace(0.62, 0.65, 60), "high": np.linspace(0.63, 0.66, 60),
    "low": np.linspace(0.61, 0.64, 60), "close": np.linspace(0.62, 0.65, 60),
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
    row = conn.execute("SELECT reason FROM signals ORDER BY id DESC LIMIT 1").fetchone()

assert row is not None, "geen signal-rij aangemaakt"
reason = row["reason"]
print(f"reason: {reason}")
assert "Candlepatroon" in reason, f"factor 'Candlepatroon' ontbreekt: {reason}"
print("OK: 'Candlepatroon' zit in de breakdown, geen crash in de volledige pipeline")
```

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_candle_pattern_pipeline.py
```

Verwacht: script eindigt met de laatste `print`-regel, geen traceback
vóór die regel (de Telegram-stap erna mag wél een `NetworkError` geven —
zie CLAUDE.md, de sandbox heeft geen netwerktoegang; dat gebeurt na de
assert en is geen testfout).

- [ ] **Step 4: Commit**

```bash
git add app/signal_processor.py
git commit -m "Bedraad check_candle_pattern_extended in de signaal-pipeline

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q"
```

---

### Task 4: `/api/candles/{symbol}` route

**Files:**
- Modify: `web/main.py:1379-1398` (route `api_candles`)
- Test: `<SCRATCHPAD>/test_api_candles_patterns.py`

**Interfaces:**
- Consumes: `indicators.scan_candle_patterns` (Task 2).
- Produces: response-veld `patterns: list[{"time": int, "pattern": str, "direction": str}]`, gebruikt door Task 5 (`coin.js`).

- [ ] **Step 1: Lees de huidige route**

```bash
sed -n '1379,1398p' /home/user/Trade/web/main.py
```

- [ ] **Step 2: Schrijf de falende test**

Maak `<SCRATCHPAD>/test_api_candles_patterns.py`, naar het patroon van
het eerder deze sessie gebruikte `test_oefen_preview.py` (tijdelijke DB,
`TestClient`, sessie-cookie, gemockte `exchange.fetch_ohlcv`):

```python
import os, sys, tempfile
sys.path.insert(0, "/home/user/Trade")
sys.path.insert(0, "/home/user/Trade/web")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd); os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-api-candles-patterns-0123456789012"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path
from app import db, repo, security

db.init_db()
uid = repo.create_user("apicandlesuser", security.hash_password("testpass123"), 1000.0, 1.0, "1")

import main as web_main
from fastapi.testclient import TestClient
from unittest.mock import patch
import pandas as pd

client = TestClient(web_main.app)
token = security.create_session_token(uid)
client.cookies.set("session", token)

n = 60
closes = [0.90 - i * 0.003 for i in range(n - 1)] + [0.643]
opens = [c + 0.003 for c in closes[:-1]] + [0.638]
highs = [max(o, c) + 0.001 for o, c in zip(opens, closes)]
highs[-1] = 0.645
lows = [min(o, c) - 0.001 for o, c in zip(opens, closes)]
lows[-1] = 0.60
timestamps = pd.date_range("2026-01-01", periods=n, freq="4h", tz="UTC")
fake_df = pd.DataFrame({"timestamp": timestamps, "open": opens, "high": highs, "low": lows, "close": closes, "volume": [500000.0] * n})

with patch("main.exchange.fetch_ohlcv", return_value=fake_df):
    resp = client.get("/api/candles/SUIUSDT")
assert resp.status_code == 200, resp.text
data = resp.json()
assert "patterns" in data, f"'patterns' ontbreekt in de response: {list(data.keys())}"
assert any(p["pattern"] == "Hammer" for p in data["patterns"]), f"geen Hammer gevonden: {data['patterns']}"
for p in data["patterns"]:
    assert set(p.keys()) == {"time", "pattern", "direction"}, p
    assert p["direction"] in ("bullish", "bearish")
print(f"OK: {len(data['patterns'])} patronen teruggegeven, inclusief de verwachte Hammer")
```

- [ ] **Step 3: Run de test, bevestig `KeyError`/`AssertionError` op `'patterns'`**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_api_candles_patterns.py
```

- [ ] **Step 4: Implementeer het nieuwe veld**

Vervang de huidige `return`-regel en voeg de scan ervoor toe:

```python
@app.get("/api/candles/{symbol}")
async def api_candles(symbol: str, user: dict = Depends(require_login)):
    df = await asyncio.to_thread(exchange.fetch_ohlcv, symbol.upper(), config.TIMEFRAME, 200)
    ema9, ema21 = indicators.ema_series(df)

    candles = [
        {
            "time": int(row.timestamp.timestamp()),
            "open": row.open, "high": row.high, "low": row.low, "close": row.close,
        }
        for row in df.itertuples()
    ]
    ema9_series = [
        {"time": c["time"], "value": v} for c, v in zip(candles, ema9) if v == v
    ]
    ema21_series = [
        {"time": c["time"], "value": v} for c, v in zip(candles, ema21) if v == v
    ]
    pattern_matches = indicators.scan_candle_patterns(df, ema9, ema21)
    patterns = [
        {"time": candles[p["index"]]["time"], "pattern": p["pattern"], "direction": p["direction"]}
        for p in pattern_matches
    ]

    return {"candles": candles, "ema9": ema9_series, "ema21": ema21_series, "patterns": patterns}
```

- [ ] **Step 5: Run de test, bevestig dat hij slaagt**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_api_candles_patterns.py
```

- [ ] **Step 6: Commit**

```bash
git add web/main.py
git commit -m "/api/candles: patterns-veld met herkende candlestick-patronen

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q"
```

---

### Task 5: Grafiek-weergave (`coin.js` + `coin.html`)

**Files:**
- Modify: `web/static/coin.js:30-37` (comment + `narrativeMarkers`-declaratie), `web/static/coin.js:159-174` (marker-opbouw), nieuwe blok voor de patroon-lijst direct erna
- Modify: `web/templates/coin.html:169` (`--i: 3` → `--i: 4`), `:213` (`--i: 4` → `--i: 5`), `:226` (`--i: 5` → `--i: 6`), nieuw `<details>`-blok met `--i: 3` vóór de bestaande `--i: 169`-regel (Bron niveaus)
- Test: handmatige verificatie (zie Step 5) — dit is grafiek-JS, geen server-route om te unit-testen; `<SCRATCHPAD>/test_api_candles_patterns.py` uit Task 4 bevestigt al dat de data-laag klopt.

**Interfaces:**
- Consumes: `data.patterns` uit `/api/candles/{symbol}` (Task 4), bestaande `narrativeMarkers`-variabele en `data.candles`.
- Produces: geen nieuwe interface voor latere tasks — dit is het laatste zichtbare stuk van dit deelproject.

- [ ] **Step 1: Pas het commentaar en de scope van `narrativeMarkers` aan (`web/static/coin.js:30-37`)**

Vervang:

```javascript
  // Kleine gekleurde puntjes op het moment van elke lange-termijn
  // narrative-update, zodat een langere geschiedenis van berichten over
  // deze coin ook op de prijsgrafiek zelf te volgen is. Apart bijgehouden
  // (niet steeds opnieuw uit candleSeries gelezen) omdat stopDrawing()
  // verderop candleSeries.setMarkers([]) aanroept om zijn eigen tijdelijke
  // teken-marker weg te halen — die moet deze markers herstellen, niet
  // leegmaken.
  let narrativeMarkers = [];
```

door:

```javascript
  // Alle markers die permanent op de grafiek horen te staan: narrative-
  // updates ÉN herkende candlestick-patronen samen in één array. Apart
  // bijgehouden (niet steeds opnieuw uit candleSeries gelezen) omdat
  // stopDrawing() verderop candleSeries.setMarkers([]) aanroept om zijn
  // eigen tijdelijke teken-marker weg te halen — die moet deze markers
  // herstellen, niet leegmaken. setMarkers() VERVANGT de volledige
  // markerlijst bij elke aanroep, dus narrative- en patroon-markers
  // moeten altijd samen in deze ene array staan, nooit in aparte
  // setMarkers()-aanroepen.
  let narrativeMarkers = [];
```

- [ ] **Step 2: Voeg patroon-markers en de patroon-lijst toe (`web/static/coin.js:159-174`)**

Vervang:

```javascript
      if (narrativeUpdates.length && data.candles.length) {
        // LightweightCharts vereist markers oplopend gesorteerd op tijd;
        // narrativeUpdates komt binnen in narrative-volgorde (nieuwste
        // narrative eerst), niet chronologisch, dus zonder deze sort
        // vallen markers afhankelijk van zoom/scroll stilzwijgend weg.
        narrativeMarkers = narrativeUpdates
          .map((u) => ({
            time: nearestCandleTime(data.candles, Math.floor(new Date(u.received_at).getTime() / 1000)),
            position: "aboveBar",
            color: u.direction === "long" ? "#33d69f" : "#f2685c",
            shape: "circle",
            text: u.direction === "long" ? "L" : "S",
          }))
          .sort((a, b) => a.time - b.time);
        candleSeries.setMarkers(narrativeMarkers);
      }
```

door:

```javascript
      if (narrativeUpdates.length && data.candles.length) {
        // LightweightCharts vereist markers oplopend gesorteerd op tijd;
        // narrativeUpdates komt binnen in narrative-volgorde (nieuwste
        // narrative eerst), niet chronologisch, dus zonder deze sort
        // vallen markers afhankelijk van zoom/scroll stilzwijgend weg.
        narrativeMarkers = narrativeUpdates
          .map((u) => ({
            time: nearestCandleTime(data.candles, Math.floor(new Date(u.received_at).getTime() / 1000)),
            position: "aboveBar",
            color: u.direction === "long" ? "#33d69f" : "#f2685c",
            shape: "circle",
            text: u.direction === "long" ? "L" : "S",
          }))
          .sort((a, b) => a.time - b.time);
      }

      // Patroon-markers uit dezelfde /api/candles respons, samengevoegd
      // met narrativeMarkers vóór de ENE setMarkers()-aanroep hieronder
      // (zie de comment bij de declaratie van narrativeMarkers hierboven).
      const patternMarkers = (data.patterns || []).map((p) => ({
        time: p.time,
        position: p.direction === "bullish" ? "belowBar" : "aboveBar",
        color: p.direction === "bullish" ? "#33d69f" : "#f2685c",
        shape: "circle",
        text: "",
      }));
      narrativeMarkers = [...narrativeMarkers, ...patternMarkers].sort((a, b) => a.time - b.time);
      if (narrativeMarkers.length) {
        candleSeries.setMarkers(narrativeMarkers);
      }

      const patternListEl = document.getElementById("pattern-list");
      if (patternListEl) {
        if (data.patterns && data.patterns.length) {
          const sorted = [...data.patterns].sort((a, b) => b.time - a.time).slice(0, 10);
          patternListEl.innerHTML = sorted.map((p) => {
            const date = new Date(p.time * 1000).toLocaleDateString("nl-NL", { day: "2-digit", month: "2-digit", year: "numeric" });
            const cls = p.direction === "bullish" ? "pos" : "neg";
            return `<p class="muted" style="margin: 4px 0; font-size: 12.5px;"><span class="${cls}">${p.pattern}</span> · ${date}</p>`;
          }).join("");
        } else {
          patternListEl.innerHTML = '<p class="muted">Geen patronen herkend in de laatste 100 candles.</p>';
        }
      }
```

`stopDrawing()` (verderop in het bestand, roept `candleSeries.setMarkers(narrativeMarkers)`
aan) hoeft niet aangepast te worden: `narrativeMarkers` bevat na deze
wijziging altijd de volledige, samengevoegde set.

- [ ] **Step 3: Voeg de nieuwe sectie toe aan `web/templates/coin.html`**

Voeg vóór de bestaande regel `<details class="stats-collapse js-accordion" style="--i: 3">`
(regel 169, "Bron niveaus en screenshots") dit nieuwe blok toe:

```html
<details class="stats-collapse js-accordion" style="--i: 3">
  <summary class="stats-summary">
    <svg class="h2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 3v18h18"/><path d="m19 9-5 5-4-4-3 3"/></svg>
    <span>Herkende patronen</span>
    <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6,9 12,15 18,9"/></svg>
  </summary>
  <p class="muted" style="margin: 0 0 10px; font-size: 12px;">Candlestick-patronen die HesPulse zelf herkent in de laatste 100 candles op de grafiek hierboven, los van wat de community meldt.</p>
  <div id="pattern-list"><p class="muted">Laden...</p></div>
</details>
```

- [ ] **Step 4: Schuif de `--i`-waarden van de bestaande blokken eronder één op**

- `<details class="stats-collapse js-accordion" style="--i: 3">` (Bron niveaus, oorspronkelijk regel 169) → `--i: 4`
- `<details class="stats-collapse js-accordion" style="--i: 4">` (Notitie bij {{ symbol }}, oorspronkelijk regel 213) → `--i: 5`
- `<details class="stats-collapse js-accordion" style="--i: 5">` (Oefenen met deze coin, oorspronkelijk regel 226) → `--i: 6`

Controleer met `grep -n "stats-collapse js-accordion" web/templates/coin.html`
dat er na deze wijziging exact één blok per `--i`-waarde 2 (of 2 tweemaal,
conditioneel), 3, 4, 5, 6 is, en geen dubbele of overgeslagen waarde.

- [ ] **Step 5: Handmatige verificatie met Playwright**

Er is geen geautomatiseerde manier om canvas-rendering (de markers zelf)
te controleren; volg de aanpak die dit project al gebruikt voor
UI-wijzigingen (zie CLAUDE.md, "Commands"): start de server tegen een
scratch-DB, seed een coin met candle-historie die een bekend patroon
bevat, en maak een screenshot.

```bash
source /home/user/Trade/.venv/bin/activate
cd /home/user/Trade
DATABASE_PATH=<SCRATCHPAD>/verify_patterns.db JWT_SECRET=verify-secret-0123456789012345678 TELEGRAM_BOT_TOKEN=dummy python3 -c "
from app import db, repo, security
db.init_db()
repo.create_user('verifyuser', security.hash_password('testpass123'), 1000.0, 1.0, '1')
repo.add_coin_if_new('SUIUSDT', 'spot')
"
DATABASE_PATH=<SCRATCHPAD>/verify_patterns.db JWT_SECRET=verify-secret-0123456789012345678 TELEGRAM_BOT_TOKEN=dummy uvicorn web.main:app --port 8420 &
sleep 2
```

Log in via Playwright met de aangemaakte gebruiker, mock of laat
`/api/candles/SUIUSDT` de echte Binance-call maken (in de sandbox lukt dat
niet — netwerktoegang ontbreekt, zie CLAUDE.md; op een omgeving met
netwerktoegang, of via `--project-dir`-mock, wél), navigeer naar
`/coins/SUIUSDT`, en maak een screenshot. Controleer visueel: staan er
groene/rode cirkels op de candles, verschijnt de "Herkende patronen"-sectie
met een gevulde lijst (niet "Laden..." of de lege staat), en staan de
overige secties (Bron niveaus, Notitie, Oefenen) nog in de juiste volgorde
met de bijgewerkte `--i`-waarden. Sluit de server af na de check:

```bash
kill %1
```

- [ ] **Step 6: Commit**

```bash
git add web/static/coin.js web/templates/coin.html
git commit -m "Grafiek: markers + lijst voor herkende candlestick-patronen

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q"
```

---

### Task 6: `scripts/backtest_factors.py` en `/uitleg`

**Files:**
- Modify: `scripts/backtest_factors.py:70-71` (aanroep binnen `evaluate_signal`)
- Modify: `web/templates/uitleg.html:196-200` (Candlepatroon-kaart)
- Test: handmatige inspectie (geen netwerktoegang in de sandbox voor `backtest_factors.py` zelf) + `<SCRATCHPAD>/test_uitleg_candlepatroon_card.py` voor de template

**Interfaces:**
- Consumes: `indicators.check_candle_pattern_extended`, `indicators.ema_series` (Task 2/3).
- Produces: geen nieuwe interface — laatste inhoudelijke stap van dit deelproject.

- [ ] **Step 1: Werk `scripts/backtest_factors.py` bij**

Vervang (regel 70-71):

```python
        _, candle_ok, _ = indicators.check_candle_pattern(df, direction)
        results["Candlepatroon"] = candle_ok
```

door:

```python
        ema9_hist, ema21_hist = indicators.ema_series(df)
        _, candle_ok, _ = indicators.check_candle_pattern_extended(df, direction, ema9_hist, ema21_hist)
        results["Candlepatroon"] = candle_ok
```

- [ ] **Step 2: Controleer dat het script nog importeert zonder fouten**

```bash
source /home/user/Trade/.venv/bin/activate && python3 -c "import scripts.backtest_factors"
```

Verwacht: geen output, geen traceback (het script zelf runnen vereist
live Binance-toegang, niet beschikbaar in de sandbox — zie CLAUDE.md).

- [ ] **Step 3: Werk de Candlepatroon-kaart in `web/templates/uitleg.html` bij**

Vervang (regel 196-200):

```html
    <div class="factor factor-preview">
      <h3>Candlepatroon</h3>
      <p>Staat er op de signaal-candle zelf een bullish of bearish
      engulfing: slokt die candle de vorige volledig op in de richting van
      het signaal?</p>
    </div>
```

door:

```html
    <div class="factor factor-preview">
      <h3>Candlepatroon</h3>
      <p>Staat er op de signaal-candle zelf een herkenbaar patroon:
      engulfing, Hammer/Hanging Man, Shooting Star/Inverted Hammer, Doji,
      of Morning/Evening Star? Eén match in de juiste richting is genoeg.</p>
    </div>
```

- [ ] **Step 4: Schrijf en run een test die de bijgewerkte kaart controleert**

Maak `<SCRATCHPAD>/test_uitleg_candlepatroon_card.py`, naar het patroon
van het eerder deze sessie gebruikte `test_uitleg_page_factors.py`:

```python
import os, sys, tempfile
sys.path.insert(0, "/home/user/Trade")
sys.path.insert(0, "/home/user/Trade/web")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd); os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-uitleg-candlepatroon-01234567890123"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path
from app import db, repo, security

db.init_db()
uid = repo.create_user("uitlegcandletester", security.hash_password("testpass123"), 1000.0, 1.0, "1")

import main as web_main
from fastapi.testclient import TestClient

client = TestClient(web_main.app)
token = security.create_session_token(uid)
client.cookies.set("session", token)

resp = client.get("/uitleg")
assert resp.status_code == 200, resp.text
html = resp.text
for expected in ["Hammer/Hanging Man", "Shooting Star/Inverted Hammer", "Morning/Evening Star"]:
    assert expected in html, f"'{expected}' ontbreekt op de uitleg-pagina"
    print(f"OK: '{expected}' staat op de pagina")
print("\nuitleg-pagina toont de bijgewerkte Candlepatroon-kaart.")
```

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_uitleg_candlepatroon_card.py
```

- [ ] **Step 5: Commit**

```bash
git add scripts/backtest_factors.py web/templates/uitleg.html
git commit -m "Backtest + uitleg-pagina: bredere candlestick-patroonset

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q"
```

---

### Task 7: Volledige regressie en push

**Files:** geen wijzigingen — alleen verificatie.

**Interfaces:** geen — dit is de afsluitende controle van alle vorige tasks samen.

- [ ] **Step 1: Draai alle nieuwe testscripts uit dit plan opnieuw achter elkaar**

```bash
source /home/user/Trade/.venv/bin/activate
for f in test_candle_pattern_detectors.py test_candle_pattern_combined.py \
         test_candle_pattern_pipeline.py test_api_candles_patterns.py \
         test_uitleg_candlepatroon_card.py; do
  echo "=== $f ==="
  python3 <SCRATCHPAD>/$f || echo "FAILED: $f"
done
```

Verwacht: elk script eindigt met zijn eigen "geslaagd"-regel, geen
`FAILED`-regel in de output.

- [ ] **Step 2: Draai de bestaande regressietests die deze sessie eerder al voor de factorenset zijn geschreven**

```bash
python3 <SCRATCHPAD>/test_factor_refinements.py
python3 <SCRATCHPAD>/test_advanced_factors_integration.py
python3 <SCRATCHPAD>/test_uitleg_page_factors.py
```

Deze bevestigen dat de eerdere factor-uitbreiding (ADX-richting,
Volume-percentiel, RSI 1u) door de wijzigingen in dit plan niet gebroken
is — `check_candle_pattern_extended` raakt alleen de Candlepatroon-factor
zelf, niet de andere negen.

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
git log --oneline -8
git push -u origin claude/crypto-day-trading-alerts-5p8w6v
```

Verwacht: `git status --short` toont geen wijzigingen (alles uit Task 1-6
is al gecommit), de laatste 6-7 commits tonen de tasks uit dit plan, en de
push slaagt.
