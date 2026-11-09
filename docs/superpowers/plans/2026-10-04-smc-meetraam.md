# SMC-meetraam Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Het SMC-type (`trade_type='smc'`, snelle trades op 30m/15m) afspelen over 12 maanden Binance-data met uitkomsten op 1-minuut-candles, zodat we zien waarom 82% van de setups doodloopt, hoe snel trades eindigen, en wat een verandering in R na kosten oplevert.

**Architecture:** De beslislogica van `_check_smc_setup` en `_complete_smc_setup` wordt zonder gedragswijziging in pure functies (`app/smc_eval.py`) gezet; de live code roept die aan. Het raam bouwt alle timeframes uit een 1m-basis (zo is de lopende 15m/30m-candle gedeeltelijk, precies zoals live), houdt de setups in het geheugen bij (`SmcBook`, gelijk aan `repo.upsert_smc_setup`) en speelt per 5 minuten door de tijd. Een sequentie-golden van de live code en een equivalentietest live-tegen-raam bewijzen dat beide hetzelfde beslissen.

**Tech Stack:** Python 3, pandas, stdlib `unittest`, bestaande `app/replay/` (zie het eerste meetraam-plan).

**Spec:** `docs/superpowers/specs/2026-10-04-signaalkwaliteit-design.md` (deel 1, meetraam, type smc). Voorganger: `docs/superpowers/plans/2026-10-04-meetraam.md` (day_trading, gebouwd). Verbeteringen testen (stopmarge, zone-buffer, filters, take-varianten) volgt als eigen plan op de resultaten van dit raam.

## Global Constraints

- Geen nieuwe dependency. Tests met `unittest` vanaf de repo-root: `python3 -m unittest discover -s tests -t . -v`. Python voor tests in de sandbox: `/tmp/claude-0/venv/bin/python` (volledige requirements); op de VPS in een aparte kloon met de bestaande venv.
- Gedrag van de live SMC-pijplijn mag niet veranderen. Elke refactor in `app/market_scanner.py` wordt vooraf met een sequentie-golden vastgelegd en daarna identiek bevonden.
- Namen die andere modules uit `app.market_scanner` importeren blijven daar importeerbaar: `smc_stop_take_margins` (web/main.py), `SMC_SETUP_MAX_AGE_HOURS` (scripts/check_dead_smc_setups.py, scripts/cleanup_stale_smc_setups.py). Verhuis je een constante naar `smc_eval`, dan importeert `market_scanner` hem terug (`# noqa: F401`).
- Comments leggen het niet-voor-de-hand-liggende *waarom* uit (CLAUDE.md). Bij verplaatste code blijven de bestaande comments letterlijk behouden.
- De SMC-timer draait elke 5 minuten op minuut 3, 8, 13, ... (`deploy/crypto-market-scan-smc.timer`). Het raam stapt daarom per 5 minuten met een offset van 3 minuten t.o.v. het uur (instelling).
- Kosten (fee 0,1% en slippage 0,05% per kant) en uitkomstvenster zijn instellingen. Het uitkomstvenster blijft gelijk aan live (effectief 48 uur, zie `level_check.SIGNAL_MAX_AGE_DAYS` en `.days`). Het rapport toont daarnaast de tijd tot uitkomst in minuten.
- Alleen 1m-candles die op het tijdstip gesloten waren zijn zichtbaar; de lopende candle van een afgeleid timeframe is gedeeltelijk (zoals live).
- Niet nagebootst: `scan_market`-pre-checks voor de 4u-detectoren, de structurele tegenstrijdigheid-onderdrukking (`smc_direction`), pushmeldingen, journal-fan-out. Elk rapport noemt dit.

## Bestandsstructuur

- Modify `app/replay/candles.py`: cache per timeframe (1m erbij), `ensure_candles(coin, years, timeframe="15m")`.
- Modify `app/replay/view.py`: `ReplayData(base, at, base_delta=BASE_DELTA)`, 1m/5m/30m erbij.
- Create `app/smc_eval.py`: pure SMC-beslislogica en verplaatste constanten.
- Modify `app/market_scanner.py`: gebruikt `smc_eval`.
- Create `app/replay/smc_engine.py`: `SmcBook`, `replay_smc()`.
- Create `app/replay/smc_report.py`: trechter, prestaties, snelheid, kosten.
- Create `scripts/replay_smc_report.py`, `scripts/replay_smc_compare_live.py`.
- Create tests: `tests/replay/test_view_1m.py`, `tests/replay/test_smc_engine.py`, `tests/replay/test_smc_report.py`, `tests/test_smc_eval.py`, `tests/test_smc_golden.py`, `tests/test_smc_equivalence.py`, `tests/golden/smc_sequence.json`; uitbreiding `tests/replay/fixtures.py` met `make_smc_prone_1m`.
- Modify `README.md`, `CLAUDE.md` (korte vermelding).

---

### Task 1: 1m-basis voor candles en ReplayData

**Files:**
- Modify: `app/replay/candles.py`, `app/replay/view.py`
- Modify: `tests/replay/fixtures.py` (generator `make_smc_prone_1m`)
- Test: `tests/replay/test_view_1m.py`

**Interfaces:**
- Produces: `candles.BASE_DELTAS = {"1m": pd.Timedelta(minutes=1), "15m": BASE_DELTA}`; `candles.cache_path(coin, timeframe="15m")`; `candles.download_candles(coin, years, fetch=None, now=None, timeframe="15m")`, `candles.load_candles(coin, timeframe="15m")`, `candles.save_candles(coin, df, timeframe="15m")`, `candles.ensure_candles(coin, years, refresh=False, timeframe="15m")`. De bestaande 15m-bestandsnaam (`{COIN}_15m.csv`) en alle bestaande aanroepen blijven werken.
- Produces: `ReplayData(base, at, base_delta=BASE_DELTA)`; `fetch_ohlcv(coin, timeframe, limit, since)` ondersteunt `"1m", "5m", "15m", "30m", "1h", "4h", "1d"`. Is `timeframe` gelijk aan de basis, dan blijft het gedrag van nu (alleen gesloten candles). Een afgeleid timeframe bevat de lopende candle gedeeltelijk.
- Produces: `tests.replay.fixtures.make_smc_prone_1m(days, start, seed, start_price) -> DataFrame` (1m, deterministisch, met trend-segmenten en wicks zodat structuurbreuken en sweeps voorkomen).

- [ ] **Step 1: Schrijf de falende test**

`tests/replay/test_view_1m.py`:

```python
import unittest

import pandas as pd

from app.replay import candles, view
from tests.replay.fixtures import make_smc_prone_1m

ONE_MINUTE = pd.Timedelta(minutes=1)


class OneMinuteBaseTest(unittest.TestCase):
    def setUp(self):
        self.base = make_smc_prone_1m(days=5)

    def data_at(self, at):
        return view.ReplayData({"ETH": self.base}, pd.Timestamp(at, tz="UTC"), base_delta=ONE_MINUTE)

    def test_cache_path_per_timeframe(self):
        self.assertTrue(str(candles.cache_path("eth", "1m")).endswith("ETH_1m.csv"))
        self.assertTrue(str(candles.cache_path("eth")).endswith("ETH_15m.csv"))

    def test_no_lookahead_and_forming_15m_is_partial(self):
        data = self.data_at("2026-01-03 10:07")
        df = data.fetch_ohlcv("ETH", "15m", limit=20)
        self.assertEqual(df["timestamp"].iloc[-1], pd.Timestamp("2026-01-03 10:00", tz="UTC"))
        part = self.base[(self.base["timestamp"] >= "2026-01-03 10:00") & (self.base["timestamp"] < "2026-01-03 10:07")]
        self.assertAlmostEqual(df["volume"].iloc[-1], part["volume"].sum())
        self.assertAlmostEqual(df["close"].iloc[-1], part["close"].iloc[-1])
        self.assertTrue((df["timestamp"] < pd.Timestamp("2026-01-03 10:07", tz="UTC")).all())

    def test_30m_candle_is_aggregate_of_1m(self):
        df = self.data_at("2026-01-03 10:45").fetch_ohlcv("ETH", "30m", limit=5)
        self.assertEqual(df["timestamp"].iloc[-1], pd.Timestamp("2026-01-03 10:30", tz="UTC"))
        part = self.base[(self.base["timestamp"] >= "2026-01-03 10:30") & (self.base["timestamp"] < "2026-01-03 10:45")]
        self.assertAlmostEqual(df["high"].iloc[-1], part["high"].max())
        self.assertAlmostEqual(df["low"].iloc[-1], part["low"].min())

    def test_1m_returns_only_closed_candles(self):
        df = self.data_at("2026-01-03 10:07").fetch_ohlcv("ETH", "1m", limit=10)
        self.assertEqual(df["timestamp"].iloc[-1], pd.Timestamp("2026-01-03 10:06", tz="UTC"))


if __name__ == "__main__":
    unittest.main()
```

Voeg `make_smc_prone_1m` toe aan `tests/replay/fixtures.py` (de signatuur staat vast; de parameters van de generator mag de implementeerder aanpassen tot Step 2 van Task 2 aantoont dat er setups, minstens één signaal en minstens één ongeldigverklaring voorkomen):

```python
def make_smc_prone_1m(days: int = 12, start: str = "2026-01-01", seed: int = 5, start_price: float = 100.0) -> pd.DataFrame:
    """1m-data met trend-segmenten en uitschietende wicks, zodat structuurbreuken,
    sweeps en fair-value-gaps op 30m/15m voorkomen. Deterministisch."""
    rng = np.random.default_rng(seed)
    n = days * 1440
    drift = np.zeros(n)
    i = 0
    while i < n:
        length = int(rng.integers(90, 420))
        drift[i:i + length] = rng.choice([-1, 1]) * rng.uniform(0.0002, 0.0007)
        i += length
    noise = rng.normal(0, 0.0009, n)
    spikes = (rng.random(n) < 0.002) * rng.normal(0, 0.006, n)
    closes = start_price * np.exp(np.cumsum(drift + noise + spikes))
    ts = pd.date_range(start, periods=n, freq="1min", tz="UTC")
    opens = np.concatenate([[start_price], closes[:-1]])
    wick = np.abs(rng.normal(0, 0.0006, n)) + np.abs(spikes) * 0.5
    highs = np.maximum(opens, closes) * (1 + wick)
    lows = np.minimum(opens, closes) * (1 - wick)
    volume = rng.lognormal(4, 0.4, n)
    return pd.DataFrame({"timestamp": ts, "open": opens, "high": highs, "low": lows, "close": closes, "volume": volume})
```

- [ ] **Step 2: Draai de test, verwacht falen**

Run: `/tmp/claude-0/venv/bin/python -m unittest tests.replay.test_view_1m -v`
Expected: `TypeError: ... got an unexpected keyword argument 'base_delta'` of `AttributeError` op `cache_path`.

- [ ] **Step 3: Pas `candles.py` aan**

Vervang in `app/replay/candles.py` de constanten en functies zo dat `timeframe` overal doorgegeven wordt. Het volledige bestand wordt:

```python
"""Lokale cache van basis-candles voor het meetraam (15m voor day_trading, 1m
voor smc). Alle andere timeframes worden hieruit afgeleid (zie view.py), zodat
een afgeleide candle nooit ongemerkt later gesloten kan zijn dan het moment
waarop hij wordt gebruikt."""
from pathlib import Path
from typing import Callable, Optional

import pandas as pd

from app import config, exchange

BASE_TIMEFRAME = "15m"
BASE_DELTA = pd.Timedelta(minutes=15)
BASE_DELTAS = {"1m": pd.Timedelta(minutes=1), "15m": BASE_DELTA}
PAGE_LIMIT = 1000
CACHE_DIR = Path(config.BASE_DIR) / "data" / "candles"


def cache_path(coin: str, timeframe: str = BASE_TIMEFRAME) -> Path:
    return CACHE_DIR / f"{coin.upper()}_{timeframe}.csv"


def download_candles(
    coin: str, years: float, fetch: Optional[Callable] = None, now: Optional[pd.Timestamp] = None,
    timeframe: str = BASE_TIMEFRAME,
) -> pd.DataFrame:
    """Haalt `years` jaar candles op, pagina voor pagina. Een nog vormende
    candle (nu nog niet gesloten) blijft er bewust uit: het raam bepaalt zelf
    per tijdstip welke candle nog in wording is."""
    fetch = fetch or exchange.fetch_ohlcv
    delta = BASE_DELTAS[timeframe]
    now = now or pd.Timestamp.now(tz="UTC")
    since = int((now - pd.Timedelta(days=365 * years)).timestamp() * 1000)
    pages = []
    while True:
        page = fetch(coin, timeframe=timeframe, limit=PAGE_LIMIT, since=since)
        if page.empty:
            break
        pages.append(page)
        last_ts = page["timestamp"].iloc[-1]
        next_since = int(last_ts.timestamp() * 1000) + int(delta.total_seconds() * 1000)
        if next_since <= since or last_ts + delta >= now:
            break
        since = next_since
    if not pages:
        return pd.DataFrame(columns=["timestamp", "open", "high", "low", "close", "volume"])
    df = pd.concat(pages).drop_duplicates("timestamp").sort_values("timestamp")
    df = df[df["timestamp"] + delta <= now]
    return df.reset_index(drop=True)


def save_candles(coin: str, df: pd.DataFrame, timeframe: str = BASE_TIMEFRAME) -> None:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    df.to_csv(cache_path(coin, timeframe), index=False)


def load_candles(coin: str, timeframe: str = BASE_TIMEFRAME) -> pd.DataFrame:
    df = pd.read_csv(cache_path(coin, timeframe))
    df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True)
    return df


def ensure_candles(coin: str, years: float, refresh: bool = False, timeframe: str = BASE_TIMEFRAME) -> pd.DataFrame:
    """Geeft de gecachete candles terug, of downloadt ze als er nog geen
    cache is (of `refresh` gezet is)."""
    if not refresh and cache_path(coin, timeframe).exists():
        return load_candles(coin, timeframe)
    df = download_candles(coin, years, timeframe=timeframe)
    save_candles(coin, df, timeframe)
    return df
```

Controleer dat `tests/replay/test_candles.py` ongewijzigd blijft slagen.

- [ ] **Step 4: Pas `view.py` aan**

In `app/replay/view.py`:

```python
TIMEFRAME_DELTAS = {
    "1m": pd.Timedelta(minutes=1),
    "5m": pd.Timedelta(minutes=5),
    "15m": pd.Timedelta(minutes=15),
    "30m": pd.Timedelta(minutes=30),
    "1h": pd.Timedelta(hours=1),
    "4h": pd.Timedelta(hours=4),
    "1d": pd.Timedelta(days=1),
}
# "24h" in plaats van "1D": alleen een Tick-achtige frequentie respecteert
# origin="epoch", en zo sluit de daily candle aan op Binance (00:00 UTC).
_RESAMPLE_RULES = {"5m": "5min", "15m": "15min", "30m": "30min", "1h": "1h", "4h": "4h", "1d": "24h"}
```

`ReplayData.__init__(self, base, at, base_delta=BASE_DELTA)` slaat `self._base_delta = base_delta` op. In `_visible` wordt `BASE_DELTA` vervangen door `self._base_delta`. In `fetch_ohlcv` wordt `ratio = int(TIMEFRAME_DELTAS[timeframe] / self._base_delta)`, en het basis-pad is `if TIMEFRAME_DELTAS[timeframe] == self._base_delta: out = visible`. `fetch_24h_quote_volume` gebruikt `int(pd.Timedelta(hours=24) / self._base_delta)` candles in plaats van het vaste `_QUOTE_VOLUME_CANDLES`. Het gedrag bij de standaard basis (15m) blijft exact gelijk.

- [ ] **Step 5: Draai alle tests**

Run: `/tmp/claude-0/venv/bin/python -m unittest tests.replay.test_view_1m tests.replay.test_view tests.replay.test_candles -v`
Expected: `OK` (nieuwe en bestaande view- en candle-tests).

- [ ] **Step 6: Commit**

```bash
git add app/replay/candles.py app/replay/view.py tests/replay/fixtures.py tests/replay/test_view_1m.py
git commit -m "Meetraam: 1m-basis voor candles en ReplayData, 30m/5m/1m timeframes"
```

---

### Task 2: Pure SMC-beslislogica (`smc_eval`), sequentie-golden eerst

Doel: `_check_smc_setup` en `_complete_smc_setup` lezen de database en de exchange. De beslissingen zelf worden pure functies in `app/smc_eval.py`; live roept ze aan.

**Files:**
- Create: `tests/test_smc_golden.py`, `tests/golden/smc_sequence.json`
- Create: `app/smc_eval.py`, `tests/test_smc_eval.py`
- Modify: `app/market_scanner.py`

**Interfaces:**
- Consumes: `ReplayData(..., base_delta)`, `make_smc_prone_1m` (Task 1).
- Produces in `app/smc_eval.py` (de verplaatste constanten en hulpfuncties behouden hun waarde en comments):
  `SMC_ZONE_SEARCH_LOOKBACK_30M`, `STOP_MARGIN_ATR_MULTIPLE`, `TARGET_MARGIN_ATR_MULTIPLE`, `LEGACY_STOP_MARGIN_PCT`, `LEGACY_TARGET_MARGIN_PCT`, `SMC_SETUP_MAX_AGE_HOURS`, `ZONE_BREAK_BUFFER_ATR_MULTIPLE`, `SMC_ENTRY_CANDLE_MINUTES`, `SMC_MAX_CANDLES_PER_CHECK`, `smc_stop_take_margins(setup)`, `last_candle_state(candle, zone_low, zone_high, direction, atr=None)`, `candles_since(closed_15m, since_iso)`, `valid_stop_take(direction, entry, stop, take)`.
  Plus nieuw:
  - `@dataclass SmcCandidate(direction, zone_low, zone_high, structure_level, sweep_price, liquidity_target, atr)`
  - `@dataclass SmcScan(break_direction: Optional[str], candidate: Optional[SmcCandidate], skip_reason: Optional[str], detail: str = "")`
  - `find_candidate(closed_30m, df_30m, closed_15m, last_candle) -> SmcScan`
  - `setup_expired(setup: dict, now: datetime) -> bool`
  - `judge_forming_setup(setup: dict, closed_15m) -> str` met uitkomst `"rejected"`, `"passed"` of `"open"`
  - `@dataclass SmcSignalDraft(entry_price, stop_loss, take_profit, sniper_entry_price, sniper_reason, risk_reward_ratio)`
  - `@dataclass SmcCompletion(signal: Optional[SmcSignalDraft], reject_reason: Optional[str], detail: str = "")`
  - `evaluate_completion(setup: dict, df_15m) -> SmcCompletion` (entry = `df_15m["close"].iloc[-1]`, de lopende candle telt mee zoals live)
  `skip_reason`-codes: `geen_structuurbreuk`, `geen_sweep`, `geen_confluentiezone`, `geen_liquiditeitsdoel`, `stop_of_doel_binnen_zone`, `koers_al_in_zone`. `reject_reason`-codes: `entry_slechter_dan_sniper`, `stop_take_verkeerde_kant`, `risico_rendement_te_laag`.
  Setups zijn gewone `dict`s met dezelfde sleutels als een `smc_setups`-rij (`id, coin, direction, zone_low, zone_high, structure_level, sweep_price, liquidity_target, atr, created_at, updated_at, signal_id, invalidated_at`).

- [ ] **Step 1: Schrijf de sequentie-golden-test en neem hem op, vóór enige wijziging**

`tests/test_smc_golden.py`:

```python
"""Golden-test: de live SMC-pijplijn (market_scanner._run_smc_check) geeft na de
extractie over een hele synthetische periode exact dezelfde setups en signalen
als ervoor. Opnemen met: python3 -m tests.test_smc_golden --record (alleen op
code die nog NIET is aangepast; zie tests/golden/ voor de herstelinstructie)."""
import asyncio
import json
import sys
import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest import mock

import pandas as pd

from app import config, db, market_scanner, repo
from app.replay.view import ReplayData
from tests.replay.fixtures import make_smc_prone_1m

GOLDEN = Path(__file__).parent / "golden" / "smc_sequence.json"
ONE_MINUTE = pd.Timedelta(minutes=1)
COIN = "ETH"
START = pd.Timestamp("2026-01-03 00:03", tz="UTC")
END = pd.Timestamp("2026-01-12 00:03", tz="UTC")
STEP = pd.Timedelta(minutes=5)


class FrozenClock:
    now = datetime(2026, 1, 1)


class FrozenDatetime(datetime):
    @classmethod
    def now(cls, tz=None):
        return FrozenClock.now


def run_live_sequence() -> dict:
    base = {COIN: make_smc_prone_1m(days=12, seed=5, start_price=2600.0)}
    with tempfile.TemporaryDirectory() as tmp, \
            mock.patch.object(config, "DATABASE_PATH", str(Path(tmp) / "t.db")), \
            mock.patch.object(market_scanner, "datetime", FrozenDatetime), \
            mock.patch.object(db, "now_iso", lambda: FrozenClock.now.isoformat()):
        db.init_db()
        t = START
        while t <= END:
            FrozenClock.now = t.to_pydatetime()
            data = ReplayData(base, t, base_delta=ONE_MINUTE)
            with mock.patch.object(market_scanner, "exchange", data):
                asyncio.run(market_scanner._run_smc_check(COIN))
            t += STEP
        with db.session() as conn:
            setups = [dict(r) for r in conn.execute("SELECT * FROM smc_setups ORDER BY id")]
            signals = [dict(r) for r in conn.execute(
                "SELECT id, coin, direction, price, stop_loss, take_profit, created_at, sniper_entry_price "
                "FROM signals ORDER BY id")]
    def rounded(row):
        return {k: (round(v, 6) if isinstance(v, float) else v) for k, v in row.items()}
    return {"setups": [rounded(r) for r in setups], "signals": [rounded(r) for r in signals]}


class GoldenTest(unittest.TestCase):
    def test_live_sequence_matches_golden(self):
        self.assertEqual(run_live_sequence(), json.loads(GOLDEN.read_text()))


if __name__ == "__main__":
    if "--record" in sys.argv:
        GOLDEN.parent.mkdir(parents=True, exist_ok=True)
        result = run_live_sequence()
        GOLDEN.write_text(json.dumps(result, indent=1, ensure_ascii=False))
        print(f"golden opgenomen in {GOLDEN}: {len(result['setups'])} setups, {len(result['signals'])} signalen")
    else:
        unittest.main()
```

Run (op ongewijzigde code): `/tmp/claude-0/venv/bin/python -m tests.test_smc_golden --record`
Expected: `golden opgenomen ...: N setups, M signalen`. Dit duurt enkele minuten (2592 stappen).

Controleer: er staan minstens 3 setups in, minstens 1 setup met een `signal_id` (afgewezen en voltooid), minstens 1 met `invalidated_at` en minstens 1 signaal. Is dat niet zo: pas `make_smc_prone_1m`-parameters (drift-lengte, ruis, spikes) of `seed` aan, niet de productiecode, en neem opnieuw op. Voeg de gekozen waarden toe aan de docstring van de test.

Run: `/tmp/claude-0/venv/bin/python -m unittest tests.test_smc_golden -v`
Expected: `OK`

- [ ] **Step 2: Commit het golden-bestand en de test**

```bash
git add tests/test_smc_golden.py tests/golden/smc_sequence.json tests/replay/fixtures.py
git commit -m "Test: sequentie-golden voor de live SMC-pijplijn, vóór de extractie opgenomen"
```

- [ ] **Step 3: Maak `app/smc_eval.py`**

Verplaats uit `app/market_scanner.py` letterlijk (met alle comments): de constanten `SMC_ZONE_SEARCH_LOOKBACK_30M`, `STOP_MARGIN_ATR_MULTIPLE`, `TARGET_MARGIN_ATR_MULTIPLE`, `LEGACY_STOP_MARGIN_PCT`, `LEGACY_TARGET_MARGIN_PCT`, `SMC_SETUP_MAX_AGE_HOURS`, `ZONE_BREAK_BUFFER_ATR_MULTIPLE`, `SMC_ENTRY_CANDLE_MINUTES`, `SMC_MAX_CANDLES_PER_CHECK` en de functies `smc_stop_take_margins`, `_smc_last_candle_state` (nieuwe naam `last_candle_state`), `_smc_candles_since` (nieuwe naam `candles_since`) en `_valid_stop_take` (nieuwe naam `valid_stop_take`). De imports bovenin: `from dataclasses import dataclass`, `from datetime import datetime, timedelta`, `from typing import Optional`, `from app import indicators`, `from app.setup_eval import MIN_RISK_REWARD_RATIO`.

Voeg daarna de nieuwe delen toe (de bodies zijn de bestaande logica uit `_check_smc_setup` fase 1 en 2 en uit `_complete_smc_setup`, ongewijzigd behalve dat database, exchange en logging eruit zijn):

```python
@dataclass
class SmcCandidate:
    direction: str
    zone_low: float
    zone_high: float
    structure_level: float
    sweep_price: float
    liquidity_target: float
    atr: float


@dataclass
class SmcScan:
    # Richting van de laatst gevonden structuurbreuk, ook als er daarna geen
    # kandidaat overblijft: de aanroeper laat bestaande setups in de andere
    # richting vervallen zodra een breuk is gezien (zie _check_smc_setup).
    break_direction: Optional[str]
    candidate: Optional[SmcCandidate]
    skip_reason: Optional[str]
    detail: str = ""


def setup_expired(setup: dict, now: datetime) -> bool:
    created_at = datetime.fromisoformat(setup["created_at"])
    return (now - created_at).total_seconds() / 3600 > SMC_SETUP_MAX_AGE_HOURS


def judge_forming_setup(setup: dict, closed_15m) -> str:
    """Fase 1 van _check_smc_setup voor één bouwende setup: "rejected" zodra een
    candle sinds de vorige beoordeling de zone raakte en er weer buiten sloot
    (entry-trigger), "passed" zodra een candle er doorheen sloot zonder afwijzing
    (setup achterhaald), anders "open"."""
    for candle in candles_since(closed_15m, setup["updated_at"]):
        in_zone, rejected, passed_without_rejection = last_candle_state(
            candle, setup["zone_low"], setup["zone_high"], setup["direction"], atr=setup["atr"],
        )
        if rejected:
            return "rejected"
        # Geen extra in_zone-eis: de candle die door de zone heen sluit
        # heeft vrijwel altijd zelf een staart in de zone, en rejected en
        # passed_without_rejection sluiten elkaar al uit (close aan
        # tegenovergestelde kanten van de zone).
        if passed_without_rejection:
            return "passed"
    return "open"


def find_candidate(closed_30m, df_30m, closed_15m, last_candle) -> SmcScan:
    structure_break = indicators.find_structure_break(closed_30m)
    if structure_break is None:
        return SmcScan(None, None, "geen_structuurbreuk")
    direction = structure_break.direction
    # Op hetzelfde moment en dezelfde candle-set als de breuk zelf: de
    # volatiliteit die hier geldt, is die van de 30m-candle waarop de
    # structuur net brak, niet een latere, mogelijk heel andere ATR.
    atr = indicators.compute_indicators(closed_30m).atr

    sweep = indicators.find_liquidity_sweep_before_break(closed_30m, structure_break)
    if sweep is None:
        return SmcScan(direction, None, "geen_sweep")

    sweep_time = closed_30m["timestamp"].iloc[sweep.index]
    displacement_15m = closed_15m[closed_15m["timestamp"] >= sweep_time]
    fvgs = indicators.find_fair_value_gaps(displacement_15m, direction)
    order_blocks = indicators.find_order_blocks(displacement_15m, direction)
    zone = indicators.find_confluence_zone(fvgs, order_blocks)
    if zone is None:
        return SmcScan(direction, None, "geen_confluentiezone")
    zone_low, zone_high = zone

    since_break = df_30m.iloc[structure_break.break_index:]
    if direction == "long":
        untouched_from = max(zone_high, float(since_break["high"].max()))
    else:
        untouched_from = min(zone_low, float(since_break["low"].min()))
    target_kind = "high" if direction == "long" else "low"
    target_pivots = [
        p for p in indicators._find_pivots(closed_30m)
        if p.kind == target_kind and (
            (direction == "long" and p.price > untouched_from) or
            (direction == "short" and p.price < untouched_from)
        )
    ]
    if not target_pivots:
        return SmcScan(direction, None, "geen_liquiditeitsdoel")
    liquidity_target_pivot = min(target_pivots, key=lambda p: abs(p.price - untouched_from))

    sign = 1 if direction == "short" else -1
    projected_stop_loss = sweep.price + sign * STOP_MARGIN_ATR_MULTIPLE * atr
    projected_take_profit = liquidity_target_pivot.price + sign * TARGET_MARGIN_ATR_MULTIPLE * atr
    stop_niet_voorbij_zone = (
        (direction == "short" and projected_stop_loss <= zone_high) or
        (direction == "long" and projected_stop_loss >= zone_low)
    )
    doel_niet_voorbij_zone = (
        (direction == "short" and projected_take_profit >= zone_low) or
        (direction == "long" and projected_take_profit <= zone_high)
    )
    if stop_niet_voorbij_zone or doel_niet_voorbij_zone:
        return SmcScan(
            direction, None, "stop_of_doel_binnen_zone",
            detail=f"stop {projected_stop_loss:.4f} / doel {projected_take_profit:.4f} (na marge) liggen niet voorbij de zone {zone_low:.4f}-{zone_high:.4f}",
        )

    last_close = float(last_candle["close"])
    if (direction == "short" and last_close >= zone_low) or (direction == "long" and last_close <= zone_high):
        return SmcScan(direction, None, "koers_al_in_zone")

    return SmcScan(direction, SmcCandidate(
        direction=direction, zone_low=zone_low, zone_high=zone_high,
        structure_level=structure_break.broken_pivot.price, sweep_price=sweep.price,
        liquidity_target=liquidity_target_pivot.price, atr=atr,
    ), None)


@dataclass
class SmcSignalDraft:
    entry_price: float
    stop_loss: float
    take_profit: float
    sniper_entry_price: Optional[float]
    sniper_reason: Optional[str]
    risk_reward_ratio: float


@dataclass
class SmcCompletion:
    signal: Optional[SmcSignalDraft]
    reject_reason: Optional[str]
    detail: str = ""


def evaluate_completion(setup: dict, df_15m) -> SmcCompletion:
    direction = setup["direction"]
    sign = -1 if direction == "long" else 1
    stop_margin, target_margin = smc_stop_take_margins(setup)
    stop_loss = setup["sweep_price"] + stop_margin * sign
    take_profit = setup["liquidity_target"] + target_margin * sign
    entry_price = float(df_15m["close"].iloc[-1])

    sniper = indicators.find_sniper_entry_price(direction, df_15m)
    sniper_entry_price, sniper_reason = sniper if sniper else (None, None)
    entry_worse_than_sniper = (
        sniper_entry_price is None
        or (direction == "short" and entry_price < sniper_entry_price)
        or (direction == "long" and entry_price > sniper_entry_price)
    )
    if entry_worse_than_sniper:
        return SmcCompletion(None, "entry_slechter_dan_sniper", detail=(
            f"entry {entry_price:.4f} ligt niet meer aan de juiste kant van de sniper-prijs "
            f"({f'{sniper_entry_price:.4f}' if sniper_entry_price is not None else 'geen sniper gevonden'}, {direction})"
        ))

    if sniper_entry_price is not None and indicators.sniper_beyond_stop(direction, sniper_entry_price, stop_loss):
        sniper_entry_price, sniper_reason = None, None

    if not valid_stop_take(direction, entry_price, stop_loss, take_profit):
        return SmcCompletion(None, "stop_take_verkeerde_kant", detail=(
            f"stop {stop_loss:.4f} / doel {take_profit:.4f} liggen niet aan de juiste kant van entry {entry_price:.4f} ({direction})"
        ))

    risk_distance = abs(entry_price - stop_loss)
    reward_distance = abs(take_profit - entry_price)
    risk_reward_ratio = (reward_distance / risk_distance) if risk_distance else 0.0
    if risk_reward_ratio < MIN_RISK_REWARD_RATIO:
        return SmcCompletion(None, "risico_rendement_te_laag", detail=(
            f"risico/rendement {risk_reward_ratio:.2f} tegen 1 onder de ondergrens van {MIN_RISK_REWARD_RATIO} "
            f"(stop {stop_loss:.4f} / doel {take_profit:.4f} / entry {entry_price:.4f}, {direction})"
        ))

    return SmcCompletion(SmcSignalDraft(
        entry_price, stop_loss, take_profit, sniper_entry_price, sniper_reason, risk_reward_ratio,
    ), None)
```

Behoud bij de verplaatste constanten en functies hun volledige comment-blokken uit `market_scanner.py`. De comments van de brokken die hierboven in de nieuwe functies zijn opgenomen (liquidity-doel, de afbakening van de displacement, de ATR-marge-uitleg, de entry-vs-sniper-uitleg, de geen-`stop_within_max_distance`-uitleg) verhuizen mee en worden niet ingekort: kopieer ze uit `git show HEAD:app/market_scanner.py` naar de overeenkomstige plek, met verwijzingen aangepast aan de nieuwe plek.

- [ ] **Step 4: Laat `market_scanner.py` `smc_eval` gebruiken**

Bovenin `app/market_scanner.py`:

```python
from app.smc_eval import (  # noqa: F401  (andere modules importeren deze namen hier)
    LEGACY_STOP_MARGIN_PCT, LEGACY_TARGET_MARGIN_PCT, SMC_ENTRY_CANDLE_MINUTES, SMC_MAX_CANDLES_PER_CHECK,
    SMC_SETUP_MAX_AGE_HOURS, SMC_ZONE_SEARCH_LOOKBACK_30M, STOP_MARGIN_ATR_MULTIPLE, TARGET_MARGIN_ATR_MULTIPLE,
    ZONE_BREAK_BUFFER_ATR_MULTIPLE, candles_since, evaluate_completion, find_candidate, judge_forming_setup,
    last_candle_state, setup_expired, smc_stop_take_margins, valid_stop_take,
)
```

Verwijder de verplaatste definities uit `market_scanner.py`. Als `_valid_stop_take` ook buiten het SMC-pad wordt gebruikt (grep!), laat dan `_valid_stop_take = valid_stop_take` als alias staan.

`_check_smc_setup` fase 1 wordt:

```python
    existing = [s for s in repo.list_forming_smc_setups() if s["coin"] == coin]
    for existing_setup in existing:
        if setup_expired(existing_setup, datetime.now(timezone.utc)):
            age_hours = (datetime.now(timezone.utc) - datetime.fromisoformat(existing_setup["created_at"])).total_seconds() / 3600
            repo.invalidate_smc_setup(existing_setup["id"])
            logger.info(
                "%s %s SMC-setup vervallen na %.0f uur zonder afwijzing of doorbraak",
                coin, existing_setup["direction"], age_hours,
            )
            continue
        verdict = judge_forming_setup(existing_setup, closed_15m)
        if verdict == "rejected":
            return existing_setup
        if verdict == "passed":
            repo.invalidate_smc_setup(existing_setup["id"])
            break
```

Fase 2 (vanaf het ophalen van `df_30m`) wordt:

```python
    df_30m = await asyncio.to_thread(
        exchange.fetch_ohlcv, coin, timeframe="30m", limit=SMC_ZONE_SEARCH_LOOKBACK_30M + 1,
    )
    closed_30m = df_30m.iloc[:-1]
    scan = find_candidate(closed_30m, df_30m, closed_15m, last_candle)
    if scan.break_direction is None:
        return None
    # Een nieuwe breuk in de TEGENGESTELDE richting van een bestaande
    # bouwende setup maakt die setup achterhaald (de markt heeft zijn
    # structuur omgedraaid voordat de oude zone geraakt werd).
    for existing_setup in existing:
        if existing_setup["direction"] != scan.break_direction:
            repo.invalidate_smc_setup(existing_setup["id"])
    if scan.candidate is None:
        if scan.skip_reason == "stop_of_doel_binnen_zone":
            logger.info("%s %s SMC-setup overgeslagen: %s", coin, scan.break_direction, scan.detail)
        return None
    candidate = scan.candidate
    direction, zone_low, zone_high = candidate.direction, candidate.zone_low, candidate.zone_high

    setup_id = repo.upsert_smc_setup(
        coin, direction, zone_low, zone_high,
        structure_level=candidate.structure_level,
        sweep_price=candidate.sweep_price,
        liquidity_target=candidate.liquidity_target,
        atr=candidate.atr,
        seen_until=(last_candle["timestamp"] + timedelta(minutes=SMC_ENTRY_CANDLE_MINUTES)).isoformat(),
    )
    # ... de rest (list_forming_smc_setups, rejected-check op last_candle, bouwend-melding) blijft letterlijk gelijk.
```

Behoud de bestaande comments bij elk stuk dat hierboven door `find_candidate` is overgenomen (ze staan nu in `smc_eval.py`). Laat de comments die bij de upsert en de bouwend-melding horen op hun plek staan.

`_complete_smc_setup` begint met:

```python
    direction = setup["direction"]
    df_15m = await asyncio.to_thread(exchange.fetch_ohlcv, coin, timeframe="15m")
    completion = evaluate_completion(setup, df_15m)
    if completion.signal is None:
        logger.info("SMC-setup %s voor %s niet gemeld: %s", setup["id"], coin, completion.detail)
        return None
    draft = completion.signal
    entry_price, stop_loss, take_profit = draft.entry_price, draft.stop_loss, draft.take_profit
    sniper_entry_price, sniper_reason = draft.sniper_entry_price, draft.sniper_reason
```

en gaat daarna verder met het bestaande vervolg vanaf `ignored = repo.auto_ignore_opposite_pending(coin, direction)` (de risicoafstand-, R:R- en sniper-berekeningen in het oude blok vervallen: ze zitten nu in `evaluate_completion`). De docstring van `_complete_smc_setup` blijft behouden.

- [ ] **Step 5: Schrijf directe unit-tests voor `smc_eval`**

`tests/test_smc_eval.py` (alle tests asserteren echte waarden):

```python
import unittest
from datetime import datetime, timezone

import pandas as pd

from app import smc_eval


def candle(low, high, close, ts="2026-01-01 10:00"):
    return {"timestamp": pd.Timestamp(ts, tz="UTC"), "open": close, "high": high, "low": low, "close": close, "volume": 1.0}


class CandleStateTest(unittest.TestCase):
    def test_short_rejection_closes_below_zone_after_touch(self):
        in_zone, rejected, passed = smc_eval.last_candle_state(candle(99, 101, 98.5), 100.0, 102.0, "short")
        self.assertEqual((in_zone, rejected, passed), (True, True, False))

    def test_short_passed_needs_close_above_zone_plus_buffer(self):
        _, rejected, passed = smc_eval.last_candle_state(candle(101, 104, 103.5), 100.0, 102.0, "short", atr=2.0)
        self.assertEqual((rejected, passed), (False, True))
        _, _, passed_small = smc_eval.last_candle_state(candle(101, 102.4, 102.3), 100.0, 102.0, "short", atr=2.0)
        self.assertFalse(passed_small)

    def test_long_mirror(self):
        in_zone, rejected, passed = smc_eval.last_candle_state(candle(99.5, 101, 102.5), 100.0, 102.0, "long")
        self.assertEqual((in_zone, rejected, passed), (True, True, False))


class MarginsTest(unittest.TestCase):
    def test_atr_margins(self):
        setup = {"atr": 8.0, "sweep_price": 2820.0, "liquidity_target": 2600.0}
        self.assertEqual(smc_eval.smc_stop_take_margins(setup), (2.0, 2.0))

    def test_legacy_pct_margins_when_atr_missing(self):
        setup = {"atr": None, "sweep_price": 2000.0, "liquidity_target": 1000.0}
        self.assertEqual(smc_eval.smc_stop_take_margins(setup), (2.0, 5.0))


class ExpiryTest(unittest.TestCase):
    def test_expired_after_max_age(self):
        setup = {"created_at": "2026-01-01T00:00:00+00:00"}
        self.assertFalse(smc_eval.setup_expired(setup, datetime(2026, 1, 1, 23, 0, tzinfo=timezone.utc)))
        self.assertTrue(smc_eval.setup_expired(setup, datetime(2026, 1, 2, 1, 0, tzinfo=timezone.utc)))


class JudgeTest(unittest.TestCase):
    def frame(self, rows):
        ts = pd.date_range("2026-01-01 10:00", periods=len(rows), freq="15min", tz="UTC")
        return pd.DataFrame({"timestamp": ts, "open": [r[2] for r in rows], "high": [r[1] for r in rows],
                             "low": [r[0] for r in rows], "close": [r[2] for r in rows], "volume": [1.0] * len(rows)})

    def setup(self, **kw):
        base = {"zone_low": 100.0, "zone_high": 102.0, "direction": "short", "atr": None,
                "updated_at": "2026-01-01T10:00:00+00:00"}
        base.update(kw)
        return base

    def test_rejected_candle_after_updated_at(self):
        closed = self.frame([(95, 96, 95.5), (99, 101, 98.5)])  # tweede candle sluit 10:30, na updated_at
        self.assertEqual(smc_eval.judge_forming_setup(self.setup(), closed), "rejected")

    def test_candle_before_updated_at_is_ignored(self):
        closed = self.frame([(99, 101, 98.5)])  # sloot 10:15
        self.assertEqual(smc_eval.judge_forming_setup(self.setup(updated_at="2026-01-01T10:30:00+00:00"), closed), "open")

    def test_passed_candle(self):
        closed = self.frame([(101, 104, 103.5)])
        self.assertEqual(smc_eval.judge_forming_setup(self.setup(), closed), "passed")


if __name__ == "__main__":
    unittest.main()
```

Voeg in dezelfde file twee tests toe voor `evaluate_completion` met een handgebouwd `df_15m` (genoeg candles voor `find_sniper_entry_price`): een geval waarin `reject_reason == "entry_slechter_dan_sniper"` (geen sweep in de data) en één met `valid_stop_take` en R:R-poort via `mock.patch.object(smc_eval.indicators, "find_sniper_entry_price", return_value=(<prijs>, "reden"))`, waarin `risico_rendement_te_laag` en daarna een geslaagd signaal worden bevestigd met de verwachte waarden van `stop_loss = sweep_price ± margin` en `take_profit = liquidity_target ± margin`.

- [ ] **Step 6: Draai alle tests**

Run: `/tmp/claude-0/venv/bin/python -m unittest tests.test_smc_eval tests.test_smc_golden -v`
Expected: `OK`. De golden moet na de refactor identiek zijn aan het opgenomen bestand.

Run: `/tmp/claude-0/venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -4`
Expected: alle tests `OK`.

Run: `/tmp/claude-0/venv/bin/python -c "import app.market_scanner, web.main" ` (web.main importeert `smc_stop_take_margins`; als `web.main` niet importeerbaar is zonder extra dependencies, controleer dat met `grep -n smc_stop_take_margins web/main.py app/market_scanner.py` en laat de import via de re-export staan).
Expected: geen `ImportError`.

- [ ] **Step 7: Commit**

```bash
git add app/smc_eval.py app/market_scanner.py tests/test_smc_eval.py
git commit -m "SMC-beslislogica als pure functies in smc_eval, live ongewijzigd"
```

---

### Task 3: SMC-afspeel-engine

**Files:**
- Create: `app/replay/smc_engine.py`
- Test: `tests/replay/test_smc_engine.py`, `tests/test_smc_equivalence.py`

**Interfaces:**
- Consumes: `smc_eval` (Task 2), `ReplayData` met `base_delta` (Task 1), `resolve`/`Outcome` (bestaand), `repo.ZONE_DEDUP_PCT`.
- Produces:
  - `SmcBook()` met `upsert(coin, direction, zone_low, zone_high, structure_level, sweep_price, liquidity_target, atr, seen_until, now_iso) -> int`, `forming(coin=None) -> list[dict]`, `invalidate(setup_id, why: str, at_iso: str)`, `complete(setup_id, signal_index)`, `all_setups() -> list[dict]`. Semantiek identiek aan `repo.upsert_smc_setup` / `list_forming_smc_setups` / `invalidate_smc_setup` / `complete_smc_setup`.
  - `@dataclass SmcSignal(coin, direction, at, entry, stop, take, setup_id, outcome: Optional[Outcome], sniper_price: Optional[float])`
  - `@dataclass SmcFunnelEvent(at, coin, direction, kind, detail)` met `kind` uit: `geen_structuurbreuk`, `geen_sweep`, `geen_confluentiezone`, `geen_liquiditeitsdoel`, `stop_of_doel_binnen_zone`, `koers_al_in_zone`, `setup_gebouwd`, `setup_vervallen`, `setup_doorbroken`, `setup_tegenrichting`, `afgewezen_geen_signaal` (met `detail` = reject_reason), `signaal`.
  - `replay_smc(coin, base, outcome_frame, start, end, step=pd.Timedelta(minutes=5), max_age=pd.Timedelta(days=2), fee_pct=0.1, slippage_pct=0.05, events: Optional[list]=None) -> list[SmcSignal]`. `base` = `{coin: 1m-frame}`; `outcome_frame` = het 1m-frame van de coin voor `resolve`.

- [ ] **Step 1: Schrijf de falende tests**

`tests/replay/test_smc_engine.py` (deterministisch en snel; geen echte data nodig):

```python
import unittest
from unittest import mock

import pandas as pd

from app import repo
from app.replay import smc_engine
from app.replay.smc_engine import SmcBook


def upsert(book, **kw):
    args = dict(coin="ETH", direction="short", zone_low=100.0, zone_high=102.0, structure_level=110.0,
                sweep_price=111.0, liquidity_target=90.0, atr=2.0, seen_until="2026-01-01T10:15:00+00:00",
                now_iso="2026-01-01T10:15:00+00:00")
    args.update(kw)
    return book.upsert(**args)


class SmcBookTest(unittest.TestCase):
    def test_same_event_updates_zone_and_target_only(self):
        book = SmcBook()
        a = upsert(book)
        b = upsert(book, zone_low=100.5, zone_high=102.5, liquidity_target=88.0, seen_until="2026-01-01T10:30:00+00:00")
        self.assertEqual(a, b)
        row = book.forming("ETH")[0]
        self.assertEqual((row["zone_low"], row["zone_high"], row["liquidity_target"], row["updated_at"]),
                         (100.5, 102.5, 88.0, "2026-01-01T10:30:00+00:00"))

    def test_zone_within_dedup_pct_updates_existing_row_including_levels(self):
        book = SmcBook()
        a = upsert(book)
        b = upsert(book, structure_level=111.0, sweep_price=112.0, zone_low=100.1, zone_high=102.1)
        self.assertEqual(a, b)
        self.assertEqual(book.forming("ETH")[0]["sweep_price"], 112.0)

    def test_far_zone_creates_new_row(self):
        book = SmcBook()
        a = upsert(book)
        b = upsert(book, structure_level=120.0, sweep_price=121.0, zone_low=110.0, zone_high=112.0)
        self.assertNotEqual(a, b)
        self.assertEqual(len(book.forming("ETH")), 2)

    def test_completed_or_invalidated_same_event_is_returned_but_not_forming(self):
        book = SmcBook()
        a = upsert(book)
        book.invalidate(a, "doorbraak", "2026-01-01T11:00:00+00:00")
        self.assertEqual(upsert(book), a)
        self.assertEqual(book.forming("ETH"), [])

    def test_dedup_pct_is_the_live_constant(self):
        self.assertEqual(smc_engine.ZONE_DEDUP_PCT, repo.ZONE_DEDUP_PCT)


if __name__ == "__main__":
    unittest.main()
```

Voeg in dezelfde file scripted-engine tests toe die `smc_engine.smc_eval.find_candidate`, `judge_forming_setup` en `evaluate_completion` met `mock.patch.object` laten teruggeven wat de test voorschrijft (scripted `SmcScan`/`SmcCompletion` objecten) op een kleine synthetische 1m-basis (2 dagen), met `step=pd.Timedelta(minutes=15)`:
  (a) een kandidaat wordt `setup_gebouwd` en daarna bij `"rejected"` + geslaagde completion een `SmcSignal` met de gescripte entry/stop/take, en de setup is `complete`;
  (b) `"rejected"` + `SmcCompletion(None, "entry_slechter_dan_sniper")` levert `afgewezen_geen_signaal` en de setup blijft bouwend (zelfde gedrag als live);
  (c) `"passed"` laat de setup `setup_doorbroken` worden en gaat door naar fase 2;
  (d) een nieuwe breuk in de andere richting laat een bestaande setup `setup_tegenrichting` worden;
  (e) een setup ouder dan `SMC_SETUP_MAX_AGE_HOURS` wordt `setup_vervallen`;
  (f) fase 1 geeft bij de eerste `"rejected"` terug zonder de overige setups te beoordelen (live: `return existing_setup`).
Elke test asserteert de uitkomst-waarden (aantal events per `kind`, velden van het signaal), niet alleen dat er niets crasht.

`tests/test_smc_equivalence.py`: hergebruik `run_live_sequence`-opzet uit `tests/test_smc_golden.py` (importeer `COIN, START, END, STEP, FrozenClock, FrozenDatetime`) en draai ook `smc_engine.replay_smc` over dezelfde basis en tijdstippen. Vergelijk:

```python
class EquivalenceTest(unittest.TestCase):
    def test_replay_matches_live_pipeline(self):
        live = run_live_sequence()          # uit tests.test_smc_golden
        base = {COIN: make_smc_prone_1m(days=12, seed=5, start_price=2600.0)}
        events = []
        replay = smc_engine.replay_smc(COIN, base, base[COIN], START, END, step=STEP, events=events)
        live_signals = [(s["direction"], round(s["price"], 6), round(s["stop_loss"], 6), round(s["take_profit"], 6),
                         s["created_at"]) for s in live["signals"]]
        replay_signals = [(s.direction, round(s.entry, 6), round(s.stop, 6), round(s.take, 6), s.at.isoformat())
                          for s in replay]
        self.assertEqual(replay_signals, live_signals)
        live_setups = [(r["direction"], r["zone_low"], r["zone_high"], r["sweep_price"], r["created_at"],
                        r["invalidated_at"] is not None, r["signal_id"] is not None) for r in live["setups"]]
        replay_setups = [(r["direction"], round(r["zone_low"], 6), round(r["zone_high"], 6), round(r["sweep_price"], 6),
                          r["created_at"], r["invalidated_at"] is not None, r["signal_id"] is not None)
                         for r in engine_setups]
        self.assertEqual(replay_setups, live_setups)
```

(`engine_setups` is `smc_engine.last_book.all_setups()`; geef `replay_smc` daarvoor het modulevariabele `last_book` of een optionele parameter `book_out: Optional[list]`. Kies één van de twee en gebruik die consistent.) De equivalentietest is de kern van het vertrouwen: verschilt het raam van live op deze synthetische periode, dan is het raam fout, niet de test.

- [ ] **Step 2: Draai de tests, verwacht falen**

Run: `/tmp/claude-0/venv/bin/python -m unittest tests.replay.test_smc_engine -v`
Expected: `ImportError: cannot import name 'smc_engine' from 'app.replay'`

- [ ] **Step 3: Schrijf `app/replay/smc_engine.py`**

```python
"""Afspeel-engine voor SMC-setups: bootst market_scanner._run_smc_check na op een
1m-basis, met de setups in het geheugen (SmcBook, gelijk aan de smc_setups-tabel
en repo.upsert_smc_setup) in plaats van in de database. De beslislogica komt
uit app/smc_eval.py, dezelfde code als live. Niet nagebootst: pushmeldingen,
journal-fan-out en de structurele tegenstrijdigheid-onderdrukking van scan_market."""
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import pandas as pd

from app import smc_eval
from app.replay.candles import BASE_DELTAS
from app.replay.outcome import Outcome, resolve
from app.replay.view import ReplayData

ONE_MINUTE = BASE_DELTAS["1m"]
# Zelfde waarde en betekenis als repo.ZONE_DEDUP_PCT; een test bewaakt dat ze gelijk blijven.
ZONE_DEDUP_PCT = 0.3


class SmcBook:
    """In-memory spiegel van de smc_setups-tabel."""

    def __init__(self):
        self._rows: list[dict] = []
        self._next_id = 1

    def upsert(self, coin, direction, zone_low, zone_high, structure_level, sweep_price,
               liquidity_target, atr, seen_until, now_iso) -> int:
        zone_mid = (zone_low + zone_high) / 2
        same_event = next((r for r in reversed(self._rows)
                           if r["coin"] == coin and r["direction"] == direction
                           and r["structure_level"] == structure_level and r["sweep_price"] == sweep_price), None)
        if same_event is not None:
            if same_event["signal_id"] is None and same_event["invalidated_at"] is None:
                same_event.update(zone_low=zone_low, zone_high=zone_high,
                                  liquidity_target=liquidity_target, updated_at=seen_until)
            return same_event["id"]
        for row in self.forming(coin):
            if row["direction"] != direction:
                continue
            existing_mid = (row["zone_low"] + row["zone_high"]) / 2
            if existing_mid and abs(existing_mid - zone_mid) <= ZONE_DEDUP_PCT / 100 * zone_mid:
                row.update(zone_low=zone_low, zone_high=zone_high, structure_level=structure_level,
                           sweep_price=sweep_price, liquidity_target=liquidity_target, atr=atr, updated_at=seen_until)
                return row["id"]
        row = {"id": self._next_id, "coin": coin, "direction": direction, "zone_low": zone_low,
               "zone_high": zone_high, "structure_level": structure_level, "sweep_price": sweep_price,
               "liquidity_target": liquidity_target, "atr": atr, "alert_sent": 0, "signal_id": None,
               "created_at": now_iso, "updated_at": seen_until, "invalidated_at": None, "ended_because": None}
        self._next_id += 1
        self._rows.append(row)
        return row["id"]

    def forming(self, coin: Optional[str] = None) -> list[dict]:
        rows = [r for r in self._rows if r["signal_id"] is None and r["invalidated_at"] is None
                and (coin is None or r["coin"] == coin)]
        return sorted(rows, key=lambda r: r["updated_at"], reverse=True)

    def invalidate(self, setup_id: int, why: str, at_iso: str) -> None:
        for r in self._rows:
            if r["id"] == setup_id:
                r["invalidated_at"], r["ended_because"] = at_iso, why

    def complete(self, setup_id: int, signal_index: int) -> None:
        for r in self._rows:
            if r["id"] == setup_id:
                r["signal_id"] = signal_index

    def all_setups(self) -> list[dict]:
        return [dict(r) for r in self._rows]


@dataclass
class SmcSignal:
    coin: str
    direction: str
    at: pd.Timestamp
    entry: float
    stop: float
    take: float
    setup_id: int
    outcome: Optional[Outcome]
    sniper_price: Optional[float] = None


@dataclass
class SmcFunnelEvent:
    at: pd.Timestamp
    coin: str
    direction: Optional[str]
    kind: str
    detail: str = ""


last_book: Optional[SmcBook] = None


def _emit(events, t, coin, direction, kind, detail=""):
    if events is not None:
        events.append(SmcFunnelEvent(t, coin, direction, kind, detail))


def _check_cycle(coin, data, book, t, events):
    """Spiegel van market_scanner._check_smc_setup. Geeft de afgewezen setup (dict) of None."""
    df_15m = data.fetch_ohlcv(coin, timeframe="15m")
    closed_15m = df_15m.iloc[:-1]
    last_candle = closed_15m.iloc[-1]
    now = t.to_pydatetime()
    now_iso = t.isoformat()

    existing = book.forming(coin)
    for existing_setup in existing:
        if smc_eval.setup_expired(existing_setup, now):
            book.invalidate(existing_setup["id"], "vervallen", now_iso)
            _emit(events, t, coin, existing_setup["direction"], "setup_vervallen")
            continue
        verdict = smc_eval.judge_forming_setup(existing_setup, closed_15m)
        if verdict == "rejected":
            return existing_setup
        if verdict == "passed":
            book.invalidate(existing_setup["id"], "doorbraak", now_iso)
            _emit(events, t, coin, existing_setup["direction"], "setup_doorbroken")
            break

    df_30m = data.fetch_ohlcv(coin, timeframe="30m", limit=smc_eval.SMC_ZONE_SEARCH_LOOKBACK_30M + 1)
    closed_30m = df_30m.iloc[:-1]
    scan = smc_eval.find_candidate(closed_30m, df_30m, closed_15m, last_candle)
    if scan.break_direction is None:
        _emit(events, t, coin, None, scan.skip_reason)
        return None
    for existing_setup in existing:
        if existing_setup["direction"] != scan.break_direction and existing_setup["invalidated_at"] is None:
            book.invalidate(existing_setup["id"], "tegenrichting", now_iso)
            _emit(events, t, coin, existing_setup["direction"], "setup_tegenrichting")
    if scan.candidate is None:
        _emit(events, t, coin, scan.break_direction, scan.skip_reason, scan.detail)
        return None
    c = scan.candidate
    known = {r["id"] for r in book.all_setups()}
    seen_until = (last_candle["timestamp"] + timedelta(minutes=smc_eval.SMC_ENTRY_CANDLE_MINUTES)).isoformat()
    setup_id = book.upsert(coin, c.direction, c.zone_low, c.zone_high, c.structure_level, c.sweep_price,
                           c.liquidity_target, c.atr, seen_until, now_iso)
    if setup_id not in known:
        _emit(events, t, coin, c.direction, "setup_gebouwd")
    setup = next((s for s in book.forming(coin) if s["id"] == setup_id), None)
    if setup is None:
        return None
    _, rejected, _ = smc_eval.last_candle_state(last_candle, c.zone_low, c.zone_high, c.direction)
    if rejected:
        return setup
    return None


def replay_smc(
    coin: str, base: dict, outcome_frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp,
    step: pd.Timedelta = pd.Timedelta(minutes=5), max_age: pd.Timedelta = pd.Timedelta(days=2),
    fee_pct: float = 0.1, slippage_pct: float = 0.05, events: Optional[list] = None,
) -> list[SmcSignal]:
    global last_book
    book = SmcBook()
    last_book = book
    signals: list[SmcSignal] = []
    t = start
    while t <= end:
        data = ReplayData(base, t, base_delta=ONE_MINUTE)
        if len(data.fetch_ohlcv(coin, timeframe="30m", limit=smc_eval.SMC_ZONE_SEARCH_LOOKBACK_30M + 1)) >= \
                smc_eval.SMC_ZONE_SEARCH_LOOKBACK_30M + 1:
            setup = _check_cycle(coin, data, book, t, events)
            if setup is not None:
                df_15m = data.fetch_ohlcv(coin, timeframe="15m")
                completion = smc_eval.evaluate_completion(setup, df_15m)
                if completion.signal is None:
                    _emit(events, t, coin, setup["direction"], "afgewezen_geen_signaal", completion.reject_reason)
                else:
                    d = completion.signal
                    outcome = resolve(setup["direction"], d.entry_price, d.stop_loss, d.take_profit,
                                      outcome_frame, t, max_age, fee_pct, slippage_pct)
                    signals.append(SmcSignal(coin, setup["direction"], t, d.entry_price, d.stop_loss, d.take_profit,
                                             setup["id"], outcome, d.sniper_entry_price))
                    book.complete(setup["id"], len(signals))
                    _emit(events, t, coin, setup["direction"], "signaal")
        t += step
    return signals
```

Controleer bij het schrijven tegen de live code dat `_check_cycle` dezelfde volgorde heeft: (1) fase 1 over de bestaande setups (verlopen → `continue`, `rejected` → return, `passed` → ongeldig + `break`), (2) pas daarna fase 2; `existing` is de lijst van vóór fase 1 (ook zijn net ongeldig gemaakte rijen, dus de `invalidated_at is None`-controle voorkomt een dubbele melding in het raam zonder het livegedrag te veranderen: live roept `invalidate_smc_setup` ook op al ongeldige rijen aan, zonder effect).

- [ ] **Step 4: Draai de tests, verwacht slagen**

Run: `/tmp/claude-0/venv/bin/python -m unittest tests.replay.test_smc_engine tests.test_smc_equivalence -v`
Expected: `OK`. De equivalentietest draait enkele minuten. Faalt hij, dan wijkt de engine af van live: zoek het verschil (eerste afwijkende signaal of setup) en herstel de engine, nooit de test.

- [ ] **Step 5: Commit**

```bash
git add app/replay/smc_engine.py tests/replay/test_smc_engine.py tests/test_smc_equivalence.py
git commit -m "Meetraam: SMC-afspeel-engine met setups in het geheugen, gelijk aan live"
```

---

### Task 4: SMC-rapport (trechter, prestaties, snelheid, kosten)

**Files:**
- Create: `app/replay/smc_report.py`
- Test: `tests/replay/test_smc_report.py`

**Interfaces:**
- Consumes: `SmcSignal`, `SmcFunnelEvent`, `SmcBook.all_setups()` (Task 3).
- Produces: `funnel_summary(setups: list[dict], events: list[SmcFunnelEvent]) -> dict` met `gebouwd`, `signaal`, `vervallen`, `doorbroken`, `tegenrichting`, `nog_bouwend`, `afgewezen_geen_signaal` (per reject_reason) en `skip` (per skip_reason);
  `performance(signals: list[SmcSignal]) -> dict` met `n, take_profit, stop_loss, expired, winrate, expectancy_net, expectancy_gross, median_minutes, p90_minutes, share_within_60m, breakeven_cost_pct, avg_cost_r`;
  `format_smc_report(signals, setups, events, notes=()) -> str` (Nederlands, per coin, per kwartaal en train/test zoals het day_trading-rapport).
  `breakeven_cost_pct` = hoogste fee+slippage per kant (in procent van de entry) waarbij de gemiddelde R na kosten nog op nul staat: `mean(r_gross) / mean(2 * entry / risk / 100)`, `None` bij nul trades of een niet-positief gemiddelde.

- [ ] **Step 1: Schrijf de falende test**

`tests/replay/test_smc_report.py`:

```python
import unittest

import pandas as pd

from app.replay import smc_report
from app.replay.outcome import Outcome
from app.replay.smc_engine import SmcFunnelEvent, SmcSignal


def sig(at, result, r_net, r_gross, minutes, entry=100.0, stop=99.0, coin="ETH"):
    t0 = pd.Timestamp(at, tz="UTC")
    exit_at = t0 + pd.Timedelta(minutes=minutes)
    return SmcSignal(coin, "long", t0, entry, stop, 102.0, 1, Outcome(result, exit_at, 100.0, r_gross, r_net))


class PerformanceTest(unittest.TestCase):
    def test_basic_stats_and_speed(self):
        signals = [sig("2026-01-01 10:00", "take_profit", 1.7, 2.0, 20), sig("2026-01-02 10:00", "stop_loss", -1.3, -1.0, 90),
                   sig("2026-01-03 10:00", "stop_loss", -1.3, -1.0, 30), sig("2026-01-04 10:00", "expired", 0.1, 0.3, 2880)]
        p = smc_report.performance(signals)
        self.assertEqual((p["n"], p["take_profit"], p["stop_loss"], p["expired"]), (4, 1, 2, 1))
        self.assertAlmostEqual(p["winrate"], 1 / 3)
        self.assertAlmostEqual(p["expectancy_gross"], (2.0 - 1.0 - 1.0 + 0.3) / 4)
        self.assertEqual(p["median_minutes"], 60.0)
        self.assertAlmostEqual(p["share_within_60m"], 2 / 4)

    def test_breakeven_cost(self):
        # gemiddelde bruto R 0,1, kosten per 1% per kant = 2 * 100/1/100 = 2R per 1% => 0,05% per kant
        signals = [sig("2026-01-01 10:00", "take_profit", 0.0, 1.1, 10), sig("2026-01-02 10:00", "stop_loss", 0.0, -0.9, 10)]
        p = smc_report.performance(signals)
        self.assertAlmostEqual(p["breakeven_cost_pct"], 0.1 / 2.0, places=6)

    def test_none_without_trades_or_edge(self):
        self.assertIsNone(smc_report.performance([])["breakeven_cost_pct"])
        losing = [sig("2026-01-01 10:00", "stop_loss", -1.3, -1.0, 10)]
        self.assertIsNone(smc_report.performance(losing)["breakeven_cost_pct"])


class FunnelTest(unittest.TestCase):
    def test_counts_by_end_state_and_reasons(self):
        setups = [
            {"id": 1, "signal_id": 1, "invalidated_at": None, "ended_because": None},
            {"id": 2, "signal_id": None, "invalidated_at": "x", "ended_because": "vervallen"},
            {"id": 3, "signal_id": None, "invalidated_at": "x", "ended_because": "doorbraak"},
            {"id": 4, "signal_id": None, "invalidated_at": "x", "ended_because": "tegenrichting"},
            {"id": 5, "signal_id": None, "invalidated_at": None, "ended_because": None},
        ]
        t = pd.Timestamp("2026-01-01", tz="UTC")
        events = [SmcFunnelEvent(t, "ETH", "long", "geen_sweep"), SmcFunnelEvent(t, "ETH", "long", "geen_sweep"),
                  SmcFunnelEvent(t, "ETH", "long", "afgewezen_geen_signaal", "entry_slechter_dan_sniper")]
        f = smc_report.funnel_summary(setups, events)
        self.assertEqual((f["gebouwd"], f["signaal"], f["vervallen"], f["doorbroken"], f["tegenrichting"], f["nog_bouwend"]),
                         (5, 1, 1, 1, 1, 1))
        self.assertEqual(f["skip"], {"geen_sweep": 2})
        self.assertEqual(f["afgewezen_geen_signaal"], {"entry_slechter_dan_sniper": 1})


class FormatTest(unittest.TestCase):
    def test_report_mentions_sections(self):
        signals = [sig("2026-01-01 10:00", "take_profit", 1.7, 2.0, 20), sig("2026-06-01 10:00", "stop_loss", -1.3, -1.0, 30)]
        text = smc_report.format_smc_report(signals, [], [], notes=("pushmeldingen niet nagebootst",))
        for needle in ("Trechter", "Prestaties", "snelheid", "train", "test", "ETH", "pushmeldingen niet nagebootst"):
            self.assertIn(needle, text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Draai de test, verwacht falen**

Run: `/tmp/claude-0/venv/bin/python -m unittest tests.replay.test_smc_report -v`
Expected: `ImportError: cannot import name 'smc_report'`

- [ ] **Step 3: Schrijf `app/replay/smc_report.py`**

```python
"""Rapport voor het SMC-meetraam: waarom lopen setups dood (trechter), wat leveren
signalen op in R, hoe snel eindigen ze (minuten) en hoe hoog mogen de kosten zijn
voor de strategie nog wint."""
from collections import Counter
from typing import Optional

import pandas as pd

from app.replay.smc_engine import SmcFunnelEvent, SmcSignal

SKIP_KINDS = ("geen_structuurbreuk", "geen_sweep", "geen_confluentiezone", "geen_liquiditeitsdoel",
              "stop_of_doel_binnen_zone", "koers_al_in_zone")


def funnel_summary(setups: list[dict], events: list[SmcFunnelEvent]) -> dict:
    ended = Counter(s["ended_because"] for s in setups if s["invalidated_at"] is not None)
    skip = Counter(e.kind for e in events if e.kind in SKIP_KINDS)
    rejected = Counter(e.detail for e in events if e.kind == "afgewezen_geen_signaal")
    return {
        "gebouwd": len(setups),
        "signaal": sum(1 for s in setups if s["signal_id"] is not None),
        "vervallen": ended.get("vervallen", 0),
        "doorbroken": ended.get("doorbraak", 0),
        "tegenrichting": ended.get("tegenrichting", 0),
        "nog_bouwend": sum(1 for s in setups if s["signal_id"] is None and s["invalidated_at"] is None),
        "skip": dict(skip),
        "afgewezen_geen_signaal": dict(rejected),
    }


def performance(signals: list[SmcSignal]) -> dict:
    rows = [s for s in signals if s.outcome is not None]
    n = len(rows)
    tp = sum(1 for s in rows if s.outcome.result == "take_profit")
    sl = sum(1 for s in rows if s.outcome.result == "stop_loss")
    minutes = pd.Series([(s.outcome.exit_at - s.at).total_seconds() / 60 for s in rows], dtype=float)
    gross = pd.Series([s.outcome.r_gross for s in rows], dtype=float)
    net = pd.Series([s.outcome.r_net for s in rows], dtype=float)
    cost_per_pct = pd.Series([2 * s.entry / abs(s.entry - s.stop) / 100 for s in rows], dtype=float)
    breakeven: Optional[float] = None
    if n and gross.mean() > 0:
        breakeven = float(gross.mean() / cost_per_pct.mean())
    return {
        "n": n, "take_profit": tp, "stop_loss": sl, "expired": n - tp - sl,
        "winrate": tp / (tp + sl) if tp + sl else None,
        "expectancy_net": float(net.mean()) if n else None,
        "expectancy_gross": float(gross.mean()) if n else None,
        "median_minutes": float(minutes.median()) if n else None,
        "p90_minutes": float(minutes.quantile(0.9)) if n else None,
        "share_within_60m": float((minutes <= 60).mean()) if n else None,
        "avg_cost_r": float((gross - net).mean()) if n else None,
        "breakeven_cost_pct": breakeven,
    }


def _line(label: str, p: dict) -> str:
    wr = f"{p['winrate'] * 100:.0f}%" if p["winrate"] is not None else "-"
    net = f"{p['expectancy_net']:+.2f}R" if p["expectancy_net"] is not None else "-"
    gross = f"{p['expectancy_gross']:+.2f}R" if p["expectancy_gross"] is not None else "-"
    med = f"{p['median_minutes']:.0f} min" if p["median_minutes"] is not None else "-"
    return (f"{label:<12} n={p['n']:<4} TP={p['take_profit']:<3} SL={p['stop_loss']:<3} verlopen={p['expired']:<3} "
            f"winrate={wr:<5} netto={net:<8} bruto={gross:<8} mediaan {med}")


def format_smc_report(signals: list[SmcSignal], setups: list[dict], events: list[SmcFunnelEvent],
                      train_fraction: float = 0.7, notes: tuple[str, ...] = ()) -> str:
    out = ["Trechter (setups)"]
    f = funnel_summary(setups, events)
    out.append(f"gebouwd={f['gebouwd']}  signaal={f['signaal']}  vervallen={f['vervallen']}  doorbroken={f['doorbroken']}  "
               f"tegenrichting={f['tegenrichting']}  nog bouwend={f['nog_bouwend']}")
    if f["afgewezen_geen_signaal"]:
        out.append("afgewezen bij afwijzing, geen signaal: " + ", ".join(f"{k}={v}" for k, v in f["afgewezen_geen_signaal"].items()))
    if f["skip"]:
        out.append("geen setup gebouwd, per reden (aantal stappen): " + ", ".join(f"{k}={v}" for k, v in f["skip"].items()))

    rows = [s for s in signals if s.outcome is not None]
    out.append("\nPrestaties")
    p = performance(rows)
    out.append(_line("alles", p))
    if not rows:
        return "\n".join(out + ["Geen signalen met uitkomst in deze run."] + [f"\nBeperking: {n}" for n in notes])

    frame = pd.DataFrame({"coin": [s.coin for s in rows], "at": [s.at for s in rows]})
    for coin in sorted(frame["coin"].unique()):
        out.append(_line(coin, performance([s for s in rows if s.coin == coin])))

    out.append("\nPer kwartaal")
    quarters = sorted({s.at.tz_convert(None).to_period("Q") for s in rows})
    for q in quarters:
        out.append(_line(str(q), performance([s for s in rows if s.at.tz_convert(None).to_period("Q") == q])))

    first, last = frame["at"].min(), frame["at"].max()
    cutoff = first + (last - first) * train_fraction
    out.append(f"\nTrain en test (splitsing op {cutoff:%Y-%m-%d}, {train_fraction:.0%} train)")
    out.append(_line("train", performance([s for s in rows if s.at <= cutoff])))
    out.append(_line("test", performance([s for s in rows if s.at > cutoff])))

    out.append("\nSnelheid en kosten")
    out.append(f"mediaan {p['median_minutes']:.0f} min, 90e percentiel {p['p90_minutes']:.0f} min, "
               f"{p['share_within_60m'] * 100:.0f}% binnen 60 minuten klaar")
    out.append(f"gemiddelde kosten per trade: {p['avg_cost_r']:.2f}R (met de ingestelde fee en slippage)")
    if p["breakeven_cost_pct"] is not None:
        out.append(f"break-even: de strategie wint nog bij hoogstens {p['breakeven_cost_pct']:.3f}% kosten per kant (fee plus spread plus slippage)")
    else:
        out.append("break-even: geen positieve verwachting voor kosten, dus geen kostenruimte")
    for note in notes:
        out.append(f"\nBeperking: {note}")
    return "\n".join(out)
```

- [ ] **Step 4: Draai de test, verwacht slagen**

Run: `/tmp/claude-0/venv/bin/python -m unittest tests.replay.test_smc_report -v`
Expected: `OK`

- [ ] **Step 5: Commit**

```bash
git add app/replay/smc_report.py tests/replay/test_smc_report.py
git commit -m "Meetraam: SMC-rapport met trechter, snelheid en break-even kosten"
```

---

### Task 5: Runner en vergelijking met de echte SMC-signalen

**Files:**
- Create: `scripts/replay_smc_report.py`, `scripts/replay_smc_compare_live.py`

**Interfaces:**
- Consumes: `candles.ensure_candles(coin, years, timeframe="1m")`, `smc_engine.replay_smc`, `smc_report.format_smc_report`.

- [ ] **Step 1: Schrijf `scripts/replay_smc_report.py`**

Opbouw (zelfde stijl als `scripts/replay_report.py`; kopieer de argument-, pool- en CSV-opzet en pas aan):
- Opties: `--coins` (standaard `config.FIXED_COINS`), `--months 12`, `--step-minutes 5`, `--offset-minutes 3`, `--years-download 1.1`, `--refresh`, `--workers 2`, `--fee-pct 0.1`, `--slippage-pct 0.05`, `--max-age-hours 48`.
- Per coin: `candles.ensure_candles(coin, years, timeframe="1m")` (download kan enkele minuten per coin duren; druk `flush=True` voortgangsregels af zodat een `nohup`-run niet leeg lijkt: `print(..., flush=True)` bij elke gedownloade coin en bij elke afgeronde coin).
- `end = laatste candle - 1 dag`, `start = end - 30 dagen * months`, uitgelijnd op `offset-minutes` (eerste stap op de eerstvolgende hele 5 minuten plus offset).
- Per coin een job in een `ProcessPoolExecutor`; geef elke job alleen `{coin: frame}` mee; elke job geeft `(signals, setups, events)` terug (`smc_engine.last_book.all_setups()` binnen de job uitlezen).
- Combineer en druk `smc_report.format_smc_report(...)` af met `NOTES`: pushmeldingen en journal niet nagebootst; de structurele tegenstrijdigheid-onderdrukking van `scan_market` niet nagebootst; entry is de laatste 1m-close op het scanmoment, uitkomsten op 1m-candles met stop-eerst bij gelijke candle; kosten volgens de opties.
- Sla de signalen op in `data/replay/smc_<datum>_<HHMM>_<months>m.csv` met kolommen `coin, direction, at, entry, stop, take, result, minutes, r_net, r_gross`.

- [ ] **Step 2: Schrijf `scripts/replay_smc_compare_live.py`**

Controle van het raam tegen de echte SMC-signalen (alleen lezen):
- Opties: `--since`, `--until` (exclusief, ISO-datum of `YYYY-MM-DDTHH:MM`), `--coins`, `--refresh`.
- Dezelfde bewaking als `scripts/replay_compare_live.py`: DB-bestand moet bestaan (`DATABASE_PATH`-hint), `signals`-tabel moet bestaan, de 1m-cache moet tot `--until` lopen (anders stoppen met de `--refresh`-hint, zonder oordeel).
- Live signalen: `SELECT id, coin, direction, created_at, price, stop_loss, take_profit FROM signals WHERE trade_type = 'smc' AND is_practice = 0 AND created_at >= ? AND created_at < ?`.
- Speel `replay_smc` af over dezelfde periode voor elke betrokken coin, stap 5 minuten met offset 3.
- Een live signaal geldt als TERUGGEVONDEN als er een replay-signaal is met dezelfde coin en richting binnen 15 minuten, en de stop van het replay-signaal binnen 0,5% van de live stop ligt.
- Druk af: aantal live signalen, terug in replay, aantal replay-signalen zonder live signaal, en per niet-teruggevonden live signaal het id, de coin, de richting en het tijdstip. Criterium: minstens 70% teruggevonden. Bij nul live signalen: `GEEN LIVE SIGNALEN, niet te beoordelen` zonder verdict.

- [ ] **Step 3: Controleer dat beide scripts laden en op synthetische data werken**

Run: `/tmp/claude-0/venv/bin/python scripts/replay_smc_report.py --help` en `/tmp/claude-0/venv/bin/python scripts/replay_smc_compare_live.py --help`
Expected: optielijst zonder traceback.

Schrijf een weggooi-smoketest in de scratchpad (niet committen) die `candles.ensure_candles` mockt met `make_smc_prone_1m`, een scratch-database met één `smc`-signaal vult, en `main()` van het compare-script draait (stale cache, geen live signalen, normaal pad) en `replay_smc_report.main()` met `--workers 1 --months 0.3` op de synthetische data. Beide moeten zonder fout een rapport of verdict afdrukken.

- [ ] **Step 4: Commit**

```bash
git add scripts/replay_smc_report.py scripts/replay_smc_compare_live.py
git commit -m "Meetraam: SMC-runner en vergelijking met de echte SMC-signalen"
```

---

### Task 6: Documentatie en controle op de VPS

**Files:**
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: README en CLAUDE.md**

README, in de sectie "Meetraam (replay)": voeg toe hoe je het SMC-raam draait (`scripts/replay_smc_report.py --months 12`, eerste keer downloadt hij 1m-candles, reken op ongeveer 1 uur voor 7 coins met `--workers 2`, gebruik `nohup ... > bestand &` en `-u` of de ingebouwde `flush`), en de vergelijking met `scripts/replay_smc_compare_live.py` met het `DATABASE_PATH`-voorbeeld. CLAUDE.md (Engels): één zin dat `app/smc_eval.py` de SMC-beslislogica bevat die live en het raam delen en dat `tests/test_smc_golden.py` en `tests/test_smc_equivalence.py` die bewaken.

- [ ] **Step 2: Draai de volledige testset en push**

Run: `/tmp/claude-0/venv/bin/python -m unittest discover -s tests -t . 2>&1 | tail -4`
Expected: alle tests `OK`.

```bash
git add README.md CLAUDE.md
git commit -m "Docs: SMC-meetraam"
git push -u origin claude/crypto-day-trading-alerts-geb2v7
```

- [ ] **Step 3: Controle op de VPS (door de gebruiker)**

```
cd /opt/crypto-alerts && git fetch origin claude/crypto-day-trading-alerts-geb2v7 && cd /opt/crypto-alerts-dev && git checkout --detach origin/claude/crypto-day-trading-alerts-geb2v7
/opt/crypto-alerts/.venv/bin/python3 -m unittest discover -s tests -t . 2>&1 | tail -4
DATABASE_PATH=/opt/crypto-alerts/data/trading.db /opt/crypto-alerts/.venv/bin/python3 scripts/replay_smc_compare_live.py --since 2026-09-01 --until 2026-10-04T10:00 --refresh
nohup /opt/crypto-alerts/.venv/bin/python3 -u scripts/replay_smc_report.py --months 12 --workers 2 > /tmp/smc12.txt 2>&1 &
```

Beslismoment: het raam is pas bruikbaar als `replay_smc_compare_live.py` `GESLAAGD` meldt (minstens 70% van de live SMC-signalen komt terug, nu 8 stuks sinds het begin). Bij `NIET GESLAAGD` zoeken we het verschil per signaal voordat we iets uit de 12-maandsrun concluderen.

---

## Self-review tegen de spec en de afspraken

- **SMC afspelen op 15m/30m met uitkomst per minuut:** Task 1 (1m-basis) en Task 3 (`replay_smc` met `outcome_frame` in 1m).
- **Waarom 82% doodloopt:** `funnel_summary` (Task 4) telt per eindtoestand (vervallen, doorbroken, tegenrichting, nog bouwend, afgewezen zonder signaal per reden) en per skip-reden.
- **Snelle trades (minuten):** `performance` toont mediaan, 90e percentiel en aandeel binnen 60 minuten.
- **Kosten zijn instelbaar en zichtbaar:** rapport toont gemiddelde kosten in R en de break-even kosten per kant; geen aannames over het account van de gebruiker (risico per trade en limieten zijn bewust niet gemodelleerd).
- **Zelfde code als live:** Task 2 (pure functies, sequentie-golden vooraf) en de equivalentietest in Task 3 die engine en live pijplijn op dezelfde data vergelijkt.
- **Controle tegen echte signalen:** Task 5, criterium 70% van de live `smc`-signalen terug (nu 8 live signalen: klein, het rapport zegt dat).
- **Buiten dit plan:** verbeteringen testen (stopmarge, `ZONE_BREAK_BUFFER`, MIN R:R, sniper-eis aan of uit, setup-leeftijd, hogere-timeframe-filter, sessietijden, take-varianten) en nieuwe coins volgen als eigen plan zodra dit raam bewezen klopt.
- **Type-consistentie:** `SmcScan`, `SmcCandidate`, `SmcCompletion`, `SmcSignalDraft` (Task 2) worden in Task 3 met dezelfde veldnamen gebruikt; `SmcSignal`, `SmcFunnelEvent`, `SmcBook` (Task 3) in Task 4 en 5; `ReplayData(..., base_delta=...)` en `ensure_candles(..., timeframe=...)` (Task 1) in Task 2, 3 en 5.
- **Bekende risico's:** de sequentie-golden en de equivalentietest zijn traag (enkele minuten); `make_smc_prone_1m` moet genoeg setups, afwijzingen en ongeldigverklaringen opleveren (Task 2, Step 1 controleert dat). Een live-afwijking die alleen op echte data voorkomt, vangt de VPS-controle in Task 6 op.
