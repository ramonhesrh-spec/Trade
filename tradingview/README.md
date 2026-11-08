# HesPulse in TradingView

`hespulse_structuur.pine` tekent op je TradingView-grafiek wat "Groot" in de app tekent, op het tijdframe van je grafiek: dezelfde laatste 499
gesloten candles, dezelfde regels. `tests/test_tradingview_port.py` toetst een Python-versie in precies de stappen van het script tegen de
echte code van Groot.

## Zo zet je hem erop

1. Open TradingView en kies de perp van Binance, bijvoorbeeld `BINANCE:SOLUSDT.P`. De app rekent op die candles.
2. Open onderin de Pine Editor, wis wat er staat en plak de hele inhoud van `hespulse_structuur.pine`.
3. Klik op "Save" en dan op "Add to chart".
4. Rechtsboven staat de trendregel. Bij de instellingen (tandwiel) zet je lagen aan of uit.

## Wat hij tekent

- De richting van de dag, en welke kant het model zoekt.
- Per tijdframe zoals Groot: de laatste breuk in de richting van de dag (BOS, CHoCH of MSB), range high (RH), range low (RL), evenwicht
  (EQ), de laatste swing high en low (SH, SL) of gelijke toppen en bodems (EQH, EQL), het order block (OB) en de dichtste open FVG boven en
  onder de koers.
- De trend per tijdframe: D, 4u, 1u en 15m, met "herstel" als een breuk tegen de dag in ging. Een tijdframe onder dat van je grafiek krijgt
  een streepje.
- Het positievak: plak limiet, stop en doel uit de melding bij "Plan uit HesPulse".

## Wat hij niet doet

- Hij kent de plannen van het model niet. TradingView laat geen andere app lijnen op je grafiek zetten.
- Hij meldt niets. De melding komt uit de app.
- Pools, sweeps en de instappunten A, B, B0, R en K staan er niet in. Die staan op de kaart en op Groot.

Regels: `app/model.py` (swings, breuken, `Context4h` top-down, `DailyBias`) en `app/structure_levels.py` (FVG). Verandert daar een regel, dan
moet dit script mee.

## De kleuren van de app instellen

Rechtsklik op de grafiek, kies Settings.
- Symbol: Body omhoog #FFFFFF, omlaag #1B2324; Borders en Wick allebei #1B2324.
- Canvas: Background Solid #FFFFFF; Vert grid lines uit; Horz grid lines #0D1415 op 6% dekking; Scales text #3E4A4C.
- Onderaan: Template, Save as, "HesPulse".
Stop is #C42F3D, doel #0F7A45, lijnen #8A9698.

## HesPulse Clean (nieuw, `hespulse_clean.pine`)

Opvolger van `hespulse_structuur.pine`: dezelfde structuur als Groot, plus de liquiditeit van 1u en 4u en de sweep-aanduidingen. **Nog niet in
TradingView gecompileerd.** Plak hem in de Pine Editor, kijk of hij zonder fout op je grafiek komt en meld wat je ziet. Tot dan blijft het
oude script de geteste kopie van Groot.

Wat erbij kwam:
- **BSL en SSL van 1u en 4u** (`1u BSL`, `4u SSL`, `4u EQH`): de dichtstbijzijnde onaangeroerde swing high en low van gesloten candles, een pool
  is hoogstens 120 candles oud en vervalt bij de eerste aanraking van een latere candle (`Pools._touch`). De lijn begint bij de echte
  pivot-candle (tijd van het hogere tijdframe, `xloc.bar_time`). Een niveau van 1u binnen 0,1 ATR van dat van 4u blijft weg. Op een grafiek
  boven 4u of 1u verschijnt dat tijdframe niet.
- **L? en S?** (alleen op 15m): sweep van het model (4.8): prik minstens 0,1 en hoogstens 2,5 ATR door een onaangeroerde 1u-pool, slot terug
  binnen 6 candles van 15m. Een pool geeft hoogstens één sweep: elke aanraking, ook een ondiepe, verbruikt hem.
- **L+ en S+** (alleen op 15m): dezelfde keten tot en met shift (slot boven de laatste 15m-top vóór de prik, binnen 24 candles), displacement
  (1,0 ATR, 5 candles) en een ongevulde FVG (4.9 tot 4.11). Het signaal komt op de candle waar de keten sluit, nooit terug op de sweep.
- Alleen met de dagrichting: L? en L+ bij dag long, S? en S+ bij dag short.
- Labels vallen niet over elkaar (samengevoegd tot één regel), alle instellingen zijn `display.none`, SH of SL die samenvalt met RH of RL
  blijft weg, en de range rekt top-down op zoals Groot.

Wat er **niet** in zit en waarom de signalen geen modelplan zijn: de 4u-range (premium en discount), de groepering van gelijke pools tot één
pool, het doel en de BTC-poort. L+ is dus vaker dan een entry van het model. Het zijn geen A, B, B0, R of K. Experimenteel, niet getest op
winst, niet voor beslissingen over een trade zonder de kaart in de app.

Wat getest is: `tests/test_tradingview_signals.py` houdt een Python-versie van `f_sig` en `f_disp` bij en eist dat die op 60 willekeurige
reeksen, long en short, dezelfde sweep- en displacement-candles geeft als `_Run._step` van het model, bij dezelfde pools. Niet getest:
compileren, de HTF-aanroepen (`request.security`) in TradingView en het uiterlijk. De ATR rekent dezelfde Wilder-recursie, maar over de candles
die TradingView laadt, dus de eerste honderd candles kunnen een tik afwijken. De dagrichting en de pools komen uit `request.security` met de
vorige gesloten candle (`[1]` en `lookahead_on`); of die in TradingView niet herschrijven, moet je op een lopende candle bekijken.
