# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

HesPulse: a crypto day-trading alert system. A user forwards a Discord DM
(text and/or a chart screenshot) from a paid trading community to their own
bot's DM. The system interprets it via the Anthropic API, checks it against
live technical data on Binance, and sends a Telegram alert with a suggested
stop loss and take profit. It never places trades itself — every trade is
a manual decision. Multiple users share the same signal stream but each
has their own login, own settings (quiet hours, confirmation threshold,
required factors), and journal. See
`README.md` for the full product description and VPS deployment steps
(systemd units, HTTPS, backups); it is kept up to date and is the source of
truth for setup — don't duplicate it here.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in tokens; JWT_SECRET must be long and random

python3 scripts/create_user.py        # creates the DB (if needed) + one account
python3 main.py                       # Discord bot + Telegram /start listener + pipeline
uvicorn web.main:app --reload         # dashboard at http://127.0.0.1:8000
```

Apart from the small `tests/` folder described below, verification is done with
throwaway scripts run against a scratch database, e.g.:

```bash
DATABASE_PATH=/tmp/scratch.db python3 -c "from app import db, repo; db.init_db(); ..."
```

`scripts/test_step1_bitcoin.py` exercises the indicator pipeline against
live Binance data in isolation. `scripts/backtest_factors.py --limit 50`
shows the historical pass rate of the optional advanced factors before
turning them on. For UI changes, start `uvicorn` against a scratch DB and
drive it with Playwright — there's no existing template for this in-repo,
build the check from scratch each time.

There is still no pytest and no linter, but a small stdlib `unittest` folder
`tests/` exists (`python3 -m unittest discover -s tests -t . -v`). It covers
the replay engine (`app/replay/`), the shared `app/setup_eval.py` logic
(`tests/test_setup_eval.py`) and two golden tests that guard the live
day-trading pipeline. `app/setup_eval.py` holds the decision logic that live
and the replay share: don't change it without running the golden tests.
Likewise `app/smc_eval.py` holds the SMC decision logic that live and the
replay share, guarded by `tests/test_smc_golden.py` and
`tests/test_smc_equivalence.py` (the latter takes several minutes;
`SKIP_SLOW_TESTS=1` skips it).

## Architecture

**Two independent long-running processes, one shared SQLite database.**
`main.py` runs the Discord bot and the Telegram `/start` listener
concurrently (`asyncio.gather`) and feeds the processing pipeline.
`web/main.py` is a separate FastAPI process serving the dashboard. Both
talk to the same `data/trading.db` (WAL mode, see `app/db.py`) — they are
deployed as separate systemd units (`deploy/crypto-bot.service`,
`deploy/crypto-web.service`) and must be restarted independently after a
deploy.

**Pipeline** (`app/signal_processor.py:handle_message`, called from
`app/discord_bot.py` for every DM): dedupe against a recent identical
message → `app/anthropic_interpret.py` (retried up to 3x on transient
failure, then logged as unclear rather than silently dropped) → for
`day_trading` messages, `app/exchange.py` + `app/indicators.py` pull 4h
candles and compute EMA/MACD/RSI/volume (and optionally ADX/ATR/BTC-trend/
1h-confirmation/divergence/liquidity, gated by `ENABLE_ADVANCED_FACTORS`)
→ `app/risk.py` derives stop loss (1.5x ATR) and take profit (3x ATR) →
fans out to `journal_entries`, one row per user, via `app/repo.py` →
`app/telegram_notify.py` sends each user the same entry/stop/take-profit
alert. `lange_termijn` (long-term) messages are stored but never
alerted on directly; a later day-trading signal for the same coin is
compared against the most recent long-term direction
(`signal_processor._build_context_note`). `repo.find_open_signal` en
`update_signal` laten een signaal met `auto_outcome` altijd met rust: een
nieuw bericht na de uitkomst wordt een vers signaal.

Two periodic jobs run outside this DM-triggered flow, each its own systemd
timer: `app/level_check.py` (every 15 min — has an open position's SL/TP
been hit on the live price, or has price returned near an untaken signal's
level) and `app/heartbeat.py` (daily liveness ping). Both are "fire once
per journal row until reset" — check the existing sent-flag before adding
a new alert path, or you'll spam.
`check_open_trades` toetst alleen candles die na het signaal openden
(`candles_after`, ook in `candles_in_validity`), noemt in de melding het
niveau zelf ("koers raakte X" voor het extreem) en zet `level_alert_sent`
pas na een geslaagde push of na `MAX_LEVEL_ALERT_ATTEMPTS` mislukte;
elke poging staat in `push_attempts`; `check_pending_signals` (terug bij
niveau) doet hetzelfde met soort `level_check.PENDING_ALERT_KIND`. `push_notify.send_push` geeft de
fout terug als geen apparaat de push aannam; `send_kans_push` zet een
mislukte kans dan op de meldingenpagina (de claim `alert_sent` vooraf
blijft). Stop en doel in één candle telt als stop, met
`signals.auto_outcome_note` = `level_check.AMBIGUOUS_NOTE`; Bewijs telt dat per soort (`summarize`'s `ambiguous`) en Logboek en replay
zeggen "Volgorde onbekend" (`logbook.ORDER_UNKNOWN`).
`scan_smc_fast` schrijft hartslag `snelcyclus` (start na het 5m-slot, duur); de timer staat op `*:0/5:20` (gemeten met `*:3/5:00`: start 183 s
na het slot, duur 83 s).

**Meting rond de focus-soorten (alleen meting, geen motor leest het).** Kosten: Bewijs toont per soort bruto, netto en kosten per trade in R
(`summarize`'s `gross_total`/`avg_cost_r`, uitleg `track_record.cost_text` met `TRACK_RECORD_COST_PCT`); het Logboek blijft bruto en zegt dat.
Funding zit in de kosten: `track_record._cost_r` telt de gemeten `funding_r` mee (dus ook live_net_r, curves, uurkaart), `summarize` geeft
`avg_funding_r` ("waarvan funding"), `funding_measured` en `funding_unknown`. Regel in `app/funding.py` (zuiver: momenten strikt na de vulling en
strikt vóór het einde van de uitgangscandle, long betaalt een positieve rate, short ontvangt, over de instapwaarde, naar R met de stopafstand; het
interval komt uit de API), ophalen in `app/outcome_measure.py` (`derivs.funding_between`, timeout 5 s, cache per contract, bij falen status
'onbekend' en `funding_r` NULL, nooit 0), tabel `trade_funding`, alleen focus-soorten; gezet in `level_check.check_signal_outcomes` (einde =
`hit_at` + candlelengte) en `range_sweep_live._measure_exit`; `scripts/funding_check.py` rekent oude trades na, `--opslaan` schrijft. Perps en
spot: `summarize(..., era_types=focus.FOCUS_TYPES)` op Bewijs maakt de hoofdcijfers per focus-soort alleen `candle_market = 'perp'`; de rest
(NULL of 'spot') staat in `older` met `SPOT_ERA_LABEL` "Vóór 1 november (spot-candles)"; het totaal en de andere soorten blijven gemengd.
MAE/MFE: `app/excursion.py` (zuiver; stop in een candle telt als 1R tegen zonder meebeweging, doel telt tot het doel, de vulcandle niet), tabel
`trade_excursions` (mae_r/mfe_r mogen leeg zijn: timeframe 'onbekend'; `_migrate` herbouwt een oude tabel met NOT NULL één keer), gezet in
`level_check.check_signal_outcomes` op dezelfde candles als de uitkomst en zonder doel in `range_sweep_live.follow_trade` bij de referentie-uitgang
via `outcome_measure.record_excursion`: 5m-candles via `exchange.fetch_ohlcv(since=)` van het signaalmoment tot het einde van de uitgangscandle
(hoogstens nu), dezelfde `excursion.measure` met doel None; halen ze de uitgang niet, dan 'onbekend', nooit de lopende meting van `follow_step`.
Tests vervangen de naden `outcome_measure._candles_fetch`/`_funding_get` (in `tests/__init__.py` standaard offline).
Bewijs toont per focus-soort `excursion.line`, `scripts/mae_check.py` rekent alleen-lezen achteraf (`excursion.measure_row`, stops die binnen 24
uur toch het doel haalden); `--opnieuw` meet de trades zonder doel opnieuw zoals live (`repo.reference_exits`, `outcome_measure.exit_end`) en schrijft. Vertraging: `app/latency.py` en tabel `alert_timing` (één rij per verzonden push uit `send_kans_push(..., timing=)`;
geweerde kansen hebben geen rij); de vier focus-motoren geven `latency.timing(soort, "nieuw"|"vulling", candlesluiting, detectie)` mee, ook via
`fanout_confirmed_signal(timing=)`; een vulling in de vormende candle telt vanaf het laatste 5m-slot. `scripts/vertraging.py` toont per soort
mediaan en 90e percentiel. Afsluiten met reden: `app/end_reason.py` is de enige vertaling van een eindstand zonder vulling naar gewone woorden
(`tests/test_basis_afsluiten.py` leest elke stand uit de code en eist een tekst; een nieuwe stand heeft dus een tekst nodig). `repo.list_ended_cards`
voedt `kansen.page(..., ended=)` (rijen onder "Uitgevallen, gemist of vervallen" per tab, met het anker van de kaart) en `logbook.timeline(ended=)`;
"Niet meer actief" en de Structuur-geschiedenis tonen dezelfde tekst.

**HesPulse-model (CEO, 2026-11-02; bindende spec `docs/onderzoek/hespulse-model/preregistratie.md` met "Besluiten CEO 2026-11-02" en het
aanvullend besluit over kenmerken).** Het enige model dat meldt. `app/model.py` (zuiver): context 4u (`Context4h`, bias uit de laatste breuk,
60 candles, range L/H/EQ), pools 1u (`Pools`, onaangeraakt ook op 15m, gelijke lows binnen 0,1 ATR één pool), sweep/shift/displacement/FVG op
15m, limiet op de zone (laagste ongevulde FVG of de overlap met het OB), stop met de 0,4%-vloer (`_floor`, gelijk aan `smc_eval.floor_stop`),
doel de dichtste van de range-rand en een naakte POC, geen R:R-eis; short = long op gespiegelde candles. Alle constanten vooraf vast; nooit
afstellen. `scenarios(frames, now, pocs)` is prefix-vast (een stap verandert nooit met meer candles; `tests/hespulse_model/test_model.py`), dus
`app/model_live.py` rekent elke cyclus opnieuw (in `scan_smc_fast` na de POC-radar, `rsl.fetch_bars` 1000 candles) en bewaart alleen wat nieuw
is in `model_scenarios` (UNIQUE coin, range_id; `repo.sync_model_scenario` raakt een afgerond scenario nooit meer aan; detected_at en
entry_detected_at zijn de momenten van vastleggen). Een scenario dat al voorbij was voordat de motor het zag, komt niet in de app. Moment A
(scenario ontdekt): geen push. Moment B (entry beschikbaar): de ene luide melding (`send_kans_push(kind="entry")`, budget, conflictregel,
bundel "N entries klaar"), niet als de koers al door de limiet stond (`niet_vulbaar`) of het plan omgekeerd is (`model_card.plan_ok`).
`track` vult op 5m na de publicatie (`model.walk_fill`): gevuld een signaal `hespulse_model` (journaal, `chain_it=False`, stil via
`send_new_card`), `level_check` beslist doel/stop; verder `vervallen` (6 uur), `weggelopen`, `context_weg` (`end_reason`). V1 stil in
`model_v1` (`track_v1`). Kaart: `model_card` (moment A `scenario_item` in groep `scenarios` zonder order en buiten de tellers, moment B
`radar_setup` met sleutel `model:N`, anker `radar-model-N`), context/entrytype/status apart (`context_lines`, `face_line`), BTC-context
(`app/btc_context.py`: BTC 4u, Pearson 96/672 op uitgelijnde 15m-log-rendementen, relatieve sterkte 24u; kolom `btc_context` "a"/"b"; alleen
kenmerk, niets leest het), grafiek `card_chart.model_svg` in analistenstijl (rustige candles `--mc-*`, 4u range high/low en evenwicht, zones "15m FVG"/"15m OB" als lichtpaars vlak `--mz` met de naam erin, "1u swing low"/EQL uit de stap `sweep.pool_at`/`pool_n`, sweep, "15m CHoCH", limiet/stop/doel met prijs, labels rechts met `ladder.spread`; alleen uit de opgeslagen rij, de range van de entry uit `entry.range_low/high`; tijdframe `model_tf`: het kleinste waarop swing tot nu in 96 candles past; `tests/test_model_chart_card.py`), `/api/kaart_svg/model:N` met `no-store` (`?groot=1`: dezelfde tekening hoger, "Groot" via `data-kc-big` in `kaarten.js`). Iedereen ziet
het. Meting: `app/model_measure.py` (vulbaar, vertraging, trechter, N_eff, verliesreeks, drawdown met herschikking, zonder beste 5%, 98,75%
per week; V1/V2/V3 alleen CEO) op Bewijs en in de nachtexport (`model`). Controle achteraf: `scripts/model_kaarten.py` (14 dagen, eerste 30,
`app/model_chart.full_svg`, per stap herberekend zonder latere candles). `HESPULSE_MODEL_ENABLED` (standaard true) en `MODEL_ONLY_ALERTS`
(standaard gelijk): met beide aan sturen Structuur, zone-radar, zone-sweep en POC-radar niets (`focus.alerts_on` in hun meldpaden en
`skip_push` op hun fanout), `_kansen_kinds` geeft alleen het model en `_forming_setups` alleen modelkaarten; open trades van oude soorten
houden hun tab. Tests draaien met beide uit (`tests/__init__.py`); de modeltests zetten ze aan: `tests/hespulse_model/`, `test_model_live.py`,
`test_model_only_alerts.py`, `test_model_acceptance.py`, `test_web_model.py`.

**Meldingen: alleen de vulling is luid (CEO, 2026-11-02, "veel te veel meldingen": ~560 nieuwe kaarten en ~255 vullingen in een week).**
Met het HesPulse-model aan (standaard) geldt dit alleen nog voor het model zelf (entry luid, vulling stil, ontdekt niets); de vier soorten
hieronder sturen dan niets (`MODEL_ONLY_ALERTS`).
Een nieuwe kaart van de vier focus-motoren gaat via `push_notify.send_new_card`: een rij op `/meldingen` plus hoogstens een stille push, buiten
het budget en de conflictregel (pauze en volg-set houden de push tegen). Een vulling gaat via `send_kans_push` en `push_policy`: conflictregel
(6 uur), dan het dagbudget `DEFAULT_BUDGET` 8 (`users.push_budget`, Account), waarin elke luide push telt (de oude uitzondering voor dezelfde coin
en richting is teruggedraaid); boven het budget een stille push plus een rij op `/meldingen`, dus een vulling krijgt altijd een melding.
`scan_smc_fast` opent een bundel (`push_notify.open_bundle`, een ContextVar) en sluit hem na de POC-radar en in zijn `finally`
(`close_bundle`): meer vullingen voor één gebruiker in één cyclus worden één push `push_policy.bundle_text` ("3 kansen gevuld", link
`/smc`) die één keer telt (`push_log.counts`: 1 voor de eerste rij, 0 voor de rest; de rijen per coin blijven voor de conflictregel).
Uitkomsten (`level_check`, `send_push`, één keer per journaalregel via `level_alert_sent`) en trade-updates tellen niet mee. Budgetring:
`today.budget_ring` met `push_policy.used`. Tests: `tests/test_meldingen_compact.py`. Een nieuw meldpad voor een nieuwe kaart hoort in
`send_new_card`, niet in `send_kans_push`.

**Multi-tenant model, not multi-tenant data.** `signals`, `messages`, and
`source_levels` are global — every user sees the same signals, computed
once. `journal_entries` is per-user (status, own entry/exit price, notes,
result) and is the only place a user's own decisions live; `users` holds
`telegram_chat_id` per account. `portfolio_eur`/`risk_percent` remain in
the schema but are no longer read or written by active code — position
sizing and portfolio tracking were removed, see the
`docs/superpowers/plans/2026-09-30-positiegrootte-weghalen.md` spec.
`repo.close_journal_trade` only computes and stores `result_pct` (the
plain, direction-aware price move between entry and exit) on close; it no
longer touches any portfolio balance. A practice trade (`is_practice=1`,
created from the dashboard, not from a Discord signal) never counts
toward winrate stats — every query that touches those filters it out
explicitly; a new query that forgets to will quietly pollute a user's
real numbers.

**Database access is centralized in `app/repo.py`** — the bot, the
pipeline, and the web dashboard all go through it, never raw SQL
elsewhere. `app/db.py:session()` is a contextmanager that only commits if
the block completes without raising, so a failure partway through a
multi-statement write rolls back cleanly. Schema changes are two-part:
add the column/table to `app/schema.sql` (for fresh databases, via
`CREATE TABLE IF NOT EXISTS`) *and* add an idempotent `ALTER TABLE ... ADD
COLUMN` guarded by a `PRAGMA table_info` check in `db.py:_migrate()` (for
existing ones) — schema.sql alone never reaches a database that already
has the table. Never add an index in schema.sql for a column that a
migration in `_migrate()` might still need to add on an existing DB;
create such indexes in `_migrate()` itself, after the column exists.

**Web layer**: `web/main.py` is one file with all FastAPI routes;
`web/templates/` are Jinja2 templates extending `base.html`, with shared
fragments factored into `web/templates/_macros.html` (import as `macros`,
e.g. `{{ macros.reason_popup(entry) }}`) rather than copy-pasted across
templates — check there before duplicating a block that appears more than
once. `web/static/dashboard.js` and `coin.js` progressively enhance
server-rendered pages (price/PnL polling, AJAX trade actions, the trendline
drawing tool) rather than the pages being a client-rendered SPA. Session
auth is a JWT in a cookie (`app/security.py`), checked via the
`require_login` FastAPI dependency on every protected route.

**Radar and Bewijs.** `/smc` (nav label "Radar") and `/bewijs` render from pure functions in `app/trade_plan.py`, `app/radar.py` and `app/track_record.py`; keep the maths there, not in templates or `web/main.py`. `/bewijs` must stay honest: only `take_profit`/`stop_loss` outcomes count in winrate and R, expired/open are shown beside them, never dropped silently. SMC alert text comes from `market_scanner.format_smc_body`.

**Kansen en kaarten.** Elke kans die nog niet gevuld is toont dezelfde drie stappen (`app/chance_steps.py`, macro `steps_list`): wacht, zet de limietorder, stop en doel. Gemeten kenmerken per kans (✓/✗ en een score in `pass_pct`) komen uit `app/chance_checks.py`; ze beschrijven de kans en Bewijs toont per soort of een hoge score vaker wint (`track_record.score_split`), neem ze dus nooit als bewezen voorspeller op. Een stop onder `SMC_MIN_STOP_PCT` wordt verbreed met `smc_eval.floor_stop`, nooit geweigerd.

**Rejectie en misser-controle.** `app/replay/rejection.py` (zuivere detector, beide richtingen) en `app/rejection_live.py` melden een afwijzing op een niveau met minstens drie aanrakingen (`trade_type = 'rejectie'`, altijd ongetest, Bewijs toont de score). `scripts/misser_check.py` toetst een trade die jij zag en HesPulse niet meldde: per motor zag hij hem, en zo niet welke regel hem weigerde. Stel drempels af op meerdere missers, niet op één voorbeeld. Met `--csv` leest hij een lijst handtrades (`app/misser.py`); `--alleen-parsen` leest en toont die alleen, zonder beurs. Een kans krijgt altijd een melding zodra de limiet vult.

**Marktbrein.** `/vandaag` (Markt) komt uit `app/today.py` (pure weergavefuncties), `app/market_script.py` (scenario's van Claude met harde toets en
een motor die ze tot gewone signalen maakt, `trade_type = 'script'`), `app/news.py`, `app/liquidations.py` en `app/market_calendar.py`. Alles wat Claude
levert is een hypothese: valideer in code, label ongetest, laat Bewijs de score tonen. Voeg geen getal toe aan Vandaag dat niet gemeten is (zie
`today.MEASURED_VOLATILITY` met de bron in de comment).

**Lab en proefmotor.** `app/replay/trendlab.py` en `scripts/strategy_lab.py` toetsen regels die vooraf vastliggen in `VARIANTS` (20 varianten; vier swing-varianten op 1u met een 4u-trendfilter `htf_trend`, die alleen gesloten 4u-candles gebruikt; zes kanteling-varianten `KANT_*` op 5m, 15m en 1u, paarsgewijs enkele en dubbele conformatie, met een pivot die pas p+n candles later bekend is; `scripts/strategy_lab.py --familie kanteling|standaard|alle` kiest de set en laadt alleen de timeframes die nodig zijn). Het aantal getoetste varianten staat in de uitvoer, en er wordt nooit afgesteld op de data. `evaluate` eist minstens `MIN_TRADES` trades, een gemiddelde netto R boven 0 in beide helften, een marge boven 0 en een marge per week-cluster boven 0 (`app/replay/stats.py`, bootstrap per week), en `MIN_PLACEBO_MARGIN` boven willekeurige instappen met dezelfde uitgang. `--alleen-volledig` is de overlevingscontrole; `--opslaan` schrijft de uitkomst per regel naar de tabel `rule_status` (`repo.set_rule_lab`, `get_rule_lab`, `list_rule_labs`). De proefmotor is `app/rule_live.py`, niet `app/trend_live.py` (dat is een oudere, andere motor): `RULE_VARIANT` "DON55_TREND" met `trade_type` "don55_trend", alleen voor de CEO (`CEO_ONLY_TYPES`, `for_viewer`), met een meelopende stop. Nieuwe trades komen er pas als de regel in het lab slaagde en dat is opgeslagen met `scripts/strategy_lab.py --opslaan` (`rule_status.lab_passes`); lopende trades volgt `update_open` altijd verder. `signals.stop_loss` blijft de eerste stop en de lopende stop staat in `rule_trades.current_stop`; `take_profit` is leeg; `level_check` slaat dit type over met een expliciet filter op `trade_type` en de motor zet zelf `auto_outcome` en de echte R in `trade_results`, die `track_record.signal_r` voorrang geeft. Proefsignalen gaan met `chain_it=False` buiten de hash-keten, zodat de openbare `/keten` ze niet toont. `track_record.rule_status(lab, live_r_net)` leidt "In proef", "Bewezen" of "Negatief" elke keer af uit lab en live data (Bewezen vraagt een geslaagde test, minstens 50 afgeronde live trades met een netto gemiddelde van 0 of hoger, en dat de laatste 100 niet duidelijk onder nul liggen); er is geen opgeslagen status, en Bewijs toont die. Leerlingen zien alleen soorten met een publiek label (`visible_rule_types`). Spec: `docs/superpowers/specs/2026-10-09-hespulse-visie-en-plan-design.md`; plan: `docs/superpowers/plans/2026-10-09-hespulse-onderzoek-en-proefmotor.md`.

**Range sweep.** Onze lezing van een range-sweep-strategie, vooraf vastgelegd in `docs/onderzoek/range-sweep/preregistratie.md`: de uitkomst volgt live dezelfde regels als in het lab, er wordt nooit afgesteld op data of op een voorbeeld. Zuivere detectoren in `app/replay/rangesweep.py`, stopmeting zonder doel (MAE/MFE, doelkans 1R tot 6R, kosten in R) in `app/replay/stopquality.py`, labfamilie `app/replay/rangesweep_lab.py` via `scripts/strategy_lab.py --familie rangesweep --opslaan` volgens `docs/onderzoek/range-sweep/vps-protocol.md` (30 toetsen, register 64, horde t ≥ 3,4). De kop is de stopkwaliteit (`range_sweep_stop`): `rule_status(..., stop_lab=)` geeft "In proef" bij geslaagde stopkwaliteit en nooit "Negatief" alleen omdat de strenge toets `range_sweep` mislukte; "Bewezen" vraagt die toets plus de live bewaking. Proefmotor `app/range_sweep_live.py` (`trade_type` 'range_sweep', geen `take_profit`, `chain_it=False`, meting in `range_sweep_trades`, R alleen bij de referentie-uitgang en zo gelabeld) en `app/range_watch.py` (stille ranges, eigen budget), aan met `RANGE_SWEEP_ENABLED` en `RANGE_WATCH_ENABLED`; CEO-only via `rule_live.CEO_ONLY_TYPES` tot `RANGE_SWEEP_PUBLIC` (Bewijs, kanspagina en `/keten` volgen dat). Bewijs toont lab naast live (`track_record.stop_quality_live`) met lopende en niet gevulde setups ernaast; de score 40/60 en de doelkans beschrijven, ze voorspellen niets.

**Zone-sweep.** Prik door een actieve zone met herstel (`app/replay/zonesweep.py`, lab `zonesweep_lab.py`, `docs/onderzoek/zone-sweep/preregistratie.md`). Live vóór de labrun op uitdrukkelijk verzoek van de gebruiker (2026-10-27, "Aanvullende besluiten"), altijd ongetest: `app/zone_sweep.py` (zuiver: kaart met limiet, stop `wick_025`, doel de rand van de eerstvolgende tegenovergestelde actieve zone via `zone_radar.target_for` bij minstens 2R, anders geen doel) en `app/zone_sweep_live.py` (scan alleen de eerste 20 minuten na een 1u-slot, track met `stopquality.simulate_fills`, follow met `range_sweep_live.follow_trade` voor kaarten zonder doel) in `scan_smc_fast` na de range sweep (gedeelde candlecache in `range_sweep_live.fetch_bars`). Alleen ZS_1H, ZS_2H en ZS_4H (`zone_sweep.LIVE_VARIANTS`); niets toevoegen of afstellen. Tabellen `zone_sweep_setups` (één rij per coin en zone, `quiet` = stil door dagcap `ZONE_SWEEP_MAX_PER_DAY` of een plan dat al voorbij stop of doel stond) en `zone_sweep_trades` (alleen zonder doel). Gevuld: `trade_type = 'zone_sweep'`, `chain_it=False`, journaal en melding via `send_kans_push` voor `zone_sweep_live.viewers()`. Met doel beslist `level_check`; zonder doel slaat `level_check._self_measured` hem over en zet de motor uitkomst en referentie-R. Radarkaart via `radar.setup_card` met sleutel `zsweep:<id>` (`zone_sweep.radar_setup`, `radar.KEY_PREFIX`), ook in Nu, Logboek (`repo.list_plan_moments(include_zone_sweep=)`) en Bewijs (eigen rij onder Per soort; na een opgeslagen labrun ook een status onder Regels met `zone_sweep_stop` als stop_lab, `STOP_LAB_KEYS`). Aan met `ZONE_SWEEP_ENABLED`, voor iedereen tot `ZONE_SWEEP_PUBLIC=false` (dan CEO-only via `rule_live.ceo_only_types`).

**POC-radar.** Point of control: de prijs met het meeste volume per gesloten UTC-dag en ISO-week, live op uitdrukkelijk verzoek van de CEO (2026-10-28) zonder labrun, altijd ongetest. `app/poc.py` (zuiver: bakken van `BIN_PCT` 0,05% van de eerste open, volume van elke gesloten 5m-candle gelijk over de bakken van low tot high, POC = midden van de zwaarste bak, periodes binnen `LOOKBACK` 14 dagen en alleen als ze volledig in de data zitten; naakt zolang geen latere 5m-candle hem raakte, een lont telt als geraakt), `app/poc_radar.py` (zuiver, naar het patroon van `zone_radar.py`: dichtstbijzijnde naakte POC binnen `MAX_DISTANCE_PCT` 6% per kant, onder de koers long en erboven short, limiet op de POC, stop een kwart ATR (1u) erachter met `smc_eval.floor_stop`, doel het eerste niveau voorbij de limiet, ook tussen limiet en koers (`poc_radar.obstacles`: elke POC, bekend bij het einde van zijn periode, of een zonerand uit `zone_radar.obstacles`) bij minstens 2R, anders geen doel; nooit doorzoeken; de kaart bewaart de niveaus in kolom `obstacles`; `TTL` 3 dagen) en `app/poc_radar_live.py` in `scan_smc_fast` na de zone-radar. De snelcyclus is elke keer een nieuw proces, dus de motor onthoudt alles in de database: `poc_levels` (één keer berekend per gesloten periode, met `touched_at`) en `poc_scans` (tot waar de aanrakingen per coin bijgewerkt zijn); hij haalt één keer per uur per coin alleen de nieuwe 5m-candles (`poc.fetch_from`) en zoekt dan nieuwe kaarten, 1u/4u via `range_sweep_live.fetch_bars`. Tabellen `poc_radar_setups` (UNIQUE coin, `level_key`; komt nooit terug) en `poc_radar_trades` (zonder doel, `range_sweep_live.follow_trade`; `level_check._self_measured` slaat hem dan over). Gevuld: `trade_type = 'poc_radar'`, `chain_it=False`, journaal, `send_kans_push`. Kaart via `radar.setup_card` met sleutel `poc:<id>` (geen zone: `no_zone`), eigen tab POC-radar op Kansen, kaartgrafiek `card_chart.poc_radar_svg` (`setup_chart.zone_svg` zonder vlak) via `/api/kaart_svg/poc:N`, Logboek (`list_plan_moments(include_poc=)`), eigen rij op Bewijs. `POC_RADAR_ENABLED`, `POC_RADAR_PUBLIC` (false: CEO-only via `rule_live.ceo_only_types`), `POC_RADAR_MAX_PER_DAY` (30). Kenmerk POC-samenval (`chance_checks.poc_checks`/`with_checks`, kolom `poc_near` op `zone_radar_setups` en `zone_sweep_setups`, gelezen via `poc_radar_live.samenval`, leeg = niet gemeten): alleen beschrijvend, Bewijs toont het via `score_split`; nooit een filter.

**Zone-radar.** Gewoon niveaus met een limietplan: `app/zone_radar.py` (zuiver) neemt per coin de actieve vraag- en aanbodzones uit `rangesweep.find_zones`/`zone_active` op gesloten 1u- en 4u-candles, de dichtstbijzijnde per richting binnen `MAX_DISTANCE_PCT` (6%, vooraf gekozen), limiet op de binnenrand, stop een kwart ATR voorbij de buitenrand met `smc_eval.floor_stop`, doel de rand van het eerste obstakel vanaf de limiet (`zone_radar.obstacles`: alle tegenovergestelde actieve zones voorbij de instap, met R en `known_at`, het slot van de candle waarop de zone bekend werd; ook een zone tussen limiet en koers, CEO v2-plan punt 2, 2026-10-31; nooit een verder obstakel om een mooier R-getal), opgeslagen als JSON in kolom `obstacles` (hoogstens 5, oude rijen leeg) en in het detailblad als "Eerste obstakel" en "Daarna" (`kansen.obstacle_lines`). Ligt het doel bij het ontstaan tussen limiet en koers (`tussen`), dan vervalt de kaart er niet als gemist op (`zone_radar.miss_take`, ook voor `walk` en `radar.setup_state`). `zone_radar.target_for` (vanaf de koers) is alleen nog van de zone-sweep. Zonder minimale R:R (sinds 2026-10-29 op verzoek van de CEO: de brede 4u-zone van WLD haalde op het dichtste doel 1,6R en kreeg geen kaart; de kaart toont de R:R en jij beslist; `MIN_RR` blijft alleen voor zone-sweep en POC-radar, die dan zonder doel gaan); alleen de dichtstbijzijnde eigen zone telt, nooit doorzoeken tot er een past. Levensduur (`zone_radar.MAX_AGE`, vooraf gekozen): 1u 200 candles, 4u 400 candles (`FETCH_LIMIT_BY_TF` haalt er 200 extra op); met 200 candles verdween de 4u-steun van 24 september 2026 op 28 oktober, anderhalve dag voordat de koers terugkwam (WLD). `rangesweep.find_zones`/`zone_active` nemen `max_age` met `ZONE_MAX_AGE` als standaard, dus lab, range sweep en de doelzoek van de zone-sweep houden 200. Motor `app/zone_radar_live.py` in `scan_smc_fast`, tabel `zone_radar_setups` (één rij per coin en zone, komt nooit terug), dagcap `ZONE_RADAR_MAX_PER_DAY` (40), aan met `ZONE_RADAR_ENABLED`, voor iedereen. Stille melding bij een nieuwe kaart (`alert_sent`, `send_new_card`) en luide bij de vulling (overgang waiting -> filled in `repo.fill_zone_radar_setup`, `send_kans_push`). De kaart staat op de Radar via `radar.setup_card` (sleutel `zone:<id>`, `zone_radar.radar_setup`), niet in `smc_setups`: die tabel is van de SMC-motor en zijn golden test. Gevuld wordt het een gewoon signaal `trade_type = 'zone_radar'`, ongetest, apart op Bewijs. "Groot" op een kaartgrafiek opent hem op het tijdframe van de zone (keuze 15m/1u/4u) met zone en doelzone als vlak vanaf de ontstaanscandle uit `zone_key` en de uitleg uit `zone_radar.chart_zone` (via `chart_spec(zone=)`); de kleine kaartgrafiek blijft 15m.

**Marktcontext.** Gratis publieke bronnen naast Binance als gemeten feit, nooit als beslissing: `app/market_context.py` (zuiver: funding naar % per 8u, verschil met Binance, OI over 24u, parsers per bron, teksten zonder koop/verkoop of voorspelling; drempels `FUNDING_HIGH_PCT`/`FUNDING_LOW_PCT` liggen vooraf vast) en `app/market_context_live.py` (in `scan_smc_fast` naast de motoren, één client-functie per bron via `_request`: 5s timeout, bij falen None en een log; cache per bron is de laatste meting in tabel `market_context`, heartbeat `marktcontext`, aan met `MARKET_CONTEXT_ENABLED`). Een zone-radar-kaart bewaart de stand bij zijn ontstaan in `ctx_funding`, `ctx_oi_change_24h`, `ctx_spread`; de vulling overschrijft ze niet. Weergave via macro `context_block` (Radar-kaart, kanspagina, Vandaag) met bron en leeftijd uit `app/freshness.py`; Bewijs toont `track_record.funding_split`. Geen motor, filter of melding mag deze waarden lezen; wie dat wil, toetst het eerst in het lab.

**Candlebron.** Alle live candles en koersen gaan via `app/exchange.py` (`fetch_ohlcv`, `fetch_last_price`), die per coin de markt kiest met `resolve` en de zuivere symboolkaart `app/candle_source.py`: `CANDLE_MARKET` 'perp' (standaard, ccxt `binanceusdm`, `BTC/USDT:USDT`) of 'spot' (terugval, `EXCHANGE_ID`); een coin zonder perp valt per coin terug op spot. Een 1000-contract (`PERP_ALIASES`, nu alleen PEPE uit `FIXED_COINS`; een onbekend 1000-contract herkent `pick_perp` aan de marktenlijst) komt terug in de prijs per munt (prijs / schaal, volume * schaal), want oude kaarten, POC-niveaus en open trades staan in die eenheid. Haal nooit candles buiten `exchange` om. `repo` schrijft bij elke nieuwe rij in `signals`, `structure_setups`, `range_sweep_setups`, `zone_radar_setups`, `zone_sweep_setups` en `poc_radar_setups` de kolom `candle_market` (`candle_source.market_of`: wat dit proces voor de coin ophaalde); oude rijen blijven leeg en worden niet herberekend; `smc_setups` krijgt hem bewust niet (de SMC-golden legt elke kolom vast). Het detailblad toont "Bron: Binance perps/spot" (`kansen.source_text`). `live.js` opent per markt een stroom (`hesLiveStreams`: perps op `fstream.binance.com`, met de kaart uit meta `live-symbols` = `candle_source.stream_map`). `exchange.get_exchange()` is de spotclient, alleen voor onderzoeksscripts met spotsymbolen. Lab, replay en golden tests volgen dit niet. Tests: `tests/test_candle_market.py`.

**UX-extra's.** Pauze: `push_policy` en `users.push_paused_until` (knop in `pause.js`, route `/api/push/pauze`). Prijsalarm: `app/price_alerts.py` plus `level_check.check_price_alerts` (`alarm.js`). Kopieerchips: `chance_steps.level_chips` (`copy.js`). Appicoon-badge: `radar.in_zone_count` via `/api/system_status`, die alleen de koerscache leest. Koersleeftijd: `app/freshness.py` (`stale.js`), per coin: `live.js` houdt `__liveAtByCoin` bij, `hesLiveFresh(coin)` (zonder coin: elke coin vers) en de stip volgt de oudste getoonde koers. Afstandsbalk: `trade_plan.approach_pct`. Sparklines: `radar.spark` (`spark.js`). Dagbudgetring: `budget_ring` in `today.py`. Resultaatcurves en uurkaart op Bewijs: `track_record.equity_curves` en `hour_grid`; ze tellen alleen doel en stop en volgen `rule_live.for_viewer`.

**Indeling.** Telefoon eerst, ontwerp V4 (bouwt op V2 `docs/design/hespulse_v2.dc.html` en `docs/design/fase2.md`, en de V3-tokens). Vier tabs in het dok en in de desktopbalk: Kansen (`/smc`, ook de PWA-start `start_url` `/smc` en waar inloggen, registreren, `/` en `/dashboard` heen sturen, ook voor de CEO), Logboek (`/signalen`), Bewijs en Markt (`/vandaag`); de urls bleven, het manifest-`id` bleef `/ceo`. Het getal op Kansen is `radar.in_zone_count`. Account, Meldingen, Handleiding, Zone-radar uitleg, Kwartaalcijfers, en voor de eigenaar Beheer, Galerij en CEO zitten in het blad achter het initiaal rechtsboven (`ph-avatar`/`topbar-avatar` met `data-more-toggle`, `tabbar.js`). Elke pagina vult `{% block page_title %}` (macro `page_header`) en bouwt zijn lijsten uit de macro's in `_macros.html` (`headline`, `keylines`, `utabs`, `row_head`, `market_row`); `utabs.js` doet de tabpanelen en opent bij een hash naar een kaart het paneel waarin die staat. **Kansen** komt uit `app/kansen.py` (zuiver): een tab per soort (Structuur met `structuur` en `structuur_c`, Zone-radar, Zone-sweep en POC-radar voor wie ze mag zien; zonder focus ook SMC, en een soort met een open trade houdt zijn tab), in de zone eerst, dan op gemeten afstand tot de limiet, zonder koers achteraan, overgeslagen (`hp_skip`/`plan_skips`) achteraan en gemarkeerd; open trades onder Open in de tab van hun soort; de tab met de meeste kansen in de zone gaat open, anders Structuur (`?tab=` kiest er een). Boven de tabs staat `page.total` (`kansen.summary`: "12 kansen klaar · 2 in de zone · 3 open", alleen wat er is, anders "Geen kansen"); elke tab draagt `num` (wachtende plannen, in de zone meegeteld, open trades niet) en `badge` (in de zone, alleen boven 0) via `utabs`; `kaarten.js` telt ze opnieuw na elke `/api/radar` (event `hp:radar` uit `radar.js`) met dezelfde woorden (`hesKansenSummary`, `tests/test_static_js.py`). Per tab ontdubbelt `kansen.dedupe` wachtende plannen en open trades apart: zelfde coin en richting met een instap binnen `DUP_PCT` (0,2%, vooraf gekozen) is één kaart, de oudste blijft, het blad zegt "Nog N vergelijkbaar signaal"; alleen de weergave, Bewijs, Logboek en meldingen houden alles. Een kaart is `macros.kans_card`: coin en richting in tekst, de stand-pil, het bewijslabel als gestippelde `pill`, de geplande R:R als klein label zonder kleur (`kansen.planned_rr`/`rr_text`: vanaf de limiet, bij Structuur het doel dat het signaal meet; niets zonder doel en niets bij een open trade; het blad zegt één keer "gepland" bij Doel; nooit een volgorde of filter) en een grafiek per soort, geen logo, chips of afstand. Structuur toont `svg` (zijn ongewijzigde momentopname `setup_chart.setup_svg` uit `_structure_cards`, voor een open Structuur-trade `kans_view.chart` zonder nieuwe candles via `_structure_trade_svg`); Zone-radar en Zone-sweep laden `svg_src` lazy (`/api/kaart_svg/<zone:N|zsweep:N|poc:N|signal:N>`, `kaarten.js`, hoogstens 4 tegelijk) uit `app/card_chart.py` en `setup_chart.zone_svg` (galerijstijl, viewBox 316 breed zodat tekst op een telefoon 11px of meer is: zone vanaf de ontstaanscandle met markering, doelzone, prik en herstel, lijnen met naam en prijs rechts), met een verborgen `level-chart` als bron voor "Groot" en als terugval bij een 404; SMC houdt `level_chart` met `legend=false`. De kaart-id is het anker van de meldingen (`radar-zone-N`, `radar-zsweep-N`, `radar-poc-N`, `radar-setup-N`, `radar-signal-N`, `structuur-N`); `/structuur` stuurt door naar `/smc?tab=structuur` zonder hash in de Location, zodat het anker van de melding blijft staan. Wat van Setups niet dubbel was (uitgevallen/gemist/vervallen, trend, range sweep en ranges, motorstand) staat als inklapbare regel onder de tab Structuur (`_structure_extras`). **Verbergen** (`kans_hidden`, per gebruiker, `UNIQUE (user_id, key)` met de kaartsleutel): kruisje `kc-hide` naast de kop, "Verberg" in het blad, "Verberg alles" onder Wachtend en Open; de kaart klapt weg naar de onzichtbare voorraad `data-kt-stash` van zijn tab (met detailblad, zodat Toon weer zonder herladen werkt), een balk van 5 s biedt Ongedaan (`kansen.hidden_text`, gelijk aan `kaarten.js`). `kansen.page(..., hidden=)` haalt verborgen kaarten vóór `dedupe` uit lijst, tellers en "vergelijkbaar" en geeft per tab `hidden` (rijen onder "Verborgen (N)") en `hidden_cards`; `dedupe` geeft `keys` zodat Verberg de tweelingen meeneemt. Dok en appicoon: `radar.in_zone_count`/`waiting_count(..., hidden)` met `repo.list_hidden_kansen`. Routes `POST /api/kans/verberg` en `/api/kans/toon` (JSON `keys` of formulier `key`, `kansen.parse_keys`). Alleen weergave: niets anders (Bewijs, Logboek, meldingen, `level_check`, journaal) leest `kans_hidden`; "Sla over voor vandaag" blijft apart bestaan. Tests: `tests/test_kansen.py` (HiddenTests), `tests/test_web_kans_hidden.py`. Een tik op de kop opent het detailblad (`macros.kans_detail`, één blad `#kd`, `kaarten.js`): de ladder, Stop/Instap/Doel één keer met houd-vast-om-te-kopiëren (`data-hold-copy`) en een prijsalarm (`level-bell`), de herkomst in één regel, de context op één regel per meting, en vast onderaan "Zet de order, stap voor stap" of "Bekijk de trade" plus "Sla over voor vandaag" (alleen plannen) en "Verberg". De zin in het blad (`kansen.say`) herhaalt geen getallen en staat er niet bij een open trade. **De ladder** (`app/ladder.py`, zuiver; macro `macros.ladder`, modes plan en trade; `ladder.js` met dezelfde formules, `tests/test_static_js.py`) heeft drie kolommen: links het koerslabel (`label_y`), in het midden de lijnen, rechts alleen de namen; de koerslijn loopt nooit door de tagkolom en `spread` houdt tags `TAG_PX` uit elkaar binnen `HEIGHT_PX` (`tests/test_ladder.py` toetst koers op de instap, net boven de stop, voorbij het doel en twee tags binnen 12px). Het grote getal erboven is gemeten (afstand of live R). **Prijzen om te lezen** komen uit `app/price_text.py` (komma, 2 decimalen vanaf 10, 3 vanaf 1, 4 vanaf 0,01, daaronder minstens drie cijfers die tellen; kopiëren met een punt) en `levelchart.js` volgt die regel; meldings- en pushteksten houden `chance_steps.fmt` vanwege de golden tests. Markt is de oude Vandaag zonder het Nu-gedeelte en zonder tweede kansenlijst; open meldingen van soorten zonder tab staan er onder Verder open. Het scherm Nu (rust of één ding) verviel; `app/nu.py` levert nog de items voor het blad en de checklist en het overslaan. V3-tokens (`--zone`, `--zone-in`, `--cu`, `--cdn`, bewegingstokens `--t-*`/`--e-*`) staan in `style.css`; bijtekst haalt 6,9:1 (`tests/test_theme.py`). De order-checklist is `/nu/order/<sleutel>` (`order.html` met `bare`, `order.js`): instrument, limiet, stop, doel, nooit een grootte; openen en afronden (POST `/nu/order/<sleutel>/klaar`, één keer, `keepalive`) staan per gebruiker in `checklist_runs`. Zwevend zoekveld alleen als een pagina `{% block dock_search %}` vult (nu alleen Kansen). Thema: donker is standaard; Account kiest Systeem, Donker of Licht (cookie `hp_theme`, `theme.js`, `html[data-theme]`); de lichte tokens staan twee keer in `style.css` (gekozen en Systeem) en `tests/test_theme.py` eist dat ze gelijk zijn en dat tekst 4,5 haalt. Nieuwe schermen lezen de V2-tokens (`--s1`, `--tx2`, `--ac`, `--aci` ...). De gloed bovenin komt van de tokens `--glow-top-*` (licht heeft er geen); `scripts/layout_check.py --theme dark|light` meet het contrast (minstens 4,5), draai hem voor beide. Een groot getal in `headline` is altijd een gemeten waarde, nooit een schatting of een opgesmukt getal.

**Logboek, replay en week (fase 2).** `/signalen` is een dagtijdlijn uit `app/logbook.py` (zuiver): per dag wat de app zag (nieuwe plannen en in de zone, uit `repo.list_plan_moments`; `smc_setups.zone_alert_at` is het moment van de zonemelding, bij de zone-radar is in de zone de vulling), wat jij deed (checklist afgerond, gevuld, genomen, overgeslagen) en de uitkomst. "Jouw trade" is één definitie, `logbook.user_trades`: een plan met een afgeronde checklist dat vulde, of een journaalregel genomen/aangepast; R komt alleen uit `track_record.signal_r` (bruto, zonder kosten), oefentrades nooit. Oudere dagen zijn uitklapregels. De signalenlijst staat onder `?weergave=open` en `?alles=1`, het Journaal op `/account#journaal`. `_logbook_inputs` in `web/main.py` haalt alles op met de `user_id` van de kijker: een leerling ziet nooit andermans skips, checklists of journaal (`tests/test_web_logbook.py`). Replay: `/logboek/replay/<id>` uit `app/trade_replay.py` (venster een uur voor de vulling tot de uitkomst op 5m, grover boven 600 candles; momenten alleen met echte tijdstempels; R pas na de vulling uit de candle-sluiting, vanaf de uitkomst het gemeten resultaat), server-SVG met grijze candles, `replay.js` verschuift alleen de cursor; candles van een gesloten venster blijven in `_replay_candles`. Week: tab Week op Bewijs uit `app/week_review.py` (week-R van jouw trades, acht ISO-weken, gemiddelde en grootste verlies, hoogstens één observatie uit overgeslagen plannen met een uitkomst; "volgens plan" bestaat niet en staat er niet).

**Beheer (fase 2).** `/beheer`, alleen de eigenaar (`_owner`, anders 404), achter het initiaal; `/ceo` blijft. Leerlingen (naam, set, week-R via `_week_review`, laatst gekeken uit `user_visits`, weggelaten zonder bezoek), volg-sets (`follow_sets`, `users.follow_set_id`) en uitnodigingscodes (`invites`, `HES-XXXX` zonder verwarrende tekens, aantal keer en verloopdatum, kopieer geeft de link `/registreer?code=`). Pure helpers in `app/beheer.py`. Een volg-set filtert alleen de pushmeldingen: `push_policy.in_follow_set` in `push_notify.send_kans_push` en `send_new_card`; buiten de set wordt het een rustige melding, kaarten en data blijven gelijk. Registreren blijft open; met `REGISTRATION_REQUIRES_INVITE=true` is een geldige code nodig. `repo.register_user(..., invite_code=)` telt het gebruik en kent de set toe in één transactie; een bezette naam kost geen gebruik.

**Aankondiging.** `app/announce.py` (zuiver: aftellen, fase vóór/live, wanneer verhaal, link en push komen, en alle tekst) met `announce_live.py` (eenmalige push in `scan_smc_fast`, vóór de noodrem, via `send_push` en niet het kansbudget; `repo.claim_flag` in `settings` maakt hem eenmalig over processen heen). Het moment staat in `settings` (`repo.get_announcement_at`, `.env` `ANNOUNCEMENT_AT` alleen als startwaarde), te zetten met `scripts/aankondiging.py` (`--zet 2026-11-02T18:00` in Amsterdamse tijd of `--zet +30m`/`+2u` vanaf nu via `announce.parse_when`; `--toon` geeft ook de resterende tijd). De teksten (V4, `STORY_VERSION` "v4": alle kansen op één plek, zones en Structuur, de order stap voor stap, Logboek en Replay, licht en donker, op je beginscherm) beloven geen ladder of "één ding tegelijk" meer (`tests/test_announce.py`). `/nieuw` is openbaar (`nieuw.html`, `nieuw.js`, `announce.css`, linkvoorbeeld uit `scripts/make_og.py`); het verhaal komt één keer per gebruiker en `STORY_VERSION` (`user_flags`, plus localStorage), alleen na een gezet en bereikt moment, en staat opnieuw op `/wat-is-nieuw`. Alleen wat er echt is: het aantal coins volgt `config.FIXED_COINS` (test), geen winst of "bewezen", nieuwe soorten heten ongetest.

**Structuur zonder oordeel.** `scripts/structuur_check.py` (alleen-lezen, telling in `app/structure_report.py`) toont per dag breuken, plannen, gemeld, gevuld en uitkomst, de dagcap, de hartslag en de coins zonder plan; de hartslag zegt "N van M coins gecontroleerd in X s" met mislukte en niet gevolgde coins (`structure_live.beat_detail`/`parse_beat`), en het oordeel van Claude heeft een korte timeout (`CLAUDE_TIMEOUT_S`). `app/structure_live.py` meldt elke gespotte Structuur-kans (A, B en C) bij het ontstaan van het plan met dezelfde stille melding (`_announce`, `_push_all(..., new_card=True)` naar `send_new_card`), en luid bij de vulling. De dagcap `STRUCTURE_MAX_ALERTS_PER_DAY` (30) telt alle kansen gelijk; bij een volle cap kiest `structure_live.choose` de kans die het dichtst bij zijn limiet ligt. Het oordeel van Claude (`grade`, `reason`) blijft als meting in de database en bepaalt alleen nog of een vulling `structuur` of `structuur_c` heet: geen filter, geen volgorde, geen volume, geen kenmerk in `chance_checks`. Op geen scherm voor gebruikers staan A/B/C of sterk, redelijk, zwak; beide soorten heten naar buiten Structuur (Vandaag telt ze samen). Alleen Bewijs toont `structuur` en `structuur_c` als twee regels (`tests/test_web_structuur_neutral.py`). Naast LINE en RANGE kent Structuur sinds 2026-10-28 (op verzoek van de CEO, zonder labrun, ongetest) de breuk `CHOCH`: hogere bodem met breuk van de laatste top, gespiegeld voor short (`breakretest.find_choch`, constanten `CHOCH_*` vooraf vast, nooit afstellen). `find_breaks` en `run` blijven ongewijzigd; live leest `find_structure_breaks` (ontdubbeld met `drop_duplicate_choch`: een LINE/RANGE op dezelfde candle en kant binnen 0,2% blijft). Zelfde recept, melding, dagcap en oordeel; de grafiek tekent het niveau met de twee bodems (`plan.points`, `setup_chart.structure_words` voor de tekst), de hartslag en `structuur_check.py` tellen hem apart (`choch`, kolom h.bodem).

**Dagcaps zichtbaar.** Sinds 2026-11-01 (WLD-breuk van 29 okt bleef `niet_gemeld` door een volle cap) staan de caps hoger en telt elke focus-motor met een dagcap (Structuur, zone-radar, zone-sweep, POC-radar) wat de cap tegenhield: `repo.record_cap_hold` in tabel `cap_holds` (één rij per motor en kans, dus een kans die elke cyclus terugkomt telt één keer per 24 uur; een zone of niveau dat al een kaart had telt niet), tekst uit `app/daycap.py` achter de hartslag ("; 3 kansen tegengehouden door de dagcap van 40") en per soort één regel onder Dagcap in Beheer. Alleen meting: geen motor leest het. Tests: `tests/test_dagcap.py`.

**Focus.** `app/focus.py` (zuiver) is de enige bron voor welke soorten nog nieuwe kansen zoeken en melden: `FOCUS_TYPES` = `structuur`, `structuur_c`, `zone_radar`, `zone_sweep`, `poc_radar` en `hespulse_model` (alle live, ongetest); `focus.model_only()`/`alerts_on(trade_type)` beslissen wie nog meldt. `ENGINE_FOCUS` (standaard true; false zet alles terug) zet de andere motoren uit met een gate op de aanroep via `focus.engine_on(trade_type)`, nooit in de beslislogica: `scan_market` (smc, patroon, de autonome day trading; een al open day-trading-signaal wordt nog ververst), `scan_smc_fast` (de SMC-check), `trend_live.run`, `rejection_live.run`, `rule_live.scan`, `range_watch.run`, `range_sweep_live.scan`, `market_script.generate_all`/`run_triggers`, `samenval.run`, `level_check` (swing-watches) en `signal_processor.handle_message` (na opslaan en dedupe, vóór de Anthropic-aanroep; `process_day_trading_signal` blijft onaangeroerd voor de golden test). Een uitgezette motor schrijft `focus.OFF_DETAIL` in zijn hartslag. Lopende trades volgen `level_check`, `rule_live.update_open` en `range_sweep_live.track`/`follow` altijd verder. In de weergave filtert `web.main._forming_setups` de SMC-setups weg (Radar, Nu, dok, appicoon tellen daardoor gelijk), `_open_chances` de wachtende scenario's en `_range_sweep_shown` de range sweep; open signalen van elke soort blijven staan. Bewijs splitst met `focus.split` in de focus-soorten (open, bovenaan) en "Uitgezet, ter verbetering" (n, doel, stop, netto R uit `summarize`'s `net_total`). Tests: `tests/test_focus.py`, `test_focus_gates.py`, `test_web_focus.py`; de andere tests draaien met focus uit (`tests/__init__.py`).

**Automatische verbeterlus.** Elke nacht om 03:17 UTC (`deploy/hespulse-nacht.timer`) draait `scripts/nacht_export.py --git`: auto-missers
(`app/auto_misser.py` zuiver, `scripts/auto_misser.py`: omkeer vanaf een bevestigd 1u-swing-punt van minstens `MIN_MOVE_ATR` 3 ATR binnen 24 uur,
vooraf vast; gezien als een kaart of signaal binnen ±12 uur van het begin, anders per focus-motor de weigerreden uit `scripts/misser_check.py`;
tabel `auto_missers`), lekken per soort over 7 en 30 dagen (`app/leaks.py`, `repo.leak_inputs`) en de schaduw, als JSON en Markdown in
`data/export/`, gepusht via een aparte kloon (`data/export-git/`) naar alleen de tak `hespulse-data` met deploy key (`HESPULSE_DATA_REMOTE`,
`HESPULSE_DATA_KEY`). De export bevat nooit gebruikers, e-mail, journaal of push-abonnementen (`tests/test_nacht_export.py`). Daarna
`scripts/schaduw.py --auto`. Schaduwvarianten (`app/shadow.py`, `app/shadow_live.py`, tabellen `shadow_variants`, `shadow_results`,
`engine_overrides`): elke variant ligt vooraf vast met reden (`shadow.SEEDS` in code, vastgelegd door `--auto`, of `--nieuw`), hoogstens één
actieve schaduw per soort, alleen parameters uit `shadow.PARAMS` (zone-radar `stop_atr`/`max_distance_pct`, zone-sweep `stop_buffer_atr`,
POC-radar `stop_atr`, Structuur `stop_atr`), ingespoten als optioneel argument van de planfunctie met de constante als standaard. De motor roept
`shadow_live.observe` aan met dezelfde invoer voor de hoofd- en de variant-arm; beide gaan alleen naar `shadow_results` (geen melding, journaal of
signals-rij) en `shadow_live.track` volgt ze in `scan_smc_fast` op gesloten 5m-candles met dezelfde meting (`shadow.step`, netto na
`TRACK_RECORD_COST_PCT`, zonder funding, kaarten zonder doel tellen niet). Promotieregel `shadow.verdict` (vast): minstens 50 afgeronde trades per
arm; promoveren als de variant netto beter is in beide helften én `stats.cluster_bootstrap_diff` per week boven 0 ligt; afvallen als dat interval
onder 0 ligt of na 100 per arm; anders wachten. Promoveren zet de waarde in `engine_overrides`, die de motor elke cyclus leest
(`shadow.live_params`), en stuurt de CEO één push; `--terug <id>` haalt hem weg. Bewijs toont per soort een schaduwregel, alleen voor de CEO.
Wijzig nooit een gewone motorregel of constante buiten deze route; de wekelijkse sessie volgt `docs/verbeterlus.md`. Tests: `tests/test_auto_misser.py`,
`test_leaks.py`, `test_nacht_export.py`, `test_shadow.py`.

**Conventions to preserve**: comments explain non-obvious *why* (a past
bug, a deliberate tradeoff, a constraint that isn't visible from the code
itself) — not what the code does; keep that ratio, don't add narration
comments. Confidence/signal UI text distinguishes what was *measured* (the
✓/✗ technical factors) from what is *estimated* (historical win-rate
percentages) — don't blur that line when adding new signal metadata.
The page background is flat on purpose: the base colour plus the static
top glow (`html.has-glow`, `.glow-edge-tint`), with no grid, drifting blobs
or outline shapes behind the content; don't add background layers. Any
remaining motion (the live-pill heartbeat, the logo's breathing glow in
`base.html`/`style.css`) is tied to a real, live value (time since last
message, volatility of open positions) and always respects
`prefers-reduced-motion`; never add animation that's purely decorative.
