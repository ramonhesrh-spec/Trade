# Automatische verbeterlus — implementatieplan

> Uitgevoerd in één sessie (TDD, kleine commits). Spec: de opdracht van de CEO van 2026-11-01 (zie CLAUDE.md, alinea "Automatische verbeterlus").

**Doel:** HesPulse meet zelf waar de focus-soorten kansen laten liggen, en kan één vooraf vastgelegde parameterwijziging per soort als schaduw
naast de live motor meten en volgens een vaste regel promoveren of laten afvallen.

**Architectuur:** zuivere modules (`app/auto_misser.py`, `app/leaks.py`, `app/shadow.py`) met dunne lagen eromheen (`app/shadow_live.py`,
`scripts/auto_misser.py`, `scripts/nacht_export.py`, `scripts/schaduw.py`). Parameterinjectie in de planfuncties van de motoren via optionele
argumenten met de huidige constante als standaard; de beslislogica zelf verandert niet.

## Global Constraints
- Candles alleen via `app/exchange.fetch_ohlcv`.
- Schema: `app/schema.sql` + idempotente migratie in `db._migrate` (nieuwe tabellen: `CREATE TABLE IF NOT EXISTS` volstaat; geen index in schema.sql
  op een kolom die een migratie nog moet toevoegen).
- Alles netto na kosten (`TRACK_RECORD_COST_PCT`, zelfde formule als `track_record._cost_r`; funding wordt in de schaduw niet gemeten, voor beide armen gelijk).
- Constanten vooraf vastgelegd en gedocumenteerd; nooit afstellen op data.
- Export: geen gebruikersnamen, e-mail, push-abonnementen, chat-id's of secrets.
- Golden tests blijven groen; tests draaien offline.

## Taken
1. `auto_missers`-tabel + `app/auto_misser.py` (`find_moves`, `seen_by`, `ENGINES`) + `scripts/auto_misser.py` (ophalen, motorredenen uit
   `scripts/misser_check.py`, opslaan). Tests: 3 ATR wel, 2 ATR niet; kaart binnen ±12 u = gezien.
2. `app/leaks.py` (`per_kind(inputs, now, days)`) + `repo.leak_inputs`. Tests: tellingen per soort.
3. `scripts/nacht_export.py` (+ `--git` naar tak `hespulse-data` via een aparte kloon in `data/export-git/`), deploy-units, README. Test: geen
   persoonsgegevens in de export.
4. `shadow_variants`, `shadow_results`, `engine_overrides`; `app/shadow.py` (register, `verdict`, `step`, teksten), `app/shadow_live.py`
   (`observe`, `track`), injectie in zone-radar, zone-sweep, POC-radar en Structuur, `scripts/schaduw.py` (`--promoveer`, `--terug`, `--auto`),
   Bewijs-regel voor de CEO. Tests: verdict-randen, geen melding/signaal, overlay gelezen, terugdraaien.
5. CLAUDE.md-alinea en `docs/verbeterlus.md`.
