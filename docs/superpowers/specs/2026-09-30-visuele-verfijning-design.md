# Visuele verfijning: spacing/type-schaal + overzichtelijkere pushmeldingen — design

## Aanleiding

Na het verkleinen-project wilde de gebruiker dat deze update ook echt als
een zichtbare stap vooruit aanvoelt ("mooie verbetering... stapje omhoog"),
op twee vlakken: de layout van dashboard/coin-pagina/account, en de
pushmeldingen. Het bestaande ontwerp heeft al veel (heartbeat-animatie,
ambient gloed, risico-ademhaling, allemaal gekoppeld aan echte data) — dit
is dus geen nieuw ontwerp, maar een verfijningsslag op wat er al staat.

Tijdens het brainstormen kwam een los, veel groter punt naar boven (risico%
en portfoliowaarde volledig weghalen, HesPulse alleen nog puur signalen).
Dat is expliciet **niet** onderdeel van deze spec — een fundamentele
wijziging aan wat HesPulse berekent en toont, verdient een eigen brainstorm
met eigen vragen over wat er dan nog in een melding staat en wat er met
bestaande data gebeurt. Deze spec raakt alleen hoe dingen getoond worden,
niet wat er berekend of getoond wordt.

## Scope

Twee onderdelen:

1. Een echte spacing- en lettergrootte-schaal in `web/static/style.css`,
   toegepast op `base.html`, `dashboard.html`, `coin.html` en
   `account.html` — bestaande losse pixelwaardes vervangen door de
   dichtstbijzijnde tokenwaarde, zowel in CSS-regels als in inline
   `style="..."`-attributen in de templates.
2. Pushmeldingen die nu een dichte, met `·` gescheiden regel zijn,
   herschrijven met regeleinden zodat de belangrijkste cijfers in één
   oogopslag op een lockscreen te lezen zijn.

Niet in scope: nieuwe kleuraccenten, nieuwe kaartstijl, herstructurering
van markup of paginaopbouw, wijzigingen aan de animatie-logica (die blijft
precies zoals hij is, alleen de onderliggende getallen waar hij op
gebaseerd is — spacing/font-size — verschuiven naar tokens), en niets aan
wat risico%/portfolio berekenen of tonen (zie hierboven).

## Onderzoek: huidige staat

`style.css` gebruikt nu 24 verschillende spacing-waardes (`margin`,
`padding`, `gap`) en 19 verschillende lettergroottes, waaronder halve
pixels als 9.5px, 10.5px, 11.5px, 12.5px en 13.5px — duidelijk organisch
gegroeid, geen bewuste schaal. `account.html` is niet alleen een
profielpagina: het is het volledige journaal + instellingen + statistieken
in één pagina (onboarding-checklist, winrate-ring, portfolio-kaart,
stille-uren, drempel-instelling, verplichte-factoren, trade-kalender,
cumulatief-resultaat-grafiek, en de volledige meldingen-tabel met CSV-export)
— dichtbevolkt, met veel inline `style="..."`-attributen.

Een relevante bestaande code-comment in `account.html` (rond regel 210-215):
het formulier om `portfolio_eur`/`risk_percent` zelf in te stellen is al
eerder (Taak 11) verwijderd, de velden staan er nu alleen nog verborgen in
om het stille-uren-formulier te laten werken. Dit is precies het soort
restant dat relevant wordt zodra de aparte, latere brainstorm over
positiegrootte-verwijdering plaatsvindt — hier niet aangeraakt.

## Deel 1: spacing- en lettergrootte-schaal

Nieuwe tokens in `style.css`'s `:root`-blok, naast de bestaande
kleur/border/radius-tokens:

```css
/* Lettergrootte-schaal */
--text-2xs: 10px;
--text-xs: 11px;
--text-sm: 12px;
--text-base: 13px;
--text-md: 14px;
--text-lg: 16px;
--text-xl: 20px;
--text-2xl: 24px;
--text-3xl: 32px;

/* Ruimte-schaal */
--space-1: 2px;
--space-2: 4px;
--space-3: 6px;
--space-4: 8px;
--space-5: 10px;
--space-6: 12px;
--space-7: 16px;
--space-8: 20px;
--space-9: 24px;
--space-10: 32px;
```

Elke bestaande `margin`/`padding`/`gap`/`font-size`-waarde in `style.css`
en in inline `style="..."`-attributen in de vier templates wordt vervangen
door de dichtstbijzijnde token (bv. 12.5px en 13px worden allebei
`var(--text-base)`, 9px en 10px worden allebei `var(--space-5)`). Een paar
bewust bespoke grote layout-waardes (zoals 44px, 48px, 52px, 56px, 88px —
stuk voor stuk unieke, grote elementen zoals een hero-cijfer) blijven
letterlijke pixelwaardes, geen token nodig voor een waarde die maar één
keer voorkomt.

Geen wijziging aan kleur-tokens, borders, radius, of de animatie-`@keyframes`
zelf — alleen spacing en font-size.

## Deel 2: pushmeldingen met regeleinden

De dichte, `·`-gescheiden regel wordt een paar regels, met de belangrijkste
cijfers gescheiden van de rest. Toegepast op elk pad dat nu zo'n
dichte regel bouwt:

**Dagtradingsignaal** (`app/signal_processor.py`, in `process_day_trading_signal`):

Nu:
```python
body = (
    f"Entry {signal_data['price']:.4f} · Stop {effective_stop_loss:.4f} · "
    f"Take profit {effective_take_profit:.4f}{entry_zone_note}{sniper_line}"
)
```

Wordt:
```python
body = (
    f"Entry {signal_data['price']:.4f}\n"
    f"Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}"
    f"{entry_zone_note}{sniper_line}"
)
```

(`entry_zone_note` en `sniper_line` beginnen zelf al met `\n`, zie de
bestaande code — die blijven zo, komen dus automatisch op hun eigen regel.)

**Level-check-meldingen** (`app/level_check.py`, drie varianten): zelfde
patroon — het geraakte niveau op de eerste regel, de rest (entry-prijs,
huidige prijs) op de regel erna. Exacte regels worden in de plan-fase
opgezocht (regelnummers verschuiven na eerdere taken deze sessie).

**SMC-melding** (`app/market_scanner.py`): blijft ongewijzigd — is al een
lopende zin, geen dichte cijferregel.

Titel-opbouw (coin-symbool, richting, vertrouwen) blijft overal ongewijzigd,
alleen de body krijgt regeleinden.

## Testen

Geen pytest-suite in dit project. Voor Deel 1: geen geautomatiseerd testpad
nodig (puur CSS/template-waardes), verificatie via `uvicorn` tegen een
scratch-database + Playwright-screenshot van dashboard/coin/account, zoals
eerdere redesign-rondes deze sessie. Voor Deel 2: een throwaway script dat
`process_day_trading_signal`/de level-check-functies met een gemockte
`push_notify.send_push` aanroept en het body-argument op de aanwezigheid
van de juiste `\n`-regeleinden controleert.
