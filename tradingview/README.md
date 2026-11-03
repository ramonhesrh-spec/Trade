# HesPulse in TradingView

`hespulse_structuur.pine` tekent de structuur van het HesPulse-model op je eigen TradingView-grafiek. Het is een benadering: dezelfde vaste
regels, opnieuw geschreven in Pine. De app blijft de bron; wijkt iets af, dan geldt wat de app zegt.

## Zo zet je hem erop

1. Open TradingView en kies de perp van Binance, bijvoorbeeld `BINANCE:SOLUSDT.P`. De app rekent op die candles.
2. Open onderin de Pine Editor, wis wat er staat en plak de hele inhoud van `hespulse_structuur.pine`.
3. Klik op "Save" en dan op "Add to chart".
4. Rechtsboven staat de trendregel. Bij de instellingen (tandwiel) zet je lagen aan of uit.

## Wat hij tekent

- De richting van de dag, en welke kant het model zoekt.
- De 4u-range top-down: range high, range low, evenwicht 0,5, premium en discount.
- De trend per tijdframe: D, 4u, 1u en 15m, met "herstel" als de 4u tegen de dag in brak.
- BOS en CHoCH, en de dichtste open FVG boven en onder de koers, op het tijdframe van je grafiek.
- Het positievak: plak limiet, stop en doel uit de melding bij "Plan uit HesPulse".

## Wat hij niet doet

- Hij kent de plannen van het model niet. TradingView laat geen andere app lijnen op je grafiek zetten.
- Hij meldt niets. De melding komt uit de app.
- Pools, sweeps en de instappunten A, B, B0, R en K staan er niet in. Die staan op de kaart en op Groot.

Regels: `app/model.py` (swings, breuken, `Context4h` top-down, `DailyBias`) en `app/structure_levels.py` (FVG). Verandert daar een regel, dan
moet dit script mee.
