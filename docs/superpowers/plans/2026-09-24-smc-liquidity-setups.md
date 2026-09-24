# SMC liquidity setups Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Een vierde, volledig autonome structurele detector in de marktscan
die op 30 minuten (structuurbreuk + liquidity sweep) en 15 minuten
(terugtrek naar een fair value gap/order block-overlap, afwijzing als
trigger) SMC/ICT-stijl liquidity-setups vindt, met een eigen bouwende-
setups-tabel, eigen meldingen en een eigen pagina.

**Architecture:** Vier nieuwe detectie-primitieven in `app/indicators.py`
(structuurbreuk, sweep-vóór-de-breuk, fair value gaps, order blocks,
confluence-zone), een nieuwe `smc_setups`-tabel die een setup volgt van
"bouwend" (zone bekend, nog niet geraakt) tot "compleet" (afgewezen,
wordt een gewoon signaal), een nieuwe detectiefunctie in
`app/market_scanner.py` die binnen de bestaande 20-minuten-scan-cyclus
draait maar buiten de bestaande top-3-structurele-cap om altijd meldt, en
een nieuwe pagina `/smc`.

**Tech Stack:** Python 3, pandas, FastAPI, Jinja2, SQLite.

**Spec:** `docs/superpowers/specs/2026-09-24-smc-liquidity-setups-design.md`

## Global Constraints

- Volledig autonoom, geen Discord-afhankelijkheid — draait binnen de
  bestaande marktscan (`scan_market()`, elke 20 minuten), niet getriggerd
  door een doorgestuurd bericht.
- Tijdshorizon vast: 30 minuten voor structuurbreuk/sweep, 15 minuten
  voor de FVG/order-block/afwijzing. Niet instelbaar.
- Geen nieuwe, snellere scan-timer — hergebruikt de bestaande 20-minuten-
  cyclus.
- Geen ATR, nergens in dit onderdeel: niet voor zone-dedup (percentage-
  marge, `ZONE_DEDUP_PCT`), niet voor stop/doel (structuur-gebaseerd).
- Harde, binaire eis: alle stappen moeten kloppen (structuurbreuk + sweep
  + confluence-zone + afwijzing) of er is geen setup. Geen percentage,
  geen integratie met `confirm_threshold_pct` of `user_required_factors`.
- Alleen bij overlap tussen een fair value gap en een order block telt de
  zone — een los FVG of los order block is niet genoeg.
- Altijd melden, ook op een gemute coin (`is_coin_muted` wordt hier
  nooit gecheckt, zelfde precedent als patroon/swing).
- SMC-kandidaten delen NIET de bestaande top-3-structurele-cap
  (`MAX_STRUCTURAL_NOTIFICATIONS_PER_CYCLE`) met uitbraak+terugtest/
  trendlijn+terugtest/patroon — eigen, ongelimiteerde meldingsroute,
  buiten `structural`/`cycle_structural_candidates` om.
- `app/repo.py` blijft de enige plek met databasetoegang. Nieuwe tabel:
  `CREATE TABLE IF NOT EXISTS` in `app/schema.sql` volstaat, geen
  `_migrate()`-guard (brand-new tabel, precedent `muted_coins`/
  `sr_zone_failures`).
- Geen pytest-suite: verificatie via throwaway scripts tegen een
  scratch-database (`DATABASE_PATH=/tmp/scratch.db`) en handmatige
  Playwright-verificatie voor UI-wijzigingen.

---

## Task 1: indicators.py — structuurbreuk + sweep-vóór-de-breuk

**Files:**
- Modify: `app/indicators.py` (nieuwe dataclass + twee nieuwe functies,
  plaats ze direct na `_find_liquidity_sweep`/`check_daily_liquidity_sweep`,
  rond regel 856, waar de bestaande liquidity-sweep-code al staat)

**Interfaces:**
- Consumes: bestaande `_find_pivots(window) -> list[Pivot]` (regel 603),
  bestaande `Pivot` dataclass (`index`, `price`, `kind`), bestaande
  `_find_liquidity_sweep(window, direction) -> Optional[Pivot]` (regel 795).
- Produces: `StructureBreak` dataclass (`direction: str`,
  `broken_pivot: Pivot`, `break_index: int`), `find_structure_break(window: pd.DataFrame) -> Optional[StructureBreak]`,
  `find_liquidity_sweep_before_break(window: pd.DataFrame, structure_break: StructureBreak) -> Optional[Pivot]`
  — gebruikt door Task 4.

- [ ] **Step 1: Schrijf de mislukkende test voor `find_structure_break`**

Maak `/tmp/test_smc_structure.py`:

Deze exacte candle-waarden zijn tijdens het schrijven van dit plan al
tegen de echte `_find_pivots` uitgevoerd en geverifieerd (`_find_pivots`
vindt met `SR_PIVOT_WINDOW=3` alleen pivots binnen `range(3, n-3)` — met
n=11 candles dus alleen indices 3 t/m 7 — dat is waarom de pivot in dit
voorbeeld op index 5 zit, niet toevallig):

```python
import sys
sys.path.insert(0, "/home/user/Trade")
import pandas as pd
from app import indicators


def _candles(closes, highs, lows):
    n = len(closes)
    return pd.DataFrame({
        "open": closes, "close": closes, "high": highs, "low": lows,
        "volume": [100.0] * n,
    })


def test_bearish_structure_break():
    # Duidelijke swing-low op index 5 (low 90, bevestigd doordat de 3
    # candles aan weerskanten allemaal hoger liggen). Laatste candle
    # (index 10) sluit met close=80 onder die 90.
    lows =  [110, 108, 106, 104, 102, 90, 104, 106, 108, 110, 50]
    highs = [120, 118, 116, 114, 112, 100, 130, 116, 118, 120, 135]
    closes = [115, 113, 111, 109, 107, 95, 109, 111, 113, 115, 80]
    df = _candles(closes, highs, lows)
    result = indicators.find_structure_break(df)
    assert result is not None
    assert result.direction == "short"
    assert result.break_index == 10
    assert result.broken_pivot.price == 90.0


def test_no_structure_break_when_close_stays_above_swing_low():
    # Zelfde data, maar de laatste candle sluit op 95, boven de swing-low
    # van 90 — geen breuk.
    lows =  [110, 108, 106, 104, 102, 90, 104, 106, 108, 110, 50]
    highs = [120, 118, 116, 114, 112, 100, 130, 116, 118, 120, 135]
    closes = [115, 113, 111, 109, 107, 95, 109, 111, 113, 115, 95]
    df = _candles(closes, highs, lows)
    assert indicators.find_structure_break(df) is None


def test_wick_through_swing_low_without_close_below_is_not_a_break():
    # De laatste candle heeft een lage staart (low 70, ver onder de 90),
    # maar sluit weer op 95 — geen structuurbreuk (close-based, geen wick).
    lows =  [110, 108, 106, 104, 102, 90, 104, 106, 108, 110, 70]
    highs = [120, 118, 116, 114, 112, 100, 130, 116, 118, 120, 135]
    closes = [115, 113, 111, 109, 107, 95, 109, 111, 113, 115, 95]
    df = _candles(closes, highs, lows)
    assert indicators.find_structure_break(df) is None


for test in [test_bearish_structure_break, test_no_structure_break_when_close_stays_above_swing_low,
             test_wick_through_swing_low_without_close_below_is_not_a_break]:
    test()
    print(f"OK: {test.__name__}")
```

- [ ] **Step 2: Verifieer dat de test mislukt**

Run: `python3 /tmp/test_smc_structure.py`
Expected: `AttributeError: module 'app.indicators' has no attribute 'find_structure_break'`

- [ ] **Step 3: Implementeer `StructureBreak` en `find_structure_break`**

Plaats direct na `check_daily_liquidity_sweep` (rond regel 856-870):

```python
@dataclass
class StructureBreak:
    direction: str          # "long" of "short"
    broken_pivot: Pivot     # de swing-high/low die brak
    break_index: int        # candle-index van de sluiting die brak


def find_structure_break(window: pd.DataFrame) -> Optional[StructureBreak]:
    """Market structure shift: de laatste candle in window sluit voorbij
    een eerdere, bevestigde swing (via de bestaande _find_pivots) — een
    close onder de meest recente swing-low is een bearish breuk, een
    close boven de meest recente swing-high een bullish breuk. Een staart
    die er doorheen prikt zonder dat de candle er ook mee sluit telt
    niet, dat is een sweep, geen structuurbreuk (zie
    find_liquidity_sweep_before_break hieronder). Kijkt alleen naar de
    LAATSTE candle van window — een breuk die eerder in het venster
    gebeurde en toen niet gezien is, wordt niet met terugwerkende kracht
    alsnog gevonden, elke scan-cyclus kijkt opnieuw naar de actuele
    laatste candle."""
    pivots = _find_pivots(window)
    last_index = len(window) - 1
    last_close = window["close"].iloc[last_index]

    recent_low = max((p for p in pivots if p.kind == "low"), key=lambda p: p.index, default=None)
    if recent_low is not None and last_close < recent_low.price:
        return StructureBreak(direction="short", broken_pivot=recent_low, break_index=last_index)

    recent_high = max((p for p in pivots if p.kind == "high"), key=lambda p: p.index, default=None)
    if recent_high is not None and last_close > recent_high.price:
        return StructureBreak(direction="long", broken_pivot=recent_high, break_index=last_index)

    return None
```

- [ ] **Step 4: Run de test opnieuw, `find_structure_break`-tests moeten slagen**

Run: `python3 /tmp/test_smc_structure.py`
Expected: eerste drie `OK:`-regels, dan een `AttributeError` voor
`find_liquidity_sweep_before_break` (nog niet geïmplementeerd) — dat is
verwacht op dit punt, ga door naar Step 5.

- [ ] **Step 5: Voeg tests toe voor `find_liquidity_sweep_before_break`**

Voeg toe aan `/tmp/test_smc_structure.py`, vóór de `for test in [...]`-regel:

Ook deze waarden zijn al uitgevoerd en geverifieerd. `_find_pivots` vindt
in deze data twee pivots: de swing-low op index 5 (90, hierboven al
gebruikt) én een swing-high op index 6 (130) — bewust op index 6 gezet,
niet index 8 of later: een pivot heeft `SR_PIVOT_WINDOW=3` candles rechts
nodig ter bevestiging, en die rechterkant mag de sweep-candle zelf
(index 10) niet meebevatten, anders zou de sweep-candle's eigen hoge
staart de pivot-bevestiging van diezelfde pivot verstoren (circulaire
afhankelijkheid). Index 6 (rechterkant t/m index 9) zit daar ruim voor:

```python
def test_sweep_before_bearish_break():
    # Zelfde basisdata als de structuurbreuk-test hierboven, met één extra
    # swing-high op index 6 (130) die de laatste candle met zijn staart
    # (high 135) veegt terwijl hij op 80 sluit, onder de swing-low (90) —
    # dezelfde candle levert dus zowel de sweep als de structuurbreuk,
    # precies zoals de spec beschrijft ("meestal dezelfde beweging die de
    # doorbraak veroorzaakt").
    lows =  [110, 108, 106, 104, 102, 90, 104, 106, 108, 110, 50]
    highs = [120, 118, 116, 114, 112, 100, 130, 116, 118, 120, 135]
    closes = [115, 113, 111, 109, 107, 95, 109, 111, 113, 115, 80]
    df = _candles(closes, highs, lows)
    structure_break = indicators.find_structure_break(df)
    assert structure_break is not None and structure_break.direction == "short"
    sweep = indicators.find_liquidity_sweep_before_break(df, structure_break)
    assert sweep is not None
    assert sweep.kind == "high"
    assert sweep.price == 130.0


def test_no_sweep_before_break_returns_none():
    # Zelfde structuurbreuk, maar de laatste candle's high blijft onder
    # de 130 (82 in plaats van 135) — geen sweep, geen staart-doorbraak-
    # en-terugsluiting van die swing-high.
    lows =  [110, 108, 106, 104, 102, 90, 104, 106, 108, 110, 50]
    highs = [120, 118, 116, 114, 112, 100, 130, 116, 118, 120, 82]
    closes = [115, 113, 111, 109, 107, 95, 109, 111, 113, 115, 80]
    df = _candles(closes, highs, lows)
    structure_break = indicators.find_structure_break(df)
    assert structure_break is not None
    assert indicators.find_liquidity_sweep_before_break(df, structure_break) is None
```

En voeg beide functienamen toe aan de `for test in [...]`-lijst onderaan
het bestand.

- [ ] **Step 6: Verifieer dat de nieuwe tests mislukken**

Run: `python3 /tmp/test_smc_structure.py`
Expected: `AttributeError: module 'app.indicators' has no attribute 'find_liquidity_sweep_before_break'`

- [ ] **Step 7: Implementeer `find_liquidity_sweep_before_break`**

Direct na `find_structure_break`:

```python
def find_liquidity_sweep_before_break(
    window: pd.DataFrame, structure_break: StructureBreak,
) -> Optional[Pivot]:
    """Hergebruikt de bestaande _find_liquidity_sweep (al gebruikt door de
    sniper-entry-feature) op het venster tot en met de doorbraak-candle,
    met DEZELFDE richting als de structuurbreuk — niet tegengesteld.
    _find_liquidity_sweep's eigen conventie is al dat direction="short"
    een sweep aan de high-kant betekent (kind="high" intern), en dat is
    precies de buy-side liquidity die een bearish reversal voedt: prijs
    veegt eerst een eerdere high leeg voordat hij hard omlaag draait en
    een eerdere low doorbreekt (de structuurbreuk zelf). Bij
    direction="long" spiegelt dit: een sweep van een eerdere low, de
    sell-side liquidity die een bullish reversal voedt. Geeft de geveegde
    pivot terug (wordt in Task 5 de stop), of None als er geen sweep vlak
    voor de breuk zat — dan is het geen geldige setup."""
    pre_break_window = window.iloc[:structure_break.break_index + 1]
    return _find_liquidity_sweep(pre_break_window, structure_break.direction)
```

- [ ] **Step 8: Run alle tests, allemaal moeten slagen**

Run: `python3 /tmp/test_smc_structure.py`
Expected: vijf `OK:`-regels, geen `AssertionError`/`AttributeError`.

- [ ] **Step 9: Commit**

```bash
git add app/indicators.py
git commit -m "Voeg SMC structuurbreuk- en sweep-vóór-de-breuk-detectie toe"
```

---

## Task 2: indicators.py — fair value gap, order block, confluence-zone

**Files:**
- Modify: `app/indicators.py` (drie dataclasses + drie functies, direct
  na de code van Task 1)

**Interfaces:**
- Consumes: niets nieuws, puur op basis van een `pd.DataFrame` met
  `open`/`high`/`low`/`close`-kolommen (het bestaande OHLCV-formaat).
- Produces: `FVG` (`low`, `high`), `OrderBlock` (`low`, `high`),
  `find_fair_value_gaps(df, direction) -> list[FVG]`,
  `find_order_blocks(df, direction) -> list[OrderBlock]`,
  `find_confluence_zone(fvgs, order_blocks) -> Optional[tuple[float, float]]`
  — gebruikt door Task 4.

**Ontwerpbeslissing genomen tijdens het schrijven van dit plan** (niet
expliciet in de spec, hier vastgelegd): zowel FVG- als order-block-
zoektocht kijkt alleen naar de laatste `ZONE_SEARCH_LOOKBACK` candles
(veertig 15m-candles, ongeveer tien uur), niet naar de volledige
meegegeven `df`. Zonder die begrenzing zou een oude, allang gevulde FVG
van dagen geleden nog als geldige zone meetellen — deze setups horen bij
de specifieke displacement die de structuurbreuk veroorzaakte, niet bij
willekeurige oude gaten in de prijsgeschiedenis.

**Tweede ontwerppunt, ontdekt tijdens de scratch-verificatie van Task 4**:
`FVG`/`OrderBlock.low`/`.high` worden expliciet met `float(...)` uit de
pandas-kolom gehaald, niet direct `window["low"].iloc[i]` toegekend —
zelfde conventie als de bestaande `_find_pivots` (regel 616-619 elders in
dit bestand, `Pivot(price=float(high_i), ...)`). Reden: bij echte
Binance-data via ccxt zijn OHLCV-kolommen altijd `float64` en maakt dit
niets uit, maar in een testscript met platte Python-integers (zoals de
candle-data in Task 4's Step 3) krijgt de kolom dtype `int64`, en
`numpy.int64` is — anders dan `numpy.float64` — geen subklasse van
Python's `int`. Python's `sqlite3`-module herkent zo'n waarde dan niet
als integer, valt terug op het buffer-protocol en slaat hem stilzwijgend
op als BLOB in plaats van als getal (`repo.upsert_smc_setup` zou dan een
`zone_low`/`zone_high` opslaan die bij het uitlezen geen getal meer is).
`float(...)` voorkomt dat volledig, ongeacht de bron-dtype.

- [ ] **Step 1: Schrijf de mislukkende tests**

Maak `/tmp/test_smc_zones.py`:

```python
import sys
sys.path.insert(0, "/home/user/Trade")
import pandas as pd
from app import indicators


def _ohlc(rows):
    # rows: list van (open, high, low, close)
    return pd.DataFrame(rows, columns=["open", "high", "low", "close"]).assign(volume=100.0)


def test_bearish_fvg_found():
    # Candle 0: 100-102 (low-high). Candle 1: grote rode displacement-candle.
    # Candle 2: 90-95 (low-high) — candle 0's low (100) ligt boven candle
    # 2's high (95), dat is het gat.
    rows = [
        (101, 102, 100, 101),
        (101, 101, 90, 91),
        (91, 95, 90, 92),
    ]
    df = _ohlc(rows)
    gaps = indicators.find_fair_value_gaps(df, "short")
    assert len(gaps) == 1
    assert gaps[0].low == 95 and gaps[0].high == 100


def test_bullish_fvg_found():
    rows = [
        (100, 101, 99, 100),
        (100, 112, 100, 111),
        (111, 115, 108, 112),
    ]
    df = _ohlc(rows)
    gaps = indicators.find_fair_value_gaps(df, "long")
    assert len(gaps) == 1
    assert gaps[0].low == 101 and gaps[0].high == 108


def test_no_gap_when_candles_overlap():
    rows = [
        (100, 105, 95, 101),
        (101, 106, 96, 102),
        (102, 107, 97, 103),
    ]
    df = _ohlc(rows)
    assert indicators.find_fair_value_gaps(df, "short") == []


def test_order_block_before_bearish_displacement():
    # Negen rustige candles (klein bereik), dan één groene candle
    # (order block-kandidaat), dan een grote rode displacement-candle.
    rows = [(100, 101, 99, 100)] * 9
    rows.append((100, 102, 99, 101.5))   # groene candle, order block
    rows.append((101.5, 102, 80, 81))    # grote rode displacement
    df = _ohlc(rows)
    blocks = indicators.find_order_blocks(df, "short")
    assert len(blocks) == 1
    assert blocks[0].low == 99 and blocks[0].high == 102


def test_no_order_block_without_displacement():
    rows = [(100, 101, 99, 100)] * 11
    df = _ohlc(rows)
    assert indicators.find_order_blocks(df, "short") == []


def test_confluence_zone_overlap():
    fvgs = [indicators.FVG(low=95, high=100)]
    blocks = [indicators.OrderBlock(low=97, high=103)]
    zone = indicators.find_confluence_zone(fvgs, blocks)
    assert zone == (97, 100)


def test_no_confluence_without_overlap():
    fvgs = [indicators.FVG(low=95, high=97)]
    blocks = [indicators.OrderBlock(low=99, high=103)]
    assert indicators.find_confluence_zone(fvgs, blocks) is None


for test in [
    test_bearish_fvg_found, test_bullish_fvg_found, test_no_gap_when_candles_overlap,
    test_order_block_before_bearish_displacement, test_no_order_block_without_displacement,
    test_confluence_zone_overlap, test_no_confluence_without_overlap,
]:
    test()
    print(f"OK: {test.__name__}")
```

- [ ] **Step 2: Verifieer dat de tests mislukken**

Run: `python3 /tmp/test_smc_zones.py`
Expected: `AttributeError: module 'app.indicators' has no attribute 'FVG'`

- [ ] **Step 3: Implementeer alle drie**

Direct na `find_liquidity_sweep_before_break` (Task 1):

```python
ZONE_SEARCH_LOOKBACK = 40       # 15m-candles, ongeveer tien uur
DISPLACEMENT_LOOKBACK = 10      # candles voor het gemiddelde bereik
DISPLACEMENT_RANGE_MULTIPLE = 2.0


@dataclass
class FVG:
    low: float
    high: float


def find_fair_value_gaps(df: pd.DataFrame, direction: str) -> list[FVG]:
    """Klassieke drie-candle fair value gap, alleen binnen de laatste
    ZONE_SEARCH_LOOKBACK candles (zie de ontwerpbeslissing in dit plan).
    Voor short (bearish setup): candle 1's low boven candle 3's high, het
    gat daartussen is de zone waar prijs later tegenaan kan lopen voordat
    hij verder zakt — deze bearish FVG ontstaat tijdens de displacement
    die de structuurbreuk zelf veroorzaakte. Voor long het spiegelbeeld.
    Nieuwste eerst."""
    window = df.tail(ZONE_SEARCH_LOOKBACK).reset_index(drop=True)
    gaps: list[FVG] = []
    for i in range(2, len(window)):
        c1_low, c1_high = window["low"].iloc[i - 2], window["high"].iloc[i - 2]
        c3_low, c3_high = window["low"].iloc[i], window["high"].iloc[i]
        if direction == "short" and c1_low > c3_high:
            gaps.append(FVG(low=float(c3_high), high=float(c1_low)))
        elif direction == "long" and c1_high < c3_low:
            gaps.append(FVG(low=float(c1_high), high=float(c3_low)))
    gaps.reverse()
    return gaps


@dataclass
class OrderBlock:
    low: float
    high: float


def find_order_blocks(df: pd.DataFrame, direction: str) -> list[OrderBlock]:
    """De laatste candle in de tegengestelde kleur vlak vóór een sterke
    displacement-beweging: voor short de laatste groene candle voor een
    duidelijke rode dump. 'Duidelijk' is hier candle_range minstens
    DISPLACEMENT_RANGE_MULTIPLE keer het gemiddelde bereik van de
    voorgaande DISPLACEMENT_LOOKBACK candles — zelfde soort maat als
    elders in dit bestand voor 'een echte beweging' (geen losse, nieuwe
    aparte definitie). Loopt terug vanaf de displacement-candle tot de
    eerste tegengestelde candle, voor het geval de displacement zelf uit
    meerdere candles op rij bestaat. Alleen binnen ZONE_SEARCH_LOOKBACK
    candles. Nieuwste eerst."""
    window = df.tail(ZONE_SEARCH_LOOKBACK).reset_index(drop=True)
    blocks: list[OrderBlock] = []
    for i in range(DISPLACEMENT_LOOKBACK, len(window)):
        candle_range = window["high"].iloc[i] - window["low"].iloc[i]
        prior = window.iloc[i - DISPLACEMENT_LOOKBACK:i]
        avg_range = (prior["high"] - prior["low"]).mean()
        if avg_range <= 0 or candle_range < DISPLACEMENT_RANGE_MULTIPLE * avg_range:
            continue
        is_down = window["close"].iloc[i] < window["open"].iloc[i]
        is_up = window["close"].iloc[i] > window["open"].iloc[i]
        if direction == "short" and not is_down:
            continue
        if direction == "long" and not is_up:
            continue
        j = i - 1
        while j >= 0:
            open_j, close_j = window["open"].iloc[j], window["close"].iloc[j]
            if direction == "short" and close_j > open_j:
                blocks.append(OrderBlock(low=float(window["low"].iloc[j]), high=float(window["high"].iloc[j])))
                break
            if direction == "long" and close_j < open_j:
                blocks.append(OrderBlock(low=float(window["low"].iloc[j]), high=float(window["high"].iloc[j])))
                break
            j -= 1
    blocks.reverse()
    return blocks


def find_confluence_zone(fvgs: list[FVG], order_blocks: list[OrderBlock]) -> Optional[tuple[float, float]]:
    """Enige geldige terugtrek-zone: een fair value gap en een order
    block die elkaar overlappen. Geen overlap, geen zone — puur alleen
    een FVG of alleen een order block telt niet mee. fvgs/order_blocks
    zijn al nieuwste-eerst gesorteerd (zie hierboven), dus de eerste
    gevonden overlap is ook de meest recente. Geeft (low, high) van de
    overlap terug."""
    for fvg in fvgs:
        for block in order_blocks:
            overlap_low = max(fvg.low, block.low)
            overlap_high = min(fvg.high, block.high)
            if overlap_low < overlap_high:
                return (overlap_low, overlap_high)
    return None
```

- [ ] **Step 4: Run de tests, allemaal moeten slagen**

Run: `python3 /tmp/test_smc_zones.py`
Expected: zeven `OK:`-regels.

- [ ] **Step 5: Commit**

```bash
git add app/indicators.py
git commit -m "Voeg SMC fair-value-gap, order-block en confluence-zone-detectie toe"
```

---

## Task 3: schema + repo — smc_setups tabel

**Files:**
- Modify: `app/schema.sql` (nieuwe tabel)
- Modify: `app/repo.py` (vijf nieuwe functies, plaats ze in een nieuwe
  sectie, bijvoorbeeld direct vóór de `# Per-gebruiker bevestigde status
  en winrate`-sectie)

**Interfaces:**
- Produces: `ZONE_DEDUP_PCT` (module-constante in `app/repo.py`),
  `upsert_smc_setup(coin, direction, zone_low, zone_high, structure_level, sweep_price, liquidity_target) -> int`,
  `list_forming_smc_setups() -> list[dict]`,
  `mark_smc_alert_sent(setup_id: int) -> None`,
  `complete_smc_setup(setup_id: int, signal_id: int) -> None`,
  `delete_smc_setup(setup_id: int) -> None`
  — gebruikt door Task 4 en 5.

- [ ] **Step 1: Voeg de tabel toe aan `app/schema.sql`**

Ergens in het bestand, bijvoorbeeld direct na de bestaande
`forming_patterns`-tabel:

```sql
CREATE TABLE IF NOT EXISTS smc_setups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin TEXT NOT NULL,
    direction TEXT NOT NULL,
    zone_low REAL NOT NULL,
    zone_high REAL NOT NULL,
    structure_level REAL NOT NULL,
    sweep_price REAL NOT NULL,
    liquidity_target REAL NOT NULL,
    alert_sent INTEGER NOT NULL DEFAULT 0,
    signal_id INTEGER REFERENCES signals(id),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_smc_setups_coin ON smc_setups(coin);
```

- [ ] **Step 2: Voeg de vijf functies toe aan `app/repo.py`**

```python
# ---------------------------------------------------------------------------
# SMC liquidity setups
# ---------------------------------------------------------------------------

ZONE_DEDUP_PCT = 0.3  # procent van de zone-middenprijs, geen ATR (zie de spec)


def upsert_smc_setup(
    coin: str, direction: str, zone_low: float, zone_high: float,
    structure_level: float, sweep_price: float, liquidity_target: float,
) -> int:
    """Vindt een bestaande bouwende setup (signal_id IS NULL) voor deze
    coin+richting waarvan de zone-middenprijs binnen ZONE_DEDUP_PCT
    procent van de nieuwe zone ligt en werkt die bij, of maakt een nieuwe
    rij aan. alert_sent wordt bij een update nooit teruggezet — dat zou
    de eenmalige 'bouwend'-melding laten herhalen voor een setup die al
    gemeld is."""
    now = db.now_iso()
    zone_mid = (zone_low + zone_high) / 2
    with db.session() as conn:
        existing = conn.execute(
            """SELECT id, zone_low, zone_high FROM smc_setups
               WHERE coin = ? AND direction = ? AND signal_id IS NULL""",
            (coin, direction),
        ).fetchall()
        for row in existing:
            existing_mid = (row["zone_low"] + row["zone_high"]) / 2
            if existing_mid and abs(existing_mid - zone_mid) <= ZONE_DEDUP_PCT / 100 * zone_mid:
                conn.execute(
                    """UPDATE smc_setups SET zone_low = ?, zone_high = ?, structure_level = ?,
                       sweep_price = ?, liquidity_target = ?, updated_at = ? WHERE id = ?""",
                    (zone_low, zone_high, structure_level, sweep_price, liquidity_target, now, row["id"]),
                )
                return row["id"]
        cur = conn.execute(
            """INSERT INTO smc_setups
               (coin, direction, zone_low, zone_high, structure_level, sweep_price,
                liquidity_target, alert_sent, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, 0, ?, ?)""",
            (coin, direction, zone_low, zone_high, structure_level, sweep_price, liquidity_target, now, now),
        )
        return cur.lastrowid


def list_forming_smc_setups() -> list[dict]:
    """Alle bouwende setups (nog geen signal_id), meest recent bijgewerkt
    eerst, voor de nieuwe /smc-pagina."""
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM smc_setups WHERE signal_id IS NULL ORDER BY updated_at DESC"
        ).fetchall()
        return [dict(r) for r in rows]


def mark_smc_alert_sent(setup_id: int) -> None:
    with db.session() as conn:
        conn.execute("UPDATE smc_setups SET alert_sent = 1 WHERE id = ?", (setup_id,))


def complete_smc_setup(setup_id: int, signal_id: int) -> None:
    """Koppelt de bouwende setup aan het net aangemaakte signaal — vanaf
    hier telt hij niet meer mee in list_forming_smc_setups (signal_id is
    niet meer NULL) en wordt hij nooit meer door delete_smc_setup
    opgeruimd."""
    with db.session() as conn:
        conn.execute("UPDATE smc_setups SET signal_id = ? WHERE id = ?", (signal_id, setup_id))


def delete_smc_setup(setup_id: int) -> None:
    """Verwijdert één bouwende setup: de prijs is voorbij de zone gelopen
    zonder afwijzing, of een nieuwe, tegengestelde structuurbreuk maakte
    hem achterhaald (zie Task 4). Werkt op één rij tegelijk, niet op alle
    setups van een coin — een structuurbreuk is een eenmalige
    gebeurtenis die op de LAATSTE candle van een venster gezien wordt, dus
    'geen nieuwe breuk deze cyclus' betekent niet 'de oude setup is
    ongeldig', een bouwende setup moet over meerdere cycli blijven
    bestaan totdat de zone geraakt wordt."""
    with db.session() as conn:
        conn.execute("DELETE FROM smc_setups WHERE id = ? AND signal_id IS NULL", (setup_id,))
```

- [ ] **Step 3: Scratch-DB round-trip test**

`complete_smc_setup` koppelt aan een `signal_id` die als foreign key naar
`signals(id)` wijst (`app/schema.sql`), en `app/db.py` zet `PRAGMA
foreign_keys=ON` op elke connectie — een niet-bestaand `signal_id` breekt
dus met een `IntegrityError`. De test maakt daarom eerst een echte,
minimale `signals`-rij aan via `repo.insert_signal` (de kolommen die geen
default hebben in `signals` zijn NOT NULL: `technical_confirmed`,
`hard_gates_ok`, `is_practice`, `confidence` — al het andere mag `None`
blijven).

```bash
DATABASE_PATH=/tmp/scratch_smc_task3.db python3 -c "
from app import db, repo
db.init_db()

real_signal_id = repo.insert_signal({
    'coin': 'BTC', 'direction': 'short', 'category': 'day_trading', 'price': 60000.0,
    'technical_confirmed': 1, 'hard_gates_ok': 1, 'is_practice': 0, 'confidence': 'test',
})

# Nieuwe setup aanmaken
sid = repo.upsert_smc_setup('BTC', 'short', 60000.0, 60500.0, 61000.0, 61200.0, 58000.0)
assert isinstance(sid, int)
forming = repo.list_forming_smc_setups()
assert len(forming) == 1 and forming[0]['id'] == sid
assert forming[0]['alert_sent'] == 0

# Update binnen de dedup-marge (zelfde zone-midden, iets andere randen) --> zelfde rij
sid2 = repo.upsert_smc_setup('BTC', 'short', 60050.0, 60550.0, 61000.0, 61200.0, 58000.0)
assert sid2 == sid
assert len(repo.list_forming_smc_setups()) == 1

# Melding markeren, dan nog een update binnen de marge -- alert_sent blijft 1
repo.mark_smc_alert_sent(sid)
repo.upsert_smc_setup('BTC', 'short', 60060.0, 60560.0, 61000.0, 61200.0, 58000.0)
assert repo.list_forming_smc_setups()[0]['alert_sent'] == 1

# Buiten de dedup-marge (heel andere zone) --> nieuwe rij
sid3 = repo.upsert_smc_setup('BTC', 'short', 50000.0, 50500.0, 51000.0, 51200.0, 48000.0)
assert sid3 != sid
assert len(repo.list_forming_smc_setups()) == 2

# Compleet maken -- verdwijnt uit forming
repo.complete_smc_setup(sid, signal_id=real_signal_id)
forming_after = repo.list_forming_smc_setups()
assert len(forming_after) == 1 and forming_after[0]['id'] == sid3

# Vervallen: één specifieke bouwende setup verwijderen
repo.delete_smc_setup(sid3)
assert repo.list_forming_smc_setups() == []
print('OK')
"
rm -f /tmp/scratch_smc_task3.db
```

Expected: `OK` zonder AssertionError.

- [ ] **Step 4: Commit**

```bash
git add app/schema.sql app/repo.py
git commit -m "Voeg smc_setups-tabel en CRUD-functies toe"
```

---

## Task 4: market_scanner.py — detectie + bouwende-setup-persistentie + melding

**Files:**
- Modify: `app/market_scanner.py` (nieuwe functie `_check_smc_setup`,
  aangeroepen vanuit de bestaande per-coin-loop in `scan_market()`)

**Interfaces:**
- Consumes: `indicators.find_structure_break`, `find_liquidity_sweep_before_break`,
  `find_fair_value_gaps`, `find_order_blocks`, `find_confluence_zone`
  (Task 1-2), `repo.upsert_smc_setup`, `repo.list_forming_smc_setups`,
  `repo.mark_smc_alert_sent`, `repo.delete_smc_setup` (Task 3). Bestaande
  `exchange.fetch_ohlcv(coin, timeframe=..., limit=...)`,
  `push_notify.send_push`, `push_notify.is_quiet_now`, `repo.list_users()`.
- Produces: `_check_smc_setup(coin: str) -> Optional[dict]` — geeft de
  bouwende-of-net-complete setup-rij terug (als dict, met `id`,
  `signal_id` nog None) zodra de zone geraakt EN afgewezen is, anders
  `None` (bouwend zonder afwijzing, of geen setup dit cyclus). Gebruikt
  door Task 5, die de `notify()`-closure en signaal-aanmaak toevoegt.

Deze taak levert de detectie en de eenmalige "bouwend"-melding. De
afwijzings-check en de daadwerkelijke signaal-aanmaak komen in Task 5 —
gesplitst omdat dit al een aanzienlijk stuk logica is en Task 5 er
zelfstandig op voortbouwt.

**Belangrijk ontwerppunt, tijdens het schrijven van dit plan al
mis-geschreven en daarna gecorrigeerd (zie de multi-cycle test in Step
3b hieronder):** `find_structure_break` kijkt alleen naar de LAATSTE
candle van het 30m-venster — een structuurbreuk is een eenmalig
gebeurtenis, geen aanhoudende toestand. `None` teruggeven op een cyclus
betekent dus alleen "geen NIEUWE breuk deze cyclus", niet "de eerder
gevonden bouwende setup is ongeldig". Een bouwende setup moet daarom
over meerdere cycli blijven bestaan totdat er ofwel een afwijzing komt
(compleet signaal, Task 5), de zone zonder afwijzing gepasseerd wordt
(vervallen), of een NIEUWE, tegengestelde structuurbreuk hem achterhaalt.
`_check_smc_setup` doet dit daarom in twee gescheiden fasen: eerst
bestaande bouwende setups tegen de huidige laatste candle houden (los
van of er deze cyclus opnieuw een breuk gevonden wordt), pas daarna naar
een nieuwe breuk zoeken.

- [ ] **Step 1: Voeg de nieuwe functie toe aan `app/market_scanner.py`**

Plaats vlak vóór `async def scan_market():`:

```python
SMC_ZONE_SEARCH_LOOKBACK_30M = 60  # 30m-candles, ongeveer anderhalve dag


def _smc_last_candle_state(last_candle, zone_low: float, zone_high: float, direction: str) -> tuple[bool, bool, bool]:
    """Bepaalt voor één 15m-candle en één bouwende zone drie onafhankelijke
    toestanden: (in_zone, rejected, passed_without_rejection).
    in_zone: de candle raakte de zone (wick of volledige overlap).
    rejected: de candle raakte de zone EN sloot er weer buiten aan de
    kant die de setup ongeldig maakt voor voortzetting maar geldig maakt
    als entry-trigger (short: sluit onder zone_low, long: sluit boven
    zone_high) - dit is de signaal-trigger uit Task 5.
    passed_without_rejection: het SPIEGELBEELD van rejected, niet
    hetzelfde teken. Een short-zone ligt BOVEN de prijs die er van
    onderaf naartoe beweegt (na de bearish structuurbreuk) — 'voorbij
    zonder afwijzing' betekent dus dat de candle DOOR de top van de zone
    brak (close boven zone_high) zonder ooit een rejectie-close onder
    zone_low te laten zien: de supply hield niet stand, de setup is
    achterhaald. Long is het spiegelbeeld (close onder zone_low, door de
    bodem heen). Vóórdat de zone ooit bereikt is — bijvoorbeeld een
    short-setup waarvan de laatste close nog onder zone_low ligt, op weg
    naar boven — is dit nadrukkelijk GEEN 'passed': dat zou een net
    aangemaakte, nog nooit geraakte setup meteen weer weggooien (de bug
    die deze functie's test in Step 3b dichttimmert)."""
    in_zone = (
        zone_low <= last_candle["low"] <= zone_high
        or zone_low <= last_candle["high"] <= zone_high
        or (last_candle["low"] <= zone_low and last_candle["high"] >= zone_high)
    )
    rejected = in_zone and (
        (direction == "short" and last_candle["close"] < zone_low) or
        (direction == "long" and last_candle["close"] > zone_high)
    )
    passed_without_rejection = (
        (direction == "short" and last_candle["close"] > zone_high) or
        (direction == "long" and last_candle["close"] < zone_low)
    )
    return in_zone, rejected, passed_without_rejection


async def _check_smc_setup(coin: str) -> Optional[dict]:
    """SMC/ICT-liquidity-setup: structuurbreuk + sweep op 30m, terugtrek
    naar een FVG/order-block-overlap op 15m. Volledig autonoom, los van
    de drie bestaande structurele detectoren (uitbraak+terugtest,
    trendlijn+terugtest, patroon) en van hun top-3-per-cyclus-cap — zie
    de Global Constraints in dit plan. Geeft de smc_setups-rij terug
    zodra de zone geraakt EN afgewezen is (Task 5 maakt daar het echte
    signaal van), None in elk ander geval (geen structuurbreuk, geen
    sweep, geen confluence-zone, of wel een bouwende setup maar nog geen
    afwijzing).

    Fase 1: bestaande bouwende setups voor deze coin tegen de huidige
    laatste 15m-candle houden, ONAFHANKELIJK van of er deze cyclus een
    nieuwe structuurbreuk gevonden wordt (zie de ontwerptoelichting
    hierboven de functie-docstring van deze taak). Fase 2: pas daarna
    zoeken naar een nieuwe breuk."""
    df_15m = await asyncio.to_thread(exchange.fetch_ohlcv, coin, timeframe="15m")
    last_candle = df_15m.iloc[-1]

    existing = [s for s in repo.list_forming_smc_setups() if s["coin"] == coin]
    for existing_setup in existing:
        in_zone, rejected, passed_without_rejection = _smc_last_candle_state(
            last_candle, existing_setup["zone_low"], existing_setup["zone_high"], existing_setup["direction"],
        )
        if rejected:
            return existing_setup
        if not in_zone and passed_without_rejection:
            repo.delete_smc_setup(existing_setup["id"])

    df_30m = await asyncio.to_thread(exchange.fetch_ohlcv, coin, timeframe="30m", limit=SMC_ZONE_SEARCH_LOOKBACK_30M)
    structure_break = indicators.find_structure_break(df_30m)
    if structure_break is None:
        return None
    direction = structure_break.direction

    # Een nieuwe breuk in de TEGENGESTELDE richting van een bestaande
    # bouwende setup maakt die setup achterhaald (de markt heeft zijn
    # structuur omgedraaid voordat de oude zone geraakt werd).
    for existing_setup in existing:
        if existing_setup["direction"] != direction:
            repo.delete_smc_setup(existing_setup["id"])

    sweep = indicators.find_liquidity_sweep_before_break(df_30m, structure_break)
    if sweep is None:
        return None

    fvgs = indicators.find_fair_value_gaps(df_15m, direction)
    order_blocks = indicators.find_order_blocks(df_15m, direction)
    zone = indicators.find_confluence_zone(fvgs, order_blocks)
    if zone is None:
        return None
    zone_low, zone_high = zone

    # Liquidity-doel: de eerstvolgende tegengestelde pivot voorbij de
    # zone, op hetzelfde 30m-venster als de structuurbreuk zelf (dezelfde
    # bron als structure_level en sweep_price, geen extra candle-fetch).
    target_kind = "high" if direction == "long" else "low"
    target_pivots = [
        p for p in indicators._find_pivots(df_30m)
        if p.kind == target_kind and (
            (direction == "long" and p.price > zone_high) or
            (direction == "short" and p.price < zone_low)
        )
    ]
    if not target_pivots:
        return None
    # Dichtstbijzijnde tegengestelde pivot voorbij de zone: de eerste
    # liquidity die de prijs waarschijnlijk gaat opzoeken, niet een verre.
    liquidity_target_pivot = min(
        target_pivots,
        key=lambda p: abs(p.price - (zone_high if direction == "long" else zone_low)),
    )

    setup_id = repo.upsert_smc_setup(
        coin, direction, zone_low, zone_high,
        structure_level=structure_break.broken_pivot.price,
        sweep_price=sweep.price,
        liquidity_target=liquidity_target_pivot.price,
    )

    setups = repo.list_forming_smc_setups()
    setup = next((s for s in setups if s["id"] == setup_id), None)
    if setup is None:
        return None  # inmiddels al compleet gemaakt door een eerdere cyclus (race, zou niet moeten, defensief)

    _, rejected, _ = _smc_last_candle_state(last_candle, zone_low, zone_high, direction)
    if rejected:
        return setup

    if not setup["alert_sent"]:
        title = f"{push_notify.coin_symbol(coin)} {coin}, SMC-setup bouwt op"
        body = (
            f"Structuur + sweep gezien, zone {zone_low:.4f}-{zone_high:.4f}. "
            f"Zet je limit order klaar."
        )
        for user in repo.list_users():
            quiet = push_notify.is_quiet_now(user["quiet_hours_start"], user["quiet_hours_end"])
            try:
                await push_notify.send_push(user["id"], title, body, "/smc", silent=quiet)
            except Exception:
                logger.exception("SMC-bouwend-melding voor %s naar gebruiker %s is mislukt", coin, user["username"])
        repo.mark_smc_alert_sent(setup_id)
    return None
```

- [ ] **Step 2: Bedraad de aanroep in `scan_market()`'s per-coin-loop**

Zoek de bestaande drie aanroepen (`breakout_candidate = await
_find_breakout_retest_candidate(...)` t/m `pattern_candidate = await
_find_chart_pattern_candidate(...)`, rond regel 700-708) en voeg er
direct na toe, buiten de `structural`-lijst om (zie Global Constraints —
SMC deelt de top-3-cap niet):

```python
            try:
                smc_setup = await _check_smc_setup(coin)
                if smc_setup:
                    await _complete_smc_setup(coin, smc_setup)
            except Exception:
                logger.exception("SMC-check voor %s is mislukt, ga door met de rest van de cyclus", coin)
```

`_complete_smc_setup` wordt in Task 5 geïmplementeerd — deze taak
compileert dus nog niet zonder Task 5, dat is bedoeld: Task 4 en 5 horen
qua uitvoering bij elkaar, maar zijn gesplitst voor de review. Voeg voor
nu een tijdelijke stub direct vóór `async def scan_market():` toe zodat
Task 4 op zichzelf te testen is:

```python
async def _complete_smc_setup(coin: str, setup: dict) -> None:
    """Placeholder voor Task 4's eigen verificatie — Task 5 vervangt dit
    door de echte signaal-aanmaak en meldingslogica."""
    logger.info("SMC-setup compleet voor %s (id=%s), signaal-aanmaak volgt in Task 5", coin, setup["id"])
```

- [ ] **Step 3: Scratch-verificatie van `_check_smc_setup` zelf**

Dit test de detectiefunctie direct, zonder de volledige async
marktscan-pipeline te hoeven draaien (die vereist live Binance-data, niet
beschikbaar in deze sandbox — zelfde beperking als bij eerdere plannen in
dit project). De 30m-data is dezelfde, al geverifieerde reeks als Task 1
(structuurbreuk op index 10, sweep van de swing-high op 130). De 15m-data
is tijdens het schrijven van dit plan al uitgevoerd en geverifieerd: ze
levert een confluence-zone van (98, 100) op (een order block op 98-101 uit
de up-candle op index 9, een fair value gap op 95-100 tussen index 9 en
14), met de laatste candle (index 15, rond prijs 79-82) duidelijk nog
niet in die zone — dus bouwend, geen afwijzing.

```bash
DATABASE_PATH=/tmp/scratch_smc_task4.db python3 -c "
import asyncio
import sys
sys.path.insert(0, '/home/user/Trade')
import pandas as pd
from unittest.mock import patch
from app import db, repo, market_scanner

db.init_db()

def fake_fetch_ohlcv(coin, timeframe='4h', limit=200, since=None):
    if timeframe == '30m':
        lows =  [110, 108, 106, 104, 102, 90, 104, 106, 108, 110, 50]
        highs = [120, 118, 116, 114, 112, 100, 130, 116, 118, 120, 135]
        closes = [115, 113, 111, 109, 107, 95, 109, 111, 113, 115, 80]
        return pd.DataFrame({'open': closes, 'close': closes, 'high': highs, 'low': lows, 'volume': [100.0]*11})
    rows = []
    for _ in range(9):
        rows.append(dict(open=100, high=101, low=99, close=100))
    rows.append(dict(open=99, high=101, low=98, close=100.5))       # idx9: order-block-candle (up)
    rows.append(dict(open=100.5, high=101, low=80, close=81))       # idx10: down displacement
    rows.append(dict(open=81, high=83, low=79, close=80))           # idx11: filler
    rows.append(dict(open=101, high=103, low=100, close=102))       # idx12: FVG c1
    rows.append(dict(open=95, high=96, low=85, close=86))           # idx13: filler
    rows.append(dict(open=91, high=95, low=90, close=92))           # idx14: FVG c3
    rows.append(dict(open=80, high=82, low=78, close=79))           # idx15: laatste candle, NIET in de zone
    return pd.DataFrame(rows).assign(volume=100.0)

async def main():
    with patch.object(market_scanner.exchange, 'fetch_ohlcv', side_effect=fake_fetch_ohlcv):
        result = await market_scanner._check_smc_setup('ETH')
        forming = repo.list_forming_smc_setups()
        assert len(forming) == 1, forming
        assert forming[0]['coin'] == 'ETH'
        assert forming[0]['direction'] == 'short'
        assert forming[0]['zone_low'] == 98.0 and forming[0]['zone_high'] == 100.0
        assert forming[0]['sweep_price'] == 130.0
        assert forming[0]['structure_level'] == 90.0
        assert forming[0]['liquidity_target'] == 90.0  # dichtstbijzijnde low-pivot onder de zone in de 30m-data
        assert forming[0]['alert_sent'] == 1  # eerste keer bouwend -> melding verstuurd (VAPID ontbreekt in dit script, send_push logt een warning en stuurt niets, maar mark_smc_alert_sent wordt nog steeds gezet)
        assert result is None  # nog geen afwijzing, dus nog geen kandidaat voor Task 5
        print('OK')

asyncio.run(main())
"
rm -f /tmp/scratch_smc_task4.db
```

Expected: `OK` zonder AssertionError.

- [ ] **Step 3b: Scratch-verificatie van meerdere cycli (persistentie zonder
  nieuwe breuk, en vervallen bij doorbraak zonder afwijzing)**

Dit is de regressietest voor het ontwerppunt hierboven Step 1: een
bouwende setup mag NIET verdwijnen zomaar omdat een latere cyclus geen
nieuwe structuurbreuk meer vindt (dat is normaal — een breuk gebeurt
eenmalig op de candle die op dat moment de laatste was). Drie cycli:
cyclus 1 maakt de setup (identieke data als Step 3 hierboven), cyclus 2
laat de 30m-candle herstellen tot een close tussen de gebroken swing-low
(90) en de geveegde swing-high (130) — geen nieuwe breuk — terwijl de
15m-prijs nog niet in de zone is; de setup moet intact blijven. Cyclus 3
laat de 15m-prijs de zone raken én er weer onder sluiten (afwijzing) —
dat moet de setup als kandidaat teruggeven.

```bash
DATABASE_PATH=/tmp/scratch_smc_task4b.db python3 -c "
import asyncio
import sys
sys.path.insert(0, '/home/user/Trade')
import pandas as pd
from unittest.mock import patch
from app import db, repo, market_scanner

db.init_db()

lows_30 =  [110, 108, 106, 104, 102, 90, 104, 106, 108, 110, 50]
highs_30 = [120, 118, 116, 114, 112, 100, 130, 116, 118, 120, 135]
closes_30 = [115, 113, 111, 109, 107, 95, 109, 111, 113, 115, 80]

rows_15_base = []
for _ in range(9):
    rows_15_base.append(dict(open=100, high=101, low=99, close=100))
rows_15_base.append(dict(open=99, high=101, low=98, close=100.5))
rows_15_base.append(dict(open=100.5, high=101, low=80, close=81))
rows_15_base.append(dict(open=81, high=83, low=79, close=80))
rows_15_base.append(dict(open=101, high=103, low=100, close=102))
rows_15_base.append(dict(open=95, high=96, low=85, close=86))
rows_15_base.append(dict(open=91, high=95, low=90, close=92))

state = {'lows_30': list(lows_30), 'highs_30': list(highs_30), 'closes_30': list(closes_30), 'rows_15': list(rows_15_base)}

def fake_fetch_ohlcv(coin, timeframe='4h', limit=200, since=None):
    if timeframe == '30m':
        return pd.DataFrame({
            'open': state['closes_30'], 'close': state['closes_30'],
            'high': state['highs_30'], 'low': state['lows_30'],
            'volume': [100.0] * len(state['closes_30']),
        })
    return pd.DataFrame(state['rows_15']).assign(volume=100.0)

async def main():
    with patch.object(market_scanner.exchange, 'fetch_ohlcv', side_effect=fake_fetch_ohlcv):
        # Cyclus 1: laatste 15m-candle nog niet in de zone (98-100) -> bouwend
        state['rows_15'].append(dict(open=80, high=82, low=78, close=79))
        r1 = await market_scanner._check_smc_setup('ETH')
        forming1 = repo.list_forming_smc_setups()
        assert r1 is None and len(forming1) == 1, forming1
        setup_id = forming1[0]['id']

        # Cyclus 2: 30m herstelt naar een close tussen 90 en 130 (GEEN
        # nieuwe breuk), 15m nog steeds niet in de zone -> setup blijft.
        state['lows_30'].append(76); state['highs_30'].append(98); state['closes_30'].append(95)
        state['rows_15'].append(dict(open=79, high=97, low=78, close=95))
        r2 = await market_scanner._check_smc_setup('ETH')
        forming2 = repo.list_forming_smc_setups()
        assert r2 is None, r2
        assert len(forming2) == 1 and forming2[0]['id'] == setup_id, forming2

        # Cyclus 3: 15m raakt de zone en sluit eronder -> afwijzing.
        state['lows_30'].append(96); state['highs_30'].append(101); state['closes_30'].append(99)
        state['rows_15'].append(dict(open=95, high=100, low=94, close=97))
        r3 = await market_scanner._check_smc_setup('ETH')
        assert r3 is not None and r3['id'] == setup_id, r3
        print('OK')

asyncio.run(main())
"
rm -f /tmp/scratch_smc_task4b.db
```

Expected: `OK` zonder AssertionError.

- [ ] **Step 4: Commit**

```bash
git add app/market_scanner.py
git commit -m "Voeg SMC-detectie en eenmalige bouwend-melding toe aan de marktscan"
```

---

## Task 5: market_scanner.py — afwijzing, signaal-aanmaak, fanout

**Files:**
- Modify: `app/market_scanner.py` (vervangt de Task 4-stub
  `_complete_smc_setup` door de echte implementatie)

**Interfaces:**
- Consumes: `repo.complete_smc_setup` (Task 3), `risk.compute_position_size`
  (ongewijzigd, bestaand: `compute_position_size(risk_eur, entry_price, stop_loss, cost_rate=0.0)`),
  `repo.insert_signal`, `fanout_confirmed_signal` (al geïmporteerd in dit
  bestand, `_KANSBEREKENING_NOT_APPLICABLE`-sentinel-pad), `indicators.find_sniper_entry_price`
  (bestaand, optioneel meegeven net als de andere drie detectoren doen).
- Produces: vervangt de placeholder `_complete_smc_setup(coin: str, setup: dict) -> None`
  uit Task 4 door de echte versie. Geen nieuwe publieke interface voor
  latere taken.

- [ ] **Step 1: Vervang de placeholder-functie**

Verwijder de Task 4-placeholder en vervang door:

```python
STOP_MARGIN_PCT = 0.1    # procent, marge voorbij de sweep
TARGET_MARGIN_PCT = 0.5  # procent, marge vóór de liquidity


async def _complete_smc_setup(coin: str, setup: dict) -> None:
    """Bouwt het echte signaal zodra _check_smc_setup een afgewezen zone
    teruggeeft. Geen ATR: stop en doel zijn volledig structuur-gebaseerd
    (zie de spec en de Global Constraints in dit plan). sign is voor
    zowel stop als doel hetzelfde teken, dat is geen typefout: voor short
    ligt de stop BOVEN de geveegde high (verder van de entry af) en het
    doel ligt ook BOVEN de liquidity-low (dichter bij de entry, 'net
    vóór' het niveau) — voor long allebei eronder. Zie de spec's
    zelf-review-correctie voor het concrete rekenvoorbeeld (short,
    sweep_price 2820, liquidity_target 2600 -> stop 2848, doel 2626)."""
    direction = setup["direction"]
    sign = -1 if direction == "long" else 1
    stop_loss = setup["sweep_price"] + STOP_MARGIN_PCT / 100 * setup["sweep_price"] * sign
    take_profit = setup["liquidity_target"] + TARGET_MARGIN_PCT / 100 * setup["liquidity_target"] * sign

    df_15m = await asyncio.to_thread(exchange.fetch_ohlcv, coin, timeframe="15m")
    entry_price = float(df_15m["close"].iloc[-1])

    reason = (
        f"SMC-liquidity-setup: structuur brak op {setup['structure_level']:.4f}, "
        f"sweep op {setup['sweep_price']:.4f}, zone {setup['zone_low']:.4f}-{setup['zone_high']:.4f}, "
        f"doel bij liquidity {setup['liquidity_target']:.4f}."
    )

    sniper = indicators.find_sniper_entry_price(direction, df_15m)
    sniper_entry_price, sniper_reason = sniper if sniper else (None, None)

    signal_data = {
        "message_id": None, "coin": coin, "direction": direction,
        "category": "day_trading", "trade_type": "smc", "pattern_name": "SMC liquidity sweep",
        "price": entry_price, "rsi": None, "macd": None, "macd_signal": None,
        "volume_ratio": None, "ema9": None, "ema21": None,
        "atr": None, "atr_avg20": None, "adx": None,
        "technical_confirmed": 1, "pass_pct": None, "hard_gates_ok": 1,
        "confidence": "SMC-setup bevestigd",
        "reason": reason,
        "stop_loss": stop_loss, "take_profit": take_profit,
        "context_note": None, "is_practice": 0, "plain_explanation": None,
        "suggested_entry_low": None, "suggested_entry_high": None,
        "sniper_entry_price": sniper_entry_price, "sniper_reason": sniper_reason,
    }
    signal_id = repo.insert_signal(signal_data)
    repo.complete_smc_setup(setup["id"], signal_id)

    def _smc_body(effective_stop_loss: float, effective_take_profit: float, stop_was_capped: bool) -> str:
        base = (
            f"Entry {entry_price:.4f} · Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}\n"
            f"Zone {setup['zone_low']:.4f}-{setup['zone_high']:.4f}, doel bij liquidity {setup['liquidity_target']:.4f}"
        )
        if sniper_entry_price is not None:
            base += f"\n🎯 Sniper: {sniper_entry_price:.4f} — {sniper_reason}"
        return base

    premise_level = setup["zone_high"] if direction == "short" else setup["zone_low"]
    await fanout_confirmed_signal(
        signal_id, coin, direction, entry_price, stop_loss, take_profit, premise_level,
        title=f"{push_notify.coin_symbol(coin)} {coin} {direction}, SMC liquidity sweep",
        make_body=_smc_body,
        reason=reason,
    )
```

- [ ] **Step 2: Regressietest voor de stop/doel-formule**

Rekent het concrete voorbeeld uit de spec na, los van de rest van de
functie (die vereist async/DB/netwerk):

```bash
python3 -c "
STOP_MARGIN_PCT = 0.1
TARGET_MARGIN_PCT = 0.5

def compute(direction, sweep_price, liquidity_target):
    sign = -1 if direction == 'long' else 1
    stop_loss = sweep_price + STOP_MARGIN_PCT / 100 * sweep_price * sign
    take_profit = liquidity_target + TARGET_MARGIN_PCT / 100 * liquidity_target * sign
    return stop_loss, take_profit

# Short: sweep_price 2820, liquidity_target 2600 -> stop 2848, doel 2626 (uit de spec)
stop, target = compute('short', 2820.0, 2600.0)
assert round(stop, 0) == 2848, stop
assert round(target, 0) == 2626, target

# Long, spiegelbeeld: sweep_price 2600 (geveegde low), liquidity_target 2820 (hoge liquidity)
stop, target = compute('long', 2600.0, 2820.0)
assert round(stop, 0) == 2597, stop     # net onder de sweep
assert round(target, 0) == 2806, target # net onder het doel
print('OK')
"
```

Expected: `OK`.

- [ ] **Step 3: Scratch-verificatie van de volledige `_complete_smc_setup`**

```bash
DATABASE_PATH=/tmp/scratch_smc_task5.db python3 -c "
import asyncio
import sys
sys.path.insert(0, '/home/user/Trade')
import pandas as pd
from unittest.mock import patch, AsyncMock
from app import db, repo, market_scanner

db.init_db()
uid = repo.create_user('testuser', 'x', 1000.0, 1.0)

setup_id = repo.upsert_smc_setup('ETH', 'short', 2695.0, 2710.0, 2820.0, 2825.0, 2600.0)

def fake_fetch_ohlcv(coin, timeframe='4h', limit=200, since=None):
    rows = [(2700, 2705, 2695, 2698)] * 5
    return pd.DataFrame(rows, columns=['open', 'high', 'low', 'close']).assign(volume=100.0)

async def main():
    with patch.object(market_scanner.exchange, 'fetch_ohlcv', side_effect=fake_fetch_ohlcv), \
         patch.object(market_scanner, 'fanout_confirmed_signal', new=AsyncMock()) as fanout_mock:
        setup = repo.list_forming_smc_setups()[0]
        await market_scanner._complete_smc_setup('ETH', setup)

        assert fanout_mock.await_count == 1
        signal_id = fanout_mock.await_args.args[0]
        signal = repo.get_signal(signal_id)
        assert signal['trade_type'] == 'smc'
        assert signal['pass_pct'] is None
        assert signal['hard_gates_ok'] == 1
        assert round(signal['stop_loss'], 0) == 2848
        assert round(signal['take_profit'], 0) == 2626

        # De bouwende setup is nu gekoppeld, verdwenen uit forming
        assert repo.list_forming_smc_setups() == []
        print('OK')

asyncio.run(main())
"
rm -f /tmp/scratch_smc_task5.db
```

Expected: `OK`.

- [ ] **Step 4: Commit**

```bash
git add app/market_scanner.py
git commit -m "Voeg SMC signaal-aanmaak en fanout toe (structuur-gebaseerde stop/doel)"
```

---

## Task 6: web/main.py + web/templates/smc.html — de /smc-pagina

**Files:**
- Modify: `web/main.py` (nieuwe route `/smc`)
- Create: `web/templates/smc.html`
- Modify: `web/templates/base.html` (nieuwe navigatielink)

**Interfaces:**
- Consumes: `repo.list_forming_smc_setups()` (Task 3), `repo.list_signalen_for_user`
  of vergelijkbaar gefilterd op `trade_type == "smc"` (bestaand patroon,
  zie `signalen_page`), `macros.signal_card` (bestaande macro).

- [ ] **Step 1: Voeg de route toe aan `web/main.py`**

Plaats bij de andere paginaroutes, bijvoorbeeld direct na `signalen_page`:

```python
@app.get("/smc")
async def smc_page(request: Request, user: dict = Depends(require_login)):
    """SMC liquidity-setups: bouwende setups bovenaan (de zone om een
    limit order op te zetten), afgeronde signalen daaronder in dezelfde
    stijl als /signalen. Afgeronde signalen verschijnen ook gewoon op de
    bestaande /signalen en het dashboard (zie de spec, Component 6) —
    deze pagina is een extra, gerichte weergave, geen aparte wereld."""
    forming = repo.list_forming_smc_setups()
    entries = [e for e in repo.list_signalen_for_user(user["id"]) if e["trade_type"] == "smc"]
    winrate = repo.winrate_stats(user["id"])
    pattern_winrate = repo.pattern_winrate_stats()
    entries = _add_signal_context(entries, winrate, pattern_winrate)
    entries.sort(key=lambda e: e["created_at"], reverse=True)
    return templates.TemplateResponse(request, "smc.html", {
        "user": user,
        "forming": forming,
        "entries": entries,
    })
```

- [ ] **Step 2: Maak `web/templates/smc.html`**

```html
{% extends "base.html" %}
{% import "_macros.html" as macros %}
{% block title %}SMC — HesPulse{% endblock %}
{% block content %}

<div class="page-head">
  <h2>SMC liquidity setups</h2>
</div>
<p class="page-intro">Structuurbreuk, liquidity sweep, terugtrek in een fair value gap of order block, afwijzing.</p>

<section class="card" style="--i: 0">
  <h3>Bouwende setups</h3>
  {% if not forming %}
  <p class="muted empty">Nog geen bouwende setup gevonden.</p>
  {% else %}
  {% for setup in forming %}
  <div class="smc-setup-card">
    <div class="smc-setup-head">
      <strong>{{ setup.coin }}</strong>
      <span class="muted">{{ setup.direction }}</span>
    </div>
    <div class="smc-setup-zone">Zone {{ "%.4f"|format(setup.zone_low) }} - {{ "%.4f"|format(setup.zone_high) }}</div>
    <details class="confidence-detail js-accordion">
      <summary>Waarom</summary>
      <p class="muted">
        Structuur brak op {{ "%.4f"|format(setup.structure_level) }},
        sweep op {{ "%.4f"|format(setup.sweep_price) }},
        doel bij liquidity {{ "%.4f"|format(setup.liquidity_target) }}.
      </p>
    </details>
  </div>
  {% endfor %}
  {% endif %}
</section>

<section class="card" style="--i: 1">
  <h3>Afgeronde signalen</h3>
  {% if not entries %}
  <p class="muted empty">Nog geen afgeronde SMC-signalen.</p>
  {% else %}
  <div class="signal-list">
    {% for entry in entries %}
    {{ macros.signal_card(entry, dismissible=False, showing_all=True) }}
    {% endfor %}
  </div>
  {% endif %}
</section>
{% endblock %}
```

- [ ] **Step 3: Voeg CSS toe aan `web/static/style.css`**

Nieuwe, eenvoudige regels voor `.smc-setup-card`/`.smc-setup-head`/
`.smc-setup-zone`, bijvoorbeeld direct na de bestaande
`.signal-card-sniper`-regels:

```css
.smc-setup-card {
  border: 1px solid var(--border); border-radius: var(--radius);
  padding: 12px; margin-bottom: 10px;
}
.smc-setup-head { display: flex; gap: 8px; align-items: baseline; margin-bottom: 4px; }
.smc-setup-zone { font-weight: 700; font-size: 15px; margin-bottom: 6px; }
```

- [ ] **Step 4: Voeg de navigatielink toe aan `web/templates/base.html`**

Zoek de bestaande navigatie (rond de links naar Signalen/Mijn account/
Coins/Meldingen/Uitleg) en voeg een link naar `/smc` toe, bijvoorbeeld
direct na de link naar Signalen:

```html
<a href="/smc">SMC</a>
```

- [ ] **Step 5: FastAPI TestClient-verificatie**

```bash
DATABASE_PATH=/tmp/scratch_smc_task6.db python3 -c "
from app import db, repo, security
db.init_db()
uid = repo.create_user('testuser', 'x', 1000.0, 1.0)
repo.upsert_smc_setup('BTC', 'long', 60000.0, 60500.0, 59000.0, 58800.0, 62000.0)

from fastapi.testclient import TestClient
from web.main import app, SESSION_COOKIE
client = TestClient(app)
token = security.create_session_token(uid)
client.cookies.set(SESSION_COOKIE, token)

resp = client.get('/smc')
assert resp.status_code == 200, resp.status_code
assert 'BTC' in resp.text
assert '60000' in resp.text or '60000.0000' in resp.text
print('OK')
"
rm -f /tmp/scratch_smc_task6.db
```

Expected: `OK`.

- [ ] **Step 6: Handmatige Playwright-verificatie**

Start de server tegen een scratch-DB met een paar handmatig ingevoegde
`smc_setups`-rijen (zelfde `upsert_smc_setup`-aanroep als Step 5),
bezoek `/smc` in een browser, controleer dat de zone leesbaar groot
staat, de "Waarom"-sectie uitklapt, en de navigatielink werkt vanaf elke
andere pagina.

- [ ] **Step 7: Commit**

```bash
git add web/main.py web/templates/smc.html web/templates/base.html web/static/style.css
git commit -m "Voeg /smc-pagina toe: bouwende setups en afgeronde SMC-signalen"
```

---

## Task 7: Volledige regressie + push

**Files:** geen wijzigingen, alleen verificatie.

- [ ] **Step 1: Draai alle eerdere scratch-scripts opnieuw achter elkaar**

```bash
python3 /tmp/test_smc_structure.py
python3 /tmp/test_smc_zones.py
```

Expected: alle `OK:`-regels van Task 1 en 2, geen fouten.

- [ ] **Step 2: End-to-end scenario — bouwend tot compleet, in één script**

```bash
DATABASE_PATH=/tmp/scratch_smc_final.db python3 -c "
import asyncio
import sys
sys.path.insert(0, '/home/user/Trade')
import pandas as pd
from unittest.mock import patch, AsyncMock
from app import db, repo, market_scanner

db.init_db()
uid = repo.create_user('testuser', 'x', 1000.0, 1.0)

# Fase 1: bouwend, nog geen afwijzing (hergebruikt Task 4's geverifieerde fake candles)
def fake_fetch_forming(coin, timeframe='4h', limit=200, since=None):
    if timeframe == '30m':
        lows =  [110, 108, 106, 104, 102, 90, 104, 106, 108, 110, 50]
        highs = [120, 118, 116, 114, 112, 100, 130, 116, 118, 120, 135]
        closes = [115, 113, 111, 109, 107, 95, 109, 111, 113, 115, 80]
        return pd.DataFrame({'open': closes, 'close': closes, 'high': highs, 'low': lows, 'volume': [100.0]*11})
    rows = []
    for _ in range(9):
        rows.append(dict(open=100, high=101, low=99, close=100))
    rows.append(dict(open=99, high=101, low=98, close=100.5))
    rows.append(dict(open=100.5, high=101, low=80, close=81))
    rows.append(dict(open=81, high=83, low=79, close=80))
    rows.append(dict(open=101, high=103, low=100, close=102))
    rows.append(dict(open=95, high=96, low=85, close=86))
    rows.append(dict(open=91, high=95, low=90, close=92))
    rows.append(dict(open=80, high=82, low=78, close=79))
    return pd.DataFrame(rows).assign(volume=100.0)

async def main():
    with patch.object(market_scanner.exchange, 'fetch_ohlcv', side_effect=fake_fetch_forming):
        result = await market_scanner._check_smc_setup('ETH')
        assert result is None
        forming = repo.list_forming_smc_setups()
        assert len(forming) == 1
        print('Fase 1 OK: bouwend, geen signaal')

    # Fase 2: geef de bouwende setup handmatig een afwijzende laatste candle
    # en roep _complete_smc_setup rechtstreeks aan (het volledige
    # geraakt+afgewezen-pad in _check_smc_setup vereist een langere
    # candle-reeks om exact op te zetten dan zinvol is in een scratch-
    # script; deze taak test dat pad al apart in Task 5 Step 3).
    setup = repo.list_forming_smc_setups()[0]
    def fake_fetch_entry(coin, timeframe='4h', limit=200, since=None):
        rows = [(90, 91, 89, 90)] * 5
        return pd.DataFrame(rows, columns=['open', 'high', 'low', 'close']).assign(volume=100.0)
    with patch.object(market_scanner.exchange, 'fetch_ohlcv', side_effect=fake_fetch_entry), \
         patch.object(market_scanner, 'fanout_confirmed_signal', new=AsyncMock()) as fanout_mock:
        await market_scanner._complete_smc_setup('ETH', setup)
        assert fanout_mock.await_count == 1
        signal_id = fanout_mock.await_args.args[0]
        signal = repo.get_signal(signal_id)
        assert signal['trade_type'] == 'smc'
        assert repo.list_forming_smc_setups() == []
        print('Fase 2 OK: compleet, signaal aangemaakt, bouwende setup opgeruimd')

    # Signaal moet ook gewoon op de normale /signalen-lijst verschijnen
    entries = repo.list_signalen_for_user(uid)
    assert any(e['trade_type'] == 'smc' for e in entries)
    print('OK: SMC-signaal verschijnt ook op de gewone signalenlijst')

asyncio.run(main())
"
rm -f /tmp/scratch_smc_final.db
```

- [ ] **Step 3: Handmatige Playwright-smoketest**

Start de server tegen een scratch-DB (zie Task 6 Step 6), doorloop:
`/smc` (bouwende sectie + afgeronde sectie, geen crash), `/signalen` (het
SMC-signaal uit Step 2 staat er ook tussen), navigatie vanaf elke andere
pagina naar `/smc` en terug. Stop de server na afloop.

- [ ] **Step 4: Push naar de branch**

```bash
git push -u origin claude/crypto-day-trading-alerts-5p8w6v
```
