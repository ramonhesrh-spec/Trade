# Ordertype vergelijken: limiet, market of stop-order

Status: wacht
Laatst bijgewerkt: 2026-11-03

## Doel
Meten welk ordertype per plan het beste netto R geeft, met dezelfde stop en hetzelfde doel.

## Klaar wanneer
- Het verschil met de limiet staat per instappunt met weekinterval.
- De uitkomst staat in `bewijsregister.md`.

## Stappen
- [ ] `scripts/instap_vergelijking.py --dagen 30` op de VPS draaien
- [ ] Uitvoer delen
- [ ] Besluit noteren in `besluiten.md` (ook bij geen verschil)

## Stand van nu
Script gebouwd en getest. Nog niet op echte data gedraaid.

## Besluiten en bronnen
B-2026-11-03-13, `app/entry_compare.py`, `tests/test_entry_compare.py`.

## Volgende stap
CEO draait het script op de VPS.
