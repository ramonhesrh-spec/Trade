# Range sweep: de vijf voorbeelden van 15 en 16 oktober 2026

Bron: de gebruiker, grafieken van TradingView met het long/short-gereedschap. Datums van de gebruiker ("vandaag en gisteren"), nog te bevestigen.
Tijden zijn de klok van de telefoon (CEST, UTC+2) op het moment van de screenshot; de candle rechts vormt nog. De aftelklok rechts op de prijsas
geeft hoe lang die candle nog loopt: ARB 2u 01:07:28 om 17:52 (candle 15:00 tot 17:00 UTC), APT 1u 22:32 om 14:37 (12:00 tot 13:00 UTC),
APT 2u 01:14:13 om 13:45 (11:00 tot 13:00 UTC), WLD 1u 14:26 om 11:45 (09:00 tot 10:00 UTC), AAVE 30m 17:38 om 23:42 (21:30 tot 22:00 UTC).
Deze trades zijn zo recent dat de uitkomst nog open kan zijn. De eerste toets kijkt alleen of de detector de setup ziet op het moment van de
screenshot; de uitkomst lezen we pas later en nooit om een regel aan te passen.

Niet in de CSV: de eerdere APT-long uit `apt-2u-long-en-short.webp` (instap 0,7472, stop 0,7191) omdat de tijd niet te lezen is, en het geplande
AAVE-long (136,64, stop 132,77, doel 156,94) omdat het een plan is en geen trade. Geeft de gebruiker de tijd van de APT-long, dan komt hij erbij.

## Wat de vijf voorbeelden laten zien

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

## Besluiten van 2026-10-16 bij deze voorbeelden
- De datums zijn van de gebruiker en staan op "te bevestigen" (AAVE 2026-10-15 23:42 CEST, de andere vier 2026-10-16).
- De naam van de TradingView-indicator achter de vakken is onbekend. We gebruiken daarom onze eigen zonedetector (zie de definities in `preregistratie.md`) en vergelijken op structuur, niet op de tick.
- De gebruiker stuurt later nog 5 of meer voorbeelden. Dat blokkeert niets: ze komen in `handtrades.csv` en `missers.md` en tellen mee voor S0 (vanaf 10 voorbeelden).
