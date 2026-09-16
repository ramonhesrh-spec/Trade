# Smart Money Concepts: premium/discount + liquidity sweeps — ontwerp

## Aanleiding

Derde SMC-achtige deelproject na push-meldingen en de BTC-trend-
consistentiefix (commit fbec4e5). Taak #213 in de sessie-todolist. Scope
bewust beperkt tot twee SMC-concepten: premium/discount zones en liquidity
sweeps. Order blocks, fair value gaps en break of structure/change of
character komen niet in dit deelproject — elk vraagt eigen, nieuwe
detectielogica (order blocks: laatste tegengestelde candle voor een
uitbraak; FVG: prijsgat tussen candles; BOS/CHoCH: sequentie-classificatie
van pivots, niet alleen clusteren op prijs zoals de bestaande
pivot-detectie doet). Samen drie keer de omvang van dit deelproject: een
volgend deelproject, niet dit een.

Het nieuws-idee van de gebruiker (een externe gebeurtenis die de prijs
kort uit balans trekt) krijgt geen aparte nieuwsbron of API-integratie —
er is nu geen enkele nieuwsbron in het systeem. Liquidity sweeps dekken
dit al: een sweep rond een nieuwsmoment ziet er technisch precies zo uit
als elke andere sweep, geen aparte detectie nodig.

Beide nieuwe factoren draaien op twee tijdsbestekken (4u en dag), niet
alleen 4u. Product owner: hoe hoger het tijdsbestek, hoe sterker de kans.
De bestaande factorenset kent al dit patroon (Daily-trend/RSI daily naast
de 4u-basisfactoren, elk een eigen, apart tellende factor) — dezelfde
aanpak hier, geen nieuw scoremechanisme nodig.

## Niet-doelen

- Geen order blocks, fair value gaps of break of structure/change of
  character. Zie Aanleiding.
- Geen aparte nieuwsbron/API. Liquidity sweeps dekken het nieuws-idee.
- Geen chart-visualisatie. Premium/discount en liquidity sweeps worden,
  net als Divergentie, Candlepatroon en Liquiditeit nu, niet als laag op
  de candlestick-grafiek getekend — puur een ✓/✗-factor in de uitgebreide
  toetsing. Geen wijziging aan `/api/candles/{symbol}` of `coin.js`.
- Geen database-opslag of migratie. Beide factoren rekenen live op de
  al opgehaalde 4u- en daily-candles, net als de bestaande factoren in
  `compute_advanced_extra_factors`.
- Geen wijziging aan `CONFIRM_THRESHOLD` (blijft 60%) of aan de twee
  bestaande harde eisen (Uitgerektheid, BTC-trend). Vier factoren komen
  erbij, gepoold met de rest.
- Geen extra Binance-aanroep. De daily-candles worden al opgehaald in
  `compute_advanced_extra_factors` voor Daily-trend/RSI daily — beide
  nieuwe daily-factoren hergebruiken diezelfde `daily_df`.
- Geen wijziging aan `swing_levels` of `_find_pivots` zelf. Beide nieuwe
  factoren roepen ze aan zoals ze zijn.

## Sectie 1: Premium/discount (`app/indicators.py`)

Premium/discount zet de entry-prijs af tegen het midden (equilibrium) van
de recente swing-range: onder het midden is discount (goedkoop, sterker
voor long), erboven is premium (duur, sterker voor short). Reuse van
`swing_levels(df, lookback=20)`, die al bestaat voor de stop-plaatsing —
geen nieuwe range-detectie nodig.

```python
def check_premium_discount(
    direction: str, entry_price: float, swing_low: float, swing_high: float,
) -> tuple[str, bool, str]:
    """Ligt de entry in de goedkope (discount) of dure (premium) helft van
    de recente swing-range (swing_levels, dezelfde die ook de stop-
    plaatsing bepaalt)? Long is sterker onder het midden (equilibrium),
    short erboven — de klassieke SMC-knip op 50%, geen marge: een long
    net onder equilibrium is nog altijd relatief goedkoop, een long er
    net boven is dat per definitie niet meer."""
    direction = direction.lower()
    equilibrium = (swing_low + swing_high) / 2
    if swing_high == swing_low:
        return ("Premium/discount", False, "range te vlak om te bepalen")
    if direction == "long":
        ok = entry_price <= equilibrium
        kant = "discount" if ok else "premium"
    else:
        ok = entry_price >= equilibrium
        kant = "premium" if ok else "discount"
    detail = f"entry in {kant}-zone (equilibrium {equilibrium:.4f})"
    return ("Premium/discount", ok, detail)


def check_daily_premium_discount(
    direction: str, entry_price: float, daily_swing_low: float, daily_swing_high: float,
) -> tuple[str, bool, str]:
    """Zelfde check als check_premium_discount, maar op de swing-range van
    de dagcandle in plaats van 4u — een daily premium/discount-zone is een
    sterker signaal, dezelfde reden waarom Daily-trend naast de 4u-
    trendfactor bestaat."""
    direction = direction.lower()
    equilibrium = (daily_swing_low + daily_swing_high) / 2
    if daily_swing_high == daily_swing_low:
        return ("Premium/discount (dag)", False, "range te vlak om te bepalen")
    if direction == "long":
        ok = entry_price <= equilibrium
        kant = "discount" if ok else "premium"
    else:
        ok = entry_price >= equilibrium
        kant = "premium" if ok else "discount"
    detail = f"entry in {kant}-zone op daily (equilibrium {equilibrium:.4f})"
    return ("Premium/discount (dag)", ok, detail)
```

Beide functies zijn bewust bijna identiek in plaats van één functie met
een `label`-parameter — zelfde stijl als `check_1h_trend`/`check_daily_trend`
hiernaast, waar elke tijdshorizon zijn eigen, met de hand leesbare functie
heeft in plaats van een generieke variant met parameters.

## Sectie 2: Liquidity sweeps (`app/indicators.py`)

Een liquidity sweep (stop-hunt) is een candle die met zijn pen (high/low,
niet de close) voorbij een eerdere, bevestigde pivot-low/-high schiet, en
vervolgens terugsluit aan de oorspronkelijke kant. Klassieke interpretatie:
de markt heeft de stop-loss-liquiditeit onder/boven dat niveau opgehaald,
en draait daarna de andere kant op. Reuse van `_find_pivots`, dezelfde
gedeelde pivot-detectie die `detect_sr_zones` en `detect_trendlines` al
gebruiken.

**Nieuwe constante:**

```python
# Hoeveel van de laatste candles gecontroleerd worden op een sweep van een
# eerdere pivot. Kort genoeg om alleen een verse sweep te vangen, niet een
# willekeurige oude pen-doorbraak die allang geen rol meer speelt — zelfde
# soort venster als SR_ZONE_BOUNCE_LOOKBACK, kleiner omdat een sweep per
# definitie een kortstondige gebeurtenis is (één candle, niet een
# meerdaagse terugveer).
LIQUIDITY_SWEEP_RECENT_CANDLES = 3
```

**Nieuwe functies:**

```python
def _find_liquidity_sweep(window: pd.DataFrame, direction: str) -> Optional[Pivot]:
    """Gedeelde kernlogica voor check_liquidity_sweep en
    check_daily_liquidity_sweep: zoekt in `window` een pivot van de
    stop-kant (low voor long, high voor short) die door een van de
    laatste LIQUIDITY_SWEEP_RECENT_CANDLES candles met zijn pen doorbroken
    is, waarna diezelfde candle terugsloot aan de oorspronkelijke kant.
    Geeft de meest recente treffer terug, of None."""
    pivots = _find_pivots(window)
    kind = "low" if direction == "long" else "high"
    cutoff = len(window) - LIQUIDITY_SWEEP_RECENT_CANDLES
    candidates = [p for p in pivots if p.kind == kind and p.index < cutoff]
    if not candidates:
        return None

    recent = window.tail(LIQUIDITY_SWEEP_RECENT_CANDLES)
    for _, candle in recent.iloc[::-1].iterrows():
        for p in candidates:
            if direction == "long":
                swept = candle["low"] < p.price and candle["close"] > p.price
            else:
                swept = candle["high"] > p.price and candle["close"] < p.price
            if swept:
                return p
    return None


def check_liquidity_sweep(direction: str, df: pd.DataFrame) -> tuple[str, bool, str]:
    """Liquidity sweep op de hoofd-timeframe (4u): is er, in de laatste
    LIQUIDITY_SWEEP_RECENT_CANDLES candles, een stop-hunt geweest van een
    eerdere pivot-low (long) of pivot-high (short), gevolgd door een close
    terug aan de goede kant? Andere invalshoek dan check_sr_zone: die kijkt
    naar een bevestigde terugveer over meerdere candles, dit naar één
    scherpe pen-doorbraak-en-terugsluiting."""
    direction = direction.lower()
    window = df.tail(SR_ZONE_LOOKBACK).reset_index(drop=True)
    hit = _find_liquidity_sweep(window, direction)
    if hit is None:
        return ("Liquidity sweep", False, "geen recente stop-hunt gevonden")
    return ("Liquidity sweep", True, f"stop-hunt van {hit.price:.4f}, candle sloot terug aan de goede kant")


def check_daily_liquidity_sweep(direction: str, daily_df: pd.DataFrame) -> tuple[str, bool, str]:
    """Zelfde check als check_liquidity_sweep, maar op de dagcandle — een
    sweep van een daily swing high/low is een sterker signaal, klassieke
    SMC-liquiditeit zit vaak juist op dagniveau (de meest voor de hand
    liggende stop-plek voor de meeste marktdeelnemers)."""
    direction = direction.lower()
    window = daily_df.tail(SR_ZONE_LOOKBACK).reset_index(drop=True)
    hit = _find_liquidity_sweep(window, direction)
    if hit is None:
        return ("Liquidity sweep (dag)", False, "geen recente stop-hunt op daily gevonden")
    return ("Liquidity sweep (dag)", True, f"stop-hunt op daily van {hit.price:.4f}, candle sloot terug aan de goede kant")
```

Bewust een aparte naam (`check_liquidity_sweep`, `Liquidity sweep`) in
plaats van iets met "liquiditeit": `check_liquidity`/"Liquiditeit" bestaat
al voor 24u handelsvolume, een compleet ander concept. Dezelfde
verwarring die `check_liquidity`'s eigen docstring al benoemt.

## Sectie 3: Wiring (`app/signal_processor.py`)

`compute_advanced_extra_factors` berekent `daily_df`/`daily_ind` al voor
Daily-trend/RSI daily (regel 617-624). De vier nieuwe factoren sluiten
aan op de al bestaande blokken, geen nieuwe parameters, geen nieuwe
Binance-aanroep:

```python
    swing_low, swing_high = indicators.swing_levels(df)

    try:
        daily_df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, "1d")
        daily_ind = indicators.compute_indicators(daily_df)
        factors.append(indicators.check_daily_trend(direction, daily_ind))
        factors.append(indicators.check_daily_rsi(direction, daily_ind))
        daily_swing_low, daily_swing_high = indicators.swing_levels(daily_df)
        factors.append(indicators.check_daily_premium_discount(direction, entry_price, daily_swing_low, daily_swing_high))
        factors.append(indicators.check_daily_liquidity_sweep(direction, daily_df))
    except Exception:
        logger.exception("Daily-trend/RSI voor %s kon niet berekend worden", coin)
        factors.append(("Daily-trend", False, "kon niet opgehaald worden, telt als niet bevestigd"))
        factors.append(("RSI daily", False, "kon niet opgehaald worden, telt als niet bevestigd"))
        factors.append(("Premium/discount (dag)", False, "kon niet opgehaald worden, telt als niet bevestigd"))
        factors.append(("Liquidity sweep (dag)", False, "kon niet opgehaald worden, telt als niet bevestigd"))

    ...

    try:
        factors.append(indicators.check_sr_zone(direction, entry_price, atr, zones, df))
    except Exception:
        ...

    try:
        factors.append(indicators.check_premium_discount(direction, entry_price, swing_low, swing_high))
    except Exception:
        logger.exception("Premium/discount voor %s kon niet berekend worden", coin)
        factors.append(("Premium/discount", False, "kon niet berekend worden, telt als niet bevestigd"))

    try:
        factors.append(indicators.check_liquidity_sweep(direction, df))
    except Exception:
        logger.exception("Liquidity sweep voor %s kon niet berekend worden", coin)
        factors.append(("Liquidity sweep", False, "kon niet berekend worden, telt als niet bevestigd"))
```

`swing_low`/`swing_high` zijn al beschikbaar in `process_day_trading_signal`
(regel 694) voor de stop/take-berekening, maar `compute_advanced_extra_factors`
krijgt ze nu niet doorgegeven. Aanpak: `swing_levels(df)` opnieuw aanroepen
binnen `compute_advanced_extra_factors` zelf (zoals hierboven), in plaats
van de functiesignatuur uit te breiden — een pandas-berekening op data die
al in geheugen zit, geen extra kosten, en de signatuur (twee aanroepplekken:
`signal_processor.py` en `web/main.py`'s oefentrade-route) blijft
ongewijzigd.

Fail-closed geldt voor alle vier: lukt de daily-fetch niet, dan tellen
Daily-trend, RSI daily, Premium/discount (dag) én Liquidity sweep (dag)
alle vier als niet bevestigd — consistent met het bestaande patroon voor
de rest van dat blok.

## Sectie 4: Factorentelling en documentatie

Huidige stand (zie `CONFIRM_THRESHOLD`-docstring in `indicators.py`): 17
factoren totaal (5 basis + 12 uitgebreid: 3 vaste + 9 losse in
`compute_advanced_extra_factors`). Na dit deelproject: 21 totaal (5 basis
+ 16 uitgebreid: 3 vaste + 13 losse). De docstrings van
`CONFIRM_THRESHOLD` en `confirms_direction` (die de exacte aantallen
noemen, "17 factoren totaal", "15 overige factoren") moeten mee bijgewerkt
worden naar 21 en 19 — puur documentatie, geen logica-wijziging.

## Sectie 5: UI (`web/templates/uitleg.html`)

Vier nieuwe `factor factor-preview`-blokken, zelfde structuur als de
bestaande (bijvoorbeeld Steun/weerstand, regel 221-227): korte `<h3>` met
de factornaam, `<p>` met een korte uitleg in dezelfde spartaanse toon als
de rest van de pagina. Ook de tekst bij de twee harde eisen ("de andere elf
factoren hieronder", regel 174) moet mee naar "de andere vijftien
factoren hieronder" — dat getal telt alle uitgebreide factoren behalve
BTC-trend zelf.

## Sectie 6: Backtest (`scripts/backtest_factors.py`)

`evaluate_signal` roept nu al `check_daily_trend`/`check_daily_rsi` binnen
het daily-blok (regel 106-113) en `check_sr_zone` binnen het 4u-blok
(regel 75-77). Beide nieuwe paren sluiten daarop aan: `swing_levels(df)`/
`check_premium_discount`/`check_liquidity_sweep` in het 4u-blok,
`swing_levels(daily_df)`/`check_daily_premium_discount`/
`check_daily_liquidity_sweep` in het daily-blok. Zelfde patroon als de
twee bestaande scripts-secties, geen nieuwe historische data-aanroep
nodig (daily_df wordt al opgehaald voor Daily-trend).

## Testen

Zelfde patroon als de vorige twee SDD-plannen (steun/weerstand,
candlestick-patronen): synthetische candle-DataFrames voor de losse
detectorfuncties (`check_premium_discount`, `check_daily_premium_discount`,
`check_liquidity_sweep`/`_find_liquidity_sweep`, `check_daily_liquidity_sweep`),
een pipeline-integratietest voor `compute_advanced_extra_factors` met
gemockte exchange-calls die alle vier nieuwe factoren in de teruggegeven
lijst laat zien, en een handmatige run van `scripts/backtest_factors.py
--limit 10` tegen live data om te zien hoe streng de nieuwe factoren in de
praktijk uitpakken. Geen Playwright nodig — geen chart-wijziging, alleen
tekst in `/uitleg` (visuele check daar is genoeg via een korte
screenshot-vergelijking, geen interactie om te testen).
