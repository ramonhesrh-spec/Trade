# Nieuwe indeling (app-layout naar referentie) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Elke ingelogde pagina krijgt de indeling van de referentie-app (kop met avatar en titel, één groot meetgetal met minigrafiek, drie kernregels, tekst-tabs met onderstreping, rijen per coin, zwevend zoekveld boven de pil-tabbalk, zachte gloed bovenaan), met de bestaande donkere kleuren en tokens en zonder gedrag te verliezen.

**Architecture:** Zes nieuwe macro's in `web/templates/_macros.html` plus één nieuw CSS-blok "Indeling" onderaan `web/static/style.css` vormen het hele ontwerp. `base.html` krijgt de nieuwe kop, het dok (zoekveld plus tabbalk) en de gloedlaag. Daarna zet elke pagina zijn bestaande data in die macro's; er komt geen nieuw getal bij dat niet al gemeten werd. Eén klein script (`utabs.js`) schakelt tabpanelen; zonder JS blijft alles zichtbaar onder elkaar.

**Tech Stack:** FastAPI + Jinja2, plain CSS, vanilla JS (geen bundler), stdlib `unittest` met `fastapi.testclient`, node-harnassen in `tests/js/`, Playwright (Python, al geinstalleerd) voor de 390px-controle.

**Spec:** dit document, deel 1 (ontwerpbrief). Referentie: schermafbeelding van een prop-firm-app die de gebruiker deelde (lichte app: kop "Eval 50k" met avatar, "Totaal eigen vermogen 50.000,00 USD" met lijntje rechts, drie regels Doelvermogen/Dagelijkse verlieslimiet/Drawdownlimiet, tabs Favorieten/Positions/Orders met "...", rijen BTC 10x en ETH 5x met prijs en 24 uur, zwevend "Zoeken" boven een pil-tabbalk Start/Markten/Traden/Portfolio, lichtblauwe gloed bovenaan).

## Global Constraints

- Alleen de indeling overnemen. Kleuren blijven de bestaande tokens in `:root` van `style.css` (`--bg #0a0e0f`, `--panel`, `--accent #17e5d6`, `--green`, `--red`, `--muted`, `--text`). Geen lichte modus.
- Alle pagina's met een ingelogde gebruiker in één ronde. `landing.html`, `login.html`, `register.html` blijven ongemoeid (geen tabbalk, geen gebruiker).
- Telefoon eerst: 390px breed, 16px zijmarge, geen horizontale scroll. Desktop (vanaf 761px) mag breder, maar mag niet breken.
- Geen nieuwe afhankelijkheden (geen npm, geen CDN, geen webfont erbij).
- Commentaar alleen voor het waarom.
- Alle UI-tekst Nederlands, geen em dash (ook geen en dash als gedachtestreep) in nieuwe tekst.
- Gemeten en geschat blijven gescheiden (CLAUDE.md). Een groot getal is altijd een gemeten waarde die de route al had of een bestaande functie al levert. Een kenmerkscore (✓/✗, `pass_pct`) wordt nooit als voorspeller gepresenteerd.
- Bewijs blijft eerlijk: alleen `take_profit`/`stop_loss` tellen in winrate en R, open en vervallen staan ernaast.
- Geen decoratieve beweging. De nieuwe gloed is statisch. Bestaande beweging blijft gebonden aan een live waarde en `prefers-reduced-motion` blijft gelden (de globale regel in `style.css` regel 62 dekt nieuwe transities al, maar zet nieuwe transities ook expliciet uit in het reduced-motion-blok).
- Contrast: tekst boven de gloed haalt WCAG AA (4,5:1 voor `--muted` op 13px).
- Blijven werken: pauzeknop (`#push-pause`, `pause.js`), prijsalarm-bellen (`.level-bell`, `alarm.js`), kopieerchips (`.level-copy`, `copy.js`), afstandsbalken (`.approach`, `trade_plan.approach_pct`), afstandsring (`ring.js`), sparklines (`spark.js`), trek-om-te-verversen (`smooth.js`), pushbanner (`#push-banner`, `push-banner.js`), scroll-verbergen van de tabbalk (`tabbar.js`), tik-op-actieve-tab naar boven, het Meer-blad, de command palette (Ctrl+K), de systeemstatus-popover, de koersleeftijd-stip (`#price-dot`, `stale.js`), de appicoon-badge, het swipe-om-te-sluiten.
- Bestaande tests blijven groen zonder hun verwachte tekst aan te passen. Strings die tests eisen en die dus moeten blijven staan: `class="tabbar"`, `>SMC</a>`, `>Bewijs</a>`, `>Journaal<`, `quick-actions`, `>Pauze<`, `Stil 2:00`, `aria-pressed="true"`, `1 van 6 meldingen in 24 uur`, `stroke-dashoffset="83.3"`, `Er staat niets open`, `Wacht op de zone`, `aria-label="Koers op 33% van de weg naar je instap"`, `left: 33.3%`, `r-progress`, `Doel +`, `SMC-radar`, `Resultaatcurve per soort`, `Uurkaart`, `class="hourmap"`, `class="equity-dd"`, `proof-spark`, `Nog te weinig data`, `vd-timeline`, `Plan voor BTC`, `Laatste 24 uur: 1 kans gezien, 1 beoordeeld`, `Alleen sterk en redelijk`, `Geen plan klaar`, `data-share-chart`, `laatste 7 dagen`, `Chief Executive Officer`, `Aanwezigheid`, `CEO tester`, `Meldingen staan uit op dit apparaat.` Draai na elke taak de hele suite.

---

## Deel 1. Ontwerpbrief

### 1.1 Wat we van de referentie nemen

| Referentie | HesPulse |
|---|---|
| Avatarknop links, titel met chevron | Ronde knop met de eerste letter van `user.username` (link naar `/account`), daarnaast de paginatitel als knop met chevron die het bestaande Meer-blad opent (pagina wisselen, zoals daar account wisselen). |
| Groot getal, kleine eenheid, lijntje rechts, gekleurde verandering eronder | Macro `headline`. Mono-cijfers (huisstijlregel: elk getal is IBM Plex Mono). Lijntje uit `track_record.sparkline_svg` of live uit `spark.js`. |
| Drie regels label links, waarde rechts vet, gestippeld onderstreept label met uitleg | Macro `keylines`. Uitleg via het native `popover`-attribuut, zonder JS. |
| Tekst-tabs met streep onder de actieve, "..." rechts | Macro `utabs`. Linktabs (andere URL) of paneeltabs (`utabs.js`). "..." is een `<details>`-menu. |
| Rij per markt: rond icoon, symbool plus chip, ondertitel, prijs en 24u rechts | Macro `market_row`. Icoon is een monogram (geen logo-bestanden). Prijs via `data-vd-price` (live.js), 24u via `data-spark-chg` (spark.js). |
| Zwevend rond zoekveld boven pil-tabbalk | Macro `float_search` in een nieuw `.dock` rond de bestaande `.tabbar`. Opent de bestaande command palette. |
| Veel wit, dunne lijnen, geen zware kaarten | Nieuwe klasse `.flat` voor secties: geen achtergrond, geen rand, alleen een 1px lijn erboven. Pagina's zetten `card` om naar `flat` waar het een overzicht is; formulieren en open trades houden hun kaart. |
| Lichtblauwe gloed bovenaan | Statische teal gloed in een vaste laag `.top-glow` in `base.html`, plus een zachte gloed achter de actieve tab. |

### 1.2 Tokens (toevoegen aan `:root` in `style.css`, na `--space-10`)

```css
  /* Indeling naar de referentie-app: een groot meetgetal, ruime rijen, dunne lijnen. */
  --gutter: 16px;
  --space-11: 40px;
  --space-12: 48px;
  --num-hero: clamp(38px, 10.5vw, 52px);   /* 41px op 390px: past "+12,34" plus eenheid op één regel */
  --num-hero-unit: 18px;
  --num-row: 15px;
  --row-h: 64px;                            /* marktrij, ruim genoeg voor een duim (minimaal 44px tikvlak) */
  --kl-row-h: 44px;                         /* kernregel */
  --icon-row: 36px;
  --avatar: 44px;
  --sep: 1px solid var(--border);
  --radius-pill: 999px;
  --radius-dock: 22px;
  /* Gloed bovenaan. Maximaal 8% teal: daarboven zakt --muted onder 4,5:1 (rekensom in 1.4). Niet verhogen zonder die som opnieuw. */
  --glow-top: rgba(23, 229, 214, 0.08);
  --glow-top-height: 320px;
  --glow-tab: 0 0 18px -2px rgba(23, 229, 214, 0.35);
```

Typeschaal voor de nieuwe onderdelen:

| Rol | Grootte | Gewicht | Font |
|---|---|---|---|
| Paginatitel in de kop | `var(--text-xl)` 20px | 700 | `--sans` |
| Label boven het grote getal | `var(--text-md)` 14px | 400, `--text-dim` | `--sans` |
| Groot getal | `var(--num-hero)` | 600, letter-spacing -0.02em | `--mono` |
| Eenheid achter het getal | `var(--num-hero-unit)` | 500, `--muted` | `--mono` |
| Verandering eronder | `var(--text-md)` | 600, `--green`/`--red`/`--muted` | `--mono` |
| Kernregel label | `var(--text-lg)` 16px | 400, `--text-dim` | `--sans` |
| Kernregel waarde | `var(--text-lg)` | 700, `--text` | `--mono` |
| Tab | `var(--text-lg)` | 600 actief `--text`, anders `--muted` | `--sans` |
| Rij titel | `var(--num-row)` 15px | 700 | `--mono` |
| Rij ondertitel | `var(--text-sm)` 12px | 400, `--muted` | `--sans` |
| Rij prijs en 24u | `var(--num-row)` | 600 | `--mono` |

Ruimte: zijmarge `--gutter` (16px), tussen kop en groot getal `--space-9` (24px), tussen groot getal en kernregels `--space-10` (32px), tussen kernregels en tabs `--space-9` met een `--sep`-lijn, rijhoogte `--row-h`, geen lijn tussen rijen (de referentie gebruikt alleen wit), wel een `--sep` tussen secties.

### 1.3 Gedeelde componenten (macro's, volledige code)

Voeg toe onderaan `web/templates/_macros.html`:

```jinja
{# ===== Indeling (plan 2026-10-13). Kop, groot getal, kernregels, tabs, rijen en zoekveld: elke pagina bouwt hiermee,
   zodat de indeling op één plek bijgehouden wordt. ===== #}

{# Kop van een pagina: avatar naar Account, titel die het Meer-blad opent (pagina wisselen), rechts de vaste knoppen uit base.html. #}
{% macro page_header(user, title) %}
<div class="ph">
  <a class="ph-avatar" href="/account" aria-label="Mijn account">{{ (user.username or "?")[0]|upper }}</a>
  <button type="button" class="ph-title" data-more-toggle aria-controls="more-sheet" aria-expanded="false">
    <span>{{ title }}</span>
    <svg viewBox="0 0 24 24" width="18" height="18" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6,9 12,15 18,9"/></svg>
  </button>
  {{ caller() if caller }}
</div>
{% endmacro %}

{# Eén groot meetgetal. `spark` is kant-en-klare SVG (track_record.sparkline_svg) of leeg; `spark_coin` tekent de live koerslijn via
   spark.js. `delta` is tekst met `tone` pos/neg; `delta_coin` laat spark.js de 24u-verandering invullen. `attrs` komt op het getal,
   zodat live.js of coin.js het kan bijwerken (bv. {"id": "coin-price", "data-symbol": "BTC"}). #}
{% macro headline(label, value, unit="", spark=none, spark_coin=none, delta=none, tone="", delta_coin=none, href=none, attrs={}) %}
<section class="hl">
  <div class="hl-text">
    <p class="hl-label">{% if href %}<a href="{{ href }}">{{ label }}</a>{% else %}{{ label }}{% endif %}</p>
    <p class="hl-value"><span class="hl-num"{{ attrs|xmlattr }}>{{ value }}</span>{% if unit %}<span class="hl-unit">{{ unit }}</span>{% endif %}</p>
    {% if delta_coin %}<p class="hl-delta" data-spark-chg="{{ delta_coin }}"></p>
    {% elif delta %}<p class="hl-delta {{ tone }}">{{ delta }}</p>{% endif %}
  </div>
  {% if spark %}<div class="hl-spark">{{ spark }}</div>
  {% elif spark_coin %}<div class="hl-spark"><svg class="radar-spark" data-spark-coin="{{ spark_coin }}" viewBox="0 0 120 28" preserveAspectRatio="none" role="img" aria-label="Koers {{ spark_coin }}, laatste 24 uur"><path d=""/></svg></div>{% endif %}
</section>
{% endmacro %}

{# Drie (of meer) kernregels. Elke regel: {"label", "value", "unit"?, "explain"?, "tone"?, "href"?, "html"?}. `html` is Markup die naast
   de waarde komt (bv. de dagbudgetring). Een uitleg opent met het native popover-attribuut: geen JS nodig, en in een browser zonder
   popover blijft het label gewoon tekst met een stippellijn. #}
{% macro keylines(rows, id_prefix="kl") %}
<dl class="kl">
  {% for r in rows %}
  <div class="kl-row">
    <dt>{% if r.explain %}<button type="button" class="kl-term" popovertarget="{{ id_prefix }}-{{ loop.index }}">{{ r.label }}</button>
        <span class="kl-pop" id="{{ id_prefix }}-{{ loop.index }}" popover>{{ r.explain }}</span>{% else %}{{ r.label }}{% endif %}</dt>
    <dd class="{{ r.tone or '' }}">{% if r.href %}<a href="{{ r.href }}">{% endif %}{{ r.html or "" }}<span class="kl-num">{{ r.value }}</span>{% if r.unit %}<span class="kl-unit">{{ r.unit }}</span>{% endif %}{% if r.href %}</a>{% endif %}</dd>
  </div>
  {% endfor %}
</dl>
{% endmacro %}

{# Tekst-tabs met streep. items: lijst van {"key", "label", "href", "count"?}. Een href die met # begint is een paneeltab (utabs.js
   toont alleen dat paneel); anders is het een gewone link. `menu` is een lijst {"label", "href"} achter de drie puntjes. #}
{% macro utabs(items, active, group="main", menu=none, menu_class="") %}
<div class="ut" data-utabs="{{ group }}">
  <div class="ut-list" role="tablist" aria-label="Onderdelen">
    {% for t in items %}
    <a class="ut-tab{% if t.key == active %} is-active{% endif %}" href="{{ t.href }}" role="tab" aria-selected="{{ 'true' if t.key == active else 'false' }}"
       {% if t.href.startswith('#') %}aria-controls="{{ t.href[1:] }}"{% endif %}>{{ t.label }}{% if t.count %} <i class="ut-count">{{ t.count }}</i>{% endif %}</a>
    {% endfor %}
  </div>
  {% if menu %}
  <details class="ut-more">
    <summary aria-label="Meer opties"><svg viewBox="0 0 24 24" width="22" height="22" fill="currentColor" aria-hidden="true"><circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/></svg></summary>
    <nav class="ut-menu {{ menu_class }}">{% for m in menu %}<a href="{{ m.href }}">{{ m.label }}</a>{% endfor %}</nav>
  </details>
  {% endif %}
</div>
{% endmacro %}

{# Kolomkoppen boven een lijst rijen, zoals "Markten / Prijs / 24 uur" in de referentie. #}
{% macro row_head(left, mid="", right="") %}
<div class="mrow-head" aria-hidden="true"><span>{{ left }}</span><span>{{ mid }}</span><span>{{ right }}</span></div>
{% endmacro %}

{# Eén rij per coin of soort. `el` is a, div of summary (in een <details> voor een uitklapbare rij). `price_coin` laat live.js de koers
   bijwerken; `chg_coin` laat spark.js de 24u-verandering invullen. Zonder die twee tonen `price_text`/`right_text` vaste tekst. #}
{% macro market_row(icon, title, chip=none, chip_tone="", subtitle="", price_coin=none, price_text="", chg_coin=none, right_text=none, right_tone="", href=none, el="a", attrs={}) %}
<{{ el }} class="mrow"{% if el == "a" and href %} href="{{ href }}"{% endif %}{{ attrs|xmlattr }}>
  <span class="mrow-icon" aria-hidden="true">{{ icon[:4] }}</span>
  <span class="mrow-main">
    <span class="mrow-title">{{ title }}{% if chip %} <i class="mrow-chip {{ chip_tone }}">{{ chip }}</i>{% endif %}</span>
    {% if subtitle %}<span class="mrow-sub">{{ subtitle }}</span>{% endif %}
  </span>
  <span class="mrow-price"{% if price_coin %} data-vd-price="{{ price_coin }}"{% endif %}>{{ price_text }}</span>
  {% if chg_coin %}<span class="mrow-chg" data-spark-chg="{{ chg_coin }}" data-spark-short></span>
  {% else %}<span class="mrow-chg {{ right_tone }}">{{ right_text or "" }}</span>{% endif %}
</{{ el }}>
{% endmacro %}

{# Zwevend zoekveld boven de tabbalk. Een knop, geen echt veld: een tik opent de bestaande command palette (base.html), zodat er
   één zoekfunctie blijft. #}
{% macro float_search() %}
<button type="button" class="fsearch" id="fsearch" aria-haspopup="dialog" aria-controls="cmdk">
  <svg viewBox="0 0 24 24" width="20" height="20" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><line x1="21" y1="21" x2="16.65" y2="16.65"/></svg>
  <span>Zoek een coin of pagina</span>
</button>
{% endmacro %}
```

Let op bij `market_row`: de lege `data-vd-price` krijgt de bestaande glimmende plaatshouder (`[data-vd-price]:empty` in `style.css`). Dat is bestaand gedrag en blijft. `data-spark-short` vraagt spark.js om "+0,9%" zonder " 24u" (de kolomkop zegt al "24 uur").

### 1.4 CSS (volledig, nieuw blok onderaan `style.css`)

```css
/* ===== Indeling (plan 2026-10-13) =====
   Overgenomen van een referentie-app: veel lucht, grote cijfers, dunne lijnen en geen zware kaarten. Kleuren blijven de tokens hierboven. */

/* Gloed bovenaan: statisch, één laag achter alles. Een vaste laag en geen body-achtergrond, omdat html[data-session] de body-kleur zet. */
.top-glow {
  position: absolute; top: 0; left: 0; right: 0; height: var(--glow-top-height); z-index: 0; pointer-events: none;
  background:
    radial-gradient(120% 100% at 50% 0%, var(--glow-top) 0%, transparent 70%),
    linear-gradient(to bottom, var(--glow-top) 0%, transparent 100%);
}
/* Niet z-index -1: html en body hebben allebei een eigen achtergrond, en de body-achtergrond zou een negatieve laag afdekken. */
main { position: relative; z-index: 1; }

/* Kop */
.ph { display: flex; align-items: center; gap: var(--space-6); min-height: var(--avatar); margin: 0 0 var(--space-9); }
.ph-avatar {
  flex: 0 0 var(--avatar); width: var(--avatar); height: var(--avatar); border-radius: 50%;
  display: grid; place-items: center; background: var(--panel); border: var(--sep); box-shadow: var(--shadow-sm);
  color: var(--text); font-family: var(--display); font-size: 20px; font-weight: 700; text-decoration: none;
}
.ph-title {
  display: inline-flex; align-items: center; gap: var(--space-3); min-height: 44px; padding: 0; background: none; border: 0; cursor: pointer;
  color: var(--text); font: 700 var(--text-xl) / 1.2 var(--sans); letter-spacing: -0.01em;
}
.ph-title svg { color: var(--muted); }
.ph-title[aria-expanded="true"] svg { transform: rotate(180deg); }
.ph-right { margin-left: auto; display: flex; align-items: center; gap: var(--space-5); }

/* Groot getal */
.hl { display: flex; align-items: flex-end; justify-content: space-between; gap: var(--space-7); margin: 0 0 var(--space-10); }
.hl-text { min-width: 0; }
.hl-label { margin: 0 0 var(--space-3); color: var(--text-dim); font-size: var(--text-md); }
.hl-label a { color: inherit; text-decoration: none; }
.hl-value { margin: 0; display: flex; align-items: baseline; gap: var(--space-3); white-space: nowrap; }
.hl-num { font-family: var(--mono); font-size: var(--num-hero); font-weight: 600; line-height: 1.05; letter-spacing: -0.02em; color: var(--text); font-variant-numeric: tabular-nums; }
.hl-unit { font-family: var(--mono); font-size: var(--num-hero-unit); font-weight: 500; color: var(--muted); }
.hl-delta { margin: var(--space-3) 0 0; font-family: var(--mono); font-size: var(--text-md); font-weight: 600; color: var(--muted); }
.hl-delta.pos, .hl-delta.is-up { color: var(--green); }
.hl-delta.neg, .hl-delta.is-down { color: var(--red); }
.hl-spark { flex: 0 1 132px; min-width: 88px; height: 44px; }
.hl-spark svg { display: block; width: 100%; height: 100%; }

/* Kernregels */
.kl { margin: 0 0 var(--space-9); padding-bottom: var(--space-6); border-bottom: var(--sep); }
.kl-row { display: flex; align-items: center; justify-content: space-between; gap: var(--space-6); min-height: var(--kl-row-h); }
.kl dt { color: var(--text-dim); font-size: var(--text-lg); }
.kl dd { margin: 0; display: inline-flex; align-items: center; gap: var(--space-3); font-size: var(--text-lg); text-align: right; }
.kl dd a { color: inherit; text-decoration: none; display: inline-flex; align-items: center; gap: var(--space-3); }
.kl-num { font-family: var(--mono); font-weight: 700; color: var(--text); font-variant-numeric: tabular-nums; }
.kl dd.pos .kl-num { color: var(--green); }
.kl dd.neg .kl-num { color: var(--red); }
.kl-unit { font-family: var(--mono); font-size: var(--text-md); font-weight: 600; color: var(--muted); }
.kl-term {
  padding: 0; background: none; border: 0; cursor: help; color: inherit; font: inherit; text-align: left;
  text-decoration: underline dashed var(--muted); text-decoration-thickness: 1px; text-underline-offset: 6px;
}
.kl-pop {
  max-width: min(320px, calc(100vw - 2 * var(--gutter))); margin: auto; padding: var(--space-7); border: 1px solid var(--border-strong);
  border-radius: 14px; background: var(--panel); color: var(--text); font-size: var(--text-md); line-height: 1.5; box-shadow: var(--shadow-md);
}
.kl-pop::backdrop { background: rgba(0, 0, 0, 0.4); }

/* Tekst-tabs */
.ut { display: flex; align-items: center; gap: var(--space-6); margin: 0 0 var(--space-7); }
.ut-list { display: flex; gap: var(--space-8); overflow-x: auto; scrollbar-width: none; min-width: 0; flex: 1; }
.ut-list::-webkit-scrollbar { display: none; }
.ut-tab {
  flex: 0 0 auto; padding: var(--space-4) 0 var(--space-5); border-bottom: 2px solid transparent; color: var(--muted);
  font-size: var(--text-lg); font-weight: 600; text-decoration: none; white-space: nowrap;
}
.ut-tab.is-active, .ut-tab[aria-selected="true"] { color: var(--text); border-bottom-color: var(--text); }
.ut-tab:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
.ut-count { font-style: normal; font-family: var(--mono); font-size: var(--text-sm); color: var(--accent); }
.ut-more { position: relative; flex: 0 0 auto; }
.ut-more summary { list-style: none; display: grid; place-items: center; width: 44px; height: 44px; color: var(--text-dim); cursor: pointer; }
.ut-more summary::-webkit-details-marker { display: none; }
.ut-menu {
  position: absolute; right: 0; top: 100%; z-index: 40; min-width: 200px; padding: var(--space-3); display: flex; flex-direction: column;
  background: var(--panel); border: 1px solid var(--border-strong); border-radius: 14px; box-shadow: var(--shadow-md);
}
.ut-menu a { padding: var(--space-5) var(--space-6); border-radius: 10px; color: var(--text); text-decoration: none; }
.ut-menu a:active, .ut-menu a:hover { background: var(--panel-hover); }
/* utabs.js zet .is-js op de groep: pas dan verdwijnen de niet-actieve panelen. Zonder JS staat alles onder elkaar. */
.ut-panels.is-js > [data-utab-panel]:not(.is-shown) { display: none; }

/* Rijen */
.mrow-head, .mrow { display: grid; grid-template-columns: var(--icon-row) minmax(0, 1fr) auto 72px; align-items: center; column-gap: var(--space-6); }
.mrow-head { padding: 0 0 var(--space-4); color: var(--muted); font-size: var(--text-md); }
.mrow-head span:first-child { grid-column: 1 / 3; }
.mrow-head span:nth-child(2), .mrow-head span:nth-child(3) { text-align: right; }
.mrow { min-height: var(--row-h); padding: var(--space-4) 0; color: var(--text); text-decoration: none; list-style: none; cursor: pointer; }
.mrow::-webkit-details-marker { display: none; }
.mrow-icon {
  width: var(--icon-row); height: var(--icon-row); border-radius: 50%; display: grid; place-items: center;
  background: var(--panel-hover); border: var(--sep); color: var(--text-dim); font-family: var(--mono); font-size: 10px; font-weight: 700; letter-spacing: -0.02em;
}
.mrow-main { display: flex; flex-direction: column; gap: 2px; min-width: 0; }
.mrow-title { font-family: var(--mono); font-size: var(--num-row); font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mrow-chip {
  display: inline-block; margin-left: var(--space-3); padding: 1px 7px; border-radius: 6px; background: var(--panel-hover);
  color: var(--text-dim); font-style: normal; font-family: var(--sans); font-size: var(--text-xs); font-weight: 500; vertical-align: 2px;
}
.mrow-chip.pos { color: var(--green); background: var(--green-bg); }
.mrow-chip.neg { color: var(--red); background: var(--red-bg); }
.mrow-sub { color: var(--muted); font-size: var(--text-sm); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.mrow-price, .mrow-chg { font-family: var(--mono); font-size: var(--num-row); font-weight: 600; text-align: right; font-variant-numeric: tabular-nums; white-space: nowrap; }
.mrow-chg { color: var(--muted); }
.mrow-chg.pos, .mrow-chg.is-up { color: var(--green); }
.mrow-chg.neg, .mrow-chg.is-down { color: var(--red); }
details.mrow-wrap { border-bottom: var(--sep); }
details.mrow-wrap:last-child { border-bottom: 0; }
details.mrow-wrap > .mrow-body { padding: 0 0 var(--space-7) calc(var(--icon-row) + var(--space-6)); }
@media (max-width: 420px) { details.mrow-wrap > .mrow-body { padding-left: 0; } }

/* Platte sectie in plaats van een kaart: alleen een dunne lijn erboven. */
.flat { margin: 0 0 var(--space-10); padding: var(--space-9) 0 0; border-top: var(--sep); background: none; }
.flat:first-of-type { border-top: 0; padding-top: 0; }
.flat > h3 { margin: 0 0 var(--space-6); font-size: var(--text-lg); font-weight: 700; color: var(--text); text-transform: none; letter-spacing: -0.01em; }

/* Dok: zoekveld boven de tabbalk, samen weg bij omlaag scrollen. */
.dock { display: none; }
@media (max-width: 760px) {
  .dock {
    display: flex; flex-direction: column; gap: var(--space-5); position: fixed; left: 12px; right: 12px;
    bottom: calc(10px + env(safe-area-inset-bottom)); z-index: 500; transition: transform 0.22s ease-out;
  }
  .dock.is-hidden { transform: translateY(calc(100% + 24px + env(safe-area-inset-bottom))); }
  .dock .tabbar { position: static; left: auto; right: auto; bottom: auto; transition: none; }
  .dock .tabbar.is-hidden { transform: none; }
  main { padding: var(--space-6) var(--gutter) calc(150px + env(safe-area-inset-bottom)); }
  .tab.is-active { box-shadow: var(--glow-tab); }
  .fsearch {
    display: flex; align-items: center; gap: var(--space-6); width: 100%; min-height: 52px; padding: 0 var(--space-8);
    background: rgba(19, 26, 27, 0.86); -webkit-backdrop-filter: blur(16px); backdrop-filter: blur(16px);
    border: 1px solid var(--border-strong); border-radius: var(--radius-pill); box-shadow: var(--shadow-md);
    color: var(--text-dim); font: 400 var(--text-lg) var(--sans); text-align: left; cursor: pointer;
  }
  .fsearch:active { background: var(--panel-hover); }
  .fsearch:focus-visible { outline: 2px solid var(--accent); outline-offset: 2px; }
  /* Kop op de telefoon: de merkrij wijkt voor .ph. Pauze, koersstip en systeemstip blijven in .topbar staan (hun ID's moeten uniek
     blijven voor pause.js, stale.js en het statusscript), maar de balk wordt een transparante rechterhoek over .ph heen. */
  .topbar { position: absolute; top: max(12px, env(safe-area-inset-top)); right: var(--gutter); left: auto; padding: 0; background: none; border: 0; z-index: 20; }
  .topbar .brand, .topbar-watermark-clip, .logout-form, .shortcuts-hint, .topbar-ticker, .last-signal-pill, .live-pill { display: none; }
  .topbar-top { min-height: var(--avatar); }
  .ph-title { max-width: calc(100% - 170px); }
  .ph-title span { overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
  .cmdk-overlay { align-items: flex-start; padding: max(var(--space-8), env(safe-area-inset-top)) var(--gutter) 0; }
  .cmdk-panel { width: 100%; border-radius: 18px; }
}
@media (min-width: 761px) { .fsearch, .ph-title svg { display: none; } .ph-title { cursor: default; } }
@media (prefers-reduced-motion: reduce) { .dock, .ph-title svg { transition: none; } }
```

### 1.5 Gloed: contrastsom

`--muted` (#7d8c8a) heeft relatieve luminantie 0,249. Voor 4,5:1 moet de achtergrond onder 0,0164 blijven. De ergste plek is de bovenrand, waar radiaal en lineair optellen: effectief ongeveer 15% teal over `--bg`. Groen kanaal: 14 + 0,15 x 215 = 46 → lineair 0,027, luminantie ongeveer 0,021 inclusief rood en blauw. Dat is te veel, maar alleen in de bovenste 20px waar geen muted tekst staat (statusbalk en safe area). Op de hoogte van het label onder het grote getal (ongeveer 110px) is de lineaire laag op 66% en de radiale op ongeveer 45%, samen ongeveer 9% teal: groen 33 → luminantie ongeveer 0,0135, contrast 0,299 / 0,0635 = 4,7:1. Dat haalt AA, krap. De bestaande `.glow-accent` (opacity 0,10, wazig, linksboven) ligt er nog onder; daarom eist Taak 2 een meting met pixels in de schermafbeelding in plaats van te vertrouwen op deze som. Zakt de meting onder 4,5:1, verlaag dan `--glow-top` naar 0,06 (één token).

### 1.6 Beweging

Nieuw is alleen: het dok schuift weg (bestond al voor de tabbalk, verhuist naar `.dock`) en de chevron draait bij openen van het Meer-blad (directe reactie op een tik, geen decoratie). Beide staan uit onder `prefers-reduced-motion`. De gloed is statisch. De tel-op-animatie in `base.html` (`.card .big`) raakt `.hl-num` niet en blijft daar ook buiten.

---

## Deel 2. Per pagina

Alle getallen hieronder bestaan al in de route of komen uit een bestaande functie. Nieuw rekenwerk: geen.

### Vandaag (`/vandaag`, `vandaag.html`, route `_vandaag_context` in `web/main.py`)

- Kop: `page_header(user, "Vandaag")`, rechts de sessienaam (`data-session-name`) klein.
- Groot getal: resultaat laatste 7 dagen in R na kosten. Bron: `track_record.week_summary(rows, config.TRACK_RECORD_COST_PCT)` met `rows = report_rows(user)` (staat al in `_vandaag_context`), veld `net_r`. Eenheid "R". Lijntje: `track_record.sparkline_svg(week["cumulative"], width=132, height=44)`. Verandering: R van vandaag, `week["days"][-1][1]`, als "+0,40R vandaag", toon pos/neg/leeg bij 0. Label "Resultaat laatste 7 dagen, na kosten", link naar `/week`. Zelfde getal als Kwartaalcijfers, dus geen tweede waarheid. Gemeten, geen schatting. Bij `week.resolved == 0` toont de verandering "Nog niets afgerond".
- Kernregels: (1) "Kansen open" = `plans_ready`, uitleg = de `open_parts` als zin (bestaande tekst, inclusief "Er staat niets open..." als het nul is); (2) "Het eerst aan de beurt" = `nearest.name` plus `nearest.dist`, link `nearest.url`, of "-"; (3) "Meldingen in 24 uur" = `budget.label` met de bestaande ring-SVG als `html` (de ring met `stroke-dashoffset` blijft, test eist het). Stemming (`mood_bar`) en BTC-koers verhuizen naar de tab Markt.
- Tabs (paneel): Kansen (getekende plannen plus scenario's die wachten), Markt (BTC-koers, stemming, liquidaties, nieuws), Agenda, Score. Menu "...": Mijn week, Beste setups, Instellingen, in een `nav` met klasse `quick-actions` (test eist die klasse).
- Rijen: "Markt-script per coin" wordt een lijst `details.mrow-wrap` met `market_row(el="summary")`: icoon = coin, chip = bias (long pos, short neg, neutraal grijs), ondertitel = aantal scenario's of "Geen scenario", prijs live via `price_coin`, 24u via `chg_coin`. Het bestaande scenario-blok (stappen, kopieerchips, bellen, deelknop, grafiek) staat ongewijzigd in `.mrow-body`. Een coin met minstens één wachtend scenario staat standaard open.
- Blijft: `vd-timeline`, alle `data-vd-*`-hooks, `vandaag.js`, `levelchart.js`.
- Verdwijnt: `vd-board` als groot vlak (de inhoud gaat naar het grote getal en de kernregels), losse `quick-actions`-tegels (worden het menu).

### Radar (`/smc`, `smc.html`, route `smc_page`)

- Kop "Radar". Het woord "SMC-radar" blijft in de `<title>` (test).
- Groot getal: aantal setups dat wacht, `len(setup_cards)`, eenheid "wachten". Geen lijntje (een telling heeft geen reeks). Verandering: "`len(signal_cards)` open trades", toon leeg.
- Kernregels: "Open trades" `len(signal_cards)`; "Doel gehaald zonder vulling" `len(moot_cards)`; "SMC per trade, na kosten" = `proof("smc")` label en tekst (bestaande global), uitleg "Gemeten op afgeronde SMC-trades. Bewijs toont de details."
- Tabs (paneel): Wachten, Open, Afgerond.
- Rijen: elke radarkaart krijgt als kop een `market_row(el="div")` in plaats van `.radar-head`: icoon en titel coin, chip richting, ondertitel `state_label` (met `data-radar="state"` behouden op een eigen element eronder, zie Taak 5), rechts live koers en 24u (`data-spark-chg`). De rest van de kaart (afstandsbalk, grafiek, chips, stappen, `r-progress`, feiten) blijft eronder, zonder kaartrand (`.radar-card` wordt plat met `--sep` ertussen). Niet inklappen: dit is de kern van de pagina.
- Blijft: `data-radar-key`, `data-radar=*`, `radar.js`, `spark.js`, de `approach`-aria-tekst.

### Setups (`/structuur`, `structuur.html`)

- Kop "Setups". Groot getal: `len(structure_cards)`, eenheid "klaar". Verandering: `engine-status`-zin "Laatste controle N min geleden" als neutrale tekst (de volledige `engine-status`-alinea blijft eronder staan, test eist de tekst).
- Kernregels: "Gezien, 24 uur" `counts.total`; "Beoordeeld" `counts.goedgekeurd + counts.afgekeurd`; "Zonder plan" `counts.geen_plan`.
- Tabs (paneel): Klaarstaand, Trend, Eerder. De filterchips (Alles, Alleen sterk en redelijk, Long, Short) blijven chips onder de tab Klaarstaand.
- Rijen: "Trend" en "Eerder" (`setup-history-row`) worden `market_row(el="a" of "div")`: chip richting, ondertitel instap/stop/doel of `state_label`, rechts `grade_word` of uitkomst. Setupkaarten (`setup_card`) blijven kaarten: daar zitten grafiek, afstandsring en stappen.

### Bewijs (`/bewijs`, `bewijs.html`)

- Kop "Bewijs". Groot getal: de entry met `source == "alles"`, veld `avg_net`, eenheid "R per trade". Lijntje: diens `spark` (bestaande `sparkline_svg`). Verandering: `recent_avg_net` als "+0,12R laatste 30 dagen" (`RECENT_DAYS`). Label "Alle soorten, na kosten".
- Kernregels: "Afgeronde trades" `resolved`; "Winrate" `winrate` met uitleg "Alleen doel en stop tellen. Open en vervallen staan ernaast."; "Open of vervallen" `open_or_expired`, uitleg "Tellen niet mee in winrate en R." Zo staat open/vervallen naast de winrate, niet weg.
- Tabs (paneel): Per soort, Regels, Curves, Uurkaart. "Zo lees je dit" staat onder Per soort.
- Rijen: per soort een `details.mrow-wrap` met `market_row(el="summary")`: icoon = eerste letters van het label, titel `e.label`, chip `status_labels[e.status]`, ondertitel "`resolved` afgerond, winrate", rechts `avg_net` als R (pos/neg). De volledige bestaande `proof-card`-inhoud (r_ruler, spark, feiten, score_split, footnote met open/vervallen) staat in `.mrow-body`. De "alles"-entry staat niet nog eens in de lijst (die is het grote getal; zijn feiten zijn de kernregels; zijn footnote komt onder de kernregels).
- Link "Jouw week als plaatje" gaat naar het "..."-menu.

### Journaal (`/signalen`) en Meldingen (`/meldingen`)

- Signalen: kop "Journaal", groot getal `entries|length` met eenheid "open" of "signalen" (bij `showing_all`). Linktabs Open (`/signalen`) en Alle (`/signalen?alles=1`) vervangen `view-toggle`. "alles niet interessant" in het "..."-menu als formulierknop (blijft POST met confirm, dus geen gewone link: render het formulier in `.ut-menu`). `signal_card` blijft, `.card` om de lijst wordt `.flat`.
- Meldingen: kop "Meldingen", groot getal `unread_count`, eenheid "ongelezen". "alles gelezen" in het menu (formulier). `nf-item` krijgt de rij-indeling via CSS (`.nf-link` als grid zoals `.mrow`, `nf-chip` als rond icoon); markup en `mark-read-link`-script blijven.

### Coin (`/coins/{symbol}`, `coin.html`)

- Kop: titel = symbool. Groot getal: de live koers, `headline(..., attrs={"id": "coin-price", "data-symbol": symbol})`, eenheid `live_quote|upper` (USDT), `spark_coin=symbol`, `delta_coin=symbol`. coin.js blijft `#coin-price` bijwerken. spark.js laden.
- Kernregels: "Signalen deze week" `recent_activity.count`; "Hoog vertrouwen" `recent_activity.hoog`; "Notitie" `coin_note` of "-". Muted-pil blijft eronder.
- Rest van de pagina blijft, `.card` om overzichten wordt `.flat`; open trades en formulieren houden hun kaart.

### Account, CEO, Week, Kans, Keten, Handleiding

- Account: kop "Account". Groot getal `taken_entries|length` "open posities"; kernregels "Nieuwe kansen" `pending_entries|length`, "Winrate" uit `winrate` (bestaand veld, uitleg "Eigen trades, oefentrades niet meegeteld"), "Drempel" `user.confirm_threshold_pct` %. `summary-strip` verdwijnt (zit nu in kop en regels). Uitloggen komt als laatste regel in het Meer-blad (de topbar is op de telefoon weg). Formulieren onveranderd.
- CEO: kop "De CEO". `ceo-stats` wordt `keylines` (dezelfde labels en waarden, ook de grappige). Hero, jacht en geld blijven, want dat is de pagina.
- Week: kop "Kwartaalcijfers". Groot getal `week.net_r` "R na kosten" met de bestaande `spark` (houdt `data-share-chart`). Bereikchips 1W/2W/1M/3M worden linktabs. `kans-facts` wordt `keylines`.
- Kans: kop met coin en richting, `kans-facts` wordt `keylines`. Keten en Handleiding: alleen de kop.

---

## Deel 3. Taken

**Volgorde en gedeelde bestanden.** Taak 1 tot 3 zijn het fundament en moeten eerst. Daarna paginataken. Bestanden die meerdere taken raken (dus taken na elkaar, niet parallel):

| Bestand | Taken |
|---|---|
| `web/static/style.css` | 1, 2, 4, 5, 6, 7, 8, 9, 10 |
| `web/templates/_macros.html` | 1 (5 en 7 alleen aanroepen) |
| `web/templates/base.html` | 2, 10 (alleen het Meer-blad: uitloggen) |
| `web/main.py` | 4, 5, 7, 9, 10 |
| `web/static/spark.js` | 3 |
| `tests/test_web_layout.py` (nieuw) | 1 tot en met 10, elke taak voegt een testklasse toe |
| `scripts/layout_check.py` (nieuw) | 2, aangevuld in 4 tot en met 11 |

Omdat `style.css` overal terugkomt: geen parallelle uitvoering van paginataken. Wel kan één reviewer per taak goed- of afkeuren.

**Playwright-controle (geldt voor elke taak met UI).** `scripts/layout_check.py` (Taak 2) start niets zelf; de uitvoerder start eerst:

```bash
DATABASE_PATH=/tmp/layout.db python3 scripts/create_user.py   # eenmalig, gebruiker "tester"
DATABASE_PATH=/tmp/layout.db uvicorn web.main:app --port 8765 &
python3 scripts/layout_check.py --base http://127.0.0.1:8765 --user tester --pages /vandaag /smc --out /tmp/layout-shots
```

Het script logt in, opent elke pagina op 390x844 (en op 1280x800 met `--desktop`), maakt een schermafbeelding per pagina, controleert dat `document.documentElement.scrollWidth <= 390`, dat `#push-pause`, `#price-dot`, `#system-status`, `#fsearch`, `.tabbar`, `#more-sheet` bestaan, en meet het contrast van het eerste `.hl-label` tegen de pixel eronder (PIL, al geinstalleerd). De uitvoerder BEKIJKT elke schermafbeelding met de Read-tool en schrijft in de taakafronding wat hij zag. Een schermafbeelding maken zonder hem te bekijken telt niet.

---

### Task 1: Tokens, gedeelde CSS, macro's en utabs.js

**Files:**
- Modify: `web/static/style.css` (tokens in `:root` na regel 59; nieuw blok onderaan, volledige CSS uit 1.4)
- Modify: `web/templates/_macros.html` (onderaan, volledige macro's uit 1.3)
- Create: `web/static/utabs.js`
- Create: `tests/js/utabs_harness.js`
- Create: `tests/test_web_layout.py`
- Modify: `tests/test_static_js.py` (testklasse voor utabs)

**Interfaces:**
- Produces: macro's `page_header(user, title)` (met optionele `caller` voor de rechterkant), `headline(label, value, unit="", spark=none, spark_coin=none, delta=none, tone="", delta_coin=none, href=none, attrs={})`, `keylines(rows, id_prefix="kl")`, `utabs(items, active, group="main", menu=none, menu_class="")`, `row_head(left, mid="", right="")`, `market_row(icon, title, chip=none, chip_tone="", subtitle="", price_coin=none, price_text="", chg_coin=none, right_text=none, right_tone="", href=none, el="a", attrs={})`, `float_search()`. CSS-klassen `.ph .ph-avatar .ph-title .ph-right .hl .hl-num .hl-unit .hl-delta .hl-spark .kl .kl-row .kl-term .kl-pop .ut .ut-tab .ut-more .ut-menu .ut-panels [data-utab-panel] .mrow-head .mrow .mrow-icon .mrow-chip .mrow-sub .mrow-price .mrow-chg .mrow-wrap .mrow-body .flat .dock .fsearch .top-glow`. Paneelconventie: `<div class="ut-panels" data-utabs-panels="main">` met kinderen `<section data-utab-panel id="tab-...">`.

- [ ] **Step 1: Failing test voor de macro's** in `tests/test_web_layout.py`:

```python
import unittest
from markupsafe import Markup

from web import main


def render(src: str, **ctx) -> str:
    env = main.templates.env
    return env.from_string('{% import "_macros.html" as m %}' + src).render(**ctx)


class LayoutMacroTests(unittest.TestCase):
    def test_headline_toont_getal_eenheid_en_toon(self):
        html = render('{{ m.headline("Resultaat", "+1,20", "R", delta="+0,40R vandaag", tone="pos") }}')
        self.assertIn('class="hl-num"', html)
        self.assertIn('>+1,20</span><span class="hl-unit">R</span>', html)
        self.assertIn('class="hl-delta pos"', html)

    def test_headline_zet_attributen_op_het_getal(self):
        html = render('{{ m.headline("Koers", "1", attrs={"id": "coin-price", "data-symbol": "BTC"}) }}')
        self.assertIn('id="coin-price"', html)
        self.assertIn('data-symbol="BTC"', html)

    def test_keylines_uitleg_via_popover(self):
        html = render('{{ m.keylines([{"label": "Winrate", "value": "52", "unit": "%", "explain": "Alleen doel en stop."}], "bw") }}')
        self.assertIn('popovertarget="bw-1"', html)
        self.assertIn('id="bw-1" popover', html)
        self.assertIn('class="kl-term"', html)

    def test_utabs_paneeltab_heeft_aria_controls(self):
        html = render('{{ m.utabs([{"key": "a", "label": "Kansen", "href": "#tab-a"}, {"key": "b", "label": "Markt", "href": "/x"}], "a") }}')
        self.assertIn('aria-controls="tab-a"', html)
        self.assertIn('class="ut-tab is-active"', html)
        self.assertEqual(html.count("aria-controls"), 1)

    def test_market_row_live_hooks(self):
        html = render('{{ m.market_row("BTC", "BTC", chip="long", chip_tone="pos", price_coin="BTC", chg_coin="BTC", el="summary") }}')
        self.assertTrue(html.strip().startswith('<summary class="mrow"'))
        self.assertIn('data-vd-price="BTC"', html)
        self.assertIn('data-spark-chg="BTC" data-spark-short', html)

    def test_geen_em_dash_in_nieuwe_macros(self):
        src = (main.BASE_DIR / "templates" / "_macros.html").read_text()
        new = src.split("===== Indeling", 1)[1]
        self.assertNotIn("—", new)
        self.assertNotIn("–", new)
```

- [ ] **Step 2: Run** `python3 -m unittest tests.test_web_layout -v`. Verwacht: FAIL (macro bestaat niet).
- [ ] **Step 3: Implementeer** tokens, CSS en macro's precies zoals in 1.2 tot en met 1.4. Schrijf `web/static/utabs.js`:

```js
// Tekst-tabs: toont alleen het paneel van de actieve tab. Zonder dit script staan alle panelen onder elkaar en springen de tabs
// als ankers, dus niets is ooit onbereikbaar. De gekozen tab staat in de hash, zodat terug-navigeren en een gedeelde link kloppen.
(function () {
  function init(group) {
    var name = group.getAttribute("data-utabs");
    var panels = document.querySelector('[data-utabs-panels="' + name + '"]');
    if (!panels) return;
    var tabs = Array.prototype.filter.call(group.querySelectorAll(".ut-tab"), function (t) { return t.getAttribute("href").charAt(0) === "#"; });
    if (!tabs.length) return;
    function show(id, push) {
      var found = false;
      tabs.forEach(function (t) {
        var on = t.getAttribute("href") === "#" + id;
        found = found || on;
        t.classList.toggle("is-active", on);
        t.setAttribute("aria-selected", on ? "true" : "false");
      });
      if (!found) return false;
      panels.querySelectorAll("[data-utab-panel]").forEach(function (p) { p.classList.toggle("is-shown", p.id === id); });
      if (push) history.replaceState(null, "", "#" + id);
      // levelchart.js tekent pas als een grafiek in beeld komt; een net getoond paneel moet dat zelf kunnen melden.
      window.dispatchEvent(new Event("resize"));
      return true;
    }
    panels.classList.add("is-js");
    var start = location.hash.slice(1);
    if (!start || !show(start, false)) show(tabs[0].getAttribute("href").slice(1), false);
    group.addEventListener("click", function (e) {
      var t = e.target.closest && e.target.closest(".ut-tab");
      if (!t || tabs.indexOf(t) === -1) return;
      e.preventDefault();
      show(t.getAttribute("href").slice(1), true);
    });
  }
  window.hpUtabsInit = init;
  document.querySelectorAll("[data-utabs]").forEach(init);
})();
```

  Laad het in `base.html` naast `tabbar.js` (`<script src="{{ asset('utabs.js') }}" defer></script>`); dat is de enige `base.html`-regel in deze taak.
- [ ] **Step 4: Node-harnas** `tests/js/utabs_harness.js`: een minimale nep-DOM in de stijl van `stale_harness.js` (lees die eerst) met twee tabs en twee panelen; laad het script met `vm`, simuleer een klik op tab 2, print JSON `{"shown": "<id>", "selected": ["false","true"], "hash": "#tab-b"}`. Testklasse in `tests/test_static_js.py`:

```python
@unittest.skipUnless(shutil.which("node"), "node ontbreekt")
class UtabsTest(unittest.TestCase):
    def test_klik_toont_alleen_het_gekozen_paneel(self):
        out = run_node("utabs_harness.js", "utabs.js")
        self.assertEqual(out, {"shown": "tab-b", "selected": ["false", "true"], "hash": "#tab-b"})
```

- [ ] **Step 5: Run** `python3 -m unittest discover -s tests -t . -v` (met `SKIP_SLOW_TESTS=1`). Verwacht: alles PASS.
- [ ] **Step 6: Commit** `git add web/static/style.css web/templates/_macros.html web/static/utabs.js web/templates/base.html tests/test_web_layout.py tests/test_static_js.py tests/js/utabs_harness.js && git commit -m "Indeling: tokens, gedeelde macro's en tekst-tabs"`

### Task 2: Basisschil: kop, dok met zoekveld, gloed, controle-script

**Files:**
- Modify: `web/templates/base.html` (body-begin: `.top-glow`; nieuwe kop in `main`; `.dock` rond `.tabbar`; command palette)
- Modify: `web/static/tabbar.js` (scroll-verbergen op `.dock`, Meer-blad ook via `[data-more-toggle]`)
- Modify: `web/static/smooth.js` (regel met `pullBlocked`: `.cmdk` wordt `.cmdk-overlay:not([hidden])`)
- Modify: `web/static/style.css` (alleen als de controle iets laat zien)
- Create: `scripts/layout_check.py`
- Test: `tests/test_web_layout.py` (klasse `BaseShellTests`)

**Interfaces:**
- Consumes: `page_header`, `float_search` uit Taak 1.
- Produces: Jinja-blok `{% block page_title %}` (standaard leeg: dan geen `.ph`, zodat een nog niet omgezette pagina gewoon werkt); `window.HP.openSearch()`; klasse `.dock` met `is-hidden`; `scripts/layout_check.py --base URL --user NAME --pages ... --out DIR [--desktop] [--reduced-motion]`.

- [ ] **Step 1: Failing tests** (`BaseShellTests`, opzet zoals `tests/test_web_vandaag.py` `setUp`): GET `/vandaag` bevat `class="top-glow"`, `id="fsearch"`, `class="dock"`, `class="tabbar"`, `id="push-pause"`, `id="price-dot"`, `id="system-status"`, `id="cmdk"`, `id="more-sheet"`, `id="push-banner"`, `>SMC</a>` en `>Bewijs</a>` (desktopnav blijft), en `data-more-toggle`. GET `/login` bevat geen `fsearch` en geen `top-glow` (uitgelogde pagina's vallen buiten deze ronde; zet de gloed binnen `{% if user %}`).
- [ ] **Step 2: Run**, verwacht FAIL.
- [ ] **Step 3: Implementeer.**
  - Direct na `<body>`: `{% if user %}<div class="top-glow" aria-hidden="true"></div>{% endif %}`.
  - In `<main>` voor `{% block content %}`: als `self.page_title()` niet leeg is, render `{% call macros.page_header(user, self.page_title()) %}<div class="ph-right"></div>{% endcall %}`. Importeer `_macros.html` bovenaan `base.html` als `macros`.
  - De knoppen `#push-pause`, `#price-dot` en `#system-status` (met popover) blijven één keer in de DOM: verplaats ze uit `.topbar-right` naar een eigen `<div class="ph-right-src">` direct na `<main>`-open, en laat een klein script ze bij laden in `.ph-right` hangen als die bestaat (op desktop blijft `.topbar` zichtbaar; zet daar de knoppen terug met dezelfde verplaatsing in omgekeerde richting). Eenvoudiger alternatief dat de voorkeur heeft als het past: laat de knoppen in `.topbar-right` staan en zet op telefoonbreedte niet de hele `.topbar` op `display:none`, maar alleen `.topbar .brand`, `.topbar-watermark-clip`, `.logout-form`, `.shortcuts-hint`, `#cmdk-hint` en `.topbar-ticker`, en maak `.topbar` op de telefoon transparant zonder rand en niet sticky, absoluut rechtsboven op de hoogte van `.ph` (`position: absolute; top: max(12px, env(safe-area-inset-top)); right: var(--gutter); background: none; border: 0; padding: 0;`). Kies dit alternatief: geen DOM-verhuizing, geen dubbele ID's, `pause.js` en `stale.js` blijven hun elementen vinden. De CSS daarvoor staat al in 1.4 (blok "Kop op de telefoon"); `.ph-right` blijft dan leeg en mag weg uit de aanroep. Let op: `#cmdk-hint` deelt de klasse `.shortcuts-hint` en verdwijnt dus mee op de telefoon; dat is gewild, het zwevende zoekveld vervangt hem.
  - Dok: `<div class="dock">{{ macros.float_search() }}<nav class="tabbar" ...>` (tabbalk ongewijzigd) `</div>`; het Meer-blad blijft erbuiten.
  - Command palette: maak `open` beschikbaar als `window.HP.openSearch = open;` en koppel `#fsearch` net als `#cmdk-hint`. Voeg aan `buildItems` toe: Vandaag, Setups, Radar, Bewijs, Meldingen, Kwartaalcijfers (alle met `hint: "pagina"`). Coins blijven uit `.coin-menu-list a` komen: die staat in de desktopnav en blijft in de DOM.
  - `tabbar.js`: het scroll-blok zoekt `document.querySelector(".dock") || document.querySelector(".tabbar")`. Het Meer-blok bindt `#more-toggle` en alle `[data-more-toggle]` en zet `aria-expanded` op allemaal.
  - `smooth.js`: `pullBlocked` blokkeert ook `.cmdk-overlay:not([hidden])` (de oude selector `.cmdk` bestond niet) en `.fsearch`.
- [ ] **Step 4: Schrijf `scripts/layout_check.py`** (stdlib plus Playwright plus PIL):

```python
"""Indelingscontrole: logt in, maakt per pagina een schermafbeelding op 390px (en desktop met --desktop), en faalt bij horizontale
scroll, ontbrekende vaste knoppen of te weinig contrast onder het label boven het grote getal. Bekijk de afbeeldingen daarna zelf."""
import argparse, sys
from pathlib import Path
from PIL import Image
from playwright.sync_api import sync_playwright

REQUIRED = ["#push-pause", "#price-dot", "#system-status", "#fsearch", ".tabbar", "#more-sheet"]


def lum(rgb):
    def ch(c):
        c = c / 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = (ch(x) for x in rgb[:3])
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", required=True); ap.add_argument("--user", required=True); ap.add_argument("--password", default="wachtwoord-123456")
    ap.add_argument("--pages", nargs="+", required=True); ap.add_argument("--out", required=True)
    ap.add_argument("--desktop", action="store_true"); ap.add_argument("--reduced-motion", action="store_true")
    a = ap.parse_args()
    out = Path(a.out); out.mkdir(parents=True, exist_ok=True)
    failures = []
    with sync_playwright() as p:
        browser = p.chromium.launch()
        size = {"width": 1280, "height": 800} if a.desktop else {"width": 390, "height": 844}
        ctx = browser.new_context(viewport=size, device_scale_factor=2, reduced_motion="reduce" if a.reduced_motion else "no-preference")
        page = ctx.new_page()
        page.goto(a.base + "/login")
        page.fill("input[name=username]", a.user); page.fill("input[name=password]", a.password)
        page.click("button[type=submit]"); page.wait_for_load_state("networkidle")
        for path in a.pages:
            page.goto(a.base + path); page.wait_for_load_state("networkidle"); page.wait_for_timeout(600)
            name = path.strip("/").replace("/", "_") or "root"
            shot = out / f"{name}-{'desktop' if a.desktop else '390'}.png"
            page.screenshot(path=str(shot), full_page=False)
            if not a.desktop and page.evaluate("document.documentElement.scrollWidth") > 390:
                failures.append(f"{path}: horizontale scroll")
            for sel in REQUIRED if not a.desktop else REQUIRED[:3]:
                if page.locator(sel).count() == 0:
                    failures.append(f"{path}: {sel} ontbreekt")
            label = page.locator(".hl-label").first
            if label.count():
                box = label.bounding_box()
                img = Image.open(shot).convert("RGB")
                bg = img.getpixel((int((box["x"] + box["width"] + 6) * 2), int((box["y"] + box["height"] / 2) * 2)))
                ratio = (0.249 + 0.05) / (lum(bg) + 0.05)        # 0,249 = luminantie van --muted, de lichtste tekst die erboven kan staan
                print(f"{path}: contrast muted op gloed {ratio:.2f}")
                if ratio < 4.5:
                    failures.append(f"{path}: contrast {ratio:.2f} onder 4,5")
            print(f"{path}: {shot}")
        browser.close()
    if failures:
        print("\n".join(failures)); sys.exit(1)


if __name__ == "__main__":
    main()
```

  Controleer de veldnamen in `login.html` voor je dit draait (pas `input[name=...]` aan als ze anders heten).
- [ ] **Step 5: Run** unittest-suite (PASS), dan de Playwright-controle op `/vandaag /smc /bewijs /account` op 390px, op 1280px en met `--reduced-motion`. Bekijk elke afbeelding met Read. Controleer zichtbaar: gloed bovenaan vloeit zacht over in `--bg` zonder harde rand, zoekveld zweeft boven de tabbalk, actieve tab heeft een zachte gloed, pauzeknop en systeemstip rechtsboven, geen overlap met de pushbanner. Scroll in de browser 400px omlaag en weer omhoog (`page.mouse.wheel`) en maak twee extra afbeeldingen: het dok moet weg en weer terug zijn. Tik op `#fsearch`: de palette opent, typ "eth", Enter landt op `/coins/ETH`.
- [ ] **Step 6: Commit** `git add web/templates/base.html web/static/tabbar.js web/static/smooth.js web/static/style.css scripts/layout_check.py tests/test_web_layout.py && git commit -m "Indeling: kop, gloed en zwevend zoekveld in de basis"`

### Task 3: spark.js vult 24u-verandering los van de minigrafiek

**Files:**
- Modify: `web/static/spark.js`
- Modify: `web/templates/base.html` (spark.js globaal laden met `defer`; uit `smc.html` halen)
- Create: `tests/js/spark_harness.js`
- Modify: `tests/test_static_js.py`

**Interfaces:**
- Consumes: `data-spark-chg` en `data-spark-short` uit `market_row`/`headline`.
- Produces: elk `[data-spark-chg]` krijgt `is-up`/`is-down` en tekst `change_text`, of zonder " 24u" als `data-spark-short` er staat. Coins worden verzameld uit zowel `[data-spark-coin]` als `[data-spark-chg]`.

- [ ] **Step 1: Failing harnas-test**: nep-DOM met één `[data-spark-chg="BTC"][data-spark-short]` en geen svg; nep-`fetch` geeft `{"BTC": {"path": "M0 0", "change_pct": -0.9, "change_text": "-0,9% 24u"}}`. Verwacht `{"text": "-0,9%", "down": true, "fetched": "BTC"}`.
- [ ] **Step 2: Run**, verwacht FAIL (het script stopt nu zonder svg).
- [ ] **Step 3: Implementeer**: verzamel coins uit beide selectors, stop alleen als beide leeg zijn; in `apply` zet op elk chg-element `classList.toggle("is-up", d.change_pct > 0)`, `toggle("is-down", d.change_pct < 0)` en tekst `el.hasAttribute("data-spark-short") ? d.change_text.replace(" 24u", "") : d.change_text`.
- [ ] **Step 4: Run** suite, PASS. Bestaande Radar-test met `spark.js` in de pagina blijft groen omdat base het nu laadt.
- [ ] **Step 5: Commit** `git commit -m "spark.js: 24u-verandering ook zonder minigrafiek, met kleur"`

### Task 4: Vandaag

**Files:**
- Modify: `web/main.py` (`_vandaag_context`: `week` toevoegen)
- Modify: `web/templates/vandaag.html`
- Modify: `web/static/style.css` (alleen kleine aanvullingen voor `.vd-*` in `.mrow-body`)
- Test: `tests/test_web_layout.py` (klasse `VandaagLayoutTests`), bestaande `tests/test_web_vandaag.py`

**Interfaces:**
- Consumes: alle macro's uit Taak 1; `track_record.week_summary(rows, cost_pct)` met velden `net_r: float`, `resolved: int`, `cumulative: list[float]`, `days: list[tuple[date, float]]`.
- Produces: contextsleutels `week` (dict uit `week_summary`), `week_spark` (Markup), `today_r` (float, `week["days"][-1][1]`).

- [ ] **Step 1: Failing tests**: (a) met twee afgeronde signalen (maak ze zoals de week-tests in `tests/test_web_extras.py` doen; lees die eerst) toont `/vandaag` `class="hl-num"` met het getal gelijk aan wat `/week` toont (`"%+.1f"|format(week.net_r)`), en `proof-spark` in `.hl-spark`. (b) zonder afgeronde trades: tekst "Nog niets afgerond". (c) `data-utabs="vandaag"`, `id="tab-kansen"`, `class="mrow-wrap"` bij een script met scenario, `quick-actions` nog aanwezig. (d) de bestaande tekst `1 van 6 meldingen in 24 uur` en `stroke-dashoffset="83.3"` (bestaande test dekt dit).
- [ ] **Step 2: Run**, verwacht FAIL.
- [ ] **Step 3: Implementeer.** In `_vandaag_context` na `rows = report_rows(user)`:

```python
    week = track_record.week_summary(rows, config.TRACK_RECORD_COST_PCT)
```

  en in het return-dict `"week": week, "week_spark": Markup(track_record.sparkline_svg(week["cumulative"], width=132, height=44)), "today_r": week["days"][-1][1] if week["days"] else 0.0`. `/api/vandaag` gebruikt dezelfde context en geeft deze sleutels niet door: niets aan te passen.

  In `vandaag.html` (prosa-diff):
  - `{% block page_title %}Vandaag{% endblock %}`; weg: `page-head` met `h2`. Begroeting blijft als kleine regel onder de kop (test zoekt "Goede" en "CEO tester").
  - Groot getal:

```jinja
{{ macros.headline("Resultaat laatste 7 dagen, na kosten", "%+.1f"|format(week.net_r), "R", spark=week_spark,
     delta=("Nog niets afgerond" if not week.resolved else "%+.2f"|format(today_r) ~ "R vandaag"),
     tone=("pos" if week.resolved and today_r > 0 else "neg" if week.resolved and today_r < 0 else ""), href="/week") }}
```

  - Kernregels: rijen zoals in Deel 2; de ring:

```jinja
{% set ring %}{% if not budget.off %}<svg class="vd-budget-ring" viewBox="0 0 40 40" aria-hidden="true"><circle class="vd-budget-bg" cx="20" cy="20" r="17"/><circle class="vd-budget-fill" cx="20" cy="20" r="17" pathLength="100" stroke-dasharray="100" stroke-dashoffset="{{ budget.offset }}"/></svg>{% endif %}{% endset %}
{{ macros.keylines([
  {"label": "Kansen open", "value": plans_ready, "explain": (open_parts|map("join", " ")|join(". ") ~ ".") if open_parts else "Er staat niets open. Een melding volgt zodra er een breuk of voorwaarde klopt."},
  {"label": "Het eerst aan de beurt", "value": (nearest.name ~ " " ~ nearest.dist) if nearest else "-", "href": nearest.url if nearest else none},
  {"label": "Meldingen in 24 uur", "value": budget.label, "html": ring, "href": "/account"}], "vd") }}
```

    Let op: `open_parts` is een lijst `(n, label)`; `map("join", " ")` werkt niet op ints. Bouw de zin in de template met een lus (`{% set parts %}{% for n, label in open_parts %}{{ n }} {{ label }}{% if not loop.last %}. {% endif %}{% endfor %}{% endset %}`) en geef `parts` door. `.vd-budget-ring` krijgt in CSS `width: 18px; height: 18px` binnen `.kl`.
  - Tabs: `utabs([{"key":"kansen","label":"Kansen","href":"#tab-kansen","count":plans_ready}, {"key":"markt","label":"Markt","href":"#tab-markt"}, {"key":"agenda","label":"Agenda","href":"#tab-agenda"}, {"key":"score","label":"Score","href":"#tab-score"}], "kansen", "vandaag", menu=[{"label":"Mijn week","href":"/week"},{"label":"Beste setups","href":"/structuur?alleen=ab"},{"label":"Instellingen","href":"/account"}], menu_class="quick-actions")`. Het oude `<nav class="quick-actions">` met tegels verdwijnt.
  - `<div class="ut-panels" data-utabs-panels="vandaag">` met vier `<section data-utab-panel id="tab-...">`. Kansen: getekende plannen (bestaand) en het markt-script per coin als rijen:

```jinja
{{ macros.row_head("Markten", "Prijs", "24 uur") }}
{% for s in scripts %}
<details class="mrow-wrap vd-bias-{{ s.bias }}"{% if s.scenarios|selectattr("state", "equalto", "waiting")|list %} open{% endif %}>
  {{ macros.market_row(s.coin, s.coin, chip=s.bias, chip_tone=("pos" if s.bias == "long" else "neg" if s.bias == "short" else ""),
       subtitle=(s.scenarios|length ~ " scenario" ~ ("'s" if s.scenarios|length != 1 else "")) if s.scenarios else "Geen scenario",
       price_coin=s.coin, price_text=(fmt(s.price) if s.price else ""), chg_coin=s.coin, el="summary") }}
  <div class="mrow-body">
    <p class="vd-summary">{{ s.summary or "Geen duiding." }}</p>
    {# hier ongewijzigd het bestaande blok vanaf "{% if not s.scenarios %}" tot en met de footer "Geschreven om" #}
  </div>
</details>
{% endfor %}
```

    Markt: BTC-koers (`vd-hero-price`, met `data-vd-price="BTC"`), `mood_bar` (blijft, test zoekt "1 long-scenario"), liquidaties, nieuws, als `.flat`-secties. Agenda: bestaande `#agenda`-sectie als `.flat` (id `agenda` blijft voor oude links: zet `id="tab-agenda"` op het paneel en laat `id="agenda"` op de inhoud). Score: `vd-score-grid` blijft.
  - Lege `scripts`: bestaande tekst "Nog geen script geschreven" blijft.
- [ ] **Step 4: Run** suite, PASS. Playwright op `/vandaag` 390px, 1280px, reduced-motion; bekijk de afbeeldingen. Klik door de vier tabs met een schermafbeelding per tab; open een coinrij en controleer dat de grafiek getekend is (canvas zichtbaar in de afbeelding), een kopieerchip tikken zet tekst op het klembord (`page.evaluate("navigator.clipboard.readText()")` met clipboard-permissie), de bel `aria-pressed` wisselt. Trek-om-te-verversen: touch-emulatie, `page.touchscreen` omlaag 120px bovenaan, de `.pull-hint` verschijnt.
- [ ] **Step 5: Commit** `git commit -m "Vandaag in de nieuwe indeling, weekresultaat als groot getal"`

### Task 5: Radar

**Files:**
- Modify: `web/templates/smc.html`
- Modify: `web/static/style.css` (`.radar-card` plat op de telefoon)
- Test: `tests/test_web_layout.py` (`RadarLayoutTests`), bestaande `tests/test_web_radar.py`

**Interfaces:**
- Consumes: macro's uit Taak 1; global `proof("smc")` met `label`, `text`, `state`.
- Produces: geen nieuwe contextsleutels (route ongewijzigd).

- [ ] **Step 1: Failing tests**: `/smc` bevat `data-utabs="radar"`, `id="tab-wachten"`, `class="hl-num"` met het aantal wachtende setups, en per kaart `class="mrow"` met `data-vd-price="<coin>"`; nog steeds `data-radar-key`, `data-radar="state"`, `r-progress`, `Wacht op de zone`, de approach-aria.
- [ ] **Step 2: Run**, FAIL.
- [ ] **Step 3: Implementeer.** `page_title` "Radar"; `<title>` blijft "SMC-radar". Groot getal `headline("Setups die wachten", setup_cards|length, "wachten", delta=signal_cards|length ~ " open trades")`. Kernregels zoals Deel 2. Tabs Wachten/Open/Afgerond met panelen; "Doel gehaald zonder vulling" staat onder Wachten. Per kaart: vervang `<header class="radar-head">...</header>` door

```jinja
{{ macros.market_row(c.coin, c.coin, chip=c.direction, chip_tone=("pos" if c.direction == "long" else "neg"),
     price_coin=c.coin, chg_coin=c.coin, href="/coins/" ~ c.coin) }}
```

  en laat `<div class="radar-state ..." data-radar="state">` direct eronder staan (radar.js schrijft daar). De oude `radar-spark`-svg verdwijnt uit de kop (24u staat nu als getal; het lijntje staat op de coinpagina). Kaarten van open trades idem. "Afgeronde signalen" blijft `signal_card`-lijst in een `.flat`. CSS: op ≤760px `.radar-card { background: none; border: 0; border-bottom: var(--sep); border-radius: 0; box-shadow: none; padding: 0 0 var(--space-9); }`.
- [ ] **Step 4: Run** suite, PASS. Playwright `/smc` 390px en 1280px met minstens één wachtende setup in de scratch-DB (maak er een zoals `tests/test_web_radar.py` doet, of laat de echte scanner draaien). Bekijk: afstandsbalk zichtbaar, live koers rechts in de rij, 24u gekleurd na het laden van spark-data, bellen en chips werken.
- [ ] **Step 5: Commit** `git commit -m "Radar in de nieuwe indeling"`

### Task 6: Setups

**Files:**
- Modify: `web/templates/structuur.html`, `web/static/style.css`
- Test: `tests/test_web_layout.py` (`SetupsLayoutTests`), bestaande tests in `tests/test_web_vandaag.py`

**Interfaces:** Consumes macro's; route ongewijzigd.

- [ ] **Step 1: Failing tests**: `/structuur` bevat `data-utabs="setups"`, groot getal met het aantal klaarstaande plannen, kernregels met `counts.total`; filterchips en `engine-status`-tekst blijven ("Laatste 24 uur: 1 kans gezien, 1 beoordeeld", "Alleen sterk en redelijk", "Geen plan klaar"); `stack.js`-knoppen (`#stack-toggle`) blijven.
- [ ] **Step 2: Run**, FAIL.
- [ ] **Step 3: Implementeer** volgens Deel 2. Rijen voor Trend:

```jinja
{{ macros.market_row(s.coin, s.coin, chip=s.direction, chip_tone=("pos" if s.direction == "long" else "neg"),
     subtitle="Instap " ~ "%.4f"|format(s.price) ~ ", stop " ~ "%.4f"|format(s.stop_loss) ~ ", doel " ~ "%.4f"|format(s.take_profit),
     right_text=(s.auto_outcome or "open"), href="/coins/" ~ s.coin ~ "#signal-" ~ s.id) }}
```

  (vervangt de oude regel met `·`-scheiders). Eerder: `subtitle=h.state_label`, `right_text=h.grade|grade_word`, `el="div"`; de `geen_plan`-reden komt als tweede ondertitelregel.
- [ ] **Step 4: Run** suite, Playwright `/structuur` 390px en desktop, bekijk; stapelweergave aan en uit.
- [ ] **Step 5: Commit** `git commit -m "Setups in de nieuwe indeling"`

### Task 7: Bewijs

**Files:**
- Modify: `web/templates/bewijs.html`, `web/static/style.css`, `web/main.py` (`bewijs_page`: `total` apart doorgeven)
- Test: `tests/test_web_layout.py` (`BewijsLayoutTests`), bestaande Bewijs-tests

**Interfaces:**
- Consumes: macro's; `summary` entries met `source`, `avg_net`, `recent_avg_net`, `resolved`, `winrate`, `open_or_expired`, `wins`, `losses`, `spark`.
- Produces: contextsleutel `total` (de entry met `source == "alles"` of `None`) en `per_type` (de rest, zelfde volgorde).

- [ ] **Step 1: Failing tests**: met de bestaande fixture uit de Bewijs-test (3 trades, 1 winst 2 verlies): groot getal is `"%+.2f"|format(total.avg_net)`, kernregel "Open of vervallen" bestaat en toont `open_or_expired`, de tekst "1 winst, 2 verlies" staat er nog, en het totaal komt niet twee keer als rij voor (`html.count('data-proof-source="alles"') == 0` in de rijenlijst). `Resultaatcurve per soort`, `Uurkaart`, `class="hourmap"`, `class="equity-dd"`, `proof-spark`, `Nog te weinig data` blijven.
- [ ] **Step 2: Run**, FAIL.
- [ ] **Step 3: Implementeer.** In `bewijs_page`: `total = next((e for e in summary if e["source"] == "alles"), None)`, `per_type = [e for e in summary if e["source"] != "alles"]`, beide meegeven (`summary` blijft voor de lege-staat-check). Template volgens Deel 2. Per soort:

```jinja
<details class="mrow-wrap">
  {{ macros.market_row(e.label[:3]|upper, e.label, chip=status_labels[e.status], subtitle=e.resolved ~ " afgerond" ~ (", winrate " ~ "%.0f"|format(e.winrate * 100) ~ "%" if e.winrate is not none else ""),
       right_text=("%+.2f"|format(e.avg_net) ~ "R" if e.avg_net is not none else "-"), right_tone=("pos" if e.avg_net and e.avg_net > 0 else "neg" if e.avg_net and e.avg_net < 0 else ""), el="summary") }}
  <div class="mrow-body">{# de volledige bestaande inhoud van <article class="proof-card"> vanaf proof-quote tot en met de laatste proof-footnote #}</div>
</details>
```

  De footnote met "open of vervallen, die tellen niet mee" staat ook onder de kernregels voor het totaal. Tabs Per soort / Regels / Curves / Uurkaart; de bestaande `<details class="stats-collapse">` rond curves en uurkaart mogen in hun paneel open staan (`open`-attribuut), de samenvattingstekst blijft voor de test.
- [ ] **Step 4: Run** suite, Playwright `/bewijs` 390px en desktop, bekijk alle vier tabs; de uurkaart scrollt horizontaal binnen zijn eigen vak (`.hourmap-wrap`), niet de pagina.
- [ ] **Step 5: Commit** `git commit -m "Bewijs in de nieuwe indeling, totaal als groot getal"`

### Task 8: Journaal, Meldingen en Week

**Files:**
- Modify: `web/templates/signalen.html`, `web/templates/meldingen.html`, `web/templates/week.html`, `web/static/style.css`
- Test: `tests/test_web_layout.py` (`ListPagesLayoutTests`), bestaande tests

**Interfaces:** Consumes macro's; routes ongewijzigd.

- [ ] **Step 1: Failing tests**: `/signalen` heeft linktabs met `href="/signalen?alles=1"` als `ut-tab` en het formulier `action="/signalen/verbergen-alles"` binnen `.ut-menu`; `/meldingen` heeft groot getal `unread_count` en `data-notification-id` blijft; `/week?dagen=30` heeft `ut-tab is-active` op "1M", `data-share-chart` blijft, "laatste 30 dagen" blijft.
- [ ] **Step 2: Run**, FAIL.
- [ ] **Step 3: Implementeer** volgens Deel 2. Formulieren in het menu: geef `utabs` geen `menu` maar zet zelf `<details class="ut-more">` met het formulier erin, of breid de macro uit met `{{ caller() }}` in `.ut-menu` (kies de `caller`-variant en pas Taak 1-test niet aan: `caller` is optioneel). Meldingen CSS:

```css
.nf-link { display: grid; grid-template-columns: var(--icon-row) minmax(0, 1fr) auto; column-gap: var(--space-6); align-items: start; min-height: var(--row-h); padding: var(--space-4) 0; }
.nf-chip { width: var(--icon-row); height: var(--icon-row); border-radius: 50%; display: grid; place-items: center; overflow: hidden; font-size: 9px; }
```

  (controleer eerst de bestaande `.nf-*`-regels en vervang ze in plaats van ze te stapelen). Week: `headline("Resultaat, laatste " ~ dagen ~ " dagen", "%+.1f"|format(week.net_r), "R na kosten", spark=spark)`, de `kans-outcome`-regel vervalt, `ceo-headline` blijft.
- [ ] **Step 4: Run** suite, Playwright `/signalen`, `/signalen?alles=1`, `/meldingen`, `/week` op 390px, bekijk; "alles niet interessant" toont nog de confirm (luister met `page.on("dialog")`).
- [ ] **Step 5: Commit** `git commit -m "Journaal, Meldingen en Week in de nieuwe indeling"`

### Task 9: Coinpagina

**Files:**
- Modify: `web/templates/coin.html`, `web/static/style.css`, `web/main.py` (alleen als `live_quote` niet in de template-globals staat: het staat er al als global, dus waarschijnlijk niets)
- Test: `tests/test_web_layout.py` (`CoinLayoutTests`), bestaande coin-tests

**Interfaces:** Consumes `headline` met `attrs`, `spark_coin`, `delta_coin`; coin.js zoekt `#coin-price` met `data-symbol` (lees `coin.js` op die selector voor je begint).

- [ ] **Step 1: Failing tests**: `/coins/BTC` bevat `class="hl-num" id="coin-price" data-symbol="BTC"` (volgorde van attributen kan verschillen: test met twee losse `assertIn`), `data-spark-coin="BTC"`, `data-spark-chg="BTC"`, en nog steeds "Plan voor BTC" en "verlies je ongeveer € 25".
- [ ] **Step 2: Run**, FAIL.
- [ ] **Step 3: Implementeer** volgens Deel 2: `coin-masthead` wordt kop plus `headline("Koers", prijs-tekst, live_quote|upper, spark_coin=symbol, delta_coin=symbol, attrs={"id": "coin-price", "data-symbol": symbol})` plus `keylines`. De prijsopmaak blijft de bestaande uitdrukking (`"%.4f"` onder 100, anders met spaties). `muted-pill` en `coin-note-banner` blijven onder de kernregels. Overzichtskaarten worden `.flat`; `primary-card` met open trade en formulieren blijft kaart.
- [ ] **Step 4: Run** suite, Playwright `/coins/BTC` 390px en desktop, bekijk; wacht 3 seconden en controleer dat het getal live verandert (twee schermafbeeldingen of `textContent` vergelijken) als de beurs bereikbaar is; anders noteren.
- [ ] **Step 5: Commit** `git commit -m "Coinpagina in de nieuwe indeling, live koers als groot getal"`

### Task 10: Account, CEO, Kans, Keten, Handleiding en Meer-blad

**Files:**
- Modify: `web/templates/account.html`, `ceo.html`, `kans.html`, `keten.html`, `uitleg.html`, `web/templates/base.html` (Meer-blad: regel Uitloggen), `web/static/style.css`
- Test: `tests/test_web_layout.py` (`RestLayoutTests`), bestaande tests

**Interfaces:** Consumes macro's. `winrate` op Account is `repo.winrate_for_user(user_id)`: lees de vorm (dict of getal) voor je hem toont.

- [ ] **Step 1: Failing tests**: elke pagina heeft `class="ph"` met de juiste titel; `/account` heeft groot getal open posities en nog steeds "Maximaal aantal pushes per dag"; `/ceo` heeft `class="kl"` met "Dagen in functie" en nog steeds "Chief Executive Officer", "De leerlingen", "Leerling van de maand", "Aanwezigheid"; het Meer-blad bevat `action="/logout"`.
- [ ] **Step 2: Run**, FAIL.
- [ ] **Step 3: Implementeer** volgens Deel 2. Meer-blad: onder `.more-links` een `<form action="/logout" method="post" class="more-logout"><button type="submit">Uitloggen</button></form>`, gestyled als een `.more-links a`.
- [ ] **Step 4: Run** suite, Playwright op alle zes pagina's 390px, bekijk.
- [ ] **Step 5: Commit** `git commit -m "Overige pagina's in de nieuwe indeling, uitloggen in Meer"`

### Task 11: Eindcontrole over alles en documentatie

**Files:**
- Modify: `CLAUDE.md` (alinea Web layer: één zin over de indelingsmacro's en `utabs.js`; alinea UX-extra's: dok en gloed), `README.md` alleen als daar schermbeschrijvingen staan (controleer)
- Modify: `scripts/layout_check.py` (standaard paginalijst)

- [ ] **Step 1:** Zet in `layout_check.py` als standaard alle ingelogde pagina's: `/vandaag /structuur /smc /bewijs /signalen /meldingen /account /week /ceo /uitleg /keten /coins/BTC` plus één `/kans/<id>` als die bestaat.
- [ ] **Step 2:** Draai de volledige suite (`SKIP_SLOW_TESTS=1 python3 -m unittest discover -s tests -t . -v`) en daarna zonder `SKIP_SLOW_TESTS` (`test_smc_equivalence` duurt minuten; de golden tests horen ongemoeid te blijven, deze ronde raakt geen beslislogica).
- [ ] **Step 3:** Draai de controle op 390px, op 1280px en met `--reduced-motion`. Bekijk elke afbeelding. Lijst per pagina: gloed zacht, geen harde rand; contrastregel uit de uitvoer ≥ 4,5; geen horizontale scroll; dok niet over de laatste inhoud (scroll naar onder, laatste element boven het zoekveld); pushbanner (forceer `hidden=false` via `page.evaluate`) duwt de kop niet onder de statusbalk.
- [ ] **Step 4:** Doorloop de gedragslijst uit Global Constraints één voor één in de browser en noteer per punt "werkt" of wat er mis is: pauzeknop (tik, label wordt "Stil 2:00"), bel, kopieerchip, afstandsbalk, afstandsring, sparklines, trek-om-te-verversen, pushbanner, dok weg bij scrollen, tik op actieve tab naar boven, Meer-blad via tab en via titel, palette via zoekveld en Ctrl+K, systeemstatus-popover, koersstip.
- [ ] **Step 5:** Zoek naar em dashes in gewijzigde templates: `git diff -U0 | grep -n $'—\|–'` moet leeg zijn voor nieuwe regels.
- [ ] **Step 6: Commit** `git commit -m "Indeling: eindcontrole en documentatie"`

---

## Deel 4. Risico's en open vragen

**Risico's**

1. **Panelen verbergen grafieken.** levelchart.js tekent bij in beeld komen. Een grafiek in een verborgen paneel of dichte `<details>` moet tekenen zodra hij zichtbaar wordt. utabs.js stuurt daarom een `resize`; Taak 4 en 5 controleren dit met een schermafbeelding. Werkt het niet, dan krijgt levelchart.js een `toggle`-luisteraar op `details` (kleine wijziging, eigen test in `levelchart_harness.js`).
2. **`popover`-attribuut** werkt vanaf iOS 17 en Chrome 114. Op ouder toestel is het gestippelde label gewoon tekst zonder uitleg. Geen fout, wel minder uitleg.
3. **Contrast boven de gloed** is krap (4,7:1 berekend). De meting in Taak 2 beslist; één token (`--glow-top`) regelt het. Samen met de bestaande drijvende `.glow-accent` kan een plek lokaal lichter worden; de meting op meerdere pagina's vangt dat.
4. **Stapeling van de gloed.** `html` (inline in `base.html`) en `body` hebben allebei een achtergrond, dus een laag met `z-index: -1` wordt door de body-achtergrond afgedekt. Daarom `z-index: 0` op `.top-glow` en `main` op `z-index: 1`. Controleer in de schermafbeelding dat de gloed echt zichtbaar is, en dat de bestaande `.page-ambient` (ook `z-index: -1`) niet onbedoeld zichtbaar of onzichtbaar wordt door deze wijziging.
5. **Topbar op de telefoon.** De vaste knoppen blijven in `.topbar` (unieke ID's voor pause.js, stale.js, base-script). Die wordt op de telefoon een transparante rechterhoek over de kop. Als de titel lang is (coin plus richting op Kans) kan hij onder de knoppen lopen: `.ph-title` krijgt `max-width: calc(100% - 170px)` met ellips als de controle overlap toont.
6. **Ruimte onderaan.** Zoekveld plus tabbalk kosten ongeveer 130px. `main` krijgt 150px onderruimte; op Vandaag met veel inhoud is dat prima, op lege pagina's ziet het leeg uit, wat bij de referentie past.
7. **Tests die op markup leunen.** De lijst in Global Constraints is gemaakt met grep op de huidige tests; een uitvoerder die een string weghaalt die een test eist, moet de markup terugzetten, niet de test aanpassen.
8. **Coin-iconen** zijn monogrammen (eerste letters), want er zijn geen logobestanden en externe logo's zouden een nieuwe bron zijn.
9. **Desktop.** Het plan is telefoon eerst. Op desktop blijft de topbar met nav, het dok is verborgen, de nieuwe componenten werken ook breed maar zijn niet apart ontworpen.

**Open vragen voor de gebruiker**

1. Zoekveld op elke pagina, of alleen op Vandaag en Radar (zoals de referentie het alleen op Start toont)? Plan gaat uit van elke pagina.
2. Groot getal op Vandaag: resultaat laatste 7 dagen in R na kosten (zelfde als Kwartaalcijfers). Akkoord, of liever het aantal open kansen als groot getal?
3. De lopende koersband (ticker) bovenaan Account en de drijvende achtergrondvlakken: laten staan, of weg op de telefoon nu de rijen de koersen tonen? Plan: ticker weg op de telefoon, achtergrondvlakken blijven (die zijn aan live waarden gekoppeld).
4. Markt-script per coin op Vandaag: standaard dicht en alleen coins met een wachtend scenario open, akkoord?
5. Coin-iconen: monogram (BTC in een rondje) goed genoeg, of later echte logo's als lokale bestanden toevoegen?
6. Titel met pijltje opent het Meer-blad om van pagina te wisselen. Is dat wat je verwacht bij het pijltje, of liever een eigen lijst met alleen de hoofdpagina's?
