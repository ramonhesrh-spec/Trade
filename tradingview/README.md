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

## Bekende verschillen

Nagelopen op 2026-11-03 tegen `app/model.py` (`_pivot_flags`, `breaks`, `Context4h`, `DailyBias`) en `app/structure_levels.py` (`levels`,
`open_fvgs`). De swingregel (strikt links, gelijk of lager rechts, 3 candles op 1u, anders 2), de breukregel (slot voorbij de laatste
herkenbare, nog niet gebroken swing; een breuk verbruikt elke gepasseerde swing; BOS, CHoCH, MSB), de range (laagste low tussen top en
breuk, hoogste high sinds de top), de opgerekte range top-down, het order block, EQH/EQL binnen 0,1 ATR en de open FVG zijn gelijk aan
Groot. Deze verschillen blijven:

- Geen limiet van 60 candles op de range. Het model laat een 4u-range na `BIAS_MAX_BARS` (60 candles van 4u) vervallen. Groot en het
  script tekenen de laatste breuk hoe oud ook. Reden: Groot toont de structuur zoals een analist, niet het moment waarop het model zoekt.
- Elk tijdframe krijgt een range. Het model bouwt de range alleen op 4u (`Context4h`). Groot en het script doen het op 15m, 1u, 4u, 12u en
  D. Reden: Groot is een kaart per tijdframe.
- Zonder dagbreuk geen filter. Het model zoekt dan geen scenario. Groot en het script tekenen de laatste breuk in welke richting ook, en
  melden "Nog geen dagbreuk". Op de dag zelf (D) volgt de tekening ook geen richting van boven. Reden: er is geen richting om te volgen.
- Een slot door de verre rand van de range zonder dagrichting (op D) laat de range staan. Het model laat zonder top-down de range
  vervallen en rekt hem top-down op. Reden: Groot rekt alleen op als de dag een richting geeft, zoals in `levels(bias=)`.
- Andere geschiedenis voor de richting van de dag en de trendregel. De app rekent op de candles die hij ophaalt (`DAY_LIMIT` voor de dag).
  Het script rekent op alle candles die TradingView voor dat tijdframe geladen heeft, met hoogstens 400 open swings per kant. De laatste
  richting valt meestal samen. Ligt de laatste breuk ver terug, dan kan een andere beginhistorie een andere gebroken swing geven. Reden:
  `request.security` kent geen vast venster.
- Een tijdframe onder dat van je grafiek krijgt een streepje in de trendregel. De app toont daar wel een richting. Reden: TradingView geeft
  op een hoger tijdframe geen betrouwbare candles van een lager tijdframe.
- Op een tijdframe buiten 15m, 1u, 4u, 12u en D (bijvoorbeeld 5m) gebruikt het script 2 candles per swing. De app kent die tijdframes niet.
- De vlakken premium en discount staan niet in het script. Groot slaat ze ook over (`levelchart.js`); alleen de EQ-lijn staat erop.
- Candles komen van TradingView. Kleine verschillen met de candles van de app (een gemiste of herziene candle) kunnen een swing
  verschuiven. De tekening is dan een benadering.

## De kleuren van de app instellen

Rechtsklik op de grafiek, kies Settings.
- Symbol: Body omhoog #FFFFFF, omlaag #1B2324; Borders en Wick allebei #1B2324.
- Canvas: Background Solid #FFFFFF; Vert grid lines uit; Horz grid lines #0D1415 op 6% dekking; Scales text #3E4A4C.
- Onderaan: Template, Save as, "HesPulse".
Stop is #C42F3D, doel #0F7A45, lijnen #8A9698.
