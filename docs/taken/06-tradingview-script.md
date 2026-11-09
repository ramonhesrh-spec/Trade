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
Clean 4 (`tradingview/hespulse_clean.pine`, 2026-11-09) is geschreven en nog niet in TradingView gecompileerd. De versie ervoor draaide op ZEC en WLD
(4H en 15m) en gaf de feedback die erin is verwerkt: L? en S? standaard uit, geen ballen, namen bij het begin van de lijn, trendregel linksonder.
Motor: structuur zoals Groot, 1u- en 4u-pools, sweepketen getest tegen `app/model.py` (`tests/test_tradingview_signals.py`, 60 reeksen, long en
short). De versie "Clean 3.2" uit de sessie "TradingView script" is gelezen: de opmaak is overgenomen, de eigen regels niet (zie README, kop Clean 4).
Bekend ontbrekend in de signalen: 4u-range (premium en discount), groepering van gelijke pools, doel. L+ en S+ zijn geen A, B, B0, R of K.
Niet getest: compileren van Clean 4, `request.security` zonder herschrijven, `chart.left_visible_bar_time`, de samengevoegde namen op een telefoon.

## Besluiten en bronnen
`tradingview/hespulse_structuur.pine`, `tradingview/README.md`.

## Volgende stap
CEO plakt Clean 4 in een nieuw indicator-script, meldt compileerfouten met regelnummer en stuurt een schermafdruk (WLD 4H en 15m). Daarna fixen. Daarna de repaint-test op 15m (een 15m-sluiting en Bar Replay) en BTC, ETH en een altcoin.
