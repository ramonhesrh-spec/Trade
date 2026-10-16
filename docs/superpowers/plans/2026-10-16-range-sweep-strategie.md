# Range sweep: onderzoek, proefmotor en kaart Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** De strategie van Cos867 ("Range 40% order block 60%. Liquidation. And back range short or Long / limit orders. HTF analysis. 1h/15m confirmation.") in onze eigen woorden vastleggen, eerst laten zien dat onze detector zijn vijf echte voorbeelden terugvindt, dan de kwaliteit van de stop eerlijk meten in het lab, en pas daarna als proefmotor (alleen de CEO) met range-watch, meldingen, getekende kaart en Bewijs live zetten.

**Architecture:** Zuivere detectoren in `app/replay/rangesweep.py`: range, aanbod- en vraagzones (order blocks als vakken), twee setupfamilies (zone-retest en sweep), bevestiging, HTF en de stops. Een zuivere stopmeting in `app/replay/stopquality.py` (vulling van de limiet, MAE/MFE, doelkans 1R tot 6R, kosten in R, te krappe stop, referentie-uitgangen). Een labfamilie `app/replay/rangesweep_lab.py` met 15 vooraf vastgelegde varianten maal 2 stops, gedraaid via `scripts/strategy_lab.py --familie rangesweep` (hervatbaar, op de VPS). Live: `app/range_watch.py` (ranges volgen en waarschuwen) en `app/range_sweep_live.py` (setup, vulling, volgen, uitkomst), in het patroon van `app/rule_live.py` en `app/structure_live.py`. Kaart en Bewijs lezen alleen pure functies (`app/chance_checks.py`, `app/chance_steps.py`, `app/setup_chart.py`, `app/today.py`, `app/track_record.py`).

**Tech Stack:** Python 3.11, pandas, numpy, SQLite, FastAPI, Jinja2, stdlib unittest, Playwright (alleen als handmatige UI-controle).

**Spec:** dit document (sectie "Lezingen en besluiten") plus de bronnen: het Discord-bericht van Cos867 (screenshot `/root/.claude/uploads/364f7494-289a-5ff0-935d-605be1a79c9c/992113b2-image.png`, 17:28, kanaal trading-floor), de vijf voorbeeldgrafieken in `docs/onderzoek/range-sweep/voorbeelden/` (commit 612cba5) en de besluiten van de gebruiker van 2026-10-16. Achtergrond en eerlijke verwachting: `docs/onderzoek/Crypto edges na kosten onderzoek.md`. Vorig plan in hetzelfde patroon: `docs/superpowers/plans/2026-10-09-hespulse-onderzoek-en-proefmotor.md`.

---

## Wat de vijf voorbeelden laten zien

Afgelezen van de prijsas, dus bij benadering. Tijd is de klok van de telefoon (Nederlandse tijd, CEST); de datum komt van de gebruiker ("vandaag en gisteren") en is nog te bevestigen. De candle rechts is de candle die nog vormt.

| # | Bestand | Coin | Tf | Kant | Instap | Stop | Doel (getekend) | Stop % | Kosten R bij 0,12% | R:R tot doel | Wat er te zien is |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | `arb-2u-short.webp` | ARB (perp) | 2u | short | 0,19903 | 0,20446 | 0,16254 | 2,73% | 0,044 | 6,7 | Range ongeveer 0,17 tot 0,20 sinds de 5e; aanbodzone "Bear OB" 0,1990 tot 0,2045 is drie keer bezocht. Instap bij de terugkeer in de zone, geen prik erboven. 16-10 17:52. |
| 2 | `apt-1u-short.webp` | APT (perp) | 1u | short | 0,8861 | 0,9077 | 0,7191 | 2,44% | 0,049 | 7,7 | Sterke pomp van 0,765 naar 0,884 tegen een rode lijn en een vak boven de koers; vraagzone 0,7350 tot 0,7472 eronder. Geen duidelijke 1u-range. 16-10 14:37. |
| 3 | `apt-2u-long-en-short.webp` | APT (perp) | 2u | short | 0,8729 | 0,8868 | 0,6813 | 1,59% | 0,075 | 13,8 | "Bear OB" op de candle vóór de daling van de 12e, zone 0,8729 tot 0,8868; doel de Bull-zone. Een eerder getekende long (0,7472, stop 0,7191) zonder bekende tijd. 16-10 13:45. |
| 4 | `wld-1u-long.webp` | WLD (spot) | 1u | long | 0,4681 | 0,4513 | 0,56 | 3,59% | 0,033 | 5,5 | De enige echte **sweep**: twee wicks onder de Bullish-zone (rond 0,452) en terug erboven; daarna naar 0,5385. De trade liep al toen de screenshot werd gemaakt. 16-10 11:45. |
| 5 | `aave-30m-short-plan.webp` | AAVE (perp) | 30m | short | 157,01 | 161,16 | 136,64 | 2,64% | 0,045 | 4,9 | Terugkeer naar een gebroken steun rond 157 (rode lijn, roze vak erboven). Het tweede vak rechts is een **gepland** long (136,64, stop 132,77, doel 156,94), geen trade. 15-10 23:42. |

Wat we daaruit overnemen:
- **Zones zijn vakken, geen lijnen.** Een aanbodzone (bearish order block) bovenaan en een vraagzone (bullish order block) onderaan, elk met een boven- en onderkant. De trade gaat bij de terugkeer in de zone aan de rand waar de koers net naar terugkwam, terug door de range.
- **Vier van de vijf zijn een zone-retest zonder sweep** (1, 2, 3, 5); één is een sweep met terugkeer (4). We toetsen daarom twee families: **zone-retest** en **sweep**. Dat zegt ook iets eerlijks: "Liquidation" in het bericht van Cos867 is in zijn eigen voorbeelden maar één keer een zichtbare prik.
- **Timeframes 30m, 1u, 2u** in de voorbeelden, naast de 4u uit zijn tekst ("HTF"). Alle vier gaan in het lab. 30m en 2u maken we door candles samen te voegen (15m naar 30m, 1u naar 2u), zodat de cache niet groeit en lab en live hetzelfde rekenen.
- **De stop ligt telkens net voorbij de buitenkant van de zone** (bij WLD is dat ook de wick van de sweep), 1,6 tot 3,6% van de instap. Primaire regel: buitenkant van de zone plus een kleine buffer. "Voorbij de wick" is een variant voor de sweepfamilie.
- **Hypothese over kosten (gemeten op deze vijf):** bij deze stops kost een rondreis van 0,12% maar 0,03 tot 0,08R. De oude sweep- en rejectietoetsen hadden stops rond 0,4% en verloren al 0,15R aan kosten. Dat is een structurele reden waarom deze familie anders kan uitvallen. Het is een hypothese: vijf achteraf gekozen voorbeelden zijn geen steekproef.
- **Doelen zijn de overkant (5 tot 14R).** Er wordt geen doel opgelegd; de overkant blijft een referentieniveau, en de doelkans-tabel loopt van 1R tot 6R zodat je ziet wat de stop toelaat.
- **Coins buiten onze basisset.** ARB, APT en AAVE zitten in de labset `trendlab.LAB_COINS` (20 coins); WLD niet. Zie "Coins" hieronder.

## Lezingen en besluiten

Cos867 schreef vijf regels. We wachten niet op uitleg van hem: we leggen zelf vast wat we eronder verstaan en toetsen dat. Een **besluit** is een keuze van de gebruiker, een **lezing** een keuze van ons.

| Regel van Cos867 | Wat wij ermee doen | Soort |
|---|---|---|
| "Range 40% order block 60%" | Een **setupscore van 100 punten**: 40 voor de kwaliteit van de range, 60 voor de zone (het order block). Elk onderdeel is een gemeten ✓/✗. Sterk (A, ≥ 80), redelijk (B, ≥ 60), zwak (C, < 60), bewaard als `pass_pct`. Het lab meet per graad of een hogere score een betere stop geeft; nooit als bewezen voorspeller getoond. | Besluit 1 |
| idem, andere lezing | **Positie 40/60**: 40% van de order op de rand van de range, 60% op de zone. Eén extra variant (`RZ_2H_SPLIT`). | Besluit 1, extra variant |
| "Liquidation" | Sweepfamilie: een prik voorbij een rand en een slot terug binnen, **plus** liquidatiedata op dat niveau. | Besluit 2 |
| idem, de grens van de data | Liquidaties (`liquidations_5m`) hebben **geen historie**: alleen live. Het lab toetst de sweep zonder liquidaties. Open interest heeft wel historie (`app/replay/positioning.py`), dus een OI-daling tijdens de prik is een extra variant (`RS_1H_OIFLUSH`). Live staat de liquidatiecontrole erbij als ✓/✗ "niet getoetst, geen historie", buiten de score. | Besluit 2, beperking |
| "And back range short or Long / limit orders" | Limietorder op de **binnenkant van de zone** (zone-retest) of op het midden van het order block (sweep). Richting terug door de range. | Besluit 3, lezing voor de prijs in de zone |
| (stop) | Primair: **voorbij de buitenkant van de zone** plus 0,25 of 0,5 maal de ATR. Variant: voorbij de wick van de sweep plus 0,25 ATR. Daarna `smc_eval.floor_stop` met vaste ondergrens 0,4%. **Geen doel.** | Besluit 3, aangescherpt door de voorbeelden |
| "HTF analysis" | Short mag als de 4u-trend omlaag is (EMA50 onder EMA200 op gesloten 4u-candles, `trendlab.htf_trend`) **of** het midden van de range in de bovenste helft ligt van het hoog-laag van de laatste 180 gesloten 4u-candles (30 dagen). Long gespiegeld. Twee varianten zonder HTF-filter. | Besluit 4, lezing |
| "1h/15m confirmation" | `slot`: geen extra wachten (zone-retest: order bij het naderen; sweep: order na het slot terug binnen op de triggerframe). `choch15`: eerst een 15m-slot voorbij het laatste 15m-zwaaipunt (change of character), dan de order. | Besluit 4 |
| Timeframes | Ranges en zones op **30m, 1u, 2u en 4u**. De sweep en het slot terug binnen op de triggerframe: 30m voor 30m, anders 1u ("1h confirmation"). | Besluit 4, aangevuld door de voorbeelden |
| De app | (a) melding als een setup klaar is, (b) range, zone, sweep, instap en stop **getekend**, (c) een **range-watch** met een eigen budget. | Besluit 5 |
| Voorbeelden | De vijf grafieken zijn de **eerste toets**, vóór een grote labrun: detectie op het moment van de screenshot, uitkomsten later. | Besluit 6 |
| Tempo | Grondig, met poorten tussen de fasen. Ongetest label, eerlijk Bewijs, eerst alleen de CEO. | Besluit 7 |

### Definities (vooraf vastgelegd, bevroren bij poort 1)

**Candles.** Uit de cache van `app/replay/candles.py` (15m, 1u, 4u, van `config.EXCHANGE_ID`, standaard Binance spot). 30m uit 15m en 2u uit 1u met `rangesweep.resample` (alleen volle vakken, vakken op UTC-grenzen zoals Binance). De voorbeelden zijn grotendeels perp-grafieken: kleine prijsverschillen met spot, daarom vergelijken we op structuur, niet op de tick. ATR is Wilder-14 (`replay.lab.add_indicators`). Een candle is bekend op timestamp + timeframe.

**Range (op timeframe T).** Op het slot van candle i: zwaaipunten met `trendlab._pivot_flags` (n = 3, strikt links, gelijk of lager rechts; bekend op p + 3) in de laatste 120 candles (30m, 1u) of 90 (2u, 4u). De grootste groep zwaaipunt-hogen binnen 0,5 ATR(T) is de bovenrand, idem voor de lagen; bij gelijkstand de groep met het laatste punt. Minstens 3 per rand. Bovenrand = hoogste hoog van de groep, onderrand = laagste laag. Breedte 3 tot 15 ATR(T). Geen slot meer dan 0,25 ATR(T) buiten de range sinds het eerste zwaaipunt van de range.

**Zone (aanbod of vraag, op timeframe T).** Een aanbodzone ("bear") ontstaat als een slot op candle m minstens 1,0 ATR(T) onder het laag van de laatste groene candle k komt, met k hooguit 5 candles vóór m. Zone = laag tot hoog van candle k; bekend op m. Vraagzone ("bull") gespiegeld (laatste rode candle, slot minstens 1,0 ATR boven zijn hoog). Een nieuwe zone die voor meer dan de helft overlapt met een nog actieve zone van dezelfde soort telt niet (de oudere blijft). Een zone is actief tot een slot voorbij de buitenkant (aanbod: boven het hoog) of tot 200 candles na m. Buitenkant = hoog bij aanbod, laag bij vraag; binnenkant = de andere kant.

**Familie zone-retest.** Een actieve aanbodzone in of boven het bovenste kwart van een actieve range (binnenkant ≥ bovenrand − 0,25 maal de breedte), en de koers nadert van onderen: slot hooguit 1,0 ATR(T) onder de binnenkant en het hoog nog onder de binnenkant. Short-limiet op de binnenkant. Vraagzone onderaan gespiegeld voor long. Eén setup per zone, bij de eerste nadering waarop alle voorwaarden kloppen. Met `choch15` wacht de order tot de koers de zone raakte en daarna een 15m-candle sluit voorbij het laatste 15m-zwaaipunt (n = 2) van vóór het uiterste van die aanraking, binnen 24 15m-candles.

**Familie sweep.** Een candle op de triggerframe (30m voor T = 30m, anders 1u) prikt minstens 0,1 ATR voorbij een rand van de range die bekend was bij het openen, en binnen 6 triggercandles sluit er een weer binnen; komt het uiterste meer dan 1,5 ATR(T) voorbij de rand, dan is het een uitbraak. Eén sweep per range per kant, en dezelfde kant op dezelfde coin telt 24 triggercandles niet. Het order block is de laatste groene (short) of rode (long) 15m-candle op of vóór de 15m-candle met het uiterste, hooguit 8 terug; geen gevonden: de uiterste candle zelf. Limiet = midden van het order block. Met `choch15` wacht de order op een 15m-slot voorbij het laatste 15m-zwaaipunt van vóór het uiterste, binnen 24 15m-candles.

**Limiet die niet geldig is.** Een limiet aan de verkeerde kant van de koers bij het plaatsen (short: op of onder het laatste slot) vervalt; geen geldige limiet, geen setup.

**Stops.** `zone_025` en `zone_05`: buitenkant van de zone plus 0,25 of 0,5 maal de ATR (van T bij zone-retest, van de triggerframe bij sweep). `wick_025`: uiterste van de sweep plus 0,25 ATR (alleen sweep). `zone_0`: buitenkant zonder buffer, alleen ter vergelijking. Daarna `smc_eval.floor_stop(direction, geplande instap, stop, min_pct=0.4)`.

**Vulling en verval (op 15m).** Short-limiet vult als het hoog de limiet raakt, tegen de limietprijs; long gespiegeld. De order staat 96 15m-candles (24 uur). Vervalt eerder als een candle al voorbij de stop opent ("stop voor vulling") of als de koers het midden van de range raakt ("weggelopen").

**Meting na de vulling (zonder doel).** Tot de stop of 672 15m-candles (7 dagen). In de vulcandle telt alleen het nadeel. Een candle die stop en een R-niveau raakt telt als stop. Een gat door de stop vult op de open. R-eenheid: het risico dat echt genomen is (gewogen instap tot de stop).

**Setupscore (100 punten, Besluit 1).**

| Onderdeel | Gemeten kenmerk | Punten |
|---|---|---|
| Range | Beide randen minstens 4 keer aangeraakt | 10 |
| Range | Breedte tussen 4 en 10 ATR | 10 |
| Range | Range minstens 48 candles oud (30m, 1u) of 36 (2u, 4u), van het eerste zwaaipunt tot de setup | 10 |
| Range | Schone randen: spreiding binnen elke rand hooguit 0,25 ATR | 10 |
| Zone | Echte tegenkaars vlak voor de beweging (sweep: een groene of rode 15m-candle gevonden; zone-retest: de beweging kwam binnen 2 candles) | 15 |
| Zone | Sterke beweging weg (minstens 1,5 ATR; sweep: van het uiterste tot het slot bij het plaatsen; zone-retest: grootste slot weg van de zone tot de bevestiging) | 15 |
| Zone | Zone vers: hooguit één eerdere aanraking (sweep: na het eerste slot voorbij het order block raakte geen candle het weer) | 15 |
| Zone | Zone dun: hooguit 1,5 ATR dik | 15 |

### Varianten (15, samen 30 toetsen)

| Naam | Familie | Range/zone | Instap | Bevestiging | HTF | OI-daling | Getoetste stops |
|---|---|---|---|---|---|---|---|
| `RZ_30M` | zone-retest | 30m | binnenkant zone | slot | ja | nee | zone_025, zone_05 |
| `RZ_1H` | zone-retest | 1u | binnenkant zone | slot | ja | nee | zone_025, zone_05 |
| `RZ_2H` | zone-retest | 2u | binnenkant zone | slot | ja | nee | zone_025, zone_05 |
| `RZ_4H` | zone-retest | 4u | binnenkant zone | slot | ja | nee | zone_025, zone_05 |
| `RZ_1H_CHOCH` | zone-retest | 1u | binnenkant zone | choch15 | ja | nee | zone_025, zone_05 |
| `RZ_2H_CHOCH` | zone-retest | 2u | binnenkant zone | choch15 | ja | nee | zone_025, zone_05 |
| `RZ_2H_ZONDERHTF` | zone-retest | 2u | binnenkant zone | slot | nee | nee | zone_025, zone_05 |
| `RZ_2H_SPLIT` | zone-retest | 2u | 40% rand, 60% zone | slot | ja | nee | zone_025, zone_05 |
| `RS_30M` | sweep | 30m | midden order block | slot | ja | nee | zone_025, wick_025 |
| `RS_1H` | sweep | 1u | midden order block | slot | ja | nee | zone_025, wick_025 |
| `RS_2H` | sweep | 2u | midden order block | slot | ja | nee | zone_025, wick_025 |
| `RS_4H` | sweep | 4u | midden order block | slot | ja | nee | zone_025, wick_025 |
| `RS_1H_CHOCH` | sweep | 1u | midden order block | choch15 | ja | nee | zone_025, wick_025 |
| `RS_1H_ZONDERHTF` | sweep | 1u | midden order block | slot | nee | nee | zone_025, wick_025 |
| `RS_1H_OIFLUSH` | sweep | 1u | midden order block | slot | ja | ja | zone_025, wick_025 |

OI-daling: open interest op het laatste 5m-punt vóór het slot terug binnen minstens 1,0% lager dan op het laatste punt vóór het openen van de sweepcandle (zelfde 1,0% en 5 minuten vertraging als `replay.lab.OI_MOVE_PCT` en `SAMPLE_LAG`). Setups zonder OI-data vallen buiten die variant; het aantal staat in de uitvoer.

**Register.** Er zijn al ongeveer 34 varianten op deze data bekeken (onderzoeksrapport sectie 4). Deze familie voegt 30 toetsen toe: 64 in totaal. De beste van 64 nulvarianten haalt ongeveer t ≈ 2,4; de horde voor een voordeel is daarom **t ≥ 3,4** (week-geclusterd), naast de bestaande `trendlab.evaluate`.

### Coins

- **Lab:** de 20 coins van `trendlab.LAB_COINS` (BTC, ETH, SOL, BNB, XRP, ADA, DOGE, AVAX, LINK, DOT, LTC, BCH, NEAR, ATOM, UNI, AAVE, SUI, INJ, APT, ARB), met `--alleen-volledig` als overlevingscontrole. Vast vóór de run. We voegen **geen** coin toe omdat hij in een winnend voorbeeld staat (WLD): dat is selectie op uitkomst.
- **Misser-controle:** elke coin uit de CSV, ook WLD.
- **Live:** dezelfde 20 als het lab, zodat live en lab dezelfde markten vergelijken. Een extra coin (via `EXTRA_COINS` of later een eigen lijst) krijgt pas een kaart na een eigen labrun op die coin, en heet tot dan "niet in het lab".
- **Data:** de sandbox heeft geen verbinding met Binance. Alle runs met echte candles draait de gebruiker op de VPS met de commando's uit taak 12; de cache (`data/candles/`) en de tussenresultaten per coin maken een onderbroken run hervatbaar.

### Wat we meten en wanneer het telt

Per setup en per stop (zonder doel): stopafstand in % en in ATR, kosten in R bij 0,12% per rondreis, MAE en MFE in R, uren tot de stop, of +1R tot en met +6R vóór de stop gehaald werden (de **doelkans-tabel**), of de stop raakte, of de stop **te krap** was (na de stop binnen 12 uur een 15m-slot terug in de range én binnen 48 uur de koers op +1R vanaf de instap), en ter vergelijking de netto R bij drie referentie-uitgangen: midden van de range, overkant van de range en een meelopende stop op 3 maal de 1u-ATR. De meelopende stop is de vooraf gekozen referentie voor de strenge toets; de andere twee staan ernaast, nooit als kop.

**Toets op stopkwaliteit (de kop).** Een variant met één stop slaagt alleen als alles klopt:
1. minstens 300 gevulde setups en minstens 80 verschillende weken;
2. mediane kosten hooguit 0,10R;
3. kans op +1R vóór de stop in de eerste en tweede helft verschilt hooguit 10 procentpunt;
4. in 6 tijdsblokken wijkt geen blok meer dan 15 procentpunt af van het totaal;
5. tegen willekeurige instappen (een willekeurig slot op de triggerframe binnen een actieve range van dezelfde coin en timeframe, zelfde kant, stop op dezelfde afstand in 1u-ATR, zelfde meting): de kans op +1R vóór de stop is minstens 5 procentpunt hoger en de ondergrens van het 95%-interval per week van het verschil ligt boven 0;
6. hooguit 25% van de geraakte stops is te krap.

**Toets op een voordeel (ernaast).** `trendlab.evaluate` op de netto R bij de meelopende referentie-uitgang en daarbovenop t ≥ 3,4 per week. Alleen dit mag ooit "Bewezen" op Bewijs opleveren, via `track_record.rule_status`.

**Score.** Per graad (A, B, C) de kans op +1R vóór de stop en het stop-percentage. Beschrijvend, nooit een poort.

**Steekproef.** Bij een kans rond 0,5 en een effectieve steekproef van ongeveer 150 (weken als clusters) is het 95%-interval ongeveer ± 8 procentpunt. Schatting vooraf (eigen, niet gemeten): zone-retest op 30m en 1u 800 tot 2.000 gevulde setups over 20 coins en 3 jaar, op 2u 400 tot 900, op 4u 150 tot 400; sweep ongeveer de helft daarvan. Een variant onder 300 vullingen heet "te weinig data".

### Stopcriteria (vóór de run vastgelegd)

- **S0 (poort 0, voorbeelden).** Minder dan 3 van de 5 voorbeelden (en later minder dan 60% van alle voorbeelden, bij minstens 10) wordt na hooguit twee definitierondes door minstens één variant gezien op het moment van de screenshot: onze lezing is niet zijn strategie. Geen labrun; we schrijven op welke regel verschilt.
- **S1 (poort 1, met het oog).** Minder dan 80% van 30 willekeurige getekende setups is volgens de gebruiker "klopt": detector repareren (vóór het bevriezen), hooguit twee rondes, anders stoppen.
- **S2 (poort 3, lab).** Geen enkele van de 30 toetsen slaagt op stopkwaliteit: geen live setupmotor. De range-watch mag blijven, als informatie.
- **S3 (lab).** Bij alle 30 toetsen zijn de mediane kosten hoger dan 0,10R: stoppen zoals S2.
- **S4 (live).** De laatste 30 afgeronde proeftrades zijn samen netto negatief bij de referentie-uitgang: de motor zet zichzelf uit.
- **S5 (live).** Na 50 vullingen ligt de live kans op +1R vóór de stop buiten het 95%-interval van het lab: terug naar alleen de CEO en "wijkt af van het lab" op Bewijs.

### Fasen en poorten

| Fase | Taken | Poort naar de volgende fase |
|---|---|---|
| 0 Voorbeelden | 1 tot 8 | Poort 0a: misser-controle op de 5 voorbeelden, minstens 3 gezien (S0). Poort 0b: de 5 getekend naast de screenshots, de gebruiker bevestigt range en zones. |
| 1 Met het oog | 8 | Poort 1: 30 willekeurige getekende setups, minstens 80% "klopt" (S1); daarna bevriest de pre-registratie (commit-hash in het document). |
| 2 Lab | 9 tot 12 | Poort 2: bevroren, run op de VPS met `--kosten 0.12`; poort 3: minstens één toets slaagt op stopkwaliteit (S2, S3). |
| 3 Proef | 13 tot 17 | Poort 4: de CEO beslist over leerlingen, pas na 50 live vullingen binnen het lab-interval. |

Taken 13 tot 17 mogen naast fase 2 gebouwd worden (de code laat zonder geslaagde toets geen nieuwe setups toe), maar worden niet uitgerold als S2 of S3 geldt.

---

## Global Constraints

- Kosten in het lab voor deze familie: 0,12% per rondreis (`--kosten 0.12`), gevoeligheid 0,16% (niet opslaan). `--opslaan` weigert onder 0,12.
- Stop-ondergrens 0,4% via `smc_eval.floor_stop(direction, ref, stop, min_pct=0.4)`; lab en live gebruiken `rangesweep.MIN_STOP_PCT = 0.4`, niet de omgevingswaarde. Een te krappe stop wordt verbreed, nooit geweigerd.
- Geen doel: `signals.take_profit` blijft `None`. Meldingen zeggen "doel kies je zelf" en tonen het midden en de overkant van de range als referentie.
- `trade_type = 'range_sweep'` voor beide families, `pattern_name` = de variantnaam. Label "ongetest" tot `track_record.rule_status` "Bewezen" zegt.
- Alleen de CEO tot de CEO beslist (`config.RANGE_SWEEP_PUBLIC`, standaard `false`); `rule_live.CEO_ONLY_TYPES` bevat `range_sweep` zolang dat zo is.
- Proefsignalen met `chain_it=False`.
- Bewijs telt alleen `take_profit` en `stop_loss`. Deze soort zet `auto_outcome` bij het einde van de referentie-uitgang: R > 0 is `take_profit`, anders `stop_loss`, met de echte R in `trade_results`. Bewijs zegt erbij: "R gemeten bij de referentie-uitgang (meelopende stop 3 ATR op 1u), niet bij jouw eigen doel".
- Nieuwe kans: `push_notify.send_kans_push` (budget, tegenstrijdigheid, pauze). Vulling en stop geraakt: `push_notify.send_push`. Range-watch: eigen budget van 3 stille pushes per gebruiker per 24 uur, pauze geldt.
- Sterk (A) luid, redelijk (B) stil, zwak (C) pas een melding als de limiet vult.
- Gemeten kenmerken zijn ✓/✗; de doelkans uit het lab heet "historische kans (lab)", nooit een belofte.
- Schemawijzigingen in `app/schema.sql` én `db._migrate()`; nieuwe tabellen, geen nieuwe kolommen op `signals`.
- Commentaar legt het waarom uit. Geen afstelling op labuitkomsten. Na poort 1 wijzigt geen constante uit `docs/onderzoek/range-sweep/preregistratie.md`.
- Voor elke taak blijft groen: `SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t . -v`. Raak `app/setup_eval.py` en `app/smc_eval.py` niet aan.
- Telefoon eerst; elke UI-taak eindigt met een Playwright-controle op 390 px breed tegen een scratch-database.

## Bestandsoverzicht

| Bestand | Verantwoordelijkheid | Taken |
|---|---|---|
| `docs/onderzoek/range-sweep/voorbeelden.md`, `handtrades.csv` (nieuw) | Lezing van de vijf grafieken, seed-CSV | 1 |
| `docs/onderzoek/range-sweep/preregistratie.md`, `resultaten.md`, `missers.md` (nieuw) | Definities, sjabloon, log | 2 |
| `app/misser.py`, `scripts/range_sweep_examples.py` (nieuw) | CSV met optionele stop en doel, concept uit berichten | 3 |
| `app/replay/rangesweep.py` (nieuw) | Resample, range, zones, setups, stops, diagnose | 4, 5 |
| `app/chance_checks.py` | Setupscore 40/60 | 6 |
| `scripts/misser_check.py` | `--motor rangesweep`, `--venster-uren` | 7 |
| `app/setup_chart.py`, `scripts/range_sweep_gallery.py` (nieuw) | Getekende setup, galerij (voorbeelden en willekeurig) | 8 |
| `app/replay/stats.py`, `app/replay/stopquality.py` (nieuw) | Cluster-t, vulling, meting, samenvatting, placebo, toets | 9, 10 |
| `app/replay/rangesweep_lab.py` (nieuw) | Varianten, run per coin, oordeel, keuze voor live | 11 |
| `scripts/strategy_lab.py`, `app/track_record.py` | `--familie rangesweep`, hervatten, rapport, opslaan, labels | 12 |
| `app/schema.sql`, `app/db.py`, `app/repo.py`, `app/config.py`, `app/rule_live.py` | Tabellen, opties, CEO-only | 13 |
| `app/range_watch.py` (nieuw) | Ranges volgen en waarschuwen | 14 |
| `app/range_sweep_live.py` (nieuw), `app/market_scanner.py`, `app/level_check.py` | Proefmotor | 15 |
| `app/chance_steps.py`, `app/today.py`, `web/main.py`, templates, `style.css` | Kaart, stappen, chips, open kansen, Ranges-tab | 16 |
| `app/track_record.py`, `app/kans_view.py`, `web/main.py`, `bewijs.html`, `kans.html`, `CLAUDE.md` | Bewijs, kanspagina, documentatie | 17 |

**Parallel.** Taken 1, 2 en 3 kunnen naast elkaar en naast 4. Taak 6 kan naast 5 (de featurenamen staan hieronder vast). Taken 9 en 10 kunnen naast 4 tot 8 (eigen bestanden; ze gebruiken alleen `rangesweep.MIN_STOP_PCT` en de fixture). Taak 13 kan naast fase 2. Gedeelde bestanden, dus na elkaar: 4 en 5 (`rangesweep.py`), 9 en 10 (`stopquality.py`), 12 en 17 (`track_record.py`), 14 en 15 (`market_scanner.py`), 16 en 17 (`web/main.py`, templates).

---

### Task 1: Voorbeelden en seed-CSV vastleggen

**Files:**
- Create: `docs/onderzoek/range-sweep/voorbeelden.md`
- Create: `docs/onderzoek/range-sweep/handtrades.csv`
- Bestaand: `docs/onderzoek/range-sweep/voorbeelden/*.webp` (al gecommit in 612cba5; niet opnieuw toevoegen)

**Interfaces:**
- Produces: `handtrades.csv` in het formaat van taak 3 (kolommen `coin,richting,tijd,instap,stop,doel,uitkomst,bron,notitie,tf`). Taak 7 leest het.

- [ ] **Step 1: Schrijf `voorbeelden.md`**

Neem de tabel "Wat de vijf voorbeelden laten zien" en de lijst eronder uit dit plan letterlijk over, met bovenaan:

```markdown
# Range sweep: de vijf voorbeelden van 15 en 16 oktober 2026

Bron: de gebruiker, grafieken van TradingView met het long/short-gereedschap. Datums van de gebruiker ("vandaag en gisteren"), nog te bevestigen.
Tijden zijn de klok van de telefoon (CEST, UTC+2) op het moment van de screenshot; de candle rechts vormt nog. De aftelklok rechts op de prijsas
geeft hoe lang die candle nog loopt: ARB 2u 01:07:28 om 17:52 (candle 15:00 tot 17:00 UTC), APT 1u 22:32 om 14:37 (12:00 tot 13:00 UTC),
APT 2u 01:14:13 om 13:45 (11:00 tot 13:00 UTC), WLD 1u 14:26 om 11:45 (09:00 tot 10:00 UTC), AAVE 30m 17:38 om 23:42 (21:30 tot 22:00 UTC).
Deze trades zijn zo recent dat de uitkomst nog open kan zijn. De eerste toets kijkt alleen of de detector de setup ziet op het moment van de
screenshot; de uitkomst lezen we pas later en nooit om een regel aan te passen.

Niet in de CSV: de eerdere APT-long uit `apt-2u-long-en-short.webp` (instap 0,7472, stop 0,7191) omdat de tijd niet te lezen is, en het geplande
AAVE-long (136,64, stop 132,77, doel 156,94) omdat het een plan is en geen trade. Geeft de gebruiker de tijd van de APT-long, dan komt hij erbij.
```

- [ ] **Step 2: Schrijf de seed-CSV**

`docs/onderzoek/range-sweep/handtrades.csv`, precies:

```
coin,richting,tijd,instap,stop,doel,uitkomst,bron,notitie,tf
ARB,short,2026-10-16 17:52,0.19903,0.20446,0.16254,,arb-2u-short.webp,"datum van de gebruiker, te bevestigen; Bear OB 0.1990-0.2045; range 0.17-0.20; perp",2h
APT,short,2026-10-16 14:37,0.8861,0.9077,0.7191,,apt-1u-short.webp,"datum te bevestigen; pomp tegen een bearish vak; vraagzone 0.7350-0.7472; perp",1h
APT,short,2026-10-16 13:45,0.8729,0.8868,0.6813,,apt-2u-long-en-short.webp,"datum te bevestigen; Bear OB 0.8729-0.8868; doel Bull-zone; perp",2h
WLD,long,2026-10-16 11:45,0.4681,0.4513,0.56,,wld-1u-long.webp,"datum te bevestigen; spot; sweep onder de Bullish-zone tot ca. 0.452; trade liep al, instap ca. 15-10",1h
AAVE,short,2026-10-15 23:42,157.01,161.16,136.64,,aave-30m-short-plan.webp,"datum te bevestigen; terugkeer naar gebroken steun ca. 157; perp",30m
```

- [ ] **Step 3: Commit**

```bash
git add docs/onderzoek/range-sweep/voorbeelden.md docs/onderzoek/range-sweep/handtrades.csv
git commit -m "docs: lezing van de vijf range sweep-voorbeelden en de seed-CSV"
```

---

### Task 2: Pre-registratie, resultatensjabloon en misserlog

**Files:**
- Create: `docs/onderzoek/range-sweep/preregistratie.md`
- Create: `docs/onderzoek/range-sweep/resultaten.md`
- Create: `docs/onderzoek/range-sweep/missers.md`

**Interfaces:**
- Produces: een fenced block met de taal-tag `prereg-constants`; taak 11 toetst dat elke regel `module.NAAM = waarde` gelijk is aan de constante in code. De markers `<!-- resultaten:begin -->` en `<!-- resultaten:end -->` in `resultaten.md`; taak 12 schrijft daartussen.

- [ ] **Step 1: Schrijf de pre-registratie**

Neem de secties "Lezingen en besluiten", "Definities", "Varianten", "Coins", "Wat we meten en wanneer het telt", "Stopcriteria" en "Fasen en poorten" van dit plan letterlijk over. Zet bovenaan:

```markdown
# Range sweep: pre-registratie

Status: concept (definities mogen nog wijzigen op grond van de voorbeelden, niet op grond van resultaten)
Bevroren op: (datum en commit-hash, in te vullen bij poort 1)
```

Voeg onderaan het constantenblok toe, precies zo:

````markdown
```prereg-constants
rangesweep.PIVOT_N = 3
rangesweep.TOUCHES = 3
rangesweep.CLUSTER_ATR = 0.5
rangesweep.RANGE_MIN_ATR = 3.0
rangesweep.RANGE_MAX_ATR = 15.0
rangesweep.CONTAIN_ATR = 0.25
rangesweep.DISP_BARS = 5
rangesweep.DISP_ATR = 1.0
rangesweep.ZONE_MAX_AGE = 200
rangesweep.ZONE_OVERLAP = 0.5
rangesweep.APPROACH_ATR = 1.0
rangesweep.EDGE_BAND = 0.25
rangesweep.SWEEP_MIN_ATR = 0.1
rangesweep.SWEEP_MAX_ATR = 1.5
rangesweep.RETURN_MAX_BARS = 6
rangesweep.SWEEP_COOLDOWN = 24
rangesweep.OB_SEARCH_15M = 8
rangesweep.CHOCH_PIVOT_N = 2
rangesweep.CHOCH_MAX_BARS = 24
rangesweep.HTF_LOOKBACK_4H = 180
rangesweep.EDGE_WEIGHT = 0.4
rangesweep.OB_WEIGHT = 0.6
rangesweep.MIN_STOP_PCT = 0.4
stopquality.TTL_15M = 96
stopquality.HORIZON_15M = 672
stopquality.TIGHT_BACK_15M = 48
stopquality.TIGHT_WIN_15M = 192
stopquality.TRAIL_K = 3.0
stopquality.MIN_FILLS = 300
stopquality.MIN_WEEKS = 80
stopquality.MAX_MEDIAN_COST_R = 0.10
stopquality.MAX_HALF_DIFF = 0.10
stopquality.MAX_BLOCK_DIFF = 0.15
stopquality.N_BLOCKS = 6
stopquality.MIN_PLACEBO_EDGE = 0.05
stopquality.MAX_TIGHT_RATE = 0.25
rangesweep_lab.PRIOR_VARIANTS = 34
rangesweep_lab.EDGE_T_MIN = 3.4
rangesweep_lab.LAB_COST_PCT = 0.12
```
````

- [ ] **Step 2: Schrijf het resultatensjabloon**

```markdown
# Range sweep: resultaten

Pre-registratie: docs/onderzoek/range-sweep/preregistratie.md (bevroren op commit ...). Dit document wordt gevuld door
`scripts/strategy_lab.py --familie rangesweep --rapport docs/onderzoek/range-sweep/resultaten.md`; tekst buiten de markers schrijft een mens.

## Hoe te lezen
- De kop is de stopkwaliteit: hoe vaak de stop raakt, wat hij kost in R en hoe vaak +1R tot +6R vóór de stop kwamen.
- De netto R bij de referentie-uitgangen staat ernaast. Geen van die uitgangen is jouw doel.
- 30 toetsen in deze familie, 64 in het register. Eén geslaagde toets is nog geen bewijs.

<!-- resultaten:begin -->
(nog geen run)
<!-- resultaten:end -->

## Oordeel (na de run, door een mens)
- Stopcriteria S2 en S3: ...
- Gekozen variant en stop voor de proef (regel: geslaagd, meeste vullingen, dan laagste mediane kosten, dan de bredere stop): ...
```

De drie puntjes onder "Oordeel" vult een mens na de run; het zijn invulvakken, geen ontbrekende plandelen.

- [ ] **Step 3: Schrijf de misserlog**

```markdown
# Range sweep: voorbeelden en missers

Elk voorbeeld komt hier één keer, met wat de detector deed. We kijken alleen of de detector het voorbeeld ziet, nooit naar de uitkomst:
anders stellen we af op winnaars die achteraf gekozen zijn.

| # | Coin | Kant | Tijd (NL) | Tf | Bron | Gezien door | Weigerende regel | Gemeten waarde | Besluit |
|---|---|---|---|---|---|---|---|---|---|

## Vergelijking met het oog (poort 0b)
| # | Onze range | Onze zone | Zone op de screenshot | Klopt | Opmerking |
|---|---|---|---|---|---|

## Definitierondes (hooguit twee, alleen vóór poort 1)
| Ronde | Datum | Regel | Was | Wordt | Reden (welke voorbeelden) |
|---|---|---|---|---|---|
```

- [ ] **Step 4: Commit**

```bash
git add docs/onderzoek/range-sweep/preregistratie.md docs/onderzoek/range-sweep/resultaten.md docs/onderzoek/range-sweep/missers.md
git commit -m "docs: pre-registratie range sweep, resultatensjabloon en misserlog"
```

---

### Task 3: Handtrades-CSV met optionele stop en doel, concept uit de berichten

**Files:**
- Modify: `app/misser.py`, `scripts/misser_check.py` (alleen het printen van lege waarden)
- Create: `scripts/range_sweep_examples.py`
- Test: `tests/test_misser.py`

**Interfaces:**
- Produces: `misser.parse_rows(text)` geeft `stop` en `target` als `float` of `None`, plus `source`, `note`, `tf` (string, leeg als de kolom ontbreekt; `tf` in `("", "30m", "1h", "2h", "4h")`). `misser.draft_rows(messages: list[dict]) -> list[dict]` met sleutels `coin, richting, tijd, instap, bron, notitie`.

- [ ] **Step 1: Schrijf de falende tests**

Voeg toe aan `tests/test_misser.py` in `ParseRowsTest`:

```python
    def test_empty_stop_and_target_become_none(self):
        rows = misser.parse_rows(HEAD + "DOGE,short,2026-10-15 17:20,0.199,,,\n")
        self.assertIsNone(rows[0]["stop"])
        self.assertIsNone(rows[0]["target"])
        self.assertEqual(rows[0]["entry"], 0.199)

    def test_extra_columns_are_kept(self):
        text = "coin,richting,tijd,instap,stop,doel,uitkomst,bron,notitie,tf\nARB,short,2026-10-16 17:52,0.19903,0.20446,0.16254,,arb.webp,top,2h\n"
        r = misser.parse_rows(text)[0]
        self.assertEqual((r["source"], r["note"], r["tf"]), ("arb.webp", "top", "2h"))

    def test_missing_extra_columns_are_empty(self):
        r = misser.parse_rows(HEAD + "BTC,long,2026-10-08 14:30,100,95,115,winst\n")[0]
        self.assertEqual((r["source"], r["note"], r["tf"]), ("", "", ""))

    def test_bad_tf_names_the_line(self):
        text = "coin,richting,tijd,instap,stop,doel,uitkomst,tf\nBTC,long,2026-10-08 14:30,100,,,,3h\n"
        with self.assertRaisesRegex(ValueError, "regel 2: tf"):
            misser.parse_rows(text)

    def test_seed_csv_parses(self):
        rows = misser.parse_rows((ROOT / "docs" / "onderzoek" / "range-sweep" / "handtrades.csv").read_text(encoding="utf-8"))
        self.assertEqual([r["coin"] for r in rows], ["ARB", "APT", "APT", "WLD", "AAVE"])
        self.assertEqual(rows[4]["at"].isoformat(), "2026-10-15T21:42:00+00:00")
        self.assertEqual({r["tf"] for r in rows}, {"30m", "1h", "2h"})
```

En een nieuwe klasse:

```python
class DraftRowsTest(unittest.TestCase):
    def test_draft_takes_coin_direction_time_and_first_price(self):
        msgs = [{"id": 7, "received_at": "2026-10-15T15:28:00+00:00", "raw_text": "Entry was up top 0.19900 Now 0.19550", "coin": "ARB", "direction": "short"}]
        r = misser.draft_rows(msgs)[0]
        self.assertEqual((r["coin"], r["richting"], r["tijd"], r["instap"]), ("ARB", "short", "2026-10-15 17:28", "0.199"))
        self.assertEqual(r["bron"], "bericht 7")

    def test_draft_skips_messages_without_coin_or_direction(self):
        self.assertEqual(misser.draft_rows([{"id": 1, "received_at": "2026-10-15T15:28:00+00:00", "raw_text": "gm", "coin": None, "direction": None}]), [])
```

- [ ] **Step 2: Run de tests en zie ze falen**

Run: `python3 -m unittest tests.test_misser -v`
Expected: FAIL (`KeyError: 'source'`, `ValueError` op een leeg getal, `AttributeError: draft_rows`).

- [ ] **Step 3: Implementeer**

In `app/misser.py`:

```python
import re

OPTIONAL = ["bron", "notitie", "tf"]
TIMEFRAMES = ("", "30m", "1h", "2h", "4h")
_PRICE = re.compile(r"\d+(?:[.,]\d+)?")


def _maybe_number(raw: str):
    """Leeg veld: None. Voorbeelden uit de community hebben vaak alleen een instap; een verzonnen stop zou de misser-controle vervuilen."""
    return None if not raw.strip() else _number(raw)
```

In `parse_rows`, na `pos`: `opt = {c: names.index(c) for c in OPTIONAL if c in names}`, en de rij-opbouw wordt:

```python
            tf = cells[opt["tf"]].strip().lower() if "tf" in opt else ""
            if tf not in TIMEFRAMES:
                raise ValueError(f"tf moet leeg of een van 30m, 1h, 2h, 4h zijn, kreeg '{tf}'")
            rows.append({
                "coin": coin, "direction": direction, "at": _local_to_utc(cells[pos["tijd"]]),
                "entry": _number(cells[pos["instap"]]), "stop": _maybe_number(cells[pos["stop"]]), "target": _maybe_number(cells[pos["doel"]]),
                "outcome": cells[pos["uitkomst"]].strip(),
                "source": cells[opt["bron"]].strip() if "bron" in opt else "", "note": cells[opt["notitie"]].strip() if "notitie" in opt else "", "tf": tf,
            })
```

Onderaan:

```python
def draft_rows(messages: list[dict]) -> list[dict]:
    """Conceptregels voor de handtrades-CSV uit opgeslagen berichten: coin en kant zoals de pipeline ze las, tijd in Nederlandse tijd, de eerste
    prijs uit de tekst als instap. Stop, doel en uitkomst blijven leeg: die vult de gebruiker, wij raden niet."""
    out = []
    for m in messages:
        if not m.get("coin") or m.get("direction") not in ("long", "short"):
            continue
        at = datetime.fromisoformat(m["received_at"]).astimezone(LOCAL_TZ)
        price = _PRICE.search(m.get("raw_text") or "")
        out.append({"coin": m["coin"].upper(), "richting": m["direction"], "tijd": at.strftime("%Y-%m-%d %H:%M"),
                    "instap": f"{_number(price.group(0)):g}" if price else "", "bron": f"bericht {m['id']}", "notitie": (m.get("raw_text") or "")[:120]})
    return out
```

In `scripts/misser_check.py:run_csv` met `--alleen-parsen`: print stop en doel als `-` als ze `None` zijn (`f"{r['stop']:g}" if r["stop"] is not None else "-"`).

`scripts/range_sweep_examples.py`:

```python
"""Concept voor de handtrades-CSV uit de opgeslagen berichten op de VPS. Draai daar:

  .venv/bin/python3 scripts/range_sweep_examples.py --zoek "range,liq,order block,Cos867" --dagen 60 > data/misser/range_sweep_concept.csv

De gebruiker vult stop, doel, uitkomst en tf aan en voegt de regels toe aan docs/onderzoek/range-sweep/handtrades.csv. Het script schrijft niets in de database."""
import argparse
import csv
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import db, misser  # noqa: E402

FIELDS = ["coin", "richting", "tijd", "instap", "stop", "doel", "uitkomst", "bron", "notitie", "tf"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zoek", default="range,liq,order block,ob,sweep")
    ap.add_argument("--dagen", type=int, default=60)
    a = ap.parse_args()
    words = [w.strip().lower() for w in a.zoek.split(",") if w.strip()]
    since = (datetime.now(timezone.utc) - timedelta(days=a.dagen)).isoformat()
    with db.session() as conn:
        rows = [dict(r) for r in conn.execute("SELECT id, received_at, raw_text, coin, direction FROM messages WHERE received_at >= ? ORDER BY received_at", (since,))]
    hits = [r for r in rows if any(w in (r["raw_text"] or "").lower() for w in words)]
    drafts = misser.draft_rows(hits)
    out = csv.DictWriter(sys.stdout, fieldnames=FIELDS)
    out.writeheader()
    for d in drafts:
        out.writerow({**{k: "" for k in FIELDS}, **d})
    print(f"{len(hits)} berichten gevonden, {len(drafts)} met coin en kant", file=sys.stderr)


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run de tests en zie ze slagen**

Run: `python3 -m unittest tests.test_misser -v`
Expected: PASS, ook de bestaande tests.

- [ ] **Step 5: Commit**

```bash
git add app/misser.py scripts/misser_check.py scripts/range_sweep_examples.py tests/test_misser.py
git commit -m "feat: handtrades met optionele stop en doel, tf-kolom en concept uit berichten"
```

---

### Task 4: Range- en zonedetector

**Files:**
- Create: `app/replay/rangesweep.py`
- Create: `tests/replay/rangesweep_fixtures.py`
- Test: `tests/replay/test_rangesweep.py`

**Interfaces:**
- Produces:
  - Constanten `TFS = ("30m", "1h", "2h", "4h")`, `TF_DELTA` (15m tot 4h), `TRIGGER_TF = {"30m": "30m", "1h": "1h", "2h": "1h", "4h": "1h"}`, `RANGE_LOOKBACK`, en de range- en zoneconstanten uit het `prereg-constants`-blok.
  - `resample(bars, tf) -> pd.DataFrame` en `build_frames(b15, b1h, b4h) -> dict[str, pd.DataFrame]` met sleutels `15m, 30m, 1h, 2h, 4h`.
  - `Range` (frozen dataclass): `tf, known_at, high, low, high_touches, low_touches, high_spread, low_spread, first_at, atr`, eigenschappen `mid`, `width`.
  - `range_at(b, i, tf, ph, pl) -> tuple[Optional[Range], str]`, `range_series(bars, tf) -> tuple[pd.DataFrame, list[Optional[Range]]]`, `active_for(b_trig, b_tf, ranges, tf) -> list[Optional[Range]]`.
  - `Zone` (frozen dataclass): `kind ("bear" of "bull"), low, high, ob_idx, known_idx, broken_idx (Optional[int]), disp_bars, disp_atr`, eigenschappen `inner(direction)`, `outer`.
  - `find_zones(b) -> list[Zone]` (b met `atr`), `zone_active(z, i) -> bool`, `retests_before(z, b, i) -> int`.
  - Fixture: `rangesweep_fixtures.frames() -> tuple[b15, b1h, b4h]`, `SWEEP_HOUR = 174`, `FIRST_PEAK_HOUR = 54`, `FIRST_SHORT_ZONE_SETUP_HOUR = 112`, `FIRST_LONG_ZONE_SETUP_HOUR = 102`.

- [ ] **Step 1: Schrijf de fixture**

`tests/replay/rangesweep_fixtures.py`:

```python
"""Een kunstmatige markt met één schone range, aanbod- en vraagzones op de randen en één sweep, opgebouwd uit 15m-candles zodat 30m, 1u, 2u
en 4u er exact uit volgen. Uren: 40 vlak op 103, in 5 uur naar 100, zes keer 10 uur op naar 106 en 10 uur af naar 100, 9 uur op naar 105,4,
dan het sweep-uur (prik naar 106,5, slot 105,6), 10 uur af naar 100 en 20 uur vlak. Pieken op uur 54, 74, ..., 154; dalen op 44, 64, ..., 164.
Elke piek is een groene candle met daarna een daling van meer dan 1 ATR: een aanbodzone 105,375 tot 106,025. Elke dal gespiegeld: een
vraagzone 99,975 tot 100,625. De range is pas bekend als er drie toppen en drie dalen bevestigd zijn: de eerste long-setup komt bij de
nadering op uur 102, de eerste short-setup op uur 112."""
import pandas as pd

START = pd.Timestamp("2025-03-03 00:00", tz="UTC")
SWEEP_HOUR = 174
FIRST_PEAK_HOUR = 54
FIRST_SHORT_ZONE_SETUP_HOUR = 112
FIRST_LONG_ZONE_SETUP_HOUR = 102
WICK = 0.025
SWEEP_15M = [(105.4, 105.925, 105.375, 105.9), (105.9, 106.5, 105.875, 106.2), (106.2, 106.225, 105.775, 105.8), (105.8, 105.825, 105.575, 105.6)]


def hourly_closes_before_sweep() -> list[float]:
    p = [103.0] * 40
    p += [103.0 - 0.6 * k for k in range(1, 6)]
    for _ in range(6):
        p += [100.0 + 0.6 * k for k in range(1, 11)]
        p += [106.0 - 0.6 * k for k in range(1, 11)]
    p += [100.0 + 0.6 * k for k in range(1, 10)]
    return p


def _linear_15m(prev: float, close: float) -> list[tuple]:
    out, o = [], prev
    for q in range(1, 5):
        c = prev + (close - prev) * q / 4
        out.append((o, max(o, c) + WICK, min(o, c) - WICK, c))
        o = c
    return out


def frames() -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    closes = hourly_closes_before_sweep()
    rows, prev = [], closes[0]
    for c in closes:
        rows += _linear_15m(prev, c)
        prev = c
    rows += SWEEP_15M
    prev = 105.6
    for k in range(1, 11):
        c = 105.6 - 0.56 * k
        rows += _linear_15m(prev, c)
        prev = c
    for _ in range(20):
        rows += _linear_15m(prev, 100.0)
        prev = 100.0
    b15 = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    b15.insert(0, "timestamp", pd.date_range(START, periods=len(b15), freq="15min"))
    b15["volume"] = 1.0
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    b1h = b15.set_index("timestamp").resample("1h", origin="epoch").agg(agg).dropna().reset_index()
    b4h = b15.set_index("timestamp").resample("4h", origin="epoch").agg(agg).dropna().reset_index()
    return b15, b1h, b4h
```

- [ ] **Step 2: Schrijf de falende tests**

`tests/replay/test_rangesweep.py`:

```python
import unittest

import numpy as np
import pandas as pd

from app.replay import rangesweep as rs
from app.replay import trendlab as tl
from app.replay.lab import add_indicators
from tests.replay.rangesweep_fixtures import FIRST_PEAK_HOUR, SWEEP_HOUR, frames


class ResampleTest(unittest.TestCase):
    def test_frames_have_every_timeframe_and_full_buckets_only(self):
        b15, b1h, b4h = frames()
        f = rs.build_frames(b15, b1h, b4h)
        self.assertEqual(set(f), {"15m", "30m", "1h", "2h", "4h"})
        self.assertEqual(len(f["30m"]), len(b15) // 2)
        self.assertEqual(len(f["2h"]), len(b1h) // 2)
        self.assertEqual(f["2h"]["timestamp"].iloc[0].hour % 2, 0)
        self.assertAlmostEqual(f["2h"]["high"].iloc[0], max(b1h["high"].iloc[0], b1h["high"].iloc[1]))

    def test_incomplete_last_bucket_is_dropped(self):
        b15, b1h, _ = frames()
        self.assertEqual(len(rs.resample(b1h.iloc[:-1], "2h")), (len(b1h) - 1) // 2)


class RangeTest(unittest.TestCase):
    def setUp(self):
        self.b15, self.b1h, self.b4h = frames()
        self.b, self.ranges = rs.range_series(self.b1h, "1h")

    def test_range_known_just_before_the_sweep(self):
        r = self.ranges[SWEEP_HOUR - 1]
        self.assertIsNotNone(r)
        self.assertAlmostEqual(r.high, 106.025, places=6)
        self.assertAlmostEqual(r.low, 99.975, places=6)
        self.assertEqual((r.high_touches, r.low_touches), (6, 6))
        self.assertAlmostEqual(r.high_spread, 0.0, places=9)
        self.assertEqual(r.first_at, self.b["timestamp"].iloc[FIRST_PEAK_HOUR])
        self.assertEqual(r.known_at, self.b["timestamp"].iloc[SWEEP_HOUR])

    def test_no_range_in_the_flat_start(self):
        hi, lo = self.b["high"].to_numpy(float), self.b["low"].to_numpy(float)
        r, why = rs.range_at(self.b, 30, "1h", tl._pivot_flags(-hi, rs.PIVOT_N), tl._pivot_flags(lo, rs.PIVOT_N))
        self.assertIsNone(r)
        self.assertIn("te weinig aanrakingen", why)

    def test_width_bounds(self):
        hi, lo = self.b["high"].to_numpy(float), self.b["low"].to_numpy(float)
        ph, pl = tl._pivot_flags(-hi, rs.PIVOT_N), tl._pivot_flags(lo, rs.PIVOT_N)
        b = self.b.copy()
        b["atr"] = 3.0
        self.assertEqual(rs.range_at(b, SWEEP_HOUR - 1, "1h", ph, pl), (None, "range te smal"))
        b["atr"] = 0.3
        self.assertEqual(rs.range_at(b, SWEEP_HOUR - 1, "1h", ph, pl), (None, "range te breed"))

    def test_active_for_uses_only_known_ranges(self):
        active = rs.active_for(self.b, self.b, self.ranges, "1h")
        self.assertIs(active[SWEEP_HOUR], self.ranges[SWEEP_HOUR - 1])
        self.assertIsNone(active[0])

    def test_active_for_4h_waits_for_the_close(self):
        b4, r4 = rs.range_series(self.b4h, "4h")
        for j, r in enumerate(rs.active_for(self.b, b4, r4, "4h")):
            if r is not None:
                self.assertLessEqual(r.known_at, self.b["timestamp"].iloc[j])


class ZoneTest(unittest.TestCase):
    def setUp(self):
        _, b1h, _ = frames()
        self.b = add_indicators(b1h).reset_index(drop=True)
        self.zones = rs.find_zones(self.b)

    def test_supply_zone_on_the_first_peak(self):
        bear = [z for z in self.zones if z.kind == "bear"]
        z = bear[0]
        self.assertEqual(z.ob_idx, FIRST_PEAK_HOUR)
        self.assertAlmostEqual(z.low, 105.375)
        self.assertAlmostEqual(z.high, 106.025)
        self.assertAlmostEqual(z.outer, 106.025)
        self.assertAlmostEqual(z.inner("short"), 105.375)
        self.assertLessEqual(z.disp_bars, rs.DISP_BARS)

    def test_overlapping_later_peaks_do_not_make_new_zones(self):
        bear = [z for z in self.zones if z.kind == "bear" and z.ob_idx < SWEEP_HOUR]
        self.assertEqual(len(bear), 1)

    def test_demand_zone_on_the_first_trough(self):
        bull = [z for z in self.zones if z.kind == "bull"]
        self.assertEqual(bull[0].ob_idx, 44)
        self.assertAlmostEqual(bull[0].low, 99.975)
        self.assertAlmostEqual(bull[0].high, 100.625)

    def test_zone_is_active_until_a_close_beyond_the_outer_edge(self):
        z = rs.Zone("bear", 100.0, 101.0, 0, 2, 5, 2, 1.5)
        self.assertTrue(rs.zone_active(z, 4))
        self.assertFalse(rs.zone_active(z, 5))
        self.assertFalse(rs.zone_active(z, 2))
        self.assertFalse(rs.zone_active(rs.Zone("bear", 100.0, 101.0, 0, 2, None, 2, 1.5), 2 + rs.ZONE_MAX_AGE + 1))

    def test_retests_count_entries_into_the_zone(self):
        bear = [z for z in self.zones if z.kind == "bear"][0]
        self.assertEqual(rs.retests_before(bear, self.b, 72), 0)
        self.assertEqual(rs.retests_before(bear, self.b, 95), 1)
```

- [ ] **Step 3: Run de tests en zie ze falen**

Run: `python3 -m unittest tests.replay.test_rangesweep -v`
Expected: FAIL met `ModuleNotFoundError: No module named 'app.replay.rangesweep'`.

- [ ] **Step 4: Implementeer**

`app/replay/rangesweep.py` (deel 1):

```python
"""Range sweep: onze lezing van de strategie van Cos867 (docs/onderzoek/range-sweep/preregistratie.md). Een range met minstens drie aanrakingen
op beide randen, aanbod- en vraagzones (order blocks als vakken) op die randen, en twee manieren om terug door de range te handelen: de
zone-retest (de koers keert terug in de zone aan de rand) en de sweep (een prik voorbij de rand en een slot terug binnen). Altijd met een
limietorder en een stop voorbij de zone. Pure functies op candles: lab, misser-controle en live motor gebruiken dezelfde code.

Tijd: de timestamp van een candle is zijn openmoment; een candle is bekend op timestamp + timeframe. Een zwaaipunt op p is pas bekend op p + PIVOT_N."""
from dataclasses import dataclass
from typing import Optional

import numpy as np
import pandas as pd

from app.replay import trendlab as tl
from app.replay.lab import add_indicators

TFS = ("30m", "1h", "2h", "4h")
TF_DELTA = {"15m": pd.Timedelta(minutes=15), "30m": pd.Timedelta(minutes=30), "1h": pd.Timedelta(hours=1),
            "2h": pd.Timedelta(hours=2), "4h": pd.Timedelta(hours=4)}
# "1h/15m confirmation": de sweep en het slot terug binnen op 1u, behalve op 30m, waar 1u grover is dan de range zelf.
TRIGGER_TF = {"30m": "30m", "1h": "1h", "2h": "1h", "4h": "1h"}
PIVOT_N = 3
TOUCHES = 3
CLUSTER_ATR = 0.5
RANGE_LOOKBACK = {"30m": 120, "1h": 120, "2h": 90, "4h": 90}
RANGE_MIN_ATR = 3.0
RANGE_MAX_ATR = 15.0
CONTAIN_ATR = 0.25
DISP_BARS = 5
DISP_ATR = 1.0
ZONE_MAX_AGE = 200
ZONE_OVERLAP = 0.5
SHORT, LONG = "short", "long"
_AGG = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}


def resample(bars: pd.DataFrame, tf: str) -> pd.DataFrame:
    """Candles van tf uit fijnere candles, alleen volle vakken op UTC-grenzen (zoals Binance 30m en 2u opent). Een half vak aan het eind valt weg,
    anders verschijnt live een candle die het lab nooit zag."""
    delta = TF_DELTA[tf]
    step = bars["timestamp"].diff().dropna().min()
    g = bars.set_index("timestamp").resample(delta, origin="epoch", label="left", closed="left")
    out, count = g.agg(_AGG), g["close"].count()
    return out[count == int(delta / step)].dropna().reset_index()


def build_frames(b15: pd.DataFrame, b1h: pd.DataFrame, b4h: pd.DataFrame) -> dict[str, pd.DataFrame]:
    return {"15m": b15.reset_index(drop=True), "30m": resample(b15, "30m"), "1h": b1h.reset_index(drop=True), "2h": resample(b1h, "2h"),
            "4h": b4h.reset_index(drop=True)}


@dataclass(frozen=True)
class Range:
    tf: str
    known_at: pd.Timestamp
    high: float
    low: float
    high_touches: int
    low_touches: int
    high_spread: float
    low_spread: float
    first_at: pd.Timestamp
    atr: float

    @property
    def mid(self) -> float:
        return (self.high + self.low) / 2

    @property
    def width(self) -> float:
        return self.high - self.low


def _best_cluster(values: np.ndarray, tol: float) -> np.ndarray:
    """Posities van de grootste groep binnen tol van één anker; bij gelijkstand de groep met het laatste punt, zoals rejection.py."""
    best = np.array([], dtype=int)
    for a in range(len(values)):
        group = np.flatnonzero(np.abs(values - values[a]) <= tol)
        if len(group) > len(best) or (len(group) == len(best) and len(group) and group[-1] > best[-1]):
            best = group
    return best


def range_at(b: pd.DataFrame, i: int, tf: str, ph: np.ndarray, pl: np.ndarray) -> tuple[Optional[Range], str]:
    atr = float(b["atr"].iloc[i])
    if not np.isfinite(atr) or atr <= 0:
        return None, "te weinig candles voor de ATR"
    lo_idx, hi_idx = max(0, i - RANGE_LOOKBACK[tf]), i - PIVOT_N
    if hi_idx <= lo_idx:
        return None, "te weinig candles"
    high, low, close = b["high"].to_numpy(float), b["low"].to_numpy(float), b["close"].to_numpy(float)
    highs = np.flatnonzero(ph[lo_idx:hi_idx + 1]) + lo_idx
    lows = np.flatnonzero(pl[lo_idx:hi_idx + 1]) + lo_idx
    hc = highs[_best_cluster(high[highs], CLUSTER_ATR * atr)] if len(highs) else highs
    lc = lows[_best_cluster(low[lows], CLUSTER_ATR * atr)] if len(lows) else lows
    if len(hc) < TOUCHES or len(lc) < TOUCHES:
        return None, f"te weinig aanrakingen (boven {len(hc)}, onder {len(lc)}, nodig {TOUCHES})"
    top, bottom = float(high[hc].max()), float(low[lc].min())
    if top - bottom < RANGE_MIN_ATR * atr:
        return None, "range te smal"
    if top - bottom > RANGE_MAX_ATR * atr:
        return None, "range te breed"
    start = int(min(hc.min(), lc.min()))
    inside = close[start:i + 1]
    if (inside > top + CONTAIN_ATR * atr).any() or (inside < bottom - CONTAIN_ATR * atr).any():
        return None, "slot buiten de range sinds de eerste aanraking"
    ts = b["timestamp"]
    return Range(tf, ts.iloc[i] + TF_DELTA[tf], top, bottom, len(hc), len(lc), float(high[hc].max() - high[hc].min()),
                 float(low[lc].max() - low[lc].min()), ts.iloc[start], atr), ""


def range_series(bars: pd.DataFrame, tf: str) -> tuple[pd.DataFrame, list[Optional[Range]]]:
    b = add_indicators(bars).reset_index(drop=True)
    hi, lo = b["high"].to_numpy(float), b["low"].to_numpy(float)
    ph, pl = tl._pivot_flags(-hi, PIVOT_N), tl._pivot_flags(lo, PIVOT_N)
    return b, [range_at(b, i, tf, ph, pl)[0] for i in range(len(b))]


def active_for(b_trig: pd.DataFrame, b_tf: pd.DataFrame, ranges: list[Optional[Range]], tf: str) -> list[Optional[Range]]:
    """Per candle van b_trig de range van de laatste candle van tf die gesloten was bij het openen van die candle."""
    known = (b_tf["timestamp"] + TF_DELTA[tf]).to_numpy()
    pos = np.searchsorted(known, b_trig["timestamp"].to_numpy(), side="right") - 1
    return [ranges[p] if p >= 0 else None for p in pos]


@dataclass(frozen=True)
class Zone:
    kind: str
    low: float
    high: float
    ob_idx: int
    known_idx: int
    broken_idx: Optional[int]
    disp_bars: int
    disp_atr: float

    @property
    def outer(self) -> float:
        return self.high if self.kind == "bear" else self.low

    def inner(self, direction: str) -> float:
        return self.low if self.kind == "bear" else self.high


def _overlap(a: tuple[float, float], b: tuple[float, float]) -> float:
    """Deel van het kleinste vak dat in het andere ligt."""
    inter = min(a[1], b[1]) - max(a[0], b[0])
    return max(0.0, inter) / max(1e-12, min(a[1] - a[0], b[1] - b[0]))


def zone_active(z: Zone, i: int) -> bool:
    return z.known_idx < i <= z.known_idx + ZONE_MAX_AGE and (z.broken_idx is None or i < z.broken_idx)


def find_zones(b: pd.DataFrame) -> list[Zone]:
    """Aanbodzone: de laatste groene candle k (hooguit DISP_BARS vóór m) waarna een slot op m minstens DISP_ATR ATR onder het laag van k komt.
    Zone = laag tot hoog van k, bekend op m. Vraagzone gespiegeld. broken_idx is de eerste candle na m die voorbij de buitenkant sluit; consumenten
    vergelijken hem alleen met hun eigen index, zodat er niets uit de toekomst lekt. Een zone die voor meer dan ZONE_OVERLAP overlapt met een
    nog actieve zone van dezelfde soort telt niet: de oudere is dezelfde liquiditeit."""
    op, hi, lo, cl, atr = (b[c].to_numpy(float) for c in ("open", "high", "low", "close", "atr"))
    n, out, seen = len(b), [], set()
    for m in range(1, n):
        if not np.isfinite(atr[m]) or atr[m] <= 0:
            continue
        for kind in ("bear", "bull"):
            k = next((k for k in range(m - 1, max(-1, m - DISP_BARS - 1), -1) if ((cl[k] > op[k]) if kind == "bear" else (cl[k] < op[k]))), None)
            if k is None or (kind, k) in seen:
                continue
            moved = (lo[k] - cl[m]) if kind == "bear" else (cl[m] - hi[k])
            if moved < DISP_ATR * atr[m]:
                continue
            seen.add((kind, k))
            if any(z.kind == kind and zone_active(z, m) and _overlap((z.low, z.high), (lo[k], hi[k])) > ZONE_OVERLAP for z in out):
                continue
            after = cl[m + 1:min(n, m + 1 + ZONE_MAX_AGE)]
            beyond = np.flatnonzero(after > hi[k]) if kind == "bear" else np.flatnonzero(after < lo[k])
            window = cl[k + 1:m + 1]
            disp = ((lo[k] - window.min()) if kind == "bear" else (window.max() - hi[k])) / atr[m]
            out.append(Zone(kind, float(lo[k]), float(hi[k]), k, m, int(m + 1 + beyond[0]) if len(beyond) else None, m - k, float(disp)))
    return out


def retests_before(z: Zone, b: pd.DataFrame, i: int) -> int:
    """Hoe vaak de koers tussen het ontstaan en candle i (exclusief) de zone binnenkwam: elke overgang van erbuiten naar erin telt één keer."""
    hi, lo = b["high"].to_numpy(float), b["low"].to_numpy(float)
    count, inside = 0, False
    for m in range(z.known_idx + 1, i):
        now = (hi[m] >= z.low) if z.kind == "bear" else (lo[m] <= z.high)
        count += now and not inside
        inside = now
    return count
```

- [ ] **Step 5: Run de tests en zie ze slagen**

Run: `python3 -m unittest tests.replay.test_rangesweep -v`
Expected: PASS. Faalt `test_retests_count_entries_into_the_zone` op 95, controleer met de hand: de zone van piek 54 wordt geraakt op piek 74 (uur 72 tot 76 komt het hoog boven 105,375), dus vóór uur 95 precies één keer.

- [ ] **Step 6: Commit**

```bash
git add app/replay/rangesweep.py tests/replay/rangesweep_fixtures.py tests/replay/test_rangesweep.py
git commit -m "feat: range- en zonedetector voor de range sweep"
```

---

### Task 5: Setups (zone-retest en sweep), stops en diagnose

**Files:**
- Modify: `app/replay/rangesweep.py`
- Create: `tests/golden/range_sweep_setup.json`
- Test: `tests/replay/test_rangesweep.py`

**Interfaces:**
- Consumes: taak 4.
- Produces:
  - `Sweep` (frozen): `direction, rng, start, ret, extreme, atr`.
  - `find_sweeps(b_trig, active) -> tuple[list[Sweep], list[dict]]` (weigering `{"at", "direction", "reason"}`).
  - `htf_context(b_trig, b4h)`, `htf_ok(direction, trend, hh, ll, rng)`.
  - `find_setups(frames, tf, family, entry, confirm, use_htf, ranges=None) -> tuple[list[dict], list[dict]]` met `family` in `("zone", "sweep")`, `entry` in `("zone", "ob", "split")`, `confirm` in `("slot", "choch15")`. Setup-dict, precies deze sleutels: `direction, family, tf, range_high, range_low, range_first_at, zone_low, zone_high, zone_at, sweep_at, extreme, return_at, placed_at, place_idx15, ref_price, legs, atr_t, htf_trend, htf_pos, htf_ok, features`. Bij de zone-retest zijn `sweep_at`, `extreme` en `return_at` `None`. `features`: `touches_high, touches_low, width_atr, age_bars, edge_spread_atr, ob_opposite, displacement_atr, zone_fresh, zone_atr`.
  - Stops: `MIN_STOP_PCT = 0.4`, `STOP_BUFFER = {"zone_0": ("zone", 0.0), "zone_025": ("zone", 0.25), "zone_05": ("zone", 0.5), "wick_025": ("wick", 0.25)}`, `TESTED_STOPS = {"zone": ("zone_025", "zone_05"), "sweep": ("zone_025", "wick_025")}`, `DESCRIPTIVE_STOP = "zone_0"`, `raw_stops(setup) -> dict[str, float]`, `final_stop(setup, name) -> float` (met `floor_stop`).
  - `diagnose(frames, at, direction, tf, family, entry, confirm, use_htf, window=pd.Timedelta(hours=12)) -> dict` met `seen, reason, setup`.

- [ ] **Step 1: Schrijf de falende tests**

Voeg toe aan `tests/replay/test_rangesweep.py`:

```python
import json
import os
from pathlib import Path

from tests.replay.rangesweep_fixtures import FIRST_LONG_ZONE_SETUP_HOUR, FIRST_SHORT_ZONE_SETUP_HOUR

GOLDEN = Path(__file__).resolve().parent.parent / "golden" / "range_sweep_setup.json"


class SweepSetupTest(unittest.TestCase):
    def setUp(self):
        b15, b1h, b4h = frames()
        self.f, self.b1h = rs.build_frames(b15, b1h, b4h), b1h

    def setups(self, entry="ob", confirm="slot"):
        return rs.find_setups(self.f, "1h", "sweep", entry, confirm, use_htf=False)

    def test_one_short_setup_at_the_sweep(self):
        setups, _ = self.setups()
        self.assertEqual(len(setups), 1)
        s = setups[0]
        self.assertEqual((s["direction"], s["family"]), ("short", "sweep"))
        self.assertAlmostEqual(s["extreme"], 106.5)
        self.assertEqual(s["sweep_at"], self.b1h["timestamp"].iloc[SWEEP_HOUR])
        self.assertEqual(s["placed_at"], self.b1h["timestamp"].iloc[SWEEP_HOUR] + pd.Timedelta(hours=1))
        self.assertEqual(s["place_idx15"], 4 * (SWEEP_HOUR + 1))
        self.assertAlmostEqual(s["ref_price"], 105.6)

    def test_order_block_is_the_last_green_15m_candle_at_the_top(self):
        s = self.setups()[0][0]
        self.assertAlmostEqual(s["zone_low"], 105.875)
        self.assertAlmostEqual(s["zone_high"], 106.5)
        self.assertEqual(s["legs"], [(1.0, (105.875 + 106.5) / 2)])

    def test_features(self):
        f = self.setups()[0][0]["features"]
        self.assertEqual((f["touches_high"], f["touches_low"]), (6, 6))
        self.assertEqual(f["age_bars"], SWEEP_HOUR - FIRST_PEAK_HOUR)
        self.assertTrue(f["ob_opposite"])
        self.assertTrue(f["zone_fresh"])
        self.assertLess(f["displacement_atr"], 1.5)
        self.assertLessEqual(f["zone_atr"], 1.5)

    def test_choch_is_missing_here_and_says_why(self):
        setups, refused = self.setups(confirm="choch15")
        self.assertEqual(setups, [])
        self.assertIn("geen CHoCH op 15m binnen 6 uur", [r["reason"] for r in refused])

    def test_breakout_is_not_a_sweep(self):
        b15, _, b4h = frames()
        b15 = b15.copy()
        b15.loc[4 * SWEEP_HOUR + 1, "high"] = 108.0
        b1h = rs.resample(b15, "1h")
        setups, refused = rs.find_setups(rs.build_frames(b15, b1h, b4h), "1h", "sweep", "ob", "slot", use_htf=False)
        self.assertEqual(setups, [])
        self.assertIn("prik te diep, dit is een uitbraak", [r["reason"] for r in refused])

    def test_stops(self):
        s = self.setups()[0][0]
        raw = rs.raw_stops(s)
        self.assertEqual(set(raw), {"zone_0", "zone_025", "zone_05", "wick_025"})
        self.assertAlmostEqual(raw["zone_0"], 106.5)
        self.assertAlmostEqual(raw["wick_025"], 106.5 + 0.25 * s["atr_t"])
        self.assertGreaterEqual(rs.final_stop(s, "zone_025"), raw["zone_025"])

    def test_golden(self):
        s = self.setups()[0][0]
        got = json.loads(json.dumps({k: (str(v) if isinstance(v, pd.Timestamp) else v) for k, v in s.items()}, default=float))
        if os.environ.get("REGEN_GOLDEN"):
            GOLDEN.write_text(json.dumps(got, indent=2, sort_keys=True))
        if not GOLDEN.exists():
            self.fail(f"maak {GOLDEN} met REGEN_GOLDEN=1 en controleer hem met de hand tegen de definities")
        want = json.loads(GOLDEN.read_text())
        self.assertEqual(set(got), set(want))
        for k in want:
            if isinstance(want[k], float):
                self.assertAlmostEqual(got[k], want[k], places=6, msg=k)
            else:
                self.assertEqual(got[k], want[k], msg=k)


class ZoneSetupTest(unittest.TestCase):
    def setUp(self):
        b15, b1h, b4h = frames()
        self.f, self.b1h = rs.build_frames(b15, b1h, b4h), b1h
        self.setups, self.refused = rs.find_setups(self.f, "1h", "zone", "zone", "slot", use_htf=False)

    def test_first_short_is_the_first_approach_with_a_known_range(self):
        short = [s for s in self.setups if s["direction"] == "short"][0]
        self.assertEqual(short["placed_at"], self.b1h["timestamp"].iloc[FIRST_SHORT_ZONE_SETUP_HOUR] + pd.Timedelta(hours=1))
        self.assertEqual(short["legs"], [(1.0, 105.375)])
        self.assertAlmostEqual(short["zone_high"], 106.025)
        self.assertIsNone(short["extreme"])

    def test_first_long_mirrors(self):
        long_ = [s for s in self.setups if s["direction"] == "long"][0]
        self.assertEqual(long_["placed_at"], self.b1h["timestamp"].iloc[FIRST_LONG_ZONE_SETUP_HOUR] + pd.Timedelta(hours=1))
        self.assertEqual(long_["legs"], [(1.0, 100.625)])

    def test_earlier_approaches_were_refused_for_lack_of_a_range(self):
        self.assertTrue(any(r["reason"].startswith("geen range op 1h") for r in self.refused))

    def test_one_setup_per_zone(self):
        keys = [(s["direction"], s["zone_low"], s["zone_high"]) for s in self.setups]
        self.assertEqual(len(keys), len(set(keys)))

    def test_zone_stops_have_no_wick(self):
        s = self.setups[0]
        self.assertEqual(set(rs.raw_stops(s)), {"zone_0", "zone_025", "zone_05"})

    def test_htf_ok(self):
        r = rs.Range("1h", pd.Timestamp("2025-01-01", tz="UTC"), 110.0, 100.0, 3, 3, 0.0, 0.0, pd.Timestamp("2025-01-01", tz="UTC"), 1.0)
        self.assertTrue(rs.htf_ok("short", -1, 200.0, 0.0, r))
        self.assertFalse(rs.htf_ok("short", 1, 200.0, 0.0, r))
        self.assertTrue(rs.htf_ok("short", 1, 120.0, 80.0, r))
        self.assertTrue(rs.htf_ok("long", 1, 120.0, 80.0, r))
        self.assertFalse(rs.htf_ok("long", 0, float("nan"), float("nan"), r))

    def test_diagnose(self):
        at = self.b1h["timestamp"].iloc[FIRST_SHORT_ZONE_SETUP_HOUR] + pd.Timedelta(hours=1)
        self.assertTrue(rs.diagnose(self.f, at, "short", "1h", "zone", "zone", "slot", False)["seen"])
        early = self.b1h["timestamp"].iloc[30]
        d = rs.diagnose(self.f, early, "short", "1h", "zone", "zone", "slot", False)
        self.assertFalse(d["seen"])
        self.assertIn("geen range op 1h", d["reason"])
```

- [ ] **Step 2: Run de tests en zie ze falen**

Run: `python3 -m unittest tests.replay.test_rangesweep -v`
Expected: FAIL met `AttributeError: module 'app.replay.rangesweep' has no attribute 'find_setups'`.

- [ ] **Step 3: Implementeer**

Voeg toe aan `app/replay/rangesweep.py`:

```python
from app import smc_eval

APPROACH_ATR = 1.0
EDGE_BAND = 0.25
SWEEP_MIN_ATR = 0.1
SWEEP_MAX_ATR = 1.5
RETURN_MAX_BARS = 6
SWEEP_COOLDOWN = 24
OB_SEARCH_15M = 8
CHOCH_PIVOT_N = 2
CHOCH_MAX_BARS = 24
HTF_LOOKBACK_4H = 180
EDGE_WEIGHT, OB_WEIGHT = 0.4, 0.6
AGE_MIN = {"30m": 48, "1h": 48, "2h": 36, "4h": 36}
# Vast, niet uit config: lab en live moeten met dezelfde ondergrens rekenen, ook als SMC_MIN_STOP_PCT op de VPS anders staat.
MIN_STOP_PCT = 0.4
STOP_BUFFER = {"zone_0": ("zone", 0.0), "zone_025": ("zone", 0.25), "zone_05": ("zone", 0.5), "wick_025": ("wick", 0.25)}
TESTED_STOPS = {"zone": ("zone_025", "zone_05"), "sweep": ("zone_025", "wick_025")}
DESCRIPTIVE_STOP = "zone_0"


@dataclass(frozen=True)
class Sweep:
    direction: str
    rng: Range
    start: int
    ret: int
    extreme: float
    atr: float


def find_sweeps(b: pd.DataFrame, active: list[Optional[Range]]) -> tuple[list[Sweep], list[dict]]:
    """b: triggercandles met atr. Een prik voorbij een rand met een slot terug binnen in RETURN_MAX_BARS candles; dieper dan SWEEP_MAX_ATR is een uitbraak."""
    hi, lo, cl, atr = (b[c].to_numpy(float) for c in ("high", "low", "close", "atr"))
    ts = b["timestamp"]
    out, refused, used, last_start = [], [], set(), {}
    for j in range(len(b)):
        r = active[j]
        if r is None or not np.isfinite(atr[j]):
            continue
        for direction in (SHORT, LONG):
            beyond = hi[j] - r.high if direction == SHORT else r.low - lo[j]
            if beyond < SWEEP_MIN_ATR * atr[j]:
                continue
            key = (direction, r.first_at, r.high, r.low)
            # Na een sweep vormt de prik vaak een nieuwe range met bijna dezelfde randen: binnen SWEEP_COOLDOWN telt dezelfde kant één keer.
            if key in used or j - last_start.get(direction, -10**9) < SWEEP_COOLDOWN:
                continue
            used.add(key)
            last_start[direction] = j
            extreme, ret, reason = (hi[j] if direction == SHORT else lo[j]), None, "geen terugkeer binnen 6 candles"
            for k in range(j, min(len(b), j + RETURN_MAX_BARS)):
                extreme = max(extreme, hi[k]) if direction == SHORT else min(extreme, lo[k])
                if (extreme - r.high if direction == SHORT else r.low - extreme) > SWEEP_MAX_ATR * r.atr:
                    reason = "prik te diep, dit is een uitbraak"
                    break
                if (cl[k] < r.high) if direction == SHORT else (cl[k] > r.low):
                    ret = k
                    break
            if ret is None:
                refused.append({"at": ts.iloc[j], "direction": direction, "reason": reason})
                continue
            out.append(Sweep(direction, r, j, ret, float(extreme), float(atr[ret])))
    return out, refused


def htf_context(b: pd.DataFrame, b4h: pd.DataFrame) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """(trend, hh, ll) per candle van b, alleen uit gesloten 4u-candles (beschikbaar op timestamp + 4u)."""
    trend = tl.htf_trend(b, b4h)
    b4 = b4h.reset_index(drop=True)
    frame = pd.DataFrame({"timestamp": b4["timestamp"] + pd.Timedelta(hours=4), "hh": b4["high"].rolling(HTF_LOOKBACK_4H).max(),
                          "ll": b4["low"].rolling(HTF_LOOKBACK_4H).min()})
    merged = pd.merge_asof(b[["timestamp"]].reset_index(drop=True), frame, on="timestamp")
    return trend, merged["hh"].to_numpy(float), merged["ll"].to_numpy(float)


def htf_ok(direction: str, trend: int, hh: float, ll: float, rng: Range) -> bool:
    """Short mag met de 4u-trend omlaag of met de range in de bovenste helft van de laatste 30 dagen; long gespiegeld."""
    want = -1 if direction == SHORT else 1
    if not (np.isfinite(hh) and np.isfinite(ll)) or hh <= ll:
        return trend == want
    pos = (rng.mid - ll) / (hh - ll)
    return trend == want or (pos >= 0.5 if direction == SHORT else pos <= 0.5)


def _htf_pos(rng: Range, hh: float, ll: float) -> Optional[float]:
    return float((rng.mid - ll) / (hh - ll)) if np.isfinite(hh) and np.isfinite(ll) and hh > ll else None


def _extreme_15m(b15: pd.DataFrame, t0: pd.Timestamp, t1: pd.Timestamp, direction: str) -> Optional[int]:
    pos = np.flatnonzero(((b15["timestamp"] >= t0) & (b15["timestamp"] < t1)).to_numpy())
    if not len(pos):
        return None
    col = b15["high" if direction == SHORT else "low"].to_numpy(float)[pos]
    return int(pos[np.argmax(col)] if direction == SHORT else pos[np.argmin(col)])


def order_block(b15: pd.DataFrame, k: int, direction: str) -> tuple[float, float, int, bool]:
    """(laag, hoog, index, echte_tegenkaars). Vanaf de uiterste 15m-candle k terug: de eerste groene (short) of rode (long) candle."""
    op, cl = b15["open"].to_numpy(float), b15["close"].to_numpy(float)
    for m in range(k, max(-1, k - OB_SEARCH_15M - 1), -1):
        if (cl[m] > op[m]) if direction == SHORT else (cl[m] < op[m]):
            return float(b15["low"].iloc[m]), float(b15["high"].iloc[m]), m, True
    return float(b15["low"].iloc[k]), float(b15["high"].iloc[k]), k, False


def choch_index(b15: pd.DataFrame, k: int, start: int, direction: str, extreme: float) -> Optional[int]:
    """Eerste 15m-candle vanaf start die sluit voorbij het laatste zwaaipunt (CHOCH_PIVOT_N) vóór k; een nieuw uiterste eerst maakt het ongeldig."""
    hi, lo, cl = (b15[c].to_numpy(float) for c in ("high", "low", "close"))
    flags = tl._pivot_flags(lo, CHOCH_PIVOT_N) if direction == SHORT else tl._pivot_flags(-hi, CHOCH_PIVOT_N)
    known = [p for p in np.flatnonzero(flags[:k]) if p + CHOCH_PIVOT_N < start]
    if not known:
        return None
    level = lo[known[-1]] if direction == SHORT else hi[known[-1]]
    for m in range(start, min(len(cl), start + CHOCH_MAX_BARS)):
        if (hi[m] > extreme) if direction == SHORT else (lo[m] < extreme):
            return None
        if (cl[m] < level) if direction == SHORT else (cl[m] > level):
            return m
    return None


def _ob_unmitigated(b15: pd.DataFrame, ob_idx: int, end: int, direction: str, ob_low: float, ob_high: float) -> bool:
    """Na het eerste slot voorbij het order block (short: onder het laag) raakte geen candle tot end (exclusief) het weer."""
    hi, lo, cl = (b15[c].to_numpy(float) for c in ("high", "low", "close"))
    left = False
    for m in range(ob_idx + 1, end):
        if not left:
            left = bool((cl[m] < ob_low) if direction == SHORT else (cl[m] > ob_high))
            continue
        if (hi[m] >= ob_low) if direction == SHORT else (lo[m] <= ob_high):
            return False
    return True


def legs_for(entry: str, direction: str, rng: Range, zone_price: float, ref_price: float) -> list[tuple[float, float]]:
    """[(gewicht, prijs)]. Een limiet aan de verkeerde kant van de koers is een marktorder: die vervalt, dit is een limietrecept."""
    edge = rng.high if direction == SHORT else rng.low
    raw = [(EDGE_WEIGHT, edge), (OB_WEIGHT, zone_price)] if entry == "split" else [(1.0, zone_price)]
    return [(w, p) for w, p in raw if (p > ref_price if direction == SHORT else p < ref_price)]


def _range_features(r: Range, start_at: pd.Timestamp, tf: str) -> dict:
    return {"touches_high": r.high_touches, "touches_low": r.low_touches, "width_atr": r.width / r.atr,
            "age_bars": int(round((start_at - r.first_at) / TF_DELTA[tf])), "edge_spread_atr": max(r.high_spread, r.low_spread) / r.atr}


def _setup(direction, family, tf, r, zone_low, zone_high, zone_at, sweep_at, extreme, return_at, placed_at, place_idx, ref_price, legs, atr_t,
           trend, hh, ll, ok, features) -> dict:
    return {"direction": direction, "family": family, "tf": tf, "range_high": r.high, "range_low": r.low, "range_first_at": r.first_at,
            "zone_low": zone_low, "zone_high": zone_high, "zone_at": zone_at, "sweep_at": sweep_at, "extreme": extreme, "return_at": return_at,
            "placed_at": placed_at, "place_idx15": place_idx, "ref_price": ref_price, "legs": legs, "atr_t": atr_t, "htf_trend": int(trend),
            "htf_pos": _htf_pos(r, hh, ll), "htf_ok": bool(ok), "features": features}


def _sweep_setups(frames, tf, entry, confirm, use_htf, ranges) -> tuple[list[dict], list[dict]]:
    b15 = frames["15m"]
    bt = add_indicators(frames[TRIGGER_TF[tf]]).reset_index(drop=True)
    b_tf, rlist = ranges
    sweeps, refused = find_sweeps(bt, active_for(bt, b_tf, rlist, tf))
    trend, hh, ll = htf_context(bt, frames["4h"])
    ts, ts15, clt, cl15 = bt["timestamp"], b15["timestamp"], bt["close"].to_numpy(float), b15["close"].to_numpy(float)
    dt = TF_DELTA[TRIGGER_TF[tf]]
    setups = []
    for sw in sweeps:
        r, d, at = sw.rng, sw.direction, ts.iloc[sw.ret] + dt
        ok = htf_ok(d, int(trend[sw.ret]), float(hh[sw.ret]), float(ll[sw.ret]), r)
        if use_htf and not ok:
            refused.append({"at": at, "direction": d, "reason": "HTF-filter: tegen de 4u-trend en aan de verkeerde kant van de grotere range"})
            continue
        k = _extreme_15m(b15, ts.iloc[sw.start], at, d)
        if k is None:
            refused.append({"at": at, "direction": d, "reason": "geen 15m-candles bij de prik"})
            continue
        ob_low, ob_high, ob_idx, ob_real = order_block(b15, k, d)
        start15 = int(np.searchsorted(ts15.to_numpy(), at.to_datetime64()))
        if confirm == "choch15":
            m = choch_index(b15, k, start15, d, sw.extreme)
            if m is None:
                refused.append({"at": at, "direction": d, "reason": "geen CHoCH op 15m binnen 6 uur"})
                continue
            placed_at, place_idx, ref_price = ts15.iloc[m] + TF_DELTA["15m"], m + 1, float(cl15[m])
        else:
            placed_at, place_idx, ref_price = at, start15, float(clt[sw.ret])
        legs = legs_for(entry, d, r, (ob_low + ob_high) / 2, ref_price)
        if not legs:
            refused.append({"at": placed_at, "direction": d, "reason": "geen geldige limiet: het order block ligt aan de verkeerde kant van de koers"})
            continue
        features = {**_range_features(r, ts.iloc[sw.start], tf), "ob_opposite": ob_real, "displacement_atr": abs(sw.extreme - ref_price) / sw.atr,
                    "zone_fresh": _ob_unmitigated(b15, ob_idx, place_idx, d, ob_low, ob_high), "zone_atr": (ob_high - ob_low) / sw.atr}
        setups.append(_setup(d, "sweep", tf, r, ob_low, ob_high, ts15.iloc[ob_idx], ts.iloc[sw.start], sw.extreme, at, placed_at, place_idx,
                             ref_price, legs, sw.atr, trend[sw.ret], hh[sw.ret], ll[sw.ret], ok, features))
    return setups, refused


def _zone_setups(frames, tf, entry, confirm, use_htf, ranges) -> tuple[list[dict], list[dict]]:
    b15 = frames["15m"]
    b, rlist = ranges
    hi, lo, cl, atr = (b[c].to_numpy(float) for c in ("high", "low", "close", "atr"))
    ts, ts15, cl15 = b["timestamp"], b15["timestamp"], b15["close"].to_numpy(float)
    trend, hh, ll = htf_context(b, frames["4h"])
    setups, refused = [], []
    for z in find_zones(b):
        d = SHORT if z.kind == "bear" else LONG
        inner = z.inner(d)
        for i in range(z.known_idx + 1, min(len(b), z.known_idx + 1 + ZONE_MAX_AGE)):
            if not zone_active(z, i):
                break
            near = (inner - APPROACH_ATR * atr[i] <= cl[i] < inner and hi[i] < inner) if d == SHORT else (inner < cl[i] <= inner + APPROACH_ATR * atr[i] and lo[i] > inner)
            touched = (hi[i] >= inner) if d == SHORT else (lo[i] <= inner)
            if not (near if confirm == "slot" else touched):
                continue
            at, r = ts.iloc[i] + TF_DELTA[tf], rlist[i]
            if r is None:
                refused.append({"at": at, "direction": d, "reason": f"geen range op {tf} bij de nadering van de zone"})
                continue
            in_band = (inner >= r.high - EDGE_BAND * r.width) if d == SHORT else (inner <= r.low + EDGE_BAND * r.width)
            if not in_band:
                refused.append({"at": at, "direction": d, "reason": "zone ligt niet aan de rand van de range"})
                continue
            ok = htf_ok(d, int(trend[i]), float(hh[i]), float(ll[i]), r)
            if use_htf and not ok:
                refused.append({"at": at, "direction": d, "reason": "HTF-filter: tegen de 4u-trend en aan de verkeerde kant van de grotere range"})
                continue
            start15 = int(np.searchsorted(ts15.to_numpy(), at.to_datetime64()))
            if confirm == "choch15":
                k = _extreme_15m(b15, ts.iloc[i], at, d)
                extreme = float(hi[i] if d == SHORT else lo[i])
                m = None if k is None else choch_index(b15, k, start15, d, extreme)
                if m is None:
                    refused.append({"at": at, "direction": d, "reason": "geen CHoCH op 15m binnen 6 uur"})
                    break
                placed_at, place_idx, ref_price = ts15.iloc[m] + TF_DELTA["15m"], m + 1, float(cl15[m])
            else:
                placed_at, place_idx, ref_price = at, start15, float(cl[i])
            legs = legs_for(entry, d, r, inner, ref_price)
            if not legs:
                refused.append({"at": placed_at, "direction": d, "reason": "geen geldige limiet: de zone ligt aan de verkeerde kant van de koers"})
                break
            features = {**_range_features(r, ts.iloc[i], tf), "ob_opposite": z.disp_bars <= 2, "displacement_atr": z.disp_atr,
                        "zone_fresh": retests_before(z, b, i) <= 1, "zone_atr": (z.high - z.low) / atr[i]}
            setups.append(_setup(d, "zone", tf, r, z.low, z.high, ts.iloc[z.ob_idx], None, None, None, placed_at, place_idx, ref_price, legs,
                                 float(atr[i]), trend[i], hh[i], ll[i], ok, features))
            break
    return setups, refused


def find_setups(frames: dict, tf: str, family: str, entry: str, confirm: str, use_htf: bool,
                ranges: Optional[tuple[pd.DataFrame, list]] = None) -> tuple[list[dict], list[dict]]:
    """frames: uitvoer van build_frames. ranges: uitvoer van range_series voor tf (het lab rekent die één keer per coin)."""
    ranges = ranges if ranges is not None else range_series(frames[tf], tf)
    if family == "zone":
        return _zone_setups(frames, tf, entry, confirm, use_htf, ranges)
    return _sweep_setups(frames, tf, entry, confirm, use_htf, ranges)


def raw_stops(setup: dict) -> dict[str, float]:
    """Ruwe stops: buitenkant van de zone (of het uiterste van de sweep) plus een buffer in ATR. Bij de zone-retest is er geen wick."""
    side = 1 if setup["direction"] == SHORT else -1
    outer = setup["zone_high"] if setup["direction"] == SHORT else setup["zone_low"]
    out = {}
    for name, (base, buf) in STOP_BUFFER.items():
        ref = outer if base == "zone" else setup.get("extreme")
        if ref is not None:
            out[name] = ref + side * buf * setup["atr_t"]
    return out


def final_stop(setup: dict, name: str) -> float:
    legs = setup["legs"]
    planned = sum(w * p for w, p in legs) / sum(w for w, _ in legs)
    return smc_eval.floor_stop(setup["direction"], planned, raw_stops(setup)[name], min_pct=MIN_STOP_PCT)


def diagnose(frames: dict, at: pd.Timestamp, direction: str, tf: str, family: str, entry: str, confirm: str, use_htf: bool,
             window: pd.Timedelta = pd.Timedelta(hours=12)) -> dict:
    """Voor de misser-controle: zag deze variant een setup rond `at`, en zo niet, welke regel weigerde. Volgorde: setup, weigering, en anders
    waarom er geen range of geen zone was op het laatste slot vóór `at`."""
    setups, refused = find_setups(frames, tf, family, entry, confirm, use_htf)
    near = [s for s in setups if s["direction"] == direction and abs(s["placed_at"] - at) <= window]
    if near:
        return {"seen": True, "reason": "", "setup": min(near, key=lambda s: abs(s["placed_at"] - at))}
    ref = [r for r in refused if r["direction"] == direction and abs(r["at"] - at) <= window]
    if ref:
        return {"seen": False, "reason": min(ref, key=lambda r: abs(r["at"] - at))["reason"], "setup": None}
    b = add_indicators(frames[tf]).reset_index(drop=True)
    idx = int(((b["timestamp"] + TF_DELTA[tf]) <= at).sum()) - 1
    if idx < 0:
        return {"seen": False, "reason": f"geen range op {tf}: te weinig candles", "setup": None}
    hi, lo = b["high"].to_numpy(float), b["low"].to_numpy(float)
    rng, why = range_at(b, idx, tf, tl._pivot_flags(-hi, PIVOT_N), tl._pivot_flags(lo, PIVOT_N))
    if rng is None:
        return {"seen": False, "reason": f"geen range op {tf}: {why}", "setup": None}
    if family == "zone":
        kind = "bear" if direction == SHORT else "bull"
        if not any(z.kind == kind and zone_active(z, idx) for z in find_zones(b)):
            return {"seen": False, "reason": f"range op {tf}, maar geen actieve {'aanbod' if kind == 'bear' else 'vraag'}zone", "setup": None}
        return {"seen": False, "reason": f"range en zone op {tf}, maar de koers kwam niet binnen {APPROACH_ATR} ATR van de zone", "setup": None}
    return {"seen": False, "reason": f"range op {tf} gevonden, maar geen prik voorbij de rand van minstens {SWEEP_MIN_ATR} ATR", "setup": None}
```

- [ ] **Step 4: Maak de golden en controleer hem met de hand**

Run: `REGEN_GOLDEN=1 python3 -m unittest tests.replay.test_rangesweep.SweepSetupTest.test_golden -v`
Controleer `tests/golden/range_sweep_setup.json` tegen de definities: `range_high` 106.025, `range_low` 99.975, `extreme` 106.5, `zone_low` 105.875, `zone_high` 106.5, `legs` `[[1.0, 106.1875]]`, `ref_price` 105.6, `direction` short, `family` sweep.

- [ ] **Step 5: Run alle tests**

Run: `python3 -m unittest tests.replay.test_rangesweep -v`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/replay/rangesweep.py tests/replay/test_rangesweep.py tests/golden/range_sweep_setup.json
git commit -m "feat: zone-retest en sweep, stops en diagnose voor de range sweep"
```

---

### Task 6: Setupscore 40/60

**Files:**
- Modify: `app/chance_checks.py`
- Test: `tests/test_chance_checks.py`

**Interfaces:**
- Consumes: de `features`-dict uit taak 5.
- Produces: `chance_checks.range_sweep_checks(features: dict, tf: str) -> list[tuple[str, bool, int]]`, `chance_checks.weighted_finish(checks) -> tuple[str, float]`, `chance_checks.grade_of(score: float) -> str`.

- [ ] **Step 1: Schrijf de falende tests**

```python
class RangeSweepScoreTest(unittest.TestCase):
    F = {"touches_high": 6, "touches_low": 6, "width_atr": 9.3, "age_bars": 120, "edge_spread_atr": 0.0, "ob_opposite": True,
         "displacement_atr": 1.3, "zone_fresh": True, "zone_atr": 0.9}

    def test_fixture_scores_85_and_is_strong(self):
        reason, score = chance_checks.weighted_finish(chance_checks.range_sweep_checks(self.F, "1h"))
        self.assertEqual(score, 85.0)
        self.assertEqual(chance_checks.grade_of(score), "A")
        self.assertIn("✗ Sterke beweging weg van de zone (minstens 1,5 ATR)", reason)

    def test_weights_are_forty_and_sixty(self):
        checks = chance_checks.range_sweep_checks(self.F, "1h")
        self.assertEqual(sum(w for _, _, w in checks[:4]), 40)
        self.assertEqual(sum(w for _, _, w in checks[4:]), 60)

    def test_age_minimum_depends_on_timeframe(self):
        f = {**self.F, "age_bars": 40}
        by_label = lambda tf: {l: ok for l, ok, _ in chance_checks.range_sweep_checks(f, tf)}
        self.assertFalse(by_label("30m")["Range minstens 48 candles oud"])
        self.assertTrue(by_label("2h")["Range minstens 36 candles oud"])

    def test_grades(self):
        self.assertEqual([chance_checks.grade_of(s) for s in (80, 79.9, 60, 59.9)], ["A", "B", "B", "C"])
```

- [ ] **Step 2: Run en zie falen**

Run: `python3 -m unittest tests.test_chance_checks -v`
Expected: FAIL met `AttributeError: ... range_sweep_checks`.

- [ ] **Step 3: Implementeer**

```python
WeightedCheck = tuple[str, bool, int]
GRADE_A, GRADE_B = 80.0, 60.0


def range_sweep_checks(f: dict, tf: str) -> list[WeightedCheck]:
    """Onze lezing van "Range 40% order block 60%" (docs/onderzoek/range-sweep/preregistratie.md): 40 punten voor de range, 60 voor de zone.
    Elk kenmerk is gemeten bij het plaatsen van de order. Het lab en Bewijs tonen per graad of een hoge score een betere stop geeft; aangenomen wordt het niet."""
    age_min = {"30m": 48, "1h": 48, "2h": 36, "4h": 36}[tf]
    return [
        ("Beide randen minstens 4 keer aangeraakt", min(int(f["touches_high"]), int(f["touches_low"])) >= 4, 10),
        ("Breedte tussen 4 en 10 ATR", 4.0 <= float(f["width_atr"]) <= 10.0, 10),
        (f"Range minstens {age_min} candles oud", int(f["age_bars"]) >= age_min, 10),
        ("Schone randen (spreiding hooguit 0,25 ATR)", float(f["edge_spread_atr"]) <= 0.25, 10),
        ("Echte tegenkaars vlak voor de beweging", bool(f["ob_opposite"]), 15),
        ("Sterke beweging weg van de zone (minstens 1,5 ATR)", float(f["displacement_atr"]) >= 1.5, 15),
        ("Zone vers (hooguit één eerdere aanraking)", bool(f["zone_fresh"]), 15),
        ("Zone dun (hooguit 1,5 ATR)", float(f["zone_atr"]) <= 1.5, 15),
    ]


def weighted_finish(checks: list[WeightedCheck]) -> tuple[str, float]:
    """Zelfde reason-vorm als finish, maar de score telt punten in plaats van het aandeel kenmerken."""
    reason = " | ".join(("✓ " if ok else "✗ ") + label for label, ok, _ in checks)
    return reason, float(sum(w for _, ok, w in checks if ok)) * 100.0 / sum(w for _, _, w in checks)


def grade_of(score: float) -> str:
    return "A" if score >= GRADE_A else "B" if score >= GRADE_B else "C"
```

- [ ] **Step 4: Run en zie slagen**

Run: `python3 -m unittest tests.test_chance_checks -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/chance_checks.py tests/test_chance_checks.py
git commit -m "feat: setupscore 40/60 voor de range sweep"
```

---

### Task 7: Misser-controle voor de range sweep (poort 0a)

**Files:**
- Modify: `scripts/misser_check.py`, `docs/onderzoek/range-sweep/missers.md` (na de echte run)
- Test: `tests/test_misser.py`

**Interfaces:**
- Consumes: `rangesweep.diagnose`, `rangesweep.build_frames` (taken 4, 5), `misser.parse_rows` (taak 3).
- Produces: `misser_check.RS_COMBOS: tuple[tuple[str, str, str, str, bool], ...]` (naam, familie, tf, bevestiging, htf), `misser_check.fetch_rangesweep(coin, at) -> dict` (frames), `misser_check.judge_rangesweep(frames, at, direction, tf_hint="", window_hours=12) -> dict` met `engines`, `blocker`, `per_variant`; CLI-opties `--motor alle|rangesweep` en `--venster-uren`.

- [ ] **Step 1: Schrijf de falende tests**

```python
class RangeSweepJudgeTest(unittest.TestCase):
    def frames(self):
        from app.replay import rangesweep as rs
        from tests.replay.rangesweep_fixtures import frames
        b15, b1h, b4h = frames()
        return rs.build_frames(b15, b1h, b4h), b1h

    def test_fixture_short_zone_retest_is_seen_without_htf(self):
        from tests.replay.rangesweep_fixtures import FIRST_SHORT_ZONE_SETUP_HOUR
        f, b1h = self.frames()
        at = b1h["timestamp"].iloc[FIRST_SHORT_ZONE_SETUP_HOUR] + pd.Timedelta(hours=1)
        r = misser_check.judge_rangesweep(f, at, "short", tf_hint="1h")
        self.assertIn("range_sweep:RZ_1H_ZONDERHTF", r["engines"])
        self.assertTrue(all("_1H" in k for k in r["per_variant"]))

    def test_fixture_sweep_is_seen(self):
        from tests.replay.rangesweep_fixtures import SWEEP_HOUR
        f, b1h = self.frames()
        at = b1h["timestamp"].iloc[SWEEP_HOUR] + pd.Timedelta(hours=1)
        self.assertIn("range_sweep:RS_1H_ZONDERHTF", misser_check.judge_rangesweep(f, at, "short")["engines"])

    def test_blocker_is_the_reason_of_the_furthest_variant(self):
        f, b1h = self.frames()
        r = misser_check.judge_rangesweep(f, b1h["timestamp"].iloc[30], "short")
        self.assertEqual(r["engines"], [])
        self.assertTrue(r["blocker"].startswith("range_sweep: "))
```

- [ ] **Step 2: Run en zie falen**

Run: `python3 -m unittest tests.test_misser -v`
Expected: FAIL met `AttributeError: ... judge_rangesweep`.

- [ ] **Step 3: Implementeer**

In `scripts/misser_check.py`:

```python
from app.replay import rangesweep as rs  # noqa: E402

# Zelfde combinaties als rangesweep_lab.VARIANTS zonder SPLIT en OIFLUSH (tests/test_rangesweep_lab.py toetst dat). Die twee zien dezelfde setups
# als hun basisvariant (een andere ordergrootte of een filter), dus de misser-controle hoeft ze niet apart te rekenen.
RS_COMBOS = (("RZ_30M", "zone", "30m", "slot", True), ("RZ_1H", "zone", "1h", "slot", True), ("RZ_2H", "zone", "2h", "slot", True),
             ("RZ_4H", "zone", "4h", "slot", True), ("RZ_1H_CHOCH", "zone", "1h", "choch15", True), ("RZ_2H_CHOCH", "zone", "2h", "choch15", True),
             ("RZ_2H_ZONDERHTF", "zone", "2h", "slot", False), ("RS_30M", "sweep", "30m", "slot", True), ("RS_1H", "sweep", "1h", "slot", True),
             ("RS_2H", "sweep", "2h", "slot", True), ("RS_4H", "sweep", "4h", "slot", True), ("RS_1H_CHOCH", "sweep", "1h", "choch15", True),
             ("RS_1H_ZONDERHTF", "sweep", "1h", "slot", False))
# Extra combinaties zonder HTF, alleen in de misser-controle: ze vertellen of juist het HTF-filter een voorbeeld weigerde.
RS_DIAG_ONLY = tuple((f"{n}_ZONDERHTF", fam, tf, c, False) for n, fam, tf, c, h in RS_COMBOS if h and "ZONDERHTF" not in n and f"{n}_ZONDERHTF" not in {x[0] for x in RS_COMBOS})
# Hoe ver een variant kwam: hoe hoger, hoe dichter bij een setup. De blokkerende regel is die van de variant die het verst kwam.
RS_STAGE = {"geen range": 0, "range op": 1, "range en zone": 2, "zone ligt niet": 2, "prik te diep": 2, "geen terugkeer": 2, "HTF-filter": 3,
            "geen 15m": 3, "geen CHoCH": 4, "geen geldige limiet": 5}


def _stage(reason: str) -> int:
    return max((v for k, v in RS_STAGE.items() if reason.startswith(k)), default=0)


def fetch_rangesweep(coin: str, at: pd.Timestamp) -> dict:
    """15m, 1u en 4u tot 14 uur na `at`, daaruit 30m en 2u zoals het lab. 4u genoeg voor 180 candles HTF plus de EMA van 200."""
    parts = []
    for tf, back in (("15m", pd.Timedelta(days=9)), ("1h", pd.Timedelta(days=40)), ("4h", pd.Timedelta(days=160))):
        df = exchange.fetch_ohlcv(coin, timeframe=tf, limit=1000, since=int((at - back).timestamp() * 1000))
        parts.append(df[df["timestamp"] <= at + pd.Timedelta(hours=14)].reset_index(drop=True))
    return rs.build_frames(*parts)


def judge_rangesweep(frames: dict, at: pd.Timestamp, direction: str, tf_hint: str = "", window_hours: float = 12) -> dict:
    per, engines = {}, []
    for name, family, tf, confirm, htf in RS_COMBOS + RS_DIAG_ONLY:
        if tf_hint and tf != tf_hint:
            continue
        d = rs.diagnose(frames, at, direction, tf, family, "zone" if family == "zone" else "ob", confirm, htf, pd.Timedelta(hours=window_hours))
        per[name] = "gezien" if d["seen"] else d["reason"]
        if d["seen"] and name in {c[0] for c in RS_COMBOS}:
            engines.append(f"range_sweep:{name}")
    blocker = None
    if not engines and per:
        name = max(per, key=lambda n: (per[n] == "gezien") * 10 + _stage(per[n]))
        blocker = f"range_sweep: {per[name]} ({name})"
    return {"engines": engines, "blocker": blocker, "per_variant": per}
```

Let op: een voorbeeld dat alleen een `RS_DIAG_ONLY`-combinatie ziet, telt niet als gezien; de blokker wordt dan "gezien (RZ_2H_ZONDERHTF)"-achtig. Maak de blokkertekst in dat geval expliciet: `blocker = f"range_sweep: alleen zonder HTF-filter gezien ({name})"`.

In `run_csv` een parameter `motor: str = "alle"`, `window_hours: float = 12` en `fetch_rs=None`: bij `motor == "rangesweep"` per rij `res = judge_rangesweep((fetch_rs or fetch_rangesweep)(r["coin"], pd.Timestamp(r["at"])), pd.Timestamp(r["at"]), r["direction"], r.get("tf", ""), window_hours)` in plaats van `judge`, en print daaronder per variant één regel `naam: reden`. In `main`: `ap.add_argument("--motor", choices=("alle", "rangesweep"), default="alle")`, `ap.add_argument("--venster-uren", type=float, default=12.0)`, doorgeven aan `run_csv`; zonder `--csv` en met `--motor rangesweep` print het script `judge_rangesweep(fetch_rangesweep(coin, at), at, a.direction, window_hours=a.venster_uren)` per variant.

- [ ] **Step 4: Run en zie slagen**

Run: `python3 -m unittest tests.test_misser -v`
Expected: PASS.

- [ ] **Step 5: Poort 0a op de VPS (geen code)**

```bash
cd /opt/<map uit README.md> && git pull
.venv/bin/python3 scripts/misser_check.py --csv docs/onderzoek/range-sweep/handtrades.csv --alleen-parsen
.venv/bin/python3 scripts/misser_check.py --csv docs/onderzoek/range-sweep/handtrades.csv --motor rangesweep --venster-uren 12
.venv/bin/python3 scripts/misser_check.py --csv docs/onderzoek/range-sweep/handtrades.csv --motor rangesweep --venster-uren 36   # WLD: de trade liep al bij de screenshot
```

Zet elke rij in `docs/onderzoek/range-sweep/missers.md`. Verwachting vooraf (zodat de uitkomst niet achteraf mooi gepraat wordt): ARB, beide APT-shorts en AAVE horen bij de zone-retest, WLD bij de sweep. Een zone-retest op APT 1u zonder range op 1u is een mogelijke misser ("geen range op 1h"); de 2u-range van APT zou hem wel kunnen dragen.

Wat we met elke misser doen:
- **Gezien:** loggen.
- **Geweigerd door een regel:** regel en gemeten waarde noteren. Weigert dezelfde regel minstens 2 van de 5 (later 30% bij minstens 10), dan mag die regel in een definitieronde veranderen. Hooguit twee rondes, elk gelogd met oud, nieuw en de voorbeelden die erom vroegen. Een ronde verandert een regel, nooit iets op grond van de uitkomst van een voorbeeld.
- **Alleen zonder HTF gezien:** noteren; het HTF-filter blijft, want daarvoor zijn de ZONDERHTF-varianten.
- **Geen data:** apart tellen.

Poort 0a: minstens 3 van de 5 gezien na hooguit twee rondes (S0). Vraag de gebruiker meer voorbeelden (doel: minstens 10) via `scripts/range_sweep_examples.py` en zijn eigen screenshots.

- [ ] **Step 6: Commit**

```bash
git add scripts/misser_check.py tests/test_misser.py docs/onderzoek/range-sweep/missers.md
git commit -m "feat: misser-controle voor de range sweep"
```

---

### Task 8: Getekende setup en galerij (poort 0b en poort 1)

**Files:**
- Modify: `app/setup_chart.py`, `web/static/style.css` (klassen `sc-range`, `sc-zone`, `sc-sweep`)
- Create: `scripts/range_sweep_gallery.py`
- Test: `tests/test_setup_chart.py` (nieuw)

**Interfaces:**
- Consumes: setups en zones uit taken 4 en 5.
- Produces: `setup_chart.range_sweep_svg(candles: list[list], setup: dict, stop: float, price: Optional[float] = None, zones: Optional[list[dict]] = None) -> str`. Tekent: de range als rechthoek (`sc-range`), de zone van de setup als rechthoek van `zone_low` tot `zone_high` vanaf `zone_at` tot rechts (`sc-zone`), extra zones (`zones`: `{"low", "high", "from", "kind"}`) gedempt, bij een sweep de wick op `extreme` bij `sweep_at` (`sc-sweep`), elke limiet (`sc-limit`, "Limiet" of "Limiet 40%"/"Limiet 60%"), de stop (`sc-stop`), midden en overkant als stippellijn (`sc-target`, "Midden (ref.)", "Overkant (ref.)") en de koers (`sc-price`).

- [ ] **Step 1: Schrijf de falende test**

```python
import unittest

from app import setup_chart
from app.replay import rangesweep as rs
from tests.replay.rangesweep_fixtures import frames


class RangeSweepSvgTest(unittest.TestCase):
    def setUp(self):
        b15, b1h, b4h = frames()
        f = rs.build_frames(b15, b1h, b4h)
        self.sweep = rs.find_setups(f, "1h", "sweep", "ob", "slot", use_htf=False)[0][0]
        self.zone = rs.find_setups(f, "1h", "zone", "split", "slot", use_htf=False)[0][0]
        self.candles = [[r.timestamp.isoformat(), r.open, r.high, r.low, r.close] for r in b1h.itertuples()]

    def test_sweep_draws_every_part(self):
        svg = setup_chart.range_sweep_svg(self.candles[-80:], self.sweep, stop=106.7, price=105.0)
        for cls in ("sc-range", "sc-zone", "sc-sweep", "sc-limit", "sc-stop", "sc-target", "sc-price"):
            self.assertIn(cls, svg)
        self.assertIn("Midden (ref.)", svg)
        self.assertIn("Overkant (ref.)", svg)
        self.assertNotIn("Doel", svg)

    def test_zone_retest_has_no_sweep_and_shows_the_split(self):
        svg = setup_chart.range_sweep_svg(self.candles[:140], self.zone, stop=106.2)
        self.assertNotIn("sc-sweep", svg)
        self.assertIn("Limiet 40%", svg)
        self.assertIn("Limiet 60%", svg)

    def test_no_candles_no_svg(self):
        self.assertEqual(setup_chart.range_sweep_svg([], self.sweep, stop=106.7), "")
```

- [ ] **Step 2: Run en zie falen**

Run: `python3 -m unittest tests.test_setup_chart -v`
Expected: FAIL met `AttributeError: ... range_sweep_svg`.

- [ ] **Step 3: Implementeer**

Lees eerst `setup_svg` in `app/setup_chart.py` en gebruik dezelfde schaal, marges, `_fmt`, `_ts`, `SHOWN_BARS` en `FUTURE_BARS`. Schrijf `range_sweep_svg` met dezelfde opbouw (candles, dan vakken, dan horizontale lijnen met labels rechts). Hulpfunctie:

```python
def _rect(x0: float, x1: float, y_top: float, y_bottom: float, cls: str, label: str = "") -> str:
    out = f'<rect class="{cls}" x="{x0:.1f}" y="{y_top:.1f}" width="{max(1.0, x1 - x0):.1f}" height="{max(1.0, y_bottom - y_top):.1f}"/>'
    if label:
        out += f'<text class="{cls}-label" x="{x0 + 3:.1f}" y="{y_top + 11:.1f}">{label}</text>'
    return out
```

De range loopt van de x van `range_first_at` (of de linkerrand) tot de x van `placed_at`; de zone van de x van `zone_at` tot de rechterrand van het plaatsvak, label "Aanbod" (short) of "Vraag" (long); extra zones in dezelfde klasse met `sc-zone is-other`; de sweep is een streep van 8 px op `extreme` bij de x van `sweep_at` met label "Sweep" en alleen als `extreme` niet `None` is. Labels van limieten: met twee limieten "Limiet 40%" en "Limiet 60%" (gewicht maal 100, zonder decimalen), met één "Limiet". Midden `(range_high + range_low) / 2`, overkant `range_low` bij short en `range_high` bij long. In `style.css`, naast de `sc-*`-regels, met de bestaande tokens voor het Tiffany-accent, tekst en gedempte tekst (neem hun echte namen uit `:root`):

```css
.sc-range { fill: var(--accent); fill-opacity: .06; stroke: var(--accent); stroke-opacity: .45; stroke-dasharray: 3 3; }
.sc-zone { fill: var(--accent); fill-opacity: .18; stroke: var(--accent); }
.sc-zone.is-other { fill-opacity: .07; stroke-opacity: .35; }
.sc-sweep { stroke: var(--text); stroke-width: 2; }
.sc-range-label, .sc-zone-label { font-size: 10px; fill: var(--muted); }
```

- [ ] **Step 4: Maak de galerij**

`scripts/range_sweep_gallery.py`:

```python
"""Keuren met het oog. Twee standen, draai op de VPS:

  # poort 0b: elk voorbeeld uit de CSV met onze ranges en zones op dat moment, naast de screenshot te leggen
  .venv/bin/python3 scripts/range_sweep_gallery.py --csv docs/onderzoek/range-sweep/handtrades.csv --uit /tmp/range_sweep_voorbeelden.html
  # poort 1: willekeurige setups uit de historie, vaste seed
  .venv/bin/python3 scripts/range_sweep_gallery.py --coins BTC,ETH,SOL,ARB,APT,AAVE --n 30 --uit /tmp/range_sweep_galerij.html

Per kaart: klopt / klopt niet, met een reden (in docs/onderzoek/range-sweep/missers.md). Poort 1: minstens 80% klopt."""
import argparse
import random
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from app import misser, setup_chart  # noqa: E402
from app.replay import candles as cc, rangesweep as rs  # noqa: E402
from app.replay.lab import add_indicators  # noqa: E402

COMBOS = (("zone", "zone", "slot"), ("sweep", "ob", "slot"))


def _candles(frame: pd.DataFrame, t0, t1) -> list[list]:
    w = frame[(frame["timestamp"] >= t0) & (frame["timestamp"] <= t1)]
    return [[r.timestamp.isoformat(), r.open, r.high, r.low, r.close] for r in w.itertuples()]


def _zones_at(frame: pd.DataFrame, at) -> list[dict]:
    b = add_indicators(frame).reset_index(drop=True)
    idx = int((b["timestamp"] <= at).sum()) - 1
    return [{"low": z.low, "high": z.high, "from": b["timestamp"].iloc[z.ob_idx].isoformat(), "kind": z.kind}
            for z in rs.find_zones(b) if rs.zone_active(z, idx)]


def card(title: str, frame: pd.DataFrame, setup: dict, zones: list[dict]) -> str:
    span = setup["placed_at"] - setup["range_first_at"]
    candles = _candles(frame, setup["range_first_at"] - span * 0.15, setup["placed_at"] + pd.Timedelta(hours=24))
    stop = rs.final_stop(setup, "zone_025")
    return f"<section><h2>{title}</h2>{setup_chart.range_sweep_svg(candles, setup, stop, zones=zones)}<p>klopt / klopt niet: ______</p></section>"


def from_csv(path: str) -> list[str]:
    from scripts.misser_check import fetch_rangesweep
    cards = []
    for r in misser.parse_rows(Path(path).read_text(encoding="utf-8")):
        at = pd.Timestamp(r["at"])
        frames = fetch_rangesweep(r["coin"], at)
        tfs = [r["tf"]] if r["tf"] else list(rs.TFS)
        for tf in tfs:
            found = False
            for family, entry, confirm in COMBOS:
                d = rs.diagnose(frames, at, r["direction"], tf, family, entry, confirm, False, pd.Timedelta(hours=36))
                if d["seen"]:
                    cards.append(card(f"{r['coin']} {r['direction']} {tf} {family}: gezien · {r['source']}", frames[tf], d["setup"], _zones_at(frames[tf], at)))
                    found = True
            if not found:
                cards.append(f"<section><h2>{r['coin']} {r['direction']} {tf}: niet gezien · {r['source']}</h2><p>zones op dat moment: "
                             + ", ".join(f"{z['kind']} {z['low']:g}-{z['high']:g}" for z in _zones_at(frames[tf], at)) + "</p></section>")
    return cards


def random_cards(coins: list[str], n: int, jaren: float) -> list[str]:
    pool = []
    for coin in coins:
        frames = rs.build_frames(*(cc.ensure_candles(coin, jaren, timeframe=tf) for tf in ("15m", "1h", "4h")))
        for tf in rs.TFS:
            for family, entry, confirm in COMBOS:
                pool += [(coin, tf, family, s, frames[tf]) for s in rs.find_setups(frames, tf, family, entry, confirm, use_htf=True)[0]]
    random.Random(7).shuffle(pool)
    return [card(f"{k}. {coin} {s['direction']} · {tf} · {family} · {s['placed_at']:%Y-%m-%d %H:%M} UTC", fr, s, [])
            for k, (coin, tf, family, s, fr) in enumerate(pool[:n], 1)]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv")
    ap.add_argument("--coins", default="BTC,ETH,SOL,ARB,APT,AAVE")
    ap.add_argument("--n", type=int, default=30)
    ap.add_argument("--jaren", type=float, default=1.0)
    ap.add_argument("--uit", default="/tmp/range_sweep_galerij.html")
    a = ap.parse_args()
    cards = from_csv(a.csv) if a.csv else random_cards(a.coins.split(","), a.n, a.jaren)
    css = (Path(__file__).resolve().parent.parent / "web" / "static" / "style.css").read_text(encoding="utf-8")
    Path(a.uit).write_text(f"<!doctype html><meta charset=utf-8><style>{css}</style><body>" + "".join(cards) + "</body>", encoding="utf-8")
    print(f"{len(cards)} kaarten in {a.uit}")


if __name__ == "__main__":
    main()
```

De "______" op de pagina is het invulvak voor de keurder.

- [ ] **Step 5: Run en zie slagen**

Run: `python3 -m unittest tests.test_setup_chart -v`
Expected: PASS.

- [ ] **Step 6: Poort 0b en poort 1 (geen code)**

Poort 0b: draai de `--csv`-stand, open het bestand naast de vijf screenshots en noteer per voorbeeld in `missers.md` (tabel "Vergelijking met het oog") of onze range en zone liggen waar de zone op de screenshot ligt (binnen ongeveer een halve zonedikte). Poort 1: draai de willekeurige stand, laat de gebruiker de 30 kaarten keuren; minstens 80% "klopt": zet in de pre-registratie "Status: bevroren", de datum en de commit-hash. Daarna verandert geen definitie of constante meer.

- [ ] **Step 7: Commit**

```bash
git add app/setup_chart.py scripts/range_sweep_gallery.py web/static/style.css tests/test_setup_chart.py
git commit -m "feat: getekende range sweep en galerij voor de keuring"
```

---

### Task 9: Cluster-t, vulling en meting na de vulling

**Files:**
- Modify: `app/replay/stats.py`
- Create: `app/replay/stopquality.py`
- Test: `tests/replay/test_stats.py`, `tests/replay/test_stopquality.py` (nieuw)

**Interfaces:**
- Produces:
  - `stats.cluster_t(values: list[float], clusters: list) -> float`.
  - `stopquality.TTL_15M, HORIZON_15M, TIGHT_BACK_15M, TIGHT_WIN_15M, R_LEVELS = (1, 2, 3, 4, 5, 6), TRAIL_K, REF_NAMES = ("mid", "opp", "trail")`.
  - `atr_on_15m(b15, b1h_prepared) -> np.ndarray`.
  - `simulate_fills(direction, legs, stop, mid, b15, start) -> dict` met `filled: list[(gewicht, prijs, index)], first: Optional[int], cancel: str`.
  - `measure(direction, filled, stop, b15, atr15, range_high, range_low, cost_pct) -> dict` met `entry, stop, weight, stop_pct, stop_atr, cost_r, stop_hit, stop_r, hours_to_stop, mae_r, mfe_r, reach_1r .. reach_6r, back_in_range, win_after_stop, tight, ref_mid, ref_opp, ref_trail`.

- [ ] **Step 1: Schrijf de falende tests**

In `tests/replay/test_stats.py`:

```python
    def test_cluster_t(self):
        self.assertAlmostEqual(stats.cluster_t([1, 3, 5, 7], ["a", "a", "b", "b"]), 4 / (32 ** 0.5 / 4), places=9)
        self.assertEqual(stats.cluster_t([1, 1, 1], ["a", "b", "c"]), 0.0)
        self.assertEqual(stats.cluster_t([2.0], ["a"]), 0.0)
```

`tests/replay/test_stopquality.py`:

```python
import unittest

import numpy as np
import pandas as pd

from app.replay import stopquality as sq


def frame(rows):
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df.insert(0, "timestamp", pd.date_range("2025-01-06", periods=len(df), freq="15min", tz="UTC"))
    return df


class FillTest(unittest.TestCase):
    def test_short_limit_fills_when_the_high_reaches_it(self):
        b = frame([(104, 104.5, 103.8, 104.2), (104.2, 105.1, 104.0, 104.9)])
        self.assertEqual(sq.simulate_fills("short", [(1.0, 105.0)], 106.0, 100.0, b, 0), {"filled": [(1.0, 105.0, 1)], "first": 1, "cancel": ""})

    def test_open_beyond_the_stop_cancels(self):
        b = frame([(106.3, 106.5, 106.1, 106.2)])
        self.assertEqual(sq.simulate_fills("short", [(1.0, 105.0)], 106.0, 100.0, b, 0)["cancel"], "stop voor vulling")

    def test_mid_before_fill_cancels(self):
        b = frame([(104, 104.2, 99.9, 100.1)])
        self.assertEqual(sq.simulate_fills("short", [(1.0, 105.0)], 106.0, 100.0, b, 0)["cancel"], "weggelopen")

    def test_ttl(self):
        b = frame([(104, 104.1, 103.9, 104)] * (sq.TTL_15M + 5))
        self.assertEqual(sq.simulate_fills("short", [(1.0, 105.0)], 106.0, 100.0, b, 0)["cancel"], "verlopen")

    def test_split_fills_both_legs(self):
        b = frame([(104, 105.1, 104, 105), (105, 105.6, 104.9, 105.2)])
        self.assertEqual(sq.simulate_fills("short", [(0.4, 105.0), (0.6, 105.5)], 106.0, 100.0, b, 0)["filled"], [(0.4, 105.0, 0), (0.6, 105.5, 1)])

    def test_long_mirror(self):
        b = frame([(96, 96.2, 94.9, 95.1)])
        self.assertEqual(sq.simulate_fills("long", [(1.0, 95.0)], 94.0, 100.0, b, 0)["first"], 0)


class MeasureTest(unittest.TestCase):
    def setUp(self):
        self.b = frame([(104.5, 105.2, 104.4, 104.8), (104.8, 104.9, 103.9, 104.0), (104.0, 104.1, 102.8, 103.0),
                        (103.0, 106.1, 102.9, 105.9), (105.9, 105.95, 105.0, 105.2), (105.2, 105.3, 103.9, 104.1)])
        self.atr = np.full(len(self.b), 1.0)

    def test_short_reaches_two_r_then_stops(self):
        m = sq.measure("short", [(1.0, 105.0, 0)], 106.0, self.b, self.atr, 105.5, 100.0, 0.12)
        self.assertTrue(m["stop_hit"])
        self.assertAlmostEqual(m["stop_r"], -1.0)
        self.assertAlmostEqual(m["mfe_r"], 2.2)
        self.assertAlmostEqual(m["mae_r"], 1.0)
        self.assertEqual([m[f"reach_{k}r"] for k in sq.R_LEVELS], [True, True, False, False, False, False])
        self.assertAlmostEqual(m["hours_to_stop"], 0.75)
        self.assertAlmostEqual(m["cost_r"], 0.12 / 100 * 105.0)
        self.assertTrue(m["back_in_range"] and m["win_after_stop"] and m["tight"])

    def test_fill_candle_counts_only_against_you(self):
        b = frame([(104.5, 105.2, 103.0, 104.8), (104.8, 104.9, 104.5, 104.6)])
        m = sq.measure("short", [(1.0, 105.0, 0)], 106.0, b, np.ones(2), 105.5, 100.0, 0.12)
        self.assertFalse(m["reach_1r"])
        self.assertAlmostEqual(m["mfe_r"], 0.5)

    def test_gap_through_stop_fills_on_the_open(self):
        b = frame([(104.5, 105.1, 104.4, 104.8), (106.5, 106.8, 106.3, 106.6)])
        self.assertAlmostEqual(sq.measure("short", [(1.0, 105.0, 0)], 106.0, b, np.ones(2), 105.5, 100.0, 0.12)["stop_r"], -1.5)

    def test_mid_reference_takes_the_midpoint(self):
        b = frame([(104.5, 105.1, 104.4, 104.8), (104.8, 104.9, 102.6, 102.7)])
        self.assertAlmostEqual(sq.measure("short", [(1.0, 105.0, 0)], 106.0, b, np.ones(2), 105.5, 100.0, 0.12)["ref_mid"], 105.0 - 102.75)

    def test_r_unit_is_the_risk_actually_taken(self):
        m = sq.measure("short", [(0.4, 105.0, 0), (0.6, 105.5, 0)], 106.0, self.b, self.atr, 105.5, 100.0, 0.12)
        self.assertAlmostEqual(m["entry"], 105.3)
        self.assertAlmostEqual(m["stop_r"], -1.0)
        self.assertAlmostEqual(m["weight"], 1.0)


class AtrOn15mTest(unittest.TestCase):
    def test_uses_only_closed_hours(self):
        b1 = pd.DataFrame({"timestamp": pd.date_range("2025-01-06", periods=2, freq="1h", tz="UTC"), "atr": [1.0, 2.0]})
        b15 = pd.DataFrame({"timestamp": pd.date_range("2025-01-06 00:45", periods=6, freq="15min", tz="UTC")})
        a = sq.atr_on_15m(b15, b1)
        self.assertTrue(np.isnan(a[0]))
        self.assertEqual(list(a[1:5]), [1.0, 1.0, 1.0, 1.0])
        self.assertEqual(a[5], 2.0)
```

- [ ] **Step 2: Run en zie falen**

Run: `python3 -m unittest tests.replay.test_stats tests.replay.test_stopquality -v`
Expected: FAIL (`cluster_t` en `stopquality` bestaan niet).

- [ ] **Step 3: Implementeer**

In `app/replay/stats.py` (met `import math` bovenaan):

```python
def cluster_t(values: list[float], clusters: list) -> float:
    """t van het gemiddelde met een standaardfout die samenhang binnen een cluster (week) toelaat: se = sqrt(som_c (som_i in c (x_i - m))^2) / N.
    De gewone t telt 8 trades in één BTC-week als 8 metingen; dit telt ze als ongeveer één."""
    n = len(values)
    if n < 2:
        return 0.0
    m = sum(values) / n
    groups: dict = defaultdict(float)
    for v, c in zip(values, clusters):
        groups[c] += v - m
    se = math.sqrt(sum(g * g for g in groups.values())) / n
    return m / se if se > 0 else 0.0
```

`app/replay/stopquality.py`:

```python
"""Stopkwaliteit zonder vast doel: wat doet de stop van een setup, los van waar jij winst neemt. Per gevulde setup: stopafstand, kosten in R,
MAE en MFE, uren tot de stop, of +1R tot +6R vóór de stop kwamen, of de stop te krap was, en ter vergelijking drie referentie-uitgangen.
Regels in docs/onderzoek/range-sweep/preregistratie.md. Pure functies op 15m-candles."""
from typing import Optional

import numpy as np
import pandas as pd

from app.replay import trendlab as tl

TTL_15M = 96
HORIZON_15M = 672
TIGHT_BACK_15M = 48
TIGHT_WIN_15M = 192
# Tot 6R: de doelen in de voorbeelden lagen op 5 tot 14R. De tabel laat zien wat de stop toelaat, geen doel.
R_LEVELS = (1, 2, 3, 4, 5, 6)
TRAIL_K = 3.0
REF_NAMES = ("mid", "opp", "trail")


def atr_on_15m(b15: pd.DataFrame, b1h: pd.DataFrame) -> np.ndarray:
    """Per 15m-candle de ATR van de laatste 1u-candle die bij het openen gesloten was."""
    frame = pd.DataFrame({"timestamp": b1h["timestamp"] + pd.Timedelta(hours=1), "atr": b1h["atr"].to_numpy(float)})
    return pd.merge_asof(b15[["timestamp"]].reset_index(drop=True), frame, on="timestamp")["atr"].to_numpy(float)


def simulate_fills(direction: str, legs: list[tuple[float, float]], stop: float, mid: float, b15: pd.DataFrame, start: int) -> dict:
    """Vulling tegen de limietprijs. Vóór de eerste vulling vervalt de setup als een candle voorbij de stop opent, of als de koers het midden van de
    range raakt; na TTL_15M candles vervalt hij. Na de eerste vulling vullen de andere orders tot TTL of tot de stop."""
    short = direction == "short"
    op, hi, lo = (b15[c].to_numpy(float) for c in ("open", "high", "low"))
    waiting, filled = list(legs), []
    for m in range(start, min(len(hi), start + TTL_15M)):
        if not filled and ((op[m] >= stop) if short else (op[m] <= stop)):
            return {"filled": [], "first": None, "cancel": "stop voor vulling"}
        for leg in list(waiting):
            if (hi[m] >= leg[1]) if short else (lo[m] <= leg[1]):
                filled.append((leg[0], leg[1], m))
                waiting.remove(leg)
        if not filled and ((lo[m] <= mid) if short else (hi[m] >= mid)):
            return {"filled": [], "first": None, "cancel": "weggelopen"}
        if filled and (not waiting or ((hi[m] >= stop) if short else (lo[m] <= stop))):
            break
    if not filled:
        return {"filled": [], "first": None, "cancel": "verlopen"}
    return {"filled": filled, "first": filled[0][2], "cancel": ""}


def _ref_target(direction, entry, risk, stop, b15, first, last, target) -> Optional[float]:
    short = direction == "short"
    if (target >= entry) if short else (target <= entry):
        return None
    op, hi, lo, cl = (b15[c].to_numpy(float) for c in ("open", "high", "low", "close"))
    for m in range(first, last + 1):
        if (hi[m] >= stop) if short else (lo[m] <= stop):
            fill = max(op[m], stop) if short else min(op[m], stop)
            return ((entry - fill) if short else (fill - entry)) / risk
        if m > first and ((lo[m] <= target) if short else (hi[m] >= target)):
            return abs(target - entry) / risk
    return ((entry - cl[last]) if short else (cl[last] - entry)) / risk


def measure(direction: str, filled: list[tuple[float, float, int]], stop: float, b15: pd.DataFrame, atr15: np.ndarray,
            range_high: float, range_low: float, cost_pct: float) -> dict:
    """R-eenheid: het risico dat echt genomen is (gewogen instap tot de stop over de gevulde orders), zodat een stop-uit -1R is hoeveel orders er
    ook vulden. In de vulcandle telt alleen het nadeel. Een candle die de stop en een R-niveau raakt telt als stop."""
    short = direction == "short"
    weight = sum(w for w, _, _ in filled)
    entry = sum(w * p for w, p, _ in filled) / weight
    risk = abs(entry - stop)
    first = filled[0][2]
    op, hi, lo, cl = (b15[c].to_numpy(float) for c in ("open", "high", "low", "close"))
    last = min(len(cl), first + HORIZON_15M) - 1
    mae = mfe = 0.0
    reach = {k: False for k in R_LEVELS}
    stop_idx, stop_r = None, None
    for m in range(first, last + 1):
        adverse = ((hi[m] - entry) if short else (entry - lo[m])) / risk
        if (hi[m] >= stop) if short else (lo[m] <= stop):
            fill = max(op[m], stop) if short else min(op[m], stop)
            stop_idx, stop_r = m, ((entry - fill) if short else (fill - entry)) / risk
            mae = max(mae, -stop_r)
            break
        mae = max(mae, adverse)
        if m > first:
            fav = ((entry - lo[m]) if short else (hi[m] - entry)) / risk
            mfe = max(mfe, fav)
            for k in R_LEVELS:
                reach[k] = reach[k] or fav >= k
    back = win_after = False
    if stop_idx is not None:
        edge = range_high if short else range_low
        bw = slice(stop_idx + 1, min(len(cl), stop_idx + 1 + TIGHT_BACK_15M))
        back = bool(((cl[bw] < edge) if short else (cl[bw] > edge)).any())
        ww = slice(stop_idx + 1, min(len(cl), stop_idx + 1 + TIGHT_WIN_15M))
        win_after = bool(((lo[ww] <= entry - risk) if short else (hi[ww] >= entry + risk)).any())
    mid, opp = (range_high + range_low) / 2, (range_low if short else range_high)
    # De vulcandle is hierboven al tegen de stop getoetst; de meelopende stop begint op de candle erna.
    trail = stop_r if stop_idx == first else tl.exit_trail(b15.assign(atr=atr15), first + 1, -1 if short else 1, entry, stop, TRAIL_K, HORIZON_15M - 1)[0]
    a0 = atr15[first] if np.isfinite(atr15[first]) and atr15[first] > 0 else float("nan")
    return {"entry": entry, "stop": stop, "weight": weight, "stop_pct": risk / entry * 100, "stop_atr": risk / a0, "cost_r": cost_pct / 100 * entry / risk,
            "stop_hit": stop_idx is not None, "stop_r": stop_r, "hours_to_stop": None if stop_idx is None else (stop_idx - first) / 4,
            "mae_r": mae, "mfe_r": mfe, **{f"reach_{k}r": reach[k] for k in R_LEVELS},
            "back_in_range": back, "win_after_stop": win_after, "tight": back and win_after,
            "ref_mid": _ref_target(direction, entry, risk, stop, b15, first, last, mid),
            "ref_opp": _ref_target(direction, entry, risk, stop, b15, first, last, opp), "ref_trail": float(trail)}
```

- [ ] **Step 4: Run en zie slagen**

Run: `python3 -m unittest tests.replay.test_stats tests.replay.test_stopquality -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/replay/stats.py app/replay/stopquality.py tests/replay/test_stats.py tests/replay/test_stopquality.py
git commit -m "feat: stopmeting zonder doel en cluster-t"
```

---

### Task 10: Samenvatting, doelkans, placebo en toets op stopkwaliteit

**Files:**
- Modify: `app/replay/stopquality.py`
- Test: `tests/replay/test_stopquality.py`

**Interfaces:**
- Consumes: taak 9, `rangesweep.MIN_STOP_PCT`.
- Produces:
  - `MIN_FILLS = 300, MIN_WEEKS = 80, MAX_MEDIAN_COST_R = 0.10, MAX_HALF_DIFF = 0.10, MAX_BLOCK_DIFF = 0.15, N_BLOCKS = 6, MIN_PLACEBO_EDGE = 0.05, MAX_TIGHT_RATE = 0.25`.
  - `summarize(rows) -> dict`: `setups, n, fill_rate, cancels, weeks, median_stop_pct, median_stop_atr, median_cost_r, share_cost_over_01, stop_hit {p, ci}, reach {k: {p, ci}} voor k in R_LEVELS, median_hours_to_stop, mae_q, mfe_q, tight_rate, halves, blocks, ref {naam: {n, avg_net, ci}}, by_grade {A/B/C: {n, reach1, stop_hit}}`.
  - `doelkans_table(summary) -> list[dict]` met `r, p_text, ci_text, n`.
  - `placebo_rows(real, b15, b_trig, active, atr15, cost_pct, seed=0) -> pd.DataFrame` met `pair_id` en de velden van `measure`.
  - `accept(summary, real, placebo) -> dict` met `checks, passes, reason, placebo_diff, placebo_ci`.

- [ ] **Step 1: Schrijf de falende tests**

```python
def rows_for(reach1, weeks, cost=0.05, grade="A"):
    at = [pd.Timestamp("2025-01-06", tz="UTC") + pd.Timedelta(weeks=w) for w in weeks]
    n = len(reach1)
    df = pd.DataFrame({"row_id": [f"X:{k}" for k in range(n)], "at": at, "filled": True, "cancel": "", "reach_1r": reach1,
                       "stop_hit": [not r for r in reach1], "tight": [False] * n, "cost_r": cost, "stop_pct": 2.5, "stop_atr": 1.2,
                       "hours_to_stop": 3.0, "mae_r": 0.5, "mfe_r": 1.0, "ref_mid": 0.5, "ref_opp": 1.0, "ref_trail": 0.2, "grade": grade})
    for k in sq.R_LEVELS[1:]:
        df[f"reach_{k}r"] = False
    return df


class SummaryTest(unittest.TestCase):
    def test_counts_and_shares(self):
        s = sq.summarize(rows_for([True, False, True, True], [0, 0, 1, 1]))
        self.assertEqual((s["n"], s["weeks"]), (4, 2))
        self.assertAlmostEqual(s["reach"][1]["p"], 0.75)
        self.assertAlmostEqual(s["stop_hit"]["p"], 0.25)
        self.assertAlmostEqual(s["ref"]["trail"]["avg_net"], 0.15)
        self.assertEqual(sorted(s["reach"]), list(sq.R_LEVELS))

    def test_unfilled_rows_count_as_setups_only(self):
        extra = pd.DataFrame([{"at": pd.Timestamp("2025-01-06", tz="UTC"), "filled": False, "cancel": "weggelopen"}])
        s = sq.summarize(pd.concat([rows_for([True], [0]), extra], ignore_index=True))
        self.assertEqual((s["setups"], s["n"], s["cancels"]), (2, 1, {"weggelopen": 1}))

    def test_doelkans_table(self):
        t = sq.doelkans_table(sq.summarize(rows_for([True, False, True, True], [0, 0, 1, 1])))
        self.assertEqual([x["r"] for x in t], list(sq.R_LEVELS))
        self.assertEqual(t[0]["p_text"], "75%")


class AcceptTest(unittest.TestCase):
    def test_all_checks_named_and_small_sample_fails(self):
        real = rows_for([True, False] * 10, list(range(20)))
        out = sq.accept(sq.summarize(real), real, real.assign(pair_id=real["row_id"], reach_1r=False))
        self.assertFalse(out["passes"])
        self.assertFalse(out["checks"]["genoeg vullingen (300)"])
        self.assertTrue(out["checks"]["beter dan willekeurig (+1R vóór de stop minstens 5 procentpunt)"])
        self.assertEqual(len(out["checks"]), 7)

    def test_big_stable_sample_passes(self):
        weeks = [k // 4 for k in range(400)]
        real = rows_for([k % 2 == 0 for k in range(400)], weeks)
        out = sq.accept(sq.summarize(real), real, real.assign(pair_id=real["row_id"], reach_1r=[k % 5 == 0 for k in range(400)]))
        self.assertTrue(out["passes"], out["reason"])

    def test_expensive_stop_fails(self):
        weeks = [k // 4 for k in range(400)]
        real = rows_for([k % 2 == 0 for k in range(400)], weeks, cost=0.2)
        out = sq.accept(sq.summarize(real), real, real.assign(pair_id=real["row_id"], reach_1r=False))
        self.assertFalse(out["checks"]["kosten mediaan hooguit 0,10R"])


class PlaceboTest(unittest.TestCase):
    def test_pairs_and_measures(self):
        from app.replay import rangesweep as rs
        from app.replay.lab import add_indicators
        from tests.replay.rangesweep_fixtures import frames
        b15, b1h, _ = frames()
        b1 = add_indicators(b1h).reset_index(drop=True)
        b_tf, ranges = rs.range_series(b1h, "1h")
        active = rs.active_for(b1, b_tf, ranges, "1h")
        real = pd.DataFrame([{"row_id": "X:0", "direction": "short", "stop_atr": 1.0, "at": b1["timestamp"].iloc[150]}])
        p = sq.placebo_rows(real, b15.reset_index(drop=True), b1, active, sq.atr_on_15m(b15, b1), 0.12, seed=3)
        self.assertEqual(list(p["pair_id"]), ["X:0"])
        self.assertIn("reach_1r", p.columns)
```

- [ ] **Step 2: Run en zie falen**

Run: `python3 -m unittest tests.replay.test_stopquality -v`
Expected: FAIL (`summarize`, `accept`, `placebo_rows` bestaan niet).

- [ ] **Step 3: Implementeer**

```python
from app import smc_eval
from app.replay import rangesweep as rs, stats

MIN_FILLS = 300
MIN_WEEKS = 80
MAX_MEDIAN_COST_R = 0.10
MAX_HALF_DIFF = 0.10
MAX_BLOCK_DIFF = 0.15
N_BLOCKS = 6
MIN_PLACEBO_EDGE = 0.05
MAX_TIGHT_RATE = 0.25


def _share(f: pd.DataFrame, col: str, weeks: list) -> dict:
    vals = f[col].astype(float).tolist()
    lo, hi = stats.cluster_bootstrap_mean(vals, weeks)
    return {"p": float(np.mean(vals)), "ci": (lo, hi)}


def summarize(rows: pd.DataFrame) -> dict:
    setups = len(rows)
    if not setups:
        return {"setups": 0, "n": 0, "fill_rate": 0.0, "cancels": {}}
    filled_mask = rows["filled"].astype(bool)
    f = rows[filled_mask].sort_values("at")
    cancels = {k: int(v) for k, v in rows.loc[~filled_mask, "cancel"].value_counts().items()}
    out = {"setups": setups, "n": len(f), "fill_rate": len(f) / setups, "cancels": cancels}
    if f.empty:
        return out
    weeks = [stats.week_key(t) for t in f["at"]]
    halves = np.array_split(f, 2)
    blocks = np.array_split(f, N_BLOCKS) if len(f) >= N_BLOCKS else [f]
    stopped = f[f["stop_hit"].astype(bool)]
    q = (0.25, 0.5, 0.75, 0.9)
    ref = {}
    for name in REF_NAMES:
        ok = f[f[f"ref_{name}"].notna()]
        net = (ok[f"ref_{name}"] - ok["cost_r"]).tolist()
        ref[name] = {"n": len(net), "avg_net": float(np.mean(net)) if net else None,
                     "ci": stats.cluster_bootstrap_mean(net, [stats.week_key(t) for t in ok["at"]]) if net else (0.0, 0.0)}
    by_grade = {g: {"n": len(p), "reach1": float(p["reach_1r"].mean()), "stop_hit": float(p["stop_hit"].mean())}
                for g, p in f.groupby("grade")} if "grade" in f else {}
    out.update({"weeks": len(set(weeks)), "median_stop_pct": float(f["stop_pct"].median()), "median_stop_atr": float(f["stop_atr"].median()),
                "median_cost_r": float(f["cost_r"].median()), "share_cost_over_01": float((f["cost_r"] > 0.1).mean()),
                "stop_hit": _share(f, "stop_hit", weeks), "reach": {k: _share(f, f"reach_{k}r", weeks) for k in R_LEVELS},
                "median_hours_to_stop": float(stopped["hours_to_stop"].median()) if len(stopped) else None,
                "mae_q": [float(f["mae_r"].quantile(x)) for x in q], "mfe_q": [float(f["mfe_r"].quantile(x)) for x in q],
                "tight_rate": float(stopped["tight"].mean()) if len(stopped) else 0.0,
                "halves": tuple(float(h["reach_1r"].mean()) for h in halves), "blocks": [float(b["reach_1r"].mean()) for b in blocks],
                "ref": ref, "by_grade": by_grade})
    return out


def doelkans_table(summary: dict) -> list[dict]:
    """De tabel die de gebruiker leest: hoe vaak +1R tot +6R vóór de stop kwamen, met de marge per week. Historisch, geen belofte."""
    if not summary.get("n"):
        return []
    return [{"r": k, "p_text": f"{summary['reach'][k]['p'] * 100:.0f}%",
             "ci_text": f"{summary['reach'][k]['ci'][0] * 100:.0f} tot {summary['reach'][k]['ci'][1] * 100:.0f}%", "n": summary["n"]} for k in R_LEVELS]


def placebo_rows(real: pd.DataFrame, b15: pd.DataFrame, bt: pd.DataFrame, active: list, atr15: np.ndarray, cost_pct: float, seed: int = 0) -> pd.DataFrame:
    """Per echte gevulde trade één willekeurige instap: een willekeurig slot van de triggerframe binnen een actieve range van dezelfde coin en
    timeframe, zelfde kant, instap op dat slot, stop op dezelfde afstand in 1u-ATR (atr15) als de echte trade, daarna floor_stop, zelfde meting.
    pair_id koppelt hem aan de echte trade voor het verschil per paar."""
    rng = np.random.default_rng(seed)
    cl, ts = bt["close"].to_numpy(float), bt["timestamp"]
    delta = ts.diff().dropna().min()
    cand = [j for j, r in enumerate(active) if r is not None and r.low < cl[j] < r.high]
    ts15 = b15["timestamp"].to_numpy()
    out = []
    for row in real.itertuples():
        if not cand:
            break
        j = cand[int(rng.integers(0, len(cand)))]
        r, short = active[j], row.direction == "short"
        first = int(np.searchsorted(ts15, (ts.iloc[j] + delta).to_datetime64()))
        if first >= len(ts15) or not np.isfinite(atr15[first]):
            continue
        entry = float(cl[j])
        stop = smc_eval.floor_stop(row.direction, entry, entry + (1 if short else -1) * float(row.stop_atr) * atr15[first], min_pct=rs.MIN_STOP_PCT)
        m = measure(row.direction, [(1.0, entry, first)], stop, b15, atr15, r.high, r.low, cost_pct)
        out.append({"pair_id": row.row_id, "at": ts.iloc[j], **m})
    return pd.DataFrame(out)


def accept(summary: dict, real: pd.DataFrame, placebo: pd.DataFrame) -> dict:
    """Toets op stopkwaliteit voor één variant en één stop (pre-registratie, 'Wat we meten en wanneer het telt')."""
    n = summary.get("n", 0)
    pairs = real.merge(placebo[["pair_id", "reach_1r"]].rename(columns={"reach_1r": "plac"}), left_on="row_id", right_on="pair_id") if n and len(placebo) else pd.DataFrame()
    diff = (pairs["reach_1r"].astype(float) - pairs["plac"].astype(float)).tolist() if len(pairs) else []
    dlo, dhi = stats.cluster_bootstrap_mean(diff, [stats.week_key(t) for t in pairs["at"]]) if diff else (0.0, 0.0)
    dmean = float(np.mean(diff)) if diff else 0.0
    p = summary["reach"][1]["p"] if n else 0.0
    checks = {
        f"genoeg vullingen ({MIN_FILLS})": n >= MIN_FILLS,
        f"genoeg weken ({MIN_WEEKS})": summary.get("weeks", 0) >= MIN_WEEKS,
        "kosten mediaan hooguit 0,10R": n > 0 and summary["median_cost_r"] <= MAX_MEDIAN_COST_R,
        "helften stabiel (hooguit 10 procentpunt)": n > 0 and abs(summary["halves"][0] - summary["halves"][-1]) <= MAX_HALF_DIFF,
        "blokken stabiel (hooguit 15 procentpunt)": n > 0 and max(abs(b - p) for b in summary["blocks"]) <= MAX_BLOCK_DIFF,
        "beter dan willekeurig (+1R vóór de stop minstens 5 procentpunt)": dmean >= MIN_PLACEBO_EDGE and dlo > 0,
        "stop niet te krap (hooguit 25%)": n > 0 and summary["tight_rate"] <= MAX_TIGHT_RATE,
    }
    passes = all(checks.values())
    return {"checks": checks, "passes": passes, "reason": "" if passes else "faalt: " + ", ".join(k for k, ok in checks.items() if not ok),
            "placebo_diff": dmean, "placebo_ci": (dlo, dhi)}
```

- [ ] **Step 4: Run en zie slagen**

Run: `python3 -m unittest tests.replay.test_stopquality -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/replay/stopquality.py tests/replay/test_stopquality.py
git commit -m "feat: doelkans, placebo en toets op stopkwaliteit"
```

---

### Task 11: Labfamilie range sweep

**Files:**
- Create: `app/replay/rangesweep_lab.py`
- Test: `tests/test_rangesweep_lab.py` (nieuw)

**Interfaces:**
- Consumes: taken 4, 5, 6, 9, 10; `app/replay/positioning.py` voor OI.
- Produces:
  - `RSVariant(name, family, tf, entry, confirm, htf, oi_flush)` met eigenschap `stops` (= `rangesweep.TESTED_STOPS[family]`) en `VARIANTS` (15, zie tabel).
  - `PRIOR_VARIANTS = 34`, `TESTED_TOTAL` (64), `EDGE_T_MIN = 3.4`, `LAB_COST_PCT = 0.12`.
  - `oi_change_pct(metrics, t0, t1) -> Optional[float]`.
  - `run_coin(v, coin, frames, cost_pct, cache, metrics=None) -> pd.DataFrame` (één rij per setup en stopnaam uit `raw_stops`; kolommen `row_id, coin, variant, stop_name, at, placed_at, direction, filled, cancel, grade, score` plus de velden van `measure`).
  - `placebo_coin(v, frames, cache, real, cost_pct, seed) -> pd.DataFrame`.
  - `judge(rows, placebo: dict[str, pd.DataFrame], v) -> dict` met per getoetste stop `{"summary", "quality", "edge", "doelkans"}` en `"zone_0": {"summary"}`.
  - `select_live(results: list[tuple[RSVariant, dict]]) -> Optional[tuple[RSVariant, str]]`.

- [ ] **Step 1: Schrijf de falende tests**

```python
import re
import sys
import unittest
from pathlib import Path

import pandas as pd

from app.replay import rangesweep as rs, rangesweep_lab as rl, stopquality as sq
from tests.replay.rangesweep_fixtures import frames

ROOT = Path(__file__).resolve().parent.parent
PREREG = ROOT / "docs" / "onderzoek" / "range-sweep" / "preregistratie.md"


class PreregTest(unittest.TestCase):
    def test_constants_match_the_preregistration(self):
        block = re.search(r"```prereg-constants\n(.*?)```", PREREG.read_text(encoding="utf-8"), re.S).group(1)
        mods = {"rangesweep": rs, "stopquality": sq, "rangesweep_lab": rl}
        for line in block.strip().splitlines():
            name, value = (x.strip() for x in line.split("="))
            mod, attr = name.split(".")
            self.assertAlmostEqual(float(getattr(mods[mod], attr)), float(value), msg=name)

    def test_every_variant_is_preregistered(self):
        text = PREREG.read_text(encoding="utf-8")
        for v in rl.VARIANTS:
            self.assertIn(f"`{v.name}`", text)
        self.assertEqual(len(rl.VARIANTS), 15)
        self.assertEqual(rl.TESTED_TOTAL, 64)

    def test_misser_combos_match_the_variants(self):
        sys.path.insert(0, str(ROOT / "scripts"))
        import misser_check
        lab = {(v.name, v.family, v.tf, v.confirm, v.htf) for v in rl.VARIANTS if v.entry != "split" and not v.oi_flush}
        self.assertEqual(set(misser_check.RS_COMBOS), lab)


class RunCoinTest(unittest.TestCase):
    def setUp(self):
        b15, b1h, b4h = frames()
        self.f = rs.build_frames(b15, b1h, b4h)

    def test_sweep_setup_is_measured_for_every_stop_and_runs_away(self):
        v = rl.RSVariant("T", "sweep", "1h", "ob", "slot", False, False)
        rows = rl.run_coin(v, "TST", self.f, 0.12, {})
        self.assertEqual(sorted(rows["stop_name"]), sorted(["zone_0", "zone_025", "zone_05", "wick_025"]))
        self.assertTrue((~rows["filled"]).all())
        self.assertEqual(set(rows["cancel"]), {"weggelopen"})
        self.assertEqual(set(rows["grade"]), {"A"})

    def test_zone_retest_fills_and_reaches_one_r(self):
        v = rl.RSVariant("T", "zone", "1h", "zone", "slot", False, False)
        rows = rl.run_coin(v, "TST", self.f, 0.12, {})
        prim = rows[rows["stop_name"] == "zone_025"]
        first_two = prim.sort_values("placed_at").head(2)
        self.assertTrue(first_two["filled"].all())
        self.assertTrue(first_two["reach_1r"].all())

    def test_oi_flush_without_data_drops_the_setup(self):
        v = rl.RSVariant("T", "sweep", "1h", "ob", "slot", False, True)
        self.assertTrue(rl.run_coin(v, "TST", self.f, 0.12, {}, metrics=None).empty)

    def test_oi_change(self):
        m = pd.DataFrame({"timestamp": pd.date_range("2025-01-06", periods=4, freq="5min", tz="UTC"), "oi": [100.0, 100.0, 98.0, 97.0]})
        t0, t1 = pd.Timestamp("2025-01-06 00:06", tz="UTC"), pd.Timestamp("2025-01-06 00:16", tz="UTC")
        self.assertAlmostEqual(rl.oi_change_pct(m, t0, t1), -2.0)
        self.assertIsNone(rl.oi_change_pct(m, pd.Timestamp("2024-01-01", tz="UTC"), t1))


class SelectTest(unittest.TestCase):
    def test_most_fills_then_cheapest_then_wider_stop(self):
        a = next(v for v in rl.VARIANTS if v.name == "RZ_2H")
        b = next(v for v in rl.VARIANTS if v.name == "RS_1H")
        ok = lambda n, cost: {"quality": {"passes": True}, "summary": {"n": n, "median_cost_r": cost}}
        bad = {"quality": {"passes": False}, "summary": {"n": 999, "median_cost_r": 0.01}}
        res = [(a, {"zone_025": ok(400, 0.05), "zone_05": ok(400, 0.05)}), (b, {"zone_025": bad, "wick_025": ok(350, 0.04)})]
        self.assertEqual(rl.select_live(res), (a, "zone_05"))
        self.assertIsNone(rl.select_live([(a, {"zone_025": bad, "zone_05": bad})]))
```

- [ ] **Step 2: Run en zie falen**

Run: `python3 -m unittest tests.test_rangesweep_lab -v`
Expected: FAIL met `ModuleNotFoundError: ... rangesweep_lab`.

- [ ] **Step 3: Implementeer**

```python
"""Labfamilie range sweep (docs/onderzoek/range-sweep/preregistratie.md). Vijftien varianten in twee families, elk met twee getoetste stops,
vooraf vastgelegd. De kop is de stopkwaliteit (stopquality.accept); de strenge toets op een voordeel (trendlab.evaluate plus t per week) staat ernaast."""
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from app import chance_checks
from app.replay import rangesweep as rs, stats, stopquality as sq, trendlab as tl
from app.replay.lab import add_indicators


@dataclass(frozen=True)
class RSVariant:
    name: str
    family: str
    tf: str
    entry: str
    confirm: str
    htf: bool
    oi_flush: bool

    @property
    def stops(self) -> tuple[str, ...]:
        return rs.TESTED_STOPS[self.family]


VARIANTS = (
    RSVariant("RZ_30M", "zone", "30m", "zone", "slot", True, False),
    RSVariant("RZ_1H", "zone", "1h", "zone", "slot", True, False),
    RSVariant("RZ_2H", "zone", "2h", "zone", "slot", True, False),
    RSVariant("RZ_4H", "zone", "4h", "zone", "slot", True, False),
    RSVariant("RZ_1H_CHOCH", "zone", "1h", "zone", "choch15", True, False),
    RSVariant("RZ_2H_CHOCH", "zone", "2h", "zone", "choch15", True, False),
    RSVariant("RZ_2H_ZONDERHTF", "zone", "2h", "zone", "slot", False, False),
    RSVariant("RZ_2H_SPLIT", "zone", "2h", "split", "slot", True, False),
    RSVariant("RS_30M", "sweep", "30m", "ob", "slot", True, False),
    RSVariant("RS_1H", "sweep", "1h", "ob", "slot", True, False),
    RSVariant("RS_2H", "sweep", "2h", "ob", "slot", True, False),
    RSVariant("RS_4H", "sweep", "4h", "ob", "slot", True, False),
    RSVariant("RS_1H_CHOCH", "sweep", "1h", "ob", "choch15", True, False),
    RSVariant("RS_1H_ZONDERHTF", "sweep", "1h", "ob", "slot", False, False),
    RSVariant("RS_1H_OIFLUSH", "sweep", "1h", "ob", "slot", True, True),
)
PRIOR_VARIANTS = 34
TESTED_TOTAL = PRIOR_VARIANTS + sum(len(v.stops) for v in VARIANTS)
EDGE_T_MIN = 3.4
LAB_COST_PCT = 0.12
OI_FLUSH_PCT = -1.0
OI_LAG = pd.Timedelta(minutes=5)


def oi_change_pct(metrics: Optional[pd.DataFrame], t0: pd.Timestamp, t1: pd.Timestamp) -> Optional[float]:
    """Procentuele verandering van open interest tussen het laatste punt vóór t0 en het laatste vóór t1, elk met OI_LAG vertraging (een 5m-punt staat
    er pas na zijn eigen periode). None als er vóór t0 geen punt is."""
    if metrics is None or metrics.empty:
        return None
    ts = metrics["timestamp"]
    a, b = metrics[ts <= t0 - OI_LAG], metrics[ts <= t1 - OI_LAG]
    if a.empty or b.empty or not a["oi"].iloc[-1]:
        return None
    return (b["oi"].iloc[-1] / a["oi"].iloc[-1] - 1) * 100


def _ranges(v: RSVariant, frames: dict, cache: dict):
    if v.tf not in cache:
        cache[v.tf] = rs.range_series(frames[v.tf], v.tf)
    return cache[v.tf]


def run_coin(v: RSVariant, coin: str, frames: dict, cost_pct: float, cache: dict, metrics: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    b15 = frames["15m"]
    atr15 = sq.atr_on_15m(b15, add_indicators(frames["1h"]).reset_index(drop=True))
    setups, _ = rs.find_setups(frames, v.tf, v.family, v.entry, v.confirm, v.htf, ranges=_ranges(v, frames, cache))
    rows = []
    for k, s in enumerate(setups):
        if v.oi_flush:
            change = oi_change_pct(metrics, s["sweep_at"], s["return_at"])
            if change is None or change > OI_FLUSH_PCT:
                continue
        _, score = chance_checks.weighted_finish(chance_checks.range_sweep_checks(s["features"], v.tf))
        mid = (s["range_high"] + s["range_low"]) / 2
        short = s["direction"] == "short"
        for name in rs.raw_stops(s):
            stop = rs.final_stop(s, name)
            base = {"row_id": f"{coin}:{v.name}:{k}", "coin": coin, "variant": v.name, "stop_name": name, "placed_at": s["placed_at"],
                    "direction": s["direction"], "grade": chance_checks.grade_of(score), "score": score}
            if not all((stop > p) if short else (stop < p) for _, p in s["legs"]):
                rows.append({**base, "at": s["placed_at"], "filled": False, "cancel": "stop binnen de instapzone"})
                continue
            fills = sq.simulate_fills(s["direction"], s["legs"], stop, mid, b15, s["place_idx15"])
            if not fills["filled"]:
                rows.append({**base, "at": s["placed_at"], "filled": False, "cancel": fills["cancel"]})
                continue
            m = sq.measure(s["direction"], fills["filled"], stop, b15, atr15, s["range_high"], s["range_low"], cost_pct)
            rows.append({**base, "at": b15["timestamp"].iloc[fills["first"]], "filled": True, "cancel": "", **m})
    return pd.DataFrame(rows)


def placebo_coin(v: RSVariant, frames: dict, cache: dict, real: pd.DataFrame, cost_pct: float, seed: int = 0) -> pd.DataFrame:
    b_tf, ranges = _ranges(v, frames, cache)
    bt = add_indicators(frames[rs.TRIGGER_TF[v.tf]]).reset_index(drop=True)
    atr15 = sq.atr_on_15m(frames["15m"], add_indicators(frames["1h"]).reset_index(drop=True))
    return sq.placebo_rows(real, frames["15m"], bt, rs.active_for(bt, b_tf, ranges, v.tf), atr15, cost_pct, seed)


def edge_verdict(prim: pd.DataFrame, plac: pd.DataFrame) -> dict:
    trades = pd.DataFrame({"at": prim["at"], "gross": prim["ref_trail"], "net": prim["ref_trail"] - prim["cost_r"], "risk_pct": prim["stop_pct"]})
    placebo = pd.DataFrame({"gross": plac["ref_trail"], "net": plac["ref_trail"] - plac["cost_r"]}) if len(plac) else pd.DataFrame(columns=["gross", "net"])
    ev = tl.evaluate(trades, placebo)
    t = stats.cluster_t(trades["net"].tolist(), [stats.week_key(x) for x in trades["at"]]) if len(trades) else 0.0
    checks = {**ev.get("checks", {}), f"t per week minstens {EDGE_T_MIN}": t >= EDGE_T_MIN}
    passes = bool(ev.get("passes")) and t >= EDGE_T_MIN
    return {**ev, "t_week": t, "checks": checks, "passes": passes, "reason": "" if passes else "faalt: " + ", ".join(k for k, ok in checks.items() if not ok)}


def judge(rows: pd.DataFrame, placebo: dict, v: RSVariant) -> dict:
    """placebo: per getoetste stop de placeborijen van de gevulde trades met die stop."""
    part = lambda name: rows[rows["stop_name"] == name] if len(rows) else rows
    out = {rs.DESCRIPTIVE_STOP: {"summary": sq.summarize(part(rs.DESCRIPTIVE_STOP))}}
    for name in v.stops:
        p = part(name)
        summary = sq.summarize(p)
        filled = p[p["filled"].astype(bool)] if len(p) else p
        plac = placebo.get(name, pd.DataFrame())
        out[name] = {"summary": summary,
                     "quality": sq.accept(summary, filled, plac) if summary["n"] else {"passes": False, "reason": "geen vullingen", "checks": {}, "placebo_diff": 0.0, "placebo_ci": (0.0, 0.0)},
                     "edge": edge_verdict(filled, plac) if summary["n"] else {"passes": False, "n": 0, "t_week": 0.0, "reason": "geen vullingen"},
                     "doelkans": sq.doelkans_table(summary)}
    return out


def select_live(results: list[tuple[RSVariant, dict]]) -> Optional[tuple[RSVariant, str]]:
    """Vooraf vastgelegd: geslaagd op stopkwaliteit, dan de meeste vullingen, dan de laagste mediane kosten, dan de bredere stop."""
    cands = [(v, name, r[name]) for v, r in results for name in v.stops if r.get(name, {}).get("quality", {}).get("passes")]
    if not cands:
        return None
    v, name, _ = min(cands, key=lambda c: (-c[2]["summary"]["n"], c[2]["summary"]["median_cost_r"], -rs.STOP_BUFFER[c[1]][1]))
    return v, name
```

- [ ] **Step 4: Run en zie slagen**

Run: `python3 -m unittest tests.test_rangesweep_lab -v`
Expected: PASS. Faalt `test_constants_match_the_preregistration`, dan wijkt code of document af: pas de code aan het document aan, nooit andersom na poort 1.

- [ ] **Step 5: Commit**

```bash
git add app/replay/rangesweep_lab.py tests/test_rangesweep_lab.py
git commit -m "feat: labfamilie range sweep met vooraf vastgelegde varianten"
```

---

### Task 12: `--familie rangesweep` (hervatbaar), rapport, opslaan en het VPS-protocol (poort 2 en 3)

**Files:**
- Modify: `scripts/strategy_lab.py`, `app/track_record.py` (`LAB_LABELS`, `TYPE_LABELS`)
- Test: `tests/test_strategy_lab_rangesweep.py` (nieuw)

**Interfaces:**
- Consumes: taak 11.
- Produces: `strategy_lab.write_between_markers(text, block) -> str`, `check_rangesweep_costs(kosten, opslaan)`, `render_rangesweep(results, meta) -> str`, `save_rangesweep(results, live_choice, now_iso) -> int`, `coin_part_paths(outdir, coin) -> tuple[Path, Path]`, en de opties `--rapport PAD` en `--hervat MAP`. Rijen in `rule_status`: per variant `v.name.lower()` (lab_passes = strenge toets op de stop met de meeste vullingen), `range_sweep_stop` (lab_passes = stopkwaliteit van de gekozen variant; `lab_json` met `variant, stop_name, quality, summary, doelkans`), `range_sweep` (lab_passes = strenge toets van de gekozen variant en stop).

- [ ] **Step 1: Schrijf de falende tests**

```python
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))
import strategy_lab  # noqa: E402

from app.replay import rangesweep_lab as rl, stopquality as sq  # noqa: E402


def fake_cell(passes=False, n=10):
    summ = {"setups": 20, "n": n, "fill_rate": 0.5, "cancels": {}, "weeks": 5, "median_stop_pct": 2.4, "median_stop_atr": 1.1, "median_cost_r": 0.05,
            "share_cost_over_01": 0.1, "stop_hit": {"p": 0.5, "ci": (0.4, 0.6)}, "reach": {k: {"p": 0.5 / k, "ci": (0.3 / k, 0.6 / k)} for k in sq.R_LEVELS},
            "median_hours_to_stop": 5.0, "mae_q": [0.2, 0.5, 0.9, 1.0], "mfe_q": [0.3, 0.8, 1.6, 2.4], "tight_rate": 0.2, "halves": (0.5, 0.5),
            "blocks": [0.5] * 6, "ref": {k: {"n": n, "avg_net": -0.05, "ci": (-0.2, 0.1)} for k in sq.REF_NAMES}, "by_grade": {}}
    return {"summary": summ, "quality": {"passes": passes, "reason": "" if passes else "faalt: genoeg vullingen (300)", "checks": {}, "placebo_diff": 0.02, "placebo_ci": (-0.03, 0.07)},
            "edge": {"passes": False, "n": n, "avg": -0.05, "t_week": 0.4, "reason": "faalt"}, "doelkans": [{"r": 1, "p_text": "50%", "ci_text": "30 tot 60%", "n": n}]}


def fake_result(v):
    return {"zone_0": {"summary": fake_cell()["summary"]}, **{s: fake_cell() for s in v.stops}}


class RangeSweepReportTest(unittest.TestCase):
    def test_markers(self):
        doc = "kop\n<!-- resultaten:begin -->\noud\n<!-- resultaten:end -->\nstaart"
        out = strategy_lab.write_between_markers(doc, "nieuw")
        self.assertIn("<!-- resultaten:begin -->\nnieuw\n<!-- resultaten:end -->", out)
        self.assertTrue(out.startswith("kop") and out.endswith("staart"))
        with self.assertRaises(ValueError):
            strategy_lab.write_between_markers("geen markers", "x")

    def test_report_names_the_register_and_every_variant(self):
        md = strategy_lab.render_rangesweep([(v, fake_result(v)) for v in rl.VARIANTS], {"kosten": 0.12, "jaren": 3.0, "coins": 20, "first": "2023-10-16", "last": "2026-10-15"})
        self.assertIn("30 toetsen in deze familie, 64 in het register", md)
        for v in rl.VARIANTS:
            self.assertIn(v.name, md)
        self.assertIn("+1R vóór de stop", md)
        self.assertIn("+6R", md)
        self.assertIn("geen enkele toets slaagt", md)

    def test_save_refuses_low_costs(self):
        with self.assertRaises(SystemExit):
            strategy_lab.check_rangesweep_costs(0.06, opslaan=True)
        strategy_lab.check_rangesweep_costs(0.06, opslaan=False)

    def test_save_writes_variant_rows_and_the_two_live_rows(self):
        with mock.patch.object(strategy_lab.repo, "set_rule_lab") as s, mock.patch.object(strategy_lab.db, "init_db"):
            n = strategy_lab.save_rangesweep([(v, fake_result(v)) for v in rl.VARIANTS], None, "2026-10-16T00:00:00+00:00")
        keys = [c.args[0] for c in s.call_args_list]
        self.assertEqual(n, len(rl.VARIANTS) + 2)
        self.assertIn("range_sweep_stop", keys)
        self.assertFalse(next(c for c in s.call_args_list if c.args[0] == "range_sweep_stop").args[1])

    def test_resume_paths_per_coin(self):
        with tempfile.TemporaryDirectory() as d:
            rows, plac = strategy_lab.coin_part_paths(Path(d), "ARB")
            self.assertEqual((rows.name, plac.name), ("ARB_rows.pkl", "ARB_placebo.pkl"))
```

- [ ] **Step 2: Run en zie falen**

Run: `python3 -m unittest tests.test_strategy_lab_rangesweep -v`
Expected: FAIL met `AttributeError: ... write_between_markers`.

- [ ] **Step 3: Implementeer**

In `scripts/strategy_lab.py`:

```python
import pickle

from app.replay import positioning, rangesweep as rs, rangesweep_lab as rl, stopquality as sq  # noqa: E402

BEGIN, END = "<!-- resultaten:begin -->", "<!-- resultaten:end -->"


def write_between_markers(text: str, block: str) -> str:
    if BEGIN not in text or END not in text:
        raise ValueError(f"markers {BEGIN} en {END} ontbreken")
    head, rest = text.split(BEGIN, 1)
    _, tail = rest.split(END, 1)
    return f"{head}{BEGIN}\n{block}\n{END}{tail}"


def check_rangesweep_costs(kosten: float, opslaan: bool) -> None:
    if opslaan and kosten < rl.LAB_COST_PCT:
        sys.exit(f"--opslaan voor rangesweep vraagt --kosten {rl.LAB_COST_PCT} of hoger (gekozen {kosten})")


def coin_part_paths(outdir: Path, coin: str) -> tuple[Path, Path]:
    """Tussenresultaat per coin: een onderbroken run op de VPS gaat verder bij de volgende coin in plaats van opnieuw te beginnen."""
    return outdir / f"{coin}_rows.pkl", outdir / f"{coin}_placebo.pkl"


def _pct(x) -> str:
    return "-" if x is None else f"{x * 100:.0f}%"


def render_rangesweep(results, meta: dict) -> str:
    n_tests = sum(len(v.stops) for v, _ in results)
    lines = [f"Run: {meta['first']} tot {meta['last']}, {meta['coins']} coins, kosten {meta['kosten']}% per rondreis, {meta['jaren']} jaar.",
             f"{n_tests} toetsen in deze familie, {rl.TESTED_TOTAL} in het register sinds het begin; horde voor een voordeel t ≥ {rl.EDGE_T_MIN}.", "",
             "### Stopkwaliteit (de kop)", "",
             "| Variant | Stop | Setups | Gevuld | Stop % | Kosten R | Stop geraakt | +1R vóór de stop | +2R | +3R | +6R | Te krap | Tegen willekeurig | Oordeel |",
             "|---|---|---|---|---|---|---|---|---|---|---|---|---|---|"]
    passed = 0
    for v, r in results:
        for name in v.stops:
            s, q = r[name]["summary"], r[name]["quality"]
            if not s.get("n"):
                lines.append(f"| {v.name} | {name} | {s.get('setups', 0)} | 0 | - | - | - | - | - | - | - | - | - | geen vullingen |")
                continue
            passed += bool(q["passes"])
            ci = s["reach"][1]["ci"]
            lines.append(f"| {v.name} | {name} | {s['setups']} | {s['n']} | {s['median_stop_pct']:.2f}% | {s['median_cost_r']:.3f} | {_pct(s['stop_hit']['p'])} | "
                         f"{_pct(s['reach'][1]['p'])} ({ci[0] * 100:.0f} tot {ci[1] * 100:.0f}%) | {_pct(s['reach'][2]['p'])} | {_pct(s['reach'][3]['p'])} | "
                         f"{_pct(s['reach'][6]['p'])} | {_pct(s['tight_rate'])} | {q['placebo_diff'] * 100:+.1f} pp | {'SLAAGT' if q['passes'] else q['reason']} |")
    lines += ["", f"{passed} van {n_tests} toetsen slagen op stopkwaliteit." + (" Stopcriterium S2: geen enkele toets slaagt." if not passed else ""), "",
              "### Netto R bij de referentie-uitgangen (ernaast, nooit de kop)", "",
              "| Variant | Stop | Midden | Overkant | Meelopend (3 ATR 1u) | t per week | Strenge toets |", "|---|---|---|---|---|---|---|"]
    for v, r in results:
        for name in v.stops:
            s, e = r[name]["summary"], r[name]["edge"]
            if not s.get("n"):
                continue
            ref = lambda k: "-" if s["ref"][k]["avg_net"] is None else f"{s['ref'][k]['avg_net']:+.3f}"
            lines.append(f"| {v.name} | {name} | {ref('mid')} | {ref('opp')} | {ref('trail')} | {e.get('t_week', 0):.2f} | {'SLAAGT' if e.get('passes') else e.get('reason', '')} |")
    lines += ["", "### Score per graad (beschrijvend, geen poort)", "", "| Variant | Stop | Graad | n | +1R vóór de stop | Stop geraakt |", "|---|---|---|---|---|---|"]
    for v, r in results:
        for name in v.stops:
            for g, x in sorted(r[name]["summary"].get("by_grade", {}).items()):
                lines.append(f"| {v.name} | {name} | {g} | {x['n']} | {_pct(x['reach1'])} | {_pct(x['stop_hit'])} |")
    lines += ["", "Ter vergelijking, stop op de buitenkant van de zone zonder buffer (geen toets):", ""]
    for v, r in results:
        w = r[rs.DESCRIPTIVE_STOP]["summary"]
        if w.get("n"):
            lines.append(f"- {v.name}: {w['n']} gevuld, stop geraakt {_pct(w['stop_hit']['p'])}, te krap {_pct(w['tight_rate'])}, kosten {w['median_cost_r']:.3f}R")
    return "\n".join(lines)


def save_rangesweep(results, live_choice, now_iso: str) -> int:
    db.init_db()
    saved = 0
    for v, r in results:
        best = max(v.stops, key=lambda n: r[n]["summary"].get("n", 0))
        e = r[best]["edge"]
        repo.set_rule_lab(v.name.lower(), bool(e.get("passes")), {"stop_name": best, "n": e.get("n"), "avg": e.get("avg"), "t_week": e.get("t_week"),
                                                                  "quality_passes": bool(r[best]["quality"]["passes"])}, now_iso)
        saved += 1
    if live_choice is None:
        repo.set_rule_lab("range_sweep_stop", False, {"variant": None, "reason": "geen toets slaagde op stopkwaliteit"}, now_iso)
        repo.set_rule_lab("range_sweep", False, {"variant": None}, now_iso)
        return saved + 2
    v, name = live_choice
    cell = next(r for vv, r in results if vv == v)[name]
    repo.set_rule_lab("range_sweep_stop", True, {"variant": v.name, "stop_name": name, "quality": cell["quality"], "summary": cell["summary"],
                                                 "doelkans": cell["doelkans"]}, now_iso)
    repo.set_rule_lab("range_sweep", bool(cell["edge"].get("passes")), {"variant": v.name, "stop_name": name, **{k: cell["edge"].get(k) for k in SUMMARY_KEYS}}, now_iso)
    return saved + 2


def _run_one_coin(coin: str, a) -> tuple[dict, dict, list]:
    tfs = load_coin(coin, ("15m", "1h", "4h"), a.jaren)
    if any(tf not in tfs or tfs[tf].empty for tf in ("15m", "1h", "4h")):
        return {}, {}, []
    frames = rs.build_frames(tfs["15m"], tfs["1h"], tfs["4h"])
    span = [frames["15m"]["timestamp"].iloc[0], frames["15m"]["timestamp"].iloc[-1]]
    metrics = None
    try:
        metrics, _ = positioning.ensure_positioning(coin, span[0], span[1])
        print(f"{coin}: OI vanaf {metrics['timestamp'].iloc[0]:%Y-%m-%d}" if len(metrics) else f"{coin}: geen OI", flush=True)
    except Exception as exc:
        print(f"{coin}: geen OI ({exc})", flush=True)
    cache, rows, plac = {}, {}, {}
    for v in rl.VARIANTS:
        r = rl.run_coin(v, coin, frames, a.kosten, cache, metrics if v.oi_flush else None)
        rows[v.name] = r
        plac[v.name] = {}
        for n in v.stops:
            filled = r[(r["stop_name"] == n) & r["filled"]] if len(r) else r
            plac[v.name][n] = rl.placebo_coin(v, frames, cache, filled, a.kosten, seed=0) if len(filled) else pd.DataFrame()
        print(f"{coin} {v.name}: {len(r)} rijen", flush=True)
    return rows, plac, span


def run_rangesweep(a) -> None:
    check_rangesweep_costs(a.kosten, a.opslaan)
    coins = a.coins.split(",")
    if a.alleen_volledig:
        firsts = {c: candle_cache.ensure_candles(c, a.jaren, timeframe="15m").head(1) for c in coins}
        coins = [c for c in coins if c in set(tl.full_history(firsts))]
        print(f"{len(coins)} coins met volle historie", flush=True)
    outdir = Path(a.hervat) if a.hervat else None
    if outdir:
        outdir.mkdir(parents=True, exist_ok=True)
    all_rows = {v.name: [] for v in rl.VARIANTS}
    all_plac = {v.name: {n: [] for n in v.stops} for v in rl.VARIANTS}
    span = []
    for coin in coins:
        paths = coin_part_paths(outdir, coin) if outdir else None
        if paths and paths[0].exists() and paths[1].exists():
            rows, plac, cspan = pickle.loads(paths[0].read_bytes()), *pickle.loads(paths[1].read_bytes())
            print(f"{coin}: uit {paths[0]}", flush=True)
        else:
            rows, plac, cspan = _run_one_coin(coin, a)
            if paths:
                paths[0].write_bytes(pickle.dumps(rows))
                paths[1].write_bytes(pickle.dumps((plac, cspan)))
        span += cspan
        for v in rl.VARIANTS:
            if len(rows.get(v.name, [])):
                all_rows[v.name].append(rows[v.name])
            for n in v.stops:
                p = plac.get(v.name, {}).get(n)
                if p is not None and len(p):
                    all_plac[v.name][n].append(p)
    results = []
    for v in rl.VARIANTS:
        r = pd.concat(all_rows[v.name], ignore_index=True) if all_rows[v.name] else pd.DataFrame(columns=["stop_name", "filled", "at", "cancel"])
        results.append((v, rl.judge(r, {n: pd.concat(p, ignore_index=True) if p else pd.DataFrame() for n, p in all_plac[v.name].items()}, v)))
    meta = {"kosten": a.kosten, "jaren": a.jaren, "coins": len(coins), "first": f"{min(span):%Y-%m-%d}" if span else "-", "last": f"{max(span):%Y-%m-%d}" if span else "-"}
    md = render_rangesweep(results, meta)
    print(md)
    choice = rl.select_live(results)
    print(f"\nGekozen voor de proef: {choice[0].name} met stop {choice[1]}" if choice else "\nGeen variant gekozen voor de proef (S2).")
    if a.rapport:
        p = Path(a.rapport)
        p.write_text(write_between_markers(p.read_text(encoding="utf-8"), md), encoding="utf-8")
    if a.opslaan:
        print(f"{save_rangesweep(results, choice, datetime.now(timezone.utc).isoformat())} regels opgeslagen.")
```

De regel `rows, plac, cspan = pickle.loads(...), *pickle.loads(...)` werkt zo: het tweede bestand bevat het tuple `(plac, cspan)`. Schrijf het als twee regels als dat leesbaarder is:

```python
            rows = pickle.loads(paths[0].read_bytes())
            plac, cspan = pickle.loads(paths[1].read_bytes())
```

Het tussenbestand is een eigen bestand in een map die de gebruiker opgeeft; pickle laden is hier veilig omdat het script het zelf schreef.

In `main()`: `--familie` krijgt de keuze `"rangesweep"`; nieuwe opties `ap.add_argument("--rapport", help="rangesweep: schrijf de uitkomst tussen de markers van dit markdownbestand")` en `ap.add_argument("--hervat", help="rangesweep: map voor tussenresultaten per coin; een tweede run slaat klare coins over")`; direct na `parse_args`: `if a.familie == "rangesweep": return run_rangesweep(a)`. Zet in de docstring bovenaan dat `alle` alleen de trendlab-families is; rangesweep heeft een eigen register.

In `app/track_record.py`, `LAB_LABELS`:

```python
    "rz_30m": "Zone-retest 30m", "rz_1h": "Zone-retest 1u", "rz_2h": "Zone-retest 2u", "rz_4h": "Zone-retest 4u",
    "rz_1h_choch": "Zone-retest 1u, CHoCH 15m", "rz_2h_choch": "Zone-retest 2u, CHoCH 15m", "rz_2h_zonderhtf": "Zone-retest 2u zonder HTF",
    "rz_2h_split": "Zone-retest 2u, 40/60 verdeeld", "rs_30m": "Range sweep 30m", "rs_1h": "Range sweep 1u", "rs_2h": "Range sweep 2u",
    "rs_4h": "Range sweep 4u", "rs_1h_choch": "Range sweep 1u, CHoCH 15m", "rs_1h_zonderhtf": "Range sweep 1u zonder HTF",
    "rs_1h_oiflush": "Range sweep 1u met OI-daling", "range_sweep_stop": "Range sweep, stopkwaliteit",
```

en `TYPE_LABELS["range_sweep"] = "Range sweep (ongetest)"`.

- [ ] **Step 4: Run en zie slagen**

Run: `python3 -m unittest tests.test_strategy_lab_rangesweep tests.test_track_record -v`
Expected: PASS.

- [ ] **Step 5: VPS-protocol (poort 2 en 3, geen code)**

Alleen na poort 1 (pre-registratie bevroren). Op de VPS, in de map uit `README.md`, in `tmux` of `screen` zodat een verbroken SSH de run niet stopt:

```bash
git pull && .venv/bin/pip install -r requirements.txt
# 1. candles ophalen (eenmalig, ongeveer 20 coins maal 3 timeframes; de cache in data/candles/ blijft staan)
for c in BTC ETH SOL BNB XRP ADA DOGE AVAX LINK DOT LTC BCH NEAR ATOM UNI AAVE SUI INJ APT ARB; do
  .venv/bin/python3 -c "from app.replay import candles as cc; [cc.ensure_candles('$c', 3, timeframe=t) for t in ('15m','1h','4h')]" && echo "$c klaar"
done
# 2. de run, hervatbaar per coin
.venv/bin/python3 scripts/strategy_lab.py --familie rangesweep --jaren 3 --kosten 0.12 --alleen-volledig --hervat data/replay/rangesweep_012 --rapport docs/onderzoek/range-sweep/resultaten.md
# 3. gevoeligheid, niet opslaan
.venv/bin/python3 scripts/strategy_lab.py --familie rangesweep --jaren 3 --kosten 0.16 --alleen-volledig --hervat data/replay/rangesweep_016
# 4. opslaan (leest de tussenresultaten van stap 2, rekent niets opnieuw)
.venv/bin/python3 scripts/strategy_lab.py --familie rangesweep --jaren 3 --kosten 0.12 --alleen-volledig --hervat data/replay/rangesweep_012 --opslaan
# 5. resultaten terug naar de repo
git add docs/onderzoek/range-sweep/resultaten.md && git commit -m "onderzoek: uitkomst range sweep-lab" && git push
```

Schrijf het menselijke oordeel onder "Oordeel" in `resultaten.md`. Geldt S2 of S3, dan stopt het plan hier voor de setupmotor (taak 15 gaat niet live; de range-watch van taak 14 mag als informatie blijven).

- [ ] **Step 6: Commit**

```bash
git add scripts/strategy_lab.py app/track_record.py tests/test_strategy_lab_rangesweep.py
git commit -m "feat: strategy_lab --familie rangesweep, hervatbaar, met rapport en opslaan"
```

---

### Task 13: Tabellen, opties en CEO-only

**Files:**
- Modify: `app/schema.sql`, `app/db.py` (`_migrate`), `app/repo.py`, `app/config.py`, `app/rule_live.py`
- Test: `tests/test_range_sweep_repo.py` (nieuw)

**Interfaces:**
- Produces:
  - Tabellen `range_watches`, `range_watch_log`, `range_sweep_setups`, `range_sweep_trades` (schema hieronder).
  - `repo.upsert_range_watch(row) -> tuple[int, bool]`, `repo.list_range_watches(states=("actief",))`, `repo.set_range_watch_state(id, state)`, `repo.mark_range_watch_edge(id, edge) -> bool`, `repo.log_range_watch_push(user_id, watch_id, kind, at, pushed)`, `repo.count_range_watch_pushes(user_id, since_iso) -> int`.
  - `repo.insert_range_sweep_setup(row) -> Optional[int]`, `repo.list_range_sweep_setups(states, since_iso=None)`, `repo.set_range_sweep_setup_state(id, state, signal_id=None)`, `repo.insert_range_sweep_trade(signal_id, setup_id, legs_filled_json, entry, stop, filled_at)`, `repo.list_open_range_sweep_trades()`, `repo.update_range_sweep_trade(signal_id, **fields)`, `repo.list_range_sweep_trades(limit)`, `repo.set_signal_price(signal_id, price)`.
  - `config.RANGE_SWEEP_ENABLED`, `RANGE_WATCH_ENABLED`, `RANGE_SWEEP_PUBLIC` (alle standaard false), `RANGE_WATCH_MAX_PER_DAY` (3), `RANGE_SWEEP_MAX_PER_DAY` (6), `RANGE_SWEEP_MAX_NEGATIVE` (30).
  - `rule_live.RANGE_SWEEP = "range_sweep"` en `rule_live.CEO_ONLY_TYPES` bevat het zolang `RANGE_SWEEP_PUBLIC` uit is.

- [ ] **Step 1: Schrijf de falende tests**

```python
import importlib
import os
import tempfile
import unittest


class RangeSweepRepoTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        os.environ["DATABASE_PATH"] = os.path.join(self.tmp.name, "t.db")
        from app import config, db, repo
        importlib.reload(config); importlib.reload(db); importlib.reload(repo)
        self.repo = repo
        db.init_db()

    def tearDown(self):
        self.tmp.cleanup()

    def watch(self, **kw):
        return {"coin": "ARB", "tf": "2h", "range_high": 0.2045, "range_low": 0.17, "first_at": "2026-10-05T00:00:00+00:00",
                "found_at": "2026-10-10T00:00:00+00:00", "atr": 0.003, **kw}

    def test_watch_is_unique_per_coin_tf_and_start(self):
        a, new_a = self.repo.upsert_range_watch(self.watch())
        b, new_b = self.repo.upsert_range_watch(self.watch(range_high=0.205))
        self.assertEqual((a == b, new_a, new_b), (True, True, False))
        self.assertTrue(self.repo.mark_range_watch_edge(a, "high"))
        self.assertFalse(self.repo.mark_range_watch_edge(a, "high"))

    def test_push_budget_count(self):
        w, _ = self.repo.upsert_range_watch(self.watch())
        self.repo.log_range_watch_push(1, w, "gevonden", "2026-10-16T10:00:00+00:00", True)
        self.repo.log_range_watch_push(1, w, "rand_high", "2026-10-16T11:00:00+00:00", False)
        self.assertEqual(self.repo.count_range_watch_pushes(1, "2026-10-16T00:00:00+00:00"), 1)

    def test_setup_is_unique(self):
        row = {"coin": "ARB", "direction": "short", "variant": "RZ_2H", "family": "zone", "stop_name": "zone_025", "range_tf": "2h",
               "range_high": 0.2045, "range_low": 0.17, "range_first_at": "2026-10-05T00:00:00+00:00", "zone_low": 0.199, "zone_high": 0.2045,
               "zone_at": "2026-10-05T04:00:00+00:00", "sweep_at": None, "extreme": None, "placed_at": "2026-10-16T15:00:00+00:00",
               "legs": "[[1.0, 0.199]]", "stop": 0.2052, "atr_t": 0.003, "score": 85.0, "grade": "A", "reason": "✓ a", "features": "{}",
               "liq_json": "{}", "expires_at": "2026-10-17T15:00:00+00:00", "plan": "{}"}
        self.assertIsNotNone(self.repo.insert_range_sweep_setup(row))
        self.assertIsNone(self.repo.insert_range_sweep_setup(row))
        self.assertEqual(len(self.repo.list_range_sweep_setups(("waiting",))), 1)

    def test_range_sweep_is_ceo_only_by_default(self):
        from app import rule_live
        importlib.reload(rule_live)
        self.assertIn("range_sweep", rule_live.CEO_ONLY_TYPES)
```

- [ ] **Step 2: Run en zie falen**

Run: `python3 -m unittest tests.test_range_sweep_repo -v`
Expected: FAIL (tabellen en functies bestaan niet).

- [ ] **Step 3: Implementeer**

In `app/schema.sql` en met dezelfde `CREATE TABLE IF NOT EXISTS` in `db._migrate()` (volg het patroon waarmee `_migrate` `rule_trades` op een bestaande database zet):

```sql
-- Range-watch (app/range_watch.py): een coin die in een geldige range ligt, zodat je weet waar een sweep of retest kan komen. Eén rij per coin,
-- timeframe en eerste zwaaipunt; de randen mogen bijschuiven. edge_high_at/edge_low_at: wanneer "koers bij de rand" ging (één keer per rand).
CREATE TABLE IF NOT EXISTS range_watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin TEXT NOT NULL,
    tf TEXT NOT NULL,
    range_high REAL NOT NULL,
    range_low REAL NOT NULL,
    first_at TEXT NOT NULL,
    found_at TEXT NOT NULL,
    atr REAL NOT NULL,
    state TEXT NOT NULL DEFAULT 'actief',
    edge_high_at TEXT,
    edge_low_at TEXT,
    ended_at TEXT,
    UNIQUE (coin, tf, first_at)
);
-- Elke waarschuwing van de range-watch per gebruiker, ook als hij geen push werd: het eigen dagbudget telt de rijen met pushed = 1.
CREATE TABLE IF NOT EXISTS range_watch_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL,
    watch_id INTEGER NOT NULL,
    kind TEXT NOT NULL,
    at TEXT NOT NULL,
    pushed INTEGER NOT NULL
);
-- Range sweep-setups (app/range_sweep_live.py), beide families: wachtend op de limiet. Wordt een signaal (trade_type 'range_sweep') zodra een limiet vult.
CREATE TABLE IF NOT EXISTS range_sweep_setups (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin TEXT NOT NULL,
    direction TEXT NOT NULL,
    variant TEXT NOT NULL,
    family TEXT NOT NULL,
    stop_name TEXT NOT NULL,
    range_tf TEXT NOT NULL,
    range_high REAL NOT NULL,
    range_low REAL NOT NULL,
    range_first_at TEXT NOT NULL,
    zone_low REAL NOT NULL,
    zone_high REAL NOT NULL,
    zone_at TEXT NOT NULL,
    sweep_at TEXT,
    extreme REAL,
    placed_at TEXT NOT NULL,
    legs TEXT NOT NULL,
    stop REAL NOT NULL,
    atr_t REAL NOT NULL,
    score REAL NOT NULL,
    grade TEXT NOT NULL,
    reason TEXT NOT NULL,
    features TEXT NOT NULL,
    liq_json TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    plan TEXT NOT NULL,
    state TEXT NOT NULL DEFAULT 'waiting',
    signal_id INTEGER,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (coin, direction, variant, zone_at, placed_at)
);
-- Gevulde range sweep-trades. signals.stop_loss is de stop; deze rij houdt de meting bij die Bewijs toont (stopkwaliteit) en de referentie-uitgang
-- (meelopende stop 3 ATR op 1u) die de R in trade_results geeft. checked_until: openmoment van de laatst verwerkte 15m-candle.
CREATE TABLE IF NOT EXISTS range_sweep_trades (
    signal_id INTEGER PRIMARY KEY,
    setup_id INTEGER NOT NULL,
    legs_filled TEXT NOT NULL,
    entry REAL NOT NULL,
    stop REAL NOT NULL,
    filled_at TEXT NOT NULL,
    checked_until TEXT NOT NULL,
    mae_r REAL NOT NULL DEFAULT 0,
    mfe_r REAL NOT NULL DEFAULT 0,
    reached_1r_at TEXT,
    reached_2r_at TEXT,
    reached_3r_at TEXT,
    reached_4r_at TEXT,
    reached_5r_at TEXT,
    reached_6r_at TEXT,
    stop_hit_at TEXT,
    ref_stop REAL NOT NULL,
    ref_extreme REAL NOT NULL,
    ref_r REAL,
    ref_closed_at TEXT,
    closed_at TEXT
);
```

In `app/config.py`, bij de andere motoren:

```python
# Range sweep (app/range_sweep_live.py) en range-watch (app/range_watch.py): onze lezing van de strategie van Cos867, zie
# docs/onderzoek/range-sweep/preregistratie.md. Standaard uit: de setupmotor gaat pas aan na een geslaagde toets op stopkwaliteit
# (rule_status 'range_sweep_stop'), de range-watch na de keuring met het oog (poort 1). Leerlingen zien het pas als de CEO RANGE_SWEEP_PUBLIC aanzet.
RANGE_SWEEP_ENABLED = _get("RANGE_SWEEP_ENABLED", "false").lower() == "true"
RANGE_WATCH_ENABLED = _get("RANGE_WATCH_ENABLED", "false").lower() == "true"
RANGE_SWEEP_PUBLIC = _get("RANGE_SWEEP_PUBLIC", "false").lower() == "true"
RANGE_WATCH_MAX_PER_DAY = int(_get("RANGE_WATCH_MAX_PER_DAY", "3"))
RANGE_SWEEP_MAX_PER_DAY = int(_get("RANGE_SWEEP_MAX_PER_DAY", "6"))
RANGE_SWEEP_MAX_NEGATIVE = int(_get("RANGE_SWEEP_MAX_NEGATIVE", "30"))
```

In `app/rule_live.py`:

```python
RANGE_SWEEP = "range_sweep"
# De range sweep is een proef zoals deze regel: alleen de CEO tot hij RANGE_SWEEP_PUBLIC aanzet. Via deze tuple filteren for_viewer,
# pending_directions_for_coin en coins_with_recent_signal hem al zonder extra code.
CEO_ONLY_TYPES = (RULE,) + (() if config.RANGE_SWEEP_PUBLIC else (RANGE_SWEEP,))
```

In `app/repo.py` de functies uit Interfaces, elk met `db.session()`. Deze twee precies zo:

```python
def upsert_range_watch(row: dict) -> tuple[int, bool]:
    with db.session() as conn:
        cur = conn.execute("""INSERT OR IGNORE INTO range_watches (coin, tf, range_high, range_low, first_at, found_at, atr)
                              VALUES (:coin, :tf, :range_high, :range_low, :first_at, :found_at, :atr)""", row)
        if cur.rowcount:
            return cur.lastrowid, True
        conn.execute("UPDATE range_watches SET range_high = :range_high, range_low = :range_low, atr = :atr WHERE coin = :coin AND tf = :tf AND first_at = :first_at", row)
        rid = conn.execute("SELECT id FROM range_watches WHERE coin = ? AND tf = ? AND first_at = ?", (row["coin"], row["tf"], row["first_at"])).fetchone()["id"]
        return rid, False


def mark_range_watch_edge(watch_id: int, edge: str) -> bool:
    """Eén waarschuwing per rand: markeer vóór het versturen, zoals price_alerts, zodat een herstart niet dubbel meldt."""
    col = {"high": "edge_high_at", "low": "edge_low_at"}[edge]
    with db.session() as conn:
        return conn.execute(f"UPDATE range_watches SET {col} = datetime('now') WHERE id = ? AND {col} IS NULL", (watch_id,)).rowcount == 1
```

`insert_range_sweep_setup` gebruikt `INSERT OR IGNORE` en geeft `None` bij `rowcount == 0`.

- [ ] **Step 4: Run en zie slagen**

Run: `python3 -m unittest tests.test_range_sweep_repo -v && SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/schema.sql app/db.py app/repo.py app/config.py app/rule_live.py tests/test_range_sweep_repo.py
git commit -m "feat: tabellen en opties voor range-watch en range sweep"
```

---

### Task 14: Range-watch

**Files:**
- Create: `app/range_watch.py`
- Modify: `app/market_scanner.py` (aanroep in de 5-minutencyclus, naast `rule_live.scan()`)
- Test: `tests/test_range_watch.py` (nieuw)

**Interfaces:**
- Consumes: `rangesweep.range_series`, `rangesweep.build_frames` (taak 4), repo en config (taak 13).
- Produces: `EDGE_NEAR_ATR = 0.25`, `PUSH_TFS = ("2h", "4h")`, `current_ranges(frames, now) -> dict[str, Optional[Range]]`, `events(watch, price, rng_now) -> list[str]` (uit `"rand_high"`, `"rand_low"`, `"einde"`), `should_push(kind, tf, sent_24h, budget) -> tuple[bool, str]`, `watch_body(coin, tf, rng, price) -> str`, `async run(now=None)`.

Regels (vooraf, tegen spam):
1. Een nieuwe range op **2u of 4u** geeft "Range gevonden". Nieuwe 30m- en 1u-ranges staan alleen op de pagina.
2. "Koers bij de rand": één keer per range per rand, als de koers binnen 0,25 ATR van de rand komt, voor alle timeframes.
3. Een range die eindigt (`gesweept`, `gebroken`, `verlopen`) geeft geen push, alleen de pagina.
4. Hooguit `RANGE_WATCH_MAX_PER_DAY` (3) watch-pushes per gebruiker per 24 uur, los van het kansbudget. Daarboven een rustige melding. Pushes zijn stil; de pauze geldt via `send_push`.
5. Alleen de CEO zolang `RANGE_SWEEP_PUBLIC` uit is.

- [ ] **Step 1: Schrijf de falende tests**

```python
import unittest

import pandas as pd

from app import range_watch as rw
from app.replay import rangesweep as rs
from tests.replay.rangesweep_fixtures import SWEEP_HOUR, frames


def rng(high=110.0, low=100.0, atr=1.0, first="2026-10-01"):
    t = pd.Timestamp(first, tz="UTC")
    return rs.Range("4h", t, high, low, 3, 3, 0.0, 0.0, t, atr)


class RangeWatchTest(unittest.TestCase):
    def test_current_ranges_uses_closed_candles(self):
        b15, b1h, b4h = frames()
        now = b1h["timestamp"].iloc[SWEEP_HOUR]
        cut = lambda df: df[df["timestamp"] < now]
        cur = rw.current_ranges(rs.build_frames(cut(b15), cut(b1h), cut(b4h)), now)
        self.assertAlmostEqual(cur["1h"].high, 106.025)
        self.assertEqual(set(cur), set(rs.TFS))

    def test_edge_events_once_per_edge(self):
        w = {"range_high": 110.0, "range_low": 100.0, "atr": 1.0, "edge_high_at": None, "edge_low_at": None}
        self.assertEqual(rw.events(w, 109.8, rng()), ["rand_high"])
        self.assertEqual(rw.events({**w, "edge_high_at": "x"}, 109.8, rng()), [])
        self.assertEqual(rw.events(w, 105.0, rng()), [])
        self.assertEqual(rw.events(w, 100.1, rng()), ["rand_low"])
        self.assertEqual(rw.events(w, 105.0, None), ["einde"])

    def test_budget_and_small_timeframes(self):
        self.assertEqual(rw.should_push("gevonden", "4h", 0, 3), (True, ""))
        self.assertEqual(rw.should_push("gevonden", "2h", 0, 3), (True, ""))
        self.assertFalse(rw.should_push("gevonden", "30m", 0, 3)[0])
        ok, why = rw.should_push("rand_high", "1h", 3, 3)
        self.assertFalse(ok)
        self.assertIn("budget", why)

    def test_body_is_measured_only(self):
        body = rw.watch_body("ARB", "2h", rng(0.2045, 0.17, 0.003), 0.1988)
        self.assertIn("Range 2u", body)
        self.assertIn("3 keer boven, 3 keer onder", body)
        self.assertNotIn("kans", body.lower())
```

- [ ] **Step 2: Run en zie falen**

Run: `python3 -m unittest tests.test_range_watch -v`
Expected: FAIL met `ModuleNotFoundError: No module named 'app.range_watch'`.

- [ ] **Step 3: Implementeer**

```python
"""Range-watch: welke coins liggen nu in een geldige range (zelfde detector als het lab, app/replay/rangesweep.py), zodat je weet waar een sweep of
retest kan komen. Informatie, geen kans: geen richting, geen order. Eigen budget van RANGE_WATCH_MAX_PER_DAY stille pushes per gebruiker, zodat een
setup nooit wegvalt omdat een watch het kansbudget opmaakte. Regels in docs/superpowers/plans/2026-10-16-range-sweep-strategie.md, taak 14."""
import asyncio
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from app import config, push_notify, repo
from app.replay import rangesweep as rs, trendlab as tl

logger = logging.getLogger("range_watch")
EDGE_NEAR_ATR = 0.25
# Op 30m en 1u ontstaan tientallen ranges per dag; alleen de grotere geven een push "gevonden", de rest staat op de pagina.
PUSH_TFS = ("2h", "4h")
COINS = tl.LAB_COINS
TF_LABEL = {"30m": "30m", "1h": "1u", "2h": "2u", "4h": "4u"}


def current_ranges(frames: dict, now: pd.Timestamp) -> dict[str, Optional[rs.Range]]:
    out = {}
    for tf in rs.TFS:
        bars = frames[tf]
        closed = bars[bars["timestamp"] + rs.TF_DELTA[tf] <= now]
        out[tf] = rs.range_series(closed, tf)[1][-1] if len(closed) > rs.RANGE_LOOKBACK[tf] else None
    return out


def events(watch: dict, price: float, rng_now: Optional[rs.Range]) -> list[str]:
    if rng_now is None:
        return ["einde"]
    near = EDGE_NEAR_ATR * watch["atr"]
    out = []
    if not watch.get("edge_high_at") and price >= watch["range_high"] - near:
        out.append("rand_high")
    if not watch.get("edge_low_at") and price <= watch["range_low"] + near:
        out.append("rand_low")
    return out


def should_push(kind: str, tf: str, sent_24h: int, budget: int) -> tuple[bool, str]:
    if kind == "gevonden" and tf not in PUSH_TFS:
        return False, "Ranges op 30m en 1u staan alleen op de pagina."
    if budget and sent_24h >= budget:
        return False, f"Range-watch: budget van {budget} per 24 uur bereikt, daarom geen push."
    return True, ""


def watch_body(coin: str, tf: str, rng: rs.Range, price: float) -> str:
    return "\n".join([f"Range {TF_LABEL[tf]}: {push_notify.fmt_price(rng.low)} tot {push_notify.fmt_price(rng.high)}",
                      f"{rng.high_touches} keer boven, {rng.low_touches} keer onder aangeraakt. Koers {push_notify.fmt_price(price)}.",
                      "Aan de randen kan een retest van een zone of een sweep komen."])


def viewers() -> list[int]:
    return [u["id"] for u in repo.list_users()] if config.RANGE_SWEEP_PUBLIC else repo.list_ceo_user_ids()


async def _warn(watch_id: int, tf: str, kind: str, title: str, body: str, now: datetime) -> None:
    since = (now - timedelta(hours=24)).isoformat()
    for uid in viewers():
        ok, why = should_push(kind, tf, repo.count_range_watch_pushes(uid, since), config.RANGE_WATCH_MAX_PER_DAY)
        repo.log_range_watch_push(uid, watch_id, kind, now.isoformat(), ok)
        if ok:
            await push_notify.send_push(uid, title, body, "/structuur#ranges", silent=True, tag=f"range-{watch_id}")
        else:
            repo.create_notification(uid, "range", title, f"{body}\n{why}", "/structuur#ranges")


async def _coin(coin: str, now: datetime) -> None:
    from app import exchange
    parts = [await asyncio.to_thread(exchange.fetch_ohlcv, coin, timeframe=tf, limit=400) for tf in ("15m", "1h", "4h")]
    frames = rs.build_frames(*parts)
    price = float(parts[0]["close"].iloc[-1])
    cur = current_ranges(frames, pd.Timestamp(now))
    for tf, r in cur.items():
        if r is None:
            continue
        wid, new = repo.upsert_range_watch({"coin": coin, "tf": tf, "range_high": r.high, "range_low": r.low, "first_at": r.first_at.isoformat(),
                                            "found_at": r.known_at.isoformat(), "atr": r.atr})
        if new:
            await _warn(wid, tf, "gevonden", f"{coin} · Range {TF_LABEL[tf]} gevonden", watch_body(coin, tf, r, price), now)
    for w in (x for x in repo.list_range_watches(("actief",)) if x["coin"] == coin):
        r = cur.get(w["tf"])
        same = r is not None and r.first_at.isoformat() == w["first_at"]
        for ev in events(w, price, r if same else None):
            if ev == "einde":
                out = price > w["range_high"] + rs.CONTAIN_ATR * w["atr"] or price < w["range_low"] - rs.CONTAIN_ATR * w["atr"]
                repo.set_range_watch_state(w["id"], "gebroken" if out else "verlopen")
            elif repo.mark_range_watch_edge(w["id"], ev.split("_")[1]):
                edge = "bovenrand" if ev == "rand_high" else "onderrand"
                await _warn(w["id"], w["tf"], ev, f"{coin} · Koers bij de {edge} ({TF_LABEL[w['tf']]})", watch_body(coin, w["tf"], r, price), now)


async def run(now: Optional[datetime] = None) -> None:
    """5-minutencyclus. Alleen in de eerste 10 minuten na een half uur: een range verandert alleen bij een gesloten 30m-candle of groter."""
    if not config.RANGE_WATCH_ENABLED:
        return
    now = now or datetime.now(timezone.utc)
    if now.minute % 30 >= 10:
        return
    for coin in COINS:
        try:
            await _coin(coin, now)
        except Exception:
            logger.exception("Range-watch voor %s is mislukt", coin)
    repo.beat("range_watch", f"{len(COINS)} coins gecontroleerd")
```

De status `gesweept` zet `range_sweep_live` (taak 15). `limit=400` 15m-candles geeft 200 30m-candles, genoeg voor een lookback van 120 plus de ATR; 1u en 4u idem. In `app/market_scanner.py`, direct na het blok met `await rule_live.scan()`:

```python
    try:
        await range_watch.run()
    except Exception:
        logger.exception("Range-watch is mislukt")
```

en voeg `range_watch` toe aan de import van `app`.

- [ ] **Step 4: Run en zie slagen**

Run: `python3 -m unittest tests.test_range_watch -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add app/range_watch.py app/market_scanner.py tests/test_range_watch.py
git commit -m "feat: range-watch met eigen budget"
```

---

### Task 15: Proefmotor range sweep

**Files:**
- Create: `app/range_sweep_live.py`
- Modify: `app/market_scanner.py`, `app/level_check.py`
- Test: `tests/test_range_sweep_live.py` (nieuw)

**Interfaces:**
- Consumes: taken 4, 5, 6, 9, 13; `rule_status` rij `range_sweep_stop` (taak 12).
- Produces: `TRADE_TYPE = "range_sweep"`, `STOP_KEY = "range_sweep_stop"`, `EDGE_KEY = "range_sweep"`, `REF_HORIZON = pd.Timedelta(days=7)`, `live_variant(lab_row) -> Optional[tuple[RSVariant, str]]`, `fresh_setups(frames, v, now) -> list[dict]`, `liquidation_check(direction, buckets, t0, t1, baseline_buckets) -> dict`, `alert_body(row, price) -> str`, `follow_step(trade, candles, atr15) -> dict`, `async scan(now=None)`, `async track(now=None)`, `async follow(now=None)`.

Uitkomst en Bewijs:
- Stop geraakt: push "Stop geraakt" (altijd), `stop_hit_at` gezet. Is de referentie nog open, dan sluit die op dezelfde candle met de stop-R.
- Referentie-uitgang (meelopende stop 3 ATR op 1u) geraakt of 7 dagen voorbij: `repo.set_trade_result(signal_id, ref_r, closed_at)` en `repo.mark_signal_auto_outcome(signal_id, "take_profit" if ref_r > 0 else "stop_loss", closed_at)`; alleen een rustige melding ("Meting klaar: referentie-uitgang +1,40R, jouw trade beslis je zelf").
- De meting van de stopkwaliteit (stop geraakt, +1R tot +6R) loopt door tot de stop of 7 dagen.
- Liquidaties: bij een sweep de som in het venster van de prik; bij een zone-retest in het uur vóór het plaatsen. Altijd "niet getoetst, geen historie".

- [ ] **Step 1: Schrijf de falende tests**

```python
import unittest

import numpy as np
import pandas as pd

from app import range_sweep_live as live
from app.replay import rangesweep as rs, rangesweep_lab as rl
from tests.replay.rangesweep_fixtures import FIRST_SHORT_ZONE_SETUP_HOUR, frames


class VariantTest(unittest.TestCase):
    def test_variant_from_the_lab_row(self):
        v, stop = live.live_variant({"lab_passes": 1, "lab_json": {"variant": "RZ_2H", "stop_name": "zone_05"}})
        self.assertEqual((v.name, stop), ("RZ_2H", "zone_05"))
        self.assertIsNone(live.live_variant({"lab_passes": 0, "lab_json": {"variant": "RZ_2H"}}))
        self.assertIsNone(live.live_variant(None))


class FreshTest(unittest.TestCase):
    def test_only_setups_placed_in_the_last_20_minutes(self):
        b15, b1h, b4h = frames()
        v = rl.RSVariant("T", "zone", "1h", "zone", "slot", False, False)
        placed = b1h["timestamp"].iloc[FIRST_SHORT_ZONE_SETUP_HOUR] + pd.Timedelta(hours=1)
        def at(now):
            cut = lambda df: df[df["timestamp"] < now]
            return rs.build_frames(cut(b15), cut(b1h), cut(b4h))
        now = placed + pd.Timedelta(minutes=5)
        self.assertEqual([s["direction"] for s in live.fresh_setups(at(now), v, now)], ["short"])
        later = placed + pd.Timedelta(minutes=40)
        self.assertEqual(live.fresh_setups(at(later), v, later), [])


class LiquidationTest(unittest.TestCase):
    def test_short_counts_liquidated_shorts(self):
        t = pd.Timestamp("2026-10-15 14:00", tz="UTC")
        buckets = [{"bucket": (t + pd.Timedelta(minutes=5 * k)).isoformat(), "long_usd": 0.0, "short_usd": 50_000.0} for k in range(12)]
        base = [{"bucket": (t - pd.Timedelta(hours=h)).isoformat(), "long_usd": 0.0, "short_usd": 10_000.0} for h in range(1, 169)]
        out = live.liquidation_check("short", buckets, t, t + pd.Timedelta(hours=1), base)
        self.assertEqual(out["usd"], 600_000.0)
        self.assertTrue(out["ok"])

    def test_no_data_is_not_a_pass(self):
        t = pd.Timestamp("2026-10-15 14:00", tz="UTC")
        self.assertFalse(live.liquidation_check("long", [], t, t + pd.Timedelta(hours=1), [])["ok"])


class FollowTest(unittest.TestCase):
    def frame(self, rows):
        df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
        df.insert(0, "timestamp", pd.date_range("2026-10-15 15:00", periods=len(df), freq="15min", tz="UTC"))
        return df

    def trade(self):
        base = {"direction": "short", "entry": 105.0, "stop": 106.0, "filled_at": "2026-10-15T15:00:00+00:00", "checked_until": "2026-10-15T14:45:00+00:00",
                "mae_r": 0.0, "mfe_r": 0.0, "stop_hit_at": None, "ref_stop": 106.0, "ref_extreme": 105.0, "ref_r": None, "ref_closed_at": None}
        return {**base, **{f"reached_{k}r_at": None for k in range(1, 7)}}

    def test_reaches_one_r_and_records_the_time(self):
        c = self.frame([(105, 105.1, 104.9, 105), (105, 105.1, 103.9, 104.0)])
        out = live.follow_step(self.trade(), c, np.ones(len(c)))
        self.assertIsNotNone(out["reached_1r_at"])
        self.assertIsNone(out["stop_hit_at"])
        self.assertAlmostEqual(out["mfe_r"], 1.1)

    def test_stop_closes_reference_too(self):
        c = self.frame([(105, 105.1, 104.9, 105), (105, 106.2, 104.9, 106.1)])
        out = live.follow_step(self.trade(), c, np.ones(len(c)))
        self.assertIsNotNone(out["stop_hit_at"])
        self.assertAlmostEqual(out["ref_r"], -1.0)

    def test_already_checked_candles_are_skipped(self):
        c = self.frame([(105, 106.2, 104.9, 106.1)])
        self.assertIsNone(live.follow_step({**self.trade(), "checked_until": c["timestamp"].iloc[0].isoformat()}, c, np.ones(1))["stop_hit_at"])


class BodyTest(unittest.TestCase):
    def test_alert_says_choose_your_own_target(self):
        row = {"coin": "ARB", "direction": "short", "family": "zone", "range_tf": "2h", "legs": "[[1.0, 0.199]]", "stop": 0.2052, "range_high": 0.2045,
               "range_low": 0.17, "grade": "A", "score": 85.0, "liq_json": '{"ok": false}'}
        body = live.alert_body(row, 0.1985)
        self.assertIn("Limiet 0.1990", body)
        self.assertIn("Stop 0.2052", body)
        self.assertIn("doel kies je zelf", body)
        self.assertIn("Overkant 0.1700", body)
        self.assertIn("Zone-retest 2u", body)
        self.assertIn("Ongetest", body)
```

- [ ] **Step 2: Run en zie falen**

Run: `python3 -m unittest tests.test_range_sweep_live -v`
Expected: FAIL met `ModuleNotFoundError`.

- [ ] **Step 3: Implementeer**

`app/range_sweep_live.py`:

```python
"""Proefmotor range sweep: dezelfde detector als het lab (app/replay/rangesweep.py) op gesloten candles, met de variant en stop die het lab koos
(rule_status 'range_sweep_stop'). Een setup wacht met een limiet op de zone; vult de limiet, dan wordt het een signaal (trade_type 'range_sweep')
zonder doel. Eerlijk over wat dit is: ongetest, alleen voor de CEO tot hij anders beslist, en een R op Bewijs die gemeten is bij een referentie-uitgang
(meelopende stop 3 ATR op 1u), niet bij jouw doel. Liquidaties hebben geen historie: hier staan ze als extra ✓/✗, buiten de score en buiten het lab."""
import asyncio
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Optional

import numpy as np
import pandas as pd

from app import chance_checks, config, push_notify, repo
from app.replay import rangesweep as rs, rangesweep_lab as rl, stopquality as sq, trendlab as tl

logger = logging.getLogger("range_sweep_live")
TRADE_TYPE = "range_sweep"
STOP_KEY, EDGE_KEY = "range_sweep_stop", "range_sweep"
COINS = tl.LAB_COINS
REF_HORIZON = pd.Timedelta(days=7)
FRESH = pd.Timedelta(minutes=20)
LIQ_FACTOR = 2.0
TF_LABEL = {"30m": "30m", "1h": "1u", "2h": "2u", "4h": "4u"}
FAMILY_LABEL = {"zone": "Zone-retest", "sweep": "Range sweep"}


def live_variant(lab_row: Optional[dict]) -> Optional[tuple[rl.RSVariant, str]]:
    if not lab_row or not lab_row.get("lab_passes"):
        return None
    data = lab_row.get("lab_json") or {}
    data = json.loads(data) if isinstance(data, str) else data
    v = next((x for x in rl.VARIANTS if x.name == data.get("variant")), None)
    return (v, data.get("stop_name") or v.stops[0]) if v else None


def fresh_setups(frames: dict, v: rl.RSVariant, now: pd.Timestamp) -> list[dict]:
    setups, _ = rs.find_setups(frames, v.tf, v.family, v.entry, v.confirm, v.htf)
    return [s for s in setups if now - FRESH < s["placed_at"] <= now]


def liquidation_check(direction: str, buckets: list[dict], t0, t1, baseline_buckets: list[dict]) -> dict:
    """Een prik omhoog liquideert shorts (short_usd), omlaag longs. ✓ als de som in het venster per uur minstens LIQ_FACTOR maal de mediaan per uur
    van de week ervoor is. Geen data is geen ✓: de stroom kan uit hebben gestaan."""
    col = "short_usd" if direction == "short" else "long_usd"
    t0, t1 = pd.Timestamp(t0), pd.Timestamp(t1)
    usd = float(sum(b[col] for b in buckets if t0 <= pd.Timestamp(b["bucket"]) < t1))
    hours = max(1.0, (t1 - t0) / pd.Timedelta(hours=1))
    per_hour: dict = {}
    for b in baseline_buckets:
        h = pd.Timestamp(b["bucket"]).floor("h")
        per_hour[h] = per_hour.get(h, 0.0) + b[col]
    base = float(np.median(list(per_hour.values()))) if per_hour else 0.0
    return {"usd": usd, "baseline": base, "ok": bool(usd > 0 and base > 0 and usd / hours >= LIQ_FACTOR * base)}


def alert_body(row: dict, price: Optional[float]) -> str:
    legs = json.loads(row["legs"])
    mid = (row["range_high"] + row["range_low"]) / 2
    opp = row["range_low"] if row["direction"] == "short" else row["range_high"]
    liq = json.loads(row.get("liq_json") or "{}")
    lim = " · ".join(f"Limiet {push_notify.fmt_price(p)}" + (f" ({w * 100:.0f}%)" if len(legs) > 1 else "") for w, p in legs)
    planned = sum(w * p for w, p in legs) / sum(w for w, _ in legs)
    return "\n".join([lim, f"Stop {push_notify.fmt_price(row['stop'])} ({abs(planned - row['stop']) / planned * 100:.2f}%) · doel kies je zelf",
                      f"Referentie: Midden {push_notify.fmt_price(mid)} · Overkant {push_notify.fmt_price(opp)}",
                      f"{FAMILY_LABEL[row['family']]} {TF_LABEL[row['range_tf']]}, score {row['score']:.0f} van 100" + (" · liquidaties ✓" if liq.get("ok") else ""),
                      "Ongetest: een proef, Bewijs toont de stopkwaliteit.", push_notify.OPEN_PLAN_LINE])


def follow_step(trade: dict, candles: pd.DataFrame, atr15: np.ndarray) -> dict:
    """Werkt de meting en de referentie bij met de candles na checked_until. Zelfde regels als stopquality.measure: een candle die de stop en een
    R-niveau raakt telt als stop, een gat door de stop vult op de open, de referentie-stop schuift alleen de goede kant op."""
    short = trade["direction"] == "short"
    entry, stop = trade["entry"], trade["stop"]
    risk = abs(entry - stop)
    keys = ["mae_r", "mfe_r", "stop_hit_at", "ref_stop", "ref_extreme", "ref_r", "ref_closed_at", "checked_until"] + [f"reached_{k}r_at" for k in sq.R_LEVELS]
    out = {k: trade[k] for k in keys}
    filled_at, checked = pd.Timestamp(trade["filled_at"]), pd.Timestamp(trade["checked_until"])
    for k, c in enumerate(candles.itertuples()):
        if c.timestamp <= checked or out["stop_hit_at"] or c.timestamp >= filled_at + REF_HORIZON:
            continue
        at = c.timestamp.isoformat()
        if out["ref_r"] is None and ((c.high >= out["ref_stop"]) if short else (c.low <= out["ref_stop"])):
            fill = max(c.open, out["ref_stop"]) if short else min(c.open, out["ref_stop"])
            out["ref_r"], out["ref_closed_at"] = ((entry - fill) if short else (fill - entry)) / risk, at
        if (c.high >= stop) if short else (c.low <= stop):
            fill = max(c.open, stop) if short else min(c.open, stop)
            out["stop_hit_at"], out["checked_until"] = at, at
            out["mae_r"] = max(out["mae_r"], ((fill - entry) if short else (entry - fill)) / risk)
            if out["ref_r"] is None:
                out["ref_r"], out["ref_closed_at"] = ((entry - fill) if short else (fill - entry)) / risk, at
            break
        out["mae_r"] = max(out["mae_r"], ((c.high - entry) if short else (entry - c.low)) / risk)
        fav = ((entry - c.low) if short else (c.high - entry)) / risk
        out["mfe_r"] = max(out["mfe_r"], fav)
        for r in sq.R_LEVELS:
            if fav >= r and not out[f"reached_{r}r_at"]:
                out[f"reached_{r}r_at"] = at
        if out["ref_r"] is None and np.isfinite(atr15[k]):
            ext = min(out["ref_extreme"], c.low) if short else max(out["ref_extreme"], c.high)
            trail = ext + sq.TRAIL_K * atr15[k] if short else ext - sq.TRAIL_K * atr15[k]
            out["ref_extreme"], out["ref_stop"] = ext, (min(out["ref_stop"], trail) if short else max(out["ref_stop"], trail))
        out["checked_until"] = at
    return out
```

De async-delen in dezelfde module:

- `viewers()`: zoals `range_watch.viewers`.
- `_frames(coin, now)`: haal 15m, 1u, 4u op (`exchange.fetch_ohlcv`, `limit=1000`), houd alleen gesloten candles (`rule_live.closed_only` met de juiste delta), en geef `rs.build_frames(...)`.
- `scan(now)`: stop als `config.RANGE_SWEEP_ENABLED` uit is of als `now.minute % 15 >= 10` (alleen kort na een gesloten 15m-candle). `choice = live_variant(repo.get_rule_lab(STOP_KEY))`; zonder keuze: log "geen geslaagde toets op stopkwaliteit" en stop. Zet de motor uit als `structure_live.should_disable(repo.list_type_results(TRADE_TYPE, config.RANGE_SWEEP_MAX_NEGATIVE), config.RANGE_SWEEP_MAX_NEGATIVE)` (S4) met `repo.notify_engine_disabled("Range sweep", "De laatste 30 afgeronde proeftrades zijn samen negatief bij de referentie-uitgang. Zie Bewijs.")`. Per coin uit `COINS`: `fresh_setups(_frames(coin, now), v, now)`. Per setup: stop = `rs.final_stop(s, stop_name)`; score en reason met `chance_checks.weighted_finish(chance_checks.range_sweep_checks(s["features"], v.tf))`; graad met `grade_of`; liquidaties met `liquidation_check(direction, repo.list_liquidations(coin, t0), t0, t1, repo.list_liquidations(coin, (t0 - 7 dagen)))` met `t0, t1 = sweep_at, return_at` bij een sweep en `placed_at - 1 uur, placed_at` bij een zone-retest. Bewaar met `repo.insert_range_sweep_setup` (plan-json met de laatste 80 candles van `v.tf` en de actieve zones van dat moment voor de grafiek); `None` is al bekend: niets doen. Zet de range-watch van die range op `gesweept` (alleen bij de sweepfamilie). Dagcap: bij `len(repo.list_range_sweep_setups(("waiting", "filled"), since_iso=24 uur terug)) >= config.RANGE_SWEEP_MAX_PER_DAY` wordt de setup bewaard met state `niet_gemeld`, zonder push. Push per viewer met titel `push_notify.alert_title(coin, direction, f"{FAMILY_LABEL[family]} wacht")`, URL `/structuur#range-sweep-{id}`, tag `range-sweep-{id}`: A met `send_kans_push(..., silent=quiet)`, B met `send_kans_push(..., silent=True)`, C geen push. `repo.beat("range_sweep", ...)`.
- `track(now)`: voor `repo.list_range_sweep_setups(("waiting", "niet_gemeld"))`: 15m-candles (gesloten plus de vormende) sinds `placed_at`, `sq.simulate_fills(direction, legs, stop, mid, candles, 0)`. Verval en de candles dekken die reden: state `stop_voor_vulling`, `weggelopen` of `verlopen`, alleen een rustige melding. Gevuld: `repo.insert_signal({"message_id": None, "coin": coin, "direction": direction, "category": "day_trading", "trade_type": TRADE_TYPE, "pattern_name": variant, "price": gewogen instap van de gevulde orders, "stop_loss": stop, "take_profit": None, "confidence": f"{FAMILY_LABEL[family]} {grade}", "reason": reason, "pass_pct": score, "technical_confirmed": 1, "hard_gates_ok": 1, "is_practice": 0, "plain_explanation": f"{FAMILY_LABEL[family]} {TF_LABEL[tf]}: limiet gevuld, stop voorbij de zone, doel kies je zelf."}, chain_it=False)`, journaalregels voor de viewers (`repo.create_journal_entry(signal_id, uid, None)`), `repo.insert_range_sweep_trade(...)` met `ref_stop = stop` en `ref_extreme = instap`, state `filled`, en `push_notify.send_push` naar elke viewer, ook bij C ("een kans krijgt altijd een melding zodra de limiet vult"), titel `alert_title(coin, direction, f"{FAMILY_LABEL[family]} gevuld")`, body "Limiet geraakt op X, stop Y, doel kies je zelf". Vult later de tweede order van een split: `repo.set_signal_price(signal_id, nieuwe gewogen instap)` en `legs_filled` bijwerken, zolang er geen uitkomst is.
- `follow(now)`: voor `repo.list_open_range_sweep_trades()`: 15m-candles sinds `checked_until`, 1u-candles voor `sq.atr_on_15m`, `follow_step`, `repo.update_range_sweep_trade(...)`. Nieuwe `stop_hit_at`: `send_push` "Stop geraakt, -1,00R" (of de echte R bij een gat). Nieuwe `ref_closed_at`: `repo.set_trade_result(signal_id, ref_r, closed_at)` en `repo.mark_signal_auto_outcome(signal_id, "take_profit" if ref_r > 0 else "stop_loss", closed_at)` met `closed_at = max(now, signal.created_at)` zoals `rule_live._update_trade`, plus een rustige melding. Na 7 dagen zonder referentie-uitgang: `ref_r` is de R op het slot van de laatste candle binnen de horizon, zelfde afhandeling. `closed_at` gezet bij stop of 7 dagen.

In `app/market_scanner.py` na de range-watch:

```python
    try:
        await range_sweep_live.scan()
        await range_sweep_live.track()
        await range_sweep_live.follow()
    except Exception:
        logger.exception("Range sweep-motor is mislukt")
```

In `app/level_check.py`, naast de filters op `rule_live.RULE` (regels 103 en 167): sluit ook `range_sweep_live.TRADE_TYPE` uit, met het comment "Geen vast doel en een eigen meting: range_sweep_live zet uitkomst en R zelf". `list_unresolved_signals_with_levels` slaat signalen zonder doel al over; het expliciete filter houdt dat waar als die query verandert.

- [ ] **Step 4: Run en zie slagen**

Run: `python3 -m unittest tests.test_range_sweep_live -v && SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .`
Expected: PASS.

- [ ] **Step 5: Scratch-controle**

```bash
DATABASE_PATH=/tmp/scratch_rs.db python3 -c "
from app import db, repo; db.init_db()
repo.set_rule_lab('range_sweep_stop', True, {'variant': 'RZ_2H', 'stop_name': 'zone_025'}, '2026-10-16T00:00:00+00:00')
from app import range_sweep_live as l; print(l.live_variant(repo.get_rule_lab('range_sweep_stop')))"
```

Expected: `(RSVariant(name='RZ_2H', ...), 'zone_025')`.

- [ ] **Step 6: Commit**

```bash
git add app/range_sweep_live.py app/market_scanner.py app/level_check.py tests/test_range_sweep_live.py
git commit -m "feat: proefmotor range sweep zonder doel, met stopmeting"
```

---

### Task 16: Kaart, stappen, open kansen en de Ranges-tab

**Files:**
- Modify: `app/chance_steps.py`, `app/today.py`, `web/main.py`, `web/templates/_macros.html`, `web/templates/structuur.html`, `web/templates/smc.html`, `web/templates/vandaag.html`, `web/static/style.css`
- Test: `tests/test_chance_steps.py`, `tests/test_today.py`, `tests/test_web_layout.py`

**Interfaces:**
- Consumes: tabellen uit taak 13, rijen uit taak 15, `setup_chart.range_sweep_svg` (taak 8), labrij `range_sweep_stop`.
- Produces:
  - `chance_steps.range_sweep_steps(row: dict, price: Optional[float], coin: str) -> list[dict]`, `chance_steps.range_chips(legs, stop, mid, opp) -> list[dict]`.
  - `today.open_chances(..., range_cards: list[dict] = ())`, `today.SIGNAL_LABELS["range_sweep"] = "Range sweep gevuld"`, `today.stop_headline(row, lab, cost_pct) -> dict`.
  - `web.main._range_sweep_cards(user)`, `web.main._range_watch_rows(user)`, macro `macros.range_sweep_card(c)`.

- [ ] **Step 1: Schrijf de falende tests**

In `tests/test_chance_steps.py`:

```python
class RangeSweepStepsTest(unittest.TestCase):
    ROW = {"direction": "short", "family": "zone", "legs": "[[0.4, 0.2045], [0.6, 0.199]]", "stop": 0.2052, "range_high": 0.2045, "range_low": 0.17, "range_tf": "2h"}

    def test_three_steps_and_no_target(self):
        steps = chance_steps.range_sweep_steps(self.ROW, 0.1985, "ARB")
        self.assertEqual(len(steps), 3)
        self.assertIn("zone", steps[0]["title"])
        self.assertIn("40% op 0.2045", steps[1]["title"])
        self.assertIn("60% op 0.199", steps[1]["title"])
        self.assertIn("doel kies je zelf", steps[2]["title"])
        self.assertIn("Overkant 0.17", steps[2]["sub"])
        self.assertNotIn("rr", steps[2])

    def test_chips(self):
        chips = chance_steps.range_chips([(0.4, 0.2045), (0.6, 0.199)], 0.2052, 0.18725, 0.17)
        self.assertEqual([c["label"] for c in chips], ["Limiet 40%", "Limiet 60%", "Stop", "Midden (ref.)", "Overkant (ref.)"])
```

In `tests/test_today.py`:

```python
    def test_range_sweep_card_counts_as_open_chance(self):
        card = {"id": 3, "coin": "ARB", "direction": "short", "distance_pct": 0.12, "family": "zone"}
        items = today.open_chances([], [], [], [], {}, datetime(2026, 10, 16, tzinfo=timezone.utc), range_cards=[card])
        self.assertEqual([(i["kind"], i["soort"], i["url"]) for i in items], [("range_sweep", "Zone-retest", "/structuur#range-sweep-3")])

    def test_filled_range_sweep_without_target_stays_open_for_six_hours(self):
        now = datetime(2026, 10, 16, 12, tzinfo=timezone.utc)
        sig = {"id": 9, "coin": "ARB", "direction": "short", "trade_type": "range_sweep", "auto_outcome": None, "created_at": "2026-10-16T10:00:00+00:00",
               "stop_loss": 0.2052, "take_profit": None}
        self.assertEqual(today.open_chances([], [], [], [sig], {"ARB": 0.199}, now)[0]["soort"], "Range sweep gevuld")

    def test_stop_headline_is_measured(self):
        h = today.stop_headline({"direction": "short", "legs": "[[1.0, 100.0]]", "stop": 102.5}, {"doelkans": [{"r": 1, "p_text": "48%", "ci_text": "41 tot 55%", "n": 412}]}, 0.12)
        self.assertEqual((h["value"], h["unit"]), ("2,50", "%"))
        self.assertEqual(h["delta"], "kosten 0,05R")
        self.assertEqual(h["doelkans"][0]["p_text"], "48%")
```

In `tests/test_web_layout.py` (zelfde patroon als de bestaande tests daar): `/structuur` als CEO met één wachtende `range_sweep_setups`-rij toont `id="range-sweep-`, "doel kies je zelf", een kop "Stop" en `class="sc-zone`; als leerling geen `range-sweep-`.

- [ ] **Step 2: Run en zie falen**

Run: `python3 -m unittest tests.test_chance_steps tests.test_today tests.test_web_layout -v`
Expected: FAIL.

- [ ] **Step 3: Implementeer**

`app/chance_steps.py` (met `import json` bovenaan):

```python
FAMILY_WORD = {"zone": "de zone", "sweep": "het order block"}


def range_sweep_steps(row: dict, price: Optional[float], coin: str) -> list[dict]:
    """Zelfde drie stappen als elke kans, maar stap drie heeft geen doel: HesPulse levert de stop, het doel kies je zelf; midden en overkant
    van de range staan erbij als referentie, niet als advies."""
    legs = [tuple(x) for x in json.loads(row["legs"])]
    short = row["direction"] == "short"
    planned = sum(w * p for w, p in legs) / sum(w for w, _ in legs)
    nearest = min(p for _, p in legs) if short else max(p for _, p in legs)
    dist = (nearest - price) / price * 100 if price else None
    mid, opp = (row["range_high"] + row["range_low"]) / 2, row["range_low"] if short else row["range_high"]
    first = {"title": f"Wacht tot de koers terugkomt in {FAMILY_WORD[row['family']]} bij {fmt(nearest)}", "sub": "te gaan",
             "dist": f"{dist:+.2f}%" if dist is not None else "-", "dist_key": DIST_KEYS["vandaag"], "state": "now",
             "approach": trade_plan.approach_pct(None if dist is None else abs(dist))}
    if coin:
        first["live_coin"], first["live_level"], first["live_mode"] = coin, nearest, "lp"
    orders = " en ".join(f"{w * 100:.0f}% op {fmt(p)}" for w, p in legs) if len(legs) > 1 else fmt(legs[0][1])
    return [first,
            {"title": f"Zet een limietorder op {orders}", "state": "next"},
            {"title": f"Stop {fmt(row['stop'])}, doel kies je zelf", "state": "next",
             "sub": f"De stop ligt {abs(planned - row['stop']) / planned * 100:.2f}% van je instap, voorbij de zone. Referentie: Midden {fmt(mid)} · Overkant {fmt(opp)}."}]


def range_chips(legs, stop: float, mid: float, opp: float) -> list[dict]:
    names = ["Limiet"] if len(legs) == 1 else [f"Limiet {w * 100:.0f}%" for w, _ in legs]
    items = [(f"limit{k}", n, p) for k, (n, (_, p)) in enumerate(zip(names, legs), 1)]
    items += [("stop", "Stop", stop), ("mid", "Midden (ref.)", mid), ("opp", "Overkant (ref.)", opp)]
    return [{"key": key, "label": label, "value": value, "text": fmt(value)} for key, label, value in items]
```

`app/today.py`: `SIGNAL_LABELS["range_sweep"] = "Range sweep gevuld"`; `open_chances` krijgt `range_cards: list[dict] = ()` als laatste parameter en vóór de signalen:

```python
    for c in range_cards:
        d = c.get("distance_pct")
        items.append({"kind": "range_sweep", "coin": c["coin"], "direction": c["direction"], "soort": "Zone-retest" if c.get("family") == "zone" else "Range sweep",
                      "state": "Wacht op de limiet", "dist": abs(d) if d is not None else None, "dist_text": f"{d:+.2f}%" if d is not None else "",
                      "url": f"/structuur#range-sweep-{c['id']}", "card": c})
```

Werk de docstring bij (range sweep-kaarten tellen mee zolang ze wachten en niet verlopen zijn). En:

```python
def stop_headline(row: dict, lab: Optional[dict], cost_pct: float) -> dict:
    """De kop van een range sweep-kaart: stopafstand en wat de stop kost in R, allebei gemeten uit het plan; de doelkans komt uit het lab en heet op
    de kaart 'historische kans (lab)'."""
    legs = json.loads(row["legs"])
    planned = sum(w * p for w, p in legs) / sum(w for w, _ in legs)
    pct = abs(planned - row["stop"]) / planned * 100
    return {"label": "Stop", "value": f"{pct:.2f}".replace(".", ","), "unit": "%", "delta": f"kosten {cost_pct / pct:.2f}R".replace(".", ","),
            "doelkans": (lab or {}).get("doelkans") or []}
```

`web/main.py`: `_range_sweep_cards(user)` leest `repo.list_range_sweep_setups(("waiting",))` (leeg als `range_sweep` in `rule_live.CEO_ONLY_TYPES` staat en de kijker geen CEO is), haalt koersen met `_cached_prices`, laat verlopen setups (`expires_at` voorbij) en setups waarvan de koers al voorbij de stop staat weg, en bouwt per rij `steps`, `chips` (`range_chips` met midden en overkant), `chart` (`Markup(setup_chart.range_sweep_svg(plan["candles"], rij met pd.Timestamp-velden, row["stop"], price, plan["zones"]))`), `headline` (`today.stop_headline(row, lab_json van range_sweep_stop, config.TRACK_RECORD_COST_PCT)`), `checks` (uit `row["reason"]` terug naar `(label, ok)`), `liq` en `distance_pct`. `_range_watch_rows(user)` leest `repo.list_range_watches(("actief",))` met per rij de afstand tot beide randen in %. Geef `range_cards=await _range_sweep_cards(user)` door in `_open_chances`; geef `range_sweep_cards` en `range_watches` mee aan `/structuur`, `/smc` en `/vandaag`.

`web/templates/_macros.html`, naast `setup_card`:

```jinja
{# Een range sweep of zone-retest: de stop is het product, het doel kies je zelf. De kop is de stopafstand (gemeten), de doelkans komt uit het lab (historisch). #}
{% macro range_sweep_card(c) %}
<article class="setup-card{% if c.grade == 'C' %} is-weak{% endif %}" id="range-sweep-{{ c.id }}">
  <header class="setup-head">
    {{ coin_avatar(c.coin, 36, "setup-av") }}
    <div class="setup-id">
      <p class="setup-title"><a class="radar-coin" href="/coins/{{ c.coin }}">{{ c.coin }}</a><span class="radar-dir radar-dir-{{ c.direction }}">{{ c.direction }}</span></p>
      <p class="setup-sub"><span class="setup-grade setup-grade-{{ c.grade|lower }}">{{ c.grade | grade_word }}</span><span class="muted">{{ "Zone-retest" if c.family == "zone" else "Range sweep" }} {{ c.range_tf|replace('h', 'u') }} · ongetest</span>{{ proof_tag("range_sweep", "rs" ~ c.id) }}</p>
    </div>
    <span class="muted setup-age">{{ c.created_at | age }}</span>
  </header>
  {{ headline(c.headline.label, c.headline.value, c.headline.unit, delta=c.headline.delta, explain="Afstand van je gemiddelde instap tot de stop, en wat een rondreis aan kosten is in R. Allebei gemeten uit dit plan.") }}
  {{ c.chart }}
  {{ steps_list(c.steps) }}
  {{ level_chips(c.coin, c.chips, "/structuur#range-sweep-" ~ c.id) }}
  {% if c.headline.doelkans %}
  <table class="rs-doelkans" aria-label="Historische kans uit het lab, geen belofte">
    <caption class="muted">Historische kans (lab, {{ c.headline.doelkans[0].n }} trades): haalde de koers dit vóór de stop?</caption>
    <tr>{% for d in c.headline.doelkans %}<th>+{{ d.r }}R</th>{% endfor %}</tr>
    <tr>{% for d in c.headline.doelkans %}<td>{{ d.p_text }}</td>{% endfor %}</tr>
  </table>
  {% endif %}
  {{ share_button(c.coin, c.direction, c.steps) }}
  <details class="setup-why">
    <summary>Waarom <span class="muted">score {{ "%.0f"|format(c.score) }} van 100</span></summary>
    <ul class="setup-checks" aria-label="Wat er klopt en wat niet">{% for label, ok in c.checks %}<li class="{{ 'is-ok' if ok else 'is-no' }}"><span aria-hidden="true">{{ "✓" if ok else "✗" }}</span> {{ label }}</li>{% endfor %}
      <li class="{{ 'is-ok' if c.liq.ok else 'is-no' }}"><span aria-hidden="true">{{ "✓" if c.liq.ok else "✗" }}</span> Liquidaties bij de prik <span class="muted">(niet getoetst, geen historie)</span></li></ul>
  </details>
</article>
{% endmacro %}
```

Zes kolommen passen niet op 390 px met de marges erbij: geef `.rs-doelkans` `font-size` en `padding` zo dat zes kolommen passen, of laat de tabel binnen de kaart horizontaal scrollen (`overflow-x: auto` op een omhullende `div`), nooit de pagina. `structuur.html`: tabs "Range sweep" (count = aantal kaarten) en "Ranges" (`#tab-ranges`, paneel `id="ranges"`) met per actieve range een `macros.market_row` (coin, timeframe, "Boven X · Onder Y", afstand tot de dichtstbijzijnde rand). Lege staat: `macros.empty_state("Geen setup klaar", "De motor wacht op een terugkeer in een zone aan de rand van een range, of een sweep met een slot terug binnen. In Ranges zie je waar dat kan komen.", "Bekijk de Ranges", "#tab-ranges")`. `vandaag.html` toont een kaart uit de open kansen met `kind == "range_sweep"` via `macros.range_sweep_card(i.card)`. `smc.html` (Radar) toont ze in de wachtlijst via dezelfde macro. `style.css`: `.rs-doelkans` met de tabelstijl van Bewijs, bestaande tokens, geen nieuwe achtergrondlaag.

- [ ] **Step 4: Run en zie slagen**

Run: `python3 -m unittest tests.test_chance_steps tests.test_today tests.test_web_layout -v && SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .`
Expected: PASS.

- [ ] **Step 5: Playwright op 390 px**

Start `DATABASE_PATH=/tmp/scratch_rs.db uvicorn web.main:app --port 8011` met een scratch-database met een CEO, een leerling, één wachtende zone-retest (ARB-achtige getallen uit `handtrades.csv`, plan met 80 candles van de fixture en twee zones), twee `range_watches` en een `range_sweep_stop`-labrij met een doelkans van zes rijen. Een wegwerpscript in de scratchpad met Playwright (Chromium, viewport 390x844):
1. CEO opent `/structuur#range-sweep-1`: kaart zichtbaar; SVG heeft `.sc-range`, `.sc-zone`, `.sc-limit`, `.sc-stop`; kop "Stop" met "%"; doelkans-tabel met "Historische kans (lab"; `document.documentElement.scrollWidth <= 390`; tik op chip "Stop" zet de waarde op het klembord (`navigator.clipboard.readText()` met toestemming); bel naast "Limiet" zet `aria-pressed="true"`;
2. tab "Ranges" toont twee rijen;
3. `/vandaag` telt de kans in "Kansen open" (zelfde getal als het aantal items);
4. leerling ziet op `/structuur` en `/vandaag` geen `range-sweep-`;
5. schermafdruk per pagina in de scratchpad, ook met `prefers-color-scheme: dark`.

- [ ] **Step 6: Commit**

```bash
git add app/chance_steps.py app/today.py web/main.py web/templates/_macros.html web/templates/structuur.html web/templates/smc.html web/templates/vandaag.html web/static/style.css tests/test_chance_steps.py tests/test_today.py tests/test_web_layout.py
git commit -m "feat: range sweep-kaart met stop als kop, ranges-tab en open kansen"
```

---

### Task 17: Bewijs, kanspagina en documentatie

**Files:**
- Modify: `app/track_record.py`, `app/kans_view.py`, `web/main.py` (`/bewijs`, `/kans/{id}`), `web/templates/bewijs.html`, `web/templates/kans.html`, `CLAUDE.md`
- Test: `tests/test_track_record.py`, `tests/test_kans_view.py`, `tests/test_web_layout.py`

**Interfaces:**
- Consumes: `repo.list_range_sweep_trades`, labrijen `range_sweep_stop` en `range_sweep`.
- Produces: `track_record.stop_quality_live(trades) -> dict` (`n, open, stop_hit, reach {1..6}, median_stop_pct, enough, tight_known`), `track_record.stop_quality_rows(lab, live) -> list[dict]` (`label, lab_text, live_text`), `track_record.drift_warning(lab, live) -> Optional[str]`, `kans_view.reference_outcome(signal, r_value) -> Optional[dict]`.

- [ ] **Step 1: Schrijf de falende tests**

In `tests/test_track_record.py`:

```python
class StopQualityLiveTest(unittest.TestCase):
    def t(self, stop=False, r1=False, closed=True):
        return {"entry": 100.0, "stop": 102.5, "stop_hit_at": "x" if stop else None, "closed_at": "x" if closed else None,
                **{f"reached_{k}r_at": ("x" if (k == 1 and r1) else None) for k in range(1, 7)}}

    def test_counts_only_finished_trades(self):
        out = track_record.stop_quality_live([self.t(stop=True), self.t(r1=True), self.t(closed=False)])
        self.assertEqual((out["n"], out["open"]), (2, 1))
        self.assertAlmostEqual(out["stop_hit"], 0.5)
        self.assertAlmostEqual(out["reach"][1], 0.5)
        self.assertFalse(out["enough"])

    def test_rows_show_lab_beside_live(self):
        lab = {"summary": {"n": 412, "stop_hit": {"p": 0.55}, "reach": {str(k): {"p": 0.5 / k} for k in range(1, 7)}, "median_stop_pct": 2.4, "median_cost_r": 0.05, "tight_rate": 0.18}}
        rows = track_record.stop_quality_rows(lab, track_record.stop_quality_live([]))
        self.assertEqual(rows[0], {"label": "Stop geraakt", "lab_text": "55%", "live_text": "-"})
        self.assertEqual(rows[6]["label"], "+6R vóór de stop")

    def test_drift_warning_after_fifty(self):
        lab = {"summary": {"reach": {"1": {"p": 0.48, "ci": [0.42, 0.54]}}}}
        self.assertIn("wijkt af van het lab", track_record.drift_warning(lab, {"n": 60, "reach": {1: 0.30}}))
        self.assertIsNone(track_record.drift_warning(lab, {"n": 20, "reach": {1: 0.30}}))
```

In `tests/test_kans_view.py`:

```python
    def test_reference_outcome_names_the_reference(self):
        out = kans_view.reference_outcome({"trade_type": "range_sweep", "auto_outcome": "take_profit"}, 1.4)
        self.assertIn("Referentie-uitgang", out["text"])
        self.assertIn("+1,40R", out["text"])
        self.assertIn("Jouw trade beslis je zelf.", out["text"])
        self.assertIsNone(kans_view.reference_outcome({"trade_type": "range_sweep", "auto_outcome": None}, None))
```

In `tests/test_web_layout.py`: `/bewijs` als CEO met een `range_sweep_stop`-labrij toont "Range sweep, stopkwaliteit", "Stop geraakt", "+1R vóór de stop" en "R gemeten bij de referentie-uitgang"; als leerling zonder `RANGE_SWEEP_PUBLIC` niets van de range sweep.

- [ ] **Step 2: Run en zie falen**

Run: `python3 -m unittest tests.test_track_record tests.test_kans_view tests.test_web_layout -v`
Expected: FAIL.

- [ ] **Step 3: Implementeer**

`app/track_record.py`:

```python
RANGE_R_LEVELS = (1, 2, 3, 4, 5, 6)


def stop_quality_live(trades: list[dict]) -> dict:
    """Stopkwaliteit van de live range sweep-trades, zelfde maten als het lab (stopquality.summarize) behalve 'te krap': dat vraagt 48 uur na de stop
    en meet de motor niet. Een trade telt pas als hij klaar is (stop geraakt of 7 dagen voorbij); lopende staan als aantal ernaast."""
    done = [t for t in trades if t.get("closed_at") or t.get("stop_hit_at")]
    n = len(done)
    share = lambda key: sum(1 for t in done if t.get(key)) / n if n else None
    pcts = sorted(abs(t["entry"] - t["stop"]) / t["entry"] * 100 for t in done)
    return {"n": n, "open": len(trades) - n, "stop_hit": share("stop_hit_at"), "reach": {k: share(f"reached_{k}r_at") for k in RANGE_R_LEVELS},
            "median_stop_pct": pcts[n // 2] if n else None, "enough": n >= MIN_FOR_STATUS, "tight_known": False}


def _p(x) -> str:
    return "-" if x is None else f"{x * 100:.0f}%"


def stop_quality_rows(lab: Optional[dict], live: dict) -> list[dict]:
    s = (lab or {}).get("summary") or {}
    reach = s.get("reach") or {}
    lab_reach = lambda k: (reach.get(str(k)) or reach.get(k) or {}).get("p")
    rows = [("Stop geraakt", (s.get("stop_hit") or {}).get("p"), live["stop_hit"])]
    rows += [(f"+{k}R vóór de stop", lab_reach(k), live["reach"][k]) for k in RANGE_R_LEVELS]
    out = [{"label": label, "lab_text": _p(a), "live_text": _p(b) if live["n"] else "-"} for label, a, b in rows]
    out.append({"label": "Stopafstand (mediaan)", "lab_text": f"{s['median_stop_pct']:.2f}%" if s.get("median_stop_pct") else "-",
                "live_text": f"{live['median_stop_pct']:.2f}%" if live.get("median_stop_pct") else "-"})
    out.append({"label": "Kosten in R (mediaan, 0,12%)", "lab_text": f"{s['median_cost_r']:.2f}R" if s.get("median_cost_r") else "-", "live_text": "-"})
    out.append({"label": "Te krappe stops", "lab_text": _p(s.get("tight_rate")), "live_text": "niet gemeten"})
    return out


DRIFT_MIN_LIVE = 50


def drift_warning(lab: Optional[dict], live: dict) -> Optional[str]:
    """Stopcriterium S5: na DRIFT_MIN_LIVE vullingen moet de live kans op +1R vóór de stop binnen het 95%-interval van het lab liggen."""
    reach = ((lab or {}).get("summary") or {}).get("reach") or {}
    one = reach.get("1") or reach.get(1)
    if not one or live.get("n", 0) < DRIFT_MIN_LIVE or live["reach"].get(1) is None:
        return None
    lo, hi = one["ci"]
    if lo <= live["reach"][1] <= hi:
        return None
    return f"Live wijkt af van het lab: +1R vóór de stop {live['reach'][1] * 100:.0f}% tegen {lo * 100:.0f} tot {hi * 100:.0f}% in het lab."
```

`app/kans_view.py`:

```python
def reference_outcome(signal: dict, r_value: Optional[float]) -> Optional[dict]:
    """Een range sweep heeft geen doel; de R op Bewijs komt van een referentie-uitgang. Dat moet op de kans staan, anders lijkt +1,4R jouw resultaat."""
    if signal.get("auto_outcome") not in ("take_profit", "stop_loss") or r_value is None:
        return None
    r_text = f"{r_value:+.2f}".replace(".", ",")
    return {"r": r_value, "text": f"Referentie-uitgang (meelopende stop 3 ATR op 1u): {r_text}R. Jouw trade beslis je zelf."}
```

`web/main.py`:
- `/kans/{id}`: voor `trade_type == "range_sweep"` `kans_view.reference_outcome` in plaats van `trailing_outcome`, en de tijdlijn uit `range_sweep_trades` (gevuld, +1R tot +6R, stop geraakt, meting klaar).
- `/bewijs`: voeg `"range_sweep"` toe aan de set types voor `track_record.visible_rule_types(..., rule_live.CEO_ONLY_TYPES)`; als hij zichtbaar is, geef mee: `range_sweep = {"rows": stop_quality_rows(lab_stop, live), "live": live, "drift": drift_warning(lab_stop, live), "status": rule_status(lab_edge, live_net_r(rows, "range_sweep", cost)), "variant": lab_stop["lab_json"]["variant"]}` met `lab_stop = repo.get_rule_lab("range_sweep_stop")` (lab_json geparst) en `lab_edge = repo.get_rule_lab("range_sweep")`, en `live = stop_quality_live(repo.list_range_sweep_trades(1000))`.

`web/templates/bewijs.html`, onder de regelstatussen:

```jinja
{% if range_sweep %}
<section class="card" id="range-sweep">
  <h2>Range sweep, stopkwaliteit <span class="muted">ongetest</span></h2>
  <p class="muted">Geen vast doel: hier staat wat de stop deed. Lab: {{ range_sweep.variant }}. Live: {{ range_sweep.live.n }} afgerond, {{ range_sweep.live.open }} lopend{% if not range_sweep.live.enough %}, nog te weinig om te vergelijken{% endif %}.</p>
  {% if range_sweep.drift %}<p class="tone-neg">{{ range_sweep.drift }}</p>{% endif %}
  <div class="rs-scroll"><table class="rs-doelkans"><tr><th></th><th>Lab</th><th>Live</th></tr>
    {% for r in range_sweep.rows %}<tr><th>{{ r.label }}</th><td>{{ r.lab_text }}</td><td>{{ r.live_text }}</td></tr>{% endfor %}</table></div>
  <p class="muted">R gemeten bij de referentie-uitgang (meelopende stop 3 ATR op 1u), niet bij jouw eigen doel. Alleen afgeronde trades tellen; lopende en vervallen setups staan ernaast. Status: {{ range_sweep.status.status }}. {{ range_sweep.status.reason }}</p>
</section>
{% endif %}
```

`CLAUDE.md`: een alinea na "Lab en proefmotor", in dezelfde stijl:

```markdown
**Range sweep.** Onze lezing van de strategie van Cos867, vooraf vastgelegd in `docs/onderzoek/range-sweep/preregistratie.md` (bevroren na de keuring met het oog; daarna wijzigt geen constante, `tests/test_rangesweep_lab.py` toetst code tegen document; de vijf voorbeelden staan in `docs/onderzoek/range-sweep/`). Zuivere detector `app/replay/rangesweep.py`: range en aanbod-/vraagzones op 30m, 1u, 2u en 4u (30m en 2u samengevoegd uit 15m en 1u), twee families (zone-retest en sweep), stop voorbij de buitenkant van de zone. Setupscore 40/60 in `chance_checks.range_sweep_checks` (A/B/C, nooit een bewezen voorspeller), stopmeting zonder doel in `app/replay/stopquality.py` (doelkans 1R tot 6R), labfamilie `app/replay/rangesweep_lab.py` via `scripts/strategy_lab.py --familie rangesweep --kosten 0.12 --hervat MAP` (15 varianten, 30 toetsen, register 64, horde t ≥ 3,4). De kop is de stopkwaliteit (`rule_status` `range_sweep_stop`), de strenge toets staat ernaast (`range_sweep`). Live: `app/range_watch.py` (eigen budget, stil) en `app/range_sweep_live.py` (`trade_type` 'range_sweep', geen `take_profit`, CEO-only via `rule_live.CEO_ONLY_TYPES` tot `RANGE_SWEEP_PUBLIC`, `chain_it=False`, R op Bewijs bij de referentie-uitgang en zo gelabeld). Liquidaties hebben geen historie: alleen live als ✓/✗ buiten de score. Misser-controle: `scripts/misser_check.py --motor rangesweep`.
```

- [ ] **Step 4: Run en zie slagen**

Run: `python3 -m unittest tests.test_track_record tests.test_kans_view tests.test_web_layout -v && SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t .`
Expected: PASS.

- [ ] **Step 5: Playwright op 390 px**

Met de scratch-database van taak 16 plus twee afgeronde `range_sweep_trades` en hun signalen: CEO opent `/bewijs#range-sweep` (tabel met Lab en Live, "R gemeten bij de referentie-uitgang", geen horizontale paginascroll) en `/kans/<id>` ("Referentie-uitgang", "Jouw trade beslis je zelf"); leerling opent `/bewijs` en ziet geen "Range sweep". Schermafdrukken in de scratchpad, licht en donker.

- [ ] **Step 6: Commit**

```bash
git add app/track_record.py app/kans_view.py web/main.py web/templates/bewijs.html web/templates/kans.html CLAUDE.md tests/test_track_record.py tests/test_kans_view.py tests/test_web_layout.py
git commit -m "feat: stopkwaliteit van de range sweep op Bewijs en de kanspagina"
```

---

## Risico's en eerlijke verwachting

- **Eerdere toetsen waren negatief.** Sweeps van dag- en weekniveaus en rejecties verloren in ons lab 0,06 tot 0,12R per trade na kosten (onderzoeksrapport 2a en 4); de mechanische breuk-en-terugkeer -0,16R. Grote munten tonen eerder momentum dan omkering (2c). Een retest van een zone tegen de beweging in is een omkering.
- **Wat hier anders is.** Een echte range met aanrakingen op beide randen; zones als vakken in plaats van lijnen; een HTF-filter; een limiet in de zone in plaats van een instap op het slot; en vooral een andere vraag: niet "is er winst bij doel X" maar "is de stop goed". De stops in de voorbeelden liggen op 1,6 tot 3,6% en kosten 0,03 tot 0,08R, tegen 0,15R en meer bij de oude toetsen. Dat maakt de kosten geen doodsoorzaak meer; of er een voordeel overblijft is daarmee niet gezegd.
- **Kans op een positief netto resultaat (eigen schatting).** Dat de strenge toets slaagt (t ≥ 3,4 na kosten): ongeveer **5%**. Dat de netto R bij de referentie-uitgang als puntschatting boven nul ligt voor de gekozen variant: ongeveer **25%**. Dat minstens één van de 30 toetsen slaagt op stopkwaliteit: ongeveer **30%**. Reden: alle eerdere omkeerfamilies verloren, de filters hier zijn plausibel maar onbewezen, en bij 30 toetsen haalt ook een nul-effect vaak één keer een mooie uitslag.
- **Productwaarde zonder bewezen voordeel.** Een setup met een stop die zelden te krap is en weinig kost kan nuttig zijn als beslishulp. Dat mag zo heten, nooit "bewezen" of "winnaar". De kaart zegt "ongetest", de doelkans heet historisch.
- **Overfitten op voorbeelden.** De voorbeelden zijn achteraf gekozen en recent; vier van de vijf liepen of lopen gunstig. Daarom kijken we in poort 0 alleen of de detector ze ziet, hooguit twee definitierondes vóór het bevriezen, en geen coin erbij omdat hij in een voorbeeld stond.
- **Onze zone is niet zijn indicator.** De vakken op de screenshots komen van een TradingView-indicator die we niet kennen. Onze zone is een eigen, vaste definitie; poort 0b laat zien hoe ver ze uit elkaar liggen.
- **Data.** Liquidaties: geen historie, dus die helft van "Liquidation" is in het lab niet te toetsen. OI-historie begint later dan de candles. Spot-candles tegen perp-grafieken: kleine verschillen.
- **Effectieve steekproef.** Met ongeveer 156 weken is ± 8 procentpunt op een kans het best haalbare; kleine verschillen tussen varianten of graden zijn niet te zien.

## Open vragen voor de gebruiker

1. Kloppen de datums (AAVE 15-10 23:42, de andere vier 16-10) en de afgelezen prijzen in `handtrades.csv`? Wanneer ging de eerdere APT-long op 0,7472 in, en wanneer de WLD-long?
2. Welke TradingView-indicator tekent de Bearish/Bullish-vakken (naam en instellingen)? Dan vergelijken we onze zones er preciezer mee.
3. Range-watch: "gevonden" alleen voor 2u- en 4u-ranges, "koers bij de rand" voor alle timeframes, maximaal 3 stille pushes per dag. Akkoord?
4. Een limiet die binnen 24 uur niet vult vervalt. Akkoord, of een andere termijn (dan vóór het bevriezen vastleggen)?
5. Kun je nog minstens 5 voorbeelden sturen, liefst ook verliezers en trades zonder sweep, met tijd op de minuut?

## Self-review

- Besluiten 1 tot 7 en de voorbeelden: score 40/60 (taak 6), split als extra variant (taak 11), sweep plus liquidatie met beperking (taken 5, 11, 15), zones als vakken en zone-retest (taken 4, 5), stop voorbij de buitenkant van de zone met wick als variant (taak 5), timeframes 30m, 1u, 2u en 4u (taken 4, 11), doelkans 1R tot 6R (taken 9, 10, 16, 17), coinselectie (sectie Coins), VPS-commando's en hervatten (taak 12), seed-CSV met datums te bevestigen (taak 1), voorbeelden eerst en met het oog (taken 7, 8), melding, tekening en range-watch (taken 8, 14, 15, 16), poorten tussen fasen.
- Namen die over taken lopen staan elk in één taak gedefinieerd: `build_frames`, `resample`, `range_series`, `active_for`, `find_zones`, `zone_active`, `retests_before`, `find_setups`, `raw_stops`, `final_stop`, `TESTED_STOPS`, `MIN_STOP_PCT` (taak 5), `simulate_fills`, `measure`, `atr_on_15m` (taak 9), `summarize`, `accept`, `doelkans_table`, `placebo_rows` (taak 10), `RSVariant`, `VARIANTS`, `run_coin`, `judge`, `select_live` (taak 11), `range_sweep_checks`, `weighted_finish`, `grade_of` (taak 6), `live_variant`, `follow_step` (taak 15), `range_sweep_steps`, `range_chips`, `stop_headline` (taak 16), `stop_quality_live`, `stop_quality_rows`, `drift_warning`, `reference_outcome` (taak 17).
- Invulvakken voor mensen (de drie puntjes onder "Oordeel", de "______" in de galerij) zijn geen ontbrekende plandelen.
