# Zone-sweep: pre-registratie (concept)

Status: concept. De definities mogen nog veranderen op grond van de voorbeelden, niet op grond van resultaten. Dit is een eigen traject, los van de bevroren range sweep (`docs/onderzoek/range-sweep/preregistratie.md`).

## Waarom

De gebruiker liet zeven voorbeelden zien uit één nacht (19 en 20 oktober 2026): ETH, ZEC, SUI, ARB en drie coins zonder naam. Telkens zakt de koers in een neerwaartse trend naar een vraagzone, prikt er onderdoor en herstelt snel. Gemeten beweging na de prik: +2,5% tot +10%, bij een stop van 1,4% tot 3,1% onder de wick. Geen van onze motoren ziet dit: de range sweep eist een range met drie aanrakingen, de Structuur-motor eist een gebroken lijn.

## Eerlijkheid vooraf

- De zeven voorbeelden zijn één gebeurtenis (een marktbrede bounce) en allemaal winnaars. Ze tonen dat het patroon bestaat, niet dat het een voordeel heeft.
- Het lab telt daarom per kalenderdag als cluster, niet per setup. De horde en de toetsen zijn dezelfde machinerie als de range sweep (`stopquality`, week-clusters, placebo, `t >= 3,4`).
- Geen doel. Wat wij meten is de stopkwaliteit: hoe vaak de stop geraakt wordt, hoe ver de koers vóór de stop kwam (MAE en MFE) en de kosten in R.

## Definities (concept)

**Zone.** Dezelfde vraagzone (aanbodzone bij short) als de range sweep: `rangesweep.find_zones`, actief tot een slot voorbij de buitenkant of 200 candles. Timeframes 1u, 2u en 4u.

**Prik.** Een triggercandle (1u) prikt minstens 0,1 ATR(T) onder de onderkant van een actieve vraagzone. Het uiterste (wick) is de lage prik. Komt het uiterste meer dan 2,5 ATR(T) onder de zone, dan is het een uitbraak en telt het niet.

**Herstel.** Binnen 6 triggercandles sluit een candle weer boven de onderkant van de zone. Zonder herstel in 6 candles is het geen setup, en dezelfde zone telt 24 triggercandles niet.

**Instap.** Limiet op de bovenkant van de zone (tweede variant: het midden van de zone), geplaatst na het herstel. Ligt die prijs boven het slot van de herstelcandle (long; bij short gespiegeld), dan is het slot zelf de limiet: de koers staat dan al in of onder de zone en de instap is meteen. Orders vervallen na 24 uur. Dezelfde regels voor vulling en verval als de range sweep.

**Stop.** Onder het uiterste van de prik plus 0,25 ATR of 0,5 ATR (twee stops per variant). Daarna `smc_eval.floor_stop` met ondergrens 0,4%.

**Richting.** Long bij een vraagzone. Short bij een aanbodzone gespiegeld (prik boven de bovenkant en herstel eronder).

**HTF-filter.** Twee varianten: met het 4u-trendfilter van de range sweep (`rangesweep.htf_ok`) en zonder. Voor een sweep tegen de trend in (long in een neerwaartse trend) is de vraag juist of het filter helpt of schaadt.

## Varianten

| Naam | Timeframe | Instap | HTF-filter |
|---|---|---|---|
| ZS_1H | 1u | bovenkant zone | met |
| ZS_2H | 2u | bovenkant zone | met |
| ZS_4H | 4u | bovenkant zone | met |
| ZS_1H_ZONDERHTF | 1u | bovenkant zone | zonder |
| ZS_2H_ZONDERHTF | 2u | bovenkant zone | zonder |
| ZS_4H_ZONDERHTF | 4u | bovenkant zone | zonder |
| ZS_2H_MIDDEN | 2u | midden van de zone | met |

7 varianten met 2 stops zijn 14 toetsen. De hordes voor meervoudig toetsen volgen die van de range sweep en worden bij het bevriezen vastgelegd.

## Poorten

1. Misser-controle op de voorbeelden. VERVALLEN, zie 'Aanvullende besluiten'.
2. Getekende setups: 30 willekeurige kaarten tot het plaatsmoment, minstens 80% klopt volgens de gebruiker (zoals poort 1 van de range sweep).
3. Daarna bevriezen en één volledige labrun (20 coins, 3 jaar, kosten 0,12%).
4. Pas bij een geslaagde labrun een proefmotor, eerst alleen voor de CEO.

## Wat de gebruiker nog moet leveren

- De namen van de drie coins zonder naam (prijzen rond 1,05, rond 58 en rond 0,12).
- Per voorbeeld de tijd van de prik en de instapprijs.
- Minstens vijf voorbeelden van andere dagen, waarvan minstens twee waar de koers doorzakte en de stop raakte.

## Aanvullende besluiten (2026-10-20, vóór de eerste labrun)

- **Poort 0a vervalt.** De misser-controle zag 2 van de 6 afleesbare voorbeelden (ETH en WLD, beide op 4u). De meting (`scripts/zone_probe.py`) liet zien dat de candles van de VPS en de grafieken van de gebruiker niet overeenkomen: de stop van ETH (2.308,59) en SUI (0,9203) lag onder het laagste punt in onze data (2.329 en 0,9372), en het plaatje dat ik als ARB las had geen coinnaam en een prijs die bij ARB niet past. Zonder tijd, beurs en instrument per voorbeeld is afstellen op deze zes zinloos. De gebruiker koos ervoor dat niet uit te zoeken. Beperking, ook voor Bewijs: de uitkomst zegt iets over de prikken die onze detector op onze candles vindt, niet over de trades van de gebruiker.
- **Afstelling vermeden.** Dat meerdere zones van de voorbeelden weken oud zijn (onze zones vervallen na 200 candles) en dat sommige zones pas na de prik ontstaan, staat in `zone_probe` en is geen reden om de zone-regels nu aan te passen: we stellen niet af op voorbeelden waarvan de data niet klopt.
- **Wel aangepast: de limiet (definitieronde 1).** Zie 'Instap' hierboven. Reden: een limiet boven de koers is een marktorder; de eerdere regel weigerde ZEC, OP en WLD (2u) om een fout in de regel, niet in de voorbeelden.

## Aanvullende besluiten (2026-10-27): live zonder labrun op verzoek van de gebruiker, ongetest

- **Poort 4 vervalt voor nu, op uitdrukkelijk verzoek van de gebruiker (CEO).** De proefmotor draait live vóór de labrun, met het label ongetest, op dezelfde manier als de range sweep met `RANGE_SWEEP_UNTESTED`: `app/zone_sweep_live.py`, aan met `ZONE_SWEEP_ENABLED` (standaard aan), voor iedereen met `ZONE_SWEEP_PUBLIC` (standaard aan; uit is alleen de CEO via `rule_live.CEO_ONLY_TYPES`).
- **Niets afgesteld, niets toegevoegd.** Live draaien alleen ZS_1H, ZS_2H en ZS_4H (limiet op de binnenrand van de zone, met HTF-filter) met de stop `wick_025` (`zonesweep.final_stop`), allemaal uit de tabel hierboven. Geen nieuwe varianten of drempels; de detector is dezelfde code als het lab, op alleen gesloten candles. Vulling en verval volgen de regels van het lab (`stopquality.simulate_fills`: 24 uur, weggelopen bij het midden van het referentiekader, open voorbij de stop).
- **Doel voor een bruikbare kaart, buiten de toets.** De pre-registratie meet stopkwaliteit en heeft geen doel. De kaart krijgt als doel de rand van de eerstvolgende tegenovergestelde actieve zone (de regel van de zone-radar, `zone_radar.target_for`) bij minstens 2R; anders heeft de kaart geen doel en kies je het zelf. Met een doel beslist `level_check` op doel en stop; zonder doel telt Bewijs de R bij de referentie-uitgang (meelopende stop 3 ATR op 1u), zoals bij de range sweep, en zo staat het ook op de kans.
- **Eerlijkheid.** Alles heet ongetest, de signalen gaan buiten de openbare keten (`chain_it=False`), Bewijs toont de zone-sweep als eigen rij en als "In proef" onder Regels. De live cijfers bewijzen niets; de labrun (`zs_*`, `zone_sweep_stop`, `zone_sweep`) blijft de toets die later volgt en verandert niets aan deze regels.

## Lab (vastgelegd 2026-10-20, vóór de eerste labrun)

De labfamilie staat in `app/replay/zonesweep_lab.py` en draait met `scripts/strategy_lab.py --familie zonesweep` (zie `vps-protocol.md`). Alles hieronder ligt vast vóór de eerste run en wordt na een run niet aangepast.

- **Toetsen.** De 7 varianten uit de tabel hierboven, elk met de stops `wick_025` en `wick_05` (`zonesweep.raw_stops`, daarna `zonesweep.final_stop`): 14 toetsen. Zones op 1u, 2u of 4u, prik en herstel op 1u (`zonesweep.find_setups(frames, tf, entry, use_htf)`). Er is geen beschrijvende stop zonder buffer zoals `zone_0` bij de range sweep.
- **Register.** 34 eerder bekeken varianten plus de 30 toetsen van de range sweep: 64 (`zonesweep_lab.PRIOR_VARIANTS` = `rangesweep_lab.TESTED_TOTAL`). Met deze 14 erbij staan er **78** toetsen in het register (`zonesweep_lab.TESTED_TOTAL`); de uitvoer van elke run noemt dat getal. De horde voor een voordeel blijft **t ≥ 3,4** per week (`zonesweep_lab.EDGE_T_MIN` = `rangesweep_lab.EDGE_T_MIN`): de verwachte beste van 78 onafhankelijke nulvarianten is ongeveer t ≈ 2,4 (gesimuleerd 2,42; bij 64 is dat 2,35), de marge van ongeveer 1 blijft dus staan.
- **Machinerie.** Dezelfde als de range sweep, met dezelfde code: vulling en verval tegen het midden van het referentiekader (`range_high`/`range_low` van de setup) via `rangesweep_lab.stop_row`, meting met `stopquality.measure`, de toets op stopkwaliteit `stopquality.accept` met de bevroren drempels van de range sweep (`docs/onderzoek/range-sweep/preregistratie.md`, blok `prereg-constants`), de strenge toets `rangesweep_lab.edge_verdict` (`trendlab.evaluate` op de netto R bij de meelopende referentie-uitgang plus de week-geclusterde t). Kosten 0,12% per rondreis, 20 coins (`trendlab.LAB_COINS`), 3 jaar, `--alleen-volledig`.
- **Clusters.** Week, zoals de machinerie van de range sweep. Een week bevat de kalenderdag, dus een marktbrede bounce op één dag (zoals de zeven voorbeelden) valt altijd in één cluster; een aparte dagcluster komt er niet bij.
- **Placebo.** Per gevulde trade 20 willekeurige instappen (`stopquality.placebo_rows`, seed 7): een willekeurig slot van een 1u-candle waarvan het slot binnen een actieve zone van **dezelfde soort** ligt (vraagzone bij long, aanbodzone bij short), op het zone-timeframe van de variant, met actief en bekend zoals in de detector (`zonesweep.active_zones`), zonder prik of herstel. Instap op dat slot, stop op dezelfde afstand in 1u-ATR als de echte trade, daarna `floor_stop`, dezelfde meting. Reden: de range sweep vergelijkt met een willekeurige instap binnen een actieve range; voor de zone-sweep is de zone het equivalent, en de vraag is of de prik met herstel meer doet dan een gewone instap in dezelfde zone met dezelfde stop. Long trekt met seed 7, short met seed 8, elk uit de eigen kandidatenset. De placebo gebruikt van de echte trade alleen kant, stopafstand en id.
- **Stopcriteria.** S2: geen van de 14 toetsen slaagt op stopkwaliteit, dan geen proefmotor. S3: bij alle 14 toetsen zijn de mediane kosten hoger dan 0,10R, zelfde besluit. `stopquality.kill_check(..., tests=zonesweep_lab.KILL_TESTS)` beslist alleen over een volledige set van 14.
- **Keuze voor de proef.** Zoals bij de range sweep (`rangesweep_lab.select_live`): uit de toetsen die geslaagd zijn op stopkwaliteit de meeste vullingen, dan de laagste mediane kosten, dan de bredere stop (buffer uit `zonesweep.BUFFERS`, dan de mediane stopafstand), dan de naam van de variant en van de stop.
- **Opslaan.** `--opslaan` alleen met `--kosten` 0,12 of hoger, precies de 20 coins, `--jaren 3`, `--alleen-volledig` en minstens één geslaagde toets. Per variant een regel in `rule_status` (`zs_1h` enz.), plus `zone_sweep_stop` (stopkwaliteit van de gekozen variant) en `zone_sweep` (de strenge toets). Er is geen proefmotor; opslaan zet niets live.

```prereg-constants
zonesweep.PRIK_MIN_ATR = 0.1
zonesweep.PRIK_MAX_ATR = 2.5
zonesweep.HERSTEL_BARS = 6
zonesweep.COOLDOWN_BARS = 24
zonesweep.REF_LOOKBACK = 60
rangesweep.ZONE_MAX_AGE = 200
rangesweep.MIN_STOP_PCT = 0.4
zonesweep_lab.PRIOR_VARIANTS = 64
zonesweep_lab.TESTED_TOTAL = 78
zonesweep_lab.KILL_TESTS = 14
zonesweep_lab.EDGE_T_MIN = 3.4
zonesweep_lab.LAB_COST_PCT = 0.12
zonesweep_lab.LAB_YEARS = 3
zonesweep_lab.PLACEBO_DRAWS = 20
zonesweep_lab.PLACEBO_SEED = 7
```
