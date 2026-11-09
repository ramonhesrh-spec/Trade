# Voortgang

Nieuwste ronde bovenaan. Per ronde: onderzocht, bronnen en controles, aangetoond en niet, tegenbewijs, advies, volgende stap.

## Ronde 12 (2026-11-03, laat): ordertype achteraf, TradingView-script, case goud

**Gebouwd.**
- B-2026-11-03-13: `app/entry_compare.py` en `scripts/instap_vergelijking.py --dagen 30`. Per plan drie instappen (limiet, market, stop-order)
  met dezelfde stop en hetzelfde doel. Uitvoer: netto R per instappunt en het verschil met de limiet met weekinterval. Alleen meting achteraf,
  geen motor leest het. Test: `tests/test_entry_compare.py`.
- `tradingview/hespulse_structuur.pine` (Pine v6) met `tradingview/README.md`: dag-richting, 4u-range top-down, trend per tijdframe,
  BOS/CHoCH, open FVG en positievak uit ingeplakte niveaus. Daarna in zes stappen bijgewerkt: leesbaar op donker, vast aan de prijsschaal,
  candlenummers in plaats van tijden, kopie van Groot in de kleuren van de app, prijs en afkortingen in elk label, dichte labels op één regel.
  Het script is een benadering; de app blijft de bron. Verandert een swing-, breuk- of rangeregel, dan moet het script mee.
- Fout hersteld: de placebo-meting liep vast (`KeyError`) op een instappunt zonder id en blokkeerde de modelmeting op Bewijs.

**Onderzocht.**
- Case goud 15m long tegen de dag in (`cases/2026-11-03-goud-15m-long.md`). Niveaus van de 1u-schermafdruk gaven 2,2R; de eerste aflezing is
  verbeterd. Hypothese H4 staat geparkeerd in `hypotheses.md`.

**Niet aangetoond.** Of limiet, market of stop-order beter is: het script moet nog op de VPS draaien.

**Volgende stap.**
- CEO op de VPS: `scripts/instap_vergelijking.py --dagen 30` draaien en de uitvoer delen.
- Na de eerste 30 trades per punt de drie tabellen onder "Controle op de cijfers" op Bewijs lezen (ronde 11).

## Ronde 11 (2026-11-03, avond): vier controles op de cijfers, alleen meting

**Gebouwd (B-2026-11-03-12, preregistratie laatste aanvulling).** Strenge vulling (doortik) naast de gewone; MAE/MFE over de hele looptijd en
stopslip als ondergrens; placebo met tien willekeurige instappen per trade; de auto-misser kent nu het model.

**Gevonden tijdens het bouwen.** De MAE van een A-trade werd alleen gemeten over het venster van 25 uur. Een trade die langer liep, kreeg een
te kleine MAE. Nu over de hele looptijd, en 'onbekend' als dat niet lukt.

**Niet aangetoond.** Nog niets: er zijn nog geen afgeronde trades na de bevriezing. De strenge arm telt alleen plannen van na de eerste
cyclus met deze code.

**Volgende stap.** Na de eerste 30 trades per punt de drie tabellen onder "Controle op de cijfers" op Bewijs lezen, samen met de stopregel.

## Ronde 10 (2026-11-03, nacht): kritische terugblik

Alle beschikbare voorbeelden opnieuw bekeken (16 beelden, 9 cases). Uitkomst en voorstel in `plan-van-aanpak-2026-11-04.md`. Correctie:
mijn bewering dat V1 bij ZEC gevuld en gestopt zou zijn, was niet nagerekend.

## Ronde 9 (2026-11-03): ONDO en ZEC nagelopen, de range rekt op, meer meldingen, kortere lijst

**Gecontroleerd op de VPS.**
- ONDO: V1 (0,4063) vulde niet, stand `weggelopen`. B viel af op `niet_in_premium` (top 0,4063 onder EQ 0,40705). B0 gaf om 05:15 een plan:
  limiet 0,4016, stop 0,40687, doel 0,3984. B0 was stil. Of hij vulde, staat in `model_entries` (nog niet gezien).
- ZEC: het short-scenario eindigde `geen_pool`. De top van 1.291 lag boven de range high van 1.255, buiten het model.
- ONDO scenario 2: begonnen volgens de regel om 08:00, opgeslagen om 12:30 UTC. Oorzaak nog niet vastgesteld.

**Gebouwd, live op besluit van de CEO.**
- De range rekt op na een 4u-slot door de rand tegen de dag in (B-2026-11-03-05). Test plus drie tegenvoorbeelden en de prefix-toets.
- Luide melding voor B, B0 en R; B0 op de kaart; korte meldtekst (B-2026-11-03-06). Tests: B0 en R melden één keer; P meldt niet; al
  door de limiet of tegen BTC meldt niet maar wordt wel gevolgd.
- Kansen: wachtende scenario's als korte regel op afstand (B-2026-11-03-07). Playwright op 375px: korte regels, uitklappen werkt.
- De instaplijn op Groot begint op het moment dat de app hem zag.

**Grenzen.** Ongetest. Meer luide meldingen (B, B0, R): het dagbudget van 8 vangt de rest op als stille melding.

## Ronde 8 (2026-11-03): uitkomst van de PUMP-controle, richting top-down en Groot per tijdframe

**Gecontroleerd op de VPS.** `model_kaarten.py --coins PUMP --dagen 3 --tekst`:
- Geen afwijkingen zonder latere candles: de code volgt de regels.
- Short-scenario: "run" door de pool, daarna "context_weg".
- Long-scenario: sweep zonder shift, geen entry.
- De HesPulse-long kwam dus niet van het model.

**Oorzaak van de gemiste short.** De 4u-bias "laatste breuk" sloeg om naar long door het herstel van 1 november.

**Gebouwd, live op besluit van de CEO.**
- *Richting top-down.* De dag bepaalt de richting en de 4u-range volgt de breuk in die richting. Tests: dag omlaag houdt een long tegen;
  tegenvoorbeeld dag omhoog laat hem staan; zonder dagcandles de oude regel; prefix-vast met dagcandles.
- *Groot per tijdframe (15m, 1u, 4u, D).* Structuur zoals een analist, met een trendregel bovenin.

**Grenzen.**
- Ongetest. Er loopt geen stille vergelijking met de oude 4u-regel; daarvoor koos de CEO niet.
- Of het model de PUMP-short nu wel had gegeven, is onbekend tot `model_kaarten.py` opnieuw op de VPS draait.

## Ronde 7 (2026-11-03): alle instappunten op één kaart

**Gebouwd.**
- Model: B, B0 en P naast A. A is ongewijzigd: de gedeelde `_plan` en de bestaande tests zijn groen.
- De prefix-toets dekt nu ook P, B en B0.
- Opslag en stille meting per punt (`model_entries`).
- Grafiek met letters (A, B, P, V1) en een detailblad "Instappunten" met de basis per punt.
- Meting per punt op Bewijs en in de nachtexport.

**Gecontroleerd.**
- Playwright op 375px met synthetische candles: drie punten in het blad, letters op de grafiek, geen JS-fouten.
- Fout gevonden en opgelost: de stippelstijl streepte de labels door.

**Grenzen.**
- Nog niet op echte candles gedraaid (geen Binance vanuit de container).
- "Zet de order" en de luide melding horen bij A.
- "Groot" toont alleen A.

**Volgende.**
- Eerste echte kaarten bekijken.
- Op de VPS `model_kaarten.py --coins PUMP --dagen 3`.

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
