# SMC premium/discount + liquidity sweeps Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HesPulse herkent premium/discount-zones en liquidity sweeps
(stop-hunts), elk op zowel de 4u- als de dagcandle, en telt ze mee als
vier nieuwe, gepoolde factoren in de uitgebreide toetsing.

**Architecture:** Twee pure detectiefuncties in `app/indicators.py`
(premium/discount rekent op `swing_levels`, liquidity sweep hergebruikt de
gedeelde `_find_pivots`), elk in een 4u- en een dag-variant — zelfde stijl
als het bestaande `check_daily_trend` naast `check_1h_trend`. Alle vier
sluiten aan op het bestaande fail-closed try/except-patroon in
`compute_advanced_extra_factors`, geen nieuwe Binance-aanroep (de
dag-candles worden daar al opgehaald voor Daily-trend/RSI daily).

**Tech Stack:** Python 3.11, pandas.

**Spec:** `docs/superpowers/specs/2026-09-16-smc-premium-discount-liquidity-sweeps-design.md`

## Global Constraints

- Geen database-migratie, geen chart-wijziging: alles live berekend uit
  al opgehaalde candle-data, puur tekst-factoren (spec, Niet-doelen).
- Geen extra Binance-aanroep: de dag-variant hergebruikt `daily_df`, al
  opgehaald in `compute_advanced_extra_factors` voor Daily-trend/RSI
  daily (spec, Sectie 3).
- `LIQUIDITY_SWEEP_RECENT_CANDLES = 3` (spec, Sectie 2).
- `check_liquidity_sweep`/`Liquidity sweep` is een andere naam dan de
  bestaande `check_liquidity`/`Liquiditeit` (24u handelsvolume) — niet
  hernoemen, niet samenvoegen, dat is een ander concept (spec, Sectie 2).
- `CONFIRM_THRESHOLD` blijft 60%. Van 17 naar 21 factoren totaal (5 basis
  + 16 uitgebreid: 3 vast + 13 los), van 15 naar 19 "overige" factoren
  (excl. Uitgerektheid en BTC-trend) in de pooling (spec, Sectie 4). Geen
  van de vier nieuwe factoren is een harde eis.
- Dit project heeft geen pytest-suite en geen testmap in de repo (zie
  CLAUDE.md). Elke test in dit plan is een losstaand, wegwerpbaar script
  in de sessie-scratchpad-map, gedraaid met `python3 <pad>` — niet
  gecommit naar de repo. Vervang `<SCRATCHPAD>` hieronder door het pad
  dat je systeemprompt als scratchpad-directory noemt.

---

### Task 1: Premium/discount en liquidity sweep detectie (`app/indicators.py`)

**Files:**
- Modify: `app/indicators.py` (nieuwe functies direct na `check_sr_zone`, regel 735, vóór de `BREAKOUT_RETEST_TOLERANCE_ATR_MULTIPLE`-sectie op regel 738)
- Test: `<SCRATCHPAD>/test_smc_factors.py`

**Interfaces:**
- Consumes: `Pivot` (dataclass, bestaat al: `index: int`, `price: float`, `kind: str`), `_find_pivots(window: pd.DataFrame) -> list[Pivot]` (bestaat al), `SR_ZONE_LOOKBACK` (bestaande constante, waarde 100).
- Produces (gebruikt door Task 2):
  - `check_premium_discount(direction: str, entry_price: float, swing_low: float, swing_high: float) -> tuple[str, bool, str]`
  - `check_daily_premium_discount(direction: str, entry_price: float, daily_swing_low: float, daily_swing_high: float) -> tuple[str, bool, str]`
  - `check_liquidity_sweep(direction: str, df: pd.DataFrame) -> tuple[str, bool, str]`
  - `check_daily_liquidity_sweep(direction: str, daily_df: pd.DataFrame) -> tuple[str, bool, str]`
  - `LIQUIDITY_SWEEP_RECENT_CANDLES = 3`

- [ ] **Step 1: Schrijf het testscript met de eerste falende asserties**

Maak `<SCRATCHPAD>/test_smc_factors.py`:

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


# --- check_premium_discount: long onder equilibrium is discount, ok ---
name, ok, detail = indicators.check_premium_discount("long", 95.0, swing_low=90.0, swing_high=110.0)
check("factornaam is 'Premium/discount'", name == "Premium/discount")
check("long onder equilibrium (100) is discount, ok", ok)
check("detail noemt discount", "discount" in detail)

# --- check_premium_discount: long boven equilibrium is premium, niet ok ---
name, ok, detail = indicators.check_premium_discount("long", 105.0, swing_low=90.0, swing_high=110.0)
check("long boven equilibrium (100) is premium, niet ok", not ok)
check("detail noemt premium", "premium" in detail)

# --- check_premium_discount: short boven equilibrium is premium, ok ---
name, ok, detail = indicators.check_premium_discount("short", 105.0, swing_low=90.0, swing_high=110.0)
check("short boven equilibrium is premium, ok", ok)

# --- check_premium_discount: short onder equilibrium is discount, niet ok ---
name, ok, detail = indicators.check_premium_discount("short", 95.0, swing_low=90.0, swing_high=110.0)
check("short onder equilibrium is discount, niet ok", not ok)

# --- check_premium_discount: vlakke range geeft nette fail, geen crash ---
name, ok, detail = indicators.check_premium_discount("long", 100.0, swing_low=100.0, swing_high=100.0)
check("vlakke range: factor faalt met duidelijke reden", not ok and "vlak" in detail)

# --- check_daily_premium_discount: zelfde logica, eigen naam ---
name, ok, detail = indicators.check_daily_premium_discount("long", 95.0, daily_swing_low=90.0, daily_swing_high=110.0)
check("factornaam is 'Premium/discount (dag)'", name == "Premium/discount (dag)")
check("long onder daily equilibrium is discount, ok", ok)

# --- liquidity sweep: pivot-low geveegd, candle sluit terug erboven (long) ---
rows = []
for i in range(20):
    if i == 10:
        rows.append({"open": 100.5, "high": 101.0, "low": 100.0, "close": 100.8})
    else:
        rows.append({"open": 103.0, "high": 104.0, "low": 102.0, "close": 103.5})
rows[19] = {"open": 100.8, "high": 101.5, "low": 99.0, "close": 100.5}
df_long_sweep = pd.DataFrame(rows)

name, ok, detail = indicators.check_liquidity_sweep("long", df_long_sweep)
check("factornaam is 'Liquidity sweep'", name == "Liquidity sweep")
check("long: pivot-low geveegd en teruggesloten telt als sweep", ok)

# --- liquidity sweep: pivot-high geveegd, candle sluit terug eronder (short) ---
rows = []
for i in range(20):
    if i == 10:
        rows.append({"open": 109.5, "high": 110.0, "low": 109.0, "close": 109.2})
    else:
        rows.append({"open": 105.0, "high": 106.0, "low": 104.0, "close": 105.5})
rows[19] = {"open": 109.2, "high": 111.0, "low": 108.5, "close": 109.5}
df_short_sweep = pd.DataFrame(rows)

name, ok, detail = indicators.check_liquidity_sweep("short", df_short_sweep)
check("short: pivot-high geveegd en teruggesloten telt als sweep", ok)

# --- liquidity sweep: geen sweep, factor faalt netjes ---
rows = [{"open": 103.0, "high": 104.0, "low": 102.0, "close": 103.5} for _ in range(20)]
df_no_sweep = pd.DataFrame(rows)
name, ok, detail = indicators.check_liquidity_sweep("long", df_no_sweep)
check("geen sweep: factor faalt met duidelijke reden", not ok and "geen recente stop-hunt" in detail)

# --- check_daily_liquidity_sweep: zelfde logica, eigen naam ---
name, ok, detail = indicators.check_daily_liquidity_sweep("long", df_long_sweep)
check("factornaam is 'Liquidity sweep (dag)'", name == "Liquidity sweep (dag)")
check("daily sweep telt ook mee", ok)

print(f"\n=== {passed} geslaagd, {failed} gefaald ===")
sys.exit(1 if failed else 0)
```

- [ ] **Step 2: Run het script, bevestig `AttributeError`**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_smc_factors.py
```

Verwacht: `AttributeError: module 'app.indicators' has no attribute 'check_premium_discount'`.

- [ ] **Step 3: Implementeer `check_premium_discount` en `check_daily_premium_discount` in `app/indicators.py`**

Voeg toe direct na regel 735 (na `check_sr_zone`, vóór de
`BREAKOUT_RETEST_TOLERANCE_ATR_MULTIPLE`-comment op regel 738):

```python
def check_premium_discount(
    direction: str, entry_price: float, swing_low: float, swing_high: float,
) -> tuple[str, bool, str]:
    """Ligt de entry in de goedkope (discount) of dure (premium) helft van
    de recente swing-range (swing_levels, dezelfde die ook de stop-
    plaatsing bepaalt)? Long is sterker onder het midden (equilibrium),
    short erboven — de klassieke SMC-knip op 50%, geen marge: een long
    net onder equilibrium is nog altijd relatief goedkoop, een long er
    net boven is dat per definitie niet meer."""
    direction = direction.lower()
    if swing_high == swing_low:
        return ("Premium/discount", False, "range te vlak om te bepalen")
    equilibrium = (swing_low + swing_high) / 2
    if direction == "long":
        ok = entry_price <= equilibrium
        kant = "discount" if ok else "premium"
    else:
        ok = entry_price >= equilibrium
        kant = "premium" if ok else "discount"
    detail = f"entry in {kant}-zone (equilibrium {equilibrium:.4f})"
    return ("Premium/discount", ok, detail)


def check_daily_premium_discount(
    direction: str, entry_price: float, daily_swing_low: float, daily_swing_high: float,
) -> tuple[str, bool, str]:
    """Zelfde check als check_premium_discount, maar op de swing-range van
    de dagcandle in plaats van 4u — een daily premium/discount-zone is een
    sterker signaal, dezelfde reden waarom Daily-trend naast de 4u-
    trendfactor bestaat."""
    direction = direction.lower()
    if daily_swing_high == daily_swing_low:
        return ("Premium/discount (dag)", False, "range te vlak om te bepalen")
    equilibrium = (daily_swing_low + daily_swing_high) / 2
    if direction == "long":
        ok = entry_price <= equilibrium
        kant = "discount" if ok else "premium"
    else:
        ok = entry_price >= equilibrium
        kant = "premium" if ok else "discount"
    detail = f"entry in {kant}-zone op daily (equilibrium {equilibrium:.4f})"
    return ("Premium/discount (dag)", ok, detail)
```

- [ ] **Step 4: Run het script, bevestig dat de premium/discount-asserties slagen en de liquidity-sweep-asserties nog falen op `AttributeError`**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_smc_factors.py
```

- [ ] **Step 5: Implementeer de liquidity sweep-functies in `app/indicators.py`**

Voeg toe direct na de twee functies uit Step 3:

```python
# Hoeveel van de laatste candles gecontroleerd worden op een sweep van een
# eerdere pivot. Kort genoeg om alleen een verse sweep te vangen, niet een
# willekeurige oude pen-doorbraak die allang geen rol meer speelt — zelfde
# soort venster als SR_ZONE_BOUNCE_LOOKBACK, kleiner omdat een sweep per
# definitie een kortstondige gebeurtenis is (één candle, niet een
# meerdaagse terugveer).
LIQUIDITY_SWEEP_RECENT_CANDLES = 3


def _find_liquidity_sweep(window: pd.DataFrame, direction: str) -> Optional[Pivot]:
    """Gedeelde kernlogica voor check_liquidity_sweep en
    check_daily_liquidity_sweep: zoekt in `window` een pivot van de
    stop-kant (low voor long, high voor short) die door een van de
    laatste LIQUIDITY_SWEEP_RECENT_CANDLES candles met zijn pen doorbroken
    is, waarna diezelfde candle terugsloot aan de oorspronkelijke kant.
    Geeft de meest recente treffer terug, of None."""
    pivots = _find_pivots(window)
    kind = "low" if direction == "long" else "high"
    cutoff = len(window) - LIQUIDITY_SWEEP_RECENT_CANDLES
    candidates = [p for p in pivots if p.kind == kind and p.index < cutoff]
    if not candidates:
        return None

    recent = window.tail(LIQUIDITY_SWEEP_RECENT_CANDLES)
    for _, candle in recent.iloc[::-1].iterrows():
        for p in candidates:
            if direction == "long":
                swept = candle["low"] < p.price and candle["close"] > p.price
            else:
                swept = candle["high"] > p.price and candle["close"] < p.price
            if swept:
                return p
    return None


def check_liquidity_sweep(direction: str, df: pd.DataFrame) -> tuple[str, bool, str]:
    """Liquidity sweep op de hoofd-timeframe (4u): is er, in de laatste
    LIQUIDITY_SWEEP_RECENT_CANDLES candles, een stop-hunt geweest van een
    eerdere pivot-low (long) of pivot-high (short), gevolgd door een close
    terug aan de goede kant? Andere invalshoek dan check_sr_zone: die kijkt
    naar een bevestigde terugveer over meerdere candles, dit naar één
    scherpe pen-doorbraak-en-terugsluiting. Bewust een andere naam dan
    check_liquidity (24u handelsvolume) — compleet ander concept, zie die
    functie se docstring."""
    direction = direction.lower()
    window = df.tail(SR_ZONE_LOOKBACK).reset_index(drop=True)
    hit = _find_liquidity_sweep(window, direction)
    if hit is None:
        return ("Liquidity sweep", False, "geen recente stop-hunt gevonden")
    return ("Liquidity sweep", True, f"stop-hunt van {hit.price:.4f}, candle sloot terug aan de goede kant")


def check_daily_liquidity_sweep(direction: str, daily_df: pd.DataFrame) -> tuple[str, bool, str]:
    """Zelfde check als check_liquidity_sweep, maar op de dagcandle — een
    sweep van een daily swing high/low is een sterker signaal, klassieke
    SMC-liquiditeit zit vaak juist op dagniveau (de meest voor de hand
    liggende stop-plek voor de meeste marktdeelnemers)."""
    direction = direction.lower()
    window = daily_df.tail(SR_ZONE_LOOKBACK).reset_index(drop=True)
    hit = _find_liquidity_sweep(window, direction)
    if hit is None:
        return ("Liquidity sweep (dag)", False, "geen recente stop-hunt op daily gevonden")
    return ("Liquidity sweep (dag)", True, f"stop-hunt op daily van {hit.price:.4f}, candle sloot terug aan de goede kant")
```

- [ ] **Step 6: Run het volledige script, bevestig dat alle asserties slagen**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_smc_factors.py
```

Verwacht: `=== 16 geslaagd, 0 gefaald ===`.

- [ ] **Step 7: Commit**

```bash
git add app/indicators.py
git commit -m "$(cat <<'EOF'
SMC: premium/discount en liquidity sweep detectie (4u + dag)

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

### Task 2: Koppeling in `signal_processor.py` (`compute_advanced_extra_factors`)

**Files:**
- Modify: `app/signal_processor.py` (functie `compute_advanced_extra_factors`, regel 590-662)
- Test: `<SCRATCHPAD>/test_smc_factors_pipeline.py`

**Interfaces:**
- Consumes: `indicators.check_premium_discount`, `indicators.check_daily_premium_discount`, `indicators.check_liquidity_sweep`, `indicators.check_daily_liquidity_sweep`, `indicators.swing_levels` (bestaat al) (Task 1).
- Produces: `compute_advanced_extra_factors` geeft nu 4 extra tuples terug
  in de lijst (`("Premium/discount", ...)`, `("Premium/discount (dag)", ...)`,
  `("Liquidity sweep", ...)`, `("Liquidity sweep (dag)", ...)`), signatuur
  ongewijzigd — geen aanpassing nodig in `web/main.py`'s oefentrade-route.

- [ ] **Step 1: Voeg de daily-varianten toe aan het bestaande Daily-trend/RSI daily-blok**

Zoek in `app/signal_processor.py` (rond regel 616-624):

```python
    try:
        daily_df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, "1d")
        daily_ind = indicators.compute_indicators(daily_df)
        factors.append(indicators.check_daily_trend(direction, daily_ind))
        factors.append(indicators.check_daily_rsi(direction, daily_ind))
    except Exception:
        logger.exception("Daily-trend/RSI voor %s kon niet berekend worden", coin)
        factors.append(("Daily-trend", False, "kon niet opgehaald worden, telt als niet bevestigd"))
        factors.append(("RSI daily", False, "kon niet opgehaald worden, telt als niet bevestigd"))
```

Vervang door:

```python
    try:
        daily_df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, "1d")
        daily_ind = indicators.compute_indicators(daily_df)
        factors.append(indicators.check_daily_trend(direction, daily_ind))
        factors.append(indicators.check_daily_rsi(direction, daily_ind))
        daily_swing_low, daily_swing_high = indicators.swing_levels(daily_df)
        factors.append(indicators.check_daily_premium_discount(direction, entry_price, daily_swing_low, daily_swing_high))
        factors.append(indicators.check_daily_liquidity_sweep(direction, daily_df))
    except Exception:
        logger.exception("Daily-trend/RSI voor %s kon niet berekend worden", coin)
        factors.append(("Daily-trend", False, "kon niet opgehaald worden, telt als niet bevestigd"))
        factors.append(("RSI daily", False, "kon niet opgehaald worden, telt als niet bevestigd"))
        factors.append(("Premium/discount (dag)", False, "kon niet opgehaald worden, telt als niet bevestigd"))
        factors.append(("Liquidity sweep (dag)", False, "kon niet opgehaald worden, telt als niet bevestigd"))
```

- [ ] **Step 2: Voeg de 4u-varianten toe na het bestaande Steun/weerstand-blok**

Zoek (rond regel 656-660, het laatste blok vóór `return factors`):

```python
    try:
        factors.append(indicators.check_sr_zone(direction, entry_price, atr, zones, df))
    except Exception:
        logger.exception("Steun/weerstand voor %s kon niet berekend worden", coin)
        factors.append(("Steun/weerstand", False, "kon niet berekend worden, telt als niet bevestigd"))

    return factors
```

Vervang door:

```python
    try:
        factors.append(indicators.check_sr_zone(direction, entry_price, atr, zones, df))
    except Exception:
        logger.exception("Steun/weerstand voor %s kon niet berekend worden", coin)
        factors.append(("Steun/weerstand", False, "kon niet berekend worden, telt als niet bevestigd"))

    try:
        swing_low, swing_high = indicators.swing_levels(df)
        factors.append(indicators.check_premium_discount(direction, entry_price, swing_low, swing_high))
    except Exception:
        logger.exception("Premium/discount voor %s kon niet berekend worden", coin)
        factors.append(("Premium/discount", False, "kon niet berekend worden, telt als niet bevestigd"))

    try:
        factors.append(indicators.check_liquidity_sweep(direction, df))
    except Exception:
        logger.exception("Liquidity sweep voor %s kon niet berekend worden", coin)
        factors.append(("Liquidity sweep", False, "kon niet berekend worden, telt als niet bevestigd"))

    return factors
```

`swing_levels(df)` wordt hier opnieuw aangeroepen in plaats van als
parameter doorgegeven — een pandas-berekening op data die al in geheugen
zit (`df` is al opgehaald door de aanroeper), geen extra kosten, en de
functiesignatuur (twee aanroepplekken: `process_day_trading_signal` en
`web/main.py`'s oefentrade-route) blijft ongewijzigd (spec, Sectie 3).

- [ ] **Step 3: Schrijf en run de integratietest**

Maak `<SCRATCHPAD>/test_smc_factors_pipeline.py`, naar het patroon van de
eerdere `test_sr_zones_pipeline.py` uit deze sessie: tijdelijke DB,
`ENABLE_ADVANCED_FACTORS=true`, gemockte `exchange.fetch_ohlcv` voor
4h/1h/1d/BTC, `coinlist.ensure_coin_tracked` gemockt op `(True, False)`.
De 4u-candle-data bevat dezelfde bewuste pivot-low-sweep als in Task 1
(gesimuleerd op een realistische prijsschaal), zodat zowel
"Liquidity sweep" als "Premium/discount" aantoonbaar in de reason-string
terechtkomen.

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
os.environ["JWT_SECRET"] = "test-secret-smc-factors-pipeline-0123456789012345"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"
os.environ["ENABLE_ADVANCED_FACTORS"] = "true"

from app import config
config.DATABASE_PATH = db_path
config.ENABLE_ADVANCED_FACTORS = True

from app import db, repo, security, signal_processor, coinlist
from app.anthropic_interpret import Interpretation
from app.db import session as db_session

import numpy as np
import pandas as pd

db.init_db()
repo.create_user("smcfactoruser", security.hash_password("testpass123"), 10000.0, 1.0, "1")
repo.add_coin_if_new("SUIUSDT", "spot")

# 4u-candles: vlakke bodem rond 0.640 (pivot-low), laatste candle veegt
# er met de pen onderdoor en sluit terug erboven op 0.650 — zowel een
# liquidity sweep als, met swing_low/high op respectievelijk ~0.639/0.660,
# een entry in de onderste (discount) helft van de range.
rows = []
for i in range(90):
    if i == 45:
        rows.append({"open": 0.6405, "high": 0.6420, "low": 0.6400, "close": 0.6410, "volume": 500000.0})
    else:
        rows.append({"open": 0.655, "high": 0.660, "low": 0.650, "close": 0.657, "volume": 500000.0})
rows[-1] = {"open": 0.646, "high": 0.652, "low": 0.639, "close": 0.650, "volume": 500000.0}
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
    row = conn.execute("SELECT reason FROM signals ORDER BY id DESC LIMIT 1").fetchone()

assert row is not None, "geen signal-rij aangemaakt"
reason = row["reason"]
print(f"reason: {reason}")
assert "Liquidity sweep" in reason, f"factor 'Liquidity sweep' ontbreekt: {reason}"
print("OK: 'Liquidity sweep' zit in de breakdown")
assert "Premium/discount" in reason, f"factor 'Premium/discount' ontbreekt: {reason}"
print("OK: 'Premium/discount' zit in de breakdown")
assert "(dag)" in reason, f"geen daily-variant zichtbaar in de breakdown: {reason}"
print("OK: minstens één daily-variant ('(dag)') zit in de breakdown")
```

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_smc_factors_pipeline.py
```

Verwacht: script eindigt met de laatste `print`-regel, geen traceback
vóór die regel (de Telegram-stap erna mag wél een `NetworkError` geven,
zie CLAUDE.md, dat is de bekende sandbox-beperking, geen testfout). Als
een assertie faalt omdat de fake candle-data een andere uitkomst oplevert
dan verwacht: print `indicators.check_liquidity_sweep("long", fake_4h)` en
`indicators.check_premium_discount("long", fake_4h["close"].iloc[-1], *indicators.swing_levels(fake_4h))`
om te zien wat de functies er echt uit halen, pas de fake-data aan zodat
ze overeenkomt, verander niet de productielogica om de test te laten
slagen.

- [ ] **Step 4: Commit**

```bash
git add app/signal_processor.py
git commit -m "$(cat <<'EOF'
Bedraad premium/discount en liquidity sweep in de uitgebreide toetsing

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

### Task 3: Documentatie-tekstupdates (`app/indicators.py`)

**Files:**
- Modify: `app/indicators.py` (docstrings van `CONFIRM_THRESHOLD` en `confirms_direction`)

**Interfaces:**
- Consumes: geen nieuwe code, puur tekst — Task 1 en Task 2 zijn al
  functioneel compleet, dit is documentatie die de nieuwe aantallen
  bijwerkt.
- Produces: niets voor latere taken.

- [ ] **Step 1: Werk de `CONFIRM_THRESHOLD`-docstring bij**

Zoek in `app/indicators.py` (rond regel 945-958):

```python
# In de uitgebreide versie telt geen enkele factor apart als harde eis: met
# 17 factoren in totaal (5 basis + 12 uitgebreid) blokkeert anders één
# marginale miss (bijvoorbeeld volume op 0.89x in plaats van 1.0x) een
# verder overtuigend signaal volledig, terwijl bijna alle andere factoren
# wel klopten. Minstens 60% is hier de grens: is dat gehaald, dan is het
# een melding waard, en blijft het aan de gebruiker zelf om op basis van de
# zichtbare ✓/✗ per factor te beslissen of hij hem neemt. De factoren die
# hun eigen candle-data ophalen (BTC-trend, Daily-trend, RSI daily, 1u
# bevestiging, RSI 1u, Divergentie, Candlepatroon, Liquiditeit) tellen
# "fail-closed" mee: lukt het ophalen niet, dan telt de factor als niet
# gehaald in plaats van dat de melding daarop crasht of de factor
# overslaat, dus een tijdelijke ophaalfout kan in het slechtste geval één
# factor kosten.
CONFIRM_THRESHOLD = 0.6
```

Vervang door:

```python
# In de uitgebreide versie telt geen enkele factor apart als harde eis: met
# 21 factoren in totaal (5 basis + 16 uitgebreid) blokkeert anders één
# marginale miss (bijvoorbeeld volume op 0.89x in plaats van 1.0x) een
# verder overtuigend signaal volledig, terwijl bijna alle andere factoren
# wel klopten. Minstens 60% is hier de grens: is dat gehaald, dan is het
# een melding waard, en blijft het aan de gebruiker zelf om op basis van de
# zichtbare ✓/✗ per factor te beslissen of hij hem neemt. De factoren die
# hun eigen candle-data ophalen (BTC-trend, Daily-trend, RSI daily,
# Premium/discount (dag), Liquidity sweep (dag), 1u bevestiging, RSI 1u,
# Divergentie, Candlepatroon, Liquiditeit) tellen "fail-closed" mee: lukt
# het ophalen niet, dan telt de factor als niet gehaald in plaats van dat
# de melding daarop crasht of de factor overslaat, dus een tijdelijke
# ophaalfout kan in het slechtste geval meerdere factoren kosten (voor de
# daily-fetch: Daily-trend, RSI daily, Premium/discount (dag) en Liquidity
# sweep (dag) tegelijk).
CONFIRM_THRESHOLD = 0.6
```

- [ ] **Step 2: Werk de `confirms_direction`-docstring bij**

Zoek (rond regel 1065-1078):

```python
    Uitgebreide versie (`include_advanced=True`, aan via
    config.ENABLE_ADVANCED_FACTORS): daar komen drie vaste factoren bij,
    trendsterkte (ADX), volatiliteit (ATR t.o.v. zijn eigen 20-candle
    gemiddelde) en volume-percentiel, plus wat er in `extra_factors`
    meegegeven wordt (BTC-trend, Daily-trend, RSI daily, 1u bevestiging,
    RSI 1u, Divergentie, Candlepatroon, Liquiditeit, Steun/weerstand: elk
    een (naam, ok, detail) tuple, berekend buiten deze functie omdat ze
    andere data nodig hebben — zie signal_processor.compute_advanced_extra_factors).
    Bevestigd is hier een kwestie van hoeveel van de OVERIGE factoren
    (dus zonder Uitgerektheid en BTC-trend, die allebei hun eigen harde
    eis hebben, zie hieronder) in totaal kloppen (zie CONFIRM_THRESHOLD),
    niet van elke losse factor apart hard vereisen: bij 15 overige
    factoren samen (4 basis + 11 uitgebreid) blokkeert anders één
    marginale miss een verder overtuigend signaal.
```

Vervang door:

```python
    Uitgebreide versie (`include_advanced=True`, aan via
    config.ENABLE_ADVANCED_FACTORS): daar komen drie vaste factoren bij,
    trendsterkte (ADX), volatiliteit (ATR t.o.v. zijn eigen 20-candle
    gemiddelde) en volume-percentiel, plus wat er in `extra_factors`
    meegegeven wordt (BTC-trend, Daily-trend, RSI daily, Premium/discount,
    Premium/discount (dag), Liquidity sweep, Liquidity sweep (dag), 1u
    bevestiging, RSI 1u, Divergentie, Candlepatroon, Liquiditeit,
    Steun/weerstand: elk een (naam, ok, detail) tuple, berekend buiten
    deze functie omdat ze andere data nodig hebben — zie
    signal_processor.compute_advanced_extra_factors).
    Bevestigd is hier een kwestie van hoeveel van de OVERIGE factoren
    (dus zonder Uitgerektheid en BTC-trend, die allebei hun eigen harde
    eis hebben, zie hieronder) in totaal kloppen (zie CONFIRM_THRESHOLD),
    niet van elke losse factor apart hard vereisen: bij 19 overige
    factoren samen (4 basis + 15 uitgebreid) blokkeert anders één
    marginale miss een verder overtuigend signaal.
```

- [ ] **Step 3: Controleer dat de module nog importeert zonder fouten**

```bash
source /home/user/Trade/.venv/bin/activate && python3 -c "import app.indicators"
```

Verwacht: geen output, geen traceback.

- [ ] **Step 4: Commit**

```bash
git add app/indicators.py
git commit -m "$(cat <<'EOF'
Docs: factorentelling bijwerken naar 21 totaal / 19 overige

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

### Task 4: `/uitleg`-pagina (`web/templates/uitleg.html`)

**Files:**
- Modify: `web/templates/uitleg.html`
- Test: `<SCRATCHPAD>/test_uitleg_smc_factors.py`

**Interfaces:**
- Consumes: geen nieuwe backend-code, puur template-tekst.
- Produces: niets voor latere taken.

- [ ] **Step 1: Werk het aantal in het BTC-trend-blok bij**

Zoek (rond regel 172-180):

```html
    <div class="factor factor-preview">
      <h3>BTC-trend</h3>
      <p>Voor altcoins: staat Bitcoin zelf niet lijnrecht tegenover de
      trade in? De hele markt volgt vaak BTC. Anders dan de andere elf
      factoren hieronder is dit een harde eis, net als Uitgerektheid:
```

Vervang `elf` door `vijftien`:

```html
    <div class="factor factor-preview">
      <h3>BTC-trend</h3>
      <p>Voor altcoins: staat Bitcoin zelf niet lijnrecht tegenover de
      trade in? De hele markt volgt vaak BTC. Anders dan de andere
      vijftien factoren hieronder is dit een harde eis, net als Uitgerektheid:
```

- [ ] **Step 2: Voeg vier nieuwe factor-blokken toe na Steun/weerstand**

Zoek (rond regel 221-228):

```html
    <div class="factor factor-preview">
      <h3>Steun/weerstand</h3>
      <p>Ligt er een zone binnen 6x ATR aan de stop-kant van de entry —
      een prijsniveau waar de markt zelf al minstens twee keer eerder
      keerde? Dezelfde zone verscherpt ook de voorgestelde stop loss en
      take profit.</p>
    </div>
  </div>
```

Vervang door:

```html
    <div class="factor factor-preview">
      <h3>Steun/weerstand</h3>
      <p>Ligt er een zone binnen 6x ATR aan de stop-kant van de entry —
      een prijsniveau waar de markt zelf al minstens twee keer eerder
      keerde? Dezelfde zone verscherpt ook de voorgestelde stop loss en
      take profit.</p>
    </div>
    <div class="factor factor-preview">
      <h3>Premium/discount</h3>
      <p>Staat de entry in de goedkope (discount) of dure (premium) helft
      van de recente swing-range? Long is sterker onder het midden van die
      range, short erboven — de klassieke Smart Money-knip op 50%.</p>
    </div>
    <div class="factor factor-preview">
      <h3>Premium/discount (dag)</h3>
      <p>Dezelfde check als hierboven, maar dan op de swing-range van de
      dagcandle: een daily premium/discount-niveau is een sterker signaal
      dan hetzelfde op 4 uur.</p>
    </div>
    <div class="factor factor-preview">
      <h3>Liquidity sweep</h3>
      <p>Is er een eerdere swing low/high met de pen doorbroken (niet de
      slotkoers), waarna de candle terugsloot aan de goede kant? Een
      klassieke stop-hunt: de markt haalt eerst de liquiditeit onder/boven
      dat niveau op, en draait daarna de andere kant op.</p>
    </div>
    <div class="factor factor-preview">
      <h3>Liquidity sweep (dag)</h3>
      <p>Dezelfde check als hierboven, maar dan op de dagcandle: een sweep
      van een daily swing high/low is een sterker signaal, dat is vaak
      juist de meest voor de hand liggende stop-plek voor de markt.</p>
    </div>
  </div>
```

- [ ] **Step 3: Schrijf en run een test die de bijgewerkte pagina controleert**

Maak `<SCRATCHPAD>/test_uitleg_smc_factors.py`, naar het patroon van de
eerdere `test_uitleg_sr_zones.py` uit deze sessie:

```python
import os
import sys
import tempfile

sys.path.insert(0, "/home/user/Trade")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-uitleg-smc-factors-0123456789012345"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path

from app import db
from fastapi.testclient import TestClient
from web.main import app

db.init_db()
client = TestClient(app)

resp = client.get("/uitleg")
assert resp.status_code == 200, resp.text
html = resp.text
for expected in [
    "Premium/discount</h3>",
    "Premium/discount (dag)</h3>",
    "Liquidity sweep</h3>",
    "Liquidity sweep (dag)</h3>",
    "vijftien factoren hieronder",
]:
    assert expected in html, f"'{expected}' ontbreekt op de uitleg-pagina"
print("OK: alle vier nieuwe factor-blokken en het bijgewerkte aantal staan op /uitleg")
```

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_uitleg_smc_factors.py
```

Verwacht: `OK: alle vier nieuwe factor-blokken en het bijgewerkte aantal staan op /uitleg`.

- [ ] **Step 4: Commit**

```bash
git add web/templates/uitleg.html
git commit -m "$(cat <<'EOF'
Uitleg-pagina: premium/discount en liquidity sweep factoren toevoegen

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

### Task 5: Backtest (`scripts/backtest_factors.py`)

**Files:**
- Modify: `scripts/backtest_factors.py`

**Interfaces:**
- Consumes: `indicators.swing_levels`, `indicators.check_premium_discount`,
  `indicators.check_daily_premium_discount`, `indicators.check_liquidity_sweep`,
  `indicators.check_daily_liquidity_sweep` (Task 1).
- Produces: niets voor latere taken — dit is een operator-tool, geen
  onderdeel van de live pipeline.

- [ ] **Step 1: Werk het 4u-blok van `evaluate_signal` bij**

Zoek (rond regel 58-77):

```python
    try:
        df = _historical_df(coin, "4h", created_at)
        if len(df) < 30:
            results["4u data"] = None
            return results
        ind = indicators.compute_indicators(df)
        strong_enough = ind.adx >= indicators.ADX_MIN
        direction_aligned = ind.adx_pos > ind.adx_neg if direction.lower() == "long" else ind.adx_neg > ind.adx_pos
        results["Trendsterkte (ADX+richting)"] = strong_enough and direction_aligned
        results["ATR stijgend"] = ind.atr >= ind.atr_avg20
        _, div_ok, _ = indicators.check_divergence(df, direction)
        results["Geen divergentie"] = div_ok
        ema9_hist, ema21_hist = indicators.ema_series(df)
        _, candle_ok, _ = indicators.check_candle_pattern_extended(df, direction, ema9_hist, ema21_hist)
        results["Candlepatroon"] = candle_ok
        _, vol_pct_ok, _ = indicators.check_volume_percentile(ind)
        results["Volume-percentiel"] = vol_pct_ok
        zones = indicators.detect_sr_zones(df)
        _, sr_ok, _ = indicators.check_sr_zone(direction, ind.price, ind.atr, zones, df)
        results["Steun/weerstand"] = sr_ok
    except Exception as exc:
        results["4u data"] = None
        print(f"    (4u data mislukt: {exc})")
        return results
```

Vervang door:

```python
    try:
        df = _historical_df(coin, "4h", created_at)
        if len(df) < 30:
            results["4u data"] = None
            return results
        ind = indicators.compute_indicators(df)
        strong_enough = ind.adx >= indicators.ADX_MIN
        direction_aligned = ind.adx_pos > ind.adx_neg if direction.lower() == "long" else ind.adx_neg > ind.adx_pos
        results["Trendsterkte (ADX+richting)"] = strong_enough and direction_aligned
        results["ATR stijgend"] = ind.atr >= ind.atr_avg20
        _, div_ok, _ = indicators.check_divergence(df, direction)
        results["Geen divergentie"] = div_ok
        ema9_hist, ema21_hist = indicators.ema_series(df)
        _, candle_ok, _ = indicators.check_candle_pattern_extended(df, direction, ema9_hist, ema21_hist)
        results["Candlepatroon"] = candle_ok
        _, vol_pct_ok, _ = indicators.check_volume_percentile(ind)
        results["Volume-percentiel"] = vol_pct_ok
        zones = indicators.detect_sr_zones(df)
        _, sr_ok, _ = indicators.check_sr_zone(direction, ind.price, ind.atr, zones, df)
        results["Steun/weerstand"] = sr_ok
        swing_low, swing_high = indicators.swing_levels(df)
        _, pd_ok, _ = indicators.check_premium_discount(direction, ind.price, swing_low, swing_high)
        results["Premium/discount"] = pd_ok
        _, sweep_ok, _ = indicators.check_liquidity_sweep(direction, df)
        results["Liquidity sweep"] = sweep_ok
    except Exception as exc:
        results["4u data"] = None
        print(f"    (4u data mislukt: {exc})")
        return results
```

- [ ] **Step 2: Werk het daily-blok van `evaluate_signal` bij**

Zoek (regel 105-115):

```python
    try:
        daily_df = _historical_df(coin, "1d", created_at, candles_needed=60)
        daily_ind = indicators.compute_indicators(daily_df)
        _, daily_ok, _ = indicators.check_daily_trend(direction, daily_ind)
        results["Daily-trend"] = daily_ok
        _, daily_rsi_ok, _ = indicators.check_daily_rsi(direction, daily_ind)
        results["RSI daily"] = daily_rsi_ok
    except Exception as exc:
        results["Daily-trend"] = None
        results["RSI daily"] = None
        print(f"    (daily data mislukt: {exc})")
```

Vervang door:

```python
    try:
        daily_df = _historical_df(coin, "1d", created_at, candles_needed=60)
        daily_ind = indicators.compute_indicators(daily_df)
        _, daily_ok, _ = indicators.check_daily_trend(direction, daily_ind)
        results["Daily-trend"] = daily_ok
        _, daily_rsi_ok, _ = indicators.check_daily_rsi(direction, daily_ind)
        results["RSI daily"] = daily_rsi_ok
        daily_swing_low, daily_swing_high = indicators.swing_levels(daily_df)
        _, daily_pd_ok, _ = indicators.check_daily_premium_discount(direction, ind.price, daily_swing_low, daily_swing_high)
        results["Premium/discount (dag)"] = daily_pd_ok
        _, daily_sweep_ok, _ = indicators.check_daily_liquidity_sweep(direction, daily_df)
        results["Liquidity sweep (dag)"] = daily_sweep_ok
    except Exception as exc:
        results["Daily-trend"] = None
        results["RSI daily"] = None
        results["Premium/discount (dag)"] = None
        results["Liquidity sweep (dag)"] = None
        print(f"    (daily data mislukt: {exc})")
```

`ind.price` (de 4u-slotkoers, al berekend in het 4u-blok hierboven) is
bewust de entry-prijs voor de daily premium/discount-check, niet
`daily_ind.price` — de entry van een day trading signaal is altijd de 4u-
prijs, alleen de swing-range komt van de dagcandle, zelfde aanpak als in
Task 2's wiring in `signal_processor.py`.

- [ ] **Step 3: Werk de modulenaam-docstring bovenaan bij**

Zoek (regel 1-4):

```python
"""Backtest: hoeveel van je eigen historische day trading signalen zouden
elke nieuwe factor (ADX+richting, volatiliteit, BTC-trend, 1u bevestiging,
RSI 1u, divergentie, candlepatroon, volume-percentiel, liquiditeit) gehaald
hebben, als die toen al hadden meegeteld.
```

Vervang door:

```python
"""Backtest: hoeveel van je eigen historische day trading signalen zouden
elke nieuwe factor (ADX+richting, volatiliteit, BTC-trend, 1u bevestiging,
RSI 1u, divergentie, candlepatroon, volume-percentiel, liquiditeit,
steun/weerstand, premium/discount, liquidity sweep — elk ook op daily waar
van toepassing) gehaald hebben, als die toen al hadden meegeteld.
```

- [ ] **Step 4: Controleer dat het script nog importeert zonder fouten**

```bash
source /home/user/Trade/.venv/bin/activate && python3 -c "import scripts.backtest_factors"
```

Verwacht: geen output, geen traceback.

- [ ] **Step 5: Draai het script tegen live data (handmatige verificatie)**

```bash
source /home/user/Trade/.venv/bin/activate && python3 scripts/backtest_factors.py --limit 10
```

Verwacht: geen traceback; de output toont "Premium/discount",
"Premium/discount (dag)", "Liquidity sweep" en "Liquidity sweep (dag)" als
losse regels in de pass-rate-samenvatting, naast de bestaande factoren.
Dit is de kans om te zien hoe streng de nieuwe factoren in de praktijk
uitpakken op echte historische signalen, vóórdat je verder gaat.

- [ ] **Step 6: Commit**

```bash
git add scripts/backtest_factors.py
git commit -m "$(cat <<'EOF'
Backtest: premium/discount en liquidity sweep meenemen

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

### Task 6: Volledige regressie en push

**Files:** geen nieuwe wijzigingen — verificatie van Task 1 t/m 5 samen.

- [ ] **Step 1: Draai alle nieuwe testscripts uit dit plan opnieuw achter elkaar**

```bash
source /home/user/Trade/.venv/bin/activate
python3 <SCRATCHPAD>/test_smc_factors.py
python3 <SCRATCHPAD>/test_smc_factors_pipeline.py
python3 <SCRATCHPAD>/test_uitleg_smc_factors.py
```

Verwacht: alle drie eindigen zonder traceback vóór hun laatste
succesregel (de Telegram-stap in de pipeline-test mag een `NetworkError`
geven, zie CLAUDE.md).

- [ ] **Step 2: Draai de bestaande regressietests van eerdere deelprojecten die de factorenset raken**

Als de eerdere scratch-testscripts van deze sessie nog op schijf staan
(`test_sr_zones.py`, `test_sr_zones_pipeline.py`, testscripts van de
candlestick-patronen- en marktscan-deelprojecten), draai ze opnieuw om te
bevestigen dat de nieuwe factoren geen bestaande factor-namen of
detectielogica overschrijven. Als ze niet meer op schijf staan (scratch,
kunnen verwijderd zijn tussen sessies), is dit een import-check in plaats
daarvan:

```bash
source /home/user/Trade/.venv/bin/activate && python3 -c "
from app import indicators, signal_processor
factor_functions = [
    'check_sr_zone', 'check_premium_discount', 'check_daily_premium_discount',
    'check_liquidity_sweep', 'check_daily_liquidity_sweep', 'check_liquidity',
    'check_daily_trend', 'check_daily_rsi', 'check_1h_trend', 'check_1h_rsi',
    'check_btc_trend', 'check_divergence', 'check_candle_pattern_extended',
]
for name in factor_functions:
    assert hasattr(indicators, name), f'{name} ontbreekt'
print('OK: alle bestaande en nieuwe factor-functies bestaan naast elkaar')
"
```

- [ ] **Step 3: Importcontrole van alle gewijzigde modules**

```bash
source /home/user/Trade/.venv/bin/activate && python3 -c "
import app.indicators
import app.signal_processor
import scripts.backtest_factors
import web.main
print('OK: alle gewijzigde modules importeren zonder fouten')
"
```

- [ ] **Step 4: Controleer de git-status en push**

```bash
cd /home/user/Trade && git status --short && git log --oneline -6
git push -u origin claude/crypto-day-trading-alerts-5p8w6v
```

Verwacht: `git status --short` toont geen wijzigingen (alles al gecommit
in Task 1 t/m 5), de push slaagt.

## Self-Review (uitgevoerd bij het schrijven van dit plan)

- **Spec coverage:** Sectie 1 (premium/discount) → Task 1. Sectie 2
  (liquidity sweeps) → Task 1. Sectie 3 (wiring) → Task 2. Sectie 4
  (factorentelling) → Task 3. Sectie 5 (UI) → Task 4. Sectie 6 (backtest)
  → Task 5. Testen-sectie → Task 1/2/4 (scripttests) + Task 6 (volledige
  regressie). Niet-doelen (geen migratie, geen chart, geen extra
  Binance-call, geen wijziging aan CONFIRM_THRESHOLD) zijn overal expliciet
  benoemd in de betreffende taak, geen taak schendt ze.
- **Placeholder-scan:** geen TBD/TODO, elke stap heeft volledige code of
  een letterlijk te draaien commando.
- **Type-consistentie:** `check_premium_discount`/`check_daily_premium_discount`
  en `check_liquidity_sweep`/`check_daily_liquidity_sweep` gebruiken overal
  dezelfde signatuur als in Task 1's Interfaces-blok gedeclareerd; Task 2,
  4 en 5 roepen ze allemaal met die exacte parameters aan.
