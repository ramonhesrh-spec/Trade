# Bevriezing van het model bewaken

Status: loopt
Laatst bijgewerkt: 2026-11-03

## Doel
Drie weken geen regelwijziging aan de instapregels, zodat de meting schoon blijft.

## Klaar wanneer
- `settings` `model_freeze_at_v2` is verstreken en de meting telt alleen wat daarna ontstond.
- In die periode is geen constante of regel van `app/model.py` veranderd.

## Stappen
- [x] Einddatum van de bevriezing noteren (3 weken na `model_freeze_at_v2`): uiterlijk 2026-11-24, exact tijdstip volgt uit de database
- [x] Controlescript `scripts/bevriezing_check.py` met test `tests/test_bevriezing_check.py` (alleen lezen)
- [ ] Elke week Bewijs lezen: stopregel per punt, `apart`, afwijsredenen
- [ ] Wijzigingsverzoeken naar de parkeerlijst in `NU.md`

## Stand van nu
Bevriezing loopt sinds 2026-11-03 (B-2026-11-03-09, opnieuw gestart met K). Einddatum: 2026-11-03 plus 21 dagen is 2026-11-24. Het exacte tijdstip van `model_freeze_at_v2` staat alleen in de database op de VPS. Tot die waarde bekend is, geldt 2026-11-24 aan het einde van de dag als veilige grens.

Controle van 2026-11-03: `python3 scripts/bevriezing_check.py` (sinds 2026-11-03) toont vier commits op de bewaakte bestanden, allemaal op 2026-11-03:
- 07:22 `c075b15` bevriezing zelf (B-2026-11-03-09), raakt `htf_zones`, `model`, `model_live`, `structure_levels`
- 08:12 `3f5e3b3` instappunt K en herstelde tijd van R, begin van `model_freeze_at_v2` (B-2026-11-03-10)
- 10:10 `f7c03ec` stille arm tegen de dagtrend en afwijsredenen (B-2026-11-03-11)
- 12:15 `55f8052` vier controles M1 tot M4, alleen meting (B-2026-11-03-12)
De laatste twee vallen na de start van de v2-bevriezing en raken `app/model.py` en `app/model_live.py`. Beide hebben een besluit van de CEO. Het script kan niet zien of een commit de instapregels of alleen de meting raakt. Dat oordeel blijft handwerk. Een kale datum telt vanaf 00:00 UTC; trek hem straks naar het exacte tijdstip uit de database.
Let op: de kloon in deze sessie is ondiep, dus een lege lijst bewijst daar niets.

## Besluiten en bronnen
B-2026-11-03-09 en B-2026-11-03-10 in `docs/onderzoek/besluiten.md`.

## Volgende stap
1. Op de VPS `SELECT value FROM settings WHERE key='model_freeze_at_v2'` draaien en het tijdstip hier invullen.
2. Elke week `python3 scripts/bevriezing_check.py --sinds <tijdstip>` draaien. Elke nieuwe commit zonder besluit in `besluiten.md` meteen melden aan de CEO.
3. Eerste wekelijkse lezing van Bewijs rond 2026-11-10.
