# Bevriezing van het model bewaken

Status: wacht
Laatst bijgewerkt: 2026-11-03

## Doel
Drie weken geen regelwijziging aan de instapregels, zodat de meting schoon blijft.

## Klaar wanneer
- `settings` `model_freeze_at_v2` is verstreken en de meting telt alleen wat daarna ontstond.
- In die periode is geen constante of regel van `app/model.py` veranderd.

## Stappen
- [x] Einddatum van de bevriezing noteren (3 weken na `model_freeze_at_v2`): uiterlijk 2026-11-24, exact tijdstip volgt uit de database
- [ ] Elke week Bewijs lezen: stopregel per punt, `apart`, afwijsredenen
- [ ] Wijzigingsverzoeken naar de parkeerlijst in `NU.md`

## Stand van nu
Bevriezing loopt sinds 2026-11-03 (B-2026-11-03-09, opnieuw gestart met K). Einddatum: 2026-11-03 plus 21 dagen is 2026-11-24. Het exacte tijdstip van `model_freeze_at_v2` staat alleen in de database op de VPS en niet in de repository of in de exports (branch `hespulse-data`). Tot die waarde bekend is, geldt 2026-11-24 aan het einde van de dag als veilige grens.

## Besluiten en bronnen
B-2026-11-03-09 en B-2026-11-03-10 in `docs/onderzoek/besluiten.md`.

## Volgende stap
Op de VPS `SELECT value FROM settings WHERE key='model_freeze_at_v2'` draaien en het exacte tijdstip hier invullen. Daarna de eerste wekelijkse lezing van Bewijs plannen rond 2026-11-10.
