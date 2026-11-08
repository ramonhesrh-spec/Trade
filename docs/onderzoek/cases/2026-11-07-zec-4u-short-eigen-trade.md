# ZEC 4u: eigen short, goed uitgepakt, model zag hem niet (2026-11-07)

**Bron.**
- Screenshot van de CEO, TradingView, ZECUSDT.P (perp), 4u, telefoonklok 22:15 op 2026-11-07, koers 1.238,21 (−1,77%).
- Trendregel van het script: D omlaag, 4u omhoog "herstel", "Model zoekt short, structuur 4u".
- Nachtexport 2026-11-08 03:17 UTC (`origin/hespulse-data:export/hespulse-2026-11-08.json`, `auto_missers`, `model`).

**Van de CEO nog in te vullen** (staat niet in de screenshot en ik heb het niet geraden):
- Instap, stop, doel, uitstap, tijdstippen, uitkomst in R, ordertype (limiet of market).
- Waarom op dit moment: welk signaal gaf de doorslag.

**Waarneming.**
- Koers 1.238,21, onder het evenwicht van 1.255,75 (discount). Range high 1.390,68.
- De auto-misser vond dezelfde beweging: short, begin 2026-11-07 02:00 UTC op 1.363,84, einde 21:00 UTC op 1.235,21, 9,4% en 4,6 ATR. `seen_by` is leeg: geen enkele motor zag hem.
- Reden per motor:
  - hespulse_model: geen 4u-range met een onaangeraakte pool binnen 6% in deze richting.
  - zone_sweep: de zone had al een setup (ZS_1H).
  - zone_radar: aanbodzone bij het begin, maar geen kaart (al een kaart voor die zone, dagcap of een wachtende kaart).
  - structuur: breuk gezien, maar geen kaart.
  - poc_radar: geen naakte POC bij het beginpunt.
- Eerder die dag nog een short zonder zicht: 6 november 14:00 van 1.387,98 naar 1.261,66 (9,1%), dezelfde modelreden.

**Wat goed ging** (alleen wat de data laat zien, de rest vult de CEO aan):
- De richting klopte met de dag (D omlaag) en met de structuur op 4u. De beweging was 4,6 ATR groot en kwam uit een hoge top na een herstel.
- De trade ligt in dezelfde richting als wat het model wil: short met de dag mee. Het model miste alleen het moment.

**Wat het niet bewijst.**
- Eén gelukte trade bewijst geen voordeel. De auto-misser kijkt achteraf naar elke beweging van minstens 3 ATR en zegt niets over een instap die je vooraf kon kiezen.
- Van de 215 missers sinds de bevriezing (2026-11-03 08:30 UTC) zag het model er 58. Bij 85 was de reden "geen 4u-range met een onaangeraakte pool binnen 6% in deze richting", bij 38 de dagtrend (stille arm tegen de dag), bij 8 de omgekeerde dag, bij 26 staat geen reden. Dat zijn tellingen van bewegingen, geen uitkomsten van trades.

**Terugkijken.**
- Zelfde patroon als NEAR (2026-11-03): een lange daling, de koers staat in discount en de pool in premium ligt buiten 6%. Het model meldt dat niet, eerlijk volgens zijn regels.
- Het patroon komt vaak voor: 85 van de 157 bewegingen die het model niet zag, hebben deze reden.
- Om te kunnen beslissen is een stille meting nodig van de instappen die jij zelf kiest, vooraf vastgelegd (soort, niveau, stop, doel), en pas daarna een besluit. Dat staat op de parkeerlijst.

**Besluit.** Geen regelwijziging; het model is bevroren tot uiterlijk 2026-11-24. CEO (2026-11-03): alle trades bewijzen en opslaan.
