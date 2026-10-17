# Range sweep: VPS-protocol (poort 0 tot en met 3)

De sandbox heeft geen toegang tot Binance. Alle runs met echte candles draai jij op de VPS. Voer de stappen in deze volgorde uit en ga pas naar de volgende stap als de poort van de vorige gehaald is. Alles hieronder is copy-paste; de map is die uit `README.md`.

```bash
ssh <jouw-vps>
cd /opt/crypto-alerts
tmux new -s rangesweep        # of: screen -S rangesweep. Terug na een verbroken verbinding: tmux attach -t rangesweep
```

Draai de lange stappen (4 en 5) altijd binnen `tmux` of `screen`: een verbroken SSH-verbinding stopt de run dan niet.

## 1. Code binnenhalen

```bash
git pull && .venv/bin/pip install -r requirements.txt
```

Controle: `git log --oneline -1` toont de nieuwste commit van de branch. Het labscript schrijft niets in de database zonder `--opslaan`, dus dit is veilig.

## 2. Poort 0a: de misser-controle op jouw voorbeelden

De voorbeelden staan in `docs/onderzoek/range-sweep/handtrades.csv`. Eerst alleen inlezen (geen netwerk), om te zien dat de tijden en niveaus kloppen:

```bash
.venv/bin/python3 scripts/misser_check.py --csv docs/onderzoek/range-sweep/handtrades.csv --alleen-parsen
```

Dan de echte controle per variant:

```bash
.venv/bin/python3 scripts/misser_check.py --csv docs/onderzoek/range-sweep/handtrades.csv --motor rangesweep --venster-uren 12 | tee data/replay/misser_rangesweep.txt
```

Lees per voorbeeld of minstens een variant het zag, en zo niet welke regel het weigerde. Vul `docs/onderzoek/range-sweep/missers.md` in (kolommen Gezien door, Weigerende regel, Gemeten waarde, Besluit).

Poort 0a (S0): minstens 3 van de 5 voorbeelden gezien door minstens een variant, later minstens 60% bij minstens 10 voorbeelden. Anders: hooguit twee definitierondes (noteer ze onder "Definitierondes"), daarna stoppen. Geen labrun.

## 3. Poort 0b en 1: de galerij met het oog

Beide pagina's zijn statisch. De VPS heeft geen browser: maak de bestanden en haal ze naar je eigen computer.

```bash
# poort 0b: jouw voorbeelden met onze ranges en zones op dat moment
.venv/bin/python3 scripts/range_sweep_gallery.py --csv docs/onderzoek/range-sweep/handtrades.csv --uit /tmp/range_sweep_voorbeelden.html
# poort 1: 30 willekeurige setups uit de historie (vaste seed 7)
.venv/bin/python3 scripts/range_sweep_gallery.py --coins BTC,ETH,SOL,ARB,APT,AAVE --n 30 --jaren 3 --uit /tmp/range_sweep_galerij.html
```

Op je eigen computer (nieuw terminalvenster, niet op de VPS), open daarna de bestanden in je browser:

```bash
scp <gebruiker>@<jouw-vps>:/tmp/range_sweep_voorbeelden.html /tmp/range_sweep_galerij.html .
```

- Poort 0b: leg elk getekend voorbeeld naast je screenshot. Bevestig range en zones (of noteer wat afwijkt) in `missers.md` onder "Vergelijking met het oog".
- Poort 1: oordeel per kaart "klopt" of "klopt niet" met een reden. Minstens 80% van de 30 moet kloppen (S1). Anders: detector repareren (hooguit twee rondes, noteer ze) en deze stap herhalen.

Pas als poort 1 gehaald is, wordt de pre-registratie bevroren: vul in `preregistratie.md` de datum en de commit-hash in op de regel "Bevroren op" en commit dat. Na het bevriezen verandert er niets meer aan varianten, drempels of definities.

## 4. Poort 2: de volledige labrun

Alleen op de bevroren commit. De volgorde: eerst de candles, dan de run. De cache in `data/candles/` wordt gedeeld met andere scripts en `ensure_candles` geeft een bestaande cache terug zonder naar het aantal jaren te kijken; daarom haalt de lus hieronder alles met `refresh=True` opnieuw op (ook de zes coins die de galerij van stap 3 al vulde), en weigert het labscript een cache die meer dan 14 dagen korter dekt dan `--jaren` (foutmelding "dekt maar ... dagen").

```bash
# candles ophalen: 20 coins maal 3 timeframes, enkele minuten
for c in BTC ETH SOL BNB XRP ADA DOGE AVAX LINK DOT LTC BCH NEAR ATOM UNI AAVE SUI INJ APT ARB; do
  .venv/bin/python3 -c "from app.replay import candles as cc; [cc.ensure_candles('$c', 3, refresh=True, timeframe=t) for t in ('15m','1h','4h')]" && echo "$c klaar"
done

# de run: hervatbaar per coin, rapport tussen de markers van resultaten.md
.venv/bin/python3 scripts/strategy_lab.py --familie rangesweep --jaren 3 --kosten 0.12 --alleen-volledig \
  --hervat data/replay/rangesweep_012 --rapport docs/onderzoek/range-sweep/resultaten.md | tee data/replay/rangesweep_012.log
```

Verwachte duur: ongeveer 40 minuten (circa 2 minuten per coin, 20 coins; dit is een schatting vooraf, de eerste coin laat zien of jouw VPS sneller of trager is). Je ziet per coin een regel `COIN: uit ...` of per variant `COIN VARIANT: n rijen`; dat is voortgang.

De run schrijft niets in de database. De uitvoer begint met het aantal varianten en toetsen (15 varianten, 30 toetsen, 64 in het register): dat is de horde voor meervoudig toetsen uit de pre-registratie (voordeel pas bij t van minstens 3,4).

**Onderbroken?** Een verbroken verbinding, herstart of Ctrl+C is geen ramp. Dezelfde opdracht opnieuw uitvoeren (met dezelfde `--hervat` map) slaat de klare coins over (`COIN: uit data/replay/rangesweep_012/COIN_rows.pkl`) en rekent alleen de rest. Het resultaat is gelijk aan een run zonder onderbreking. Het script weigert een map die met andere `--kosten`, `--jaren` of varianten is gemaakt; gebruik dan een nieuwe map. Een klare coin opnieuw laten rekenen: verwijder `data/replay/rangesweep_012/COIN_*.pkl`.

**Rapport.** Het rapport komt in `docs/onderzoek/range-sweep/resultaten.md`, tussen `<!-- resultaten:begin -->` en `<!-- resultaten:end -->`. Alleen die ruimte wordt overschreven; de tekst erbuiten (hoe te lezen, jouw oordeel) blijft staan. Ontbreken de markers, dan stopt het script direct, voordat er iets gerekend wordt.

Gevoeligheid (hogere kosten), nooit opslaan:

```bash
.venv/bin/python3 scripts/strategy_lab.py --familie rangesweep --jaren 3 --kosten 0.16 --alleen-volledig --hervat data/replay/rangesweep_016
```

## 5. Poort 3: het oordeel lezen

Onderaan de uitvoer staat een van twee regels:

- `Gekozen voor de proef: <VARIANT> met stop <STOP>`: PASS. Minstens een toets slaagde op stopkwaliteit (de kop). Gekozen wordt vooraf vastgelegd: geslaagd, dan de meeste vullingen, dan de laagste mediane kosten, dan de bredere stop.
- `Geen variant gekozen voor de proef (S2).`: geen enkele van de 30 toetsen slaagt. Geen live setupmotor (taak 15 niet uitrollen); de range-watch uit taak 14 mag blijven als informatie. Bij mediane kosten boven 0,10R in alle 30 toetsen geldt S3: zelfde besluit.

Hoe je het rapport leest:

1. Tabel "Stopkwaliteit" is de kop: stop geraakt, kosten in R, en hoe vaak +1R tot +6R vóór de stop kwamen. De kolom Oordeel zegt SLAAGT of welke eis faalde (bijvoorbeeld "genoeg vullingen (300)").
2. "Netto R bij de referentie-uitgangen" staat ernaast. Geen van die uitgangen is jouw doel. Alleen de strenge toets daar (met t van minstens 3,4 per week) kan ooit "Bewezen" opleveren.
3. Eén geslaagde toets van 30 (64 in het register) is nog geen bewijs. Controleer of de uitkomst niet aan een paar coins of een paar maanden hangt, en of de variant met en zonder HTF-filter niet tegenstrijdig is.
4. Schrijf je oordeel onder "Oordeel (na de run, door een mens)" in `resultaten.md`: S2 en S3, en de gekozen variant en stop.

## 6. Opslaan, alleen bij PASS

Alleen als stap 5 een gekozen variant gaf. Dit leest de tussenresultaten van stap 4 (geen nieuwe berekening, de candles komen uit de cache) en schrijft per variant een regel in `rule_status`, plus `range_sweep_stop` en `range_sweep`:

```bash
.venv/bin/python3 scripts/strategy_lab.py --familie rangesweep --jaren 3 --kosten 0.12 --alleen-volledig \
  --hervat data/replay/rangesweep_012 --opslaan
```

Het script weigert `--opslaan` bij `--kosten` onder 0,12 en bij een oordeel zonder geslaagde toets (er wordt dan niets geschreven). Daarna het rapport terug naar de repo:

```bash
git add docs/onderzoek/range-sweep/resultaten.md docs/onderzoek/range-sweep/missers.md
git commit -m "onderzoek: uitkomst range sweep-lab"
git push
```

Bij S2 of S3 sla je niets op en commit je alleen het rapport met jouw oordeel. Het tussenresultaat in `data/replay/` staat in `.gitignore` en blijft op de VPS.
