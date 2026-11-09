---
name: smoketest
description: Gebruik na een wijziging en vóór een commit of release. Draait de bestaande tests, toont de uitvoer en meldt wat rood is.
---
Draai `python3 -m unittest discover -s tests -t . -v` (met `SKIP_SLOW_TESTS=1` voor de snelle ronde; vóór een release zonder). Toon de samenvatting of de rode regels.
Rood betekent geen commit en geen "klaar". Werk een verwachte uitkomst (golden) nooit stil bij: dat is een besluit van Ramon in `besluiten.md`.
Er is nog geen volledige keten met vaste candles; dat staat als aparte taak in `docs/blueprint.md`. Live-smoketest tegen Binance draait Ramon zelf.
Noteer de uitslag met datum en commit in `docs/onderzoek/bewijsregister.md`.
