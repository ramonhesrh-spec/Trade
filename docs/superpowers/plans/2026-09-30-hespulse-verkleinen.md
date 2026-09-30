# HesPulse verkleinen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vervang de onbeperkt groeiende coinlijst door een vaste lijst van 7
coins met een kostenfilter op Discord-berichten, en schrap drie ongebruikte
of nauwelijks zichtbare features (nieuwe swing-signalen, de aparte
narrative-melding+dashboard-blok, nieuwe prop-evaluatie-runs) terwijl
bestaande data en de narrative-context-vergelijking bij dagtradingsignalen
intact blijven — inclusief het alsnog zichtbaar maken van die
context-vergelijking in de pushmelding, waar hij momenteel onzichtbaar is.

**Architecture:** Eén nieuwe constante (`FIXED_COINS`) met een enkel
handhavingspunt in `repo.add_coin_if_new`, een eenmalige migratie die
bestaande coins buiten de lijst deactiveert, en een tweetraps-filter vóór en
ná de Anthropic-interpretatie van een Discord-bericht. De drie
ongein-verwijderingen zijn elk een gerichte, losse wijziging die alleen het
AANMAKEN van nieuwe rijen stopt (of, bij narrative, alleen de melding en het
losse dashboard-blok) — leesroutes en bestaande data blijven overal
ongewijzigd.

**Tech Stack:** Python 3, SQLite (via `app/db.py`), FastAPI + Jinja2
(`web/main.py` + `web/templates/`).

**Spec:** `docs/superpowers/specs/2026-09-30-hespulse-verkleinen-design.md`

## Global Constraints

- `app/repo.py` is de enige plek die de database aanraakt.
- Schemawijzigingen horen zowel in `app/schema.sql` (`CREATE TABLE IF NOT
  EXISTS`, voor een verse database) als in `app/db.py::_migrate()` met een
  `PRAGMA table_info`-guard (voor een bestaande database) — schema.sql
  alleen bereikt een database die de tabel al heeft nooit. Een nieuwe index
  voor een kolom die `_migrate()` zelf toevoegt hoort in `_migrate()`, nooit
  in `schema.sql`.
- Geen pytest-suite in dit project: verifieer met throwaway scripts tegen
  een scratch-database (`DATABASE_PATH=/tmp/scratch.db`), nooit met
  `pytest`.
- Commit-berichten eindigen met:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
  ```
- Code-commentaar en commit-berichten in het Nederlands, informele stijl,
  consistent met de rest van de codebase (why-comments, geen
  what-comments).
- VPS-deploy na de laatste push: `cd /opt/crypto-alerts && sudo -u crypto
  git pull origin claude/crypto-day-trading-alerts-5p8w6v`, daarna
  `sudo systemctl restart crypto-bot.service` (Discord-pijplijn) én
  `sudo systemctl restart crypto-web.service` (dashboard) — twee losse
  herstarts, dit raakt beide processen.

---

## Task 1: Vaste coinlijst — constante, handhaving, migratie

**Files:**
- Modify: `app/config.py` (nieuwe constante, na `TIMEFRAME` op regel 30)
- Modify: `app/repo.py:679-692` (`add_coin_if_new`)
- Modify: `app/db.py::_migrate()` (nieuw migratieblok, toevoegen na het
  `existing_coins`-blok dat eindigt op regel 239, vóór het
  `existing_prop_evaluations`-blok dat op regel 241 begint)
- Test: scratchpad-script (throwaway, scratch-database)

**Interfaces:**
- Produces: `config.FIXED_COINS: list[str]` — de 7 vaste coin-symbolen,
  gebruikt door Task 2 en door `repo.add_coin_if_new`.

- [ ] **Step 1: Voeg de constante toe aan `app/config.py`**

Na regel 30 (`TIMEFRAME = "4h"`), voeg toe:

```python

# Vaste coinlijst (HesPulse-verkleinen, 2026-09-30): geen onbeperkte
# automatische groei meer zodra een nieuwe coin in Discord voorbijkomt,
# een handjevol coins waarop de marktscan (elke 20 min, alle detectoren)
# daadwerkelijk draait. repo.add_coin_if_new is het enige handhavingspunt
# — een coin hier niet in mag nooit toegevoegd worden, ongeacht wie
# aanroept (Discord-verwerking, bron-niveaus, dagtradinginterpretatie).
FIXED_COINS = ["BTC", "ETH", "SOL", "BNB", "AVAX", "DOGE", "SUI"]
```

- [ ] **Step 2: Handhaaf de lijst in `repo.add_coin_if_new`**

Huidige code (`app/repo.py:679-692`):

```python
def add_coin_if_new(symbol: str, market: str) -> bool:
    """Voegt een coin toe aan de dynamische lijst als die nog niet bestaat.
    Geeft True terug als de coin nieuw was."""
    with db.session() as conn:
        existing = conn.execute(
            "SELECT 1 FROM coins WHERE symbol = ?", (symbol.upper(),)
        ).fetchone()
        if existing:
            return False
        conn.execute(
            "INSERT INTO coins (symbol, market, added_at, active) VALUES (?, ?, ?, 1)",
            (symbol.upper(), market, db.now_iso()),
        )
        return True
```

Vervang door:

```python
def add_coin_if_new(symbol: str, market: str) -> bool:
    """Voegt een coin toe aan de vaste lijst als die nog niet bestaat EN op
    config.FIXED_COINS staat. Geeft True terug als de coin nieuw was. Een
    coin buiten de vaste lijst wordt hier stilzwijgend nooit toegevoegd —
    zelfde False als "bestaat al", de aanroeper (coinlist.ensure_coin_tracked)
    behandelt beide identiek (geen "nieuwe coin"-melding)."""
    if symbol.upper() not in config.FIXED_COINS:
        return False
    with db.session() as conn:
        existing = conn.execute(
            "SELECT 1 FROM coins WHERE symbol = ?", (symbol.upper(),)
        ).fetchone()
        if existing:
            return False
        conn.execute(
            "INSERT INTO coins (symbol, market, added_at, active) VALUES (?, ?, ?, 1)",
            (symbol.upper(), market, db.now_iso()),
        )
        return True
```

(`config` is al geïmporteerd bovenaan `app/repo.py`, regel 8.)

- [ ] **Step 3: Migratie in `app/db.py::_migrate()`**

Zoek het blok dat eindigt met (rond regel 238-239):

```python
    if "last_pattern_key" not in existing_coins:
        conn.execute("ALTER TABLE coins ADD COLUMN last_pattern_key TEXT")
```

Voeg er direct na toe (vóór het `existing_prop_evaluations`-blok):

```python

    # Vaste coinlijst (HesPulse-verkleinen, 2026-09-30): elke bestaande
    # coin buiten config.FIXED_COINS gaat op active=0 (geen dataverlies,
    # de coin verdwijnt alleen uit repo.list_coins()/de marktscan), en de
    # 7 vaste coins moeten bestaan en actief zijn. Onvoorwaardelijk bij
    # elke start: idempotent en goedkoop (de coins-tabel is klein), dus
    # geen aparte guard nodig — een coin die al klopt wordt gewoon
    # opnieuw hetzelfde gezet.
    placeholders = ",".join("?" for _ in config.FIXED_COINS)
    conn.execute(
        f"UPDATE coins SET active = 0 WHERE symbol NOT IN ({placeholders})",
        tuple(config.FIXED_COINS),
    )
    for symbol in config.FIXED_COINS:
        existing_coin = conn.execute(
            "SELECT active FROM coins WHERE symbol = ?", (symbol,)
        ).fetchone()
        if existing_coin is None:
            conn.execute(
                "INSERT INTO coins (symbol, market, added_at, active) VALUES (?, ?, ?, 1)",
                (symbol, f"{symbol}/USDT", db.now_iso()),
            )
        elif existing_coin["active"] != 1:
            conn.execute("UPDATE coins SET active = 1 WHERE symbol = ?", (symbol,))
```

(`config.QUOTE_CURRENCY` is standaard al `"USDT"`, zie `app/config.py:29` —
de `f"{symbol}/USDT"`-market-string hierboven is dezelfde vorm als
`exchange.to_symbol` voor elke bestaande coin al produceert, dus consistent
met hoe `market` elders gevuld wordt.)

- [ ] **Step 4: Importcheck**

```bash
cd /home/user/Trade && python3 -c "from app import config, repo, db; print(config.FIXED_COINS)"
```

Expected: `['BTC', 'ETH', 'SOL', 'BNB', 'AVAX', 'DOGE', 'SUI']`, geen
Traceback.

- [ ] **Step 5: Schrijf en draai het testscript**

Maak `<jouw scratchpad>/test_fixed_coins.py`:

```python
import os
import sys
from pathlib import Path

sys.path.insert(0, "/home/user/Trade")
os.environ["DATABASE_PATH"] = "/tmp/scratch_fixed_coins.db"
db_path = Path(os.environ["DATABASE_PATH"])
if db_path.exists():
    db_path.unlink()

from app import config, db, repo  # noqa: E402

db.init_db()

# Scenario 1: een coin buiten de vaste lijst bestond al vóór de migratie
# (simuleert een oude, organisch gegroeide database) en moet op active=0
# komen, zonder dat de rij zelf verdwijnt.
with db.session() as conn:
    conn.execute(
        "INSERT INTO coins (symbol, market, added_at, active) VALUES ('LINK', 'LINK/USDT', ?, 1)",
        (db.now_iso(),),
    )
db.init_db()  # migratie nogmaals draaien, simuleert een herstart

with db.session() as conn:
    link_row = conn.execute("SELECT active FROM coins WHERE symbol = 'LINK'").fetchone()
assert link_row is not None, "LINK-rij had niet verwijderd mogen worden, alleen active=0"
assert link_row["active"] == 0, f"LINK had active=0 moeten zijn, is {link_row['active']}"
print("Scenario 1 OK: coin buiten de lijst blijft bestaan maar wordt inactief")

active_coins = {c["symbol"] for c in repo.list_coins()}
assert active_coins == set(config.FIXED_COINS), (
    f"list_coins() gaf {active_coins}, verwacht exact {set(config.FIXED_COINS)}"
)
print("Scenario 2 OK: repo.list_coins() geeft precies de 7 vaste coins")

# Scenario 3: add_coin_if_new weigert een coin buiten de lijst.
added = repo.add_coin_if_new("PEPE", "PEPE/USDT")
assert added is False, "add_coin_if_new had False moeten geven voor een coin buiten FIXED_COINS"
with db.session() as conn:
    pepe_row = conn.execute("SELECT 1 FROM coins WHERE symbol = 'PEPE'").fetchone()
assert pepe_row is None, "PEPE had helemaal niet toegevoegd mogen worden"
print("Scenario 3 OK: add_coin_if_new weigert een coin buiten de vaste lijst")

# Scenario 4: add_coin_if_new accepteert nog gewoon een coin die al op de
# vaste lijst staat en per ongeluk (nog) niet in de tabel zat.
with db.session() as conn:
    conn.execute("DELETE FROM coins WHERE symbol = 'SUI'")
added_sui = repo.add_coin_if_new("SUI", "SUI/USDT")
assert added_sui is True, "SUI staat op FIXED_COINS, add_coin_if_new had True moeten geven"
print("Scenario 4 OK: een vaste coin kan nog gewoon (opnieuw) toegevoegd worden")

print("Alle scenario's geslaagd.")
```

- [ ] **Step 6: Draai het testscript**

```bash
cd /home/user/Trade && rm -f /tmp/scratch_fixed_coins.db && python3 <jouw scratchpad>/test_fixed_coins.py
```

Expected: eindigt met `Alle scenario's geslaagd.`, geen `AssertionError` of
Traceback.

- [ ] **Step 7: Opruimen en committen**

```bash
rm -f /tmp/scratch_fixed_coins.db
cd /home/user/Trade
git add app/config.py app/repo.py app/db.py
git commit -m "$(cat <<'EOF'
Vaste coinlijst: 7 coins in plaats van onbeperkte automatische groei

Nieuwe config.FIXED_COINS (BTC, ETH, SOL, BNB, AVAX, DOGE, SUI).
repo.add_coin_if_new is het enige handhavingspunt: een coin buiten de
lijst wordt nooit meer toegevoegd, ongeacht welk pad aanroept. Migratie
zet elke bestaande coin buiten de lijst op active=0 (geen dataverlies,
verdwijnt alleen uit de scan) en zorgt dat de 7 vaste coins bestaan en
actief zijn.

Getest met een scratch-database: een oude coin blijft bestaan maar wordt
inactief, list_coins() geeft precies de 7 vaste coins, add_coin_if_new
weigert een nieuwe coin buiten de lijst maar accepteert nog gewoon een
vaste coin die (opnieuw) toegevoegd moet worden.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 2: Tweetraps-filter op Discord-berichten

**Files:**
- Modify: `app/coinlist.py` (nieuwe alias-mapping + helperfunctie)
- Modify: `app/signal_processor.py:149` (`handle_message`, stap 1) en
  `app/signal_processor.py:191` (`_process_one_coin`, stap 2)
- Test: scratchpad-script (throwaway, scratch-database, gemockte
  `interpret_message`)

**Interfaces:**
- Consumes: `config.FIXED_COINS` (Task 1).
- Produces: `coinlist.message_mentions_tracked_coin(text: str) -> bool`,
  gebruikt door `handle_message`.

- [ ] **Step 1: Alias-mapping en helperfunctie in `app/coinlist.py`**

Huidige bestand (volledig, 27 regels):

```python
"""Dynamische coinlijst: coins genoemd in verwerkte berichten worden
automatisch toegevoegd, na controle dat het paar bestaat op de exchange."""
import logging

from app import exchange, repo

logger = logging.getLogger("coinlist")


def ensure_coin_tracked(coin: str) -> tuple[bool, bool]:
    ...
```

Vervang de module-docstring en voeg de mapping + helperfunctie toe vóór
`ensure_coin_tracked`:

```python
"""Vaste coinlijst (zie config.FIXED_COINS): coins genoemd in verwerkte
berichten worden alleen nog getoetst, nooit meer automatisch toegevoegd
buiten de vaste lijst (zie repo.add_coin_if_new)."""
import logging

from app import config, exchange, repo

logger = logging.getLogger("coinlist")

# Symbool + volledige naam per vaste coin, voor het goedkope tekstfilter in
# signal_processor.handle_message: een Discord-bericht zonder afbeelding
# dat geen van deze aliassen bevat, wordt nooit aan Anthropic voorgelegd
# (scheelt de duurste API-call per bericht). Bewust een losse, statische
# mapping in plaats van afgeleid uit FIXED_COINS: de sleutels moeten
# exact FIXED_COINS zijn, zie de assert hieronder die dat bij elke import
# bevestigt in plaats van pas bij een gemiste melding te ontdekken.
COIN_NAME_ALIASES = {
    "BTC": ["btc", "bitcoin"],
    "ETH": ["eth", "ethereum"],
    "SOL": ["sol", "solana"],
    "BNB": ["bnb", "binance coin"],
    "AVAX": ["avax", "avalanche"],
    "DOGE": ["doge", "dogecoin"],
    "SUI": ["sui"],
}
assert set(COIN_NAME_ALIASES) == set(config.FIXED_COINS), (
    "COIN_NAME_ALIASES moet exact dezelfde coins als config.FIXED_COINS bevatten"
)


def message_mentions_tracked_coin(text: str) -> bool:
    """True zodra de tekst (case-insensitive) een symbool of volledige naam
    van een vaste coin bevat. Puur tekstueel, geen exchange-aanroep — dit
    moet goedkoop zijn, het draait op ELK inkomend Discord-bericht, vóór de
    Anthropic-interpretatie."""
    lowered = text.lower()
    return any(
        alias in lowered
        for aliases in COIN_NAME_ALIASES.values()
        for alias in aliases
    )
```

- [ ] **Step 2: Stap 1 van het filter — vóór de Anthropic-call**

Huidige code (`app/signal_processor.py:149-159`):

```python
async def handle_message(message_id: int, raw_text: str, image_paths: list[str]) -> None:
    duplicate = repo.find_recent_duplicate(raw_text, exclude_id=message_id) if raw_text.strip() else None
    if duplicate:
```

Voeg de nieuwe check direct na de functiedefinitie toe, vóór de
`duplicate`-regel (dus als allereerste inhoud van de functie):

```python
async def handle_message(message_id: int, raw_text: str, image_paths: list[str]) -> None:
    # Kostenfilter (HesPulse-verkleinen, 2026-09-30): een bericht zonder
    # afbeelding dat geen van de 7 vaste coins noemt, wordt nooit aan
    # Anthropic voorgelegd — dat is de duurste stap per bericht. Een
    # bericht MET afbeelding wordt altijd nog geïnterpreteerd: een
    # screenshot is niet goedkoop op tekst te filteren, en dat is precies
    # het scenario waarin dit filter een echt signaal zou kunnen missen
    # als het ook afbeeldingen zou overslaan. Stap 2 van dit filter (ná de
    # interpretatie, voor het geval Anthropic bij een screenshot toch een
    # niet-gevolgde coin teruggeeft) staat in _process_one_coin hieronder.
    if not image_paths and not coinlist.message_mentions_tracked_coin(raw_text):
        logger.info(
            "Bericht %s bevat geen gevolgde coin en geen afbeelding, niet geïnterpreteerd", message_id,
        )
        repo.mark_message_processed(
            message_id, None, None, None, True,
            note="Geen gevolgde coin herkend in tekst en geen afbeelding, niet geïnterpreteerd (kostenfilter)",
        )
        return

    duplicate = repo.find_recent_duplicate(raw_text, exclude_id=message_id) if raw_text.strip() else None
    if duplicate:
```

(`coinlist` is al geïmporteerd bovenaan `app/signal_processor.py`, regel
12.)

- [ ] **Step 3: Stap 2 van het filter — ná de interpretatie**

Huidige code (`app/signal_processor.py:191-203`):

```python
async def _process_one_coin(message_id: int, raw_text: str, interp: Interpretation) -> None:
    """Verwerkt de interpretatie voor precies één coin uit een (mogelijk
    multi-coin) bericht: eigen samenvatting, eigen bron-niveaus, eigen
    day-trading-toets of lange-termijn/narrative-pad. Dit is exact de
    logica die vóór de multi-coin-wijziging rechtstreeks in handle_message
    stond, nu geparametriseerd per coin en schrijvend naar
    message_coin_results in plaats van naar messages (zie
    repo.insert_message_coin_result: message_id + coin identificeren samen
    deze rij, meerdere coins uit hetzelfde bericht krijgen elk hun eigen
    rij)."""
    result_id = repo.insert_message_coin_result(
        message_id, interp.coin, interp.direction, interp.category, interp.unclear, note=interp.reason,
    )
```

Voeg de check toe direct ná de docstring, vóór `result_id = ...`:

```python
async def _process_one_coin(message_id: int, raw_text: str, interp: Interpretation) -> None:
    """Verwerkt de interpretatie voor precies één coin uit een (mogelijk
    multi-coin) bericht: eigen samenvatting, eigen bron-niveaus, eigen
    day-trading-toets of lange-termijn/narrative-pad. Dit is exact de
    logica die vóór de multi-coin-wijziging rechtstreeks in handle_message
    stond, nu geparametriseerd per coin en schrijvend naar
    message_coin_results in plaats van naar messages (zie
    repo.insert_message_coin_result: message_id + coin identificeren samen
    deze rij, meerdere coins uit hetzelfde bericht krijgen elk hun eigen
    rij)."""
    # Vangnet voor stap 1 van het kostenfilter in handle_message: die kan
    # een bericht MET afbeelding niet goedkoop vooraf filteren, dus hier
    # (ná de interpretatie, als de coin al bekend is) alsnog negeren als
    # Anthropic een coin teruggaf die niet op de vaste lijst staat.
    if interp.coin and interp.coin.upper() not in config.FIXED_COINS:
        repo.insert_message_coin_result(
            message_id, interp.coin, interp.direction, interp.category, True,
            note=f"{interp.coin.upper()} staat niet op de vaste coinlijst, niet verder verwerkt",
        )
        logger.info(
            "Coin %s (bericht %s) staat niet op de vaste lijst, overgeslagen", interp.coin, message_id,
        )
        return

    result_id = repo.insert_message_coin_result(
        message_id, interp.coin, interp.direction, interp.category, interp.unclear, note=interp.reason,
    )
```

(`config` is al geïmporteerd bovenaan `app/signal_processor.py`, regel 12.)

- [ ] **Step 4: Importcheck**

```bash
cd /home/user/Trade && python3 -c "import app.signal_processor; print('import OK')"
```

Expected: `import OK`.

- [ ] **Step 5: Schrijf en draai het testscript**

Maak `<jouw scratchpad>/test_coin_filter.py`:

```python
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/home/user/Trade")
os.environ["DATABASE_PATH"] = "/tmp/scratch_coin_filter.db"
db_path = Path(os.environ["DATABASE_PATH"])
if db_path.exists():
    db_path.unlink()

from app import coinlist, db, repo, signal_processor  # noqa: E402
from app.anthropic_interpret import Interpretation  # noqa: E402

db.init_db()


def make_interp(coin, direction="long", category="day_trading", unclear=False):
    return Interpretation(
        coin=coin, direction=direction, category=category, unclear=unclear,
        reason="test", source_levels=[],
    )


# --- Helperfunctie zelf ---
assert coinlist.message_mentions_tracked_coin("BTC gaat long") is True
assert coinlist.message_mentions_tracked_coin("bitcoin naar de maan") is True
assert coinlist.message_mentions_tracked_coin("LINK ziet er goed uit") is False
assert coinlist.message_mentions_tracked_coin("") is False
print("Helperfunctie-tests OK")


async def run():
    # Scenario 1: tekst zonder afbeelding, geen gevolgde coin genoemd ->
    # interpret_message wordt NIET aangeroepen.
    message_id_1 = repo.insert_message("Random tekst over LINK, geen van de 7 coins", [])
    with patch("app.signal_processor.interpret_message") as mock_interp:
        await signal_processor.handle_message(message_id_1, "Random tekst over LINK, geen van de 7 coins", [])
        assert mock_interp.call_count == 0, "interpret_message had niet aangeroepen mogen worden"
    with db.session() as conn:
        row = conn.execute("SELECT unclear, note FROM messages WHERE id = ?", (message_id_1,)).fetchone()
    assert row["unclear"] == 1
    assert "kostenfilter" in row["note"]
    print("Scenario 1 OK: bericht zonder gevolgde coin en zonder afbeelding wordt niet geïnterpreteerd")

    # Scenario 2: tekst noemt een gevolgde coin -> interpret_message WORDT
    # aangeroepen (we hoeven de rest van de pijplijn niet te volgen, alleen
    # bevestigen dat de eerste poort passeert).
    message_id_2 = repo.insert_message("BTC ziet er sterk uit", [])
    with patch("app.signal_processor.interpret_message", return_value=[make_interp("BTC", unclear=True)]) as mock_interp:
        await signal_processor.handle_message(message_id_2, "BTC ziet er sterk uit", [])
        assert mock_interp.call_count == 1
    print("Scenario 2 OK: bericht met gevolgde coin wordt wel geïnterpreteerd")

    # Scenario 3: tekst noemt geen gevolgde coin, MAAR heeft een
    # afbeelding -> interpret_message wordt SOWIESO aangeroepen.
    message_id_3 = repo.insert_message("kijk deze screenshot", ["/tmp/fake.png"])
    with patch("app.signal_processor.interpret_message", return_value=[make_interp("LINK", unclear=True)]) as mock_interp:
        await signal_processor.handle_message(message_id_3, "kijk deze screenshot", ["/tmp/fake.png"])
        assert mock_interp.call_count == 1
    print("Scenario 3 OK: bericht met afbeelding wordt altijd geïnterpreteerd, ongeacht tekst")

    # Scenario 4 (stap 2, het vangnet): Anthropic geeft bij een afbeelding
    # toch een niet-gevolgde coin terug -> genegeerd, geen signaal.
    message_id_4 = repo.insert_message("screenshot zonder herkenbare tekst", ["/tmp/fake2.png"])
    with patch("app.signal_processor.interpret_message", return_value=[make_interp("LINK", unclear=False)]), \
         patch("app.signal_processor.explain.summarize_message", return_value="samenvatting"):
        await signal_processor.handle_message(message_id_4, "screenshot zonder herkenbare tekst", ["/tmp/fake2.png"])
    with db.session() as conn:
        result_row = conn.execute(
            "SELECT unclear, note FROM message_coin_results WHERE message_id = ?", (message_id_4,)
        ).fetchone()
    assert result_row is not None, "er had wel een message_coin_results-rij moeten komen"
    assert result_row["unclear"] == 1
    assert "vaste coinlijst" in result_row["note"]
    print("Scenario 4 OK: een niet-gevolgde coin uit een screenshot wordt na interpretatie alsnog genegeerd")

    # Scenario 5: een gevolgde coin uit een screenshot gaat wel gewoon door.
    message_id_5 = repo.insert_message("screenshot van ETH", ["/tmp/fake3.png"])
    with patch("app.signal_processor.interpret_message", return_value=[make_interp("ETH", unclear=True)]), \
         patch("app.signal_processor.explain.summarize_message", return_value="samenvatting"):
        await signal_processor.handle_message(message_id_5, "screenshot van ETH", ["/tmp/fake3.png"])
    with db.session() as conn:
        result_row_5 = conn.execute(
            "SELECT unclear, note FROM message_coin_results WHERE message_id = ?", (message_id_5,)
        ).fetchone()
    assert result_row_5 is not None
    assert result_row_5["note"] == "test"  # interp.reason, niet het kostenfilter-notitie
    print("Scenario 5 OK: een gevolgde coin uit een screenshot wordt gewoon verwerkt")


asyncio.run(run())
print("Alle scenario's geslaagd.")
```

- [ ] **Step 6: Draai het testscript**

```bash
cd /home/user/Trade && rm -f /tmp/scratch_coin_filter.db && python3 <jouw scratchpad>/test_coin_filter.py
```

Expected: eindigt met `Alle scenario's geslaagd.`, geen `AssertionError` of
Traceback. Controleer bij een falend scenario eerst of je `interpret_message`
op de juiste plek patcht (`app.signal_processor.interpret_message`, want
`signal_processor.py` importeert die functie met een `from`-import, regel
13) vóórdat je de testcode zelf aanpast.

- [ ] **Step 7: Opruimen en committen**

```bash
rm -f /tmp/scratch_coin_filter.db
cd /home/user/Trade
git add app/coinlist.py app/signal_processor.py
git commit -m "$(cat <<'EOF'
Tweetraps-kostenfilter: alleen vaste-lijst-coins nog naar Anthropic

Stap 1 (handle_message, vóór de interpretatie): een bericht zonder
afbeelding dat geen van de 7 vaste coins (symbool of volledige naam)
noemt, wordt nooit meer aan Anthropic voorgelegd — de duurste stap per
bericht. Een bericht mét afbeelding wordt altijd nog geïnterpreteerd,
niet goedkoop vooraf te filteren zonder een echt signaal te missen.

Stap 2 (_process_one_coin, ná de interpretatie): het vangnet voor het
geval Anthropic bij een screenshot toch een niet-gevolgde coin
teruggeeft — genegeerd, geen signaal, geen coin-toevoeging.

Getest met een scratch-database en gemockte interpret_message: 5
scenario's (geen coin+geen afbeelding, wel coin, wel afbeelding zonder
coin-tekst, afbeelding met niet-gevolgde coin teruggegeven, afbeelding
met gevolgde coin teruggegeven).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 3: Swing volledig weg

**Files:**
- Modify: `app/signal_processor.py:250-257` (de aanroep in
  `_process_one_coin`) en `app/signal_processor.py:295-326`
  (`evaluate_level_watch` zelf, wordt verwijderd)
- Test: scratchpad-script (throwaway, scratch-database)

**Interfaces:**
- Produces: geen nieuwe interfaces. `level_check.py::check_swing_watches()`
  en `run_swing_check` blijven ongewijzigd bestaan (handelen bestaande,
  nog niet-vervallen `swing_watches`-rijen af) — niet aanraken.

- [ ] **Step 1: Verwijder de aanroep in `_process_one_coin`**

Huidige code (`app/signal_processor.py:243-257`, binnen de
`if interp.source_levels:`-lus):

```python
            for level in interp.source_levels:
                if live_price and abs(level.price_level - live_price) / live_price > SOURCE_LEVEL_MAX_DISTANCE_RATIO:
                    logger.warning(
                        "Niveau %.4f voor %s ligt te ver van de live prijs %.4f, waarschijnlijk verkeerd afgelezen, niet bewaard",
                        level.price_level, interp.coin, live_price,
                    )
                    continue
                source_level_id = repo.insert_source_level(
                    message_id, interp.coin, level.price_level, level.pattern_name,
                )
                # Alleen voor niet-day_trading categorieën (lange_termijn,
                # aandelen): een day_trading bericht krijgt al volledige,
                # directe, niveau-bewuste behandeling via zijn eigen
                # pijplijn (process_day_trading_signal). Een parallelle
                # swing-watch voor exact hetzelfde bericht voegt niets toe
                # behalve een dubbele melding en dubbel risicobedrag voor
                # dezelfde kans.
                if interp.category != "day_trading":
                    try:
                        await evaluate_level_watch(
                            message_id, interp.coin, interp.direction, source_level_id, level.price_level,
                        )
                    except Exception:
                        logger.exception("Swing-watch evaluatie voor %s (bericht %s) is mislukt",
                                          interp.coin, message_id)
```

Vervang door (bron-niveaus blijven gewoon opgeslagen, alleen de
swing-watch-evaluatie eraf):

```python
            for level in interp.source_levels:
                if live_price and abs(level.price_level - live_price) / live_price > SOURCE_LEVEL_MAX_DISTANCE_RATIO:
                    logger.warning(
                        "Niveau %.4f voor %s ligt te ver van de live prijs %.4f, waarschijnlijk verkeerd afgelezen, niet bewaard",
                        level.price_level, interp.coin, live_price,
                    )
                    continue
                repo.insert_source_level(
                    message_id, interp.coin, level.price_level, level.pattern_name,
                )
```

- [ ] **Step 2: Verwijder `evaluate_level_watch` zelf**

Verwijder de volledige functie (`app/signal_processor.py:295-326`):

```python
async def evaluate_level_watch(
    message_id: int, coin: str, direction: str, source_level_id: int, level_price: float,
) -> None:
    """Aangeroepen voor elk opgeslagen bron-niveau van een bericht in een
    niet-day_trading categorie (lange_termijn, aandelen): maakt een
    swing_watches-regel aan en checkt meteen of de prijs nu al dichtbij
    genoeg is om door te gaan naar de volledige toets. Zo niet, blijft de
    watch "wachtend" en pakt level_check.check_swing_watches() hem later
    periodiek op. Wordt bewust NIET aangeroepen voor day_trading berichten:
    die krijgen hun eigen niveau al direct via process_day_trading_signal
    (zie de trade_type-filter in handle_message hierboven) — een aparte
    swing-watch voor exact hetzelfde bericht zou alleen een dubbele
    melding en dubbel risicobedrag opleveren."""
    if (direction or "").lower() not in ("long", "short"):
        return  # "neutraal" (of None, bv. een lange-termijn niveau zonder
        # duidelijke richting) heeft geen kant om een niveau tegen te toetsen
    existing = [w for w in repo.active_swing_watches_for_coin(coin) if w["direction"] == direction.lower()]
    if existing:
        logger.info(
            "Al een wachtende swing-watch voor %s %s (watch %s), geen nieuwe aangemaakt voor bericht %s",
            coin, direction, existing[0]["id"], message_id,
        )
        return
    watch_id = repo.create_swing_watch(message_id, source_level_id, coin, direction)
    try:
        daily_df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, "1d")
    except Exception:
        logger.exception("Kon daily data voor %s niet ophalen, watch %s blijft wachtend", coin, watch_id)
        return
    daily_ind = indicators.compute_indicators(daily_df)
    if _price_near_level(daily_ind.price, level_price, daily_ind.atr):
        await run_swing_check(watch_id)
```

(Niets anders in het bestand roept `evaluate_level_watch` aan — bevestig dit
zelf met `grep -n "evaluate_level_watch" app/signal_processor.py` na het
verwijderen: dan hoort er geen enkele regel meer over te blijven.)

- [ ] **Step 3: Importcheck**

```bash
cd /home/user/Trade && python3 -c "import app.signal_processor; print('import OK')"
grep -n "evaluate_level_watch" app/signal_processor.py
```

Expected: `import OK`, en de `grep` geeft geen enkele regel terug (lege
output).

- [ ] **Step 4: Schrijf en draai het testscript**

Maak `<jouw scratchpad>/test_no_new_swing.py`:

```python
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/home/user/Trade")
os.environ["DATABASE_PATH"] = "/tmp/scratch_no_swing.db"
db_path = Path(os.environ["DATABASE_PATH"])
if db_path.exists():
    db_path.unlink()

from app import db, repo, signal_processor  # noqa: E402
from app.anthropic_interpret import Interpretation, SourceLevel  # noqa: E402

db.init_db()


async def run():
    interp = Interpretation(
        coin="BTC", direction="long", category="lange_termijn", unclear=False,
        reason="test", source_levels=[SourceLevel(price_level=50000.0, pattern_name="support")],
    )
    with patch("app.signal_processor.explain.summarize_message", return_value="samenvatting"), \
         patch("app.signal_processor.exchange.fetch_last_price", return_value=50100.0):
        await signal_processor._process_one_coin(1, "BTC support op 50000", interp)

    with db.session() as conn:
        watches = conn.execute("SELECT * FROM swing_watches").fetchall()
        levels = conn.execute("SELECT * FROM source_levels WHERE coin = 'BTC'").fetchall()

    assert len(watches) == 0, f"er had geen swing_watches-rij aangemaakt mogen worden, {len(watches)} gevonden"
    assert len(levels) == 1, f"het bron-niveau had wel opgeslagen moeten blijven, {len(levels)} gevonden"
    print("OK: geen nieuwe swing-watch aangemaakt, het bron-niveau zelf blijft wel bewaard")


asyncio.run(run())
print("Test geslaagd.")
```

- [ ] **Step 5: Draai het testscript**

```bash
cd /home/user/Trade && rm -f /tmp/scratch_no_swing.db && python3 <jouw scratchpad>/test_no_new_swing.py
```

Expected: `Test geslaagd.`, geen `AssertionError` of Traceback. Als
`Interpretation`/`SourceLevel` een ander veld verwachten dan hierboven
gebruikt: zoek de exacte dataclass-definitie op in
`app/anthropic_interpret.py` en pas de constructor-aanroep in het
testscript aan (niet de productiecode).

- [ ] **Step 6: Opruimen en committen**

```bash
rm -f /tmp/scratch_no_swing.db
cd /home/user/Trade
git add app/signal_processor.py
git commit -m "$(cat <<'EOF'
Swing-signalen: geen nieuwe meer, bestaande watches lopen vanzelf af

evaluate_level_watch (het enige aanmaakpunt voor swing_watches-rijen) is
verwijderd, samen met zijn aanroep in _process_one_coin voor
lange_termijn/aandelen-berichten. Bron-niveaus zelf blijven gewoon
opgeslagen. level_check.check_swing_watches() en run_swing_check blijven
ongewijzigd: bestaande, nog niet-vervallen watches worden nog gewoon
afgehandeld, en de functie gaat vanzelf stil zodra ze er niet meer zijn.

Getest met een scratch-database: een lange-termijn bericht met een
bron-niveau maakt geen swing_watches-rij meer aan, het niveau zelf blijft
wel bewaard.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 4: Narrative — data blijft, melding+blok weg, context_note in de pushmelding

**Files:**
- Modify: `app/signal_processor.py:329-413` (`evaluate_narrative`,
  `_narrative_summary_text`, `_send_narrative_notifications`) en
  `app/signal_processor.py:1192-1199` (de pushmelding-body van een
  dagtradingsignaal)
- Modify: `app/repo.py` (verwijder `coin_long_term_track_record`)
- Modify: `web/main.py` (de coin-pagina-route, rond regel 1730-1770)
- Modify: `web/templates/coin.html:147-173` (het "Lopend verhaal"-blok)
- Test: scratchpad-script (throwaway, scratch-database)

**Interfaces:**
- Consumes: geen nieuwe. `_build_context_note(coin, direction) -> str`
  (ongewijzigd) blijft lezen uit `coin_narratives` via
  `repo.get_active_narrative`/`repo.list_narratives_for_coin`.
- Produces: geen nieuwe publieke namen. `evaluate_narrative` behoudt zijn
  signatuur en blijft `coin_narratives` bijwerken, alleen zonder
  meldingen te versturen.

- [ ] **Step 1: `evaluate_narrative` — geen meldingen meer versturen**

Huidige code (`app/signal_processor.py:329-365`):

```python
async def evaluate_narrative(coin: str, direction: str, result_id: int) -> None:
    """Aangeroepen voor elk lange_termijn-bericht met een duidelijke
    richting (long/short — 'neutraal' en een ontbrekende richting doen
    hier niet aan mee, net als bij _build_context_note). Bepaalt of dit
    bericht een update is van het lopende verhaal over deze coin, een
    tegenspraak daarvan, of het begin van een nieuw verhaal. `result_id` is
    het id van de message_coin_results-rij voor DEZE coin (niet het
    message_id): met meerdere coins per bericht delen ze hetzelfde
    message_id, dus de narrative-koppeling moet coin-gescopet blijven (zie
    repo.create_narrative/update_narrative_progress).

    Tegenspraak sluit het oude narrative expliciet af (status
    'tegengesproken') vóór er een nieuwe wordt aangemaakt: er hoort op elk
    moment hoogstens één actief narrative per coin te zijn, ongeacht welke
    richting."""
    if direction not in ("long", "short"):
        return

    active = repo.get_active_narrative(coin)
    if active is None:
        narrative_id = repo.create_narrative(coin, direction, result_id)
        await _send_narrative_notifications(narrative_id, is_new=True, is_contradiction=False)
        return

    if active["direction"] == direction:
        repo.update_narrative_progress(active["id"], result_id)
        await _send_narrative_notifications(active["id"], is_new=False, is_contradiction=False)
        return

    repo.close_narrative(
        active["id"], "tegengesproken",
        f"tegengesproken door een nieuw {direction}-narrative voor {coin}",
    )
    new_narrative_id = repo.create_narrative(coin, direction, result_id)
    await _send_narrative_notifications(
        new_narrative_id, is_new=True, is_contradiction=True, contradicted=active,
    )
```

Vervang door (zelfde structuur, de drie
`await _send_narrative_notifications(...)`-aanroepen eraf):

```python
async def evaluate_narrative(coin: str, direction: str, result_id: int) -> None:
    """Aangeroepen voor elk lange_termijn-bericht met een duidelijke
    richting (long/short — 'neutraal' en een ontbrekende richting doen
    hier niet aan mee, net als bij _build_context_note). Bepaalt of dit
    bericht een update is van het lopende verhaal over deze coin, een
    tegenspraak daarvan, of het begin van een nieuw verhaal. `result_id` is
    het id van de message_coin_results-rij voor DEZE coin (niet het
    message_id): met meerdere coins per bericht delen ze hetzelfde
    message_id, dus de narrative-koppeling moet coin-gescopet blijven (zie
    repo.create_narrative/update_narrative_progress).

    Tegenspraak sluit het oude narrative expliciet af (status
    'tegengesproken') vóór er een nieuwe wordt aangemaakt: er hoort op elk
    moment hoogstens één actief narrative per coin te zijn, ongeacht welke
    richting.

    Puur interne boekhouding sinds HesPulse-verkleinen (2026-09-30): geen
    eigen melding meer (was _send_narrative_notifications) en geen apart
    dashboard-blok meer (coin.html). coin_narratives blijft wel gevuld —
    _build_context_note (elders in dit bestand) leest hier rechtstreeks
    uit en zet het resultaat sinds deze wijziging weer echt in de
    pushmelding van een dagtradingsignaal, zie process_day_trading_signal
    hieronder."""
    if direction not in ("long", "short"):
        return

    active = repo.get_active_narrative(coin)
    if active is None:
        repo.create_narrative(coin, direction, result_id)
        return

    if active["direction"] == direction:
        repo.update_narrative_progress(active["id"], result_id)
        return

    repo.close_narrative(
        active["id"], "tegengesproken",
        f"tegengesproken door een nieuw {direction}-narrative voor {coin}",
    )
    repo.create_narrative(coin, direction, result_id)
```

- [ ] **Step 2: Verwijder `_narrative_summary_text` en `_send_narrative_notifications`**

Verwijder beide, nu ongebruikte, functies volledig (`app/signal_processor.py`,
de twee functies direct na `evaluate_narrative`):

```python
def _narrative_summary_text(narrative: dict, is_new: bool, is_contradiction: bool,
                             contradicted_since: Optional[str]) -> str:
    ...


async def _send_narrative_notifications(
    narrative_id: int, is_new: bool, is_contradiction: bool, contradicted: Optional[dict] = None,
) -> None:
    ...
```

(Bevestig na het verwijderen met `grep -n "_send_narrative_notifications\|_narrative_summary_text" app/signal_processor.py` dat er geen enkele regel meer over is.)

- [ ] **Step 3: `context_note` alsnog in de pushmelding van een dagtradingsignaal**

Huidige code (`app/signal_processor.py:1192-1199`):

```python
            body = (
                f"Entry {signal_data['price']:.4f} · Stop {effective_stop_loss:.4f} · "
                f"Take profit {effective_take_profit:.4f}{entry_zone_note}{sniper_line}"
            )
            if signal_data.get("repeated_loss_note"):
                body += f"\n{signal_data['repeated_loss_note']}"
            if eval_blocked_note:
                body += f"\n{eval_blocked_note}"
```

Vervang door (één extra blok, ná `repeated_loss_note`, vóór
`eval_blocked_note` — geen wijziging aan de bestaande regels zelf):

```python
            body = (
                f"Entry {signal_data['price']:.4f} · Stop {effective_stop_loss:.4f} · "
                f"Take profit {effective_take_profit:.4f}{entry_zone_note}{sniper_line}"
            )
            if signal_data.get("repeated_loss_note"):
                body += f"\n{signal_data['repeated_loss_note']}"
            if signal_data.get("context_note"):
                body += f"\n{signal_data['context_note']}"
            if eval_blocked_note:
                body += f"\n{eval_blocked_note}"
```

- [ ] **Step 4: Verwijder het narrative-blok uit `web/main.py`'s coin-route**

Huidige code (rond regel 1726-1770 in `web/main.py`):

```python
    # Trackrecord van de community zelf: klopte de lange-termijn richting
    # achteraf. Vereist een live koers, mislukt die (exchange down, coin
    # niet (meer) verhandelbaar) dan blijft dit gewoon leeg in plaats van de
    # hele pagina te breken.
    long_term_track_record = None
    try:
        current_price = await asyncio.to_thread(exchange.fetch_last_price, symbol)
        long_term_track_record = repo.coin_long_term_track_record(symbol, current_price)
    except Exception:
        logger.exception("Live prijs voor trackrecord van %s kon niet opgehaald worden", symbol)

    coin = repo.get_coin(symbol)
    active_swing_watches = repo.active_swing_watches_for_coin(symbol)
    coin_narratives = repo.list_narratives_for_coin(symbol)
    for narrative in coin_narratives:
        narrative["timeline"] = repo.list_narrative_messages(narrative["id"])

    narrative_updates = [
        {"received_at": entry["received_at"], "direction": narrative["direction"]}
        for narrative in coin_narratives
        for entry in narrative["timeline"]
    ]

    active_evaluation = repo.get_active_evaluation(user["id"])

    return templates.TemplateResponse(request, "coin.html", {
        "user": user,
        "active_evaluation": active_evaluation,
        "symbol": symbol,
        "source_levels": source_levels,
        "images": repo.list_recent_images_for_coin(symbol),
        "open_trades": open_trades,
        "recent_signals": recent_signals,
        "sparkline": sparkline,
        "recent_activity": recent_activity,
        "coin_stat": coin_stat,
        "community_stat": community_stat,
        "coins": repo.list_coins(),
        "trendlines": repo.list_trendlines(symbol),
        "long_term_track_record": long_term_track_record,
        "coin_note": coin["note"] if coin else None,
        "is_muted": repo.is_coin_muted(user["id"], symbol),
        "active_swing_watches": active_swing_watches,
        "coin_narratives": coin_narratives,
        "narrative_updates": narrative_updates,
    })
```

Vervang door (`long_term_track_record`/`coin_narratives` als
template-context weg — `coin_narratives` blijft als LOKALE variabele
bestaan, want `narrative_updates` (de grafiekmarkeringen, blijven staan)
is er nog steeds van afhankelijk):

```python
    coin = repo.get_coin(symbol)
    active_swing_watches = repo.active_swing_watches_for_coin(symbol)
    coin_narratives = repo.list_narratives_for_coin(symbol)
    for narrative in coin_narratives:
        narrative["timeline"] = repo.list_narrative_messages(narrative["id"])

    # Alleen de grafiekmarkeringen blijven (wanneer een lange-termijn-
    # richting veranderde) — het tekstblok/de eigen melding zijn met
    # HesPulse-verkleinen (2026-09-30) verwijderd, coin_narratives zelf
    # gaat daarom niet meer de template-context in, alleen deze afgeleide
    # lijst.
    narrative_updates = [
        {"received_at": entry["received_at"], "direction": narrative["direction"]}
        for narrative in coin_narratives
        for entry in narrative["timeline"]
    ]

    active_evaluation = repo.get_active_evaluation(user["id"])

    return templates.TemplateResponse(request, "coin.html", {
        "user": user,
        "active_evaluation": active_evaluation,
        "symbol": symbol,
        "source_levels": source_levels,
        "images": repo.list_recent_images_for_coin(symbol),
        "open_trades": open_trades,
        "recent_signals": recent_signals,
        "sparkline": sparkline,
        "recent_activity": recent_activity,
        "coin_stat": coin_stat,
        "community_stat": community_stat,
        "coins": repo.list_coins(),
        "trendlines": repo.list_trendlines(symbol),
        "coin_note": coin["note"] if coin else None,
        "is_muted": repo.is_coin_muted(user["id"], symbol),
        "active_swing_watches": active_swing_watches,
        "narrative_updates": narrative_updates,
    })
```

- [ ] **Step 5: Verwijder `repo.coin_long_term_track_record`**

Zoek de functie op in `app/repo.py` (rond regel 1024) en verwijder hem
volledig — geen andere aanroeper (bevestig met
`grep -rn "coin_long_term_track_record" app/ web/` ná het verwijderen: alleen
nog de definitie-loze grep, dus lege output).

- [ ] **Step 6: Verwijder het "Lopend verhaal"-blok uit `coin.html`**

Huidige code (`web/templates/coin.html:147-173`):

```jinja
{% if coin_narratives %}
<details class="stats-collapse js-accordion" style="--i: 2">
  <summary class="stats-summary">
    <svg class="h2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 19.5A2.5 2.5 0 0 1 6.5 17H20"/><path d="M6.5 2H20v20H6.5A2.5 2.5 0 0 1 4 19.5v-15A2.5 2.5 0 0 1 6.5 2z"/></svg>
    <span>Lopend verhaal
      {%- if long_term_track_record %} · {{ long_term_track_record.correct }}/{{ long_term_track_record.total }} klopte achteraf{% endif %}</span>
    <svg class="chevron" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="6,9 12,15 18,9"/></svg>
  </summary>
  {% if long_term_track_record %}
  <p class="muted" style="margin: 0 0 10px; font-size: 12px;">Hoe vaak de richting van deze analyses achteraf klopte, vergeleken met de huidige koers. Analyses van de laatste dagen tellen nog niet mee.</p>
  {% endif %}
  {% for narrative in coin_narratives %}
  <div class="long-term-item" style="{{ 'opacity: 0.6;' if narrative.status != 'actief' else '' }}">
    <span class="badge badge-{{ narrative.direction if narrative.direction in ('long', 'short') else 'status' }}">{{ narrative.direction }}</span>
    <span class="badge badge-status">{{ narrative.status }}</span>
    <span class="muted mono" style="font-size: 11px;">sinds {{ narrative.opened_at[:10] }} · {{ narrative.message_count }} update{{ 's' if narrative.message_count != 1 else '' }}</span>
    {% if narrative.closed_reason %}<p class="muted" style="font-size: 11px; margin: 4px 0 0;">{{ narrative.closed_reason }}</p>{% endif %}
    {% for entry in narrative.timeline %}
    <p style="font-size: 12px; margin: 6px 0 0;">
      <span class="mono muted">{{ entry.received_at[:10] }}:</span>
      {{ entry.message_summary or entry.raw_text }}
    </p>
    {% endfor %}
  </div>
  {% endfor %}
</details>
{% endif %}
```

Verwijder dit hele blok (van `{% if coin_narratives %}` tot en met de
bijbehorende `{% endif %}`).

- [ ] **Step 7: Importcheck**

```bash
cd /home/user/Trade && python3 -c "import app.signal_processor, app.repo; print('import OK')"
grep -n "_send_narrative_notifications\|_narrative_summary_text\|coin_long_term_track_record" app/signal_processor.py app/repo.py web/main.py
```

Expected: `import OK`, en de `grep` geeft geen enkele regel terug.

- [ ] **Step 8: Schrijf en draai het testscript**

Maak `<jouw scratchpad>/test_narrative_silent.py`:

```python
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/home/user/Trade")
os.environ["DATABASE_PATH"] = "/tmp/scratch_narrative_silent.db"
db_path = Path(os.environ["DATABASE_PATH"])
if db_path.exists():
    db_path.unlink()

from app import db, repo, signal_processor  # noqa: E402

db.init_db()
user_id = repo.create_user("narrtest", "hash", 1000.0, 1.0)


async def run():
    # evaluate_narrative moet coin_narratives nog gewoon vullen...
    await signal_processor.evaluate_narrative("BTC", "long", result_id=1)
    active = repo.get_active_narrative("BTC")
    assert active is not None, "coin_narratives had gevuld moeten worden"
    assert active["direction"] == "long"
    print("OK: evaluate_narrative vult coin_narratives nog gewoon")

    # ...maar geen notifications-rij meer aanmaken (was _send_narrative_notifications).
    with db.session() as conn:
        notif_count = conn.execute(
            "SELECT COUNT(*) AS c FROM notifications WHERE type = 'narrative_update'"
        ).fetchone()["c"]
    assert notif_count == 0, f"er had geen narrative_update-notificatie meer aangemaakt mogen worden, {notif_count} gevonden"
    print("OK: geen narrative_update-notificatie meer verstuurd")

    # _build_context_note blijft werken op basis van diezelfde data.
    note = signal_processor._build_context_note("BTC", "long")
    assert note != "", "context_note had niet leeg moeten zijn voor een aligned narrative"
    note_conflict = signal_processor._build_context_note("BTC", "short")
    assert note_conflict != "", "context_note had niet leeg moeten zijn voor een tegengesteld narrative"
    print(f"OK: _build_context_note blijft werken (aligned: {note!r}, conflict: {note_conflict!r})")


asyncio.run(run())
print("Alle checks geslaagd.")
```

- [ ] **Step 9: Draai het testscript**

```bash
cd /home/user/Trade && rm -f /tmp/scratch_narrative_silent.db && python3 <jouw scratchpad>/test_narrative_silent.py
```

Expected: eindigt met `Alle checks geslaagd.`, geen `AssertionError` of
Traceback.

- [ ] **Step 10: Opruimen en committen**

```bash
rm -f /tmp/scratch_narrative_silent.db
cd /home/user/Trade
git add app/signal_processor.py app/repo.py web/main.py web/templates/coin.html
git commit -m "$(cat <<'EOF'
Narrative: geen eigen melding/dashboard-blok meer, context_note weer zichtbaar

evaluate_narrative blijft coin_narratives bijwerken (nodig voor
_build_context_note, de kern-vergelijking bij een dagtradingsignaal),
maar stuurt geen eigen notificatie meer (_send_narrative_notifications en
_narrative_summary_text zijn dode code geworden, verwijderd). Het losse
"Lopend verhaal"-blok op de coin-pagina (coin.html) is weg, samen met de
nu ongebruikte long_term_track_record/coin_long_term_track_record. De
grafiekmarkeringen (narrative_updates) blijven wel gewoon staan, die zijn
losstaand van het tekstblok.

Ontdekt tijdens het brainstormen: context_note werd al een tijdje nergens
getoond (het enige leespad was telegram_notify.py, dat sinds de overstap
naar push nergens meer aangeroepen wordt). Nu alsnog toegevoegd aan de
pushmelding-body van een dagtradingsignaal, zodat de context-vergelijking
weer echt zichtbaar is zoals oorspronkelijk bedoeld.

Getest met een scratch-database: evaluate_narrative vult coin_narratives
nog gewoon, stuurt geen notificatie meer, en _build_context_note blijft
werken (zowel het aligned- als het conflict-pad).

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 5: Prop-evaluatie — geen nieuwe runs meer

**Files:**
- Modify: `web/main.py:1452-1470` (`POST /evaluatie/start`)
- Modify: `web/templates/evaluatie.html:108-122` (het startformulier)
- Modify: `web/templates/dashboard.html:44-56` (de "geen actieve
  evaluatie"-kaart)
- Test: scratchpad-script (throwaway, scratch-database, FastAPI
  TestClient)

**Interfaces:**
- Produces: geen nieuwe. `POST /evaluatie/stop` en `GET /evaluatie` blijven
  ongewijzigd.

- [ ] **Step 1: `POST /evaluatie/start` geeft geen nieuwe run meer**

Huidige code (`web/main.py:1452-1470`):

```python
@app.post("/evaluatie/start")
async def start_evaluation(
    tier_amount: float = Form(...),
    profit_target_pct: float = Form(...),
    max_drawdown_pct: float = Form(...),
    user: dict = Depends(require_login),
):
    if (
        tier_amount not in PROP_EVAL_TIERS
        or not (0 < profit_target_pct <= 50)
        or not (0 < max_drawdown_pct <= 50)
        or repo.get_active_evaluation(user["id"]) is not None
    ):
        # Ongeldige input of dubbele start (bv. twee tabbladen tegelijk):
        # stil negeren, het dashboard toont sowieso alleen het
        # startformulier als er nog geen actieve run is.
        return RedirectResponse(url="/evaluatie", status_code=303)
    repo.create_evaluation(user["id"], tier_amount, profit_target_pct, max_drawdown_pct)
    return RedirectResponse(url="/evaluatie", status_code=303)
```

Vervang door (route blijft bestaan zodat een oude bladwijzer/ingesleten
gewoonte niet op een 404 uitkomt, maar maakt nooit meer een nieuwe run
aan):

```python
@app.post("/evaluatie/start")
async def start_evaluation(user: dict = Depends(require_login)):
    # Nieuwe evaluatie-runs starten kan sinds HesPulse-verkleinen
    # (2026-09-30) niet meer (zie de spec: ongein eruit, prop-evaluatie is
    # weinig gebruikt en kost onderhoud). De route blijft bestaan zodat een
    # oude bladwijzer of het startformulier (nu verwijderd, evaluatie.html)
    # niet op een 404 uitkomt — stil negeren en terug naar /evaluatie, dat
    # bestaande/afgesloten runs blijft tonen.
    return RedirectResponse(url="/evaluatie", status_code=303)
```

- [ ] **Step 2: Verwijder het startformulier uit `evaluatie.html`**

Huidige code (`web/templates/evaluatie.html:108-122`):

```jinja
  <form method="post" action="/evaluatie/start" class="prop-eval-start">
    <label>Bedrag
      <select name="tier_amount">
        <option value="5000">€5.000</option>
        <option value="10000" selected>€10.000</option>
        <option value="25000">€25.000</option>
        <option value="50000">€50.000</option>
        <option value="100000">€100.000</option>
        <option value="200000">€200.000</option>
      </select>
    </label>
    <label>Winstdoel % <input type="number" name="profit_target_pct" value="8" min="1" max="50" step="0.5" required></label>
    <label>Max drawdown % <input type="number" name="max_drawdown_pct" value="6" min="1" max="50" step="0.5" required></label>
    <button type="submit">Start evaluatie</button>
  </form>
```

Verwijder dit hele `<form>`-blok.

- [ ] **Step 3: Verwijder de "geen actieve evaluatie"-kaart uit `dashboard.html`**

Huidige code (`web/templates/dashboard.html:44-56`):

```jinja
{% if eval_display %}
<section class="card" style="--i: 1">
  <h2><svg class="h2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2 2 7l10 5 10-5-10-5z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/></svg>Evaluatie simulatie</h2>
  <p class="muted" style="margin: 0 0 6px;">€{{ "{:,.0f}".format(eval_display.tier_amount).replace(",", ".") }} tier · €{{ "%.2f"|format(eval_display.current_balance) }}{% if eval_display.status != 'actief' %} · {{ eval_display.status }}{% endif %}</p>
  <a href="/evaluatie">Bekijk evaluatie →</a>
</section>
{% else %}
<section class="card" style="--i: 1">
  <h2><svg class="h2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2 2 7l10 5 10-5-10-5z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/></svg>Evaluatie simulatie</h2>
  <p class="muted">Nog geen evaluatie actief.</p>
  <a href="/evaluatie">Start een evaluatie →</a>
</section>
{% endif %}
```

Vervang door (alleen de kaart tonen als er al een evaluatie bestaat,
actief of niet — geen "start"-uitnodiging meer als er nog nooit een is
geweest):

```jinja
{% if eval_display %}
<section class="card" style="--i: 1">
  <h2><svg class="h2-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 2 2 7l10 5 10-5-10-5z"/><path d="m2 17 10 5 10-5"/><path d="m2 12 10 5 10-5"/></svg>Evaluatie simulatie</h2>
  <p class="muted" style="margin: 0 0 6px;">€{{ "{:,.0f}".format(eval_display.tier_amount).replace(",", ".") }} tier · €{{ "%.2f"|format(eval_display.current_balance) }}{% if eval_display.status != 'actief' %} · {{ eval_display.status }}{% endif %}</p>
  <a href="/evaluatie">Bekijk evaluatie →</a>
</section>
{% endif %}
```

- [ ] **Step 4: Importcheck**

```bash
cd /home/user/Trade && python3 -c "import web.main; print('import OK')"
```

Expected: `import OK`.

- [ ] **Step 5: Schrijf en draai het testscript**

Maak `<jouw scratchpad>/test_no_new_evaluation.py`:

```python
import os
import sys
from pathlib import Path

sys.path.insert(0, "/home/user/Trade")
os.environ["DATABASE_PATH"] = "/tmp/scratch_no_eval.db"
db_path = Path(os.environ["DATABASE_PATH"])
if db_path.exists():
    db_path.unlink()

from fastapi.testclient import TestClient  # noqa: E402

from app import db, repo, security  # noqa: E402
from web.main import app  # noqa: E402

db.init_db()
user_id = repo.create_user("evaltest", "hash", 1000.0, 1.0)
token = security.create_session_token(user_id)
client = TestClient(app, cookies={"session": token})

# POST /evaluatie/start maakt geen nieuwe run meer aan.
resp = client.post(
    "/evaluatie/start",
    data={"tier_amount": "10000", "profit_target_pct": "8", "max_drawdown_pct": "6"},
    follow_redirects=False,
)
assert resp.status_code == 303, f"verwacht een redirect, kreeg {resp.status_code}"
active = repo.get_active_evaluation(user_id)
assert active is None, f"er had geen actieve evaluatie aangemaakt mogen worden, kreeg {active}"
print("OK: POST /evaluatie/start maakt geen nieuwe run meer aan")

# GET /evaluatie blijft gewoon werken.
resp_get = client.get("/evaluatie")
assert resp_get.status_code == 200, f"verwacht 200, kreeg {resp_get.status_code}"
print("OK: GET /evaluatie blijft werken")

print("Alle checks geslaagd.")
```

(Zoek zelf de exacte functienaam voor een sessie-token op in
`app/security.py` als `create_session_token` niet klopt — het testscript
moet inloggen via hetzelfde mechanisme als `require_login` verwacht, dat is
een cookie met een geldig JWT, zie `app/security.py`.)

- [ ] **Step 6: Draai het testscript**

```bash
cd /home/user/Trade && rm -f /tmp/scratch_no_eval.db && python3 <jouw scratchpad>/test_no_new_evaluation.py
```

Expected: eindigt met `Alle checks geslaagd.`, geen `AssertionError` of
Traceback.

- [ ] **Step 7: Opruimen en committen**

```bash
rm -f /tmp/scratch_no_eval.db
cd /home/user/Trade
git add web/main.py web/templates/evaluatie.html web/templates/dashboard.html
git commit -m "$(cat <<'EOF'
Prop-evaluatie: geen nieuwe runs meer starten

POST /evaluatie/start negeert een poging stil en stuurt terug naar
/evaluatie (route blijft bestaan tegen een 404 op een oude bladwijzer).
Het startformulier op evaluatie.html en de "Start een evaluatie"-kaart op
het dashboard (voor een gebruiker die nog nooit een evaluatie deed) zijn
verwijderd. POST /evaluatie/stop en GET /evaluatie blijven ongewijzigd:
een lopende run kan nog afgesloten worden, oude runs blijven zichtbaar.

Getest met een scratch-database en FastAPI's TestClient: POST
/evaluatie/start maakt geen prop_evaluations-rij meer aan, GET /evaluatie
blijft gewoon werken.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 6: Volledige regressie en push

**Files:**
- Geen nieuwe wijzigingen verwacht — deze taak verifieert Taak 1 t/m 5
  samen en rondt af.

**Interfaces:**
- Consumes: alles uit Taak 1 t/m 5.
- Produces: niets nieuws; eindstaat is een gepushte branch en een
  draaiende VPS.

- [ ] **Step 1: Draai alle vijf testscripts nog een keer achter elkaar**

Als de scratchpad-scripts uit de vorige taken nog bestaan, draai ze
allemaal opnieuw (elk met zijn eigen scratch-database, zoals in de
oorspronkelijke stap). Als een scratchpad al opgeruimd is: herbouw het
script kort met dezelfde inhoud als in de betreffende taak hierboven.
Expected: alle vijf eindigen zonder `AssertionError` of Traceback.

- [ ] **Step 2: Bekijk de volledige diff**

```bash
cd /home/user/Trade && git diff 1bd83ca -- app/ web/
```

(`1bd83ca` is de laatste commit vóór dit plan begon — de spec-commit. Als
dat niet de juiste basis blijkt, gebruik `git log --oneline | head -10` om
de commit vóór Taak 1 te vinden.)

Controleer: alleen de wijzigingen uit Taak 1 t/m 5 zitten in de diff (vaste
coinlijst + migratie, tweetraps-filter, swing weg, narrative-melding+blok
weg + context_note in de pushmelding, prop-evaluatie-start weg) — niets
anders in `app/` of `web/` is aangeraakt. `ENABLE_ADVANCED_FACTORS`,
`TOGGLEABLE_FACTORS`, de systemd-timers, en de Anthropic-modelconfiguratie
zijn ongewijzigd.

- [ ] **Step 3: Push**

```bash
cd /home/user/Trade && git push -u origin claude/crypto-day-trading-alerts-5p8w6v
```

- [ ] **Step 4: Geef VPS-deploy-instructies**

Drie losse commando's (niet combineren met `&&` in één plak-actie —
meerdere commando's tegelijk plakken heeft dit sessie eerder tot verminkte
commando's geleid):

```bash
cd /opt/crypto-alerts && sudo -u crypto git pull origin claude/crypto-day-trading-alerts-5p8w6v
```

Daarna:

```bash
sudo systemctl restart crypto-bot.service
```

Daarna:

```bash
sudo systemctl restart crypto-web.service
```

(De marktscan-, level-check- en overige timers draaien dezelfde
Python-code opnieuw bij hun volgende cyclus, geen aparte herstart nodig —
alleen de twee altijd-actieve processen, bot en web, moeten expliciet
herstarten om de nieuwe code te laden.)

- [ ] **Step 5: Bevestig bij de gebruiker**

Meld kort: welke commits gepusht zijn, dat alle testscripts nog slagen, en
dat de VPS herstart moet worden met de drie commando's hierboven om het
live te krijgen. Noem ook expliciet dat de migratie (Taak 1, Step 3) bij
de eerstvolgende start van `crypto-bot.service` automatisch draait —
bestaande coins buiten de vaste lijst worden dan gedeactiveerd, geen
handmatige stap nodig.

## Self-Review (uitgevoerd tijdens het schrijven van dit plan)

1. **Spec-dekking:**
   - Vaste coinlijst + handhaving + migratie → Taak 1. ✓
   - Tweetraps-filter (vóór en ná interpretatie) → Taak 2. ✓
   - Swing volledig weg → Taak 3. ✓
   - Narrative: data blijft, melding+blok weg, context-vergelijking blijft
     werken → Taak 4. ✓ (inclusief de tijdens het brainstormen ontdekte en
     door de gebruiker bevestigde toevoeging: `context_note` nu ook echt in
     de pushmelding, en de grafiekmarkeringen die expliciet moesten
     blijven staan.)
   - Prop-evaluatie: geen nieuwe runs → Taak 5. ✓
   - "Wat niet verandert" (dagtrading, SMC, structurele detectoren,
     ENABLE_ADVANCED_FACTORS, systemd-timers, geen bredere visuele
     herziening) → expliciet niet aangeraakt in geen enkele taak, bevestigd
     via de diff-check in Taak 6. ✓
   - API-kosten "meten, niet nu al ingrijpen" → geen taak nodig, met opzet
     geen wijziging aan `anthropic_interpret.py`/`explain.py`. ✓
2. **Placeholder-scan:** geen TBD/TODO; elke stap bevat de letterlijke code
   of het letterlijke commando. Twee stappen (Taak 3 Step 5, Taak 5 Step 5)
   bevatten een expliciete "zoek dit zelf op als het niet klopt"-instructie
   voor een dataclass/functienaam buiten dit plan se scope — dat is een
   bewuste, beperkte uitzondering (de exacte vorm van `Interpretation`/
   `SourceLevel`/`security`'s sessie-tokenfunctie ligt niet vast in de
   spec), geen vage taakomschrijving.
3. **Typeconsistentie:** `config.FIXED_COINS` wordt in Taak 1 gedefinieerd
   en in Taak 2/3 (via `repo.add_coin_if_new`, al in Taak 1 zelf) en Taak 2
   (`_process_one_coin`) ongewijzigd hergebruikt.
   `coinlist.message_mentions_tracked_coin(text: str) -> bool` heeft in
   Taak 2 dezelfde signatuur bij definitie en aanroep.
   `evaluate_narrative(coin: str, direction: str, result_id: int) -> None`
   blijft in Taak 4 exact dezelfde signatuur houden als vóór de wijziging
   (alleen het lichaam verandert), dus de aanroep in `_process_one_coin`
   (ongewijzigd) blijft kloppen.
