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
