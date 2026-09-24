# Verplichte factoren per gebruiker — design

## Probleem

De bestaande drempel-instelling (`confirm_threshold_pct`, drie presets:
soepel 45%, normaal 60%, streng 75%) is één blind percentage. Een
gebruiker die vindt dat bijvoorbeeld "Steun/weerstand" of "Liquidity
sweep" voor hem persoonlijk doorslaggevend is, heeft geen manier om dat
uit te drukken — hij kan alleen de algemene lat hoger zetten, wat ook
allerlei andere, voor hem onbelangrijke factoren zwaarder laat wegen.
De gebruiker vroeg initieel om een drempel als los getal ("pas melding
vanaf 15 of 17 factoren goed"), maar wil uiteindelijk duidelijkheid per
factor: een uitleg wat elke factor precies meet, en de mogelijkheid om
per factor zelf te bepalen of die voor hem verplicht is.

## Kernidee

Bovenop de bestaande, gedeelde percentage-toets komt een tweede,
optionele, per-gebruiker eis: een selectie van factoren die voor deze
gebruiker altijd ✓ moeten staan. Staat een verplichte factor ✗ (of
ontbreekt hij helemaal uit de toetsing van dit specifieke signaal), dan
telt het signaal voor deze gebruiker nooit als bevestigd — ongeacht het
percentage. Wie geen enkele factor verplicht stelt, ziet exact het
huidige gedrag: alleen de drempel-knoppen zijn dan van invloed.

Dit is een AND bovenop de bestaande OF-drempel-vergelijking, geen
vervanging: `bevestigd = (percentage ≥ drempel) AND (alle verplichte
factoren ✓)`.

## Niet-doelen

- Geen wijziging aan hoe het percentage zelf berekend wordt
  (`confirms_direction` in `app/indicators.py`) — die blijft gedeeld en
  identiek voor iedereen, precies zoals nu.
- Geen wijziging aan de drie bestaande harde eisen (Uitgerektheid,
  BTC-trend, Daily-trend) — die blijven voor iedereen hard, niet
  per-gebruiker uit te zetten. Die beschermen tegen chasen en tegen-de-
  trend-in traden, een risico dat voor niemand optioneel moet zijn.
- Geen toepassing op swing-signalen: die hebben geen gepoolde ✓/✗-lijst
  (twee losse checks, zie `signal_processor.run_swing_check`), swing
  blijft overal in dit project al een uitzondering en blijft dat ook hier.
- Geen wijziging aan stop-loss/take-profit/positiegrootte.
- Geen gewicht/weging per factor (factor A telt zwaarder dan factor B in
  het percentage zelf) — expliciet buiten scope, YAGNI: de gebruiker
  vroeg om aan/uit, niet om een schuifregelaar per factor.

## De 18 toggle-bare factoren

Vaste lijst, met een korte uitleg in gewone taal voor de instellingen-
pagina (bron: de bestaande docstrings van elke losse check-functie in
`app/indicators.py`):

| Factor | Uitleg |
|---|---|
| Trend | EMA9 t.o.v. EMA21 volgt de richting van de trade |
| Momentum | MACD-lijn t.o.v. signaallijn volgt de richting |
| RSI | Niet al te extreem overbought/oversold tegen de richting in |
| Volume | Minstens gemiddeld handelsvolume, geen dunne markt |
| Trendsterkte | ADX sterk genoeg en wijst de juiste kant op |
| Volatiliteit | Prijsbeweging (ATR) trekt niet samen, markt leeft |
| Volume-percentiel | Huidig volume zit hoog genoeg t.o.v. recente historie |
| RSI daily | RSI op dagniveau bevestigt, niet extreem tegen de richting in |
| Premium/discount | Entry in de goedkope (long) of dure (short) helft van de recente range |
| Premium/discount (dag) | Zelfde, op dagniveau — een sterker signaal |
| Liquidity sweep | Recente stop-hunt (pen door een niveau, direct terug) in de goede richting |
| Liquidity sweep (dag) | Zelfde, op dagniveau |
| 1u bevestiging | De trend op het 1-uur-timeframe bevestigt de richting |
| RSI 1u | RSI op 1 uur bevestigt, niet extreem |
| Divergentie | Geen waarschuwende afwijking tussen prijs en RSI |
| Candlepatroon | Een herkenbaar candlestick-patroon ondersteunt de richting |
| Liquiditeit | Genoeg 24u-handelsvolume om in en uit te kunnen zonder de prijs te bewegen |
| Steun/weerstand | Een bevestigde terugveer op een zelf-gedetecteerde zone |

Deze lijst wordt één keer vastgelegd als een module-constante in
`app/indicators.py` (`TOGGLEABLE_FACTORS: list[tuple[str, str]]`, naam +
uitleg) — enige bron van waarheid voor zowel de validatie in de
opslaan-route als de weergave op /account. De namen moeten letterlijk
overeenkomen met wat `confirms_direction`/de losse `check_*`-functies als
factornaam in de breakdown-tekst zetten (bijv. `"Steun/weerstand"`,
exact zoals `indicators.check_sr_zone` teruggeeft) — een tikfout hier
betekent stilzwijgend "deze factor komt nooit voor, dus faalt altijd
fail-closed", zie Foutafhandeling.

## Component 1 — opslag

Nieuwe tabel, `app/schema.sql` (brand-new tabel, `CREATE TABLE IF NOT
EXISTS` volstaat voor zowel een verse als een bestaande database, geen
`_migrate()`-guard nodig — zelfde precedent als `muted_coins`/
`sr_zone_failures`):

```sql
CREATE TABLE IF NOT EXISTS user_required_factors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    factor_name TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, factor_name)
);
CREATE INDEX IF NOT EXISTS idx_user_required_factors_user ON user_required_factors(user_id);
```

`app/repo.py`, drie nieuwe functies:

```python
def list_required_factors(user_id: int) -> set[str]:
    """Alle factoren die deze gebruiker verplicht heeft gesteld."""

def list_required_factors_all_users() -> dict[int, set[str]]:
    """Batch-variant voor de marktscan-fanout en level_check.py: één query
    voor alle gebruikers tegelijk in plaats van één per gebruiker per
    signaal — zelfde 'één keer per cyclus, niet per rij'-discipline als
    pattern_winrate_stats()/winrate_stats() elders in dit bestand."""

def set_required_factors(user_id: int, factor_names: list[str]) -> None:
    """Vervangt de hele set in één transactie (DELETE + INSERT), net als
    market_scanner.py's forming_patterns-precedent: de instellingenpagina
    stuurt altijd de complete, actuele lijst, geen los toevoegen/
    verwijderen nodig."""
```

## Component 2 — de toets zelf

`repo.user_confirmed` krijgt twee nieuwe, optionele parameters — de
bestaande drie-parameter-aanroepen (er zijn er meerdere in dit project)
blijven exact hetzelfde gedrag vertonen zonder aangepast te hoeven
worden:

```python
def user_confirmed(
    pass_pct: Optional[float], hard_gates_ok: bool, threshold_pct: float,
    reason: str = "", required_factors: Optional[set[str]] = None,
) -> bool:
    base_confirmed = bool(hard_gates_ok) and pass_pct is not None and pass_pct >= threshold_pct
    if not base_confirmed or not required_factors:
        return base_confirmed
    results = _parse_factor_results(reason)
    # Fail-closed: een verplichte factor die niet in results voorkomt
    # (nooit gecheckt voor dit signaal, bv. Trendsterkte ontbreekt zonder
    # ENABLE_ADVANCED_FACTORS) telt ook als niet voldaan — .get(f, False),
    # niet .get(f, True). Anders zou een gebruiker die "Trendsterkte"
    # verplicht heeft gesteld toch meldingen krijgen voor signalen waar
    # die factor domweg nooit is berekend.
    return all(results.get(f, False) for f in required_factors)


def _parse_factor_results(reason: str) -> dict[str, bool]:
    """Zelfde breakdown-formaat als confirms_direction opbouwt
    ("✓ Trend: ... | ✗ Volume: ..."), maar dan alle factoren met hun
    ✓/✗-status, niet alleen de gefaalde (vergelijk
    signal_processor._extract_failing_factors, die alleen de ✗'s
    teruggeeft en hier niet volstaat: fail-closed op afwezigheid vereist
    weten welke namen WEL voorkwamen)."""
    results: dict[str, bool] = {}
    for part in reason.split(" | "):
        part = part.strip()
        if part[:1] in ("✓", "✗"):
            name = part[1:].split(":", 1)[0].strip()
            results[name] = part.startswith("✓")
    return results
```

## Component 3 — de aanroepplekken

`repo.user_confirmed` heeft vier aanroepplekken in vier bestanden, niet
één functie die vanaf vier pagina's wordt aangeroepen — dat laatste was
een eerdere, onjuiste aanname in dit document, gecorrigeerd na het
naspeuren van elke aanroep. Alle vier krijgen de twee nieuwe argumenten
erbij. Overal geldt: alleen doorgeven voor `trade_type in ("day_trading",
"patroon")` — voor swing blijft `required_factors=None` (impliciet, door
het simpelweg niet mee te geven), dat behoudt swing's bestaande "altijd
bevestigd"-kortsluiting ongewijzigd.

1. **`web/main.py::_apply_user_confirmed(entries, threshold_pct)`** →
   `_apply_user_confirmed(entries, threshold_pct, required_factors)`.
   Deze functie heeft maar twee echte aanroepplekken: `/signalen`
   (`signalen_page`, regel 203, op `entries`) en de coin-pagina
   (`coin_page`, regel 1636, alleen op `recent_signals`). Dashboard
   (`dashboard`) en `/account` (`account_page`) roepen
   `_apply_user_confirmed` niet aan — hun `open_entries`/`taken_entries`/
   `pending_entries` lopen alleen door `_add_signal_context` (advies +
   slagingskans), die zet nooit `entry["user_confirmed"]`. Op die twee
   pagina's wordt de groene bevestigd-rand dus vandaag al nergens getoond,
   en blijft dat ook na deze wijziging — daar hoeft niets aangepast te
   worden. Elke route die `_apply_user_confirmed` wél aanroept haalt
   `repo.list_required_factors(user["id"])` één keer op vóór de aanroep,
   net zoals `winrate = repo.winrate_stats(user["id"])` al één keer per
   requesthandler gebeurt.

2. **`signal_processor.py::_fanout_confirmed_signal`** — de per-user-loop
   die nu al `repo.user_confirmed(kansberekening, hard_gates_ok,
   user["confirm_threshold_pct"])` aanroept per gebruiker (regel 514),
   krijgt `required_by_user = repo.list_required_factors_all_users()` één
   keer vóór de loop (niet per gebruiker opnieuw), en geeft
   `required_by_user.get(user["id"], set())` + de signaal-`reason`-tekst
   mee per aanroep.

3. **`level_check.py::check_pending_signals()`** — `reason` staat nog niet
   in `repo.list_pending_entries_with_price()`'s SELECT (die kolomlijst
   is, net als `_JOURNAL_SELECT`, expliciet en niet `SELECT s.*` — zie de
   bestaande waarschuwende comment daarboven), dus `s.reason AS reason`
   erbij. `required_by_user = repo.list_required_factors_all_users()` één
   keer aan het begin van de functie, zelfde plek als de bestaande
   `pattern_winrate = repo.pattern_winrate_stats()`. In de drie-weg
   `is_confirmed`-branch (swing/patroon/overig, regel 205-212) krijgen
   alleen de patroon- en "overig" (day_trading)-takken de nieuwe
   argumenten mee.

4. **`repo.winrate_for_user(user_id)`** — pas tijdens dit self-review
   gevonden, ontbrak in een eerdere versie van dit document. Dit is de
   automatische trackrecord-winrate die `/account` zelf toont (zie
   `account_page`'s eigen docstring: "de winrate die deze pagina zelf
   toont is repo.winrate_for_user"). De functie loopt zelf over alle
   `day_trading`-signalen van het systeem (patroon is al uitgesloten via
   `trade_type != 'patroon'` in de eigen SELECT, swing valt vanzelf weg
   omdat `pass_pct IS NOT NULL` swing's altijd-None pass_pct uitfiltert)
   en roept per rij `user_confirmed(pass_pct, hard_gates_ok, threshold)`
   aan zonder de nieuwe argumenten. Zonder aanpassing zou het winrate-
   cijfer op /account iets anders blijven meten dan wat de gebruiker
   daadwerkelijk als melding krijgt: alleen tegen zijn percentage-drempel
   gefilterd, niet tegen zijn verplichte factoren. Fix: de eigen SELECT
   krijgt `reason` erbij (`SELECT pass_pct, hard_gates_ok, auto_outcome,
   reason FROM signals WHERE ...`, ongewijzigde WHERE-clausule), de
   functie haalt `repo.list_required_factors(user_id)` eenmalig op vóór
   de loop (één losse query per page-load, geen batch nodig — in
   tegenstelling tot de fanout/level_check-paden loopt deze functie maar
   over signalen van één gebruiker, niet over alle gebruikers) en geeft
   die mee aan elke `user_confirmed`-aanroep in de loop. De publieke
   signature (`winrate_for_user(user_id: int) -> dict`) verandert niet,
   dus geen enkele aanroeper van `winrate_for_user` zelf hoeft aangepast
   te worden.

## UI

Nieuwe sectie op `/account`, direct onder de bestaande drempel-knoppen
in `web/templates/account.html`:

```html
<details class="stats-collapse js-accordion" style="margin-top: 12px;">
  <summary class="stats-summary">Belangrijke factoren</summary>
  <p class="muted" style="margin: 8px 0 10px; font-size: 12.5px;">
    Vink een factor aan als die voor jou verplicht is: staat hij ✗ in een
    signaal, dan telt het voor jou nooit als bevestigd, ongeacht het
    percentage. Niet aangevinkt telt gewoon mee in het percentage zoals nu.
  </p>
  <form action="/instellingen/factoren" method="post" class="required-factors-form">
    {% for name, uitleg in toggleable_factors %}
    <label class="factor-toggle">
      <input type="checkbox" name="factoren" value="{{ name }}"{% if name in user_required_factors %} checked{% endif %}>
      <span class="factor-toggle-name">{{ name }}</span>
      <span class="muted factor-toggle-uitleg">{{ uitleg }}</span>
    </label>
    {% endfor %}
    <button type="submit">Opslaan</button>
  </form>
</details>
```

Nieuwe route in `web/main.py`:

```python
@app.post("/instellingen/factoren")
async def update_required_factors_setting(
    factoren: list[str] = Form([]),
    user: dict = Depends(require_login),
):
    # Nooit ruwe formulierinvoer direct opslaan: alleen namen uit de
    # vaste TOGGLEABLE_FACTORS-lijst zijn geldig, geknoei met het
    # formulier (of een verouderde factornaam) wordt stil genegeerd.
    valid_names = {name for name, _ in indicators.TOGGLEABLE_FACTORS}
    factoren = [f for f in factoren if f in valid_names]
    repo.set_required_factors(user["id"], factoren)
    return RedirectResponse(url="/account", status_code=303)
```

`account_page`'s context krijgt `"toggleable_factors":
indicators.TOGGLEABLE_FACTORS` en `"user_required_factors":
repo.list_required_factors(user["id"])` erbij.

CSS: nieuwe, eenvoudige `.factor-toggle`-regel in `web/static/style.css`
(checkbox + naam + grijze uitleg op een regel, geen nieuw patroon nodig —
volgt de bestaande `.levels-form`/label-stijl die al in dit bestand
staat).

## Foutafhandeling

- Een verplichte factor die nooit voorkomt in een signaal se breakdown
  (verkeerde naam door een toekomstige refactor van een check-functie,
  of een signaal-type dat die factor domweg niet berekent) faalt altijd
  fail-closed (Component 2) — geen crash, gewoon "niet bevestigd voor
  deze gebruiker", consistent met de bestaande fail-closed-filosofie in
  `compute_advanced_extra_factors`.
- De opslaan-route valideert tegen de vaste `TOGGLEABLE_FACTORS`-lijst,
  nooit ruwe stringinvoer rechtstreeks in de database.
- Een gebruiker zonder enkele verplichte factor (de meerderheid,
  standaard) ziet géén gedragsverandering: `required_factors` is dan een
  lege set, `user_confirmed` slaat de hele nieuwe check over.

## Testen

Geen pytest-suite in dit project — verificatie via throwaway scripts
tegen een scratch-database, zoals de rest van deze sessie:
- `_parse_factor_results`: een handmatige breakdown-string met bekende
  ✓/✗-namen, controleren dat de dict klopt.
- `user_confirmed`: vier scenario's — geen verplichte factoren (ongewijzigd
  gedrag), een verplichte factor die ✓ staat (bevestigd als het
  percentage ook klopt), een verplichte factor die ✗ staat (nooit
  bevestigd, ook niet bij 100% op de rest), een verplichte factor die
  helemaal niet in de reason voorkomt (fail-closed, nooit bevestigd).
- Scratch-DB round-trip voor `list_required_factors`/
  `list_required_factors_all_users`/`set_required_factors`.
- FastAPI `TestClient`: `/instellingen/factoren` met een geldige en een
  ongeldige (verzonnen) factornaam, controleren dat alleen de geldige
  wordt opgeslagen; `/account` toont de checkbox-lijst met de juiste
  aangevinkte staat.
- End-to-end: een signaal met een bekende breakdown-tekst, een gebruiker
  die één van de gefaalde factoren daarin verplicht heeft gesteld, en
  controleren dat zowel de kaart (`user_confirmed`) als de pushmelding-
  gate (`_fanout_confirmed_signal`) hem als niet-bevestigd behandelen
  ondanks een percentage boven zijn drempel.
- `winrate_for_user`: twee afgeronde signalen met hetzelfde percentage
  boven de drempel, één met een verplichte factor ✓, één ✗ — controleren
  dat alleen de eerste meetelt in `total`/`wins`/`losses` zodra de
  gebruiker die factor verplicht heeft gesteld, en dat beide meetellen
  zodra hij geen enkele factor verplicht heeft (ongewijzigd gedrag).
