"""FastAPI webdashboard. Meerdere gebruikers mogelijk, elk met een eigen
login, eigen portfolio en eigen logboek. Iedereen ziet dezelfde signalen.
Open registratie op /registreer. Draai met:
uvicorn web.main:app --host 0.0.0.0 --port 8000
"""
import asyncio
import csv
import io
import json
import logging
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
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app import advice as advice_module
from app import patterns as chart_patterns
from app import config, db, exchange, indicators, market_calendar, notifications_view, push_notify, radar, repo, risk, security, setup_chart, today, track_record
from app.market_scanner import smc_stop_take_margins

logger = logging.getLogger("web")

BASE_DIR = Path(__file__).resolve().parent
def _nav_context(request: Request) -> dict:
    """De coinlijst in het menu staat in elke pagina. Zonder dit moest elke route `coins` zelf meegeven, en de nieuwere
    pagina's (Vandaag, Setups, Bewijs) deden dat niet: het menu klapte open met een lege lijst."""
    return {"coins": repo.list_coins()}


templates = Jinja2Templates(directory=str(BASE_DIR / "templates"), context_processors=[_nav_context])
templates.env.globals["disclaimer"] = config.DISCLAIMER


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

app = FastAPI(title="HesPulse")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


@app.get("/service-worker.js")
async def service_worker():
    """Zelfde bestand als /static/service-worker.js, maar dan op de root
    geserveerd: een service worker kan alleen pagina's binnen zijn eigen
    pad beheren (tenzij de server een Service-Worker-Allowed-header stuurt,
    wat hier niet gebeurt), dus vanaf /static/ zou hij nooit /dashboard
    kunnen bedienen. navigator.serviceWorker.ready op /dashboard bleef
    daardoor voor altijd hangen, precies de oorzaak van de kapotte
    pushmelding-knop. Zie base.html voor de registratie."""
    return FileResponse(
        str(BASE_DIR / "static" / "service-worker.js"), media_type="application/javascript",
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
    return user


# ---------------------------------------------------------------------------
# Openbare landingspagina
# ---------------------------------------------------------------------------

@app.get("/")
async def landing(request: Request):
    token = request.cookies.get(SESSION_COOKIE)
    user_id = security.verify_session_token(token) if token else None
    if user_id and repo.get_user(user_id):
        return RedirectResponse(url="/vandaag", status_code=303)

    now = datetime.now(timezone.utc)
    scripts = repo.latest_scripts()
    return templates.TemplateResponse(request, "landing.html", {
        "timeline": Markup(today.timeline_svg(now, today.agenda(market_calendar.upcoming(now, 24)))), "mood": today.mood(scripts),
        "n_scripts": len(scripts), "now": today.nl_stamp(today.local(now)), "demo_chart": Markup(setup_chart.demo_svg()),
        "kraken_referral_url": config.KRAKEN_REFERRAL_URL,
        "kraken_referral_code": config.KRAKEN_REFERRAL_CODE,
    })


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


@app.get("/signalen")
async def signalen_page(request: Request, alles: bool = False, user: dict = Depends(require_login)):
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
    zelf de sorteersleutel is)."""
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
        "user": user,
        "coins": repo.list_coins(),
        "entries": entries,
        "showing_all": alles,
    })


PRICE_TTL_SECONDS = 10
_price_cache: dict[str, tuple[float, Optional[float]]] = {}


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
    setup["preview_stop_loss"] = setup["sweep_price"] + stop_margin * sign
    setup["preview_take_profit"] = setup["liquidity_target"] + target_margin * sign
    return setup


async def _radar_cards() -> list[dict]:
    forming = [_with_preview(s) for s in repo.list_forming_smc_setups()]
    open_signals = repo.list_open_smc_signals()
    prices = await _cached_prices([s["coin"] for s in forming] + [s["coin"] for s in open_signals])
    cards = [c for s in forming if (c := radar.setup_card(s, prices.get(s["coin"])))]
    cards += [c for s in open_signals if (c := radar.signal_card(s, prices.get(s["coin"])))]
    return cards


async def _structure_cards() -> list[dict]:
    """Wachtende structuur-setups met hun plan, voor de Radar (app/structure_live.py)."""
    setups = repo.list_structure_setups(("waiting",), 12)
    prices = await _cached_prices({s["coin"] for s in setups}) if setups else {}
    cards = []
    for s in setups:
        plan = json.loads(s["plan"])
        cards.append({**s, "plan": plan, "targets": list(zip(plan["targets"], plan["targets_r"])),
                      "chart": Markup(setup_chart.setup_svg(plan.get("candles", []), s, plan, prices.get(s["coin"])))})
    return cards


STRUCTURE_STATE_LABELS = {"geen_plan": "Geen plan: te weinig ruimte of stop buiten bereik", "fired": "Limiet geraakt, signaal gemeld", "expired": "Verlopen, koers kwam niet terug", "niet_gemeld": "Claude keurde af (C)",
                          "overgeslagen": "Stop buiten het toegestane bereik", "geen_oordeel": "Geen oordeel van Claude"}


@app.get("/structuur")
async def structuur_page(request: Request, user: dict = Depends(require_login)):
    """De nieuwe methode: breuk van een lijn of range op 30m met het plan getekend (app/structure_live.py)."""
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    history = [{**h, "state_label": STRUCTURE_STATE_LABELS.get(h["state"], h["state"])}
               for h in repo.list_structure_setups(("fired", "expired", "niet_gemeld", "overgeslagen", "geen_oordeel", "geen_plan"), 40)
               if h["created_at"] >= since]
    beat = repo.get_beat("structuur")
    minutes = None
    if beat:
        minutes = int((datetime.now(timezone.utc) - datetime.fromisoformat(beat["at"])).total_seconds() // 60)
    since24 = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    return templates.TemplateResponse(request, "structuur.html", {
        "user": user, "structure_cards": await _structure_cards(), "history": history,
        "engine_minutes": minutes, "counts": repo.structure_counts(since24), "engine_on": config.STRUCTURE_ENABLED})


@app.get("/smc")
async def smc_page(request: Request, user: dict = Depends(require_login)):
    """Trade Radar: bouwende setups en open SMC-signalen als handelsplan met prijsladder en live status (de limietorder
    staat op de zone-rand, zie app/trade_plan.py), daaronder de afgeronde signalen in dezelfde stijl als /signalen.
    Afgeronde signalen verschijnen ook op /signalen en het dashboard: deze pagina is een extra, gerichte weergave."""
    cards = await _radar_cards()
    entries = [e for e in repo.list_signalen_for_user(user["id"]) if e["trade_type"] == "smc"]
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
        "user": user,
        "setup_cards": [c for c in cards if c["kind"] == "setup"],
        "signal_cards": [c for c in cards if c["kind"] == "signal"],
        "entries": entries,
    })


async def _vandaag_context() -> dict:
    now = datetime.now(timezone.utc)
    scripts_raw = repo.latest_scripts()
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
    summary = track_record.summarize(repo.list_signals_for_quality_report(None), config.TRACK_RECORD_COST_PCT)
    score = [e for e in summary if e["trade_type"] in ("script", "samenval", "smc", "structuur") or e["source"] == "alles"]
    for e in score:
        e["spark"] = Markup(track_record.sparkline_svg(e["cumulative"], width=180, height=36))
    return {
        "now": today.nl_stamp(today.local(now)), "fmt": today.fmt_price, "prices": prices, "scripts": scripts, "mood": today.mood(scripts_raw),
        "timeline": Markup(today.timeline_svg(now, moments)), "moments": moments, "liquidations": liquidations,
        "liq_last": repo.latest_liquidation_bucket(), "events": events, "score": score, "money": today.money,
        "status_labels": track_record.STATUS_LABELS, "script_enabled": config.SCRIPT_ENABLED,
        "structure_cards": structure_cards,
        "plans_ready": len(structure_cards),
        "scenarios_waiting": sum(1 for sc in scripts for x in sc["scenarios"] if x["state"] == "waiting"),
    }


@app.get("/vandaag")
async def vandaag_page(request: Request, user: dict = Depends(require_login)):
    """Cockpit: het markt-script van nu, de agenda van de komende 24 uur, wat beweegt (liquidaties en nieuws) en de score van
    wat HesPulse zelf voorspelde. Alles komt uit app/today.py en de verzamelaars; er staat niets op wat niet gemeten is."""
    return templates.TemplateResponse(request, "vandaag.html", {"user": user, **await _vandaag_context()})


@app.get("/api/vandaag")
async def api_vandaag(user: dict = Depends(require_login)):
    """Live koersen en afstand tot de voorwaarde per scenario, voor vandaag.js."""
    ctx = await _vandaag_context()
    return {
        "prices": ctx["prices"],
        "scenarios": {str(sc["id"]): {"state": sc["state"], "label": sc["state_label"], "to_trigger_pct": sc["to_trigger_pct"],
                                       "hours_left": sc["hours_left"], "ladder": sc["ladder"]}
                      for s in ctx["scripts"] for sc in s["scenarios"]},
    }


@app.get("/api/radar")
async def api_radar(user: dict = Depends(require_login)):
    """Live status per radar-kaart, voor radar.js: nieuwe koers, afstand tot de limietorder, live R en de bijgewerkte ladder."""
    return radar.live_payload(await _radar_cards())


@app.get("/bewijs")
async def bewijs_page(request: Request, user: dict = Depends(require_login)):
    """Eerlijk, automatisch gemeten trackrecord per soort melding in R na kosten (zie app/track_record.py)."""
    summary = track_record.summarize(repo.list_signals_for_quality_report(None), config.TRACK_RECORD_COST_PCT)
    summary.sort(key=lambda e: e["source"] != "alles")      # het totaal bovenaan, de rest in vaste volgorde
    for entry in summary:
        entry["spark"] = Markup(track_record.sparkline_svg(entry["cumulative"]))
    return templates.TemplateResponse(request, "bewijs.html", {
        "user": user, "summary": summary, "status_labels": track_record.STATUS_LABELS,
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
    response = RedirectResponse(url="/vandaag", status_code=303)
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
async def register_form(request: Request):
    return templates.TemplateResponse(request, "register.html", {"error": None})


@app.post("/registreer")
async def register_submit(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    password_confirm: str = Form(...),
):
    ip = request.client.host if request.client else ""

    def error(message: str, status_code: int = 400):
        return templates.TemplateResponse(
            request, "register.html", {"error": message}, status_code=status_code,
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

    security.record_registration_attempt(ip)
    user_id = repo.register_user(username, security.hash_password(password))
    if user_id is None:
        return error("Deze gebruikersnaam is al in gebruik.")

    token = security.create_session_token(user_id)
    response = RedirectResponse(url="/vandaag", status_code=303)
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
        if entry["trade_type"] in ("swing", "smc"):
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
        return 0.0, "23, 229, 214"
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

    return {
        "exchange_ok": exchange_ok,
        "last_message_at": repo.last_message_received_at(),
        "server_started_at": SERVER_STARTED_AT,
        "checked_at": db.now_iso(),
        "pending_count": repo.count_pending_signals(user["id"]),
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
    eval_flag = None
    try:
        result_pct, is_practice = repo.close_journal_trade(entry_id, user["id"], exit_price, exit_time)
        won = (not is_practice) and result_pct > 0
    except ValueError:
        # Geen eigen entry gevonden (niet van deze gebruiker, of nog geen
        # entry prijs ingevuld). Stil negeren, niets om te sluiten.
        pass
    target = _safe_next(next)
    extra_query = []
    if won:
        extra_query.append(("closed_win", "1"))
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
async def coin_page(request: Request, symbol: str, user: dict = Depends(require_login)):
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
    recent_signals = [
        s for s in repo.list_recent_signals(symbol)
        if s["id"] not in open_signal_ids and s["id"] not in ignored_signal_ids
        and (s["stop_loss"] or s["take_profit"])
    ]
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
    sparkline = list(reversed(repo.list_recent_signals(symbol, limit=14)))

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
    return sorted(repo.coins_with_recent_signal())


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
