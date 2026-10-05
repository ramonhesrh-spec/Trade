# Visieplan: SMC met community als bevestiging

## Doel

HesPulse meldt trades van minuten tot uren (maximaal een dag) waar twee onafhankelijke bronnen
samenvallen: een SMC-setup op de 15m/30m-grafiek en een call uit de community voor dezelfde coin en
richting. Maatstaf: netto positief in R na kosten. Alleen resultaten voor de gebruiker; het systeem
meet zelf en rapporteert.

Niet-doelen: automatisch handelen, meldingen forceren, bestaande meldingen uitzetten voordat een
beter alternatief bewezen is (de huidige meldingen blijven staan en krijgen een label met de gemeten uitkomst).

## Wat we weten (5 oktober 2026)

- Geen enkele regel die alleen candles leest heeft een voorsprong: day_trading (-0,23R bruto), SMC met
  vaste take (bruto ongeveer 0, 122 signalen in 12 maanden op 7 coins), patroon (live -0,34R op 117 trades) en
  zeven standaardregels (215.000 trades, 0 van 48 varianten).
- Eén mogelijke voorsprong: community day_trading-calls, vooral op kleinere coins (LINK, SOL, SUI, AVAX),
  over ongeveer 4 uur (+1,0% in de richting, 71%, t=2,7 op 28 calls). Eén maand data. Nog geen bewijs.
- Snelle voorsprong (eerste uur) verdwijnt bij 15 minuten vertraging. Het venster van 4 uur blijft staan.
- De bevestigingsstatus in de database volgt de uitkomst (hindsight) en is geen bewijs.

## Beperkingen die het plan bepalen

1. De community-geschiedenis is één maand. Een afspeeltest over 12 maanden is voor de community niet mogelijk.
2. Een samenval van SMC en community komt waarschijnlijk niet vaak voor (naar schatting enkele per maand).
   100 samenvallen kost dan maanden. Daarom meten we de twee bronnen eerst los en de samenval als laag erbovenop.
3. De afspeelrun van SMC en de testbank draaien op de VPS. Alleen de gebruiker bereikt de VPS. Wat zonder
   tussenkomst moet lopen, gaat daarom in een timer op de VPS (eenmalige installatie).

## Bewijsladder (streng: 100 trades en 4 weken schaduw)

Een signaaltype gaat pas live met alert als het alle drie haalt:
1. Netto positief in R na kosten (0,06% per rondreis) in train en test, minstens 100 trades, minstens 70% van de coins positief.
2. Een controle met willekeurige instap van dezelfde coin en richting scoort duidelijk slechter (t >= 2).
3. 4 weken schaduwmodus (gemeten, geen melding) met nog steeds netto positief.

## Fasen

**Fase 1: de meetmachine zelf laten draaien (week 1).**
- Het wekelijkse kwaliteitsrapport afmaken (scan per type, SMC apart, community-calls tegen controle) en als
  melding op /meldingen zetten. Eenmalig installeren op de VPS (timer).
- `signals.confirmed_initial`: de bevestigingsstatus op het moment van de melding apart opslaan, zodat live cijfers eerlijk worden.
- Oplevering: elke zondag een rapport. Geen handeling van de gebruiker.

**Fase 2: SMC los verbeteren (week 1 tot 2).**
- De SMC-setup-analyse (alle 733 setups, ongeveer 700 nagespeelde trades) levert kenmerken met een voorsprong in
  train en test, of de conclusie dat er geen is.
- Kenmerken: trend op 4u en dag, BTC-trend, sweepdiepte, zonegrootte, volatiliteit, stopafstand, tijdblok, coin.
- Uitkomst: een lijst regels die SMC-setups beter maken, of "SMC heeft geen voorsprong".

**Fase 3: community los verbeteren (week 1 tot 4).**
- Meer calls verzamelen (automatisch). Per week het oordeel uit het rapport.
- Test welke categorie (day_trading, lange_termijn) en welke coins werken. Test de tijdstop van 2 tot 8 uur.

**Fase 4: samenval in schaduw (week 3 tot 8).**
- Een detector die per nieuwe SMC-setup of -signaal en per nieuwe community-call vastlegt of ze op dezelfde coin
  en richting binnen een venster van 6 uur vallen. Alleen vastleggen en meten, geen melding.
- Elke samenval krijgt dezelfde vaste trade als in de afspeelruns. Het rapport vergelijkt: SMC alleen, community
  alleen, samenval.

**Fase 5: live met bewijs (vanaf week 8 als de poort gehaald wordt).**
- Alleen de typen die de bewijsladder halen sturen een alert, met het label "gemeten: n trades, +x R netto".
- De overige meldingen blijven zichtbaar met hun gemeten uitkomst.

**Fase 6: nieuwe coins HBAR, WLD, ONDO, XRP in schaduwmodus.**
- Zoals in het eerste ontwerp (2026-10-04): eerst afspelen, dan twee weken schaduw, dan live.

## Stopregels

- Na 8 weken: geen voorsprong in SMC-kenmerken (fase 2) en community t < 1 (fase 3) betekent: geen signaal op
  alleen candles en community levert iets op. Dan stoppen we met de signaaljacht en testen we positioneringsdata
  (open interest, top-trader long/short, taker-volume, funding) als laatste bron.
- Een live type dat na 30 trades netto negatief is, gaat automatisch terug naar schaduw.

## Succes in cijfers (richtwaarden, geen belofte)

- Netto +0,2R per trade of beter.
- Minstens 2 tot 3 meldingen per week van het bewezen type. Bij minder is dat het bewijs dat de selectie scherp is, niet een fout.

## Open punten

- Welke gebruiker in het journaal is de eigenaar, en wat meet `result_pct` bij gebruiker 3 (gemiddeld -40%)?
- Welke houdtijdgrens past bij de prop firm (minimale houdtijd, nieuws, hefboom)?
