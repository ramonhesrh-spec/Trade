# HesPulse-model: preregistratie van de backtest over meerdere maanden

Status: concept, wacht op akkoord van de CEO. Er is niets gedraaid.
Opgesteld: 2026-11-03 (taak 08, `docs/taken/08-backtesten.md`)
Aanvulling op: `preregistratie.md` (model, §8 beoordeling) en `docs/onderzoek/range-sweep/preregistratie.md` (labregels, kostenregel, register).

Wat hier staat, ligt vast voor de run. Na het akkoord verandert niets meer, ook niet nadat een uitkomst bekend is. Een andere wens betekent een nieuwe preregistratie op data die nog niemand zag.

## 1. De vraag

Eén vraag: **geeft elk instappunt van het HesPulse-model (A, B, B0, R, K) over meerdere maanden historische candles een netto R boven 0, na kosten en funding, op een manier die niet aan toeval of aan één periode ligt?**

Niet de vraag:
- Of het model live werkt. Dat doet taak 01 (H2) en de live meting.
- Of een regel beter kan. Er wordt niets afgesteld.
- Of de tegenarm (`tegen:`), V1 of P iets doen. Die staan buiten deze toets.

Een uitkomst "te weinig data" of "geen aantoonbaar voordeel" is een geldige uitkomst en geen reden om de regels te wijzigen.

## 2. Periode, markt en coins

**Regels van het model.** De code van `app/model.py` op één vooraf genoteerde commit. Het commit-hash komt bovenaan het resultatenbestand. Verandert `app/model.py` tussen nu en de run, dan geldt de run niet en komt er een nieuwe preregistratie.

**Periode.**
- Instappunten die bekend worden (`known_at`) van **2025-04-01 00:00 UTC** tot en met **2026-10-31 23:59 UTC**: 19 maanden.
- De ontwikkelperiode 2025-01-01 tot en met 2025-03-31 (§8 van `preregistratie.md`) blijft buiten de toets. Candles daarvan dienen alleen als opwarming (4u 60 candles, 1u 120 candles, dag 400 candles). Een scenario dat voor 2025-04-01 ontdekt is, telt mee zodra een instappunt ervan in de periode bekend wordt.
- Alles vanaf **2026-11-01** valt buiten de backtest. Dat is het **perps-tijdperk**: vanaf die dag meet de app op de candles van het contract zelf, en de live meting (taak 01 en 02, de bevriezing tot uiterlijk 2026-11-24) is de vooruit-periode die voor niets anders gebruikt is. Die cijfers komen nooit in de backtest en de backtest nooit in de live cijfers. Ze staan in het resultaat als twee aparte regels.

**Markt.** Candles van de Binance USDⓈ-M perpetuals (`CANDLE_MARKET=perp`), voor de hele periode. De candlecache in `data/candles/` bewaart niet welke markt erin zit. Voor de run gaat de cache van de VPS opnieuw op met `refresh`, en het resultaat noemt de markt en de datum van het ophalen. Een coin zonder perp in een deel van de periode doet pas mee vanaf zijn eerste perp-candle.

**Timeframes.** Dag, 4u, 1u, 15m voor het model (`model.scenarios`), 5m voor vulling en uitkomst (`model.walk_fill`, `model.outcome`). Alleen gesloten candles.

**Coins.** `config.FIXED_COINS` op het moment van de run (7 basiscoins plus de standaardlijst extra coins), zoals §8 van `preregistratie.md` vastlegt. De lijst staat in het resultaat. Er komt geen coin bij of af op grond van een uitkomst.
- Waarschuwing vooraf: een deel van deze lijst kwam er pas bij na een casus (WLD, PUMP, ZEC). Dat is selectie op achteraf. Daarom staat er een beschrijvende regel op alleen `trendlab.LAB_COINS` die ook in `FIXED_COINS` zitten (zie §7).

## 3. Instappunten

Vijf instappunten, elk met de definitie, de stop en het doel uit `app/model.py` en `preregistratie.md` §4.12 en de aanvullende besluiten van 2026-11-03:

| Punt | Wat | Bron |
|---|---|---|
| A | Limiet na sweep, shift en displacement (het plan) | `scenarios()[i]["entry"]` |
| B | Lagere top (long: hogere bodem in discount), naast A | `["b"]` |
| B0 | B zonder premium-eis | `["b0"]` |
| R | Breuk en terugtest op het gebroken niveau | `["r"]` |
| K | Consolidatiebreuk, `CONS_BARS` 8 | `["k"]` |

Vaste regels voor de simulatie:
- **Richting:** de dagbreuk bepaalt de richting (top-down, `DailyBias`), zoals live. Alleen de hoofdarm. De tegenarm staat uit.
- **Poorten zoals bij een luide melding:** niet al door de limiet bij publicatie (`niet_vulbaar`), plan in de goede volgorde (`model_card.plan_ok`), en de BTC-poort (`MODEL_BTC_GATE` aan: een entry tegen BTC 4u eindigt als `btc_tegen`). Het aantal afgewezen entries per poort staat in het resultaat.
- **Publicatie:** op `known_at`, zonder vertraging. De koers bij publicatie is het slot van de laatste gesloten 5m-candle op dat moment.
- **Vulling:** `model.walk_fill` op 5m, geldig tot `expires_at` (24 candles van 15m, 6 uur) of tot een nieuwe 4u-breuk (`context_weg`) of het doel (`weggelopen`). Aanraking vult, zoals live.
- **Uitkomst:** `model.outcome` op 5m vanaf de vulcandle. Stop en doel in één candle telt als stop. Na 7 dagen sluit de meting op het slot (`tijd`).
- **Trades zonder doel** (geen naakte POC en geen range-rand) vallen buiten de toets en staan geteld in het resultaat.
- **`tijd` telt mee** in de toets met de R op het slot. Live valt `tijd` uit de hoofd-R. Hier niet: wie `tijd` weglaat, laat de trades weg die nergens heen gaan, en dat maakt de uitkomst mooier dan ze is. De live-conventie (zonder `tijd`) staat als beschrijvende regel erbij.
- **Eén trade per instappunt per scenario.** Overlappende trades van verschillende punten in hetzelfde scenario tellen per punt apart. Er is geen portefeuille: elk punt is een eigen toets.

## 4. Kosten en funding

Netto R per trade = bruto R, min kosten in R, min funding in R.
- **Kosten:** 0,06% per rondreis (`TRACK_RECORD_COST_PCT`, zoals Bewijs en §8) gedeeld door de stopafstand in procenten. Dat is `track_record._cost_r`.
- **Funding:** de werkelijk betaalde of ontvangen funding tussen vulling en uitgang, uit `/fapi/v1/fundingRate` via `outcome_measure.funding_events` en `derivs.funding_between`, omgerekend naar R met de stopafstand. Long betaalt bij een positieve rate, short ontvangt.
- **Onbekende funding** is nooit 0. Zijn er na twee pogingen meer dan 2% trades zonder funding, dan geldt de run als mislukt en komt er geen oordeel. Anders worden die trades geteld, genoemd en uit de toets gelaten.
- **Stopslip** (`model.slip_r`) is een ondergrens en staat ernaast, niet in de netto R.
- **Gevoeligheid (beschrijvend, geen toets):** dezelfde run met 0,12% per rondreis (de lab-aanname van range-sweep).

## 5. Aantal toetsen

**Vijf toetsen**, één per instappunt: netto R van A, B, B0, R en K elk boven 0. Het register is 5.

Geen toetsen, wel getoond:
- verschillen tussen punten (B min A en dergelijke),
- de gevoeligheidsruns uit §7,
- delen van de periode of van de coins.

Een zesde toets of een andere combinatie, ook achteraf, is niet toegestaan. Correctie voor meervoudig toetsen: Bonferroni voor vijf toetsen, dus de intervallen staan op **99%** (95% gedeeld door 5, tweezijdig; dezelfde regel als de 98,75% voor vier toetsen in `model_measure.LEVEL`).

Het model heeft al eerder naar uitkomsten gekeken: R, K, B0, de BTC-poort en de top-down dagrichting kwamen na casussen in oktober en november 2026. De toets is daarom geen schone eerste toets voor die punten. Het resultaat noemt dat. De ISO-week 2026-W44 bevat twee van die casussen (WLD en SOL, 29 en 30 oktober) en krijgt een eigen beschrijvende regel (zie §7).

## 6. Toetsregels

Een instappunt **slaagt** alleen als alles tegelijk klopt. Dit zijn de regels van `trendlab.evaluate` en `app/replay/stats.py`, met één wijziging: het niveau van de week-bootstrap.

| # | Regel | Waarde |
|---|---|---|
| 1 | Genoeg trades: `MIN_TRADES` | **500** afgeronde trades van dit punt (doel, stop of `tijd`) |
| 2 | Eerste helft boven 0 | gemiddelde netto R boven 0 in de eerste helft (op tijd van de vulling, mediaan als snede); elke helft heeft minstens `MIN_HALF` = 125 trades |
| 3 | Tweede helft boven 0 | idem |
| 4 | Marge per week boven 0 | ondergrens van het **99%-interval** van het gemiddelde, bootstrap per ISO-week (`stats.cluster_bootstrap_mean`, `n_boot` 2000, seed 7, `level=0.99`), weken bepaald op de vulling (`stats.week_key`) |
| 5 | Marge over trades boven 0 | ondergrens van het gewone bootstrap-interval (`structure_review.bootstrap_mean`) boven 0 (als rapportage; regel 4 is strenger en beslist) |
| 6 | Placebo-marge | gemiddelde netto R minus gemiddelde netto R van de placebo's is minstens `MIN_PLACEBO_MARGIN` = **0,03 R** |

Aanvullingen:
- **Placebo:** `model_placebo.placebo_rs`, 10 willekeurige 5m-instappen per echte trade (`N`), tussen 7 dagen en 1 uur voor de vulling, zelfde coin, richting en stop- en doelpercentage, uitkomst met `model.outcome`, zaad uit soort en id. Netto met dezelfde kosten per R als de echte trade.
- **Seeds, aantallen en niveau staan vast** en veranderen niet.
- **Rapportage naast de toets (geen poort):** N, N_eff en weken met trades (`model_measure.n_eff`), langste verliesreeks, grootste daling en het 95e percentiel bij herschikken, gemiddelde zonder de beste 5%, winrate, mediane kosten in R, vulbaarheid, het aantal `niet_vulbaar`, `btc_tegen`, `vervallen`, `weggelopen`, `context_weg`.
- **Slaagt een punt niet op regel 1**, dan is de uitkomst "te weinig data". Er wordt niets versoepeld. Een tweede periode of extra coins om het aantal te halen is niet toegestaan.
- **Wat "geslaagd" betekent:** het punt hield in dit verleden stand onder deze regels. Het is een screening, geen bewijs. Bij vijf toetsen en een eerdere blik op de casussen blijft de kans op toeval aanwezig. "Bewezen" op Bewijs vraagt altijd ook de live bewaking (`track_record.rule_status`).
- **Een slagend punt** gaat niet in de app aan of uit door deze backtest. Elke wissel is een besluit van de CEO met een nieuwe preregistratie.

## 7. Beschrijvende regels (geen toets, nooit een poort)

Staan in het resultaat onder de toets, met de zin "beschrijvend, telt niet mee in het register":
- gevoeligheid kosten 0,12% per rondreis;
- vertraging van 15 minuten tussen `known_at` en publicatie;
- live-conventie zonder `tijd`;
- zonder ISO-week 2026-W44;
- alleen `trendlab.LAB_COINS` die in `FIXED_COINS` zitten;
- per maand en per coin (om te zien of één maand of één coin de uitkomst draagt);
- vergelijking met het live-vooruit cijfer van hetzelfde punt (taak 01), apart gehouden in het perps-tijdperk.

## 8. Wat bestaat en wat ontbreekt

**Hergebruikt (ongewijzigd):**
- `app/model.py`: `scenarios()` is prefix-vast, dus één run over de hele geschiedenis geeft dezelfde scenario's als live stap voor stap; `walk_fill`, `outcome`, `slip_r`.
- `scripts/model_kaarten.py`: het patroon voor frames per coin (`LIMITS`, `fetch`, `collect`) en de prefix-controle `check_prefix`. De controle blijft als steekproef op 30 scenario's in de run.
- `app/replay/candles.py`: `download_candles` en `ensure_candles` met `since` voor de pagina's, de cache per coin en timeframe.
- `app/replay/stats.py`: `week_key`, `cluster_bootstrap_mean`, `cluster_bootstrap_diff`, `cluster_t`.
- `app/replay/trendlab.py`: `MIN_TRADES`, `MIN_HALF`, `MIN_PLACEBO_MARGIN`, `evaluate`.
- `app/model_placebo.py`: `sample_times`, `placebo_rs`.
- `app/model_measure.py`: `n_eff`, `longest_losing_streak`, `max_drawdown`, `shuffled_drawdown_p95`, `mean_without_best`, `entry_trades`, `_cost_r`.
- `app/outcome_measure.py` en `app/derivs.py`: `funding_events`, `funding_between`.
- `app/btc_context.py` (`measure`, `bias`) en `app/poc.py` (`volume_profile`, `poc_of`, `closed_starts`, `first_touch`).
- Patroon van `scripts/strategy_lab.py`: tussenresultaat per coin (`--hervat`), coverage-controle (`check_coverage`), `--opslaan` alleen bij het volledige protocol.

**Ontbreekt (nog te bouwen, alleen meting, zonder dat de regels van het model veranderen):**
1. **Een stuurscript** `scripts/model_backtest.py`. `model_kaarten.py` kijkt maar 14 dagen terug en tekent kaarten. Het script loopt per coin over de hele periode, houdt tussenresultaat per coin vast en schrijft de trades weg.
2. **Dagcandles in de cache.** `BASE_DELTAS` in `app/replay/candles.py` kent geen `1d`; `model.scenarios` heeft ze nodig voor de top-down richting.
3. **Historische naakte POC's.** `model_kaarten.stored_pocs` leest de live database. Voor de backtest moeten de POC-niveaus per dag en week uit de candles volgen, met `touched_at`, en op elk moment alleen de niveaus kennen die toen gesloten en naakt waren. Zonder dit verschilt het doel van A, B, B0, R en K van het live doel. Dit is de grootste bouwstap en krijgt een eigen test op synthetische candles.
4. **BTC-poort op historie.** `btc_context.measure` met de candles van BTC en de coin tot `known_at`, in de stuurlus, met een test dat de poort geen candle na `known_at` leest.
5. **Een evaluatie met `level`.** `trendlab.evaluate` rekent de week-bootstrap vast op 95%. Voor de vijf toetsen komt er een parameter (`level=0.99`), waarbij de default gelijk blijft, zodat het lab en de schaduw niets verschuiven. Plus een placebo-invoer in netto R.
6. **Vulling zonder database.** `model_live.track_entry` schrijft naar de database; de backtest heeft een zuivere variant op `model.walk_fill` en `model.outcome` die de poorten van §3 toepast.
7. **Funding in bulk** per coin en periode in plaats van per trade, met de status 'onbekend' bij falen.
8. **Resultaatbestand en rapport** met per punt de toetsregels van §6, de telling van §5 en de beschrijvende regels van §7.
9. **Een rekentijdmeting** van `model.scenarios` op één coin over 19 maanden (alleen tijd, geen uitkomst), vóór de volledige run. Is de run te zwaar, dan gaat hij per coin en per kwartaal met een prefix-gelijke overlap van de opwarming. Dat verandert geen uitkomst.
10. **Tests** op synthetische candles: geen kijken in de toekomst, geen trade buiten de periode, geen candle van 2026-11-01 of later, funding-teken.

## 9. Protocol (pas na akkoord van de CEO)

1. CEO akkoord op dit document. Het commit-hash van dit bestand en van `app/model.py` komt in het resultaat.
2. De bouwstappen van §8 klaar, getest, zonder één uitkomst te draaien. Alleen de rekentijd van stap 9 en de tests.
3. Candlecache op de VPS verversen (perp, `refresh`), dekking controleren (`check_coverage`).
4. Eén keer draaien:

```bash
.venv/bin/python3 scripts/model_backtest.py --van 2025-04-01 --tot 2026-10-31 --kosten 0.06 --niveau 0.99 --hervat data/backtest_model
```

   (het script bestaat nog niet; de vlaggen leggen de waarden van dit document vast).
5. Resultaat met commando, hash, markt en datum in `docs/onderzoek/bewijsregister.md`. Wat het niet bewijst staat erbij.
6. Een besluit staat in `docs/onderzoek/besluiten.md`. Uitkomsten leiden niet tot afstellen.

## 10. Wat de CEO goedkeurt

- [ ] De vraag en de vijf toetsen (§1, §5), niveau 99%.
- [ ] De periode 2025-04-01 tot en met 2026-10-31 en het perps-tijdperk apart (§2).
- [ ] Perp-candles voor de hele periode en de coins van `FIXED_COINS` (§2).
- [ ] `tijd` telt mee, trades zonder doel uit de toets (§3).
- [ ] Kosten 0,06% plus gemeten funding, onbekende funding nooit 0 (§4).
- [ ] Toetsregels met `MIN_TRADES` 500 en placebo-marge 0,03 R, zonder versoepeling bij te weinig trades (§6).
- [ ] De bouwlijst van §8, in het bijzonder de historische POC's (stap 3).
