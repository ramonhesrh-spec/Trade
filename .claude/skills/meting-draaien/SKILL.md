---
name: meting-draaien
description: Gebruik na een wijziging in regels of vaste waarden. Draait tests en meetinstrumenten en vergelijkt met de vorige uitkomst.
---
Draai eerst `smoketest`. Draai daarna het meetinstrument dat bij de wijziging hoort (bijvoorbeeld `scripts/backtest_factors.py`, `scripts/model_kaarten.py`,
`app/model_measure.py` via de nachtexport) en zet de uitkomst naast de vorige in `docs/onderzoek/bewijsregister.md` met het commando. Zwaar meetwerk draait Ramon zelf op de VPS;
vraag hem alleen de uitslag of de rode regel te plakken. Stel nooit een regel af op deze uitkomst.
