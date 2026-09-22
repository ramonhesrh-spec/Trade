-- Schema voor het crypto alertsysteem.

-- Gebruikers van het dashboard. Geen open registratie, accounts worden
-- toegevoegd via scripts/create_user.py. Iedereen ziet dezelfde signalen,
-- maar houdt zijn eigen logboek bij met een eigen portfolio en risico.
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL UNIQUE,
    password_hash TEXT NOT NULL,
    portfolio_eur REAL NOT NULL DEFAULT 0,
    risk_percent REAL NOT NULL DEFAULT 1.0,
    -- Restant van de Telegram-bot (verwijderd in Taak 11): niet meer
    -- ingevuld voor nieuwe gebruikers en niet meer gebruikt om meldingen
    -- te routeren (dat loopt nu via push_subscriptions), kolom blijft
    -- staan voor bestaande rijen, geen migratie om hem te verwijderen.
    telegram_chat_id TEXT,
    created_at TEXT NOT NULL,
    -- Stille uren, bijvoorbeeld "23:00" / "07:00": in dat venster komt ook
    -- een bevestigde kans stil binnen. Beide leeg (NULL) = geen stille
    -- uren, altijd geluid bij een bevestigde kans (het bestaande gedrag).
    quiet_hours_start TEXT,
    quiet_hours_end TEXT,
    -- Drempel (percentage) waarboven de gepoolde factoren voor DEZE
    -- gebruiker als "bevestigd" tellen. De twee harde eisen (Uitgerektheid,
    -- BTC-trend) blijven voor iedereen hard, dit percentage geldt alleen
    -- voor de rest. Standaard 60.0, gelijk aan de oude globale
    -- CONFIRM_THRESHOLD, zodat een bestaande gebruiker zonder wijziging
    -- exact hetzelfde gedrag ziet als voorheen.
    confirm_threshold_pct REAL NOT NULL DEFAULT 60.0,
    -- NULL totdat de gebruiker bewust op één van de drie drempel-knoppen
    -- klikt (Task 5). Los van confirm_threshold_pct zelf nodig, want de
    -- default (60.0) is numeriek gelijk aan de "Normaal"-stand, dus de
    -- waarde alleen kan "nog niet gekozen" niet van "bewust Normaal
    -- gekozen" onderscheiden. Voedt de onboarding-checklist (Task 9).
    confirm_threshold_set_at TEXT
);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    received_at TEXT NOT NULL,
    raw_text TEXT NOT NULL,
    has_image INTEGER NOT NULL DEFAULT 0,
    image_paths TEXT,
    coin TEXT,
    direction TEXT,
    category TEXT,
    unclear INTEGER NOT NULL DEFAULT 0,
    note TEXT,
    processed_at TEXT,
    discord_user_id TEXT,
    -- Het origineel doorgestuurde bericht herschreven in klare taal (zie
    -- explain.summarize_message), los van plain_explanation op signals dat
    -- de berekende technische factoren uitlegt, niet de inhoud van het
    -- bericht zelf. NULL zolang de samenvatting nog niet gegenereerd is of
    -- mislukt is, de rauwe tekst blijft dan het enige alternatief.
    message_summary TEXT,
    -- Live koers op het moment van verwerken, alleen ingevuld voor lange
    -- termijn analyses (zie signal_processor). Basis voor het trackrecord:
    -- kwam de koers achteraf de kant op die de analyse voorspelde.
    price_at_receipt REAL,
    -- Welk lopend verhaal (coin_narratives) dit bericht opvolgt of start.
    -- NULL voor berichten zonder duidelijke lange-termijn richting, en
    -- voor alle berichten van vóór deze feature (geen backfill).
    narrative_id INTEGER REFERENCES coin_narratives(id)
);

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
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id),
    coin TEXT NOT NULL,
    price_level REAL NOT NULL,
    pattern_name TEXT,
    source_label TEXT NOT NULL DEFAULT 'analyse Discord',
    created_at TEXT NOT NULL,
    -- Eén gezamenlijk oordeel, niet per gebruiker: bij een klein groepje
    -- gebruikers is een niveau dat er echt naast zit voor iedereen fout,
    -- en is per-gebruiker bijhouden onnodige complexiteit. Wie het eerst
    -- "klopt niet" klikt, verbergt het niveau voor iedereen uit de
    -- grafiek; het blijft wel in de lijst staan, doorgestreept, zodat de
    -- geschiedenis niet verdwijnt.
    dismissed INTEGER NOT NULL DEFAULT 0
);

-- Zelf getekende schuine lijnen op de coin-grafiek (wig, driehoek, kanaal,
-- trendlijn), die de automatische toetsing niet kan naberekenen. Gedeeld
-- tussen gebruikers, net als source_levels: iedereen kijkt naar dezelfde
-- grafiek van dezelfde coin.
CREATE TABLE IF NOT EXISTS trendlines (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin TEXT NOT NULL,
    user_id INTEGER NOT NULL REFERENCES users(id),
    label TEXT,
    x1 INTEGER NOT NULL,
    y1 REAL NOT NULL,
    x2 INTEGER NOT NULL,
    y2 REAL NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_trendlines_coin ON trendlines(coin);

-- Coins die genoemd zijn in verwerkte berichten, geeft een eigen
-- grafiekpagina in het dashboard.
CREATE TABLE IF NOT EXISTS coins (
    symbol TEXT PRIMARY KEY,
    market TEXT NOT NULL,
    added_at TEXT NOT NULL,
    active INTEGER NOT NULL DEFAULT 1,
    -- Eigen aantekening bij een coin, los van een specifieke trade
    -- (bijvoorbeeld een unlock-datum of een aankomend nieuwsmoment).
    -- Gedeeld tussen gebruikers, net als de rest van de coin-gegevens.
    note TEXT,
    -- Whiplash-rem voor de autonome marktscan (app/market_scanner.py): de
    -- richting van de laatst geziene scan-cyclus, en hoeveel cycli achter
    -- elkaar dezelfde richting al aanhoudt. Voorkomt dat een wispelturige
    -- EMA9/EMA21-kruising binnen een paar cycli eerst een long en dan een
    -- short meldt voor dezelfde coin.
    last_scan_direction TEXT,
    last_scan_direction_count INTEGER NOT NULL DEFAULT 0,
    -- Dedup voor de uitbraak-dan-terugtest-melding (app/market_scanner.py):
    -- "richting:zone_low:zone_high" van de laatst gemelde zone voor deze
    -- coin. Voorkomt dat dezelfde zone elk uur opnieuw een melding stuurt
    -- zolang de terugtest geldig blijft.
    last_breakout_retest_key TEXT,
    -- Dedup voor de trendlijn-uitbraak-dan-terugtest-melding
    -- (app/market_scanner.py): "richting:soort:lijnwaarde" van de laatst
    -- gemelde trendlijn voor deze coin. Zelfde soort dedup als
    -- last_breakout_retest_key hierboven, nu voor een diagonale lijn.
    last_trendline_retest_key TEXT
);

-- Coins waarvoor een gebruiker zelf geen Telegram-meldingen meer wil,
-- meestal nadat hij dezelfde coin herhaaldelijk genegeerd heeft (zie
-- signal_processor.REPEATED_IGNORE_MUTE_THRESHOLD). De logboekregel en
-- dashboard-cijfers blijven gewoon bestaan, alleen de Telegram-melding
-- wordt overgeslagen.
CREATE TABLE IF NOT EXISTS muted_coins (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    coin TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(user_id, coin)
);

-- Verwerkte day trading signalen: gedeelde technische toetsing. Objectief,
-- hetzelfde voor iedereen die het dashboard gebruikt.
CREATE TABLE IF NOT EXISTS signals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER REFERENCES messages(id),
    coin TEXT NOT NULL,
    direction TEXT NOT NULL,
    category TEXT NOT NULL,
    price REAL,
    rsi REAL,
    macd REAL,
    macd_signal REAL,
    volume_ratio REAL,
    ema9 REAL,
    ema21 REAL,
    atr REAL,
    atr_avg20 REAL,
    adx REAL,
    technical_confirmed INTEGER NOT NULL DEFAULT 0,
    confidence TEXT NOT NULL,
    reason TEXT,
    stop_loss REAL,
    take_profit REAL,
    context_note TEXT,
    is_practice INTEGER NOT NULL DEFAULT 0,
    -- 'day_trading' of 'swing': welk mechanisme dit signaal produceerde.
    -- Swing-signalen komen uit een bewaakt bron-niveau (zie swing_watches),
    -- hebben geen hoog/laag vertrouwen-label (nog niet gevalideerd op deze
    -- tijdshorizon) en worden apart geteld in winrate/journaal.
    trade_type TEXT NOT NULL DEFAULT 'day_trading',
    plain_explanation TEXT,
    -- Kaal percentage gepoolde factoren dat raak was (bv. 68.0 voor 11 van
    -- 16), los van welke drempel een individuele gebruiker instelt. Elke
    -- gebruiker vergelijkt dit percentage zelf tegen zijn eigen
    -- confirm_threshold_pct, zodat de technische berekening en de
    -- AI-uitleg maar één keer per signaal hoeven te draaien.
    pass_pct REAL,
    -- Of de twee harde eisen (Uitgerektheid, BTC-trend) allebei klopten,
    -- los van pass_pct. Nodig omdat "technical_confirmed" al het EINDRESULTAAT
    -- op de globale drempel is; om een ANDERE (per-gebruiker) drempel tegen
    -- pass_pct te leggen moet los vaststaan of de harde eisen al dan niet
    -- geslaagd waren, ongeacht welke drempel je gebruikt.
    hard_gates_ok INTEGER NOT NULL DEFAULT 1,
    -- Automatisch, op prijsdata gebaseerd trackrecord: is de take-profit
    -- of de stop-loss van DIT signaal geraakt, ongeacht of een gebruiker
    -- het ooit als "genomen" markeerde. NULL zolang nog geen van beide
    -- geraakt is.
    auto_outcome TEXT,
    auto_outcome_at TEXT,
    -- Dichtstbijzijnde zelf-gedetecteerde steun/weerstand-zonerand aan de
    -- stop-kant van de prijs op het moment van dit signaal (los prijsgetal,
    -- niet de hele zone) — NULL als er geen bruikbare zone dichtbij was.
    -- Gebruikt om terug te koppelen naar sr_zone_failures zodra dit signaal
    -- als stop_loss resolvt, zie app/level_check.py check_signal_outcomes.
    nearest_sr_zone_price REAL,
    -- Realistische, iets betere entry-zone dan de live prijs, gebaseerd op
    -- de dichtstbijzijnde zelf-gedetecteerde steun/weerstand-zone tussen de
    -- entry en de stop loss — PUUR informatief, telt nergens mee in
    -- sizing/journaal/trackrecord (product owner: live prijs blijft de
    -- echte entry). Beide NULL als er geen bruikbare zone was.
    suggested_entry_low REAL,
    suggested_entry_high REAL,
    created_at TEXT NOT NULL
);

-- Eigen trade logboek per gebruiker en per signaal: eigen risicobedrag
-- (op basis van eigen portfolio), eigen status, eigen entry/exit en
-- notitie, en of de melding naar deze gebruiker is verstuurd (kolomnaam
-- telegram_sent uit de tijd van de Telegram-bot, blijft ongewijzigd
-- staan sinds de overstap naar pushmeldingen, zie Taak 11).
CREATE TABLE IF NOT EXISTS journal_entries (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    signal_id INTEGER NOT NULL REFERENCES signals(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    risk_eur REAL,
    telegram_sent INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'nieuw',
    entry_price REAL,
    entry_time TEXT,
    exit_price REAL,
    exit_time TEXT,
    result_eur REAL,
    result_pct REAL,
    note TEXT,
    level_alert_sent INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    stop_loss_override REAL,
    take_profit_override REAL,
    position_size_override REAL,
    position_size REAL,
    evaluation_id INTEGER REFERENCES prop_evaluations(id),
    -- Deze gebruiker heeft dit signaal weggeklikt op /signalen ("niet
    -- interessant"), NULL = niet weggeklikt. Puur een per-gebruiker
    -- weergavefilter, raakt nooit signals zelf: de gedeelde trackrecord en
    -- ieders eigen winrate (repo.winrate_for_user) lezen rechtstreeks uit
    -- signals, niet uit journal_entries, dus dit heeft daar geen invloed op.
    dismissed_at TEXT,
    UNIQUE (signal_id, user_id)
);

-- Eén rij per (browser × apparaat)-abonnement op Web Push. Eén gebruiker
-- kan meerdere rijen hebben (telefoon + PC). endpoint is uniek: een nieuw
-- abonnement van hetzelfde apparaat overschrijft de bestaande rij i.p.v.
-- een duplicaat aan te maken.
CREATE TABLE IF NOT EXISTS push_subscriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    endpoint TEXT NOT NULL,
    p256dh TEXT NOT NULL,
    auth TEXT NOT NULL,
    device_label TEXT,
    created_at TEXT NOT NULL,
    UNIQUE (endpoint)
);
CREATE INDEX IF NOT EXISTS idx_push_subscriptions_user ON push_subscriptions(user_id);

-- Rustige, niet-tijdkritische meldingen die NIET pushen: vervallen
-- pending signalen, lange-termijn-verhaal-updates, weekoverzichten,
-- systeemgezondheid. user_id is NULL voor admin-only rijen
-- (systeemgezondheid, herhaalde API-fouten) — zie
-- docs/superpowers/specs/2026-09-15-push-meldingen-design.md.
CREATE TABLE IF NOT EXISTS notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER REFERENCES users(id),
    type TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL,
    url TEXT,
    is_read INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_notifications_user ON notifications(user_id, is_read);

-- Bewaakt een bron-niveau (support/resistance uit een screenshot) totdat
-- de prijs er weer dichtbij komt. Ongeacht of het onderliggende bericht
-- day_trading of lange_termijn was: elk bericht met een niveau krijgt een
-- watch. Geen migratie nodig, dit is een gloednieuwe tabel.
CREATE TABLE IF NOT EXISTS swing_watches (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id INTEGER NOT NULL REFERENCES messages(id),
    source_level_id INTEGER NOT NULL REFERENCES source_levels(id),
    coin TEXT NOT NULL,
    direction TEXT NOT NULL,
    -- wachtend/bevestigd/vervallen/ongeldig, zie de spec.
    status TEXT NOT NULL DEFAULT 'wachtend',
    created_at TEXT NOT NULL,
    checked_at TEXT
);
CREATE INDEX IF NOT EXISTS idx_swing_watches_status ON swing_watches(status);
CREATE INDEX IF NOT EXISTS idx_swing_watches_coin ON swing_watches(coin);

-- Eén rij per doorlopend "verhaal" over een coin: een reeks lange-termijn
-- berichten met dezelfde richting die bij elkaar horen. Zie
-- docs/superpowers/specs/2026-09-07-coin-narratives-design.md.
CREATE TABLE IF NOT EXISTS coin_narratives (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    coin TEXT NOT NULL,
    direction TEXT NOT NULL,
    -- actief/tegengesproken/verlopen, zie de spec.
    status TEXT NOT NULL DEFAULT 'actief',
    message_count INTEGER NOT NULL DEFAULT 1,
    opened_at TEXT NOT NULL,
    last_update_at TEXT NOT NULL,
    closed_reason TEXT
);
CREATE INDEX IF NOT EXISTS idx_coin_narratives_coin_status ON coin_narratives(coin, status);

-- Welk Telegram-bericht-ID bij welk narrative hoort voor welke gebruiker:
-- nodig om een update te kunnen bewerken (bot.edit_message_text) in
-- plaats van een nieuwe melding te sturen. Eén regel per narrative+
-- gebruiker, bijgewerkt bij elke nieuwe melding voor dat narrative.
CREATE TABLE IF NOT EXISTS narrative_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    narrative_id INTEGER NOT NULL REFERENCES coin_narratives(id),
    user_id INTEGER NOT NULL REFERENCES users(id),
    telegram_message_id INTEGER NOT NULL,
    sent_at TEXT NOT NULL,
    UNIQUE(narrative_id, user_id)
);

-- Eén virtuele Kraken Prop-achtige evaluatie: een gebruiker test zijn
-- eigen discipline en HesPulse's signalen tegen dezelfde dagverlies-,
-- drawdown- en winstdoel-regels als een echte evaluatie, zonder geld uit
-- te geven. Zie de spec voor de volledige regels. Hoogstens één rij per
-- gebruiker met status 'actief' (bewaakt door de webroute, niet door een
-- database-constraint, zelfde patroon als coin_narratives).
CREATE TABLE IF NOT EXISTS prop_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    tier_amount REAL NOT NULL,
    profit_target_pct REAL NOT NULL,
    max_daily_loss_pct REAL NOT NULL DEFAULT 3.0,
    max_drawdown_pct REAL NOT NULL,
    current_balance REAL NOT NULL,
    day_start_balance REAL NOT NULL,
    day_start_date TEXT NOT NULL,
    -- actief/geslaagd/mislukt/gestopt, zie de spec.
    status TEXT NOT NULL DEFAULT 'actief',
    closed_reason TEXT,
    started_at TEXT NOT NULL,
    ended_at TEXT,
    -- Eenmalig-vuur-vlag voor de Telegram-waarschuwing zodra dagverlies of
    -- drawdown de 85%-drempel passeert: zonder dit zou elke volgende
    -- trade-close op een run die al boven de drempel zit opnieuw een
    -- melding sturen. Reset naar 0 zodra het weer onder de drempel zakt,
    -- zodat een nieuwe overschrijding later in dezelfde run wel weer
    -- gemeld wordt.
    danger_alert_sent INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_prop_evaluations_user_status ON prop_evaluations(user_id, status);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

-- Voor het beperken van het aantal inlogpogingen, per gebruikersnaam.
CREATE TABLE IF NOT EXISTS login_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT NOT NULL,
    attempted_at TEXT NOT NULL,
    success INTEGER NOT NULL,
    ip_address TEXT
);

-- Voor het beperken van het aantal registraties per IP, tegen geautomatiseerde spam.
CREATE TABLE IF NOT EXISTS registration_attempts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    attempted_at TEXT NOT NULL,
    ip_address TEXT NOT NULL
);

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

-- Indexen op kolommen waar steeds op gefilterd of gesorteerd wordt. Zonder
-- deze doorzoekt SQLite bij elke dashboard- of coinpagina de volledige
-- tabel, dat wordt merkbaar trager naarmate er meer berichten en trades
-- bijkomen.
CREATE INDEX IF NOT EXISTS idx_messages_coin ON messages(coin);
CREATE INDEX IF NOT EXISTS idx_messages_coin_category ON messages(coin, category);
CREATE INDEX IF NOT EXISTS idx_source_levels_coin ON source_levels(coin);
CREATE INDEX IF NOT EXISTS idx_signals_coin ON signals(coin);
CREATE INDEX IF NOT EXISTS idx_signals_coin_direction ON signals(coin, direction);
CREATE INDEX IF NOT EXISTS idx_signals_message_id ON signals(message_id);
CREATE INDEX IF NOT EXISTS idx_journal_user_id ON journal_entries(user_id);
CREATE INDEX IF NOT EXISTS idx_journal_signal_id ON journal_entries(signal_id);
CREATE INDEX IF NOT EXISTS idx_journal_open ON journal_entries(entry_price, exit_price);
CREATE INDEX IF NOT EXISTS idx_login_attempts_username_time ON login_attempts(username, attempted_at);
CREATE INDEX IF NOT EXISTS idx_registration_attempts_ip_time ON registration_attempts(ip_address, attempted_at);
