# HesPulse verkleinen: vaste coinlijst + ongein eruit — design

## Aanleiding

Twee losse punten die deze sessie eerder al genoemd zijn, gecombineerd tot
één project: de Anthropic API-kosten moeten omlaag ("ik moet weer bijna
opwaarderen"), en HesPulse moet kleiner en gerichter worden — kwaliteit
in plaats van kwantiteit, op een handvol coins in plaats van een
onbeperkt groeiende lijst. Beide problemen hebben dezelfde oorzaak: het
systeem groeit ongecontroleerd mee met alles wat ooit in Discord
voorbijkomt, en houdt features in de lucht (swing, narrative-dashboard,
prop-evaluatie) die weinig gebruikt worden maar wel onderhoud en
API-verkeer kosten.

## Scope

Drie samenhangende delen:

1. Een vaste, handmatige coinlijst in plaats van de huidige onbeperkte
   automatische groei.
2. Drie features die als "ongein" worden geschrapt: swing-signalen,
   het narrative-dashboard-onderdeel (los van de context-vergelijking,
   die blijft), en het aanmaken van nieuwe prop-evaluatie-runs.
3. Geen aparte ingreep op de Anthropic-calls zelf nu — de verwachting is
   dat de coinlijst-krimp en het negeren van niet-gevolgde coins het
   grootste deel van de besparing al opleveren. Kosten worden na
   livegang opnieuw gemeten; een gericht vervolgproject op de calls zelf
   komt pas als dat nodig blijkt.

Niet in scope: dagtrading (Discord + eigen scan), SMC, en de drie
structurele detectoren (patroon, uitbraak+terugtest, trendlijn+terugtest)
blijven functioneel ongewijzigd — alleen het aantal coins waarop ze
draaien krimpt. `ENABLE_ADVANCED_FACTORS` en de rest van de config
blijven ongewijzigd. Geen bredere visuele herontwerp van dashboard/
coin-pagina — alleen de UI-onderdelen die bij de geschrapte features
horen worden verwijderd.

## 1. Vaste coinlijst

Nieuwe constante (locatie te bepalen in de plan-fase, waarschijnlijk
`app/config.py` of `app/coinlist.py`):

```python
FIXED_COINS = ["BTC", "ETH", "SOL", "BNB", "AVAX", "DOGE", "SUI"]
```

Migratie zet elke bestaande rij in `coins` die niet in `FIXED_COINS` staat
op `active = 0` — geen dataverlies, de coin verdwijnt alleen uit de
actieve scan. De migratie zorgt ook dat deze 7 coins bestaan en
`active = 1` zijn (aanmaken als ze nog niet bestaan).

`app/market_scanner.py`'s `scan_market()` blijft ongewijzigd
`repo.list_coins()` (`WHERE active = 1`) gebruiken — de scan krimpt dus
vanzelf naar deze 7 coins zonder dat `market_scanner.py` zelf hoeft te
weten van `FIXED_COINS`.

`app/coinlist.py::ensure_coin_tracked()` en `app/repo.py::add_coin_if_new()`
voegen een coin die niet in `FIXED_COINS` staat nooit meer toe, ongeacht
wie ze aanroept (Discord-verwerking, source-levels, dagtradinginterpretatie).

### Filter op inkomende Discord-berichten

Een tweetraps-filter, in `app/signal_processor.py::handle_message` (of de
vroegst mogelijke plek in die pipeline):

1. **Vóór de Anthropic-call**: als het bericht geen bijlage/afbeelding
   heeft ÉN de tekst geen van de 7 symbolen of hun volledige naam bevat
   (BTC/Bitcoin, ETH/Ethereum, SOL/Solana, BNB/Binance Coin,
   AVAX/Avalanche, DOGE/Dogecoin, SUI/Sui), wordt het bericht genegeerd:
   geen `anthropic_interpret.interpret_message`-aanroep, geen opslag.
   Een bericht mét afbeelding wordt altijd nog geïnterpreteerd — een
   screenshot is niet goedkoop op tekst te filteren, en dat is precies
   het scenario waarin dit filter een echt signaal zou kunnen missen als
   het ook afbeeldingen zou overslaan.
2. **Ná de interpretatie**: als Anthropic alsnog een coin teruggeeft die
   niet in `FIXED_COINS` staat (kan bij een screenshot die buiten stap 1
   om alsnog geïnterpreteerd werd), wordt het resultaat genegeerd: geen
   signaal, geen coin-toevoeging. Dit is het vangnet voor het geval dat
   stap 1 niet kon filteren.

De naam-alias-lijst (symbool → volledige naam) is een simpele, statische
mapping, geen aparte databronnentabel.

## 2. Ongein eruit

### Swing: volledig weg

`app/signal_processor.py::handle_message` roept `evaluate_level_watch`
niet meer aan voor `lange_termijn`/`aandelen`-categorie berichten. Geen
nieuwe rijen in `swing_watches`, dus geen nieuwe swing-signalen.
`level_check.py::check_swing_watches()` blijft ongewijzigd bestaande,
nog openstaande watches afhandelen tot ze resolven of vervallen — daarna
wordt die functie vanzelf stil (leest alleen `status = 'wachtend'`-rijen,
die er zonder nieuwe aanmaak op den duur niet meer zijn). Bestaande
swing-trades (rijen in `signals` met `trade_type = 'swing'`, gekoppelde
`journal_entries`) blijven gewoon zichtbaar in journaal, trackrecord en
coin-pagina.

### Narrative: data blijft, melding en dashboard-blok weg

**Belangrijk technisch punt, ontdekt tijdens het brainstormen**: de
bestaande "vergelijk dagtradingsignaal met de laatste lange-termijn-
richting"-functionaliteit (`signal_processor.py::_build_context_note`,
al onderdeel van de kernpijplijn, zie CLAUDE.md) leest uitsluitend uit
`coin_narratives` (via `repo.get_active_narrative`/`list_narratives_for_coin`).
Die tabel wordt gevuld door `evaluate_narrative`. Als `evaluate_narrative`
volledig zou stoppen, stopt ook de context-vergelijking voor elk
lange-termijn-bericht ná de cutoff — dat is niet de bedoeling, de
context-vergelijking hoort bij de dagtradingkern, niet bij het
"narrative-dashboard" dat als ongein gezien wordt.

Daarom een gerichter snijpunt:
- `evaluate_narrative` blijft `coin_narratives` bijwerken (aanmaken,
  voortgang, afsluiten) — puur als interne data, geen gebruikersgerichte
  functie meer.
- `_send_narrative_notifications` wordt niet meer aangeroepen vanuit
  `evaluate_narrative`: geen eigen "lopend verhaal bevestigd/
  tegengesproken"-pushmelding meer.
- Het losse narrative-blok op de coin-pagina (`coin.html`, het
  `coin_narratives`-leesblok, los van de context-regel die al in een
  dagtradingsignaal-toelichting verschijnt) wordt verwijderd.
- `_build_context_note` zelf blijft ongewijzigd en blijft dus ook voor
  nieuwe lange-termijn-berichten werken.
- `level_check.py::check_narratives()` (de vervalcheck) blijft
  ongewijzigd — die opereert toch al alleen op de tabel, niet op de
  melding.

### Prop-evaluatie: geen nieuwe runs meer

`web/main.py`'s `POST /evaluatie/start` route verdwijnt (of geeft een
duidelijke "niet meer beschikbaar"-reactie in plaats van een nieuwe
`prop_evaluations`-rij aan te maken). Het bijbehorende formulier in
`evaluatie.html` en de "Start een evaluatie →"-link op het dashboard
(`dashboard.html`, getoond als er geen actieve evaluatie is) worden
verwijderd. `POST /evaluatie/stop` en de leesweergave (`GET /evaluatie`,
de evaluatiegrafiek, de dashboard-kaart voor een eventuele nog lopende of
afgesloten evaluatie) blijven ongewijzigd: een gebruiker met een al
lopende evaluatie kan die nog afsluiten, en oude evaluatie-runs blijven
zichtbaar.

## Wat niet verandert (nogmaals expliciet)

- Dagtrading (Discord-gedreven én de autonome scan), SMC, patroon,
  uitbraak+terugtest, trendlijn+terugtest: functioneel ongewijzigd.
- `journal_entries`, portfolio/risk-berekening, alle bestaande historische
  data (ook van swing/narrative/evaluatie): blijft intact en zichtbaar.
- Geen wijziging aan `ENABLE_ADVANCED_FACTORS`, `TOGGLEABLE_FACTORS`, of
  enige andere bestaande configuratie.
- Geen wijziging aan de systemd-timers/intervallen.
- Geen bredere visuele herziening van dashboard/coin-pagina — alleen de
  UI-elementen die bij de drie geschrapte aanmaak-paden horen.

## API-kosten: meten, niet nu al ingrijpen

Geen directe wijziging aan `anthropic_interpret.py`, `explain.py`, of de
modellen die ze gebruiken. De verwachte besparing komt uit twee dingen die
hierboven al beschreven staan: veel minder coins om te scannen (elke
scan-cyclus roept `explain_signal` per coin aan, `config.py` markeert dit
nu al als de snelst groeiende kostenpost) en het negeren van berichten
over niet-gevolgde coins vóór de interpretatie-call. Na livegang worden de
kosten opnieuw gemeten; blijkt er dan nog gericht iets nodig
(bijvoorbeeld `explain_signal` niet elke cyclus opnieuw voor hetzelfde
signaal aanroepen), dan wordt dat een apart, kleiner vervolgproject.

## Testen

Geen pytest-suite in dit project. Verificatie zoals gebruikelijk met
throwaway scripts tegen een scratch-database (`DATABASE_PATH=/tmp/...`):
- Migratie: bevestig dat na de migratie alleen de 7 `FIXED_COINS` actief
  zijn, en dat een coin die al journaalregels/signalen had niet verdwijnt
  (alleen `active` verandert, geen rijen worden verwijderd).
- Filter: synthetische Discord-berichten (met/zonder afbeelding,
  met/zonder herkenbare coin-naam) testen tegen de nieuwe filterlogica,
  gemockte `anthropic_interpret.interpret_message` om te bevestigen dat
  hij wel/niet aangeroepen wordt zoals verwacht.
- Swing/narrative/evaluatie: bevestig dat `evaluate_level_watch` niet
  meer aangeroepen wordt vanuit `handle_message` voor de relevante
  categorieën, dat `evaluate_narrative` nog wel `coin_narratives` vult
  maar geen melding meer verstuurt, en dat `POST /evaluatie/start` geen
  nieuwe rij meer aanmaakt terwijl `GET /evaluatie` en `POST
  /evaluatie/stop` blijven werken.
- Regressie: bestaande signalen/journaalregels van vóór de wijziging
  blijven queryable en zichtbaar op dashboard/coin-pagina.
