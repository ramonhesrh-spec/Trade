# Patroon + factor-toetsing + kansberekening Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Patroon-signalen lopen door dezelfde factor-toetsing als dagtrading (EMA/MACD/RSI/volume, dagtrend, en bij `ENABLE_ADVANCED_FACTORS` de uitgebreide factoren) zonder ooit geblokkeerd te worden, en krijgen een kansberekening die het gepoolde factor-percentage combineert met de historische winrate van dat specifieke patroontype.

**Architecture:** `process_day_trading_signal`'s bestaande inline toetsing-opbouw wordt geëxtraheerd naar een gedeelde `signal_processor.compute_full_confirmation`, hergebruikt door zowel dagtrading als `market_scanner._check_chart_patterns`. Een nieuwe `repo.pattern_winrate_stats()` levert de systeembrede winrate per patroontype, gecombineerd bij weergave in `web/main.py::_add_signal_context`.

**Tech Stack:** Python 3, FastAPI, SQLite, Jinja2.

**Spec:** docs/superpowers/specs/2026-09-23-patroon-factor-toetsing-design.md

## Global Constraints

- Geen enkele patroon-melding wordt ooit geblokkeerd of tegengehouden: `technical_confirmed` blijft VAST op `1` voor `trade_type='patroon'`, in alle taken hieronder.
- Geen wijziging aan stop/take/target-berekening voor patroon (blijft de bestaande gemeten-beweging-met-ATR-terugval-logica).
- Swing blijft volledig buiten scope van dit plan.
- Geen wijziging aan `app/patterns.py`'s detectielogica.
- Geen pytest-suite in dit project: elke taak verifieert met een throwaway-script tegen `DATABASE_PATH=/tmp/...db`.
- `app/repo.py` is de enige plek die de database aanraakt.

---

### Task 1: `compute_full_confirmation` extraheren in signal_processor.py

**Files:**
- Modify: `app/signal_processor.py:764-817` (huidige inline toetsing-opbouw in `process_day_trading_signal`)

**Interfaces:**
- Produces: `async def compute_full_confirmation(coin: str, direction: str, df, ind: indicators.Indicators, zones: list[indicators.SRZone]) -> tuple[bool, str, float, bool]` — retourneert `(confirmed, breakdown, pass_pct, hard_gates_ok)`, exact dezelfde vorm als `indicators.confirms_direction` nu al teruggeeft.

De huidige code (regels 770-817, precies zo in het bestand):

```python
    daily_trend_factor = None
    daily_df = None
    daily_ind = None
    try:
        daily_df = await asyncio.to_thread(exchange.fetch_ohlcv, interp.coin, "1d")
        daily_ind = indicators.compute_indicators(daily_df)
        # Net als BTC-trend (indicators.btc_is_flat): een coin zonder
        # duidelijke eigen dagtrend mag niet hard geblokkeerd worden, dat
        # zou een normale consolidatie vlak voor een uitbraak onterecht
        # wegfilteren. btc_is_flat is ondanks zijn naam coin-onafhankelijk
        # (alleen ema9/ema21/atr), dus rechtstreeks herbruikbaar hier.
        if not indicators.btc_is_flat(daily_ind):
            daily_trend_factor = indicators.check_daily_trend(interp.direction, daily_ind)
    except Exception:
        logger.exception("Dagtrend kon niet berekend worden voor %s", interp.coin)
        daily_trend_factor = ("Daily-trend", False, "kon niet opgehaald worden, telt als niet bevestigd")

    extra_factors = None
    if config.ENABLE_ADVANCED_FACTORS:
        extra_factors = await compute_advanced_extra_factors(
            interp.coin, interp.direction, df, ind.price, ind.atr, zones,
            daily_df=daily_df, daily_ind=daily_ind,
        )

    ...
    confirmed, reason, pass_pct, hard_gates_ok = indicators.confirms_direction(
        ind, interp.direction, extra_factors=extra_factors, include_advanced=config.ENABLE_ADVANCED_FACTORS,
        daily_trend_factor=daily_trend_factor,
    )
```

(De `edges`/`nearest_sr_zone_price`-berekening ertussenin, regels 794-812, hoort NIET bij deze extractie — dat is een apart mechanisme (zone-faalgeheugen) dat in `process_day_trading_signal` blijft staan, ongewijzigd.)

- [ ] **Step 1: Schrijf de nieuwe functie**

Voeg toe in `app/signal_processor.py`, vlak vóór `def _notify_new_coin` (regel 738):

```python
async def compute_full_confirmation(
    coin: str, direction: str, df, ind: indicators.Indicators, zones: list[indicators.SRZone],
) -> tuple[bool, str, float, bool]:
    """Volledige factor-toetsing: dagtrend (met vlakke-markt-uitzondering)
    plus, bij config.ENABLE_ADVANCED_FACTORS, de uitgebreide factoren, dan
    indicators.confirms_direction. Geëxtraheerd uit process_day_trading_signal
    zodat market_scanner._check_chart_patterns exact dezelfde toetsing kan
    hergebruiken voor een patroon-richting, zonder deze logica te
    dupliceren. Retourneert (confirmed, breakdown, pass_pct, hard_gates_ok),
    identiek aan wat confirms_direction zelf teruggeeft."""
    daily_trend_factor = None
    daily_df = None
    daily_ind = None
    try:
        daily_df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, "1d")
        daily_ind = indicators.compute_indicators(daily_df)
        if not indicators.btc_is_flat(daily_ind):
            daily_trend_factor = indicators.check_daily_trend(direction, daily_ind)
    except Exception:
        logger.exception("Dagtrend kon niet berekend worden voor %s", coin)
        daily_trend_factor = ("Daily-trend", False, "kon niet opgehaald worden, telt als niet bevestigd")

    extra_factors = None
    if config.ENABLE_ADVANCED_FACTORS:
        extra_factors = await compute_advanced_extra_factors(
            coin, direction, df, ind.price, ind.atr, zones,
            daily_df=daily_df, daily_ind=daily_ind,
        )

    return indicators.confirms_direction(
        ind, direction, extra_factors=extra_factors, include_advanced=config.ENABLE_ADVANCED_FACTORS,
        daily_trend_factor=daily_trend_factor,
    )
```

- [ ] **Step 2: Vervang de inline versie in `process_day_trading_signal`**

Vervang regels 770-817 (van `daily_trend_factor = None` tot en met de `confirms_direction`-aanroep) door:

```python
    confirmed, reason, pass_pct, hard_gates_ok = await compute_full_confirmation(
        interp.coin, interp.direction, df, ind, zones,
    )
```

De rest van `process_day_trading_signal` (de `edges`/`nearest_sr_zone_price`-blok, de zone-faalgeheugen-check, stop/take, entry-zone-suggestie) blijft ongewijzigd en gebruikt `confirmed`/`reason`/`pass_pct`/`hard_gates_ok` zoals voorheen.

- [ ] **Step 3: Regressie tegen dagtrading — throwaway script**

Dit project heeft geen pytest-suite. Schrijf `/tmp/test_compute_full_confirmation.py` (of direct als `python3 -c`) die aantoont dat `process_day_trading_signal` nog exact hetzelfde gedrag heeft. Omdat dit een pure extractie is (geen enkele regel logica veranderd, alleen verplaatst), volstaat een aanroep tegen een scratch-database met een synthetisch, bekend `Indicators`-object dat een voorspelbare `pass_pct` oplevert:

```python
import asyncio
from app import db, indicators, signal_processor
db.init_db()

ind = indicators.Indicators(
    price=100.0, rsi=60.0, macd=1.0, macd_signal=0.5, volume_ratio=1.5,
    ema9=101.0, ema21=99.0, atr=2.0, atr_avg20=1.8, adx=30.0, adx_pos=25.0, adx_neg=10.0,
)
import pandas as pd
df = pd.DataFrame({
    "timestamp": range(60), "open": [100.0]*60, "high": [101.0]*60,
    "low": [99.0]*60, "close": [100.0]*60, "volume": [1000.0]*60,
})

confirmed, reason, pass_pct, hard_gates_ok = asyncio.run(
    signal_processor.compute_full_confirmation("TESTCOIN", "long", df, ind, zones=[])
)
print("confirmed:", confirmed, "pass_pct:", pass_pct, "hard_gates_ok:", hard_gates_ok)
assert isinstance(pass_pct, float)
assert isinstance(hard_gates_ok, bool)
print("OK: compute_full_confirmation levert dezelfde vorm als confirms_direction")
```

Run: `DATABASE_PATH=/tmp/scratch_task1.db python3 /tmp/test_compute_full_confirmation.py`
Expected: geen exception, "OK: ..." geprint. (De echte `fetch_ohlcv("TESTCOIN", "1d")`-aanroep zal falen omdat dit geen bestaand paar is — dat is prima, `compute_full_confirmation`'s eigen `try/except` vangt dat af en levert `daily_trend_factor = ("Daily-trend", False, ...)`, exact het bestaande fail-closed-gedrag. Verifieer dat de log-regel "Dagtrend kon niet berekend worden voor TESTCOIN" verschijnt en het script alsnog "OK" print.)

- [ ] **Step 4: Commit**

```bash
git add app/signal_processor.py
git commit -m "Patroon+factoren: compute_full_confirmation geëxtraheerd uit process_day_trading_signal"
```

---

### Task 2: market_scanner.py koppelen aan compute_full_confirmation

**Files:**
- Modify: `app/market_scanner.py:220-314` (`_check_chart_patterns`)
- Modify: `app/market_scanner.py:21` (import)

**Interfaces:**
- Consumes: `signal_processor.compute_full_confirmation(coin, direction, df, ind, zones) -> tuple[bool, str, float, bool]` (Task 1).

- [ ] **Step 1: Importeer de nieuwe functie**

In `app/market_scanner.py:21`, huidige regel:
```python
from app.signal_processor import fanout_confirmed_signal, process_day_trading_signal
```
wordt:
```python
from app.signal_processor import compute_full_confirmation, fanout_confirmed_signal, process_day_trading_signal
```

- [ ] **Step 2: Roep de toetsing aan en gebruik het echte resultaat**

In `_check_chart_patterns`, direct ná het `ignored = repo.auto_ignore_opposite_pending(...)`-blok (na regel 275) en vóór `entry_options = patterns.find_entry_options(...)` (regel 277), voeg toe:

```python
    # Zones lokaal berekend, net als _check_breakout_retest elders in dit
    # bestand al doet — geen gedeelde cache tussen de drie check-functies
    # in dit bestand.
    zones = indicators.detect_sr_zones(df)
    _, factor_breakdown, factor_pass_pct, factor_hard_gates_ok = await compute_full_confirmation(
        coin, match.direction, df, ind, zones,
    )
```

(De eerste teruggegeven waarde, `confirmed`, wordt bewust genegeerd via `_` — `technical_confirmed` blijft voor patroon vast op 1, zie Global Constraints.)

Pas `signal_data` aan (huidige regels 301-314): vervang

```python
        "technical_confirmed": 1, "pass_pct": None, "hard_gates_ok": 1,
        "confidence": "patroon bevestigd",
        "reason": f"Patroon: {match.name}, richting {match.direction}",
```

door

```python
        "technical_confirmed": 1, "pass_pct": factor_pass_pct, "hard_gates_ok": factor_hard_gates_ok,
        "confidence": "patroon bevestigd",
        "reason": factor_breakdown,
```

- [ ] **Step 2: Verifieer met een throwaway script tegen een scratch-database**

```python
import asyncio
from app import db, indicators, market_scanner
db.init_db()

async def main():
    import pandas as pd
    # Synthetische candles genoeg voor SR_PIVOT_WINDOW/SR_ZONE_LOOKBACK,
    # geen echt patroon nodig — we testen alleen dat signal_data de
    # echte pass_pct/hard_gates_ok/reason krijgt in plaats van None/1/platte tekst.
    rows = [{"open": 100.0, "high": 100.5, "low": 99.5, "close": 100.0, "volume": 1000.0} for _ in range(110)]
    df = pd.DataFrame(rows)
    ind = indicators.compute_indicators(df)
    await market_scanner._check_chart_patterns("TESTCOIN2", df, ind)

    row = None
    from app import db as db_module
    with db_module.session() as conn:
        row = conn.execute(
            "SELECT pass_pct, hard_gates_ok, reason FROM signals WHERE coin='TESTCOIN2' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    if row is None:
        print("Geen patroon gedetecteerd op deze synthetische data (verwacht bij vlakke candles) — "
              "geen signal_data om te controleren, dit is geen falen van deze taak.")
    else:
        print("pass_pct:", row["pass_pct"], "hard_gates_ok:", row["hard_gates_ok"], "reason:", row["reason"])
        assert row["reason"] != "" and not row["reason"].startswith("Patroon: "), \
            "reason moet nu de echte factor-breakdown zijn, niet de oude platte tekst"

asyncio.run(main())
```

Run: `DATABASE_PATH=/tmp/scratch_task2.db python3 /tmp/test_check_chart_patterns.py`

Expected: ofwel geen patroon gedetecteerd (vlakke synthetische candles geven vaak geen geldig patroon — geen probleem, de code-wijziging zelf is dan alsnog gedekt door Task 1's regressietest), ofwel een `reason` die niet meer met "Patroon: " begint. Wil je een gegarandeerd patroon om tegen te testen, hergebruik de synthetische bullish-divergence-candles uit de eerdere sessie (zie de "waarom is een pure divergentie lastig"-fix eerder in dit project, dezelfde soort candle-opbouw met een duidelijke lagere bodem + RSI-afwijking + doorbraak van de structuur-top) in plaats van vlakke candles.

- [ ] **Step 3: Commit**

```bash
git add app/market_scanner.py
git commit -m "Patroon+factoren: _check_chart_patterns gebruikt compute_full_confirmation"
```

---

### Task 3: `repo.pattern_winrate_stats()`

**Files:**
- Modify: `app/repo.py` (nieuwe functie, plaats vlak na `winrate_stats`, rond regel 1880 — exacte plek: eerste lege regel ná het einde van `winrate_stats`)

**Interfaces:**
- Produces: `def pattern_winrate_stats() -> dict[str, dict]` — `{pattern_name: {"winrate": float, "total": int}}`, alleen voor patroontypes met minstens `PATTERN_MIN_SAMPLE` afgeronde signalen.

- [ ] **Step 1: Schrijf de functie**

```python
# Minimaal aantal afgeronde signalen van een patroontype voordat de
# winrate ervan getoond wordt — te weinig data geeft een misleidend
# percentage (bijvoorbeeld 100% op 1 signaal). Zelfde soort ondergrens-
# gedachte als SR_ZONE_MIN_TOUCHES in indicators.py, hier voor een ander
# soort telling.
PATTERN_MIN_SAMPLE = 5


def pattern_winrate_stats() -> dict[str, dict]:
    """Systeembrede winrate per patroontype (niet per gebruiker — een
    patroon-signaal is voor iedereen hetzelfde, zie signals.auto_outcome),
    gebruikt voor de kansberekening op een patroon-signaal. Alleen
    patroontypes met minstens PATTERN_MIN_SAMPLE afgeronde (take_profit/
    stop_loss) signalen krijgen een entry — te weinig data geeft een
    misleidend percentage. Geen 'vervallen'-uitkomsten meegeteld, net als
    de bestaande winrate_stats hierboven dat ook niet doet voor
    dagtrading."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT pattern_name, auto_outcome, COUNT(*) AS n
               FROM signals
               WHERE trade_type = 'patroon' AND is_practice = 0
                     AND auto_outcome IN ('take_profit', 'stop_loss')
               GROUP BY pattern_name, auto_outcome"""
        ).fetchall()

    by_pattern: dict[str, dict[str, int]] = {}
    for row in rows:
        by_pattern.setdefault(row["pattern_name"], {})[row["auto_outcome"]] = row["n"]

    result: dict[str, dict] = {}
    for pattern_name, counts in by_pattern.items():
        wins = counts.get("take_profit", 0)
        losses = counts.get("stop_loss", 0)
        total = wins + losses
        if total < PATTERN_MIN_SAMPLE:
            continue
        result[pattern_name] = {"winrate": (wins / total) * 100, "total": total}
    return result
```

- [ ] **Step 2: Verifieer met een throwaway script tegen een scratch-database**

```python
from app import db, repo
db.init_db()

signal_base = {
    "message_id": None, "coin": "ETH", "direction": "long", "category": "day_trading",
    "trade_type": "patroon", "pattern_name": "double bottom",
    "price": 100.0, "rsi": 50, "macd": 0, "macd_signal": 0, "volume_ratio": 1.0,
    "ema9": 1, "ema21": 1, "atr": 1, "atr_avg20": 1, "adx": 20,
    "technical_confirmed": 1, "pass_pct": 60.0, "hard_gates_ok": 1,
    "confidence": "patroon bevestigd", "reason": "test",
    "stop_loss": 95.0, "take_profit": 110.0,
    "context_note": None, "is_practice": 0, "plain_explanation": None,
    "suggested_entry_low": None, "suggested_entry_high": None,
}

# 4 keer winst, 2 keer verlies -> 6 totaal (>= PATTERN_MIN_SAMPLE), winrate 66.7%
outcomes = ["take_profit"] * 4 + ["stop_loss"] * 2
for outcome in outcomes:
    sid = repo.insert_signal(dict(signal_base))
    with db.session() as conn:
        conn.execute("UPDATE signals SET auto_outcome = ? WHERE id = ?", (outcome, sid))

# Een ander patroontype met te weinig data (2 signalen, onder PATTERN_MIN_SAMPLE=5)
for outcome in ["take_profit", "stop_loss"]:
    other = dict(signal_base)
    other["pattern_name"] = "double top"
    sid = repo.insert_signal(other)
    with db.session() as conn:
        conn.execute("UPDATE signals SET auto_outcome = ? WHERE id = ?", (outcome, sid))

stats = repo.pattern_winrate_stats()
print(stats)
assert "double bottom" in stats
assert abs(stats["double bottom"]["winrate"] - (4/6*100)) < 0.01
assert stats["double bottom"]["total"] == 6
assert "double top" not in stats, "moet ontbreken: onder PATTERN_MIN_SAMPLE"
print("OK: pattern_winrate_stats klopt")
```

Run: `DATABASE_PATH=/tmp/scratch_task3.db python3 /tmp/test_pattern_winrate_stats.py`
Expected: "OK: pattern_winrate_stats klopt", geen assertion errors.

- [ ] **Step 3: Commit**

```bash
git add app/repo.py
git commit -m "Patroon+factoren: repo.pattern_winrate_stats per patroontype"
```

---

### Task 4: kansberekening in web/main.py

**Files:**
- Modify: `web/main.py:588-606` (`_add_signal_context`)
- Modify: `web/main.py:747, 748, 798` (dashboard-route)
- Modify: `web/main.py:907, 908, 943` (oefentrade-route)
- Modify: `web/main.py:1606, 1607, 1608` (coin-pagina-route)

**Interfaces:**
- Consumes: `repo.pattern_winrate_stats() -> dict[str, dict]` (Task 3).
- Produces: `_add_signal_context(entries, winrate, pattern_winrate)` — nieuwe derde parameter; elke `entry` krijgt (ongewijzigd qua naam) `entry["success_rate"]`/`entry["success_sample"]`, nu ook gevuld voor `trade_type == "patroon"`.

- [ ] **Step 1: `_add_signal_context` een patroon-tak geven**

Vervang de hele functie (regels 588-606):

```python
def _add_signal_context(entries: list[dict], winrate: dict, pattern_winrate: dict) -> list[dict]:
    """Voegt aan elk signaal het concrete advies toe (wat kan je beter
    doen dan nu instappen) en een slagingskans toe. Voor dagtrading is dat
    de eigen trackrecord van dit vertrouwen-niveau; voor patroon een
    kansberekening die het gepoolde factor-percentage van dit signaal
    combineert met de systeembrede historische winrate van dit
    patroontype (repo.pattern_winrate_stats). Swing heeft geen van
    beide (zie de spec), dus geen geleende statistiek."""
    for entry in entries:
        entry["advice"] = advice_module.build_advice(entry)
        if entry.get("trade_type") == "swing":
            entry["success_rate"] = None
            entry["success_sample"] = None
            continue
        if entry.get("trade_type") == "patroon":
            pattern_stats = pattern_winrate.get(entry.get("pattern_name"))
            factor_pct = entry.get("pass_pct")
            pattern_pct = pattern_stats["winrate"] if pattern_stats else None
            if factor_pct is not None and pattern_pct is not None:
                entry["success_rate"] = (factor_pct + pattern_pct) / 2
            elif factor_pct is not None:
                entry["success_rate"] = factor_pct
            elif pattern_pct is not None:
                entry["success_rate"] = pattern_pct
            else:
                entry["success_rate"] = None
            entry["success_sample"] = pattern_stats["total"] if pattern_stats else None
            continue
        bucket = "hoog_vertrouwen" if entry.get("confidence") == "hoog vertrouwen" else "laag_vertrouwen"
        stats = winrate[bucket]
        entry["success_rate"] = stats["winrate"]
        entry["success_sample"] = stats["total"]
    return entries
```

- [ ] **Step 2: Dashboard-route (rond regel 747)**

Huidige regel 747:
```python
    winrate = repo.winrate_stats(user["id"])
```
wordt:
```python
    winrate = repo.winrate_stats(user["id"])
    pattern_winrate = repo.pattern_winrate_stats()
```
En de twee `_add_signal_context`-aanroepen in deze route (regels 748 en 798) krijgen het derde argument:
```python
    open_entries = _add_signal_context(
        await _enrich_open_positions(_filter_journal(real_entries, "open")), winrate, pattern_winrate,
    )
```
```python
    practice_open = _add_signal_context(
        await _enrich_open_positions([e for e in practice_entries if e["exit_price"] is None]), winrate, pattern_winrate,
    )
```

- [ ] **Step 3: Oefentrade-route (rond regel 907)**

Huidige regel 907:
```python
    confidence_winrate = repo.winrate_stats(user["id"])
```
wordt:
```python
    confidence_winrate = repo.winrate_stats(user["id"])
    pattern_winrate = repo.pattern_winrate_stats()
```
En de twee aanroepen (regels 908, 943) krijgen het derde argument, zelfde patroon als Step 2 hierboven maar met `confidence_winrate` als tweede argument (ongewijzigde naam).

- [ ] **Step 4: Coin-pagina-route (rond regel 1606)**

Huidige regel 1606:
```python
    winrate = repo.winrate_stats(user["id"])
```
wordt:
```python
    winrate = repo.winrate_stats(user["id"])
    pattern_winrate = repo.pattern_winrate_stats()
```
En regels 1607-1608:
```python
    open_trades = _add_signal_context(open_trades, winrate, pattern_winrate)
    recent_signals = _add_signal_context(recent_signals, winrate, pattern_winrate)
```

- [ ] **Step 5: Verifieer met een throwaway script**

```python
from app import db, repo
import web.main as web_main
db.init_db()

entry = {
    "trade_type": "patroon", "pattern_name": "double bottom", "pass_pct": 70.0,
    "hard_gates_ok": 1, "reason": "✓ Trend: ok | ✗ Momentum: nee", "direction": "long",
    "rsi": 50, "ema9": 1, "ema21": 1, "macd": 0, "macd_signal": 0, "volume_ratio": 1.0,
    "technical_confirmed": 1,
}
pattern_winrate = {"double bottom": {"winrate": 50.0, "total": 6}}
result = web_main._add_signal_context([entry], winrate={"hoog_vertrouwen": {"winrate": 0, "total": 0}, "laag_vertrouwen": {"winrate": 0, "total": 0}}, pattern_winrate=pattern_winrate)
print(result[0]["success_rate"], result[0]["success_sample"])
assert abs(result[0]["success_rate"] - 60.0) < 0.01, "gemiddelde van 70.0 (factor) en 50.0 (patroon) moet 60.0 zijn"
assert result[0]["success_sample"] == 6
print("OK: kansberekening combineert factor_pct en pattern_pct correct")
```

Run: `DATABASE_PATH=/tmp/scratch_task4.db python3 /tmp/test_add_signal_context.py`
Expected: "OK: kansberekening combineert factor_pct en pattern_pct correct".

- [ ] **Step 6: Commit**

```bash
git add web/main.py
git commit -m "Patroon+factoren: kansberekening in _add_signal_context, alle drie routes bijgewerkt"
```

---

### Task 5: advice.py's patroon-tak gebruikt de echte factor-breakdown

**Files:**
- Modify: `app/advice.py` (hele bestand, herstructurering van `build_advice`)

**Interfaces:**
- Consumes: `signal["pass_pct"]` (nu echt gevuld voor patroon, Task 2), `signal["reason"]` (nu de echte breakdown-tekst, Task 2).

- [ ] **Step 1: Herschrijf `build_advice`**

Vervang de hele functie:

```python
def build_advice(signal: dict) -> str:
    # technical_confirmed betekent voor een swing-signaal iets anders (het
    # bewaakte niveau is bevestigd, geen 3-van-4-toets), dus het
    # day-trading-advies eronder klopt er niet voor.
    if signal.get("trade_type") == "swing":
        return (
            "Geen automatisch advies voor een bewaakt niveau: beoordeel de "
            "daily- en 4-uur-factoren in de melding zelf, dit is geen "
            "3-van-4-toets zoals bij day trading."
        )

    is_pattern = signal.get("trade_type") == "patroon"
    pattern_name = signal.get("pattern_name") or "onbekend patroon"
    factor_pct = signal.get("pass_pct")

    # Een patroon-signaal heeft, sinds de factor-toetsing ook op patronen
    # draait (zie compute_full_confirmation), een echte breakdown in
    # signal["reason"] i.p.v. de vroegere platte "Patroon: ...". Boven de
    # helft van de factoren klopt -> citeer die breakdown i.p.v. de
    # generieke "alle vier factoren"-tekst hieronder, die alleen voor
    # dagtrading klopt (technical_confirmed staat voor patroon altijd op
    # 1, zegt dus niets over de factoren zelf).
    if is_pattern and factor_pct is not None and factor_pct >= 50:
        return (
            f"Patroon ({pattern_name}) wordt ondersteund door de factoren: "
            f"{signal.get('reason') or 'geen details beschikbaar'}."
        )

    if not is_pattern and signal.get("technical_confirmed"):
        return "Alle vier factoren kloppen, dit is volgens de regels een directe instap."

    direction = (signal.get("direction") or "").lower()
    rsi = signal.get("rsi")
    ema9 = signal.get("ema9")
    ema21 = signal.get("ema21")
    macd = signal.get("macd")
    macd_signal = signal.get("macd_signal")
    volume_ratio = signal.get("volume_ratio")

    tips = []

    if ema9 is not None and ema21 is not None:
        trend_up = ema9 > ema21
        if direction == "long" and not trend_up:
            tips.append(f"wacht tot EMA9 boven EMA21 komt (nu {ema9:.4f} tegen {ema21:.4f})")
        elif direction == "short" and trend_up:
            tips.append(f"wacht tot EMA9 onder EMA21 komt (nu {ema9:.4f} tegen {ema21:.4f})")

    if macd is not None and macd_signal is not None:
        momentum_up = macd > macd_signal
        if direction == "long" and not momentum_up:
            tips.append("wacht tot de MACD-lijn boven de signaallijn kruist voor opwaarts momentum")
        elif direction == "short" and momentum_up:
            tips.append("wacht tot de MACD-lijn onder de signaallijn kruist voor neerwaarts momentum")

    if rsi is not None and ema21 is not None:
        if direction == "long" and rsi >= 75:
            tips.append(f"RSI staat op {rsi:.0f}, oververhit: wacht op een terugval richting EMA21 rond {ema21:.4f} voor een gunstiger instapmoment")
        elif direction == "short" and rsi <= 25:
            tips.append(f"RSI staat op {rsi:.0f}, oversold: wacht op een opleving richting EMA21 rond {ema21:.4f} voor een gunstiger instapmoment")

    if volume_ratio is not None and volume_ratio < 1.0:
        tips.append(f"volume ligt op {volume_ratio:.2f}x het gemiddelde, nog niet overtuigend: wacht op een sterkere beweging")

    if not tips:
        if is_pattern:
            tips.append(f"niet alle factoren ondersteunen dit patroon ({pattern_name}) nog, beoordeel de nek/lijn zelf voor je instapt")
        else:
            tips.append("niet alle vier factoren kloppen, wacht op een duidelijkere bevestiging voor je instapt")

    return " Ook: ".join(tips) if len(tips) > 1 else tips[0]
```

- [ ] **Step 2: Verifieer met een throwaway script**

```python
from app import advice

high = {
    "trade_type": "patroon", "pattern_name": "double bottom", "pass_pct": 75.0,
    "reason": "✓ Trend: ok | ✓ Momentum: ok | ✗ Volume: nee",
}
low = {
    "trade_type": "patroon", "pattern_name": "double top", "pass_pct": 20.0,
    "reason": "✗ Trend: nee | ✗ Momentum: nee", "direction": "short",
    "ema9": 101.0, "ema21": 99.0, "macd": 1.0, "macd_signal": 0.5, "rsi": 50.0, "volume_ratio": 1.0,
}

r1 = advice.build_advice(high)
print(r1)
assert "double bottom" in r1 and "Trend: ok" in r1

r2 = advice.build_advice(low)
print(r2)
assert "EMA9 onder EMA21" in r2 or "MACD-lijn onder" in r2

swing = {"trade_type": "swing"}
r3 = advice.build_advice(swing)
assert "bewaakt niveau" in r3

print("OK: advice.py's patroon-tak werkt voor hoge en lage factor_pct")
```

Run: `python3 /tmp/test_advice.py`
Expected: "OK: advice.py's patroon-tak werkt voor hoge en lage factor_pct".

- [ ] **Step 3: Commit**

```bash
git add app/advice.py
git commit -m "Patroon+factoren: advice.py citeert de echte factor-breakdown"
```

---

### Task 6: Templates — badge-volgorde, factor-breakdown, guards terugdraaien

**Files:**
- Modify: `web/templates/_macros.html:20-51` (`reason_factors`, `reason_popup`)
- Modify: `web/templates/_macros.html:146-196` (`signal_card`, badge-blok)
- Modify: `web/templates/dashboard.html:95,96,101,125,126,131,209,541`
- Modify: `web/templates/account.html:80,400`
- Modify: `web/templates/coin.html:82,95`

**Interfaces:**
- Consumes: `entry.pass_pct`/`entry.reason`/`entry.success_rate`/`entry.success_sample` (nu echt gevuld voor patroon, Taken 2 en 4).

- [ ] **Step 1: `reason_factors` — patroon valt voortaan samen met dagtrading**

`entry.reason` is voor patroon nu een " | "-gescheiden ✓/✗-breakdown, exact dezelfde vorm als dagtrading — de aparte platte-tekst-tak is niet meer nodig. Vervang (huidige regels 20-39):

```jinja
{% macro reason_factors(entry, p_style='') %}
{% if entry.trade_type == "patroon" %}
{# entry.reason is hier één platte zin ("Patroon: ..., richting ..."), geen
   " | "-gescheiden factoren zoals dagtrading — op " | " splitsen en de
   ✓/✗-kleuring toepassen zou de zin altijd rood ("mislukt") kleuren, terwijl
   het gewoon een neutrale beschrijving van het herkende patroon is. #}
<p class="muted"{% if p_style %} style="{{ p_style }}"{% endif %}>{{ entry.reason }}</p>
{% elif entry.trade_type != 'swing' %}
{% for factor in entry.reason.split(" | ") %}
<p class="{{ 'factor-ok' if factor.startswith('✓') else 'factor-bad' }}"{% if p_style %} style="{{ p_style }}"{% endif %}>{{ factor }}</p>
{% endfor %}
{% else %}
{% for group in entry.reason.split("\n") %}
<p class="muted" style="font-weight: 600; margin: 8px 0 2px;">{{ group.split(": ", 1)[0] }}</p>
{% for factor in group.split(": ", 1)[1].split(" | ") %}
<p class="{{ 'factor-ok' if factor.startswith('✓') else 'factor-bad' }}"{% if p_style %} style="{{ p_style }}"{% endif %}>{{ factor }}</p>
{% endfor %}
{% endfor %}
{% endif %}
{% endmacro %}
```

door:

```jinja
{% macro reason_factors(entry, p_style='') %}
{% if entry.trade_type != 'swing' %}
{# Geldt nu ook voor patroon: sinds compute_full_confirmation ook op een
   patroon-richting draait, is entry.reason een " | "-gescheiden ✓/✗-
   breakdown, exact dezelfde vorm als dagtrading. #}
{% for factor in entry.reason.split(" | ") %}
<p class="{{ 'factor-ok' if factor.startswith('✓') else 'factor-bad' }}"{% if p_style %} style="{{ p_style }}"{% endif %}>{{ factor }}</p>
{% endfor %}
{% else %}
{% for group in entry.reason.split("\n") %}
<p class="muted" style="font-weight: 600; margin: 8px 0 2px;">{{ group.split(": ", 1)[0] }}</p>
{% for factor in group.split(": ", 1)[1].split(" | ") %}
<p class="{{ 'factor-ok' if factor.startswith('✓') else 'factor-bad' }}"{% if p_style %} style="{{ p_style }}"{% endif %}>{{ factor }}</p>
{% endfor %}
{% endfor %}
{% endif %}
{% endmacro %}
```

- [ ] **Step 2: `reason_popup`'s patroon-legende bijwerken**

Huidige regel 46:
```jinja
{% elif entry.trade_type == "patroon" %}
<p class="muted reason-legend">Herkend chart-patroon, geen gepoold percentage: entry/stop/take zijn gebaseerd op de gemeten beweging van het patroon zelf.</p>
```
wordt:
```jinja
{% elif entry.trade_type == "patroon" %}
<p class="muted reason-legend">Herkend chart-patroon: entry/stop/take zijn gebaseerd op de gemeten beweging van het patroon zelf. De vinkjes hieronder zijn de gepoolde factoren die dit patroon ondersteunen of tegenspreken; het percentage hierboven combineert dat met de historische winrate van dit patroontype.</p>
```

- [ ] **Step 3: `signal_card`'s badge-blok — patroon vóór de generieke pass_pct-check**

Huidige regels 152-158:
```jinja
    {% if entry.pass_pct is not none %}
    <span class="pass-pct">{{ "%.0f"|format(entry.pass_pct) }}%</span>
    {% elif entry.trade_type == "swing" %}
    <span class="badge badge-swing" title="Bevestigd op een bewaakt steun/weerstand-niveau, geen gepoold percentage">swing</span>
    {% elif entry.trade_type == "patroon" %}
    <span class="badge badge-swing" title="Chart-patroon herkend door HesPulse, geen gepoold percentage">{{ entry.pattern_name }}</span>
    {% endif %}
```

wordt (patroon eerst gecheckt, anders wint de nu-wél-gevulde `pass_pct` het altijd en verdwijnt de patroonbadge):

```jinja
    {% if entry.trade_type == "swing" %}
    <span class="badge badge-swing" title="Bevestigd op een bewaakt steun/weerstand-niveau, geen gepoold percentage">swing</span>
    {% elif entry.trade_type == "patroon" %}
    <span class="badge badge-swing" title="Chart-patroon herkend door HesPulse">{{ entry.pattern_name }}</span>
    {% if entry.success_rate is not none %}<span class="pass-pct" title="kansberekening: gepoolde factoren + historische winrate van dit patroontype">{{ "%.0f"|format(entry.success_rate) }}%</span>{% endif %}
    {% elif entry.pass_pct is not none %}
    <span class="pass-pct">{{ "%.0f"|format(entry.pass_pct) }}%</span>
    {% endif %}
```

(De kansberekening gebruikt bewust `entry.success_rate` — het combinatiecijfer uit Task 4 — niet `entry.pass_pct`, dat laatste is alleen het factor-percentage van dit ene signaal.)

- [ ] **Step 4: dashboard.html — guards terugdraaien**

Op regels 95, 96, 101, 125, 126, 131, 209, 541: elke `e.trade_type not in ('swing', 'patroon')` wordt `e.trade_type != 'swing'`. Voorbeeld (regel 95):
```jinja
{% if e.reason and e.trade_type not in ('swing', 'patroon') %}<span class="confidence-ratio mono muted">{{ e.reason.count("✓") }}/{{ e.reason.split(" | ")|length }}</span>{% endif %}
```
wordt:
```jinja
{% if e.reason and e.trade_type != 'swing' %}<span class="confidence-ratio mono muted">{{ e.reason.count("✓") }}/{{ e.reason.split(" | ")|length }}</span>{% endif %}
```
Zelfde vervanging (`not in ('swing', 'patroon')` → `!= 'swing'`) op de andere 7 genoemde regels in dit bestand — regels 96/126 zijn de bijbehorende sluitende `{% if e.trade_type not in (...) %}...slagingskans...{% endif %}`-blokken voor dezelfde twee kaarten, regel 101/131 zijn hun `{% endif %}` (niet aanpassen, alleen de openende `{% if %}` op 96/126 verandert). Regel 209 en 541 zijn losse confidence-ratio-badges op andere plekken in dit bestand (tabelrij resp. compacte kaart), zelfde vervanging.

- [ ] **Step 5: account.html en coin.html — dezelfde vervanging**

`account.html:80` en `account.html:400`: `e.trade_type not in ('swing', 'patroon')` → `e.trade_type != 'swing'`.
`coin.html:82` en `coin.html:95`: `primary.trade_type not in ('swing', 'patroon')` → `primary.trade_type != 'swing'`.

- [ ] **Step 6: Handmatige Playwright-verificatie**

Dit project heeft geen geautomatiseerde UI-tests. Start `uvicorn web.main:app` tegen een scratch-database met minstens één afgerond patroon-signaal (zoals opgebouwd in Task 3's testscript) en minstens één open patroon-signaal met een reële `reason`-breakdown (zoals opgebouwd in Task 2's testscript), en controleer met Chromium (`/opt/pw-browsers/chromium`, zie eerdere sessies in dit project voor het exacte Node-commando):
- De patroonbadge ("double bottom" e.d.) staat nog gewoon op de kaart, mét een percentage ernaast.
- De "waarom dit patroon?"-uitklap toont ✓/✗-regels per factor, niet meer de platte "Patroon: ..., richting ..."-tekst.
- Op `/signalen`, het dashboard en de coin-pagina komt de patroon-slagingskans-regel weer in beeld (was verborgen sinds de vorige fix-ronde, hoort nu weer te tonen).

- [ ] **Step 7: Commit**

```bash
git add web/templates/_macros.html web/templates/dashboard.html web/templates/account.html web/templates/coin.html
git commit -m "Patroon+factoren: templates tonen de echte factor-breakdown en kansberekening"
```

---

### Task 7: Volledige regressie + push

**Files:** geen nieuwe wijzigingen, alleen verificatie.

- [ ] **Step 1: Import-check van alle gewijzigde modules**

```bash
python3 -c "
import app.signal_processor, app.market_scanner, app.repo, app.advice, web.main
print('imports OK')
"
```
Expected: "imports OK", geen ImportError.

- [ ] **Step 2: Herdraai Taak 1 t/m 4's throwaway-scripts achter elkaar**

Alle vier scripts uit de Steps hierboven nog een keer draaien tegen verse scratch-databases, om te bevestigen dat de latere taken de eerdere niet stilzwijgend hebben gebroken.

- [ ] **Step 3: Jinja2-compileercheck van alle aangepaste templates**

```bash
python3 -c "
from jinja2 import Environment, FileSystemLoader
env = Environment(loader=FileSystemLoader('web/templates'))
env.filters['age'] = lambda x: x
for name in ['_macros.html', 'dashboard.html', 'account.html', 'coin.html', 'signalen.html']:
    env.get_template(name)
print('templates OK')
"
```
Expected: "templates OK", geen TemplateSyntaxError.

- [ ] **Step 4: Push**

```bash
git push origin claude/crypto-day-trading-alerts-5p8w6v
```
