"""Alle databasetoegang op één plek: berichten, bron niveaus, coins en
signalen. Wordt gebruikt door de Discord bot, de verwerkingspijplijn en het
webdashboard."""
import json
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import config, db, risk


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


def last_message_received_at() -> Optional[str]:
    """Tijdstip van het laatst binnengekomen Discord bericht, ongeacht van
    wie. Simpele graadmeter of de bot uberhaupt nog berichten ontvangt."""
    with db.session() as conn:
        row = conn.execute("SELECT received_at FROM messages ORDER BY id DESC LIMIT 1").fetchone()
        return row["received_at"] if row else None


def find_recent_duplicate(raw_text: str, exclude_id: int, minutes: int = 3) -> Optional[dict]:
    """Zoekt een eerder bericht met exact dezelfde tekst, al verwerkt binnen
    de laatste paar minuten. Voorkomt alleen een dubbele melding als hetzelfde
    bericht per ongeluk vlak na elkaar twee keer wordt doorgestuurd (bijvoorbeeld
    een dubbele klik). Bewust een kort venster, geen uren: prijs, koersdata en
    de technische toetsing veranderen continu, dus eenzelfde tekst een uur
    later (of na een update van de regels zelf) verdient een verse analyse,
    niet het stokoude resultaat van de eerste keer. Een bericht dat technisch
    mislukte (API fout, geen geldige interpretatie) telt niet mee: anders
    blokkeert een tijdelijke storing een identiek bericht voor de rest van
    het venster, ook nadat de storing allang voorbij is."""
    cutoff = datetime.now(timezone.utc) - timedelta(minutes=minutes)
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


def set_message_summary(message_id: int, summary: str) -> None:
    """Slaat de klare-taal herschrijving van het originele bericht op (zie
    explain.summarize_message), los van signals.plain_explanation dat de
    berekende technische factoren uitlegt."""
    with db.session() as conn:
        conn.execute("UPDATE messages SET message_summary = ? WHERE id = ?", (summary, message_id))


def mark_message_untracked(message_id: int, coin: str) -> None:
    """Coin bestaat niet (meer) als handelspaar op de exchange: geen
    technische toetsing mogelijk. Zonder dit verdwijnt zo'n bericht na een
    geslaagde AI-interpretatie alsnog volledig stil, geen Telegram, geen
    spoor voor de operator, alsof het bericht nooit aangekomen is.

    Coin-gescopet op message_coin_results, niet messages: met meerdere
    coins per bericht (zie message_coin_results) delen ze hetzelfde
    message_id, dus zonder coin-filter zou coin A's onvolgbaarheid ook
    coin B's al wel geslaagde resultaat overschrijven."""
    with db.session() as conn:
        conn.execute(
            "UPDATE message_coin_results SET unclear = 1, note = ? WHERE message_id = ? AND coin = ?",
            (f"{coin.upper()} staat niet (meer) als paar op de exchange, kon niet getoetst worden",
             message_id, coin),
        )


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
    overneemt, niet alleen de eerste.

    narrative_id en price_at_receipt worden bewust NIET meegekopieerd: een
    duplicaat-bericht is geen nieuwe narrative-update (die telling zou dan
    dubbel oplopen) en geen nieuwe live-prijs-meting (die prijs hoort bij
    het moment van het origineel, niet bij dit duplicaat)."""
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
                 new_note, row["message_summary"], None, None, db.now_iso()),
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


_SWING_WATCH_SELECT = """
    SELECT sw.id AS id, sw.message_id AS message_id, sw.source_level_id AS source_level_id,
           sw.coin AS coin, sw.direction AS direction, sw.status AS status,
           sw.created_at AS created_at, sw.checked_at AS checked_at,
           sl.price_level AS price_level, sl.pattern_name AS pattern_name,
           COALESCE(mcr.price_at_receipt, m.price_at_receipt) AS reference_price
    FROM swing_watches sw
    JOIN source_levels sl ON sl.id = sw.source_level_id
    JOIN messages m ON m.id = sw.message_id
    LEFT JOIN message_coin_results mcr ON mcr.message_id = sw.message_id AND mcr.coin = sw.coin
"""


def create_swing_watch(message_id: int, source_level_id: int, coin: str, direction: str) -> int:
    """Idempotent op coin+richting: als er al een 'wachtende' watch is voor
    dezelfde coin+richting, wordt die teruggegeven in plaats van een tweede
    aangemaakt. Dit is de enige plek waar swing_watches-rijen ontstaan (ook
    vanuit het backfill-script), dus dit is waar dubbele watches voor
    dezelfde kans structureel voorkomen worden, ongeacht welke aanroeper
    het was — een losse check in slechts één aanroeper laat de andere
    aanroepers alsnog een dubbel signaal/dubbele melding opleveren."""
    with db.session() as conn:
        existing = conn.execute(
            "SELECT id FROM swing_watches WHERE coin = ? AND direction = ? AND status = 'wachtend'",
            (coin.upper(), direction.lower()),
        ).fetchone()
        if existing:
            return existing["id"]
        cur = conn.execute(
            """INSERT INTO swing_watches (message_id, source_level_id, coin, direction, status, created_at)
               VALUES (?, ?, ?, ?, 'wachtend', ?)""",
            (message_id, source_level_id, coin.upper(), direction.lower(), db.now_iso()),
        )
        return cur.lastrowid


def get_swing_watch(watch_id: int) -> Optional[dict]:
    with db.session() as conn:
        row = conn.execute(_SWING_WATCH_SELECT + "WHERE sw.id = ?", (watch_id,)).fetchone()
        return dict(row) if row else None


def list_watches_by_status(status: str) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(_SWING_WATCH_SELECT + "WHERE sw.status = ?", (status,)).fetchall()
        return [dict(r) for r in rows]


def update_swing_watch_status(watch_id: int, status: str) -> None:
    with db.session() as conn:
        conn.execute(
            "UPDATE swing_watches SET status = ?, checked_at = ? WHERE id = ?",
            (status, db.now_iso(), watch_id),
        )


def claim_swing_watch(watch_id: int) -> bool:
    """Atomisch: zet een watch van 'wachtend' naar 'bevestigd', maar
    alleen als hij op dit moment nog echt 'wachtend' is. Voorkomt dat de
    directe check (bij binnenkomst van een bericht) en de periodieke
    15-minuten-check dezelfde watch allebei afhandelen als ze elkaar
    net overlappen: wie hier als eerste bij is wint, de ander stopt."""
    with db.session() as conn:
        cur = conn.execute(
            "UPDATE swing_watches SET status = 'bevestigd', checked_at = ? WHERE id = ? AND status = 'wachtend'",
            (db.now_iso(), watch_id),
        )
        return cur.rowcount > 0


def active_swing_watches_for_coin(coin: str) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            _SWING_WATCH_SELECT + "WHERE sw.coin = ? AND sw.status = 'wachtend' ORDER BY sw.created_at DESC",
            (coin.upper(),),
        ).fetchall()
        return [dict(r) for r in rows]


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


def list_recent_source_levels_without_watch(since_iso: str) -> list[dict]:
    """Bron-niveaus van na `since_iso` die nog geen swing_watches-regel
    hebben, met de richting van hun eigen bericht erbij. Voor het eenmalige
    backfill-script (scripts/backfill_swing_watches.py). Alleen bruikbaar
    als het bericht zelf een duidelijke long/short richting had: 'neutraal'
    of leeg heeft geen kant om een niveau tegen te toetsen.

    day_trading-berichten blijven buiten beschouwing: die krijgen hun
    niveau-gebaseerde SL/TP al via hun eigen pijplijn (zie Task 6), een
    aparte swing-watch zou een dubbel signaal voor hetzelfde bericht
    opleveren."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT sl.id AS source_level_id, sl.message_id AS message_id,
                      sl.coin AS coin, sl.price_level AS price_level, sl.pattern_name AS pattern_name,
                      m.direction AS direction
               FROM source_levels sl
               JOIN messages m ON m.id = sl.message_id
               LEFT JOIN swing_watches sw ON sw.source_level_id = sl.id
               WHERE sw.id IS NULL AND sl.created_at >= ? AND m.direction IN ('long', 'short')
                     AND m.category != 'day_trading'""",
            (since_iso,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_active_narrative(coin: str) -> Optional[dict]:
    """Het narrative met status 'actief' voor deze coin, ongeacht richting.
    Op elk moment hoort er hoogstens één te bestaan: een tegenspraak sluit
    het vorige altijd af vóór er een nieuwe wordt aangemaakt (zie
    signal_processor.evaluate_narrative)."""
    with db.session() as conn:
        row = conn.execute(
            "SELECT * FROM coin_narratives WHERE coin = ? AND status = 'actief' ORDER BY id DESC LIMIT 1",
            (coin.upper(),),
        ).fetchone()
        return dict(row) if row else None


def get_narrative(narrative_id: int) -> Optional[dict]:
    with db.session() as conn:
        row = conn.execute("SELECT * FROM coin_narratives WHERE id = ?", (narrative_id,)).fetchone()
        return dict(row) if row else None


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


def close_narrative(narrative_id: int, status: str, closed_reason: str) -> None:
    with db.session() as conn:
        conn.execute(
            "UPDATE coin_narratives SET status = ?, closed_reason = ? WHERE id = ?",
            (status, closed_reason, narrative_id),
        )


def list_active_narratives() -> list[dict]:
    """Voor de periodieke verval-check (check_narratives): alle actieve
    narratives, over alle coins heen."""
    with db.session() as conn:
        rows = conn.execute("SELECT * FROM coin_narratives WHERE status = 'actief'").fetchall()
        return [dict(r) for r in rows]


def list_narratives_for_coin(coin: str) -> list[dict]:
    """Voor de coin-pagina: het actieve narrative (indien aanwezig)
    bovenaan, recente tegengesproken/verlopen narratives erna."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT * FROM coin_narratives WHERE coin = ?
               ORDER BY (status = 'actief') DESC, last_update_at DESC""",
            (coin.upper(),),
        ).fetchall()
        return [dict(r) for r in rows]


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


def get_narrative_notification(narrative_id: int, user_id: int) -> Optional[dict]:
    with db.session() as conn:
        row = conn.execute(
            "SELECT * FROM narrative_notifications WHERE narrative_id = ? AND user_id = ?",
            (narrative_id, user_id),
        ).fetchone()
        return dict(row) if row else None


def upsert_narrative_notification(narrative_id: int, user_id: int, telegram_message_id: int) -> None:
    """Onthoudt welk Telegram-bericht-ID de laatste melding van dit
    narrative was voor deze gebruiker, zodat een volgende update kan
    proberen dat bericht te bewerken. Overschrijft de vorige waarde in
    plaats van een tweede rij aan te maken."""
    with db.session() as conn:
        conn.execute(
            """INSERT INTO narrative_notifications (narrative_id, user_id, telegram_message_id, sent_at)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(narrative_id, user_id) DO UPDATE SET
                   telegram_message_id = excluded.telegram_message_id,
                   sent_at = excluded.sent_at""",
            (narrative_id, user_id, telegram_message_id, db.now_iso()),
        )


# ---------------------------------------------------------------------------
# Web Push abonnementen en rustige meldingen
# ---------------------------------------------------------------------------

def upsert_push_subscription(
    user_id: int, endpoint: str, p256dh: str, auth: str, device_label: Optional[str] = None,
) -> None:
    """Slaat een Web Push-abonnement op. endpoint is uniek: hetzelfde
    apparaat dat opnieuw abonneert (bijvoorbeeld na het wissen van
    browserdata) overschrijft de bestaande rij i.p.v. een duplicaat aan
    te maken."""
    with db.session() as conn:
        conn.execute(
            """INSERT INTO push_subscriptions (user_id, endpoint, p256dh, auth, device_label, created_at)
               VALUES (?, ?, ?, ?, ?, ?)
               ON CONFLICT(endpoint) DO UPDATE SET
                   user_id = excluded.user_id,
                   p256dh = excluded.p256dh,
                   auth = excluded.auth,
                   device_label = excluded.device_label""",
            (user_id, endpoint, p256dh, auth, device_label, db.now_iso()),
        )


def list_push_subscriptions(user_id: int) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM push_subscriptions WHERE user_id = ?", (user_id,)
        ).fetchall()
        return [dict(r) for r in rows]


def delete_push_subscription(endpoint: str) -> None:
    """Aangeroepen zodra pywebpush een 404/410 teruggeeft: de browser/OS
    kent dit abonnement niet meer, verder blijven proberen vervuilt de
    tabel alleen maar."""
    with db.session() as conn:
        conn.execute("DELETE FROM push_subscriptions WHERE endpoint = ?", (endpoint,))


def create_notification(
    user_id: Optional[int], type: str, title: str, body: str, url: Optional[str] = None,
) -> int:
    """Rustige melding, geen push. user_id=None is een admin-only rij
    (systeemgezondheid, herhaalde API-fouten), alleen zichtbaar op de
    admin-pagina/sectie, nooit op de gewone /meldingen-lijst van een
    normale gebruiker."""
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO notifications (user_id, type, title, body, url, created_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (user_id, type, title, body, url, db.now_iso()),
        )
        return cur.lastrowid


def list_notifications(user_id: int, limit: int = 50) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE user_id = ? ORDER BY created_at DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def list_admin_notifications(limit: int = 50) -> list[dict]:
    """Systeemgezondheid en herhaalde-API-fouten: user_id IS NULL, alleen
    voor de admin-pagina, nooit gemengd met een normale gebruiker se
    eigen lijst."""
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM notifications WHERE user_id IS NULL ORDER BY created_at DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [dict(r) for r in rows]


def count_unread_notifications(user_id: int) -> int:
    with db.session() as conn:
        row = conn.execute(
            "SELECT COUNT(*) AS n FROM notifications WHERE user_id = ? AND is_read = 0",
            (user_id,),
        ).fetchone()
        return row["n"]


def mark_notification_read(notification_id: int, user_id: int) -> None:
    """user_id in de WHERE, niet alleen notification_id: een gebruiker
    mag nooit andermans meldingsrij als gelezen markeren via een geraden
    ID (zelfde ownership-check-patroon als update_journal_status)."""
    with db.session() as conn:
        conn.execute(
            "UPDATE notifications SET is_read = 1 WHERE id = ? AND user_id = ?",
            (notification_id, user_id),
        )


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
        legacy_rows = conn.execute(
            """SELECT id, received_at, image_paths FROM messages
               WHERE coin = ? AND has_image = 1 ORDER BY id DESC""",
            (coin.upper(),),
        ).fetchall()
        per_coin_rows = conn.execute(
            """SELECT m.id AS id, m.received_at AS received_at, m.image_paths AS image_paths
               FROM message_coin_results mcr
               JOIN messages m ON m.id = mcr.message_id
               WHERE mcr.coin = ? AND m.has_image = 1""",
            (coin.upper(),),
        ).fetchall()
    rows = list(legacy_rows) + list(per_coin_rows)
    rows.sort(key=lambda r: r["id"], reverse=True)
    rows = rows[:limit]
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


MARKET_SCAN_SETTING_KEY = "market_scan_enabled"


def is_market_scan_enabled() -> bool:
    """Noodrem voor de autonome marktscan (app/market_scanner.py): een
    systeembrede vlag in de bestaande settings-tabel, standaard aan.
    Geen per-gebruiker instelling, zie de spec."""
    return db.get_setting(MARKET_SCAN_SETTING_KEY, default="1") == "1"


def set_market_scan_enabled(enabled: bool) -> None:
    db.set_setting(MARKET_SCAN_SETTING_KEY, "1" if enabled else "0")


def record_scan_direction(coin: str, direction: str) -> int:
    """Whiplash-rem voor de autonome marktscan: registreert de richting van
    deze cyclus en geeft terug hoeveel cycli achter elkaar dezelfde
    richting al aanhoudt (1 bij een wissel of de eerste keer). De
    aanroeper (market_scanner.py) vereist minstens 2 op rij voor een
    NIEUW signaal, zodat een EMA9/EMA21-kruising die na één cyclus alweer
    terugklapt niet meteen een melding oplevert."""
    with db.session() as conn:
        row = conn.execute(
            "SELECT last_scan_direction, last_scan_direction_count FROM coins WHERE symbol = ?",
            (coin.upper(),),
        ).fetchone()
        if row and row["last_scan_direction"] == direction.lower():
            new_count = row["last_scan_direction_count"] + 1
        else:
            new_count = 1
        conn.execute(
            "UPDATE coins SET last_scan_direction = ?, last_scan_direction_count = ? WHERE symbol = ?",
            (direction.lower(), new_count, coin.upper()),
        )
        return new_count


def get_breakout_retest_key(coin: str) -> Optional[str]:
    with db.session() as conn:
        row = conn.execute(
            "SELECT last_breakout_retest_key FROM coins WHERE symbol = ?", (coin.upper(),),
        ).fetchone()
        return row["last_breakout_retest_key"] if row else None


def set_breakout_retest_key(coin: str, key: str) -> None:
    with db.session() as conn:
        conn.execute(
            "UPDATE coins SET last_breakout_retest_key = ? WHERE symbol = ?", (key, coin.upper()),
        )


def get_trendline_retest_key(coin: str) -> Optional[str]:
    with db.session() as conn:
        row = conn.execute(
            "SELECT last_trendline_retest_key FROM coins WHERE symbol = ?", (coin.upper(),),
        ).fetchone()
        return row["last_trendline_retest_key"] if row else None


def set_trendline_retest_key(coin: str, key: str) -> None:
    with db.session() as conn:
        conn.execute(
            "UPDATE coins SET last_trendline_retest_key = ? WHERE symbol = ?", (key, coin.upper()),
        )


def list_coins() -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM coins WHERE active = 1 ORDER BY symbol"
        ).fetchall()
        return [dict(r) for r in rows]


def coins_with_recent_signal(hours: int = 24) -> set[str]:
    """Coins met minstens één echt signaal in de laatste `hours` uur. Basis
    voor het activiteits-stipje in het coin-menu: welke coins net nog iets
    deden, in plaats van dat de lijst er overal even stil uitziet."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with db.session() as conn:
        rows = conn.execute(
            "SELECT DISTINCT coin FROM signals WHERE created_at >= ? AND is_practice = 0",
            (cutoff,),
        ).fetchall()
        return {r["coin"] for r in rows}


def get_coin(symbol: str) -> Optional[dict]:
    with db.session() as conn:
        row = conn.execute("SELECT * FROM coins WHERE symbol = ?", (symbol.upper(),)).fetchone()
        return dict(row) if row else None


def set_coin_note(symbol: str, note: str) -> None:
    """Eigen aantekening bij een coin, los van een specifieke trade
    (bijvoorbeeld een unlock-datum of een aankomend nieuwsmoment). Gedeeld
    tussen gebruikers, net als de rest van de coin-gegevens. Lege string
    wist de aantekening weer."""
    with db.session() as conn:
        conn.execute(
            "UPDATE coins SET note = ? WHERE symbol = ?", (note or None, symbol.upper()),
        )


# ---------------------------------------------------------------------------
# Gebruikers
# ---------------------------------------------------------------------------

def create_user(
    username: str, password_hash: str, portfolio_eur: float,
    risk_percent: float,
) -> int:
    """Maakt een gebruiker aan, of werkt een bestaande bij (zelfde
    gebruikersnaam). Gebruikt door scripts/create_user.py, een beheerder die
    bewust een account aanmaakt of bijwerkt. Overschrijft desgewenst het
    wachtwoord van een bestaande gebruiker, gebruik hiervoor nooit
    gebruikersinvoer van een openbaar formulier, dat is register_user().
    telegram_chat_id zit hier bewust niet meer bij (Taak 11): net als
    update_user_settings mag dit een eventuele bestaande (legacy) waarde
    niet stilzwijgend op elke aanroep naar NULL overschrijven."""
    with db.session() as conn:
        conn.execute(
            """INSERT INTO users
               (username, password_hash, portfolio_eur, risk_percent, created_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(username) DO UPDATE SET
                 password_hash = excluded.password_hash,
                 portfolio_eur = excluded.portfolio_eur,
                 risk_percent = excluded.risk_percent""",
            (username, password_hash, portfolio_eur, risk_percent, db.now_iso()),
        )
        row = conn.execute("SELECT id FROM users WHERE username = ?", (username,)).fetchone()
        return row["id"]


def register_user(username: str, password_hash: str) -> Optional[int]:
    """Voor open registratie via /registreer. In tegenstelling tot
    create_user() faalt dit gewoon (geeft None) als de gebruikersnaam al
    bestaat, in plaats van het bestaande account te overschrijven. Portfolio
    en risicopercentage starten op 0 / de standaardwaarde, in te stellen na
    het inloggen. telegram_chat_id staat hier vast op NULL: die kolom is
    een restant van de Telegram-bot (Taak 11), niet meer instelbaar."""
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
    quiet_hours_start: Optional[str] = None, quiet_hours_end: Optional[str] = None,
) -> None:
    """telegram_chat_id zit hier bewust niet meer bij (Taak 11): het veld is
    uit het instellingenformulier gehaald, dus deze functie mag een
    eventuele bestaande (legacy) waarde niet stilzwijgend op elke opslag
    naar NULL overschrijven."""
    with db.session() as conn:
        conn.execute(
            """UPDATE users SET portfolio_eur = ?, risk_percent = ?,
                      quiet_hours_start = ?, quiet_hours_end = ?
               WHERE id = ?""",
            (portfolio_eur, risk_percent, quiet_hours_start, quiet_hours_end, user_id),
        )


# ---------------------------------------------------------------------------
# Signalen: gedeelde technische toetsing, hetzelfde voor iedereen
# ---------------------------------------------------------------------------

def insert_signal(data: dict) -> int:
    fields = [
        "message_id", "coin", "direction", "category", "price", "rsi", "macd",
        "macd_signal", "volume_ratio", "ema9", "ema21", "atr", "atr_avg20", "adx",
        "technical_confirmed", "pass_pct", "hard_gates_ok", "confidence", "reason", "stop_loss", "take_profit",
        "context_note", "is_practice", "plain_explanation", "trade_type",
    ]
    values = [
        data.get("is_practice", 0) if f == "is_practice"
        else data.get("trade_type", "day_trading") if f == "trade_type"
        else data.get(f)
        for f in fields
    ]
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
    een handmatige oefening net een echt signaal voor alle gebruikers.
    LEFT JOIN naar messages: een autonoom, door de marktscan ontdekt
    signaal heeft geen message_id, zie app/market_scanner.py."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT s.*,
                      COALESCE(mcr.message_summary, m.message_summary, 'Zelf gedetecteerd door HesPulse')
                          AS message_summary
               FROM signals s
               LEFT JOIN messages m ON m.id = s.message_id
               LEFT JOIN message_coin_results mcr ON mcr.message_id = s.message_id AND mcr.coin = s.coin
               WHERE s.coin = ? AND s.is_practice = 0 ORDER BY s.created_at DESC LIMIT ?""",
            (coin.upper(), limit),
        ).fetchall()
        return [dict(r) for r in rows]


def coin_long_term_track_record(coin: str, current_price: float, min_age_days: int = 3) -> Optional[dict]:
    """Hoe vaak wees de richting van een lange-termijn analyse voor deze
    coin achteraf de juiste kant op, vergeleken met de huidige koers. Dit
    is de kern van waarom iemand voor een betaalde community betaalt: is de
    bron het geld waard, dat werd tot nu toe nergens gemeten.

    Alleen analyses van minstens min_age_days oud tellen mee: een analyse
    van een paar uur oud "gelijk geven" is toeval, geen trackrecord.
    Neutrale analyses tellen niet mee, die voorspellen geen kant.
    None als er nog geen enkele analyse oud genoeg is."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=min_age_days)).isoformat()
    with db.session() as conn:
        legacy_rows = conn.execute(
            """SELECT direction, price_at_receipt FROM messages
               WHERE coin = ? AND category = 'lange_termijn' AND direction IN ('long', 'short')
                     AND price_at_receipt IS NOT NULL AND received_at <= ?""",
            (coin.upper(), cutoff),
        ).fetchall()
        per_coin_rows = conn.execute(
            """SELECT mcr.direction AS direction, mcr.price_at_receipt AS price_at_receipt
               FROM message_coin_results mcr
               JOIN messages m ON m.id = mcr.message_id
               WHERE mcr.coin = ? AND mcr.category = 'lange_termijn' AND mcr.direction IN ('long', 'short')
                     AND mcr.price_at_receipt IS NOT NULL AND m.received_at <= ?""",
            (coin.upper(), cutoff),
        ).fetchall()
    rows = list(legacy_rows) + list(per_coin_rows)
    if not rows:
        return None
    correct = sum(
        1 for r in rows
        if (r["direction"] == "long" and current_price > r["price_at_receipt"])
        or (r["direction"] == "short" and current_price < r["price_at_receipt"])
    )
    return {"correct": correct, "total": len(rows)}


def recent_rejected_reasons(coin: str, limit: int = 3) -> list[str]:
    """Reason-teksten (de ✓/✗ per factor breakdown) van de laatste `limit`
    afgekeurde signalen voor deze coin, nieuwste eerst. Gebruikt om te
    zien of dezelfde factor er herhaaldelijk uitspringt, zie
    signal_processor._repeated_failing_factor."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT reason FROM signals
               WHERE coin = ? AND technical_confirmed = 0 AND is_practice = 0
               ORDER BY id DESC LIMIT ?""",
            (coin.upper(), limit),
        ).fetchall()
        return [r["reason"] for r in rows]


def find_open_signal(coin: str, direction: str) -> Optional[dict]:
    """Het meest recente DAY-TRADING signaal voor deze coin en richting,
    alleen als minstens één gebruiker die nog niet gesloten HEEFT EN niet
    genegeerd heeft. Een nieuw bericht over dezelfde coin en richting werkt
    dit signaal bij in plaats van er een los signaal naast te zetten.

    "Genegeerd" is zelf ook een definitieve beslissing, net als een
    gesloten trade, alleen zonder exit_price (die wordt bij negeren nooit
    gezet). Zonder de status-uitsluiting hieronder blijft een genegeerd
    signaal voor altijd "nog open" tellen, en werkt elk volgend bericht
    over dezelfde coin en richting tot in lengte van dagen datzelfde oude
    signaal bij in plaats van een vers signaal aan te maken, ook voor
    gebruikers die pas later worden toegevoegd.

    Aanvankelijk had deze functie precies één aanroeper
    (process_day_trading_signal() in signal_processor.py, voor day-trading's
    eigen update-in-plaats gedrag); sinds app/market_scanner.py hergebruikt
    de marktscanner hem ook, om was_open_before te bepalen (of een coin al
    een open signaal heeft, vóór de cooldown-check en de confirmation-
    precheck). De trade_type-filter hieronder is nodig sinds swing-signalen
    (run_swing_check(), via insert_signal()) ook een signals-rij voor
    dezelfde coin+richting kunnen aanmaken: zonder filter pikte deze query
    per ongeluk zo'n swing-rij op en liet een day-trading bericht hem
    (fout) bijwerken in plaats van zijn eigen signaal aan te maken. Swing
    hoeft hier zelf nooit doorheen: die maakt zijn eigen signaal altijd
    rechtstreeks aan via insert_signal(), nooit via deze functie."""
    with db.session() as conn:
        row = conn.execute(
            """SELECT * FROM signals WHERE coin = ? AND direction = ? AND trade_type = 'day_trading'
               ORDER BY created_at DESC LIMIT 1""",
            (coin.upper(), direction.lower()),
        ).fetchone()
        if not row:
            return None
        signal = dict(row)
        still_open = conn.execute(
            """SELECT COUNT(*) FROM journal_entries
               WHERE signal_id = ? AND exit_price IS NULL AND status != 'genegeerd'""",
            (signal["id"],),
        ).fetchone()[0]
        return signal if still_open > 0 else None


def update_signal(signal_id: int, data: dict) -> None:
    # message_id staat bewust NIET in deze lijst: een signaal houdt zijn
    # originele bron vast, ook bij een update.
    fields = [
        "price", "rsi", "macd", "macd_signal", "volume_ratio", "ema9", "ema21", "atr",
        "atr_avg20", "adx",
        "technical_confirmed", "pass_pct", "hard_gates_ok", "confidence", "reason", "stop_loss", "take_profit",
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
        je.entry_time AS entry_time, je.position_size AS position_size,
        je.exit_price AS exit_price, je.exit_time AS exit_time,
        je.result_eur AS result_eur, je.result_pct AS result_pct,
        je.note AS note,
        je.position_size_override AS position_size_override,
        je.evaluation_id AS evaluation_id,
        s.coin AS coin, s.direction AS direction, s.category AS category,
        s.trade_type AS trade_type,
        s.price AS price,
        s.message_id AS message_id,
        COALESCE(je.stop_loss_override, s.stop_loss) AS stop_loss,
        COALESCE(je.take_profit_override, s.take_profit) AS take_profit,
        s.stop_loss AS stop_loss_default, s.take_profit AS take_profit_default,
        s.confidence AS confidence, s.technical_confirmed AS technical_confirmed,
        s.rsi AS rsi, s.ema9 AS ema9, s.ema21 AS ema21,
        s.macd AS macd, s.macd_signal AS macd_signal, s.volume_ratio AS volume_ratio,
        s.atr_avg20 AS atr_avg20, s.adx AS adx,
        s.reason AS reason, s.context_note AS context_note, s.created_at AS created_at,
        s.is_practice AS is_practice, s.plain_explanation AS plain_explanation,
        COALESCE(mcr.message_summary, m.message_summary, 'Zelf gedetecteerd door HesPulse')
            AS message_summary
    FROM journal_entries je
    JOIN signals s ON s.id = je.signal_id
    LEFT JOIN messages m ON m.id = s.message_id
    LEFT JOIN message_coin_results mcr ON mcr.message_id = s.message_id AND mcr.coin = s.coin
"""


def list_recent_signals_for_user(user_id: int, limit: int = 1) -> list[dict]:
    """Meest recente ECHTE signalen (geen oefentrade-events) die deze
    gebruiker een logboekregel opleverden, nieuwste eerst. Gebruikt voor
    het laatste-seintje-bannertje op het dashboard (/api/system_status)."""
    with db.session() as conn:
        rows = conn.execute(
            _JOURNAL_SELECT + """
            WHERE je.user_id = ? AND s.is_practice = 0
            ORDER BY s.created_at DESC LIMIT ?""",
            (user_id, limit),
        ).fetchall()
        return [dict(r) for r in rows]


def create_journal_entry(
    signal_id: int, user_id: int, risk_eur: float,
    evaluation_id: Optional[int] = None, position_size: Optional[float] = None,
) -> int:
    """position_size is de daadwerkelijk gebruikte positiegrootte (na alle
    caps en, voor evaluatie-trades, de fee-aanpassing in
    risk.compute_position_size). Opgeslagen zodat close_journal_trade bij
    het sluiten precies dezelfde positiegrootte gebruikt voor de
    fee-verrekening, in plaats van een losse herberekening die uit de pas
    kan lopen met wat er werkelijk gesized is."""
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO journal_entries (signal_id, user_id, risk_eur, created_at, evaluation_id, position_size)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (signal_id, user_id, risk_eur, db.now_iso(), evaluation_id, position_size),
        )
        return cur.lastrowid


def mark_journal_telegram_sent(entry_id: int) -> None:
    with db.session() as conn:
        conn.execute("UPDATE journal_entries SET telegram_sent = 1 WHERE id = ?", (entry_id,))


def total_open_risk_eur(user_id: int) -> float:
    """Som van het risicobedrag van alle echt open trades (eigen entry al
    ingevuld, nog niet gesloten) van deze gebruiker. Zelfde definitie van
    "echt open" als de risicogauge op het dashboard: een nog niet genomen
    signaal heeft nog geen kapitaal gekost, een oefentrade telt nooit mee.
    Een aan een evaluatie gekoppelde trade telt hier evenmin mee, ook niet
    als het een echt signaal is: die is gesized tegen het virtuele
    evaluatiesaldo, niet tegen dit portfolio, en zou de portfolio-
    risicogauge met een heel ander schaalbedrag laten uitslaan (het eigen
    open risico van een run staat in total_open_risk_eur_for_evaluation)."""
    with db.session() as conn:
        row = conn.execute(
            """SELECT COALESCE(SUM(je.risk_eur), 0) AS total
               FROM journal_entries je
               JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.entry_price IS NOT NULL AND je.exit_price IS NULL
                     AND s.is_practice = 0 AND je.evaluation_id IS NULL""",
            (user_id,),
        ).fetchone()
        return row["total"]


def total_open_risk_eur_for_evaluation(evaluation_id: int) -> float:
    """Som van het risicobedrag van alle nog open oefentrades die aan deze
    evaluatie-run gekoppeld zijn. Zelfde 'echt open'-definitie als
    total_open_risk_eur, maar dan tegen evaluation_id in plaats van
    user_id: dit is precies het gecombineerde risico dat nog niet in
    current_balance verwerkt is (dat gebeurt pas op close, zie
    close_journal_trade)."""
    with db.session() as conn:
        row = conn.execute(
            """SELECT COALESCE(SUM(je.risk_eur), 0) AS total
               FROM journal_entries je
               WHERE je.evaluation_id = ? AND je.entry_price IS NOT NULL AND je.exit_price IS NULL""",
            (evaluation_id,),
        ).fetchone()
        return row["total"]


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
    """Zet entry_time altijd samen met entry_price: het moment waarop een
    trade daadwerkelijk genomen wordt, nodig om bij het sluiten de
    werkelijke hefboomkosten van een evaluatie-trade te berekenen (zie
    close_journal_trade). Geen aparte parameter: elke bestaande aanroeper
    die al entry_price meegeeft omdat de trade genomen wordt, krijgt dit
    gratis mee.

    Als deze regel aan een evaluatie gekoppeld is en nog geen position_size
    heeft (een signaal dat bij het versturen niet bevestigd was — dus geen
    positiegrootte kreeg — maar later toch genomen wordt), wordt die hier
    alsnog berekend tegen de WERKELIJKE entry_price. Zonder dit blijft
    position_size None, waardoor close_journal_trade's fee/hefboomkosten-
    berekening (notional_eur = position_size * entry_price) op nul uitkomt
    en een evaluatie-trade zo geen fees betaalt.

    Dashboard/repo bepalen "nog niet genomen" overal aan de hand van
    entry_price IS NULL, niet aan de hand van status (zie bijvoorbeeld
    list_pending_entries_with_price). Kiest een gebruiker "Genomen" of
    "Aangepast" zonder zelf een prijs in te vullen, dan zou de kaart
    zonder onderstaande fallback status='genomen' krijgen maar toch in de
    "nog niet genomen"-lijst blijven staan — voor de gebruiker onzichtbaar
    alsof de klik niks deed. Bij geen eigen prijs valt hij daarom terug op
    de signaalprijs zelf: "genomen zonder aanpassing" betekent immers
    "genomen tegen het gemelde niveau". Alleen 'genegeerd' mag entry_price
    leeg laten, dat is precies "geen trade"."""
    with db.session() as conn:
        if entry_price is None and status != "genegeerd":
            signal_row = conn.execute(
                """SELECT s.price AS price FROM journal_entries je
                   JOIN signals s ON s.id = je.signal_id
                   WHERE je.id = ? AND je.user_id = ?""",
                (entry_id, user_id),
            ).fetchone()
            if signal_row and signal_row["price"] is not None:
                entry_price = signal_row["price"]

        if entry_price is not None:
            row = conn.execute(
                """SELECT je.evaluation_id AS evaluation_id, je.risk_eur AS risk_eur,
                          je.position_size AS position_size,
                          COALESCE(je.stop_loss_override, s.stop_loss) AS stop_loss
                   FROM journal_entries je JOIN signals s ON s.id = je.signal_id
                   WHERE je.id = ? AND je.user_id = ?""",
                (entry_id, user_id),
            ).fetchone()
            if (
                row and row["position_size"] is None and row["evaluation_id"] is not None
                and row["stop_loss"] is not None
            ):
                cost_rate = risk.EVAL_TRADE_FEE_RATE + risk.EVAL_LEVERAGE_DAILY_RATE * risk.EVAL_SIZING_DAYS_ASSUMPTION
                position_size = risk.compute_position_size(
                    row["risk_eur"] or 0.0, entry_price, row["stop_loss"], cost_rate=cost_rate,
                )
                conn.execute(
                    """UPDATE journal_entries
                       SET status = ?, entry_price = ?, entry_time = ?, position_size = ?
                       WHERE id = ? AND user_id = ?""",
                    (status, entry_price, db.now_iso(), position_size, entry_id, user_id),
                )
            else:
                conn.execute(
                    """UPDATE journal_entries SET status = ?, entry_price = ?, entry_time = ?
                       WHERE id = ? AND user_id = ?""",
                    (status, entry_price, db.now_iso(), entry_id, user_id),
                )
        else:
            conn.execute(
                "UPDATE journal_entries SET status = ? WHERE id = ? AND user_id = ?",
                (status, entry_id, user_id),
            )


def auto_ignore_opposite_pending(coin: str, direction: str) -> list[dict]:
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

    Geeft een lijst met username/telegram_chat_id van elke geraakte
    logboekregel terug, zodat de aanroeper die gebruikers kan laten weten
    dat hun kans niet meer actueel is in plaats van dit stil te laten
    gebeuren.

    Alleen day_trading signalen: deze functie wordt alleen aangeroepen
    vanuit process_day_trading_signal, om zijn EIGEN nog niet genomen
    tegenovergestelde day-trading kans op te ruimen. Zonder deze filter
    zou een day-trading bericht ook een nog "wachtende" swing-melding voor
    dezelfde coin (tegenovergestelde richting) automatisch negeren, terwijl
    swing een eigen, veel langere tijdshorizon heeft en daar nooit door een
    losstaand day-trading signaal achterhaald van mag raken."""
    opposite = "short" if direction.lower() == "long" else "long"
    note = f"automatisch genegeerd: nieuwe {direction} melding voor {coin.upper()} maakt dit tegenovergestelde signaal achterhaald"
    with db.session() as conn:
        affected = conn.execute(
            """SELECT je.id AS id, u.username AS username, u.telegram_chat_id AS telegram_chat_id
               FROM journal_entries je
               JOIN signals s ON s.id = je.signal_id
               JOIN users u ON u.id = je.user_id
               WHERE je.entry_price IS NULL AND je.status != 'genegeerd'
                     AND s.coin = ? AND s.direction = ? AND s.is_practice = 0
                     AND s.trade_type = 'day_trading'""",
            (coin.upper(), opposite),
        ).fetchall()
        if affected:
            placeholders = ",".join("?" * len(affected))
            conn.execute(
                f"UPDATE journal_entries SET status = 'genegeerd', note = ? WHERE id IN ({placeholders})",
                (note, *[row["id"] for row in affected]),
            )
        return [dict(r) for r in affected]


def auto_ignore_stale_pending_for_coin(coin: str, exclude_signal_id: int) -> list[dict]:
    """Negeert automatisch elke nog niet bevestigde logboekregel voor deze
    coin die hoort bij een ánder signaal dan het signaal dat net is
    aangemaakt.

    auto_ignore_opposite_pending hierboven ruimt de tegenovergestelde
    richting op, maar dekt niet het geval waarin find_open_signal het vorige
    signaal voor dezelfde coin en richting niet meer als "open" genoeg
    beschouwde (bv. iedereen had die kans al afgesloten) en er dus een apart
    nieuw signaal is aangemaakt in plaats van een update. Zonder dit blijft
    zo'n oude, nog niet opgevolgde kans met verouderde koers/stop-loss/
    take-profit niveaus gewoon naast de nieuwe op het dashboard staan.

    Zelfde vorm als auto_ignore_opposite_pending, en om dezelfde reden
    beperkt tot day_trading signalen: dit wordt alleen aangeroepen vanuit
    process_day_trading_signal voor zijn eigen day-trading kansen, een nog
    "wachtende" swing-melding voor dezelfde coin heeft een eigen, veel
    langere tijdshorizon en mag daar nooit door achterhaald raken."""
    note = "automatisch genegeerd: nieuwere melding voor dezelfde coin maakt dit signaal achterhaald"
    with db.session() as conn:
        affected = conn.execute(
            """SELECT je.id AS id, u.username AS username, u.telegram_chat_id AS telegram_chat_id
               FROM journal_entries je
               JOIN signals s ON s.id = je.signal_id
               JOIN users u ON u.id = je.user_id
               WHERE je.entry_price IS NULL AND je.status != 'genegeerd'
                     AND s.coin = ? AND s.id != ? AND s.is_practice = 0
                     AND s.trade_type = 'day_trading'""",
            (coin.upper(), exclude_signal_id),
        ).fetchall()
        if affected:
            placeholders = ",".join("?" * len(affected))
            conn.execute(
                f"UPDATE journal_entries SET status = 'genegeerd', note = ? WHERE id IN ({placeholders})",
                (note, *[row["id"] for row in affected]),
            )
        return [dict(r) for r in affected]


def consecutive_ignored_count(user_id: int, coin: str) -> int:
    """Hoeveel meldingen voor deze coin de gebruiker op rij genegeerd heeft
    (handmatig of automatisch), meest recent eerst, tot de eerste die dat
    niet is. Basis voor de vermoeidheids-vraag ("wil je dit uitzetten?"),
    zie signal_processor.REPEATED_IGNORE_MUTE_THRESHOLD. Een genomen of
    aangepaste trade breekt de reeks altijd."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT je.status AS status FROM journal_entries je
               JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND s.coin = ? AND s.is_practice = 0
               ORDER BY je.id DESC""",
            (user_id, coin.upper()),
        ).fetchall()
    count = 0
    for row in rows:
        if row["status"] != "genegeerd":
            break
        count += 1
    return count


def is_coin_muted(user_id: int, coin: str) -> bool:
    with db.session() as conn:
        row = conn.execute(
            "SELECT 1 FROM muted_coins WHERE user_id = ? AND coin = ?", (user_id, coin.upper()),
        ).fetchone()
        return row is not None


def mute_coin(user_id: int, coin: str) -> None:
    with db.session() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO muted_coins (user_id, coin, created_at) VALUES (?, ?, ?)",
            (user_id, coin.upper(), db.now_iso()),
        )


def unmute_coin(user_id: int, coin: str) -> None:
    with db.session() as conn:
        conn.execute("DELETE FROM muted_coins WHERE user_id = ? AND coin = ?", (user_id, coin.upper()))


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


def close_journal_trade(entry_id: int, user_id: int, exit_price: float, exit_time: str) -> tuple[float, bool, Optional[int]]:
    """Sluit de trade af en geeft (result_eur, is_practice, evaluation_id)
    terug: is_practice bepaalt of dit voor de winst-confetti telt,
    evaluation_id (kan None zijn) vertelt de caller of dit resultaat nog op
    een lopende evaluatie-simulatie moet worden bijgeschreven."""
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

    # Fees en hefboomkosten van een Kraken Prop-achtig evaluatie-account
    # gelden alleen voor trades die aan een evaluatie hangen; een gewone
    # portfolio-trade kent dit systeem niet en result_eur blijft daar
    # ongewijzigd, exact het bestaande gedrag.
    if entry["evaluation_id"] is not None:
        notional_eur = (entry["position_size"] or 0.0) * entry_price
        trade_fee_eur = notional_eur * risk.EVAL_TRADE_FEE_RATE
        days_held = 0.0
        if entry["entry_time"]:
            # entry_time is altijd tz-aware (db.now_iso()), maar exit_time komt
            # in productie van een <input type="datetime-local"> formulierveld
            # (web/main.py) en is dan tz-naive; naive min aware crasht met een
            # TypeError. Beide naar naive normaliseren voordat we aftrekken
            # voorkomt dat, ongeacht welke van de twee een offset meedraagt.
            exit_dt = datetime.fromisoformat(exit_time)
            entry_dt = datetime.fromisoformat(entry["entry_time"])
            if exit_dt.tzinfo is not None:
                exit_dt = exit_dt.replace(tzinfo=None)
            if entry_dt.tzinfo is not None:
                entry_dt = entry_dt.replace(tzinfo=None)
            days_held = max(0.0, (exit_dt - entry_dt).total_seconds() / 86400)
        leverage_cost_eur = notional_eur * risk.EVAL_LEVERAGE_DAILY_RATE * days_held
        result_eur -= (trade_fee_eur + leverage_cost_eur)

    with db.session() as conn:
        conn.execute(
            """UPDATE journal_entries
               SET exit_price = ?, exit_time = ?, result_eur = ?, result_pct = ?
               WHERE id = ? AND user_id = ?""",
            (exit_price, exit_time, result_eur, result_pct, entry_id, user_id),
        )
        # Positiegrootte en risicobedrag schalen mee met het echte, actuele
        # kapitaal, niet met een vast bedrag dat nooit meebeweegt met winst
        # of verlies: zo blijft "risico X% per trade" ook X% betekenen na
        # een reeks winsten of verliezen, precies zoals professionele
        # risicomanagement dat toepast. Alleen echte trades tellen mee, een
        # oefentrade raakt nooit het echte portfoliobedrag.
        # Een aan een evaluatie gekoppelde trade telt hier ook nooit mee, ook
        # niet als het een echt signaal is (is_practice=0): zijn resultaat is
        # op evaluatieschaal berekend (tier_amount, inclusief prop-fees
        # hierboven) en wordt apart op het virtuele evaluatiesaldo
        # bijgeschreven via risk.evaluate_prop_progress/
        # update_evaluation_progress — ook op het echte portfolio optellen zou
        # dat evaluatiebedrag een tweede keer, op echt geld, toepassen.
        if not entry["is_practice"] and entry["evaluation_id"] is None:
            conn.execute(
                "UPDATE users SET portfolio_eur = portfolio_eur + ? WHERE id = ?",
                (result_eur, user_id),
            )
    return result_eur, bool(entry["is_practice"]), entry["evaluation_id"]


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


def update_journal_position_size(entry_id: int, user_id: int, position_size: Optional[float]) -> None:
    """Herberekende AUTO-positiegrootte (de kolom zelf, niet
    position_size_override) op een nog niet genomen regel, gebruikt als de
    effectieve stop loss van een evaluatie-gekoppelde regel verandert door
    een signaal-update: zonder dit blijft de opgeslagen grootte op de OUDE
    stop-afstand gebaseerd, waardoor de getoonde grootte en de nieuwe stop
    niet meer bij hetzelfde risicobedrag horen."""
    with db.session() as conn:
        conn.execute(
            "UPDATE journal_entries SET position_size = ? WHERE id = ? AND user_id = ?",
            (position_size, entry_id, user_id),
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
                      u.username AS username, u.telegram_chat_id AS telegram_chat_id,
                      u.quiet_hours_start AS quiet_hours_start, u.quiet_hours_end AS quiet_hours_end
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
                      s.atr AS atr, s.confidence AS confidence, s.created_at AS signal_created_at,
                      u.username AS username, u.telegram_chat_id AS telegram_chat_id,
                      u.quiet_hours_start AS quiet_hours_start, u.quiet_hours_end AS quiet_hours_end
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


def list_unresolved_signals_with_levels() -> list[dict]:
    """Signalen (van elke gebruiker samen, want stop_loss/take_profit zijn
    per signaal gedeeld) waarvan nog niet vastgesteld is of de take-profit
    of de stop-loss al geraakt is. Dit voedt het volledig automatische
    trackrecord, los van of een gebruiker het signaal ooit als "genomen"
    markeerde."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT id, coin, direction, stop_loss, take_profit, created_at
               FROM signals
               WHERE auto_outcome IS NULL
                 AND stop_loss IS NOT NULL
                 AND take_profit IS NOT NULL
                 AND is_practice = 0"""
        ).fetchall()
        return [dict(row) for row in rows]


def mark_signal_auto_outcome(signal_id: int, outcome: str, occurred_at: str) -> None:
    with db.session() as conn:
        conn.execute(
            "UPDATE signals SET auto_outcome = ?, auto_outcome_at = ? WHERE id = ?",
            (outcome, occurred_at, signal_id),
        )


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


def largest_open_position_volatility(user_id: int) -> Optional[float]:
    """Hoogste atr/atr_avg20-ratio onder de open (niet-oefen) posities van
    deze gebruiker: hoeveel heftiger de markt nu beweegt dan zijn eigen
    20-daags gemiddelde. Basis voor het logo dat sneller "ademt" bij hogere
    volatiliteit. None zonder open posities, of als ENABLE_ADVANCED_FACTORS
    uit staat en atr_avg20 dus nooit gevuld is."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT s.atr AS atr, s.atr_avg20 AS atr_avg20
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.entry_price IS NOT NULL AND je.exit_price IS NULL
                     AND s.is_practice = 0""",
            (user_id,),
        ).fetchall()
    ratios = [r["atr"] / r["atr_avg20"] for r in rows if r["atr"] and r["atr_avg20"]]
    return max(ratios) if ratios else None


def winrate_stats(user_id: int) -> dict:
    """Winrate en gemiddeld resultaat apart voor hoog en laag vertrouwen,
    op basis van gesloten trades van deze gebruiker. Winrate alleen zegt
    weinig over de verhouding tussen winst en verlies per trade, het
    gemiddelde resultaat erbij geeft een eerlijker beeld.

    Het percentage hoort bij het risicobedrag, niet bij de rauwe koersbeweging
    (dat is wat journal_entries.result_pct is: hoeveel de onderliggende prijs
    zelf bewoog, los van positiegrootte). Naast een risicogewogen euro-bedrag
    is die koers-% zinloos en zelfs misleidend: een trade die 30x het risico
    won kan een kleine koersbeweging hebben gehad met een kleine stop loss.
    Het percentage hier is dus result_eur t.o.v. het eigen risk_eur van die
    trade, zodat het altijd dezelfde verhouding toont als het eurobedrag
    ernaast."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT s.confidence AS confidence, je.result_eur AS result_eur,
                      je.risk_eur AS risk_eur
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL AND s.is_practice = 0
                     AND je.evaluation_id IS NULL AND s.trade_type = 'day_trading'""",
            (user_id,),
        ).fetchall()

    def stats_for(confidence: str) -> dict:
        subset = [r for r in rows if r["confidence"] == confidence]
        total = len(subset)
        wins = len([r for r in subset if r["result_eur"] is not None and r["result_eur"] > 0])
        winrate = (wins / total * 100) if total else 0.0
        eur_values = [r["result_eur"] for r in subset if r["result_eur"] is not None]
        pct_values = [
            r["result_eur"] / r["risk_eur"] * 100
            for r in subset if r["result_eur"] is not None and r["risk_eur"]
        ]
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


def swing_winrate_stats(user_id: int) -> dict:
    """Winrate en gemiddeld resultaat van gesloten swing-trades, apart van
    winrate_stats (day trading): andere tijdshorizon, ander risicoprofiel,
    en swing heeft geen hoog/laag vertrouwen-label om op te splitsen (geen
    vertrouwenscijfer zonder backtest op deze tijdshorizon, zie de spec)."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT je.result_eur AS result_eur, je.risk_eur AS risk_eur
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL
                     AND s.is_practice = 0 AND je.evaluation_id IS NULL AND s.trade_type = 'swing'""",
            (user_id,),
        ).fetchall()
    total = len(rows)
    wins = len([r for r in rows if r["result_eur"] is not None and r["result_eur"] > 0])
    winrate = (wins / total * 100) if total else 0.0
    eur_values = [r["result_eur"] for r in rows if r["result_eur"] is not None]
    pct_values = [
        r["result_eur"] / r["risk_eur"] * 100
        for r in rows if r["result_eur"] is not None and r["risk_eur"]
    ]
    avg_eur = sum(eur_values) / len(eur_values) if eur_values else 0.0
    avg_pct = sum(pct_values) / len(pct_values) if pct_values else 0.0
    return {
        "total": total, "wins": wins, "winrate": round(winrate, 1),
        "avg_result_eur": round(avg_eur, 2), "avg_result_pct": round(avg_pct, 1),
    }


def winrate_by_ratio(user_id: int) -> list[dict]:
    """Voor elke gesloten, echte trade: hoeveel van de getoonde factoren
    klopten (bv. "3/4"), en hoe vaak leidde dat tot winst. Losstaand van
    het hoog/laag vertrouwen label zelf, dit toetst of de score binnen
    een label ook echt iets voorspelt. Werkt met elk aantal factoren, dus
    ook ongewijzigd zodra de uitgebreide factoren ooit meetellen.

    Alleen day trading: een swing-reason heeft een heel andere vorm (twee
    tijdshorizons, geen gecombineerde toets), die zou deze
    kalibratietabel vervuilen met een ratio die niets met de 3-van-4-toets
    te maken heeft."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT s.reason AS reason, je.result_eur AS result_eur
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL AND s.is_practice = 0
                     AND je.evaluation_id IS NULL AND s.trade_type = 'day_trading'""",
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


def week_result_eur(user_id: int) -> Optional[float]:
    """Resultaat van echte gesloten trades in de laatste 7 dagen. None als
    er niets gesloten is deze week (niet hetzelfde als 0: 0 is exact
    quitte, None is 'geen data om iets over te zeggen'). Gebruikt om de
    ambient achtergrond een beetje mee te laten kleuren met hoe de week
    gaat, geen harde metric."""
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    with db.session() as conn:
        row = conn.execute(
            """SELECT SUM(je.result_eur) AS total, COUNT(*) AS n
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL AND s.is_practice = 0
                     AND je.evaluation_id IS NULL AND je.exit_time >= ?""",
            (user_id, week_ago),
        ).fetchone()
        return round(row["total"], 2) if row["n"] else None


def cumulative_result_series(user_id: int) -> list[dict]:
    with db.session() as conn:
        rows = conn.execute(
            """SELECT je.exit_time AS exit_time, je.result_eur AS result_eur
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL AND s.is_practice = 0
                     AND je.evaluation_id IS NULL
               ORDER BY je.exit_time ASC""",
            (user_id,),
        ).fetchall()
    series = []
    running = 0.0
    for row in rows:
        running += row["result_eur"] or 0.0
        series.append({"time": row["exit_time"], "cumulative_eur": round(running, 2)})
    return series


def daily_results(user_id: int, days: int = 126) -> dict:
    """Resultaat per dag (som van result_eur van echte, gesloten trades) van
    de laatste `days` dagen, als {"YYYY-MM-DD": bedrag}. Basis voor de
    trade-kalender heatmap op het dashboard: een dag zonder gesloten
    trades komt simpelweg niet in dit dict voor."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    with db.session() as conn:
        rows = conn.execute(
            """SELECT je.exit_time AS exit_time, je.result_eur AS result_eur
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL AND s.is_practice = 0
                     AND je.evaluation_id IS NULL AND je.exit_time >= ?""",
            (user_id, cutoff),
        ).fetchall()
    by_day: dict[str, float] = {}
    for row in rows:
        if not row["exit_time"]:
            continue
        day = row["exit_time"][:10]
        by_day[day] = by_day.get(day, 0.0) + (row["result_eur"] or 0.0)
    return by_day


def recent_autonomous_loss(coin: str, direction: str, hours: int) -> bool:
    """True als de laatst GESLOTEN journal-regel op een autonoom signaal
    (message_id IS NULL, zie app/market_scanner.py) voor deze coin+richting
    binnen `hours` uur geleden een verlies was. 'Gesloten' wordt hier,
    net als in period_stats, herkend aan exit_price IS NOT NULL (er is
    geen apart 'gesloten'-statusveld in dit schema). Gebruikt om de scan
    een afkoelperiode te geven na een verlies op dezelfde coin/richting,
    in plaats van elk uur opnieuw dezelfde whipsaw te melden.

    Bekende beperking: `cutoff` en `je.exit_time` worden hieronder als
    strings lexicografisch vergeleken (>=), geen echte datumvergelijking.
    Dat werkt correct zolang het ISO-timestampformaat consistent blijft
    (zoals db.now_iso() het altijd aanlevert), maar is gevoelig voor
    afwijkingen in tijdzone-suffix of precisie tussen de vergeleken
    waarden."""
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()
    with db.session() as conn:
        row = conn.execute(
            """SELECT je.result_eur AS result_eur
               FROM journal_entries je
               JOIN signals s ON s.id = je.signal_id
               WHERE s.coin = ? AND s.direction = ? AND s.message_id IS NULL
                     AND s.is_practice = 0 AND je.exit_price IS NOT NULL
                     AND je.exit_time >= ?
               ORDER BY je.exit_time DESC LIMIT 1""",
            (coin.upper(), direction.lower(), cutoff),
        ).fetchone()
    return bool(row and row["result_eur"] is not None and row["result_eur"] < 0)


def consecutive_autonomous_losses(coin: str, direction: str, limit: int = 3) -> int:
    """Hoeveel van de laatste `limit` GESLOTEN autonome journal-regels
    (message_id IS NULL) voor deze coin+richting op rij een verlies waren,
    nieuwste eerst geteld, stopt zodra een winst wordt tegengekomen (0 als
    de nieuwste al een winst is). Puur informatief — het signaal wordt
    hierdoor nooit onderdrukt, alleen gewaarschuwd (zie
    signal_processor's repeated_loss_note)."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT je.result_eur AS result_eur
               FROM journal_entries je
               JOIN signals s ON s.id = je.signal_id
               WHERE s.coin = ? AND s.direction = ? AND s.message_id IS NULL
                     AND s.is_practice = 0 AND je.exit_price IS NOT NULL
               ORDER BY je.exit_time DESC LIMIT ?""",
            (coin.upper(), direction.lower(), limit),
        ).fetchall()
    count = 0
    for row in rows:
        if row["result_eur"] is not None and row["result_eur"] < 0:
            count += 1
        else:
            break
    return count


def period_stats(user_id: int, since_iso: str) -> dict:
    """Samenvatting van deze gebruiker zijn activiteit sinds `since_iso`,
    voor de wekelijkse/maandelijkse Telegram samenvatting. Signalen = elke
    logboekregel aangemaakt in de periode (ongeacht vertrouwen), trades =
    alleen de rijen die ook echt gesloten zijn in de periode. exit_time
    komt uit een browser datetime-local veld (geen tijdzone), een simpele
    string-vergelijking is hier goed genoeg voor een week/maand-venster,
    dezelfde aanpak als recent_activity op de coinpagina gebruikt.

    hoog_count telt alleen day trading: technical_confirmed betekent voor
    een swing-signaal "het bewaakte niveau is bevestigd", niet "hoog
    vertrouwen". De andere tellingen (signalen, gesloten, resultaat)
    blijven bewust over beide trade_types gaan."""
    with db.session() as conn:
        signals_row = conn.execute(
            """SELECT COUNT(*) AS n,
                      SUM(CASE WHEN s.technical_confirmed AND s.trade_type = 'day_trading' THEN 1 ELSE 0 END) AS hoog
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.created_at >= ? AND s.is_practice = 0""",
            (user_id, since_iso),
        ).fetchone()
        closed = conn.execute(
            """SELECT je.result_eur AS result_eur, s.coin AS coin
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_time >= ? AND je.exit_price IS NOT NULL
                     AND s.is_practice = 0 AND je.evaluation_id IS NULL""",
            (user_id, since_iso),
        ).fetchall()

    wins = sum(1 for r in closed if r["result_eur"] is not None and r["result_eur"] > 0)
    total_result = sum(r["result_eur"] or 0 for r in closed)
    with_result = [dict(r) for r in closed if r["result_eur"] is not None]
    best = max(with_result, key=lambda r: r["result_eur"], default=None)
    worst = min(with_result, key=lambda r: r["result_eur"], default=None)
    return {
        "signal_count": signals_row["n"] or 0,
        "hoog_count": signals_row["hoog"] or 0,
        "closed_count": len(closed),
        "wins": wins,
        "total_result_eur": total_result,
        "best": best,
        "worst": worst if worst != best else None,
    }


def period_stats_auto_scan(user_id: int, since_iso: str) -> dict:
    """Zelfde vorm als period_stats hierboven, maar alleen voor autonome,
    door de marktscan ontdekte signalen (message_id IS NULL). Gebruikt
    voor de extra regel in de wekelijkse samenvatting (niet de
    maandelijkse) — zie de spec, sectie 2."""
    with db.session() as conn:
        signals_row = conn.execute(
            """SELECT COUNT(*) AS n
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.created_at >= ? AND s.is_practice = 0
                     AND s.message_id IS NULL""",
            (user_id, since_iso),
        ).fetchone()
        closed = conn.execute(
            """SELECT je.result_eur AS result_eur
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_time >= ? AND je.exit_price IS NOT NULL
                     AND s.is_practice = 0 AND je.evaluation_id IS NULL AND s.message_id IS NULL""",
            (user_id, since_iso),
        ).fetchall()
    wins = sum(1 for r in closed if r["result_eur"] is not None and r["result_eur"] > 0)
    return {
        "signal_count": signals_row["n"] or 0,
        "closed_count": len(closed),
        "wins": wins,
        "winrate_pct": (wins / len(closed) * 100) if closed else None,
    }


def coin_stats(user_id: int) -> list[dict]:
    """Winrate en gemiddeld resultaat per coin, op basis van gesloten trades
    van deze gebruiker. Laat zien welke coin het goed doet met dit systeem,
    en welke niet."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT s.coin AS coin, je.result_eur AS result_eur
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.user_id = ? AND je.exit_price IS NOT NULL AND s.is_practice = 0
                     AND je.evaluation_id IS NULL""",
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


# ---------------------------------------------------------------------------
# Kraken Prop-achtige evaluatie simulatie
# ---------------------------------------------------------------------------

def create_evaluation(
    user_id: int, tier_amount: float, profit_target_pct: float, max_drawdown_pct: float,
) -> int:
    """Nieuwe evaluatie-run, status 'actief', saldo begint op tier_amount.
    De aanroeper (web/main.py) controleert dat de gebruiker nog geen
    actieve run heeft — dezelfde verantwoordelijkheidsverdeling als
    evaluate_narrative's 'hoogstens één actief narrative per coin'."""
    now = db.now_iso()
    today_label = risk.trading_day_label(datetime.now(timezone.utc))
    with db.session() as conn:
        cur = conn.execute(
            """INSERT INTO prop_evaluations
               (user_id, tier_amount, profit_target_pct, max_drawdown_pct,
                current_balance, day_start_balance, day_start_date, started_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (user_id, tier_amount, profit_target_pct, max_drawdown_pct,
             tier_amount, tier_amount, today_label, now),
        )
        return cur.lastrowid


def get_active_evaluation(user_id: int) -> Optional[dict]:
    with db.session() as conn:
        row = conn.execute(
            "SELECT * FROM prop_evaluations WHERE user_id = ? AND status = 'actief' ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def get_evaluation(evaluation_id: int) -> Optional[dict]:
    with db.session() as conn:
        row = conn.execute("SELECT * FROM prop_evaluations WHERE id = ?", (evaluation_id,)).fetchone()
        return dict(row) if row else None


def list_evaluations_for_user(user_id: int) -> list[dict]:
    """Geschiedenis voor het dashboard, nieuwste eerst."""
    with db.session() as conn:
        rows = conn.execute(
            "SELECT * FROM prop_evaluations WHERE user_id = ? ORDER BY started_at DESC",
            (user_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def update_evaluation_state(
    evaluation_id: int, current_balance: float, day_start_balance: float, day_start_date: str,
) -> None:
    with db.session() as conn:
        conn.execute(
            """UPDATE prop_evaluations
               SET current_balance = ?, day_start_balance = ?, day_start_date = ?
               WHERE id = ?""",
            (current_balance, day_start_balance, day_start_date, evaluation_id),
        )


def set_evaluation_danger_alert_sent(evaluation_id: int, sent: bool) -> None:
    """Eenmalig-vuur-vlag voor de Telegram-waarschuwing bij de 85%-drempel
    (zie web/main.py's close-route). Ook gebruikt om terug te zetten naar
    False zodra het percentage weer onder de drempel zakt, zodat een
    latere nieuwe overschrijding in dezelfde run opnieuw gemeld wordt."""
    with db.session() as conn:
        conn.execute(
            "UPDATE prop_evaluations SET danger_alert_sent = ? WHERE id = ?",
            (int(sent), evaluation_id),
        )


def close_evaluation(evaluation_id: int, status: str, closed_reason: str) -> None:
    with db.session() as conn:
        conn.execute(
            "UPDATE prop_evaluations SET status = ?, closed_reason = ?, ended_at = ? WHERE id = ?",
            (status, closed_reason, db.now_iso(), evaluation_id),
        )


def list_evaluation_daily_results(evaluation_id: int) -> list[dict]:
    """Netto resultaat per handelsdag voor deze run, oudste eerst. Voedt de
    dag-stippen op het dashboard. Groepeert met risk.trading_day_label,
    gebaseerd op hetzelfde ingevulde exit_time-veld als de saldo-berekening
    gebruikte op het moment van sluiten."""
    with db.session() as conn:
        rows = conn.execute(
            """SELECT exit_time, result_eur FROM journal_entries
               WHERE evaluation_id = ? AND exit_price IS NOT NULL
               ORDER BY exit_time""",
            (evaluation_id,),
        ).fetchall()
    daily: dict[str, float] = {}
    for row in rows:
        try:
            label = risk.trading_day_label(datetime.fromisoformat(row["exit_time"]))
        except (ValueError, TypeError):
            # Een niet-ISO exit_time (bv. handmatig ingevoerd op een browser
            # zonder datetime-local-ondersteuning) mag de hele heatmap en
            # daarmee het dashboard niet laten crashen — die ene dag
            # ontbreekt dan gewoon in de stippen.
            continue
        daily[label] = daily.get(label, 0.0) + (row["result_eur"] or 0.0)
    return [{"date": date, "value": value} for date, value in sorted(daily.items())]


def list_evaluation_balance_curve(evaluation_id: int) -> list[dict]:
    """Cumulatieve saldo-lijn voor de grafiek op de evaluatie-pagina: één
    punt bij de start (tier_amount, started_at) en daarna één punt per
    gesloten, aan deze run gekoppelde trade, oplopend saldo. Anders dan
    list_evaluation_daily_results (dat per handelsdag optelt voor de
    dag-stippen) geeft dit de exacte volgorde van individuele trades
    terug, voor een vloeiende lijn in plaats van een dagoverzicht."""
    evaluation = get_evaluation(evaluation_id)
    if not evaluation:
        return []
    with db.session() as conn:
        rows = conn.execute(
            """SELECT exit_time, result_eur FROM journal_entries
               WHERE evaluation_id = ? AND exit_price IS NOT NULL
               ORDER BY exit_time""",
            (evaluation_id,),
        ).fetchall()
    curve = [{"time": evaluation["started_at"], "balance": evaluation["tier_amount"]}]
    running = evaluation["tier_amount"]
    for row in rows:
        try:
            datetime.fromisoformat(row["exit_time"])
        except (ValueError, TypeError):
            # Zelfde beschermende patroon als list_evaluation_daily_results:
            # een niet-ISO exit_time mag de grafiek niet laten crashen of
            # een onbruikbaar punt opleveren, die ene sluiting ontbreekt
            # dan gewoon in de lijn.
            continue
        running += (row["result_eur"] or 0.0)
        curve.append({"time": row["exit_time"], "balance": running})
    return curve


def list_evaluation_trade_context(evaluation_id: int) -> list[dict]:
    """Elke aan deze run gekoppelde, DAADWERKELIJK GENOMEN trade (open of
    gesloten) met de context die het disciplineprofiel op de
    evaluatiepagina nodig heeft: welk volgnummer die trade was op zijn
    handelsdag (op basis van created_at), hoeveel procent van het
    toenmalige saldo het risico was, en het vertrouwen-niveau van het
    signaal. Sluit een nog niet genomen (entry_price NULL) of genegeerde
    kans uit: sinds echte, aan een evaluatie gekoppelde signalen ontstaat
    een logboekregel al bij de MELDING, niet bij het nemen (anders dan een
    oefentrade, die altijd meteen genomen wordt) — zonder dit filter telde
    elke ontvangen melding mee als "trade vandaag", ook een die nooit
    genomen is. Puur feiten, geen oordeel: het disciplineprofiel trekt daar
    zelf patronen uit in plaats van dat hier al een vaste regel ingebakken
    zit.

    Saldo-op-dat-moment is tier_amount plus het resultaat van elke trade
    die vóór dit created_at al gesloten was (exit_time < created_at,
    beide ISO-strings, dus lexicografisch vergelijkbaar) — dezelfde
    chronologie als list_evaluation_balance_curve, maar hier per
    open-moment in plaats van per sluit-moment, omdat risico bepaald
    wordt bij het openen, niet bij het sluiten."""
    evaluation = get_evaluation(evaluation_id)
    if not evaluation:
        return []
    with db.session() as conn:
        rows = [dict(row) for row in conn.execute(
            """SELECT je.id AS id, je.created_at AS created_at, je.exit_time AS exit_time,
                      je.risk_eur AS risk_eur, je.result_eur AS result_eur,
                      s.coin AS coin, s.direction AS direction, s.confidence AS confidence
               FROM journal_entries je JOIN signals s ON s.id = je.signal_id
               WHERE je.evaluation_id = ? AND je.entry_price IS NOT NULL
                     AND (je.status != 'genegeerd' OR je.exit_price IS NOT NULL)
               ORDER BY je.created_at""",
            (evaluation_id,),
        )]

    day_counts: dict[str, int] = {}
    trades = []
    for row in rows:
        created_at = row["created_at"]
        if row["risk_eur"] is None:
            continue
        balance_at_entry = evaluation["tier_amount"] + sum(
            (r["result_eur"] or 0.0) for r in rows
            if r["exit_time"] and r["exit_time"] < created_at
        )
        try:
            day_label = risk.trading_day_label(datetime.fromisoformat(created_at))
        except (ValueError, TypeError):
            # Zelfde beschermende patroon als list_evaluation_daily_results:
            # een niet-ISO created_at mag deze trade niet laten crashen,
            # hij telt dan gewoon niet mee voor het dag-volgnummer.
            day_label = None
        trade_number_in_day = None
        if day_label is not None:
            day_counts[day_label] = day_counts.get(day_label, 0) + 1
            trade_number_in_day = day_counts[day_label]
        trades.append({
            "id": row["id"],
            "coin": row["coin"],
            "direction": row["direction"],
            "confidence": row["confidence"],
            "result_eur": row["result_eur"],
            "trade_number_in_day": trade_number_in_day,
            "risk_percent_used": (row["risk_eur"] / balance_at_entry * 100) if balance_at_entry else None,
        })
    return trades


# ---------------------------------------------------------------------------
# Per-gebruiker bevestigde status en winrate
# ---------------------------------------------------------------------------

def user_confirmed(pass_pct: float, hard_gates_ok: bool, threshold_pct: float) -> bool:
    """Of een signaal voor DEZE gebruiker als bevestigd geldt: de twee
    harde eisen (al verwerkt in hard_gates_ok) blijven voor iedereen hard,
    alleen het percentage van de gepoolde factoren wordt per gebruiker
    tegen zijn eigen drempel gelegd."""
    return hard_gates_ok and pass_pct >= threshold_pct


def winrate_for_user(user_id: int) -> dict:
    """Winrate puur op basis van het automatische trackrecord: van de
    signalen die voor DEZE gebruiker (zijn eigen drempel) bevestigd waren
    en waarvan de uitkomst al vaststaat, hoeveel raakten take-profit."""
    with db.session() as conn:
        user_row = conn.execute(
            "SELECT confirm_threshold_pct FROM users WHERE id = ?", (user_id,)
        ).fetchone()
        if not user_row:
            raise ValueError(f"Onbekende gebruiker: {user_id}")
        threshold = user_row["confirm_threshold_pct"]
        rows = conn.execute(
            """SELECT pass_pct, hard_gates_ok, auto_outcome
               FROM signals
               WHERE is_practice = 0 AND pass_pct IS NOT NULL"""
        ).fetchall()

    total = wins = losses = open_count = 0
    for row in rows:
        if not user_confirmed(row["pass_pct"], bool(row["hard_gates_ok"]), threshold):
            continue
        total += 1
        if row["auto_outcome"] == "take_profit":
            wins += 1
        elif row["auto_outcome"] == "stop_loss":
            losses += 1
        else:
            open_count += 1

    resolved = wins + losses
    winrate_pct = (wins / resolved * 100) if resolved else None
    return {"total": total, "wins": wins, "losses": losses, "open": open_count, "winrate_pct": winrate_pct}
