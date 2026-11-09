# Zone-sweep: VPS-protocol (labrun)

De sandbox heeft geen toegang tot Binance: de labrun draai jij op de VPS. De opzet is dezelfde als bij de range sweep (`docs/onderzoek/range-sweep/vps-protocol.md`, stappen 1, 4 en 6); hieronder alleen wat voor de zone-sweep anders is. Regels en drempels staan in `preregistratie.md`, onder 'Lab'.

**Eerst de poorten.** Volgens de pre-registratie komt de labrun pas na poort 2 (30 willekeurige getekende setups, minstens 80% klopt) en na het bevriezen van de pre-registratie. Draai de run alleen op die bevroren commit.

```bash
ssh <jouw-vps>
cd /opt/crypto-alerts
tmux new -s zonesweep         # terug na een verbroken verbinding: tmux attach -t zonesweep
git pull && .venv/bin/pip install -r requirements.txt
```

## 1. Candles

Dezelfde cache als de range sweep (15m, 1u en 4u van de 20 coins; 2u wordt daaruit samengevoegd). Heb je de range sweep-run net gedaan, dan is dit al klaar; anders, of als de cache korter is dan 3 jaar (foutmelding "dekt maar ... dagen"):

```bash
for c in BTC ETH SOL BNB XRP ADA DOGE AVAX LINK DOT LTC BCH NEAR ATOM UNI AAVE SUI INJ APT ARB; do
  .venv/bin/python3 -c "from app.replay import candles as cc; [cc.ensure_candles('$c', 3, refresh=True, timeframe=t) for t in ('15m','1h','4h')]" && echo "$c klaar"
done
```

Let op: een verse download van de cache maakt een hervatbare range sweep-map ongeldig (de laatste 15m-candle is dan anders). Doe de range sweep-run dus eerst af, of gebruik daar daarna `--verse-start`.

## 2. De run

```bash
mkdir -p data/replay
.venv/bin/python3 scripts/strategy_lab.py --familie zonesweep --jaren 3 --kosten 0.12 --alleen-volledig \
  --hervat data/replay/zonesweep_012 | tee data/replay/zonesweep_012.log
```

Verwachte duur: ongeveer 1,5 tot 3 uur (schatting vooraf: circa 5 minuten per coin in de sandbox op kunstmatige candles, 20 coins; het meeste werk is de placebo met 20 trekkingen per gevulde trade). De eerste coin laat zien hoe snel jouw VPS is. Per variant zie je een regel `COIN ZS_...: n rijen`; dat is voortgang. Er wordt geen OI opgehaald.

De uitvoer begint met `7 varianten, 14 toetsen; samen met eerder bekeken varianten 78 in het register`. De run schrijft niets in de database. Onderbroken? Dezelfde opdracht opnieuw (met dezelfde `--hervat` map) slaat de klare coins over; het script weigert een map van andere instellingen, varianten, code of pre-registratie (dan een nieuwe map, of `--verse-start`).

Wil je het rapport in een bestand: maak `docs/onderzoek/zone-sweep/resultaten.md` met de regels `<!-- resultaten:begin -->` en `<!-- resultaten:end -->` en voeg `--rapport docs/onderzoek/zone-sweep/resultaten.md` toe; zonder markers stopt het script meteen.

## 3. Het oordeel

Onderaan staat `Gekozen voor de proef: <VARIANT> met stop <STOP>` of `Geen variant gekozen voor de proef (S2).`, en de regel `Stopcriteria: S2 ...: ja/nee. S3 ...: ja/nee.` over de 14 toetsen. Lees het rapport zoals bij de range sweep (stap 5 daar): de stopkwaliteit is de kop, de netto R bij de referentie-uitgangen staat ernaast, en een PASS bij 14 toetsen (78 in het register) is een screening-resultaat, geen bewijs.

## 4. Opslaan, alleen bij een gekozen variant

```bash
.venv/bin/python3 scripts/strategy_lab.py --familie zonesweep --jaren 3 --kosten 0.12 --alleen-volledig \
  --hervat data/replay/zonesweep_012 --opslaan
```

Dit leest de tussenresultaten (geen nieuwe berekening) en schrijft per variant een regel in `rule_status` (`zs_1h` enz.), plus `zone_sweep_stop` en `zone_sweep`. Het script weigert bij `--kosten` onder 0,12, minder dan de 20 coins, een andere `--jaren` dan 3, zonder `--alleen-volledig` en zonder geslaagde toets. Er is geen proefmotor voor de zone-sweep: opslaan zet niets live.
