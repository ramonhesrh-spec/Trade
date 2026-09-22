# Kritischere signaaltoetsing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HesPulse's technische toetsing zelf (niet de site eromheen, dat was de vorige herziening) kritischer en professioneler maken: vier concrete, elk apart beargumenteerde verbeteringen aan hoe een day-trading-signaal wel of niet bevestigt.

**Architecture:** Vier onafhankelijke uitbreidingen op de bestaande toetsingsketen in `app/signal_processor.py` (`process_day_trading_signal`) en `app/indicators.py` (`confirms_direction`), gedeeld door zowel het bericht-pad als de autonome marktscan (`app/market_scanner.py` roept dezelfde `process_day_trading_signal` aan, CLAUDE.md). Twee nieuwe harde eisen (risico/rendement, dagtrend), één nieuw geheugen-mechanisme (gefaalde zones), één nieuwe informatieve toevoeging (entry-zone-suggestie).

**Tech Stack:** Ongewijzigd — Python/FastAPI/SQLite, geen nieuwe dependencies.

**Spec:** Geen apart spec-document (gebruiker slaat die fase standaard over, direct door naar dit implementatieplan). Herkomst van elke beslissing staat per taak genoteerd, uit een brainstormronde deze sessie met expliciete keuzes van de product owner.

## Global Constraints

- `app/repo.py` is de ENIGE plek voor databasetoegang, nooit losse SQL elders.
- Schema-wijzigingen zijn altijd tweeledig: `CREATE TABLE IF NOT EXISTS`/kolom in `app/schema.sql` (verse installatie) ÉN een idempotente `ALTER TABLE ... ADD COLUMN` in `app/db.py:_migrate()` met een `PRAGMA table_info`-check (bestaande installatie). Een index op een kolom die `_migrate()` zelf toevoegt hoort in `_migrate()`, nooit in `schema.sql`.
- `app/signal_processor.py`'s `process_day_trading_signal` is de EN­IGE plek waar dagtrading-signalen daadwerkelijk getoetst worden; `app/market_scanner.py` roept deze functie rechtstreeks aan (CLAUDE.md, "gedeeld door zowel het bericht-pad als de autonome marktscan") — wijzigingen hier gelden voor beide paden zonder aparte duplicatie.
- Geen pytest-suite. Verificatie via scratch-database-scripts (`DATABASE_PATH=/tmp/scratch.db`) en voor UI-wijzigingen handmatige Playwright-verificatie tegen een lokale uvicorn-instantie.
- Comments leggen niet-vanzelfsprekende WAAROM uit (een eerdere bug, een bewuste afweging), nooit WAT de code doet.
- `hard_gates_ok` (kolom op `signals`) is de centrale plek waar ELKE harde eis (Uitgerektheid, BTC-trend, en nu ook Risico/rendement en Dagtrend) samenkomt — een nieuwe harde eis moet hierin meetellen, nooit een aparte parallelle "confirmed"-berekening ernaast bouwen, anders raakt `repo.user_confirmed()` (per-gebruiker drempelvergelijking, gebruikt op `/signalen` en de coin-pagina) los van wat er werkelijk gebeurde.

---

### Task 1: Risico/rendement als harde eis

**Herkomst:** brainstorm deze sessie, punt 4. Nu kan een steun/weerstand-niveau-gebaseerde stop de risico/rendement-verhouding stilzwijgend verslechteren (`risk.compute_stop_take_from_levels` staat al een ondergrens van 1:1 toe op het target-niveau) zonder dat iets dit tegenhoudt. Product owner koos: 1.5 tegen 1, alleen day-trading-signalen (swing-signalen, `compute_stop_take_from_levels` voor bron-niveaus, hebben al hun eigen 1:1-ondergrens-logica en blijven hier buiten beeld).

**Files:**
- Modify: `app/signal_processor.py` (`process_day_trading_signal`, na de bestaande `stop_take`-berekening rond regel 747)

**Interfaces:**
- Consumes: bestaande `stop_take.stop_loss`/`stop_take.take_profit`/`ind.price`, en de `confirmed`/`hard_gates_ok` die `indicators.confirms_direction` al teruggaf.
- Produces: geen nieuwe publieke functie — `confirmed`/`hard_gates_ok` worden lokaal aangescherpt vóór ze in `signal_data` terechtkomen, dus elke latere lezer (repo.insert_signal, /signalen, de coin-pagina) ziet vanzelf het eindresultaat.

- [ ] **Step 1: Nieuwe constante**

In `app/signal_processor.py`, bij de andere module-constanten (zoek `SWING_WATCH_MAX_AGE_DAYS`):

```python
# Onder deze verhouding is een setup geen goede trade meer, ongeacht hoeveel
# andere factoren wel kloppen — een niveau-gebaseerde stop
# (risk.compute_stop_take_from_levels) kan de verhouding laten zakken tot
# zijn eigen ondergrens van 1:1, dat is lager dan hier acceptabel is.
MIN_RISK_REWARD_RATIO = 1.5
```

- [ ] **Step 2: Verhouding berekenen en meenemen in hard_gates_ok**

Direct na de bestaande `stop_take = risk.compute_stop_take(...)` / `risk.compute_stop_take_from_levels(...)` if/else-blok (rond regel 747), vóór `context_note = _build_context_note(...)`:

```python
    risk_distance = abs(ind.price - stop_take.stop_loss)
    reward_distance = abs(stop_take.take_profit - ind.price)
    risk_reward_ratio = (reward_distance / risk_distance) if risk_distance else 0.0
    if risk_reward_ratio < MIN_RISK_REWARD_RATIO:
        hard_gates_ok = False
        confirmed = False
        reason += f" | ✗ Risico/rendement: {risk_reward_ratio:.1f} tegen 1, onder de ondergrens van {MIN_RISK_REWARD_RATIO}"
```

`hard_gates_ok`/`confirmed` zijn de twee waarden die `indicators.confirms_direction` net hierboven teruggaf (regel ~728: `confirmed, reason, pass_pct, hard_gates_ok = indicators.confirms_direction(...)`) — dit past ze in-place aan, `signal_data`'s latere `"technical_confirmed": int(confirmed)` en `"hard_gates_ok": int(hard_gates_ok)` pikken de aangepaste waarden vanzelf op omdat die regels pas ná dit blok lopen.

- [ ] **Step 3: Verifiëren met een throwaway script**

```bash
DATABASE_PATH=/tmp/scratch_rr.db python3 -c "
from app import db, risk
db.init_db()
# Long: entry 100, stop 98 (afstand 2), take 102 (afstand 2) -> 1:1, moet falen
st = risk.StopTake(stop_loss=98.0, take_profit=102.0)
entry = 100.0
risk_distance = abs(entry - st.stop_loss)
reward_distance = abs(st.take_profit - entry)
ratio = reward_distance / risk_distance
print('ratio', ratio, 'faalt (verwacht True):', ratio < 1.5)
"
```

Verwacht: `ratio 1.0 faalt (verwacht True): True`.

- [ ] **Step 4: Commit**

```bash
git add app/signal_processor.py
git commit -m "Risico/rendement onder 1.5 tegen 1 telt als harde eis, ongeacht andere factoren"
```

---

### Task 2: Dagtrend als altijd-actieve harde eis, met vlakke-markt-uitzondering

**Herkomst:** brainstorm deze sessie, punt 5. `indicators.check_daily_trend` bestaat al maar is nu een GEPOOLDE factor, alleen berekend als `ENABLE_ADVANCED_FACTORS` aan staat. Product owner koos: altijd berekenen (ook in de goedkope basisversie) en als harde eis behandelen — MAAR pas nadat er, net als bij BTC-trend (`indicators.btc_is_flat`), een vlakke-markt-uitzondering is: een coin zonder duidelijke eigen dagtrend mag niet hard geblokkeerd worden, dat zou een normale consolidatie voor een uitbraak onterecht wegfilteren.

**Belangrijke ontdekking tijdens onderzoek:** `indicators.btc_is_flat(btc_ind: Indicators) -> bool` is ondanks zijn naam al volledig coin-onafhankelijk (gebruikt alleen `ema9`/`ema21`/`atr` van het meegegeven `Indicators`-object). Hij kan dus rechtstreeks hergebruikt worden voor de dagtrend van een willekeurige coin, geen nieuwe functie nodig.

**Files:**
- Modify: `app/indicators.py` (`confirms_direction`, beide takken: basisversie én uitgebreide versie)
- Modify: `app/signal_processor.py` (`process_day_trading_signal` haalt de dagcandle nu altijd op, niet alleen in `compute_advanced_extra_factors`; `compute_advanced_extra_factors` verliest zijn eigen dagtrend-blok)

**Interfaces:**
- Consumes: bestaande `indicators.check_daily_trend`, `indicators.btc_is_flat`, `indicators.compute_indicators`.
- Produces: `confirms_direction(ind, direction, extra_factors=None, include_advanced=False, daily_trend_factor=None) -> tuple[bool, str, float, bool]` — nieuwe optionele parameter `daily_trend_factor: Optional[tuple[str, bool, str]]`, een kant-en-klare `(name, ok, detail)`-tuple zoals elke andere factor, of `None` als de dagcandle niet opgehaald kon worden (fail-closed, zie Step 2).

- [ ] **Step 1: `compute_advanced_extra_factors` verliest zijn eigen dagtrend-blok**

In `app/signal_processor.py`, verwijder uit `compute_advanced_extra_factors` (rond regel 623-626) het blok:

```python
    try:
        daily_df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, "1d")
        daily_ind = indicators.compute_indicators(daily_df)
        factors.append(indicators.check_daily_trend(direction, daily_ind))
```

(inclusief de bijbehorende `except`-tak eronder als die alleen dit blok afving — lees de functie in zijn geheel om zeker te zijn welke regels precies bij dit blok horen, er staan meerdere try/except-blokken na elkaar in deze functie). Dagtrend wordt vanaf nu altijd apart berekend, zie Step 2, niet meer als onderdeel van de uitgebreide factorenset.

- [ ] **Step 2: Dagcandle altijd ophalen in `process_day_trading_signal`**

In `app/signal_processor.py`, vlak vóór de bestaande `extra_factors = None` / `if config.ENABLE_ADVANCED_FACTORS:`-blok (rond regel 719-724):

```python
    daily_trend_factor = None
    try:
        daily_df = await asyncio.to_thread(exchange.fetch_ohlcv, interp.coin, "1d")
        daily_ind = indicators.compute_indicators(daily_df)
        # Net als BTC-trend (indicators.btc_is_flat): een coin zonder
        # duidelijke eigen dagtrend mag niet hard geblokkeerd worden, dat
        # zou een normale consolidatie vlak voor een uitbraak onterecht
        # wegfilteren. btc_is_flat is ondanks zijn naam coin-onafhankelijk
        # (alleen ema9/ema21/atr), dus rechtstreeks herbruikbaar hier.
        if not indicators.btc_is_flat(daily_ind):
            daily_trend_factor = indicators.check_daily_trend(interp.direction, daily_ind)
    except Exception:
        logger.exception("Dagtrend kon niet berekend worden voor %s", interp.coin)
        daily_trend_factor = ("Daily-trend", False, "kon niet opgehaald worden, telt als niet bevestigd")
```

- [ ] **Step 3: Doorgeven aan `confirms_direction`**

Pas de bestaande aanroep (rond regel 728) aan:

```python
    confirmed, reason, pass_pct, hard_gates_ok = indicators.confirms_direction(
        ind, interp.direction, extra_factors=extra_factors, include_advanced=config.ENABLE_ADVANCED_FACTORS,
        daily_trend_factor=daily_trend_factor,
    )
```

- [ ] **Step 4: `confirms_direction` behandelt dagtrend als harde eis in BEIDE takken**

In `app/indicators.py`, wijzig de signatuur:

```python
def confirms_direction(
    ind: Indicators, direction: str, extra_factors: list[tuple[str, bool, str]] | None = None,
    include_advanced: bool = False, daily_trend_factor: tuple[str, bool, str] | None = None,
) -> tuple[bool, str, float, bool]:
```

In de basisversie-tak (na de bestaande `extension_ok = next(...)` / `core_passed = sum(...)` / `pass_pct = ...` regels, vóór `hard_gates_ok = extension_ok`):

```python
        daily_trend_ok = daily_trend_factor[1] if daily_trend_factor is not None else True
        if daily_trend_factor is not None:
            breakdown += f" | {'✓' if daily_trend_factor[1] else '✗'} {daily_trend_factor[0]}: {daily_trend_factor[2]}"
        hard_gates_ok = extension_ok and daily_trend_ok
        confirmed = hard_gates_ok and core_passed >= BASIC_CONFIRM_MIN_PASSED
        return confirmed, breakdown, pass_pct, hard_gates_ok
```

(Dit vervangt de bestaande `hard_gates_ok = extension_ok` / `confirmed = extension_ok and core_passed >= BASIC_CONFIRM_MIN_PASSED` regels — `breakdown` was hierboven al opgebouwd uit `factors`, dagtrend zat daar nog niet in omdat hij geen deel is van `basic_factors()`, vandaar de losse toevoeging hier.)

In de uitgebreide-versie-tak: voeg `daily_trend_factor` toe aan `factors` vóórdat `breakdown` opgebouwd wordt (rond regel 1266, waar `extra_factors` al wordt toegevoegd):

```python
    if extra_factors:
        factors.extend(extra_factors)
    if daily_trend_factor is not None:
        factors.append(daily_trend_factor)
```

En reken hem mee als harde eis, net als BTC-trend (rond regel 1277-1284):

```python
    btc_trend_ok = next((ok for name, ok, _ in factors if name == "BTC-trend"), True)
    daily_trend_ok = next((ok for name, ok, _ in factors if name == "Daily-trend"), True)

    other_factors = [f for f in factors if f[0] not in ("Uitgerektheid", "BTC-trend", "Daily-trend")]
    passed = sum(1 for _, ok, _ in other_factors if ok)
    pass_pct = (passed / len(other_factors)) * 100 if other_factors else 100.0
    hard_gates_ok = extension_ok and btc_trend_ok and daily_trend_ok
    confirmed = hard_gates_ok and pass_pct >= CONFIRM_THRESHOLD * 100
    return confirmed, breakdown, pass_pct, hard_gates_ok
```

(Let op: in de uitgebreide versie stond `check_daily_trend` vroeger AL in `factors` via het nu-verwijderde blok in `compute_advanced_extra_factors` — met Task 2 Step 1 verwijderd, komt hij hier terug via de nieuwe `daily_trend_factor`-parameter, dus geen dubbeltelling.)

- [ ] **Step 5: Docstring bijwerken**

`confirms_direction`'s docstring noemt nu nog maar twee harde eisen (Uitgerektheid, BTC-trend) en een verouderd `tuple[bool, str]`-returntype in de functiehandtekening zelf (een al bekend, apart genoteerd punt uit een eerdere review, zie de ledger-geschiedenis) — voeg Dagtrend toe aan de opsomming van harde eisen in de docstring-tekst, in dezelfde stijl als de bestaande BTC-trend-alinea.

- [ ] **Step 6: Verifiëren met een throwaway script**

```bash
DATABASE_PATH=/tmp/scratch_dt.db python3 -c "
from app import indicators

def make_ind(price=100.0, ema9=101.0, ema21=99.0, atr=1.0, rsi=55.0, macd=0.5, macd_signal=0.2, volume_ratio=1.2, volume_percentile=60.0, adx=20.0, adx_pos=25.0, adx_neg=10.0, atr_avg20=1.0):
    return indicators.Indicators(price=price, rsi=rsi, macd=macd, macd_signal=macd_signal, volume_ratio=volume_ratio, volume_percentile=volume_percentile, ema9=ema9, ema21=ema21, atr=atr, atr_avg20=atr_avg20, adx=adx, adx_pos=adx_pos, adx_neg=adx_neg)

ind = make_ind()
# Dagtrend tegen de trade in (long, maar EMA9 < EMA21 op daily), duidelijke trend (niet vlak)
daily_ind_against = make_ind(ema9=95.0, ema21=105.0, atr=1.0)
factor = indicators.check_daily_trend('long', daily_ind_against)
print('factor:', factor)
confirmed, breakdown, pass_pct, hard_gates_ok = indicators.confirms_direction(ind, 'long', daily_trend_factor=factor)
print('basisversie met tegen-dagtrend, hard_gates_ok (verwacht False):', hard_gates_ok)

# Vlakke dagtrend (EMA9/EMA21 heel dicht bij elkaar t.o.v. ATR) -> geen factor meegegeven (zoals signal_processor zou doen)
confirmed2, breakdown2, pass_pct2, hard_gates_ok2 = indicators.confirms_direction(ind, 'long', daily_trend_factor=None)
print('basisversie zonder dagtrend-factor (vlak of niet opgehaald), hard_gates_ok (verwacht True, want extension_ok):', hard_gates_ok2)
"
```

Verwacht: eerste `hard_gates_ok` is `False`, tweede is `True` (afhankelijk van of Uitgerektheid in de synthetische `ind` toevallig ok is — controleer de printregel, niet blind aannemen).

- [ ] **Step 7: Commit**

```bash
git add app/indicators.py app/signal_processor.py
git commit -m "Dagtrend van de coin zelf altijd een harde eis, met vlakke-markt-uitzondering zoals BTC-trend"
```

---

### Task 3: Schema en repo-functies voor geheugen van gefaalde zones

**Herkomst:** brainstorm deze sessie, punt 6. Product owner koos: 3 dagen afkoeling, alleen zelf-gedetecteerde steun/weerstand-zones (niet community-niveaus uit een doorgestuurd bericht).

**Ontwerpbeslissing (genomen tijdens onderzoek, niet los voorgelegd — kosten-inschatting was te hoog om apart te bevragen, dit is de goedkoopste correcte aanpak):** in plaats van de volledige `SRZone` te koppelen aan een signaal, wordt alleen de dichtstbijzijnde zone-*rand* (een los prijsgetal, zelfde `edges`-berekening als `indicators.check_sr_zone` al intern doet) opgeslagen op het signaal. Bij een latere stop-loss-uitkomst wordt die ene prijs teruggekoppeld naar een nieuwe, kleine `sr_zone_failures`-tabel. Een toekomstig signaal vergelijkt zijn eigen dichtstbijzijnde zone-rand tegen recente mislukkingen, met dezelfde ATR-tolerantie-stijl als `market_scanner._same_breakout_retest_zone` al gebruikt voor een vergelijkbaar "is dit dezelfde zone"-vraagstuk.

**Files:**
- Modify: `app/schema.sql` (nieuwe kolom `signals.nearest_sr_zone_price`, nieuwe tabel `sr_zone_failures`)
- Modify: `app/db.py` (`_migrate()`: idempotente ALTER TABLE + CREATE TABLE + index)
- Modify: `app/repo.py` (nieuwe functies)

**Interfaces:**
- Consumes: bestaand `db.now_iso()`, bestaand migratiepatroon in `_migrate()`.
- Produces:
  - `repo.record_sr_zone_failure(coin: str, direction: str, zone_price: float, failed_at: str) -> None`
  - `repo.recent_sr_zone_failure(coin: str, direction: str, zone_price: float, atr: float, within_days: int = 3) -> bool`
  - `signals.nearest_sr_zone_price` beschikbaar via `repo.insert_signal(data)` (nieuwe optionele sleutel `"nearest_sr_zone_price"` in de `data`-dict) en via elke bestaande `SELECT s.*`/`_JOURNAL_SELECT`-lezer (geen aparte functie nodig, kolom komt vanzelf mee).

- [ ] **Step 1: Schema — nieuwe kolom en tabel**

In `app/schema.sql`, in de `CREATE TABLE IF NOT EXISTS signals (...)`-definitie, direct na `auto_outcome_at TEXT,`:

```sql
    -- Dichtstbijzijnde zelf-gedetecteerde steun/weerstand-zonerand aan de
    -- stop-kant van de prijs op het moment van dit signaal (los prijsgetal,
    -- niet de hele zone) — NULL als er geen bruikbare zone dichtbij was.
    -- Gebruikt om terug te koppelen naar sr_zone_failures zodra dit signaal
    -- als stop_loss resolvt, zie app/level_check.py check_signal_outcomes.
    nearest_sr_zone_price REAL,
```

Nieuwe tabel, aan het einde van `schema.sql` (na de bestaande tabellen, vóór eventuele losse `CREATE INDEX`-statements die niet aan een migratie-kolom hangen):

```sql
-- Geheugen voor zelf-gedetecteerde steun/weerstand-zones die recent een
-- stop loss veroorzaakten: een zone die net bewees onbetrouwbaar te zijn
-- mag niet morgen alweer een nieuw signaal bevestigen alsof er niks
-- gebeurd is. Community-niveaus (uit een doorgestuurd bericht) staan hier
-- expres niet in, die komen van een externe bron, niet van HesPulse's
-- eigen detectie.
CREATE TABLE IF NOT EXISTS sr_zone_failures (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin TEXT NOT NULL,
    direction TEXT NOT NULL,
    zone_price REAL NOT NULL,
    failed_at TEXT NOT NULL
);
```

- [ ] **Step 2: Migratie voor bestaande databases**

In `app/db.py`, in `_migrate()`, volg het bestaande patroon (zoek de meest recente `PRAGMA table_info(signals)`-check als voorbeeld, bijvoorbeeld die voor `auto_outcome`):

```python
        cursor.execute("PRAGMA table_info(signals)")
        signal_columns = {row[1] for row in cursor.fetchall()}
        if "nearest_sr_zone_price" not in signal_columns:
            cursor.execute("ALTER TABLE signals ADD COLUMN nearest_sr_zone_price REAL")
```

(Als er al een `signal_columns`-variabele bestaat uit een eerdere check verderop in dezelfde functie, hergebruik die in plaats van `PRAGMA table_info(signals)` een tweede keer aan te roepen — lees `_migrate()` in zijn geheel om dit te bepalen, er is eerder in deze sessie al eens een reviewbevinding geweest over een overbodige herhaalde `PRAGMA table_info`-aanroep.)

De nieuwe tabel zelf heeft geen migratie nodig (`CREATE TABLE IF NOT EXISTS` in `schema.sql` volstaat voor een bestaande database net zo goed als voor een verse, want het is een heel nieuwe tabel, geen kolom op een bestaande). Voeg wel een index toe in `_migrate()`, buiten elke kolom-guard (zelfde patroon als `idx_signals_auto_outcome_pending`, die ook onvoorwaardelijk aangemaakt wordt):

```python
        cursor.execute(
            "CREATE INDEX IF NOT EXISTS idx_sr_zone_failures_lookup "
            "ON sr_zone_failures (coin, direction, failed_at)"
        )
```

- [ ] **Step 3: Repo-functies**

In `app/repo.py`, in de buurt van andere signalen-gerelateerde functies (bijvoorbeeld na `mark_signal_auto_outcome`):

```python
def record_sr_zone_failure(coin: str, direction: str, zone_price: float, failed_at: str) -> None:
    """Onthoudt dat een signaal gebaseerd op deze zelf-gedetecteerde zone
    de stop loss raakte, zodat een toekomstig signaal vlakbij dezelfde zone
    een tijdje overgeslagen kan worden — zie recent_sr_zone_failure."""
    with db.session() as conn:
        conn.execute(
            "INSERT INTO sr_zone_failures (coin, direction, zone_price, failed_at) VALUES (?, ?, ?, ?)",
            (coin, direction, zone_price, failed_at),
        )


def recent_sr_zone_failure(coin: str, direction: str, zone_price: float, atr: float, within_days: int = 3) -> bool:
    """Faalde een zone die dicht genoeg bij zone_price ligt (binnen 0.5x
    ATR, dezelfde grootteorde tolerantie als market_scanner's
    _same_breakout_retest_zone voor een vergelijkbaar 'is dit dezelfde
    zone'-vraagstuk) al eerder binnen within_days dagen, voor dezelfde coin
    en richting?"""
    if not atr:
        return False
    tolerance = 0.5 * atr
    cutoff = (datetime.now(timezone.utc) - timedelta(days=within_days)).isoformat()
    with db.session() as conn:
        rows = conn.execute(
            """SELECT zone_price FROM sr_zone_failures
               WHERE coin = ? AND direction = ? AND failed_at >= ?""",
            (coin, direction, cutoff),
        ).fetchall()
    return any(abs(row["zone_price"] - zone_price) <= tolerance for row in rows)
```

Controleer of `datetime`/`timezone`/`timedelta` al geïmporteerd zijn bovenaan `app/repo.py` (waarschijnlijk wel, andere functies in dit bestand gebruiken tijdstempels op dezelfde manier) — zo niet, toevoegen aan de bestaande import-regel, geen nieuwe losse import-statement.

Voeg `"nearest_sr_zone_price"` toe aan `insert_signal`'s `fields`-lijst (rond regel 905-910):

```python
    fields = [
        "message_id", "coin", "direction", "category", "price", "rsi", "macd",
        "macd_signal", "volume_ratio", "ema9", "ema21", "atr", "atr_avg20", "adx",
        "technical_confirmed", "pass_pct", "hard_gates_ok", "confidence", "reason", "stop_loss", "take_profit",
        "context_note", "is_practice", "plain_explanation", "trade_type", "nearest_sr_zone_price",
    ]
```

(`values`-lijst comprehension hoeft niet aangepast: die valt voor onbekende velden al terug op `data.get(f)`, en `data.get("nearest_sr_zone_price")` geeft correct `None` terug als de sleutel ontbreekt.)

- [ ] **Step 4: Verifiëren met een throwaway script**

```bash
rm -f /tmp/scratch_zonefail.db
DATABASE_PATH=/tmp/scratch_zonefail.db python3 -c "
from datetime import datetime, timedelta, timezone
from app import db, repo
db.init_db()

# Fresh install: kolom en tabel moeten bestaan
with db.session() as conn:
    cols = {row['name'] for row in conn.execute('PRAGMA table_info(signals)').fetchall()}
    assert 'nearest_sr_zone_price' in cols, 'kolom ontbreekt op verse database'
    conn.execute('SELECT * FROM sr_zone_failures LIMIT 1')
print('schema OK')

repo.record_sr_zone_failure('BTC', 'long', 100.0, datetime.now(timezone.utc).isoformat())
assert repo.recent_sr_zone_failure('BTC', 'long', 100.3, atr=1.0, within_days=3) is True, 'binnen tolerantie had True moeten zijn'
assert repo.recent_sr_zone_failure('BTC', 'long', 150.0, atr=1.0, within_days=3) is False, 'ver weg had False moeten zijn'
assert repo.recent_sr_zone_failure('ETH', 'long', 100.0, atr=1.0, within_days=3) is False, 'andere coin had False moeten zijn'
old = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
repo.record_sr_zone_failure('SOL', 'short', 50.0, old)
assert repo.recent_sr_zone_failure('SOL', 'short', 50.0, atr=1.0, within_days=3) is False, 'te oud had False moeten zijn'
print('alle checks OK')
"
rm -f /tmp/scratch_zonefail.db
```

Ook een migratie-check tegen een DB gebouwd van vóór deze taak (kopieer het patroon dat eerdere taken deze sessie al gebruikten: bouw eerst met `git show <commit-vóór-deze-taak>:app/schema.sql`, migreer dan met de huidige `db.init_db()`).

- [ ] **Step 5: Commit**

```bash
git add app/schema.sql app/db.py app/repo.py
git commit -m "Schema en repo-functies voor geheugen van gefaalde zelf-gedetecteerde zones"
```

---

### Task 4: Zone-cooldown wiring — vastleggen bij signaal, checken bij toetsing, registreren bij stop loss

**Files:**
- Modify: `app/signal_processor.py` (`process_day_trading_signal`: dichtstbijzijnde zone-rand bepalen, cooldown checken, opslaan in `signal_data`)
- Modify: `app/level_check.py` (`check_signal_outcomes`: bij een stop_loss-uitkomst de zone-mislukking registreren)
- Modify: `app/repo.py` (`list_unresolved_signals_with_levels` moet `nearest_sr_zone_price` ook teruggeven)

**Interfaces:**
- Consumes: `repo.recent_sr_zone_failure`, `repo.record_sr_zone_failure` (Task 3).

- [ ] **Step 1: Dichtstbijzijnde zone-rand bepalen in `process_day_trading_signal`**

Vlak vóór de bestaande `confirmed, reason, pass_pct, hard_gates_ok = indicators.confirms_direction(...)`-aanroep (rond regel 728), waar `zones` (uit `indicators.detect_sr_zones(df)`) al beschikbaar is:

```python
    edges = [edge for zone in zones for edge in (zone.price_low, zone.price_high)]
    if interp.direction.lower() == "long":
        zone_candidates = [e for e in edges if e < ind.price]
        nearest_sr_zone_price = max(zone_candidates) if zone_candidates else None
    else:
        zone_candidates = [e for e in edges if e > ind.price]
        nearest_sr_zone_price = min(zone_candidates) if zone_candidates else None
```

(Dit is dezelfde `edges`/kant-bepaling-logica als `indicators.check_sr_zone` intern al gebruikt, hier apart herhaald in plaats van `check_sr_zone`'s eigen returnwaarde uit te breiden — dat zou zijn bestaande `(name, ok, detail)`-vorm inconsistent maken met elke andere factor-functie in dit bestand, en de twee aanroepers van `check_sr_zone` (`signal_processor.py`, `scripts/backtest_factors.py`) hoeven dan niet aangepast te worden.)

- [ ] **Step 2: Cooldown checken en meenemen in hard_gates_ok**

Direct na de `confirms_direction`-aanroep, vóór de Task 1-code (risico/rendement-check) — de volgorde tussen Task 1 en Task 4's harde eisen maakt inhoudelijk niet uit, maar zet deze check bij de andere net-uitgevoerde harde-eis-aanpassingen zodat ze bij elkaar in de leescode staan:

```python
    if nearest_sr_zone_price is not None and repo.recent_sr_zone_failure(
        interp.coin, interp.direction, nearest_sr_zone_price, ind.atr,
    ):
        hard_gates_ok = False
        confirmed = False
        reason += " | ✗ Zone recent gefaald: deze steun/weerstand-zone veroorzaakte de laatste 3 dagen al een stop loss"
```

- [ ] **Step 3: Opslaan in `signal_data`**

Voeg toe aan de bestaande `signal_data`-dict (rond regel 780-805):

```python
        "nearest_sr_zone_price": nearest_sr_zone_price,
```

- [ ] **Step 4: `list_unresolved_signals_with_levels` geeft de nieuwe kolom mee**

In `app/repo.py`, wijzig de `SELECT` in `list_unresolved_signals_with_levels` (rond regel 1681-1687):

```python
            """SELECT id, coin, direction, stop_loss, take_profit, created_at, nearest_sr_zone_price
               FROM signals
               WHERE auto_outcome IS NULL
                 AND stop_loss IS NOT NULL
                 AND take_profit IS NOT NULL
                 AND is_practice = 0"""
```

- [ ] **Step 5: Zone-mislukking registreren bij stop_loss in `check_signal_outcomes`**

In `app/level_check.py`, in `check_signal_outcomes` (rond regel 101-127), waar nu `repo.mark_signal_auto_outcome(...)` wordt aangeroepen na een `hit`, voeg ernaast toe:

```python
        outcome = "take_profit" if hit == "take profit" else "stop_loss"
        occurred_at = datetime.now(timezone.utc).isoformat()
        repo.mark_signal_auto_outcome(signal["id"], outcome, occurred_at)
        if outcome == "stop_loss" and signal["nearest_sr_zone_price"] is not None:
            repo.record_sr_zone_failure(
                signal["coin"], signal["direction"], signal["nearest_sr_zone_price"], occurred_at,
            )
```

(Lees de bestaande functie eerst in zijn geheel om te zien of `occurred_at`/een vergelijkbare tijdstempel al lokaal bestaat als variabele — Task 16 van de vorige sessie's plan voegde hier al vervaltermijn-logica toe met een eigen `SIGNAL_MAX_AGE_DAYS`-check, hergebruik dezelfde tijdstempel-variabele als die al berekend wordt in plaats van een tweede `datetime.now(timezone.utc)`-aanroep toe te voegen als dat vermijdbaar is.)

- [ ] **Step 6: Verifiëren met een throwaway script**

```bash
rm -f /tmp/scratch_zonewire.db
DATABASE_PATH=/tmp/scratch_zonewire.db python3 -c "
import asyncio
from unittest.mock import patch
from app import db, repo, level_check
db.init_db()

signal_id = repo.insert_signal({
    'coin': 'BTC', 'direction': 'long', 'category': 'day_trading',
    'price': 100.0, 'stop_loss': 95.0, 'take_profit': 110.0,
    'confidence': 'hoog vertrouwen', 'technical_confirmed': 1,
    'pass_pct': 80.0, 'hard_gates_ok': 1, 'nearest_sr_zone_price': 95.5,
    'reason': 'test', 'context_note': None, 'is_practice': 0, 'plain_explanation': None,
})

with patch('app.exchange.fetch_last_price', return_value=94.0):
    asyncio.run(level_check.check_signal_outcomes())

sig = repo.get_signal(signal_id)
print('auto_outcome (verwacht stop_loss):', sig['auto_outcome'])
assert sig['auto_outcome'] == 'stop_loss'
assert repo.recent_sr_zone_failure('BTC', 'long', 95.5, atr=1.0, within_days=3) is True, 'zone-mislukking had geregistreerd moeten zijn'
print('OK')
"
rm -f /tmp/scratch_zonewire.db
```

(Pas de `patch`-aanroep aan als `check_signal_outcomes` de live prijs anders ophaalt dan `exchange.fetch_last_price` — lees de functie na Task 16's eerdere wijzigingen om het exacte huidige aanroeppad te bevestigen vóór dit script geschreven wordt.)

- [ ] **Step 7: Commit**

```bash
git add app/signal_processor.py app/level_check.py app/repo.py
git commit -m "Zone-cooldown: recent gefaalde zelf-gedetecteerde zone blokkeert een nieuw signaal 3 dagen"
```

---

### Task 5: Slimmere entry-zone-suggestie — berekenen en opslaan

**Herkomst:** brainstorm deze sessie, punt 2. Product owner koos expliciet: ALLEEN als informatieve suggestie, de live prijs blijft de echte entry voor sizing/journaal/trackrecord. Geen wijziging aan hoe risico/positiegrootte berekend wordt.

**Files:**
- Modify: `app/schema.sql` (nieuwe kolommen `signals.suggested_entry_low`, `signals.suggested_entry_high`)
- Modify: `app/db.py` (`_migrate()`)
- Modify: `app/repo.py` (`insert_signal`'s `fields`-lijst)
- Modify: `app/signal_processor.py` (`process_day_trading_signal`: favoriete zone bepalen)

**Interfaces:**
- Consumes: `zones` (`indicators.detect_sr_zones`), al beschikbaar in `process_day_trading_signal`.
- Produces: `signals.suggested_entry_low`/`suggested_entry_high` (beide `NULL` als er geen bruikbare zone was), beschikbaar via elke bestaande `SELECT s.*`/`_JOURNAL_SELECT`-lezer.

- [ ] **Step 1: Schema**

In `app/schema.sql`, in de `signals`-tabel, na de `nearest_sr_zone_price`-kolom uit Task 3:

```sql
    -- Realistische, iets betere entry-zone dan de live prijs, gebaseerd op
    -- de dichtstbijzijnde zelf-gedetecteerde steun/weerstand-zone tussen de
    -- entry en de stop loss — PUUR informatief, telt nergens mee in
    -- sizing/journaal/trackrecord (product owner: live prijs blijft de
    -- echte entry). Beide NULL als er geen bruikbare zone was.
    suggested_entry_low REAL,
    suggested_entry_high REAL,
```

- [ ] **Step 2: Migratie**

In `app/db.py`, `_migrate()`, zelfde `signal_columns`-check als Task 3 Step 2 hergebruiken (niet opnieuw `PRAGMA table_info(signals)` aanroepen als die variabele al in scope is):

```python
        if "suggested_entry_low" not in signal_columns:
            cursor.execute("ALTER TABLE signals ADD COLUMN suggested_entry_low REAL")
        if "suggested_entry_high" not in signal_columns:
            cursor.execute("ALTER TABLE signals ADD COLUMN suggested_entry_high REAL")
```

- [ ] **Step 3: `insert_signal`'s fields-lijst**

In `app/repo.py`, voeg toe aan de `fields`-lijst uit Task 3 Step 3:

```python
        "context_note", "is_practice", "plain_explanation", "trade_type", "nearest_sr_zone_price",
        "suggested_entry_low", "suggested_entry_high",
```

- [ ] **Step 4: Favoriete zone bepalen in `process_day_trading_signal`**

Direct ná Task 4 Step 1's `edges`/`nearest_sr_zone_price`-blok (ze hergebruiken dezelfde `zones`/`edges`):

```python
    # Een bruikbare entry-zone ligt tussen de huidige prijs en de stop
    # loss (in het voordeel van de trade: dichter bij de stop dan de
    # huidige prijs bij long is een BETERE, niet slechtere, entry — bij
    # short andersom), en is dus nooit voorbij de stop loss zelf.
    if interp.direction.lower() == "long":
        favorable = [z for z in zones if stop_take.stop_loss < z.price_low < ind.price]
        best_zone = max(favorable, key=lambda z: z.price_high) if favorable else None
    else:
        favorable = [z for z in zones if ind.price < z.price_high < stop_take.stop_loss]
        best_zone = min(favorable, key=lambda z: z.price_low) if favorable else None
    suggested_entry_low = best_zone.price_low if best_zone else None
    suggested_entry_high = best_zone.price_high if best_zone else None
```

Let op: dit blok gebruikt `stop_take`, die pas verderop in de functie berekend wordt (rond regel 736-750, ná de plek waar Task 4 Step 1 zit). Plaats dit blok daarom NA de `stop_take`-berekening, niet direct na Task 4 Step 1 — pas het commentaar/de volgorde in de brief zelf aan zodat de daadwerkelijke implementatie logisch na `stop_take` komt, ook al staan Task 4 en Task 5 als losse taken beschreven.

Voeg toe aan `signal_data` (naast `"nearest_sr_zone_price"` uit Task 4 Step 3):

```python
        "suggested_entry_low": suggested_entry_low,
        "suggested_entry_high": suggested_entry_high,
```

- [ ] **Step 5: Verifiëren met een throwaway script**

```bash
DATABASE_PATH=/tmp/scratch_entry.db python3 -c "
from app.indicators import SRZone

class FakeStopTake:
    def __init__(self, stop_loss, take_profit):
        self.stop_loss = stop_loss
        self.take_profit = take_profit

# Long: prijs 100, stop 90. Een zone tussen 90 en 100 is favorable.
zones = [SRZone(price_low=94.0, price_high=96.0, touches=3), SRZone(price_low=80.0, price_high=85.0, touches=2)]
stop_take = FakeStopTake(stop_loss=90.0, take_profit=115.0)
price = 100.0
favorable = [z for z in zones if stop_take.stop_loss < z.price_low < price]
best_zone = max(favorable, key=lambda z: z.price_high) if favorable else None
print('beste zone (verwacht 94.0-96.0, niet de 80-85 zone die voorbij de stop ligt qua relevantie):', best_zone)
assert best_zone.price_low == 94.0
print('OK')
"
```

(Controleer `SRZone`'s exacte veldnamen/constructor-signatuur in `app/indicators.py` vóór dit script geschreven wordt — dit voorbeeld gaat uit van `price_low`/`price_high`/`touches`, gebaseerd op eerder gebruik elders in deze sessie, maar verifieer dit tegen de daadwerkelijke dataclass-definitie.)

- [ ] **Step 6: Commit**

```bash
git add app/schema.sql app/db.py app/repo.py app/signal_processor.py
git commit -m "Entry-zone-suggestie berekenen en opslaan, puur informatief naast de live-prijs-entry"
```

---

### Task 6: Entry-zone-suggestie tonen — melding en site

**Files:**
- Modify: `app/signal_processor.py` (pushmelding-body voor day-trading-signalen)
- Modify: `web/templates/_macros.html` (`signal_card`-macro)

**Interfaces:**
- Consumes: `entry.suggested_entry_low`/`suggested_entry_high` (Task 5), al beschikbaar via `_JOURNAL_SELECT`/`SELECT s.*` op elke plek waar `signal_card` al gebruikt wordt (`/signalen`, coin-pagina).

- [ ] **Step 1: Pushmelding-body**

Zoek in `app/signal_processor.py` waar de `body`-tekst voor een day-trading-pushmelding wordt opgebouwd (zoek `f"Entry {signal_data['price']:.4f} · Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}"` of vergelijkbaar, er zijn meerdere bijna-identieke plekken in dit bestand voor het bericht-pad en de swing-melding — pas ALLEEN de day-trading-melding aan, niet de swing-melding, die heeft geen `suggested_entry_low/high`). Voeg een optionele regel toe:

```python
    entry_zone_note = (
        f" · Mogelijk betere entry: {suggested_entry_low:.4f}–{suggested_entry_high:.4f}"
        if suggested_entry_low is not None else ""
    )
    body = f"Entry {signal_data['price']:.4f} · Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}{entry_zone_note}"
```

(`suggested_entry_low`/`suggested_entry_high` zijn lokale variabelen uit Task 5 Step 4, binnen bereik van dezelfde functie — als de melding-opbouw in een aparte functie zit die deze twee niet meekrijgt, geef ze door als parameter in plaats van een globale/nonlocal te forceren.)

- [ ] **Step 2: `signal_card`-macro**

In `web/templates/_macros.html`, in de `signal_card`-macro (uit een eerdere sessie, toont nu coin/richting/percentage/niveaus), voeg toe na de bestaande niveaus-regel:

```html
  {% if entry.suggested_entry_low is not none %}
  <div class="signal-card-entry-zone muted">
    Mogelijk betere entry: {{ "%.4f"|format(entry.suggested_entry_low) }}–{{ "%.4f"|format(entry.suggested_entry_high) }}
  </div>
  {% endif %}
```

- [ ] **Step 3: Handmatige Playwright-verificatie**

Bezoek `/signalen` met een testsignaal dat een `suggested_entry_low/high` heeft (scratch-database), controleer dat de regel verschijnt; en met een signaal zonder (`None`), controleer dat er niks extra's staat.

- [ ] **Step 4: Commit**

```bash
git add app/signal_processor.py web/templates/_macros.html
git commit -m "Entry-zone-suggestie zichtbaar in pushmelding en op signaalkaarten"
```

---

### Task 7: Volledige regressie en push

**Files:** geen nieuwe, alleen verificatie.

- [ ] **Step 1: Scratch-database volledige doorloop van alle vier verbeteringen samen**

Bouw één scratch-script dat een synthetisch signaal door `signal_processor`'s nieuwe logica haalt (met gemockte `exchange`-aanroepen, zelfde patroon als Task 4 Step 6) en controleert dat:
- Een slechte risico/rendement-verhouding het signaal afwijst (Task 1).
- Een tegen-de-dagtrend-in signaal met een duidelijke (niet-vlakke) dagtrend wordt afgewezen, maar NIET als de dagtrend vlak is (Task 2).
- Een signaal vlakbij een recent gefaalde zone wordt afgewezen (Task 4).
- Een `suggested_entry_low/high` correct wordt opgeslagen als er een bruikbare zone is (Task 5/6).

- [ ] **Step 2: Grep-controle**

```bash
grep -n "daily_trend_factor" app/indicators.py app/signal_processor.py
grep -n "nearest_sr_zone_price\|suggested_entry_low\|suggested_entry_high" app/schema.sql app/repo.py
```

Elke hit moet bewust zijn, geen half afgemaakte aanroep zonder tegenhanger.

- [ ] **Step 3: `market_scanner.py` blijft werken**

`app/market_scanner.py` roept `process_day_trading_signal` rechtstreeks aan (CLAUDE.md) — controleer dat er geen aparte, oudere aanroep van `confirms_direction` of `compute_advanced_extra_factors` in `market_scanner.py` zelf staat die door Task 2's wijzigingen zou breken (er is al een korte `confirms_direction(ind, direction)`-precheck met standaardwaarden in dit bestand, die hoeft NIET aangepast te worden met `daily_trend_factor` — het is een goedkope, niet-authoritatieve voorfilter, de echte toetsing loopt via `process_day_trading_signal`).

- [ ] **Step 4: Push**

```bash
git push
```
