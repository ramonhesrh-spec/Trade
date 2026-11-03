# TradingView-script synchroon houden

Status: wacht (nagelopen 2026-11-03)
Laatst bijgewerkt: 2026-11-03

## Doel
Het Pine-script blijft een eerlijke benadering van de swing-, breuk- en rangeregels van het model.

## Klaar wanneer
- Na elke wijziging aan `app/model.py` of `app/structure_levels.py` staat in dit bestand of het script mee moest.
- `tradingview/README.md` is actueel.

## Stappen
- [x] Bij elke regelwijziging het script nalopen (2026-11-03: swing, breuk, range, OB, EQH/EQL, FVG)
- [x] Verschillen met de app in `tradingview/README.md` noteren (kop "Bekende verschillen")

## Stand van nu
2026-11-03: script nagelopen tegen `app/model.py` en `app/structure_levels.py`. Swing-, breuk-, range-, OB-, EQH/EQL- en FVG-regels zijn gelijk
aan Groot; het script hoefde niet te veranderen. Acht verschillen staan met reden in `tradingview/README.md` onder "Bekende verschillen"
(onder meer: geen 60-candleslimiet op de range, range op elk tijdframe, andere geschiedenis voor de dagrichting). Het model is niet gewijzigd.
`tests/test_tradingview_port.py` draaide niet in deze sessie (module `ta` en `http-ece` niet te bouwen); draai hem op de VPS.

## Besluiten en bronnen
`tradingview/hespulse_structuur.pine`, `tradingview/README.md`.

## Volgende stap
Test `tests/test_tradingview_port.py` draaien op de VPS. Daarna wachten op een regelwijziging (die ligt tijdens de bevriezing stil).
