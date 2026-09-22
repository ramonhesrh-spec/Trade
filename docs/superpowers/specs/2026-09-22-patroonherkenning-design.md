# Patroonherkenning (Fase 1) — ontwerp

## Doel

HesPulse herkent zelf chart-patronen op de 4-uurs grafiek (dezelfde candles
als de rest van day trading), gebaseerd op het patronenblad van The Next
Move (community-materiaal van de gebruiker), en meldt elk bevestigd
patroon als een eigen signaal op /signalen — met de patroonnaam, en twee
entry-opties: het uitbraakniveau zelf (snel, nog niet teruggetest) en het
retest-niveau (bevestigd, teruggekeerd naar het gebroken niveau).

Nooit een trade zelf plaatsen, net als de rest van HesPulse: alleen een
signaal met entry/stop/take en de reden.

## Waarom dit zo kan (bestaande bouwstenen)

Alle patronen op het blad zijn drie geometrische vormen, en voor alle drie
bestaat de detectie-bouwsteen al in `app/indicators.py`:

1. **Twee schuine lijnen** (wedge, kanaal, driehoek-varianten, pennant) —
   `detect_trendlines` geeft al maximaal twee lijnen terug (steun +
   weerstand), op basis van `_find_pivots`.
2. **Twee horizontale niveaus** (rectangle) — een steun- en een
   weerstandzone samen, al gedekt door `detect_sr_zones`.
3. **Top/bottom-vormen** (double/triple top/bottom, head & shoulders,
   inverse head & shoulders) — al volledig gecodeerd in
   `scripts/research_reversal_patterns.py`
   (`find_double_triple`, `find_head_and_shoulders`, `PatternMatch`),
   alleen nog niet live gekoppeld.

`find_breakout_retest` (horizontale zones) en `find_trendline_breakout_retest`
(schuine lijnen) bestaan al en detecteren precies het "uitbraak, dan
terugtest"-patroon dat de tweede entry-optie wordt.

## Scope Fase 1

- Top/bottom-vormen: double top/bottom, triple top/bottom, head & shoulders,
  inverse head & shoulders.
- Kanaal/wedge/driehoek-familie, afgeleid van `detect_trendlines`'s twee
  lijnen, geclassificeerd op hellingscombinatie:
  - beide lijnen dezelfde richting, ~evenwijdig → rising/descending channel
  - beide lijnen dezelfde richting, convergerend → rising/falling wedge
  - één lijn vlak, andere hellend → ascending/descending triangle
  - beide lijnen tegengesteld, convergerend → symmetrical triangle
  - beide lijnen tegengesteld, divergerend → (bullish/bearish) expanding
    triangle
- Bullish/bearish divergence: laatste twee prijs-pivots (lows voor bullish,
  highs voor bearish) tegen RSI op dezelfde candles.

**Niet in fase 1** (aparte iteratie): flag/pennant — die hebben een
"vlaggenmast"-detectie (een scherpe beweging vlak vóór de consolidatie)
nodig die op de kanaal/wedge-classifier van fase 1 voortbouwt. Rectangle
blijft ook apart: functioneel al gedekt door de bestaande SR-zone-breakout-
melding (`_check_breakout_retest`), geen aparte patroonnaam-melding nodig
tenzij de gebruiker daar later expliciet om vraagt.

## Architectuurbeslissingen (bevestigd met de gebruiker)

1. **Eigen signaaltype**, zoals swing nu: `signals.trade_type = 'patroon'`.
   Geen gepoold percentage (`pass_pct = None`, net als swing), altijd
   `technical_confirmed = 1`, `hard_gates_ok = 1`. Op /signalen: zelfde
   `is-confirmed`-styling en een eigen badge (`PATROON` naast `SWING`,
   zelfde `badge-swing`-stijl of een eigen kleur), plus de patroonnaam
   zelf zichtbaar op de kaart (niet alleen in de "waarom"-popup).
2. **Geen extra harde eisen**: geen R:R-ondergrens, geen dagtrend/
   BTC-trend-gate. Een bevestigd patroon (nek/lijn daadwerkelijk
   doorbroken op closing-prijs, zie hieronder) is zelf de bevestiging,
   consistent met hoe swing nu werkt.
3. **Stop/take op de gemeten beweging van het patroon zelf**, niet de
   ATR-methode:
   - Top/bottom/H&S: target = neckline ∓ (extreme − neckline), exact zoals
     `research_reversal_patterns.py.find_double_triple`/
     `find_head_and_shoulders` al berekent. Stop loss: net voorbij de
     extreme (top/hoofd/dal) van het patroon zelf, plus een kleine marge
     (zelfde soort marge als een swing-stop nu net voorbij het bewaakte
     niveau ligt).
   - Kanaal/wedge/driehoek: target = hoogte van de vorm (verschil tussen de
     twee lijnen bij de meest recente candle) toegepast vanaf het
     uitbraakpunt; stop loss net voorbij de gebroken lijn.
   - Divergence: geen eigen neckline/hoogte — hier blijft de bestaande
     ATR-methode (`risk.compute_stop_take`) de enige zinnige basis, divergence
     is een momentum-signaal, geen prijsvorm met een eigen gemeten doel.
4. **Volgorde**: fase 1 zoals hierboven, flag/pennant in een latere,
   losse iteratie.

## Nieuwe module: `app/patterns.py`

Niet in `indicators.py` (die is al groot en bevat vooral losse-factor-
logica) en niet in `market_scanner.py` (die orkestreert, detecteert niet
zelf). Eén nieuwe, gefocuste module:

- `@dataclass PatternMatch`: `name: str`, `direction: str`, `neckline: float`
  (of lijnwaarde bij wedge/driehoek), `extreme: float`, `target: float`,
  `stop_loss: float`, `confirmed_index: int`, `pattern_kind: str`
  (`"top_bottom" | "hs" | "channel_wedge_triangle" | "divergence"`).
- `find_reversal_patterns(df) -> list[PatternMatch]`: porteert
  `find_double_triple`/`find_head_and_shoulders` uit
  `scripts/research_reversal_patterns.py` (imports die functies, of
  verplaatst ze hierheen en laat het script importeren — voorkeur:
  verplaatsen naar `app/patterns.py`, script wordt dunne CLI-wrapper
  eromheen, zodat er geen logica dubbel bestaat tussen `app/` en `scripts/`).
- `classify_channel_wedge_triangle(trendlines: list[Trendline], df, atr) -> Optional[PatternMatch]`:
  neemt de output van `indicators.detect_trendlines`, classificeert op
  hellingscombinatie (zie Scope hierboven), None als er geen twee bruikbare
  lijnen zijn.
- `find_divergence(df, ind_rsi_series) -> Optional[PatternMatch]`: laatste
  twee lows (bullish) of highs (bearish) uit `_find_pivots` tegen RSI op
  dezelfde candle-indices.
- `find_entry_options(df, match: PatternMatch, atr) -> dict`: geeft
  `{"breakout_level": float, "retest_low": float|None, "retest_high": float|None}`
  terug — breakout_level is `match.neckline`/lijnwaarde zelf, retest_*
  komt van `find_breakout_retest`/`find_trendline_breakout_retest` als die
  al een geldige terugtest zien, anders None (dan toont de kaart alleen de
  uitbraak-optie, retest is er simpelweg nog niet).

## Wiring: `app/market_scanner.py`

Nieuwe functie `_check_chart_patterns(coin, direction, df, ind)`, zelfde
plek/patroon als `_check_breakout_retest`/`_check_trendline_retest`
ernaast, maar in plaats van alleen een pushmelding: bouwt een
`signal_data`-dict (`trade_type: "patroon"`, `pattern_name`, `pass_pct: None`,
`hard_gates_ok: 1`, `technical_confirmed: 1`, `stop_loss`/`take_profit` uit
`find_entry_options`) en roept dezelfde
insert-signaal-plus-journaalregel-plus-push-fanout-logica aan die
`signal_processor.run_swing_check` nu al gebruikt (die fanout-logica wordt
een gedeelde helper, `signal_processor._fanout_confirmed_signal`, zodat
swing en patroon 'm allebei hergebruiken in plaats van de fanout-lus twee
keer uit te schrijven).

Dedup per coin+patroon+richting via een nieuwe `coins.last_pattern_key`-
kolom, zelfde ATR-marge-aanpak als `last_breakout_retest_key`/
`last_trendline_retest_key` nu al gebruiken (voorkomt dat dezelfde,
ongewijzigde vorm elke marktscan-cyclus opnieuw meldt).

## Database

- `signals.pattern_name TEXT` (nullable) — schema.sql `CREATE TABLE IF NOT
  EXISTS` + idempotente `ALTER TABLE` in `db.py:_migrate()`.
- `coins.last_pattern_key TEXT` (nullable) — zelfde tweeledige aanpak.

## UI

- `web/templates/_macros.html` `signal_card`: naast de bestaande
  `swing`-badge een `patroon`-badge (`entry.trade_type == "patroon"`),
  tekst = `entry.pattern_name` zelf (bijv. "HEAD & SHOULDERS") in plaats
  van het generieke woord "swing" — de patroonnaam IS de badge, dat is
  precies wat de gebruiker wil zien.
- Entry-regel: naast de bestaande `Entry`/`Stop`/`Take profit`-regel een
  nieuwe `signal-card-entry-zone`-achtige regel met twee entry-opties:
  "Uitbraak: X" en, als aanwezig, "Retest: Y–Z" (zelfde stijl als de
  bestaande "Mogelijke betere entry"-regel, maar nu met twee expliciete
  labels in plaats van één range).
- `reason_popup`: patroon-uitleg (welke pivots, neckline, target-berekening)
  in plaats van de swing-tekst "Twee losse toetsen, geen gecombineerd
  cijfer" — eigen variant voor `trade_type == "patroon"`.

## Telegram

Eigen berichtformaat in `app/telegram_notify.py`, patroonnaam in de titel
(zelfde patroon als de swing-titel `"... swing-kans"` nu al doet, hier
`"... {pattern_name}"`), en de twee entry-opties in de body.

## Validatie

`scripts/research_reversal_patterns.py` blijft bestaan (wordt een dunne
wrapper om `app/patterns.find_reversal_patterns` + de bestaande
outcome-classificatie) en krijgt een tegenhanger voor de nieuwe
kanaal/wedge/driehoek- en divergence-detectie, zodat de win/target-rate
van deze nieuwe patronen ook eerst op historische data gemeten kan worden
vóór ze standaard aanstaan — zelfde bewijslast-aanpak als
`backtest_factors.py`/`backtest_hard_gates.py` eerder dit project. Geen
ENABLE_PATTERN_DETECTION-vlag nodig zolang de validatie geen zorgwekkend
resultaat laat zien; wel een korte historische steekproef vóór live-deploy,
zelfde stap als bij de eerdere kritischer-plan-uitrol.
