# Patroonherkenning (Fase 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HesPulse herkent zelf chart-patronen (reversal-vormen, kanaal/wedge,
divergence) op de bestaande 4-uurs candles en meldt elk bevestigd patroon
als een eigen signaal op /signalen, met patroonnaam en twee entry-opties
(uitbraak / retest).

**Architecture:** Nieuwe, gefocuste module `app/patterns.py` bevat alle
detectielogica, bovenop bestaande bouwstenen (`indicators._find_pivots`,
`indicators.detect_trendlines`, `indicators.find_trendline_breakout_retest`).
`app/market_scanner.py` roept deze elke scan-cyclus aan (net als de
bestaande `_check_breakout_retest`/`_check_trendline_retest`) en deelt een
bevestigd patroon via een nieuwe, gedeelde fan-out-helper in
`signal_processor.py` (hergebruikt door zowel swing als patroon). UI en
Telegram/push-melding volgen de bestaande swing-conventies.

**Tech Stack:** Python 3.11, pandas, de `ta`-library (al gebruikt in
`indicators.py`), SQLite (via `app/db.py`/`app/repo.py`), FastAPI + Jinja2
(`web/`).

**Spec:** `docs/superpowers/specs/2026-09-22-patroonherkenning-design.md`

## Global Constraints

- Alle database-toegang loopt via `app/repo.py`, nooit rechtstreeks SQL
  elders (CLAUDE.md).
- Schema-wijzigingen zijn tweeledig: `CREATE TABLE IF NOT EXISTS`/kolom in
  `app/schema.sql` (verse installaties) + idempotente `ALTER TABLE ... ADD
  COLUMN` achter een `PRAGMA table_info`-check in `app/db.py:_migrate()`
  (bestaande installaties). Een index op een nieuwe kolom hoort in
  `_migrate()`, niet in `schema.sql`, als de kolom zelf ook pas in
  `_migrate()` wordt toegevoegd.
- Geen pytest-suite. Verifieer met een throwaway script tegen een scratch-
  database: `DATABASE_PATH=/tmp/scratch.db python3 -c "..."` of een los
  scriptbestand in de sessie-scratchpad. UI-wijzigingen: handmatige
  Playwright-verificatie tegen een lokale `uvicorn`-instantie (Chromium op
  `/opt/pw-browsers/chromium`, Node-module via
  `NODE_PATH=/opt/node22/lib/node_modules node ...`, geen Python-Playwright
  beschikbaar in deze omgeving).
- Nooit zelf een trade plaatsen. Een patroon-signaal is, net als elk ander
  signaal, puur informatief: entry/stop/take en de reden, de gebruiker
  beslist en voert zelf uit.
- Confidence/signaal-UI-tekst houdt gemeten en geschat uit elkaar (CLAUDE.md):
  een patroon-signaal heeft geen gepoold percentage (zie Sectie
  "Architectuurbeslissingen" in de spec) — toon nooit een percentage-badge
  voor `trade_type == "patroon"`, alleen de patroonnaam zelf.
- **Scope-verfijning t.o.v. de spec** (vastgesteld tijdens dit plan, zie
  Task 2): de kanaal/wedge/driehoek-familie uit de spec wordt in Fase 1
  beperkt tot de richtingsgebonden vormen — rising/falling wedge, rising/
  descending channel (beide lijnen dezelfde kant op). Driehoek-vormen met
  tegengestelde hellingen (symmetrical/expanding triangle) hebben geen
  betrouwbare richting uit geometrie alleen (het patronenblad plaatst ze
  zelf apart als "50/50 kans") en worden al gedekt door de bestaande
  `_check_trendline_retest`-melding zodra een van beide lijnen echt breekt.
  Ascending/descending triangle (één vlakke rand + één hellende lijn) valt
  ook buiten Fase 1: dat vergt een aparte combinatie van `detect_sr_zones`
  (vlakke rand) en `detect_trendlines` (hellende rand) die zijn eigen
  detector verdient, geen kleine uitbreiding van deze taak.

---

### Task 1: `app/patterns.py` — reversal-patronen (top/bottom, head & shoulders)

**Files:**
- Create: `app/patterns.py`
- Modify: `scripts/research_reversal_patterns.py` (wordt een dunne
  CLI-wrapper om de verplaatste logica, geen dubbele implementatie)

**Interfaces:**
- Produces: `@dataclass PatternMatch` (`name: str`, `direction: str`,
  `neckline: float`, `extreme: float`, `target: Optional[float]`,
  `stop_loss: Optional[float]`, `confirmed_index: int`, `pattern_kind: str`
  — `"top_bottom" | "hs" | "channel_wedge" | "divergence"`),
  `find_reversal_patterns(df: pd.DataFrame) -> list[PatternMatch]`.
  Gebruikt door Task 4 (`find_entry_options`), Task 7
  (`market_scanner._check_chart_patterns`), Task 9 (validatiescript).

- [ ] **Step 1: Schrijf `app/patterns.py` met de geporteerde reversal-detectie**

`scripts/research_reversal_patterns.py` bevat al bewezen, geteste logica
(`find_double_triple`, `find_head_and_shoulders`, `_find_neckline_break`,
`_equal_enough`, de constanten `PEAK_TOLERANCE_PCT`/`HS_HEAD_MARGIN_PCT`).
Verplaats die naar `app/patterns.py`, breid `PatternMatch` uit met
`stop_loss`/`pattern_kind`, en voeg een eigen stop-berekening toe (de
research-versie had die nog niet nodig, alleen live signalering wel):

```python
"""Chart-patroonherkenning op de 4-uurs candle (config.TIMEFRAME): welk
patroon staat er nu, en wat is de bijbehorende entry/stop/target? Bouwt op
dezelfde pivot-detectie als indicators.detect_sr_zones/detect_trendlines
(indicators._find_pivots), zodat er geen tweede, afwijkende pivot-definitie
ontstaat. Zie docs/superpowers/specs/2026-09-22-patroonherkenning-design.md."""
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import ta

from app import indicators

# Hoe gelijk twee of drie pieken/dalen moeten zijn om als "hetzelfde
# niveau" te tellen. Crypto op de 4u-candle ligt zelden binnen 0.5%
# (SR_ZONE_CLUSTER_TOLERANCE_PCT), 2% is dichter bij hoe deze patronen er
# in de praktijk uitzien.
PEAK_TOLERANCE_PCT = 0.02

# Het hoofd moet minstens dit percentage verder uitsteken dan de
# schouders, anders is het gewoon een triple top/bottom met een
# toevallig randje.
HS_HEAD_MARGIN_PCT = 0.01

# Hoeveel candles na de nek-doorbraak op een geldige terugtest gewacht
# wordt (Task 4, find_entry_options) voordat de kans als vervlogen geldt.
# Zelfde orde-grootte als PENDING_LEVEL_MIN_AGE_MINUTES/4h-candles elders.
NECKLINE_RETEST_MAX_WAIT_CANDLES = 30

# Kleine marge voorbij de extreme van het patroon (top/hoofd/dal) zelf: een
# stop precies OP de extreme zou door een enkele wick al geraakt worden
# terwijl het patroon zelf nog geldig is. Zelfde soort kleine buffer als
# elders in het project (ATR_BUFFER_MULTIPLIER in risk.py), hier als vast
# percentage omdat een patroon-extreme geen eigen ATR-schaal heeft zoals
# een swing-niveau dat wel heeft.
PATTERN_STOP_MARGIN_PCT = 0.005


@dataclass
class PatternMatch:
    name: str
    direction: str  # "long" of "short"
    neckline: float  # of lijnwaarde bij channel_wedge
    extreme: float  # hoogste piek / laagste dal van het patroon zelf
    target: Optional[float]  # None bij divergence (geen gemeten beweging)
    stop_loss: Optional[float]  # None bij divergence
    confirmed_index: int  # candle-index waarop de nek/lijn daadwerkelijk doorbroken werd
    pattern_kind: str  # "top_bottom" | "hs" | "channel_wedge" | "divergence"


def _equal_enough(prices: list[float], tolerance_pct: float) -> bool:
    return (max(prices) - min(prices)) <= tolerance_pct * (sum(prices) / len(prices))


def _find_neckline_break(
    df: pd.DataFrame, after_index: int, neckline: float, kind: str, max_wait: int = 30,
) -> Optional[int]:
    """Eerste candle na het patroon zelf die de nek daadwerkelijk doorbreekt
    (close voorbij de nek, niet alleen een schaduw): zonder deze bevestiging
    is het patroon nooit 'af', slechts een vorm die nog kan mislukken."""
    window = df.iloc[after_index + 1:after_index + 1 + max_wait]
    for idx, row in window.iterrows():
        if kind == "high" and row["close"] < neckline:
            return idx
        if kind == "low" and row["close"] > neckline:
            return idx
    return None


def _pattern_stop_loss(extreme: float, direction: str) -> float:
    return extreme * (1 + PATTERN_STOP_MARGIN_PCT) if direction == "short" \
        else extreme * (1 - PATTERN_STOP_MARGIN_PCT)


def find_double_triple(df: pd.DataFrame, kind: str, n: int) -> list[PatternMatch]:
    """kind='high' -> double/triple top (bearish), kind='low' -> double/
    triple bottom (bullish). n=2 of n=3 pieken/dalen op ongeveer gelijke
    hoogte; de nek is de laagste/hoogste candle tussen de buitenste twee."""
    pivots = sorted([p for p in indicators._find_pivots(df) if p.kind == kind], key=lambda p: p.index)
    direction = "short" if kind == "high" else "long"
    matches = []
    for i in range(len(pivots) - n + 1):
        group = pivots[i:i + n]
        prices = [p.price for p in group]
        if not _equal_enough(prices, PEAK_TOLERANCE_PCT):
            continue
        start, end = group[0].index, group[-1].index
        between = df.iloc[start:end + 1]
        neckline = between["low"].min() if kind == "high" else between["high"].max()
        extreme = max(prices) if kind == "high" else min(prices)
        target = neckline - (extreme - neckline) if kind == "high" else neckline + (neckline - extreme)
        confirmed_index = _find_neckline_break(df, end, neckline, kind)
        if confirmed_index is not None:
            matches.append(PatternMatch(
                name=f"{'triple' if n == 3 else 'double'} {'top' if kind == 'high' else 'bottom'}",
                direction=direction, neckline=neckline, extreme=extreme,
                target=target, stop_loss=_pattern_stop_loss(extreme, direction),
                confirmed_index=confirmed_index, pattern_kind="top_bottom",
            ))
    return matches


def find_head_and_shoulders(df: pd.DataFrame, kind: str) -> list[PatternMatch]:
    """kind='high' -> head & shoulders (bearish), kind='low' -> inverse
    head & shoulders (bullish). Vijf afwisselende pivots nodig: schouder,
    dal, hoofd, dal, schouder (of gespiegeld). Het hoofd moet duidelijk
    verder uitsteken dan de twee schouders, de schouders moeten ongeveer
    gelijk zijn."""
    all_pivots = sorted(indicators._find_pivots(df), key=lambda p: p.index)
    direction = "short" if kind == "high" else "long"
    other = "low" if kind == "high" else "high"
    matches = []
    for i in range(len(all_pivots) - 4):
        window = all_pivots[i:i + 5]
        if [p.kind for p in window] != [kind, other, kind, other, kind]:
            continue
        shoulder1, trough1, head, trough2, shoulder2 = window
        if not _equal_enough([shoulder1.price, shoulder2.price], PEAK_TOLERANCE_PCT):
            continue
        head_beats_shoulders = (
            head.price > max(shoulder1.price, shoulder2.price) * (1 + HS_HEAD_MARGIN_PCT)
            if kind == "high" else
            head.price < min(shoulder1.price, shoulder2.price) * (1 - HS_HEAD_MARGIN_PCT)
        )
        if not head_beats_shoulders:
            continue
        neckline = max(trough1.price, trough2.price) if kind == "high" else min(trough1.price, trough2.price)
        target = neckline - (head.price - neckline) if kind == "high" else neckline + (neckline - head.price)
        confirmed_index = _find_neckline_break(df, shoulder2.index, neckline, kind)
        if confirmed_index is not None:
            matches.append(PatternMatch(
                name="head & shoulders" if kind == "high" else "inverse head & shoulders",
                direction=direction, neckline=neckline, extreme=head.price,
                target=target, stop_loss=_pattern_stop_loss(head.price, direction),
                confirmed_index=confirmed_index, pattern_kind="hs",
            ))
    return matches


def find_reversal_patterns(df: pd.DataFrame) -> list[PatternMatch]:
    """Alle bevestigde double/triple top/bottom- en head & shoulders-
    matches in dit candle-venster, nieuwste eerst niet gegarandeerd (zie
    caller: market_scanner pakt zelf de match met de hoogste
    confirmed_index)."""
    matches: list[PatternMatch] = []
    matches += find_double_triple(df, "high", 2)
    matches += find_double_triple(df, "low", 2)
    matches += find_double_triple(df, "high", 3)
    matches += find_double_triple(df, "low", 3)
    matches += find_head_and_shoulders(df, "high")
    matches += find_head_and_shoulders(df, "low")
    return matches
```

- [ ] **Step 2: Verifieer met een throwaway script**

```bash
mkdir -p /tmp/claude-0/-home-user-Trade/scratchpad
cat > /tmp/claude-0/-home-user-Trade/scratchpad/test_patterns_reversal.py << 'EOF'
import sys
sys.path.insert(0, "/home/user/Trade")
import numpy as np
import pandas as pd
from app import patterns

# Bouw een synthetische double bottom: twee ongeveer gelijke dalen met een
# hogere piek ertussen, dan een doorbraak boven de nek.
n = 80
closes = [100.0] * 10
closes += list(np.linspace(100, 90, 8))     # eerste daling naar dal 1
closes += list(np.linspace(90, 98, 6))      # terug omhoog (nek-gebied)
closes += list(np.linspace(98, 91, 8))      # tweede daling naar dal 2 (~gelijk aan dal 1)
closes += list(np.linspace(91, 100, 10))    # doorbraak boven de nek (~98)
closes += [102.0] * (n - len(closes))
closes = closes[:n]
df = pd.DataFrame({
    "open": closes, "close": closes,
    "high": [c + 0.3 for c in closes], "low": [c - 0.3 for c in closes],
    "volume": [1000.0] * n,
})

matches = patterns.find_double_triple(df, "low", 2)
print(f"double bottom matches: {len(matches)}")
assert len(matches) >= 1, "verwacht minstens 1 double bottom"
m = matches[0]
assert m.direction == "long"
assert m.pattern_kind == "top_bottom"
assert m.stop_loss < m.extreme, "stop moet voorbij (onder) de extreme liggen bij long"
assert m.target > m.neckline, "target moet boven de nek liggen bij long"
print("double bottom: name=%s neckline=%.2f extreme=%.2f target=%.2f stop=%.2f" % (
    m.name, m.neckline, m.extreme, m.target, m.stop_loss))

all_matches = patterns.find_reversal_patterns(df)
print(f"find_reversal_patterns totaal: {len(all_matches)}")
assert len(all_matches) >= 1

print("OK")
EOF
python3 /tmp/claude-0/-home-user-Trade/scratchpad/test_patterns_reversal.py
```

Expected: `OK` aan het eind, geen AssertionError.

- [ ] **Step 3: Maak `scripts/research_reversal_patterns.py` een dunne wrapper**

Vervang de geporteerde functies/dataclass door een import, laat
`classify_outcome`/`run`/de CLI ongewijzigd (die blijven hier, ze horen bij
de validatie-flow, niet bij live detectie):

```python
"""Onderzoek: hoe vaak volgen omkeerpatronen (double/triple top/bottom,
head & shoulders, inverse head & shoulders) op de daily of 4u grafiek
daadwerkelijk de richting die het patroon impliceert, tegen jaren echte
Binance-data. Detectielogica zelf staat in app/patterns.py (hergebruikt
door live signalering, zie app/market_scanner.py), dit script voegt alleen
de outcome-classificatie en het jaren-lange-historie-onderzoek toe.

Drie uitkomsten per patroon, niet twee: naast "target gehaald" en
"ongeldig geworden" telt ook "zijwaarts, geen van beide" apart mee.

Kost tijd: haalt jaren daily, of maanden 4u-candles op bij de exchange.

Draai met: python3 scripts/research_reversal_patterns.py --coin BTC --timeframe 1d --years 4
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

from app import exchange
from app.patterns import PatternMatch, find_reversal_patterns

# Hoeveel candles na de nek-doorbraak de uitkomst afgewacht wordt voor het
# patroon als "voltooid" geldt, target of niet.
LOOKFORWARD_CANDLES = 20

# Blijft de prijs binnen dit veelvoud van de ATR rond de nek hangen zonder
# het target te raken of duidelijk terug te draaien, dan telt dat als
# zijwaarts: geen van beide kanten heeft het gewonnen.
SIDEWAYS_ATR_MULT = 1.0


def _atr(df: pd.DataFrame, window: int = 14) -> pd.Series:
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    tr = pd.concat([
        high - low, (high - prev_close).abs(), (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def classify_outcome(df: pd.DataFrame, match: PatternMatch, atr: pd.Series) -> str:
    """target_hit / invalidated / zijwaarts, binnen LOOKFORWARD_CANDLES na
    de nek-doorbraak."""
    window = df.iloc[match.confirmed_index + 1:match.confirmed_index + 1 + LOOKFORWARD_CANDLES]
    if window.empty:
        return "onbekend"
    band = SIDEWAYS_ATR_MULT * atr.iloc[match.confirmed_index]
    for _, row in window.iterrows():
        if match.direction == "short":
            if row["low"] <= match.target:
                return "target_hit"
            if row["close"] > match.neckline + band:
                return "invalidated"
        else:
            if row["high"] >= match.target:
                return "target_hit"
            if row["close"] < match.neckline - band:
                return "invalidated"
    return "zijwaarts"


def run(coin: str, timeframe: str, years: float) -> None:
    candles_per_year = {"4h": 6 * 365, "1d": 365}[timeframe]
    limit = int(candles_per_year * years)
    df = exchange.fetch_ohlcv(coin, timeframe=timeframe, limit=limit)
    atr = _atr(df)

    all_matches = find_reversal_patterns(df)

    print(f"{coin} {timeframe}, {len(df)} candles ({years} jaar), {len(all_matches)} bevestigde patronen\n")

    by_name: dict[str, list[str]] = {}
    for match in all_matches:
        outcome = classify_outcome(df, match, atr)
        by_name.setdefault(match.name, []).append(outcome)

    for name, outcomes in sorted(by_name.items()):
        total = len(outcomes)
        if total == 0:
            continue
        hit = outcomes.count("target_hit")
        invalid = outcomes.count("invalidated")
        sideways = outcomes.count("zijwaarts")
        print(
            f"{name}: {total} keer, target {hit} ({hit / total:.0%}), "
            f"ongeldig {invalid} ({invalid / total:.0%}), zijwaarts {sideways} ({sideways / total:.0%})"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--coin", default="BTC")
    parser.add_argument("--timeframe", default="1d", choices=["4h", "1d"])
    parser.add_argument("--years", type=float, default=4)
    args = parser.parse_args()
    run(args.coin, args.timeframe, args.years)
```

- [ ] **Step 4: Verifieer dat het script nog importeert en draait (zonder netwerk hier, alleen een import-check)**

```bash
python3 -c "
import sys; sys.path.insert(0, '/home/user/Trade')
import importlib
m = importlib.import_module('scripts.research_reversal_patterns')
print('import OK, run callable:', callable(m.run))
"
```

Expected: `import OK, run callable: True`. Netwerkafhankelijke `run()` zelf
hoeft hier niet te draaien (geen Binance-route in deze omgeving), dat komt
in Task 9 op de VPS.

- [ ] **Step 5: Commit**

```bash
git add app/patterns.py scripts/research_reversal_patterns.py
git commit -m "Patroonherkenning: reversal-patronen naar app/patterns.py verplaatst"
```

---

### Task 2: `app/patterns.py` — kanaal/wedge-classificatie

**Files:**
- Modify: `app/patterns.py`

**Interfaces:**
- Consumes: `indicators.Trendline` (velden `kind`, `slope`, `intercept`,
  `touches`, `last_index`, `first_index`, methode `value_at(index)`),
  `indicators.detect_trendlines(df, atr) -> list[Trendline]`.
- Produces: `classify_channel_wedge(trendlines: list[Trendline], window_len: int, atr: float) -> Optional[PatternMatch]`
  (`pattern_kind = "channel_wedge"`). Gebruikt door Task 4 en Task 7.

- [ ] **Step 1: Voeg de classifier toe aan `app/patterns.py`**

```python
# Hoeveel de breedte tussen de twee lijnen aan begin en eind van het
# venster nog van elkaar mag afwijken (als fractie van de gemiddelde
# breedte) om als "ongeveer evenwijdig" (kanaal) te tellen in plaats van
# convergerend/divergerend (wedge/driehoek).
CHANNEL_PARALLEL_TOLERANCE_PCT = 0.15

# De twee lijnen moeten minstens dit veelvoud van de ATR uit elkaar
# liggen, anders is de "vorm" ruis: twee bijna samenvallende lijnen zijn
# geen bruikbaar kanaal/wedge.
MIN_PATTERN_WIDTH_ATR_MULTIPLE = 0.5


def classify_channel_wedge(
    trendlines: list[indicators.Trendline], window_len: int, atr: float,
) -> Optional[PatternMatch]:
    """Herkent kanaal/wedge uit de twee lijnen van indicators.detect_trendlines:
    resistance (bovenlijn) en support (onderlijn) allebei dezelfde kant op
    hellend. Beide omhoog en ongeveer evenwijdig -> rising channel
    (bearish, breekt naar beneden door de steunlijn); beide omhoog en
    convergerend -> rising wedge (zelfde richting, scherper). Beide omlaag
    en evenwijdig -> descending channel (bullish, breekt naar boven door
    de weerstandlijn); beide omlaag en convergerend -> falling wedge.

    Driehoek-vormen (tegengestelde hellingen: symmetrical/expanding
    triangle) hebben geen betrouwbare richting uit geometrie alleen — het
    patronenblad van de gebruiker plaatst ze zelf apart als "50/50 kans".
    Die blijven hier bewust ongedetecteerd (geen PatternMatch, dus geen
    aparte melding); een echte uitbraak van zo'n vorm wordt al gevangen
    door de bestaande indicators.find_trendline_breakout_retest via
    market_scanner._check_trendline_retest, ongeacht welke kant hij
    doorbreekt."""
    resistance = next((l for l in trendlines if l.kind == "resistance"), None)
    support = next((l for l in trendlines if l.kind == "support"), None)
    if resistance is None or support is None:
        return None

    start_idx, end_idx = 0, window_len - 1
    width_start = resistance.value_at(start_idx) - support.value_at(start_idx)
    width_end = resistance.value_at(end_idx) - support.value_at(end_idx)
    if width_start <= 0 or width_end <= 0:
        return None  # lijnen kruisen al binnen dit venster, geen bruikbare vorm
    if atr and min(width_start, width_end) < MIN_PATTERN_WIDTH_ATR_MULTIPLE * atr:
        return None

    res_rising = resistance.slope > 0
    sup_rising = support.slope > 0
    if res_rising != sup_rising:
        return None  # driehoek-vorm, zie docstring

    avg_width = (width_start + width_end) / 2
    width_change_pct = (width_end - width_start) / avg_width
    parallel = abs(width_change_pct) <= CHANNEL_PARALLEL_TOLERANCE_PCT

    if res_rising:
        name = "rising channel" if parallel else "rising wedge"
        direction = "short"
        breakout_level = support.value_at(end_idx)
        stop_loss = resistance.value_at(end_idx) * (1 + PATTERN_STOP_MARGIN_PCT)
        height = width_start
        target = breakout_level - height
    else:
        name = "descending channel" if parallel else "falling wedge"
        direction = "long"
        breakout_level = resistance.value_at(end_idx)
        stop_loss = support.value_at(end_idx) * (1 - PATTERN_STOP_MARGIN_PCT)
        height = width_start
        target = breakout_level + height

    return PatternMatch(
        name=name, direction=direction, neckline=breakout_level, extreme=stop_loss,
        target=target, stop_loss=stop_loss, confirmed_index=end_idx, pattern_kind="channel_wedge",
    )
```

- [ ] **Step 2: Verifieer met een throwaway script**

```bash
cat > /tmp/claude-0/-home-user-Trade/scratchpad/test_patterns_wedge.py << 'EOF'
import sys
sys.path.insert(0, "/home/user/Trade")
from app import patterns
from app.indicators import Trendline

# Rising wedge: beide lijnen omhoog, convergerend (support stijgt sneller
# dan resistance, breedte krimpt van 10 naar 2).
resistance = Trendline(kind="resistance", slope=0.05, intercept=100.0, touches=3, last_index=40, first_index=5)
support = Trendline(kind="support", slope=0.15, intercept=90.0, touches=3, last_index=42, first_index=3)
match = patterns.classify_channel_wedge([resistance, support], window_len=50, atr=1.0)
assert match is not None
assert match.pattern_kind == "channel_wedge"
assert match.direction == "short"
assert "wedge" in match.name
print("rising wedge OK:", match.name, match.direction, match.neckline, match.stop_loss, match.target)

# Rising channel: beide omhoog, ~evenwijdig (zelfde helling).
resistance2 = Trendline(kind="resistance", slope=0.1, intercept=100.0, touches=3, last_index=40, first_index=5)
support2 = Trendline(kind="support", slope=0.1, intercept=90.0, touches=3, last_index=42, first_index=3)
match2 = patterns.classify_channel_wedge([resistance2, support2], window_len=50, atr=1.0)
assert match2 is not None
assert match2.name == "rising channel"
print("rising channel OK:", match2.name)

# Symmetrical triangle (tegengestelde hellingen): geen match verwacht.
resistance3 = Trendline(kind="resistance", slope=-0.05, intercept=100.0, touches=3, last_index=40, first_index=5)
support3 = Trendline(kind="support", slope=0.05, intercept=90.0, touches=3, last_index=42, first_index=3)
match3 = patterns.classify_channel_wedge([resistance3, support3], window_len=50, atr=1.0)
assert match3 is None
print("symmetrical triangle correct genegeerd")

# Te smalle vorm (onder MIN_PATTERN_WIDTH_ATR_MULTIPLE): geen match.
resistance4 = Trendline(kind="resistance", slope=0.05, intercept=100.05, touches=3, last_index=40, first_index=5)
support4 = Trendline(kind="support", slope=0.05, intercept=100.0, touches=3, last_index=42, first_index=3)
match4 = patterns.classify_channel_wedge([resistance4, support4], window_len=50, atr=1.0)
assert match4 is None
print("te smalle vorm correct genegeerd")

print("OK")
EOF
python3 /tmp/claude-0/-home-user-Trade/scratchpad/test_patterns_wedge.py
```

Expected: `OK` aan het eind.

- [ ] **Step 3: Commit**

```bash
git add app/patterns.py
git commit -m "Patroonherkenning: kanaal/wedge-classificatie op detect_trendlines"
```

---

### Task 3: `app/patterns.py` — divergence

**Files:**
- Modify: `app/patterns.py`

**Interfaces:**
- Consumes: `indicators._find_pivots`, `indicators.SR_ZONE_LOOKBACK`.
- Produces: `find_divergence(df: pd.DataFrame) -> Optional[PatternMatch]`
  (`pattern_kind = "divergence"`, `target=None`, `stop_loss=None`).

- [ ] **Step 1: Voeg divergence-detectie toe aan `app/patterns.py`**

```python
def find_divergence(df: pd.DataFrame) -> Optional[PatternMatch]:
    """Bullish divergence: prijs zet een lagere bodem neer, RSI juist een
    hogere (minder oversold dan de vorige bodem) — momentum zwakt af
    terwijl de prijs nog daalt, vaak een voorbode van een omkeer. Bearish:
    spiegelbeeld op pieken. Kijkt alleen naar de laatste twee pivots van
    hetzelfde soort, niet naar elk historisch paar: voor live signalering
    telt of er NU een divergentie staat, niet of er ooit één stond.

    Puur momentum-signaal, geen eigen neckline/hoogte zoals top/bottom of
    channel_wedge — target/stop_loss blijven None, de caller (Task 4/7)
    valt voor deze pattern_kind terug op risk.compute_stop_take (ATR)."""
    window = df.tail(indicators.SR_ZONE_LOOKBACK).reset_index(drop=True)
    rsi_series = ta.momentum.RSIIndicator(window["close"], window=14).rsi()
    pivots = indicators._find_pivots(window)

    lows = sorted([p for p in pivots if p.kind == "low"], key=lambda p: p.index)
    if len(lows) >= 2:
        prev, last = lows[-2], lows[-1]
        rsi_prev, rsi_last = rsi_series.iloc[prev.index], rsi_series.iloc[last.index]
        if (
            not pd.isna(rsi_prev) and not pd.isna(rsi_last)
            and last.price < prev.price and rsi_last > rsi_prev
        ):
            return PatternMatch(
                name="bullish divergence", direction="long", neckline=last.price,
                extreme=last.price, target=None, stop_loss=None,
                confirmed_index=last.index, pattern_kind="divergence",
            )

    highs = sorted([p for p in pivots if p.kind == "high"], key=lambda p: p.index)
    if len(highs) >= 2:
        prev, last = highs[-2], highs[-1]
        rsi_prev, rsi_last = rsi_series.iloc[prev.index], rsi_series.iloc[last.index]
        if (
            not pd.isna(rsi_prev) and not pd.isna(rsi_last)
            and last.price > prev.price and rsi_last < rsi_prev
        ):
            return PatternMatch(
                name="bearish divergence", direction="short", neckline=last.price,
                extreme=last.price, target=None, stop_loss=None,
                confirmed_index=last.index, pattern_kind="divergence",
            )
    return None
```

- [ ] **Step 2: Verifieer met een throwaway script**

```bash
cat > /tmp/claude-0/-home-user-Trade/scratchpad/test_patterns_divergence.py << 'EOF'
import sys
sys.path.insert(0, "/home/user/Trade")
import numpy as np
import pandas as pd
from app import patterns

# Bullish divergence: prijs maakt een lagere bodem, met een RUSTIGERE
# daling de tweede keer (kleinere candle-to-candle beweging) zodat RSI bij
# de tweede bodem hoger staat dan bij de eerste.
n = 60
closes = [100.0] * 10
closes += list(np.linspace(100, 80, 10))    # scherpe daling naar bodem 1 (laag RSI)
closes += list(np.linspace(80, 95, 8))      # herstel
closes += list(np.linspace(95, 78, 16))     # trage, vlakkere daling naar bodem 2 (lagere prijs, hoger RSI)
closes += list(np.linspace(78, 90, 10))
closes += [92.0] * (n - len(closes))
closes = closes[:n]
df = pd.DataFrame({
    "open": closes, "close": closes,
    "high": [c + 0.2 for c in closes], "low": [c - 0.2 for c in closes],
    "volume": [1000.0] * n,
})

match = patterns.find_divergence(df)
print("match:", match)
if match is not None:
    assert match.pattern_kind == "divergence"
    assert match.target is None
    assert match.stop_loss is None
    assert match.direction in ("long", "short")
print("OK (match kan None zijn afhankelijk van exacte pivot-vorming, geen harde eis op deze synthetische data)")
EOF
python3 /tmp/claude-0/-home-user-Trade/scratchpad/test_patterns_divergence.py
```

Expected: geen exception; print toont `match: None` of een
`PatternMatch(...)`. De synthetische candles zijn een benadering (exacte
pivot-vorming hangt af van `SR_PIVOT_WINDOW`), dus dit script controleert
vooral dat de functie niet crasht en, als er een match is, dat de velden
kloppen — geen harde `assert match is not None`.

- [ ] **Step 3: Commit**

```bash
git add app/patterns.py
git commit -m "Patroonherkenning: divergence-detectie (prijs- vs RSI-pivots)"
```

---

### Task 4: `app/patterns.py` — twee entry-opties (uitbraak + retest)

**Files:**
- Modify: `app/patterns.py`

**Interfaces:**
- Consumes: `indicators.find_trendline_breakout_retest`,
  `indicators.BREAKOUT_RETEST_TOLERANCE_ATR_MULTIPLE`,
  `indicators.SR_ZONE_LOOKBACK`, `PatternMatch` (Task 1-3).
- Produces: `find_entry_options(df, match, atr, trendlines=None) -> dict`
  (`{"breakout_level": float, "retest_low": Optional[float], "retest_high": Optional[float]}`).
  Gebruikt door Task 7 (`market_scanner._check_chart_patterns`).

- [ ] **Step 1: Voeg de neckline-retest-check en `find_entry_options` toe**

```python
def _check_neckline_retest(df: pd.DataFrame, match: PatternMatch, atr: float) -> Optional[tuple[float, float]]:
    """Is de prijs sinds de nek-doorbraak (match.confirmed_index) weer
    teruggekomen tot dichtbij de nek zelf, zonder de doorbraak ongedaan te
    maken? Zelfde soort toets als indicators.find_breakout_retest, hier op
    één niveau (de nek) in plaats van een zone met een boven- en
    ondergrens. Geeft (low, high) van de retest-band terug, of None als er
    nog geen (geldige) terugtest is geweest."""
    closes = df["close"].reset_index(drop=True)
    if match.confirmed_index >= len(closes) - 1:
        return None
    since = closes.iloc[match.confirmed_index + 1:]
    tolerance = indicators.BREAKOUT_RETEST_TOLERANCE_ATR_MULTIPLE * atr
    current = closes.iloc[-1]
    if match.direction == "short":
        if (since > match.neckline).any():
            return None
        if current <= match.neckline + tolerance:
            return (match.neckline - tolerance, match.neckline + tolerance)
    else:
        if (since < match.neckline).any():
            return None
        if current >= match.neckline - tolerance:
            return (match.neckline - tolerance, match.neckline + tolerance)
    return None


def find_entry_options(
    df: pd.DataFrame, match: PatternMatch, atr: float,
    trendlines: Optional[list[indicators.Trendline]] = None,
) -> dict:
    """Twee entry-opties voor een bevestigd patroon: het uitbraakniveau
    zelf (breakout_level, snel, kan nog zonder terugtest zijn) en, als de
    prijs al is teruggekeerd, het retest-niveau (bevestigd). retest_low/
    retest_high zijn None zolang er nog geen retest is geweest — de kaart
    toont dan alleen de uitbraak-optie."""
    if match.pattern_kind == "channel_wedge" and trendlines:
        line = next(
            (l for l in trendlines if (l.kind == "resistance") == (match.direction == "long")), None,
        )
        if line is not None:
            window_len = len(df.tail(indicators.SR_ZONE_LOOKBACK))
            hits = indicators.find_trendline_breakout_retest(df, [line], atr, match.direction)
            if hits:
                tolerance = indicators.BREAKOUT_RETEST_TOLERANCE_ATR_MULTIPLE * atr
                current_value = line.value_at(window_len - 1)
                return {
                    "breakout_level": match.neckline,
                    "retest_low": current_value - tolerance,
                    "retest_high": current_value + tolerance,
                }
        return {"breakout_level": match.neckline, "retest_low": None, "retest_high": None}

    if match.pattern_kind in ("top_bottom", "hs"):
        retest = _check_neckline_retest(df, match, atr)
        return {
            "breakout_level": match.neckline,
            "retest_low": retest[0] if retest else None,
            "retest_high": retest[1] if retest else None,
        }

    return {"breakout_level": match.neckline, "retest_low": None, "retest_high": None}
```

- [ ] **Step 2: Verifieer met een throwaway script**

```bash
cat > /tmp/claude-0/-home-user-Trade/scratchpad/test_patterns_entry_options.py << 'EOF'
import sys
sys.path.insert(0, "/home/user/Trade")
import pandas as pd
from app import patterns

# top_bottom-patroon: nek op 98, doorbraak op index 30, prijs is sindsdien
# teruggekomen tot dichtbij 98 (retest) zonder terug onder de nek te sluiten.
n = 40
closes = [100.0] * 30 + [99.5, 99.0, 98.5, 98.2, 98.4, 98.6, 99.0, 99.5, 100.0, 100.5]
df = pd.DataFrame({
    "open": closes, "close": closes,
    "high": [c + 0.2 for c in closes], "low": [c - 0.2 for c in closes],
    "volume": [1000.0] * n,
})
match = patterns.PatternMatch(
    name="double bottom", direction="long", neckline=98.0, extreme=90.0,
    target=106.0, stop_loss=89.5, confirmed_index=29, pattern_kind="top_bottom",
)
options = patterns.find_entry_options(df, match, atr=1.0)
print("opties:", options)
assert options["breakout_level"] == 98.0
assert options["retest_low"] is not None, "verwacht een geldige retest in deze synthetische reeks"
assert options["retest_low"] < 98.0 < options["retest_high"]
print("OK")
EOF
python3 /tmp/claude-0/-home-user-Trade/scratchpad/test_patterns_entry_options.py
```

Expected: `OK` aan het eind.

- [ ] **Step 3: Commit**

```bash
git add app/patterns.py
git commit -m "Patroonherkenning: twee entry-opties (uitbraak + retest)"
```

---

### Task 5: Schema, migratie en repo.py

**Files:**
- Modify: `app/schema.sql`
- Modify: `app/db.py`
- Modify: `app/repo.py`

**Interfaces:**
- Produces: `repo.insert_signal` accepteert nu ook `"pattern_name"` in de
  data-dict, `repo.get_pattern_key(coin) -> Optional[str]`,
  `repo.set_pattern_key(coin, key) -> None`. `_JOURNAL_SELECT` levert
  voortaan ook `pattern_name`. Gebruikt door Task 6, Task 7, Task 8.

- [ ] **Step 1: `app/schema.sql` — nieuwe kolommen**

In de `signals`-tabel, direct na de `pass_pct`-kolom (rond regel 205,
zoek op `pass_pct REAL,`):

```sql
    pass_pct REAL,
    -- Naam van het herkende chart-patroon (bijv. "head & shoulders",
    -- "rising wedge"), alleen gezet als trade_type = 'patroon'. Puur
    -- weergave, telt niet mee in enige berekening — de entry/stop/take
    -- van het signaal zelf zijn al op het patroon gebaseerd op het
    -- moment van aanmaken (zie app/patterns.py).
    pattern_name TEXT,
```

In de `coins`-tabel, direct na `last_trendline_retest_key TEXT` (rond
regel 153):

```sql
    last_trendline_retest_key TEXT,
    -- Dedup voor de patroon-melding (app/market_scanner.py):
    -- "richting:patroonnaam:neckline" van het laatst gemelde patroon voor
    -- deze coin. Zelfde soort dedup als last_breakout_retest_key/
    -- last_trendline_retest_key hierboven.
    last_pattern_key TEXT
```

(Let op: verwijder de komma achter de oude laatste regel
`last_trendline_retest_key TEXT` en zet die komma nu achter de nieuwe
regel ervoor, `last_pattern_key TEXT` blijft de laatste kolom zonder komma
vóór de sluitende `);`.)

- [ ] **Step 2: `app/db.py` — idempotente migratie**

Bij `existing_signals` (rond regel 197-210), voeg toe:

```python
    if "pattern_name" not in existing_signals:
        conn.execute("ALTER TABLE signals ADD COLUMN pattern_name TEXT")
```

Bij `existing_coins` (rond regel 228-231), voeg toe:

```python
    if "last_pattern_key" not in existing_coins:
        conn.execute("ALTER TABLE coins ADD COLUMN last_pattern_key TEXT")
```

- [ ] **Step 3: `app/repo.py` — `insert_signal`, `get/set_pattern_key`, `_JOURNAL_SELECT`**

In `insert_signal`'s `fields`-lijst (rond regel 905-911), voeg
`"pattern_name"` toe:

```python
    fields = [
        "message_id", "coin", "direction", "category", "price", "rsi", "macd",
        "macd_signal", "volume_ratio", "ema9", "ema21", "atr", "atr_avg20", "adx",
        "technical_confirmed", "pass_pct", "hard_gates_ok", "confidence", "reason", "stop_loss", "take_profit",
        "context_note", "is_practice", "plain_explanation", "trade_type", "nearest_sr_zone_price",
        "suggested_entry_low", "suggested_entry_high", "pattern_name",
    ]
```

Direct na `set_trendline_retest_key` (rond regel 755-759), voeg toe:

```python
def get_pattern_key(coin: str) -> Optional[str]:
    with db.session() as conn:
        row = conn.execute(
            "SELECT last_pattern_key FROM coins WHERE symbol = ?", (coin.upper(),),
        ).fetchone()
        return row["last_pattern_key"] if row else None


def set_pattern_key(coin: str, key: str) -> None:
    with db.session() as conn:
        conn.execute(
            "UPDATE coins SET last_pattern_key = ? WHERE symbol = ?", (key, coin.upper()),
        )
```

In `_JOURNAL_SELECT` (rond regel 1112-1113), voeg `pattern_name` toe naast
`trade_type`:

```python
        s.coin AS coin, s.direction AS direction, s.category AS category,
        s.trade_type AS trade_type, s.pattern_name AS pattern_name,
```

- [ ] **Step 4: Verifieer met een throwaway script tegen een scratch-database**

```bash
rm -f /tmp/scratch_patterns.db
DATABASE_PATH=/tmp/scratch_patterns.db python3 -c "
from app import db, repo, security
db.init_db()
uid = repo.create_user('t', security.hash_password('wachtwoord123'), 1000.0, 1.0)

sid = repo.insert_signal({
    'message_id': None, 'coin': 'ETH', 'direction': 'short',
    'category': 'day_trading', 'trade_type': 'patroon', 'pattern_name': 'head & shoulders',
    'price': 3000.0, 'rsi': 50.0, 'macd': 0.0, 'macd_signal': 0.0,
    'volume_ratio': 1.0, 'ema9': 3000.0, 'ema21': 3000.0, 'atr': 30.0,
    'atr_avg20': 28.0, 'adx': 20.0,
    'technical_confirmed': 1, 'pass_pct': None, 'hard_gates_ok': 1,
    'confidence': 'patroon bevestigd', 'reason': 'test',
    'stop_loss': 3100.0, 'take_profit': 2800.0,
    'context_note': None, 'is_practice': 0, 'plain_explanation': None,
})
sig = repo.get_signal(sid)
assert sig['pattern_name'] == 'head & shoulders', sig
print('insert_signal met pattern_name OK')

assert repo.get_pattern_key('ETH') is None
repo.set_pattern_key('ETH', 'short:head & shoulders:3100.00')
assert repo.get_pattern_key('ETH') == 'short:head & shoulders:3100.00'
print('get/set_pattern_key OK')

eid = repo.create_journal_entry(sid, uid, None)
rows = repo.list_signalen_for_user(uid)
assert rows[0]['pattern_name'] == 'head & shoulders', rows[0]
print('_JOURNAL_SELECT levert pattern_name OK')
"
```

Expected: drie `... OK`-regels, geen exception.

- [ ] **Step 5: Commit**

```bash
git add app/schema.sql app/db.py app/repo.py
git commit -m "Patroonherkenning: schema/migratie + repo.py (pattern_name, last_pattern_key)"
```

---

### Task 6: `signal_processor.py` — gedeelde fan-out-helper

**Files:**
- Modify: `app/signal_processor.py`

**Interfaces:**
- Consumes: bestaande `_resolve_signal_risk`, `repo.create_journal_entry`,
  `repo.update_journal_levels`, `repo.mark_journal_telegram_sent`,
  `push_notify.send_push`, `push_notify.is_quiet_now`, `risk.compute_position_size`,
  `repo.get_active_evaluation`, `repo.total_open_risk_eur_for_evaluation`,
  `risk.compute_eval_daily_budget_remaining`.
- Produces: `async def _fanout_confirmed_signal(signal_id, coin, direction, entry_price, stop_loss, take_profit, title, make_body) -> None`,
  publieke re-export `fanout_confirmed_signal = _fanout_confirmed_signal`
  zodat `market_scanner.py` (ander module) 'm kan importeren zonder een
  "private" underscore-naam over de modulegrens te halen.
  Gebruikt door Task 7 (`market_scanner._check_chart_patterns`) en
  hergebruikt binnen `run_swing_check` zelf.

- [ ] **Step 1: Voeg de gedeelde helper toe, vlak vóór `run_swing_check`**

```python
from typing import Callable

...

async def _fanout_confirmed_signal(
    signal_id: int, coin: str, direction: str, entry_price: float,
    stop_loss: float, take_profit: float, title: str,
    make_body: Callable[[float, float, bool], str],
) -> None:
    """Deelt een al-bevestigd signaal (geen gepoold percentage, altijd
    gemeld) met alle gebruikers: journaalregel + pushmelding per gebruiker,
    met per-gebruiker evaluatie-sizing en stop-cap. Gedeeld tussen
    run_swing_check (swing) en market_scanner._check_chart_patterns
    (patroon) — beide zijn "autonoom bevestigd"-signalen met identieke
    fan-out-logica, alleen titel en berichttekst verschillen per soort.
    make_body ontvangt de EFFECTIEVE (mogelijk ingeperkte) stop/take voor
    deze ene gebruiker en of die stop gecapt werd, zodat de melding altijd
    de daadwerkelijke cijfers voor deze gebruiker toont."""
    for user in repo.list_users():
        active_eval_for_display = repo.get_active_evaluation(user["id"])
        risk_eur, evaluation_id, cost_rate, effective_stop_loss, effective_take_profit = _resolve_signal_risk(
            user, direction, entry_price, stop_loss, take_profit,
        )
        stop_was_capped = effective_stop_loss != stop_loss
        if stop_was_capped and (
            (direction == "long" and effective_stop_loss >= entry_price)
            or (direction == "short" and effective_stop_loss <= entry_price)
        ):
            effective_stop_loss, effective_take_profit = stop_loss, take_profit
            stop_was_capped = False
        position_size = (
            risk.compute_position_size(risk_eur, entry_price, effective_stop_loss, cost_rate=cost_rate)
            if risk_eur is not None else None
        )
        entry_id = repo.create_journal_entry(
            signal_id, user["id"], risk_eur, evaluation_id=evaluation_id, position_size=position_size,
        )
        if stop_was_capped:
            repo.update_journal_levels(entry_id, user["id"], effective_stop_loss, effective_take_profit, None)

        eval_blocked_note = None
        if active_eval_for_display and evaluation_id is None:
            eval_blocked_note = (
                "Dagbudget of drawdown-ruimte van je evaluatie is (bijna) op, "
                "deze trade telt niet mee voor je evaluatie."
            )

        quiet = push_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
        try:
            body = make_body(effective_stop_loss, effective_take_profit, stop_was_capped)
            if eval_blocked_note:
                body += f"\n{eval_blocked_note}"
            await push_notify.send_push(user["id"], title, body, f"/coins/{coin}", silent=quiet)
            repo.mark_journal_telegram_sent(entry_id)
        except Exception:
            logger.exception("Melding voor %s naar gebruiker %s is mislukt", coin, user["username"])


fanout_confirmed_signal = _fanout_confirmed_signal
```

- [ ] **Step 2: Herschrijf `run_swing_check`'s fan-out-lus om de helper te gebruiken**

Vervang het hele blok `for user in repo.list_users(): ...` (regels 495-557,
zoals hierboven getoond in de context) door:

```python
    signal_id = repo.insert_signal(signal_data)

    def _swing_body(effective_stop_loss: float, effective_take_profit: float, stop_was_capped: bool) -> str:
        pattern_note = f" ({watch['pattern_name']})" if watch["pattern_name"] else ""
        return (
            f"Vanuit bewaakt niveau {watch['price_level']:.4f}{pattern_note} · "
            f"Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}"
        )

    await _fanout_confirmed_signal(
        signal_id, coin, direction, ind_4h.price, stop_take.stop_loss, stop_take.take_profit,
        title=f"{push_notify.coin_symbol(coin)} {coin} {direction}, swing-kans",
        make_body=_swing_body,
    )
```

De rest van `run_swing_check` (alles vóór `signal_id = repo.insert_signal(signal_data)`,
dus de candle-ophaling, factoren, `stop_take`-berekening) blijft
ongewijzigd.

- [ ] **Step 3: Verifieer dat `run_swing_check` nog steeds hetzelfde gedrag heeft**

```bash
python3 -c "
import sys; sys.path.insert(0, '/home/user/Trade')
import ast
ast.parse(open('app/signal_processor.py').read())
print('syntax OK')
from app import signal_processor
assert hasattr(signal_processor, '_fanout_confirmed_signal')
assert hasattr(signal_processor, 'fanout_confirmed_signal')
assert callable(signal_processor.run_swing_check)
print('imports OK')
"
```

Expected: `syntax OK` en `imports OK`, geen exception.

- [ ] **Step 4: Commit**

```bash
git add app/signal_processor.py
git commit -m "Patroonherkenning: gedeelde fan-out-helper (swing + patroon)"
```

---

### Task 7: `market_scanner.py` — koppeling

**Files:**
- Modify: `app/market_scanner.py`

**Interfaces:**
- Consumes: `app.patterns.find_reversal_patterns`,
  `app.patterns.classify_channel_wedge`, `app.patterns.find_divergence`,
  `app.patterns.find_entry_options`, `indicators.detect_trendlines`,
  `signal_processor.fanout_confirmed_signal`, `repo.get_pattern_key`,
  `repo.set_pattern_key`, `repo.insert_signal`, `risk.compute_stop_take`
  (alleen voor `divergence`).

- [ ] **Step 1: Voeg `_check_chart_patterns` toe, na `_check_trendline_retest`**

```python
from app import patterns
from app.signal_processor import fanout_confirmed_signal

...

# Dedup-marge voor de patroon-melding: hoe dicht de neckline/stop van een
# nieuw gevonden patroon bij die van het laatst gemelde patroon voor deze
# coin+richting moet liggen om als "hetzelfde patroon" te tellen. Zelfde
# aanpak als TRENDLINE_DEDUP_ATR_MULTIPLE hierboven.
PATTERN_DEDUP_ATR_MULTIPLE = 1.0


def _same_pattern(existing_key: Optional[str], direction: str, match, atr: float) -> bool:
    if not existing_key:
        return False
    try:
        prev_direction, prev_name, prev_neckline_s = existing_key.split(":")
        prev_neckline = float(prev_neckline_s)
    except (ValueError, AttributeError):
        return False
    if prev_direction != direction or prev_name != match.name or not atr:
        return False
    return abs(prev_neckline - match.neckline) <= PATTERN_DEDUP_ATR_MULTIPLE * atr


async def _check_chart_patterns(coin: str, df, ind) -> None:
    """Los van de dagtrading-richting van deze scan-cyclus: een chart-
    patroon (top/bottom, head & shoulders, kanaal/wedge, divergence) heeft
    zijn EIGEN richting uit de vorm zelf, niet uit ind.ema9/ind.ema21. Geen
    percentage-toets, geen harde eisen (R:R/dagtrend/BTC-trend) — een
    bevestigd patroon is zelf de bevestiging, zie
    docs/superpowers/specs/2026-09-22-patroonherkenning-design.md."""
    trendlines = indicators.detect_trendlines(df, ind.atr)
    window_len = len(df.tail(indicators.SR_ZONE_LOOKBACK))

    candidates: list = []
    candidates += patterns.find_reversal_patterns(df)
    wedge = patterns.classify_channel_wedge(trendlines, window_len, ind.atr)
    if wedge:
        candidates.append(wedge)
    divergence = patterns.find_divergence(df)
    if divergence:
        candidates.append(divergence)

    if not candidates:
        return
    match = max(candidates, key=lambda m: m.confirmed_index)

    key = f"{match.direction}:{match.name}:{match.neckline:.8f}"
    if _same_pattern(repo.get_pattern_key(coin), match.direction, match, ind.atr):
        return

    entry_options = patterns.find_entry_options(df, match, ind.atr, trendlines=trendlines)

    if match.stop_loss is not None and match.target is not None:
        stop_loss, take_profit = match.stop_loss, match.target
    else:
        # divergence: geen eigen gemeten beweging, terugval op de
        # bestaande ATR-methode (zie de spec, sectie "Stop/take").
        stop_take = risk.compute_stop_take(match.direction, ind.price, ind.atr)
        stop_loss, take_profit = stop_take.stop_loss, stop_take.take_profit

    # suggested_entry_low/high zijn bestaande kolommen (van een eerder
    # plan, daar gevuld met de dagtrading-entry-zone-suggestie) — hier
    # hergebruikt voor exact hetzelfde soort informatie (een optionele,
    # tweede entry-band naast de live prijs), in plaats van twee nieuwe
    # kolommen voor hetzelfde concept. Task 8 leest ze uit voor de
    # "Retest: ..."-regel op de kaart. None zolang er nog geen retest is.
    signal_data = {
        "message_id": None, "coin": coin, "direction": match.direction,
        "category": "day_trading", "trade_type": "patroon", "pattern_name": match.name,
        "price": ind.price, "rsi": ind.rsi, "macd": ind.macd, "macd_signal": ind.macd_signal,
        "volume_ratio": ind.volume_ratio, "ema9": ind.ema9, "ema21": ind.ema21,
        "atr": ind.atr, "atr_avg20": ind.atr_avg20, "adx": ind.adx,
        "technical_confirmed": 1, "pass_pct": None, "hard_gates_ok": 1,
        "confidence": "patroon bevestigd",
        "reason": f"Patroon: {match.name}, richting {match.direction}",
        "stop_loss": stop_loss, "take_profit": take_profit,
        "context_note": None, "is_practice": 0, "plain_explanation": None,
        "suggested_entry_low": entry_options["retest_low"],
        "suggested_entry_high": entry_options["retest_high"],
    }
    signal_id = repo.insert_signal(signal_data)

    def _pattern_body(effective_stop_loss: float, effective_take_profit: float, stop_was_capped: bool) -> str:
        retest_note = (
            f" · Retest {entry_options['retest_low']:.4f}–{entry_options['retest_high']:.4f}"
            if entry_options["retest_low"] is not None else ""
        )
        return (
            f"Uitbraak {entry_options['breakout_level']:.4f}{retest_note} · "
            f"Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}"
        )

    await fanout_confirmed_signal(
        signal_id, coin, match.direction, ind.price, stop_loss, take_profit,
        title=f"{push_notify.coin_symbol(coin)} {coin} {match.direction}, {match.name}",
        make_body=_pattern_body,
    )
    repo.set_pattern_key(coin, key)
```

- [ ] **Step 2: Roep de nieuwe check aan in `scan_market`**

Na de bestaande regel `await _check_trendline_retest(coin, direction, df, ind)`
(rond regel 222):

```python
            await _check_breakout_retest(coin, direction, df, ind)
            await _check_trendline_retest(coin, direction, df, ind)
            await _check_chart_patterns(coin, df, ind)
```

(Let op: `_check_chart_patterns` krijgt GEEN `direction`-argument — een
patroon bepaalt zijn eigen richting, zie de docstring hierboven.)

- [ ] **Step 3: Verifieer met een throwaway script (geen netwerk nodig, alleen de detectie- en dedup-logica)**

```bash
rm -f /tmp/scratch_market_scanner.db
cat > /tmp/claude-0/-home-user-Trade/scratchpad/test_check_chart_patterns.py << 'EOF'
import asyncio
import sys
sys.path.insert(0, "/home/user/Trade")
import numpy as np
import pandas as pd

import os
os.environ["DATABASE_PATH"] = "/tmp/scratch_market_scanner.db"

from app import db, repo, security, indicators
db.init_db()
repo.create_user("t", security.hash_password("wachtwoord123"), 1000.0, 1.0)
with db.session() as conn:
    conn.execute(
        "INSERT INTO coins (symbol, market, added_at, active) VALUES (?, ?, ?, 1)",
        ("ETH", "ETH/USDT", db.now_iso()),
    )

from app import market_scanner

n = 80
closes = [100.0] * 10
closes += list(np.linspace(100, 90, 8))
closes += list(np.linspace(90, 98, 6))
closes += list(np.linspace(98, 91, 8))
closes += list(np.linspace(91, 100, 10))
closes += [102.0] * (n - len(closes))
closes = closes[:n]
df = pd.DataFrame({
    "open": closes, "close": closes,
    "high": [c + 0.3 for c in closes], "low": [c - 0.3 for c in closes],
    "volume": [1000.0] * n,
})
ind = indicators.compute_indicators(df)

asyncio.run(market_scanner._check_chart_patterns("ETH", df, ind))

signals = [dict(r) for r in db.session().__enter__().execute("SELECT * FROM signals WHERE coin = 'ETH'")]
print(f"aantal signalen na 1e check: {len(signals)}")
assert len(signals) == 1, signals
assert signals[0]["trade_type"] == "patroon"
assert signals[0]["pattern_name"] is not None
print("pattern_name:", signals[0]["pattern_name"])

# Tweede aanroep met dezelfde candles: dedup moet een tweede signaal
# voorkomen.
asyncio.run(market_scanner._check_chart_patterns("ETH", df, ind))
signals_after = [dict(r) for r in db.session().__enter__().execute("SELECT * FROM signals WHERE coin = 'ETH'")]
assert len(signals_after) == 1, "dedup had een 2e melding moeten voorkomen"
print("dedup OK")
EOF
python3 /tmp/claude-0/-home-user-Trade/scratchpad/test_check_chart_patterns.py
```

Expected: `aantal signalen na 1e check: 1`, een `pattern_name`-regel, en
`dedup OK`. Als de synthetische candles toevallig geen enkel patroon
opleveren (0 signalen), verklein `PEAK_TOLERANCE_PCT` niet — pas in dat
geval de synthetische reeks in het script aan (bijv. de twee dalen exacter
gelijk maken), niet de productiecode, en herhaal Step 3.

- [ ] **Step 4: Commit**

```bash
git add app/market_scanner.py
git commit -m "Patroonherkenning: marktscan-koppeling (_check_chart_patterns)"
```

---

### Task 8: UI — patroon-badge, dubbele entry, reason-popup

**Files:**
- Modify: `web/templates/_macros.html`
- Modify: `web/static/style.css`

**Interfaces:**
- Consumes: `entry.trade_type`, `entry.pattern_name`, `entry.suggested_entry_low`/`high`
  (bestaand veld, hergebruikt voor de retest-band — zie Step 1) uit de
  journal-select (Task 5).

- [ ] **Step 1: `signal_card`-macro — patroon-badge in plaats van percentage**

In `web/templates/_macros.html`, huidige blok (na de Task uit de vorige
sessie die al een `swing`-badge toevoegde):

```html
    {% if entry.pass_pct is not none %}
    <span class="pass-pct">{{ "%.0f"|format(entry.pass_pct) }}%</span>
    {% elif entry.trade_type == "swing" %}
    <span class="badge badge-swing" title="Bevestigd op een bewaakt steun/weerstand-niveau, geen gepoold percentage">swing</span>
    {% endif %}
```

Wordt:

```html
    {% if entry.pass_pct is not none %}
    <span class="pass-pct">{{ "%.0f"|format(entry.pass_pct) }}%</span>
    {% elif entry.trade_type == "swing" %}
    <span class="badge badge-swing" title="Bevestigd op een bewaakt steun/weerstand-niveau, geen gepoold percentage">swing</span>
    {% elif entry.trade_type == "patroon" %}
    <span class="badge badge-swing" title="Chart-patroon herkend door HesPulse, geen gepoold percentage">{{ entry.pattern_name }}</span>
    {% endif %}
```

(Hergebruikt bewust dezelfde `badge-swing`-CSS-klasse: zelfde soort
signaal — bevestigd, geen percentage — verdient dezelfde visuele taal, een
aparte kleur zou een onderscheid suggereren dat er niet is.)

- [ ] **Step 2: Entry-regel met uitbraak + retest**

De bestaande "Mogelijke betere entry"-regel is dagtrading-specifiek
(`entry.suggested_entry_low`/`high`, alleen gezet bij `trade_type ==
"day_trading"`). Voeg er direct na een patroon-specifieke regel aan toe:

```html
  {% if entry.suggested_entry_low is defined and entry.suggested_entry_low is not none %}
  <div class="signal-card-entry-zone muted">
    Mogelijk betere entry: {{ "%.4f"|format(entry.suggested_entry_low) }}–{{ "%.4f"|format(entry.suggested_entry_high) }}
  </div>
  {% endif %}
```

wordt (nieuwe `{% elif %}`-tak toegevoegd voor `trade_type == "patroon"`,
die leest `entry.suggested_entry_low`/`high` op dezelfde manier — zie de
noot hieronder):

```html
  {% if entry.trade_type == "patroon" and entry.suggested_entry_low is defined and entry.suggested_entry_low is not none %}
  <div class="signal-card-entry-zone muted">
    Retest: {{ "%.4f"|format(entry.suggested_entry_low) }}–{{ "%.4f"|format(entry.suggested_entry_high) }}
  </div>
  {% elif entry.suggested_entry_low is defined and entry.suggested_entry_low is not none %}
  <div class="signal-card-entry-zone muted">
    Mogelijk betere entry: {{ "%.4f"|format(entry.suggested_entry_low) }}–{{ "%.4f"|format(entry.suggested_entry_high) }}
  </div>
  {% endif %}
```

**Noot:** `entry.suggested_entry_low`/`high` zijn bestaande kolommen op
`signals` (van een eerder plan, daar gevuld met de dagtrading-entry-zone-
suggestie) — Task 7 vult ze voor een patroon-signaal al met
`entry_options["retest_low"]`/`entry_options["retest_high"]` (kan `None`
zijn, dat is toegestaan), hergebruikt voor exact hetzelfde soort
informatie in plaats van twee nieuwe kolommen voor hetzelfde concept. Geen
verdere actie hier nodig, alleen de template leest ze nu ook voor
`trade_type == "patroon"`.

En het "uitbraakniveau"-getal (`entry_options["breakout_level"]`) hoort
als apart, altijd-zichtbaar stukje tekst naast de bestaande
`signal-card-levels`-regel — pas die regel aan:

```html
  <div class="signal-card-levels">
    Entry {{ "%.4f"|format(entry.price) if entry.price is not none else "-" }} ·
    Stop {{ "%.4f"|format(entry.stop_loss) if entry.stop_loss else "-" }} ·
    Take profit {{ "%.4f"|format(entry.take_profit) if entry.take_profit else "-" }}
  </div>
```

Deze regel blijft ONGEWIJZIGD (Entry/Stop/Take profit is universeel voor
elk signaaltype, ook patroon — `entry.price` is voor een patroon-signaal
al de live prijs op het moment van melden, `Entry` in deze regel is dus
feitelijk het uitbraak-moment, geen aparte "Uitbraak"-regel nodig).

- [ ] **Step 3: `reason_popup`-variant voor `trade_type == "patroon"`**

In `reason_popup` (huidige `{% if entry.trade_type != 'swing' %}`-tak),
voeg een `patroon`-tak toe:

```html
{% macro reason_popup(entry) %}
{% if entry.plain_explanation %}<p class="plain-explanation">{{ entry.plain_explanation }}</p>{% endif %}
{% if entry.trade_type == "swing" %}
<p class="muted reason-legend">Twee losse toetsen, geen gecombineerd cijfer: dit is nog niet gevalideerd op deze tijdshorizon zoals de day-trading-toets dat wel is.</p>
{% elif entry.trade_type == "patroon" %}
<p class="muted reason-legend">Herkend chart-patroon, geen gepoold percentage: entry/stop/take zijn gebaseerd op de gemeten beweging van het patroon zelf.</p>
{% else %}
<p class="muted reason-legend">De vinkjes hieronder zijn nu gemeten (RSI, volume, trend, momentum). De slagingskans hierboven is een inschatting op basis van eerdere trades, geen garantie voor deze trade.</p>
{% endif %}
{{ reason_factors(entry) }}
{% endmacro %}
```

(Verandert de bestaande `{% if entry.trade_type != 'swing' %}` in een
`{% if/elif/else %}`-drieluik — controleer dat de bestaande swing-tak
letterlijk hetzelfde blijft, alleen de structuur verandert.)

`reason_factors` hoeft niet aangepast: `entry.reason` voor een patroon-
signaal is een gewone platte string (`"Patroon: ..., richting ..."`, geen
`" | "`-gescheiden factoren zoals dagtrading, geen `"\n"`-gescheiden
groepen zoals swing) — die macro splitst op `" | "` in de `else`-tak
(niet-swing), en toont dan gewoon de hele string als één "factor"-regel
zonder ✓/✗-prefix (`factor-bad`-klasse, want de string begint niet met
"✓" — dat is een cosmetisch detail, geen functionele bug, en buiten scope
van deze taak; als het er storend uitziet in Step 5's Playwright-check,
verhelp het dan met een eigen `{% elif entry.trade_type == "patroon"
%}`-tak in `reason_factors` die `entry.reason` gewoon als platte
`<p class="muted">`-tekst toont in plaats van op `" | "` te splitsen).

- [ ] **Step 4: CSS — geen nieuwe klasse nodig**

`badge-swing` en `signal-card-entry-zone` bestaan al (zie
`web/static/style.css`, regels rond de eerdere swing/entry-zone-taken).
Geen wijziging nodig in dit bestand voor Task 8 — deze stap is hier alleen
om te bevestigen dat er GEEN CSS-taak resteert, niet om iets te doen.

- [ ] **Step 5: Handmatige Playwright-verificatie**

```bash
rm -f /tmp/scratch_ui_patterns.db
DATABASE_PATH=/tmp/scratch_ui_patterns.db python3 -c "
from app import db, repo, security
db.init_db()
uid = repo.create_user('testuser', security.hash_password('wachtwoord123'), 1000.0, 1.0)
sid = repo.insert_signal({
    'message_id': None, 'coin': 'ETH', 'direction': 'short',
    'category': 'day_trading', 'trade_type': 'patroon', 'pattern_name': 'head & shoulders',
    'price': 3000.0, 'rsi': 50.0, 'macd': 0.0, 'macd_signal': 0.0,
    'volume_ratio': 1.0, 'ema9': 3000.0, 'ema21': 3000.0, 'atr': 30.0,
    'atr_avg20': 28.0, 'adx': 20.0,
    'technical_confirmed': 1, 'pass_pct': None, 'hard_gates_ok': 1,
    'confidence': 'patroon bevestigd', 'reason': 'Patroon: head & shoulders, richting short',
    'stop_loss': 3100.0, 'take_profit': 2800.0,
    'context_note': None, 'is_practice': 0, 'plain_explanation': None,
    'suggested_entry_low': 2990.0, 'suggested_entry_high': 3010.0,
})
repo.create_journal_entry(sid, uid, None)
print('signal', sid)
"
DATABASE_PATH=/tmp/scratch_ui_patterns.db nohup .venv/bin/uvicorn web.main:app --port 8124 > /tmp/uvicorn_patterns.log 2>&1 &
sleep 3
NODE_PATH=/opt/node22/lib/node_modules node -e "
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage({ viewport: { width: 390, height: 844 } });
  await page.goto('http://127.0.0.1:8124/login');
  await page.fill('input[name=\"username\"]', 'testuser');
  await page.fill('input[name=\"password\"]', 'wachtwoord123');
  await page.click('button[type=\"submit\"]');
  await page.waitForLoadState('networkidle');
  const resp = await page.goto('http://127.0.0.1:8124/signalen');
  await page.waitForLoadState('networkidle');
  console.log('status', resp.status());
  const badgeText = await page.locator('.badge-swing').first().innerText();
  console.log('badge:', badgeText);
  const entryZone = await page.locator('.signal-card-entry-zone').first().innerText();
  console.log('entry-zone:', entryZone);
  await page.screenshot({ path: '/tmp/patroon_signalen.png', fullPage: true });
  await browser.close();
})();
"
kill %1 2>/dev/null
```

Expected: `status 200`, `badge: HEAD & SHOULDERS` (CSS uppercase), en
`entry-zone: Retest: 2990.0000–3010.0000`. Bekijk
`/tmp/patroon_signalen.png` (via de Read tool) om te bevestigen dat de
kaart er goed uitziet, geen overlappende tekst.

- [ ] **Step 6: Commit**

```bash
git add web/templates/_macros.html
git commit -m "Patroonherkenning: patroon-badge + retest-entry op signal_card"
```

---

### Task 9: Validatiescript voor kanaal/wedge en divergence

**Files:**
- Create: `scripts/backtest_pattern_detection.py`

**Interfaces:**
- Consumes: `app.patterns.classify_channel_wedge`,
  `app.patterns.find_divergence`, `indicators.detect_trendlines`,
  `indicators.compute_indicators`, `exchange.fetch_ohlcv`.

- [ ] **Step 1: Schrijf het validatiescript**

Zelfde bewijslast-aanpak als `research_reversal_patterns.py`
(`classify_outcome`): loopt een schuivend venster over historische
candles, detecteert per venster of er een kanaal/wedge of divergence
staat, en meet — net als bij de reversal-patronen — of het target binnen
`LOOKFORWARD_CANDLES` geraakt werd, ongeldig werd, of zijwaarts liep.

```python
"""Onderzoek: hoe vaak volgt de kanaal/wedge- en divergence-detectie uit
app/patterns.py daadwerkelijk de richting die het patroon impliceert,
tegen historische Binance-data. Zelfde bewijslast-aanpak als
scripts/research_reversal_patterns.py: geen patroon wordt vertrouwd op een
tekstboek-claim (het "70/30" van het patronenblad), alleen op wat
HesPulse's eigen historische data laat zien.

In tegenstelling tot research_reversal_patterns.py (dat patronen op de
VOLLEDIGE historische reeks in één keer zoekt) schuift dit script een
venster van SR_ZONE_LOOKBACK candles over de geschiedenis: kanaal/wedge/
divergence-detectie is venster-gebaseerd (indicators.detect_trendlines
werkt altijd op de laatste SR_ZONE_LOOKBACK candles), dus alleen zo'n
schuivend venster geeft een realistische "wat had HesPulse op moment X
gezien"-meting.

Kost tijd: haalt maanden tot jaren candles op bij de exchange, en schuift
daar per candle doorheen.

Draai met: python3 scripts/backtest_pattern_detection.py --coin BTC --timeframe 4h --years 1
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import exchange, indicators, patterns

LOOKFORWARD_CANDLES = 20
SIDEWAYS_ATR_MULT = 1.0

# Elke Nde candle een nieuw venster nemen, niet elke candle: detect_trendlines
# is duur (O(pivots^2) kandidaat-lijnen) en een patroon verandert niet
# candle-voor-candle. 5 candles (bij 4u dus elke 20 uur) is vaak genoeg om
# elk patroon te vangen zonder het onderzoek onnodig te vertragen.
STEP_CANDLES = 5


def _atr(df, window: int = 14):
    high, low, close = df["high"], df["low"], df["close"]
    prev_close = close.shift(1)
    import pandas as pd
    tr = pd.concat([
        high - low, (high - prev_close).abs(), (low - prev_close).abs(),
    ], axis=1).max(axis=1)
    return tr.rolling(window).mean()


def classify_outcome(df, match, atr_series, start_offset: int) -> str:
    """Zelfde soort target/invalidated/zijwaarts-classificatie als
    research_reversal_patterns.py, hier op de absolute candle-index in de
    volledige (niet-geschoven) df: start_offset + match.confirmed_index."""
    abs_index = start_offset + match.confirmed_index
    window = df.iloc[abs_index + 1:abs_index + 1 + LOOKFORWARD_CANDLES]
    if window.empty or match.target is None or match.stop_loss is None:
        return "onbekend"
    band = SIDEWAYS_ATR_MULT * atr_series.iloc[abs_index] if abs_index < len(atr_series) else 0.0
    invalidate_level = match.neckline
    for _, row in window.iterrows():
        if match.direction == "short":
            if row["low"] <= match.target:
                return "target_hit"
            if row["close"] > invalidate_level + band:
                return "invalidated"
        else:
            if row["high"] >= match.target:
                return "target_hit"
            if row["close"] < invalidate_level - band:
                return "invalidated"
    return "zijwaarts"


def run(coin: str, timeframe: str, years: float) -> None:
    candles_per_year = {"4h": 6 * 365, "1d": 365}[timeframe]
    limit = int(candles_per_year * years)
    full_df = exchange.fetch_ohlcv(coin, timeframe=timeframe, limit=limit)
    atr_series = _atr(full_df)

    by_name: dict[str, list[str]] = {}
    lookback = indicators.SR_ZONE_LOOKBACK
    start = lookback
    while start < len(full_df) - LOOKFORWARD_CANDLES:
        window = full_df.iloc[start - lookback:start].reset_index(drop=True)
        atr_now = atr_series.iloc[start - 1] if start - 1 < len(atr_series) else None
        if atr_now and atr_now == atr_now:  # niet NaN
            trendlines = indicators.detect_trendlines(window, atr_now)
            match = patterns.classify_channel_wedge(trendlines, len(window), atr_now)
            if match:
                outcome = classify_outcome(full_df, match, atr_series, start - lookback)
                by_name.setdefault(match.name, []).append(outcome)

            div_match = patterns.find_divergence(window)
            if div_match:
                # divergence heeft geen target/stop_loss, dus classify_outcome
                # kan hier niet direct op toegepast worden — meet in plaats
                # daarvan of de prijs binnen LOOKFORWARD_CANDLES in de
                # gemelde richting bewoog (eenvoudige richtings-tref-check).
                abs_index = (start - lookback) + div_match.confirmed_index
                fwd = full_df.iloc[abs_index + 1:abs_index + 1 + LOOKFORWARD_CANDLES]
                if not fwd.empty:
                    moved_right_way = (
                        fwd["close"].iloc[-1] > full_df["close"].iloc[abs_index]
                        if div_match.direction == "long" else
                        fwd["close"].iloc[-1] < full_df["close"].iloc[abs_index]
                    )
                    by_name.setdefault(div_match.name, []).append(
                        "target_hit" if moved_right_way else "invalidated"
                    )
        start += STEP_CANDLES

    print(f"{coin} {timeframe}, {len(full_df)} candles ({years} jaar)\n")
    for name, outcomes in sorted(by_name.items()):
        total = len(outcomes)
        if total == 0:
            continue
        hit = outcomes.count("target_hit")
        invalid = outcomes.count("invalidated")
        sideways = outcomes.count("zijwaarts")
        print(
            f"{name}: {total} keer, target {hit} ({hit / total:.0%}), "
            f"ongeldig {invalid} ({invalid / total:.0%}), zijwaarts {sideways} ({sideways / total:.0%})"
        )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--coin", default="BTC")
    parser.add_argument("--timeframe", default="4h", choices=["4h", "1d"])
    parser.add_argument("--years", type=float, default=1)
    args = parser.parse_args()
    run(args.coin, args.timeframe, args.years)
```

- [ ] **Step 2: Verifieer dat het script importeert (geen netwerk hier)**

```bash
python3 -c "
import sys; sys.path.insert(0, '/home/user/Trade')
import importlib
m = importlib.import_module('scripts.backtest_pattern_detection')
print('import OK, run callable:', callable(m.run))
"
```

Expected: `import OK, run callable: True`.

- [ ] **Step 3: Commit**

```bash
git add scripts/backtest_pattern_detection.py
git commit -m "Patroonherkenning: validatiescript kanaal/wedge + divergence"
```

---

### Task 10: Volledige regressie en push

**Files:** geen nieuwe, alleen verificatie over de hele Fase 1.

- [ ] **Step 1: Syntax-check alle gewijzigde Python-bestanden**

```bash
cd /home/user/Trade && python3 -c "
import ast
for f in ['app/patterns.py', 'app/repo.py', 'app/db.py', 'app/schema.sql'.replace('.sql', '.py') if False else None]:
    pass
for f in ['app/patterns.py', 'app/repo.py', 'app/db.py', 'app/signal_processor.py', 'app/market_scanner.py', 'scripts/research_reversal_patterns.py', 'scripts/backtest_pattern_detection.py']:
    ast.parse(open(f).read())
    print(f, 'OK')
"
```

- [ ] **Step 2: Draai Task 1 t/m 4's throwaway scripts opnieuw achter elkaar**

```bash
for f in test_patterns_reversal test_patterns_wedge test_patterns_divergence test_patterns_entry_options; do
  echo "=== $f ==="
  python3 /tmp/claude-0/-home-user-Trade/scratchpad/$f.py
done
```

Expected: elk script eindigt met `OK`, geen exception.

- [ ] **Step 3: Volledige scratch-database-doorloop: signaal aanmaken, opvragen, tonen**

```bash
rm -f /tmp/scratch_full_regression.db
DATABASE_PATH=/tmp/scratch_full_regression.db python3 -c "
from app import db, repo, security
db.init_db()
uid = repo.create_user('t', security.hash_password('wachtwoord123'), 1000.0, 1.0)
sid = repo.insert_signal({
    'message_id': None, 'coin': 'SOL', 'direction': 'long',
    'category': 'day_trading', 'trade_type': 'patroon', 'pattern_name': 'falling wedge',
    'price': 150.0, 'rsi': 45.0, 'macd': 0.0, 'macd_signal': 0.0,
    'volume_ratio': 1.0, 'ema9': 150.0, 'ema21': 150.0, 'atr': 3.0,
    'atr_avg20': 2.8, 'adx': 18.0,
    'technical_confirmed': 1, 'pass_pct': None, 'hard_gates_ok': 1,
    'confidence': 'patroon bevestigd', 'reason': 'Patroon: falling wedge, richting long',
    'stop_loss': 145.0, 'take_profit': 165.0,
    'context_note': None, 'is_practice': 0, 'plain_explanation': None,
    'suggested_entry_low': 149.0, 'suggested_entry_high': 151.0,
})
eid = repo.create_journal_entry(sid, uid, None)
rows = repo.list_signalen_for_user(uid)
assert len(rows) == 1
assert rows[0]['trade_type'] == 'patroon'
assert rows[0]['pattern_name'] == 'falling wedge'
assert rows[0]['pass_pct'] is None
print('volledige doorloop OK')
"
```

- [ ] **Step 4: Push**

```bash
git log --oneline -12
git push origin claude/crypto-day-trading-alerts-5p8w6v
```

- [ ] **Step 5: Geef de gebruiker de VPS-instructie**

Na het pullen op de VPS: `sudo systemctl restart crypto-bot` (market
scanner draait binnen `main.py`/de Discord-bot-service, niet apart) — geen
`crypto-web`-restart nodig tenzij Task 8's template-wijziging ook meteen
zichtbaar moet zijn (wel aan te raden, `sudo systemctl restart crypto-web
crypto-bot`). Geen migratie-script nodig: `db.py:_migrate()` draait
zichzelf bij de eerstvolgende opstart van beide services.
