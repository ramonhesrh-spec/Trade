"""Alle databasetoegang op één plek: berichten, bron niveaus, coins en
signalen. Wordt gebruikt door de Discord bot, de verwerkingspijplijn en het
webdashboard."""
import json
from typing import Optional

from app import db


# ---------------------------------------------------------------------------
# Berichten
# ---------------------------------------------------------------------------

def insert_message(raw_text: str, image_paths: list[str]) -> int:
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO messages (received_at, raw_text, has_image, image_paths)
               VALUES (?, ?, ?, ?)""",
            (db.now_iso(), raw_text, int(bool(image_paths)), json.dumps(image_paths)),
        )
        return cur.lastrowid


def mark_message_processed(
    message_id: int, coin: Optional[str], direction: Optional[str],
    category: Optional[str], unclear: bool,
) -> None:
    with db.session() as conn:
        conn.execute(
            """UPDATE messages
               SET coin = ?, direction = ?, category = ?, unclear = ?, processed_at = ?
               WHERE id = ?""",
            (coin, direction, category, int(unclear), db.now_iso(), message_id),
        )


def list_messages(limit: int = 200) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM messages ORDER BY id DESC LIMIT ?", (limit,)
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Bron niveaus (uit Discord afbeeldingen)
# ---------------------------------------------------------------------------

def insert_source_level(
    message_id: int, coin: str, price_level: float,
    pattern_name: Optional[str], source_label: str = "analyse Discord",
) -> int:
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO source_levels
               (message_id, coin, price_level, pattern_name, source_label, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (message_id, coin.upper(), price_level, pattern_name, source_label, db.now_iso()),
        )
        return cur.lastrowid


def list_source_levels(coin: str) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM source_levels WHERE coin = ? ORDER BY created_at DESC",
            (coin.upper(),),
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Dynamische coinlijst
# ---------------------------------------------------------------------------

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


def list_coins() -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM coins WHERE active = 1 ORDER BY symbol"
        ).fetchall()
        return [dict(r) for r in rows]


# ---------------------------------------------------------------------------
# Gebruikers
# ---------------------------------------------------------------------------

def create_user(
    username: str, password_hash: str, portfolio_eur: float,
    risk_percent: float, telegram_chat_id: Optional[str],
) -> int:
    """Maakt een gebruiker aan, of werkt een bestaande bij (zelfde
    gebruikersnaam). Gebruikt door scripts/create_user.py, geen open
    registratie via het dashboard zelf."""
    with db.session() as conn:
        conn.execute(
            """INSERT INTO users
               (username, password_hash, portfolio_eur, risk_percent, telegram_chat_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(username) DO UPDATE SET
                 password_hash = excluded.password_hash,
                 portfolio_eur = excluded.portfolio_eur,
                 risk_percent = excluded.risk_percent,
                 telegram_chat_id = excluded.telegram_chat_id""",
            (username, password_hash, portfolio_eur, risk_percent, telegram_chat_id, db.now_iso()),
        )
        row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        return row["id"]


def get_user(user_id: int) -> Optional[dict]:
    with db.session() as conn:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return dict(row) if row else None


def get_user_by_username(username: str) -> Optional[dict]:
    with db.session() as conn:
        row = conn.execute("SELECT * FROM users WHERE username = ?", (username,)).fetchone()
        return dict(row) if row else None


def list_users() -> list[dict]:
    with db.session() as conn:
        rows = conn.execute("SELECT * FROM users ORDER BY id").fetchall()
        return [dict(r) for r in rows]


def update_user_settings(
    user_id: int, portfolio_eur: float, risk_percent: float,
    telegram_chat_id: Optional[str],
) -> None:
    with db.session() as conn:
        conn.execute(
            """UPDATE users SET portfolio_eur = ?, risk_percent = ?, telegram_chat_id = ?
               WHERE id = ?""",
            (portfolio_eur, risk_percent, telegram_chat_id, user_id),
        )


# ---------------------------------------------------------------------------
# Signalen: gedeelde technische toetsing, hetzelfde voor iedereen
# ---------------------------------------------------------------------------

def insert_signal(data: dict) -> int:
    fields = [
        "message_id", "coin", "direction", "category", "price", "rsi", "macd",
        "macd_signal", "volume_ratio", "ema9", "ema21", "atr",
        "technical_confirmed", "confidence", "reason", "stop_loss", "take_profit",
    ]
    values = [data.get(f) for f in fields]
    placeholders = ", ".join("?" for _ in fields)
    with db.session() as conn:
        cur = conn.execute(
            f"""INSERT INTO signals ({", ".join(fields)}, created_at)
                VALUES ({placeholders}, ?)""",
            (*values, db.now_iso()),
        )
        return cur.lastrowid


def get_signal(signal_id: int) -> Optional[dict]:
    with db.session() as conn:
        row = conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()
        return dict(row) if row else None


# ---------------------------------------------------------------------------
# Logboek: eigen per gebruiker, gekoppeld aan een gedeeld signaal
# ---------------------------------------------------------------------------

_JOURNAL_SELECT = """
    SELECT
        je.id AS id, je.signal_id AS signal_id, je.user_id AS user_id,
        je.risk_eur AS risk_eur, je.telegram_sent AS telegram_sent,
        je.status AS status, je.entry_price AS entry_price,
        je.exit_price AS exit_price, je.exit_time AS exit_time,
        je.result_eur AS result_eur, je.result_pct AS result_pct,
        je.note AS note,
        s.coin AS coin, s.direction AS direction, s.category AS category,
        s.price AS price, s.stop_loss AS stop_loss, s.take_profit AS take_profit,
        s.confidence AS confidence, s.technical_confirmed AS technical_confirmed,
        s.reason AS reason, s.created_at AS created_at
    FROM journal_entries je
    JOIN signals s ON s.id = je.signal_id
"""


def create_journal_entry(signal_id: int, user_id: int, risk_eur: float) -> int:
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO journal_entries (signal_id, user_id, risk_eur, created_at)
               VALUES (?, ?, ?, ?)""",
            (signal_id, user_id, risk_eur, db.now_iso()),
        )
        return cur.lastrowid


def mark_journal_telegram_sent(entry_id: int) -> None:
    with db.session() as conn:
        conn.execute("UPDATE journal_entries SET telegram_sent = 1 WHERE id = ?", (entry_id,))


def list_journal(user_id: int, status: Optional[str] = None, limit: int = 500) -> list[dict]:
    with db.session() as conn:
        if status == "open":
            rows = conn.execute(
                _JOURNAL_SELECT + """
                WHERE je.user_id = ? AND je.status != 'genegeerd' AND je.exit_price IS NULL
                ORDER BY je.id DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        elif status == "gesloten":
            rows = conn.execute(
                _JOURNAL_SELECT + """
                WHERE je.user_id = ? AND je.exit_price IS NOT NULL
                ORDER BY je.id DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        elif status == "genegeerd":
            rows = conn.execute(
                _JOURNAL_SELECT + """
                WHERE je.user_id = ? AND je.status = 'genegeerd'
                ORDER BY je.id DESC LIMIT ?""",
                (user_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                _JOURNAL_SELECT + "WHERE je.user_id = ? ORDER BY je.id DESC LIMIT ?",
                (user_id, limit),
            ).fetchall()
        return [dict(r) for r in rows]


def get_journal_entry(entry_id: int, user_id: int) -> Optional[dict]:
    with db.session() as conn:
        row = conn.execute(
            _JOURNAL_SELECT + "WHERE je.id = ? AND je.user_id = ?", (entry_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def list_journal_for_coin(user_id: int, coin: str) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            _JOURNAL_SELECT + "WHERE je.user_id = ? AND s.coin = ? ORDER BY je.id DESC",
            (user_id, coin.upper()),
        ).fetchall()
        return [dict(r) for r in rows]


def update_journal_status(
    entry_id: int, user_id: int, status: str, entry_price: Optional[float] = None,
) -> None:
    with db.session() as conn:
        if entry_price is not None:
            conn.execute(
                "UPDATE journal_entries SET status = ?, entry_price = ? WHERE id = ? AND user_id = ?",
                (status, entry_price, entry_id, user_id),
            )
        else:
            conn.execute(
                "UPDATE journal_entries SET status = ? WHERE id = ? AND user_id = ?",
                (status, entry_id, user_id),
            )


def close_journal_trade(entry_id: int, user_id: int, exit_price: float, exit_time: str) -> None:
    entry = get_journal_entry(entry_id, user_id)
    if not entry or entry["entry_price"] is None:
        raise ValueError("kan alleen sluiten als er een entry prijs is ingevuld")

    entry_price = entry["entry_price"]
    direction = entry["direction"].lower()
    risk_eur = entry["risk_eur"] or 0.0
    stop_loss = entry["stop_loss"]

    if direction == "long":
        result_pct = (exit_price - entry_price) / entry_price * 100
        risk_per_unit = entry_price - stop_loss if stop_loss else None
    else:
        result_pct = (entry_price - exit_price) / entry_price * 100
        risk_per_unit = stop_loss - entry_price if stop_loss else None

    if risk_per_unit and risk_per_unit > 0:
        move = (exit_price - entry_price) if direction == "long" else (entry_price - exit_price)
        result_eur = risk_eur * (move / risk_per_unit)
    else:
        result_eur = risk_eur * (result_pct / 100)

    with db.session() as conn:
        conn.execute(
            """UPDATE journal_entries
               SET exit_price = ?, exit_time = ?, result_eur = ?, result_pct = ?
               WHERE id = ? AND user_id = ?""",
            (exit_price, exit_time, result_eur, result_pct, entry_id, user_id),
        )


def update_journal_note(entry_id: int, user_id: int, note: str) -> None:
    with db.session() as conn:
        conn.execute(
            "UPDATE journal_entries SET note = ? WHERE id = ? AND user_id = ?",
            (note, entry_id, user_id),
        )


def winrate_stats(user_id: int) -> dict:
    """Winrate apart voor hoog en laag vertrouwen, op basis van gesloten trades
    van deze gebruiker."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT s.confidence AS confidence, je.result_eur AS result_eur
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL""",
            (user_id,),
        ).fetchall()

    def stats_for(confidence: str) -> dict:
        subset = [r["result_eur"] for r in rows if r["confidence"] == confidence]
        total = len(subset)
        wins = len([r for r in subset if r is not None and r > 0])
        winrate = (wins / total * 100) if total else 0.0
        return {"total": total, "wins": wins, "winrate": round(winrate, 1)}

    return {
        "hoog_vertrouwen": stats_for("hoog vertrouwen"),
        "laag_vertrouwen": stats_for("laag vertrouwen"),
    }


def cumulative_result_series(user_id: int) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            """SELECT exit_time, result_eur FROM journal_entries
               WHERE user_id = ? AND exit_price IS NOT NULL ORDER BY exit_time ASC""",
            (user_id,),
        ).fetchall()
    series = []
    running = 0.0
    for row in rows:
        running += row["result_eur"] or 0.0
        series.append({"time": row["exit_time"], "cumulative_eur": round(running, 2)})
    return series
