# Visuele verfijning Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Vervang de 24 losse spacing-waardes en 19 losse lettergroottes in
`web/static/style.css` (en de bijbehorende inline styles in de vier
belangrijkste templates) door een echte token-schaal, en herschrijf
pushmeldingen die nu een dichte, met `·` gescheiden regel zijn naar
regels die op een lockscreen in één oogopslag te lezen zijn.

**Architecture:** Twee onafhankelijke onderdelen. Deel A (Taken 1-5) is een
mechanische, waarde-voor-waarde-vervanging: nieuwe CSS custom properties in
`:root`, daarna elke bestaande margin/padding/gap/font-size-declaratie
(zowel in style.css zelf als in inline `style="..."`-attributen) vervangen
door de dichtstbijzijnde token, volgens een vaste mapping-tabel. Geen
enkele visuele beslissing per regel — de tabel bepaalt het resultaat.
Deel B (Taken 6-7) herschrijft vier push-bodyconstructies (twee in
signal_processor.py, twee in level_check.py — zie de noot in Taak 6 over
een vierde plek die de spec niet noemde maar wel hetzelfde patroon heeft)
van één dichte regel naar meerdere regels, kernfeit eerst.

**Tech Stack:** Vanilla CSS (custom properties), Jinja2-templates, Python
f-strings voor pushmelding-tekst.

**Spec:** `docs/superpowers/specs/2026-09-30-visuele-verfijning-design.md`

## Global Constraints

- Geen pytest-suite in dit project: verifieer Deel A handmatig met
  `uvicorn` tegen een scratch-database + Playwright-screenshots, en Deel B
  met een throwaway script tegen gemockte `push_notify.send_push`.
- Commit-berichten eindigen met:
  ```
  Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
  Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
  ```
- Code-commentaar en commit-berichten in het Nederlands, informele stijl.
- **Niet aanraken**: kleur-tokens (`--bg`, `--panel`, `--border*`, `--text*`,
  `--green*`, `--red*`, `--accent*`), `--shadow-*`, `--radius*`, `--sans`,
  `--mono`, alle `@keyframes`-blokken, en alles wat met
  risico%/portfolio/positiegrootte te maken heeft (expliciet buiten scope,
  zie de spec).
- Alleen de CSS-eigenschappen `margin`, `margin-top/right/bottom/left`,
  `padding`, `padding-top/right/bottom/left`, `gap`, `row-gap`,
  `column-gap` en `font-size` worden getokend. Andere eigenschappen die
  toevallig dezelfde pixelwaarde gebruiken (`border-width`, `width`,
  `height`, `line-height`, `box-shadow`-offsets, `transform`, SVG
  `viewBox`/`width`/`height`-attributen) blijven met rust, ook als de
  waarde in de mapping-tabel hieronder staat.

## Mapping-tabel (bindend voor Taak 1 t/m 5)

Tie-regel: staat een waarde precies tussen twee tokens in, dan rondt hij
naar boven af (het duurdere/ruimere token).

**Lettergrootte:**

| Bestaande waarde(s) | Token |
|---|---|
| 9.5px, 10px, 10.5px | `var(--text-2xs)` |
| 11px, 11.5px | `var(--text-xs)` |
| 12px | `var(--text-sm)` |
| 12.5px, 13px, 13.5px | `var(--text-base)` |
| 14px, 15px | `var(--text-md)` |
| 16px, 17px | `var(--text-lg)` |
| 19px, 20px | `var(--text-xl)` |
| 22px, 24px, 25px | `var(--text-2xl)` |
| 30px | `var(--text-3xl)` |
| 44px | blijft letterlijk `44px` (bespoke, één keer gebruikt) |

**Ruimte (margin/padding/gap):**

| Bestaande waarde(s) | Token |
|---|---|
| 1px | blijft letterlijk `1px` (fijner dan de schaal — verdubbelen naar 2px zou zichtbaar zijn op een haarlijn-gebruik) |
| 2px | `var(--space-1)` |
| 3px, 4px | `var(--space-2)` |
| 5px, 6px | `var(--space-3)` |
| 7px, 8px | `var(--space-4)` |
| 9px, 10px | `var(--space-5)` |
| 12px, 13px | `var(--space-6)` |
| 14px, 16px | `var(--space-7)` |
| 18px, 20px | `var(--space-8)` |
| 22px, 24px | `var(--space-9)` |
| 28px, 32px | `var(--space-10)` |
| 36px, 48px, 52px, 56px, 88px | blijven letterlijk (bespoke, elk maar één of twee keer gebruikt, groter dan de schaal nuttig maakt) |

Een shorthand-declaratie zoals `margin: 8px 12px 0 4px;` wordt
`margin: var(--space-4) var(--space-6) 0 var(--space-2);` — elke waarde in
de lijst apart vervangen volgens de tabel, `0` blijft `0` (geen token
nodig voor nul).

---

## Task 1: Tokens toevoegen + style.css zelf tokenen

**Files:**
- Modify: `web/static/style.css:1-32` (nieuwe tokens) en alle
  `margin`/`padding`/`gap`/`font-size`-declaraties verderop in hetzelfde
  bestand
- Test: handmatige grep-verificatie (geen scratch-database nodig, puur CSS)

**Interfaces:**
- Produces: de CSS custom properties `--text-2xs` t/m `--text-3xl` en
  `--space-1` t/m `--space-10`, gebruikt door Taak 2 t/m 5.

- [ ] **Step 1: Voeg de tokens toe aan `:root`**

Huidige einde van het `:root`-blok (`web/static/style.css:30-32`):

```css
  --sans: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --mono: "IBM Plex Mono", "SFMono-Regular", Consolas, monospace;
}
```

Vervang door:

```css
  --sans: "Inter", -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
  --mono: "IBM Plex Mono", "SFMono-Regular", Consolas, monospace;

  /* Lettergrootte-schaal (visuele verfijning, 2026-09-30): vervangt 19
     losse font-size-waardes verspreid door dit bestand, waaronder halve
     pixels als 11.5px/12.5px/13.5px — organisch gegroeid, geen bewuste
     schaal. Zie docs/superpowers/specs/2026-09-30-visuele-verfijning-design.md
     voor de volledige mapping. */
  --text-2xs: 10px;
  --text-xs: 11px;
  --text-sm: 12px;
  --text-base: 13px;
  --text-md: 14px;
  --text-lg: 16px;
  --text-xl: 20px;
  --text-2xl: 24px;
  --text-3xl: 32px;

  /* Ruimte-schaal: zelfde reden, vervangt 24 losse margin/padding/gap-
     waardes. */
  --space-1: 2px;
  --space-2: 4px;
  --space-3: 6px;
  --space-4: 8px;
  --space-5: 10px;
  --space-6: 12px;
  --space-7: 16px;
  --space-8: 20px;
  --space-9: 24px;
  --space-10: 32px;
}
```

- [ ] **Step 2: Inventariseer de te vervangen regels**

```bash
cd /home/user/Trade
grep -nE '(margin|margin-(top|right|bottom|left)|padding|padding-(top|right|bottom|left)|gap|row-gap|column-gap|font-size):\s*[0-9.]+px' web/static/style.css > /tmp/style_css_spacing_lines.txt
wc -l /tmp/style_css_spacing_lines.txt
```

Dit is je volledige, exacte lijst — elke regel hierin moet je nalopen.
Regels met een waarde uit de "blijft letterlijk"-rijen van de mapping-tabel
(1px, 36px, 44px, 48px, 52px, 56px, 88px) sla je over; alle andere krijgen
het bijbehorende token.

- [ ] **Step 3: Vervang elke waarde volgens de mapping-tabel**

Ga de lijst uit Step 2 regel voor regel langs. Voor elke declaratie:
vervang elke losse pixelwaarde in die declaratie (ook bij een shorthand
met meerdere waardes, zie de toelichting onder de mapping-tabel hierboven)
door het token uit de tabel. Voorbeeld van hoe dit eruitziet (niet
uitputtend, de exacte regels in style.css bepaal je zelf uit Step 2's
lijst):

```css
/* vóór */
padding: 12.5px 16px;
gap: 9px;
font-size: 11.5px;

/* na */
padding: var(--text-base) var(--space-7);
gap: var(--space-5);
font-size: var(--text-xs);
```

(Let op: in dit voorbeeld staat `12.5px` in een `padding`-declaratie, dus
die gebruikt de RUIMTE-tabel niet de lettergrootte-tabel — `12.5px` heeft
in de spacing-tabel geen eigen rij, rond af naar de dichtstbijzijnde:
tussen 12 en 13 in de tabel staat 13px al op `--space-6`, dus 12.5px hoort
daar ook bij. Gebruik dezelfde afrondlogica voor elke spacing-waarde die
niet letterlijk in de tabel staat maar er wel tussenin valt.)

- [ ] **Step 4: Verifieer dat er niets is overgeslagen**

```bash
cd /home/user/Trade
grep -nE '(margin|margin-(top|right|bottom|left)|padding|padding-(top|right|bottom|left)|gap|row-gap|column-gap|font-size):\s*(2|3|4|5|6|7|8|9|10|12|13|14|16|18|20|22|24|28|32)px' web/static/style.css
```

Expected: lege output (geen enkele match meer) — elke waarde uit de
mapping-tabel is nu een token. Waardes die bewust letterlijk bleven (1px,
36px, 44px, 48px, 52px, 56px, 88px) staan niet in dit grep-patroon, dus
die geven hier terecht geen match.

- [ ] **Step 5: Draai de app lokaal en bevestig dat er niets kapot is**

```bash
cd /home/user/Trade && python3 -c "
import re
css = open('web/static/style.css').read()
# Simpele syntax-sanity-check: gelijk aantal { en }
assert css.count('{') == css.count('}'), 'ongebalanceerde accolades in style.css'
print('CSS balans OK')
"
```

- [ ] **Step 6: Commit**

```bash
cd /home/user/Trade
git add web/static/style.css
git commit -m "$(cat <<'EOF'
Spacing- en lettergrootte-schaal in style.css

Nieuwe --text-*/--space-*-tokens in :root, en elke bestaande margin/
padding/gap/font-size-waarde in dit bestand vervangen door de
dichtstbijzijnde token (zie de mapping-tabel in het plan). Vervangt 24
losse spacing- en 19 losse font-size-waardes, waaronder halve pixels als
11.5px/12.5px/13.5px, door een bewuste schaal. Geen wijziging aan kleuren,
radius, schaduwen of animaties.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 2: Tokens toepassen op `web/templates/base.html`

**Files:**
- Modify: `web/templates/base.html` (inline `style="..."`-attributen)
- Test: handmatige grep-verificatie

**Interfaces:**
- Consumes: `--text-*`/`--space-*`-tokens (Taak 1).

- [ ] **Step 1: Inventariseer**

```bash
cd /home/user/Trade
grep -noE 'style="[^"]*(margin|padding|gap|font-size)[^"]*"' web/templates/base.html
```

- [ ] **Step 2: Vervang volgens dezelfde mapping-tabel als Taak 1**

Zelfde methode: elke gevonden inline `margin`/`padding`/`gap`/`font-size`
in een `style="..."`-attribuut krijgt het bijbehorende token uit de
mapping-tabel bovenaan dit plan. Andere eigenschappen in hetzelfde
`style="..."`-attribuut (bv. `display: flex;` of `color: ...;`) blijven
ongewijzigd.

- [ ] **Step 3: Verifieer**

```bash
cd /home/user/Trade
grep -nE 'style="[^"]*(margin|padding|gap|font-size):\s*(2|3|4|5|6|7|8|9|10|12|13|14|16|18|20|22|24|28|32)px' web/templates/base.html
```

Expected: lege output.

- [ ] **Step 4: Commit**

```bash
cd /home/user/Trade
git add web/templates/base.html
git commit -m "$(cat <<'EOF'
Spacing/lettergrootte-tokens toepassen op base.html

Zelfde mapping-tabel als de style.css-tokenisatie: elke inline margin/
padding/gap/font-size in base.html (topbar, shell) krijgt het
dichtstbijzijnde token.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 3: Tokens toepassen op `web/templates/dashboard.html`

**Files:**
- Modify: `web/templates/dashboard.html` (inline `style="..."`-attributen)
- Test: handmatige grep-verificatie

**Interfaces:**
- Consumes: `--text-*`/`--space-*`-tokens (Taak 1).

- [ ] **Step 1: Inventariseer**

```bash
cd /home/user/Trade
grep -noE 'style="[^"]*(margin|padding|gap|font-size)[^"]*"' web/templates/dashboard.html
```

- [ ] **Step 2: Vervang volgens de mapping-tabel** (zelfde methode als Taak 2, Step 2)

- [ ] **Step 3: Verifieer**

```bash
cd /home/user/Trade
grep -nE 'style="[^"]*(margin|padding|gap|font-size):\s*(2|3|4|5|6|7|8|9|10|12|13|14|16|18|20|22|24|28|32)px' web/templates/dashboard.html
```

Expected: lege output.

- [ ] **Step 4: Commit**

```bash
cd /home/user/Trade
git add web/templates/dashboard.html
git commit -m "$(cat <<'EOF'
Spacing/lettergrootte-tokens toepassen op dashboard.html

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 4: Tokens toepassen op `web/templates/coin.html`

**Files:**
- Modify: `web/templates/coin.html` (inline `style="..."`-attributen)
- Test: handmatige grep-verificatie

**Interfaces:**
- Consumes: `--text-*`/`--space-*`-tokens (Taak 1).

- [ ] **Step 1: Inventariseer**

```bash
cd /home/user/Trade
grep -noE 'style="[^"]*(margin|padding|gap|font-size)[^"]*"' web/templates/coin.html
```

- [ ] **Step 2: Vervang volgens de mapping-tabel** (zelfde methode als Taak 2, Step 2)

- [ ] **Step 3: Verifieer**

```bash
cd /home/user/Trade
grep -nE 'style="[^"]*(margin|padding|gap|font-size):\s*(2|3|4|5|6|7|8|9|10|12|13|14|16|18|20|22|24|28|32)px' web/templates/coin.html
```

Expected: lege output.

- [ ] **Step 4: Commit**

```bash
cd /home/user/Trade
git add web/templates/coin.html
git commit -m "$(cat <<'EOF'
Spacing/lettergrootte-tokens toepassen op coin.html

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 5: Tokens toepassen op `web/templates/account.html`

**Files:**
- Modify: `web/templates/account.html` (inline `style="..."`-attributen)
- Test: handmatige grep-verificatie

**Interfaces:**
- Consumes: `--text-*`/`--space-*`-tokens (Taak 1).

Deze template heeft de meeste inline styles van de vier (onboarding-
checklist, winrate-ring, portfolio-kaart, meldingen-tabel) — neem de tijd
voor Step 1's inventarisatie, mis niets.

- [ ] **Step 1: Inventariseer**

```bash
cd /home/user/Trade
grep -noE 'style="[^"]*(margin|padding|gap|font-size)[^"]*"' web/templates/account.html
```

- [ ] **Step 2: Vervang volgens de mapping-tabel** (zelfde methode als Taak 2, Step 2)

**Niet aanraken**: de verborgen `portfolio_eur`/`risk_percent`-velden en
hun omliggende code-comment (rond regel 210-215, "Taak 11: het formulier
om portfolio_eur/risk_percent zelf in te stellen is hier verwijderd...")
— dat is functionele code, geen styling, en hoort bij het aparte, latere
brainstorm-onderwerp over positiegrootte. Alleen `style="..."`-attributen
aanpassen, geen andere regels.

- [ ] **Step 3: Verifieer**

```bash
cd /home/user/Trade
grep -nE 'style="[^"]*(margin|padding|gap|font-size):\s*(2|3|4|5|6|7|8|9|10|12|13|14|16|18|20|22|24|28|32)px' web/templates/account.html
```

Expected: lege output.

- [ ] **Step 4: Commit**

```bash
cd /home/user/Trade
git add web/templates/account.html
git commit -m "$(cat <<'EOF'
Spacing/lettergrootte-tokens toepassen op account.html

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 6: Pushmeldingen met regeleinden — `app/signal_processor.py`

**Files:**
- Modify: `app/signal_processor.py` (twee plekken: `process_day_trading_signal`
  en `_notify_signal_update`)
- Test: scratchpad-script (throwaway, gemockte `push_notify.send_push`)

**Interfaces:**
- Produces: geen nieuwe publieke namen, alleen gewijzigde body-tekst.

**Belangrijk, ontdekt tijdens het schrijven van dit plan (niet in de spec
genoemd)**: naast de plek die de spec citeert
(`process_day_trading_signal`) bestaat er een TWEEDE, bijna identieke
dichte regel in `_notify_signal_update` — de melding die de marktscan elke
cyclus stuurt als een al open signaal verandert. De code-comment daar zegt
letterlijk "Zelfde entry_zone_note-logica als in process_day_trading_signal
hierboven". Dezelfde reden om `process_day_trading_signal` te herschrijven
(dichte `·`-regel, moeilijk te scannen) geldt hier evengoed, dus deze taak
pakt beide plekken.

- [ ] **Step 1: `process_day_trading_signal` — vind de exacte huidige code**

Zoek in `app/signal_processor.py` (binnen `process_day_trading_signal`,
rond de `title = f"{push_notify.coin_symbol(interp.coin)}...`-regel):

```python
            title = f"{push_notify.coin_symbol(interp.coin)} {interp.coin} {interp.direction}, {signal_data['confidence']}"
            entry_zone_note = (
                f" · Mogelijk betere entry: {suggested_entry_low:.4f}–{suggested_entry_high:.4f}"
                if suggested_entry_low is not None else ""
            )
            sniper_line = (
                f"\n🎯 Sniper: {signal_data['sniper_entry_price']:.4f} — {signal_data['sniper_reason']}"
                if signal_data.get("sniper_entry_price") is not None else ""
            )
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

Vervang door:

```python
            title = f"{push_notify.coin_symbol(interp.coin)} {interp.coin} {interp.direction}, {signal_data['confidence']}"
            body = (
                f"Entry {signal_data['price']:.4f}\n"
                f"Stop {effective_stop_loss:.4f} · Take profit {effective_take_profit:.4f}"
            )
            if suggested_entry_low is not None:
                body += f"\nMogelijk betere entry: {suggested_entry_low:.4f}–{suggested_entry_high:.4f}"
            if signal_data.get("sniper_entry_price") is not None:
                body += f"\n🎯 Sniper: {signal_data['sniper_entry_price']:.4f} — {signal_data['sniper_reason']}"
            if signal_data.get("repeated_loss_note"):
                body += f"\n{signal_data['repeated_loss_note']}"
            if signal_data.get("context_note"):
                body += f"\n{signal_data['context_note']}"
            if eval_blocked_note:
                body += f"\n{eval_blocked_note}"
```

(De aparte `entry_zone_note`/`sniper_line`-variabelen vervallen: ze worden
nu net als `repeated_loss_note`/`context_note`/`eval_blocked_note` direct
met `body +=` toegevoegd, één consistente stijl voor alle optionele
regels. Entry staat nu alleen op de eerste regel, stop/take profit samen
op de tweede — zie de spec, Deel 2.)

- [ ] **Step 2: `_notify_signal_update` — vind de exacte huidige code**

Zoek in `app/signal_processor.py` (binnen `_notify_signal_update`, rond de
`title = f"{push_notify.coin_symbol(coin)}...update"`-regel):

```python
            title = f"{push_notify.coin_symbol(coin)} {coin} {message_data['direction']}, update"
            # Zelfde entry_zone_note-logica als in process_day_trading_signal
            # hierboven, anders mist deze regel juist in de pushmelding die de
            # marktscan elke cyclus stuurt voor een al open signaal, terwijl
            # de signaalkaart hem wel altijd toont.
            suggested_low = message_data.get("suggested_entry_low")
            suggested_high = message_data.get("suggested_entry_high")
            entry_zone_note = (
                f" · Mogelijk betere entry: {suggested_low:.4f}–{suggested_high:.4f}"
                if suggested_low is not None else ""
            )
            sniper_line = (
                f"\n🎯 Sniper: {message_data['sniper_entry_price']:.4f} — {message_data['sniper_reason']}"
                if message_data.get("sniper_entry_price") is not None else ""
            )
            body = (
                f"Nieuwe prijs {message_data['price']:.4f} · Stop {message_data['stop_loss']:.4f} · "
                f"Take profit {message_data['take_profit']:.4f}{entry_zone_note}{sniper_line}"
                if confirmed else
                f"Nieuwe prijs {message_data['price']:.4f} · nog geen sterke kans"
            )
            if message_data.get("repeated_loss_note"):
                body += f"\n{message_data['repeated_loss_note']}"
```

Vervang door:

```python
            title = f"{push_notify.coin_symbol(coin)} {coin} {message_data['direction']}, update"
            # Zelfde regel-per-regel-opbouw als process_day_trading_signal
            # hierboven, zelfde reden (visuele verfijning, 2026-09-30): een
            # dichte, met · gescheiden regel is lastig te scannen op een
            # lockscreen.
            suggested_low = message_data.get("suggested_entry_low")
            suggested_high = message_data.get("suggested_entry_high")
            if confirmed:
                body = (
                    f"Nieuwe prijs {message_data['price']:.4f}\n"
                    f"Stop {message_data['stop_loss']:.4f} · Take profit {message_data['take_profit']:.4f}"
                )
                if suggested_low is not None:
                    body += f"\nMogelijk betere entry: {suggested_low:.4f}–{suggested_high:.4f}"
                if message_data.get("sniper_entry_price") is not None:
                    body += f"\n🎯 Sniper: {message_data['sniper_entry_price']:.4f} — {message_data['sniper_reason']}"
            else:
                body = f"Nieuwe prijs {message_data['price']:.4f} · nog geen sterke kans"
            if message_data.get("repeated_loss_note"):
                body += f"\n{message_data['repeated_loss_note']}"
```

- [ ] **Step 3: Importcheck**

```bash
cd /home/user/Trade && python3 -c "import app.signal_processor; print('import OK')"
```

Expected: `import OK`.

- [ ] **Step 4: Schrijf en draai het testscript**

Maak `<jouw scratchpad>/test_push_linebreaks_signal_processor.py`:

```python
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/home/user/Trade")
os.environ["DATABASE_PATH"] = "/tmp/scratch_push_linebreaks.db"
db_path = Path(os.environ["DATABASE_PATH"])
if db_path.exists():
    db_path.unlink()

from app import db, repo, signal_processor  # noqa: E402
from app.anthropic_interpret import Interpretation  # noqa: E402

db.init_db()
user_id = repo.create_user("pushtest", "hash", 1000.0, 1.0)

captured_bodies = []


async def fake_send_push(user_id, title, body, url, silent=False):
    captured_bodies.append(body)


def make_interp(coin="BTC", direction="long"):
    return Interpretation(
        coin=coin, direction=direction, category="day_trading", unclear=False,
        reason="✓ Trend | ✓ Momentum | ✓ RSI | ✓ Volume", source_levels=[],
    )


async def run():
    with patch("app.signal_processor.push_notify.send_push", side_effect=fake_send_push), \
         patch("app.signal_processor.exchange.fetch_ohlcv") as mock_ohlcv, \
         patch("app.signal_processor.explain.explain_signal", return_value="uitleg"), \
         patch("app.signal_processor._repeated_failing_factor", return_value=None):
        import pandas as pd
        # Genoeg candles voor indicators.compute_indicators om niet te crashen.
        rows = [{"timestamp": pd.Timestamp.now(tz="UTC"), "open": 100, "high": 105,
                 "low": 95, "close": 100 + i, "volume": 1000} for i in range(60)]
        mock_ohlcv.return_value = pd.DataFrame(rows)
        await signal_processor.process_day_trading_signal(None, make_interp())

    assert captured_bodies, "er had een pushmelding verstuurd moeten worden"
    body = captured_bodies[0]
    assert body.startswith("Entry "), f"body moet met 'Entry ' beginnen, kreeg: {body!r}"
    lines = body.split("\n")
    assert len(lines) >= 2, f"body moet minstens 2 regels hebben, kreeg: {lines}"
    assert lines[0].startswith("Entry ") and "Stop" not in lines[0], (
        f"regel 1 hoort alleen Entry te zijn, kreeg: {lines[0]!r}"
    )
    assert "Stop" in lines[1] and "Take profit" in lines[1], (
        f"regel 2 hoort Stop en Take profit te bevatten, kreeg: {lines[1]!r}"
    )
    print(f"OK: body = {body!r}")


asyncio.run(run())
print("Test geslaagd.")
```

(Als `process_day_trading_signal`'s exacte signatuur of interne
afhankelijkheden anders blijken dan hierboven aangenomen — bijvoorbeeld
een ander aantal candles nodig, of een andere mock die moet — pas het
testscript aan op basis van de foutmelding, niet de productiecode. Het
doel van deze test is puur bevestigen dat de body nu regeleinden bevat op
de juiste plek, niet de rest van de functie herverifiëren.)

- [ ] **Step 5: Draai het testscript**

```bash
cd /home/user/Trade && rm -f /tmp/scratch_push_linebreaks.db && python3 <jouw scratchpad>/test_push_linebreaks_signal_processor.py
```

Expected: eindigt met `Test geslaagd.`, geen `AssertionError` of Traceback.

- [ ] **Step 6: Opruimen en committen**

```bash
rm -f /tmp/scratch_push_linebreaks.db
cd /home/user/Trade
git add app/signal_processor.py
git commit -m "$(cat <<'EOF'
Pushmeldingen dagtradingsignaal: regeleinden i.p.v. dichte ·-regel

Entry op zijn eigen regel, Stop/Take profit samen op de regel erna,
entry-zone/sniper/repeated-loss/context/eval-blocked elk op hun eigen
regel — allemaal met dezelfde body +=-stijl, geen losse
entry_zone_note/sniper_line-variabelen meer. Toegepast op zowel
process_day_trading_signal als _notify_signal_update (de marktscan-
update-melding voor een al open signaal) — die tweede plek stond niet
letterlijk in de spec, maar had exact dezelfde dichte opbouw (de
bestaande code-comment verwees er zelf al naar).

Getest met een scratch-database en gemockte push_notify.send_push:
bevestigt dat Entry op regel 1 staat, Stop/Take profit op regel 2.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 7: Pushmeldingen met regeleinden — `app/level_check.py`

**Files:**
- Modify: `app/level_check.py` (drie plekken: het stop/take-geraakt-pad,
  het sniper-trigger-pad, het generieke pending-niveau-pad)
- Test: scratchpad-script (throwaway, gemockte `push_notify.send_push`)

**Interfaces:**
- Produces: geen nieuwe publieke namen, alleen gewijzigde body-tekst.

- [ ] **Step 1: Stop/take-geraakt — vind de exacte huidige code**

Zoek in `app/level_check.py` (binnen `check_open_trades`):

```python
        hit_emoji = "🎯" if hit == "take profit" else "🛑"
        title = f"{hit_emoji} {push_notify.coin_symbol(coin)} {coin} {entry['direction'].upper()}"
        body = f"{hit.capitalize()} geraakt · Entry {entry['entry_price']:.4f} · Op {hit_price:.4f}"
```

Vervang door:

```python
        hit_emoji = "🎯" if hit == "take profit" else "🛑"
        title = f"{hit_emoji} {push_notify.coin_symbol(coin)} {coin} {entry['direction'].upper()}"
        body = f"{hit.capitalize()} geraakt\nEntry {entry['entry_price']:.4f} · Op {hit_price:.4f}"
```

- [ ] **Step 2: Sniper-trigger — vind de exacte huidige code**

Zoek in `app/level_check.py` (binnen `check_pending_signals`):

```python
        if sniper_hit is not None:
            sniper_price, sniper_reason = sniper_hit
            title = f"🎯 {push_notify.coin_symbol(coin)} {coin} {entry['direction'].upper()} — sniper-trigger geraakt"
            body = f"{sniper_price:.4f} · {sniper_reason} · Nu {current_price:.4f}"
```

Vervang door:

```python
        if sniper_hit is not None:
            sniper_price, sniper_reason = sniper_hit
            title = f"🎯 {push_notify.coin_symbol(coin)} {coin} {entry['direction'].upper()} — sniper-trigger geraakt"
            body = f"{sniper_price:.4f} · {sniper_reason}\nNu {current_price:.4f}"
```

- [ ] **Step 3: Generiek pending-niveau — vind de exacte huidige code**

Zoek in `app/level_check.py` (direct na het `else:`-blok uit Step 2, nog
steeds binnen `check_pending_signals`):

```python
            title = f"🔔 {push_notify.coin_symbol(coin)} {coin} {entry['direction'].upper()}"
            heading = "Terug in de betere-entry-zone" if in_entry_zone else "Terug bij een interessant niveau"
            body = f"{heading} ({entry['confidence']}) · {level_line} · Nu {current_price:.4f}"
```

Vervang door:

```python
            title = f"🔔 {push_notify.coin_symbol(coin)} {coin} {entry['direction'].upper()}"
            heading = "Terug in de betere-entry-zone" if in_entry_zone else "Terug bij een interessant niveau"
            body = f"{heading} ({entry['confidence']})\n{level_line} · Nu {current_price:.4f}"
```

- [ ] **Step 4: Importcheck**

```bash
cd /home/user/Trade && python3 -c "import app.level_check; print('import OK')"
```

Expected: `import OK`.

- [ ] **Step 5: Schrijf en draai het testscript**

Maak `<jouw scratchpad>/test_push_linebreaks_level_check.py`:

```python
import asyncio
import os
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, "/home/user/Trade")
os.environ["DATABASE_PATH"] = "/tmp/scratch_push_linebreaks_lc.db"
db_path = Path(os.environ["DATABASE_PATH"])
if db_path.exists():
    db_path.unlink()

import pandas as pd  # noqa: E402

from app import db, level_check, repo  # noqa: E402

db.init_db()
user_id = repo.create_user("pushtestlc", "hash", 1000.0, 1.0)

captured = []


async def fake_send_push(user_id, title, body, url, silent=False):
    captured.append(body)


def make_candle(o, h, l, c):
    return {"timestamp": pd.Timestamp.now(tz="UTC"), "open": o, "high": h, "low": l, "close": c, "volume": 100.0}


async def run():
    # Scenario 1: check_open_trades, stop loss geraakt.
    signal_id = repo.insert_signal({
        "coin": "BTC", "direction": "long", "category": "day_trading", "trade_type": "day_trading",
        "price": 50000.0, "stop_loss": 49000.0, "take_profit": 52000.0,
        "technical_confirmed": 1, "confidence": "hoog", "hard_gates_ok": 1, "reason": "test",
    })
    entry_id = repo.create_journal_entry(signal_id, user_id, 10.0)
    repo.update_journal_status(entry_id, user_id, "genomen", entry_price=50000.0)
    candles = pd.DataFrame([make_candle(49500, 49600, 48500, 48900) for _ in range(6)])
    with patch("app.level_check.exchange.fetch_ohlcv", return_value=candles), \
         patch("app.level_check.push_notify.send_push", side_effect=fake_send_push):
        await level_check.check_open_trades()
    assert captured, "er had een pushmelding verstuurd moeten worden"
    body = captured[-1]
    lines = body.split("\n")
    assert len(lines) == 2, f"body moet 2 regels hebben, kreeg: {lines}"
    assert lines[0] == "Stop loss geraakt", f"regel 1 klopt niet: {lines[0]!r}"
    assert lines[1].startswith("Entry "), f"regel 2 klopt niet: {lines[1]!r}"
    print(f"Scenario 1 OK: {body!r}")


asyncio.run(run())
print("Test geslaagd.")
```

(Dit dekt scenario 1 — check_open_trades' stop/take-pad — volledig
end-to-end. Voor de sniper-trigger- en generieke-pending-niveau-varianten
(Step 2 en Step 3 hierboven) is een volledige end-to-end scratch-DB-test
via `check_pending_signals()` aanzienlijk omslachtiger op te zetten dan
via `check_open_trades()` — als je die kunt opzetten naar het patroon van
eerdere sessies deze branch (zoek `check_pending_signals` in
`docs/superpowers/plans/` voor een werkend voorbeeld), doe dat; zo niet,
is een gerichte, geïsoleerde string-test voldoende bewijs dat de
f-string-syntax zelf klopt:

```python
sniper_price, sniper_reason, current_price = 50123.4567, "sweep + afwijzing", 50200.0
body = f"{sniper_price:.4f} · {sniper_reason}\nNu {current_price:.4f}"
lines = body.split("\n")
assert len(lines) == 2
assert lines[0] == "50123.4567 · sweep + afwijzing"
assert lines[1] == "Nu 50200.0000"
print("Sniper-body-syntax OK")

heading, confidence, level_line, current_price = "Terug bij een interessant niveau", "hoog", "Signaalniveau: 50000.0000", 50100.0
body = f"{heading} ({confidence})\n{level_line} · Nu {current_price:.4f}"
lines = body.split("\n")
assert len(lines) == 2
assert lines[0] == "Terug bij een interessant niveau (hoog)"
assert lines[1] == "Signaalniveau: 50000.0000 · Nu 50100.0000"
print("Pending-niveau-body-syntax OK")
```

voeg dit toe aan hetzelfde testscript, ná scenario 1.)

- [ ] **Step 6: Draai het testscript**

```bash
cd /home/user/Trade && rm -f /tmp/scratch_push_linebreaks_lc.db && python3 <jouw scratchpad>/test_push_linebreaks_level_check.py
```

Expected: eindigt met `Test geslaagd.`, geen `AssertionError` of Traceback.

- [ ] **Step 7: Opruimen en committen**

```bash
rm -f /tmp/scratch_push_linebreaks_lc.db
cd /home/user/Trade
git add app/level_check.py
git commit -m "$(cat <<'EOF'
Pushmeldingen level-check: regeleinden i.p.v. dichte ·-regel

Drie plekken: stop/take-geraakt (kernfeit op regel 1, entry+prijs op
regel 2), sniper-trigger (prijs+reden op regel 1, huidige prijs op regel
2), generiek pending-niveau (kop+vertrouwen op regel 1, niveau+huidige
prijs op regel 2). Titel-opbouw overal ongewijzigd. SMC-melding in
market_scanner.py blijft ongewijzigd (is al een lopende zin, geen dichte
cijferregel, zie de spec).

Getest met een scratch-database: check_open_trades' stop/take-pad
end-to-end, de andere twee varianten met een gerichte string-test op de
f-string-opbouw zelf.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01XPKnbxK35Sy5FydjYnrM9Q
EOF
)"
```

---

## Task 8: Visuele verificatie, volledige regressie en push

**Files:**
- Geen nieuwe wijzigingen verwacht — deze taak verifieert Taak 1 t/m 7
  samen en rondt af.

**Interfaces:**
- Consumes: alles uit Taak 1 t/m 7.
- Produces: niets nieuws; eindstaat is een gepushte branch en een
  draaiende VPS.

- [ ] **Step 1: Draai de app lokaal tegen een scratch-database**

```bash
cd /home/user/Trade
DATABASE_PATH=/tmp/scratch_visual_check.db python3 -c "from app import db; db.init_db()"
DATABASE_PATH=/tmp/scratch_visual_check.db python3 scripts/create_user.py
```

(Volg de prompts van `create_user.py` om een testaccount aan te maken —
zoek het exacte gebruik op met `python3 scripts/create_user.py --help`
als de prompts niet vanzelf duidelijk zijn.)

```bash
cd /home/user/Trade && DATABASE_PATH=/tmp/scratch_visual_check.db uvicorn web.main:app --port 8010 &
```

- [ ] **Step 2: Playwright-screenshots van de vier gewijzigde pagina's**

Log in met het testaccount, maak een screenshot van `/` (dashboard),
`/coins/BTC` (of een andere coin uit `config.FIXED_COINS`), en `/account`.
Controleer visueel: geen overlappende tekst, geen te grote of te kleine
sprongen in witruimte die er eerst niet waren, geen gebroken layout. Dit
is een verfijningsslag, dus de pagina's moeten er herkenbaar hetzelfde
uitzien als vóór dit plan — alleen strakker.

- [ ] **Step 3: Stop de lokale server en ruim op**

```bash
kill %1 2>/dev/null
rm -f /tmp/scratch_visual_check.db
```

- [ ] **Step 4: Draai de testscripts van Taak 6 en 7 nog een keer achter elkaar**

Als de scratchpad-scripts nog bestaan, draai ze allebei opnieuw (elk met
zijn eigen scratch-database). Als een scratchpad al opgeruimd is: herbouw
het script kort met dezelfde inhoud als in de betreffende taak hierboven.
Expected: beide eindigen zonder `AssertionError` of Traceback.

- [ ] **Step 5: Bekijk de volledige diff**

```bash
cd /home/user/Trade && git diff 79fd2c1 -- web/ app/signal_processor.py app/level_check.py --stat
```

(`79fd2c1` is de laatste commit vóór dit plan begon — de spec-commit.)

Controleer: alleen `web/static/style.css`, de vier templates, en
`app/signal_processor.py`/`app/level_check.py` zitten in de diff. Geen
wijziging aan kleur-tokens, `@keyframes`, `app/market_scanner.py`, of
alles wat met risico%/portfolio/positiegrootte te maken heeft.

- [ ] **Step 6: Push**

```bash
cd /home/user/Trade && git push -u origin claude/crypto-day-trading-alerts-5p8w6v
```

- [ ] **Step 7: Geef VPS-deploy-instructies**

Twee losse commando's (niet combineren):

```bash
cd /opt/crypto-alerts && sudo -u crypto git pull origin claude/crypto-day-trading-alerts-5p8w6v
```

Daarna:

```bash
sudo systemctl restart crypto-web.service
```

(Alleen `crypto-web.service` hoeft herstart — deze wijziging raakt de
webdashboard-styling en de pushmelding-opbouw, die laatste draait binnen
`crypto-bot.service`'s pijplijn, dus die moet ook herstarten:)

```bash
sudo systemctl restart crypto-bot.service
```

- [ ] **Step 8: Bevestig bij de gebruiker**

Meld kort: welke commits gepusht zijn, dat de Playwright-screenshots er
goed uitzagen, dat beide testscripts nog slagen, en dat de VPS herstart
moet worden met de commando's hierboven om het live te krijgen.

## Self-Review (uitgevoerd tijdens het schrijven van dit plan)

1. **Spec-dekking:**
   - Deel 1 (spacing/type-schaal, toegepast op style.css + 4 templates) →
     Taak 1 t/m 5. ✓
   - Deel 2 (pushmeldingen met regeleinden) → Taak 6 en 7. ✓ (inclusief de
     tijdens het schrijven ontdekte vierde plek, `_notify_signal_update`,
     die de spec niet noemde maar wel exact hetzelfde patroon had — zie de
     noot bovenaan Taak 6.)
   - "Niet in scope" (kleuren, radius, animaties, positiegrootte) →
     expliciet genoemd in Global Constraints en in Taak 5's
     niet-aanraken-noot, bevestigd via de diff-check in Taak 8. ✓
2. **Placeholder-scan:** geen kale "TBD"/"clean up spacing"-instructies —
   Taak 1 t/m 5 geven een volledige, mechanische mapping-tabel + een exact
   grep-commando om te verifiëren dat niets is overgeslagen, in plaats van
   honderden individuele regel-diffs uit te schrijven (dat zou het plan
   onwerkbaar groot maken voor een pure waarde-vervanging). Taak 6 en 7
   geven wel de volledige letterlijke code, want dat zijn maar 4 gerichte
   plekken.
3. **Typeconsistentie:** de tokens (`--text-*`/`--space-*`) worden in Taak 1
   gedefinieerd en in Taak 2 t/m 5 ongewijzigd hergebruikt via dezelfde
   mapping-tabel bovenaan het document — geen los gedefinieerde variant
   per taak.
