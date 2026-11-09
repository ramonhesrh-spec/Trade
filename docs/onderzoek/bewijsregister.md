# Bewijsregister

Per regel: wat er gemeten is, de bron, hoe je het reproduceert, en wat het niet bewijst. Uitkomsten gelden voor de genoemde data, niet
daarbuiten.

## E1. Nachtexport 2026-11-02: 374 afgeronde trades van vijf soorten (gemeten 2026-11-02)

**Bron.** `origin/hespulse-data:export/hespulse-2026-11-02.json`, 409 signalen van 30 dagen, waarvan 374 met doel of stop.
**Reproduceren.** `python3 scripts/export_analyse.py --tak 2026-11-02`.

| Soort | n | Unieke uren | Weken | Winst | Netto R | 95% per week | Kosten |
|---|---|---|---|---|---|---|---|
| Zone-sweep | 121 | 48 | 2 | 50% | +0,20 | +0,19 tot +0,33 | 0,06R |
| Structuur C | 86 | 64 | 3 | 41% | +0,28 | 0,00 tot +0,72 | 0,14R |
| Structuur | 43 | 36 | 4 | 30% | −0,12 | −0,47 tot +1,54 | 0,14R |
| Zone-radar | 111 | 66 | 2 | 18% | −0,52 | −0,72 tot −0,37 | 0,07R |
| POC-radar | 13 | 10 | 2 | 38% | +0,57 | −1,15 tot +0,71 | 0,15R |
| Alles | 374 | 196 | 5 | 36% | −0,02 | −0,22 tot +0,33 | 0,09R |

Richting:

| Soort | Long | Short |
|---|---|---|
| Zone-sweep | 55×, −0,28R | 66×, +0,60R |
| Zone-radar | 70×, −0,81R | 41×, −0,02R |
| Structuur C | 33×, −0,06R | 53×, +0,49R |
| Structuur | 20×, +0,04R | 23×, −0,26R |

**Aangetoond binnen deze data.**

- Zone-radar long verloor: 70 trades, 10% winst, −0,81R.
- De trades zijn sterk geclusterd. 374 trades vallen in 196 unieke uren. Eén uur had 18 trades in dezelfde richting.
- 357 van de 374 trades zijn van vóór de perps-candles (`candle_market` leeg). Na de overstap zijn er 17.

**Niet aangetoond.**

- Een voordeel van welke soort ook. Een interval over 2 tot 5 weken is te smal om iets te bewijzen. Het weekinterval van zone-sweep rust op
  2 weken.
- Dat shorts structureel beter zijn. Eén dalende maand kan het hele verschil verklaren. Daarom is dit nu hypothese H1.

**Tegenbewijs tegen een eerdere bewering.** Eerder stelde onderzoek (labfase, oktober) dat stops onder 1% netto verliezen door de kosten.
In deze live data gaven stops onder 0,5% +0,11R netto (139 trades, kosten 0,15R per trade). Stops van 0,5% tot 1% gaven −0,27R. Er is
dus geen oplopend verband met de stopafstand. Dit weerlegt de labbewering niet, want het is andere data en een korte periode. Het verbiedt
wel om "kleine stop = verlies" als vaststaand te behandelen.

## E2. "Groot" op de modelkaart is weer schuifbaar met keuze 15m/1u/4u (2026-11-02)

**Waarneming CEO.** Op de HesPulse-kaart kon je het tijdframe niet meer wisselen en kon de grafiek niet bewegen.

**Oorzaak.** Commit 9598c72 liet "Groot" de statische server-SVG openen in plaats van `levelchart.js`.

**Controle.** Playwright op 375px tegen een scratch-database met synthetische candles:

- Tijdframeknoppen 15m, 1u en 4u aanwezig, wisselen werkt.
- Slepen verschuift de grafiek.
- Geen JS-fouten.
- Schermafdrukken in `.superpowers/screens/modelgroot_*.png`.

**Regressietest.** `tests/test_web_model.py`, `test_groot_opens_the_movable_chart_with_timeframe_choice`.

**Niet gecontroleerd.** Echte Binance-candles. Vanuit deze container is er geen netwerk naar Binance.

## E3. Meetfout in de uitkomst van het HesPulse-model, gerepareerd (2026-11-02)

**Waarneming in de code.**
- `level_check.check_signal_outcomes` toetst alleen candles vanaf `signals.created_at` (`candles_after`).
- Het model zet `created_at` bij het opslaan (`repo._insert_signal`, `db.now_iso()`). Dat is een of twee 5m-candles na de vulcandle,
  want `walk_fill` werkt op gesloten 5m-candles.
- Signalen vervallen na `SIGNAL_MAX_AGE_DAYS = 1`.

**Gevolg.** Een stop in de eerste candles na de vulling werd niet gezien. Een doel na dag één telde niet. Beide maken H mooier of
onvollediger dan de spec, en de vergelijking met V1 (die wel vanaf de vulling meet) klopte niet.

**Reparatie.** `model_live.track_trade`, commit 4d3e50a.

**Regressietests.** `tests/test_model_live.py` `OutcomeFromFillTest`:
- stop in de eerste candle en doel later telt als stop;
- tegenvoorbeeld zonder stop telt als doel;
- doel op dag drie telt;
- na 7 dagen `tijd` met R apart;
- `level_check` haalt geen candles voor het model.

Vier van de vijf falen met de oude route (mutatiecontrole).

**Niet onderzocht.** Hoeveel modeltrades op de VPS al zo zijn afgesloten. Het model draait sinds vandaag, dus waarschijnlijk geen of
weinig. Controle op de VPS: `sqlite3 data/trading.db "SELECT COUNT(*) FROM signals WHERE trade_type='hespulse_model' AND auto_outcome IS NOT NULL;"`

**Bekend restpunt bij de andere soorten.** Het deel van de vulcandle na een vulling in een lopende candle telt niet mee. Niet gerepareerd;
die soorten melden niet meer.
