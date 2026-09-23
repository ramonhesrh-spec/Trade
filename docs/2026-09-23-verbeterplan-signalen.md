# Verbeterplan: afgeronde signalen, waarom zoveel stop loss

Onderzoek op verzoek van de gebruiker ("kijk alle afgeronde signalen, best
veel SL geraakt"). Databron: alle `signals` met `auto_outcome IS NOT NULL
AND is_practice = 0` op de VPS, opgevraagd 2026-09-23. 66 afgeronde
signalen totaal, aangemaakt tussen 2026-09-02 en 2026-09-19.

## Samenvatting

| trade_type | winst | verlies | vervallen | winrate (excl. vervallen) |
|---|---|---|---|---|
| day_trading | 15 | 27 | 5 | 35.7% |
| swing | 7 | 8 | 4 | 46.7% |

Geen patroon-signalen in deze set: die feature ging pas op 2026-09-23 live
en heeft nog geen afgeronde trades.

De cijfers op zich zeggen weinig totdat je ze opsplitst. Dat opgesplitst
beeld is duidelijk en eenduidig:

**Elke long won. Elke short verloor. Zonder uitzondering, over beide
trade_types heen.**

| richting | winst | verlies |
|---|---|---|
| long (day_trading + swing) | 22 | 0 |
| short (day_trading + swing) | 0 | 35 |

Dit is geen ruis. 57 van de 66 afgeronde signalen (86%) verklaren zich
volledig via deze ene as: had je long, dan won je; had je short, dan
verloor je.

## Bevinding 1: de markt trendde hard omhoog in dit venster, niet een
kapotte short-detectie

De EMA9/EMA21-trendfilter op het moment van elk signaal is gecontroleerd:

| trade_type | richting | EMA9 > EMA21 (trend omhoog) | EMA9 < EMA21 (trend omlaag) |
|---|---|---|---|
| day_trading | long | 16 | 4 |
| day_trading | short | 1 | 26 |

96% van de day-trading shorts (26 van 27) had wel degelijk een correcte,
technisch geldige bearish EMA-cross op het moment van melden. Dit waren
geen kansloze of verkeerd-om-gedetecteerde signalen — het waren legitieme
korte-termijn short-opzetten die vervolgens alsnog stukliepen omdat de
bredere markt bleef doorstijgen.

Sterkste concrete bewijs: op **17 september tussen 03:07 en 12:09 uur**
vuurden 16 verschillende coins (AVAX, BNB, RAY, BTC, SUI, AAVE, DOGE, ETH,
FET, GRAM, INJ, JUP, LINK, SOL, TAO, WLD, XLM) allemaal een short-signaal
af, en **alle 16 raakten stop loss**. Zestien onafhankelijke coins die
tegelijk tegen je in bewegen is geen toeval per coin — dat is één markt-
brede beweging (vrijwel zeker een BTC-rally, aangezien BTC zelf ook in die
periode van ~76.500 naar ~81.858 steeg tussen 2 en 19 september) die elke
short raakte, ongeacht hoe goed de individuele coin-opzet was.

## Bevinding 2: de twee fixes die precies dit scenario aanpakken zijn al
gebouwd — één moet je zelf nog aanzetten

- `indicators.check_btc_trend` (commit fbec4e5, **16 september**): blokkeert
  een signaal hard als de richting tegen een duidelijke BTC-trend ingaat.
  Zit alleen in `compute_advanced_extra_factors`, dus **alleen actief als
  `ENABLE_ADVANCED_FACTORS=true` in je `.env` staat**.
- De coin-eigen dagtrend als harde eis (commit a2ea9c8, **22 september,
  vandaag al gedeployed**): blokkeert een signaal als de 4u-richting tegen
  de eigen dagtrend van die coin ingaat, met een vlakke-markt-uitzondering.
  **Deze staat onvoorwaardelijk aan, geen flag nodig.**

Alle 66 signalen in dit onderzoek hebben `hard_gates_ok = 1` — geen ervan
is ooit hard geblokkeerd. Voor de 21 shorts na 16 september (inclusief de
hele 17-september-episode) zou je, als de markt toen echt duidelijk trendde
(zeer aannemelijk gezien bevinding 1), verwachten dat minstens een deel
van die shorts door de BTC-trend-gate geblokkeerd zou zijn — dat gebeurde
niet. Sterke aanwijzing dat `ENABLE_ADVANCED_FACTORS` in die periode uit
stond.

**Actie:** bevestig of `ENABLE_ADVANCED_FACTORS=true` staat op de VPS. Zo
niet: draai eerst `scripts/backtest_factors.py --limit 50` (het script
raadt dit zelf al aan in zijn eigen docstring) om te zien of de individuele
factoren een gezonde pass-rate geven, en zet de vlag dan aan.

De dagtrend-gate van vandaag heeft geen vlag nodig en dekt een groot deel
van hetzelfde scenario al af, dus een deel van het probleem is al
structureel opgelost, ook zonder die vlag.

## Bevinding 3: MACD wijst vaak de andere kant op bij shorts

| trade_type | richting | MACD > signaallijn (bullish) | MACD < signaallijn (bearish) |
|---|---|---|---|
| day_trading | short | 21 | 6 |

Bij 21 van de 27 day-trading shorts stond de MACD-lijn BOVEN de
signaallijn — bullish momentum — terwijl het signaal short was. MACD is
één van de vier gepoolde basisfactoren (3-van-4 volstaat), dus een short
kan afgaan terwijl het momentum actief tegenspreekt, zolang de andere drie
factoren (EMA-cross, RSI, volume) wel kloppen.

Dit verdient een eigen check, geen blind doorvoeren: draai
`scripts/backtest_factors.py` met een uitsplitsing MACD-mee vs MACD-tegen
en kijk of MACD-tegenstrijdige signalen structureel slechter scoren dan
MACD-bevestigde. Is dat zo, dan is MACD net zo'n kandidaat voor een harde
eis als BTC-trend en dagtrend nu al zijn.

## Bevinding 4 (operationeel, los van signaalkwaliteit): level-check lijkt
weken niet in real time te hebben gedraaid

`auto_outcome_at` van alle 66 signalen valt op **21 of 22 september** —
geen enkele eerder, ook niet voor signalen die al op 2 september zijn
aangemaakt. Dat is geen geleidelijke spreiding, dat is een enkele
inhaalslag. Als `crypto-level-check.timer` (elke 15 minuten, per
`deploy/crypto-level-check.timer`) goed had gedraaid, waren deze trades
dagen tot weken eerder als winst/verlies gemarkeerd en had je toen al
gepushte SL/TP-meldingen gekregen in plaats van nu, achteraf, in bulk.

**Actie, op de VPS:**
```
sudo systemctl status crypto-level-check.timer
sudo journalctl -u crypto-level-check.service --since "30 days ago" | head -100
```
Dit is een controle, geen codewijziging — mogelijk was de timer een tijd
niet actief, of een eerdere bug in `level_check.py` is inmiddels al
gefixt en dit is de eerste succesvolle inhaalrun. Beide zijn hier niet uit
af te leiden zonder de VPS-logs zelf.

## Bevinding 5: "laag vertrouwen" presteert dramatisch slechter, wat het
eigen doel van dat label bevestigt

| confidence (day_trading) | winst | verlies | winrate |
|---|---|---|---|
| hoog vertrouwen | 12 | 4 | 75.0% |
| laag vertrouwen | 3 | 23 | 11.5% |

Dit is geen nieuw probleem — het bevestigt juist dat het hoog/laag-
onderscheid doet wat het moet doen. Maar 11.5% winrate op laag-vertrouwen-
signalen is zo zwak dat het de vraag oproept of die signalen wel als
gelijkwaardige "kans" getoond moeten worden. Zie aanbeveling hieronder.

## Wat NIET het probleem is

- Het ontworpen risico/rendement zat gemiddeld al op 2.04:1 (day_trading)
  en exact 2.0:1 (swing) — ruim boven de nieuwe R:R-harde-eis van 1.5:1.
  Een slechte R:R-verhouding verklaart dit niet.
- De EMA-trendfilter werkte zoals bedoeld (96% van de shorts had een
  correcte bearish cross). Dit is geen "de detectie deugt niet"-verhaal.

## Aanbevelingen, geprioriteerd

1. **Bevestig `ENABLE_ADVANCED_FACTORS`** en zet aan als de backtest het
   rechtvaardigt (bevinding 2). Kost niets aan nieuwe code, mogelijk de
   grootste hefboom.
2. **Check `crypto-level-check.timer` op de VPS** (bevinding 4). Puur
   operationeel, maar zonder dit weet je nooit of toekomstige SL/TP-
   meldingen wel op tijd aankomen.
3. **Laat dit dataset met rust en meet over 2-4 weken opnieuw.** De
   dagtrend-gate ging vandaag pas live; met 66 signalen en een extreem
   eenzijdige markt-periode is dit nog geen betrouwbare basis om verder op
   te sturen. Een vervolgmeting laat zien of de asymmetrie (22/0 long/
   short) afneemt nu de nieuwe hard gates meedraaien.
4. **Backtest MACD als mogelijke extra harde eis** (bevinding 3), niet
   blind doorvoeren — eerst zien of MACD-tegenstrijdige signalen echt
   structureel slechter scoren voordat het een blokkerende eis wordt.
5. **Overweeg laag-vertrouwen-signalen anders te presenteren** (bevinding
   5): 11.5% winrate is zwak genoeg om te heroverwegen of ze als
   volwaardige "kans" op het dashboard moeten staan, of duidelijker als
   "waarschijnlijk niet nemen" gelabeld moeten worden. Dit is een
   productbeslissing, geen technische fix — vraag het de gebruiker voordat
   dit gebouwd wordt.

## Beperkingen van dit onderzoek

- 66 signalen, waarvan 57 de long/short-as volgen — een klein en
  historisch eenzijdig (sterk stijgende markt) venster. Niet generaliseren
  naar "shorts werken nooit", wel naar "in een duidelijke trend werkt een
  tegen-trend short zonder trend-gate slecht", wat precies is wat de twee
  nieuwe hard gates zouden moeten voorkomen.
- `pass_pct` ontbreekt in alle 66 rijen (leeg/NULL) — die kolom is pas
  later gevuld gaan worden, dus een uitsplitsing op het exacte gepoolde
  percentage was voor dit venster niet mogelijk, alleen op het afgeleide
  hoog/laag-label.
- Patroonherkenning is te nieuw om in dit onderzoek mee te nemen.
