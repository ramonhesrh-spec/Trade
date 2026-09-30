# Entry-zone structuurbevestiging (LTF) — design

## Aanleiding

Signaal 418 (ETH long, dagtrading) stuurde vanochtend een "terug in de
betere-entry-zone"-melding zodra de live prijs terugkwam binnen
`suggested_entry_low`–`suggested_entry_high`. De gebruiker stapte in dicht
bij de bovenkant van die zone en werd binnen ~20 minuten uitgestopt: de
prijs viel gewoon door de zone heen, zonder ooit te laten zien dat hij er
stand hield.

Ter vergelijking liet de gebruiker een eigen, handmatige BTC-trade zien:
op het 4u-tijdsframe een naderende weerstand herkend, en pas ingestapt
nadat het 3-minuten-tijdsframe een structuurwending ("kanteling") liet
zien als bevestiging. Precies dat ontbreekt in de dagtrading-melding: die
toetst alleen "is de live prijs terug in de zone", niet "houdt de zone
ook stand".

De SMC-detector (`market_scanner.py`) doet dit al wel, op zijn eigen
schaal: een structuurbreuk + sweep op 30m wordt pas een signaal na een
afwijzingscandle op 15m. Dit ontwerp brengt hetzelfde principe naar de
"terug in de betere-entry-zone"-melding voor gewone dagtradingsignalen.

## Scope

Alleen `app/level_check.py`'s `check_pending_signals()`, specifiek de
`in_entry_zone`-tak. Niet aangeraakt:

- Het allereerste dagtradingsignaal zelf (`process_day_trading_signal`
  in `signal_processor.py`) — dat blijft ongewijzigd op het 4u-tijdsframe
  draaien. Alleen de latere herbevestiging bij terugkeer in de zone
  krijgt de nieuwe stap.
- De drie andere situaties in dezelfde functie (sniper-trigger,
  signaalniveau, bron niveau) — die kunnen ongewijzigd blijven afgaan
  terwijl er op de zone-bevestiging gewacht wordt.
- SMC, patroon-, trendlijn- en uitbraak-detectoren — die hebben al hun
  eigen bevestigingsstap of zijn hier buiten scope.

## Bevestigingslogica

Een 15m-candle bevestigt de zone pas als hij de zone raakte (wick of
volledige overlap) ÉN aan de gunstige kant weer sloot:

- long: candle raakt de zone, close > `suggested_entry_high`
- short: candle raakt de zone, close < `suggested_entry_low`

Dit is dezelfde afwijzingslogica als `market_scanner._smc_last_candle_state`
al gebruikt voor SMC-zones, hier toegepast op de bestaande
`suggested_entry_low`/`suggested_entry_high` van een gewoon signaal. Geen
nieuw concept, hergebruik van een al geteste regel.

Nieuwe functie `_entry_zone_rejection_seen(direction, zone_low, zone_high,
candles) -> bool` in `app/level_check.py`: doorloopt `candles` en geeft
`True` zodra één candle aan bovenstaande eis voldoet, anders `False`.

## Terugkijkperiode, geen bijgehouden status

Geen schemawijziging. Elke cyclus waarin de ruwe prijscheck (`current_price`
binnen de zone) klopt, worden de laatste `ENTRY_ZONE_CONFIRM_LOOKBACK_CANDLES`
(8, oftewel 2 uur) 15m-candles voor die coin opgehaald en tegen
`_entry_zone_rejection_seen` getoetst. Geen afwijzing gezien binnen die
2 uur betekent geen melding deze cyclus — geen state om bij te houden,
geen resetregel nodig als de prijs de zone weer verlaat zonder afwijzing:
de eerstvolgende keer dat de prijs terugkomt, wordt gewoon opnieuw de
laatste 2 uur bekeken.

Dit is bewust dezelfde aanpak als de recente stop/take-fix in dit bestand
(`LEVEL_CHECK_CANDLE_TIMEFRAME`/`LEVEL_CHECK_CANDLE_LOOKBACK`): een vaste
terugkijkperiode in plaats van bijgehouden status, voor dezelfde reden
(eenvoud, geen migratie, geen edge cases rond een vergeten reset).

Alleen **gesloten** candles tellen mee, zelfde conventie als de SMC-detector
(`_check_smc_setup`'s eigen why-comment: "de laatste candle van de exchange
is nog in wording, een close-toets halverwege die candle kan voor het
sluiten nog volledig omdraaien"). De laatste, nog vormende candle van de
exchange-respons valt daarom weg voordat `_entry_zone_rejection_seen`
hem te zien krijgt.

Nieuwe constantes:

```python
ENTRY_ZONE_CONFIRM_TIMEFRAME = "15m"
ENTRY_ZONE_CONFIRM_LOOKBACK_CANDLES = 8  # 2 uur, gesloten candles
```

## Wiring in check_pending_signals

Huidige code (ongeveer):

```python
in_entry_zone = (
    entry["suggested_entry_low"] is not None
    and entry["suggested_entry_high"] is not None
    and entry["suggested_entry_low"] <= current_price <= entry["suggested_entry_high"]
)
```

Wordt (ruwe prijscheck blijft de poort, candle-check bepaalt de uiteindelijke
waarde):

```python
raw_in_entry_zone = (
    entry["suggested_entry_low"] is not None
    and entry["suggested_entry_high"] is not None
    and entry["suggested_entry_low"] <= current_price <= entry["suggested_entry_high"]
)
in_entry_zone = False
if raw_in_entry_zone:
    if coin not in coin_entry_zone_candles:
        try:
            df = await asyncio.to_thread(
                exchange.fetch_ohlcv, coin, timeframe=ENTRY_ZONE_CONFIRM_TIMEFRAME,
                limit=ENTRY_ZONE_CONFIRM_LOOKBACK_CANDLES + 1,  # +1: laatste candle is nog vormend
            )
            coin_entry_zone_candles[coin] = df.iloc[:-1]
        except Exception:
            logger.exception("Kon geen candles ophalen voor zone-bevestiging op %s, sla over", coin)
            coin_entry_zone_candles[coin] = None
    candles = coin_entry_zone_candles[coin]
    if candles is not None:
        in_entry_zone = _entry_zone_rejection_seen(
            entry["direction"], entry["suggested_entry_low"], entry["suggested_entry_high"], candles,
        )
```

`coin_entry_zone_candles: dict[str, object]` is een nieuwe cache,
zelfde per-cyclus patroon als de bestaande `coin_prices`/`coin_sniper`/
`coin_directions`-caches in dezelfde functie — één candle-ophaal per coin
per cyclus, niet per journaalregel. De candle-fetch gebeurt alleen als de
ruwe prijscheck al klopt, dus geen extra Binance-aanroepen voor coins die
niet in hun zone staan.

De rest van de functie (sniper-trigger, signaalniveau, bron niveau, de
uiteindelijke "geen van de vier situaties matcht, sla over"-poort, en de
tekst van de melding zelf) blijft ongewijzigd: `in_entry_zone` betekent nu
alleen "bevestigd", niet "prijs staat er toevallig".

## Wat niet verandert

- De tekst van de pushmelding zelf ("Terug in de betere-entry-zone",
  `Betere entry: {low}–{high}`) blijft ongewijzigd — alleen het moment
  waarop hij afgaat verschuift.
- `mark_level_alert_sent` blijft op dezelfde plek staan: één melding per
  journaalregel, zodra de zone bevestigd is.

## Testen

Scratch-database + gemockte `exchange.fetch_ohlcv`, zelfde stijl als de
stop/take-candle-fix:

1. Signaal met prijs terug in de zone, candle-reeks zonder afwijzingsclose
   → geen melding, `level_alert_sent` blijft 0.
2. Zelfde signaal, candle-reeks mét een afwijzingsclose binnen de laatste
   2 uur → melding verstuurd, `level_alert_sent` wordt 1.
3. Controle: een candle die de zone raakt maar aan de verkeerde kant sluit
   (geen afwijzing) → geen melding.
