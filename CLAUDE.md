# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

HesPulse: a crypto day-trading alert system. A user forwards a Discord DM
(text and/or a chart screenshot) from a paid trading community to their own
bot's DM. The system interprets it via the Anthropic API, checks it against
live technical data on Binance, and sends a Telegram alert with a suggested
stop loss, take profit, and position size. It never places trades itself —
every trade is a manual decision. Multiple users share the same signal
stream but each has their own login, portfolio, risk %, and journal. See
`README.md` for the full product description and VPS deployment steps
(systemd units, HTTPS, backups); it is kept up to date and is the source of
truth for setup — don't duplicate it here.

## Commands

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env   # fill in tokens; JWT_SECRET must be long and random

python3 scripts/create_user.py        # creates the DB (if needed) + one account
python3 main.py                       # Discord bot + Telegram /start listener + pipeline
uvicorn web.main:app --reload         # dashboard at http://127.0.0.1:8000
```

There is no pytest suite and no linter config. Verification is done with
throwaway scripts run against a scratch database, e.g.:

```bash
DATABASE_PATH=/tmp/scratch.db python3 -c "from app import db, repo; db.init_db(); ..."
```

`scripts/test_step1_bitcoin.py` exercises the indicator pipeline against
live Binance data in isolation. `scripts/backtest_factors.py --limit 50`
shows the historical pass rate of the optional advanced factors before
turning them on. For UI changes, start `uvicorn` against a scratch DB and
drive it with Playwright — there's no existing template for this in-repo,
build the check from scratch each time.

## Architecture

**Two independent long-running processes, one shared SQLite database.**
`main.py` runs the Discord bot and the Telegram `/start` listener
concurrently (`asyncio.gather`) and feeds the processing pipeline.
`web/main.py` is a separate FastAPI process serving the dashboard. Both
talk to the same `data/trading.db` (WAL mode, see `app/db.py`) — they are
deployed as separate systemd units (`deploy/crypto-bot.service`,
`deploy/crypto-web.service`) and must be restarted independently after a
deploy.

**Pipeline** (`app/signal_processor.py:handle_message`, called from
`app/discord_bot.py` for every DM): dedupe against a recent identical
message → `app/anthropic_interpret.py` (retried up to 3x on transient
failure, then logged as unclear rather than silently dropped) → for
`day_trading` messages, `app/exchange.py` + `app/indicators.py` pull 4h
candles and compute EMA/MACD/RSI/volume (and optionally ADX/ATR/BTC-trend/
1h-confirmation/divergence/liquidity, gated by `ENABLE_ADVANCED_FACTORS`)
→ `app/risk.py` derives stop loss (1.5x ATR), take profit (3x ATR), and a
per-user position size from each user's `risk_percent` × `portfolio_eur` →
fans out to `journal_entries`, one row per user, via `app/repo.py` →
`app/telegram_notify.py` sends each user their own alert with their own
position size. `lange_termijn` (long-term) messages are stored but never
alerted on directly; a later day-trading signal for the same coin is
compared against the most recent long-term direction
(`signal_processor._build_context_note`).

Two periodic jobs run outside this DM-triggered flow, each its own systemd
timer: `app/level_check.py` (every 15 min — has an open position's SL/TP
been hit on the live price, or has price returned near an untaken signal's
level) and `app/heartbeat.py` (daily liveness ping). Both are "fire once
per journal row until reset" — check the existing sent-flag before adding
a new alert path, or you'll spam.

**Multi-tenant model, not multi-tenant data.** `signals`, `messages`, and
`source_levels` are global — every user sees the same signals, computed
once. `journal_entries` is per-user (status, own entry/exit price, notes,
result) and is the only place a user's own decisions live; `users` holds
`portfolio_eur`, `risk_percent`, `telegram_chat_id` per account.
`portfolio_eur` is not static — `repo.close_journal_trade` adds/subtracts
`result_eur` on every real (non-practice) close, so position sizing always
compounds off current equity, not the original deposit. A practice trade
(`is_practice=1`, created from the dashboard, not from a Discord signal)
never touches portfolio or winrate stats — every query that touches those
filters it out explicitly; a new query that forgets to will quietly
pollute a user's real numbers.

**Database access is centralized in `app/repo.py`** — the bot, the
pipeline, and the web dashboard all go through it, never raw SQL
elsewhere. `app/db.py:session()` is a contextmanager that only commits if
the block completes without raising, so a failure partway through a
multi-statement write rolls back cleanly. Schema changes are two-part:
add the column/table to `app/schema.sql` (for fresh databases, via
`CREATE TABLE IF NOT EXISTS`) *and* add an idempotent `ALTER TABLE ... ADD
COLUMN` guarded by a `PRAGMA table_info` check in `db.py:_migrate()` (for
existing ones) — schema.sql alone never reaches a database that already
has the table. Never add an index in schema.sql for a column that a
migration in `_migrate()` might still need to add on an existing DB;
create such indexes in `_migrate()` itself, after the column exists.

**Web layer**: `web/main.py` is one file with all FastAPI routes;
`web/templates/` are Jinja2 templates extending `base.html`, with shared
fragments factored into `web/templates/_macros.html` (import as `macros`,
e.g. `{{ macros.reason_popup(entry) }}`) rather than copy-pasted across
templates — check there before duplicating a block that appears more than
once. `web/static/dashboard.js` and `coin.js` progressively enhance
server-rendered pages (price/PnL polling, AJAX trade actions, the trendline
drawing tool) rather than the pages being a client-rendered SPA. Session
auth is a JWT in a cookie (`app/security.py`), checked via the
`require_login` FastAPI dependency on every protected route.

**Conventions to preserve**: comments explain non-obvious *why* (a past
bug, a deliberate tradeoff, a constraint that isn't visible from the code
itself) — not what the code does; keep that ratio, don't add narration
comments. Confidence/signal UI text distinguishes what was *measured* (the
✓/✗ technical factors) from what is *estimated* (historical win-rate
percentages) — don't blur that line when adding new signal metadata.
Decorative motion (the ambient background, heartbeat pulse, etc. in
`base.html`/`style.css`) is always tied to a real, live value (time since
last message, this week's result, open risk %) and always respects
`prefers-reduced-motion` — never add animation that's purely decorative.
