# Weinig crypto-edge overleeft kosten en eerlijk toetsen

## Managementsamenvatting

1. Na kosten is er weinig bewijs voor korte-termijn-edges in crypto. Alleen trendvolgen op 4u tot dag heeft een redelijke basis in de literatuur, en ook daar zakt het effect buiten de testperiode vaak in.
2. Voor value area, volume profile en de "wetten" van auction market theory is geen enkele rigoureuze, openbare test met kosten gevonden. Er zijn alleen praktijkverhalen en kleine tellingen (6 van 12, 5 van 8).
3. Voor funding, open interest, taker ratio, long/short ratio en liquidaties als richtingsignaal is geen degelijke test gevonden. Het onderzoek gaat over prijsvorming en risico, niet over voorspellen.
4. Onze eigen data zeggen hetzelfde. Trend is klein positief (+0.07 tot +0.12R), maar een willekeurige instap scoort bijna even goed. Alles op korte timeframes verliest na kosten. Day trading en Chart-patroon verliezen duidelijk (circa -0.36R over 270 trades).
5. Ons lab kan +0.1R per trade met 3 jaar data niet bewijzen. Trades in dezelfde week hangen samen, dus de effectieve steekproef is veel kleiner dan het aantal trades. Strengere poorten zijn hier niet het probleem.
6. Let op: bijna alle bronnen zijn alleen via zoeksamenvattingen gelezen, omdat het ophalen van pagina's mislukte (arxiv, nexusfi, quantpedia, concretum). Controleer cijfers in het origineel voordat je erop bouwt.
7. Formules, kostenrekensommen, steekproefgroottes en rangordes zijn eigen rekenwerk of eigen oordeel van de notities of van dit rapport. Ze zijn als zodanig gemarkeerd.
8. Eerlijke conclusie: verwacht geen nieuwe grote edge. Wat het meest realistisch is: een trage, risicobeheerde trendkern plus minder signalen en veto's, en de dienst positioneren als beslishulp, niet als bron van bewezen alpha.

Leeswijzer: **[bron]** = wat een bron zegt (via een samenvatting). **[eigen]** = eigen afleiding of rekenwerk, niet uit een bron.

---

## 1. Hoe zeker zijn deze bevindingen?

Zes notities zijn gelezen: auction market theory, trend/momentum, mean reversion en lead-lag, derivatendata, niet-technische edges en toetsmethodiek. Elke notitie meldt dat het ophalen van pagina's mislukte (DNS-fouten). De cijfers komen dus uit abstracts en zoeksnippets, niet uit volledige papers.

Gevolgen:
- Kostenaannames van papers (fee, funding, slippage) zijn meestal niet bevestigd.
- Bij een paar bronnen is zelfs de toeschrijving onzeker (zie lijst in sectie 9).
- Geen enkele bron rapporteert R per trade, winrate of payoff voor crypto. Papers geven Sharpe op portefeuilleniveau. Directe vergelijking met ons lab is dus niet mogelijk.

---

## 2. Wat de literatuur zegt, per thema

### 2a. Value area, volume profile, auction market theory

**[bron]** Er is geen peer-reviewed of SSRN/arXiv-studie gevonden die value-area-, 80%-regel- of volume-profile-regels toetst, in welke markt dan ook. Wat er wel is: TradingView- en QuantConnect-scripts zonder test buiten de steekproef ([TradingView](https://www.tradingview.com/chart/ES1!/2Aiijm0n-volume-profile-trading-idea-test-spx), [QuantConnect](https://quantconnect.com/terminal/cache/embedded_backtest_c92486fcf1f50bcb2a54fb878c673464.html)). Eén script claimt "vooral groen" over 26.000 trades op 5m. Dat is een in-sample verkoopclaim ([TradingView](https://it.tradingview.com/script/Rzyqmul1-Volume-Profile-VPOC-VAH-VAL-VERY-GREEN-STRATEGY)).

**[bron]** De "80%" van de 80%-regel is een vuistregel, geen gemeten statistiek ([LuxAlgo](https://www.luxalgo.com/library/concept/80-percent-rule/)). Gemeten tellingen liggen lager: circa 50% (6 van 12 dagen) op ES in een NexusFi-analyse, alleen via samenvatting gelezen en intern niet sluitend ([NexusFi](https://nexusfi.com/a/concepts/80-percent-rule)). Een persoonlijke telling gaf 5 van 8 ([Elitetrader](https://elitetrader.com/et/threads/trading-with-market-profile.9727/post-598444)).

**[bron]** Het POC van BTC verschilt per beurs (circa 8.300 tegenover 6.250 in 2020). Profielniveaus hangen dus af van de databron ([TradingView](https://it.tradingview.com/chart/BLX/fYAFsDj8-BTCUSD-Volume-Profile-Accumulation-Zone-5-910-8-630)). Op ongereguleerde beurzen was in 2019 gemiddeld meer dan 70% van het volume wash trading ([NBER w30783](https://www.nber.org/system/files/working_papers/w30783/w30783.pdf)).

**[bron]** Het beste academische verwante werk: intraday-omkeringen in Amerikaanse indexfutures zijn bruto significant, maar die significantie zakt sterk weg na een kostenproxy ([Grant, Wolf & Yu](https://researchwith.montclair.edu/en/publications/intraday-price-reversals-in-the-us-stock-index-futures-market-a-1/)). Osler laat in FX-orderdata zien dat stops trends versnellen en take-profits omkeringen geven. Hetzelfde niveau kan dus beide kanten op ([FRBNY SR150](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr150.pdf)).

**[eigen]** Bij n=8 of 12 loopt het 95%-interval van circa 25% tot 85%. Zulke tellingen kunnen 50% niet van 80% onderscheiden. Crypto heeft geen opening en geen vaste sessie. Elke vertaling (UTC-dag, 22-uurssessie) is een vrije parameter, dus een ongetoetst analogon. Dat past bij ons lab: sweeps en rejecties -0.06 tot -0.12R, en de fase (balans/onbalans) scheidde niets over 453 live signalen.

### 2b. Trendvolgen en momentum (4u tot dag)

**[bron]** Steun in de literatuur:
- Zarattini, Pagani en Barbon (werkpaper 2025): een ensemble van Donchian-modellen met volatiliteitssizing over de 20 meest liquide munten. Netto Sharpe boven 1.5, alpha 10.8% per jaar ten opzichte van BTC ([IDEAS](https://ideas.repec.org/p/chf/rpseri/rp2580.html)).
- Liu en Tsyvinski (RFS 2021): tijdreeksmomentum in BTC, ETH en XRP op dag- en weekniveau ([NBER](https://www.nber.org/system/files/working_papers/w24877/w24877.pdf)). De steekproef is vooral van voor 2019.
- Bui en Nguyen (arXiv-preprint 2026, niet gereviewd): 6u-candles met trailing stop, Sharpe 2.41 over 2022-2024 ([arXiv](https://arxiv.org/pdf/2602.11708)). Selecteert munten op rollende Sharpe en zit 70/30 long-short.

**[bron]** Waarschuwingen:
- Hudson en Urquhart: van ~15.000 regels geen voorspelbaarheid voor BTC buiten de steekproef, wel bij andere munten ([Springer](https://link.springer.com/article/10.1007/s10479-019-03357-1)).
- Fieberg e.a. (IRFA 2024): momentum zit in bullmarkten en in de shortkant, kosten zijn aanzienlijk en het effect neemt af ([ICM](https://open.icm.edu.pl/handle/123456789/25544)).
- Een factorstudie zag momentum en reversal met circa 50% dalen van verkenning naar train/test ([arXiv 2307.13832](https://arxiv.org/pdf/2307.13832)).
- Geen degelijke test gevonden van een BTC-200d-filter of van volatiliteitstargeting die het resultaat verbetert.

**[eigen]** Het patroon van ons lab (36% winst, grote winnaars) is het normale trendprofiel. De grootte van de edge en de controle zijn het probleem. Een willekeurige instap met dezelfde trailing exit haalt +0.03 tot +0.11R. Dan komt het meeste van de exit en van de stijgende markt in de steekproef, niet van het instapmoment. De literatuur ondersteunt dat lange crypto-strategieën deels drift oogsten.

### 2c. Mean reversion, seizoenseffecten, lead-lag, orderflow

**[bron]** Korte-termijn-omkering zit vooral in kleine, illiquide munten. Het is een vergoeding voor het leveren van liquiditeit. De grootste munten tonen juist momentum op dag- en weekniveau ([Zaremba e.a.](https://earsiv.medeniyet.edu.tr/items/23a96c9f-3952-4bdf-aec5-abafb3aaab70), [Riksbank WP 413](https://www.riksbank.se/globalassets/media/rapporter/working-papers/2022/no.-413-trading-volume-and-liquidity-provision-in-cryptocurreny-markets.pdf)).

**[bron]** Kalendereffecten in BTC wisselen door de tijd en zijn niet stabiel ([Baur e.a., UWA](https://research-repository.uwa.edu.au/en/publications/bitcoin-time-of-day-day-of-week-and-month-of-year-effects-in-retu/)). De Quantpedia-regel "long 21-23 UTC" is een blog, bruto en mogelijk vervaagd sinds de ETF's ([Quantpedia](https://quantpedia.com/how-to-profitably-trade-bitcoins-overnight-sessions/)).

**[bron]** BTC loopt seconden voor op altcoins (gemiddeld ~57 s voor Cardano) ([IMFI](https://businessperspectives.org/journals/investment-management-and-financial-innovations/issue-421/a-tick-by-tick-level-measurement-of-the-lead-lag-duration-between-cryptocurrencies-the-case-of-bitcoin-versus-cardano)). Orderflow-onbalans voorspelt op seconden tot minuten ([arXiv 2602.00776](https://arxiv.org/pdf/2602.00776)). Eén werkpaper claimt 4-12 uur voorspelling uit openingsonbalans op Binance-perps; dat is niet gereviewd en niet gerepliceerd ([arXiv 2607.09426](https://arxiv.org/pdf/2607.09426)).

**[bron]** Geen degelijke test gevonden van CME-gaps, Deribit-expiry/max pain, squeeze/NR7 of candlestickpatronen. Een studie van 2022-2023 vond op BTC en ETH geen winstgevende strategie na correctie voor data snooping ([JAF](https://articlegateway.com/index.php/JAF/article/view/6453)).

**[eigen]** Kosten in R bij 0.06% heen-en-terug:

| Stop | Kosten 0.06% | Kosten 0.16% |
|---|---|---|
| 0.7% | 0.09R | 0.23R |
| 1.0% | 0.06R | 0.16R |
| 1.8% | 0.03R | 0.09R |
| 5.0% | 0.01R | 0.03R |

De kolom 0.16% is het realistischer voorbeeld uit de notities: taker 0.05% per kant plus 0.03% slippage per kant. Lead-lag en orderflow zijn het terrein van bots. Een pushmelding plus handmatige order is trager dan het effect duurt.

### 2d. Derivatendata

**[bron]** Funding is goed onderbouwd als carry en als anker tussen perp en spot, niet als richtingsignaal. De BIS vond een grote maar risicovolle carry ([BIS WP 1087](https://bis.org/publ/work1087.htm)). Een paper uit 2025 meldt dat de carry vanaf 2024 sterk is samengeperst en in 2025 negatief werd ([arXiv 2510.14435](https://arxiv.org/pdf/2510.14435)). Dat funding-extremen lagere rendementen voorspellen, staat alleen in blogs ([voorbeeld](https://axeladlerjr.com/bitcoin-open-interest-funding-rate/)).

**[bron]** Open interest: de enige gereviewde studie gaat over volatiliteit, niet over richting ([IDEAS](https://ideas.repec.org/a/eee/finana/v86y2023ics1057521923000133.html)). "OI-flush = bodem" is een ongevalideerd blogidee ([Axel Adler](https://axeladlerjr.com/bitcoin-liquidation-cascades-guide/)).

**[bron]** Liquidaties: cascades zijn goed beschreven, maar er is geen studie van rendementen erna. Cijfers voor dezelfde dag (10 okt 2025) lopen uiteen van $2.3 mrd tot $19 mrd of meer ([Amberdata](https://blog.amberdata.io/leverage-liquidations-the-31b-deleveraging), [CoinShares](https://coinshares.com/insights/knowledge/billions-in-liquidations-what-happened/)). Een preprint vond geen maatstaf die elke crash vooraf aankondigde ([CryptoSlate](https://cryptoslate.com/new-bitcoin-study-shows-the-strongest-recurring-liquidation-warning-signs-cannot-warn-of-an-individual-crash/)).

**[bron]** Positionering (top-trader en globale L/S, taker ratio): geen degelijk bewijs. Binance geeft via de API maar de laatste 30 dagen ([Binance docs](https://developers.binance.com/docs/derivatives/coin-margined-futures/market-data/Top-Trader-Long-Short-Ratio), [binance-public-data #211](https://github.com/binance/binance-public-data/issues/211)). De publieke dagbestanden hebben mogelijk langere historie; dat is niet gecontroleerd.

**[eigen]** Alleen funding heeft genoeg historie voor een echte toets (Binance sinds 2019 voor BTC). OI, ratio's en liquidaties kunnen we nu alleen verzamelen. Onze liquidatie-snapshots zijn een ondergrens: de force-order-stream geeft volgens de notities maximaal één liquidatie per symbool per seconde. Dat is uit het geheugen van de onderzoeker en nog niet gecontroleerd.

### 2e. Niet-technische edges

**[bron]** Listing-, unlock- en hackeffecten zijn echt, maar zitten vooral vóór of bij de aankondiging en in kleine munten. Een Binance-listing voegt weinig toe voor munten die al op drie of meer grote beurzen staan ([The Tie](https://www.thetie.io/insights/what-a-binance-listing-delivers-for-already-listed-tokens)). Grote unlocks (5-10% van het aanbod) geven circa 2,4x zwaardere dalingen; dat komt alleen uit een samenvatting van verkoperdata ([Keyrock](https://keyrock.com/from-locked-to-liquidity-what-16000-token-unlocks-teach-us/)). Na hacks blijft 80% of meer van de tokens langer gedrukt ([Immunefi](https://immunefi.com/blog/research/what-an-onchain-hack-actually-costs-2024-2025-update/)).

**[bron]** Fed-besluiten bewegen BTC-rendement en -volatiliteit ([Corbet e.a.](https://businessperspectives.org/journals/author/shaen-corbet)). Er is geen crypto-specifieke, kosten-overlevende drift rond FOMC/CPI gevonden.

**[bron]** De BTC-Nasdaq-correlatie hangt van het regime af en is asymmetrisch: sterker op dagen dat aandelen dalen ([arXiv 2501.09911](https://arxiv.org/abs/2501.09911v1), [Yahoo/CoinDesk](https://finance.yahoo.com/news/bitcoin-falls-harder-tech-nasdaq-085744323.html)). Er is geen getest risk-on-filter gevonden.

**[bron]** Sentiment en LLM-nieuws: bij Bitcoin-nieuws met ChatGPT-labels wel betere fit in de steekproef, maar geen significante winst erbuiten. De bron-URL van dat resultaat is onzeker, zie sectie 9.

**[eigen]** Voor 20 grote perps zijn dit hoogstens filters (veto's), geen strategieën. Listing-pops zijn te snel voor handmatig handelen.

---

## 3. Wat de handelaar-wetten betekenen

**Kern:** voor geen van de acht wetten is een rigoureuze openbare test gevonden. Het zijn hypotheses, geen feiten. Wel zijn ze goedkoop te toetsen met onze 1u-data.

**[eigen]** Opzet voor alle tests: een profiel per UTC-dag uit 1u-bars, waarbij het volume van elke bar over zijn bereik wordt verdeeld. Dat maakt het profiel wazig; tradedata zou beter zijn. Value area 70%. Eerst beschrijvend meten: hoe vaak gebeurt X, vergeleken met een willekeurige controle op dezelfde afstand. Pas daarna een handelsregel. Ook de beschrijvende tests tellen mee als varianten.

| Wet | Bewijs |
|---|---|
| 1 In value = door de VA | Alleen tellingen ~50-62% |
| 2 Buiten value = doorbraak loopt | Indirect (trend, Osler) |
| 3 Midden VA is chop | Geen |
| 4 Afwijzing vanaf POC | Geen; lab-rejectie verliest |
| 5 Compressie = voortzetting | Geen; alleen grootte |
| 6 Hertest verschoven gebied | Geen; Osler als mechanisme |
| 7 Terug naar oude value | Geen voor BTC |
| 8 In balans tot bewezen | Geen; onze fase scheidde niets |

Per familie, met een goedkope toets:

**Wet 1 (acceptatie in value).** [bron] Dit is de 80%-regel. De enige cijfers zijn 6/12 en 5/8 (zie 2a). [eigen] Toets: prijs opent of sluit buiten de VA van gisteren, daarna twee 1u-sluitingen binnen. Meet hoe vaak de andere VA-rand binnen 24u wordt geraakt. Vergelijk met willekeurige uren waarin dezelfde afstand moet worden afgelegd.

**Wet 2 (acceptatie buiten value).** [bron] Indirect gesteund: trendvolgen werkt bruto, stopclusters versnellen bewegingen ([Osler SR150](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr150.pdf)) en FX-range-breaks overleven kosten ([FMG](https://www.fmg.ac.uk/publications/discussion-papers/when-supportresistance-levels-are-broken-can-profits-be-made)). [eigen] Toets: twee 1u-sluitingen buiten de VA. Meet hoe vaak 1x de VA-breedte verder wordt gehaald vóór terugkeer in de VA. Wet 1 en 2 zijn spiegelbeelden, dus test ze samen (sectie 6, kandidaat 5).

**Wet 3 (midden is chop).** [eigen] Meet de efficiëntie van de beweging (netto beweging gedeeld door afgelegde weg over 6-12u) in het midden van de VA, aan de randen en erbuiten. Puur beschrijvend. Als het klopt, is het hooguit een veto: geen instap midden in de VA.

**Wet 4 (afwijzing vanaf POC).** [eigen] Ons lab mat rejectie op niveaus al: -0.09R over 2175 trades. Niet opnieuw als handelsregel toetsen. Hooguit beschrijvend: kaatst prijs vaker terug op het POC dan op een willekeurig niveau op dezelfde afstand?

**Wet 5 (compressie leidt tot voortzetting).** [bron] Geen degelijke squeeze-test; alleen een QuantConnect-run met 79% drawdown ([QuantConnect](https://www.quantconnect.com/terminal/cache/embedded_backtest_6535e797e18edcd11cc628937532ebff.html)). [eigen] Volatiliteitsclustering voorspelt grootte, niet richting. Toets: een lage ATR-percentiel per munt (rollend, niet over de hele steekproef). Meet de grootte en de richting van de volgende 24u-beweging ten opzichte van de trend ervoor.

**Wet 6 (hertest van verschoven gebied).** [eigen] Na een VA-verschuiving: hoe vaak raakt prijs de oude VA-rand binnen 48u, vergeleken met een willekeurige rand op dezelfde afstand?

**Wet 7 (terug naar oude value).** [bron] Alleen TradingView-commentaar. Grote munten tonen eerder momentum dan omkering (2c). [eigen] Toets: kans op het opnieuw raken van het POC van 1-5 dagen terug, vergeleken met een niveau op dezelfde afstand aan de andere kant.

**Wet 8 (balans tot het tegendeel bewezen is).** [eigen] Onze fase uit een 72u-profiel scheidde de resultaten niet over 453 live signalen. Dat is al een zwakke negatieve aanwijzing. Niet verder toetsen zonder een nieuwe, vooraf vastgelegde definitie.

---

## 4. Eerlijk toetsen in ons lab

### Wat goed is

[eigen, op basis van de methodiek-notitie] De opzet is in de kern goed: kostenbewust, clustering per week, placebo, vooraf vastgelegde varianten en een proefmotor als echte holdout. De poorten zijn niet te streng. Het probleem is dat de data +0.1R niet van 0 kunnen onderscheiden.

### Het steekproefprobleem

[eigen, rekenwerk uit de notitie] Om +0.1R te zien bij een spreiding van 1.5R (eenzijdig 5%, 80% power) zijn **circa 1.400 onafhankelijke trades** nodig. Voor de t>3-horde zijn het er circa 3.300. Bij +0.2R zijn het er circa 350, of circa 830 voor t>3.

Trades in dezelfde week zijn grotendeels één gok op de markt. Effectieve n = n / (1 + (m-1)·ρ), met m = trades per week en ρ = de samenhang binnen een week. Bij m=8 en ρ=0.3 is dat n/3: "een derde".

[eigen, extra rekenwerk] Bij onze echte aantallen is het erger. Over 156 weken:

| Motor | Trades/week | Effectieve n (ρ 0.3) |
|---|---|---|
| Donchian 4u | 14-26 | ~450-480 |
| SW_TREND_1H | ~40 | ~490 |

Meer trades per week helpen bijna niet. Bij veel trades per week gaat de effectieve n naar ongeveer weken/ρ, dus circa 520. Om 1.400 te halen zijn bij ρ=0.3 ongeveer **8 jaar** aan weken nodig. Dit verklaart waarom elke trendvariant de week-cluster-toets mist. ρ is geschat, niet gemeten. Meet het met een ANOVA van R per week.

### Hoeveel varianten, welke horde

Circa 34 varianten (families meegeteld). [eigen] De beste van 34 nulvarianten haalt al ongeveer **t ≈ 2.1**. Een "pass" rond t=2 zegt dus niets. Horde: t ≈ max(3.0, 2.1 + 1.0) ≈ **3.1**, of Bonferroni 0.05/34 eenzijdig, wat neerkomt op z ≈ 3.0. Bijna-duplicaten mogen samen als minder dan één tellen, maar dan moet je dat met een correlatiematrix onderbouwen. Bij twijfel tel je ze alle 34.

### Wat te los en wat te streng is

| Poort | Oordeel |
|---|---|
| Beide helften positief | Te ruis-gevoelig |
| Placebo-marge 0.03R vast | Te los |
| Week-bootstrap marge > 0 | Goed, maar zonder N-correctie |
| 500 trades minimum | Bindt niet; de weken binden |
| Correctie voor aantal varianten | Ontbreekt |
| Live: 50 trades, gemiddelde ≥ 0 | Te los |

Toelichting [eigen, uit de notitie]:
- **Helften:** bij een echte +0.1R en 250 trades per helft zijn beide helften maar in ~70% van de gevallen positief. Bij een nul-edge is één helft positief in 50% van de gevallen. Als bewijs is dit zwak, en voor een kleine echte edge is het tegelijk vrij streng.
- **Placebo:** 0.03R is maar ~0.45 standaardfout bij 500 trades. Zo'n marge wordt vaak toevallig gehaald.
- **Live:** de standaardfout bij 50 trades is 0.21R. Een edge van nul haalt "gemiddelde ≥ 0" in 50% van de gevallen.

### Aanbevolen wijzigingen

1. Houd een register bij van elke variant die ooit op deze data is bekeken. Zet de horde (t ≈ 3.1 bij N=34) in `evaluate`.
2. Maak de week-cluster-toets eenzijdig: de 5%-ondergrens moet boven 0 liggen, op het N-gecorrigeerde niveau. Draai hem ook met clusters van 2 weken en rapporteer de slechtste uitkomst.
3. Tel de R per dag op voor de hele portefeuille en draai daarop een stationaire bootstrap met blokken van 5-10 dagen. Rapporteer ook de alpha na correctie voor BTC-beta.
4. Vervang de twee helften door 6-8 tijdsblokken: minstens 60% positief en geen blok slechter dan -0.3R. Dit is een stabiliteitscheck, geen significantietoets.
5. Placebo: 1.000 sets die aantal per munt, per maand en de long/short-mix gelijk houden. Eis p < 0.05 en een marge > 0.
6. Kosten: reken met 1.0x, 1.5x en 2.0x, met de echte funding per symbool. Als stop en doel in dezelfde candle vallen, telt de stop. **Onze 0.06% ligt onder Binance VIP0 taker/taker (0.05% per kant, dus 0.10% alleen aan fees)** ([Binance](https://www.binance.com/en/support/articles/360033544231)). Toets minstens op 0.10-0.16%.
7. Lees de laatste 6-9 maanden niet meer. Gebruik die periode één keer per familie als holdout.
8. Live promoveren: een Bayesiaanse kans P(mu>0) ≥ 0.9 onder een sceptische prior (tau 0.05-0.1R). Degraderen met CUSUM: snel omlaag, traag omhoog.
9. Pas de universe aan naar de toen geldende top 20, inclusief munten die later zijn gedelist. Of benoem de opwaartse bias en trek die er expliciet af.
10. Haircut: halveer de lab-R van een geselecteerde variant en reken de kosten opnieuw op 1.5x. [eigen oordeel; McLean-Pontiff vond 26% minder buiten de steekproef en 58% na publicatie, bij aandelen ([paper](https://ivey.uwo.ca/media/3775549/pontiff.pdf))]

**Niet doen:** de poorten versoepelen tot er iets slaagt. "0 van 20+ geslaagd" is precies wat je verwacht als de edge circa 0 is.

---

## 5. Onze eigen live-data, eerlijk gelezen

[eigen rekenwerk, spreiding 1.5R aangenomen]

| Soort | Resultaat | Oordeel |
|---|---|---|
| Structuur oordeel | +0.27 tot +0.41R, 21-34 tr. | Ruis; SE ~0.26-0.33R |
| Day trading + Chart-patroon | ~-0.36R, 270 tr. | Duidelijk negatief |
| Trend | wisselend | Onbeslist |

- **Structuur oordeel:** het 95%-interval loopt bij 34 trades van ongeveer -0.24 tot +0.8R. Na sceptische krimp (tau 0.07) blijft er ongeveer +0.02R over. Laten draaien en loggen, maar er niets aan toevoegen.
- **Day trading en Chart-patroon:** naïef t ≈ -4. Met een clustercorrectie van 3 nog steeds t ≈ -2.3. Dit is het sterkste signaal dat we hebben, en het zegt: stoppen.

---

## 6. Kandidaten en shortlist

### Afgevallen, met reden

| Idee | Reden |
|---|---|
| Lead-lag, orderflow | Seconden; te traag per push |
| Uur/dag-seizoen | Instabiel; kosten eten het op |
| Mean reversion 1u | Zit in illiquide munten |
| Listings, Upbit-pumps | Te snel, kleine munten |
| Funding-carry | Kapitaalzwaar; ingestort sinds 2024 |
| Opties (GEX, max pain) | Geen data; geen bewijs |
| CME-gaps | Alleen mediaclaims |
| OI, taker, L/S, liquidaties | Te korte historie; eerst verzamelen |
| LLM-nieuws als instap | Geen bewijs buiten steekproef |

OI, taker en L/S zijn niet verworpen, maar nu niet toetsbaar. **Laat het lab elk uur zelf opnemen.** Binance geeft maar circa 30 dagen terug. Toets pas na ≥ 1 jaar eigen historie, en dan alleen vooruit (op nieuwe data).

### Gerangschikte shortlist (max 5)

**1. Trage trendkern (4u/1d), vol-gestuurd, met regimepoort**
- Hypothese: een Donchian-trend op 4u/1d met volatiliteitssizing geeft na kosten een kleine positieve R, die niet alleen beta is.
- Bron: middel. Meerdere papers ([Zarattini e.a.](https://ideas.repec.org/p/chf/rpseri/rp2580.html), [Liu-Tsyvinski](https://www.nber.org/system/files/working_papers/w24877/w24877.pdf)), maar Hudson-Urquhart faalt voor BTC buiten de steekproef en de resultaten zijn bull-zwaar.
- Verwacht netto: lab +0.07 tot +0.12R, na haircut **+0.03 tot +0.06R**. Na aftrek van de placebo blijft er mogelijk ~0 over.
- Test: één familie, vooraf vastgelegd, 3-4 varianten (4u 20/55, 1d 20/55, ensemble). Kosten 0.10% en 0.16% plus echte funding. Week- en 2-weken-cluster-bootstrap op de portefeuille-dag-R, alpha na BTC-beta, gematchte placebo, 6-8 tijdsblokken, horde t ≈ 3.1.
- Week-cluster-falen: niet versoepelen. Verleng de historie (daily data van majors terug tot 2019-2020, met point-in-time universe), meet ρ, en accepteer dat bewijs pas komt van meer weken of van live data.
- Risico's: survivorship, een bull-zware steekproef, edge = drift.
- Kans op succes: **laag** dat hij de strenge toets binnen 3 jaar haalt (rekenkundig vrijwel onmogelijk bij +0.1R). **Middel** dat hij als risicobeheerde kern positief blijft. Reden: de literatuur en het lab wijzen dezelfde kant op, maar het effect is klein.

**2. Minder signalen en event-veto's op bestaande motoren**
- Hypothese: verliezende soorten stoppen en geen nieuwe meldingen geven rond tier-1-macro, grote unlocks en hacks verbetert het resultaat per melding.
- Bron: sterk voor stoppen (eigen data: -0.36R over 270). Zwak voor de veto's: volatiliteit rond Fed-besluiten ([Corbet](https://businessperspectives.org/journals/author/shaen-corbet)), unlocks en hacks alleen uit verkoperdata ([Keyrock](https://keyrock.com/from-locked-to-liquidity-what-16000-token-unlocks-teach-us/), [Immunefi](https://immunefi.com/blog/research/what-an-onchain-hack-actually-costs-2024-2025-update/)).
- Verwacht netto: stoppen bespaart circa 0.36R per vermeden melding (geen haircut nodig, het is verlies dat wegvalt). Veto's: onbekend, waarschijnlijk klein. Ze raken weinig 4u-instappen.
- Test: Day trading en Chart-patroon uit. Macro-blackout (30 min voor tot 60 min na CPI/FOMC/NFP) als risicoregel. Log in de schaduw wat is overgeslagen en meet de R van die overgeslagen trades. Unlock-veto (>2-5% van het aanbod binnen 30 dagen) en hack-veto ook in de schaduw.
- Risico's: te weinig events voor statistiek; veto's worden "tuning". Label ze als risicomaatregel, niet als edge.
- Kans op succes: **hoog** voor het stoppen van verliezers, **laag-middel** voor aantoonbare winst uit de veto's.

**3. Risk-on-filter op longs (BTC boven 200d, later Nasdaq/ES)**
- Hypothese: trend-longs alleen nemen als BTC boven zijn 200-daags gemiddelde staat. Dit verlaagt vooral de drawdown.
- Bron: zwak. Asymmetrische BTC-Nasdaq-correlatie ([arXiv 2501.09911](https://arxiv.org/abs/2501.09911v1)). Geen test van een BTC-200d-poort gevonden.
- Verwacht netto: R per trade +0 tot +0.03R. Het nut zit vooral in minder drawdown.
- Test: als één vooraf vastgelegde variant binnen kandidaat 1 (telt mee in N). Gebruik alleen gesloten dagcandles. Rapporteer R, max drawdown en het aantal weken per regime. Nasdaq/ES zit niet in onze velden, dus begin met BTC-200d.
- Risico's: weinig regimewissels in 3 jaar (4-8), dus bijna geen power. Verleidt tot selectie achteraf.
- Kans op succes: **middel** voor minder drawdown, **laag** voor een bewezen hogere R.

**4. Funding-extremen als regimefilter of contrair signaal**
- Hypothese: een extreme funding-z-score (crowded long/short) voorspelt slechtere trend-longs, of een contraire beweging over 24-72u.
- Bron: geen degelijk bewijs voor richting. Wel een pricing-theorie en carry ([BIS](https://bis.org/publ/work1087.htm)); de rest zijn blogs.
- Verwacht netto: onbekend. Eerlijke verwachting ~0. Na haircut niet in te boeken.
- Test: funding per munt, een rollende z-score over 90 dagen (geen statistiek over de hele steekproef), alleen waarden die bekend waren vóór de bar-close. Eerst als filter op kandidaat 1, daarna standalone op een horizon van 24-72u met niet-overlappende vensters. Week-bootstrap, placebo, met opsplitsing voor en na 2024. Kosten 0.10-0.16% plus de betaalde funding.
- Risico's: structuurbreuk na de ETF's; funding blijft in trends lang extreem (veel valse signalen).
- Kans op succes: **laag**. Reden: geen bron, carry is ingestort, maar het is de enige derivatenreeks met genoeg historie.

**5. Wet 1 tegen Wet 2 (acceptatie in tegen buiten value)**
- Hypothese: na twee 1u-sluitingen terug binnen de VA van gisteren wordt de andere rand vaker gehaald dan bij toeval. Na twee sluitingen buiten de VA loopt de doorbraak verder.
- Bron: geen (alleen tellingen van 6/12 en 5/8).
- Verwacht netto: eerlijk ~0. De lab-familie (sweeps, rejectie) verliest 0.06-0.12R.
- Test: eerst beschrijvend (zie sectie 3), daarna één handelsregel per wet. Stop ≥ 1.5% (anders eten de kosten alles), doel bij de andere rand of trailing. Twee varianten, beide in het register. Volledige poorten en kosten 0.10-0.16%.
- Risico's: profiel uit 1u-bars is wazig; UTC-dag is een vrije keuze; bij een smalle VA worden de stops klein.
- Kans op succes: **laag**. Waarde: het beslecht een vraag die de gebruiker steeds terugziet, voor weinig werk.

### Als het eerlijke antwoord "geen edge" is

Dat is de waarschijnlijkste uitkomst voor alles behalve de trendkern. De dienst kan dan nog steeds nuttig zijn, zonder te beloven wat niet bewezen is:
- **Risicobeheerde kern:** een trage trend met een kleine inzet (≤ 0,25-0,5% risico), een cap op de totale open positie, veto's en eerlijk tonen op Bewijs.
- **Beslishulp voor de CEO:** Structuur oordeel en Radar als checklist en logboek bij discretionaire trades. Zonder belofte van winst, wel met meting.
- **Minder meldingen:** een paar keer per week in plaats van tientallen per dag. Eigen data en literatuur wijzen dezelfde kant op: veel signalen met een kleine edge verliezen aan de kosten.

---

## 7. Wat we niet doen

- **Afstellen op de data.** Geen drempels kiezen nadat je de uitkomst hebt gezien. Elke nieuwe drempel is een nieuwe variant.
- **Filters stapelen op verliezende motoren.** Day trading en Chart-patroon "redden" met extra filters is selectie op ruis. Stoppen.
- **Bouwen op screenshotbewijs.** Achteraf getekende niveaus en succesvolle voorbeelden zijn survivorship. Zo werkt ook de "80%".
- **Backtests op 5m/15m met stops onder 1,5%.** De kosten zijn daar 0,06-0,23R per trade. Dat is groter dan elke edge die we ooit zagen.
- **Poorten versoepelen tot iets slaagt.**
- **Eén periode, regime of munt kiezen omdat die goed scoorde.**
- **Verkoperscijfers als effectgrootte gebruiken** (unlocks, listings, copy trading).
- **Kortere OI/ratio-historie "toetsen" en live zetten.** Eerst een jaar verzamelen.
- **Statistiek over de hele steekproef gebruiken** in z-scores of percentielen. Dat lekt toekomstige data in de test.

---

## 8. Methodenotities en open punten

- Alle formules in sectie 4 (DSR, verwachte maximum-t, SPRT, CUSUM, design effect) komen uit de kennis van de onderzoeker. Ze zijn niet tegen de originele papers gecontroleerd. De `arch`-pakketnamen (`SPA`, `StepM`) komen uit het geheugen.
- ρ, slippage en de spreiding van R moeten uit onze eigen data komen, niet uit dit rapport.
- Niet onderzocht: White's Reality Check, Hansen SPA en Romano-Wolf uit de bron; Kraken-fees; slippage-studies; cijfers over delisting en survivorship voor perps.

---

## 9. Bronnen

Status: **samenv.** = alleen via zoeksamenvatting gelezen. **onzeker** = toeschrijving of cijfer twijfelachtig; niet citeren zonder controle. **Geen enkele bron is in deze ronde volledig gelezen.**

| Bron | Soort | Status |
|---|---|---|
| [Hudson & Urquhart](https://link.springer.com/article/10.1007/s10479-019-03357-1) | peer | samenv. |
| [Zarattini e.a. 2025](https://ideas.repec.org/p/chf/rpseri/rp2580.html) | werkpaper | samenv. |
| [Liu & Tsyvinski](https://www.nber.org/system/files/working_papers/w24877/w24877.pdf) | peer | samenv. |
| [Liu, Tsyvinski & Wu](https://www.nber.org/papers/w25882.pdf) | peer | samenv. |
| [Fieberg e.a. 2024](https://open.icm.edu.pl/handle/123456789/25544) | peer | samenv. |
| [Bui & Nguyen 2026](https://arxiv.org/pdf/2602.11708) | preprint | samenv. |
| [Multi-Factor Inception](https://arxiv.org/pdf/2307.13832) | preprint | samenv. |
| [Grant, Wolf & Yu](https://researchwith.montclair.edu/en/publications/intraday-price-reversals-in-the-us-stock-index-futures-market-a-1/) | peer | samenv. |
| [Osler SR125](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr125.html) / [SR150](https://www.newyorkfed.org/medialibrary/media/research/staff_reports/sr150.pdf) | Fed | samenv. |
| [Cong e.a. wash trading](https://www.nber.org/system/files/working_papers/w30783/w30783.pdf) | werkpaper | samenv. |
| [Zaremba e.a.](https://earsiv.medeniyet.edu.tr/items/23a96c9f-3952-4bdf-aec5-abafb3aaab70) | peer | samenv. |
| [Bianchi e.a. (Riksbank)](https://www.riksbank.se/globalassets/media/rapporter/working-papers/2022/no.-413-trading-volume-and-liquidity-provision-in-cryptocurreny-markets.pdf) | peer | samenv. |
| [Baur e.a.](https://research-repository.uwa.edu.au/en/publications/bitcoin-time-of-day-day-of-week-and-month-of-year-effects-in-retu/) | peer | samenv. |
| [BIS WP 1087](https://bis.org/publ/work1087.htm) | werkpaper | samenv. |
| [He e.a. perps](https://arxiv.org/html/2212.06888v5) | preprint | samenv. |
| [arXiv 2510.14435 carry](https://arxiv.org/pdf/2510.14435) | preprint | samenv. |
| [Zhang e.a. OI](https://ideas.repec.org/a/eee/finana/v86y2023ics1057521923000133.html) | peer | samenv. |
| [Binance L/S-docs](https://developers.binance.com/docs/derivatives/coin-margined-futures/market-data/Top-Trader-Long-Short-Ratio) | docs | samenv. |
| [Harvey, Liu & Zhu](https://nber.org/papers/w20592) | peer | samenv. |
| [Bailey & López de Prado DSR](https://papers.ssrn.com/abstract=2460551) | peer | samenv. |
| [PBO](https://papers.ssrn.com/abstract=2326253) | peer | samenv. |
| [McLean & Pontiff](https://ivey.uwo.ca/media/3775549/pontiff.pdf) | peer | samenv. |
| [Corbet e.a.](https://businessperspectives.org/journals/author/shaen-corbet) | peer | samenv. |
| [arXiv 2501.09911 BTC-Nasdaq](https://arxiv.org/abs/2501.09911v1) | preprint | samenv. |
| [Keyrock unlocks](https://keyrock.com/from-locked-to-liquidity-what-16000-token-unlocks-teach-us/) | verkoper | samenv. |
| [Immunefi hacks](https://immunefi.com/blog/research/what-an-onchain-hack-actually-costs-2024-2025-update/) | verkoper | samenv. |
| [LuxAlgo 80%-regel](https://www.luxalgo.com/library/concept/80-percent-rule/) | educatie | samenv. |
| [Binance fees](https://www.binance.com/en/support/articles/360033544231) | beurs | samenv. |

### Gemarkeerde lage-zekerheid-toeschrijvingen (niet ongecontroleerd citeren)

- **NexusFi 80%-regel:** pagina niet opgehaald; "6 van 12" en "67 dagen, 12 met tweede bar binnen" zijn niet met elkaar te rijmen ([link](https://nexusfi.com/a/concepts/80-percent-rule)).
- **Swinkels 2018** ("momentum verdween na BTC-futures"): toeschrijving laag vertrouwen ([Zenodo](https://zenodo.org/records/7326524)).
- **Svogun & Bazán-Palomino 2022:** het zoekprogramma koppelde de studie aan deze link; controleren ([IDEAS](https://ideas.repec.org/a/eee/finana/v86y2023ics1057521923000327.html)).
- **Gbadebo 2026** (31,96% per jaar): toeschrijving onzeker ([Springer](https://link.springer.com/article/10.1007/s11408-025-00474-9)).
- **ChatGPT-labels bij Bitcoin-nieuws:** arXiv 2304.07619 is het aandelenpaper van Lopez-Lira & Tang. Het Bitcoin-resultaat had geen eigen URL.
- **Liu & Tsyvinski-periode 2011-2018:** lezing van de onderzoeker, niet uit de snippet.
- **Osler 2000 (EPR):** de snippet was afgekapt; controleer de formulering ([PDF](https://resources.newyorkfed.org/medialibrary/media/research/epr/00v06n2/0007osle.pdf)).
- **BIS-carry:** "tot 60%" tegenover "boven 40%" per jaar; versies verschillen.
- **Basisniveaus midden 2025:** bronnen spreken elkaar tegen; alleen de daling is gesteund.
- **10 okt 2025:** liquidaties $2.3 mrd, $19 mrd of >$50 mrd; OI -42% tegenover 175→125 mrd. Verschillende reikwijdte.
- **Binance taker-fee:** officieel 0.05%, één bron zegt 0.04%.
- **Hyperliquid hogere fee-tiers:** bronnen spreken elkaar tegen.
- **Quantpedia-uurregel:** instap 21:00 of 22:00 UTC verschilt per artikel; bruto.
- **Perp/spot-ratio 7.87 (MEXC):** niet geverifieerd ([link](https://www.mexc.com/news/660610)).
- **Listings +41% tegenover -49%:** niet met elkaar te rijmen ([RockawayX](https://rockawayx.com/insights/bullish-or-bearish-what-really-happens-when-tokens-list-on-a-cex)).
- **Keyrock-unlocks:** alleen via secundaire samenvattingen.
- **Copy trading 97%/43.6% (AInvest):** niet geverifieerd.
- **"70% van signaalvolgers verliest" (Traders Union):** zonder bron; niet gebruiken.
- **OFI-claims via Emergent Mind:** niet crypto-specifiek; niet geverifieerd.
- **arXiv 2606.00071 en 2607.09426:** review en werkpaper; effectgrootte niet gezien.
- **Binance force-order "1 per seconde":** uit het geheugen van de onderzoeker; controleer in de docs.
- **Alle formules in de methodiek-notitie:** eigen kennis; controleer tegen de originele papers.
