# Signaalkwaliteit omhoog: meetraam, verbeteringen en nieuwe coins — design

## Aanleiding

Het aantal meldingen is laag, en de meldingen die komen verliezen vaker dan
ze winnen. Cijfers van de VPS (2026-10-04):

- Winrate over alle afgeronde signalen (`scripts/signals_winrate.py`):
  day_trading 23,7% (28 winst, 90 verlies), patroon 32,1%, smc 25,0%
  (8 trades), swing 52,9% (17 afgerond). Totaal 29,4%.
- Stop = laatste 4h swing + 0,25 ATR, take profit = 2x de stopafstand
  (`app/risk.py`). Break-even ligt dus rond 33% zonder kosten, rond 36 tot
  38% met fee en slippage. day_trading, patroon en smc zitten eronder.
- Sinds 1 oktober: 19 bevestigde autonome signalen, 1 take profit, 13 stop
  loss, 5 open (7%). Afgewezen signalen scoorden 33% (5 TP, 10 SL, 19 open),
  een te kleine steekproef om op te sturen
  (`scripts/check_rejected_outcomes.py`).
- Drie bevestigde longs op ETH, BTC en SOL op 2 oktober tussen 14:48 en
  15:27 raakten alle drie de stop: één marktbeweging, drie meldingen.
- Sniper-entry en Stopafstand falen bijna altijd samen (23 van 34
  afwijzingen): de prijs is al weggelopen. Versoepelen helpt niet.
- Vervallen signalen (137 van 273 bij day_trading) tellen nu niet mee in de
  winrate, waardoor de echte verwachting onbekend is.

Doel (gekozen): break-even of beter na kosten, ook bij 2 tot 4 meldingen per
dag. Alle vier de signaaltypes blijven bestaan en worden verbeterd, geen
type gaat uit.

## Niet-doelen

- Geen extra meldingen forceren. Minder meldingen is acceptabel.
- Geen automatische trades. Elke trade blijft een handmatige beslissing.
- Geen foutmelding via Telegram voor API-uitval (bewust afgewezen).
- Discord-signalen van de community zijn niet af te spelen op historische
  data en vallen buiten het meetraam. Ze krijgen dezelfde harde eisen.

## Aanpak: mengvorm in vier fasen

1. **Meetraam bouwen.** Geen invloed op het live systeem.
2. **Testronde** van de verbeteringen in het raam, rapport per type en idee.
   De gebruiker kiest wat live gaat.
3. **Live uitrol, één wijziging per keer**, elk achter een instelling in
   `.env` (terugdraaien = instelling uit + herstart `crypto-bot`). Na elke
   wijziging een week meten.
4. **Nieuwe coins in schaduwmodus** (zie hieronder).

## Deel 1: meetraam

Nieuwe module (werknaam `app/replay.py`) plus een runner in `scripts/`.

- **Data.** 2 jaar candles per coin voor 4h, 1h, 15m en daily via
  `app/exchange.py`, lokaal gecachet in `data/candles/` zodat herhaalde
  runs snel zijn. Respecteer de rate limiter van ccxt.
- **Afspelen.** Candle voor candle door de tijd, alleen op dat moment
  gesloten candles (geen vooruitkijken). Het raam roept dezelfde pure
  functies aan als de live scan (`app/indicators.py`, `app/patterns.py`,
  `app/risk.py`), geen losse kopie van de logica.
- **Uitkomst per signaal.** Stop en take uit `risk.py`. Raken beide dezelfde
  candle, dan telt de stop (zelfde keuze als
  `level_check._level_hit_in_candles`). Vervallen signalen tellen mee,
  gemeten als nul of tegen de slotprijs bij verloop.
- **Kosten.** Instelling, start 0,1% fee plus 0,05% slippage per kant.
  Rapport toont de uitkomst met en zonder kosten.
- **Rapport.** Per type, per coin en per kwartaal: aantal signalen, winrate,
  verwachting in R, langste reeks verliezen.
- **Train en test.** Afstellen op de eerste 70% van de data, toetsen op de
  laatste 30%.
- **Beperking.** De zone-cooldown (`sr_zone_failures`) wordt in het raam
  nagebootst op de gesimuleerde uitkomsten. De pre-checks van
  `market_scanner.scan_market` (cooldown, whiplash-rem, maximum meldingen per
  cyclus) zijn niet af te spelen. Het raam laat ze weg en elk rapport zegt dat.
  Ook niet nagebootst: de regel dat een structureel kandidaat een generiek
  dagtrading-signaal onderdrukt (tot de patroon- en smc-replay bestaan). Live
  ververst een open signaal elke cyclus en overschrijft stop, take en
  bevestiging; het raam bevriest het signaal bij de eerste bevestiging.
- **Opdeling in plannen.** Het eerste plan (`docs/superpowers/plans/2026-10-04-meetraam.md`)
  bouwt de engine voor het type day_trading. Patroon, swing en smc krijgen elk
  een eigen vervolgplan, zodra de engine de controle tegen de live signalen
  doorstaat. Deel 2 (verbeteringen testen) en deel 3 (nieuwe coins) volgen als
  eigen plannen op de resultaten van het raam.

### Controle van het raam

- Speel 1 tot 4 oktober af en vergelijk met de 53 live autonome signalen
  (ids 470 tot 522). Ze moeten grotendeels overeenkomen. Zo niet, dan klopt
  het raam niet en gaat het project niet verder.
- Een test met kunstmatige candles bewijst dat het raam niet vooruit kijkt.
- Geen pytest in dit project. Gebruik wegwerpscripts op een lege database
  (`DATABASE_PATH=... python3 -c ...`), zoals CLAUDE.md voorschrijft.

## Deel 2: verbeteringen die in het raam getest worden

Volgorde van verwachte winst. Elk idee draait apart, daarna samen. Maximaal
drie parameterfamilies tegelijk afstellen (tegen overfitting).

**Groep 1, bescherming tegen gelijke verliezen**
- Maximaal 1 open signaal per richting binnen een korte tijd over alle
  coins heen, of een bovengrens per scancyclus.
- Trendfilter: long alleen bij stijgende daily-trend en BTC niet dalend,
  short omgekeerd. Test als harde en als zachte eis.

**Groep 2, stop en take**
- Stop-buffer: nu 0,25 ATR. Test 0,5, 0,75 en 1,0 ATR.
- Take profit: nu 2R. Test 1,5R, 2R en 2,5R. Test ook de helft sluiten op
  1R met de stop naar instap.
- Tijdstop: sluiten na N candles zonder beweging.

**Groep 3, selectie**
- Per factor meten of hij de kans op winst verhoogt. Factoren zonder effect
  gaan weg of krijgen een lager gewicht.
- Volatiliteit en volume: stille, zijwaartse momenten overslaan
  (ADX-drempel).
- Per coin: BTC en ETH presteren het slechtst bij day_trading. Test aparte
  instellingen voor grote en kleinere coins.

**Succescriterium per type:** verwachting boven +0,1R na kosten op de
laatste 30% van de data, met minstens 100 signalen. Een type dat dit niet
haalt blijft bestaan, maar de gekozen wijziging moet zijn uitkomst
aantoonbaar verbeteren ten opzichte van nu.

## Deel 3: nieuwe coins HBAR, WLD, ONDO en XRP

1. **Eerst het meetraam.** Elke coin draait over zijn beschikbare historie
   (WLD en ONDO hebben een korter venster, het rapport vermeldt dat). WLD en
   XRP verloren eerder in het systeem (day_trading WLD min 5, XRP min 1,
   ONDO 0. Patroon WLD min 5, XRP min 2, ONDO min 1). Een coin die in het
   raam duidelijk negatief scoort, wordt niet toegevoegd.
2. **Schaduwmodus.** Een coin die het raam doorstaat draait twee weken mee
   zonder melding: signalen worden bewaard en gemeten, er komt geen
   Telegram-bericht en geen journaalregel.
3. **Doorstroom.** Na 14 dagen en minstens 15 beslissingen met verwachting
   nul of beter gaat de coin live. Anders blijft hij in schaduw.

Codewijzigingen:

- `app/config.py`: `FIXED_COINS` krijgt vier coins. `app/coinlist.py`:
  `COIN_NAME_ALIASES` krijgt hbar/hedera, wld/worldcoin, ondo, xrp/ripple
  (de assert daar dwingt gelijke sleutels af).
- `app/schema.sql` en `app/db.py:_migrate()`: veld `signals.is_shadow`,
  idempotente `ALTER TABLE ... ADD COLUMN` achter een `PRAGMA table_info`
  check. Geen index in schema.sql voor dit veld, die komt in `_migrate()`.
- `app/repo.py` en de meldingspaden: elke query voor gebruikers sluit
  schaduwsignalen uit, zoals bij oefentrades. Een vergeten query vervuilt
  stil de winrate. Maak vooraf een lijst van alle queries die `signals`
  lezen en test elk met een schaduwsignaal.
- Voor het toevoegen: controleer met `exchange.market_exists` dat de vier
  paren op Binance bestaan.

## Deel 4: uitrol, risico's en controle

Risico's en aanpak:

- **Overfitting:** afstellen op 70%, toetsen op 30%.
- **Te weinig data:** een resultaat telt pas bij minstens 100 signalen per
  type.
- **Korte historie** van WLD en ONDO: kortere venster, vermeld in rapport.
- **Fout in het kostenmodel:** kosten zijn een instelling, rapport toont met
  en zonder kosten.
- **Niet af te spelen eisen:** vermeld per run in het rapport.
- **Schaduwlek:** lijst van queries plus test per query.

Uitrol:

- Per wijziging een instelling in `.env`, standaard uit.
- Na elke live wijziging een week meten met `scripts/signals_winrate.py`,
  uitgebreid met winrate per week en verwachting in R.
- `crypto-bot` en `crypto-web` herstarten na elke deploy, apart (zie
  README).

## Open punten

Geen. Kosten (0,1% fee, 0,05% slippage) en de grens van 100 signalen zijn
beginwaarden en staan als instelling.
