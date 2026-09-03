"""Alle databasetoegang op één plek: berichten, bron niveaus, coins en
signalen. Wordt gebruikt door de Discord bot, de verwerkingspijplijn en het
webdashboard."""
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import config, db


# ---------------------------------------------------------------------------
# Berichten
# ---------------------------------------------------------------------------

def insert_message(raw_text: str, image_paths: list[str], discord_user_id: Optional[str] = None) -> int:
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO messages (received_at, raw_text, has_image, image_paths, discord_user_id)
               VALUES (?, ?, ?, ?, ?)""",
            (db.now_iso(), raw_text, int(bool(image_paths)), json.dumps(image_paths), discord_user_id),
        )
        return cur.lastrowid


def is_first_message_from(discord_user_id: str, exclude_message_id: int) -> bool:
    """True als er, dit bericht niet meegerekend, nog geen eerder bericht van
    deze Discord gebruiker binnenkwam. Bepaalt of het welkomstbericht gaat."""
    with db.session() as conn:
        row = conn.execute(
            "SELECT 1 FROM messages WHERE discord_user_id = ? AND id != ? LIMIT 1",
            (discord_user_id, exclude_message_id),
        ).fetchone()
        return row is None


def last_message_received_at() -> Optional[str]:
    """Tijdstip van het laatst binnengekomen Discord bericht, ongeacht van
    wie. Simpele graadmeter of de bot uberhaupt nog berichten ontvangt."""
    with db.session() as conn:
        row = conn.execute("SELECT received_at FROM messages ORDER BY id DESC LIMIT 1").fetchone()
        return row["received_at"] if row else None


def find_recent_duplicate(raw_text: str, exclude_id: int, hours: int = 24) -> Optional[dict]:
    """Zoekt een eerder bericht met exact dezelfde tekst, al verwerkt binnen
    de laatste uren. Voorkomt een dubbele melding als hetzelfde bericht per
    ongeluk twee keer wordt doorgestuurd. Een bericht dat technisch mislukte
    (API fout, geen geldige interpretatie) telt niet mee: anders blokkeert
    een tijdelijke storing een identiek bericht voor de rest van de dag,
    ook nadat de storing allang voorbij is."""
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    with db.session() as conn:
        row = conn.execute(
            """SELECT * FROM messages
               WHERE raw_text = ? AND id != ? AND processed_at IS NOT NULL
                     AND received_at > ?
                     AND (note IS NULL OR note NOT LIKE 'API fout%')
               ORDER BY id DESC LIMIT 1""",
            (raw_text, exclude_id, cutoff.isoformat()),
        ).fetchone()
        return dict(row) if row else None


def mark_message_processed(
    message_id: int, coin: Optional[str], direction: Optional[str],
    category: Optional[str], unclear: bool, note: str = "",
) -> None:
    with db.session() as conn:
        conn.execute(
            """UPDATE messages
               SET coin = ?, direction = ?, category = ?, unclear = ?, note = ?, processed_at = ?
               WHERE id = ?""",
            (coin, direction, category, int(unclear), note or None, db.now_iso(), message_id),
        )


def latest_long_term_direction(coin: str) -> Optional[dict]:
    """Meest recente lange termijn bericht over deze coin met een bekende
    richting, inclusief "neutraal" voor een verdeelde conclusie. Gebruikt om
    een nieuw day trading signaal tegen recente community visie af te
    zetten, zonder daar een eigen pagina van te maken."""
    with db.session() as conn:
        row = conn.execute(
            """SELECT direction, received_at FROM messages
               WHERE coin = ? AND category = 'lange_termijn' AND direction IS NOT NULL
               ORDER BY id DESC LIMIT 1""",
            (coin.upper(),),
        ).fetchone()
        return dict(row) if row else None



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


def create_trendline(
    coin: str, user_id: int, label: str, x1: int, y1: float, x2: int, y2: float,
) -> int:
    """Zelf getekende schuine lijn (wig, driehoek, kanaal), twee punten in
    tijd/prijs. Gedeeld tussen gebruikers, net als source_levels."""
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO trendlines (coin, user_id, label, x1, y1, x2, y2, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (coin.upper(), user_id, label or None, x1, y1, x2, y2, db.now_iso()),
        )
        return cur.lastrowid


def list_trendlines(coin: str) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM trendlines WHERE coin = ? ORDER BY created_at",
            (coin.upper(),),
        ).fetchall()
        return [dict(r) for r in rows]


def delete_trendline(trendline_id: int, user_id: int) -> None:
    """Alleen de eigen getekende lijn, niet die van een andere gebruiker,
    ook al is de lijn zelf wel gedeeld zichtbaar."""
    with db.session() as conn:
        conn.execute(
            "DELETE FROM trendlines WHERE id = ? AND user_id = ?",
            (trendline_id, user_id),
        )


def list_recent_images_for_coin(coin: str, limit: int = 8) -> list[dict]:
    """De originele screenshots die bij berichten over deze coin zijn
    meegestuurd, meest recente eerst. Toont het patroon exact zoals de bron
    het heeft ingetekend, in plaats van het na te bouwen."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT id, received_at, image_paths FROM messages
               WHERE coin = ? AND has_image = 1 ORDER BY id DESC LIMIT ?""",
            (coin.upper(), limit),
        ).fetchall()
    images = []
    for row in rows:
        for path in json.loads(row["image_paths"] or "[]"):
            images.append({"message_id": row["id"], "received_at": row["received_at"], "path": path})
    return images[:limit]


# ---------------------------------------------------------------------------
# Dynamische coinlijst
# ---------------------------------------------------------------------------

def coin_is_tracked(symbol: str) -> bool:
    with db.session() as conn:
        return conn.execute(
            "SELECT 1 FROM coins WHERE symbol = ?", (symbol.upper(),)
        ).fetchone() is not None


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
    gebruikersnaam). Gebruikt door scripts/create_user.py, een beheerder die
    bewust een account aanmaakt of bijwerkt. Overschrijft desgewenst het
    wachtwoord van een bestaande gebruiker, gebruik hiervoor nooit
    gebruikersinvoer van een openbaar formulier, dat is register_user()."""
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


def register_user(username: str, password_hash: str) -> Optional[int]:
    """Voor open registratie via /registreer. In tegenstelling tot
    create_user() faalt dit gewoon (geeft None) als de gebruikersnaam al
    bestaat, in plaats van het bestaande account te overschrijven. Portfolio
    en risicopercentage starten op 0 / de standaardwaarde, telegram_chat_id
    leeg, in te stellen na het inloggen."""
    with db.session() as conn:
        existing = conn.execute(
            "SELECT 1 FROM users WHERE username = ?", (username,)
        ).fetchone()
        if existing:
            return None
        cur = conn.execute(
            """INSERT INTO users
               (username, password_hash, portfolio_eur, risk_percent, telegram_chat_id, created_at)
               VALUES (?, ?, 0, ?, NULL, ?)""",
            (username, password_hash, config.DEFAULT_RISK_PERCENT, db.now_iso()),
        )
        return cur.lastrowid


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
        "macd_signal", "volume_ratio", "ema9", "ema21", "atr", "atr_avg20", "adx",
        "technical_confirmed", "confidence", "reason", "stop_loss", "take_profit",
        "context_note", "is_practice", "plain_explanation",
    ]
    values = [data.get("is_practice", 0) if f == "is_practice" else data.get(f) for f in fields]
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


def list_day_trading_signals_for_backtest(limit: int = 50) -> list[dict]:
    """Echte (niet-oefen) day trading signalen, meest recent eerst, voor
    scripts/backtest_factors.py: hoeveel van je eigen historische signalen
    zouden de nieuwe factoren gehaald hebben."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT id, coin, direction, created_at FROM signals
               WHERE category = 'day_trading' AND is_practice = 0
               ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_recent_signals(coin: str, limit: int = 3) -> list[dict]:
    """Gedeelde, echte signalen voor deze coin, hetzelfde voor iedereen.
    Oefentrades zijn persoonlijk en horen hier niet tussen, anders lijkt
    een handmatige oefening net een echt signaal voor alle gebruikers."""
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM signals WHERE coin = ? AND is_practice = 0 ORDER BY created_at DESC LIMIT ?",
            (coin.upper(), limit),
        ).fetchall()
        return [dict(r) for r in rows]


def find_open_signal(coin: str, direction: str) -> Optional[dict]:
    """Het meest recente signaal voor deze coin en richting, alleen als
    minstens één gebruiker die nog niet gesloten heeft. Een nieuw bericht
    over dezelfde coin en richting werkt dit signaal bij in plaats van er
    een los signaal naast te zetten."""
    with db.session() as conn:
        row = conn.execute(
            """SELECT * FROM signals WHERE coin = ? AND direction = ?
               ORDER BY created_at DESC LIMIT 1""",
            (coin.upper(), direction.lower()),
        ).fetchone()
        if not row:
            return None
        signal = dict(row)
        still_open = conn.execute(
            "SELECT COUNT(*) FROM journal_entries WHERE signal_id = ? AND exit_price IS NULL",
            (signal["id"],),
        ).fetchone()[0]
        return signal if still_open > 0 else None


def update_signal(signal_id: int, data: dict) -> None:
    fields = [
        "price", "rsi", "macd", "macd_signal", "volume_ratio", "ema9", "ema21", "atr",
        "atr_avg20", "adx",
        "technical_confirmed", "confidence", "reason", "stop_loss", "take_profit",
        "context_note", "plain_explanation",
    ]
    values = [data.get(f) for f in fields]
    with db.session() as conn:
        conn.execute(
            f"""UPDATE signals SET {", ".join(f"{f} = ?" for f in fields)}, created_at = ?
                WHERE id = ?""",
            (*values, db.now_iso(), signal_id),
        )


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
        je.position_size_override AS position_size_override,
        s.coin AS coin, s.direction AS direction, s.category AS category,
        s.price AS price,
        COALESCE(je.stop_loss_override, s.stop_loss) AS stop_loss,
        COALESCE(je.take_profit_override, s.take_profit) AS take_profit,
        s.stop_loss AS stop_loss_default, s.take_profit AS take_profit_default,
        s.confidence AS confidence, s.technical_confirmed AS technical_confirmed,
        s.rsi AS rsi, s.ema9 AS ema9, s.ema21 AS ema21,
        s.macd AS macd, s.macd_signal AS macd_signal, s.volume_ratio AS volume_ratio,
        s.atr_avg20 AS atr_avg20, s.adx AS adx,
        s.reason AS reason, s.context_note AS context_note, s.created_at AS created_at,
        s.is_practice AS is_practice, s.plain_explanation AS plain_explanation
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


def list_journal_entries_for_signal(signal_id: int) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            _JOURNAL_SELECT + "WHERE je.signal_id = ?", (signal_id,),
        ).fetchall()
        return [dict(r) for r in rows]


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


def auto_ignore_opposite_pending(coin: str, direction: str) -> int:
    """Negeert automatisch elke nog niet bevestigde logboekregel (geen eigen
    entry ingevuld) voor de tegenovergestelde richting van deze coin.

    Je kan niet tegelijk een long en een short op dezelfde coin serieus
    overwegen: zodra er een nieuwe melding voor de ene kant binnenkomt, is
    een oude, nog niet genomen melding voor de andere kant achterhaald.
    Welke van de twee richtingen daadwerkelijk klopt, blijft bepaald door
    de harde regels (de factoren op het nieuwe signaal), niet door een
    eigen inschatting hier: dit ruimt alleen de overbodige tegenstrijdige
    rest op. Een trade die al genomen is (eigen entry al ingevuld) is een
    echte open positie en wordt hier nooit aangeraakt.

    Geeft het aantal geraakte logboekregels terug."""
    opposite = "short" if direction.lower() == "long" else "long"
    note = f"automatisch genegeerd: nieuwe {direction} melding voor {coin.upper()} maakt dit tegenovergestelde signaal achterhaald"
    with db.session() as conn:
        cur = conn.execute(
            """UPDATE journal_entries SET status = 'genegeerd', note = ?
               WHERE entry_price IS NULL AND status != 'genegeerd'
                     AND signal_id IN (
                         SELECT id FROM signals
                         WHERE coin = ? AND direction = ? AND is_practice = 0
                     )""",
            (note, coin.upper(), opposite),
        )
        return cur.rowcount


def reset_journal_entry(entry_id: int, user_id: int) -> None:
    """Zet een logboekregel helemaal terug naar de beginstaat: status
    'nieuw', geen entry/exit prijs, geen resultaat. Voor als er per ongeluk
    een verkeerde prijs of status is ingevuld, zonder de hele trade
    kwijt te raken (de melding zelf, stop loss en take profit blijven
    gewoon staan). level_alert_sent gaat ook weer op 0, anders krijgt een
    teruggezet signaal nooit meer een niveau-seintje."""
    with db.session() as conn:
        conn.execute(
            """UPDATE journal_entries
               SET status = 'nieuw', entry_price = NULL, exit_price = NULL,
                   exit_time = NULL, result_eur = NULL, result_pct = NULL,
                   level_alert_sent = 0
               WHERE id = ? AND user_id = ?""",
            (entry_id, user_id),
        )


def delete_practice_entry(entry_id: int, user_id: int) -> None:
    """Verwijdert een oefentrade helemaal. Anders dan reset_journal_entry:
    een oefentrade heeft geen echte melding om naar terug te vallen, dus
    "weggooien" moet de regel echt kwijtraken, niet terugzetten naar een
    staat zonder entryprijs die de kaart niet kan tonen. De EXISTS-check
    zorgt dat dit nooit een echte trade kan raken, ook niet per ongeluk
    met een verkeerd entry_id."""
    with db.session() as conn:
        conn.execute(
            """DELETE FROM journal_entries
               WHERE id = ? AND user_id = ?
                 AND EXISTS (
                     SELECT 1 FROM signals
                     WHERE signals.id = journal_entries.signal_id AND signals.is_practice = 1
                 )""",
            (entry_id, user_id),
        )


def close_journal_trade(entry_id: int, user_id: int, exit_price: float, exit_time: str) -> None:
    entry = get_journal_entry(entry_id, user_id)
    if not entry or entry["entry_price"] is None or entry["status"] == "genegeerd":
        raise ValueError("kan alleen sluiten als er een entry prijs is ingevuld en de trade niet genegeerd is")

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


def update_journal_levels(
    entry_id: int, user_id: int,
    stop_loss: Optional[float], take_profit: Optional[float], position_size: Optional[float],
) -> None:
    """Eigen stop loss, take profit en/of positiegrootte op een open trade,
    los van wat het signaal zelf berekende. Leeg gelaten in het formulier
    betekent None hier, en dat zet de override weer terug op de berekende
    standaardwaarde (COALESCE in _JOURNAL_SELECT valt dan terug op het
    signaal, position_size_override op None valt terug op de berekening
    in web/main.py)."""
    with db.session() as conn:
        conn.execute(
            """UPDATE journal_entries
               SET stop_loss_override = ?, take_profit_override = ?, position_size_override = ?
               WHERE id = ? AND user_id = ?""",
            (stop_loss, take_profit, position_size, entry_id, user_id),
        )


def list_open_entries_with_levels() -> list[dict]:
    """Alle open logboekregels (eigen entry ingevuld, nog niet gesloten, nog
    geen seintje verstuurd), van alle gebruikers, met de coin, richting,
    stop loss/take profit en het telegram_chat_id erbij. Voor de periodieke
    check of een open trade zijn niveau al geraakt heeft. Oefentrades zijn
    niet echt, daar hoort geen Telegram seintje bij."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT je.id AS id, je.user_id AS user_id, je.entry_price AS entry_price,
                      s.coin AS coin, s.direction AS direction,
                      COALESCE(je.stop_loss_override, s.stop_loss) AS stop_loss,
                      COALESCE(je.take_profit_override, s.take_profit) AS take_profit,
                      u.username AS username, u.telegram_chat_id AS telegram_chat_id
               FROM journal_entries je
               JOIN signals s ON s.id = je.signal_id
               JOIN users u ON u.id = je.user_id
               WHERE je.entry_price IS NOT NULL AND je.exit_price IS NULL
                     AND je.level_alert_sent = 0 AND s.is_practice = 0"""
        ).fetchall()
        return [dict(r) for r in rows]


def list_pending_entries_with_price() -> list[dict]:
    """Alle logboekregels die nog niet genomen zijn (nog geen eigen entry
    ingevuld, niet genegeerd, nog geen seintje verstuurd), met het
    oorspronkelijke signaalniveau en de ATR erbij. Voor de periodieke check
    of de prijs weer dicht bij het niveau van een nog niet genomen signaal
    komt. Gebruikt dezelfde level_alert_sent vlag als de SL/TP check op
    open trades: een regel zonder eigen entry kan die twee nooit
    tegelijk nodig hebben, dus hergebruik is hier veilig."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT je.id AS id, je.user_id AS user_id,
                      s.coin AS coin, s.direction AS direction, s.price AS signal_price,
                      s.atr AS atr, s.confidence AS confidence,
                      u.username AS username, u.telegram_chat_id AS telegram_chat_id
               FROM journal_entries je
               JOIN signals s ON s.id = je.signal_id
               JOIN users u ON u.id = je.user_id
               WHERE je.entry_price IS NULL AND je.exit_price IS NULL
                     AND je.status != 'genegeerd' AND je.level_alert_sent = 0
                     AND s.is_practice = 0"""
        ).fetchall()
        return [dict(r) for r in rows]


def mark_level_alert_sent(entry_id: int) -> None:
    with db.session() as conn:
        conn.execute("UPDATE journal_entries SET level_alert_sent = 1 WHERE id = ?", (entry_id,))


def count_pending_signals(user_id: int) -> int:
    """Aantal echte meldingen die nog op een keuze wachten (nog niet
    Genomen/Aangepast/Genegeerd). Basis voor het cijfer op het app-icoon."""
    with db.session() as conn:
        row = conn.execute(
            """SELECT COUNT(*) AS n
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.status = 'nieuw' AND s.is_practice = 0""",
            (user_id,),
        ).fetchone()
        return row["n"]


def winrate_stats(user_id: int) -> dict:
    """Winrate en gemiddeld resultaat apart voor hoog en laag vertrouwen,
    op basis van gesloten trades van deze gebruiker. Winrate alleen zegt
    weinig over de verhouding tussen winst en verlies per trade, het
    gemiddelde resultaat erbij geeft een eerlijker beeld."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT s.confidence AS confidence, je.result_eur AS result_eur,
                      je.result_pct AS result_pct
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL AND s.is_practice = 0""",
            (user_id,),
        ).fetchall()

    def stats_for(confidence: str) -> dict:
        subset = [r for r in rows if r["confidence"] == confidence]
        total = len(subset)
        wins = len([r for r in subset if r["result_eur"] is not None and r["result_eur"] > 0])
        winrate = (wins / total * 100) if total else 0.0
        eur_values = [r["result_eur"] for r in subset if r["result_eur"] is not None]
        pct_values = [r["result_pct"] for r in subset if r["result_pct"] is not None]
        avg_eur = sum(eur_values) / len(eur_values) if eur_values else 0.0
        avg_pct = sum(pct_values) / len(pct_values) if pct_values else 0.0
        return {
            "total": total, "wins": wins, "winrate": round(winrate, 1),
            "avg_result_eur": round(avg_eur, 2), "avg_result_pct": round(avg_pct, 1),
        }

    return {
        "hoog_vertrouwen": stats_for("hoog vertrouwen"),
        "laag_vertrouwen": stats_for("laag vertrouwen"),
    }


def winrate_by_ratio(user_id: int) -> list[dict]:
    """Voor elke gesloten, echte trade: hoeveel van de getoonde factoren
    klopten (bv. "3/4"), en hoe vaak leidde dat tot winst. Losstaand van
    het hoog/laag vertrouwen label zelf, dit toetst of de score binnen
    een label ook echt iets voorspelt. Werkt met elk aantal factoren, dus
    ook ongewijzigd zodra de uitgebreide factoren ooit meetellen."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT s.reason AS reason, je.result_eur AS result_eur
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL AND s.is_practice = 0""",
            (user_id,),
        ).fetchall()

    buckets: dict[tuple[int, int], list[bool]] = {}
    for row in rows:
        reason = row["reason"]
        if not reason:
            continue
        factors = reason.split(" | ")
        total = len(factors)
        passed = sum(1 for f in factors if f.startswith("✓"))
        buckets.setdefault((passed, total), []).append((row["result_eur"] or 0) > 0)

    result = []
    for (passed, total), outcomes in sorted(buckets.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        wins = sum(1 for ok in outcomes if ok)
        result.append({
            "ratio": f"{passed}/{total}",
            "passed": passed, "total": total, "trades": len(outcomes),
            "winrate": round(wins / len(outcomes) * 100, 1),
        })
    return result


def cumulative_result_series(user_id: int) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            """SELECT je.exit_time AS exit_time, je.result_eur AS result_eur
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL AND s.is_practice = 0
               ORDER BY je.exit_time ASC""",
            (user_id,),
        ).fetchall()
    series = []
    running = 0.0
    for row in rows:
        running += row["result_eur"] or 0.0
        series.append({"time": row["exit_time"], "cumulative_eur": round(running, 2)})
    return series


def coin_stats(user_id: int) -> list[dict]:
    """Winrate en gemiddeld resultaat per coin, op basis van gesloten trades
    van deze gebruiker. Laat zien welke coin het goed doet met dit systeem,
    en welke niet."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT s.coin AS coin, je.result_eur AS result_eur
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL AND s.is_practice = 0""",
            (user_id,),
        ).fetchall()

    by_coin: dict[str, list] = {}
    for row in rows:
        by_coin.setdefault(row["coin"], []).append(row["result_eur"])

    stats = []
    for coin, results in by_coin.items():
        total = len(results)
        wins = len([r for r in results if r is not None and r > 0])
        values = [r for r in results if r is not None]
        stats.append({
            "coin": coin,
            "total": total,
            "wins": wins,
            "winrate": round(wins / total * 100, 1) if total else 0.0,
            "avg_result_eur": round(sum(values) / len(values), 2) if values else 0.0,
        })

    stats.sort(key=lambda s: s["total"], reverse=True)
    return stats
