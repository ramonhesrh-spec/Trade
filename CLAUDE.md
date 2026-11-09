# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Afspraken met Claude

Bron en uitleg: `docs/blueprint.md`. Register: `docs/register/index.md`. Skills: `.claude/skills/` (`plan-gate`, `besluit-vastleggen`, `smoketest`,
`meting-draaien`, `sessie-afsluiten`).

- Een niet-triviale wijziging begint met `plan-gate`: zelfbevraging, gerichte vragen aan Ramon, score 1 tot 100, go pas vanaf 95 en na akkoord van Ramon. Typo's en tekstwijzigingen hebben geen score nodig.
- Claude beslist nooit zelf over: een regel of getal wijzigen, wat "bewezen" is, een hypothese promoveren, juridische, fiscale of financiële zaken en betalingen, de scope of een nieuwe feature, de plek van de repo en wie toegang heeft. Stoppen en Ramon vragen. Een AI-voorstel is geen besluit.
- Klaar is gemeten: toon de testuitvoer (`smoketest`) voor je "klaar" zegt. Rood betekent geen commit. Werk een verwachte uitkomst nooit stil bij.
- Een nieuw idee gaat naar de parkeerlijst en start geen werk. Een besluit gaat met `besluit-vastleggen` in `docs/onderzoek/besluiten.md`.
- Plakcode voor Ramon altijd compleet (het hele blok). Plak geen grote bestanden of logs integraal; zoek gericht.
- Geen geheimen in git (sleutels, wallet, toegangscodes).
- Houd dit bestand kort (doel ongeveer 10 kB). Uitleg per onderdeel hoort in `docs/architectuur.md`; voeg hier alleen een regel toe die in elke sessie moet gelden.

## Eén taak tegelijk

Lees aan het begin van elke sessie `docs/taken/NU.md`. Werk alleen aan de actieve taak daarin. Een nieuw idee gaat naar de parkeerlijst
in `NU.md`, niet naar werk. Werk de stand en de volgende stap bij in het taakbestand (`docs/taken/NN-onderwerp.md`) voor je afsluit.

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

## Architecture (kaart)

Volledige tekst per onderdeel: `docs/architectuur.md` (zoek op de vetgedrukte kop). Lees daar het onderdeel van je taak voor je code wijzigt.
De regels die altijd gelden staan hieronder.

- **Processen:** `main.py` (Discord, Telegram, pipeline) en `web/main.py` (FastAPI) delen één SQLite (`data/trading.db`, WAL). Aparte systemd-units; herstart ze apart na een deploy. Periodiek: `app/level_check.py` (15 min), `app/heartbeat.py`, `scan_smc_fast` (5 min). Alerts zijn "één keer per rij": controleer de verzonden-vlag voor je een meldpad toevoegt.
- **Pipeline:** `signal_processor.handle_message` → `anthropic_interpret` → `exchange`+`indicators` → `risk` → `repo` → push. Zuivere beslislogica in `app/setup_eval.py` en `app/smc_eval.py`: niet wijzigen zonder de golden tests (`tests/test_smc_golden.py`, `test_smc_equivalence.py`).
- **Database:** alles via `app/repo.py`, nooit losse SQL. Schemawijziging is tweedelig: `app/schema.sql` én een idempotente `ALTER` in `db.py:_migrate()`; een index op een nieuwe kolom hoort in `_migrate()`. Oefentrades (`is_practice=1`) tellen nooit mee in statistiek: elke nieuwe query filtert ze.
- **Multi-tenant:** `signals`, `messages`, `source_levels` zijn globaal; `journal_entries` is per gebruiker. Een leerling ziet nooit andermans skips, checklists of journaal.
- **HesPulse-model** (`app/model.py`, spec `docs/onderzoek/hespulse-model/preregistratie.md`): het enige model dat meldt (`MODEL_ONLY_ALERTS`, `focus.engine_on`). Alle constanten liggen vooraf vast: nooit afstellen, niet op een voorbeeld. Bevroren tot 2026-11-24 (B-2026-11-03-09/10, B-2026-11-09-03). `scenarios()` is prefix-vast (`tests/hespulse_model/test_model.py`). Verandert een swing-, breuk- of rangeregel, dan moet `tradingview/hespulse_clean.pine` en `hespulse_structuur.pine` mee (`tests/test_tradingview_signals.py`, `test_structure_pools.py`). Meting alleen via `app/model_measure.py`, nooit als filter.
- **Meldingen:** alleen de entry en de vulling zijn luid. Nieuwe kaart via `push_notify.send_new_card`, vulling via `send_kans_push` (conflictregel, dagbudget 8, bundel). Een nieuw meldpad hoort in `send_new_card`.
- **Oude motoren** (Structuur, zone-radar, zone-sweep, POC-radar, range sweep, rejectie, trend, regelproef): zoeken en melden niets meer, lopende trades lopen af. Niets toevoegen of afstellen; elke soort is ongetest en Bewijs toont de score.
- **Kansen, kaarten, Logboek, Bewijs:** pure functies in `app/kansen.py`, `app/radar.py`, `app/track_record.py`, `app/logbook.py`, `app/week_review.py`; de rekenkunde staat daar, niet in templates of `web/main.py`. Bewijs telt alleen stop en doel in winrate en R. Kenmerken (`chance_checks`) beschrijven en filteren nooit. Een groot getal in `headline` is altijd gemeten.
- **Candlebron:** alle candles en koersen via `app/exchange.py` (`fetch_ohlcv`, `fetch_last_price`), nooit erbuiten. Perps zijn de standaard.
- **Web:** één `web/main.py`, Jinja2-templates met macro's in `_macros.html` (eerst daar zoeken), JS verbetert server-gerenderde pagina's. Thema alleen licht; tokens twee keer in `style.css` (`tests/test_theme.py`). Prijzen om te lezen via `app/price_text.py`.
- **Meting en export:** alleen-meting-modules (`funding`, `excursion`, `latency`, `daycap`, `market_context`) worden door geen motor gelezen. Nachtexport `scripts/nacht_export.py` bevat nooit gebruikers, e-mail of journaal. Schaduwvarianten alleen via `app/shadow.py`; wijzig nooit een motorregel buiten die route (`docs/verbeterlus.md`).
- **Onderzoeksgeheugen:** eerst `docs/onderzoek/README.md`, `voortgang.md`, `besluiten.md`, `hypotheses.md`. Een besluit wordt nooit stil overschreven; een hypothese ligt vast vóór de toets.

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
