# Verbeterlus en schaduwvarianten

Status: wacht
Laatst bijgewerkt: 2026-11-03 (sessie schaduw-invoer)

## Doel
De nachtexport en de wekelijkse sessie houden de oude soorten en schaduwvarianten eerlijk bij.

## Klaar wanneer
- Nachtexport draait elke nacht (03:17 UTC) en is niet ouder dan twee dagen.
- Schaduwvarianten volgen `shadow.verdict`, nooit een handmatige promotie.

## Stappen
- [ ] Wekelijks `docs/verbeterlus.md` volgen
- [x] Export controleren (hartslag niet gecontroleerd)
- [x] Schaduwuitkomsten lezen

## Stand van nu
Export: `export/hespulse-2026-11-03.json` op tak `hespulse-data`, gemaakt 2026-11-03 03:17 UTC. Gelezen op 2026-11-03 14:41 UTC, dus 11 uur oud (grens twee dagen): in orde. De vorige export (2026-11-02) staat er ook.

Schaduw (`export["schaduw"]`), beide aangemaakt 2026-11-02 09:05 UTC, status `schaduw`, verdict `wachten`:

| Variant | Soort | n variant | n hoofd | Verdict |
|---|---|---|---|---|
| structuur-stop-0.5 | structuur | 0 | 0 | wachten (minimum 50 per arm) |
| zone-radar-stop-0.5 | zone_radar | 0 | 0 | wachten (minimum 50 per arm) |

Vraag: heeft de schaduwlus nog invoer nu alleen het model meldt?

Antwoord: nee, voor de twee soorten met een schaduw niet.

Onderbouwing:
- `focus.engine_on` geeft `False` voor elke soort behalve het model zodra `MODEL_ONLY_ALERTS` aan staat. Structuur (`structure_live.py:505`), zone-radar (`zone_radar_live.py:165`), zone-sweep (`zone_sweep_live.py:109`) en POC-radar (`poc_radar_live.py:175`) stoppen dan vóór `shadow_live.observe`. Er komen geen nieuwe kaarten en dus geen nieuwe schaduwwaarnemingen. `shadow_live.track` blijft draaien, maar volgt alleen wat al open staat.
- Export, `signalen` (423 rijen), laatste aanmaakdatum per soort: structuur 2026-10-30, zone_radar 2026-11-01, zone_sweep en poc_radar 2026-11-02. Op 2026-11-02 telt de export 0 nieuwe structuur- en 0 zone_radar-signalen, 18 zone_sweep en 7 poc_radar.
- Sinds de aanmaak van beide varianten (2026-11-02 09:05 UTC) staan er in de export 0 afgeronde structuur- of zone_radar-signalen. Er staan 14 afgeronde (9 zone_sweep, 5 poc_radar), allemaal stop_loss. Voor die twee soorten bestaat geen schaduw.
- Het verschil met de 7d-telling (structuur 202 kaarten, 21 afgerond; zone_radar 140 kaarten, 66 afgerond) komt uit de dagen vóór het besluit van 2026-11-02. Die tellen niet als nieuwe invoer.
- Minimum voor een verdict is 50 afgeronde trades per arm. Beide armen staan op 0 en krijgen er geen bij, behalve wat nog open stond. Het aantal open `shadow_results` staat niet in de export; dat weet alleen de database.

Gevolg: beide varianten bereiken `MIN_TRADES` niet zolang `MODEL_ONLY_ALERTS=true`. De schaduwlus meet de oude soorten niet meer. Er is geen nieuwe variant gestart en geen motorconstante gewijzigd.

## Besluiten en bronnen
`docs/verbeterlus.md`, `app/shadow.py`, `scripts/nacht_export.py`.

## Volgende stap
De CEO beslist: (a) de twee varianten laten staan als dood register, (b) de schaduwlus naar het model verplaatsen, of (c) `observe` ook laten draaien onder model-only. Geen van de drie is zonder besluit uitgevoerd. Open `shadow_results` tellen via de database.
