# Meerdere coins per Discord-bericht Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** HesPulse herkent zelf wanneer één Discord-bericht meerdere coins
tegelijk behandelt (een watchlist-post, of een terloopse vergelijking) en
verwerkt elke coin apart, met zijn eigen bron-niveaus, eigen toetsing en
eigen melding — in plaats van alles onder één coin te proppen.

**Architecture:** De Anthropic-interpretatie levert voortaan een lijst van
per-coin-uitkomsten in plaats van één. Een nieuwe tabel
`message_coin_results` slaat één rij per (bericht, coin) op met alles wat
nu nog rechtstreeks op `messages` staat (coin/direction/category/unclear/
note/message_summary/price_at_receipt/narrative_id). `messages` zelf wordt
een envelope (raw_text, image, dedupe, "hele bericht klaar"), en
`handle_message` splitst in een envelope-deel en een per-coin-lus die de
bestaande verwerkingslogica hergebruikt. Twee bestaande functies bleken
dezelfde "coin-scoping ontbreekt"-bug te hebben als de gerapporteerde
(`list_source_levels_for_message`, `create_narrative`/
`update_narrative_progress`) — beide worden hier gefixt, anders lost deze
wijziging het gemelde probleem niet echt op.

**Tech Stack:** Python 3.11, SQLite (WAL), FastAPI, Anthropic SDK
(tool-use), python-telegram-bot.

**Spec:** `docs/superpowers/specs/2026-09-10-multi-coin-berichten-design.md`

## Global Constraints

- Geen backfill van bestaande `messages`-rijen: historische rijen behouden
  hun huidige kolommen, geen migratiescript nodig (spec, Niet-doelen).
- `scripts/backfill_swing_watches.py` wordt niet aangepast (spec,
  Niet-doelen).
- Dedupe-venster/voorwaarden (exacte `raw_text`, binnen 3 minuten, niet na
  een API-fout) blijven ongewijzigd. Alleen wát bij een duplicaat
  gekopieerd wordt verandert (spec, Niet-doelen).
- Een single-coin bericht moet zich functioneel identiek blijven gedragen
  (spec, Niet-doelen).
- Geen limiet op het aantal coins per bericht (spec, Niet-doelen).
- `message_coin_results`-schema exact zoals in de spec, Sectie 2: kolommen
  `id, message_id, coin, direction, category, unclear, note,
  message_summary, price_at_receipt, narrative_id, created_at`.
- Nieuwe tabellen komen alleen in `schema.sql` als `CREATE TABLE IF NOT
  EXISTS` — `db.init_db()` draait het volledige `schema.sql` via
  `executescript()` op ELKE opstart (zowel `main.py` als `web/main.py`
  roepen het aan), dus een gloednieuwe tabel heeft geen aparte
  `_migrate()`-stap nodig (alleen een NIEUWE KOLOM op een BESTAANDE tabel
  heeft dat nodig — hier verandert geen bestaande tabel van kolommen).
- Dit project heeft geen pytest-suite (zie CLAUDE.md). Elke test in dit
  plan is een losstaand, wegwerpbaar script in de sessie-scratchpad-map,
  gedraaid met `python3 <pad>`, niet gecommit. Vervang `<SCRATCHPAD>`
  hieronder door het pad dat je systeemprompt als scratchpad-directory
  noemt.

---

### Task 1: Anthropic-interpretatielaag (`app/anthropic_interpret.py`)

**Files:**
- Modify: `app/anthropic_interpret.py` (SYSTEM_PROMPT, TOOL, `interpret_message`)
- Test: `<SCRATCHPAD>/test_multi_coin_interpret.py`

**Interfaces:**
- Consumes: niets nieuws.
- Produces: `interpret_message(raw_text: str, image_paths: Optional[list[str]] = None) -> list[Interpretation]`
  — gebruikt door Task 3 (`signal_processor.handle_message`). `Interpretation`
  en `SourceLevel` dataclasses blijven qua velden ongewijzigd.

- [ ] **Step 1: Schrijf het testscript met de eerste falende assertie**

Maak `<SCRATCHPAD>/test_multi_coin_interpret.py`:

```python
import sys
sys.path.insert(0, "/home/user/Trade")

from unittest.mock import patch, MagicMock
from app import anthropic_interpret
from app.anthropic_interpret import interpret_message

passed = failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  OK  {label}")
    else:
        failed += 1
        print(f"  FAIL {label}")


def _fake_response(coins_payload):
    tool_use = MagicMock()
    tool_use.type = "tool_use"
    tool_use.input = {"coins": coins_payload}
    response = MagicMock()
    response.content = [tool_use]
    return response


# --- meerdere coins in één bericht, elk met eigen niveaus ---
with patch.object(anthropic_interpret.anthropic, "Anthropic") as MockAnthropic:
    client = MockAnthropic.return_value
    client.messages.create.return_value = _fake_response([
        {
            "coin": "BNB", "direction": "long", "category": "day_trading", "unclear": False,
            "reason": "", "source_levels": [{"price_level": 550.0, "pattern_name": "support"}],
        },
        {
            "coin": "TAO", "direction": "short", "category": "day_trading", "unclear": False,
            "reason": "", "source_levels": [{"price_level": 320.0, "pattern_name": "weerstand"}],
        },
        {
            "coin": "LINK", "direction": "", "category": "day_trading", "unclear": True,
            "reason": "alleen ter vergelijking genoemd, geen eigen opzet", "source_levels": [],
        },
    ])
    results = interpret_message("BNB ziet er sterk uit, TAO juist zwak, net als LINK vorige week")

check("drie interpretaties teruggegeven", len(results) == 3)
check("eerste is BNB long, niet unclear", results[0].coin == "BNB" and results[0].direction == "long" and not results[0].unclear)
check("BNB heeft precies 1 source_level van 550.0", len(results[0].source_levels) == 1 and results[0].source_levels[0].price_level == 550.0)
check("tweede is TAO short, niet unclear", results[1].coin == "TAO" and results[1].direction == "short" and not results[1].unclear)
check("TAO heeft precies 1 source_level van 320.0, niet BNB se niveau", len(results[1].source_levels) == 1 and results[1].source_levels[0].price_level == 320.0)
check("derde is LINK, unclear (geen eigen richting)", results[2].coin == "LINK" and results[2].unclear)

# --- leeg coins-array: geen enkele coin te bepalen ---
with patch.object(anthropic_interpret.anthropic, "Anthropic") as MockAnthropic:
    client = MockAnthropic.return_value
    client.messages.create.return_value = _fake_response([])
    results_empty = interpret_message("onduidelijk gebrabbel zonder coin")

check("leeg coins-array geeft lijst met precies 1 unclear-resultaat", len(results_empty) == 1 and results_empty[0].unclear and results_empty[0].coin is None)

# --- day_trading zonder richting wordt alsnog unclear, ongeacht wat de AI zelf als unclear opgaf ---
with patch.object(anthropic_interpret.anthropic, "Anthropic") as MockAnthropic:
    client = MockAnthropic.return_value
    client.messages.create.return_value = _fake_response([
        {"coin": "ETH", "direction": "", "category": "day_trading", "unclear": False, "reason": "", "source_levels": []},
    ])
    results_no_dir = interpret_message("ETH gaat iets doen")

check("day_trading zonder richting wordt geforceerd unclear", results_no_dir[0].unclear and "richting" in results_no_dir[0].reason)

print(f"\n=== {passed} geslaagd, {failed} gefaald ===")
sys.exit(1 if failed else 0)
```

- [ ] **Step 2: Run het script, bevestig dat het faalt (interpret_message geeft nu nog geen lijst terug)**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_multi_coin_interpret.py
```

Verwacht: `AttributeError` of een `FAIL`-regel op de eerste checks (`interpret_message` geeft op dit moment nog een los `Interpretation`-object terug, geen lijst — `len(results)` faalt of geeft een verkeerd getal).

- [ ] **Step 3: Werk `SYSTEM_PROMPT` bij in `app/anthropic_interpret.py`**

Zoek:

```python
Roep altijd de tool record_interpretation aan met je bevindingen."""
```

Vervang door:

```python
Eén bericht kan over meerdere coins tegelijk gaan (bijvoorbeeld een \
watchlist-post met meerdere tickers, of een analyse die één coin \
vergelijkt met een andere). Geef in dat geval een apart item per coin in \
de coins-array, ook als een coin er maar terloops in genoemd wordt (bijvoorbeeld \
puur ter vergelijking, zonder een eigen concrete opzet). Bij een afbeelding \
met niveaus voor meerdere coins: elk niveau hoort bij precies één coin se \
item, nooit bij meerdere tegelijk en nooit bij de verkeerde coin — lees \
zorgvuldig bij welke grafiek/ticker een niveau hoort voor je het \
doorgeeft.

Roep altijd de tool record_interpretation aan met je bevindingen."""
```

- [ ] **Step 4: Vervang de TOOL-definitie**

Zoek het hele `TOOL`-dict (van `TOOL = {` tot en met de sluitende `}` vlak
vóór `@dataclass\nclass SourceLevel:`):

```python
TOOL = {
    "name": "record_interpretation",
    "description": "Registreer de interpretatie van een Discord trading bericht.",
    "input_schema": {
        "type": "object",
        "properties": {
            "coin": {
                "type": "string",
                "description": "Ticker symbool, bijvoorbeeld BTC. Leeg laten indien onbekend.",
            },
            "direction": {
                "type": "string",
                "enum": ["long", "short", "neutraal", ""],
                "description": "\"neutraal\" alleen bij lange_termijn met een verdeelde conclusie. Leeg laten indien onbekend.",
            },
            "category": {
                "type": "string",
                "enum": ["day_trading", "lange_termijn", "aandelen"],
            },
            "unclear": {
                "type": "boolean",
                "description": "True als coin of direction niet zeker zijn.",
            },
            "reason": {
                "type": "string",
                "description": "Reden waarom het bericht onduidelijk is, indien van toepassing.",
            },
            "source_levels": {
                "type": "array",
                "description": "Niveaus/patroon die de bron al zelf heeft ingetekend op een bijgevoegde afbeelding.",
                "items": {
                    "type": "object",
                    "properties": {
                        "price_level": {"type": "number"},
                        "pattern_name": {"type": "string"},
                    },
                    "required": ["price_level"],
                },
            },
        },
        "required": ["category", "unclear"],
    },
}
```

Vervang door:

```python
TOOL = {
    "name": "record_interpretation",
    "description": (
        "Registreer de interpretatie van een Discord trading bericht. Een bericht kan over "
        "meerdere coins tegelijk gaan (bijvoorbeeld een watchlist-post of een vergelijking) "
        "— geef dan een apart item per coin, ook als een coin maar terloops genoemd wordt."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "coins": {
                "type": "array",
                "description": "Eén item per coin die het bericht noemt. Leeg als geen enkele coin met voldoende zekerheid te bepalen is.",
                "items": {
                    "type": "object",
                    "properties": {
                        "coin": {
                            "type": "string",
                            "description": "Ticker symbool, bijvoorbeeld BTC. Leeg laten indien onbekend.",
                        },
                        "direction": {
                            "type": "string",
                            "enum": ["long", "short", "neutraal", ""],
                            "description": "\"neutraal\" alleen bij lange_termijn met een verdeelde conclusie. Leeg laten indien onbekend.",
                        },
                        "category": {
                            "type": "string",
                            "enum": ["day_trading", "lange_termijn", "aandelen"],
                        },
                        "unclear": {
                            "type": "boolean",
                            "description": "True als coin of direction voor DEZE coin niet zeker zijn.",
                        },
                        "reason": {
                            "type": "string",
                            "description": "Reden waarom dit item onduidelijk is, indien van toepassing.",
                        },
                        "source_levels": {
                            "type": "array",
                            "description": "Alleen niveaus die de bron zelf heeft ingetekend voor DEZE coin. Een niveau dat bij een andere coin in dezelfde afbeelding hoort, hoort bij dat andere coin se item, niet hier.",
                            "items": {
                                "type": "object",
                                "properties": {
                                    "price_level": {"type": "number"},
                                    "pattern_name": {"type": "string"},
                                },
                                "required": ["price_level"],
                            },
                        },
                    },
                    "required": ["coin", "category", "unclear"],
                },
            },
        },
        "required": ["coins"],
    },
}
```

- [ ] **Step 5: Vervang `interpret_message` zodat het een lijst teruggeeft**

Zoek:

```python
def interpret_message(raw_text: str, image_paths: Optional[list[str]] = None) -> Interpretation:
    image_paths = image_paths or []
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    content: list[dict] = [{"type": "text", "text": raw_text or "(leeg bericht, alleen afbeelding)"}]
    for path in image_paths:
        content.append(_image_block(path))

    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=1024,
        system=SYSTEM_PROMPT,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "record_interpretation"},
        messages=[{"role": "user", "content": content}],
    )

    tool_use = next(b for b in response.content if b.type == "tool_use")
    payload = tool_use.input

    coin = (payload.get("coin") or "").strip().upper() or None
    direction = (payload.get("direction") or "").strip().lower() or None
    category = payload.get("category", "day_trading")
    unclear = bool(payload.get("unclear", False))
    reason = payload.get("reason", "")

    source_levels = [
        SourceLevel(price_level=lvl["price_level"], pattern_name=lvl.get("pattern_name") or None)
        for lvl in payload.get("source_levels", [])
    ]

    if coin is None:
        unclear = True
        if not reason:
            reason = "coin niet duidelijk uit het bericht te halen"
    elif category == "day_trading" and direction is None:
        # Alleen bij een concrete day trading opzet is een echte long/short
        # richting verplicht. Een lange termijn analyse mag ook "neutraal"
        # zijn, dat is een geldige, bruikbare conclusie, geen onduidelijkheid.
        unclear = True
        if not reason:
            reason = "richting niet duidelijk uit het bericht te halen"

    return Interpretation(
        coin=coin, direction=direction, category=category,
        unclear=unclear, reason=reason, source_levels=source_levels,
    )
```

Vervang door:

```python
def _parse_coin_item(item: dict) -> Interpretation:
    coin = (item.get("coin") or "").strip().upper() or None
    direction = (item.get("direction") or "").strip().lower() or None
    category = item.get("category", "day_trading")
    unclear = bool(item.get("unclear", False))
    reason = item.get("reason", "")

    source_levels = [
        SourceLevel(price_level=lvl["price_level"], pattern_name=lvl.get("pattern_name") or None)
        for lvl in item.get("source_levels", [])
    ]

    if coin is None:
        unclear = True
        if not reason:
            reason = "coin niet duidelijk uit het bericht te halen"
    elif category == "day_trading" and direction is None:
        # Alleen bij een concrete day trading opzet is een echte long/short
        # richting verplicht. Een lange termijn analyse mag ook "neutraal"
        # zijn, dat is een geldige, bruikbare conclusie, geen onduidelijkheid.
        unclear = True
        if not reason:
            reason = "richting niet duidelijk uit het bericht te halen"

    return Interpretation(
        coin=coin, direction=direction, category=category,
        unclear=unclear, reason=reason, source_levels=source_levels,
    )


def interpret_message(raw_text: str, image_paths: Optional[list[str]] = None) -> list[Interpretation]:
    """Geeft één Interpretation terug per coin die het bericht behandelt
    (zie SYSTEM_PROMPT/TOOL: een bericht kan meerdere coins tegelijk
    noemen, elk met zijn eigen richting/categorie/niveaus). Een leeg
    coins-array (geen enkele coin te bepalen) geeft een lijst met precies
    één onduidelijke Interpretation terug, zelfde effectieve gedrag als
    vroeger bij een volledig onduidelijk bericht."""
    image_paths = image_paths or []
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)

    content: list[dict] = [{"type": "text", "text": raw_text or "(leeg bericht, alleen afbeelding)"}]
    for path in image_paths:
        content.append(_image_block(path))

    response = client.messages.create(
        model=config.ANTHROPIC_MODEL,
        max_tokens=1536,
        system=SYSTEM_PROMPT,
        tools=[TOOL],
        tool_choice={"type": "tool", "name": "record_interpretation"},
        messages=[{"role": "user", "content": content}],
    )

    tool_use = next(b for b in response.content if b.type == "tool_use")
    payload = tool_use.input
    coins_payload = payload.get("coins") or []

    if not coins_payload:
        return [Interpretation(
            coin=None, direction=None, category="day_trading", unclear=True,
            reason="coin niet duidelijk uit het bericht te halen",
        )]

    return [_parse_coin_item(item) for item in coins_payload]
```

`max_tokens` gaat van 1024 naar 1536: met meerdere coins in één antwoord
kan de tool-call groter worden dan bij één coin, en een te krap
`max_tokens` geeft een afgebroken (dus ongeldige) tool-call terug in
plaats van een duidelijke fout.

- [ ] **Step 6: Run het script, bevestig dat alle asserties slagen**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_multi_coin_interpret.py
```

Verwacht: `=== 7 geslaagd, 0 gefaald ===`.

- [ ] **Step 7: Commit**

```bash
git add app/anthropic_interpret.py
git commit -m "Anthropic-interpretatie: meerdere coins per bericht

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q"
```

---

### Task 2: Database-laag (`app/schema.sql` + `app/repo.py`)

**Files:**
- Modify: `app/schema.sql` (nieuwe tabel `message_coin_results`)
- Modify: `app/repo.py` (nieuwe functies + twee coin-scoping-fixes)
- Test: `<SCRATCHPAD>/test_message_coin_results.py`

**Interfaces:**
- Consumes: niets nieuws.
- Produces (gebruikt door Task 3, 4, 5):
  - `repo.insert_message_coin_result(message_id: int, coin: Optional[str], direction: Optional[str], category: Optional[str], unclear: bool, note: str = "") -> int`
  - `repo.set_message_coin_result_summary(result_id: int, summary: str) -> None`
  - `repo.set_message_coin_result_price_at_receipt(result_id: int, price: float) -> None`
  - `repo.list_message_coin_results(message_id: int) -> list[dict]`
  - `repo.copy_message_coin_results(source_message_id: int, target_message_id: int, extra_note_suffix: str) -> None`
  - `repo.mark_message_envelope_processed(message_id: int) -> None`
  - `repo.list_source_levels_for_message(message_id: int, coin: str) -> list[dict]` (was zonder `coin`-parameter — **breaking change**, elke aanroeper moet mee-updaten, zie Task 3)
  - `repo.recent_unclear_messages(limit: int = 15) -> list[dict]` (zelfde signatuur, nu ook per-coin-rijen)
  - `repo.list_messages_for_summary_backfill() -> list[dict]` (zelfde signatuur, elk item krijgt er een `"source"`-key bij: `"legacy"` of `"coin_result"`)
  - `repo.create_narrative(coin: str, direction: str, result_id: int) -> int` (derde parameter was `message_id`, wordt `result_id` — **breaking change**, zie Task 3)
  - `repo.update_narrative_progress(narrative_id: int, result_id: int) -> None` (zelfde soort parameter-hernoeming)
  - `repo.list_narrative_messages(narrative_id: int) -> list[dict]` (zelfde signatuur, andere bron)

- [ ] **Step 1: Voeg de nieuwe tabel toe aan `app/schema.sql`**

Zoek de sectie met `source_levels` (na de `messages`-tabel, vóór
`trendlines`):

```sql
-- Bron niveaus, overgenomen uit Discord afbeeldingen. Altijd bewaard,
-- ongeacht categorie van het bericht.
CREATE TABLE IF NOT EXISTS source_levels (
```

Voeg er vlak vóór toe:

```sql
-- Eén rij per (bericht, coin): wat de AI voor DEZE ene coin uit het
-- bericht haalde. Eén Discord-bericht kan meerdere coins tegelijk
-- behandelen (een watchlist-post, of een terloopse vergelijking), messages
-- zelf is dan alleen nog de envelope (raw_text, afbeelding, dedupe) en
-- deze tabel houdt de per-coin-uitkomst. Zie
-- docs/superpowers/specs/2026-09-10-multi-coin-berichten-design.md.
CREATE TABLE IF NOT EXISTS message_coin_results (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id),
    coin TEXT,
    direction TEXT,
    category TEXT,
    unclear INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    message_summary TEXT,
    price_at_receipt REAL,
    narrative_id INTEGER REFERENCES coin_narratives(id),
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_message_coin_results_message_id ON message_coin_results(message_id);
CREATE INDEX IF NOT EXISTS idx_message_coin_results_coin ON message_coin_results(coin);
CREATE INDEX IF NOT EXISTS idx_message_coin_results_unclear ON message_coin_results(unclear);

-- Bron niveaus, overgenomen uit Discord afbeeldingen. Altijd bewaard,
-- ongeacht categorie van het bericht.
CREATE TABLE IF NOT EXISTS source_levels (
```

Geen wijziging in `app/db.py` nodig: `init_db()` draait `schema.sql` via
`executescript()` op elke opstart (`main.py`/`web/main.py` roepen
`db.init_db()` aan), en `CREATE TABLE IF NOT EXISTS` voor een tabel die op
een bestaande database nog niet bestaat wordt daarbij gewoon aangemaakt.
Dit verschilt van een NIEUWE KOLOM op een BESTAANDE tabel (dat heeft wél
een `_migrate()`-stap nodig, zie de andere ALTER TABLE-regels in
`db.py:_migrate()` voor dat patroon) — hier is `message_coin_results` een
volledig nieuwe tabel, geen bestaande tabel die van vorm verandert.

- [ ] **Step 2: Schrijf het eerste deel van het testscript (nieuwe tabel + basisfuncties), bevestig dat het faalt**

Maak `<SCRATCHPAD>/test_message_coin_results.py`:

```python
import os
import sys
import tempfile

sys.path.insert(0, "/home/user/Trade")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-message-coin-results-01234567890"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path
from app import db, repo

db.init_db()

passed = failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  OK  {label}")
    else:
        failed += 1
        print(f"  FAIL {label}")


message_id = repo.insert_message("BNB en TAO tegelijk", [], None)

# --- insert + read ---
bnb_result_id = repo.insert_message_coin_result(message_id, "BNB", "long", "day_trading", False, note="")
tao_result_id = repo.insert_message_coin_result(message_id, "TAO", "short", "day_trading", False, note="")
check("twee verschillende result-ids", bnb_result_id != tao_result_id)

results = repo.list_message_coin_results(message_id)
check("beide resultaten terug te vinden via list_message_coin_results", len(results) == 2)
check("BNB-resultaat heeft coin BNB", any(r["coin"] == "BNB" and r["id"] == bnb_result_id for r in results))

# --- updates ---
repo.set_message_coin_result_summary(bnb_result_id, "BNB samenvatting")
repo.set_message_coin_result_price_at_receipt(tao_result_id, 320.5)
updated = {r["id"]: r for r in repo.list_message_coin_results(message_id)}
check("message_summary opgeslagen op het juiste resultaat", updated[bnb_result_id]["message_summary"] == "BNB samenvatting")
check("TAO's summary NIET aangeraakt door BNB's update", updated[tao_result_id]["message_summary"] is None)
check("price_at_receipt opgeslagen op het juiste resultaat", updated[tao_result_id]["price_at_receipt"] == 320.5)

# --- envelope processed ---
repo.mark_message_envelope_processed(message_id)
with db.session() as conn:
    row = conn.execute("SELECT processed_at, coin FROM messages WHERE id = ?", (message_id,)).fetchone()
check("messages.processed_at gezet door mark_message_envelope_processed", row["processed_at"] is not None)
check("messages.coin blijft leeg (envelope-conventie, coin leeft in message_coin_results)", row["coin"] is None)

# --- copy voor dedupe ---
dup_message_id = repo.insert_message("BNB en TAO tegelijk", [], None)
repo.copy_message_coin_results(message_id, dup_message_id, "duplicaat van bericht #%s, niet opnieuw verwerkt" % message_id)
dup_results = repo.list_message_coin_results(dup_message_id)
check("dedupe-kopie heeft evenveel resultaten als het origineel", len(dup_results) == 2)
check("dedupe-kopie se coins matchen het origineel", {r["coin"] for r in dup_results} == {"BNB", "TAO"})
check("dedupe-kopie se note bevat de duplicaat-vermelding", all("duplicaat van bericht" in (r["note"] or "") for r in dup_results))

print(f"\n=== {passed} geslaagd, {failed} gefaald ===")
sys.exit(1 if failed else 0)
```

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_message_coin_results.py
```

Verwacht: faalt (`AttributeError`, de functies bestaan nog niet).

- [ ] **Step 3: Implementeer de nieuwe functies in `app/repo.py`**

Zoek de sectie direct na `mark_message_untracked` en vóór
`recent_unclear_messages`:

```python
def recent_unclear_messages(limit: int = 15) -> list[dict]:
```

Voeg er vlak vóór toe:

```python
def insert_message_coin_result(
    message_id: int, coin: Optional[str], direction: Optional[str],
    category: Optional[str], unclear: bool, note: str = "",
) -> int:
    """Eén rij per coin die een (mogelijk multi-coin) bericht behandelt.
    Wordt meteen bij het begin van de per-coin-verwerking aangemaakt (zie
    signal_processor._process_one_coin), de latere velden
    (message_summary/price_at_receipt/narrative_id) komen er via de
    set_*-functies hieronder bij zodra ze bekend worden."""
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO message_coin_results
               (message_id, coin, direction, category, unclear, note, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)""",
            (message_id, coin, direction, category, int(unclear), note or None, db.now_iso()),
        )
        return cur.lastrowid


def set_message_coin_result_summary(result_id: int, summary: str) -> None:
    with db.session() as conn:
        conn.execute("UPDATE message_coin_results SET message_summary = ? WHERE id = ?", (summary, result_id))


def set_message_coin_result_price_at_receipt(result_id: int, price: float) -> None:
    with db.session() as conn:
        conn.execute("UPDATE message_coin_results SET price_at_receipt = ? WHERE id = ?", (price, result_id))


def list_message_coin_results(message_id: int) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM message_coin_results WHERE message_id = ? ORDER BY id", (message_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def copy_message_coin_results(source_message_id: int, target_message_id: int, extra_note_suffix: str) -> None:
    """Voor het dedupe-pad (zie signal_processor.handle_message): kopieert
    alle coin-resultaten van het originele bericht naar het nieuwe
    (duplicaat) bericht, met de duidelijkmakende suffix aan de note
    toegevoegd, zodat een duplicaat van een multi-coin bericht ALLE coins
    overneemt, niet alleen de eerste."""
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM message_coin_results WHERE message_id = ?", (source_message_id,),
        ).fetchall()
        for row in rows:
            existing_note = row["note"] or ""
            new_note = f"{existing_note} ({extra_note_suffix})".strip() if existing_note else extra_note_suffix
            conn.execute(
                """INSERT INTO message_coin_results
                   (message_id, coin, direction, category, unclear, note, message_summary,
                    price_at_receipt, narrative_id, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (target_message_id, row["coin"], row["direction"], row["category"], row["unclear"],
                 new_note, row["message_summary"], row["price_at_receipt"], row["narrative_id"], db.now_iso()),
            )


def mark_message_envelope_processed(message_id: int) -> None:
    """Zet alleen processed_at: voor een bericht dat via
    message_coin_results is afgehandeld (één of meer coins gevonden), in
    tegenstelling tot mark_message_processed hieronder dat coin/direction/
    category/unclear/note rechtstreeks op messages zet — dat blijft het
    pad voor de twee gevallen die geen per-coin-resultaat hebben: een
    totale Anthropic-mislukking, en (indirect, via copy_message_coin_results
    hierboven) een dedupe-duplicaat."""
    with db.session() as conn:
        conn.execute("UPDATE messages SET processed_at = ? WHERE id = ?", (db.now_iso(), message_id))


```

- [ ] **Step 4: Run het testscript, bevestig dat alle asserties tot nu toe slagen**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_message_coin_results.py
```

Verwacht: `=== 9 geslaagd, 0 gefaald ===`.

- [ ] **Step 5: Fix de coin-scoping bug in `list_source_levels_for_message` (de kritieke, verplichte fix uit spec Sectie 4)**

Zoek:

```python
def list_source_levels_for_message(message_id: int) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM source_levels WHERE message_id = ?", (message_id,),
        ).fetchall()
        return [dict(r) for r in rows]
```

Vervang door:

```python
def list_source_levels_for_message(message_id: int, coin: str) -> list[dict]:
    """Verplicht coin-gescopet: met meerdere coins per bericht (zie
    message_coin_results) delen ze hetzelfde message_id, dus zonder
    coin-filter zou coin A hier coin B se niveaus meekrijgen in zijn
    stop/take-berekening — exact de klasse bug die dit hele multi-coin-
    plan repareert, nu een laag dieper."""
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM source_levels WHERE message_id = ? AND coin = ?", (message_id, coin.upper()),
        ).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 6: Fix de coin-scoping bug in de narrative-koppeling (spec Sectie 4b)**

Zoek:

```python
def create_narrative(coin: str, direction: str, message_id: int) -> int:
    """Nieuw narrative, status 'actief', met dit bericht als eerste update."""
    now = db.now_iso()
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO coin_narratives (coin, direction, status, message_count, opened_at, last_update_at)
               VALUES (?, ?, 'actief', 1, ?, ?)""",
            (coin.upper(), direction.lower(), now, now),
        )
        narrative_id = cur.lastrowid
        conn.execute("UPDATE messages SET narrative_id = ? WHERE id = ?", (narrative_id, message_id))
        return narrative_id


def update_narrative_progress(narrative_id: int, message_id: int) -> None:
    """Koppelt een bericht als vervolg-update aan een bestaand narrative:
    telt message_count op, zet last_update_at bij op nu."""
    now = db.now_iso()
    with db.session() as conn:
        conn.execute(
            "UPDATE coin_narratives SET message_count = message_count + 1, last_update_at = ? WHERE id = ?",
            (now, narrative_id),
        )
        conn.execute("UPDATE messages SET narrative_id = ? WHERE id = ?", (narrative_id, message_id))
```

Vervang door:

```python
def create_narrative(coin: str, direction: str, result_id: int) -> int:
    """Nieuw narrative, status 'actief', met dit coin-resultaat als eerste
    update. `result_id` is het id van de message_coin_results-rij voor
    DEZE coin (niet het message_id): met meerdere coins per bericht delen
    ze hetzelfde message_id, dus narrative_id moet op het per-coin-
    resultaat komen te staan, anders koppelt een narrative voor coin A het
    hele bericht (dus ook coin B se niet-gerelateerde resultaat) eraan
    vast."""
    now = db.now_iso()
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO coin_narratives (coin, direction, status, message_count, opened_at, last_update_at)
               VALUES (?, ?, 'actief', 1, ?, ?)""",
            (coin.upper(), direction.lower(), now, now),
        )
        narrative_id = cur.lastrowid
        conn.execute("UPDATE message_coin_results SET narrative_id = ? WHERE id = ?", (narrative_id, result_id))
        return narrative_id


def update_narrative_progress(narrative_id: int, result_id: int) -> None:
    """Koppelt een coin-resultaat als vervolg-update aan een bestaand
    narrative: telt message_count op, zet last_update_at bij op nu.
    `result_id` is het id van de message_coin_results-rij, zelfde reden als
    create_narrative hierboven."""
    now = db.now_iso()
    with db.session() as conn:
        conn.execute(
            "UPDATE coin_narratives SET message_count = message_count + 1, last_update_at = ? WHERE id = ?",
            (now, narrative_id),
        )
        conn.execute("UPDATE message_coin_results SET narrative_id = ? WHERE id = ?", (narrative_id, result_id))
```

- [ ] **Step 7: Werk `list_narrative_messages` bij zodat het via `message_coin_results` leest, met een legacy-tak voor pre-migratie rijen**

Zoek:

```python
def list_narrative_messages(narrative_id: int) -> list[dict]:
    """De berichten van dit narrative, oudste eerst: de tijdlijn voor zowel
    de Telegram-melding als de coin-pagina-kaart."""
    with db.session() as conn:
        rows = conn.execute(
            "SELECT id, received_at, raw_text, message_summary FROM messages "
            "WHERE narrative_id = ? ORDER BY received_at ASC",
            (narrative_id,),
        ).fetchall()
        return [dict(r) for r in rows]
```

Vervang door:

```python
def list_narrative_messages(narrative_id: int) -> list[dict]:
    """De berichten van dit narrative, oudste eerst: de tijdlijn voor zowel
    de Telegram-melding als de coin-pagina-kaart. Twee bronnen samengevoegd:
    message_coin_results (nieuwe, coin-gescopete koppeling) en messages
    zelf (historische rijen van vóór de multi-coin-wijziging, die hun
    narrative_id nog rechtstreeks op messages hebben staan)."""
    with db.session() as conn:
        per_coin_rows = conn.execute(
            """SELECT m.id AS id, m.received_at AS received_at, m.raw_text AS raw_text,
                      mcr.message_summary AS message_summary
               FROM message_coin_results mcr
               JOIN messages m ON m.id = mcr.message_id
               WHERE mcr.narrative_id = ?""",
            (narrative_id,),
        ).fetchall()
        legacy_rows = conn.execute(
            "SELECT id, received_at, raw_text, message_summary FROM messages "
            "WHERE narrative_id = ?",
            (narrative_id,),
        ).fetchall()
    combined = [dict(r) for r in per_coin_rows] + [dict(r) for r in legacy_rows]
    combined.sort(key=lambda r: r["received_at"])
    return combined
```

- [ ] **Step 8: Werk `recent_unclear_messages` bij zodat het ook per-coin-onduidelijkheden toont**

Zoek:

```python
def recent_unclear_messages(limit: int = 15) -> list[dict]:
    """Berichten die Anthropic niet als duidelijk signaal kon interpreteren,
    laatste [limit] stuks. Zonder dit verdwijnt zo'n bericht stil: geen
    signaal, geen melding, geen spoor in het dashboard, terwijl de
    afzender wel iets deelde. Globaal (niet per gebruiker), net als de
    rest van de berichtenverwerking."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT id, received_at, coin, raw_text, note FROM messages
               WHERE unclear = 1 AND processed_at IS NOT NULL
               ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]
```

Vervang door:

```python
def recent_unclear_messages(limit: int = 15) -> list[dict]:
    """Berichten (of, sinds multi-coin-ondersteuning, individuele coins
    binnen een bericht) die Anthropic niet als duidelijk signaal kon
    interpreteren, laatste [limit] stuks. Zonder dit verdwijnt zo'n
    bericht/coin stil: geen signaal, geen melding, geen spoor in het
    dashboard, terwijl de afzender wel iets deelde. Globaal (niet per
    gebruiker), net als de rest van de berichtenverwerking.

    Twee bronnen samengevoegd: message_coin_results (nieuwe per-coin-
    onduidelijkheden) en messages zelf (de twee gevallen die nog
    rechtstreeks op messages staan: een totale Anthropic-mislukking, en
    historische pre-migratie rijen)."""
    with db.session() as conn:
        legacy_rows = conn.execute(
            """SELECT id, received_at, coin, raw_text, note FROM messages
               WHERE unclear = 1 AND processed_at IS NOT NULL
               ORDER BY id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        per_coin_rows = conn.execute(
            """SELECT mcr.id AS id, m.received_at AS received_at, mcr.coin AS coin,
                      m.raw_text AS raw_text, mcr.note AS note
               FROM message_coin_results mcr
               JOIN messages m ON m.id = mcr.message_id
               WHERE mcr.unclear = 1
               ORDER BY mcr.id DESC LIMIT ?""",
            (limit,),
        ).fetchall()
    combined = [dict(r) for r in legacy_rows] + [dict(r) for r in per_coin_rows]
    combined.sort(key=lambda r: r["received_at"], reverse=True)
    return combined[:limit]
```

- [ ] **Step 9: Werk `list_messages_for_summary_backfill` bij met een `source`-tag per item**

Zoek:

```python
def list_messages_for_summary_backfill() -> list[dict]:
    """Alle verwerkte, niet-onduidelijke berichten met tekst, oudste eerst.
    Voor scripts/regenerate_message_summaries.py: eenmalig alsnog een
    samenvatting genereren voor berichten van voor een prompt-verbetering."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT id, coin, raw_text, message_summary FROM messages
               WHERE processed_at IS NOT NULL AND unclear = 0 AND raw_text != ''
               ORDER BY id"""
        ).fetchall()
        return [dict(r) for r in rows]
```

Vervang door:

```python
def list_messages_for_summary_backfill() -> list[dict]:
    """Alle verwerkte, niet-onduidelijke berichten (of coin-resultaten) met
    tekst, oudste eerst. Voor scripts/regenerate_message_summaries.py:
    eenmalig alsnog een samenvatting genereren voor berichten van voor een
    prompt-verbetering.

    Elk item krijgt een "source"-key: "legacy" (rechtstreeks op messages,
    van vóór de multi-coin-wijziging — regenereren via set_message_summary)
    of "coin_result" (via message_coin_results — regenereren via
    set_message_coin_result_summary)."""
    with db.session() as conn:
        legacy_rows = conn.execute(
            """SELECT id, coin, raw_text, message_summary FROM messages
               WHERE processed_at IS NOT NULL AND unclear = 0 AND raw_text != ''
               ORDER BY id"""
        ).fetchall()
        coin_result_rows = conn.execute(
            """SELECT mcr.id AS id, mcr.coin AS coin, m.raw_text AS raw_text,
                      mcr.message_summary AS message_summary
               FROM message_coin_results mcr
               JOIN messages m ON m.id = mcr.message_id
               WHERE mcr.unclear = 0 AND m.raw_text != ''
               ORDER BY mcr.id"""
        ).fetchall()
    result = [dict(r, source="legacy") for r in legacy_rows]
    result += [dict(r, source="coin_result") for r in coin_result_rows]
    return result
```

- [ ] **Step 10: Run het volledige testscript nogmaals, bevestig dat alles nog slaagt**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_message_coin_results.py
```

Verwacht: nog steeds `=== 9 geslaagd, 0 gefaald ===` (deze stappen wijzigen
geen gedrag dat het testscript uit Step 2 al controleerde, maar een
hernieuwde run bevestigt dat er niets kapot is gegaan).

- [ ] **Step 11: Commit**

```bash
git add app/schema.sql app/repo.py
git commit -m "Database: message_coin_results-tabel + coin-scoping-fixes voor source_levels en narratives

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q"
```

---

### Task 3: `signal_processor.py` herstructureren + end-to-end integratietest

**Files:**
- Modify: `app/signal_processor.py` (`handle_message` splitst, nieuwe
  `_process_one_coin`, `evaluate_narrative`/`process_day_trading_signal`
  se aanroepen aangepast aan de Task 2-signaturen)
- Test: `<SCRATCHPAD>/test_multi_coin_pipeline.py`

**Interfaces:**
- Consumes: `anthropic_interpret.interpret_message` → `list[Interpretation]`
  (Task 1); `repo.insert_message_coin_result`,
  `repo.set_message_coin_result_summary`,
  `repo.set_message_coin_result_price_at_receipt`,
  `repo.copy_message_coin_results`, `repo.mark_message_envelope_processed`,
  `repo.list_source_levels_for_message(message_id, coin)`,
  `repo.create_narrative(coin, direction, result_id)`,
  `repo.update_narrative_progress(narrative_id, result_id)` (allemaal
  Task 2).
- Produces: `handle_message(message_id, raw_text, image_paths)` blijft qua
  signatuur ongewijzigd (aangeroepen door `app/discord_bot.py`, niet
  aangepast in dit plan).

- [ ] **Step 1: Pas `handle_message` aan**

Zoek de volledige huidige functie:

```python
async def handle_message(message_id: int, raw_text: str, image_paths: list[str]) -> None:
    duplicate = repo.find_recent_duplicate(raw_text, exclude_id=message_id) if raw_text.strip() else None
    if duplicate:
        logger.info("Bericht %s is een duplicaat van bericht %s, niet opnieuw verwerkt",
                    message_id, duplicate["id"])
        repo.mark_message_processed(
            message_id, duplicate["coin"], duplicate["direction"], duplicate["category"],
            bool(duplicate["unclear"]), note=f"duplicaat van bericht #{duplicate['id']}, niet opnieuw verwerkt",
        )
        return

    global _consecutive_interpret_failures
    try:
        interp = await asyncio.to_thread(_interpret_with_retry, raw_text, image_paths)
    except Exception as exc:
        logger.exception("Interpretatie van bericht %s definitief mislukt na %s pogingen",
                          message_id, INTERPRET_ATTEMPTS)
        repo.mark_message_processed(
            message_id, None, None, None, True,
            note=f"API fout, kon niet verwerkt worden: {exc}",
        )
        _consecutive_interpret_failures += 1
        if _consecutive_interpret_failures >= INTERPRET_FAILURE_ALERT_THRESHOLD:
            try:
                await telegram_notify.send_admin_alert(
                    f"🚨 Anthropic interpretatie is nu {_consecutive_interpret_failures} berichten op rij "
                    f"mislukt. Check de serverlog en de API-status.\n\nLaatste fout: {exc}"
                )
            except Exception:
                logger.exception("Kon admin-alert voor herhaalde API-fouten niet versturen")
        return

    _consecutive_interpret_failures = 0
    repo.mark_message_processed(message_id, interp.coin, interp.direction, interp.category,
                                 interp.unclear, note=interp.reason)

    if interp.unclear:
        logger.info("Bericht %s is onduidelijk (%s), overgeslagen voor verdere verwerking",
                    message_id, interp.reason)
        return

    # Het origineel doorgestuurde bericht herschreven in klare taal, los van
    # de technische plain_explanation die pas later (bij een day trading
    # signaal) berekend wordt. Geldt voor beide categorieën: een lange
    # termijn analyse is vaak juist de langste, meest jargon-rijke tekst.
    message_summary = await asyncio.to_thread(explain.summarize_message, interp.coin, raw_text)
    if message_summary:
        repo.set_message_summary(message_id, message_summary)

    # Bron niveaus uit afbeeldingen worden altijd bewaard, ongeacht categorie.
    if interp.source_levels:
        tracked, is_new_coin = await asyncio.to_thread(coinlist.ensure_coin_tracked, interp.coin)
        if is_new_coin:
            await _notify_new_coin(interp.coin)
        if not tracked:
            logger.info("Coin %s uit bron niveaus bestaat niet op de exchange, niveaus niet bewaard",
                        interp.coin)
        else:
            live_price = None
            try:
                live_price = await asyncio.to_thread(exchange.fetch_last_price, interp.coin)
            except Exception:
                logger.exception("Live prijs voor %s kon niet opgehaald worden, niveaus zonder aannemelijkheidscheck bewaard",
                                  interp.coin)
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
                # pijplijn (process_day_trading_signal, zie Step 12). Een
                # parallelle swing-watch voor exact hetzelfde bericht voegt
                # niets toe behalve een dubbele melding en dubbel
                # risicobedrag voor dezelfde kans.
                if interp.category != "day_trading":
                    try:
                        await evaluate_level_watch(
                            message_id, interp.coin, interp.direction, source_level_id, level.price_level,
                        )
                    except Exception:
                        logger.exception("Swing-watch evaluatie voor %s (bericht %s) is mislukt",
                                          interp.coin, message_id)

    if interp.category != "day_trading":
        logger.info("Bericht %s valt in categorie %s, alleen gelogd, geen melding",
                    message_id, interp.category)
        # Live koers vastleggen op het moment van deze analyse: zonder dit
        # referentiepunt kan achteraf nooit gemeten worden of de richting
        # klopte (zie repo.coin_long_term_track_record). Mislukt de
        # koersophaal, dan telt deze analyse straks gewoon niet mee in het
        # trackrecord, geen reden om de rest van de verwerking te blokkeren.
        if interp.direction in ("long", "short"):
            try:
                live_price = await asyncio.to_thread(exchange.fetch_last_price, interp.coin)
                repo.set_message_price_at_receipt(message_id, live_price)
            except Exception:
                logger.exception("Live prijs voor lange-termijn analyse %s kon niet vastgelegd worden",
                                  interp.coin)

        # Tot nu toe volledig stil: je zag een lange termijn analyse pas
        # terug zodra een latere day trading melding voor dezelfde coin
        # ernaar verwees (_build_context_note). Met de samenvatting hierboven
        # is een korte, stille melding hierover goedkoop, en voorkomt dat de
        # inhoud van een net doorgestuurde analyse in de tussentijd onzichtbaar is.
        if interp.category == "lange_termijn" and interp.direction in ("long", "short"):
            try:
                await evaluate_narrative(message_id, interp.coin, interp.direction)
            except Exception:
                logger.exception("Narrative-evaluatie voor %s (bericht %s) is mislukt",
                                  interp.coin, message_id)
        elif message_summary:
            for user in repo.list_users():
                if not user["telegram_chat_id"]:
                    continue
                try:
                    await telegram_notify.send_long_term_message(
                        interp.coin, interp.direction, message_summary,
                        chat_id=user["telegram_chat_id"],
                    )
                except Exception:
                    logger.exception("Lange-termijn melding voor %s naar gebruiker %s is mislukt",
                                      interp.coin, user["username"])
        return

    await process_day_trading_signal(message_id, interp)
```

Vervang door:

```python
async def handle_message(message_id: int, raw_text: str, image_paths: list[str]) -> None:
    duplicate = repo.find_recent_duplicate(raw_text, exclude_id=message_id) if raw_text.strip() else None
    if duplicate:
        logger.info("Bericht %s is een duplicaat van bericht %s, niet opnieuw verwerkt",
                    message_id, duplicate["id"])
        repo.copy_message_coin_results(
            duplicate["id"], message_id,
            f"duplicaat van bericht #{duplicate['id']}, niet opnieuw verwerkt",
        )
        repo.mark_message_envelope_processed(message_id)
        return

    global _consecutive_interpret_failures
    try:
        interpretations = await asyncio.to_thread(_interpret_with_retry, raw_text, image_paths)
    except Exception as exc:
        logger.exception("Interpretatie van bericht %s definitief mislukt na %s pogingen",
                          message_id, INTERPRET_ATTEMPTS)
        repo.mark_message_processed(
            message_id, None, None, None, True,
            note=f"API fout, kon niet verwerkt worden: {exc}",
        )
        _consecutive_interpret_failures += 1
        if _consecutive_interpret_failures >= INTERPRET_FAILURE_ALERT_THRESHOLD:
            try:
                await telegram_notify.send_admin_alert(
                    f"🚨 Anthropic interpretatie is nu {_consecutive_interpret_failures} berichten op rij "
                    f"mislukt. Check de serverlog en de API-status.\n\nLaatste fout: {exc}"
                )
            except Exception:
                logger.exception("Kon admin-alert voor herhaalde API-fouten niet versturen")
        return

    _consecutive_interpret_failures = 0
    for interp in interpretations:
        await _process_one_coin(message_id, raw_text, interp)
    repo.mark_message_envelope_processed(message_id)


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

    if interp.unclear:
        logger.info("Bericht %s (coin %s) is onduidelijk (%s), overgeslagen voor verdere verwerking",
                    message_id, interp.coin, interp.reason)
        return

    # Het origineel doorgestuurde bericht herschreven in klare taal, los van
    # de technische plain_explanation die pas later (bij een day trading
    # signaal) berekend wordt. Geldt voor beide categorieën: een lange
    # termijn analyse is vaak juist de langste, meest jargon-rijke tekst.
    message_summary = await asyncio.to_thread(explain.summarize_message, interp.coin, raw_text)
    if message_summary:
        repo.set_message_coin_result_summary(result_id, message_summary)

    # Bron niveaus uit afbeeldingen worden altijd bewaard, ongeacht categorie.
    if interp.source_levels:
        tracked, is_new_coin = await asyncio.to_thread(coinlist.ensure_coin_tracked, interp.coin)
        if is_new_coin:
            await _notify_new_coin(interp.coin)
        if not tracked:
            logger.info("Coin %s uit bron niveaus bestaat niet op de exchange, niveaus niet bewaard",
                        interp.coin)
        else:
            live_price = None
            try:
                live_price = await asyncio.to_thread(exchange.fetch_last_price, interp.coin)
            except Exception:
                logger.exception("Live prijs voor %s kon niet opgehaald worden, niveaus zonder aannemelijkheidscheck bewaard",
                                  interp.coin)
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

    if interp.category != "day_trading":
        logger.info("Bericht %s (coin %s) valt in categorie %s, alleen gelogd, geen melding",
                    message_id, interp.coin, interp.category)
        # Live koers vastleggen op het moment van deze analyse: zonder dit
        # referentiepunt kan achteraf nooit gemeten worden of de richting
        # klopte (zie repo.coin_long_term_track_record). Mislukt de
        # koersophaal, dan telt deze analyse straks gewoon niet mee in het
        # trackrecord, geen reden om de rest van de verwerking te blokkeren.
        if interp.direction in ("long", "short"):
            try:
                live_price = await asyncio.to_thread(exchange.fetch_last_price, interp.coin)
                repo.set_message_coin_result_price_at_receipt(result_id, live_price)
            except Exception:
                logger.exception("Live prijs voor lange-termijn analyse %s kon niet vastgelegd worden",
                                  interp.coin)

        # Tot nu toe volledig stil: je zag een lange termijn analyse pas
        # terug zodra een latere day trading melding voor dezelfde coin
        # ernaar verwees (_build_context_note). Met de samenvatting hierboven
        # is een korte, stille melding hierover goedkoop, en voorkomt dat de
        # inhoud van een net doorgestuurde analyse in de tussentijd onzichtbaar is.
        if interp.category == "lange_termijn" and interp.direction in ("long", "short"):
            try:
                await evaluate_narrative(interp.coin, interp.direction, result_id)
            except Exception:
                logger.exception("Narrative-evaluatie voor %s (bericht %s) is mislukt",
                                  interp.coin, message_id)
        elif message_summary:
            for user in repo.list_users():
                if not user["telegram_chat_id"]:
                    continue
                try:
                    await telegram_notify.send_long_term_message(
                        interp.coin, interp.direction, message_summary,
                        chat_id=user["telegram_chat_id"],
                    )
                except Exception:
                    logger.exception("Lange-termijn melding voor %s naar gebruiker %s is mislukt",
                                      interp.coin, user["username"])
        return

    await process_day_trading_signal(message_id, interp)
```

Let op: `evaluate_narrative`'s aanroep verandert van
`evaluate_narrative(message_id, interp.coin, interp.direction)` naar
`evaluate_narrative(interp.coin, interp.direction, result_id)` — de
volgende stap past de functie zelf hierop aan.

- [ ] **Step 2: Pas `evaluate_narrative` aan naar de nieuwe parameter (`result_id` i.p.v. `message_id`)**

Zoek:

```python
async def evaluate_narrative(message_id: int, coin: str, direction: str) -> None:
    """Aangeroepen voor elk lange_termijn-bericht met een duidelijke
    richting (long/short — 'neutraal' en een ontbrekende richting doen
    hier niet aan mee, net als bij _build_context_note). Bepaalt of dit
    bericht een update is van het lopende verhaal over deze coin, een
    tegenspraak daarvan, of het begin van een nieuw verhaal.

    Tegenspraak sluit het oude narrative expliciet af (status
    'tegengesproken') vóór er een nieuwe wordt aangemaakt: er hoort op elk
    moment hoogstens één actief narrative per coin te zijn, ongeacht welke
    richting."""
    if direction not in ("long", "short"):
        return

    active = repo.get_active_narrative(coin)
    if active is None:
        narrative_id = repo.create_narrative(coin, direction, message_id)
        await _send_narrative_notifications(narrative_id, is_new=True, is_contradiction=False)
        return

    if active["direction"] == direction:
        repo.update_narrative_progress(active["id"], message_id)
        await _send_narrative_notifications(active["id"], is_new=False, is_contradiction=False)
        return

    repo.close_narrative(
        active["id"], "tegengesproken",
        f"tegengesproken door een nieuw {direction}-narrative voor {coin}",
    )
    new_narrative_id = repo.create_narrative(coin, direction, message_id)
    await _send_narrative_notifications(
        new_narrative_id, is_new=True, is_contradiction=True, contradicted=active,
    )
```

Vervang door:

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

- [ ] **Step 3: Pas de `list_source_levels_for_message`-aanroep aan in `process_day_trading_signal`**

Zoek:

```python
    message_levels = [lvl["price_level"] for lvl in repo.list_source_levels_for_message(message_id)]
```

Vervang door:

```python
    message_levels = [lvl["price_level"] for lvl in repo.list_source_levels_for_message(message_id, interp.coin)]
```

- [ ] **Step 4: Schrijf en run de end-to-end multi-coin-integratietest**

Maak `<SCRATCHPAD>/test_multi_coin_pipeline.py`, naar het patroon van
eerdere sessie-integratietests (tijdelijke DB, gemockte
`anthropic_interpret.interpret_message`, gemockte `exchange`-calls):

```python
import asyncio
import os
import sys
import tempfile
from unittest.mock import patch

sys.path.insert(0, "/home/user/Trade")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd)
os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-multi-coin-pipeline-0123456789012"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path
config.ENABLE_ADVANCED_FACTORS = False

from app import db, repo, security, signal_processor, coinlist
from app.anthropic_interpret import Interpretation, SourceLevel
from app.db import session as db_session

import pandas as pd
import numpy as np

db.init_db()
repo.create_user("multicoinuser", security.hash_password("testpass123"), 10000.0, 1.0, "1")
repo.add_coin_if_new("BNBUSDT", "spot")
repo.add_coin_if_new("TAOUSDT", "spot")

# BNB long met een niveau vlak onder de laatste prijs (~550), TAO short met
# een niveau vlak boven de laatste prijs (~320) — bewust ver uit elkaar
# gekozen zodat een lek tussen coins meteen zichtbaar zou zijn: als TAO's
# stop_loss ergens rond 550 uitkomt, is BNB's niveau gelekt.
interpretations = [
    Interpretation(
        coin="BNB", direction="long", category="day_trading", unclear=False,
        source_levels=[SourceLevel(price_level=540.0, pattern_name="support")],
    ),
    Interpretation(
        coin="TAO", direction="short", category="day_trading", unclear=False,
        source_levels=[SourceLevel(price_level=330.0, pattern_name="weerstand")],
    ),
]

n = 60
fake_bnb = pd.DataFrame({
    "open": np.linspace(548, 552, n), "high": np.linspace(549, 553, n),
    "low": np.linspace(547, 551, n), "close": np.linspace(548, 552, n),
    "volume": np.full(n, 500000.0),
})
fake_tao = pd.DataFrame({
    "open": np.linspace(318, 322, n), "high": np.linspace(319, 323, n),
    "low": np.linspace(317, 321, n), "close": np.linspace(318, 322, n),
    "volume": np.full(n, 500000.0),
})
fake_btc = pd.DataFrame({
    "open": np.linspace(65000, 64000, n), "high": np.linspace(65100, 64100, n),
    "low": np.linspace(64900, 63900, n), "close": np.linspace(65000, 64000, n),
    "volume": np.full(n, 100.0),
})


def fake_fetch_ohlcv(coin, timeframe="4h"):
    if coin.upper() == "BTC":
        return fake_btc
    if coin.upper() == "BNB":
        return fake_bnb
    return fake_tao


def fake_last_price(coin):
    return float(fake_bnb["close"].iloc[-1]) if coin.upper() == "BNB" else float(fake_tao["close"].iloc[-1])


with patch("app.signal_processor.anthropic_interpret.interpret_message" if False else "app.signal_processor.interpret_message", return_value=interpretations), \
     patch("app.signal_processor.exchange.fetch_ohlcv", side_effect=fake_fetch_ohlcv), \
     patch("app.signal_processor.exchange.fetch_last_price", side_effect=fake_last_price), \
     patch("app.signal_processor.exchange.fetch_24h_quote_volume", return_value=5_000_000.0), \
     patch.object(coinlist, "ensure_coin_tracked", return_value=(True, False)):
    message_id = repo.insert_message("BNB long op 540, TAO short op 330", [], None)
    asyncio.run(signal_processor.handle_message(message_id, "BNB long op 540, TAO short op 330", []))

passed = failed = 0


def check(label, condition):
    global passed, failed
    if condition:
        passed += 1
        print(f"  OK  {label}")
    else:
        failed += 1
        print(f"  FAIL {label}")


with db_session() as conn:
    envelope = conn.execute("SELECT processed_at, coin FROM messages WHERE id = ?", (message_id,)).fetchone()
    results = conn.execute(
        "SELECT * FROM message_coin_results WHERE message_id = ? ORDER BY coin", (message_id,),
    ).fetchall()
    bnb_levels = conn.execute(
        "SELECT price_level FROM source_levels WHERE message_id = ? AND coin = 'BNB'", (message_id,),
    ).fetchall()
    tao_levels = conn.execute(
        "SELECT price_level FROM source_levels WHERE message_id = ? AND coin = 'TAO'", (message_id,),
    ).fetchall()
    bnb_signal = conn.execute(
        "SELECT stop_loss, take_profit FROM signals WHERE message_id = ? AND coin = 'BNB' ORDER BY id DESC LIMIT 1",
        (message_id,),
    ).fetchone()
    tao_signal = conn.execute(
        "SELECT stop_loss, take_profit FROM signals WHERE message_id = ? AND coin = 'TAO' ORDER BY id DESC LIMIT 1",
        (message_id,),
    ).fetchone()

check("envelope processed_at gezet", envelope["processed_at"] is not None)
check("envelope coin blijft leeg (per-coin data leeft in message_coin_results)", envelope["coin"] is None)
check("twee message_coin_results-rijen (BNB, TAO)", len(results) == 2)
check("BNB heeft precies 1 source_level (540.0), niet TAO's niveau", len(bnb_levels) == 1 and bnb_levels[0]["price_level"] == 540.0)
check("TAO heeft precies 1 source_level (330.0), niet BNB's niveau", len(tao_levels) == 1 and tao_levels[0]["price_level"] == 330.0)
check("BNB kreeg een eigen signal-rij", bnb_signal is not None)
check("TAO kreeg een eigen signal-rij", tao_signal is not None)
if bnb_signal and tao_signal:
    check(
        "BNB's stop_loss ligt in de buurt van BNB's eigen prijs (~550), niet TAO's (~320)",
        500 < bnb_signal["stop_loss"] < 600,
    )
    check(
        "TAO's stop_loss ligt in de buurt van TAO's eigen prijs (~320), niet BNB's (~550) — geen lek",
        280 < tao_signal["stop_loss"] < 360,
    )

# --- dedupe: hetzelfde bericht nogmaals, moet beide coin-resultaten kopiëren, niet opnieuw naar Anthropic ---
with patch("app.signal_processor.interpret_message") as mock_interpret, \
     patch("app.signal_processor.exchange.fetch_ohlcv", side_effect=fake_fetch_ohlcv), \
     patch("app.signal_processor.exchange.fetch_last_price", side_effect=fake_last_price), \
     patch("app.signal_processor.exchange.fetch_24h_quote_volume", return_value=5_000_000.0), \
     patch.object(coinlist, "ensure_coin_tracked", return_value=(True, False)):
    dup_message_id = repo.insert_message("BNB long op 540, TAO short op 330", [], None)
    asyncio.run(signal_processor.handle_message(dup_message_id, "BNB long op 540, TAO short op 330", []))
    check("dedupe: interpret_message NIET opnieuw aangeroepen", mock_interpret.call_count == 0)

with db_session() as conn:
    dup_results = conn.execute(
        "SELECT coin FROM message_coin_results WHERE message_id = ?", (dup_message_id,),
    ).fetchall()
check("dedupe: beide coin-resultaten gekopieerd naar het nieuwe bericht", {r["coin"] for r in dup_results} == {"BNB", "TAO"})

print(f"\n=== {passed} geslaagd, {failed} gefaald ===")
sys.exit(1 if failed else 0)
```

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_multi_coin_pipeline.py
```

Verwacht: script eindigt met `=== 10 geslaagd, 0 gefaald ===` (of meer,
als je extra checks toevoegt), geen traceback ervoor. Een `NetworkError`
van de Telegram-stap ná de laatste assertie is de bekende sandbox-
netwerkbeperking (zie CLAUDE.md), geen testfout. Faalt een assertie omdat
de fake OHLCV-data een andere stop_loss oplevert dan verwacht: pas de
assertie-marge aan op wat er echt uitkomt (print `bnb_signal`/`tao_signal`
om te zien), verander niet de productielogica om de test te laten slagen.

- [ ] **Step 5: Commit**

```bash
git add app/signal_processor.py
git commit -m "signal_processor: multi-coin berichten per coin apart verwerken

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q"
```

---

### Task 4: Dashboard (`web/main.py` + `repo.recent_unclear_messages`-gebruik)

**Files:**
- Modify: geen wijziging in `web/main.py` zelf verwacht (de aanroep
  `repo.recent_unclear_messages()` op regel 656 blijft ongewijzigd van
  signatuur, Task 2 heeft de functie-inhoud al aangepast) — deze taak is
  puur verificatie dat de template die de resultaten rendert nog steeds
  correct werkt met de nieuwe, samengevoegde resultaten.
- Test: `<SCRATCHPAD>/test_unclear_messages_dashboard.py`

**Interfaces:**
- Consumes: `repo.recent_unclear_messages()` (Task 2, al aangepast).
- Produces: geen nieuwe interface.

- [ ] **Step 1: Zoek waar `unclear_messages` in de template gebruikt wordt**

```bash
grep -rn "unclear_messages" /home/user/Trade/web/templates/
```

Lees het resultaat: controleer of de template alleen `id`, `received_at`,
`coin`, `raw_text`, `note` gebruikt (de velden die zowel de legacy- als de
nieuwe query in `repo.recent_unclear_messages` teruggeven) — geen ander
veld dat alleen op de oude, single-query vorm bestond. Als de template een
ander veld verwacht (bijvoorbeeld iets uit `messages` dat niet in de
samengevoegde query zit), pas de query in `repo.recent_unclear_messages`
(Task 2, Step 8) aan om dat veld ook mee te geven — dat is dan een fix op
deze taak, niet een aparte sub-taak.

- [ ] **Step 2: Schrijf en run een test die het admin-dashboard met een multi-coin onduidelijkheid bevestigt**

Maak `<SCRATCHPAD>/test_unclear_messages_dashboard.py`:

```python
import os, sys, tempfile
sys.path.insert(0, "/home/user/Trade")
sys.path.insert(0, "/home/user/Trade/web")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd); os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-unclear-dashboard-0123456789012"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"
os.environ["ADMIN_TELEGRAM_CHAT_ID"] = "admin-chat-id"

from app import config
config.DATABASE_PATH = db_path
config.ADMIN_TELEGRAM_CHAT_ID = "admin-chat-id"
from app import db, repo, security

db.init_db()
uid = repo.create_user("dashboardadmin", security.hash_password("testpass123"), 1000.0, 1.0, "1")
repo.update_user_settings(uid, 1000.0, 1.0, "admin-chat-id")

message_id = repo.insert_message("BNB duidelijk, LINK niet", [], None)
repo.insert_message_coin_result(message_id, "BNB", "long", "day_trading", False, note="")
repo.insert_message_coin_result(message_id, "LINK", None, "day_trading", True, note="richting niet duidelijk uit het bericht te halen")
repo.mark_message_envelope_processed(message_id)

import main as web_main
from fastapi.testclient import TestClient

client = TestClient(web_main.app)
token = security.create_session_token(uid)
client.cookies.set("session", token)

resp = client.get("/dashboard")
assert resp.status_code == 200, resp.text
html = resp.text
assert "LINK" in html, "LINK (de onduidelijke coin uit het multi-coin bericht) ontbreekt op het dashboard"
print("OK: LINK's onduidelijkheid is zichtbaar op het admin-dashboard, ook al kwam BNB uit hetzelfde bericht wel duidelijk uit")
```

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_unclear_messages_dashboard.py
```

Verwacht: `OK`-regel, geen traceback. Faalt dit omdat de dashboard-route
of -template andere velden/namen verwacht dan Step 1 aannam: pas Step 1's
fix toe en herhaal.

- [ ] **Step 3: Als Step 1 een aanpassing aan `repo.recent_unclear_messages` nodig maakte, commit die samen met deze test-bevestiging**

```bash
git add app/repo.py
git commit -m "recent_unclear_messages: veld-fix voor dashboard-template

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q"
```

Geen wijziging nodig gebleken: sla deze commit over, ga door naar Task 5.

---

### Task 5: `scripts/regenerate_message_summaries.py`

**Files:**
- Modify: `scripts/regenerate_message_summaries.py`
- Test: `<SCRATCHPAD>/test_regenerate_summaries.py`

**Interfaces:**
- Consumes: `repo.list_messages_for_summary_backfill()` (Task 2, geeft nu
  `"source"`-key per item), `repo.set_message_coin_result_summary` (Task 2).
- Produces: geen nieuwe interface.

- [ ] **Step 1: Schrijf de falende test**

Maak `<SCRATCHPAD>/test_regenerate_summaries.py`:

```python
import os, sys, tempfile
from unittest.mock import patch

sys.path.insert(0, "/home/user/Trade")

db_fd, db_path = tempfile.mkstemp(suffix=".db")
os.close(db_fd); os.remove(db_path)
os.environ["DATABASE_PATH"] = db_path
os.environ["JWT_SECRET"] = "test-secret-regenerate-summaries-012345678901"
os.environ["TELEGRAM_BOT_TOKEN"] = "dummy-token"

from app import config
config.DATABASE_PATH = db_path
from app import db, repo

db.init_db()

# Legacy-rij: rechtstreeks op messages, alsof van vóór de multi-coin-wijziging.
legacy_message_id = repo.insert_message("oud enkel-coin bericht over ETH", [], None)
repo.mark_message_processed(legacy_message_id, "ETH", "long", "day_trading", False, note="")

# Nieuwe rij: via message_coin_results.
new_message_id = repo.insert_message("nieuw multi-coin bericht met SOL", [], None)
result_id = repo.insert_message_coin_result(new_message_id, "SOL", "long", "day_trading", False, note="")
repo.mark_message_envelope_processed(new_message_id)

sys.path.insert(0, "/home/user/Trade/scripts")
import regenerate_message_summaries as script

with patch("regenerate_message_summaries.explain.summarize_message", return_value="Nieuwe samenvatting"):
    script.main(limit=None)

with db.session() as conn:
    legacy_row = conn.execute("SELECT message_summary FROM messages WHERE id = ?", (legacy_message_id,)).fetchone()
    new_row = conn.execute("SELECT message_summary FROM message_coin_results WHERE id = ?", (result_id,)).fetchone()

assert legacy_row["message_summary"] == "Nieuwe samenvatting", f"legacy-rij niet bijgewerkt: {legacy_row}"
print("OK: legacy-rij (messages.message_summary) bijgewerkt via set_message_summary")
assert new_row["message_summary"] == "Nieuwe samenvatting", f"nieuwe rij niet bijgewerkt: {new_row}"
print("OK: nieuwe rij (message_coin_results.message_summary) bijgewerkt via set_message_coin_result_summary")
```

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_regenerate_summaries.py
```

Verwacht: `AssertionError` op de nieuwe rij (het script schrijft nu nog
alleen naar `messages`, de `message_coin_results`-rij blijft leeg).

- [ ] **Step 2: Pas `scripts/regenerate_message_summaries.py` aan**

Zoek:

```python
def main(limit: int | None) -> None:
    db.init_db()
    messages = repo.list_messages_for_summary_backfill()
    if limit:
        messages = messages[:limit]

    print(f"{len(messages)} berichten om opnieuw samen te vatten.")
    updated = 0
    failed = 0
    for i, msg in enumerate(messages, start=1):
        summary = explain.summarize_message(msg["coin"] or "", msg["raw_text"])
        if summary:
            repo.set_message_summary(msg["id"], summary)
            updated += 1
            print(f"[{i}/{len(messages)}] bericht {msg['id']} ({msg['coin']}): OK")
        else:
            failed += 1
            print(f"[{i}/{len(messages)}] bericht {msg['id']} ({msg['coin']}): mislukt, overgeslagen")
        time.sleep(SLEEP_BETWEEN_CALLS_SECONDS)

    print(f"\nKlaar: {updated} bijgewerkt, {failed} mislukt van de {len(messages)} berichten.")
```

Vervang door:

```python
def main(limit: int | None) -> None:
    db.init_db()
    messages = repo.list_messages_for_summary_backfill()
    if limit:
        messages = messages[:limit]

    print(f"{len(messages)} berichten om opnieuw samen te vatten.")
    updated = 0
    failed = 0
    for i, msg in enumerate(messages, start=1):
        summary = explain.summarize_message(msg["coin"] or "", msg["raw_text"])
        if summary:
            if msg["source"] == "legacy":
                repo.set_message_summary(msg["id"], summary)
            else:
                repo.set_message_coin_result_summary(msg["id"], summary)
            updated += 1
            print(f"[{i}/{len(messages)}] bericht {msg['id']} ({msg['coin']}, {msg['source']}): OK")
        else:
            failed += 1
            print(f"[{i}/{len(messages)}] bericht {msg['id']} ({msg['coin']}, {msg['source']}): mislukt, overgeslagen")
        time.sleep(SLEEP_BETWEEN_CALLS_SECONDS)

    print(f"\nKlaar: {updated} bijgewerkt, {failed} mislukt van de {len(messages)} berichten.")
```

- [ ] **Step 3: Run de test, bevestig dat hij slaagt**

```bash
source /home/user/Trade/.venv/bin/activate && python3 <SCRATCHPAD>/test_regenerate_summaries.py
```

Verwacht: beide `OK`-regels, geen `AssertionError`.

- [ ] **Step 4: Commit**

```bash
git add scripts/regenerate_message_summaries.py
git commit -m "regenerate_message_summaries: legacy- en coin_result-berichten allebei bijwerken

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q"
```

---

### Task 6: Volledige regressie en push

**Files:** geen wijzigingen — alleen verificatie.

**Interfaces:** geen — dit is de afsluitende controle van alle vorige
taken samen.

- [ ] **Step 1: Draai alle nieuwe testscripts uit dit plan opnieuw achter elkaar**

```bash
source /home/user/Trade/.venv/bin/activate
for f in test_multi_coin_interpret.py test_message_coin_results.py \
         test_multi_coin_pipeline.py test_unclear_messages_dashboard.py \
         test_regenerate_summaries.py; do
  echo "=== $f ==="
  python3 <SCRATCHPAD>/$f || echo "FAILED: $f"
done
```

Verwacht: elk script eindigt met zijn eigen "geslaagd"/"OK"-regel, geen
`FAILED`-regel in de output.

- [ ] **Step 2: Draai eerdere sessies se regressietests die deze bestanden raken**

`app/signal_processor.py`, `app/repo.py` en `app/anthropic_interpret.py`
zijn eerder al geraakt door de factor-verfijningen, candlestick-patronen,
en steun/weerstand-zones-deelprojecten. Bevestig dat deze wijziging die
niet breekt:

```bash
python3 <SCRATCHPAD>/test_factor_refinements.py
python3 <SCRATCHPAD>/test_advanced_factors_integration.py
python3 <SCRATCHPAD>/test_sr_zones_pipeline.py
python3 <SCRATCHPAD>/test_candle_pattern_pipeline.py
```

Bestaat een van deze scripts niet meer in de scratchpad-map (opgeruimd
sinds een eerdere sessie): sla dat script over, geen probleem — het was
toch al wegwerpbaar, geen onderdeel van dit plan om opnieuw aan te maken.

- [ ] **Step 3: Importcontrole van alle gewijzigde modules**

```bash
python3 -c "
import app.anthropic_interpret as anthropic_interpret
import app.repo as repo
import app.signal_processor as signal_processor
import scripts.regenerate_message_summaries as regenerate_message_summaries
print('alle gewijzigde modules importeren zonder fouten')
"
```

- [ ] **Step 4: Controleer de git-status en push**

```bash
git status --short
git log --oneline -8
git push -u origin claude/crypto-day-trading-alerts-5p8w6v
```

Verwacht: `git status --short` toont geen wijzigingen (alles uit Task 1-5
is al gecommit), de laatste 5-6 commits tonen de tasks uit dit plan, en de
push slaagt.
