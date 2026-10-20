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
