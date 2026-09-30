# Positiegrootte, portfolio en evaluatie weghalen — design

## Aanleiding

HesPulse draait sinds de puur-signalen-herziening (2026-09-21) al grotendeels
puur op signalen: `/signalen` is de standaardpagina, de automatische
winrate/trackrecord (`signals.auto_outcome`) is al volledig los van geld, en
het generieke portfolio×risico%-sizingformulier is al uit `account.html`
gehaald. Maar drie dingen zijn blijven staan:

1. **`/dashboard`**: een verweesde route + template van vóór die
   herziening. Geen navigatielink wijst er meer naartoe (`/` stuurt
   ingelogde gebruikers door naar `/signalen`), maar de route zelf bestaat
   nog en toont de oude UI: het "Evaluatie simulatie"-blok, de
   risicogauge, en de oude journaal-knoppen. Een geïnstalleerde
   PWA-snelkoppeling van vóór de herziening wijst hier nog naartoe — dat
   is precies wat de gebruiker op zijn telefoon zag en aanleiding gaf voor
   dit project.
2. **De evaluatie-simulatie** (`/evaluatie`, `prop_evaluations`, tiers,
   dagbudget/drawdown-bewaking): volledig actieve, aparte functie, bewust
   losstaand van het generieke sizingformulier.
3. **Wat overblijft van geld-gebaseerde berekening**: `risk_eur`/
   `position_size` op journaalregels (nog steeds gevuld voor
   evaluatie-gekoppelde trades), `result_eur` bij het sluiten van een
   trade, de losse "risicobedrag → positiegrootte"-rekenhulp op de
   coin-pagina, en de risicogauge.

Dit project haalt alle drie weg. HesPulse toont daarna alleen nog signalen
met entry/stop/take-profit en een winrate/trackrecord op basis van wat de
markt daadwerkelijk deed — geen enkele berekening meer op basis van iemands
eigen geld.

## Scope

**Wel:**

1. `/dashboard` weg (route stuurt door naar `/signalen`, template
   verwijderd).
2. De hele evaluatie-simulatie weg: routes (`/evaluatie`,
   `/evaluatie/start`, `/evaluatie/stop`), templates (`evaluatie.html`,
   `evaluatie.js`), de zichtbare kaart/link, en alle evaluatie-specifieke
   functies in `app/risk.py` en hun aanroepen in `app/signal_processor.py`.
3. De generieke positiegrootte-berekening weg: `risk.compute_risk_eur`,
   `risk.compute_position_size`, en de plekken die daarmee `risk_eur`/
   `position_size` op een journaalregel zetten.
4. De losse "risicobedrag → positiegrootte"-rekenhulp op de coin-pagina
   weg (`/coins/{symbol}/oefen-preview`-route, het formulier in
   `coin.html`, de bijbehorende JS in `coin.js`).
5. Account-pagina: de verborgen `portfolio_eur`/`risk_percent`-velden (het
   "Taak 11"-restant) en het portfolio-saldo-blok weg.
6. De risicogauge ("risico open" tegen portfolio) weg van `/signalen`.
7. Journaal-weergave en CSV-export: `risk_eur`, `position_size`,
   `risk_percent_used` weg; `result_pct` (bestaat al) wordt de enige
   resultaatmaat voor een gesloten trade.

**Niet:**

- De automatische winrate/trackrecord (`winrate_for_user`,
  `signals.auto_outcome`) — draait al puur op prijsdata, blijft
  ongewijzigd.
- `confirm_threshold_pct` (Soepel/Normaal/Streng) en de verplichte-
  factoren-instelling — ander percentage, gaat over signaalvertrouwen,
  niet over geld.
- De journaal-kernflow zelf (Genomen/eigen entry/Bevestig, status,
  sluiten met exit-prijs, notities, maandoverzicht-als-afbeelding) —
  blijft, alleen zonder de geld-kolommen.
- Databasekolommen/-tabellen (`users.portfolio_eur`, `users.risk_percent`,
  `journal_entries.risk_eur`/`position_size`/`position_size_override`/
  `evaluation_id`/`result_eur`, de hele `prop_evaluations`-tabel): blijven
  bestaan, worden alleen nergens meer gelezen of geschreven door actieve
  code (zie Aanpak hieronder).

## Aanpak: code weg, schema laten staan

Overwogen is ook de kolommen/tabellen zelf te verwijderen via een
DROP COLUMN/DROP TABLE-migratie. Gekozen is voor de lichtere aanpak: alle
code die deze kolommen leest of schrijft verwijderen, de kolommen zelf met
rust laten. Dit is consistent met hoe `users.risk_percent` al sinds de
vorige opschoning ongebruikt in de tabel staat, vereist geen destructieve
migratie op de productiedatabase, en is met minder risico terug te draaien
mocht iets over het hoofd gezien zijn. `schema.sql` en `app/db.py:_migrate()`
blijven in dit project ongewijzigd.

## Journaal-resultaat zonder geld

`journal_entries.result_pct` bestaat al en wordt in `close_journal_trade`
nu al puur uit entry-/exit-prijs berekend (percentage koersbeweging,
richting-bewust voor long/short), volledig los van `risk_eur`/
`position_size`. Alleen `result_eur` — en de evaluatie-specifieke
fee/hefboomkosten-aftrek erbovenop — verdwijnt uit die functie. De
`portfolio_eur`-bijschrijving (`UPDATE users SET portfolio_eur =
portfolio_eur + ...`) verdwijnt eveneens: zonder generieke sizing en
zonder evaluatie heeft die optelling geen doel meer.

Overal waar de UI nu `result_eur`/€-bedragen toont (journaaltabel,
CSV-export, maandoverzicht-als-afbeelding, de vergelijkende
risicopercentage-tekst op de statistiekenpagina) wordt dat `result_pct`.
De vergelijkende tekst die nu "kleiner risico (≤ jouw mediaan)" zegt op
basis van `risk_percent_used`, vervalt (geen risk_percent_used meer om op
te vergelijken) of wordt herschreven naar een vergelijking op `result_pct`
als dat zinvol blijft — dit werkt de implementatie-plan-fase verder uit.

## Wat blijft werken: bewijslast per stuk

- **Winrate/trackrecord**: `repo.winrate_for_user` (app/repo.py:2718) leest
  alleen `signals.pass_pct`, `hard_gates_ok`, `auto_outcome`, `reason` —
  geen enkele kolom uit dit project. Ongewijzigd correct na deze opschoning.
- **`confirm_threshold_pct`**: apart veld op `users`, aparte instelling
  (Soepel/Normaal/Streng) in `account.html`, geen raakvlak met
  `risk_percent`.
- **Journaal-kernflow**: de routes `/journal/{entry_id}/status`,
  `/journal/{entry_id}/close`, `/journal/{entry_id}/note` blijven
  functioneel identiek, verliezen alleen de `risk_eur`/`position_size`-
  berekening die er nu nog inzit.

## Addendum: ontdekte ripple-effecten (na spec-goedkeuring, tijdens planning)

Tijdens de planfase bleek de daadwerkelijke omvang groter dan hierboven
beschreven: `result_eur`/`risk_eur` worden niet alleen in de journaaltabel en
CSV-export gebruikt, maar ook door een reeks losse statistiek- en
weergavefuncties die na deze opschoning altijd nul/leeg zouden worden
(omdat `risk_eur` op elke nieuwe trade al 0 wordt zodra de evaluatie en de
rekenhulp weg zijn — dat gebeurt sowieso, ongeacht wat dit project doet).
Gebruiker heeft bevestigd (AskUserQuestion, "Ja, allemaal mee") dat deze
ook naar percentage-gebaseerd moeten, in plaats van stil op nul te
bevriezen:

- **Ambient achtergrondgloed** (`base.html`'s `portfolioGlow`, gevoed door
  `/api/system_status`'s `week_result_eur`) — wordt gevoed door een
  percentage-equivalent.
- **Cumulatieve resultaatgrafiek** (`repo.cumulative_result_series`) — som
  van `result_pct` in plaats van `result_eur`.
- **Trade-kalender-heatmap** (`repo.daily_results`) — zelfde omzetting.
- **Wekelijkse/maandelijkse samenvatting** (`app/periodic_summary.py`,
  `repo.period_stats`/`period_stats_auto_scan`) — tekst toont percentage
  in plaats van "+€X".
- **Overige statistiek-functies** in `app/repo.py` die `result_eur`
  sommeren/middelen voor winrate-uitsplitsingen (`winrate_stats`,
  `coin_stats`, en vergelijkbare) — consistent omgezet.
- **Live PnL op een open trade-kaart** (`risk.compute_unrealized_pnl`,
  getoond als "€X (+Y%)" op elke open-positie-kaart, bijgewerkt door
  `dashboard.js`-polling): de huidige `pnl_pct` is zelf ook
  risicogewogen (`pnl_eur / risk_eur * 100`, dus een R-multiple), niet de
  kale koersbeweging — wordt eveneens 0 zodra `risk_eur` altijd 0 is.
  Consistent met de rest van deze addendum: `pnl_eur` weg, `pnl_pct`
  herdefinieerd als de kale procentuele koersbeweging (zelfde formule als
  `journal_entries.result_pct`).

Dit raakt geen nieuwe scope-BESLISSING (alles hierboven volgt rechtstreeks
uit "puur percentage" + "alles weg"), maar wel een substantieel groter
implementatie-oppervlak dan de oorspronkelijke spec-tekst suggereerde.

## Testen

Geen pytest-suite. Verificatie zoals gebruikelijk in dit project:

- **Backend**: een throwaway script tegen een scratch-database dat een
  testsignaal aanmaakt, als "Genomen" markeert met een eigen entry-prijs,
  sluit met een exit-prijs, en bevestigt dat `result_pct` correct is en
  `result_eur`/`portfolio_eur` niet meer worden aangeraakt. Een grep-
  verificatie dat geen actieve module (`app/`, `web/main.py`) nog
  `portfolio_eur`, `risk_percent`, `compute_position_size`,
  `compute_risk_eur`, of een evaluatie-functienaam aanroept.
- **Frontend**: handmatige Playwright-controle van `/signalen`, `/account`,
  `/coins/BTC` (geen rekenhulp meer), en een directe request naar
  `/dashboard` die een redirect naar `/signalen` teruggeeft. Controleren
  dat de risicogauge weg is en dat het journaal `result_pct` toont in
  plaats van `result_eur`.
