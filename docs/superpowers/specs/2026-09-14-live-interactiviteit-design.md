# Live interactiviteit: het dashboard voelt bewegender aan

## Aanleiding

De gebruiker wil dat de site "bewegender" en "interactiever" aanvoelt: meer
live gevoel, zoals een koers die door een banner beweegt of een melding bij
de laatste update. Uit een lijst van zes ideeën heeft de gebruiker gekozen:
alle zes bouwen. Dit document ontwerpt ze samen, omdat ze grotendeels
dezelfde bestanden raken (base.html, dashboard.js, style.css) en drie ervan
letterlijk uitbreidingen zijn van iets dat al bestaat.

## Niet-doelen

- Geen enkele animatie draait op een verzonnen of decoratieve waarde: elke
  beweging hierin is aan een echte, actuele waarde gekoppeld. Dit is een
  vaste conventie uit CLAUDE.md, geen nieuwe regel.
- Geen nieuwe polling-interval toegevoegd: alles hergebruikt de bestaande
  20-seconden-cyclus van `/api/open_positions` (dashboard.js) of de
  bestaande `/api/system_status`-cyclus (base.html), op één uitzondering na
  (Sectie 1, zie daar).
- Geen wijziging aan de landingspagina se bestaande ticker (`.ticker-strip`
  in `landing.html`): die blijft ongemoeid, Sectie 1 hergebruikt alleen zijn
  CSS-klassen.
- Elke nieuwe animatie respecteert `prefers-reduced-motion`, net als alle
  bestaande animaties in style.css.

## Sectie 1: koersticker in de topbar (nieuw)

**Waar:** `web/templates/base.html`, topbar (rond regel 269-300), alleen
zichtbaar voor een ingelogde gebruiker MET minstens één open, echte trade.
Zonder open trades geen ticker: een lege of met voorbeeldwaarden gevulde
ticker op een pagina waar het net om echte cijfers gaat, hoort niet bij dit
project se eigen regel (CLAUDE.md: gemeten vs. geschat, nooit verzonnen).

**Hergebruik:** de landingspagina heeft al exact dit patroon
(`.ticker-strip`/`.ticker-track`/`.ticker-item`/`.ticker-price`,
`ticker-scroll`-keyframe, al met `prefers-reduced-motion`-uitzondering in
style.css regel 994-1008). Dezelfde CSS-klassen, geen nieuwe animatie
nodig, alleen nieuwe content en een nieuwe databron.

**Databron:** `/api/open_positions` (bestaand, al elke 20s gepolld door
dashboard.js) geeft per open positie al `coin` en `current_price` terug.
Geen nieuw endpoint nodig. dashboard.js se bestaande `refresh()`-functie
krijgt een extra stap: bouw/werk de ticker-items bij uit dezelfde
`positions`-array, in plaats van een aparte fetch.

```js
// Nieuw stuk in dashboard.js se refresh(), na de bestaande forEach over
// positions: dezelfde poll-data hergebruikt voor de topbar-ticker.
function updateTicker(positions) {
  const track = document.getElementById("dashboard-ticker-track");
  if (!track) return; // geen open trades -> topbar toont geen ticker-element
  const real = positions.filter((p) => !p.is_practice && p.current_price !== null);
  const seen = new Set();
  const items = real.filter((p) => {
    if (seen.has(p.coin)) return false;
    seen.add(p.coin);
    return true;
  });
  items.forEach((p) => {
    let el = track.querySelector(`[data-ticker-coin="${p.coin}"]`);
    if (!el) return; // server rendert de items vooraf, JS vult ze alleen
    const priceEl = el.querySelector(".ticker-price");
    const key = `ticker-${p.coin}`;
    if (previous[key] !== undefined && previous[key] !== p.current_price) {
      flash(priceEl, p.current_price > previous[key]);
    }
    previous[key] = p.current_price;
    priceEl.textContent = p.current_price.toFixed(4);
  });
}
```

**Server-kant:** `web/main.py`'s `dashboard`-route geeft nu al
`taken_entries` door aan de template. Nieuw: een kleine, losse
`ticker_coins`-lijst (unieke coins uit `taken_entries`, alleen echte, niet
oefen) aan de template-context toevoegen, zodat `base.html` de
`data-ticker-coin`-items server-side kan voorrenderen (zelfde patroon als
`landing.html` doet, alleen met de eigen coins van de gebruiker in plaats
van een vaste BTC/ETH/SOL-lijst). `base.html` wordt door ELKE pagina
uitgebreid (het is het basis-template), dus deze context moet via een
Jinja `{% block %}`-conditie of een globale context-processor beschikbaar
zijn op elke pagina — eenvoudigste weg: alleen renderen als de huidige
route "dashboard" is (`request.url.path`), anders het blok leeg laten.

**Uitzondering op "geen nieuw poll-interval":** de topbar zit ook op
pagina's zonder de 20s-poll van dashboard.js (bijvoorbeeld de coin-pagina).
Voor dit deelproject beperkt de ticker zich tot het dashboard zelf (waar de
poll toch al draait); op andere pagina's toont de topbar geen ticker-element
(server-side leeg, geen lege ruimte).

## Sectie 2: laatste seintje als lopende banner (nieuw, bouwt voort op bestaand)

**Bestaand fundament:** `base.html` heeft al `triggerSignalWave()` (regel
721-730) en een `#signal-wave`-element, getriggerd zodra
`lastPendingCount` in `/api/system_status` stijgt. Dat is nu een puur
visueel lichteffect zonder tekst.

**Nieuw:** een tekstregel naast/in hetzelfde signaalgolf-moment, die het
laatste signaal en het tijdstip toont, en zacht vervaagt naar de volgende
zodra er een nieuwer signaal binnenkomt. Geen aparte polling: `/api/system_status`
wordt al elke cyclus opgehaald; dat endpoint krijgt een klein extra veld
`last_signal` (coin, richting, vertrouwen/label, ontvangen_at) uit
`repo.list_recent_signals`-achtige data (bestaande query, LIMIT 1, ORDER BY
created_at DESC, `is_practice = 0`).

```html
<!-- base.html, direct onder de topbar, alleen gerenderd als er een
     laatste signaal is (server-side, voorkomt een lege flits bij het
     allereerste bezoek zonder ooit een signaal) -->
<div class="last-signal-banner" id="last-signal-banner" aria-live="polite">
  <span id="last-signal-text">{{ last_signal_text or "" }}</span>
</div>
```

```js
// In base.html se bestaande refresh() (system_status-cyclus), na de
// bestaande heartbeat/glow-updates:
if (s.last_signal && s.last_signal.id !== lastSignalId) {
  lastSignalId = s.last_signal.id;
  var banner = document.getElementById("last-signal-text");
  if (banner) {
    banner.style.opacity = 0;
    setTimeout(function () {
      banner.textContent = s.last_signal.coin + " · " + s.last_signal.label + " · " + timeAgo(s.last_signal.received_at);
      banner.style.opacity = 1;
      triggerSignalWave();
    }, 300);
  }
}
```

`lastSignalId` (niet `lastPendingCount`) voorkomt dat het banner opnieuw
"triggert" als een bestaand pending signaal simpelweg ouder wordt getoond;
het reageert puur op een NIEUW signaal-ID, dezelfde eerste-load-guard als
`lastPendingCount` (begin op `null`, geen wave bij het eerste laden).

## Sectie 3: live voortgangsbalk naar SL/TP (nieuw op web, bestond al in Telegram)

**Bestaand fundament:** `app/telegram_notify.py`'s `_progress_bar` berekent
al exact dit percentage (waar zit de prijs tussen stop en take profit) voor
de tekstbalk in een Telegram-bericht. Dezelfde formule, nu als CSS-balk.

**Waar:** `web/templates/_macros.html`'s `open_trade_body`-macro (regel
40+), toegevoegd na het bestaande cijferraster, vóór de PnL-regel.

```html
<!-- Nieuw in open_trade_body, na de data-grid -->
<div class="sltp-progress" data-sltp="{{ e.id }}"
     data-stop="{{ e.stop_loss }}" data-take="{{ e.take_profit }}" data-direction="{{ e.direction }}">
  <div class="sltp-progress-fill" style="width: {{ e.sltp_progress_pct }}%"></div>
</div>
```

`e.sltp_progress_pct` wordt server-side voorberekend (zelfde formule als
`_progress_bar`, als een kleine, gedeelde pure functie in `app/risk.py` die
zowel `telegram_notify._progress_bar` als deze nieuwe server-side waarde
gebruikt — geen logica dupliceren tussen Telegram en web).

**Live bijwerken:** dashboard.js se bestaande `refresh()` (elke 20s, al
lopend over `positions`) krijgt een extra regel per positie:

```js
const sltpEl = document.querySelector(`[data-sltp="${p.id}"] .sltp-progress-fill`);
if (sltpEl && p.current_price !== null && p.stop_loss && p.take_profit) {
  const pct = computeSltpProgressPct(p.direction, p.current_price, p.stop_loss, p.take_profit);
  sltpEl.style.width = pct + "%"; // CSS transition doet de vloeiende beweging, geen JS-animatie
}
```

`computeSltpProgressPct` is een kleine JS-poort van dezelfde formule
(dezelfde drie getallen, geen serverroundtrip nodig voor de live-update —
de eerste render komt server-side, elke update daarna client-side met
dezelfde formule). CSS: `.sltp-progress-fill { transition: width 0.6s ease,
background-color 0.6s ease; }`, kleur loopt van rood (dicht bij stop) via
neutraal naar groen (dicht bij take profit), zelfde rood/groen-tokens als
de rest van de site.

## Sectie 4: ademende risico-indicator (uitbreiding van de bestaande risicogauge)

**Bestaand fundament:** `.risk-gauge-fill` (style.css regel 568-591) bestaat
al, met `risk-mid`/`risk-high`-kleurklassen en een shimmer-`::after` die al
`prefers-reduced-motion` respecteert.

**Nieuw:** de shimmer se snelheid wordt een CSS custom property in plaats
van een vaste duur, gezet door dezelfde `/api/system_status`-cyclus als de
bestaande hartslag/ambient-puls:

```css
.risk-gauge-fill::after { animation-duration: var(--risk-pulse-duration, 2.4s); }
```

```js
// base.html se bestaande refresh(), naast heartbeatDuration/ambientScrollDuration.
// pct is: voor een evaluatie-gebruiker het hoogste van dagbudget-gebruik/
// drawdown-gebruik (0-100), zonder evaluatie het bestaande portfolio-
// open-risicopercentage. Server levert dit al (risicogauge bestaat al),
// alleen het PERCENTAGE zelf moet ook in /api/system_status terechtkomen.
function riskPulseDuration(pct) {
  if (pct === null || pct === undefined) return "2.4s";
  // Dichter bij de limiet = sneller: 2.4s bij 0%, 0.8s bij 100%.
  var duration = 2.4 - (Math.min(Math.max(pct, 0), 100) / 100) * 1.6;
  return duration.toFixed(2) + "s";
}
```

Dit is een uitbreiding van een al bestaand, al reduced-motion-vriendelijk
element: geen nieuwe animatie, alleen een dynamische duur.

## Sectie 5: muntenkaart met bewegingsrichting (nieuw, klein)

**Waar:** naast elk `[data-price]`-element (dashboard-kaarten EN
coin-pagina), een klein pijltje + kleur voor de laatste beweging.

```html
<!-- In open_trade_body, naast de bestaande "Nu"-cel -->
<div class="cell">
  <div class="k">Nu</div>
  <div class="v" data-price="{{ e.id }}">{{ "%.4f"|format(e.current_price) if e.current_price else "-" }}
    <span class="price-direction" data-price-direction="{{ e.id }}" aria-hidden="true"></span>
  </div>
</div>
```

```js
// In dashboard.js se bestaande refresh(), direct na de bestaande
// flash-aanroep voor priceEl: hergebruikt dezelfde previous[key]-vergelijking,
// geen aparte state nodig.
const dirEl = document.querySelector(`[data-price-direction="${p.id}"]`);
if (dirEl && previous[key] !== undefined) {
  dirEl.textContent = p.current_price > previous[key] ? "▲" : p.current_price < previous[key] ? "▼" : "";
  dirEl.classList.toggle("pos", p.current_price > previous[key]);
  dirEl.classList.toggle("neg", p.current_price < previous[key]);
}
```

Puur CSS voor het tekstteken (geen SVG/animatie nodig), verdwijnt vanzelf
weer bij een gelijke prijs. Dit is een letterlijke uitbreiding van de al
bestaande flash-logica (Task 45), geen apart mechanisme.

## Sectie 6: statuspuls harder bij activiteit (uitbreiding van de bestaande hartslag)

**Bestaand fundament:** `heartbeatDuration()` (base.html regel 671-678) zet
het hartslagtempo al op basis van hoelang geleden het laatste bericht
binnenkwam.

**Nieuw:** een kortstondige extra "tik" op het EXACTE moment dat
`triggerSignalWave()` afgaat (Sectie 2), niet pas bij de eerstvolgende
minuten-drempel:

```js
function triggerSignalWave() {
  var wave = document.getElementById("signal-wave");
  if (wave) {
    wave.classList.remove("is-active");
    void wave.offsetWidth;
    wave.classList.add("is-active");
  }
  // Kortstondige hartslag-boost: 3 tellen op het snelste tempo, daarna
  // valt de eerstvolgende refresh()-cyclus vanzelf terug op het tempo dat
  // bij de werkelijke tijd-sinds-laatste-bericht hoort (heartbeatDuration
  // hierboven) -- geen aparte "terug naar normaal"-timer nodig.
  document.documentElement.style.setProperty("--heartbeat-duration", "0.6s");
  setTimeout(function () {
    document.documentElement.style.setProperty("--heartbeat-duration", heartbeatDuration(lastKnownMessageAt));
  }, 3000);
}
```

`lastKnownMessageAt` is de laatst opgehaalde `s.last_message_at`-waarde,
al beschikbaar in dezelfde `refresh()`-closure, alleen in een
buiten-de-functie variabele bewaard zodat `triggerSignalWave()` er ook bij
kan.

## Testconventie

Geen pytest-suite in dit project (zie CLAUDE.md). Elke sectie krijgt:
- Een geïsoleerde test van de nieuwe/gedeelde pure functie (bv.
  `computeSltpProgressPct`/de gedeelde `risk.py`-progress-functie,
  `riskPulseDuration`) met concrete cijfervoorbeelden.
- Een handmatige Playwright-verificatie tegen een lokale `uvicorn` op een
  scratch-DB met minstens één open trade, één evaluatie-gebruiker en één
  net-binnengekomen signaal, met screenshots (zelfde patroon als eerdere
  redesign-taken in dit project) — inclusief één screenshot met
  `prefers-reduced-motion: reduce` geforceerd, om te bevestigen dat alle
  zes secties dan stilvallen zonder cijfers te verliezen.
