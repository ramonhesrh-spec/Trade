# HesPulse-model: preregistratie

## Besluiten CEO 2026-11-02

De CEO keurde dit document goed met de volgende besluiten op de open beslissingen (§12). Ze gaan voor wat verderop anders staat; waar een
paragraaf erdoor verandert, staat dat erbij.

1. **Live direct, controle achteraf** (gewijzigd ten opzichte van de eerste versie van dit besluit, die een controle van 30 getekende kaarten
   vooraf vroeg). Het model gaat meteen aan: `HESPULSE_MODEL_ENABLED` staat standaard op true (een `false` in `.env` zet hem uit), gelabeld
   ongetest. Poort 3 (§10) wordt een controle achteraf: `scripts/model_kaarten.py` laat het model over de laatste 14 dagen op alle
   `config.FIXED_COINS` lopen (alleen gesloten candles, stap voor stap zonder toekomst) en tekent de eerste 30 gevonden scenario's als één
   HTML-bestand. Fouten in de code worden hersteld; regels niet.
2. **Alleen het model meldt.** Structuur, Zone-radar, Zone-sweep en POC-radar lopen stil mee: ze blijven kaarten en signalen maken (meting,
   Bewijs), maar zonder enige push, ook geen stille, en zonder eigen tab op Kansen. Een open trade van zo'n soort blijft onder Open staan tot hij
   klaar is. Eén instelling, `MODEL_ONLY_ALERTS` (standaard aan zodra het model aan staat), draait dit terug. Bewijs blijft alle soorten tonen.
3. **De luide melding is moment B** (entry beschikbaar: zet de order), binnen het gedeelde dagmaximum (8) en de bundeling per cyclus. Moment A
   (scenario ontdekt) staat alleen in de app, zonder push. De vulling is stil (een rij op `/meldingen`).
4. **Geen minimale R:R.** De kaart toont de R:R en de CEO kiest. Daarmee vervalt de R:R-eis van 4.7, 4.12 en V1 (§6): het doel blijft de
   dichtste kandidaat, maar een entry valt niet meer af op "R:R onder 2". De R:R wordt bewaard en getoond, nooit als filter of volgorde.
5. **Iedereen ziet het model** (niet eerst alleen de CEO), gelabeld ongetest. De vergelijkingen (V1, V2, V3) blijven alleen voor de CEO op
   Bewijs.

Trade_type in de code: `hespulse_model` (§9 stelde `hp_model` voor).

**Aanvullend besluit CEO 2026-11-02 (kenmerken, geen filter).** Uit een extern uitvoeringsplan (PUMP en BTC), vastgelegd vóór er uitkomsten zijn:

6. **BTC-context** op elke modelkaart, gemeten op moment A en opnieuw op moment B (`app/btc_context.py`): de 4u-structuurrichting van BTC
   volgens dezelfde regel als het model (4.3: bullish, bearish, neutraal zonder geldige breuk, onbekend zonder data), de Pearson-correlatie van
   coin en BTC op log-rendementen van gesloten, op UTC uitgelijnde 15m-candles uit dezelfde futuresbron over 96 en 672 rendementen
   (ontbrekende paren niet opvullen; minder dan 90% van de slots met een paar, ontwerpkeuze, of nulvariantie is "onvoldoende data"), en het
   24u-rendement van de coin min dat van BTC (relatieve sterkte, geen alpha). Tekst: "BTC 4u: bearish · correlatie 0,82 (24u) / 0,74 (7d)",
   of "BTC-context onbekend" als data ontbreekt (nooit stil neutraal). **Alleen een kenmerk:** geen motor, filter, volgorde of melding leest
   het; het is geen extra toets in §6 of §8.
7. **De kaart scheidt in tekst** de context (4u-richting van de coin en BTC), het entrytype (het model gaat altijd met de 4u-structuur mee) en
   de status (scenario ontdekt, entry beschikbaar, gevuld). De zone op de grafiek heet "oorsprong zone", nooit entry.
8. **Eén planrij:** titel, richting, instap, stop, doel, de getekende box, de uitleg en de melding komen uit dezelfde opgeslagen rij in
   `model_scenarios`. Een short heeft altijd doel < instap < stop, een long stop < instap < doel; een rij die dat niet haalt wordt niet
   gepubliceerd (`model_card.plan_ok`), en de kaartgrafiek wordt nooit bewaard (`Cache-Control: no-store`).

Status: **goedgekeurd door de CEO op 2026-11-02, bevroren**, met de besluiten hierboven. Oorspronkelijk: Er wordt niets gebouwd voordat de CEO dit document en de open beslissingen
onderaan heeft goedgekeurd. Na goedkeuring is dit document bevroren: wijzigingen komen alleen als gedateerd "Aanvullend besluit" onderaan,
met reden, en nooit op grond van uitkomsten.

Bron: *The ICT Trading Course* (hoofdstukken 7-10, 13-15, 17-18, 20, 22-23, 25-26). Het model volgt hoofdstuk 25 ("The Complete Entry Model").

---

## Samenvatting (voor de CEO)

**Wat.** Eén hoofdmodel uit hoofdstuk 25 van het boek, in vaste regels: (1) **context** op 4u-candles: structuurrichting, dealing range met
premium en discount, en het doel (draw on liquidity); (2) **sweep** op 15m: een lont door een onaangeraakte liquiditeitspool aan de
tegenkant en een slot terug; (3) **structuurverandering** op 15m: een slot boven de laatste top (long) met displacement; (4) **terugtest**: een
limietorder op de fair value gap die de displacement achterliet, in discount; (5) **stop** voorbij het uiterste van de sweep, **doel** de
draw on liquidity: de rand van de range of, als die dichterbij ligt, een naakte dag- of week-POC. Short is het spiegelbeeld.

**Geen tijdfilter.** Stap 2 van het boek (alleen handelen in een kill zone) vervalt. Dat is een **besluit van de CEO**: crypto handelt 24/7
en het boek levert geen bewijs dat de vensters werken.

**Twee momenten op één kaart.** "Scenario ontdekt" (de context klopt; de kaart zegt waarop we wachten) en "entry beschikbaar" (alle
voorwaarden vervuld, limiet bekend). Beide met het tijdstip waarop ze herkenbaar waren. We meten ze apart.

**Vergelijkingen (vooraf vast, stil, zonder melding).** V1: een vroege limiet op de pool zodra het scenario ontdekt is, zonder sweep of
bevestiging. V2: de bestaande Zone-sweep, ongewijzigd, als referentie. V3: de bestaande POC-radar, ongewijzigd, als referentie. Dat is het
maximum van drie vergelijkingen, dus **vier toetsen** in totaal (hoofdmodel tegen nul, en V1, V2 en V3 elk tegen het hoofdmodel). Geen andere
combinaties achteraf.

**POC in het model (besluit CEO).** De POC-radar gaat niet uit, maar wordt geen eigen radar met een eigen tab. In het model telt een naakte
dag- of week-POC (definitie `app/poc.py`) mee als kandidaat voor het doel. Een OB of FVG die een naakte POC overlapt, krijgt het kenmerk
"POC-samenval": gemeten, geen voorwaarde. De huidige POC-radar loopt stil mee als V3. Zijn +0,57R per trade over 13 trades is te weinig om
iets te concluderen.

**Beoordelen.** Na 50 afgeronde trades per arm alleen een technische en uitvoerbaarheidscheck. Een besluit pas bij minstens 150 afgeronde
trades, 12 weken en 60 onafhankelijke trades, op meerdere maten samen: netto R na kosten en funding, onzekerheid per week, verliesreeks en
drawdown, resultaat zonder de beste 5%, en een periode die niet voor ontwikkeling is gebruikt.

**Eerlijk.** Het boek is uitleg, geen bewijs: de plaatjes zijn schema's, en over POC zegt het boek niets. Ook onze huidige cijfers bewijzen
niets. Zone-sweep +0,20R per trade komt uit één week met samenhangende trades en meet kaarten zonder doel bij een referentie-uitgang.
POC-radar +0,57R komt uit 13 trades.

**Bouwstenen.** Bestaande code (ook `app/poc.py`) is gecontroleerd met synthetische candles (`tests/hespulse_model/test_bouwstenen.py`). Geen ervan gebruikt
toekomstige candles voor iets dat al vaststaat, maar een weigering van de Zone-sweep aan het eind van de data is voorlopig. Drie functies
kunnen één gebeurtenis dubbel tellen (gelijke toppen, een order block bij displacement over twee candles, een breuk die vlak daarna opnieuw
telt). Bruikbaar: de pivotregel van `trendlab`, `zone_active`, `floor_stop` en de meetmodules. Met aanpassing: de sweep van de Zone-sweep,
de order-blockregel van `find_zones` en de FVG-definitie. Niet bruikbaar voor dit model: de breuken van Structuur en de FVG/OB-functies van
`indicators`.

**Meldingen (besluit CEO): compact.** "Scenario ontdekt" geeft nooit een luide push (alleen zichtbaar in de app, hoogstens stil). Per entry
komt er hoogstens één luide melding, binnen een dagmaximum per gebruiker (standaard 8) en gebundeld als er meerdere in één scancyclus vallen.
Vergelijkingsmodellen melden nooit. Het model sluit aan op de gedeelde meldingsregels die nu voor de huidige motoren gebouwd worden.

**Vijf open beslissingen** staan onderaan, elk met een aanbevolen keuze.

---

## 1. Leeswijzer en vaste afspraken

- **Boek** = wat het boek zegt, met hoofdstuk en de kern van het citaat (Engels, kort).
- **Ontwerpkeuze** = wat wij ervan maken: de keuze, de reden en wat er gebeurt bij een andere keuze. Een ontwerpkeuze is geen "juiste
  vertaling". Het boek geeft voor crypto bijna nergens getallen. Elk getal hieronder is dus een keuze van ons, vooraf vastgelegd en nooit
  afgesteld.
- **Besluit CEO** = een keuze die de CEO al gemaakt heeft.
- **Candles.** Alleen gesloten candles van Binance-perps via `app/exchange.py` (`fetch_ohlcv`). De timestamp van een candle is zijn
  openmoment. Een candle is bekend op `timestamp + timeframe`, zoals `rangesweep.closed_only`. De motor draait in de snelcyclus van 5 minuten
  en ziet een gesloten 15m-candle dus hoogstens 5 minuten (plus de rekentijd) na het sluiten.
- **Herkenbaar op** (`known_at`) = het sluitmoment van de laatste candle die een gegeven nodig heeft. **Gezien op** (`detected_at`) = het
  moment dat de motor het vastlegt. Beide worden opgeslagen; de vertraging ertussen meten we.
- **ATR** = Wilder-ATR(14) op het timeframe van de regel (`replay.lab.add_indicators`), genomen op de candle waarop de regel beslist.
- **Coins.** `config.FIXED_COINS`.
- **Long** staat overal uitgeschreven. **Short** is het spiegelbeeld: hoog en laag wisselen, boven en onder wisselen, premium en discount
  wisselen.

## 2. Het boek in het kort (alleen wat het model gebruikt)

| Stap (hfdst. 25) | Boek, kern van het citaat |
|---|---|
| 1 Context | "Before the window, establish structure, judge the draw on liquidity, and note the premium/discount split." |
| 2 Tijd | "Wait for a kill zone or macro. You do not act outside your window." |
| 3 Sweep | "wait for price to sweep liquidity against your direction — for a long, a sweep of sell-side liquidity below." |
| 4 Shift | "Confirm a change of character on displacement in your intended direction. [...] A weak, non-displacement shift does not count." |
| 5 Entry | "Enter on the retrace into the PD array left by the displacement — the order block or fair value gap, ideally where both overlap — in the correct premium/discount half." |
| 6 Stop en doel | "Stop just beyond the sweep extreme; target the draw on liquidity you identified in Step 1." |
| Volgorde | "each step gates the next [...] Only when all are present, in order, do you act." |

Het boek levert **geen bewijs**: geen steekproef, geen kosten, geen uitkomsten. De illustraties zijn schematisch (getekende candles). Het
boek zegt zelf dat de tijden "depend on your timezone and the instrument, which you must confirm for yourself" (hfdst. 22) en geeft voor
displacement, sweep en swing geen getallen. Alles wat hieronder een getal heeft, is dus een ontwerpkeuze.

## 3. Besluiten die al vastliggen

- **Besluit CEO (2026-11-02): geen tijdfilter.** Stap 2 (kill zones, macro's, Silver Bullet; hfdst. 22, 23, 25) vervalt in het hoofdmodel.
  Reden: crypto handelt 24/7, en het boek levert geen bewijs dat de vensters werken. Er komt ook geen vergelijkingsarm met een tijdfilter en
  geen andere tijdvariant. Bewijs houdt de bestaande uurkaart die het voor elke soort toont. Die is beschrijvend: geen toets en geen filter.
- **Besluit CEO (2026-11-02): POC-radar niet uit, maar opgenomen in het ene model.** De naakte dag- en week-POC telt mee als kandidaat voor
  het doel (4.7) en als kenmerk bij de entry (4.11). De huidige POC-radar loopt stil mee als vergelijkingsmodel V3 (§6): geen eigen tab, geen
  meldingen. Zijn data, zijn rij op Bewijs (voor de CEO) en het volgen van lopende trades blijven.
- **Niets wordt definitief uitgezet op grond van de huidige cijfers.** Wat stil wordt, blijft meten (zie §9).

## 4. Definities

Elke definitie noemt: **candles** (welk timeframe, alleen gesloten), **herkenbaar op**, **vervalt**, **dubbeltelling** (hoe één gebeurtenis
één keer telt). Drie timeframes: **4u** voor de context, **1u** voor de pools, **15m** voor sweep, shift en entry. Vullingen en uitkomsten
worden op **5m** gemeten.

> **Ontwerpkeuze: 4u / 1u / 15m.** Boek: structuur is fractaal en het hogere timeframe geeft de richting (hfdst. 7, 9); het boek noemt geen
> timeframes. Reden: 4u is het hoogste timeframe dat de motor al ophaalt (`range_sweep_live.fetch_bars`) en geeft een paar structuurbreuken
> per coin per week. 15m houdt sweep, shift en terugtest binnen enkele uren, zodat een limiet nog vult nadat hij gemeld is (5m-cyclus).
> 1u-pools zijn grover dan de 15m-ruis. Bij een andere keuze: met 5m komen er meer en kleinere setups, en kosten en vertraging wegen
> zwaarder in R. Met 1u voor de entry komen er minder trades, en het duurt langer voordat er een uitspraak mogelijk is.

### 4.1 Swing high en swing low

**Boek (hfdst. 8).** "A swing high is a candle whose high is higher than the candles on either side of it; a swing low is the mirror. [...]
mark them the same way every time."

**Definitie.** Swing low op candle *p* van timeframe T: `low[p]` is strikt lager dan de *k* candles links en lager of gelijk aan de *k* candles
rechts. Swing high gespiegeld. Dat is precies `trendlab._pivot_flags` (voor highs met `-high`).

| Timeframe | k | Herkenbaar op |
|---|---|---|
| 4u (context) | 2 | sluiten van candle *p + 2* (8 uur na het punt) |
| 1u (pools) | 3 | sluiten van candle *p + 3* |
| 15m (shift) | 2 | sluiten van candle *p + 2* (30 minuten) |

- **Vervalt:** nooit als punt. Wel als liquiditeit (zie 4.6) of als breukniveau (zie 4.2).
- **Dubbeltelling:** twee gelijke lows naast elkaar geven één swing low, de eerste. Dat volgt uit "strikt links, gelijk rechts" en is
  getoetst.

> **Ontwerpkeuze: k = 2 / 3 / 2, eerste van gelijke punten.** Boek: alleen "higher than the candles on either side" (dat is k = 1). Reden:
> met k = 1 wordt elke kleine schommeling een swing, en met k groter dan 3 komt de bevestiging te laat voor 15m. Gelijke toppen zijn volgens
> het boek de rijkste pools (hfdst. 13), dus mogen ze niet verdwijnen (`indicators._find_pivots` laat ze weg) en niet dubbel tellen
> (`breakretest._pivots` telt ze allebei). Bij een andere k: met een grotere k komen er minder en latere breuken en pools, met een kleinere k
> meer ruis.

### 4.2 BOS en CHoCH

**Boek (hfdst. 8).** "A Break of Structure (BOS) happens when price breaks the most recent swing point in the direction of the trend." "A
Change of Character (CHoCH) is the first break against the trend." Hfdst. 13: "The test is the close, not the touch."

**Definitie (per timeframe T).** Op elke gesloten candle *i*:
- **Breuk omhoog:** `close[i]` > de meest recente swing high die op het sluiten van *i* al herkenbaar was en nog niet gebroken is.
- **Breuk omlaag:** `close[i]` < de meest recente herkenbare, nog niet gebroken swing low.
- **Label:** een breuk in dezelfde richting als de vorige breuk heet **BOS**, een breuk tegen de vorige breuk in heet **CHoCH**. De eerste
  breuk in de data heeft geen label en zet alleen de richting.
- **Herkenbaar op:** het sluiten van candle *i*.
- **Vervalt:** n.v.t. (een gebeurtenis).
- **Dubbeltelling:** elke swing kan één keer gebroken worden; daarna telt hij niet meer als breukniveau. Een lont voorbij het niveau zonder
  slot is geen breuk (dat kan een sweep zijn, 4.7).

> **Ontwerpkeuze: breuk op het slot, zonder ATR-marge.** Boek: "the close, not the touch". Reden: dat is de letterlijke regel. Bij een andere
> keuze, bijvoorbeeld een marge van 0,25 ATR zoals Structuur: minder valse breuken en latere breuken.

### 4.3 Structuurrichting (bias)

**Boek (hfdst. 7).** "An uptrend is a market making higher highs and higher lows [...] neither = range." Hfdst. 8: "read BOS and CHoCH as a
running commentary on the trend."

**Definitie.** Bias op 4u = de richting van de laatste 4u-breuk (4.2). **Neutraal** zolang er nog geen breuk is, als de laatste breuk ouder is
dan 60 candles van 4u (10 dagen), of als de range vervalt (4.4). Bij een neutrale bias ontstaan geen nieuwe scenario's.
- **Herkenbaar op:** het sluiten van de 4u-breukcandle.
- **Vervalt:** bij de volgende 4u-breuk (die zet een nieuwe bias), na 60 candles zonder breuk, of bij een slot voorbij de verre rand van de
  range.
- **Dubbeltelling:** de bias is een toestand, geen gebeurtenis.

> **Ontwerpkeuze: bias uit de laatste breuk, niet uit HH/HL-tellen, en zonder displacement-eis op 4u.** Reden: "laatste breuk" is
> mechanisch en meteen bekend; HH+HL tellen geeft hetzelfde zodra er een breuk is, maar vraagt een extra regel voor "range". Displacement
> eisen we op 15m, waar het boek het in stap 4 vraagt. Bij een andere keuze, met displacement ook op 4u: minder scenario's en een strengere
> context. 60 candles is een keuze; bij een kortere termijn vervalt de bias vaker.

### 4.4 Dealing range, premium en discount

**Boek (hfdst. 9).** "A dealing range is simply the span between a significant swing low and a significant swing high." "Split the dealing
range in half at its midpoint — the equilibrium, the 50% level. [...] buy in discount, sell in premium."

**Definitie (long, op 4u).** Bij een breuk omhoog op candle *b* van swing high *s*:
- **Onderrand L** = de laagste low van de candles na *s* tot en met *b*: het dal waaruit de breuk kwam.
- **Bovenrand H** = de hoogste high vanaf *s* tot en met de laatst gesloten 4u-candle (H groeit mee als de koers hoger gaat).
- **Evenwicht EQ** = (L + H) / 2. **Discount** = prijs ≤ EQ, **premium** = prijs ≥ EQ.
- **Herkenbaar op:** het sluiten van *b*. H wordt bijgewerkt bij elke gesloten 4u-candle.
- **Vervangen:** bij elke volgende 4u-breuk (in welke richting ook), want die zet een nieuwe range.
- **Vervalt:** bij een 4u-slot onder L (dan is de bias neutraal tot de volgende breuk), of als de bias neutraal wordt (4.3).
- **Dubbeltelling:** de range heeft een id = (coin, richting, tijd van *b*). Eén range is hooguit één scenario (4.13).

> **Ontwerpkeuze.** Boek: "significant swing low and high", zonder te zeggen welke. Reden: het dal tussen de gebroken top en de breuk is het
> punt waar de breuk vandaan kwam; dat is mechanisch en meteen bekend. Bij een andere keuze, bijvoorbeeld de laatste bevestigde swing low:
> die ligt soms hoger, dus de range wordt smaller, discount kleiner en er komen minder scenario's.

### 4.5 Premium/discount als filter

**Boek (hfdst. 9, 25).** "A perfect PD array in the wrong half of the range is a trade to skip." Stap 5: "in the correct premium/discount
half".

**Definitie.** Een long-entry mag alleen als de **limietprijs** ≤ EQ van de 4u-range op het moment "entry beschikbaar". Een pool telt alleen
als hij tussen L en EQ ligt (4.6).

> **Ontwerpkeuze: alleen de 4u-range.** Boek: ook "a lower-timeframe discount within a higher-timeframe discount" (hfdst. 9). Reden: één
> range houdt de regels eenvoudig. Met een tweede range op 15m komen er minder entries en is er één regel meer zonder bewijs.

### 4.6 Liquiditeitspool en "onaangeraakt"

**Boek (hfdst. 13).** "A liquidity pool is a concentration of orders at an obvious level. The richest pools form at equal highs or equal
lows." Hfdst. 15: "an obvious pool that has not yet been raided is a stronger magnet than one already swept."

**Definitie (sell-side pool, voor long).**
- **Bron:** swing lows op 1u (k = 3, 4.1) uit de laatste 120 candles van 1u (5 dagen).
- **Gelijke lows:** swing lows binnen 0,1 ATR(1u) van elkaar vormen samen één pool. Het niveau is de laagste low van de groep.
- **Onaangeraakt:** geen 1u-candle na de herkenning van het (laatste) punt van de pool heeft een low ≤ het poolniveau. Een pool die
  geraakt is, is opgebruikt, ook als dat zonder sweep gebeurde.
- **Geldig voor het model:** onaangeraakt, L ≤ niveau ≤ EQ van de huidige 4u-range, en onder het slot van de laatste gesloten 15m-candle.
- **Herkenbaar op:** het sluiten van candle *p + 3* (1u) van het laatste punt van de groep.
- **Vervalt:** bij de eerste aanraking (sweep of niet), of als het punt ouder wordt dan 120 candles.
- **Dubbeltelling:** één groep is één pool. Een pool kan één keer gesweept worden.

> **Ontwerpkeuze.** Boek: "obvious level", zonder bron of tolerantie. Reden: 1u-swings zijn zichtbaar en niet de ruis van 15m. 0,1 ATR is een
> strakke "gelijk"-maat. Bij een ruimere tolerantie komen er meer samengevoegde pools en minder losse. 5 dagen houdt de lijst kort. Bij
> andere bronnen (dag-low, week-low) komen er minder, maar grotere pools.

### 4.7 Draw on liquidity (doel)

**Boek (hfdst. 15).** "The draw on liquidity is your judgement about which liquidity pool price is most likely being delivered toward right
now. [...] it sets both your direction [...] and your target." Hfdst. 14: "IRL and ERL frequently serve as entry and target for one another."
Hfdst. 26: "the primary target is always a real liquidity level". **Over POC of volumeprofiel zegt het boek niets.**

**Naakte POC (definitie `app/poc.py`, ongewijzigd).** De prijs met het meeste volume van een **gesloten** UTC-dag of ISO-week: bakken van
0,05% van de eerste open, het volume van elke gesloten 5m-candle gelijk verdeeld over de bakken van low tot high, de POC is het midden van de
zwaarste bak. Alleen periodes die volledig in de data zitten, binnen 14 dagen.
- **Herkenbaar op:** het einde van de periode (de POC van een dag bestaat pas om 00:00 UTC erna).
- **Naakt** zolang geen 5m-candle na de periode hem raakte (low ≤ POC ≤ high; een lont telt als geraakt). **Vervalt** als kandidaat bij die
  eerste aanraking, of na 14 dagen.
- **Dubbeltelling:** een dag- en een week-POC op dezelfde prijs zijn voor het doel hetzelfde niveau; het doel is een prijs, dus tellen ze
  niet dubbel.

**Definitie doel (long).** Kandidaten op moment B: de **bovenrand H** van de 4u-dealing range (externe liquiditeit), plus **elke naakte dag-
of week-POC boven de limiet**, herkend vóór moment B en dan nog naakt. **Het doel is de kandidaat die het dichtst boven de limiet ligt.**
Nooit een verdere kandidaat om een mooiere R:R te krijgen (zoals `zone_radar.obstacles`). **Besluit CEO 2026-11-02: geen R:R-eis**;
de R:R van het dichtste doel staat op de kaart.
- Op de kaart bij "scenario ontdekt" staan H en de naakte POC's tussen de koers en H als kandidaten. Bij "entry beschikbaar" wordt het doel
  **bevroren**. Een latere POC of een hogere H verandert het doel van een geplaatste entry niet.
- **Onaangeraakt:** H is per definitie de hoogste high sinds *s*; een POC telt alleen als hij naakt is. Raakt de koers vóór de vulling het
  bevroren doel, dan vervalt de entry ("weggelopen", 4.13).
- **Bewaard:** of het doel H of een POC was (en welke), als kenmerk.

> **Ontwerpkeuze: H als rand van de range; een naakte POC telt mee als die dichterbij ligt (besluit CEO om POC op te nemen).** Boek: de draw
> is een "judgement" over liquiditeitspools; een POC is een volumeniveau en geen pool van stops, en komt in het boek niet voor. Reden voor H:
> die volgt de structuur (bias) en is de externe liquiditeit waar het boek naar wijst. Reden voor de POC: de CEO wil POC in het ene model, en
> een naakt volumeniveau ligt op de weg naar H, dus het is het eerste niveau waar de koers kan reageren. Dat is dezelfde logica als het
> eerste obstakel van de Zone-radar. "Het dichtste" is mechanisch en kan geen R:R kiezen. Bij een andere keuze, met alleen H (POC alleen als
> kenmerk): grotere doelen, minder vaak geraakt, en minder entries die op de R:R-eis afvallen. Met een POC alleen als hij verder ligt dan H:
> zelden van invloed.

### 4.8 Sweep

**Boek (hfdst. 13).** "A sweep [...] pierces the level with a wick and then reverses — price pokes past the equal highs, triggers the orders,
and closes back below." "A run [...] closes decisively through the level and continues." Hfdst. 25, stap 3: sweep van sell-side liquidity
onder de koers, voor een long.

**Definitie (long, op 15m).** Voor een geldige pool met niveau P (4.6), vanaf de eerste 15m-candle na de herkenning van het scenario:
- **Prik:** candle *j* heeft `low[j]` ≤ P − 0,1·ATR(15m)[j].
- **Terug:** een candle *r* met *j* ≤ *r* < *j* + 6 sluit **strikt boven P**. "Terug" betekent dus een slot boven het poolniveau zelf, niet
  binnen een zone of boven een midden.
- **Uiterste X** = de laagste low van *j* tot en met *r*.
- **Run, geen sweep:** komt het uiterste vóór het slot terug meer dan 2,5·ATR(15m)[j] onder P, of sluit er binnen 6 candles geen candle boven
  P, dan is het een run. De pool is dan opgebruikt en het scenario wacht op een volgende pool.
- **Herkenbaar op:** het sluiten van *r*. Een weigering is pas definitief op het sluiten van candle *j* + 5 (getoetst: aan het eind van de
  data is een weigering voorlopig).
- **Vervalt:** n.v.t. (een gebeurtenis). Na de sweep loopt de klok voor de shift (4.9).
- **Dubbeltelling:** een pool wordt één keer gesweept of gerund. Prikt één candle door meerdere pools, dan telt de laagste pool die hij
  raakte; de andere zijn opgebruikt.

> **Ontwerpkeuze: dezelfde maten als de Zone-sweep (0,1 ATR, 6 candles, 2,5 ATR).** Boek: elke lont voorbij het niveau, en terug op het slot.
> Reden: 0,1 ATR voorkomt dat een aanraking van één tik telt. Zes candles laten een sweep over meerdere 15m-candles toe (anderhalf uur). Dit
> zijn de vaste constanten van `zonesweep`, zodat die code bruikbaar is en V2 dezelfde maat heeft. Bij een strengere keuze (slot terug in
> dezelfde candle) komen er minder sweeps, wel scherpere; bij een ruimere keuze meer, en ze lijken dan meer op gewone pullbacks.

### 4.9 Structuurverandering (shift)

**Boek (hfdst. 25, stap 4).** "Confirm a change of character on displacement in your intended direction." Hfdst. 8: "Often a reversal reads
as: liquidity swept, then CHoCH, then a new trend confirmed by BOS."

**Definitie (long, op 15m).**
- **Breukniveau B** = de meest recente 15m-swing high (k = 2) die op het sluiten van de prikcandle *j* al herkenbaar was (punt *p* met *p* + 2
  ≤ *j*). Dit is de top waaruit de daling naar de sweep kwam.
- **Shift** = de eerste 15m-candle *c* met *r* ≤ *c* ≤ *j* + 24 en `close[c]` > B.
- **Voorwaarde:** tussen *j* en *c* sluit geen 15m-candle onder X.
- **Label:** de motor bewaart of dit volgens de 15m-structuur (4.2) een CHoCH of een BOS was. Het label is beschrijvend en geen filter.
- **Herkenbaar op:** het sluiten van *c*.
- **Vervalt:** komt er geen shift binnen 24 candles (6 uur), of sluit de koers eerst onder X, dan is de sweep mislukt ("geen shift"). Het
  scenario wacht dan weer op een sweep van een andere pool.
- **Dubbeltelling:** één shift per sweep.

> **Ontwerpkeuze: breuk van de top vóór de sweep; label niet als filter.** Boek: "change of character". Reden: na een sweep van sell-side is de
> top waar de daling begon de natuurlijke CHoCH-lijn. Als de 15m-structuur toevallig al omhoog stond, is dezelfde breuk formeel een BOS. Een
> filter op het label zou een extra regel zijn zonder bewijs, en het label wordt toch gemeten. Bij een strengere keuze (alleen CHoCH) komen er
> minder entries. 24 candles is een keuze; bij een langer venster horen shift en sweep minder bij elkaar.

### 4.10 Displacement

**Boek (hfdst. 10).** "Displacement is a strong, purposeful move — a run of large-bodied candles travelling decisively in one direction,
usually leaving little overlap between them." "A break with displacement is intent." Hfdst. 18: displacement laat een fair value gap achter.

**Definitie (long, op 15m).** Displacement = een candle *m* met *j* ≤ *m* ≤ *c* waarvoor geldt: er is een rode candle *k* (close < open) met
*m* − 5 ≤ *k* < *m*, en `close[m]` − `high[k]` ≥ 1,0·ATR(15m)[m]. Neem de laatste rode candle vóór *m*. Dit is de order-blockregel van
`rangesweep.find_zones` (`DISP_BARS` = 5, `DISP_ATR` = 1,0), zonder het overlapfilter.
- **En:** de displacement moet een fair value gap achterlaten (4.11) waarvan de middelste candle tussen *k* + 1 en *m* ligt.
- **Herkenbaar op:** het sluiten van *m*, of het sluiten van de derde FVG-candle als die later komt.
- **Dubbeltelling:** per sweep telt de eerste *m* die aan alles voldoet; latere tellen niet.

> **Ontwerpkeuze: slot minstens 1 ATR voorbij het order block, plus een FVG.** Boek: "large-bodied", "little overlap", zonder maat. Reden:
> deze maat bestaat al in de code (`find_zones`) en is getoetst op vooruitkijken; de FVG-eis maakt "little overlap" meetbaar. Bij een
> strengere maat (1,5 ATR) komen er minder entries; zonder FVG-eis meer entries, met zwakkere shifts (wat het boek afraadt).

### 4.11 Fair value gap en order block; welke array

**Boek (hfdst. 18).** "the gap between the high of one candle and the low of the candle two positions later [...] In a bullish FVG, the first
candle's high sits below the third candle's low." Hfdst. 17: "An order block is the last opposing candle before a strong displacement move."
Hfdst. 25, stap 5: "the order block or fair value gap, ideally where both overlap". Hfdst. 20: "prefer the one with the most context".

**Definities (long, op 15m).**
- **FVG:** drie opeenvolgende candles *i* − 2, *i* − 1, *i* met `high[i−2]` < `low[i]`. Gat = (`high[i−2]`, `low[i]`). Herkenbaar op het
  sluiten van *i*.
- **Order block (OB):** de candle *k* uit 4.10, van `low[k]` tot `high[k]` (hele candle met lonten). Herkenbaar op het sluiten van *m*.
- **Welke FVG:** de laagste FVG van de displacement (middelste candle tussen *k* + 1 en *m*) die nog **ongevuld** is: geen 15m-candle na *i*,
  tot en met het moment "entry beschikbaar", had een low ≤ `low[i]`. Zijn alle FVG's al geraakt, dan is de terugtest al geweest vóór de
  melding en komt er geen entry ("terugtest al geweest").
- **Welke array:** overlappen OB en de gekozen FVG (gemeenschappelijk stuk met hoogte > 0), dan is de zone die overlap. Anders is de zone de
  FVG. Een OB alleen is nooit de zone (zonder FVG is er geen displacement, 4.10). Of er overlap was, wordt bewaard als kenmerk.
- **POC-samenval (kenmerk):** de zone (overlap, of anders de FVG) **of** het OB bevat een naakte dag- of week-POC (4.7) die op moment B
  herkenbaar en naakt was: zone-onder ≤ POC ≤ zone-boven. Bewaard als ja, nee of niet gemeten (geen POC-data voor de coin). **Alleen een
  kenmerk:** geen voorwaarde, geen volgorde, geen filter. Bewijs toont via `track_record.score_split` of trades met samenval anders uitkomen.
- **Dubbeltelling:** één zone per shift.

> **Ontwerpkeuze: POC-samenval als kenmerk, niet als voorwaarde.** Boek: niets over POC; wel "confluence [...] several independent reasons at
> one price" (hfdst. 20). Reden: een voorwaarde zonder bewijs maakt het model kleiner zonder dat we weten of het helpt. Een filter mag alleen
> als vooraf vastgelegde vergelijking, en de drie plaatsen daarvoor zijn al bezet (§6). Als kenmerk wordt het toch gemeten. Bij een
> voorwaarde komen er veel minder entries en is er geen vergelijking zonder. De overlap is exact (POC binnen de zone), niet binnen 0,3%
> zoals `poc.near` voor de Zone-radar: de zone is al een prijsgebied.

> **Ontwerpkeuze: de laagste ongevulde FVG; OB alleen via overlap.** Boek: geen regel bij meerdere FVG's. Reden: de laagste ligt het dichtst
> bij het order block, dus de kans op overlap is het grootst, en hij geeft de beste prijs. Bij de hoogste FVG: meer vullingen en een slechtere
> R:R.

### 4.12 Entry, stop en doel

**Boek (hfdst. 18, 26).** "often you enter at the edge of the gap". "An aggressive entry takes the trade as price first touches the array."
Stop: "just beyond the sweep extreme [...] a little beyond the wick, to allow for noise". Hfdst. 26: "many traders use two-to-one or better".

**Definities (long).**
- **Limiet** = de bovenkant van de zone uit 4.11 (de eerste rand die de koers bij een terugtest raakt).
- **Ruwe stop** = X − 0,25·ATR(15m) op candle *c*. **Stop** = `smc_eval.floor_stop(long, limiet, ruwe stop, min_pct=0,4)`: minstens 0,4% onder
  de limiet (verbreed, nooit geweigerd; CLAUDE.md).
- **Doel** = het bevroren doel uit 4.7 (H of een dichter gelegen naakte POC).
- **R:R** = (doel − limiet) / (limiet − stop), bewaard en getoond. **Besluit CEO 2026-11-02: geen minimum** (eerder: ≥ 2); de CEO kiest.
- **Discount-eis** = limiet ≤ EQ (4.5); anders "in premium".

> **Ontwerpkeuze: agressieve entry op de bovenrand, buffer 0,25 ATR, R:R minstens 2.** Reden: met de eerste aanraking (boek: "aggressive
> entry") meten we de vulbaarheid zo ruim mogelijk. 0,25 ATR is de buffer die Structuur en Zone-sweep (`wick_025`) al gebruiken. De
> ondergrens van 0,4% is gelijk aan `rangesweep.MIN_STOP_PCT`. De R:R van 2 noemt het boek als gangbaar. Bij een entry op het midden van de
> gap: minder vullingen en een betere R. Zonder R:R-eis (zoals de Zone-radar sinds 29 oktober): meer entries, met een kleiner doel per risico.
> Zie open beslissing 4.

### 4.13 Scenario, entry en annuleren

**Boek (hfdst. 25).** "each step gates the next [...] Only when all are present, in order, do you act." Hfdst. 15: "No clear draw, no trade."

**Scenario ontdekt (moment A).** Op het sluiten van een 15m-candle *t* geldt: de bias is long (4.3), de range is geldig (4.4), er is minstens
één geldige pool (4.6) binnen 6% onder het slot van *t*, en er is voor deze range nog geen scenario.
- **Herkenbaar op:** het sluiten van *t* (de eerste candle waarop dit alles waar is). Onthouden worden de range-id, de dichtstbijzijnde pool
  P0, de kandidaat-doelen op dat moment (H en naakte POC's, 4.7), en de R:R die V1 zou hebben (§6).
- **De kaart zegt waarop we wachten:** "Wacht op een sweep van P0 (of een lagere pool in discount), dan een 15m-slot boven de top ervoor met
  displacement, dan een limiet op de gap."
- **Toestanden:** `wacht_sweep` → `wacht_shift` → `entry` → afgerond. Een mislukte sweep of shift zet het scenario terug op `wacht_sweep`
  (de pool is opgebruikt).

**Entry beschikbaar (moment B).** Na een sweep (4.8), een shift (4.9) en displacement met een FVG (4.10, 4.11), en als de discount-eis klopt (4.12;
geen R:R-eis, besluit CEO 2026-11-02).
- **Herkenbaar op:** het sluiten van de laatste candle die nodig was (de latere van *c*, *m* en de derde FVG-candle).
- **Gepubliceerd op:** het moment dat kaart B in de app staat (`detected_at`). Dat is los van een push, die door het dagmaximum of de
  bundeling (§9) later of stil kan zijn. Uitvoerbaarheid en vertraging (§8) rekenen vanaf dit moment. Het tijdstip van een eventuele luide push
  wordt apart bewaard (`alert_timing`).

**Annuleren.**

| Wat | Wanneer | Eindstand |
|---|---|---|
| Scenario | 4u-breuk (nieuwe range of bias) | `context_weg` |
| Scenario | bias neutraal (60 candles zonder 4u-breuk, of een slot onder L) | `context_weg` |
| Scenario | geen geldige pool meer (alle geraakt of te oud) | `geen_pool` |
| Scenario | na een entry (gevuld of niet) | `afgerond` |
| Entry (limiet) | 24 candles van 15m (6 uur) na moment B zonder vulling | `vervallen` |
| Entry (limiet) | koers raakt het bevroren doel vóór de vulling | `weggelopen` |
| Entry (limiet) | nieuwe 4u-breuk vóór de vulling | `context_weg` |
| Entry (limiet) | koers al door de limiet bij publicatie | `niet_vulbaar` (geen marktorder) |

- **Dubbeltelling:** hooguit één scenario per (coin, range-id) en hooguit één entry per scenario. Een nieuw scenario kan pas met een nieuwe
  4u-range. Per coin is er dus hooguit één scenario tegelijk (de bias heeft één richting).

> **Ontwerpkeuze: één entry per range, geen marktorder na de terugtest.** Boek (hfdst. 23 over de Silver Bullet): "one window, one trade".
> Reden: zo kan één context niet meerdere trades opleveren die samen één weddenschap zijn. Bij meerdere entries per range: meer trades, maar
> sterk samenhangend, zodat de onzekerheid onderschat wordt. Zes uur geldigheid en 6% afstand zijn keuzes (6% is gelijk aan
> `zone_radar.MAX_DISTANCE_PCT`).

### 4.14 Vulling en uitkomst

- **Vulling (long):** de eerste 5m-candle die opent ná de publicatie en een low ≤ limiet heeft. Daarnaast bewaren we of de low strikt onder
  de limiet kwam (`door_limiet`). Een aanraking op de prijs zelf is niet zeker gevuld.
- **Uitkomst:** zoals `level_check` (stop of doel, alleen candles na de vulling); stop en doel in één candle telt als stop
  (`AMBIGUOUS_NOTE`).
- **Tijdslimiet:** staat een trade na 7 dagen nog open, dan sluit de meting op het slot van de 5m-candle (`tijd`). Die R wordt apart getoond.
  Winrate en hoofd-R tellen alleen doel en stop (Bewijs blijft eerlijk: `tijd` staat ernaast en valt niet weg).

## 5. De kaart: twee momenten

Eén kaart per scenario, in één eigen tab (zie §9).

- **Moment A, "Scenario ontdekt":** coin, richting, range (L, EQ, H), de dichtstbijzijnde pool, het doel en de zin waarop we wachten. Met het
  tijdstip waarop het herkenbaar was. Daarna toont de kaart de stap waarin het scenario nu staat (sweep / shift / terugtest), elk met zijn
  eigen tijdstip zodra die stap herkenbaar was.
- **Moment B, "Entry beschikbaar":** limiet, stop, doel en R:R, met de drie stappen (`chance_steps`) en de order-checklist.
- **Apart gemeten:** voor A de trechter (hoeveel scenario's kwamen bij sweep, shift, entry en vulling, en hoeveel liepen naar het doel
  zonder ons) en de uitkomst van V1 (een limiet op het moment A). Voor B de uitkomst van het hoofdmodel. Zo is te zien of wachten op
  bevestiging iets toevoegt.

## 6. Vergelijkingen (vooraf vast)

Precies drie vergelijkingsarmen naast het hoofdmodel, het maximum. Ze lopen stil mee: nooit een melding, geen eigen tab, geen kaart voor
leerlingen.

| Arm | Wat | Stop en doel |
|---|---|---|
| **H** (hoofdmodel) | §4 | §4.12 |
| **V1: vroege limiet** | Op moment A een limiet op het niveau van de dichtstbijzijnde pool P0, zonder sweep, shift of FVG. Geldig zolang het scenario leeft. Eén per scenario. | Stop P0 − 1,0·ATR(1u), dan `floor_stop` 0,4%. Doel volgens 4.7, maar vanaf de V1-limiet P0 en met de kandidaten van moment A (bevroren). Geen R:R-eis (besluit CEO 2026-11-02). |
| **V2: Zone-sweep (referentie)** | De live Zone-sweep (ZS_1H, ZS_2H, ZS_4H), ongewijzigd, zoals Bewijs hem meet, over dezelfde periode en coins; zonder eigen tab en zonder meldingen. | Zoals live: met doel via `level_check`, zonder doel via de referentie-uitgang (apart gelabeld). |
| **V3: POC-radar (referentie)** | De live POC-radar, ongewijzigd, zoals Bewijs hem meet, over dezelfde periode en coins; zonder eigen tab en zonder meldingen (besluit CEO). | Zoals live: met doel via `level_check`, zonder doel via de referentie-uitgang (apart gelabeld). |

**Totaal: vier toetsen.** (1) H netto R > 0; (2) V1 − H; (3) V2 − H; (4) V3 − H. Geen tijdvariant (besluit CEO), geen POC-samenval als
filter (4.11) en geen andere combinaties, ook niet achteraf. Wie later iets anders wil toetsen, schrijft een nieuwe preregistratie.

> **Waarom V3 meetelt als vergelijking.** De POC-radar wordt naast het model gelegd en we trekken er een conclusie uit (is het model beter of
> slechter dan wat er al liep?). Dat is een toets, en elke toets vergroot de kans op een toevallige winnaar, dus telt hij mee in het maximum en
> in de correctie (§8). V2 en V3 zijn referenties: ze lopen al en worden niet gewijzigd.

> **Ontwerpkeuze V1-stop: 1,0 ATR(1u) onder de pool.** Reden: zonder sweep is er geen uiterste. 1 ATR(1u) ligt binnen de maximale sweep-diepte
> van 2,5 ATR(15m), zodat de stop vergelijkbaar is. Bij een krappere stop vult V1 even vaak, maar wordt hij vaker uitgestopt.

## 7. Bestaande bouwstenen (inventaris)

Gecontroleerd met `tests/hespulse_model/test_bouwstenen.py` (16 tests, alleen lezen, synthetische candles). De prefix-toets: de uitkomst op
de eerste *n* candles moet gelijk zijn aan die op de hele reeks, beperkt tot wat vóór *n* bekend was. Faalt hij, dan kijkt de functie
vooruit. De bouwstenen zelf zijn niet gewijzigd.

| Bouwsteen | Wat hij herkent, vanaf wanneer | Vooruitkijken? | Dubbeltelling? | Oordeel |
|---|---|---|---|---|
| `trendlab._pivot_flags` | Swing low (en high via `-high`): strikt links, gelijk rechts, bekend op *p + n* | Nee (prefix-toets, n = 2 en 3) | Gelijke punten: alleen het eerste | **Bruikbaar** voor 4.1 |
| `breakretest._pivots` | Swing high/low met k = 3 via een gecentreerd venster, bekend op *p + 3* | Nee | **Ja**: twee gelijke toppen naast elkaar zijn allebei een pivot | **Bruikbaar met aanpassing**: niet voor pools; gebruik `_pivot_flags` |
| `breakretest.find_breaks` | Breuk van een lijn of horizontale door twee 30m-swings, met een slot 0,25 ATR voorbij, op de breukcandle | Nee | Eén per paar zwaaipunten, maar een nieuw paar kan binnen 8 candles op bijna hetzelfde niveau opnieuw breken (getoetst) | **Niet bruikbaar** voor BOS/CHoCH: hij breekt een lijn door twee punten, niet het laatste swingpunt |
| `breakretest.find_choch` | Hogere bodem L2 na de laagste bodem L1 van 40 candles, dan een slot boven de top ertussen (30m) | Nee | Eén per paar bodems | **Niet bruikbaar** voor stap 4: hij wacht op een tweede, hogere bodem (later dan het boek) en eist geen displacement. De boekhouding (`known_high`/`known_low` met *q = i − K*) is het patroon om na te volgen |
| `breakretest.known_levels` | Bevestigde swingniveaus op candle `bar` (als doel) | Nee | Erft de dubbeltelling van `_pivots` | **Bruikbaar met aanpassing**: hij weet niet of een niveau al geraakt is (getoetst); voor 4.6 is een eigen poolfunctie nodig met "onaangeraakt" en gelijke-lows-groepering |
| `rangesweep.find_zones` | Order block: de laatste tegengestelde candle *k*, hooguit 5 vóór een slot *m* minstens 1 ATR voorbij; bekend op *m* | Nee (`broken_idx` kijkt vooruit, maar wordt alleen met de eigen index vergeleken; getoetst) | Eén zone per OB-candle; een zone die meer dan 50% overlapt met een actieve zone valt weg | **Bruikbaar met aanpassing**: de regel is precies 4.10, maar het overlapfilter kan het OB van onze displacement weglaten. Nodig: dezelfde regel zonder overlapfilter, gefilterd op *j* ≤ *m* ≤ *c* |
| `rangesweep.zone_active` | Zone actief van `known_idx + 1` tot de breuk of `max_age` | Nee (getoetst) | n.v.t. | **Bruikbaar** |
| `zonesweep._scan_zone` | Prik ≥ 0,1 ATR voorbij de rand, slot terug binnen 6 candles, niet dieper dan 2,5 ATR; één setup per zone, daarna "zone had al een setup" | Nee voor setups; **een weigering aan het eind van de data is voorlopig** (getoetst) | Eén setup per zone (getoetst) | **Bruikbaar met aanpassing**: een pool als zone met `low = high = P` en 15m-candles; een weigering pas als definitief behandelen op *j* + 5 |
| `indicators.find_fair_value_gaps` | Drie-candle-gat (definitie gelijk aan het boek), alleen in de laatste 40 candles | Nee (gebruikt alleen het meegegeven venster) | Geeft geen index terug; een gevuld gat blijft in de lijst (getoetst) | **Niet bruikbaar zoals hij is**: de definitie nemen we over, maar we hebben de index, het tijdstip en "ongevuld" nodig (4.11) |
| `indicators.find_order_blocks` | Laatste tegengestelde candle vóór een candle met een bereik ≥ 2× het gemiddelde van de 10 ervoor | Nee | **Ja**: displacement over twee candles geeft hetzelfde OB twee keer (getoetst) | **Niet bruikbaar**; gebruik de regel van `find_zones` |
| `indicators.find_confluence_zone` | De eerste overlap van FVG en OB, nieuwste eerst, zonder index | Nee | n.v.t. | **Niet bruikbaar** (geen tijd, geen koppeling aan één displacement) |
| `indicators._find_pivots` | Swing strikt hoger dan 3 candles aan beide kanten, bekend op *i + 3* | Nee | Gelijke toppen worden **geen** pivot (getoetst): precies de rijkste pools van het boek verdwijnen | **Niet bruikbaar** voor pools of breuken |
| `poc.new_levels` / `PocLevel` / `first_touch` | Dag- en week-POC van gesloten periodes op gesloten 5m-candles, bekend aan het einde van de periode; `touched_at` is de eerste candle daarna die hem raakte | Nee (prefix-toets: een POC verschijnt pas na zijn periode, en 'naakt' op moment *t* hangt alleen af van candles vóór *t*) | Een dag- en week-POC kunnen op dezelfde prijs liggen; voor een doelprijs en een ja/nee-kenmerk maakt dat niet uit | **Bruikbaar** voor 4.7 en 4.11 (de live motor bewaart ze al in `poc_levels`, met `touched_at`) |
| `poc_radar_live.samenval` / `poc.near` | Ligt één prijs binnen 0,3% van een naakte POC, uit de opgeslagen niveaus | Niet apart getoetst (leest `poc_levels`) | n.v.t. | **Bruikbaar met aanpassing**: het model vraagt "POC binnen de zone", niet "binnen 0,3% van één prijs"; zelfde opgeslagen niveaus, andere vergelijking |
| `smc_eval.floor_stop` | Stop minstens `min_pct` van de prijs | n.v.t. (zuiver) | n.v.t. | **Bruikbaar** (met vaste `min_pct` 0,4, zoals `rangesweep.MIN_STOP_PCT`) |

**Meting die er al is en past:**
- `app/excursion.py` (MAE/MFE op 5m-candles vanaf de vulling) en `outcome_measure.record_excursion`.
- `app/funding.py` + `outcome_measure` (funding in R, 'onbekend' bij falen, nooit 0) en `track_record._cost_r` (0,06% per rondreis plus
  funding).
- `app/latency.py` en de tabel `alert_timing` (vertraging per verzonden push, mediaan en 90e percentiel via `scripts/vertraging.py`).
- `app/end_reason.py` (eindstand in gewone woorden; de nieuwe standen uit 4.13 hebben elk een tekst nodig, anders faalt
  `tests/test_basis_afsluiten.py`).
- `app/replay/stats.py`: `week_key`, `cluster_bootstrap_mean`, `cluster_bootstrap_diff`.
- `track_record.summarize` (netto, bruto, kosten, `ambiguous`), `equity_curves`.

**Wat ontbreekt (te bouwen, alleen meting):**
1. **Vulbaar na publicatie:** de fractie entries waarbij de limiet bij publicatie nog aan de goede kant van de koers lag en daarna gevuld
   werd. Nu meet niemand dit.
2. **Effectief aantal onafhankelijke trades** (§8).
3. **Maximale verliesreeks en drawdown in R**, en de verwachte drawdown bij hetzelfde gemiddelde (herschikking).
4. **Resultaat zonder de beste 5%.**
5. **Trechter per scenario** (A → sweep → shift → B → vulling → uitkomst), met tijdstempels.
6. **Opslag voor een stille arm met een andere instap (V1).** `shadow_results` is gebouwd voor parametervarianten van dezelfde motor
   (`shadow.PARAMS`). Voor V1 is een eigen tabel nodig, of een uitbreiding die de regels van de schaduw (geen melding, geen signals-rij)
   volgt.
7. **Een interval dat bij vier toetsen past:** `cluster_bootstrap_mean`/`_diff` geven een vast 95%-interval. Nodig is 98,75% (Bonferroni
   voor 4 toetsen), dus een parameter voor het niveau.

## 8. Beoordeling (vooraf vastgelegd)

Er is geen enkele grens die op zichzelf beslist. Elke maat wordt per arm getoond, en een besluit vraagt dat ze samen kloppen.

**Maten (per arm).**
1. **Uitvoerbaarheid:** de fractie vulbaar na publicatie (ontbreekt nu, §7); de fractie gevuld; mediaan en 90e percentiel van de vertraging
   van herkenbaar (`known_at`) tot de kaart in de app (`detected_at`), en apart tot een luide push (`alert_timing`); het aandeel `niet_vulbaar` en `terugtest al geweest`.
2. **Netto R na kosten:** bruto R uit doel of stop, min 0,06% per rondreis gedeeld door de stopafstand, min de gemeten funding in R
   (`track_record._cost_r`, zoals Bewijs). Trades met funding 'onbekend' worden geteld en apart genoemd.
3. **Onzekerheid:** interval van het gemiddelde netto R per trade met een bootstrap per ISO-week (`stats.cluster_bootstrap_mean`), op
   **98,75%** (95% met Bonferroni voor 4 toetsen). Voor V1 − H, V2 − H en V3 − H: `cluster_bootstrap_diff` op hetzelfde niveau.
4. **Effectief aantal onafhankelijke trades:** trades in dezelfde richting waarvan de looptijden (vulling tot uitkomst) elkaar overlappen,
   ook via een keten, vormen één cluster. N_eff is het aantal clusters. We tonen N, N_eff en het gemiddelde R per cluster.
5. **Verliesreeks en drawdown:** de langste reeks stops op volgorde van uitkomst en de grootste daling van de cumulatieve netto R. Daarnaast
   het 95e percentiel van de grootste daling bij 2000 willekeurige herschikkingen van dezelfde trades. Ligt de echte daling erboven, dan
   wordt dat gemeld ("groter dan toeval bij dit gemiddelde").
6. **Uitschieters:** het gemiddelde netto R zonder de beste 5% trades (naar boven afgerond, minstens één).
7. **Stabiliteit:** het gemiddelde netto R in de eerste en de tweede helft (op tijd).
8. **Beschrijvend, geen toets:** MAE/MFE (`excursion`), eindstanden (`end_reason`), de kenmerken OB-overlap, POC-samenval en doel H of POC, en het label
   CHoCH/BOS (via `track_record.score_split`; nooit een filter).

**Periodes.**
- **Ontwikkelperiode:** alleen voor de technische controle van de detector (getekende kaarten, §10 poort 2). Dat zijn de candles van 1
  januari tot en met 31 maart 2025. Uitkomsten uit deze periode tellen nergens mee.
- **Labtoets:** één run over alle andere candles tot de bevriesdatum (de coins uit `config.FIXED_COINS`, zo ver terug als de perps gaan),
  met de zelfde code als live. Eén keer draaien, niets afstellen.
- **Live vooruit:** vanaf de start van de motor. Dit is de periode die voor niets anders gebruikt is. Het besluit leunt op deze periode.

**Eerste evaluatie: na 50 afgeronde trades per arm (H en V1).** Alleen technisch en uitvoerbaarheid, geen besluit over het voordeel:
- Kloppen 20 willekeurige kaarten met de definities (elk moment op het juiste tijdstip, geen dubbele scenario's)?
- Vulbaar na publicatie en de vertraging: is de mediaan van de vertraging kleiner dan één 15m-candle?
- Kosten in R: is de mediaan van de kosten per trade hoogstens 0,10R (dezelfde grens als `stopquality.MAX_MEDIAN_COST_R`)? Zo niet, dan is de
  stop te krap voor de kosten, en dat wordt gemeld.
- Uitkomst: "technisch in orde" of een lijst met fouten. Fouten in de code worden hersteld. Regels worden niet veranderd.

**Besluit: op zijn vroegst** bij ≥ 150 afgeronde trades van H, ≥ 12 ISO-weken met trades en N_eff ≥ 60.
- **"Werkt in proef"** (publiek label, nog geen "bewezen"): de ondergrens van het 98,75%-interval van H ligt boven 0, het gemiddelde is in
  beide helften boven 0, het gemiddelde zonder de beste 5% is ≥ 0, de labtoets over de eigen periode is niet negatief (gemiddelde ≥ 0), en
  de vulbaarheid na publicatie is minstens 50%.
- **"Negatief":** de bovengrens van het interval ligt onder 0. Dan stelt de CEO de meldingen stop; de meting loopt door.
- **Anders: doorlopen** tot 300 afgeronde trades of 26 weken. Is er dan nog geen uitspraak, dan is de conclusie "geen aantoonbaar voordeel".
- **Vergelijkingen:** ligt het interval van V1 − H boven 0, dan voegt wachten op bevestiging niets toe (de vroege limiet is beter). Ligt het
  onder 0, dan voegt bevestiging iets toe. V2 − H en V3 − H zeggen alleen of het nieuwe model beter of slechter is dan de huidige
  referenties. Er wordt
  niets automatisch omgezet; elke wissel is een besluit van de CEO met een nieuwe preregistratie.

## 9. Interface en meldingen

**Besluit CEO (2026-11-02): compacte meldingen.** Er waren veel te veel meldingen. Voor dit model geldt daarom:

- **Moment A (scenario ontdekt): geen luide push.** Alleen zichtbaar in de app (kaart in de tab), hoogstens een stille melding.
- **Eén luide melding per entry.** Alleen moment B (entry beschikbaar) óf de vulling geeft een luide push, niet allebei (welke van de twee is
  open beslissing 3). De andere is stil (alleen in de app en op de meldingenpagina).
- **Dagmaximum per gebruiker:** standaard 8 luide pushes per dag. Elke luide push telt mee, ook die van andere soorten. Boven het maximum
  wordt de melding stil.
- **Bundeling:** vallen er meerdere luide meldingen in één scancyclus (5 minuten), dan gaan ze als één push met een regel per kaart. Een
  bundel telt als één luide push.
- **Vergelijkingsmodellen melden nooit**, ook niet stil: V1 loopt alleen in de meting, V3 (POC-radar) heeft geen tab en geen meldingen
  meer (besluit CEO), en V2 (Zone-sweep) meldt als vergelijkingsmodel ook niet meer en verliest zijn tab (zelfde besluit).

**Hoe het model aansluit.** Een andere agent bouwt deze regels (dagmaximum, bundeling, luid of stil) nu al in de gedeelde meldingslaag voor
de huidige motoren. Het model bouwt **geen eigen** maximum of bundeling. Het levert per gebeurtenis aan die laag: de soort (`hp_model`), het
moment (`scenario`, `entry` of `vulling`), of het luid mag (alleen het gekozen moment uit open beslissing 3; `scenario` nooit), de kaartsleutel
(het anker van de kaart) en de tekst. De laag beslist dan over het maximum en de bundeling, voor alle soorten samen, binnen `push_policy` en
de pauzeknop. Wat de laag stil maakte, wordt geteld (luid gemeld, stil door het maximum, gebundeld), zoals `cap_holds` dat nu voor de
dagcaps doet.

**Meting los van de push.** De uitkomst van het model hangt niet af van wie een push kreeg: elke entry wordt gemeten vanaf het moment dat kaart B
in de app stond (4.13). Op Bewijs staat daarnaast hoeveel entries luid, stil of gebundeld gemeld zijn, zodat te zien is of het maximum
kansen wegdrukt.

**Verder:**
- **Eén tab.** Het hoofdmodel krijgt één eigen tab op Kansen met de kaarten uit §5.
- **Gevuld** wordt het een gewoon signaal (voorstel: `trade_type = 'hp_model'`), ongetest, met een eigen rij op Bewijs, `chain_it=False`
  tot de CEO anders beslist.
- **V1** loopt stil: geen kaart voor leerlingen, geen journaal, geen signals-rij. De CEO ziet de stand op Bewijs.
- **Zone-sweep (V2):** meldt niet meer en heeft geen eigen tab; hij blijft scannen en meten, met zijn rij op Bewijs en het volgen van
  lopende trades.
- **Structuur en Zone-radar:** niet uitgezet. Of ze nog melden, is open beslissing 2; hun data, Bewijs en lopende trades blijven. Melden ze
  nog, dan vallen ze onder hetzelfde dagmaximum.
- **POC-radar:** geen eigen tab en geen meldingen meer (besluit CEO, §3). Hij blijft scannen en meten als V3; zijn rij op Bewijs blijft voor
  de CEO, en lopende trades worden verder gevolgd. De POC zelf komt in de kaart van het model: kandidaat-doelen bij moment A, het gekozen doel
  en het kenmerk POC-samenval bij moment B.
- **Geen tijdfilter in de weergave:** geen kill-zonevensters op kaarten of in de tekst.

## 10. Volgorde na goedkeuring

1. **Bevriezen:** de CEO keurt dit document en de open beslissingen goed; de datum komt bovenaan.
2. **Bouwen** (zuivere functies onder `app/`, met tests): pools, 4u-context, sweep, shift, displacement, FVG-keuze, de toestand van het
   scenario. Elke functie krijgt een prefix-toets zoals in `tests/hespulse_model/test_bouwstenen.py` en een dubbeltellingstoets.
3. **Poort: getekende kaarten.** 30 willekeurige kaarten uit de ontwikkelperiode, getekend tot moment B. Minstens 80% klopt met de definities
   volgens de CEO. Dit toetst de code, niet de winst.
4. **Live** (open beslissing 1) en tegelijk **één labrun** (§8).
5. **Eerste evaluatie** na 50 trades per arm; **besluit** volgens §8.

## 11. Eerlijkheid

- **Het boek bevat geen bewijs.** Het is lesmateriaal met schematische plaatjes. Het geeft geen steekproef, geen kosten en geen uitkomsten,
  en zegt zelf dat tijden en instrumenten per handelaar te controleren zijn. Dat een stap logisch klinkt, zegt niets over netto R.
- **Onze huidige cijfers zijn geen argument.** De nachtexport van 2 november 2026 geeft de Zone-sweep +0,20R netto per trade over 121
  afgeronde trades "in 30 dagen". Dat is om drie redenen geen bewijs, voor of tegen:
  1. **Referentie-uitgang.** Kaarten zonder doel krijgen hun R bij een referentie-uitgang (`range_sweep_live.follow_trade`). Dat is een
     meting, geen uitgang die een handelaar echt had genomen. Deze R telt dus niet als gewone doel-of-stop-R.
  2. **Samenhangende trades.** Veel prikken vallen in dezelfde marktbrede beweging (de voorbeelden uit de preregistratie van de Zone-sweep
     waren al één bounce). 121 trades zijn dan veel minder dan 121 onafhankelijke waarnemingen.
  3. **Korte periode.** Alle 139 kaarten vallen ook in het venster van 7 dagen: de motor draait live sinds 27 oktober. Het is dus één week
     markt. De 7- en 30-dagencijfers van Structuur (−0,32R en +0,15R) laten zien hoe snel zo'n gemiddelde omslaat.
  **POC-radar** staat op +0,57R netto per trade over **maar 13 afgeronde trades**. Dat is te weinig om iets te concluderen: een of twee
  trades meer of minder verschuiven het gemiddelde sterk, en ook hier gelden de referentie-uitgang voor kaarten zonder doel en de korte
  periode. Dat de POC in het model komt, is een besluit van de CEO en geen gevolg van dit cijfer. Geen van deze cijfers is een reden om iets
  aan of uit te zetten; daarom wordt in §9 niets definitief uitgezet.
- **Eén hoofdmodel, vier toetsen, vooraf vast.** Bij meer varianten wordt een toevallige winnaar waarschijnlijk. Alle getallen in §4 zijn
  keuzes zonder afstelling. Een getal verandert alleen via een gedateerd aanvullend besluit, met reden, vóór er uitkomsten zijn.
- **Ongetest** blijft het label tot §8 iets anders zegt.

## 12. Open beslissingen voor de CEO

| # | Beslissing | Aanbevolen keuze | Reden |
|---|---|---|---|
| 1 | Live na poort 3 (getekende kaarten) en de labrun tegelijk, of live pas na een geslaagde labrun? | **Live na poort 3, labrun tegelijk**, label ongetest | De live periode is de enige die voor niets gebruikt is; wachten op het lab kost weken zonder extra eerlijkheid, omdat er niets wordt afgesteld. |
| 2 | Stoppen Structuur en Zone-radar met pushen en verdwijnt hun tab, zoals bij de Zone-sweep en de POC-radar (wel meten, niets uitzetten)? | **Ja: alleen het hoofdmodel meldt**; de rest meet stil en blijft voor de CEO zichtbaar op Bewijs | Eén tab die meldt is de opdracht. Stil meten houdt hun geschiedenis en Bewijs intact; uitzetten kan later altijd nog, terugdraaien van verloren meting niet. |
| 3 | Welk moment krijgt de ene luide melding: entry beschikbaar (B) of de vulling? | **B (entry beschikbaar)**; de vulling stil | Bij B moet je iets doen (de limiet zetten); bij de vulling staat de order er al. Een luide melding na de vulling komt te laat om nog te handelen. |
| 4 | R:R minstens 2 (boek, hfdst. 26) of geen minimum (zoals de Zone-radar sinds 29 oktober)? | **Minstens 2** | Het boek noemt het als filter, en zonder minimum telt het model entries mee die het boek zelf overslaat. |
| 5 | Leerlingen meteen, of eerst alleen de CEO? | **Eerst alleen de CEO** tot de eerste evaluatie (50 trades), daarna publiek als ongetest | De eerste evaluatie controleert de code en de vulbaarheid; fouten horen niet bij leerlingen te landen. |

---

## Aanvullend besluit CEO 2026-11-02 (avond): instaptype B, "lagere top" (vastgelegd, nog niet gebouwd)

**Aanleiding.** De CEO: "Je hoeft niet per se een sweep, kijk nu was de entry bovenin toch perfect" (PUMP 4u, 18:26) en een ZEC-short op 15m
(3 november, 01:26). Beide zijn shorts vanaf een lagere top in een dalende structuur, zonder sweep van een eerdere top. Beide voorbeelden
zijn uitgekozen winnaars. Ze verklaren waarom de regel bestaat, niet dat hij werkt (`docs/onderzoek/cases/`).

**Regel (short; long gespiegeld als "hogere bodem").** Alleen de trigger verandert. De rest is §4 ongewijzigd.
1. *Context:* dezelfde 4u-bias en range L/H/EQ (4.3, 4.4), en de BTC-poort (B-2026-11-02-10).
2. *Trigger in plaats van de sweep (4.8):* een bevestigde 1u-swing high (4.1, K = 3, herkenbaar op het sluiten van de derde candle
   rechts) die
   - lager ligt dan de vorige bevestigde 1u-swing high binnen dezelfde range;
   - boven EQ ligt (premium);
   - niet boven H kwam.

   Het uiterste X is die top.
3. *Daarna gelijk aan type A:* shift (4.9), displacement (4.10), FVG of OB-overlap (4.11), limiet, stop X + 0,25·ATR met de vloer van 0,4%,
   doel de dichtste van range-rand en naakte POC (4.12, 4.7), geldigheid en annuleren (4.13), vulling en uitkomst vanaf de vulcandle met 7
   dagen tijdslimiet (4.14).
4. *Eén entry per range* (4.13): A en B delen de range. De eerste die moment B haalt, telt; de andere vervalt. Het entrytype staat op de
   kaart: "na sweep" of "lagere top".

**Meting.** B is een eigen arm in `model_measure` met dezelfde maten en beslisregel als §8. B wordt niet opgeteld bij het hoofdgetal van A
voordat B op zichzelf een eerste beoordeling heeft.

**Nog door de CEO te kiezen.** Krijgt B meteen luide meldingen, net als A, of loopt hij eerst stil tot de eerste beoordeling?

**Nooit.** Constanten afstellen op deze twee voorbeelden. K, de premiumgrens EQ en de 0,25 ATR liggen hierboven vast.

**Aanvulling 2026-11-02 (18:50), vóór de bouw en vóór enige uitkomst.** Een BTC-voorbeeld van de CEO (`cases/2026-11-02-btc-4u-1847.md`)
had zijn lagere top onder EQ. De premium-eis van type B is dus een keuze die de data moet toetsen.

Daarom loopt naast B één extra arm stil mee: **B0**. B0 is gelijk aan B, maar zonder de eis "boven EQ". De andere voorwaarden blijven:
lager dan de vorige top en niet boven H.

- B0 meldt nooit.
- De vergelijking B tegen B0 volgt dezelfde regel als de schaduwvarianten (`shadow.verdict`): minstens 50 per arm, beide helften, en een
  interval per week boven 0.
- Er komen geen verdere varianten bij.

---

## Aanvullend besluit CEO 2026-11-03: alle instappunten op één kaart, de gebruiker kiest

**Besluit.** "Ik wil gewoon alles op 1 grafiek zien [...] dat er 3/4 verschillende entry punten zijn en dat de gebruiker gewoon zelf kan
aanklikken welke waarop is gebaseerd." Een scenario toont voortaan elk instappunt dat de regels vinden, elk met zijn eigen basis, limiet,
stop, doel en stand.

De instappunten, alle vooraf vast:

| Code | Naam op de kaart | Basis | Regel |
|---|---|---|---|
| A | Na sweep | Sweep van een pool, shift, gap | §4.8–4.12, ongewijzigd |
| B | Lagere top | Lagere 1u-top in premium, shift, gap | Aanvullend besluit 2026-11-02 avond, ook voor long (hogere bodem in discount) |
| V1 | Vroege limiet op de pool | Limiet op de pool bij moment A | §6, stop 1,0 ATR(1u), ongewijzigd |
| P | POC-limiet | Limiet op de dichtste naakte dag- of week-POC aan de juiste kant | Hieronder |

**P (short; long gespiegeld).**
- Bij moment A de dichtste naakte POC (bekend aan het einde van zijn periode, nog niet aangeraakt) boven het slot van 15m.
- De POC moet in premium liggen (vanaf EQ tot en met H) en binnen 6% van het slot.
- Limiet op de POC, stop 1,0 ATR(1u) erboven met de vloer van 0,4% (zoals V1).
- Doel: de dichtste kandidaat voorbij de limiet (§4.7).
- Geldig zolang het scenario leeft, net als V1.
- Is er geen naakte POC bij moment A, dan krijgt het scenario geen P.

Dit is onze toetsbare lezing van de vPOC-short (`cases/2026-11-btc-1u-vpoc.md`). Een vPOC van een periode die de beweging zelf bevat, telt
niet: dat is vooruitkijken.

**B (uitwerking voor de bouw).** De trigger is een 1u-swing low (long-frame; short gespiegeld) die bekend wordt op het sluiten van de derde
candle rechts. Hij moet aan vier eisen voldoen:
- hoger liggen dan de vorige bekende 1u-swing low sinds de swing van de range;
- tussen L en EQ liggen (B0: tussen L en H);
- binnen 6% van het slot liggen;
- nog niet gevolgd zijn door een slot onder hem.

Het uiterste X is die low. Daarna geldt hetzelfde als bij A:
- de top om te breken: de laatste 15m-top vóór de 15m-candle met X;
- de shift binnen 24 candles van 15m na X, en een slot onder X maakt de poging ongeldig;
- displacement, gap, limiet, stop X − 0,25·ATR met de vloer, en doel zoals bij A.

Per scenario hoogstens één B-entry en één B0-entry. B loopt naast A en beëindigt het scenario niet. Eindigt het scenario, dan stopt ook het
zoeken naar B.

**Meldingen.** Alleen A houdt zijn luide melding (besluit 3). B, V1 en P staan op de kaart zonder push. Een melding per extra instappunt
zou het aantal meldingen weer verveelvoudigen (B-2026-11-02-04). Dat is een keuze die makkelijk om te zetten is.

**Meting.** Elk instappunt is een eigen arm met dezelfde vul- en uitkomstregels (§4.14) en dezelfde maten (§8). De keuze van de gebruiker
verandert niets aan de meting: elk punt wordt gevolgd, ook als niemand hem neemt. B0 meldt nooit en staat niet op de kaart.

---

## Aanvullend besluit CEO 2026-11-03: richting top-down van de dag, live (herziet 4.3 voor de richting)

**Aanleiding.** PUMP 1–2 november (`docs/onderzoek/cases/2026-11-02-pump-1u-1815.md`). De 4u-bias "laatste breuk" sloeg door een herstel om naar
long terwijl de dag en BTC daalden. Het model zocht toen alleen longs en zag de short bovenin niet. De CEO: "ja meteen live op jouw voorstel".

**Regel (vooraf vast).**
1. *Richting:* de laatste breuk op de dag, met dezelfde breukregel als 4.2. Pivots met 2 candles zoals op 4u, alleen gesloten
   dagcandles, herkenbaar op het sluiten van de breukcandle.
   - Breuk omhoog: alleen long-scenario's.
   - Breuk omlaag: alleen short-scenario's.
   - Geen breuk in de data: geen scenario.
   Wisselt de dagrichting, dan eindigt een lopend scenario als `context_weg`.
2. *Range (4u):* de laatste 4u-breuk **in de richting van de dag**. Een tussenliggende 4u-breuk de andere kant op telt niet meer. L, H,
   EQ, de 60 candles en het vervallen bij een slot voorbij de range blijven zoals 4.3 en 4.4.
3. *Entry:* ongewijzigd: pools 1u, sweep, shift, displacement en gap op 15m, en de instappunten A, B, V1 en P.
4. *BTC-poort:* blijft (B-2026-11-02-10).
5. Zonder dagcandles (alleen in tests en oude scripts) geldt de oude 4u-regel.

**Meting.** Ongetest. Bewijs en de nachtexport tellen vanaf de deploy. De oude 4u-regel loopt niet stil mee, op besluit van de CEO.

---

## Aanvullend besluit CEO 2026-11-03: instappunt R, "breuk en terugtest" (vooraf vast)

**Aanleiding.** PUMP 2 november (`docs/onderzoek/cases/2026-11-02-pump-1u-1815.md`, derde run). De lagere top en de breuk omlaag werden gezien,
maar zonder displacement (4.10) kwam er geen gap en dus geen entry. De CEO: "de r toevoegen ja".

**Regel (short; long gespiegeld).**
1. *Trigger:* dezelfde lagere top als B, met dezelfde vier eisen (aanvullend besluit 2026-11-03, B), dus in premium.
2. *Breuk:* binnen 24 candles van 15m na de top een 15m-slot voorbij het laatste 15m-dal vóór de top. Een slot boven de top maakt de
   poging ongeldig. Dit is dezelfde shift als bij B. **Geen displacement en geen gap nodig.**
3. *Limiet:* op het gebroken niveau, de terugtest. Herkenbaar op het sluiten van de breukcandle.
4. *Stop:* 0,25·ATR(15m van de breukcandle) voorbij de top, met de vloer van 0,4%.
5. *Doel:* zoals 4.7, de dichtste kandidaat voorbij de limiet. Zonder doel geen R.
6. *Geen premium-eis op de limiet.* Het gebroken niveau ligt per definitie onder de top en kan onder EQ liggen. De premium-eis geldt
   voor de top.
7. Geldigheid, vulling en uitkomst zoals B (6 uur, 4.13, 4.14). Hoogstens één R per scenario. Geen luide melding: op de kaart met zijn
   letter, stil gemeten.

**Nooit.** Afstellen op PUMP. De constanten zijn die van B.

---

## Aanvullend besluit CEO 2026-11-03: de range rekt op na een doorbraak tegen de dag in, live (vooraf vast)

**Aanleiding.** ZEC 2 november (`model_kaarten.py --coins ZEC --tekst` op de VPS). Het short-scenario in de range 1.214-1.255 eindigde als
`geen_pool`. Daarna steeg de koers tot 1.291, boven de range high, terwijl de dag omlaag bleef wijzen. Een nieuwe range kwam pas bij een
nieuwe 4u-breuk omlaag, en die kwam niet. De sweep van de top van 1.284,80 en de breuk omlaag lagen dus buiten het model. De CEO: "live en
niet stil", voor alle coins.

**Regel (long; short gespiegeld). Alleen met dagcandles (top-down).**
1. Een 4u-candle sluit onder de range low L van de laatste 4u-breuk in de richting van de dag. De dag houdt de richting.
2. De range blijft bestaan, maar L wordt het laagste low vanaf die candle tot de laatste gesloten 4u-candle. H blijft zoals 4.4. EQ volgt
   uit L en H.
3. Dit is een nieuwe range (eigen `range_id`, achtervoegsel `:door:<tijd van die candle>`). Er mag een nieuw scenario in beginnen. Een
   lopend scenario in de oude range eindigt met `context_weg`.
4. De range is herkenbaar op het sluiten van die candle. Hij eindigt zoals elke range: een nieuwe 4u-breuk in de richting van de dag, 60
   candles van 4u na de oorspronkelijke breuk, of een dag die omslaat.
5. Daarna gelden alle regels van het model ongewijzigd: pools, sweep, shift, displacement, alle instappunten, stop en doel.

**Zonder dagcandles** geldt de oude regel: een slot onder L beëindigt de range.

**Tests.** `tests/hespulse_model/test_model.py` (TopDownTest): het opgerekte scenario geeft een entry. Tegenvoorbeelden: geen slot door de
rand geeft geen opgerekte range; met de dag omlaag geen long; zonder dagcandles de oude regel. Daarnaast is gecontroleerd dat latere candles
niets veranderen aan wat eerder vaststond.

**Nooit.** Afstellen op ZEC. Er is geen nieuwe constante.

---

## Aanvullend besluit CEO 2026-11-03: één plan per kaart en een stopregel per instappunt (vooraf vast)

**Aanleiding.** ETH 2 november: B en B0 lagen op hetzelfde niveau, maar de kaart zei "Nog geen order". De CEO: "het moet wel duidelijk
blijven, en een legitieme kans zijn". Daarna: "ja prima".

**Kaart.** Een scenario met een wachtend, geldig B-, R- of B0-plan met een doel toont er één. De voorrang is B, dan R, dan B0. De kaart
toont limiet, stop, doel, hoe lang het plan nog geldig is en de orderknop (`/nu/order/mpoint:N`). Een verlopen of vervallen plan staat
er niet meer. De andere punten staan in het blad. Alleen weergave.

**Stopregel per instappunt (B, B0, R).** Netto R na `TRACK_RECORD_COST_PCT`, zonder funding, alleen afgeronde trades (doel of stop):
1. minder dan 30 afgerond: meten;
2. 30 tot 49: eerste blik op Bewijs en in de nachtexport, geen wijziging;
3. vanaf 50: ligt het interval van de netto R per ISO-week (98,75%, zoals §8) helemaal onder 0, dan meldt het punt niet meer luid;
   anders blijft de melding.

De stille meting loopt altijd door. De regel wordt elke cyclus opnieuw berekend; er is geen opgeslagen status. Een punt dat stopte kan dus
terugkomen als het interval later niet meer helemaal onder 0 ligt. A valt onder §8, niet onder deze regel.

**Nooit.** De drempels 30 en 50 of het niveau achteraf aanpassen.

---

## Aanvullend besluit CEO 2026-11-03 (ochtend): bevriezen, V1 en P van de kaart, Groot gelijk aan het model, hogere tijdframes meten

**Aanleiding.** Plan van aanpak (`docs/onderzoek/plan-van-aanpak-2026-11-04.md`) en de eerste cijfers van de VPS: A gaf in 54 scenario's
nog geen entry, V1 verloor 6 van 6 in twee gebeurtenissen, en scenario's van 30 en 31 oktober werden bij een update opgeslagen. De CEO:
"Ga door".

**Bevriezing.** Drie weken geen nieuwe of gewijzigde instapregel (A, B, B0, R, V1, P, de opgerekte range, de poorten). Het moment staat in
`settings` (`model_freeze_at`), gezet bij de eerste cyclus met deze code. De hoofdcijfers op Bewijs en in de nachtexport tellen alleen wat
daarna ontstond en niet met terugwerkende kracht: een scenario of punt dat meer dan 30 minuten na het herkenbare moment werd vastgelegd,
staat apart. De stopregel per punt telt op dezelfde manier. Weergave en meting mogen wel veranderen.

**V1 en P van de kaart.** Ze staan niet meer op de kaart, in Groot of in het blad. Ze worden stil gemeten zoals eerst.

**Groot gelijk aan het model.** Met de richting van de dag volgen range, evenwicht, MSB en order block op 15m, 1u en 4u alleen de breuken in
die richting, opgerekt na een slot door de rand. De trendregel zegt "herstel" als de laatste breuk tegen de dag in ging. Alleen weergave.

**Hogere tijdframes als kenmerk.** Per plan (A bij moment B, B, B0, R, P en V1 bij het vastleggen), met alleen gesloten 12u- en dagcandles:
1. `zone`: de limiet ligt in een open FVG of het order block van de laatste breuk in de richting van het plan, op 12u of dag;
2. `premium_dag`: short boven het evenwicht van de dagrange, long eronder;
3. `open`: de limiet ligt binnen 0,3% van de open van de lopende UTC-dag of ISO-week.

Onbekend is nooit "nee". Bewijs toont per kenmerk de afgeronde plannen die melden (A, B, B0, R) met en zonder. Pas na 50 afgeronde trades
per groep zeggen de cijfers iets; ook dan is het een kenmerk, geen filter, tot er een nieuwe preregistratie ligt.

**Nooit.** De 0,3% of de 30 minuten achteraf aanpassen. Tijdens de bevriezing een instapregel veranderen.
