# Range sweep: pre-registratie

Status: concept (definities mogen nog wijzigen op grond van de voorbeelden, niet op grond van resultaten)
Bevroren op: (datum en commit-hash, in te vullen bij poort 1)

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

**Range (op timeframe T).** Op het slot van candle i: zwaaipunten met `trendlab._pivot_flags` (n = 3, strikt links, gelijk of lager rechts; bekend op p + 3) in de laatste 120 candles (30m, 1u) of 90 (2u, 4u). In de praktijk is het venster candle i-120 tot en met i-3 (118 bruikbare candles, 88 bij 2u en 4u), omdat een zwaaipunt pas op p + 3 bekend is. De grootste groep zwaaipunt-hogen binnen 0,5 ATR(T) is de bovenrand, idem voor de lagen; bij gelijkstand de groep met het laatste punt. Minstens 3 per rand. Bovenrand = hoogste hoog van de groep, onderrand = laagste laag. Breedte 3 tot 15 ATR(T). Geen slot meer dan 0,25 ATR(T) buiten de range sinds het eerste zwaaipunt van de range.

**Zone (aanbod of vraag, op timeframe T).** Een aanbodzone ("bear") ontstaat als een slot op candle m minstens 1,0 ATR(T) onder het laag van de laatste groene candle k komt, met k hooguit 5 candles vóór m. Zone = laag tot hoog van candle k; bekend op m. Vraagzone ("bull") gespiegeld (laatste rode candle, slot minstens 1,0 ATR boven zijn hoog). Een nieuwe zone die voor meer dan de helft overlapt met een nog actieve zone van dezelfde soort telt niet (de oudere blijft). Een zone is actief tot een slot voorbij de buitenkant (aanbod: boven het hoog) of tot 200 candles na m. Buitenkant = hoog bij aanbod, laag bij vraag; binnenkant = de andere kant.

**Familie zone-retest.** Een actieve aanbodzone in of boven het bovenste kwart van een actieve range (binnenkant ≥ bovenrand − 0,25 maal de breedte), en de koers nadert van onderen: slot hooguit 1,0 ATR(T) onder de binnenkant en het hoog nog onder de binnenkant. Short-limiet op de binnenkant. Vraagzone onderaan gespiegeld voor long. Eén setup per zone, bij de eerste nadering waarop alle voorwaarden kloppen. Een nadering zonder CHoCH of zonder geldige limiet sluit de zone niet af: pas als de koers de zone verlaten heeft (slot: niet meer nabij, choch15: het hoog onder de binnenkant) telt de volgende aanraking als een nieuwe nadering, nooit twee keer binnen hetzelfde bezoek. Met `choch15` wacht de order tot de koers de zone raakte en daarna een 15m-candle sluit voorbij het laatste 15m-zwaaipunt (n = 2) van vóór het uiterste van die aanraking, binnen 24 15m-candles.

**Familie sweep.** Een candle op de triggerframe (30m voor T = 30m, anders 1u) prikt minstens 0,1 ATR voorbij een rand van de range die bekend was bij het openen, en binnen 6 triggercandles sluit er een weer binnen; komt het uiterste meer dan 1,5 ATR(T) voorbij de rand, dan is het een uitbraak. Eén sweep per range per kant, en dezelfde kant op dezelfde coin telt 24 triggercandles niet. Ook een geweigerde prik (uitbraak, of geen terugkeer binnen 6 candles) gebruikt de kant van die range op en start de 24 candles wachttijd: een tweede poging direct erna is dezelfde beweging. Het order block is de laatste groene (short) of rode (long) 15m-candle op of vóór de 15m-candle met het uiterste, hooguit 8 terug; geen gevonden: de uiterste candle zelf. Limiet = midden van het order block. Met `choch15` wacht de order op een 15m-slot voorbij het laatste 15m-zwaaipunt van vóór het uiterste, binnen 24 15m-candles.

**Limiet die niet geldig is.** Een limiet aan de verkeerde kant van de koers bij het plaatsen (short: op of onder het laatste slot) vervalt; geen geldige limiet, geen setup.

**Stops.** `zone_025` en `zone_05`: buitenkant van de zone plus 0,25 of 0,5 maal de ATR (van T bij zone-retest, van de triggerframe bij sweep). `wick_025`: uiterste van de sweep plus 0,25 ATR (alleen sweep). `zone_0`: buitenkant zonder buffer, alleen ter vergelijking. Bij de split (`RZ_2H_SPLIT`) telt als buitenkant de verste van de zonerand en de beenprijzen (het randbeen ligt op de rand van de range, vaak voorbij de zone), zodat elk been aan de winstkant van de definitieve stop ligt. Daarna `smc_eval.floor_stop(direction, geplande instap, stop, min_pct=0.4)`.

**Vulling en verval (op 15m).** Short-limiet vult als het hoog de limiet raakt, tegen de limietprijs; long gespiegeld. De order staat 96 15m-candles (24 uur). Vervalt eerder als een candle al voorbij de stop opent ("stop voor vulling") of als de koers het midden van de range raakt ("weggelopen").

**Meting na de vulling (zonder doel).** Tot de stop of 672 15m-candles (7 dagen). In de vulcandle telt alleen het nadeel (bij de split: tot en met de kandel van de laatste vulling). Een candle die stop en een R-niveau raakt telt als stop. Een gat door de stop vult op de open. R-eenheid: het risico dat echt genomen is (gewogen instap tot de stop).

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

### Aanvullende besluiten van 2026-10-16
- **Range-watch.** Een push "gevonden" alleen voor ranges op 2u en 4u; "bij de rand" voor alle timeframes; hooguit 3 stille pushes per gebruiker per dag (pauze geldt).
- **Verval.** Een niet gevulde limiet vervalt na 24 uur (96 15m-candles, `stopquality.TTL_15M`).
- **Datums.** De datums van de vijf voorbeelden komen van de gebruiker en staan op "te bevestigen" (AAVE 2026-10-15 23:42 CEST, de andere vier 2026-10-16).
- **Poort 1 gehouden, kaarten tot het plaatsmoment (2026-10-18, vóór de eerste labrun).** De gebruiker beoordeelde de 30 kaarten: 23 klopt, 7 klopt niet (77%, norm 80%). De kaarten toonden ook de 24 uur na het plaatsen, waardoor een verliezende uitkomst zichtbaar was bij de bijna alle kaarten die niet klopten. Een oordeel over de tekening hoort niet te weten hoe het afliep. De galerij toont daarom de candles tot en met het plaatsmoment (`after_hours=0`) en de gebruiker beoordeelt opnieuw. Dit telt niet als reparatieronde van de detector: er is niets aan de detector veranderd. De eerdere poort-1-uitkomst (23 van 30) wordt niet gebruikt. S1 blijft: minstens 24 van 30.
- **Zonedetector.** De naam van de TradingView-indicator is onbekend; we gebruiken onze eigen zonedetector zoals hierboven gedefinieerd.
- **Stop bij de split (2026-10-16, vóór de eerste labrun).** De stop gebruikte alleen de buitenkant van de zone, maar het randbeen (40%) ligt op de rand van de range en kon voorbij die stop liggen (58 van 897 stopberekeningen in een controlerun): dat been kon nooit vullen. De buitenkant is nu de verste van zonerand en beenprijzen. Reden: een been voorbij de stop is geen limietorder met een stop erachter maar een fout in de definitie.
- **Eerste nadering waarop alles klopt (2026-10-16, vóór de eerste labrun).** Bij zone-retest eindigde een ontbrekende CHoCH of een ongeldige limiet de zone (`break`), terwijl een ontbrekende range, een zone niet aan de rand en het HTF-filter doorgingen (`continue`). In een controlerun op 1u stierven 13 van 22 choch-zones bij de eerste aanraking. Nu `continue`, met overslaan tot de koers de zone verlaten heeft. Reden: de tekst zegt "eerste nadering waarop alle voorwaarden kloppen", en de CHoCH is een voorwaarde.
- **Beweging tot de bevestiging (2026-10-16, vóór de eerste labrun).** De score-tabel zegt "grootste slot weg van de zone tot de bevestiging", maar de code mat tot het ontstaan van de zone. Nu gemeten tot en met de candle van de nadering (slot) of de 15m-candle van de CHoCH (choch15), in de ATR van het ontstaan van de zone. Alleen een scorekenmerk, geen regel van de motor.
- **Geweigerde prik (2026-10-16).** Een geweigerde prik gebruikt de kant van de range op en start de wachttijd. Dit was al het gedrag van de code; nu staat het als regel in de sweepdefinitie.
- **Constanten uit de tekst.** `RANGE_LOOKBACK` (120, 120, 90, 90), `AGE_MIN` (48, 48, 36, 36) en `STOP_BUFFER` (0, 0,25, 0,5 maal de ATR; wick 0,25) komen uit de tekst hierboven en staan niet als regel in het constantenblok (het zijn tabellen); een test toetst ze tegen de code.
- **Opslaan alleen voor het volledige protocol (2026-10-17, vóór de eerste labrun).** `--opslaan` weigert tenzij `--coins` precies de 20 van `trendlab.LAB_COINS` zijn, `--jaren 3` (`rangesweep_lab.LAB_YEARS`) en `--alleen-volledig`; de tussenmap legt coins, jaren en alleen-volledig vast. Reden: een PASS uit een deelverzameling of een kortere periode mag nooit de database in; de horde van t ≥ 3,4 geldt voor dit protocol.
- **Meting bij de split (2026-10-17, vóór de eerste labrun).** `measure` telde bij `RZ_2H_SPLIT` de gunstige beweging (+1R tot +6R, MFE, referentie-uitgangen) vanaf de eerste vulling met de gewogen instap van alle benen, ook in kandels waarin het tweede been nog niet gevuld was. Die beweging trof de volledige positie nooit. Nu telt een gunstige beweging pas vanaf de kandel na de laatste vulling (de vulkandel van het laatste been telt alleen het nadeel, zoals bij één been); nadeel en stop gelden vanaf de eerste vulling. Bij één been is er niets veranderd. Reden: dezelfde regel als "in de vulcandle telt alleen het nadeel", toegepast op de hele positie.
- **Regels die alleen in code stonden (2026-10-17, vóór de eerste labrun).** Dit legt vast wat de code al deed; er verandert niets aan de uitkomst.
  - **Keuze voor de proef** (`rangesweep_lab.select_live`). Alleen toetsen die geslaagd zijn op stopkwaliteit komen in aanmerking. Daaruit wint achtereenvolgens: de meeste vullingen, de laagste mediane kosten in R, de bredere stop (eerst de grootste buffer van de stop, dan de grootste mediane stopafstand in %), dan de naam van de variant en tot slot de naam van de stop (beide alfabetisch). Zo is de keuze onafhankelijk van de volgorde van de uitvoer.
  - **Placebo.** Per echte gevulde trade 20 willekeurige instappen (`PLACEBO_DRAWS`), trekking met seed 7 (`PLACEBO_SEED`), per paar gemiddeld. Een placebo-instap is de sluitkoers van de triggercandle van het getrokken slot; de meting begint op de eerste 15m-candle erna.
  - **Aantal toetsen voor S2 en S3.** `KILL_TESTS` = 30; bij een andere hoeveelheid beslist `kill_check` niet.
- **Geen correctie voor meervoudig toetsen op stopkwaliteit (2026-10-17, vóór de eerste labrun).** De 30 toetsen op stopkwaliteit krijgen geen correctie voor meervoudig toetsen. Bij een eenzijdige ondergrens van 2,5% op het verschil met willekeurige instappen (eis 5) is de kans groot dat minstens één van de 30 die ene eis door toeval haalt (voor 30 onafhankelijke nulvarianten ruim 50%). De andere eisen (vullingen, kosten, stabiliteit, te krap) verkleinen die kans, maar rekenen we niet door. Een PASS is daarom een screening-resultaat dat vooruit bevestigd moet worden in de proef (poort 4); het rapport zegt dit naast de regel "N van 30".
- **Meer voorbeelden.** De gebruiker stuurt later 5 of meer voorbeelden. Dat blokkeert niets en telt mee voor S0 vanaf 10 voorbeelden.

## Constanten

Elke regel is `module.NAAM = waarde`; een test toetst dat ze gelijk zijn aan de constante in code.

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
rangesweep_lab.LAB_YEARS = 3
rangesweep_lab.PLACEBO_DRAWS = 20
rangesweep_lab.PLACEBO_SEED = 7
stopquality.KILL_TESTS = 30
```
