# Marktbrein: ontwerp

Goedgekeurd op 6 oktober 2026. Doel: winst na kosten, informatievoorsprong, en iets wat gebruikers nergens anders zien.
Alleen melden, nooit zelf orders plaatsen. Nieuwe soorten gaan direct live met het label ongetest en staan op Bewijs.

## Idee

HesPulse zegt vooraf wat hij verwacht en rekent daarna zelf af. Op Bewijs staat een openbare score van zijn eigen
voorspellingen. Vier lagen: waarnemen, duiden, handelen, leren.

## Deel A (eerst, want de data verdwijnt als we hem niet bewaren)

1. `app/liquidations.py` en `deploy/crypto-liq.service`: Binance futures forceOrder-stream, per 5 minuten per coin
   opgeteld in `liquidations_5m` (long_usd, short_usd, n).
2. `app/market_calendar.py`: vaste momenten (funding 00, 08, 16 UTC; opening VS-beurs 09:30 New York; maandelijkse
   opties-expiry laatste vrijdag 08:00 UTC) plus `data/macro_events.csv` voor CPI en FOMC die de gebruiker invult.
3. `app/replay/strategy_scan.py` en `scripts/calendar_scan.py`: toets per moment op de bestaande candles, met train, test
   en een controle op willekeurige momenten. Alleen momenten die slagen worden een kalenderkans.

## Deel B

4. Markt-script: elke 4 uur per coin één Claude-aanroep met een gestructureerd pakket (prijs, niveaus, SMC-zones, funding,
   liquidaties, agenda, nieuws, community-calls). Antwoord is JSON met twee scenario's (voorwaarde, limietorder, stop, take,
   reden). De code toetst: stop minimaal 0,2%, R:R minimaal 2, niveaus dicht bij de prijs. Wat niet klopt, valt af.
5. Als-dan motor in de bestaande SMC-snelcyclus: een voorwaarde die klopt geeft één melding met het label ongetest. Een
   scenario vervalt na 12 uur. De uitkomst wordt gemeten.
6. Nieuws en oorzaak: RSS-koppen, Binance-aankondigingen en Polymarket-kansen, gesorteerd door Haiku. Radar toont bij een
   abnormale beweging de oorzaak.
7. Bewijs krijgt de soorten script, kalender en event met een controle op willekeurige momenten.
8. Site opnieuw: Vandaag (script, agenda, wat beweegt en waarom), Radar, Bewijs, Journaal, Instellingen.
   Stijl cockpit: donker, live, grote kaart per coin, tijdlijn van de dag. Beweging alleen gekoppeld aan een live waarde en
   met respect voor `prefers-reduced-motion`.

## Beperkingen

Voor script, nieuws en liquidaties bestaat geen history: 4 tot 8 weken live data voor een oordeel. Een scenario van Claude is
geen bewezen voordeel; de score op Bewijs laat dat zien, ook als hij laag is.
