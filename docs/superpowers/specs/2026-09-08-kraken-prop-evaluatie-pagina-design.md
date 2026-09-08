# Kraken Prop evaluatie: eigen pagina — ontwerp

## Aanleiding

De evaluatie-simulator (spec `2026-09-07-kraken-prop-evaluatie-design.md`,
volledig gebouwd en live) leeft nu als één kaart op het dashboard. De
gebruiker wil dat dit een volwaardige, eigen pagina wordt: groter, met een
echte grafiek in plaats van dag-stippen, uitleg over waarom de regels
bestaan, en concrete disciplinetips van een ervaren trader.

Dit ontwerp bouwt bovenop het bestaande backend-model zonder het te
wijzigen: `prop_evaluations`, `journal_entries.evaluation_id`,
`risk.evaluate_prop_progress`, alle bestaande repo-functies en routes
blijven exact zoals ze zijn. Deze spec voegt alleen nieuwe leesfuncties en
een nieuwe pagina toe.

## Niet-doelen

- Geen wijziging aan de evaluatie-regels zelf (dagverlies/drawdown/
  winstdoel-berekening blijft ongewijzigd, `risk.py` wordt niet
  aangeraakt).
- Geen wijziging aan hoe oefentrades aan een run gekoppeld worden.
- Geen backfill: de saldografiek toont alleen wat er sinds het bestaan van
  deze feature daadwerkelijk gebeurd is.

## Navigatie en dashboard

Nieuwe link in `base.html`'s `<nav>`, naast "Dashboard" en "Uitleg":
`<a href="/evaluatie">Evaluatie</a>`.

Het dashboard verliest zijn huidige, volledige evaluatie-kaart (drie
balken, dag-stippen, start/stop-formulieren) en krijgt in plaats daarvan
één compacte samenvattingsregel:

- Actieve run: tier, huidig saldo, status, en een link "Bekijk evaluatie
  →" naar `/evaluatie`. Geen balken, geen formulieren — puur een
  aanwezigheidssignaal.
- Geen actieve run: "Nog geen evaluatie actief" met een link "Start een
  evaluatie →" naar `/evaluatie` (waar het startformulier nu staat).
- Zojuist beëindigd (geslaagd/mislukt): dezelfde reveal-mechaniek (URL-vlag, eenmalig,
  client-side opgeruimd) blijft bestaan, maar toont zich op `/evaluatie`.
  `/journal/{id}/close` blijft ongewijzigd en zet de vlag op de `next`-bestemming.
  Omdat het strip-script in `base.html` de vlag anders al op die tussenpagina zou
  weghalen — waardoor het reveal nooit afspeelt — stuurt `base.html` bij een
  aanwezige vlag op elke andere pagina dan `/evaluatie` direct door
  (`location.replace`, zodat de tussenpagina niet in de terug-historie komt);
  `dashboard.js` doet hetzelfde voor het AJAX-sluitpad op basis van `resp.url`.
  Pas op `/evaluatie` zelf wordt de vlag opgeruimd, zodat de animatie precies één
  keer speelt. De winst-confetti wordt overgeslagen als deze paginalading zichzelf
  meteen weer verlaat voor dat reveal.

## Nieuwe pagina: `/evaluatie`

Route `GET /evaluatie`, achter `require_login`, nieuwe template
`web/templates/evaluatie.html`.

### Sectie 1: statuskop

Hergebruikt de bestaande drie balken (risk-gauge/risk-mid/risk-high/
goal-fill) en het geslaagd/mislukt-reveal exact zoals ze nu op het
dashboard staan, alleen groter/prominenter gepositioneerd (eigen sectie
bovenaan de pagina, niet gedeeld met andere dashboard-content). Voegt één
uitgelicht kerngetal toe: resterende euro-ruimte tot de dagverlieslimiet
(`day_start_balance * max_daily_loss_pct/100 - loss_so_far`), groot en
duidelijk, want dat is het getal waar een trader tijdens het handelen het
meest naar kijkt.

Als er geen actieve run is: het bestaande startformulier (tier, winstdoel-
percentage, max-drawdown-percentage), verplaatst van het dashboard naar
hier, ongewijzigd in velden en validatie.

### Sectie 2: saldografiek

Nieuwe repo-functie:

```python
def list_evaluation_balance_curve(evaluation_id: int) -> list[dict]:
    """Cumulatieve saldo-lijn voor de grafiek: één punt bij de start
    (tier_amount, started_at) en daarna één punt per gesloten, aan deze
    run gekoppelde trade, oplopend saldo. Anders dan
    list_evaluation_daily_results (dat per handelsdag optelt voor de
    dag-stippen-heatmap) geeft dit de exacte volgorde van individuele
    trades terug, wat een vloeiende lijn mogelijk maakt in plaats van een
    grof dagoverzicht."""
```

Elk punt: `{"time": <ISO-timestamp>, "balance": <float>}`. Geïmplementeerd
door de evaluatie op te halen (voor `tier_amount` en `started_at`), dan
alle gesloten, gekoppelde `journal_entries` op `exit_time` gesorteerd op
te halen, en een lopende som van `result_eur` bij te houden, startend bij
`tier_amount`.

Nieuwe `web/static/evaluatie.js` (eigen bestand, zelfde patroon als
`coin.js`: één module per pagina, niet bijgebouwd in `dashboard.js`).
Gebruikt LightweightCharts (al geladen via CDN elders in de app, dezelfde
`<script src="https://cdn.jsdelivr.net/npm/lightweight-charts@4/...">`-
regel) met een line series voor het saldo. Twee horizontale referentie-
lijnen via `series.createPriceLine(...)`:

- Rood, op `tier_amount * (1 - max_drawdown_pct/100)` — de drawdown-bodem.
- Groen, op `tier_amount * (1 + profit_target_pct/100)` — het
  winstdoel-plafond.

Geen candles, geen trendlijnen-tekentool (dat blijft exclusief voor de
coin-pagina's prijsgrafiek) — puur de saldo-lijn plus de twee vaste
niveaus.

### Sectie 3: waarom deze regels bestaan

Statische, door mij geschreven uitleg (geen per-gebruiker berekening),
in dezelfde spartaanse, praktische toon als de rest van de app:

- Waarom een dagverlieslimiet bestaat: voorkomt dat één slechte dag escaleert
  tot een grote, omdat de limiet je dwingt te stoppen voordat frustratie
  de beslissingen gaat sturen.
- Waarom drawdown nooit reset: een goede week mag een slechte maand niet
  verbergen — het dwingt consistentie over de hele looptijd af, niet een
  losse geluksdag.
- Waarom er geen tijdslimiet is: druk om "op tijd" te slagen leidt tot
  overhaaste trades; zonder deadline is de enige weg naar slagen
  daadwerkelijk goed handelen.

### Sectie 4: disciplineregels

Een korte, concrete lijst (geen wall of text), bijvoorbeeld:

- Stop voor de dag na twee verliezen op rij, ook als de limiet nog niet
  geraakt is — de limiet is een noodrem, geen doel om tegenaan te
  handelen.
- Bepaal je risico per trade vóór je instapt. Achteraf uitrekenen is
  rationalisatie, geen risicobeheer.
- Een winstdoel halen in de eerste dagen is geen prestatie om te vieren,
  het is een signaal om extra voorzichtig te zijn: het verklaart vaak
  meer geluk dan proces.
- Een virtuele evaluatie die faalt kost niets — gebruik dat: test hier
  precies het gedrag dat een echte evaluatie zou breken, niet je
  makkelijkste trades.

### Sectie 5: geschiedenis met patronen

Nieuwe aggregatie, berekend in de webroute (geen nieuwe SQL, werkt op het
al bestaande resultaat van `repo.list_evaluations_for_user`):

- Gemiddeld aantal dagen tot een geslaagde run (over alle `status =
  'geslaagd'`-runs met een `ended_at`).
- Gemiddeld aantal dagen tot een mislukte run (zelfde, voor `status =
  'mislukt'`).
- Meest voorkomende `closed_reason` onder de mislukte runs (simpele
  `Counter`, geen nieuwe kolom nodig).

Als er minder dan 2 afgeronde runs zijn, worden deze statistieken
verborgen in plaats van een misleidend "gemiddelde" van één run te tonen.

Daaronder de bestaande geschiedenis-lijst (tier, resultaat,
gestart/geëindigd, reden), ongewijzigd overgenomen van de huidige
dashboard-implementatie.

## Aanvulling: gekozen creatieve uitbreidingen

Na goedkeuring van bovenstaand ontwerp zijn vier extra elementen gekozen,
elk met een concrete, haalbare technische invulling (niet elk oorspronkelijk
idee vertaalt zich 1-op-1 naar wat LightweightCharts native ondersteunt —
onderstaande is de eerlijke, gebouwde versie).

**Kleurindicatie op de saldolijn.** Geen losse 3-kleuren-verloop (niet
native ondersteund door de gebruikte chart-library zonder fragiele
custom-rendering), maar een baseline-series: groen boven de
drawdown-bodem, rood eronder. Dezelfde betekenis — de lijn toont zelf of
je aan de veilige of gevaarlijke kant zit — met een robuuste, native
bibliotheek-functie in plaats van een handgerolde gradient.

**Ademende vulling in de gevarenzone.** Zodra dagverlies- of
drawdown-opgebruik ≥85% is (dezelfde drempel als `.risk-pulse` elders in
de app) én de run nog `actief` is, pulseert de rode vulling onder de
basislijn zachtjes tussen twee opaciteitswaarden, elke 1,2 seconde
(canvas-rendering kan niet met CSS-animaties bewogen worden, dus dit
gebeurt via een JS-interval). Stopt zodra het tabblad niet zichtbaar is
(`visibilitychange`) en start niet als `prefers-reduced-motion: reduce`
staat — zelfde discipline als elke bestaande animatie in de app.

**Statusafhankelijke coaching-tip.** Vervangt geen vaste tekst, maar een
functie die op basis van de actuele percentages van een actieve run een
van twee scherpe tips teruggeeft (dicht bij een limiet: overweeg te
stoppen; dicht bij het winstdoel: waarschuwing voor verslappende
discipline), of niets als er niks bijzonders aan de hand is.

**Sectie "wat een ervaren trader nooit doet".** Statische, contrasterende
aanvulling naast de disciplineregels — dezelfde soort content, ander
format.

## Zelf-review

**Niet-doelen nageleefd**: geen wijziging aan `risk.py`, aan de
regel-logica, of aan hoe trades gekoppeld worden — deze spec voegt
uitsluitend leesfuncties en een nieuwe pagina toe.

**Hergebruik**: de drie balken, het reveal-mechanisme, en de bestaande
CSS-klassen worden 1-op-1 hergebruikt op de nieuwe pagina; geen dubbele
CSS voor hetzelfde concept.

**Databasetoegang**: `list_evaluation_balance_curve` is de enige nieuwe
repo-functie; de geschiedenis-statistieken hebben geen nieuwe query nodig
en horen daarom niet in `repo.py` maar in de webroute zelf (puur
aggregatie op al opgehaalde data, geen eigen databasetoegang).
