# HesPulse onderzoek en proefmotor Implementation Plan

> Let op: de proefmotor heet `app/rule_live.py`, omdat `app/trend_live.py` al bestond (een oudere, andere motor). Waar hieronder `trend_live` staat, is `rule_live` bedoeld.

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Een strenger swing-lab bouwen, de beste kandidaat als proefmotor voor de CEO laten lopen en per regel eerlijk laten zien of hij "In proef", "Bewezen" of "Negatief" is.

**Architecture:** Het lab (`app/replay/trendlab.py`, `scripts/strategy_lab.py`) krijgt strengere statistiek en vooraf vastgelegde swing-families. De uitkomst per regel staat in een nieuwe tabel `rule_status`. Een proefmotor (`app/rule_live.py`) maakt signalen met `trade_type = 'don55_trend'` voor alleen de CEO; trailing trades slaan hun echte R op in `trade_results`, die `track_record.signal_r` voorrang geeft. Bewijs toont de status per regel.

**Tech Stack:** Python 3.11, pandas, SQLite, FastAPI, Jinja2, stdlib unittest.

**Spec:** `docs/superpowers/specs/2026-10-09-hespulse-visie-en-plan-design.md`

## Global Constraints

- Dagbudget voor nieuwe kansen: standaard 6 pushes per 24 uur, 0 zet het uit (spec sectie 5).
- Conflictregel blijft 6 uur (`push_policy.CONFLICT_HOURS`).
- Kosten per rondreis in het lab: onder 0,1% (`config.TRACK_RECORD_COST_PCT` blijft de standaard, `--kosten` overschrijft).
- Promotie naar "Bewezen" vraagt alle drie (spec sectie 6): lab met minstens 500 trades, beide helften positief, marge per week boven 0 en duidelijke marge boven willekeurige instappen; minstens 50 afgeronde live trades met netto gemiddelde van 0 of hoger; bewaking over de laatste 100 live trades.
- Een regel zet zichzelf uit na 30 negatieve afgeronde trades (spec sectie 5).
- Geen afstelling op de data: elke variant staat in code voor de toets en het aantal varianten staat in de uitvoer (spec sectie 4).
- Geen werkwijze, geen Claude en geen methode op openbare pagina's.
- Bewijs telt alleen `take_profit` en `stop_loss` mee in winrate en R; een trailing trade telt mee met zijn opgeslagen R. Oefentrades (`is_practice = 1`) tellen nooit mee.
- Schemawijzigingen in `app/schema.sql` én `db._migrate()`; nieuwe tabellen in plaats van nieuwe `signals`-kolommen.
- Commentaar legt het waarom uit, geen verhalend commentaar. Bestaande code volgen.
- Voor elke taak: `SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .` moet groen blijven. Raak `app/setup_eval.py` en `app/smc_eval.py` niet aan.

## Bestandsoverzicht

| Bestand | Verantwoordelijkheid |
|---|---|
| `app/push_policy.py`, `web/templates/account.html` | Dagbudget standaard 6 |
| `app/replay/stats.py` (nieuw) | Bootstrap per cluster (week) |
| `app/replay/trendlab.py` | Strengere `evaluate`, swing-families, `htf_trend` |
| `scripts/strategy_lab.py` | Overlevingscontrole, aantal varianten, `--opslaan` |
| `app/schema.sql`, `app/db.py`, `app/repo.py` | Tabellen `rule_status` en `trade_results` |
| `app/track_record.py` | R-override, regelstatus |
| `app/rule_live.py` (nieuw) | Proefmotor 4u trend: signaal en meelopende stop |
| `app/level_check.py`, `main.py` | Proefmotor in de scan-cyclus |
| `web/main.py`, `web/templates/bewijs.html` | Status per regel op Bewijs |
| `app/misser.py` (nieuw), `scripts/misser_check.py` | CEO-handtrades uit CSV |
| `CLAUDE.md` | Korte sectie "Lab en proefmotor" |

---

### Task 1: Dagbudget standaard 6

**Files:**
- Modify: `app/push_policy.py:11`
- Modify: `web/templates/account.html:211`
- Test: `tests/test_push_policy.py:25-30`

**Interfaces:**
- Produces: `push_policy.DEFAULT_BUDGET == 6`.

- [ ] **Step 1: Pas de test aan (faalt eerst)**

Vervang in `tests/test_push_policy.py` de test `test_daily_budget_defaults_to_twelve_and_zero_switches_it_off`:

```python
    def test_daily_budget_defaults_to_six_and_zero_switches_it_off(self):
        many = [push(f"C{i}", "long", 3) for i in range(6)]
        self.assertFalse(push_policy.decide(many, "NEW", "long", None, NOW)[0])
        self.assertTrue(push_policy.decide(many[:5], "NEW", "long", None, NOW)[0])
        self.assertTrue(push_policy.decide(many, "NEW", "long", 20, NOW)[0])
        self.assertTrue(push_policy.decide(many, "NEW", "long", 0, NOW)[0])
```

- [ ] **Step 2: Draai de test**

Run: `python3 -m unittest tests.test_push_policy -v`
Expected: FAIL (`assertFalse` slaagt niet bij 6 pushes met standaard 12).

- [ ] **Step 3: Implementatie**

`app/push_policy.py`: `DEFAULT_BUDGET = 6`. `web/templates/account.html`: `placeholder="standaard 6"`. Zoek met `grep -rn "12" web/templates/account.html web/templates/uitleg.html` of tekst over "12 pushes" staat; pas die tekst aan naar 6.

- [ ] **Step 4: Draai de test**

Run: `python3 -m unittest tests.test_push_policy -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/push_policy.py web/templates tests/test_push_policy.py
git commit -m "Dagbudget voor nieuwe kansen standaard 6"
```

---

### Task 2: Bootstrap per week (clusters)

**Files:**
- Create: `app/replay/stats.py`
- Test: `tests/replay/test_stats.py`

**Interfaces:**
- Produces: `stats.cluster_bootstrap_mean(values: list[float], clusters: list, seed: int = 7, n_boot: int = 2000) -> tuple[float, float]`. Herbemonst hele clusters (bijvoorbeeld ISO-weken) met teruglegging en geeft het 95%-interval van het gemiddelde over alle trades. Eén cluster of lege invoer geeft `(mean, mean)` of `(0.0, 0.0)`.
- Produces: `stats.week_key(ts) -> str` zoals `"2026-W41"` voor een pandas `Timestamp`.

Waarom: alle coins volgen BTC, dus trades in dezelfde week zijn niet onafhankelijk. Een gewone bootstrap geeft een te smalle marge.

- [ ] **Step 1: Schrijf de test**

```python
import unittest

import pandas as pd

from app.replay import stats


class ClusterBootstrapTest(unittest.TestCase):
    def test_empty_and_single_cluster(self):
        self.assertEqual(stats.cluster_bootstrap_mean([], []), (0.0, 0.0))
        lo, hi = stats.cluster_bootstrap_mean([1.0, 3.0], ["a", "a"])
        self.assertEqual((lo, hi), (2.0, 2.0))

    def test_correlated_trades_widen_the_interval(self):
        values = [1.0] * 10 + [-1.0] * 10
        independent = [str(i) for i in range(20)]
        two_weeks = ["w1"] * 10 + ["w2"] * 10
        lo_i, hi_i = stats.cluster_bootstrap_mean(values, independent)
        lo_c, hi_c = stats.cluster_bootstrap_mean(values, two_weeks)
        self.assertGreater(hi_c - lo_c, hi_i - lo_i)

    def test_same_seed_same_answer(self):
        v, c = [0.5, -0.2, 1.1, -1.0], ["a", "a", "b", "c"]
        self.assertEqual(stats.cluster_bootstrap_mean(v, c), stats.cluster_bootstrap_mean(v, c))

    def test_week_key(self):
        self.assertEqual(stats.week_key(pd.Timestamp("2026-10-09", tz="UTC")), "2026-W41")
```

- [ ] **Step 2: Draai (faalt: module bestaat niet)**

Run: `python3 -m unittest tests.replay.test_stats -v`
Expected: FAIL met `ImportError`.

- [ ] **Step 3: Implementatie**

```python
"""Statistiek voor het lab. Trades in dezelfde week hangen samen (alle coins volgen BTC), dus de marge komt uit het herbemonsteren van weken, niet van trades."""
import random
from collections import defaultdict


def week_key(ts) -> str:
    iso = ts.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def cluster_bootstrap_mean(values: list[float], clusters: list, seed: int = 7, n_boot: int = 2000) -> tuple[float, float]:
    """95%-interval van het gemiddelde per trade, herbemonsterd per cluster; vaste seed zodat twee runs hetzelfde zeggen."""
    if not values:
        return 0.0, 0.0
    groups: dict = defaultdict(list)
    for v, c in zip(values, clusters):
        groups[c].append(v)
    keys = list(groups)
    if len(keys) < 2:
        m = sum(values) / len(values)
        return m, m
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        total, count = 0.0, 0
        for _ in keys:
            g = groups[rng.choice(keys)]
            total += sum(g)
            count += len(g)
        means.append(total / count)
    means.sort()
    return means[int(0.025 * n_boot)], means[int(0.975 * n_boot) - 1]
```

- [ ] **Step 4: Draai**

Run: `python3 -m unittest tests.replay.test_stats -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add app/replay/stats.py tests/replay/test_stats.py
git commit -m "Lab: bootstrap per week voor samenhangende trades"
```

---

### Task 3: Strengere `evaluate`

**Files:**
- Modify: `app/replay/trendlab.py:203-227` (`MIN_HALF`, `evaluate`)
- Test: `tests/replay/test_trendlab.py` (bestaat; voeg toe, lees eerst de bestaande helpers)

**Interfaces:**
- Consumes: `stats.cluster_bootstrap_mean`, `stats.week_key` (Task 2).
- Produces: `trendlab.MIN_TRADES = 500`, `trendlab.MIN_PLACEBO_MARGIN = 0.03` (in R per trade), en `evaluate(trades, placebo)` met extra sleutels `week_ci: (lo, hi)` en checks `"genoeg trades"`, `"marge per week boven 0"`, `"duidelijk beter dan willekeurig"`. De sleutels `n`, `avg`, `ci`, `train`, `test`, `placebo`, `passes`, `reason`, `winrate`, `gross`, `best`, `avg_win`, `median_risk_pct` blijven bestaan.

Vooraf vastgelegd: 500 trades en 0,03R marge zijn in de spec en dit plan gekozen vóór de toets.

- [ ] **Step 1: Schrijf de tests**

```python
class EvaluateStrictTest(unittest.TestCase):
    def frame(self, nets, start="2024-01-01", step_hours=4):
        at = pd.date_range(start, periods=len(nets), freq=f"{step_hours}h", tz="UTC")
        return pd.DataFrame({"at": at, "net": nets, "gross": nets, "risk_pct": 5.0})

    def test_too_few_trades_never_pass(self):
        t = self.frame([0.5] * 100)
        out = tl.evaluate(t, self.frame([0.0] * 100))
        self.assertFalse(out["passes"])
        self.assertIn("genoeg trades", out["reason"])

    def test_edge_must_beat_placebo_by_margin(self):
        nets = ([0.3, -0.1] * 300)
        t, close_placebo = self.frame(nets), self.frame([0.29, -0.1] * 300)
        out = tl.evaluate(t, close_placebo)
        self.assertFalse(out["passes"])
        self.assertIn("duidelijk beter dan willekeurig", out["reason"])

    def test_clear_edge_passes(self):
        nets = ([0.3, -0.1] * 300)
        out = tl.evaluate(self.frame(nets), self.frame([0.0, -0.1] * 300))
        self.assertTrue(out["passes"], out["reason"])
        self.assertIn("week_ci", out)
```

- [ ] **Step 2: Draai (faalt)**

Run: `python3 -m unittest tests.replay.test_trendlab -v`
Expected: FAIL (KeyError `week_ci` of passes True bij 100 trades).

- [ ] **Step 3: Implementatie**

In `trendlab.py`: vervang `MIN_HALF = 25` door

```python
MIN_TRADES = 500             # spec sectie 6: minder trades zeggen te weinig over een voordeel van 0,1R
MIN_PLACEBO_MARGIN = 0.03    # R per trade boven willekeurige instappen met dezelfde uitgang
MIN_HALF = MIN_TRADES // 4   # elke helft moet minstens een kwart van het minimum bevatten
```

Pas `evaluate` aan: importeer `from app.replay import stats`; bereken na `lo, hi`:

```python
    wlo, whi = stats.cluster_bootstrap_mean(t["net"].tolist(), [stats.week_key(x) for x in t["at"]])
```

voeg `"week_ci": (wlo, whi)` toe aan `out` en vervang `checks` door:

```python
    checks = {"genoeg trades": len(t) >= MIN_TRADES,
              "eerste helft positief": out["train"][1] is not None and out["train"][1] > 0,
              "tweede helft positief": out["test"][1] is not None and out["test"][1] > 0,
              "marge boven 0": lo > 0,
              "marge per week boven 0": wlo > 0,
              "duidelijk beter dan willekeurig": out["placebo"] is not None and out["avg"] - out["placebo"] >= MIN_PLACEBO_MARGIN}
```

Pas ook de kolomkop van `scripts/strategy_lab.py` niet aan; die volgt in Task 4. Controleer met `grep -rn "MIN_HALF\|genoeg trades per helft" app scripts tests` dat niets anders de oude sleutels gebruikt.

- [ ] **Step 4: Draai**

Run: `python3 -m unittest tests.replay.test_trendlab -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/replay/trendlab.py tests/replay/test_trendlab.py
git commit -m "Lab: strengere toets met weekmarge en duidelijke marge boven willekeurig"
```

---

### Task 4: Overlevingscontrole en variantenteller in het lab

**Files:**
- Modify: `app/replay/trendlab.py` (nieuwe functie `full_history`)
- Modify: `scripts/strategy_lab.py:23-80`
- Test: `tests/replay/test_trendlab.py`

**Interfaces:**
- Produces: `trendlab.full_history(bars_by_coin: dict[str, pd.DataFrame], tolerance_days: int = 7) -> list[str]`. Geeft de coins waarvan de eerste candle binnen `tolerance_days` van de vroegste eerste candle van alle coins ligt.
- Produces: CLI-vlag `--alleen-volledig` (filtert op `full_history` per timeframe) en een regel `"{n} varianten getoetst"` in de uitvoer.

- [ ] **Step 1: Test**

```python
class FullHistoryTest(unittest.TestCase):
    def bars(self, start):
        return pd.DataFrame({"timestamp": pd.date_range(start, periods=10, freq="4h", tz="UTC")})

    def test_keeps_coins_that_cover_the_whole_period(self):
        got = tl.full_history({"BTC": self.bars("2023-01-01"), "ETH": self.bars("2023-01-03"), "NEW": self.bars("2024-06-01")})
        self.assertEqual(sorted(got), ["BTC", "ETH"])
```

- [ ] **Step 2: Draai (faalt: AttributeError)**

Run: `python3 -m unittest tests.replay.test_trendlab.FullHistoryTest -v`

- [ ] **Step 3: Implementatie**

```python
def full_history(bars_by_coin: dict[str, pd.DataFrame], tolerance_days: int = 7) -> list[str]:
    """Overlevingscontrole: coins die later begonnen zijn bestaan nu nog, dus het lab ziet de verdwenen verliezers niet. Alleen coins met de volle periode tellen mee."""
    firsts = {c: b["timestamp"].iloc[0] for c, b in bars_by_coin.items() if len(b)}
    if not firsts:
        return []
    earliest = min(firsts.values())
    return [c for c, ts in firsts.items() if (ts - earliest) <= pd.Timedelta(days=tolerance_days)]
```

In `strategy_lab.py`: voeg `ap.add_argument("--alleen-volledig", action="store_true")` toe. Na het laden van `frames`: als de vlag staat, bepaal per timeframe `keep = tl.full_history({c: tfs[tf] for c, tfs in frames.items() if tf in tfs})` en sla in de variantenlus coins over die niet in `keep[v.timeframe]` staan. Print vóór de tabel `print(f"{len(results)} varianten getoetst; bij zoveel toetsen is een toevallige treffer normaal.")` en vervang de bestaande slotregel die "tien toetsen" noemt door een tekst die `len(results)` gebruikt.

- [ ] **Step 4: Draai**

Run: `python3 -m unittest tests.replay.test_trendlab -v && python3 scripts/strategy_lab.py --help`
Expected: PASS en de help toont `--alleen-volledig`.

- [ ] **Step 5: Commit**

```bash
git add app/replay/trendlab.py scripts/strategy_lab.py tests/replay/test_trendlab.py
git commit -m "Lab: overlevingscontrole en variantenteller"
```

---

### Task 5: Swing-families op 1 uur met trendfilter van 4 uur

**Files:**
- Modify: `app/replay/trendlab.py` (Variant, VARIANTS, nieuwe signaalfuncties, `_trade`)
- Modify: `scripts/strategy_lab.py` (4u-frames beschikbaar maken voor de 1u-varianten)
- Test: `tests/replay/test_trendlab.py`

**Interfaces:**
- Produces: `Variant` met extra velden `k_stop: float = TRAIL_K_STOP`, `k_trail: float = TRAIL_K`, `max_bars: Optional[int] = None`, `htf: bool = False`.
- Produces: `trendlab.htf_trend(b1h: pd.DataFrame, b4h: pd.DataFrame) -> np.ndarray` met per 1u-candle +1, -1 of 0 (EMA50 boven/onder EMA200 op de laatste *gesloten* 4u-candle).
- Produces: nieuwe families `swing_pullback`, `swing_donchian`, `swing_squeeze`; de signaalfuncties krijgen `htf: np.ndarray`.
- Produces: `run_variant(v, bars, cost_pct=0.06, htf_bars=None)` en `placebo_variant` ongewijzigd qua handtekening behalve dezelfde optionele `htf_bars`.

Vooraf vastgelegde varianten (vier, geen afstelling):

| Naam | Family | Params | Stop | Meelopende stop | Max duur |
|---|---|---|---|---|---|
| SW_TREND_1H | swing_donchian | (48,) | 1,5 ATR | 2,5 ATR | 48 candles (2 dagen) |
| SW_PULL_1H | swing_pullback | (21,) | 1,5 ATR | 2,5 ATR | 48 |
| SW_DON_1H | swing_donchian | (24,) | 1,5 ATR | 2,0 ATR | 36 |
| SW_SQUEEZE_1H | swing_squeeze | (12,) | 1,5 ATR | 2,0 ATR | 36 |

De trendregel (SW_TREND_1H) is stap 1 uit de spec: de 4u-trend inkorten naar 1 uur. Alle vier eisen dat `htf_trend` dezelfde kant op wijst als het signaal. Squeeze: Bollinger-breedte (20, 2) van de candle ligt in het laagste kwintiel van de laatste 100 candles, en de candle sluit voorbij het hoogste hoog of laagste laag van de vorige 12.

- [ ] **Step 1: Tests**

```python
class SwingTest(unittest.TestCase):
    def test_htf_trend_uses_only_closed_4h_candles(self):
        ts4 = pd.date_range("2024-01-01", periods=300, freq="4h", tz="UTC")
        close4 = pd.Series(range(300), dtype=float) + 100        # stijgend: EMA50 > EMA200
        b4 = pd.DataFrame({"timestamp": ts4, "open": close4, "high": close4, "low": close4, "close": close4, "volume": 1.0})
        ts1 = pd.date_range("2024-01-01", periods=1200, freq="1h", tz="UTC")
        b1 = pd.DataFrame({"timestamp": ts1})
        trend = tl.htf_trend(b1, b4)
        self.assertEqual(len(trend), 1200)
        self.assertEqual(int(trend[0]), 0)                       # nog geen gesloten 4u-candle met een trend
        self.assertEqual(int(trend[-1]), 1)

    def test_htf_trend_does_not_look_ahead_inside_a_4h_candle(self):
        ts4 = pd.date_range("2024-01-01", periods=300, freq="4h", tz="UTC")
        up = pd.Series([100.0] * 150 + [200.0] * 150)
        b4 = pd.DataFrame({"timestamp": ts4, "open": up, "high": up, "low": up, "close": up, "volume": 1.0})
        ts1 = pd.date_range("2024-01-01", periods=1200, freq="1h", tz="UTC")
        trend = tl.htf_trend(pd.DataFrame({"timestamp": ts1}), b4)
        # de 4u-candle die om 600:00 begint sluit pas om 604:00; een 1u-candle daarbinnen mag haar niet kennen
        i_open = int((ts4[150] - ts1[0]) / pd.Timedelta(hours=1))
        self.assertEqual(trend[i_open], trend[i_open - 1])

    def test_variant_count_and_names_are_fixed(self):
        names = [v.name for v in tl.VARIANTS]
        for n in ("SW_TREND_1H", "SW_PULL_1H", "SW_DON_1H", "SW_SQUEEZE_1H"):
            self.assertIn(n, names)
        self.assertEqual(len(names), 14)
```

- [ ] **Step 2: Draai (faalt)**

Run: `python3 -m unittest tests.replay.test_trendlab.SwingTest -v`
Expected: FAIL (`htf_trend` bestaat niet).

- [ ] **Step 3: Implementatie**

Breid `Variant` uit met de vier velden (defaults houden de bestaande varianten gelijk). Voeg toe aan `VARIANTS`:

```python
    Variant("SW_TREND_1H", "swing_donchian", "1h", (48,), 1.5, 2.5, 48, True),
    Variant("SW_PULL_1H", "swing_pullback", "1h", (21,), 1.5, 2.5, 48, True),
    Variant("SW_DON_1H", "swing_donchian", "1h", (24,), 1.5, 2.0, 36, True),
    Variant("SW_SQUEEZE_1H", "swing_squeeze", "1h", (12,), 1.5, 2.0, 36, True),
```

`htf_trend`: bereken op `b4h` de EMA50 en EMA200 van `close`, trend = +1 als EMA50 > EMA200, -1 als kleiner, 0 voor de eerste 200 candles; zet de beschikbaarheidstijd op `timestamp + 4h` (sluitmoment) en koppel met `pd.merge_asof(b1h[["timestamp"]], frame.rename(columns={"avail": "timestamp"}), on="timestamp")`, vul `NaN` met 0. Geef `.to_numpy().astype(int)` terug.

Signaalfuncties: `swing_donchian_signals(b, n, htf)` is `donchian_signals(b, n, False)` gefilterd op `htf[i] == sign`; `swing_pullback_signals(b, x, htf)` is `pullback_signals(b, x)` gefilterd op `htf[i] == sign` (let op: `pullback_signals` gebruikt zelf EMA50/EMA200 van de 1u-reeks als trend; voor de swing-variant vervang je die voorwaarde door `htf`, dus schrijf de aanraakvoorwaarde apart: long als `low <= ema` en `close > ema`, short omgekeerd, gefilterd op `htf`); `swing_squeeze_signals(b, n, htf)` volgens de definitie hierboven. Alle drie slaan `i < WARMUP` over zoals de bestaande functies.

`signals_for(v, b, htf)` en `run_variant(..., htf_bars=None)`: bereken `htf = htf_trend(b, prepare(htf_bars))` als `v.htf` en `htf_bars` ontbreekt niet (anders `ValueError`). In `_trade`: voor families die met `swing_` beginnen gebruik `v.k_stop` voor de eerste stop en `v.k_trail` voor `exit_trail`, en kap af op `v.max_bars` (sluit dan op de close van die candle met outcome `"time"`; schrijf dit in `exit_trail` als optionele parameter `max_bars=None`, zonder gedrag voor bestaande aanroepen te veranderen). `busy_until` geldt ook voor de swing-families (één positie tegelijk per coin).

In `strategy_lab.py`: geef `frames[coin]["4h"]` mee als `htf_bars` aan `run_variant` en `placebo_variant`.

- [ ] **Step 4: Draai alles in het lab en de golden tests**

Run: `SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t . 2>&1 | tail -5`
Expected: alle tests groen.

- [ ] **Step 5: Commit**

```bash
git add app/replay/trendlab.py scripts/strategy_lab.py tests/replay/test_trendlab.py
git commit -m "Lab: vier swing-varianten op 1u met 4u-trendfilter"
```

**Daarna (door Ramon op de VPS):** `python3 scripts/strategy_lab.py --jaren 3 --alleen-volledig`. De uitkomst bepaalt welke regel Task 8 als proefmotor krijgt. Slaagt er geen swing-variant, dan blijft DON55_TREND (4u) de kandidaat als hij de strengere toets haalt; slaagt niets, dan sla Task 8 over en rapporteer "geen kandidaat" (spec sectie 9).

---

### Task 6: Labuitkomst per regel opslaan

**Files:**
- Modify: `app/schema.sql`, `app/db.py` (`_migrate` niet nodig voor een nieuwe tabel; `CREATE TABLE IF NOT EXISTS` volstaat)
- Modify: `app/repo.py`
- Modify: `scripts/strategy_lab.py` (`--opslaan`)
- Test: `tests/test_rule_status.py`

**Interfaces:**
- Produces tabel:
  ```sql
  CREATE TABLE IF NOT EXISTS rule_status (
      rule TEXT PRIMARY KEY,
      lab_passes INTEGER NOT NULL DEFAULT 0,
      lab_json TEXT,
      lab_at TEXT
  );
  ```
- Produces: `repo.set_rule_lab(rule: str, passes: bool, summary: dict, now: str) -> None` en `repo.get_rule_lab(rule: str) -> Optional[dict]` met sleutels `rule, lab_passes (bool), summary (dict), lab_at`; `repo.list_rule_labs() -> list[dict]`.
- Produces: `trade_type`-naam per labvariant: de regel heet in de database gelijk aan de `Variant.name` in kleine letters (`don55_trend`).

- [ ] **Step 1: Test** (gebruik de bestaande `DbCase` uit `tests/test_push_policy.py` als voorbeeld voor een scratch-database)

```python
class RuleLabTest(DbCase):
    def test_roundtrip_and_overwrite(self):
        repo.set_rule_lab("don55_trend", True, {"n": 812, "avg": 0.09}, "2026-10-10T10:00:00+00:00")
        got = repo.get_rule_lab("don55_trend")
        self.assertTrue(got["lab_passes"])
        self.assertEqual(got["summary"]["n"], 812)
        repo.set_rule_lab("don55_trend", False, {"n": 900, "avg": -0.01}, "2026-10-11T10:00:00+00:00")
        self.assertFalse(repo.get_rule_lab("don55_trend")["lab_passes"])
        self.assertEqual(len(repo.list_rule_labs()), 1)

    def test_unknown_rule_is_none(self):
        self.assertIsNone(repo.get_rule_lab("bestaat_niet"))
```

- [ ] **Step 2: Draai (faalt)**, **Step 3: Implementeer** met `INSERT ... ON CONFLICT(rule) DO UPDATE`, `json.dumps(summary, default=float)`; in `strategy_lab.py` voeg `--opslaan` toe dat per variant `repo.set_rule_lab(v.name.lower(), r["passes"], {k: r[k] for k in ("n","avg","ci","week_ci","train","test","placebo","winrate","gross","median_risk_pct")}, now)` aanroept na `db.init_db()`. Zonder de vlag schrijft het script niets.

- [ ] **Step 4: Draai** `python3 -m unittest tests.test_rule_status -v` → PASS.

- [ ] **Step 5: Commit** `git commit -m "Labuitkomst per regel opslaan"`

---

### Task 7: Echte R voor trailing trades

**Files:**
- Modify: `app/schema.sql` (tabel `trade_results`)
- Modify: `app/repo.py` (`set_trade_result`, queries `list_signals_for_quality_report` en `list_type_results` voegen `r_override` toe via `LEFT JOIN trade_results`)
- Modify: `app/track_record.py:38-44` (`signal_r`)
- Test: `tests/test_track_record.py`

**Interfaces:**
- Produces tabel `trade_results (signal_id INTEGER PRIMARY KEY, r_value REAL NOT NULL, closed_at TEXT NOT NULL)`.
- Produces: `repo.set_trade_result(signal_id: int, r_value: float, closed_at: str) -> None`.
- Produces: `signal_r(row)` geeft `row["r_override"]` terug als die niet `None` is en `auto_outcome` in `("take_profit", "stop_loss")` staat; anders ongewijzigd gedrag.

Waarom: een meelopende stop sluit op een willekeurige R (+2,3 of -0,4). De vaste regel "stop = -1, doel = afstand" past daar niet op. Bewijs telt alleen uitkomsten; de uitkomst van een trailing trade is `take_profit` bij R > 0 en `stop_loss` bij R <= 0, met de echte R in `trade_results`.

- [ ] **Step 1: Test**

```python
    def test_r_override_beats_the_fixed_formula(self):
        row = {"price": 100.0, "stop_loss": 95.0, "take_profit": 120.0, "auto_outcome": "take_profit", "r_override": 2.3}
        self.assertEqual(track_record.signal_r(row), 2.3)
        row["auto_outcome"], row["r_override"] = "stop_loss", -0.4
        self.assertEqual(track_record.signal_r(row), -0.4)

    def test_without_override_nothing_changes(self):
        row = {"price": 100.0, "stop_loss": 95.0, "take_profit": 110.0, "auto_outcome": "take_profit"}
        self.assertEqual(track_record.signal_r(row), 2.0)
```

Plus een repo-test in `tests/test_rule_status.py` (zelfde bestand, tweede klasse) die een signaal invoegt, `set_trade_result` aanroept en controleert dat `list_type_results` de waarde als `r_override` teruggeeft. Gebruik hiervoor de helper waarmee `tests/test_track_record.py` of `tests/test_signal_outcomes.py` signalen aanmaakt.

- [ ] **Step 2-4: Draai (faalt), implementeer, draai (PASS).** `signal_r` krijgt bovenaan: `ov = row.get("r_override"); if ov is not None and row.get("auto_outcome") in ("take_profit", "stop_loss"): return float(ov)`.

- [ ] **Step 5: Commit** `git commit -m "Bewijs: echte R voor trailing trades"`

---

### Task 8: Proefmotor 4u/1u trend voor de CEO

Voorwaarde: Task 5 en de labrun hebben een kandidaat opgeleverd (zie het slot van Task 5). De regelnaam hieronder is `DON55_TREND`; vervang hem door de gekozen variant (`trendlab.VARIANTS` bevat de parameters) en schrijf de keuze in de commitmelding.

**Files:**
- Create: `app/rule_live.py`
- Modify: `main.py` (aanroep in de scan-cyclus naast `market_scanner`)
- Modify: `app/level_check.py` (aanroep `rule_live.update_open`)
- Test: `tests/test_rule_live.py`

**Interfaces:**
- Consumes: `trendlab.prepare`, `trendlab.signals_for`, `trendlab.TRAIL_K_STOP`, `trendlab.TRAIL_K`, `repo.set_trade_result` (Task 7), `repo.get_rule_lab` (Task 6), `push_notify.send_push`.
- Produces:
  - `rule_live.RULE = "don55_trend"` (de `trade_type`-waarde).
  - `rule_live.detect(bars: pd.DataFrame, variant) -> Optional[dict]`: kijkt alleen naar de laatste *gesloten* candle; geeft `{"direction": "long"|"short", "entry": float, "stop": float, "atr": float}` of `None`. Entry is de open van de volgende candle, dus bij detectie gebruikt de motor de slotkoers van de signaalcandle als richtprijs en meldt dat zo.
  - `rule_live.next_stop(direction: str, current_stop: float, bars_since_entry: pd.DataFrame, atr: float, k_trail: float = trendlab.TRAIL_K) -> float`: de meelopende stop gaat alleen in de gunstige richting.
  - `rule_live.close_if_hit(signal: dict, bars_since_entry: pd.DataFrame) -> Optional[tuple[float, str]]`: `(r_value, "stop_loss"|"take_profit")` als de stop geraakt is, anders `None`. R > 0 geeft `take_profit`, anders `stop_loss`.
  - `rule_live.scan(now) -> None`: voor elke labcoin met 4u-candles uit de candle-cache `detect`; maakt een signaal met `trade_type = RULE`, alleen zichtbaar voor de CEO (zie hieronder), en stuurt één push via `send_kans_push` met tag `f"trend-{signal_id}"`.
  - `rule_live.update_open(now) -> None`: voor elk open trendsignaal `next_stop`, bij een nieuwe stop een update-push (via `send_push`, zelfde tag, dus de melding vervangt zichzelf) en bij een geraakte stop `repo.set_trade_result` plus `auto_outcome`.

CEO-only: lees eerst hoe `web/main.py:is_ceo` (regel 53) de CEO bepaalt en hergebruik dat criterium in `rule_live` via een kleine functie in `repo` (bijvoorbeeld `repo.list_ceo_user_ids()`); vind die eerst met `sed -n 50,60p web/main.py`. Maak de journalrij (`journal_entries`) alleen voor die gebruikers aan, zodat leerlingen het signaal niet zien. Het label "In proef" staat al in de UI zolang `rule_status.lab_passes` niet gepromoveerd is (Task 9).

- [ ] **Step 1: Tests** (pure functies, geen netwerk)

```python
class NextStopTest(unittest.TestCase):
    def test_long_stop_only_moves_up(self):
        bars = pd.DataFrame({"high": [110.0, 120.0, 118.0], "low": [105.0, 112.0, 110.0]})
        s = rule_live.next_stop("long", 95.0, bars, atr=2.0, k_trail=3.0)
        self.assertEqual(s, 120.0 - 3 * 2.0)
        self.assertEqual(rule_live.next_stop("long", 130.0, bars, atr=2.0, k_trail=3.0), 130.0)

    def test_short_stop_only_moves_down(self):
        bars = pd.DataFrame({"high": [100.0, 99.0], "low": [90.0, 85.0]})
        self.assertEqual(rule_live.next_stop("short", 110.0, bars, atr=2.0, k_trail=3.0), 85.0 + 6.0)
        self.assertEqual(rule_live.next_stop("short", 80.0, bars, atr=2.0, k_trail=3.0), 80.0)


class CloseIfHitTest(unittest.TestCase):
    def test_long_stopped_out_with_profit_counts_as_take_profit(self):
        sig = {"direction": "long", "price": 100.0, "initial_stop": 95.0, "stop_loss": 108.0}
        bars = pd.DataFrame({"high": [112.0], "low": [107.0]})
        r, outcome = rule_live.close_if_hit(sig, bars)
        self.assertEqual(outcome, "take_profit")
        self.assertAlmostEqual(r, (108.0 - 100.0) / 5.0)

    def test_initial_stop_is_minus_one_r(self):
        sig = {"direction": "long", "price": 100.0, "initial_stop": 95.0, "stop_loss": 95.0}
        r, outcome = rule_live.close_if_hit(sig, pd.DataFrame({"high": [99.0], "low": [94.0]}))
        self.assertEqual((r, outcome), (-1.0, "stop_loss"))

    def test_not_hit_returns_none(self):
        sig = {"direction": "long", "price": 100.0, "initial_stop": 95.0, "stop_loss": 95.0}
        self.assertIsNone(rule_live.close_if_hit(sig, pd.DataFrame({"high": [103.0], "low": [97.0]})))
```

`initial_stop` bewaar je in `trade_results`-onafhankelijke vorm: voeg aan `trade_results` in Task 7 *niet* toe; sla de eerste stop op in de tabel `rule_trades (signal_id PRIMARY KEY, initial_stop REAL, rule TEXT)` die dit task aanmaakt in `schema.sql` en `repo.set_initial_stop/get_initial_stop`. Het signaal-`stop_loss` is de huidige meelopende stop.

Een `detect`-test: bouw synthetische 4u-candles met een uitbraak op de laatste gesloten candle (gebruik `trendlab.prepare` op een opgebouwde reeks van 260 candles, zelfde patroon als bestaande tests in `tests/replay/test_trendlab.py`) en controleer dat `detect` een `long` geeft, en `None` als de uitbraak één candle eerder was.

- [ ] **Step 2-4: Draai (faalt), implementeer, draai (PASS).** Pure functies gebruiken alleen pandas/numpy. `scan` en `update_open` doen I/O en blijven dun; test ze met de `fake_push`-aanpak uit `tests/test_push_policy.py::SendKansPushTest` voor het "één melding per trade"-gedrag (zelfde `tag` bij update).

- [ ] **Step 5: Commit** `git commit -m "Proefmotor voor de CEO met meelopende stop"`

---

### Task 9: Status per regel op Bewijs (proef, bewezen, negatief)

**Files:**
- Modify: `app/track_record.py` (nieuwe functie `rule_status`)
- Modify: `web/main.py` (Bewijs-route), `web/templates/bewijs.html` (of waar `/bewijs` rendert; zoek met `grep -n "bewijs" web/main.py`)
- Test: `tests/test_track_record.py`

**Interfaces:**
- Consumes: `repo.get_rule_lab(rule)` (Task 6), `track_record.signal_r` (Task 7), de lijst afgeronde live trades per `trade_type` uit `repo.list_type_results`.
- Produces: `track_record.rule_status(lab: Optional[dict], live_r_net: list[float]) -> dict` met sleutels `status` (`"In proef" | "Bewezen" | "Negatief"`), `reason` (korte Nederlandse zin), `n_live` (int), `avg_last100` (float of None). `live_r_net` staat op volgorde van afronding, oudste eerst, netto na kosten.

Regels, in deze volgorde:
1. `Negatief` als er minstens 30 afgeronde live trades zijn en het gemiddelde over de laatste 30 onder 0 ligt (spec sectie 5), of als `lab` bestaat met `lab_passes == False`.
2. `Bewezen` als `lab_passes` waar is, `n_live >= 50`, het gemiddelde over alle live trades `>= 0` en (bij minstens 100 live trades) het gemiddelde over de laatste 100 niet onder 0 ligt met een bootstrapmarge (`structure_review.bootstrap_mean(last100)[1] >= 0`, dus de bovengrens van de marge is niet negatief).
3. Anders `In proef`.

Een `Bewezen` regel valt automatisch terug naar `In proef` of `Negatief` bij de volgende berekening als regel 1 of de bewaking uit regel 2 niet meer klopt. Er is geen opgeslagen status; de status volgt elke keer uit de data.

- [ ] **Step 1: Tests**

```python
class RuleStatusTest(unittest.TestCase):
    PASS = {"lab_passes": True}

    def test_new_rule_is_in_proef(self):
        self.assertEqual(track_record.rule_status(self.PASS, [0.1] * 10)["status"], "In proef")
        self.assertEqual(track_record.rule_status(None, [])["status"], "In proef")

    def test_proven_needs_lab_and_fifty_live_trades(self):
        self.assertEqual(track_record.rule_status(self.PASS, [0.1] * 50)["status"], "Bewezen")
        self.assertEqual(track_record.rule_status(self.PASS, [0.1] * 49)["status"], "In proef")
        self.assertEqual(track_record.rule_status(None, [0.1] * 80)["status"], "In proef")

    def test_thirty_losing_trades_make_a_rule_negative(self):
        self.assertEqual(track_record.rule_status(self.PASS, [0.2] * 60 + [-0.5] * 30)["status"], "Negatief")

    def test_failed_lab_is_negative_even_without_live_trades(self):
        self.assertEqual(track_record.rule_status({"lab_passes": False}, [])["status"], "Negatief")

    def test_proven_rule_falls_back_when_last_hundred_turn_clearly_negative(self):
        series = [0.5] * 100 + [-0.2] * 100
        self.assertNotEqual(track_record.rule_status(self.PASS, series)["status"], "Bewezen")
```

- [ ] **Step 2-4: Draai (faalt), implementeer, draai (PASS).** Bewijs-route: per `trade_type` die in `rule_labs` of `list_type_results` voorkomt, haal `lab` en de netto R-lijst (R min `_cost_r`) en toon een kleine statusregel met de bestaande proefbalk/labelstijl. Sluit oefentrades uit zoals de bestaande queries al doen. Voeg een route-test toe in dezelfde stijl als de bestaande `/bewijs`-tests (zoek ze met `grep -rn "bewijs" tests`). Public pages blijven vrij van methode (Global Constraints).

- [ ] **Step 5: Commit** `git commit -m "Bewijs: status per regel met promotie en terugval"`

---

### Task 10: Handtrades van de CEO uit een CSV

Voorwaarde: Ramon levert de lijst (20 tot 30 swings met coin, richting, tijd NL, instap, stop, doel, uitkomst). Zonder lijst blijft deze taak open; de rest van het plan hangt er niet van af.

**Files:**
- Create: `app/misser.py`
- Modify: `scripts/misser_check.py` (nieuwe optie `--csv pad`)
- Test: `tests/test_misser.py`

**Interfaces:**
- Produces: `misser.parse_rows(text: str) -> list[dict]` met velden `coin (str, bijvoorbeeld "BTC"), direction ("long"|"short"), at (aware datetime UTC), entry (float), stop (float), target (float), outcome (str)`. Kolomnamen in de CSV: `coin,richting,tijd,instap,stop,doel,uitkomst`; `tijd` is `YYYY-MM-DD HH:MM` in Europe/Amsterdam; `richting` is `long` of `short`. Een ongeldige rij geeft `ValueError` met het regelnummer.
- Produces: `misser.summarize(results: list[dict]) -> dict` met `n`, `seen` (aantal waar minstens één motor het zag), `by_engine` (dict motor → aantal), `by_blocker` (dict reden → aantal). `results` heeft per rij de sleutels die `scripts/misser_check.py` al per trade berekent; lees het script en hergebruik de bestaande functie die per motor beslist.

Stel drempels af op meerdere missers, niet op één voorbeeld (CLAUDE.md): de samenvatting rapporteert patronen, het script verandert zelf geen drempel.

- [ ] **Step 1: Tests**

```python
class ParseRowsTest(unittest.TestCase):
    def test_valid_rows_become_utc(self):
        rows = misser.parse_rows("coin,richting,tijd,instap,stop,doel,uitkomst\nBTC,long,2026-10-08 14:30,100,95,115,winst\n")
        self.assertEqual(rows[0]["coin"], "BTC")
        self.assertEqual(rows[0]["at"].isoformat(), "2026-10-08T12:30:00+00:00")   # CEST is UTC+2

    def test_bad_direction_names_the_line(self):
        with self.assertRaisesRegex(ValueError, "regel 2"):
            misser.parse_rows("coin,richting,tijd,instap,stop,doel,uitkomst\nBTC,omhoog,2026-10-08 14:30,100,95,115,winst\n")

    def test_summarize_counts_seen_and_blockers(self):
        out = misser.summarize([{"engines": ["structuur"], "blocker": None}, {"engines": [], "blocker": "stop te krap"}, {"engines": [], "blocker": "stop te krap"}])
        self.assertEqual(out["n"], 3)
        self.assertEqual(out["seen"], 1)
        self.assertEqual(out["by_blocker"], {"stop te krap": 2})
```

- [ ] **Step 2-4: Draai (faalt), implementeer, draai (PASS).** Lees `scripts/misser_check.py` eerst volledig; geef `summarize` de sleutels `engines` en `blocker` mee uit het bestaande resultaat per trade, en pas de scriptuitvoer aan zodat `--csv` de samenvatting onderaan print.

- [ ] **Step 5: Commit** `git commit -m "Misser-controle voor een lijst handtrades"`

---

### Task 11: CLAUDE.md bijwerken

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1:** Voeg na de sectie "Marktbrein" een korte sectie toe:

```markdown
**Lab en proefmotor.** `app/replay/trendlab.py` en `scripts/strategy_lab.py` toetsen regels vooraf vastgelegd (aantal varianten staat in de uitvoer, nooit afstellen op de data). `evaluate` eist minstens `MIN_TRADES` trades, beide helften positief, een marge per week boven 0 (`app/replay/stats.py`) en `MIN_PLACEBO_MARGIN` boven willekeurige instappen. De uitkomst per regel staat in `rule_status` (`--opslaan`). `app/trend_live.py` laat de beste kandidaat alleen voor de CEO lopen met een meelopende stop; de echte R staat in `trade_results` en `track_record.signal_r` geeft die voorrang. `track_record.rule_status` leidt "In proef", "Bewezen" of "Negatief" elke keer af uit lab en live data; er is geen opgeslagen status. Spec: `docs/superpowers/specs/2026-10-09-hespulse-visie-en-plan-design.md`.
```

- [ ] **Step 2:** Pas in de bestaande tekst over pushes het dagbudget aan als CLAUDE.md een getal noemt (`grep -n "budget" CLAUDE.md`).

- [ ] **Step 3: Draai alle tests**

Run: `SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .`
Expected: alle tests groen.

- [ ] **Step 4: Commit** `git commit -m "CLAUDE.md: lab en proefmotor"`

---

## Volgorde en fasen

| Fase | Taken | Klaar als |
|---|---|---|
| 1 Onderzoek | 1, 2, 3, 4, 5, daarna labrun op de VPS, 10 zodra de lijst er is | Lijst kandidaten met uitkomst, of de vaststelling dat er geen is |
| 2 Proefmotor | 6, 7, 8 | Trades lopen voor de CEO met één lopende melding per trade |
| 3 Promotie | 9, 11 | Bewijs toont de status per regel |

Taak 1 gaat direct mee in de eerste deploy; die lost de klacht over te veel meldingen het snelst op.

## Zelfreview tegen de spec

- Sectie 4 stap 1 (trend inkorten): Task 5 (`SW_TREND_1H`). Stap 2 (breed lab, strengere statistiek, overlevingsfout): Task 3, 4, 5. Stap 3 (handtrades): Task 10.
- Sectie 5 (meldingen): dagbudget 6 in Task 1; conflictregel, labels en updates bestaan al; "zet zichzelf uit na 30 negatieve trades" en "één lopende melding per trade" in Task 8 en 9.
- Sectie 6 (promotie): lab-criteria in Task 3, live en bewaking in Task 9, proefmotor in Task 8.
- Sectie 7 (niet doen): geen live regel zonder lab-toets, Task 8 vraagt een geslaagde labuitkomst; geen werkwijze op openbare pagina, in Global Constraints.
- Gat dat bewust openstaat: papieren trades naast de live trades (spec sectie 6, fase 2) zijn niet apart ingebouwd. De proefmotor maakt gewone signalen die Bewijs automatisch uitrekent via `auto_outcome`; dat dekt papieren trades zolang de CEO ze niet hoeft te nemen. Wil Ramon er een aparte schakelaar voor, dan volgt dat als eigen taak.
