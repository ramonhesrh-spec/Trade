# NEAR 1u en 15m: short in discount, geen scenario (2026-11-03, ongeveer 14:55 UTC)

**Bron.**
- Twee screenshots van de CEO, TradingView, "NEARUSDT Perpetual Swap Contract" (OKX), 1u en 15m, met het HesPulse-script.
- Telefoonklok 14:5x. Het positievak (3,990 boven, 3,821 onder) komt uit ingeplakte niveaus van de CEO. HesPulse had geen plan.
- Vraag van de CEO: waarom geen melding op HesPulse.

**Waarneming.**
- Koers 3,879 (1u) en 3,872 (15m). Top rond 13:15 op 3,937 (RH), daarna terug.
- Trend D omlaag, 4u omlaag, 1u omlaag. Het script meldt "Model zoekt short".
- VPS, 2026-11-03 14:58 UTC (`model_scenarios`, `scripts/model_kaarten.py --coins NEAR --dagen 3`, diagnose met `model.Context4h`, `model.Pools`):
  - Eén NEAR-scenario sinds 2 november, short, range 4,074 tot 4,351, `context_weg` op 2 november 20:00 zonder sweep.
  - Nu: dagrichting short, range 3,742 tot 4,562, evenwicht 4,152, koers 3,885.
  - Het dichtstbijzijnde onaangeraakte swing high op 1u in premium is 4,351, 12% boven de koers. Het evenwicht ligt 6,9% boven de koers.

**Beoordeling.**
- Geen fout in de motor: live, herberekening en diagnose geven hetzelfde. Er is geen scenario omdat geen pool binnen `MAX_DISTANCE_PCT` (6%) in premium ligt (preregistratie §4.13).
- De getekende top van 3,937 ligt in discount van de 4u-range en is vandaag geraakt. Het model ziet hem niet als pool.
- Soort trade: short in een dalende trend na een daling van ongeveer 12% vanaf de range-top, in discount. Het model meldt die soort niet.
- Of dit patroon winst geeft, is niet bekend. Een trade bewijst niets. Uitkomst van de CEO-trade invullen zodra hij sluit.

**Besluit.** Geen regelwijziging; het model is bevroren tot uiterlijk 2026-11-24. Op de parkeerlijst in `docs/taken/NU.md`. CEO (2026-11-03): alle trades bewijzen en opslaan.
