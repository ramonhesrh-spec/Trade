# HesPulse: dossier voor een onafhankelijke review

Doel van dit document: een andere bot of analist beoordeelt HesPulse met een eigen visie. Het bevat wat het systeem doet, wat gemeten is, wat niet, en waar wij twijfelen. Lees het als een opdracht: zoek fouten, blinde vlekken en betere ideeen. Geef per punt bewijs of een toets die wij kunnen draaien.

## 1. Wat HesPulse is

- Een signaaldienst voor de eigenaar en een kleine kring vrienden. Handmatige uitvoering. Het systeem plaatst nooit een order.
- Perpetuals op 35 vaste coins (`config.FIXED_COINS`), data van Binance. Kosten die wij aannemen: onder 0,1% per rondreis.
- Elke kans krijgt een melding (Telegram en web push) met limiet, stop en, waar aanwezig, doel. Gebruikers beslissen zelf.
- Stack: Python, FastAPI, SQLite (WAL), vanilla JS PWA. Twee processen: `main.py` (bot en pipeline, scans elke 5 minuten) en `web/main.py` (dashboard). Periodieke jobs: `level_check` (15 min) en `heartbeat`.

## 2. Motoren die nu nieuwe kansen zoeken (focus)

`app/focus.py` is de enige bron. Alle andere motoren staan uit (`ENGINE_FOCUS`), lopende trades volgen wij altijd verder.

| Soort | Idee | Stop en doel | Status |
|---|---|---|---|
| Structuur (`structuur`, `structuur_c`) | Breuk van structuur met retest, ladder T1 tot T3 | Stop naar entry na T1 | Live, ongetest. Het oordeel van Claude (A/B/C) is een meting, geen filter |
| Zone-radar | Actieve vraag- en aanbodzones op gesloten 1u en 4u, dichtstbijzijnde per richting binnen 6%, limiet op binnenrand | Stop een kwart ATR voorbij de buitenrand, doel de rand van de volgende tegenovergestelde zone, minimaal 2R | Live, ongetest |
| Zone-sweep (ZS_1H, ZS_2H, ZS_4H) | Prik door een actieve zone met herstel | Stop `wick_025`, doel via `zone_radar.target_for` bij minstens 2R, anders geen doel | Live op uitdrukkelijk verzoek, ongetest |
| POC-radar (in aanbouw) | Limiet op naakte dag- of week-POC, richting volgt de ligging | Stop een kwart ATR voorbij het niveau, doel de volgende POC of zone-rand bij minstens 2R | Wordt gebouwd, ongetest |

Dagcaps en budget: push-budget 15 unieke coin/richting per dag, conflictregel 6 uur, caps per soort (zone-radar 20, structuur 12, zone-sweep 10).

## 3. Wat wij gemeten hebben (eerlijk)

Bron: eigen lab (`app/replay/`, `scripts/strategy_lab.py`), vooraf vastgelegde varianten, bootstrap per weekcluster. Een regel slaagt alleen met minstens `MIN_TRADES` trades, gemiddelde netto R boven 0 in beide helften, marge per weekcluster boven 0 en een marge boven een placebo (willekeurige instap, zelfde uitgang).

- Trendvolgen op 4u: +0,07 tot +0,12R netto, maar faalt de strenge weekmarge-toets.
- Sweeps, rejectie, kanteling en structuur met kleine stops verliezen na kosten. Een stop onder 1% kost al ongeveer 0,1R aan kosten.
- Fase (balans of onbalans) onderscheidt winnaars en verliezers niet.
- Zone-radar: in een dalende markt halen longs bijna nooit het doel (0 van 34 long-doelen in de laatste meting). Shorts doen het beter. Dit is regimeafhankelijk en niet gecorrigeerd.
- Structuur voelt voor de eigenaar zwakker sinds 35 coins. Mogelijke oorzaak: de 5 minuten cyclus over 35 coins duurt langer dan 5 minuten, waardoor breuken gemist worden. Niet bevestigd (`scripts/structuur_check.py` meet dit).
- Live winstcijfers zijn er niet. Niets van de live motoren is bewezen. Dit staat zo op Bewijs.

## 4. Eerlijkheidsregels in de code

- `/bewijs` telt alleen `take_profit` en `stop_loss` in winrate en R. Open en verlopen staan er naast, nooit stil weggelaten.
- Oefentrades (`is_practice=1`) tellen nooit mee.
- Gemeten kenmerken per kans (✓/✗, score) beschrijven en voorspellen niet. Bewijs toont per kenmerk of een hoge score vaker wint (`track_record.score_split`).
- Claude-output (scenario's, oordeel) is een hypothese: gevalideerd in code, gelabeld ongetest.
- Marktcontext (funding, open interest, spread) is een feit naast Binance. Geen motor of filter leest het.
- Verbergen van een kaart is een weergavekeuze per gebruiker. Bewijs, Logboek, journaal en meldingen blijven gelijk.
- Meldingen van gebruikers en de signalen zelf zijn globaal. Alleen het journaal is per gebruiker.

## 5. Beschikbare data voor toetsing

OHLCV (5m, 15m, 1u, 4u, dag) via Binance, funding, open interest, taker buy/sell ratio, long/short ratio, liquidaties. Opgeslagen trades en uitkomsten in `data/trading.db` (tabellen `signals`, `journal_entries`, `trade_results`, `zone_radar_setups`, `zone_sweep_setups`, `rule_trades` en meer). Replay-engine in `app/replay/`. Alle toetsen draaien via `scripts/`.

## 6. Wat wij van de reviewer vragen

1. Welke aannames in sectie 2 en 3 zijn zwak of onjuist? Geef bewijs.
2. Welke edge past beter bij een kleine retail-dienst met handmatige uitvoering en kosten onder 0,1%? Denk ook niet-technisch: carry, funding, structurele flows, listing-effecten, macro-kalender.
3. Waar zit overlevingsfout of datasnooping in onze werkwijze? Onze regel is: regels vooraf vastleggen en nooit afstellen op data. Houden wij die vol?
4. Is de keuze voor 35 coins, een 5 minuten scan en handmatige limietorders consistent met de kostenaanname?
5. Welke toets op live data (zonder lab) laat het snelst zien of een motor een echte edge heeft? Denk aan minimale trades, regime-opsplitsing en vergelijking met een placebo.
6. Welke risico's mist u (data, API-limieten, uitvoeringsvertraging, regimewissel)?

Geef uw antwoord als: bevinding, bewijs, voorgestelde toets, geschatte kans dat het helpt (laag, middel, hoog) en de kosten om het te toetsen.

## 7. Wat u niet hoeft te doen

- Geen orders plaatsen en geen kansen adviseren aan gebruikers.
- Geen wijzigingen in de live database.
- Geen aanname dat een motor werkt omdat hij live staat. Alles staat gelabeld als ongetest.

## 8. Waar u de code vindt

`CLAUDE.md` (architectuur), `README.md` (product en deployment), `docs/onderzoek/` (preregistraties en protocollen), `docs/superpowers/` (specs en plannen), `tests/` (golden tests voor de motoren).
