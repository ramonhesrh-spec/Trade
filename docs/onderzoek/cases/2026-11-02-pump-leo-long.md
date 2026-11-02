# PUMP 4u: long na het uitnemen van liquiditeit, en wel of geen bevestiging (Leo, 2026-11-02 20:02–20:07)

**Bron.**
- WhatsApp-tekst van Leo, doorgestuurd door de CEO.
- Vijf RAGAZZI-grafieken van 20:02 tot 20:06 UTC+1, Pump.fun 4u lijngrafiek ("CRYPTO"-index).
- Ontbreekt: de beurs en het contract, de gesloten candles, en of Leo de maker van RAGAZZI is.

**Waarneming.** Prijzen afgelezen.
- Koers ongeveer 0,00394–0,00397.
- Een rode lijn rond 0,00418, een grijze zone rond 0,00424 en "Recent High" rond 0,00465.
- "Recent Low (1)" en een gestippelde "liqiditeit" rond 0,00378, met een omcirkelde bodem van 24 september. "External Low" rond 0,00345,
  "External High" rond 0,00655, en een BOS in augustus rond 0,00532.
- Getekende route: eerst onder 0,00378 (de liquiditeit uitnemen), dan terug boven 0,00418–0,00424, terugtest, en omhoog richting 0,005.
- Getekende long (20:06): instap ongeveer 0,00394–0,00397, stop 0,0029877, doel 0,0058604. Dat is ongeveer 2R.
- Tekst:
  - "ik wacht liever op de conformatie, de trend wissel om long te gaan";
  - "je zit in premium maar je hebt nog geen liquiditeit uitgenomen";
  - "geen conformatie maar als die liquiditeit het niet houdt gaat hij sowieso lager";
  - "je zit nu in extreme".

**Wat dit is in HesPulse-termen.** Twee bestaande instappunten:
- **Met bevestiging** = A (na sweep): de liquiditeit onder 0,00378 wordt geprikt, de koers sluit terug, er volgt een breuk omhoog op 15m
  met displacement, en de limiet ligt op de gap. Leo's "trendwissel" is die breuk (CHoCH).
- **Zonder bevestiging** = V1 (vroege limiet op de pool) of P (POC-limiet): instappen op of vlak boven de liquiditeit, met een stop eronder.

**Conflict met de top-down-regel van vandaag (B-2026-11-03-02).** Zolang de dag omlaag wijst, geeft het model op PUMP geen long, ook niet
na een sweep met bevestiging. Leo's long is een omkeertrade: hij gokt op een trendwissel. In het model komt die long pas als de
richting omslaat, en dat gebeurt op de dag pas laat.

**Niet doen.** Meteen een uitzondering bouwen voor "long na sweep van grote liquiditeit tegen de dag in". Dat is de herstel-long uit de
goudcase (`cases/2026-11-02-goud.md`) en blijft een aparte hypothese. De uitkomst van deze ene PUMP-long bewijst daarover niets.
