# ADA 15m: eigen short, stop geraakt door een prik boven de 4u-top (2026-11-09, 16:50)

**Bron.**
- Screenshot van de CEO, TradingView, ADAUSDT.P (perp), 15m, telefoonklok 16:50, koers 0,1825 (+4,23%).
- Niveaus afgelezen uit de positievakken en de prijsas (geijkt op de assen: 0,1840 en 0,1780). Een afleesfout van enkele punten in de vierde decimaal is mogelijk. De CEO bevestigt de getallen.

**Waarneming.**
- Positievak (short): instap 0,1812, stop 0,1823, doel 0,1747 (RL · BOS). Stopafstand 0,0011 (0,61%), doel 0,0065, gepland 5,9R.
- De stop ligt precies op het niveau van 4u BSL en SH · RH (0,1823), dus op de pool zelf.
- Koers: V-vormige stijging van ongeveer 0,1715 naar een lont tot rond 0,1853, nu 0,1825. Geen lagere top onderweg. RSI boven 80.
- Trendregel: D omlaag, 4u omlaag, 1u omhoog "herstel", 15m omhoog "herstel". "Tussen 4u SSL en BSL: 113%, premium": de koers staat boven de 4u-top.
- Laatste 15m-breuk is omhoog (BOS bij RL). Geen 15m-breuk omlaag, geen displacement, geen slot terug onder 0,1823.

**Beoordeling** (wat de grafiek laat zien, geen bewijs):
- De stop lag op de pool. Een prik boven die top haalt hem er automatisch uit. De regel van het model zet de stop voorbij het uiterste van de sweep plus 0,25 ATR (`model.STOP_ATR`), met een vloer van 0,4%. Hier was er nog geen sweep om voorbij te staan.
- De instap kwam vóór de stappen van het model: geen slot terug onder de pool, geen shift, geen displacement. Dat is de "conformatie" waar Leo bij WLD op wees.
- De lagere tijdframes keerden tegen de dag in en de impuls was sterk. Tegen een impuls zonder lagere top is een limiet in het midden van die impuls het zwakste moment.
- Een stop voorbij de lont (rond 0,1853 plus een buffer) had het risico van 0,0011 naar ongeveer 0,0045 gebracht. Het geplande R:R was dan ongeveer 1,4 en niet 5,9. Het lage risico van 0,61% maakte het getal mooi en de trade kwetsbaar.

**Open.**
- Of de koers daarna alsnog naar 0,1747 ging, weet ik niet: de grafiek stopt om 16:50.
- Instap als limiet of market, exacte vulling, sluittijd en uitkomst in R: door de CEO in te vullen.

**Besluit.** Geen regelwijziging. Alle trades bewijzen en opslaan (CEO, 2026-11-03).
