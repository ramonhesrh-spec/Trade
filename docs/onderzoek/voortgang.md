# Voortgang

Nieuwste ronde bovenaan. Per ronde: onderzocht, bronnen en controles, aangetoond en niet, tegenbewijs, advies, volgende stap.

## Ronde 6 (2026-11-02): BTC-poort en alleen het model

**CEO-besluiten.**
- "De short is gebaseerd op het BTC-verhaal." Dat is meermaals gestuurd en ik had het alleen als kenmerk verwerkt.
- "Alle modellen weg, alleen het HesPulse-model."

**Gebouwd.**
- *BTC-poort.* Een entry tegen BTC 4u wordt niet gemeld en wordt stil gevolgd met dezelfde regels (`cf_*`). Tests: long tegen bearish
  BTC geeft geen melding; tegenvoorbeeld bullish of onbekend houdt niets tegen; met de poort uit werkt alles zoals eerst.
- *Alleen het model.* De vier oude motoren zoeken en vullen niet meer. Lopende trades lopen af, de dagbrief blijft en de POC-niveaus
  blijven bijgewerkt. Tests met tegenvoorbeeld zonder model.

**Tegenspraak, vastgelegd.**
- De BTC-poort is niet getoetst. Daarom loopt de stille arm mee: als die na 50 trades duidelijk boven 0 staat, kost de poort winst.
- De oude soorten uitzetten stopt de vergelijkingsdata (H1, V2, V3).

**Nog open.** Welke soort gaf de PUMP-long. Dat bepaalt of de 4u-contextregel van het model zelf te ruim is.

## Ronde 5 (2026-11-02): zelfstandig, de spec van het model tegen de code

**Aanleiding.** De CEO: "Bedoel meer dat je zelfstandig te werk gaat."

**Werk.** Ik heb de eisen uit de spec en de rapporten langsgelopen tegen de code van het model.

**Gevonden.** Twee meetfouten in de uitkomst van het model, beide in strijd met preregistratie §4.14:
- `level_check` mat vanaf `signals.created_at`, het moment van opslaan, in plaats van vanaf de vulcandle. De een of twee 5m-candles
  direct na de vulling vielen weg, zodat een vroege stop gemist werd en een later doel als winst telde.
- Elk signaal verviel na één dag (`SIGNAL_MAX_AGE_DAYS = 1`). De spec vraagt 7 dagen en daarna `tijd`.

**Opgelost.** `model_live.track_trade` zet de uitkomst nu met `model.outcome`, dezelfde regel als V1 (commit 4d3e50a). Vier tests vallen
om zonder de fix; er is een tegenvoorbeeld zonder stop. De volledige testrun is groen: 2329 tests.

**Open, en niet gerepareerd.** Bij de andere soorten telt het deel van de vulcandle na de vulling ook niet mee (`candles_after`). Bij een
vulling in een lopende candle is dat klein. Die soorten melden niet meer, maar hun data voedt H1 en de vergelijkingen V2 en V3. Het werkt
in alle groepen gelijk, dus het verschil tussen mee en tegen blijft eerlijk; de niveaus niet. Het staat in het bewijsregister als E3.

**Nieuwe case.** `cases/2026-11-02-pump-1u-1815.md`. Het model geeft bij lagere toppen zonder sweep per ontwerp geen short. Of er een
tweede model "voortzetting vanuit aanbod" komt, is een productkeuze voor de CEO.

## Ronde 4 (2026-11-02)

**Aanleiding.** De CEO: "Heb het gevoel dat je niet alles leest?"

**Gecontroleerd.** Beide rapporten op inhoud die mijn tekstextractie zou missen:
- geen scripts, verborgen blokken, commentaar of templates;
- de alt-teksten noemen alleen de beelden.

De tekst was dus volledig gelezen.

**Fout gevonden.** In ronde 2 had ik van de vijf PUMP-beelden er maar twee bekeken (A en E). In de chat zei ik daarna ten onrechte "alle
vijf". De drie BTC-beelden (B, C, D) heb ik nu bekeken en verwerkt in `cases/2026-11-02-pump.md`.

**Nieuw inhoudelijk.**
- Alle externe grafieken komen van één maker, binnen 5 minuten gemaakt. Ze zijn dus niet onafhankelijk.
- BTC 4u is dalend sinds 21 oktober, maar binnen een grotere range van ongeveer 75.000 tot 84.000.

**Werkwijze aangepast.**
- Bij elke bijlage tel ik eerst de beelden en de tekstlengte.
- Ik meld per beeld of het bekeken is.
- Ik zeg nooit "alles bekeken" zonder die telling.

## Ronde 3 (2026-11-02)

**Aanleiding.** Het goudrapport kwam opnieuw binnen.

**Gecontroleerd.**
- Het rapport is byte-gelijk aan het eerste.
- Beelden B en C nu zelf bekeken; in ronde 1 alleen A.

**Nieuw.**
- De tijdlijn: de herstelcandle vormde zich waarschijnlijk tussen 14:32 en 14:45. Dat is een afleiding.
- De maker tekende zelf al eerst een herstel.
- De spread op TVC was ongeveer 0,005%.

Alles staat in `cases/2026-11-02-goud.md`.

**Herzien.** Niets. Mijn eerdere oordeel over goud blijft staan.

## Ronde 2 (2026-11-02)

**Aanleiding.** De CEO vroeg of het HesPulse-rapport gelezen was.

**Eerlijk antwoord.**
- Het goudrapport had ik in ronde 1 helemaal gelezen.
- Van het PUMP-rapport had ik ongeveer driekwart gelezen. §8 (beoordeling van de HesPulse-long) en de bijlagen ontbraken.
- De beelden in beide rapporten had ik niet bekeken.

**Nu gedaan.**
- Alle tekst gelezen.
- De acht beelden uit de rapporten gehaald.
- De SHA-256 van de drie goudbeelden komt overeen met de waarden in het rapport.
- De PUMP-grafieken A en E en goud A bekeken.

**Nieuw.**
- Op de externe bron lag de PUMP-koers om 12:11 al onder de HesPulse-limiet. Een vulling op Binance is daarmee niet aangetoond (`cases/2026-11-02-pump.md`).
- De eis "BTC bearish, correlatie onbekend" werkte al. Hij heeft nu een regressietest.

**Herzien.** Geen eerdere conclusie.

## Ronde 1 (2026-11-02)

**Inventaris.**
- Code: deze repo, tak `claude/crypto-day-trading-alerts-geb2v7`.
- Specs: `hespulse-model/preregistratie.md` en de preregistraties van range-sweep en zone-sweep.
- Nachtexport: `origin/hespulse-data`, één export van 2026-11-02.
- Twee rapporten van de CEO: goud en PUMP.
- `CLAUDE.md` met de besluiten tot en met vandaag.

**Ontbreekt.**
- Marktdata in de ontwikkelcontainer. Binance, Bybit en OKX zijn vanaf hier niet bereikbaar (netwerkbeleid), dus geen replay op echte
  candles hier.
- De eerdere bijlagen (screenshots) van deze sessie. Die zijn weg na een herstart van de container.
- Signaal-id's bij de PUMP- en DOGE-voorbeelden.
- Een eerste uitvoer van `scripts/model_kaarten.py` (H2).

**Onderzocht.**
1. Melding CEO: "Groot" op de modelkaart kon niet schuiven en het tijdframe niet wisselen. Opgelost (E2, B-2026-11-02-08).
2. De nachtexport van 2026-11-02, 374 afgeronde trades (E1).

**Aangetoond binnen E1.**
- Zone-radar long verloor −0,81R over 70 trades.
- Trades zijn sterk geclusterd: 374 trades in 196 unieke uren.
- Er zijn nog maar 17 trades uit het perps-tijdperk.

**Niet aangetoond.**
- Een voordeel van welke soort ook.
- Dat shorts structureel beter zijn.

**Tegenbewijs.**
- Kleine stops waren in deze data niet slechter. Dat gaat in tegen een eerdere labbewering.
- De WLD-correctie gaf een kaart die verloor.

**Gedaan.**
- Hypothese H1 (4u-context mee of tegen, coin en BTC) vooraf vastgelegd met een beslisregel.
- De meting zit in de nachtexport, dus de data verzamelt zichzelf. Het telt pas vanaf 2026-11-03.
- `scripts/export_analyse.py` maakt E1 reproduceerbaar.
- Projectgeheugen ingericht en vier cases vastgelegd.

**Advies.**
- Geen nieuwe regels nu.
- Eerst H2 (doet het model live wat de spec zegt), dan H1 laten lopen tot de beslisregel iets zegt.

**Volgende stap.**
- CEO op de VPS: `scripts/model_kaarten.py` draaien en de uitvoer delen (H2).
- Vanaf dinsdag 03:17 UTC staat H1 automatisch in elke export.
- De wekelijkse sessie (`docs/verbeterlus.md`) leest hem.

## Onderzoeksagenda (geprioriteerd)

1. **H2: het model live controleren.** Het enige model dat meldt, is nog niet op echte candles nagerekend. Grootste risico: een
   stap die met latere candles anders uitkomt, of entries die al voorbij zijn bij de melding. Blokkade: kan alleen op de VPS.
2. **H1: 4u-context mee of tegen.** Toetst de kernfilter van het model op data van de oude soorten. Loopt automatisch; eerste beoordeling
   na 8 weken en 50 trades per groep.
3. **Effectieve steekproef.** Elke beoordeling telt unieke uren en weken, niet alleen trades. Dat staat al in `export_analyse.py` en
   `model_measure` (N_eff).
4. **Perps-tijdperk apart.** Pas na 1 november zijn de candles van het contract zelf. Oudere uitkomsten blijven apart staan (Bewijs doet dit
   al).
5. **Geparkeerd tot er data is:** bevestigde entry tegen vroege limiet (V1 loopt al), herstel-long tegen de context (wacht op H1 "tegen"),
   goud als instrument (productvraag).
