# TradingView-script synchroon houden

Status: actief
Laatst bijgewerkt: 2026-11-08

## Doel
Het Pine-script blijft een eerlijke benadering van de swing-, breuk- en rangeregels van het model.

## Klaar wanneer
- Na elke wijziging aan `app/model.py` of `app/structure_levels.py` staat in dit bestand of het script mee moest.
- `tradingview/README.md` is actueel.

## Stappen
- [x] Bij elke regelwijziging het script nalopen (2026-11-03: swing, breuk, range, OB, EQH/EQL, FVG)
- [x] Verschillen met de app in `tradingview/README.md` noteren (kop "Bekende verschillen")

## Stand van nu
`tradingview/hespulse_clean.pine` is geschreven (Pine v6) en nog niet in TradingView gecompileerd. Erin: structuur zoals Groot, BSL en SSL van 1u en 4u
vanaf de echte pivot-candle, sweepketen L?, S?, L+ en S+ op 15m met de dagfilter. De Python-spiegel van de sweepketen is gelijk aan `app/model.py`
op 60 reeksen, long en short (`tests/test_tradingview_signals.py`). Niet getest: compileren, `request.security` in TradingView, uiterlijk.
Bekend ontbrekend in de signalen: 4u-range (premium en discount), groepering van gelijke pools, doel. Het zijn geen A, B, B0, R of K.
Het oude `hespulse_structuur.pine` blijft de geteste kopie van Groot tot Clean is goedgekeurd.

Eerder (voor `hespulse_structuur.pine`): op 2026-11-03 is het script nagelopen tegen `app/model.py` en `app/structure_levels.py`. Swing-, breuk-, range-, OB-, EQH/EQL- en FVG-regels zijn gelijk
aan Groot; het script hoefde niet te veranderen. Acht verschillen staan met reden in `tradingview/README.md` onder "Bekende verschillen"
(onder meer: geen 60-candleslimiet op de range, range op elk tijdframe, andere geschiedenis voor de dagrichting). Het model is niet gewijzigd.
`tests/test_tradingview_port.py` draaide niet in deze sessie (module `ta` en `http-ece` niet te bouwen); draai hem op de VPS.

## Besluiten en bronnen
`tradingview/hespulse_structuur.pine`, `tradingview/README.md`.

## Volgende stap
CEO plakt `hespulse_clean.pine` in TradingView en meldt compileerfouten en wat hij ziet (BTC, ETH, een altcoin, 15m en 1u). Daarna fixen, dan pas Clean als standaard.
`tests/test_tradingview_port.py` en `tests/test_tradingview_signals.py` slagen (2026-11-08, hier gedraaid).
