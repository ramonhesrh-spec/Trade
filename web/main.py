"""FastAPI webdashboard. Meerdere gebruikers mogelijk, elk met een eigen
login, eigen portfolio en eigen logboek. Iedereen ziet dezelfde signalen.
Open registratie op /registreer. Draai met:
uvicorn web.main:app --host 0.0.0.0 --port 8000
"""
import asyncio
import csv
import hashlib
import io
import json
import logging
import math
import re
import sys
import time
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from starlette.middleware.gzip import GZipMiddleware
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app import advice as advice_module
from app import patterns as chart_patterns
from app import config, db, exchange, indicators, market_calendar, notifications_view, push_notify, push_policy, price_alerts, radar, repo, risk, security, setup_chart, today, track_record
from app.replay import rangesweep_lab, stopquality
from app import gallery_job
from app import ceo, chance_checks, focus, freshness, chance_steps, kans_view, ladder, logbook, market_context, nu, trade_replay, week_review, beheer, rule_live, trust, zone_radar, zone_sweep
from app import chain as chain_mod
from app.market_scanner import floor_stop, smc_stop_take_margins
from web import splash

logger = logging.getLogger("web")

BASE_DIR = Path(__file__).resolve().parent
def ceo_user() -> Optional[dict]:
    """De enige CEO: CEO_USERNAME, anders de eerst aangemaakte gebruiker. Alle anderen zijn leerlingen."""
    return repo.get_ceo_user()


_ceo_cache: dict = {"at": 0.0, "id": None}


def is_ceo(user: Optional[dict]) -> bool:
    """Is deze gebruiker de CEO? Een minuut onthouden: base.html vraagt het bij elke pagina."""
    if not user:
        return False
    if time.monotonic() - _ceo_cache["at"] > 60:
        found = ceo_user()
        _ceo_cache.update(at=time.monotonic(), id=found["id"] if found else None)
    return user["id"] == _ceo_cache["id"]


def report_rows(user: Optional[dict]) -> list[dict]:
    """Signalen voor de cijfers op Bewijs, Vandaag, Week en de CEO-pagina. De proefmotor (app/rule_live.py) is alleen voor de CEO: leerlingen
    zien zijn trades niet, ook niet in de totalen."""
    return rule_live.for_viewer(repo.list_signals_for_quality_report(None), is_ceo(user))


def _cookie_user(request: Request) -> Optional[dict]:
    token = request.cookies.get(SESSION_COOKIE)
    user_id = security.verify_session_token(token) if token else None
    return repo.get_user(user_id) if user_id else None


def _range_sweep_open_count(user: Optional[dict], prices: dict, now: datetime) -> int:
    """Hetzelfde filter als _range_sweep_cards, maar met alleen de koerscache: het menu doet geen beursaanroep per pagina."""
    if not user or not _range_sweep_shown(user):
        return 0
    return sum(1 for s in repo.list_range_sweep_setups(("waiting", "niet_gemeld")) if today.range_sweep_state(s, prices.get(s["coin"]), now) in today.OPEN_RANGE_STATES)


def _nav_context(request: Request) -> dict:
    """De coinlijst in het menu staat in elke pagina. Zonder dit moest elke route `coins` zelf meegeven, en de nieuwere
    pagina's (Vandaag, Setups, Bewijs) deden dat niet: het menu klapte open met een lege lijst."""
    # Alleen de koersen uit de cache: het menu mag geen Binance-aanroep per paginaweergave doen. Zonder koers telt een setup mee.
    cached = {coin: hit[1] for coin, hit in _price_cache.items() if hit[1]}
    forming = _forming_setups(_cookie_user(request))
    radar_count = radar.waiting_count(forming, cached)
    now = datetime.now(timezone.utc)
    setups = sum(1 for r in repo.list_structure_setups(("waiting",), 50)
                 if today.structure_state(r, json.loads(r["plan"]), cached.get(r["coin"]), now) in today.OPEN_PLAN_STATES)
    # De range sweep hoort bij Setups (de melding en de kans wijzen naar /structuur), net als in today.open_chances.
    setups += _range_sweep_open_count(_cookie_user(request), cached, now)
    # Het getal op Plannen in het dok: wat nu in de zone staat, zoals het appicoon (radar.in_zone_count). De twee tellers van vroeger
    # staan op de wisselaar Radar | Setups binnen Plannen.
    return {"coins": repo.list_coins(), "nav_counts": {"setups": setups, "radar": radar_count, "in_zone": radar.in_zone_count(forming, cached)}}


templates = Jinja2Templates(directory=str(BASE_DIR / "templates"), context_processors=[_nav_context])
templates.env.globals["disclaimer"] = config.DISCLAIMER
templates.env.globals["splash_screens"] = splash.SCREENS
def asset(path: str) -> str:
    """URL van een statisch bestand met zijn wijzigingstijd erachter, zodat de browser het onthoudt tot het bestand verandert."""
    try:
        version = int((BASE_DIR / "static" / path).stat().st_mtime)
    except OSError:
        version = 0
    return f"/static/{path}?v={version}"


# Eén keer bij het starten gelezen: een coin zonder bestand krijgt meteen zijn letters, zonder een 404-verzoek per rij.
COIN_LOGOS = frozenset(p.stem for p in (BASE_DIR / "static" / "coins").glob("*.svg"))
# Gemeten op een contactblad tegen #0a0e0f: bij deze logo's is meer dan 40% van het beeld te donker voor de donkere chip
# (zwarte of marineblauwe cirkels). Zij krijgen een licht rond plaatje erachter.
DARK_COIN_LOGOS = frozenset({"ada", "apt", "atom", "hbar", "wld", "xlm", "xrp"})


def coin_logo(coin: str | None) -> dict | None:
    sym = (coin or "").strip().lower()
    if sym not in COIN_LOGOS:
        return None
    return {"src": asset(f"coins/{sym}.svg"), "dark": sym in DARK_COIN_LOGOS}


_proof_cache = {"at": 0.0, "map": {}, "labs": {}, "rows": []}
# Proeven die om de stopkwaliteit draaien: hun strenge toets op een voordeel mag Negatief niet veroorzaken (track_record.rule_status, stop_lab=).
STOP_LAB_KEYS = {"range_sweep": "range_sweep_stop", "zone_sweep": "zone_sweep_stop"}
# De labrijen van de zone-sweep die bij de live motor horen: op Bewijs onder de motor, niet als "regel zonder live motor".
ZONE_SWEEP_LAB_KEYS = ("zone_sweep_stop", "zs_1h", "zs_2h", "zs_4h")


def proof(trade_type: str) -> dict:
    """Bewijsstatus van een soort kans (app/trust.py), een minuut onthouden: elke kaart vraagt erom."""
    if time.monotonic() - _proof_cache["at"] > 60:
        rows = repo.list_signals_for_quality_report(None)
        entries = track_record.summarize(rows, config.TRACK_RECORD_COST_PCT)
        by_type = {}
        for e in entries:
            if e["source"] != "alles":
                prev = by_type.get(e["trade_type"])
                if prev is None or e["resolved"] > prev["resolved"]:
                    by_type[e["trade_type"]] = e
        _proof_cache.update(at=time.monotonic(), map=by_type, labs={lab["rule"]: lab for lab in repo.list_rule_labs()}, rows=rows)
    labs = _proof_cache["labs"]
    if trade_type in rule_live.CEO_ONLY_TYPES or trade_type in labs:
        # Eén betekenis van Bewezen: voor een regel met een labtoets dezelfde status als op Bewijs (labtoets, 50 live trades, bewaking).
        # De range sweep draait om de stopkwaliteit: zijn strenge toets op een voordeel mag Negatief niet veroorzaken (track_record.rule_status).
        stop_lab = labs.get(STOP_LAB_KEYS[trade_type]) if trade_type in STOP_LAB_KEYS else None
        return track_record.rule_proof(labs.get(trade_type), track_record.live_net_r(_proof_cache["rows"], trade_type, config.TRACK_RECORD_COST_PCT), stop_lab=stop_lab)
    return trust.status(_proof_cache["map"].get(trade_type))


templates.env.globals["proof"] = proof
templates.env.globals["focus"] = focus
templates.env.globals["asset"] = asset
templates.env.globals["coin_logo"] = coin_logo
templates.env.filters["grade_word"] = lambda g: {"A": "Sterk", "B": "Redelijk", "C": "Zwak"}.get(g, "Geen oordeel")
def _nl_price(v: float) -> str:
    """Zelfde notatie als de live koers in coin.html (toLocaleString nl-NL): punt voor duizendtallen, komma voor decimalen."""
    return f"{v:.4f}" .replace(".", ",") if v < 100 else f"{v:,.2f}".replace(",", "\0").replace(".", ",").replace("\0", ".")


templates.env.filters["nl_price"] = _nl_price
templates.env.filters["outcome_word"] = lambda o: kans_view.OUTCOME_TEXT.get(o, "Open")
templates.env.globals["fmt_price"] = today.fmt_price
templates.env.globals["is_ceo"] = lambda user: is_ceo(user)
templates.env.globals["live_exchange"] = config.EXCHANGE_ID
templates.env.globals["live_quote"] = config.QUOTE_CURRENCY.lower()
templates.env.globals["pause_minutes_left"] = lambda u: push_policy.pause_minutes_left((u or {}).get("push_paused_until"), datetime.now(timezone.utc))
templates.env.globals["pause_text"] = push_policy.pause_text
templates.env.globals["stale_after_s"] = freshness.STALE_AFTER_S

# Thema per toestel: de cookie laat de server meteen het juiste data-theme en de juiste achtergrond schrijven, zodat er geen flits van
# donker naar licht is. Zonder keuze blijft het donker, zoals voor de lichte versie bestond. theme.js houdt cookie en localStorage gelijk.
THEME_COOKIE = "hp_theme"
THEMES = ("system", "dark", "light")
THEME_BG = {"dark": "#0a0e0f", "light": "#f4f6f6"}


def theme_of(request: Optional[Request]) -> str:
    value = request.cookies.get(THEME_COOKIE) if request is not None else None
    return value if value in THEMES else "dark"


templates.env.globals["theme_of"] = theme_of
templates.env.globals["theme_bg"] = THEME_BG


def _age_label(iso: str | None) -> str:
    """Leesbare "3 uur geleden"-tekst voor een db.now_iso()-tijdstip.
    Zelfde drempels als base.html's JS-timeAgo() voor de systeemstatus,
    hier server-side omdat een signaalkaart niet live hoeft bij te werken
    zoals die statuspopover dat wel doet."""
    if not iso:
        return "-"
    then = datetime.fromisoformat(iso)
    minutes = (datetime.now(timezone.utc) - then).total_seconds() / 60
    if minutes < 1:
        return "net nu"
    if minutes < 60:
        return f"{round(minutes)} min geleden"
    hours = minutes / 60
    if hours < 24:
        return f"{round(hours)} uur geleden"
    return f"{round(hours / 24)} dagen geleden"


templates.env.filters["age"] = _age_label

class CachedStatic(StaticFiles):
    """Statische bestanden krijgen een lange cache: de pagina verwijst met ?v=<wijzigingstijd> (zie asset()), dus een nieuw bestand krijgt een nieuwe
    URL en een oud blijft veilig onthouden. Zonder dit haalde elke paginawissel style.css (140 KB) opnieuw op."""
    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            # Alleen met ?v= is de URL gegarandeerd nieuw bij een wijziging; een kale URL (icoon, manifest) blijft kort in de cache.
            versioned = b"v=" in scope.get("query_string", b"")
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable" if versioned else "public, max-age=3600"
        return response


app = FastAPI(title="HesPulse")
app.add_middleware(GZipMiddleware, minimum_size=1024)
app.mount("/static", CachedStatic(directory=str(BASE_DIR / "static")), name="static")


@app.get("/service-worker.js")
async def service_worker():
    """Zelfde bestand als /static/service-worker.js, maar dan op de root
    geserveerd: een service worker kan alleen pagina's binnen zijn eigen
    pad beheren (tenzij de server een Service-Worker-Allowed-header stuurt,
    wat hier niet gebeurt), dus vanaf /static/ zou hij nooit /dashboard
    kunnen bedienen. navigator.serviceWorker.ready op /dashboard bleef
    daardoor voor altijd hangen, precies de oorzaak van de kapotte
    pushmelding-knop. Zie base.html voor de registratie."""
    # no-cache: een gewijzigde service worker moet bij het volgende openen van de app opgepikt worden, anders blijft een oude versie hangen.
    return FileResponse(
        str(BASE_DIR / "static" / "service-worker.js"), media_type="application/javascript", headers={"Cache-Control": "no-cache"},
    )

SESSION_COOKIE = "session"
SERVER_STARTED_AT = db.now_iso()


@app.on_event("startup")
def on_startup():
    db.init_db()


@app.exception_handler(401)
async def redirect_to_login(request: Request, exc: HTTPException):
    return RedirectResponse(url="/login", status_code=303)


def require_login(request: Request) -> dict:
    token = request.cookies.get(SESSION_COOKIE)
    user_id = security.verify_session_token(token) if token else None
    user = repo.get_user(user_id) if user_id else None
    if not user:
        raise HTTPException(status_code=401)
    # Alleen paginaweergaven tellen: de koers- en kansenpolls van een open tab zouden elke gebruiker de hele dag "actief" maken.
    if request.method == "GET" and not request.url.path.startswith(("/api", "/static", "/ws")):
        try:
            repo.record_visit(user["id"], datetime.now(timezone.utc))
        except Exception:
            pass
    return user


# ---------------------------------------------------------------------------
# Openbare landingspagina
# ---------------------------------------------------------------------------

@app.get("/")
async def landing(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    user_id = security.verify_session_token(token) if token else None
    if user_id and repo.get_user(user_id):
        return RedirectResponse(url="/ceo", status_code=303)

    now = datetime.now(timezone.utc)
    scripts = repo.latest_scripts()
    return templates.TemplateResponse(request, "landing.html", {
        "timeline": Markup(today.timeline_svg(now, today.agenda(market_calendar.upcoming(now, 24)))), "mood": today.mood(scripts),
        "n_scripts": len(scripts), "now": today.nl_stamp(today.local(now)), "demo_chart": Markup(setup_chart.demo_svg()),
        "kraken_referral_url": config.KRAKEN_REFERRAL_URL,
        "kraken_referral_code": config.KRAKEN_REFERRAL_CODE,
    })


@app.get("/keten")
async def keten_page(request: Request):
    """Openbaar, zonder login: de ketting moet voor iedereen narekenbaar zijn."""
    rows = repo.list_chain(100000)
    ok, bad = chain_mod.verify(rows)
    recent = []
    for r in reversed(rows[-100:]):
        body = json.loads(r["payload"])
        recent.append({**r, "created_at": body["created_at"], "coin": body["coin"], "direction": body["direction"], "trade_type": body["trade_type"]})
    return templates.TemplateResponse(request, "keten.html", {
        "ok": ok, "bad": bad, "total": len(rows), "recent": recent, "first_id": rows[0]["signal_id"] if rows else None,
        "base_url": config.DASHBOARD_URL.rstrip("/"),
    })


@app.get("/keten.json")
async def keten_json():
    return JSONResponse(repo.list_chain(100000))


# Vaste, kleine lijst voor de tickerstrook op de landingspagina: geen login
# nodig (dit is de openbare pagina), dus bewust geen koppeling met een
# account of met welke coins een gebruiker daadwerkelijk volgt.
PUBLIC_TICKER_COINS = ["BTC", "ETH", "SOL"]


@app.get("/api/public_prices")
async def api_public_prices():
    """Publieke, ongeauthenticeerde live koersen voor de tickerstrook op de
    landingspagina. Puur decoratief geplaatst, maar wel echte data, geen
    voorbeeldcijfers: zie CLAUDE.md, nooit verzonnen getallen tonen."""
    prices = {}
    for coin in PUBLIC_TICKER_COINS:
        try:
            prices[coin] = await asyncio.to_thread(exchange.fetch_last_price, coin)
        except Exception:
            prices[coin] = None
    return prices


@app.get("/zone-radar")
async def zone_radar_uitleg(request: Request, user: dict = Depends(require_login)):
    """Uitleg voor gebruikers bij de kaarten 'Zone-radar' op /smc."""
    return templates.TemplateResponse(request, "zones_uitleg.html", {"user": user, "coins": repo.list_coins()})


@app.get("/uitleg")
async def uitleg(request: Request, user: dict = Depends(require_login)):
    """Dezelfde uitleg als de openbare landingspagina (hoe het werkt,
    meldingen aanzetten, hoog vertrouwen), maar bereikbaar voor wie al is
    ingelogd. De landingspagina zelf stuurt ingelogde gebruikers meteen
    door naar het dashboard, dus zonder deze pagina was die uitleg
    onbereikbaar na het inloggen."""
    return templates.TemplateResponse(request, "uitleg.html", {
        "user": user,
        "coins": repo.list_coins(),
        "kraken_referral_url": config.KRAKEN_REFERRAL_URL,
        "kraken_referral_code": config.KRAKEN_REFERRAL_CODE,
        "advanced_factors_enabled": config.ENABLE_ADVANCED_FACTORS,
    })


@app.get("/meldingen")
async def meldingen_page(request: Request, user: dict = Depends(require_login)):
    """Rustige meldingen: geen push, alleen zichtbaar op deze pagina.
    De admin-sectie (user_id IS NULL, systeemgezondheid/API-fouten) is
    alleen zichtbaar voor het eigen operator-account, zelfde
    ADMIN_USERNAME-check als de onherkende-berichten-sectie op het
    dashboard."""
    is_admin = bool(config.ADMIN_USERNAME) and user["username"] == config.ADMIN_USERNAME
    return templates.TemplateResponse(request, "meldingen.html", {
        "user": user,
        "coins": repo.list_coins(),
        "notification_groups": notifications_view.group_notifications(repo.list_notifications(user["id"])),
        "admin_groups": notifications_view.group_notifications(repo.list_admin_notifications()) if is_admin else None,
        # Los van de getoonde lijst (die stopt bij limit=50): de "alles
        # gelezen"-knop moet ook verschijnen als de ongelezen achterstand
        # verder terugligt dan wat hier zichtbaar is.
        "unread_count": repo.count_unread_notifications(user["id"]),
    })


@app.post("/meldingen/{notification_id}/gelezen")
async def mark_melding_gelezen(notification_id: int, user: dict = Depends(require_login)):
    repo.mark_notification_read(notification_id, user["id"])
    return {"ok": True}


@app.post("/meldingen/alles-gelezen")
async def mark_all_meldingen_gelezen(user: dict = Depends(require_login)):
    repo.mark_all_notifications_read(user["id"])
    return RedirectResponse(url="/meldingen", status_code=303)


LOGBOOK_DAYS = logbook.DAYS_SHOWN


def _logbook_inputs(user: dict, since: str) -> dict:
    """Wat app/logbook.py van deze ene gebruiker leest: zijn overgeslagen plannen, zijn checklists en zijn genomen journaalregels (alle drie
    gefilterd op zijn user_id), met de gedeelde plannen en signalen erachter. Een proefsoort die hij niet mag zien valt weg (rule_live.for_viewer)."""
    skips = repo.list_plan_skips(user["id"], since)
    runs = repo.list_checklist_runs(user["id"], since)
    taken = [e for e in repo.list_journal(user["id"]) if not e["is_practice"] and e["status"] in logbook.TAKEN_STATUSES]
    plans = repo.plans_for_keys([r["plan_key"] for r in skips + runs])
    ids = [p["signal_id"] for p in plans.values()] + [e["signal_id"] for e in taken]
    signals = {s["id"]: s for s in rule_live.for_viewer(list(repo.signals_by_ids(ids).values()), is_ceo(user))}
    return {"skips": skips, "runs": runs, "plans": plans, "signals": signals, "taken": taken}


def _logbook_days(user: dict, now: datetime) -> list[dict]:
    since = (now - timedelta(days=LOGBOOK_DAYS + 1)).isoformat()
    return logbook.timeline(**_logbook_inputs(user, since), seen=repo.list_plan_moments(since, include_zone_sweep=_sees_zone_sweep(user)), now=now, tz=today.LOCAL_TZ)


def _week_review(user: dict, now: datetime) -> dict:
    """De weekterugblik van deze ene gebruiker (app/week_review.py) over de laatste acht weken."""
    d = _logbook_inputs(user, (now - timedelta(weeks=week_review.WEEKS, days=1)).isoformat())
    return week_review.review(logbook.closed_trades(d["runs"], d["plans"], d["signals"], d["taken"]),
                              logbook.skip_outcomes(d["skips"], d["runs"], d["plans"], d["signals"]), now, today.LOCAL_TZ)


REPLAY_CACHE_MAX = 64
_replay_candles: dict[tuple[str, str, int, int], list] = {}


async def _closed_candles(coin: str, tf: str, start: datetime, count: int) -> Optional[list]:
    """Candles van een afgesloten venster. Die veranderen nooit meer, dus ze blijven bewaard (de oudste vallen eraf na REPLAY_CACHE_MAX)."""
    key = (coin, tf, int(start.timestamp()), count)
    if key not in _replay_candles:
        try:
            df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, tf, count, int(start.timestamp() * 1000))
        except Exception:
            logger.exception("Replay-candles voor %s niet opgehaald", coin)
            return None
        rows = [[int(r.timestamp.timestamp()), float(r.open), float(r.high), float(r.low), float(r.close)] for r in df.itertuples()]
        if not rows:
            return None
        while len(_replay_candles) >= REPLAY_CACHE_MAX:
            _replay_candles.pop(next(iter(_replay_candles)))
        _replay_candles[key] = rows
    return _replay_candles[key]


@app.get("/logboek/replay/{signal_id}")
async def logboek_replay(request: Request, signal_id: int, user: dict = Depends(require_login)):
    """Replay van een afgeronde trade (app/trade_replay.py): candles van een uur voor de vulling tot de uitkomst, de niveaus en elk moment
    met zijn echte tijd. De checklist is die van deze gebruiker; de rest is het gedeelde signaal."""
    rows = repo.signals_by_ids([signal_id])
    signal = rows.get(signal_id)
    if (not signal or signal["auto_outcome"] not in trade_replay.OUTCOME_LABEL or not signal["auto_outcome_at"]
            or not rule_live.for_viewer([signal], is_ceo(user))):
        raise HTTPException(status_code=404)
    plan = repo.plan_for_signal(signal_id)
    run = repo.get_checklist_run(user["id"], plan["key"]) if plan else None
    start, end, tf = trade_replay.window(signal["created_at"], signal["auto_outcome_at"])
    candles = await _closed_candles(signal["coin"], tf, start, trade_replay.candle_count(start, end, tf))
    view = trade_replay.build(candles or [], signal, trade_replay.moments(signal, plan, run), tf, today.LOCAL_TZ)
    day = logbook.short_date(logbook._parse(signal["auto_outcome_at"]).astimezone(today.LOCAL_TZ).date()).lower()
    return templates.TemplateResponse(request, "replay.html", {"user": user, "signal": signal, "view": view, "day": day,
                                                                "svg": Markup(view["svg"]) if view else None})


@app.get("/signalen")
async def signalen_page(request: Request, alles: bool = False, weergave: str = "", user: dict = Depends(require_login)):
    """Kale, puur signalen-pagina (geen journaal/portfolio-content, zie
    CLAUDE.md 'pure signals'-uitgangspunt van deze taak): dezelfde
    gedeelde signalen als het dashboard, hier chronologisch, nieuwste
    eerst — dit is de live feed van wat er nu gebeurt, geen ranglijst.
    Percentage/kansberekening blijft zichtbaar als badge op de kaart
    (signal_card), stuurt alleen de volgorde niet meer aan. Eerder
    sorteerde deze pagina op hoogste slagingspercentage; dat had een
    reëel nadeel dat chronologisch niet heeft (een nog niet gevalideerd
    swing-signaal had geen sorteersleutel en moest apart afgevangen
    worden) en verborg bovendien net binnengekomen signalen onder oudere,
    toevallig hoger scorende signalen — precies tegengesteld aan "wat is
    er nu".

    Standaard alleen nog open signalen (auto_outcome IS NULL): het hele
    punt van deze pagina is "wat is er nu", en een allang afgeronde kans
    hoort niet tussen een net binnengekomen signaal te staan. Afgeronde
    signalen (win/verlies/vervallen) blijven bereikbaar via ?alles=1,
    daar gewoon tussen de rest op created_at — chronologisch heeft geen
    aparte open/resolved-scheiding nodig zoals de oude percentage-sortering
    die wel had (die moest voorkomen dat een oud, toevallig hoog percentage
    een vers signaal overstemde; dat risico bestaat niet meer zodra tijd
    zelf de sorteersleutel is).

    Sinds fase 2 is de standaard de dagtijdlijn (app/logbook.py); de signalenlijst staat onder ?weergave=open en ?alles=1."""
    if not alles and weergave != "open":
        return templates.TemplateResponse(request, "signalen.html", {"user": user, "view": "dag", "days": _logbook_days(user, datetime.now(timezone.utc))})
    entries = repo.list_signalen_for_user(user["id"])
    if not alles:
        entries = [e for e in entries if e["auto_outcome"] is None]
    winrate = repo.winrate_stats(user["id"])
    pattern_winrate = repo.pattern_winrate_stats()
    entries = _add_signal_context(entries, winrate, pattern_winrate)
    required_factors = repo.list_required_factors(user["id"])
    _apply_user_confirmed(entries, user["confirm_threshold_pct"], required_factors)
    entries.sort(key=lambda e: e["created_at"], reverse=True)
    return templates.TemplateResponse(request, "signalen.html", {
        "user": user, "view": "alle" if alles else "open",
        "coins": repo.list_coins(),
        "entries": entries,
        "showing_all": alles,
    })


PRICE_TTL_SECONDS = 10
_price_cache: dict[str, tuple[float, Optional[float]]] = {}
_price_fetched_at: dict[str, float] = {}       # wandklok (time.time) van de laatste geslaagde ophaal per coin, zie app/freshness.py


async def _cached_prices(coins) -> dict[str, Optional[float]]:
    """Live koersen met een korte cache: elke ingelogde gebruiker die de radar open heeft ververst elke paar seconden,
    en dat mag niet voor elke gebruiker en elke kaart een eigen Binance-aanroep worden."""
    now = time.monotonic()
    prices: dict[str, Optional[float]] = {}
    stale = []
    for coin in set(coins):
        hit = _price_cache.get(coin)
        if hit and now - hit[0] < PRICE_TTL_SECONDS:
            prices[coin] = hit[1]
        else:
            stale.append(coin)

    async def fetch(coin: str) -> Optional[float]:
        try:
            return await asyncio.to_thread(exchange.fetch_last_price, coin)
        except Exception:
            return None

    for coin, price in zip(stale, await asyncio.gather(*[fetch(c) for c in stale])):
        if price is not None:
            _price_fetched_at[coin] = time.time()
        # Een mislukte ophaal (None) vervangt een eerdere goede koers niet: liever een koers van een minuut
        # geleden dan een kaart zonder koers.
        if price is None and coin in _price_cache:
            price = _price_cache[coin][1]
        _price_cache[coin] = (now, price)
        prices[coin] = price
    return prices


def _with_preview(setup: dict) -> dict:
    """Stop en doel van een bouwende setup, zelfde formule als market_scanner._complete_smc_setup: ze hangen alleen af
    van sweep_price/liquidity_target, niet van de (nog onbekende) entry-prijs, dus dit is geen schatting maar het exacte
    cijfer dat straks ook echt gebruikt wordt, tenzij de setup intussen vervalt of vervangen wordt."""
    sign = -1 if setup["direction"] == "long" else 1
    stop_margin, target_margin = smc_stop_take_margins(setup)
    stop = setup["sweep_price"] + stop_margin * sign
    limit = setup["zone_high"] if setup["direction"] == "long" else setup["zone_low"]
    setup["preview_stop_loss"] = floor_stop(setup["direction"], limit, stop)
    setup["preview_take_profit"] = setup["liquidity_target"] + target_margin * sign
    return setup


def _sees_zone_sweep(user: Optional[dict]) -> bool:
    """De zone-sweep is voor iedereen tot ZONE_SWEEP_PUBLIC uit staat; dan alleen de CEO (rule_live.CEO_ONLY_TYPES, dezelfde bron als voor de signalen).
    Zonder kijker (een aanroep zonder gebruiker) alleen als hij openbaar is."""
    return rule_live.ZONE_SWEEP not in rule_live.CEO_ONLY_TYPES or is_ceo(user)


def _forming_setups(user: Optional[dict] = None) -> list[dict]:
    """Wat de Radar als wachtende kaart toont: bouwende SMC-setups, wachtende zone-radar-kaarten en, als de kijker hem mag zien, wachtende
    zone-sweep-kaarten, in de vorm die radar.setup_card leest.
    Met focus geen SMC-setups: die motor zoekt niets nieuws en maakt er geen signaal meer van. Hier gefilterd, zodat Radar, Nu, het dok en het appicoon gelijk tellen."""
    smc = [_with_preview(s) for s in repo.list_forming_smc_setups()] if focus.engine_on("smc") else []
    rows = smc + [zone_radar.radar_setup(r) for r in repo.list_zone_radar_setups()]
    if _sees_zone_sweep(user):
        rows += [zone_sweep.radar_setup(r) for r in repo.list_zone_sweep_setups()]
    return rows


def _context_lines(coins) -> dict[str, list[dict]]:
    """Het blok Context per coin (app/market_context.coin_lines): alleen wat de ophaler echt mat, met bron en leeftijd."""
    coins = set(coins)
    latest = market_context.latest(repo.latest_market_context(coins)) if coins else {}
    now = datetime.now(timezone.utc)
    return {c: market_context.coin_lines(latest.get(c, {}), now) for c in coins}


async def _radar_cards(user: Optional[dict] = None) -> list[dict]:
    forming = _forming_setups(user)
    types = ("smc", zone_radar.TRADE_TYPE) + ((zone_sweep.TRADE_TYPE,) if _sees_zone_sweep(user) else ())
    open_signals = repo.list_open_smc_signals(types=types)
    prices = await _cached_prices([s["coin"] for s in forming] + [s["coin"] for s in open_signals])
    cards = [c for s in forming if (c := radar.setup_card(s, prices.get(s["coin"])))]
    cards += [c for s in open_signals if (c := radar.signal_card(s, prices.get(s["coin"])))]
    return cards


async def _structure_cards() -> list[dict]:
    """Wachtende structuur-setups met hun plan (app/structure_live.py). Een plan dat verlopen is of waarvan de koers al voorbij stop of doel
    staat, valt weg: de engine zet de rij pas bij zijn volgende scan om, en tot dan mag hij nergens meetellen of staan."""
    setups = repo.list_structure_setups(("waiting",), 12)
    prices = await _cached_prices({s["coin"] for s in setups}) if setups else {}
    now = datetime.now(timezone.utc)
    cards = []
    for s in setups:
        plan = json.loads(s["plan"])
        if today.structure_state(s, plan, prices.get(s["coin"]), now) not in today.OPEN_PLAN_STATES:
            continue
        targets = list(zip(plan["targets"], plan["targets_r"]))
        checks = chance_checks.structure_checks(chance_checks.parse_features(s.get("features")), plan, s["grade"])
        cards.append({**s, "plan": plan, "targets": targets, "checks": [c for c in checks if not c[0].startswith("De CEO")],
                      "steps": chance_steps.structure_steps(plan, targets, prices.get(s["coin"]), s["direction"], s["coin"]),
                      "chart": Markup(setup_chart.setup_svg(plan.get("candles", []), s, plan, prices.get(s["coin"])))})
    return cards


def _sees_range_sweep(user: dict) -> bool:
    """De range sweep en de range-watch zijn proef: alleen de CEO, tot RANGE_SWEEP_PUBLIC aan staat (rule_live.CEO_ONLY_TYPES, dezelfde bron als voor de signalen)."""
    return rule_live.RANGE_SWEEP not in rule_live.CEO_ONLY_TYPES or is_ceo(user)


def _range_sweep_shown(user: dict) -> bool:
    """Wachtende range sweeps en de ranges zijn nieuwe kansen: met focus staan ze nergens. Een gevulde range sweep blijft als open signaal staan."""
    return _sees_range_sweep(user) and focus.engine_on(rule_live.RANGE_SWEEP)


async def _range_sweep_cards(user: dict) -> list[dict]:
    """Wachtende range sweeps met kaart, stappen en chips. Zoals _structure_cards valt een setup weg die verlopen is, waarvan de koers het midden van de
    range al raakte of voorbij de stop staat: de motor zet de rij pas bij zijn volgende cyclus om, en tot dan mag hij nergens meetellen of staan.
    Setups die de dagcap niet meldde ('niet_gemeld') staan wel op de pagina."""
    if not _range_sweep_shown(user):
        return []
    setups = repo.list_range_sweep_setups(("waiting", "niet_gemeld"))
    if not setups:
        return []
    prices = await _cached_prices({s["coin"] for s in setups})
    now = datetime.now(timezone.utc)
    lab = repo.get_rule_lab("range_sweep_stop")
    cards = []
    for s in setups:
        if today.range_sweep_state(s, prices.get(s["coin"]), now) not in today.OPEN_RANGE_STATES:
            continue
        view = today.range_sweep_view(s, prices.get(s["coin"]), lab, rangesweep_lab.LAB_COST_PCT)
        cards.append({**view, "chart": Markup(view["chart"])})
    return cards


async def _range_watch_rows(user: dict) -> list[dict]:
    """De ranges die de range-watch nu volgt, dichtstbij een rand eerst; een range zonder koers staat achteraan."""
    if not _sees_range_sweep(user) or not focus.engine_on("range_watch"):
        return []
    watches = repo.list_range_watches(("actief",))
    if not watches:
        return []
    prices = await _cached_prices({w["coin"] for w in watches})
    now = datetime.now(timezone.utc)
    rows = [today.range_watch_row(w, prices.get(w["coin"]), now) for w in watches]
    return sorted(rows, key=lambda r: (r["dist_pct"] is None, r["dist_pct"] or 0))


STRUCTURE_STATE_LABELS = {"schaduw": "Stil gevolgd, wacht op de terugkeer", "geen_plan": "Geen plan: te weinig ruimte of stop buiten bereik", "fired": "Limiet geraakt, signaal gemeld", "expired": "Verlopen, koers kwam niet terug",
                          "niet_gemeld": "Niet gemeld: het dagmaximum was bereikt", "overgeslagen": "Stop buiten het toegestane bereik", "geen_oordeel": "Niet gemeld"}


@app.get("/structuur")
async def structuur_page(request: Request, alleen: str = "", kant: str = "", user: dict = Depends(require_login)):
    """De nieuwe methode: breuk van een lijn of range op 30m met het plan getekend (app/structure_live.py)."""
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    history = [{**h, "state_label": STRUCTURE_STATE_LABELS.get(h["state"], h["state"])}
               for h in repo.list_structure_setups(("fired", "expired", "niet_gemeld", "overgeslagen", "geen_oordeel", "geen_plan", "schaduw"), 40)
               if h["created_at"] >= since]
    beat = repo.get_beat("structuur")
    minutes = None
    if beat:
        minutes = int((datetime.now(timezone.utc) - datetime.fromisoformat(beat["at"])).total_seconds() // 60)
    since24 = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    trend_beat = repo.get_beat("trend")
    trend_minutes = int((datetime.now(timezone.utc) - datetime.fromisoformat(trend_beat["at"])).total_seconds() // 60) if trend_beat else None
    trend_focus_off = not focus.engine_on("trend")        # uit door focus: alleen nog de trades die lopen
    return templates.TemplateResponse(request, "structuur.html", {"trend_minutes": trend_minutes,
        "user": user, "structure_cards": [c for c in await _structure_cards()
                            if kant not in ("long", "short") or c["direction"] == kant],
        "side": kant if kant in ("long", "short") else "", "history": history,
        "engine_minutes": minutes, "counts": repo.structure_counts(since24), "engine_on": config.STRUCTURE_ENABLED,
        "trend_signals": [s for s in repo.list_recent_signals_of_type("trend", since24) if not trend_focus_off or s["auto_outcome"] is None],
        "trend_on": config.TREND_ENABLED and not trend_focus_off, "trend_focus_off": trend_focus_off,
        "range_sweep_cards": await _range_sweep_cards(user), "range_watches": await _range_watch_rows(user), "range_visible": _range_sweep_shown(user),
        "range_watch_on": config.RANGE_WATCH_ENABLED, "range_sweep_on": config.RANGE_SWEEP_ENABLED})


@app.get("/galerij")
async def galerij_page(request: Request, maak: str = "", user: dict = Depends(require_login)):
    """Keuring van de range sweep met het oog (poort 0b en 1 van het VPS-protocol), alleen voor de CEO."""
    if not is_ceo(user):
        raise HTTPException(status_code=404)
    if maak:
        gallery_job.start(maak)
        return RedirectResponse("/galerij", status_code=303)
    kinds = [{"key": k, "title": t, **gallery_job.status(k)} for k, t in gallery_job.KINDS.items()]
    return templates.TemplateResponse(request, "galerij.html", {"user": user, "kinds": kinds, "busy": any(k["busy"] for k in kinds)})


@app.get("/galerij/{kind}")
async def galerij_file(kind: str, user: dict = Depends(require_login)):
    if not is_ceo(user) or kind not in gallery_job.KINDS or not gallery_job.path_of(kind).exists():
        raise HTTPException(status_code=404)
    return HTMLResponse(gallery_job.decorate(gallery_job.path_of(kind).read_text(encoding="utf-8"), kind))


@app.get("/smc")
async def smc_page(request: Request, user: dict = Depends(require_login)):
    """Trade Radar: bouwende setups en open SMC-signalen als handelsplan met candlegrafiek en live status (de limietorder
    staat op de zone-rand, zie app/trade_plan.py), daaronder de afgeronde signalen in dezelfde stijl als /signalen.
    Afgeronde signalen verschijnen ook op /signalen en het dashboard: deze pagina is een extra, gerichte weergave."""
    cards = await _radar_cards(user)
    entries = [e for e in repo.list_signalen_for_user(user["id"]) if e["trade_type"] in ("smc", zone_radar.TRADE_TYPE, zone_sweep.TRADE_TYPE)]
    winrate = repo.winrate_stats(user["id"])
    pattern_winrate = repo.pattern_winrate_stats()
    entries = _add_signal_context(entries, winrate, pattern_winrate)
    # Zonder deze aanroep blijft entry["user_confirmed"] ongezet en leest
    # macros.signal_card dat als Undefined (falsy), dus is-rejected voor
    # elk SMC-signaal ongeacht de smc-tak in _apply_user_confirmed hieronder
    # — zelfde patroon als signalen_page hierboven en het dashboard hieronder.
    required_factors = repo.list_required_factors(user["id"])
    _apply_user_confirmed(entries, user["confirm_threshold_pct"], required_factors)
    entries.sort(key=lambda e: e["created_at"], reverse=True)
    return templates.TemplateResponse(request, "smc.html", {
        "user": user, "context": _context_lines(c["coin"] for c in cards),
        "setup_cards": radar.waiting_cards(cards),
        "moot_cards": radar.moot_cards(cards),
        "signal_cards": [c for c in cards if c["kind"] == "signal"],
        "entries": entries,
    }, headers=_viewer_header(user))


async def _open_chances(user: dict, structure_cards: list[dict], scripts: list[dict], prices: dict, now: datetime,
                        radar_cards: Optional[list[dict]] = None) -> list[dict]:
    """De open kansen die deze kijker ziet, volgens today.open_chances: een proefsoort telt niet mee voor een leerling."""
    since = (now - timedelta(hours=today.OPEN_SIGNAL_HOURS)).isoformat()
    signals = [g for t in today.SIGNAL_LABELS for g in repo.list_recent_signals_of_type(t, since) if not g["is_practice"]]
    signals = rule_live.for_viewer(signals, is_ceo(user))
    prices = {**prices, **await _cached_prices({g["coin"] for g in signals} - prices.keys())}
    cards = radar_cards if radar_cards is not None else await _radar_cards(user)
    # Een wachtend scenario is een nieuwe kans; een gevuld script-signaal staat hierboven bij de open signalen en blijft.
    scripts = scripts if focus.engine_on("script") else []
    return today.open_chances(structure_cards, scripts, cards, signals, prices, now, range_cards=await _range_sweep_cards(user))


async def _vandaag_context(user: dict) -> dict:
    now = datetime.now(timezone.utc)
    script_on = focus.engine_on("script")
    scripts_raw = repo.latest_scripts() if script_on else []      # met focus schrijft niemand een nieuw script; een oud script is geen kans
    coins = [c["symbol"] for c in repo.list_coins()]
    prices = await _cached_prices(set(coins) | {"BTC"})
    scripts = [today.script_view(s, prices.get(s["coin"]), now) for s in scripts_raw]
    moments = today.agenda(market_calendar.upcoming(now, 24))
    liq_since = (now - timedelta(hours=1)).isoformat()
    liquidations = today.liquidation_rows({c: repo.list_liquidations(c, liq_since) for c in coins})
    events = []
    for e in repo.list_recent_events(None, (now - timedelta(hours=12)).isoformat(), limit=8):
        at = datetime.fromisoformat(e["at"])
        events.append({**e, "time": today.local(at if at.tzinfo else at.replace(tzinfo=timezone.utc)).strftime("%H:%M")})
    structure_cards = await _structure_cards()
    radar_cards = await _radar_cards(user)
    chances = await _open_chances(user, structure_cards, scripts, prices, now, radar_cards=radar_cards)
    rows = report_rows(user)        # al gefilterd op wat deze kijker mag zien
    week = track_record.week_summary(rows, config.TRACK_RECORD_COST_PCT)
    # Naar buiten is elke structuurkans Structuur: Vandaag telt structuur_c erbij; Bewijs houdt de twee interne soorten apart.
    summary = track_record.summarize([{**r, "trade_type": "structuur"} if r["trade_type"] == "structuur_c" else r for r in rows], config.TRACK_RECORD_COST_PCT)
    score_types = focus.FOCUS_TYPES if focus.active() else ("script", "samenval", "smc", "structuur", "structuur_c", "trend", "rejectie", "smc_waarschuwing", "zone_radar", "zone_sweep")
    score = [e for e in summary if e["trade_type"] in score_types or e["source"] == "alles"]
    for e in score:
        e["spark"] = Markup(track_record.sparkline_svg(e["cumulative"], width=180, height=36))
    return {
        "now": today.nl_stamp(today.local(now)), "fmt": today.fmt_price, "prices": prices, "scripts": scripts, "mood": today.mood(scripts_raw),
        "timeline": Markup(today.timeline_svg(now, moments)), "moments": moments, "liquidations": liquidations,
        "liq_last": repo.latest_liquidation_bucket(), "events": events, "score": score, "money": today.money,
        "status_labels": track_record.STATUS_LABELS, "script_enabled": config.SCRIPT_ENABLED, "script_on": script_on,
        "structure_cards": structure_cards,
        "chances": chances, "nearest": today.nearest_chance(chances), "chances_unit": today.chances_unit(len(chances)),
        "last_message_ago": today.ago_text(repo.last_message_received_at(), now),
        "last_check_ago": today.ago_text((repo.get_beat("structuur") or {}).get("at"), now),
        "chance_plans": [c["card"] for c in chances if c["card"]], "chance_rows": [c for c in chances if not c["card"]],
        "scenarios_waiting": sum(1 for sc in scripts for x in sc["scenarios"] if x["state"] == "waiting"),
        "ctx_high": market_context.FUNDING_HIGH_PCT, "ctx_low": market_context.FUNDING_LOW_PCT,
        "market_context": market_context.market_view(market_context.latest(repo.latest_market_context([market_context.MARKET, *market_context.VANDAAG_COINS])), now),
        "budget": today.budget_ring(push_policy.used(repo.list_recent_pushes(user["id"], (now - timedelta(hours=24)).isoformat())), user.get("push_budget")),
        "radar_cards": radar_cards,
    }


@app.get("/vandaag")
async def vandaag_page(request: Request, bron: str = "", user: dict = Depends(require_login)):
    """Cockpit: het markt-script van nu, de agenda van de komende 24 uur, wat beweegt (liquidaties en nieuws) en de score van
    wat HesPulse zelf voorspelde. Alles komt uit app/today.py en de verzamelaars; er staat niets op wat niet gemeten is.
    ?bron=app is de start_url van het manifest: de CEO begint de app op zijn eigen pagina, een leerling hier. Zonder die markering (de
    tab, een snelkoppeling) ziet ook de CEO Vandaag."""
    if bron == "app" and is_ceo(user):
        return RedirectResponse(url="/ceo", status_code=303)
    ctx = await _vandaag_context(user)
    greeting = ceo.greeting(today.local(datetime.now(timezone.utc)).hour, is_ceo(user), user["username"])
    cards = ctx["radar_cards"]
    screen = nu.screen(cards, _skipped_keys(request, user), request.query_params.get("plan"))
    # Gekeken: hoe oud de oudste koers achter deze kaarten is (app/freshness.py), niet de tijd van de paginaweergave.
    age = freshness.oldest_age(_price_fetched_at, {c["coin"] for c in cards}, time.time())
    focus_coin = (screen["focus"] or {}).get("coin")
    return templates.TemplateResponse(request, "vandaag.html", {
        "user": user, "greeting": greeting, **ctx, "nu": screen, "nu_stale": ladder.stale_text(age),
        "nu_context": _context_lines([focus_coin])[focus_coin] if focus_coin else [],
        "nu_when": nu.date_line(today.local(datetime.now(timezone.utc)))}, headers=_viewer_header(user))


NU_SKIP_COOKIE = "hp_skip"
NU_SKIP_HOURS = 24


def _skipped_keys(request: Request, user: dict) -> frozenset:
    """Overgeslagen op dit toestel (cookie) of op een ander toestel van dezelfde gebruiker (plan_skips), allebei een dag."""
    since = (datetime.now(timezone.utc) - timedelta(hours=NU_SKIP_HOURS)).isoformat()
    return nu.parse_skip(request.cookies.get(NU_SKIP_COOKIE)) | {r["plan_key"] for r in repo.list_plan_skips(user["id"], since)}


@app.post("/nu/overslaan")
async def nu_skip(request: Request, key: str = Form(""), user: dict = Depends(require_login)):
    """Sla over: dit plan vult Nu een dag niet meer. Het blijft op de Radar staan. De cookie houdt het op dit toestel; de rij in plan_skips
    zet het met zijn moment in het Logboek en de weekterugblik."""
    if nu.SKIP_KEY.match(key):
        item = nu.item_for(await _radar_cards(user), key)
        repo.record_plan_skip(user["id"], key, item["coin"] if item else None, item["direction"] if item else None, db.now_iso())
    response = RedirectResponse(url="/vandaag", status_code=303)
    response.set_cookie(NU_SKIP_COOKIE, nu.add_skip(request.cookies.get(NU_SKIP_COOKIE), key), max_age=24 * 3600, samesite="lax", path="/")
    return response


@app.get("/nu/order/{key}")
async def nu_order(request: Request, key: str, user: dict = Depends(require_login)):
    """De order-checklist, schermvullend: de stappen van het orderformulier met een tik-om-te-kopiëren per getal."""
    item = None
    if key.startswith("structuur:"):
        card = next((c for c in await _structure_cards() if f"structuur:{c['id']}" == key), None)
        if card:
            price = (await _cached_prices({card["coin"]})).get(card["coin"])
            item = nu.structure_item(card, price, today.structure_state(card, card["plan"], price, datetime.now(timezone.utc)))
    elif nu.SKIP_KEY.match(key):
        item = nu.item_for(await _radar_cards(user), key)
    if item is None:
        raise HTTPException(status_code=404)
    repo.open_checklist(user["id"], key, item["coin"], item["direction"], db.now_iso())
    return templates.TemplateResponse(request, "order.html", {"user": user, "item": item, "steps": nu.checklist(item), "note": nu.price_note(item)})


@app.post("/nu/order/{key}/klaar")
async def nu_order_done(key: str, user: dict = Depends(require_login)):
    """order.js meldt dat alle stappen stonden; met het openmoment geeft dat de gemeten duur in het Logboek. Een tweede melding verandert niets."""
    if not nu.SKIP_KEY.match(key):
        raise HTTPException(status_code=404)
    return {"ok": repo.finish_checklist(user["id"], key, db.now_iso())}


def _viewer_header(user: dict) -> dict:
    """Kop voor de pagina's die de service worker offline bewaart (Radar, Vandaag). Hij wist de bewaarde pagina's zodra een andere kijker
    op hetzelfde apparaat inlogt. Afgeleid met het geheim, zodat er geen kaal gebruikers-id in een kop of cache staat."""
    tag = hashlib.sha256(f"hespulse-viewer:{config.JWT_SECRET}:{user['id']}".encode()).hexdigest()[:20]
    return {"X-HP-Viewer": tag}


def _age_header(coins) -> dict:
    age = freshness.oldest_age(_price_fetched_at, coins, time.time())
    return {} if age is None else {"X-Price-Age": str(age)}


@app.get("/api/vandaag")
async def api_vandaag(user: dict = Depends(require_login)):
    """Live koersen en afstand tot de voorwaarde per scenario, voor vandaag.js."""
    ctx = await _vandaag_context(user)
    payload = {
        "prices": ctx["prices"],
        "scenarios": {str(sc["id"]): {"state": sc["state"], "label": sc["state_label"], "short": sc["state_short"], "to_trigger_pct": sc["to_trigger_pct"],
                                       "hours_left": sc["hours_left"], "chart": sc["chart"], "action": sc["action"]}
                      for s in ctx["scripts"] for sc in s["scenarios"]},
    }
    return JSONResponse(payload, headers=_age_header(ctx["prices"].keys()))


KANS_TIMEFRAMES = ("5m", "15m", "30m", "4h")


@app.get("/kans/{signal_id}")
async def kans_page(request: Request, signal_id: int, tf: str = "30m", user: dict = Depends(require_login)):
    """Eén kans op één scherm: grafiek, feiten, gemeten kenmerken en wat er sinds de melding gebeurde. Hier landt een tik op een melding."""
    signal = repo.get_signal(signal_id)
    if not signal or signal["is_practice"] or (signal["trade_type"] in rule_live.CEO_ONLY_TYPES and not is_ceo(user)):
        raise HTTPException(status_code=404)
    if signal["trade_type"] == rule_live.RANGE_SWEEP and (page := await _range_sweep_kans(request, signal, user)) is not None:
        return page
    setup = repo.get_structure_setup_by_signal(signal_id)
    candles, price = None, None
    tf = tf if tf in KANS_TIMEFRAMES and not setup else "30m"        # Structuur tekent zijn eigen momentopname op 30 minuten
    try:
        df = await asyncio.to_thread(exchange.fetch_ohlcv, signal["coin"], timeframe=tf, limit=60)
        candles = [[row.timestamp.isoformat(), row.open, row.high, row.low, row.close] for row in df.itertuples()]
    except Exception:
        candles = None
    prices = await _cached_prices({signal["coin"]})
    price = prices.get(signal["coin"])
    signal.setdefault("message_summary", None)
    trailing = reference = None
    if signal["trade_type"] in rule_live.ENGINE_TYPES:          # meelopende stop: geen doel, de uitkomst is winst of verlies in R
        trailing = kans_view.trailing_outcome(signal, (repo.get_trade_result(signal_id) or {}).get("r_value"))
    elif signal["trade_type"] == zone_sweep.TRADE_TYPE and signal["take_profit"] is None:
        # Een zone-sweep zonder doel: de R op Bewijs komt van de referentie-uitgang, niet van een doel dat geraakt werd.
        reference = kans_view.reference_outcome(signal, (repo.get_trade_result(signal_id) or {}).get("r_value"))
    facts = kans_view.facts(signal)
    still_open = signal["auto_outcome"] is None and facts["entry"] and facts["stop"]
    return templates.TemplateResponse(request, "kans.html", {
        "user": user, "signal": signal, "facts": facts, "trailing": trailing, "reference": reference,
        "action": chance_steps.now_line("open", signal["direction"], facts["entry"], facts["stop"], facts["take"]) if still_open else None,
        "levels": chance_steps.level_chips(facts["entry"], facts["stop"], facts["take"] or None) if facts["entry"] and facts["stop"] else [],
        "events": kans_view.timeline(signal, setup, (trailing or reference or {}).get("text")),
        "chart": Markup(kans_view.chart(signal, setup, candles, price)), "price": price, "setup": setup,
        "tf": tf, "timeframes": KANS_TIMEFRAMES if not setup else (),
        "fingerprint": (repo.get_chain_link(signal["id"]) or {}).get("hash"),
        **_kans_context(signal),
    })


def _kans_context(signal: dict) -> dict:
    """Context nu, en voor een zone-radar-kaart ook de bewaarde stand bij zijn ontstaan."""
    origin = repo.get_zone_radar_setup_by_signal(signal["id"]) if signal["trade_type"] == zone_radar.TRADE_TYPE else None
    return {"context": _context_lines([signal["coin"]])[signal["coin"]], "context_origin": market_context.snapshot_lines(origin) if origin else []}


async def _range_sweep_kans(request: Request, signal: dict, user: dict):
    """De kanspagina van een gevulde range sweep: de getekende setup, wat de stop deed (uit de meting van de motor) en de referentie-uitgang die Bewijs telt.
    Geen doel en geen R:R: er is er geen, en de referentie is niet jouw trade."""
    setup = repo.get_range_sweep_setup_by_signal(signal["id"])
    trade = repo.get_range_sweep_trade(signal["id"])
    if not setup or not trade:
        return None          # de motor schrijft het signaal vóór de meting; een signaal zonder meting krijgt de gewone pagina
    price = (await _cached_prices({signal["coin"]})).get(signal["coin"])
    plan = json.loads(setup["plan"]) if setup.get("plan") else {}
    chart = setup_chart.range_sweep_svg(plan.get("candles", []), {**setup, "legs": chance_steps.range_legs(setup)}, setup["stop"], price, plan.get("zones"))
    r_value = (repo.get_trade_result(signal["id"]) or {}).get("r_value")
    ref = kans_view.reference_outcome(signal, r_value)
    pct = abs(trade["entry"] - trade["stop"]) / trade["entry"] * 100
    stopped = bool(trade["stop_hit_at"])
    state = ("Stop geraakt" if stopped else "Meting klaar, de stop werd niet geraakt" if trade["closed_at"] else "Loopt nog")
    reached = [k for k in track_record.RANGE_R_LEVELS if trade.get(f"reached_{k}r_at")]
    return templates.TemplateResponse(request, "kans.html", {
        "user": user, "signal": signal, "facts": kans_view.facts(signal), "trailing": None, "price": price, "setup": None, "tf": "30m", "timeframes": (),
        "events": kans_view.format_events(kans_view.range_sweep_events(setup, trade)),
        "chart": Markup(chart), "fingerprint": None, **_kans_context(signal),
        "range_sweep": {"state": state, "stopped": stopped, "running": not trade["closed_at"] and not stopped, "reference": ref, "stop_pct": pct,
                        "cost_r": rangesweep_lab.LAB_COST_PCT / pct if pct else None, "lab_cost_pct": rangesweep_lab.LAB_COST_PCT,
                        "mae": trade["mae_r"], "mfe": trade["mfe_r"], "reached": reached, "score": setup["score"], "grade": setup["grade"],
                        "family": {"zone": "Zone-retest", "sweep": "Range sweep"}.get(setup["family"], setup["family"]),
                        "tf": {"30m": "30m", "1h": "1u", "2h": "2u", "4h": "4u"}.get(setup["range_tf"], setup["range_tf"]),
                        }})


WEEK_RANGES = {7: "1W", 14: "2W", 30: "1M", 90: "3M"}


@app.get("/week")
async def week_page(request: Request, dagen: int = 7, user: dict = Depends(require_login)):
    """Jouw week in één plaatje, om te delen: kansen, resultaat in R na kosten, beste en slechtste kans."""
    dagen = dagen if dagen in WEEK_RANGES else 7
    week = track_record.week_summary(report_rows(user), config.TRACK_RECORD_COST_PCT, days=dagen)
    spark = track_record.sparkline_svg(week["cumulative"], width=320, height=80).replace("<svg", "<svg data-share-chart", 1)
    return templates.TemplateResponse(request, "week.html", {"user": user, "week": week, "spark": Markup(spark), "headline": ceo.week_headline(week["net_r"], week["resolved"]), "dagen": dagen, "ranges": WEEK_RANGES})


@app.get("/api/kansen")
async def api_kansen(user: dict = Depends(require_login)):
    """Live afstand tot stap 1 per wachtend Structuur-plan, voor kansen.js."""
    cards = await _structure_cards()
    return {"structuur": {str(c["id"]): {"dist": c["steps"][0]["dist"]} for c in cards}}


@app.get("/api/radar")
async def api_radar(user: dict = Depends(require_login)):
    """Live status per radar-kaart, voor radar.js: nieuwe koers, afstand tot de limietorder, live R en de niveaus voor de grafiek.
    De leeftijd van de oudste koers staat in de header X-Price-Age, zodat de vorm van de payload per kaart gelijk blijft."""
    cards = await _radar_cards(user)
    return JSONResponse(radar.live_payload(cards), headers=_age_header({c["coin"] for c in cards}))


RADAR_TIMEFRAMES = ("5m", "15m", "1h", "4h")
RADAR_CANDLE_TTL_SECONDS = 60
RADAR_CANDLE_FETCH = 500            # altijd evenveel ophalen, zodat elke `limit` uit dezelfde cache-regel komt
_candle_cache: dict[tuple[str, str], tuple[float, list]] = {}


async def _cached_candles(coin: str, tf: str) -> Optional[list]:
    """Candles per (coin, tf) uit de minuutcache, [[unix_s, open, high, low, close], ...] oudste eerst. Mislukt het ophalen, dan geldt de
    laatste goede stand (ook al is die verlopen); None als er nog nooit een goede ophaal was."""
    hit = _candle_cache.get((coin, tf))
    if not hit or time.monotonic() - hit[0] >= RADAR_CANDLE_TTL_SECONDS:
        try:
            df = await asyncio.to_thread(exchange.fetch_ohlcv, coin, tf, RADAR_CANDLE_FETCH)
            rows = [[int(r.timestamp.timestamp()), float(r.open), float(r.high), float(r.low), float(r.close)] for r in df.itertuples()]
            hit = (time.monotonic(), rows)
            _candle_cache[(coin, tf)] = hit
        except Exception:
            if not hit:
                return None
    return hit[1]


@app.get("/api/radar_candles/{coin}")
async def api_radar_candles(coin: str, tf: str = "15m", limit: int = 96, user: dict = Depends(require_login)):
    """Compacte candles voor de grafiek op een radar-kaart: {"coin", "tf", "candles": [[unix_s, open, high, low, close], ...]},
    oudste eerst. Per (coin, tf) een minuut onthouden (_cached_candles): elke kaart en elke ingelogde gebruiker vraagt erom."""
    coin = coin.upper()
    if not re.fullmatch(r"[A-Z0-9]{2,12}", coin) or tf not in RADAR_TIMEFRAMES:
        raise HTTPException(status_code=422)
    # Alleen coins uit de lijst: anders groeit de candlecache met willekeurige symbolen en gaat elk daarvan naar de beurs.
    if coin not in {c["symbol"] for c in repo.list_coins()}:
        raise HTTPException(status_code=404)
    limit = max(10, min(limit, RADAR_CANDLE_FETCH))
    rows = await _cached_candles(coin, tf)
    if rows is None:
        raise HTTPException(status_code=503, detail="candles niet beschikbaar")
    return {"coin": coin, "tf": tf, "candles": rows[-limit:]}


@app.get("/api/sparklines")
async def api_sparklines(coins: str = "", user: dict = Depends(require_login)):
    """Minigrafiek van de laatste 24 uur per coin, voor spark.js: een aanroep voor alle kaarten, uit dezelfde candlecache als de grafieken
    (1u-candles), dus nooit een beursaanroep per kaart. Een coin zonder data ontbreekt in het antwoord."""
    active = {c["symbol"] for c in repo.list_coins()}
    wanted = [c for c in dict.fromkeys(x.strip().upper() for x in coins.split(",")) if c in active]
    out = {}
    for coin, rows in zip(wanted, await asyncio.gather(*[_cached_candles(c, "1h") for c in wanted])):
        item = radar.spark([r[4] for r in rows[-(radar.SPARK_HOURS + 1):]]) if rows else None
        if item:
            out[coin] = item
    return out


RANGE_REGISTER_TESTS = 64       # docs/onderzoek/range-sweep/preregistratie.md, 'Register': 34 eerdere varianten plus de 30 toetsen van deze familie


async def _range_sweep_proof(user: dict, rows: list[dict], labs: dict) -> Optional[dict]:
    """De sectie 'Range sweep, stopkwaliteit' van Bewijs, of None als deze kijker de proef niet mag zien. Alles wat telt komt uit de afgeronde
    metingen en de signalen van rows (al gefilterd op wat deze kijker ziet); lopende trades, niet gevulde setups en wachtende setups staan als aantal ernaast."""
    if rule_live.RANGE_SWEEP not in track_record.visible_rule_types({rule_live.RANGE_SWEEP}, is_ceo(user), rule_live.CEO_ONLY_TYPES):
        return None
    lab_stop, lab_edge = labs.get("range_sweep_stop"), labs.get(rule_live.RANGE_SWEEP)
    trades = repo.list_range_sweep_trades(1000)
    live = track_record.stop_quality_live(trades, rangesweep_lab.LAB_COST_PCT)
    net = track_record.live_net_r(rows, rule_live.RANGE_SWEEP, config.TRACK_RECORD_COST_PCT)
    running = {t["coin"] for t in trades if t.get("ref_r") is None}
    prices = await _cached_prices(running) if running else {}
    states = repo.count_range_sweep_setups_by_state()
    unfilled = {k: states.get(k, 0) for k in ("verlopen", "weggelopen", "stop_voor_vulling")}
    lab_view = track_record.stop_lab_view(lab_stop)
    return {"rows": track_record.stop_quality_rows(lab_view, live), "live": live, "drift": track_record.drift_warning(lab_view, live),
            "status": track_record.rule_status(lab_edge, net, stop_lab=lab_stop),
            "verdict": track_record.range_lab_verdict(lab_stop, lab_edge, stopquality.KILL_TESTS, RANGE_REGISTER_TESTS, rangesweep_lab.EDGE_T_MIN),
            "variant": track_record.rule_label(variant.lower()) if (variant := ((lab_stop or {}).get("summary") or {}).get("variant")) else None,
            "lab_n": (lab_view or {}).get("summary", {}).get("n"),
            "reference": track_record.reference_live(trades, net, prices), "cost_pct": config.TRACK_RECORD_COST_PCT, "lab_cost_pct": rangesweep_lab.LAB_COST_PCT,
            "setups": {"filled": states.get("filled", 0), "waiting": states.get("waiting", 0) + states.get("niet_gemeld", 0), "unfilled": unfilled,
                       "unfilled_total": sum(unfilled.values()), "total": sum(states.values())}}


@app.get("/bewijs")
async def bewijs_page(request: Request, user: dict = Depends(require_login)):
    """Eerlijk, automatisch gemeten trackrecord per soort melding in R na kosten (zie app/track_record.py)."""
    rows = report_rows(user)        # al gefilterd op wat deze kijker mag zien
    summary = track_record.summarize(rows, config.TRACK_RECORD_COST_PCT)
    summary.sort(key=lambda e: e["source"] != "alles")      # het totaal bovenaan, de rest in vaste volgorde
    for entry in summary:
        entry["spark"] = Markup(track_record.sparkline_svg(entry["cumulative"]))
    total = next((e for e in summary if e["source"] == "alles"), None)
    per_type, off_types = focus.split(e for e in summary if e["source"] != "alles")
    lab_types = {lab["rule"]: lab for lab in repo.list_rule_labs()}
    visible = track_record.visible_rule_types(set(lab_types) | set(rule_live.CEO_ONLY_TYPES), is_ceo(user), rule_live.CEO_ONLY_TYPES)
    # De range sweep heeft zijn eigen sectie met de stopmeting; als 'andere regel zonder motor' zou hij een live motor ontkennen die er wel is.
    # De zone-sweep draait live (ongetest): zodra zijn labrun is opgeslagen staat hij bij de regels met een motor, met zijn stoptoets als stop_lab.
    # Tot dan is zijn eigen rij onder Per soort de enige plek, zonder status.
    range_sweep = await _range_sweep_proof(user, rows, lab_types)
    hidden = (rule_live.RANGE_SWEEP, "range_sweep_stop") + ZONE_SWEEP_LAB_KEYS
    engine_types, other_types = track_record.split_rule_types([t for t in visible if t not in hidden], rule_live.ENGINE_TYPES + (rule_live.ZONE_SWEEP,))
    rule_statuses = []
    for trade_type in engine_types:
        stop_lab = lab_types.get(STOP_LAB_KEYS[trade_type]) if trade_type in STOP_LAB_KEYS else None
        status = track_record.rule_status(lab_types.get(trade_type), track_record.live_net_r(rows, trade_type, config.TRACK_RECORD_COST_PCT), stop_lab=stop_lab)
        rule_statuses.append({**status, "label": track_record.rule_label(trade_type), "css": status["status"].lower().replace(" ", "-"),
                              "lab_line": track_record.lab_line(lab_types.get(trade_type))})
    other_rules = track_record.other_rule_rows(lab_types, other_types)
    curves = track_record.equity_curves(rows, config.TRACK_RECORD_COST_PCT)
    for c in curves:
        c["svg"] = Markup(track_record.equity_svg(c["cumulative"], c["drawdown"]))
    return templates.TemplateResponse(request, "bewijs.html", {
        "my_week": _week_review(user, datetime.now(timezone.utc)),
        "curves": curves, "total": total, "per_type": per_type, "off_types": off_types, "funding_split": track_record.funding_split(rows, config.TRACK_RECORD_COST_PCT),
        "hours": track_record.hour_grid(rows, config.TRACK_RECORD_COST_PCT),
        "rule_statuses": rule_statuses, "other_rules": other_rules, "range_sweep": range_sweep, "ceo_view": is_ceo(user), "user": user, "summary": summary, "status_labels": track_record.STATUS_LABELS, "ceo_status": ceo.STATUS_QUOTE,
        "cost_pct": config.TRACK_RECORD_COST_PCT, "recent_days": track_record.RECENT_DAYS,
        "weeks": track_record.WEEKS_SHOWN, "min_status": track_record.MIN_FOR_STATUS, "min_proven": track_record.MIN_FOR_PROVEN,
    })


@app.post("/signalen/{entry_id}/verbergen")
async def dismiss_signal(entry_id: int, alles: bool = False, user: dict = Depends(require_login)):
    """Verbergt een signaal van /signalen voor deze gebruiker ("niet
    interessant"). Puur een weergavefilter op de eigen journal_entries-rij,
    zie repo.dismiss_signal_for_user — de gedeelde signalen en ieders
    winrate blijven ongemoeid."""
    repo.dismiss_signal_for_user(entry_id, user["id"])
    return RedirectResponse(url=f"/signalen{'?alles=1' if alles else ''}", status_code=303)


@app.post("/signalen/verbergen-alles")
async def dismiss_all_signals(user: dict = Depends(require_login)):
    """Verbergt in één keer alle nog open signalen op /signalen ("alles
    niet interessant"), zie repo.dismiss_all_open_signals_for_user. Landt
    altijd op de Open-weergave (niet ?alles=1): daar staat na deze actie
    niets meer open, precies het bedoelde resultaat."""
    repo.dismiss_all_open_signals_for_user(user["id"])
    return RedirectResponse(url="/signalen", status_code=303)


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@app.get("/login")
async def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if security.is_locked_out(username):
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Te veel mislukte pogingen. Probeer het later opnieuw."},
            status_code=429,
        )

    user = repo.get_user_by_username(username)
    ok = user is not None and security.verify_password(password, user["password_hash"])
    security.record_login_attempt(username, success=ok,
                                   ip_address=request.client.host if request.client else "")

    if not ok:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Onjuiste gebruikersnaam of wachtwoord."},
            status_code=401,
        )

    token = security.create_session_token(user["id"])
    response = RedirectResponse(url="/ceo", status_code=303)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=config.SESSION_HOURS * 3600)
    return response


@app.post("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


# ---------------------------------------------------------------------------
# Registreren
# ---------------------------------------------------------------------------

USERNAME_PATTERN = re.compile(r"^[a-zA-Z0-9_-]{3,32}$")


@app.get("/registreer")
async def register_form(request: Request, code: str = ""):
    return templates.TemplateResponse(request, "register.html", {"error": None, "code": beheer.normalize_code(code)[:16],
                                                                  "invite_required": config.REGISTRATION_REQUIRES_INVITE})


@app.post("/registreer")
async def register_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
    code: str = Form(""),
):
    ip = request.client.host if request.client else ""
    code = beheer.normalize_code(code)[:16]

    def error(message: str, status_code: int = 400):
        return templates.TemplateResponse(
            request, "register.html", {"error": message, "code": code, "invite_required": config.REGISTRATION_REQUIRES_INVITE}, status_code=status_code,
        )

    if security.is_registration_rate_limited(ip):
        return error("Te veel registraties vanaf dit adres. Probeer het later opnieuw.", 429)

    username = username.strip()
    if not USERNAME_PATTERN.match(username):
        return error("Gebruikersnaam moet 3 tot 32 tekens zijn: letters, cijfers, - of _.")
    if len(password) < 8:
        return error("Wachtwoord moet minstens 8 tekens zijn.")
    if password != password_confirm:
        return error("Wachtwoorden komen niet overeen.")

    now = datetime.now(timezone.utc)
    if config.REGISTRATION_REQUIRES_INVITE and not code:
        return error("Registreren gaat met een uitnodigingscode. Vraag er een aan de eigenaar.")
    if code:
        invite = repo.get_invite(code)
        if not invite or not beheer.invite_usable(invite, now):
            return error("Deze uitnodigingscode is onbekend, verlopen of al op.")

    security.record_registration_attempt(ip)
    user_id = repo.register_user(username, security.hash_password(password), invite_code=code or None, now_iso=now.isoformat())
    if user_id is None:
        return error("Deze gebruikersnaam is al in gebruik." if repo.get_user_by_username(username) else "Deze uitnodigingscode is net op of verlopen.")

    token = security.create_session_token(user_id)
    response = RedirectResponse(url="/ceo", status_code=303)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=config.SESSION_HOURS * 3600)
    return response


# ---------------------------------------------------------------------------
# Dashboard startpagina
# ---------------------------------------------------------------------------

def _build_heatmap_weeks(daily: dict[str, float], weeks: int = 18) -> list[list[Optional[dict]]]:
    """Bouwt een GitHub-achtig rooster: kolommen = weken, rijen = maandag
    t/m zondag, meest recente week uiterst rechts. Kleurintensiteit relatief
    aan de grootste absolute dagwaarde in de reeks zelf, zodat het altijd
    goed schaalt ongeacht portfolio-omvang. Een dag na vandaag (nog niet
    bestaand) wordt None, zodat de template die cel leeg kan laten."""
    today = datetime.now(timezone.utc).date()
    start = today - timedelta(days=today.weekday(), weeks=weeks - 1)
    max_abs = max((abs(v) for v in daily.values()), default=0.0) or 1.0
    columns = []
    for w in range(weeks):
        week = []
        for d in range(7):
            day = start + timedelta(days=w * 7 + d)
            if day > today:
                week.append(None)
                continue
            value = daily.get(day.isoformat())
            level = 0
            if value:
                level = min(3, max(1, round(abs(value) / max_abs * 3)))
                level = level if value > 0 else -level
            week.append({"date": day.isoformat(), "value": value, "level": level})
        columns.append(week)
    return columns


def _build_eval_day_dots(daily_results: list[dict]) -> list[dict]:
    """Zelfde kleurintensiteit-formule als _build_heatmap_weeks, maar als
    platte rij in plaats van een week-rooster: één stip per handelsdag van
    de evaluatie-run, relatief aan de grootste dagwaarde in de reeks
    zelf."""
    max_abs = max((abs(d["value"]) for d in daily_results), default=0.0) or 1.0
    dots = []
    for d in daily_results:
        level = 0
        if d["value"]:
            level = min(3, max(1, round(abs(d["value"]) / max_abs * 3)))
            level = level if d["value"] > 0 else -level
        dots.append({"date": d["date"], "value": d["value"], "level": level})
    return dots


def _eval_coaching_tip(
    eval_display: Optional[dict], daily_loss_used_pct: float, drawdown_used_pct: float, profit_progress_pct: float,
) -> Optional[str]:
    """Eén korte, op de actuele status toegesneden tip in plaats van
    altijd dezelfde statische tekst. Alleen relevant voor een actief
    lopende run — een afgeronde run heeft niks meer te sturen. Twee
    situaties zijn de moeite waard om expliciet te benoemen: dicht bij
    een limiet (stoppen is een optie, geen verplichting) en dicht bij het
    winstdoel (het moment waarop discipline het vaakst verslapt)."""
    if not eval_display or eval_display["status"] != "actief":
        return None
    if daily_loss_used_pct >= 70 or drawdown_used_pct >= 70:
        return "Je zit dicht bij een limiet. Overweeg te stoppen voor vandaag, niet omdat het moet, maar omdat het kan."
    if profit_progress_pct >= 70:
        return "Je bent dicht bij je winstdoel. Dit is precies het moment waarop mensen hun regels laten verslappen. Blijf bij je proces."
    return None


def _add_signal_context(entries: list[dict], winrate: dict, pattern_winrate: dict) -> list[dict]:
    """Voegt aan elk signaal het concrete advies toe (wat kan je beter
    doen dan nu instappen) en een slagingskans toe. Voor dagtrading is dat
    de eigen trackrecord van dit vertrouwen-niveau; voor patroon een
    kansberekening die het gepoolde factor-percentage van dit signaal
    combineert met de systeembrede historische winrate van dit
    patroontype (repo.pattern_winrate_stats). Swing heeft geen van
    beide (zie de spec), dus geen geleende statistiek. SMC volgt hetzelfde
    precedent als swing (zie de spec): geen kansberekening, altijd
    gemeld, dus ook hier geen geleende statistiek."""
    for entry in entries:
        entry["advice"] = advice_module.build_advice(entry)
        if entry.get("trade_type") in ("swing", "smc"):
            entry["success_rate"] = None
            entry["success_sample"] = None
            continue
        if entry.get("trade_type") == "patroon":
            pattern_stats = pattern_winrate.get(entry.get("pattern_name"))
            entry["success_rate"] = repo.pattern_kansberekening(entry.get("pass_pct"), pattern_stats)
            entry["success_sample"] = pattern_stats["total"] if pattern_stats else None
            continue
        bucket = "hoog_vertrouwen" if entry.get("confidence") == "hoog vertrouwen" else "laag_vertrouwen"
        stats = winrate[bucket]
        entry["success_rate"] = stats["winrate"]
        entry["success_sample"] = stats["total"]
    return entries


# Soorten met gemeten kenmerken (app/chance_checks.py): de melding ging al uit, de score beschrijft de kans en bepaalt geen groene of rode rand.
SCORED_TYPES = ("structuur", "structuur_c", "trend", "rejectie", "script", "smc_waarschuwing")


def _apply_user_confirmed(entries: list[dict], threshold_pct: float, required_factors: set[str]) -> None:
    """Zet entry['user_confirmed'] per signaal, de echte trade-kans-vlag
    achter macros.signal_card's groene rand. Swing is altijd bevestigd
    (geen gepoold percentage, een echte terugveer op een bewaakt niveau) —
    required_factors is daar niet van toepassing (zie de spec), dus die
    tak geeft hem simpelweg niet door. SMC volgt hetzelfde precedent als
    swing (zie de spec: geen kansberekening, altijd melden, hard_gates_ok=1
    al bij het aanmaken vastgezet) — pass_pct is voor smc bewust altijd
    None (market_scanner.py zet het nooit), dus zonder deze tak zou
    repo.user_confirmed(None, ...) hier altijd False geven en elk
    SMC-signaal permanent als afgewezen (is-rejected) tonen. Dagtrading en
    patroon tellen pas als bevestigd zodra hun EIGEN percentage (pass_pct
    resp. success_rate/kansberekening) de drempel van deze gebruiker haalt
    EN (als de gebruiker zelf factoren verplicht heeft gesteld) die
    factoren ✓ staan in de breakdown — voorheen kreeg elk patroon-signaal
    hier onvoorwaardelijk True, dus een kansberekening van 30% kreeg
    dezelfde groene rand als een kansberekening van 90%, amper onderscheid
    tussen een echte kans en ruis. Moet NA _add_signal_context draaien:
    patroon se success_rate bestaat pas dan."""
    for entry in entries:
        if entry["trade_type"] in ("swing", "smc", *SCORED_TYPES):
            entry["user_confirmed"] = True
        elif entry["trade_type"] == "patroon":
            entry["user_confirmed"] = repo.user_confirmed(
                entry.get("success_rate"), bool(entry["hard_gates_ok"]), threshold_pct,
                reason=entry.get("reason") or "", required_factors=required_factors,
            )
        else:
            entry["user_confirmed"] = repo.user_confirmed(
                entry["pass_pct"], bool(entry["hard_gates_ok"]), threshold_pct,
                reason=entry.get("reason") or "", required_factors=required_factors,
            )


def _position_size(entry: dict) -> Optional[float]:
    """Eigen positiegrootte als die is ingevuld, anders de grootte waarmee de
    trade destijds gesized is (journal_entries.position_size, alleen nog
    gevuld op oude regels van vóór evaluatie/generieke sizing weg waren).
    Voor de oudste regels van vóór die kolom bestond valt dit terug op een
    herberekening. Puur historische weergave — nieuwe journaalregels
    krijgen nooit meer een risk_eur/position_size."""
    if entry.get("position_size_override") is not None:
        return entry["position_size_override"]
    if entry.get("position_size") is not None:
        return entry["position_size"]
    if entry["risk_eur"] and entry["price"] and entry["stop_loss"]:
        return risk.compute_position_size(entry["risk_eur"], entry["price"], entry["stop_loss"])
    return None


def _compute_tension(current_price: Optional[float], stop_loss: Optional[float], take_profit: Optional[float]) -> tuple[float, str]:
    """Hoe dicht de koers nu bij de stop loss of take profit zit, als 0
    (ver van allebei) tot 1 (er middenin/overheen). Basis voor de
    spanningsgloed op een open-trade kaart: rood als de stop loss het
    dichtst is, groen als de take profit het dichtst is. Puur visueel,
    geen nieuw getal dat nergens anders al stond."""
    if current_price is None or not stop_loss or not take_profit:
        return 0.0, "10, 186, 181"
    dist_to_sl = abs(current_price - stop_loss)
    dist_to_tp = abs(current_price - take_profit)
    total_range = abs(take_profit - stop_loss) or 1.0
    nearest = min(dist_to_sl, dist_to_tp)
    tension = max(0.0, 1.0 - min(nearest / (total_range * 0.5), 1.0))
    color = "242, 104, 92" if dist_to_sl < dist_to_tp else "51, 214, 159"
    return tension, color


async def _enrich_open_positions(entries: list[dict]) -> list[dict]:
    """Vult elke open positie (entry_price al ingevuld) aan met de actuele
    prijs en het nog niet gerealiseerde resultaatpercentage. Eén
    prijs-opvraag per coin, ook als er meerdere open trades op dezelfde
    coin staan. De exchange-aanroep loopt via to_thread, anders blokkeert
    die synchrone netwerkcall de hele server voor iedereen tegelijk."""
    price_cache: dict[str, Optional[float]] = {}
    for entry in entries:
        entry["position_size"] = _position_size(entry)
        entry["current_price"] = None
        entry["pnl_pct"] = None
        entry["tension"], entry["tension_color"] = _compute_tension(None, entry["stop_loss"], entry["take_profit"])
        if entry["entry_price"] is None:
            continue
        if entry["coin"] not in price_cache:
            try:
                price_cache[entry["coin"]] = await asyncio.to_thread(exchange.fetch_last_price, entry["coin"])
            except Exception:
                price_cache[entry["coin"]] = None
        current_price = price_cache[entry["coin"]]
        if current_price is None:
            continue
        entry["current_price"] = current_price
        entry["pnl_pct"] = risk.compute_unrealized_pnl(entry["direction"], entry["entry_price"], current_price)
        entry["tension"], entry["tension_color"] = _compute_tension(current_price, entry["stop_loss"], entry["take_profit"])
    return entries


async def _annotate_level_outcomes(symbol: str, levels: list[dict]) -> None:
    """Vult elk bron niveau aan met hoe dicht de prijs er sindsdien bij
    kwam: 0 als een candle het niveau daadwerkelijk raakte of kruiste,
    anders de kleinste afstand als percentage van het niveau zelf. Eén
    OHLCV-aanroep voor de hele coinpagina (vanaf het oudste niveau), per
    niveau alleen candles ná zijn eigen created_at meegenomen. Faalt de
    aanroep (exchange down, geen historie zo ver terug), dan blijft
    `outcome_pct` gewoon None, dat is geen kritieke informatie."""
    for level in levels:
        level["outcome_pct"] = None
        level["outcome_reached"] = False
    if not levels:
        return
    oldest = min(levels, key=lambda lvl: lvl["created_at"])
    since_ms = int(pd.Timestamp(oldest["created_at"]).timestamp() * 1000)
    try:
        df = await asyncio.to_thread(exchange.fetch_ohlcv, symbol, config.TIMEFRAME, 500, since_ms)
    except Exception:
        return
    if df.empty:
        return
    for level in levels:
        candles = df[df["timestamp"] >= pd.Timestamp(level["created_at"])]
        if candles.empty:
            continue
        price_level = level["price_level"]
        touched = ((candles["low"] <= price_level) & (candles["high"] >= price_level)).any()
        if touched:
            level["outcome_reached"] = True
            level["outcome_pct"] = 0.0
        else:
            closest = min(
                (abs(price_level - candles["low"].min()), abs(price_level - candles["high"].max())),
            )
            level["outcome_pct"] = (closest / price_level * 100) if price_level else None


def _filter_journal(all_entries: list[dict], status: str) -> list[dict]:
    """Filtert een al opgehaalde lijst logboekregels op status, dezelfde
    regels als repo.list_journal, zonder een tweede databasebevraging.
    dismissed_at IS NULL hoort in "open": wat op /signalen als "niet
    interessant" is weggeklikt, telt nergens meer mee als open kans (zelfde
    bron als repo.count_pending_signals, het app-icoon-cijfer)."""
    if status == "open":
        return [e for e in all_entries if e["status"] != "genegeerd" and e["exit_price"] is None
                and e["dismissed_at"] is None]
    if status == "gesloten":
        return [e for e in all_entries if e["exit_price"] is not None]
    if status == "genegeerd":
        return [e for e in all_entries if e["status"] == "genegeerd"]
    return all_entries


@app.get("/dashboard")
async def dashboard():
    # Verweesde pagina van vóór de puur-signalen-herziening (2026-09-21):
    # geen navigatielink wijst hier meer naartoe, maar een oude
    # PWA-snelkoppeling kan nog steeds deze URL openen. Doorsturen i.p.v.
    # verwijderen voorkomt een kale 404 op zo'n bestaande snelkoppeling.
    return RedirectResponse(url="/vandaag", status_code=303)


@app.get("/account")
async def account_page(request: Request, status: str = "alle", user: dict = Depends(require_login)):
    """Mijn account: journaal, portfolio, instellingen en winrate, los van
    de kale signalenlijst op /signalen (zie CLAUDE.md 'pure signals'-
    uitgangspunt). Zelfde context-opbouw als de oudere /dashboard-route
    (die blijft ongewijzigd bestaan tot een latere taak hem uitfaseert),
    behalve de individuele-signalen-actiesectie ("Open nu") en de
    evaluatie-kaart, die hier niet getoond worden, en de winrate: die komt
    hier uit repo.winrate_for_user (het volledig automatische, prijs-
    gebaseerde trackrecord) in plaats van de oude, handmatige-status-
    gebaseerde berekening."""
    all_entries = repo.list_journal(user["id"], status=None)
    real_entries = [e for e in all_entries if not e["is_practice"]]
    practice_entries = [e for e in all_entries if e["is_practice"]]

    entries = _filter_journal(real_entries, status)
    # Bucketed hoog/laag-vertrouwen winrate, uitsluitend nog nodig als
    # input voor _add_signal_context hieronder (advies op de oefentrade-
    # kaarten): de winrate die deze pagina zelf toont is repo.winrate_for_user
    # verderop, niet dit handmatige-status-gebaseerde cijfer.
    confidence_winrate = repo.winrate_stats(user["id"])
    pattern_winrate = repo.pattern_winrate_stats()
    open_entries = _add_signal_context(
        await _enrich_open_positions(_filter_journal(real_entries, "open")), confidence_winrate, pattern_winrate,
    )
    taken_entries = [e for e in open_entries if e["entry_price"] is not None]
    pending_entries = [e for e in open_entries if e["entry_price"] is None]

    for e in taken_entries:
        e["sltp_progress_pct"] = (
            risk.compute_sltp_progress_pct(e["direction"], e["current_price"], e["stop_loss"], e["take_profit"])
            if e["current_price"] is not None and e["stop_loss"] and e["take_profit"] else None
        )
    seen_ticker_coins: set[str] = set()
    ticker_coins = []
    for e in taken_entries:
        if e["coin"] not in seen_ticker_coins:
            seen_ticker_coins.add(e["coin"])
            ticker_coins.append({"coin": e["coin"], "current_price": e["current_price"]})

    last_signal_row = repo.list_recent_signals_for_user(user["id"], limit=1)
    last_signal_text = None
    if last_signal_row:
        s = last_signal_row[0]
        last_signal_text = f"{s['coin']} · {s['direction']} · {s['confidence']}"

    direction_counts: dict[str, int] = {}
    for e in taken_entries:
        direction_counts[e["direction"]] = direction_counts.get(e["direction"], 0) + 1
    correlation_warning = next(
        (
            {"direction": d, "count": n}
            for d, n in direction_counts.items() if n > 1
        ),
        None,
    )
    practice_open = _add_signal_context(
        await _enrich_open_positions([e for e in practice_entries if e["exit_price"] is None]), confidence_winrate, pattern_winrate,
    )
    practice_closed = [e for e in practice_entries if e["exit_price"] is not None]
    cumulative = repo.cumulative_result_series(user["id"])
    heatmap_weeks = _build_heatmap_weeks(repo.daily_results(user["id"]))
    ratio_stats = repo.winrate_by_ratio(user["id"])
    coin_stats = repo.coin_stats(user["id"])
    coins = repo.list_coins()
    is_admin = bool(config.ADMIN_USERNAME) and user["username"] == config.ADMIN_USERNAME
    unclear_messages = repo.recent_unclear_messages() if is_admin else None

    onboarding = {
        "push_enabled": bool(repo.list_push_subscriptions(user["id"])),
        "threshold_chosen": user["confirm_threshold_set_at"] is not None,
    }
    onboarding_complete = all(onboarding.values())

    return templates.TemplateResponse(request, "account.html", {
        "user": user,
        "onboarding": onboarding,
        "onboarding_complete": onboarding_complete,
        "market_scan_enabled": repo.is_market_scan_enabled(),
        "advanced_factors_enabled": config.ENABLE_ADVANCED_FACTORS,
        "toggleable_factors": indicators.TOGGLEABLE_FACTORS,
        "user_required_factors": repo.list_required_factors(user["id"]),
        "entries": entries,
        "open_entries": open_entries,
        "taken_entries": taken_entries,
        "pending_entries": pending_entries,
        "ticker_coins": ticker_coins,
        "last_signal_text": last_signal_text,
        "correlation_warning": correlation_warning,
        "practice_open": practice_open,
        "practice_closed": practice_closed,
        "winrate": repo.winrate_for_user(user["id"]),
        "cumulative": cumulative,
        "heatmap_weeks": heatmap_weeks,
        "ratio_stats": ratio_stats,
        "coin_stats": coin_stats,
        "coins": coins,
        "status_filter": status,
        "unclear_messages": unclear_messages,
    })


@app.get("/api/open_positions")
async def api_open_positions(user: dict = Depends(require_login)):
    """Ververst de live prijs en het resultaatpercentage van open posities,
    gebruikt door het dashboard om zonder volledige herlaad bij te
    werken."""
    entries = await _enrich_open_positions(repo.list_journal(user["id"], status="open"))
    return [
        {
            "id": e["id"], "current_price": e["current_price"],
            "pnl_pct": e["pnl_pct"],
            "is_practice": bool(e["is_practice"]),
            "direction": e["direction"], "stop_loss": e["stop_loss"], "take_profit": e["take_profit"],
            "tension": e["tension"], "tension_color": e["tension_color"],
        }
        for e in entries if e["entry_price"] is not None
    ]


@app.get("/api/system_status")
async def api_system_status(user: dict = Depends(require_login)):
    """Levensteken van het systeem zelf, niet van de markt: is de exchange
    nu bereikbaar, en wanneer kwam het laatste Discord bericht binnen.
    Eén live check per opvraag, geen opgeslagen status die kan verouderen
    zonder dat iemand het merkt."""
    try:
        await asyncio.to_thread(exchange.fetch_last_price, "BTC")
        exchange_ok = True
    except Exception:
        exchange_ok = False

    recent_signals = repo.list_recent_signals_for_user(user["id"], limit=1)
    last_signal = None
    if recent_signals:
        s = recent_signals[0]
        last_signal = {
            "id": s["id"], "coin": s["coin"],
            "label": f"{s['direction']} · {s['confidence']}",
            "received_at": s["created_at"],
        }

    forming = _forming_setups(user)
    # Alleen wat de radar al in de cache zette: deze poll mag niet trager worden door een beurs die net niet antwoordt.
    zone_prices = {c: hit[1] for c in {s["coin"] for s in forming} if (hit := _price_cache.get(c)) and hit[1]}
    return {
        "exchange_ok": exchange_ok,
        "last_message_at": repo.last_message_received_at(),
        "server_started_at": SERVER_STARTED_AT,
        "checked_at": db.now_iso(),
        "pending_count": repo.count_pending_signals(user["id"]),
        "in_zone": radar.in_zone_count(forming, zone_prices),
        "unread_notifications": repo.count_unread_notifications(user["id"]),
        "week_result_pct": repo.week_result_pct(user["id"]),
        "volatility_ratio": repo.largest_open_position_volatility(user["id"]),
        "last_signal": last_signal,
    }


@app.get("/api/push/vapid-public-key")
async def api_push_vapid_public_key(user: dict = Depends(require_login)):
    return {"key": config.VAPID_PUBLIC_KEY}


@app.post("/api/push/subscribe")
async def api_push_subscribe(request: Request, user: dict = Depends(require_login)):
    """Slaat een Web Push-abonnement op vanaf de browser. Het
    subscription-object van de browser heeft altijd deze vorm:
    {endpoint, keys: {p256dh, auth}}."""
    data = await request.json()
    endpoint = data.get("endpoint")
    keys = data.get("keys", {})
    if not endpoint or not keys.get("p256dh") or not keys.get("auth"):
        return JSONResponse({"error": "ongeldig abonnement"}, status_code=400)
    repo.upsert_push_subscription(
        user["id"], endpoint, keys["p256dh"], keys["auth"], data.get("device_label"),
    )
    return {"ok": True}


def _pause_state(user: dict) -> dict:
    left = push_policy.pause_minutes_left(user.get("push_paused_until"), datetime.now(timezone.utc))
    return {"paused_until": user.get("push_paused_until") if left else None, "minutes_left": left, "label": push_policy.pause_text(left)}


@app.get("/api/push/pauze")
async def api_push_pause_state(user: dict = Depends(require_login)):
    return _pause_state(user)


@app.post("/api/push/pauze")
async def api_push_pause_toggle(user: dict = Depends(require_login)):
    """Eén tik: twee uur geen pushes. Een tik tijdens de pauze heft hem op. Signalen en journaal lopen door (alleen push_notify kijkt hiernaar)."""
    now = datetime.now(timezone.utc)
    if push_policy.pause_minutes_left(user.get("push_paused_until"), now):
        repo.set_push_pause(user["id"], None)
    else:
        repo.set_push_pause(user["id"], push_policy.pause_until(now).isoformat())
    return _pause_state(repo.get_user(user["id"]))


@app.get("/api/prijsalarm")
async def api_price_alerts(user: dict = Depends(require_login)):
    return {"alerts": [{"id": a["id"], "coin": a["coin"], "price": a["price"], "label": a["label"]} for a in repo.list_price_alerts(user["id"])]}


def _is_local_path(url: str) -> bool:
    """Alleen een pad op deze site. Een backslash telt als schuine streep in browsers, dus "/\\evil.test" is geen pad."""
    parts = urlsplit(url)
    return url.startswith("/") and not url.startswith("//") and "\\" not in url and not parts.netloc and not parts.scheme


@app.post("/api/prijsalarm")
async def api_price_alert_create(request: Request, user: dict = Depends(require_login)):
    """Alarm op een niveau van een kaart. De kant (boven of onder de koers) ligt vast bij het aanmaken; level_check toetst elke 15 minuten."""
    try:
        data = await request.json()
    except ValueError:
        data = None
    if not isinstance(data, dict):
        return JSONResponse({"error": "Ongeldig alarm"}, status_code=400)
    # create_price_alert slaat de coin op zoals hij komt, dus hier normaliseren en tegen de lijst toetsen.
    coin = str(data.get("coin", "")).strip().upper()
    raw_price = data.get("price")
    try:
        price = float(raw_price)
    except (TypeError, ValueError):
        return JSONResponse({"error": "Ongeldige prijs"}, status_code=400)
    if isinstance(raw_price, bool) or not math.isfinite(price) or price <= 0 or coin not in {c["symbol"] for c in repo.list_coins()}:
        return JSONResponse({"error": "Ongeldig alarm"}, status_code=400)
    if repo.count_open_price_alerts(user["id"]) >= price_alerts.MAX_OPEN_PER_USER:
        return JSONResponse({"error": f"Maximaal {price_alerts.MAX_OPEN_PER_USER} alarmen tegelijk"}, status_code=409)
    current = (await _cached_prices({coin})).get(coin)
    if current is None:
        return JSONResponse({"error": "Geen koers, probeer het zo opnieuw"}, status_code=503)
    raw_url = str(data.get("url") or "")
    url = raw_url if _is_local_path(raw_url) else "/smc"
    side = price_alerts.side_for(price, current)
    alert_id = repo.create_price_alert(user["id"], coin, price, side, str(data.get("label") or "Niveau")[:20], url)
    return {"id": alert_id, "side": side, "message": f"Alarm staat op {chance_steps.fmt(price)}. Melding binnen 15 minuten na het raken."}


@app.delete("/api/prijsalarm/{alert_id}")
async def api_price_alert_delete(alert_id: int, user: dict = Depends(require_login)):
    if not repo.delete_price_alert(alert_id, user["id"]):
        raise HTTPException(status_code=404)
    return {"ok": True}


@app.post("/api/push/debug-log")
async def api_push_debug_log(request: Request, user: dict = Depends(require_login)):
    """Tijdelijk: push-subscribe.js kan op iOS geen console tonen zonder Mac
    + Safari Web Inspector, dus rapporteert elke stap van de abonneerpoging
    hierheen in plaats van naar de (onbereikbare) browserconsole. Landt in
    journalctl -u crypto-web, direct leesbaar op de VPS. Weer verwijderen
    zodra de pushmeldingbug gevonden is."""
    data = await request.json()
    # warning, niet info: web/main.py configureert geen logging.basicConfig,
    # dus een kale info-regel wordt nergens getoond (geen handler onder
    # WARNING). Puur voor deze tijdelijke debug-tool, zie de docstring.
    logger.warning("PUSH-DEBUG (%s): %s", user["username"], data.get("message", ""))
    return {"ok": True}


@app.get("/export/logboek.csv")
async def export_journal_csv(user: dict = Depends(require_login)):
    entries = repo.list_journal(user["id"], status=None, limit=100000)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "tijdstip", "coin", "richting", "vertrouwen", "technisch_bevestigd",
        "prijs", "stop_loss", "take_profit", "status",
        "entry_price", "exit_price", "exit_time", "resultaat_pct", "notitie",
    ])
    for e in entries:
        writer.writerow([
            e["created_at"], e["coin"], e["direction"], e["confidence"],
            "ja" if e["technical_confirmed"] else "nee",
            e["price"], e["stop_loss"], e["take_profit"], e["status"],
            e["entry_price"], e["exit_price"], e["exit_time"], e["result_pct"],
            e["note"] or "",
        ])

    filename = f"hespulse-logboek-{user['username']}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/settings/portfolio")
async def update_settings(
    quiet_hours_start: str = Form(""),
    quiet_hours_end: str = Form(""),
    user: dict = Depends(require_login),
):
    # Allebei leeg = geen stille uren, blijft altijd geluid geven. Slechts
    # één van de twee ingevuld heeft geen betekenis, dan ook geen venster.
    start = quiet_hours_start.strip() or None
    end = quiet_hours_end.strip() or None
    if not (start and end):
        start, end = None, None
    repo.update_user_settings(user["id"], start, end)
    return RedirectResponse(url="/account", status_code=303)


@app.post("/settings/risico")
async def update_risk_per_trade(risk_eur: str = Form(""), user: dict = Depends(require_login)):
    """Eigen bedrag per trade (1R) in euro, alleen voor de weergave op de kaarten. Leeg of ongeldig zet het weer uit."""
    try:
        amount = float(risk_eur.strip().replace(",", ".")) if risk_eur.strip() else None
    except ValueError:
        amount = None
    if amount is not None and not (0 < amount <= 1_000_000):
        amount = None
    repo.set_risk_per_trade_eur(user["id"], amount)
    return RedirectResponse(url="/account", status_code=303)


@app.post("/settings/meldingen")
async def update_push_budget(budget: str = Form(""), user: dict = Depends(require_login)):
    """Maximaal aantal pushes voor nieuwe kansen per 24 uur (app/push_policy.py). Leeg is de standaard, 0 zet het budget uit."""
    try:
        value = int(budget.strip()) if budget.strip() else None
    except ValueError:
        value = None
    if value is not None and not (0 <= value <= 500):
        value = None
    repo.set_push_budget(user["id"], value)
    return RedirectResponse(url="/account", status_code=303)


@app.post("/push/voorbeeld")
async def send_demo_push_message(user: dict = Depends(require_login)):
    """Stuurt een testpush naar elk apparaat van de ingelogde gebruiker:
    laat zien hoe een echte melding eruitziet, én bevestigt meteen dat
    het abonnement van dit apparaat werkt."""
    await push_notify.send_push(
        user["id"], "Ξ ETH long, hoog vertrouwen (voorbeeld)",
        "Entry 2340.0000 · Stop 2290.0000 · Take profit 2430.0000",
        "/account", silent=False,
    )
    return RedirectResponse(url="/account", status_code=303)


@app.post("/journal/{entry_id}/status")
async def update_journal_status(
    entry_id: int,
    status: str = Form(...),
    entry_price: str = Form(""),
    next: str = Form(""),
    user: dict = Depends(require_login),
):
    entry = float(entry_price) if entry_price.strip() else None
    repo.update_journal_status(entry_id, user["id"], status, entry_price=entry)
    return RedirectResponse(url=_safe_next(next), status_code=303)


def _safe_next(next_path: str) -> str:
    """De open-trade formulieren (sluiten/terugzetten/levels aanpassen)
    staan zowel op het dashboard als op de coinpagina, en horen na het
    versturen terug te gaan naar waar je vandaan kwam, niet altijd naar
    /dashboard. Alleen een eigen, relatief pad toestaan (nooit "//host" of
    "https://...", dat zou een open redirect zijn)."""
    if next_path and next_path.startswith("/") and not next_path.startswith("//"):
        return next_path
    return "/dashboard"


@app.post("/journal/{entry_id}/close")
async def close_journal(
    entry_id: int,
    exit_price: float = Form(...),
    exit_time: str = Form(...),
    next: str = Form(""),
    user: dict = Depends(require_login),
):
    won = False
    won_pct = 0.0
    eval_flag = None
    try:
        result_pct, is_practice = repo.close_journal_trade(entry_id, user["id"], exit_price, exit_time)
        won_pct = result_pct
        won = (not is_practice) and result_pct > 0
    except ValueError:
        # Geen eigen entry gevonden (niet van deze gebruiker, of nog geen
        # entry prijs ingevuld). Stil negeren, niets om te sluiten.
        pass
    target = _safe_next(next)
    extra_query = []
    if won:
        extra_query.append(("closed_win", "1"))
        extra_query.append(("closed_pct", f"{won_pct:.2f}"))
    if eval_flag:
        extra_query.append((eval_flag, "1"))
    if extra_query:
        # Seintje voor client-side reveals (base.html leest dit uit de URL
        # na een gewone navigatie, dashboard.js uit resp.url na een
        # AJAX-swap) — zelfde patroon als de bestaande winst-confetti.
        parts = urlsplit(target)
        query = urlencode(parse_qsl(parts.query) + extra_query)
        target = urlunsplit((parts.scheme, parts.netloc, parts.path, query, parts.fragment))
    return RedirectResponse(url=target, status_code=303)


@app.post("/journal/{entry_id}/reset")
async def reset_journal(
    entry_id: int,
    next: str = Form(""),
    user: dict = Depends(require_login),
):
    """Zet een verkeerd ingevulde regel terug naar 'nieuw', zonder de
    melding zelf kwijt te raken. Voor als er een typefout in de entry
    prijs is geslopen of de verkeerde status is gekozen."""
    repo.reset_journal_entry(entry_id, user["id"])
    return RedirectResponse(url=_safe_next(next), status_code=303)


@app.post("/journal/{entry_id}/delete-practice")
async def delete_practice_trade(
    entry_id: int,
    next: str = Form(""),
    user: dict = Depends(require_login),
):
    """Een oefentrade heeft geen echte melding om naar terug te vallen,
    dus 'weggooien' verwijdert de regel echt, anders dan de 'Terugzetten'
    knop bij een echte trade."""
    repo.delete_practice_entry(entry_id, user["id"])
    return RedirectResponse(url=_safe_next(next), status_code=303)


def _parse_optional_float(raw: str) -> Optional[float]:
    raw = raw.strip()
    return float(raw) if raw else None


@app.post("/journal/{entry_id}/levels")
async def update_journal_levels(
    entry_id: int,
    stop_loss: str = Form(""),
    take_profit: str = Form(""),
    position_size: str = Form(""),
    next: str = Form(""),
    user: dict = Depends(require_login),
):
    """Eigen stop loss, take profit en/of positiegrootte op een open trade.
    Leeg gelaten veld zet de eigen waarde weer terug op de berekende
    standaard in plaats van hem verplicht te maken."""
    repo.update_journal_levels(
        entry_id, user["id"],
        stop_loss=_parse_optional_float(stop_loss),
        take_profit=_parse_optional_float(take_profit),
        position_size=_parse_optional_float(position_size),
    )
    return RedirectResponse(url=_safe_next(next), status_code=303)


@app.post("/journal/{entry_id}/note")
async def update_journal_note(
    entry_id: int,
    note: str = Form(""),
    next: str = Form(""),
    user: dict = Depends(require_login),
):
    repo.update_journal_note(entry_id, user["id"], note)
    return RedirectResponse(url=_safe_next(next), status_code=303)


# ---------------------------------------------------------------------------
# Evaluatie simulatie: virtueel een Kraken Prop-achtige evaluatie naspelen
# met dezelfde dagverlies-, drawdown- en winstdoel-regels, gevoed door
# oefentrades die tijdens een actieve run genomen worden. Zie de spec voor
# het volledige ontwerp.
# ---------------------------------------------------------------------------

PROP_EVAL_TIERS = (5000.0, 10000.0, 25000.0, 50000.0, 100000.0, 200000.0)


# ---------------------------------------------------------------------------
# Grafiekpagina per coin
# ---------------------------------------------------------------------------

@app.get("/coins/{symbol}")
async def coin_page(request: Request, symbol: str, signal: Optional[int] = None, user: dict = Depends(require_login)):
    symbol = symbol.upper()
    source_levels = repo.list_source_levels(symbol)
    await _annotate_level_outcomes(symbol, source_levels)
    entries = [e for e in repo.list_journal_for_coin(user["id"], symbol) if not e["is_practice"]]
    open_trades = await _enrich_open_positions(
        [e for e in entries if e["entry_price"] is not None and e["exit_price"] is None]
    )
    # macros.open_trade_body's SL/TP-voortgangsbalk leest sltp_progress_pct,
    # dat de dashboard-route al zet maar deze route nog niet — zonder dit
    # rendert de balk hier met een lege/ongeldige "width: %" in plaats van
    # gewoon weggelaten te worden.
    for e in open_trades:
        e["sltp_progress_pct"] = (
            risk.compute_sltp_progress_pct(e["direction"], e["current_price"], e["stop_loss"], e["take_profit"])
            if e["current_price"] is not None and e["stop_loss"] and e["take_profit"] else None
        )
    open_signal_ids = {e["signal_id"] for e in open_trades}
    # Een tegenovergestelde melding die auto_ignore_opposite_pending/
    # auto_ignore_stale_pending_for_coin al genegeerd heeft voor deze
    # gebruiker (zie app/repo.py) moet hier ook niet meer als losse kaart
    # verschijnen — anders toont deze sectie alsnog een long- en een
    # short-signaal naast elkaar terwijl /signalen de oude al opruimde.
    ignored_signal_ids = {e["signal_id"] for e in entries if e["status"] == "genegeerd"}
    # Journal-rijen zonder eigen entry_price (nog niet genomen) kunnen al wel
    # een per-gebruiker stop/take-override hebben (evaluatie-stop-cap) — die
    # override moet hier getoond worden, anders wijkt de coin-pagina af van
    # de melding en het dashboard voor dezelfde, nog open kans.
    pending_by_signal_id = {
        e["signal_id"]: e for e in entries
        if e["entry_price"] is None and e["status"] != "genegeerd"
    }
    hidden = () if is_ceo(user) else rule_live.CEO_ONLY_TYPES          # de proefmotor is alleen voor de CEO
    recent_signals = [
        s for s in repo.list_recent_signals(symbol, exclude_types=hidden)
        if s["id"] not in open_signal_ids and s["id"] not in ignored_signal_ids
        and (s["stop_loss"] or s["take_profit"])
    ]
    # Een melding linkt hierheen met ?signal=: de pagina toont maar de laatste paar signalen, dus een oudere kans (of een stille Trend-melding
    # tussen nieuwere) zou anders ontbreken en de tik landde op een pagina zonder zijn kans.
    if signal and signal not in open_signal_ids and all(s["id"] != signal for s in recent_signals):
        wanted = repo.get_signal(signal)
        if wanted and wanted["coin"] == symbol and not wanted["is_practice"] and wanted["trade_type"] not in hidden:
            wanted.setdefault("message_summary", "Zelf gedetecteerd door HesPulse")
            recent_signals.insert(0, wanted)
    for s in recent_signals:
        s.setdefault("entry_price", None)  # signalen zijn geen journal-rijen, dat veld bestaat niet
        pending_entry = pending_by_signal_id.get(s["id"])
        if pending_entry is not None:
            s["stop_loss"] = pending_entry["stop_loss"]
            s["take_profit"] = pending_entry["take_profit"]
    winrate = repo.winrate_stats(user["id"])
    pattern_winrate = repo.pattern_winrate_stats()
    open_trades = _add_signal_context(open_trades, winrate, pattern_winrate)
    recent_signals = _add_signal_context(recent_signals, winrate, pattern_winrate)
    required_factors = repo.list_required_factors(user["id"])
    _apply_user_confirmed(recent_signals, user["confirm_threshold_pct"], required_factors)

    # Sparkline: laatste signalen op een rij, oudste eerst zodat het als
    # tijdlijn leest. Puur signaal-geschiedenis (niet oefentrades, dat zijn
    # geen signalen), alleen om in één oogopslag te zien hoe vaak deze coin
    # recent hoog vertrouwen gaf.
    sparkline = list(reversed(repo.list_recent_signals(symbol, limit=14, exclude_types=hidden)))

    # Korte context bovenaan de pagina: hoeveel signalen kwamen er recent
    # binnen voor deze coin, zonder eerst de hele sparkline te moeten
    # aflezen.
    week_ago = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    recent_week = [s for s in sparkline if s["created_at"] >= week_ago]
    recent_activity = {
        "count": len(recent_week),
        "hoog": sum(1 for s in recent_week if s["technical_confirmed"]),
        "last_at": sparkline[-1]["created_at"] if sparkline else None,
    } if sparkline else None

    coin_stat = next((s for s in repo.coin_stats(user["id"]) if s["coin"] == symbol), None)

    # Community-vergelijking: hoeveel andere gebruikers namen dezelfde
    # kans. Iedereen ziet hetzelfde signaal, dat gegeven werd tot nu toe
    # nergens gebruikt. Alleen tonen als er meer dan 1 gebruiker is, anders
    # zegt "1 van de 1" niks.
    primary_signal_id = (
        open_trades[0]["signal_id"] if open_trades
        else (recent_signals[0]["id"] if recent_signals else None)
    )
    community_stat = None
    if primary_signal_id:
        fanned_out = repo.list_journal_entries_for_signal(primary_signal_id)
        if len(fanned_out) > 1:
            community_stat = {
                "taken": sum(1 for e in fanned_out if e["status"] == "genomen"),
                "total": len(fanned_out),
            }

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

    return templates.TemplateResponse(request, "coin.html", {
        "user": user,
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
        "price": (await _cached_prices({symbol})).get(symbol),
        "structure_card": next((c for c in await _structure_cards() if c["coin"] == symbol), None),
    })


@app.get("/api/price/{symbol}")
async def api_price(symbol: str, user: dict = Depends(require_login)):
    """Live koers voor de kop van de coinpagina."""
    symbol = symbol.upper()
    return {"price": (await _cached_prices({symbol})).get(symbol)}


@app.post("/coins/{symbol}/note")
async def save_coin_note(
    symbol: str, note: str = Form(""), user: dict = Depends(require_login),
):
    """Eigen aantekening bij een coin, los van een specifieke trade
    (bijvoorbeeld een unlock-datum of een aankomend nieuwsmoment). Gedeeld
    tussen gebruikers, net als de rest van de coin-gegevens."""
    repo.set_coin_note(symbol.upper(), note.strip())
    return RedirectResponse(url=f"/coins/{symbol.upper()}", status_code=303)


@app.post("/coins/{symbol}/unmute")
async def unmute_coin(symbol: str, user: dict = Depends(require_login)):
    """Zet meldingen voor deze coin weer aan voor de ingelogde gebruiker,
    na een eerdere mute-suggestie (zie
    signal_processor.REPEATED_IGNORE_MUTE_THRESHOLD)."""
    repo.unmute_coin(user["id"], symbol.upper())
    return RedirectResponse(url=f"/coins/{symbol.upper()}", status_code=303)


@app.post("/settings/market_scan")
async def toggle_market_scan(enabled: str = Form(...), user: dict = Depends(require_login)):
    """Systeembrede noodrem voor de autonome marktscan (niet per gebruiker,
    zie de spec). Elke ingelogde gebruiker mag dit omzetten, net als bij
    de portfolio-instellingen hierboven — er is geen apart adminaccount in
    dit systeem."""
    logger.info("Marktscan-noodrem gewijzigd door %s: %s", user["username"], "aan" if enabled == "1" else "uit")
    repo.set_market_scan_enabled(enabled == "1")
    return RedirectResponse(url="/account", status_code=303)


CONFIRM_THRESHOLD_PRESETS = {"soepel": 45.0, "normaal": 60.0, "streng": 75.0}


@app.post("/instellingen/thema")
async def update_theme(thema: str = Form("dark"), user: dict = Depends(require_login)):
    """Zonder JavaScript: het formulier in Account zet de cookie. Met JavaScript doet theme.js dat zelf, zonder herladen."""
    response = RedirectResponse(url="/account#weergave", status_code=303)
    response.set_cookie(THEME_COOKIE, thema if thema in THEMES else "dark", max_age=400 * 24 * 3600, samesite="lax", path="/")
    return response


@app.post("/instellingen/drempel")
async def update_confirm_threshold_setting(
    preset: str = Form(...),
    user: dict = Depends(require_login),
):
    if preset not in CONFIRM_THRESHOLD_PRESETS:
        # Onbekende waarde (geknoei met het formulier of een toekomstige
        # preset die nog niet bestaat) mag nooit crashen, negeer stil.
        return RedirectResponse(url="/account", status_code=303)
    repo.update_confirm_threshold(user["id"], CONFIRM_THRESHOLD_PRESETS[preset])
    return RedirectResponse(url="/account", status_code=303)


@app.post("/instellingen/factoren")
async def update_required_factors_setting(
    factoren: list[str] = Form([]),
    user: dict = Depends(require_login),
):
    # Nooit ruwe formulierinvoer direct opslaan: alleen namen uit de
    # vaste TOGGLEABLE_FACTORS-lijst zijn geldig, geknoei met het
    # formulier (of een verouderde factornaam) wordt stil genegeerd.
    # Ook dedupliceren: repo.set_required_factors doet een kale INSERT
    # per naam tegen een UNIQUE-constraint, dus een dubbele waarde in de
    # formulierinvoer zou een IntegrityError geven.
    valid_names = {name for name, _ in indicators.TOGGLEABLE_FACTORS}
    factoren = list(dict.fromkeys(f for f in factoren if f in valid_names))
    repo.set_required_factors(user["id"], factoren)
    return RedirectResponse(url="/account", status_code=303)


@app.post("/coins/{symbol}/trendlines")
async def create_trendline(
    symbol: str,
    x1: int = Form(...), y1: float = Form(...),
    x2: int = Form(...), y2: float = Form(...),
    label: str = Form(""),
    user: dict = Depends(require_login),
):
    """Zelf getekende schuine lijn op de coin-grafiek (wig, driehoek,
    kanaal), voor patronen die de automatische toetsing niet zelf kan
    naberekenen. Wordt via fetch() aangeroepen vanuit coin.js na de tweede
    klik op de grafiek, geen paginaherlaad nodig."""
    trendline_id = repo.create_trendline(symbol.upper(), user["id"], label, x1, y1, x2, y2)
    return {"id": trendline_id}


@app.post("/trendlines/{trendline_id}/delete")
async def delete_trendline(trendline_id: int, user: dict = Depends(require_login)):
    repo.delete_trendline(trendline_id, user["id"])
    return {"ok": True}


@app.get("/media/{filename}")
async def media(filename: str, user: dict = Depends(require_login)):
    """Toont een origineel doorgestuurde screenshot. Alleen ingelogde
    gebruikers, en alleen bestanden die echt in de afbeeldingenmap staan,
    tegen het opvragen van willekeurige bestanden via de bestandsnaam."""
    base = Path(config.IMAGE_STORAGE_PATH).resolve()
    target = (base / Path(filename).name).resolve()
    if base not in target.parents or not target.is_file():
        raise HTTPException(status_code=404)
    return FileResponse(target)


@app.get("/api/coins")
async def api_coins(user: dict = Depends(require_login)):
    return repo.list_coins()


@app.get("/api/coin_menu_activity")
async def api_coin_menu_activity(user: dict = Depends(require_login)):
    """Welke coins de laatste 24 uur nog een echt signaal hadden, voor het
    activiteits-stipje in het coin-menu (base.html)."""
    return sorted(repo.coins_with_recent_signal(exclude_types=() if is_ceo(user) else rule_live.CEO_ONLY_TYPES))


@app.get("/api/candles/{symbol}")
async def api_candles(symbol: str, user: dict = Depends(require_login)):
    df = await asyncio.to_thread(exchange.fetch_ohlcv, symbol.upper(), config.TIMEFRAME, 200)
    ema9, ema21 = indicators.ema_series(df)

    candles = [
        {
            "time": int(row.timestamp.timestamp()),
            "open": row.open, "high": row.high, "low": row.low, "close": row.close,
        }
        for row in df.itertuples()
    ]
    ema9_series = [
        {"time": c["time"], "value": v} for c, v in zip(candles, ema9) if v == v
    ]
    ema21_series = [
        {"time": c["time"], "value": v} for c, v in zip(candles, ema21) if v == v
    ]
    pattern_matches = indicators.scan_candle_patterns(df, ema9, ema21)
    patterns = [
        {"time": candles[p["index"]]["time"], "pattern": p["pattern"], "direction": p["direction"]}
        for p in pattern_matches
    ]

    ind = indicators.compute_indicators(df)
    zones = indicators.detect_sr_zones(df)
    # Alleen zones tonen die ook echt meetellen voor de stop/take-verfijning
    # (zelfde afstandsgrens als signal_processor.process_day_trading_signal
    # gebruikt), anders toont de grafiek allerlei ver weg gelegen zones die
    # geen enkele invloed op de trade hebben, puur ruis op het scherm.
    max_distance = indicators.SR_ZONE_MAX_DISTANCE_ATR_MULTIPLE * ind.atr
    sr_zones = [
        {"price_low": z.price_low, "price_high": z.price_high, "touches": z.touches}
        for z in zones
        if abs(z.price_low - ind.price) <= max_distance or abs(z.price_high - ind.price) <= max_distance
    ]

    trendlines = indicators.detect_trendlines(df, ind.atr)

    # Patronen in de maak: de vorm staat er al (wedge/kanaal, of gelijke
    # pieken/dalen), maar de nek/lijn is nog niet doorbroken. Puur
    # informatief — geen entry/stop/target, geen melding, geen signals-rij,
    # zie patterns.py's find_forming_*. Los van de BEVESTIGDE patronen die
    # via de marktscan en signals-tabel binnenkomen (Signalen voor {{ symbol }}
    # hieronder op de pagina). Module hier als chart_patterns geïmporteerd:
    # deze functie heeft al een lokale variabele "patterns" (de candlestick-
    # patronen hierboven), die zou de module anders overschaduwen.
    forming_patterns: list[dict] = []
    wedge_forming = chart_patterns.find_forming_wedge(df, trendlines, ind)
    if wedge_forming:
        forming_patterns.append(wedge_forming)
    forming_patterns += chart_patterns.find_forming_reversal_patterns(df)

    window = df.tail(indicators.SR_ZONE_LOOKBACK).reset_index(drop=True)
    trendline_data = [
        {
            "kind": t.kind,
            "touches": t.touches,
            "points": [
                {"time": candles[len(candles) - len(window) + t.first_index]["time"], "price": t.value_at(t.first_index)},
                {"time": candles[-1]["time"], "price": t.value_at(len(window) - 1)},
            ],
        }
        for t in trendlines
    ]

    return {
        "candles": candles, "ema9": ema9_series, "ema21": ema21_series,
        "patterns": patterns, "sr_zones": sr_zones, "trendlines": trendline_data,
        "forming_patterns": forming_patterns,
    }


def _owner(user: dict) -> dict:
    """Beheer is alleen van de eigenaar; voor iedereen anders bestaat de pagina niet (404, geen 403: een leerling hoort niet te weten dat hij er is)."""
    if not is_ceo(user):
        raise HTTPException(status_code=404)
    return user


@app.get("/beheer")
async def beheer_page(request: Request, fout: str = "", user: dict = Depends(require_login)):
    """Leerlingen, volg-sets en uitnodigingen op één pagina, in die volgorde (ontwerp E). Week-R per leerling is zijn eigen weekterugblik;
    laatst gekeken komt uit user_visits en ontbreekt als hij nooit keek."""
    _owner(user)
    now = datetime.now(timezone.utc)
    visits = repo.visit_stats(now)
    sets = repo.list_follow_sets()
    names = {s["id"]: s["name"] for s in sets}
    students = []
    for u in repo.list_users():
        if u["id"] == user["id"]:
            continue
        students.append({"id": u["id"], "name": u["username"], "initials": beheer.initials(u["username"]), "set_id": u.get("follow_set_id"),
                         "set": names.get(u.get("follow_set_id"), "Geen set"), "week_r": _week_review(u, now)["total_text"],
                         "seen": beheer.seen_text((visits.get(u["id"]) or {}).get("last_at"), now)})
    invites = [{**i, "line": beheer.invite_line(i, now), "usable": beheer.invite_usable(i, now)} for i in repo.list_invites()]
    return templates.TemplateResponse(request, "beheer.html", {
        "user": user, "students": students, "sets": sets, "invites": invites, "open_invites": sum(1 for i in invites if i["usable"]),
        "invite_required": config.REGISTRATION_REQUIRES_INVITE, "fout": fout[:120]})


@app.post("/beheer/sets")
async def beheer_set_create(name: str = Form(""), coins: str = Form(""), user: dict = Depends(require_login)):
    _owner(user)
    name = name.strip()[:40]
    if not name or repo.create_follow_set(name, beheer.parse_coins(coins)) is None:
        return RedirectResponse("/beheer?fout=" + ("Geef de set een naam." if not name else "Er is al een set met deze naam.") + "#sets", status_code=303)
    return RedirectResponse("/beheer#sets", status_code=303)


@app.post("/beheer/sets/{set_id}/coins")
async def beheer_set_coins(set_id: int, coins: str = Form(""), user: dict = Depends(require_login)):
    _owner(user)
    repo.update_follow_set(set_id, beheer.parse_coins(coins))
    return RedirectResponse("/beheer#sets", status_code=303)


@app.post("/beheer/sets/{set_id}/verwijder")
async def beheer_set_delete(set_id: int, user: dict = Depends(require_login)):
    _owner(user)
    repo.delete_follow_set(set_id)
    return RedirectResponse("/beheer#sets", status_code=303)


@app.post("/beheer/leerling/{student_id}/set")
async def beheer_student_set(student_id: int, set_id: str = Form(""), user: dict = Depends(require_login)):
    _owner(user)
    valid = {s["id"] for s in repo.list_follow_sets()}
    chosen = int(set_id) if set_id.isdigit() and int(set_id) in valid else None
    if repo.get_user(student_id):
        repo.set_user_follow_set(student_id, chosen)
    return RedirectResponse("/beheer#leerlingen", status_code=303)


INVITE_MAX_USES = 100
INVITE_MAX_DAYS = 90


@app.post("/beheer/uitnodiging")
async def beheer_invite_create(set_id: str = Form(""), uses: int = Form(1), days: int = Form(7), user: dict = Depends(require_login)):
    _owner(user)
    valid = {s["id"] for s in repo.list_follow_sets()}
    chosen = int(set_id) if set_id.isdigit() and int(set_id) in valid else None
    expires = (datetime.now(timezone.utc) + timedelta(days=max(1, min(days, INVITE_MAX_DAYS)))).isoformat()
    for _ in range(10):         # een botsing met een bestaande code is zeldzaam; dan een nieuwe
        if repo.create_invite(beheer.new_code(), chosen, max(1, min(uses, INVITE_MAX_USES)), expires):
            break
    return RedirectResponse("/beheer#uitnodigen", status_code=303)


@app.post("/beheer/uitnodiging/{invite_id}/verwijder")
async def beheer_invite_delete(invite_id: int, user: dict = Depends(require_login)):
    _owner(user)
    repo.delete_invite(invite_id)
    return RedirectResponse("/beheer#uitnodigen", status_code=303)


@app.get("/ceo")
async def ceo_page(request: Request, user: dict = Depends(require_login)):
    """De startpagina: de CEO. Alleen echte gegevens waar het ertoe doet (dagen in functie, aantal leerlingen, het weekresultaat voor de geldregen),
    de rest is de grap. Handelscijfers staan op Bewijs."""
    boss = ceo_user() or user
    rows = report_rows(user)
    week = track_record.week_summary(rows, config.TRACK_RECORD_COST_PCT)
    first = min((track_record._parse(r["created_at"]) for r in rows), default=None)
    now = datetime.now(timezone.utc)
    photo = BASE_DIR / "static" / "ceo.jpg"
    students = ceo.students([u["username"] for u in repo.list_users() if u["id"] != boss["id"]], now.date())
    scrapped = []
    from app.structure_live import should_disable
    for trade_type, name, limit in (("structuur", "Structuur", config.STRUCTURE_MAX_NEGATIVE), ("trend", "Trend-pullback", config.TREND_MAX_NEGATIVE),
                                    ("rejectie", "Rejectie", config.REJECTION_MAX_NEGATIVE), ("script", "Markt-script", config.SCRIPT_MAX_NEGATIVE),
                                    ("samenval", "Samenval", config.SAMENVAL_MAX_NEGATIVE)):
        if should_disable(repo.list_type_results(trade_type, limit), limit):
            scrapped.append({"name": name, "limit": limit})
    presence = None
    if is_ceo(user):
        stats = repo.visit_stats(now)
        presence = sorted(
            ({"name": u["username"], **stats.get(u["id"], {"views": 0, "active_days": 0, "last_at": None})} for u in repo.list_users()),
            key=lambda p: (-p["views"], p["name"].lower()))
    return templates.TemplateResponse(request, "ceo.html", {
        "presence": presence, "scrapped": scrapped,
        "user": user, "boss": boss, "days_in_office": (now - first).days if first else 0,
        "quote": ceo.quote_of_the_day(now.date()), "rain": ceo.rain_count(week["net_r"]), "students": students,
        "photo": f"/static/ceo.jpg?v={int(photo.stat().st_mtime)}" if photo.exists() else None,
    })
