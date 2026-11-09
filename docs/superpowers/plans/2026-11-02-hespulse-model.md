# HesPulse-model Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking. (Deze keer zelf gebouwd, inline.)

**Goal:** Het HesPulse-model uit hoofdstuk 25 (context 4u, pools 1u, sweep/shift/FVG 15m) als live motor met één tab op Kansen, één luide melding bij "entry beschikbaar", stille meting van V1, en de andere focus-motoren stil (`MODEL_ONLY_ALERTS`).

**Architecture:** `app/model.py` is zuiver: uit gesloten 4u/1u/15m-candles en POC-niveaus rekent `scenarios()` per range het hele scenario met elk tijdstip van herkenbaarheid; doordat een scenario alleen afhangt van candles vanaf zijn range, kan de live motor elke 15 minuten opnieuw rekenen en alleen nieuwe stappen opslaan (`app/model_live.py`, tabel `model_scenarios`). Een entry wordt bij de vulling een gewoon signaal `hespulse_model`; `level_check` beslist doel/stop. Weergave via `app/model_view.py` (kaart in twee momenten) en `app/model_chart.py` (SVG); meting via `app/model_measure.py` (vulbaar, N_eff, drawdown, zonder beste 5%, trechter, V1).

**Tech Stack:** Python 3, pandas/numpy, SQLite (`app/schema.sql` + `db._migrate`), FastAPI/Jinja2, stdlib `unittest`, Playwright voor screenshots.

**Spec:** `docs/onderzoek/hespulse-model/preregistratie.md` (bindend, met "Besluiten CEO 2026-11-02" bovenaan) en `tests/hespulse_model/test_bouwstenen.py`.

## Global Constraints

- Alleen gesloten candles via `app/exchange.fetch_ohlcv` (live via `range_sweep_live.fetch_bars`); candle bekend op `timestamp + tf`.
- Elk gegeven met `known_at`; geen lookahead (prefix-toets); geen dubbeltelling (één scenario per (coin, range-id), één entry per scenario, een pool één keer).
- Constanten uit de spec, vooraf vast, nooit afstellen: k = 2/3/2, bias 60 candles 4u, pools 120 candles 1u en 0,1 ATR(1u), sweep 0,1 / 6 / 2,5 ATR(15m), shift 24 candles, displacement 5 candles en 1,0 ATR, stop 0,25 ATR met `floor_stop` 0,4%, afstand 6%, entry 24 candles 15m geldig, V1-stop 1,0 ATR(1u).
- Geen R:R-eis (besluit 4); R:R alleen getoond.
- `HESPULSE_MODEL_ENABLED` standaard true; `MODEL_ONLY_ALERTS` standaard gelijk aan die vlag. Tests buiten de modeltests draaien met beide uit (`tests/__init__.py`).
- Oude bouwstenen niet wijzigen; golden tests en `test_focus_gates` groen.
- Gebruikerstekst Nederlands, "ongetest", geen tijdfilter, geen A/B/C.

---

### Task 1: Zuivere detectie `app/model.py`

**Files:** Create `app/model.py`; Test `tests/hespulse_model/test_model.py`.

**Interfaces (produces):**
- `pivot_flags(values, k) -> np.ndarray` (hergebruikt `trendlab._pivot_flags`).
- `breaks(b4h) -> list[dict]` met `i, direction ('long'|'short'), level, swing, known_at, label ('BOS'|'CHOCH'|None)`.
- `context_at(b4h, evs, T) -> Optional[dict]` met `range_id, direction, L, H, EQ, b_at, known_at` of None (neutraal).
- `pools_at(b1h, b15, rng, T) -> list[dict]` met `level, known_at, key` (gespiegeld voor short via `_mirror`).
- `scenarios(coin, b4h, b1h, b15, pocs, now) -> list[dict]`: per scenario `range_id, direction, status, discovered_at, pool0, candidates, steps` en bij een entry `limit, stop, take, rr, zone_low, zone_high, ob_overlap, poc_samenval, target_kind, shift_label, entry_at`, plus `v1` (limiet, stop, doel op moment A).
- `walk_fill(direction, limit, take, published_at, expires_at, b5) -> (state, at, door_limiet)`.

Short = long op gespiegelde candles (`_mirror`: high' = −low, enz.), zodat het spiegelbeeld per definitie klopt.

- [ ] Tests per stap (positief en negatief) met synthetische candles: pivots (gelijke lows tellen één keer), breuk op het slot (lont is geen breuk, een swing breekt één keer), bias neutraal na 60 candles en bij slot onder L, pool alleen onaangeraakt en tussen L en EQ, gelijke lows één pool, sweep met slot strikt boven P binnen 6 candles, run bij > 2,5 ATR of geen herstel, shift boven de top vóór de prik binnen 24 candles, displacement + FVG, laagste ongevulde FVG, overlap met OB, limiet = bovenkant, stop met `floor_stop`, doel = dichtste van H en naakte POC, discount-eis, één scenario per range, mirror (short).
- [ ] Geen lookahead: `scenarios` op afgekapte candles == op alle candles beperkt tot stappen met `known_at <= cut`.
- [ ] Run test → FAIL; implementeer; run → PASS; commit.

### Task 2: Opslag en configuratie

**Files:** Modify `app/schema.sql`, `app/db.py` (`_migrate`), `app/repo.py`, `app/config.py`, `.env.example`, `tests/__init__.py`, `app/focus.py`, `app/end_reason.py`, `app/track_record.py` (TYPE_LABELS).

- Tabel `model_scenarios` (UNIQUE coin, range_id): status, richting, stappen-JSON, tijdstempels `discovered_at, sweep_at, shift_at, entry_at, detected_at (A), entry_detected_at (B), filled_at, ended_at`, limiet/stop/doel/R:R/zone, kenmerken, `entry_state` (`wacht`, `gevuld`, `vervallen`, `weggelopen`, `context_weg`, `niet_vulbaar`), `signal_id`, `alert_sent`, `vulbaar`, `door_limiet`, `candle_market`.
- Tabel `model_v1` (één rij per scenario): limiet, stop, doel, uitkomst gemeten stil.
- `config.HESPULSE_MODEL_ENABLED` (true), `MODEL_ONLY_ALERTS` (standaard = model aan); `focus.model_only()`; `focus.FOCUS_TYPES += 'hespulse_model'`.
- [ ] Tests: migratie idempotent, insert/update, end_reason heeft tekst voor elke stand, focus bevat het model.

### Task 3: Live motor `app/model_live.py` in `scan_smc_fast`

- Elke 15 minuten per coin: candles ophalen (4u 200, 1u 1000, 15m 1000 via `rsl.fetch_bars`, POC uit `poc_levels`), `model.scenarios`, synchroniseren: nieuwe stappen opslaan, nooit overschrijven; entry beschikbaar → `send_kans_push` (luid, bundel, budget) één keer (`alert_sent`); scenario ontdekt → geen push.
- Elke cyclus `track`: wachtende entries op 5m → vulling (`signals`-rij `hespulse_model`, journaal, `send_new_card` stil) of verval.
- V1 stil in `model_v1`: vulling en uitkomst op 5m.
- [ ] Tests met gemockte `fetch_bars`/push: ontdekt geen push, entry luid binnen budget, vulling stil, geen dubbele melding bij een tweede cyclus.

### Task 4: Oude soorten stil met `MODEL_ONLY_ALERTS`

- Gate in `push_notify.send_new_card` en `send_kans_push` via een `trade_type`-argument? Nee: gate in de motoren (`structure_live`, `zone_radar_live`, `zone_sweep_live`, `poc_radar_live`) met `focus.alerts_on(trade_type)` vóór elke push; geen rij op `/meldingen`.
- [ ] Tests: per motor geen push en geen notificatie als `MODEL_ONLY_ALERTS` aan staat; zonder model blijft het gedrag.

### Task 5: Kansen-tab, kaart en grafiek

- `app/model_view.py`: `radar_setup(row)` (entry → `radar.setup_card`, sleutel `model:<id>`), `scenario_item(row, price)` (moment A: wat er nog moet gebeuren, stappen met tijd).
- `kansen.page(..., model_scenarios=)`: groep `scenarios` in de tab `hespulse_model` (label "HesPulse"), `_kansen_kinds` met model-only alleen het model; open trades van oude soorten houden hun tab.
- `app/model_chart.py`: kaart-SVG (`setup_chart.zone_svg`) en de volle SVG voor `model_kaarten.py`; route `/api/kaart_svg/model:N`.
- [ ] Tests: model-tab voor een leerling, alleen model-tab plus Open van oude soorten, twee momenten op één kaart.

### Task 6: Meting, Bewijs, nachtexport, script, docs

- `app/model_measure.py`: vulbaar na publicatie, N_eff, langste verliesreeks, drawdown en 95e percentiel bij 2000 herschikkingen, gemiddelde zonder beste 5%, helften, trechter, V1 − H met `cluster_bootstrap_diff` op 98,75% (`stats` krijgt een `level`-parameter met 0,95 als standaard).
- Bewijs: eigen rij via `track_record`; modelblok met meting en (alleen CEO) vergelijkingen.
- Nachtexport: sectie `model`.
- `scripts/model_kaarten.py`: 14 dagen, alle coins, eerste 30 scenario's als HTML in `data/model_kaarten.html`.
- CLAUDE.md, README.
- [ ] Volledige suite met `SKIP_SLOW_TESTS=1`, screenshots 375px, commit, push.
