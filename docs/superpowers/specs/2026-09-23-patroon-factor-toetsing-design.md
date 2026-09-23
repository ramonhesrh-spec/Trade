# Patroon + factor-toetsing + kansberekening — ontwerp

## Doel

Patroonherkenning (Fase 1, live sinds 2026-09-23) meldt een bevestigd
patroon nu zonder het door de bestaande factor-toetsing te halen: elk
patroon krijgt vast `technical_confirmed=1`, `pass_pct=None` en de tekst
"patroon bevestigd". De gebruiker ziet zo nooit of EMA/MACD/RSI/volume (en,
indien aan, BTC-trend/dagtrend/premium-discount/liquidity-sweep) het
patroon ondersteunen, en er is geen enkele kansindicatie behalve de naam
van het patroon zelf.

Dit ontwerp voegt de bestaande factor-toetsing toe aan patroon-signalen
(zichtbaar, niet blokkerend) en introduceert een kansberekening die de
factor-uitkomst combineert met de historische winrate van dat specifieke
patroontype.

## Niet-doelen

- Geen harde poort: een patroon dat de factoren niet haalt wordt nog
  steeds gemeld. `technical_confirmed` en `hard_gates_ok` blijven vast op
  1 voor `trade_type='patroon'`, exact zoals nu.
- Geen wijziging aan stop/take/target-berekening (blijft de patroon-eigen
  gemeten beweging met ATR-terugval en de C2-sanity-check uit de vorige
  fix-ronde).
- Swing blijft buiten scope — die heeft al zijn eigen "niveau
  bevestigd"-toets en een principieel andere tijdshorizon.
- Geen wijziging aan wélke patronen gedetecteerd worden of hoe (geen
  aanpassing aan `app/patterns.py`'s detectielogica zelf).

## Architectuur: gedeelde toetsing-helper

`app/signal_processor.py::process_day_trading_signal` bevat nu inline de
volledige toetsing-opbouw: dagcandle ophalen, `daily_trend_factor` bouwen
(met de vlakke-markt-uitzondering via `btc_is_flat`), bij
`config.ENABLE_ADVANCED_FACTORS` de uitgebreide factoren via
`compute_advanced_extra_factors`, en tot slot
`indicators.confirms_direction(ind, direction, extra_factors=..., daily_trend_factor=..., include_advanced=...)`.

Dit blok wordt geëxtraheerd naar een nieuwe functie in hetzelfde bestand:

```python
async def compute_full_confirmation(
    coin: str, direction: str, df: pd.DataFrame, ind: indicators.Indicators, zones: list,
) -> tuple[bool, str, float, bool]:
    """Retourneert (confirmed, breakdown, pass_pct, hard_gates_ok) — de
    volledige factor-toetsing (basis + dagtrend + eventuele uitgebreide
    factoren), identiek aan wat process_day_trading_signal altijd al deed.
    Gedeeld met market_scanner._check_chart_patterns, zodat een patroon
    door dezelfde toetsing gaat als een dagtrading-signaal, zonder de
    logica te dupliceren."""
```

`process_day_trading_signal` roept deze helper voortaan zelf aan in plaats
van de inline versie — pure refactor, geen gedragswijziging voor
dagtrading. `market_scanner._check_chart_patterns` roept dezelfde helper
aan met `match.direction` zodra een patroon bevestigt (na de bestaande
dedup-check via `_same_pattern`/`get_pattern_key`), en gebruikt het
resultaat puur informatief: nooit om de melding tegen te houden.

`zones` (voor de bestaande steun/weerstand-achtige extra factoren) is in
`market_scanner.py` nergens gedeeld tussen de drie check-functies — elke
functie berekent zelf wat hij nodig heeft (`_check_breakout_retest` doet
dat nu al lokaal met `indicators.detect_sr_zones(df)`, `_check_chart_patterns`
doet hetzelfde al met `indicators.detect_trendlines`). `_check_chart_patterns`
krijgt op dezelfde manier zijn eigen `zones = indicators.detect_sr_zones(df)`-
regel vóór de aanroep van `compute_full_confirmation` — geen gedeelde
cache, consistent met het bestaande patroon in dit bestand.

## Datamodel

`signals.pass_pct` en `signals.hard_gates_ok` worden voor patroon-signalen
voortaan gevuld met de ECHTE uitkomst van `compute_full_confirmation`
(nu altijd `None`/`1`). `technical_confirmed` blijft vast op 1 — dat veld
bepaalt of een melding als "bevestigd" telt voor bestaande gating-logica
elders (bijvoorbeeld sparklines), en dat mag voor patroon niet gaan
wisselen op basis van factoren die toch nooit blokkeren.

`signals.reason` wordt voor patroon voortaan de echte breakdown-tekst uit
`compute_full_confirmation` (bijvoorbeeld "✓ Trend: ... | ✗ Momentum: ...")
in plaats van de huidige platte "Patroon: double top, richting short".

Nieuwe repo-functie, naar het voorbeeld van de bestaande `winrate_stats`:

```python
def pattern_winrate_stats() -> dict[str, dict]:
    """Systeembrede winrate per patroontype (niet per gebruiker — een
    patroon-signaal is hetzelfde voor iedereen, zie signals.auto_outcome),
    op dezelfde manier als winrate_stats dat per hoog/laag-vertrouwen doet
    voor dagtrading. Retourneert {pattern_name: {"winrate": float, "total": int}}
    voor elk patroontype met minstens één afgeronde (take_profit/stop_loss)
    signaal; ontbrekende patroontypes hebben simpelweg geen entry."""
```

SQL: groepeer `signals` op `pattern_name, auto_outcome` waar
`trade_type='patroon' AND auto_outcome IN ('take_profit','stop_loss') AND is_practice=0`.

## Kansberekening

Op het moment dat een patroon-signaal gebouwd wordt (in
`_check_chart_patterns`, ná `compute_full_confirmation`):

- `factor_pct` = `pass_pct` uit `compute_full_confirmation` (kan `None`
  zijn als er geen enkele optionele factor beschikbaar was — in de praktijk
  zelden, de vier basisfactoren zijn er altijd).
- `pattern_pct` = `pattern_winrate_stats()[match.name]["winrate"]`, of
  `None` als dit patroontype nog geen `PATTERN_MIN_SAMPLE` (voorstel: 5)
  afgeronde signalen heeft.
- `kansberekening` = gemiddelde van de twee als beide beschikbaar zijn;
  anders het enige beschikbare cijfer; anders `None` (dan toont de UI
  "nog weinig data", zoals nu al bij dagtrading gebeurt voor een nieuwe
  gebruiker/coin-combinatie).

Dit cijfer wordt opgeslagen op de journal-context bij weergave (zoals
`_add_signal_context` nu al `success_rate`/`success_sample` toevoegt),
niet in de database zelf — het verandert elke keer `pattern_winrate_stats`
nieuwe data krijgt, dus het hoort bij weergave-tijd berekend te worden,
niet bij signaal-aanmaak bevroren. Elke route die `_add_signal_context`
aanroept haalt `pattern_winrate_stats()` net als `winrate_stats(user_id)`
nu al vóór de aanroep op en geeft het resultaat als extra argument mee —
één query per pagina-request, niet één per signaal in de lijst, exact het
patroon dat `winrate_stats` al voor de bestaande hoog/laag-vertrouwen-
lookup volgt.

## UI

`_macros.html`'s `signal_card`: de patroonbadge ("double top") blijft
staan, met het kansberekening-percentage ernaast (zelfde plek/stijl als
de bestaande `pass-pct`-badge voor dagtrading, niet die badge zelf
hergebruiken want de kleur/interpretatie verschilt — nieuw label,
bijvoorbeeld "kans 61%").

De "waarom dit patroon?"-uitklap (`reason_popup`/`reason_factors`
patroon-tak, gebouwd in de vorige fix-ronde) toont voortaan de echte
factor-breakdown uit `signals.reason` op dezelfde manier als de
dagtrading-tak dat al doet (✓/✗ per factor), in plaats van de huidige
platte tekst. `advice.py`'s patroon-tak (ook net gebouwd) blijft
grotendeels staan maar kan nu de factor-breakdown citeren in plaats van
een generieke "beoordeel de nek/lijn zelf"-tekst.

`web/main.py::_add_signal_context`'s patroon-uitsluiting van de
winrate-lookup wordt vervangen door de nieuwe patroon-specifieke lookup
hierboven — geen dubbele exclusie/inclusie-logica naast elkaar.

## Testen

Geen pytest-suite in dit project (zie CLAUDE.md). Verificatie via
throwaway-scripts tegen een scratch-database:
- `compute_full_confirmation` met een synthetische `Indicators`/`df` die
  een bekende combinatie van factoren oplevert, voor zowel dagtrading
  (regressie: zelfde uitkomst als vóór de refactor) als een patroon-
  richting.
- `pattern_winrate_stats` tegen een scratch-DB met een paar handmatig
  ingevoegde afgeronde patroon-signalen, verifieer het percentage.
- Handmatige Playwright-verificatie van de coin-pagina/`/signalen` voor
  het nieuwe kansberekening-label en de uitgeklapte factor-breakdown.

## Restpunt, geen blokkade voor het plan

`PATTERN_MIN_SAMPLE = 5` is een redelijke eerste waarde, geen harde eis
van de gebruiker — het implementatieplan mag dit bijstellen als een
vergelijkbare bestaande drempel in dit bestand (bijvoorbeeld
`SR_ZONE_MIN_TOUCHES`) een ander getal suggereert. Dit is een parameter-
keuze, geen open architectuurvraag: de rest van dit ontwerp is compleet
genoeg om direct naar een implementatieplan te gaan.
