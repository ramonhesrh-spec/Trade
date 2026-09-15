# Trendlijn-uitbraak-en-terugtest Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HesPulse herkent zelf een diagonale trendlijn (steun of
weerstand) in de candle-geschiedenis, meldt het als de lijn op
closing-prijs doorbroken is en de prijs nu weer teruggetest wordt, in
een eigen Telegram-kanaal naast optie C, en tekent de lijn op de grafiek.

**Architecture:** Pivot-detectie wordt uit `detect_sr_zones` getrokken
naar een gedeelde helper `_find_pivots`, hergebruikt door de nieuwe
`detect_trendlines` (past een lijn door pivots via een simpele
regressie-met-inliers, net als een minimalistische RANSAC).
`find_trendline_breakout_retest` volgt exact het crossing-detectiepatroon
van het bestaande `find_breakout_retest`, nu tegen een bewegende
lijnwaarde. `market_scanner.py` roept dit aan naast de bestaande
`_check_breakout_retest`, met een eigen dedup-kolom en Telegram-bericht.
`/api/candles` en `coin.js` tekenen de lijn als losse lightweight-charts
lijnserie.

**Tech Stack:** Python 3.11, pandas, FastAPI, aiogram/python-telegram-bot
(zie `app/telegram_notify.py`), vanilla JS, TradingView Lightweight
Charts v4.

**Spec:** `docs/superpowers/specs/2026-09-15-trendlijn-uitbraak-design.md`

## Global Constraints

- `TRENDLINE_MIN_TOUCHES = 3` (spec, Sectie 2) — strenger dan
  `SR_ZONE_MIN_TOUCHES = 2` voor horizontale zones, bewuste keuze.
- `TRENDLINE_FIT_TOLERANCE_PCT = 0.01` (spec, Sectie 2).
- `TRENDLINE_MIN_SLOPE_ATR_MULTIPLE = 0.05` (spec, Sectie 2) — voorkomt
  dat een bijna vlakke lijn hetzelfde vindt als `detect_sr_zones`.
- `TRENDLINE_DEDUP_ATR_MULTIPLE = 1.0` (spec, Sectie 3) — zelfde
  ATR-marge-patroon als de bestaande optie-C-dedup-fix van vandaag.
- `BREAKOUT_RETEST_TOLERANCE_ATR_MULTIPLE` wordt hergebruikt ongewijzigd
  uit de bestaande code, geen nieuwe tolerantie-constante voor de
  terugtest zelf (spec, Sectie 2).
- Geen nieuwe score-factor: dit blijft een los Telegram-kanaal zonder
  invloed op `confirms_direction`/`basic_factors` (spec, Niet-doelen).
- Geen volledige driehoekherkenning: één diagonale lijn per melding,
  steun óf weerstand (spec, Niet-doelen).
- Geen wijziging aan `detect_sr_zones`'s gedrag naar buiten toe — alleen
  zijn interne pivot-loop verhuist naar `_find_pivots`, de output blijft
  identiek (spec, Sectie 1).
- Dit project heeft geen pytest-suite en geen testmap in de repo (zie
  CLAUDE.md). Elke test in dit plan is een losstaand, wegwerpbaar script
  in de sessie-scratchpad-map, gedraaid met `python3 <pad>` — niet
  gecommit naar de repo. Vervang `<SCRATCHPAD>` hieronder door het pad
  dat je systeemprompt als scratchpad-directory noemt.
- Geen live Binance/internet-toegang in de ontwikkelomgeving. Tests
  draaien tegen synthetische `pd.DataFrame`-candles of een scratch-SQLite
  DB (`DATABASE_PATH=<scratchpad>/test.db`), nooit tegen een echte
  exchange-call — die wordt gemockt (zie Task 5).

---

### Task 1: Gedeelde pivot-detectie (`app/indicators.py`)

**Files:**
- Modify: `app/indicators.py` (net vóór `detect_sr_zones`, rond regel 578)
- Test: `<SCRATCHPAD>/test_pivots.py`

**Interfaces:**
- Consumes: niets nieuws, alleen pandas (al geïmporteerd).
- Produces:
  - `Pivot` (dataclass: `index: int`, `price: float`, `kind: str`)
  - `_find_pivots(window: pd.DataFrame) -> list[Pivot]` — gebruikt door
    `detect_sr_zones` (Task 1 zelf) en door Task 2's `detect_trendlines`.

- [ ] **Step 1: Schrijf het testscript met de eerste falende asserties**

Maak `<SCRATCHPAD>/test_pivots.py`:

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


# --- _find_pivots: een candle die 3 aan elke kant hoger/lager is, is een pivot ---
random.seed(7)
rows = []
for i in range(30):
    if i == 15:
        high, low = 120.0, 118.0  # duidelijke piek
    else:
        high = 100.0 + random.uniform(0, 2)
        low = high - random.uniform(1, 2)
    rows.append({"open": low, "high": high, "low": low, "close": (high + low) / 2})
df = pd.DataFrame(rows)

pivots = indicators._find_pivots(df)
check("index 15 wordt herkend als pivot-high", any(p.index == 15 and p.kind == "high" and p.price == 120.0 for p in pivots))
check("alle pivots hebben een geldige kind ('high' of 'low')", all(p.kind in ("high", "low") for p in pivots))

# --- _find_pivots: te weinig candles geeft geen crash, lege lijst ---
tiny_df = pd.DataFrame({"open": [1.0, 1.0], "high": [1.1, 1.1], "low": [0.9, 0.9], "close": [1.0, 1.0]})
check("te weinig candles geeft lege lijst, geen crash", indicators._find_pivots(tiny_df) == [])

# --- detect_sr_zones blijft ongewijzigd werken na de refactor (regressie) ---
touches_at = {10, 40, 70}
rows2 = []
for i in range(90):
    if i in touches_at:
        low = 100.0 + random.uniform(-0.05, 0.05)
        high = low + random.uniform(2, 4)
    else:
        low = 103.0 + random.uniform(0, 3)
        high = low + random.uniform(1, 3)
    rows2.append({"open": low + 0.5, "high": high, "low": low, "close": low + 1.0})
df2 = pd.DataFrame(rows2)
zones = indicators.detect_sr_zones(df2)
check("detect_sr_zones vindt na de refactor nog steeds de zone rond 100.0 met 3 touches",
      any(z.price_low <= 100.05 and z.price_high >= 99.95 and z.touches == 3 for z in zones))

print(f"\n=== {passed} geslaagd, {failed} gefaald ===")
sys.exit(1 if failed else 0)
```

- [ ] **Step 2: Run het script, bevestig `AttributeError: module 'app.indicators' has no attribute '_find_pivots'`**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_pivots.py
```

- [ ] **Step 3: Implementeer `Pivot` en `_find_pivots`, herschrijf `detect_sr_zones` om hem te gebruiken**

In `app/indicators.py`, vlak vóór de bestaande `@dataclass class SRZone:`
(rond regel 578), voeg toe:

```python
@dataclass
class Pivot:
    index: int
    price: float
    kind: str  # "high" of "low"


def _find_pivots(window: pd.DataFrame) -> list[Pivot]:
    """Lokale keerpunten in een candle-venster: een candle die hoger/lager
    is dan SR_PIVOT_WINDOW candles aan beide kanten. Gedeeld tussen
    detect_sr_zones (clustert op prijs, index niet nodig) en
    detect_trendlines (past een lijn door index+prijs), zodat de
    pivot-definitie één keer bestaat."""
    n = len(window)
    pivots: list[Pivot] = []
    for i in range(SR_PIVOT_WINDOW, n - SR_PIVOT_WINDOW):
        high_i = window["high"].iloc[i]
        low_i = window["low"].iloc[i]
        left_highs = window["high"].iloc[i - SR_PIVOT_WINDOW:i]
        right_highs = window["high"].iloc[i + 1:i + SR_PIVOT_WINDOW + 1]
        if high_i > left_highs.max() and high_i > right_highs.max():
            pivots.append(Pivot(index=i, price=float(high_i), kind="high"))
        left_lows = window["low"].iloc[i - SR_PIVOT_WINDOW:i]
        right_lows = window["low"].iloc[i + 1:i + SR_PIVOT_WINDOW + 1]
        if low_i < left_lows.min() and low_i < right_lows.min():
            pivots.append(Pivot(index=i, price=float(low_i), kind="low"))
    return pivots
```

Herschrijf daarna de bestaande `detect_sr_zones`-functiebody (de
pivot-verzamelende `for i in range(...)`-loop) om `_find_pivots` te
gebruiken in plaats van zijn eigen kopie. Vervang dit deel:

```python
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
```

door:

```python
    window = df.tail(lookback).reset_index(drop=True)
    pivots = [p.price for p in _find_pivots(window)]

    if not pivots:
        return []
```

Rest van `detect_sr_zones` (clustering, `SR_ZONE_MIN_TOUCHES`-filter,
return) blijft ongewijzigd.

- [ ] **Step 4: Run het script, bevestig dat alles slaagt**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_pivots.py
```

Verwacht: `=== 4 geslaagd, 0 gefaald ===`, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add app/indicators.py
git commit -m "Trendlijn-detectie: pivot-detectie uit detect_sr_zones getrokken naar _find_pivots"
```

---

### Task 2: Trendline-detectie (`app/indicators.py`)

**Files:**
- Modify: `app/indicators.py` (na `BREAKOUT_RETEST_TOLERANCE_ATR_MULTIPLE`/`find_breakout_retest`, rond regel 726)
- Test: `<SCRATCHPAD>/test_detect_trendlines.py`

**Interfaces:**
- Consumes: `Pivot`, `_find_pivots` (Task 1).
- Produces:
  - `Trendline` (dataclass: `kind: str`, `slope: float`, `intercept: float`, `touches: int`, `last_index: int`, methode `value_at(index: int) -> float`)
  - `detect_trendlines(df: pd.DataFrame, atr: float, lookback: int = SR_ZONE_LOOKBACK) -> list[Trendline]` — gebruikt door Task 3, Task 5, Task 7.

- [ ] **Step 1: Schrijf het testscript met de eerste falende asserties**

Maak `<SCRATCHPAD>/test_detect_trendlines.py`:

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


def make_candle(high, low):
    return {"open": low, "high": high, "low": low, "close": (high + low) / 2}


# --- Een dalende driehoek: 3 lower highs op één lijn, prijs verder vlak ---
rows = [make_candle(110.0, 108.0) for _ in range(90)]
# Drie duidelijke pivot-highs op een dalende lijn: index 10 -> 130, index 40 -> 122, index 70 -> 114
# (elk 3 candles ervoor/erna lager, zodat _find_pivots ze herkent)
for idx, high in [(10, 130.0), (40, 122.0), (70, 114.0)]:
    rows[idx] = make_candle(high, high - 2.0)
    for offset in (-3, -2, -1, 1, 2, 3):
        rows[idx + offset] = make_candle(high - 5.0, high - 7.0)
df = pd.DataFrame(rows)

lines = indicators.detect_trendlines(df, atr=2.0)
resistance_lines = [l for l in lines if l.kind == "resistance"]
check("een dalende driehoek levert een weerstand-trendlijn op", len(resistance_lines) == 1)
if resistance_lines:
    line = resistance_lines[0]
    check("de lijn heeft minimaal TRENDLINE_MIN_TOUCHES treffers", line.touches >= indicators.TRENDLINE_MIN_TOUCHES)
    check("de helling is negatief (dalende weerstand)", line.slope < 0)
    check("value_at(10) ligt dicht bij 130.0", abs(line.value_at(10) - 130.0) < 1.0)
    check("value_at(70) ligt dicht bij 114.0", abs(line.value_at(70) - 114.0) < 1.0)

# --- Twee punten met een derde die er ver vanaf ligt: te weinig treffers, geen lijn ---
rows_weak = [make_candle(110.0, 108.0) for _ in range(90)]
for idx, high in [(10, 130.0), (40, 90.0)]:  # maar 2 pivots, geen derde bevestiging
    rows_weak[idx] = make_candle(high, high - 2.0)
    for offset in (-3, -2, -1, 1, 2, 3):
        rows_weak[idx + offset] = make_candle(high - 5.0, high - 7.0)
df_weak = pd.DataFrame(rows_weak)
lines_weak = indicators.detect_trendlines(df_weak, atr=2.0)
check("met maar 2 pivots wordt geen trendlijn gevonden (te weinig treffers)",
      not any(l.kind == "resistance" for l in lines_weak))

# --- Een bijna vlakke lijn (helling onder de ATR-drempel): geweigerd ---
rows_flat = [make_candle(110.0, 108.0) for _ in range(90)]
for idx, high in [(10, 120.001), (40, 120.0), (70, 119.999)]:  # nagenoeg vlak
    rows_flat[idx] = make_candle(high, high - 2.0)
    for offset in (-3, -2, -1, 1, 2, 3):
        rows_flat[idx + offset] = make_candle(high - 5.0, high - 7.0)
df_flat = pd.DataFrame(rows_flat)
lines_flat = indicators.detect_trendlines(df_flat, atr=2.0)
check("een bijna vlakke lijn wordt geweigerd (te vlak voor TRENDLINE_MIN_SLOPE_ATR_MULTIPLE)",
      not any(l.kind == "resistance" for l in lines_flat))

# --- Geen crash zonder genoeg candles/pivots ---
tiny_df = pd.DataFrame({"open": [1.0, 1.0], "high": [1.1, 1.1], "low": [0.9, 0.9], "close": [1.0, 1.0]})
check("te weinig candles geeft lege lijst, geen crash", indicators.detect_trendlines(tiny_df, atr=0.1) == [])

print(f"\n=== {passed} geslaagd, {failed} gefaald ===")
sys.exit(1 if failed else 0)
```

- [ ] **Step 2: Run het script, bevestig `AttributeError`**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_detect_trendlines.py
```

- [ ] **Step 3: Implementeer `Trendline` en `detect_trendlines`**

In `app/indicators.py`, na de bestaande `find_breakout_retest`-functie
(rond regel 726, vóór de `EXTENSION_MAX_ATR_MULTIPLE`-sectie), voeg toe:

```python
# Minimaal aantal pivots dat op de lijn moet liggen (de twee punten die
# hem vastleggen niet meegerekend, dat is nog "geen bewijs", zie
# TRENDLINE_FIT_TOLERANCE_PCT hieronder) voor hij als echte trendlijn
# telt, niet toeval. Strenger dan SR_ZONE_MIN_TOUCHES (2): een schuine
# lijn door twee punten legt geen enkele relatie vast, een derde
# bevestigende pivot wel.
TRENDLINE_MIN_TOUCHES = 3

# Hoe dicht een pivot bij de kandidaat-lijn moet liggen (als fractie van
# de prijs) om als treffer op die lijn te tellen. Zelfde soort marge als
# SR_ZONE_CLUSTER_TOLERANCE_PCT, iets ruimer: een diagonale lijn door
# candle-pivots past nooit zo exact als een horizontaal cluster.
TRENDLINE_FIT_TOLERANCE_PCT = 0.01

# Minimale helling (in ATR per candle) wil een lijn als "diagonaal" tellen
# in plaats van als verkapte horizontale zone. Zonder dit zou een bijna
# vlakke lijn hetzelfde patroon als detect_sr_zones vinden, dubbel werk
# met een andere naam.
TRENDLINE_MIN_SLOPE_ATR_MULTIPLE = 0.05


@dataclass
class Trendline:
    kind: str  # "resistance" (verbindt pivot-highs) of "support" (pivot-lows)
    slope: float  # prijsverandering per candle-index binnen het venster
    intercept: float  # lijnwaarde bij index 0 van het venster
    touches: int
    last_index: int  # index van de meest recente pivot op de lijn

    def value_at(self, index: int) -> float:
        return self.slope * index + self.intercept


def detect_trendlines(df: pd.DataFrame, atr: float, lookback: int = SR_ZONE_LOOKBACK) -> list[Trendline]:
    """Vindt maximaal twee diagonale trendlijnen (één weerstand door
    pivot-highs, één steun door pivot-lows) in de laatste `lookback`
    candles. Voor elk soort: alle paren pivots van dat soort vormen een
    kandidaat-lijn, tel per kandidaat hoeveel ANDERE pivots van hetzelfde
    soort binnen TRENDLINE_FIT_TOLERANCE_PCT van die lijn liggen, houd de
    lijn met de meeste treffers. Een lijn met te weinig treffers of een te
    vlakke helling wordt niet teruggegeven — geen kandidaat is dan ook
    geen fout, gewoon geen bruikbare lijn deze cyclus."""
    window = df.tail(lookback).reset_index(drop=True)
    pivots = _find_pivots(window)
    lines: list[Trendline] = []

    for kind, pivot_kind in [("resistance", "high"), ("support", "low")]:
        candidates = [p for p in pivots if p.kind == pivot_kind]
        if len(candidates) < TRENDLINE_MIN_TOUCHES:
            continue

        best: Optional[Trendline] = None
        for i in range(len(candidates)):
            for j in range(i + 1, len(candidates)):
                p1, p2 = candidates[i], candidates[j]
                if p1.index == p2.index:
                    continue
                slope = (p2.price - p1.price) / (p2.index - p1.index)
                intercept = p1.price - slope * p1.index

                inliers = [
                    p for p in candidates
                    if abs(p.price - (slope * p.index + intercept)) <= p.price * TRENDLINE_FIT_TOLERANCE_PCT
                ]
                if len(inliers) < TRENDLINE_MIN_TOUCHES:
                    continue
                if atr and abs(slope) < TRENDLINE_MIN_SLOPE_ATR_MULTIPLE * atr:
                    continue
                if best is None or len(inliers) > best.touches:
                    best = Trendline(
                        kind=kind, slope=slope, intercept=intercept,
                        touches=len(inliers), last_index=max(p.index for p in inliers),
                    )
        if best is not None:
            lines.append(best)

    return lines
```

Controleer dat `Optional` al geïmporteerd is bovenaan `app/indicators.py`
(`from typing import Optional`); zo niet, voeg toe.

- [ ] **Step 4: Run het script, bevestig dat alles slaagt**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_detect_trendlines.py
```

Verwacht: `=== 8 geslaagd, 0 gefaald ===`, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add app/indicators.py
git commit -m "Trendlijn-detectie: Trendline-dataclass en detect_trendlines toegevoegd"
```

---

### Task 3: Uitbraak + terugtest-detectie (`app/indicators.py`)

**Files:**
- Modify: `app/indicators.py` (direct na `detect_trendlines` uit Task 2)
- Test: `<SCRATCHPAD>/test_find_trendline_breakout_retest.py`

**Interfaces:**
- Consumes: `Trendline` (Task 2), `BREAKOUT_RETEST_TOLERANCE_ATR_MULTIPLE` (bestaande constante).
- Produces:
  - `find_trendline_breakout_retest(df: pd.DataFrame, trendlines: list[Trendline], atr: float, direction: str) -> list[tuple[Trendline, int]]` — gebruikt door Task 5, Task 7.

- [ ] **Step 1: Schrijf het testscript met de eerste falende asserties**

Maak `<SCRATCHPAD>/test_find_trendline_breakout_retest.py`:

```python
import sys
sys.path.insert(0, "/home/user/Trade")

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


# Een resistance-lijn die daalt van 130 (index 10) naar 100 (index 70):
# slope = (100 - 130) / (70 - 10) = -0.5, intercept = 130 - (-0.5 * 10) = 135
line = indicators.Trendline(kind="resistance", slope=-0.5, intercept=135.0, touches=3, last_index=70)


def make_df(closes: list[float]):
    import pandas as pd
    rows = [{"open": c, "high": c + 0.5, "low": c - 0.5, "close": c} for c in closes]
    return pd.DataFrame(rows)


# --- Geldige terugtest: candle 80 breekt op closing-prijs boven de lijn, blijft erboven, candle 89 test terug ---
closes = [95.0] * 90
for i in range(80, 90):
    closes[i] = line.value_at(i) + 2.0  # steeds ruim boven de lijn
closes[89] = line.value_at(89) + 0.1  # laatste candle: net terug bij de lijn
df_valid = make_df(closes)
hits = indicators.find_trendline_breakout_retest(df_valid, [line], atr=1.0, direction="long")
check("een geldige terugtest wordt gevonden", len(hits) == 1)
if hits:
    found_line, candles_since = hits[0]
    check("candles_since > 0", candles_since > 0)

# --- Fakeout: candle 80 breekt kort boven de lijn, candle 85 sluit weer terug ONDER de lijn ---
closes_fake = [95.0] * 90
for i in range(80, 85):
    closes_fake[i] = line.value_at(i) + 2.0  # kort erboven
for i in range(85, 90):
    closes_fake[i] = line.value_at(i) - 3.0  # sluit weer terug onder de lijn: uitbraak ongeldig
df_fake = make_df(closes_fake)
hits_fake = indicators.find_trendline_breakout_retest(df_fake, [line], atr=1.0, direction="long")
check("een fakeout (teruggevallen onder de lijn) telt niet als terugtest", len(hits_fake) == 0)

# --- candles_since = 0: de uitbraak-candle zelf mag niet als eigen terugtest tellen ---
closes_zero = [95.0] * 90
closes_zero[89] = line.value_at(89) + 0.05  # breekt nu net, op de laatste candle zelf
df_zero = make_df(closes_zero)
hits_zero = indicators.find_trendline_breakout_retest(df_zero, [line], atr=1.0, direction="long")
check("een uitbraak op de laatste candle zelf (candles_since=0) telt niet mee", len(hits_zero) == 0)

# --- Verkeerde richting: een resistance-lijn hoort bij long, niet bij short ---
hits_wrong_dir = indicators.find_trendline_breakout_retest(df_valid, [line], atr=1.0, direction="short")
check("een resistance-lijn levert geen hits op voor short", len(hits_wrong_dir) == 0)

print(f"\n=== {passed} geslaagd, {failed} gefaald ===")
sys.exit(1 if failed else 0)
```

- [ ] **Step 2: Run het script, bevestig `AttributeError`**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_find_trendline_breakout_retest.py
```

- [ ] **Step 3: Implementeer `find_trendline_breakout_retest`**

In `app/indicators.py`, direct na `detect_trendlines` (Task 2), voeg toe:

```python
def find_trendline_breakout_retest(
    df: pd.DataFrame, trendlines: list[Trendline], atr: float, direction: str,
) -> list[tuple[Trendline, int]]:
    """Zelfde patroon als find_breakout_retest: crossing-detectie op de
    laatste candle die van de verkeerde naar de goede kant van het niveau
    sloot, dan checken of dat sindsdien standhield — nu tegen een
    bewegende lijnwaarde in plaats van een vaste zone-grens. Werkt op
    hetzelfde geschoven venster (df.tail(SR_ZONE_LOOKBACK)) als
    detect_trendlines, zodat line.value_at(index) in beide functies
    dezelfde candle aanwijst. Alleen een uitbraak ná line.last_index
    telt: de lijn kan niet gebroken zijn vóór zijn eigen laatste
    bevestigende pivot. Geeft (lijn, candles_since_breakout) terug voor
    elke lijn die nu een geldige terugtest is."""
    window = df.tail(SR_ZONE_LOOKBACK).reset_index(drop=True)
    closes = window["close"]
    direction = direction.lower()
    hits: list[tuple[Trendline, int]] = []

    for line in trendlines:
        if (direction == "long") != (line.kind == "resistance"):
            continue

        line_values = pd.Series([line.value_at(i) for i in range(len(closes))])
        if direction == "long":
            broke = (closes.shift(1) <= line_values.shift(1)) & (closes > line_values)
        else:
            broke = (closes.shift(1) >= line_values.shift(1)) & (closes < line_values)

        breakout_indices = [idx for idx in closes.index[broke] if idx > line.last_index]
        if not breakout_indices:
            continue
        breakout_idx = breakout_indices[-1]
        since_breakout = closes.iloc[breakout_idx + 1:]
        since_line = line_values.iloc[breakout_idx + 1:]
        if direction == "long":
            if (since_breakout < since_line).any():
                continue
        else:
            if (since_breakout > since_line).any():
                continue

        last_index = len(closes) - 1
        last_close = closes.iloc[last_index]
        current_line_value = line.value_at(last_index)
        tolerance = BREAKOUT_RETEST_TOLERANCE_ATR_MULTIPLE * atr
        candles_since = last_index - breakout_idx
        if abs(last_close - current_line_value) <= tolerance and candles_since > 0:
            hits.append((line, candles_since))

    return hits
```

- [ ] **Step 4: Run het script, bevestig dat alles slaagt**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_find_trendline_breakout_retest.py
```

Verwacht: `=== 5 geslaagd, 0 gefaald ===`, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add app/indicators.py
git commit -m "Trendlijn-detectie: find_trendline_breakout_retest toegevoegd"
```

---

### Task 4: Schema/migratie + repo.py

**Files:**
- Modify: `app/schema.sql` (`coins`-tabel, na `last_breakout_retest_key`, rond regel 131)
- Modify: `app/db.py` (`_migrate()`, na de `last_breakout_retest_key`-guard, rond regel 196)
- Modify: `app/repo.py` (na `set_breakout_retest_key`, rond regel 648)
- Test: `<SCRATCHPAD>/test_trendline_repo.py`

**Interfaces:**
- Consumes: niets nieuws.
- Produces:
  - `repo.get_trendline_retest_key(coin: str) -> Optional[str]` — gebruikt door Task 5.
  - `repo.set_trendline_retest_key(coin: str, key: str) -> None` — gebruikt door Task 5.

- [ ] **Step 1: Schrijf het testscript met de eerste falende asserties**

Maak `<SCRATCHPAD>/test_trendline_repo.py`:

```python
import sys, os
sys.path.insert(0, "/home/user/Trade")
os.environ["DATABASE_PATH"] = "<SCRATCHPAD>/test_trendline_repo.db"

from app import db, repo

if os.path.exists(os.environ["DATABASE_PATH"]):
    os.remove(os.environ["DATABASE_PATH"])
db.init_db()

with db.session() as conn:
    conn.execute("INSERT INTO coins (symbol, active) VALUES ('ETH', 1)")

passed = failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  OK  {label}")
    else:
        failed += 1
        print(f"  FAIL {label}")


check("nieuwe coin heeft nog geen trendline-key", repo.get_trendline_retest_key("ETH") is None)

repo.set_trendline_retest_key("ETH", "long:resistance:123.45000000")
check("key wordt opgeslagen en teruggelezen", repo.get_trendline_retest_key("ETH") == "long:resistance:123.45000000")

repo.set_trendline_retest_key("eth", "short:support:99.00000000")  # lowercase, moet normaliseren
check("coin-symbool wordt case-insensitive genormaliseerd", repo.get_trendline_retest_key("ETH") == "short:support:99.00000000")

print(f"\n=== {passed} geslaagd, {failed} gefaald ===")
sys.exit(1 if failed else 0)
```

- [ ] **Step 2: Run het script, bevestig `AttributeError`**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_trendline_repo.py
```

- [ ] **Step 3: Schema + migratie + repo-functies toevoegen**

In `app/schema.sql`, binnen de `coins`-tabel, direct na
`last_breakout_retest_key TEXT` (vóór de sluitende `);`, rond regel 131:

```sql
    last_breakout_retest_key TEXT,
    -- Dedup voor de trendlijn-uitbraak-dan-terugtest-melding
    -- (app/market_scanner.py): "richting:soort:lijnwaarde" van de laatst
    -- gemelde trendlijn voor deze coin. Zelfde soort dedup als
    -- last_breakout_retest_key hierboven, nu voor een diagonale lijn.
    last_trendline_retest_key TEXT
```

In `app/db.py`, binnen `_migrate()`, direct na de guard voor
`last_breakout_retest_key` (rond regel 196):

```python
    if "last_trendline_retest_key" not in existing_coins:
        conn.execute("ALTER TABLE coins ADD COLUMN last_trendline_retest_key TEXT")
```

In `app/repo.py`, direct na `set_breakout_retest_key` (rond regel 648):

```python
def get_trendline_retest_key(coin: str) -> Optional[str]:
    with db.session() as conn:
        row = conn.execute(
            "SELECT last_trendline_retest_key FROM coins WHERE symbol = ?", (coin.upper(),),
        ).fetchone()
        return row["last_trendline_retest_key"] if row else None


def set_trendline_retest_key(coin: str, key: str) -> None:
    with db.session() as conn:
        conn.execute(
            "UPDATE coins SET last_trendline_retest_key = ? WHERE symbol = ?", (key, coin.upper()),
        )
```

- [ ] **Step 4: Run het script, bevestig dat alles slaagt**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_trendline_repo.py
```

Verwacht: `=== 3 geslaagd, 0 gefaald ===`, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add app/schema.sql app/db.py app/repo.py
git commit -m "Trendlijn-detectie: schema/migratie + repo get/set_trendline_retest_key"
```

---

### Task 5: Marktscan-koppeling (`app/market_scanner.py`)

**Files:**
- Modify: `app/market_scanner.py` (na `_same_breakout_retest_zone`/`_check_breakout_retest`)
- Test: `<SCRATCHPAD>/test_check_trendline_retest.py`

**Interfaces:**
- Consumes: `indicators.detect_trendlines`, `indicators.find_trendline_breakout_retest` (Task 2/3), `repo.get_trendline_retest_key`/`set_trendline_retest_key` (Task 4), `telegram_notify.send_trendline_retest_alert` (Task 6, hier al aangeroepen — Task 6 kan onafhankelijk hiervan geïmplementeerd worden zolang de functienaam/signatuur vaststaat).
- Produces:
  - `_same_trendline(existing_key: Optional[str], direction: str, line, last_index: int, atr: float) -> bool`
  - `_check_trendline_retest(coin: str, direction: str, df, ind) -> None` — aangeroepen vanuit `scan_market()`.

- [ ] **Step 1: Schrijf het testscript met de eerste falende asserties**

Dit test alleen de nieuwe wiring-code (`_check_trendline_retest`,
`_same_trendline`), niet opnieuw de al-geteste detectielogica uit Task
2/3 — `detect_trendlines`/`find_trendline_breakout_retest` worden hier
gemockt, zelfde patroon als de bestaande test voor
`_check_breakout_retest` (zie git log van vandaag,
`app/market_scanner.py`-commit "Marktscan: eigen Telegram-melding bij
een uitbraak-dan-terugtest").

Maak `<SCRATCHPAD>/test_check_trendline_retest.py`:

```python
import sys, os, asyncio
sys.path.insert(0, "/home/user/Trade")
os.environ["DATABASE_PATH"] = "<SCRATCHPAD>/test_check_trendline_retest.db"
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")

import pandas as pd
from unittest.mock import patch
from app import db, repo, indicators, market_scanner

if os.path.exists(os.environ["DATABASE_PATH"]):
    os.remove(os.environ["DATABASE_PATH"])
db.init_db()

with db.session() as conn:
    conn.execute(
        "INSERT INTO users (username, password_hash, telegram_chat_id, portfolio_eur, risk_percent, created_at) "
        "VALUES ('u1', 'x', '123', 1000, 1, ?)", (db.now_iso(),),
    )
    conn.execute("INSERT INTO coins (symbol, active) VALUES ('ETH', 1)")

passed = failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  OK  {label}")
    else:
        failed += 1
        print(f"  FAIL {label}")


class FakeInd:
    price = 100.0
    atr = 2.0


# find_trendline_breakout_retest werkt op df.tail(SR_ZONE_LOOKBACK), dus
# de gemockte df moet minimaal zoveel rijen hebben, ook al wordt
# find_trendline_breakout_retest zelf hieronder gemockt — _check_trendline_retest
# zelf leest ook df.tail(...) om de huidige lijnwaarde te bepalen.
fake_df = pd.DataFrame([{"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0}] * indicators.SR_ZONE_LOOKBACK)
line = indicators.Trendline(kind="resistance", slope=-0.5, intercept=135.0, touches=3, last_index=70)

sent = []


async def fake_send(alert, chat_id, force_silent=False):
    sent.append((alert, chat_id, force_silent))


with patch.object(indicators, "detect_trendlines", return_value=[line]), \
     patch.object(indicators, "find_trendline_breakout_retest", return_value=[(line, 5)]), \
     patch("app.telegram_notify.send_trendline_retest_alert", fake_send):
    asyncio.run(market_scanner._check_trendline_retest("ETH", "long", fake_df, FakeInd()))

check("een melding wordt verstuurd naar de ene gebruiker", len(sent) == 1)
if sent:
    alert, chat_id, _ = sent[0]
    check("alert bevat de juiste coin", alert["coin"] == "ETH")
    check("alert bevat de juiste richting", alert["direction"] == "long")
    check("dedup-key wordt opgeslagen na versturen", repo.get_trendline_retest_key("ETH") is not None)

sent.clear()
with patch.object(indicators, "detect_trendlines", return_value=[line]), \
     patch.object(indicators, "find_trendline_breakout_retest", return_value=[(line, 5)]), \
     patch("app.telegram_notify.send_trendline_retest_alert", fake_send):
    asyncio.run(market_scanner._check_trendline_retest("ETH", "long", fake_df, FakeInd()))

check("zelfde lijn nogmaals: geen tweede melding (dedup)", len(sent) == 0)

print(f"\n=== {passed} geslaagd, {failed} gefaald ===")
sys.exit(1 if failed else 0)
```

- [ ] **Step 2: Run het script, bevestig `AttributeError`**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_check_trendline_retest.py
```

- [ ] **Step 3: Implementeer `_same_trendline` en `_check_trendline_retest`, koppel in `scan_market()`**

In `app/market_scanner.py`, direct na de bestaande
`_check_breakout_retest`-functie:

```python
TRENDLINE_DEDUP_ATR_MULTIPLE = 1.0


def _same_trendline(existing_key: Optional[str], direction: str, line, last_index: int, atr: float) -> bool:
    if not existing_key:
        return False
    try:
        prev_direction, prev_kind, prev_value_s = existing_key.split(":")
        prev_value = float(prev_value_s)
    except (ValueError, AttributeError):
        return False
    if prev_direction != direction or prev_kind != line.kind or not atr:
        return False
    current_value = line.value_at(last_index)
    return abs(prev_value - current_value) <= TRENDLINE_DEDUP_ATR_MULTIPLE * atr


async def _check_trendline_retest(coin: str, direction: str, df, ind) -> None:
    """Los van _check_breakout_retest: een diagonale trendlijn (steun of
    weerstand) is een ander patroon dan een horizontale zone, met een
    eigen melding. Zelfde striktheid (crossing op closing-prijs, moet
    standhouden) en zelfde ATR-dedup-marge als de optie-C-fix van
    vandaag, zie docs/superpowers/specs/2026-09-15-trendlijn-uitbraak-design.md."""
    trendlines = indicators.detect_trendlines(df, ind.atr)
    hits = indicators.find_trendline_breakout_retest(df, trendlines, ind.atr, direction)
    if not hits:
        return
    line, candles_since = max(hits, key=lambda h: h[0].touches)

    # last_index is HIER de laatste candle van het venster (de huidige
    # lijnwaarde), niet line.last_index (dat is de laatste PIVOT op de
    # lijn) — zelfde venster als find_trendline_breakout_retest intern
    # gebruikt, anders wijst value_at(last_index) een andere candle aan
    # dan waar de terugtest zojuist tegen getoetst is.
    window = df.tail(indicators.SR_ZONE_LOOKBACK).reset_index(drop=True)
    last_index = len(window) - 1
    current_value = line.value_at(last_index)
    key = f"{direction}:{line.kind}:{current_value:.8f}"
    if _same_trendline(repo.get_trendline_retest_key(coin), direction, line, last_index, ind.atr):
        return

    stop_take = risk.compute_stop_take(
        direction, ind.price, ind.atr,
        swing_low=current_value if direction == "long" else None,
        swing_high=current_value if direction == "short" else None,
    )
    alert = {
        "coin": coin, "direction": direction, "price": ind.price,
        "line_value": current_value, "touches": line.touches,
        "candles_since": candles_since, "stop_loss": stop_take.stop_loss,
        "take_profit": stop_take.take_profit, "message_id": None,
    }
    for user in repo.list_users():
        if not user["telegram_chat_id"]:
            continue
        if repo.is_coin_muted(user["id"], coin):
            continue
        force_silent = telegram_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            await telegram_notify.send_trendline_retest_alert(
                alert, chat_id=user["telegram_chat_id"], force_silent=force_silent,
            )
        except Exception:
            logger.exception(
                "Trendlijn-terugtest-melding voor %s naar gebruiker %s is mislukt", coin, user["username"],
            )
    repo.set_trendline_retest_key(coin, key)
```

Voeg bovenaan `app/market_scanner.py` toe (als nog niet aanwezig):
`from typing import Optional`.

Roep `_check_trendline_retest` aan in `scan_market()`, direct na de
bestaande regel `await _check_breakout_retest(coin, direction, df, ind)`:

```python
            await _check_breakout_retest(coin, direction, df, ind)
            await _check_trendline_retest(coin, direction, df, ind)
```

- [ ] **Step 4: Run het script, bevestig dat alles slaagt**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_check_trendline_retest.py
```

Verwacht: `=== 5 geslaagd, 0 gefaald ===`, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add app/market_scanner.py
git commit -m "Trendlijn-detectie: marktscan-koppeling (_check_trendline_retest)"
```

---

### Task 6: Telegram-melding (`app/telegram_notify.py`)

**Files:**
- Modify: `app/telegram_notify.py` (na `send_breakout_retest_alert`)
- Test: `<SCRATCHPAD>/test_trendline_message.py`

**Interfaces:**
- Consumes: `_direction_emoji`, `_coin_label`, `_direction_label`, `_progress_bar`, `DIVIDER`, `config.DASHBOARD_URL`, `config.DISCLAIMER` (allemaal al bestaand, hergebruikt).
- Produces:
  - `format_trendline_retest_message(alert: dict) -> str` — gebruikt door `send_trendline_retest_alert` en door Task 5's test (als referentie voor het alert-dict-formaat).
  - `send_trendline_retest_alert(alert: dict, chat_id: str, force_silent: bool = False) -> None` — al aangeroepen door Task 5.
  - `_trendline_link(coin: str) -> str`

- [ ] **Step 1: Schrijf het testscript met de eerste falende asserties**

Maak `<SCRATCHPAD>/test_trendline_message.py`:

```python
import sys
sys.path.insert(0, "/home/user/Trade")

from app import telegram_notify as tn

passed = failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  OK  {label}")
    else:
        failed += 1
        print(f"  FAIL {label}")


alert = {
    "coin": "ETH", "direction": "long", "price": 2500.1234,
    "line_value": 2480.5, "touches": 3, "candles_since": 4,
    "stop_loss": 2450.0, "take_profit": 2600.0, "message_id": None,
}
msg = tn.format_trendline_retest_message(alert)
check("bericht bevat de coin", "ETH" in msg)
check("bericht bevat het icoon 📐", "📐" in msg)
check("bericht bevat het aantal treffers", "3x eerder geraakt" in msg)
check("bericht bevat de trendlijn-link", "trendlijn op de grafiek" in msg)
check("bericht bevat de disclaimer", tn.config.DISCLAIMER in msg)

print(f"\n=== {passed} geslaagd, {failed} gefaald ===")
sys.exit(1 if failed else 0)
```

- [ ] **Step 2: Run het script, bevestig `AttributeError`**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_trendline_message.py
```

- [ ] **Step 3: Implementeer `format_trendline_retest_message`, `_trendline_link`, `send_trendline_retest_alert`**

In `app/telegram_notify.py`, direct na de bestaande
`send_breakout_retest_alert`-functie:

```python
def _trendline_link(coin: str) -> str:
    """Link naar de coin-pagina zonder query-parameters: een trendlijn
    heeft geen vaste zone-band om te markeren zoals optie C, de lijn zelf
    toont zich al als losse lijnserie op de grafiek."""
    url = f"{config.DASHBOARD_URL}/coins/{coin}"
    return f"🔎 Bekijk de trendlijn op de grafiek: {url}"


def format_trendline_retest_message(alert: dict) -> str:
    """Melding voor een diagonale-trendlijn-uitbraak-dan-terugtest: zelfde
    striktheid als optie C (format_breakout_retest_message), eigen icoon
    (📐) om de twee typen in Telegram meteen te onderscheiden."""
    kind_label = "weerstand" if alert["direction"] == "long" else "steun"
    lines = [
        f"{_direction_emoji(alert['direction'])} {_coin_label(alert['coin'])} · {_direction_label(alert['direction'])}",
        DIVIDER,
        "📐 TRENDLIJN-UITBRAAK-DAN-TERUGTEST",
        "",
        f"💰 Prijs nu: {alert['price']:.4f}",
        f"📍 Trendlijn ({alert['touches']}x eerder geraakt): {alert['line_value']:.4f}",
        f"🎯 Take profit: {alert['take_profit']:.4f}",
        f"🛑 Stop loss: {alert['stop_loss']:.4f}",
        _progress_bar(alert["price"], alert["stop_loss"], alert["take_profit"], alert["direction"]),
        DIVIDER,
        f"Deze lijn was eerder {kind_label}, is {alert['candles_since']} candle(s) geleden "
        "doorbroken en wordt nu opnieuw getest.",
        "",
        _trendline_link(alert["coin"]),
    ]
    lines += [DIVIDER, f"⚠️ {config.DISCLAIMER}"]
    return "\n".join(lines)


async def send_trendline_retest_alert(alert: dict, chat_id: str, force_silent: bool = False) -> None:
    if not config.TELEGRAM_BOT_TOKEN or not chat_id:
        logger.warning("Telegram token of chat ID ontbreekt, trendlijn-terugtest-melding niet verstuurd")
        return
    bot = Bot(token=config.TELEGRAM_BOT_TOKEN)
    text = format_trendline_retest_message(alert)
    await bot.send_message(chat_id=chat_id, text=text, disable_notification=force_silent)
    logger.info("Trendlijn-terugtest-melding verstuurd voor %s %s naar chat %s",
                alert["coin"], alert["direction"], chat_id)
```

- [ ] **Step 4: Run het script, bevestig dat alles slaagt**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_trendline_message.py
```

Verwacht: `=== 5 geslaagd, 0 gefaald ===`, exit code 0.

- [ ] **Step 5: Commit**

```bash
git add app/telegram_notify.py
git commit -m "Trendlijn-detectie: Telegram-melding (format_trendline_retest_message)"
```

---

### Task 7: `/api/candles/{symbol}`-route uitbreiden

**Files:**
- Modify: `web/main.py` (`/api/candles/{symbol}`-route, rond regel 1538-1576)
- Test: `<SCRATCHPAD>/test_candles_trendlines_route.py`

**Interfaces:**
- Consumes: `indicators.detect_trendlines` (Task 2).
- Produces: nieuw JSON-veld `trendlines` op `/api/candles/{symbol}`, gebruikt door Task 8 (`coin.js`).

- [ ] **Step 1: Lees de bestaande route om het exacte invoegpunt te bevestigen**

```bash
sed -n '1538,1576p' /home/user/Trade/web/main.py
```

Bevestig dat de route eindigt met
`return {"candles": candles, "ema9": ema9_series, "ema21": ema21_series, "patterns": patterns, "sr_zones": sr_zones}`
en dat `ind = indicators.compute_indicators(df)` al eerder in de functie
staat (nodig voor `ind.atr`).

- [ ] **Step 2: Schrijf het testscript met de eerste falende asserties**

Maak `<SCRATCHPAD>/test_candles_trendlines_route.py`. Dit vereist een
scratch-DB met een ingelogde gebruiker en een gemockte
`exchange.fetch_ohlcv`, zelfde patroon als eerdere TestClient-tests voor
`/api/candles` in dit project (zie `docs/superpowers/plans/2026-09-09-steun-weerstand-zones.md`,
Task 3, voor het volledige precedent-testscript inclusief login-flow —
hergebruik die opzet, alleen de asserties zijn nieuw):

```python
import sys, os
sys.path.insert(0, "/home/user/Trade")
os.environ["DATABASE_PATH"] = "<SCRATCHPAD>/test_candles_route.db"
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "dummy")
os.environ.setdefault("JWT_SECRET", "test-secret-key-minstens-32-tekens-lang")

from unittest.mock import patch
import pandas as pd
from fastapi.testclient import TestClient
from app import db, repo, security

if os.path.exists(os.environ["DATABASE_PATH"]):
    os.remove(os.environ["DATABASE_PATH"])
db.init_db()

with db.session() as conn:
    conn.execute(
        "INSERT INTO users (username, password_hash, telegram_chat_id, portfolio_eur, risk_percent, created_at) "
        "VALUES ('u1', ?, '123', 1000, 1, ?)", (security.hash_password("wachtwoord123"), db.now_iso()),
    )
    conn.execute("INSERT INTO coins (symbol, active) VALUES ('ETH', 1)")

from web.main import app
client = TestClient(app)

login = client.post("/login", data={"username": "u1", "password": "wachtwoord123"}, follow_redirects=False)
cookie = login.cookies.get("session")

passed = failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  OK  {label}")
    else:
        failed += 1
        print(f"  FAIL {label}")


rows = [{"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1000.0, "timestamp": 1700000000000 + i * 14400000} for i in range(150)]
fake_df = pd.DataFrame(rows)

with patch("web.main.exchange.fetch_ohlcv", return_value=fake_df):
    resp = client.get("/api/candles/ETH", cookies={"session": cookie})

check("response is 200", resp.status_code == 200)
data = resp.json()
check("response bevat het trendlines-veld", "trendlines" in data)
check("trendlines is een lijst", isinstance(data["trendlines"], list))

print(f"\n=== {passed} geslaagd, {failed} gefaald ===")
sys.exit(1 if failed else 0)
```

Pas het pad naar `exchange.fetch_ohlcv` (`web.main.exchange.fetch_ohlcv`
vs. een andere importnaam) aan zodra Step 1 het echte importpad in
`web/main.py` heeft bevestigd.

- [ ] **Step 3: Run het script, bevestig dat het faalt op het ontbrekende veld**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_candles_trendlines_route.py
```

Verwacht: `FAIL response bevat het trendlines-veld`.

- [ ] **Step 4: Voeg het `trendlines`-veld toe aan de route**

In `web/main.py`, in de `/api/candles/{symbol}`-route, na de bestaande
`sr_zones`-opbouw en vóór de `return`-regel (rond regel 1573):

```python
    trendlines = indicators.detect_trendlines(df, ind.atr)
    window = df.tail(indicators.SR_ZONE_LOOKBACK).reset_index(drop=True)
    trendline_data = [
        {
            "kind": t.kind,
            "touches": t.touches,
            "points": [
                {"time": candles[len(candles) - len(window) + t.last_index]["time"], "price": t.value_at(t.last_index)},
                {"time": candles[-1]["time"], "price": t.value_at(len(window) - 1)},
            ],
        }
        for t in trendlines
    ]
```

Pas de `return`-regel aan naar:

```python
    return {
        "candles": candles, "ema9": ema9_series, "ema21": ema21_series,
        "patterns": patterns, "sr_zones": sr_zones, "trendlines": trendline_data,
    }
```

- [ ] **Step 5: Run het script, bevestig dat alles slaagt**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_candles_trendlines_route.py
```

Verwacht: `=== 3 geslaagd, 0 gefaald ===`, exit code 0.

- [ ] **Step 6: Commit**

```bash
git add web/main.py
git commit -m "Trendlijn-detectie: trendlines-veld op /api/candles/{symbol}"
```

---

### Task 8: Grafiek-weergave (`web/static/coin.js`, `web/static/style.css`)

**Files:**
- Modify: `web/static/coin.js` (na de bestaande `srZoneEls`-opbouw in de `.then()`-callback, rond regel 270-276)
- Modify: `web/static/style.css` (geen nieuwe CSS-klasse nodig, hergebruikt de bestaande amber-highlight-kleur `#f5a623` uit de optie-C-zone-highlight)

**Interfaces:**
- Consumes: `data.trendlines` (Task 7).
- Produces: visuele lijnserie per trendlijn op de coin-grafiek.

- [ ] **Step 1: Lees de bestaande `.then()`-callback om het exacte invoegpunt te bevestigen**

```bash
sed -n '260,285p' /home/user/Trade/web/static/coin.js
```

Bevestig dat de `srZoneEls`-opbouw en `chart.timeScale().fitContent();`
nog op dezelfde plek staan als eerder deze sessie.

- [ ] **Step 2: Voeg de trendlijn-tekenlaag toe**

In `web/static/coin.js`, direct na de bestaande `srZoneEls = (data.sr_zones || []).map(...)`-blok
en vóór `chart.timeScale().fitContent();`, voeg toe:

```javascript
      // Trendlijnen (indicators.detect_trendlines, via het trendlines-veld
      // van /api/candles): een diagonale lijn past niet in het
      // .chart-zone-sr-blok (vaste top/hoogte), dus een eigen
      // lightweight-charts lijnserie per lijn, amber (#f5a623) net als de
      // "gemelde zone"-highlight van optie C — zelfde kanaal, zelfde
      // kleurtaal.
      (data.trendlines || []).forEach((line) => {
        const series = chart.addLineSeries({
          color: "#f5a623", lineWidth: 2, lastValueVisible: false, priceLineVisible: false,
        });
        series.setData(line.points);
      });
```

- [ ] **Step 3: Handmatige Playwright-verificatie**

Start de dev-server tegen een scratch-DB met een gemockte coin die een
duidelijke trendlijn oplevert (hergebruik de synthetische
driehoek-candles uit Task 2's test om een DB te vullen, of monkey-patch
`exchange.fetch_ohlcv` net als in Task 7's test), open de coin-pagina in
Playwright, en bevestig visueel:

- Er verschijnt een amber diagonale lijn op de grafiek.
- De lijn ligt op de verwachte prijshoogte (visuele check tegen de
  synthetische pivots).
- De bestaande paarse horizontale zones en teal community-niveaus blijven
  gewoon zichtbaar ernaast (geen regressie).
- Op mobiel-breedte (bijvoorbeeld 400px viewport) blijft de grafiek
  bruikbaar, geen overlappende labels.

Maak een screenshot en bekijk hem.

- [ ] **Step 4: Commit**

```bash
git add web/static/coin.js
git commit -m "Trendlijn-detectie: lijnserie op de grafiek (coin.js)"
```

---

### Task 9: Volledige regressie + push

**Files:** geen wijzigingen, alleen verificatie.

- [ ] **Step 1: Draai alle testscripts van Task 1 t/m 7 achter elkaar**

```bash
source /home/user/Trade/.venv/bin/activate
for f in test_pivots test_detect_trendlines test_find_trendline_breakout_retest \
         test_trendline_repo test_check_trendline_retest test_trendline_message \
         test_candles_trendlines_route; do
  echo "=== $f ==="
  python3 <SCRATCHPAD>/$f.py || echo "GEFAALD: $f"
done
```

Bevestig dat elk script `0 gefaald` meldt.

- [ ] **Step 2: Draai de bestaande regressietests die dit plan kan raken**

`detect_sr_zones` is herschreven in Task 1 — draai ook de bestaande
zone-tests opnieuw (zelfde testscript-inhoud als
`docs/superpowers/plans/2026-09-09-steun-weerstand-zones.md`, Task 1,
of een kort ad-hoc script dat `detect_sr_zones` los aanroept met
synthetische candles) om te bevestigen dat de refactor in Task 1 het
bestaande gedrag niet gebroken heeft.

- [ ] **Step 3: `git log --oneline` controleren, alle 8 commits van dit plan aanwezig**

```bash
git log --oneline -10
```

- [ ] **Step 4: Push**

```bash
git push -u origin claude/crypto-day-trading-alerts-5p8w6v
```

- [ ] **Step 5: Meld de deploy-commando's**

Nieuwe migratie (`coins.last_trendline_retest_key`) raakt zowel
`crypto-bot` (market_scanner draait daar via de systemd-timer) als
`crypto-web` (de nieuwe route). Beide processen herstarten na de pull:

```bash
cd /opt/crypto-alerts
git pull origin claude/crypto-day-trading-alerts-5p8w6v
sudo systemctl restart crypto-bot crypto-web
```
