# Verbeterlus en schaduwvarianten

Status: wacht
Laatst bijgewerkt: 2026-11-03

## Doel
De nachtexport en de wekelijkse sessie houden de oude soorten en schaduwvarianten eerlijk bij.

## Klaar wanneer
- Nachtexport draait elke nacht (03:17 UTC) en is niet ouder dan twee dagen.
- Schaduwvarianten volgen `shadow.verdict`, nooit een handmatige promotie.

## Stappen
- [ ] Wekelijks `docs/verbeterlus.md` volgen
- [ ] Export en hartslag controleren
- [ ] Schaduwuitkomsten lezen

## Stand van nu
Loopt. De oude soorten melden niet meer (MODEL_ONLY_ALERTS), dus de schaduw heeft weinig nieuwe invoer.

## Besluiten en bronnen
`docs/verbeterlus.md`, `app/shadow.py`, `scripts/nacht_export.py`.

## Volgende stap
Nagaan of de schaduwlus bij een model-only opzet nog zin heeft.
