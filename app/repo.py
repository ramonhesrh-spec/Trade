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
# Signalen
# ---------------------------------------------------------------------------

def insert_signal(data: dict) -> int:
    fields = [
        "message_id", "coin", "direction", "category", "price", "rsi", "macd",
        "macd_signal", "volume_ratio", "ema9", "ema21", "atr",
        "technical_confirmed", "confidence", "reason", "stop_loss",
        "take_profit", "risk_eur", "telegram_sent",
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


def list_signals(status: Optional[str] = None, limit: int = 500) -> list[dict]:
    with db.session() as conn:
        if status == "open":
            rows = conn.execute(
                """SELECT * FROM signals
                   WHERE status != 'genegeerd' AND exit_price IS NULL
                   ORDER BY id DESC LIMIT ?""",
                (limit,),
            ).fetchall()
        elif status == "gesloten":
            rows = conn.execute(
                "SELECT * FROM signals WHERE exit_price IS NOT NULL ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        elif status == "genegeerd":
            rows = conn.execute(
                "SELECT * FROM signals WHERE status = 'genegeerd' ORDER BY id DESC LIMIT ?",
                (limit,),
            ).fetchall()
        else:
            rows = conn.execute(
                "SELECT * FROM signals ORDER BY id DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(r) for r in rows]


def get_signal(signal_id: int) -> Optional[dict]:
    with db.session() as conn:
        row = conn.execute("SELECT * FROM signals WHERE id = ?", (signal_id,)).fetchone()
        return dict(row) if row else None


def list_signals_for_coin(coin: str) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM signals WHERE coin = ? ORDER BY id DESC", (coin.upper(),)
        ).fetchall()
        return [dict(r) for r in rows]


def update_status(signal_id: int, status: str, entry_price: Optional[float] = None) -> None:
    with db.session() as conn:
        if entry_price is not None:
            conn.execute(
                "UPDATE signals SET status = ?, entry_price = ? WHERE id = ?",
                (status, entry_price, signal_id),
            )
        else:
            conn.execute(
                "UPDATE signals SET status = ? WHERE id = ?", (status, signal_id)
            )


def close_trade(signal_id: int, exit_price: float, exit_time: str) -> None:
    signal = get_signal(signal_id)
    if not signal or signal["entry_price"] is None:
        raise ValueError("kan alleen sluiten als er een entry prijs is ingevuld")

    entry = signal["entry_price"]
    direction = signal["direction"].lower()
    risk_eur = signal["risk_eur"] or 0.0
    stop_loss = signal["stop_loss"]

    if direction == "long":
        result_pct = (exit_price - entry) / entry * 100
        risk_per_unit = entry - stop_loss if stop_loss else None
    else:
        result_pct = (entry - exit_price) / entry * 100
        risk_per_unit = stop_loss - entry if stop_loss else None

    if risk_per_unit and risk_per_unit > 0:
        move = (exit_price - entry) if direction == "long" else (entry - exit_price)
        result_eur = risk_eur * (move / risk_per_unit)
    else:
        result_eur = risk_eur * (result_pct / 100)

    with db.session() as conn:
        conn.execute(
            """UPDATE signals
               SET exit_price = ?, exit_time = ?, result_eur = ?, result_pct = ?
               WHERE id = ?""",
            (exit_price, exit_time, result_eur, result_pct, signal_id),
        )


def mark_telegram_sent(signal_id: int) -> None:
    with db.session() as conn:
        conn.execute("UPDATE signals SET telegram_sent = 1 WHERE id = ?", (signal_id,))


def update_note(signal_id: int, note: str) -> None:
    with db.session() as conn:
        conn.execute("UPDATE signals SET note = ? WHERE id = ?", (note, signal_id))


def winrate_stats() -> dict:
    """Winrate apart voor hoog en laag vertrouwen, op basis van gesloten trades."""
    with db.session() as conn:
        rows = conn.execute(
            "SELECT confidence, result_eur FROM signals WHERE exit_price IS NOT NULL"
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


def cumulative_result_series() -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            """SELECT exit_time, result_eur FROM signals
               WHERE exit_price IS NOT NULL ORDER BY exit_time ASC"""
        ).fetchall()
    series = []
    running = 0.0
    for row in rows:
        running += row["result_eur"] or 0.0
        series.append({"time": row["exit_time"], "cumulative_eur": round(running, 2)})
    return series
