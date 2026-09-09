# Landingspagina uitbreiden: risico, journaal, evaluatie — ontwerp

## Aanleiding

De openbare landingspagina (`web/templates/landing.html`) legt al uit hoe
een signaal binnenkomt, hoe het getoetst wordt, en wanneer iets hoog
vertrouwen is — met live prijzen in de tickerstrook en een voorbeeld-
melding in een telefoon-mockup. Voor iemand die de site voor het eerst
ziet en niets van trading of van HesPulse weet, ontbreken drie stukken
die net zo essentieel zijn: hoe positiegrootte/risico werkt, dat elke
trade in een journaal terechtkomt, en dat er een gratis evaluatie-
simulator bestaat. Deze laatste ontbreekt op dit moment volledig op de
publieke pagina.

Doel: dezelfde pagina uitbreiden met drie nieuwe secties, in dezelfde
stijl en met hergebruik van de bestaande CSS-klassen (`.steps`,
`.factor-grid`, `.landing-section`), zodat een complete leek na het lezen
het hele systeem begrijpt — niet alleen hoe een melding tot stand komt,
maar ook wat er met zijn geld gebeurt en waarom de evaluatie bestaat.

## Niet-doelen

- Geen nieuwe route, geen nieuwe pagina — dit blijft één landingspagina.
- Geen wijziging aan de bestaande vier secties (over ons, hoe het werkt,
  Telegram koppelen, hoog vertrouwen) — die blijven zoals ze zijn.
- Geen nieuwe CSS-componenten: de nieuwe secties hergebruiken `.steps`,
  `.landing-section`, `.kraken-card`-achtige structuur. Als tijdens de
  implementatie blijkt dat een layout toch niet met bestaande klassen
  past, is een kleine, gerichte toevoeging aan style.css toegestaan,
  maar geen nieuw grid-systeem.
- Geen backend-wijziging. Alle content is statisch; er is geen live data
  nodig die nog niet al via `/api/public_prices` beschikbaar is.

## Plaatsing

Na de bestaande `#hoog-vertrouwen`-sectie, vóór de Kraken-referral-kaart
aan het einde. Volgorde: risico en positiegrootte → journaal → evaluatie.
Dat is de natuurlijke volgorde van wat er met een signaal gebeurt: het
komt binnen, wordt getoetst (bestaand), krijgt een positiegrootte (nieuw),
wordt bijgehouden (nieuw), en de evaluatie is de "oefen dit veilig"-laag
erbovenop (nieuw, sluit af met een eigen registratie-knop).

De nav in de header krijgt drie nieuwe ankerlinks, in dezelfde vorm als
de bestaande vier:

```html
<a href="#risico-en-positie">Risico</a>
<a href="#journaal">Journaal</a>
<a href="#evaluatie">Evaluatie</a>
```

Toegevoegd na de bestaande `<a href="#hoog-vertrouwen">Hoog vertrouwen</a>`,
vóór `<a href="/login">Inloggen</a>`.

## Sectie: Risico en positiegrootte

```html
<section class="landing-section" id="risico-en-positie" style="--i: 5">
  <h2>Risico en positiegrootte</h2>
  <p>Bij het registreren vul je twee dingen in: je portefeuille in euro's,
  en het percentage dat je per trade wilt riskeren. HesPulse rekent daar
  zelf een bedrag uit, en gebruikt dat om te bepalen hoeveel coin je zou
  moeten kopen — nooit een vast aantal, altijd afgestemd op de afstand tot
  de stop loss.</p>
  <div class="steps">
    <div class="step">
      <div class="num">1</div>
      <p><strong>Risicobedrag</strong> Portefeuille × risicopercentage. Bij
      €1.000 en 1% is dat €10 — het maximale bedrag dat je op deze ene
      trade zou verliezen als de stop loss geraakt wordt.</p>
    </div>
    <div class="step">
      <div class="num">2</div>
      <p><strong>Positiegrootte</strong> Risicobedrag gedeeld door de
      afstand tussen entry en stop loss. Een stop dichtbij geeft een
      kleinere positie nodig voor hetzelfde risico, een stop verder weg
      een grotere — het bedrag dat op het spel staat blijft gelijk.</p>
    </div>
    <div class="step">
      <div class="num">3</div>
      <p><strong>Altijd zichtbaar</strong> Elke melding en elke open
      trade toont de berekende grootte, de stop loss en de take profit
      erbij. Geen rekenwerk zelf nodig, en nooit een verrassing achteraf.</p>
    </div>
  </div>
</section>
```

## Sectie: Journaal

```html
<section class="landing-section" id="journaal" style="--i: 6">
  <h2>Journaal</h2>
  <p>Elke melding die je opvolgt komt in een journaal terecht: coin,
  richting, entry, exit, en het resultaat in euro's. Niets hoef je zelf
  bij te houden.</p>
  <p>Je winrate staat altijd zichtbaar, uitgesplitst naar hoog en laag
  vertrouwen. Zo zie je met cijfers of het systeem voor jou werkt, in
  plaats van op gevoel te vertrouwen na een paar goede of slechte trades.</p>
</section>
```

## Sectie: Evaluatie

```html
<section class="landing-section" id="evaluatie" style="--i: 7">
  <h2>Oefen een prop-evaluatie, gratis</h2>
  <p>Bij aanbieders als Kraken Prop koop je een evaluatie: een periode
  waarin je onder strikte regels handelt — een dagverlieslimiet, een
  maximale drawdown, een winstdoel. Haal je dat, dan krijg je een
  gefinancierde rekening en deel je de winst die je daarna maakt met de
  aanbieder.</p>
  <p>HesPulse simuleert precies zo'n evaluatie, zonder dat het iets
  kost. Je stelt zelf een tier, winstdoel en max drawdown in, en elke
  oefentrade die je neemt terwijl de evaluatie loopt telt automatisch
  mee.</p>
  <div class="steps">
    <div class="step">
      <div class="num">1</div>
      <p><strong>Live grenzen in beeld</strong> Dagverlies, drawdown en
      winstdoel staan als balken op het scherm, precies zoals je ze bij
      een echte evaluatie zou bijhouden.</p>
    </div>
    <div class="step">
      <div class="num">2</div>
      <p><strong>Vooraf rekenen, niet achteraf ontdekken</strong> Voordat
      je een oefentrade neemt zie je al wat die betekent voor je saldo,
      bij winst en bij verlies.</p>
    </div>
    <div class="step">
      <div class="num">3</div>
      <p><strong>Je eigen disciplineprofiel</strong> Na een paar trades
      laat HesPulse zien waar je zelf het vaakst wint of verliest — bij
      welk vertrouwen-niveau, welk risico, welk moment van de dag.</p>
    </div>
  </div>
  <a href="/registreer" class="button-primary">Registreren en oefenen</a>
</section>
```

## Zelf-review

**Niet-doelen nageleefd**: geen nieuwe route, geen backend-wijziging,
alleen `.landing-section`/`.steps` hergebruikt, geen nieuwe CSS-klassen
bedacht.

**Toon**: sobere, directe stijl consistent met de rest van de pagina —
korte zinnen, concrete voorbeelden (€1.000, 1%, €10), geen wervende taal.

**Stagger-index**: bestaande secties gebruiken `--i: 0` t/m `--i: 5`
(hero t/m Kraken-kaart). De Kraken-kaart zelf staat nu op `--i: 5`; de
drie nieuwe secties ertussen schuiven die door naar `--i: 8`, en de
nieuwe secties krijgen `--i: 5, 6, 7`. Dit moet bij implementatie
gecontroleerd worden tegen de dan-actuele bestandsinhoud, niet blind
overgenomen — de Kraken-kaart se huidige `--i`-waarde moet in de diff
zichtbaar meeschuiven.

**Content-herhaling gecontroleerd**: "risicobedrag" en "positiegrootte"
komen nergens anders op de landingspagina voor; "journaal" ook niet;
"evaluatie" ook niet. Geen overlap met de bestaande vier secties.
