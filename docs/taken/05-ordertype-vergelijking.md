# Ordertype vergelijken: limiet, market of stop-order

Status: wacht
Laatst bijgewerkt: 2026-11-03

## Doel
Meten welk ordertype per plan het beste netto R geeft, met dezelfde stop en hetzelfde doel.

## Klaar wanneer
- Het verschil met de limiet staat per instappunt met weekinterval.
- De uitkomst staat in `bewijsregister.md`.

## Stappen
- [x] Tests draaien: `python3 -m unittest tests.test_entry_compare -v`, 9 van 9 geslaagd (2026-11-03)
- [ ] CEO draait het commando hieronder op de VPS
- [ ] CEO plakt de volledige uitvoer in de sessie
- [ ] Samenvatting maken en besluit noteren in `besluiten.md` (ook bij geen verschil)
- [ ] Uitkomst in `bewijsregister.md`

## Commando voor de CEO
Op de VPS, in de map van de repository:

```bash
cd /pad/naar/trade && git pull && .venv/bin/python3 scripts/instap_vergelijking.py --dagen 30 > /tmp/instap.txt 2> /tmp/instap.log; cat /tmp/instap.log /tmp/instap.txt
```

Plak alles wat verschijnt: de regels per coin (stderr) en de tabel. Het script leest alleen. Het schrijft niets in de database en stuurt geen melding. Het haalt candles van de beurs op, dus een run duurt enkele minuten.

## Uitvoer lezen
- Eerst de stderr-regels: `COIN: n plannen`. Staat er `overgeslagen`, dan ontbreekt die coin in de tabel.
- Kop: aantal plannen, coins, dagen en de kosten per rondreis.
- Kolommen: `punt` (A, B, B0, R, K of alle), `type` (limiet, market, stop), `plannen`, `gevuld`, `af` (afgerond op stop of doel), `winst` (aandeel afgerond met netto winst), `R/trade` (gemiddelde netto R per afgeronde trade), `R/plan` (gemiddelde netto R per plan; een plan zonder vulling telt als 0).
- `verschil met limiet`: market of stop min de limiet, per plan, met het weekinterval van 98,75%. Alleen een interval dat helemaal boven 0 ligt, telt als beter. Ligt 0 in het interval, dan is er geen verschil aangetoond.
- Vergelijk `R/plan`, niet `R/trade`: market en stop vullen vaker, de limiet vult selectiever.
- Alle drie dragen dezelfde kosten. Market en stop kosten in werkelijkheid meer, dus de uitkomst bevoordeelt die twee.
- Zes rijen en drie typen zijn veel vergelijkingen. Eén interval net boven 0 is geen bewijs. Kijk ook naar `alle`.
- Dit is een terugblik op de regels van nu, geen live meting. Er wijzigt geen motorregel.

## Stand van nu
Script gebouwd. Tests geslaagd (9 van 9). Wacht op de uitvoer van de CEO van de VPS; er is geen toegang tot de VPS.

## Besluiten en bronnen
B-2026-11-03-13, `app/entry_compare.py`, `tests/test_entry_compare.py`.

## Volgende stap
CEO draait het script op de VPS.
