"""FastAPI webdashboard. Meerdere gebruikers mogelijk, elk met een eigen
login, eigen portfolio en eigen logboek. Iedereen ziet dezelfde signalen.
Open registratie op /registreer. Draai met:
uvicorn web.main:app --host 0.0.0.0 --port 8000
"""
import asyncio
import csv
import io
import logging
import re
import sys
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

from app import advice as advice_module
from app import config, db, exchange, indicators, push_notify, repo, risk, security

logger = logging.getLogger("web")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["disclaimer"] = config.DISCLAIMER

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
        return RedirectResponse(url="/signalen", status_code=303)

    return templates.TemplateResponse(request, "landing.html", {
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
        "notifications": repo.list_notifications(user["id"]),
        "admin_notifications": repo.list_admin_notifications() if is_admin else None,
    })


@app.post("/meldingen/{notification_id}/gelezen")
async def mark_melding_gelezen(notification_id: int, user: dict = Depends(require_login)):
    repo.mark_notification_read(notification_id, user["id"])
    return {"ok": True}


@app.get("/signalen")
async def signalen_page(request: Request, user: dict = Depends(require_login)):
    """Kale, puur signalen-pagina (geen journaal/portfolio-content, zie
    CLAUDE.md 'pure signals'-uitgangspunt van deze taak): dezelfde
    gedeelde signalen als het dashboard, maar hier gesorteerd op hoogste
    slagingspercentage in plaats van chronologisch. Swing-signalen hebben
    geen pass_pct (nog niet gevalideerd op die tijdshorizon, zie
    signal_processor._build_swing_signal) en horen dus niet tussen een op
    percentage gesorteerde lijst; die blijven hier buiten beeld."""
    entries = [
        e for e in repo.list_signalen_for_user(user["id"]) if e["pass_pct"] is not None
    ]
    for entry in entries:
        entry["user_confirmed"] = repo.user_confirmed(
            entry["pass_pct"], bool(entry["hard_gates_ok"]), user["confirm_threshold_pct"]
        )
    entries.sort(key=lambda e: e["pass_pct"], reverse=True)
    return templates.TemplateResponse(request, "signalen.html", {
        "user": user,
        "coins": repo.list_coins(),
        "entries": entries,
    })


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
    response = RedirectResponse(url="/signalen", status_code=303)
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
    response = RedirectResponse(url="/signalen", status_code=303)
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


def _build_eval_context(user: dict, request: Request) -> dict:
    """Evaluatie-simulatie context, gedeeld door het dashboard (compacte
    samenvatting) en de eigen /evaluatie-pagina (volledige weergave). Bij
    een net beëindigde run (geslaagd/mislukt) is er geen actieve run meer
    om te tonen, maar de reveal-melding in de URL vraagt om die laatste
    run toch één keer te laten zien in zijn eindtoestand."""
    active_evaluation = repo.get_active_evaluation(user["id"])
    eval_history = repo.list_evaluations_for_user(user["id"])
    eval_display = active_evaluation
    if not eval_display and (request.query_params.get("evaluatie_geslaagd") or request.query_params.get("evaluatie_mislukt")):
        eval_display = eval_history[0] if eval_history else None

    eval_day_number = None
    eval_daily_loss_used_pct = 0.0
    eval_drawdown_used_pct = 0.0
    eval_profit_progress_pct = 0.0
    eval_daily_results = []
    eval_daily_loss_remaining_eur = None
    eval_next_trade_budget_eur = None
    if eval_display:
        end_reference = (
            datetime.fromisoformat(eval_display["ended_at"]) if eval_display["ended_at"]
            else datetime.now(timezone.utc)
        )
        eval_day_number = (end_reference.date() - datetime.fromisoformat(eval_display["started_at"]).date()).days + 1

        # Is de handelsdag inmiddels doorgeschoven zonder dat er een trade
        # gesloten is (dan is de opgeslagen staat nog van gisteren), dan
        # rekent deze helper al met een verse dag — anders toont de balk en
        # de risk-pulse ademhaling het verlies van een dag die al voorbij
        # is. Zelfde functie als de sizing gebruikt, zodat weergave en
        # blokkade nooit uit elkaar kunnen lopen.
        display_day_start_balance = risk.effective_day_start_balance(eval_display)

        daily_loss_amount = display_day_start_balance * eval_display["max_daily_loss_pct"] / 100
        loss_so_far = max(0.0, display_day_start_balance - eval_display["current_balance"])
        eval_daily_loss_used_pct = min(100.0, (loss_so_far / daily_loss_amount * 100) if daily_loss_amount else 0.0)
        eval_daily_loss_remaining_eur = max(0.0, daily_loss_amount - loss_so_far)
        eval_next_trade_budget_eur = eval_daily_loss_remaining_eur / risk.EVAL_BUDGET_TRADE_RESERVE

        drawdown_amount = eval_display["tier_amount"] * eval_display["max_drawdown_pct"] / 100
        drawdown_so_far = max(0.0, eval_display["tier_amount"] - eval_display["current_balance"])
        eval_drawdown_used_pct = min(100.0, (drawdown_so_far / drawdown_amount * 100) if drawdown_amount else 0.0)

        profit_amount = eval_display["tier_amount"] * eval_display["profit_target_pct"] / 100
        profit_so_far = max(0.0, eval_display["current_balance"] - eval_display["tier_amount"])
        eval_profit_progress_pct = min(100.0, (profit_so_far / profit_amount * 100) if profit_amount else 0.0)

        eval_daily_results = _build_eval_day_dots(repo.list_evaluation_daily_results(eval_display["id"]))

    # Risico van oefentrades die al genomen maar nog niet gesloten zijn:
    # zit nog niet in current_balance verwerkt (dat gebeurt pas op close),
    # dus zonder dit is er geen zicht op wat er gecombineerd op het spel
    # staat als je meerdere oefentrades tegelijk open hebt. Alleen zinvol
    # voor een echt actieve run: een net beëindigde run (eval_display bij
    # de reveal-fallback) kan geen nieuwe open oefentrades meer krijgen.
    eval_open_risk_eur = 0.0
    eval_open_risk_pct = 0.0
    if active_evaluation:
        eval_open_risk_eur = repo.total_open_risk_eur_for_evaluation(active_evaluation["id"])
        eval_open_risk_pct = (
            eval_open_risk_eur / active_evaluation["current_balance"] * 100
            if active_evaluation["current_balance"] else 0.0
        )

    return {
        "eval_display": eval_display,
        "eval_history": eval_history,
        "eval_day_number": eval_day_number,
        "eval_daily_loss_used_pct": eval_daily_loss_used_pct,
        "eval_drawdown_used_pct": eval_drawdown_used_pct,
        "eval_profit_progress_pct": eval_profit_progress_pct,
        "eval_daily_results": eval_daily_results,
        "eval_daily_loss_remaining_eur": eval_daily_loss_remaining_eur,
        "eval_next_trade_budget_eur": eval_next_trade_budget_eur,
        "eval_open_risk_eur": eval_open_risk_eur,
        "eval_open_risk_pct": eval_open_risk_pct,
    }


def _eval_history_stats(eval_history: list[dict]) -> Optional[dict]:
    """Patronen uit afgeronde evaluatie-runs voor de geschiedenis-sectie:
    gemiddeld aantal dagen tot slagen/falen (elk apart pas getoond vanaf 2
    afgeronde runs van dat type, anders is 'gemiddeld' misleidend voor een
    losse uitschieter) en de meest voorkomende faalreden. Geeft None
    terug als er nergens genoeg data voor is."""
    passed = [e for e in eval_history if e["status"] == "geslaagd" and e["ended_at"]]
    failed = [e for e in eval_history if e["status"] == "mislukt" and e["ended_at"]]

    def _avg_days(runs: list[dict]) -> float:
        days = [
            (datetime.fromisoformat(r["ended_at"]).date() - datetime.fromisoformat(r["started_at"]).date()).days + 1
            for r in runs
        ]
        return sum(days) / len(days)

    avg_days_to_pass = _avg_days(passed) if len(passed) >= 2 else None
    avg_days_to_fail = _avg_days(failed) if len(failed) >= 2 else None

    common_fail_reason = None
    if len(failed) >= 2:
        reasons = Counter(r["closed_reason"] for r in failed if r["closed_reason"])
        if reasons:
            common_fail_reason = reasons.most_common(1)[0][0]

    if avg_days_to_pass is None and avg_days_to_fail is None and common_fail_reason is None:
        return None
    return {
        "avg_days_to_pass": avg_days_to_pass,
        "avg_days_to_fail": avg_days_to_fail,
        "common_fail_reason": common_fail_reason,
    }


def _attach_discipline_facts(entries: list[dict]) -> None:
    """Zet trade_number_in_day en risk_percent_used op elke entry die aan
    een evaluatie gekoppeld is (mutatie in place, zelfde patroon als
    entry['position_size'] = _position_size(entry) elders). Puur feiten op
    de kaart zelf, geen oordeel -- de patroonanalyse zit apart in
    _build_discipline_profile. Eén lookup per unieke evaluation_id, niet
    per entry, want list_evaluation_trade_context haalt toch de hele run op."""
    eval_ids = {e["evaluation_id"] for e in entries if e.get("evaluation_id")}
    for eval_id in eval_ids:
        context_by_id = {t["id"]: t for t in repo.list_evaluation_trade_context(eval_id)}
        for entry in entries:
            if entry.get("evaluation_id") == eval_id and entry["id"] in context_by_id:
                ctx = context_by_id[entry["id"]]
                entry["trade_number_in_day"] = ctx["trade_number_in_day"]
                entry["risk_percent_used"] = ctx["risk_percent_used"]


MIN_DISCIPLINE_SAMPLE = 5  # gesloten trades nodig voor de sectie überhaupt te tonen
MIN_BUCKET_SAMPLE = 2  # per uitsplitsing, zelfde drempel als elders (avg_days_to_pass/fail)


def _build_discipline_profile(evaluation_id: int) -> Optional[dict]:
    """Winratio-uitsplitsingen over de gesloten, aan deze run gekoppelde
    trades: per vertrouwen-niveau, per volgnummer die handelsdag (eerste
    trade tegenover latere), en per risicogrootte (eigen mediaan-split,
    geen vast percentage, want dit moet het patroon van déze gebruiker
    laten zien, niet een aanname erover). Puur beschrijvend, geen advies
    -- de evaluatiepagina trekt er zelf geen conclusie uit, dat is aan de
    gebruiker. Geeft None terug als er te weinig gesloten trades zijn om
    iets zinnigs te zeggen, zelfde principe als _eval_history_stats."""
    trades = repo.list_evaluation_trade_context(evaluation_id)
    closed = [t for t in trades if t["result_eur"] is not None]
    if len(closed) < MIN_DISCIPLINE_SAMPLE:
        return None

    def _win_rate_by(group_fn) -> Optional[list[dict]]:
        groups: dict[str, list[dict]] = {}
        for t in closed:
            key = group_fn(t)
            if key is None:
                continue
            groups.setdefault(key, []).append(t)
        rows = [
            {
                "label": label,
                "win_rate": sum(1 for t in group if t["result_eur"] > 0) / len(group) * 100,
                "n": len(group),
            }
            for label, group in groups.items() if len(group) >= MIN_BUCKET_SAMPLE
        ]
        return rows or None

    by_confidence = _win_rate_by(lambda t: t["confidence"])

    by_trade_number = _win_rate_by(
        lambda t: "eerste trade van de dag" if t["trade_number_in_day"] == 1
        else ("latere trade die dag" if t["trade_number_in_day"] and t["trade_number_in_day"] > 1 else None)
    )

    by_risk_size = None
    risk_values = sorted(t["risk_percent_used"] for t in closed if t["risk_percent_used"] is not None)
    if len(risk_values) >= MIN_DISCIPLINE_SAMPLE:
        median_risk = risk_values[len(risk_values) // 2]
        by_risk_size = _win_rate_by(
            lambda t: (
                None if t["risk_percent_used"] is None
                else ("kleiner risico (≤ jouw mediaan)" if t["risk_percent_used"] <= median_risk
                      else "groter risico (> jouw mediaan)")
            )
        )

    if by_confidence is None and by_trade_number is None and by_risk_size is None:
        return None
    return {
        "by_confidence": by_confidence,
        "by_trade_number": by_trade_number,
        "by_risk_size": by_risk_size,
        "sample_size": len(closed),
    }


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


def _add_signal_context(entries: list[dict], winrate: dict) -> list[dict]:
    """Voegt aan elk signaal het concrete advies toe (wat kan je beter
    doen dan nu instappen) en een slagingskans op basis van de eigen
    trackrecord van dit vertrouwen-niveau tot nu toe. Een swing-signaal
    heeft geen vertrouwen-label (zie de spec), dus geen geleende
    day-trading-slagingskans: dat zou een gemeten day-trading-statistiek
    als voorspelling voor een andere soort trade laten doorgaan."""
    for entry in entries:
        entry["advice"] = advice_module.build_advice(entry)
        if entry.get("trade_type") == "swing":
            entry["success_rate"] = None
            entry["success_sample"] = None
            continue
        bucket = "hoog_vertrouwen" if entry.get("confidence") == "hoog vertrouwen" else "laag_vertrouwen"
        stats = winrate[bucket]
        entry["success_rate"] = stats["winrate"]
        entry["success_sample"] = stats["total"]
    return entries


def _position_size(entry: dict) -> Optional[float]:
    """Eigen positiegrootte als die is ingevuld, anders de grootte waarmee de
    trade daadwerkelijk gesized is (journal_entries.position_size, bij het
    aanmaken opgeslagen inclusief de fee-/hefboomcorrectie van een
    evaluatie-trade). Alleen voor oude regels van vóór die kolom bestond
    valt dit terug op een herberekening — die trades kenden nog geen
    kostencorrectie, dus daar ís de kale berekening de juiste waarde."""
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
    prijs en het nog niet gerealiseerde resultaat. Eén prijs-opvraag per
    coin, ook als er meerdere open trades op dezelfde coin staan. De
    exchange-aanroep loopt via to_thread, anders blokkeert die synchrone
    netwerkcall de hele server voor iedereen tegelijk."""
    price_cache: dict[str, Optional[float]] = {}
    for entry in entries:
        entry["position_size"] = _position_size(entry)
        entry["current_price"] = None
        entry["pnl_eur"] = None
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
        entry["pnl_eur"], entry["pnl_pct"] = risk.compute_unrealized_pnl(
            entry["direction"], entry["entry_price"], current_price,
            entry["stop_loss"], entry["risk_eur"],
        )
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
    regels als repo.list_journal, zonder een tweede databasebevraging."""
    if status == "open":
        return [e for e in all_entries if e["status"] != "genegeerd" and e["exit_price"] is None]
    if status == "gesloten":
        return [e for e in all_entries if e["exit_price"] is not None]
    if status == "genegeerd":
        return [e for e in all_entries if e["status"] == "genegeerd"]
    return all_entries


@app.get("/dashboard")
async def dashboard(request: Request, status: str = "alle", user: dict = Depends(require_login)):
    all_entries = repo.list_journal(user["id"], status=None)
    for entry in all_entries:
        entry["position_size"] = _position_size(entry)
        # journal_entries.result_pct is de rauwe koersbeweging van de
        # onderliggende coin, los van positiegrootte. Naast een risicogewogen
        # eurobedrag hoort daar de winst/verlies t.o.v. het eigen risicobedrag
        # van díe trade bij, anders klopt het percentage nooit met het bedrag.
        entry["result_pct_of_risk"] = (
            entry["result_eur"] / entry["risk_eur"] * 100
            if entry["result_eur"] is not None and entry["risk_eur"] else None
        )
    # Oefentrades zijn handmatig aangemaakt om te oefenen, geen echt signaal.
    # Die blijven apart, tellen niet mee in de winrate en staan niet tussen
    # de echte meldingen, anders lijkt het net of het een echt signaal was.
    real_entries = [e for e in all_entries if not e["is_practice"]]
    practice_entries = [e for e in all_entries if e["is_practice"]]

    entries = _filter_journal(real_entries, status)
    winrate = repo.winrate_stats(user["id"])
    open_entries = _add_signal_context(
        await _enrich_open_positions(_filter_journal(real_entries, "open")), winrate,
    )
    # Een pending regel (nog geen eigen entry ingevuld) is geen echte trade,
    # alleen een melding die op een beslissing wacht. Apart getoond van een
    # trade die al echt genomen is, anders lijkt het net of die "gebeurd"
    # is zonder dat de gebruiker er zelf iets voor deed.
    taken_entries = [e for e in open_entries if e["entry_price"] is not None]
    pending_entries = [e for e in open_entries if e["entry_price"] is None]
    _attach_discipline_facts(taken_entries)

    for e in taken_entries:
        e["sltp_progress_pct"] = (
            risk.compute_sltp_progress_pct(e["direction"], e["current_price"], e["stop_loss"], e["take_profit"])
            if e["current_price"] is not None and e["stop_loss"] and e["take_profit"] else None
        )
    # Unieke coins uit echte, open trades voor de topbar-ticker (Sectie 1
    # van de spec) — alleen op het dashboard zelf, waar de 20s-polling van
    # dashboard.js toch al draait om deze prijzen te verversen.
    seen_ticker_coins: set[str] = set()
    ticker_coins = []
    for e in taken_entries:
        if e["coin"] not in seen_ticker_coins:
            seen_ticker_coins.add(e["coin"])
            ticker_coins.append({"coin": e["coin"], "current_price": e["current_price"]})

    # Server-side gevuld voor de EERSTE render van de laatste-seintje-banner
    # (Sectie 2 van de spec): zonder dit blijft de banner leeg tot de eerste
    # /api/system_status-poll na het laden, hetzelfde label-formaat als daar.
    last_signal_row = repo.list_recent_signals_for_user(user["id"], limit=1)
    last_signal_text = None
    if last_signal_row:
        s = last_signal_row[0]
        last_signal_text = f"{s['coin']} · {s['direction']} · {s['confidence']}"

    # Correlatie-waarschuwing: het totale open-risicopercentage hieronder
    # telt euro's bij elkaar op, maar zegt niks over of die posities
    # onafhankelijk van elkaar bewegen. Meerdere gelijktijdige open longs
    # (of shorts) bewegen in de praktijk vaak met elkaar mee (bijvoorbeeld
    # altcoins die BTC volgen), dat voelt als spreiding maar is het niet.
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
        await _enrich_open_positions([e for e in practice_entries if e["exit_price"] is None]), winrate,
    )
    _attach_discipline_facts(practice_open)
    practice_closed = [e for e in practice_entries if e["exit_price"] is not None]
    cumulative = repo.cumulative_result_series(user["id"])
    heatmap_weeks = _build_heatmap_weeks(repo.daily_results(user["id"]))
    ratio_stats = repo.winrate_by_ratio(user["id"])
    coin_stats = repo.coin_stats(user["id"])
    coins = repo.list_coins()
    # Niet herkende berichten zijn een operator-signaal (is de AI-interpretatie
    # goed afgesteld?), geen bruikbare informatie voor een gewone gebruiker:
    # die kan er toch niks mee, en het oogt onbetrouwbaar. Daarom alleen
    # zichtbaar voor de eigen operator-account (ADMIN_USERNAME).
    is_admin = bool(config.ADMIN_USERNAME) and user["username"] == config.ADMIN_USERNAME
    unclear_messages = repo.recent_unclear_messages() if is_admin else None

    eval_ctx = _build_eval_context(user, request)

    # Setup-checklist: alleen zichtbaar zolang niet alle stappen gezet zijn,
    # verdwijnt vanzelf zodra dat wel zo is. "Eerste melding ontvangen" kijkt
    # naar telegram_sent (kolomnaam uit de Telegram-tijd, ongewijzigd sinds
    # Taak 11) op een echt signaal, een voorbeeldmelding (/push/voorbeeld)
    # telt hier bewust niet in mee.
    onboarding = {
        "push_enabled": bool(repo.list_push_subscriptions(user["id"])),
        "portfolio_set": user["portfolio_eur"] > 0,
        "first_alert_received": any(e["telegram_sent"] for e in all_entries),
    }
    onboarding_complete = all(onboarding.values())

    # Risico dat nu echt in de markt staat: alleen trades die al genomen
    # zijn (eigen entry ingevuld), niet nog niet bevestigde signalen, die
    # hebben nog geen kapitaal gekost. Aan een evaluatie gekoppelde trades
    # blijven eruit (zelfde regel als repo.total_open_risk_eur): die zijn
    # tegen het virtuele evaluatiesaldo gesized en horen niet in een
    # percentage van het echte portfolio — hun eigen gauge staat op
    # /evaluatie (eval_open_risk_pct).
    open_risk_eur = sum(e["risk_eur"] or 0 for e in taken_entries if e["evaluation_id"] is None)
    open_risk_pct = (open_risk_eur / user["portfolio_eur"] * 100) if user["portfolio_eur"] else 0

    # Portfolio-omvang schaalt mee met elke gesloten echte trade (zie
    # repo.close_journal_trade), dus het ingevulde bedrag is altijd het
    # actuele kapitaal. "Gestart op" wordt er hier van afgeleid in plaats
    # van apart bijgehouden: startbedrag = huidig bedrag min alles wat er
    # sindsdien gerealiseerd is.
    total_realized_eur = cumulative[-1]["cumulative_eur"] if cumulative else 0.0
    starting_portfolio_eur = user["portfolio_eur"] - total_realized_eur
    portfolio_change_pct = (
        (total_realized_eur / starting_portfolio_eur * 100) if starting_portfolio_eur else 0.0
    )

    return templates.TemplateResponse(request, "dashboard.html", {
        "user": user,
        "onboarding": onboarding,
        "onboarding_complete": onboarding_complete,
        "market_scan_enabled": repo.is_market_scan_enabled(),
        "entries": entries,
        "open_entries": open_entries,
        "taken_entries": taken_entries,
        "pending_entries": pending_entries,
        "ticker_coins": ticker_coins,
        "last_signal_text": last_signal_text,
        "open_risk_eur": open_risk_eur,
        "open_risk_pct": open_risk_pct,
        "correlation_warning": correlation_warning,
        "practice_open": practice_open,
        "practice_closed": practice_closed,
        "winrate": winrate,
        "cumulative": cumulative,
        "heatmap_weeks": heatmap_weeks,
        "ratio_stats": ratio_stats,
        "coin_stats": coin_stats,
        "coins": coins,
        "status_filter": status,
        "starting_portfolio_eur": starting_portfolio_eur,
        "total_realized_eur": total_realized_eur,
        "portfolio_change_pct": portfolio_change_pct,
        "unclear_messages": unclear_messages,
        **eval_ctx,
    })


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
    for entry in all_entries:
        entry["position_size"] = _position_size(entry)
        entry["result_pct_of_risk"] = (
            entry["result_eur"] / entry["risk_eur"] * 100
            if entry["result_eur"] is not None and entry["risk_eur"] else None
        )
    real_entries = [e for e in all_entries if not e["is_practice"]]
    practice_entries = [e for e in all_entries if e["is_practice"]]

    entries = _filter_journal(real_entries, status)
    # Bucketed hoog/laag-vertrouwen winrate, uitsluitend nog nodig als
    # input voor _add_signal_context hieronder (advies op de oefentrade-
    # kaarten): de winrate die deze pagina zelf toont is repo.winrate_for_user
    # verderop, niet dit handmatige-status-gebaseerde cijfer.
    confidence_winrate = repo.winrate_stats(user["id"])
    open_entries = _add_signal_context(
        await _enrich_open_positions(_filter_journal(real_entries, "open")), confidence_winrate,
    )
    taken_entries = [e for e in open_entries if e["entry_price"] is not None]
    pending_entries = [e for e in open_entries if e["entry_price"] is None]
    _attach_discipline_facts(taken_entries)

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
        await _enrich_open_positions([e for e in practice_entries if e["exit_price"] is None]), confidence_winrate,
    )
    _attach_discipline_facts(practice_open)
    practice_closed = [e for e in practice_entries if e["exit_price"] is not None]
    cumulative = repo.cumulative_result_series(user["id"])
    heatmap_weeks = _build_heatmap_weeks(repo.daily_results(user["id"]))
    ratio_stats = repo.winrate_by_ratio(user["id"])
    coin_stats = repo.coin_stats(user["id"])
    coins = repo.list_coins()
    is_admin = bool(config.ADMIN_USERNAME) and user["username"] == config.ADMIN_USERNAME
    unclear_messages = repo.recent_unclear_messages() if is_admin else None

    eval_ctx = _build_eval_context(user, request)

    onboarding = {
        "push_enabled": bool(repo.list_push_subscriptions(user["id"])),
        "threshold_chosen": user["confirm_threshold_set_at"] is not None,
    }
    onboarding_complete = all(onboarding.values())

    total_realized_eur = cumulative[-1]["cumulative_eur"] if cumulative else 0.0
    starting_portfolio_eur = user["portfolio_eur"] - total_realized_eur
    portfolio_change_pct = (
        (total_realized_eur / starting_portfolio_eur * 100) if starting_portfolio_eur else 0.0
    )

    return templates.TemplateResponse(request, "account.html", {
        "user": user,
        "onboarding": onboarding,
        "onboarding_complete": onboarding_complete,
        "market_scan_enabled": repo.is_market_scan_enabled(),
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
        "starting_portfolio_eur": starting_portfolio_eur,
        "total_realized_eur": total_realized_eur,
        "portfolio_change_pct": portfolio_change_pct,
        "unclear_messages": unclear_messages,
        **eval_ctx,
    })


@app.get("/api/open_positions")
async def api_open_positions(user: dict = Depends(require_login)):
    """Ververst de live prijs en PnL van open posities, gebruikt door het
    dashboard om zonder volledige herlaad bij te werken."""
    entries = await _enrich_open_positions(repo.list_journal(user["id"], status="open"))
    return [
        {
            "id": e["id"], "current_price": e["current_price"],
            "pnl_eur": e["pnl_eur"], "pnl_pct": e["pnl_pct"],
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

    active_eval = repo.get_active_evaluation(user["id"])
    if active_eval:
        open_risk_eur = repo.total_open_risk_eur_for_evaluation(active_eval["id"])
        daily_remaining = risk.compute_eval_daily_budget_remaining(active_eval, open_risk_eur)
        drawdown_remaining = risk.compute_eval_drawdown_budget_remaining(active_eval, open_risk_eur)
        daily_budget_total = active_eval["day_start_balance"] * active_eval["max_daily_loss_pct"] / 100
        drawdown_total = active_eval["tier_amount"] * active_eval["max_drawdown_pct"] / 100
        daily_used_pct = max(0.0, (1 - daily_remaining / daily_budget_total) * 100) if daily_budget_total else 0.0
        drawdown_used_pct = max(0.0, (1 - drawdown_remaining / drawdown_total) * 100) if drawdown_total else 0.0
        risk_pct = max(daily_used_pct, drawdown_used_pct)
    else:
        portfolio = user.get("portfolio_eur")
        open_risk = repo.total_open_risk_eur(user["id"])
        risk_pct = (open_risk / portfolio * 100) if portfolio else None

    return {
        "exchange_ok": exchange_ok,
        "last_message_at": repo.last_message_received_at(),
        "server_started_at": SERVER_STARTED_AT,
        "checked_at": db.now_iso(),
        "pending_count": repo.count_pending_signals(user["id"]),
        "unread_notifications": repo.count_unread_notifications(user["id"]),
        "week_result_eur": repo.week_result_eur(user["id"]),
        "volatility_ratio": repo.largest_open_position_volatility(user["id"]),
        "last_signal": last_signal,
        "risk_pct": risk_pct,
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
        "prijs", "stop_loss", "take_profit", "risicobedrag_eur", "status",
        "entry_price", "exit_price", "exit_time", "resultaat_eur", "resultaat_pct", "notitie",
        "evaluatie_gekoppeld",
    ])
    for e in entries:
        writer.writerow([
            e["created_at"], e["coin"], e["direction"], e["confidence"],
            "ja" if e["technical_confirmed"] else "nee",
            e["price"], e["stop_loss"], e["take_profit"], e["risk_eur"], e["status"],
            e["entry_price"], e["exit_price"], e["exit_time"], e["result_eur"], e["result_pct"],
            e["note"] or "",
            # Zonder deze kolom mengen euro's op evaluatie-schaal (tier_amount)
            # zich onopvallend tussen euro's op echte portfolio-schaal in
            # dezelfde risicobedrag_eur/resultaat_eur-kolommen.
            "ja" if e.get("evaluation_id") else "nee",
        ])

    filename = f"hespulse-logboek-{user['username']}.csv"
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@app.post("/settings/portfolio")
async def update_settings(
    portfolio_eur: float = Form(...),
    risk_percent: float = Form(...),
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
    repo.update_user_settings(user["id"], portfolio_eur, risk_percent, start, end)
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/push/voorbeeld")
async def send_demo_push_message(user: dict = Depends(require_login)):
    """Stuurt een testpush naar elk apparaat van de ingelogde gebruiker:
    laat zien hoe een echte melding eruitziet, én bevestigt meteen dat
    het abonnement van dit apparaat werkt."""
    await push_notify.send_push(
        user["id"], "Ξ ETH long, hoog vertrouwen (voorbeeld)",
        "Entry 2340.0000 · Stop 2290.0000 · Take profit 2430.0000",
        "/dashboard", silent=False,
    )
    return RedirectResponse(url="/dashboard", status_code=303)


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


EVAL_DANGER_THRESHOLD_PCT = 85.0  # zelfde drempel als de risk-pulse-animatie elders in de app


async def _check_eval_danger_alert(
    active_eval: dict, progress: risk.PropProgress, evaluation_id: int, user_id: int,
) -> None:
    """Stuurt een pushmelding zodra dagverlies of drawdown de
    85%-drempel passeert op een run die nog actief is (zelfde percentages
    als _build_eval_context laat zien op de evaluatiepagina). Vuurt maar
    één keer per overschrijding: danger_alert_sent voorkomt herhaling op
    elke volgende trade-close, en wordt teruggezet zodra het percentage
    weer onder de drempel zakt, zodat een latere nieuwe overschrijding in
    dezelfde run wél weer gemeld wordt."""
    daily_loss_amount = progress.day_start_balance * active_eval["max_daily_loss_pct"] / 100
    loss_so_far = max(0.0, progress.day_start_balance - progress.current_balance)
    daily_loss_used_pct = min(100.0, (loss_so_far / daily_loss_amount * 100) if daily_loss_amount else 0.0)
    daily_remaining_eur = max(0.0, daily_loss_amount - loss_so_far)

    drawdown_amount = active_eval["tier_amount"] * active_eval["max_drawdown_pct"] / 100
    drawdown_so_far = max(0.0, active_eval["tier_amount"] - progress.current_balance)
    drawdown_used_pct = min(100.0, (drawdown_so_far / drawdown_amount * 100) if drawdown_amount else 0.0)
    drawdown_remaining_eur = max(0.0, drawdown_amount - drawdown_so_far)

    in_danger_zone = daily_loss_used_pct >= EVAL_DANGER_THRESHOLD_PCT or drawdown_used_pct >= EVAL_DANGER_THRESHOLD_PCT
    if not in_danger_zone:
        if active_eval["danger_alert_sent"]:
            repo.set_evaluation_danger_alert_sent(evaluation_id, False)
        return

    if active_eval["danger_alert_sent"]:
        return

    if drawdown_used_pct >= daily_loss_used_pct:
        pct_type, pct_value, remaining_eur = "drawdown", drawdown_used_pct, drawdown_remaining_eur
    else:
        pct_type, pct_value, remaining_eur = "dagverlies", daily_loss_used_pct, daily_remaining_eur

    title = f"Evaluatie: {pct_type} op {pct_value:.0f}%"
    body = f"Nog {remaining_eur:.0f} EUR ruimte over van {active_eval['tier_amount']:.0f} EUR tier."
    await push_notify.send_push(user_id, title, body, "/evaluatie", silent=False)
    repo.set_evaluation_danger_alert_sent(evaluation_id, True)


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
        result_eur, is_practice, evaluation_id = repo.close_journal_trade(entry_id, user["id"], exit_price, exit_time)
        won = (not is_practice) and result_eur > 0
        if evaluation_id:
            active_eval = repo.get_evaluation(evaluation_id)
            # Een run die al eerder is afgesloten (door een andere trade,
            # of handmatig gestopt) is bevroren: dit resultaat telt niet
            # meer mee, zie de spec.
            if active_eval and active_eval["status"] == "actief":
                # BEWUST datetime.now(timezone.utc), NIET exit_time: exit_time
                # is een naive, browser-LOKALE tijd (<input type="datetime-local">,
                # zie close_journal_trade's eigen comment daarover), terwijl
                # trading_day_label een UTC-instant verwacht (Kraken's 00:30 UTC-
                # grens). risk.effective_day_start_balance en repo.create_evaluation
                # gebruiken ALLEBEI nog steeds now(timezone.utc) voor dezelfde
                # grens — hier overschakelen naar exit_time zou die drie uit
                # elkaar trekken en kan een echte dagverlies-overtreding stil
                # laten slagen (met een offset-tijdzone gebruiker, geverifieerd
                # in review). Eerder overwogen als fix voor "inconsistent met
                # de exit_time-gebaseerde dag-groepering in
                # list_evaluation_daily_results/list_evaluation_balance_curve",
                # maar die twee zijn puur weergave; dit hier is de pass/fail-poort
                # en moet op dezelfde basis blijven als de andere twee.
                progress = risk.evaluate_prop_progress(active_eval, result_eur, datetime.now(timezone.utc))
                repo.update_evaluation_state(
                    evaluation_id, progress.current_balance, progress.day_start_balance, progress.day_start_date,
                )
                if progress.status != "actief":
                    repo.close_evaluation(evaluation_id, progress.status, progress.closed_reason)
                    eval_flag = "evaluatie_geslaagd" if progress.status == "geslaagd" else "evaluatie_mislukt"
                else:
                    await _check_eval_danger_alert(active_eval, progress, evaluation_id, user["id"])
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


@app.post("/evaluatie/start")
async def start_evaluation(
    tier_amount: float = Form(...),
    profit_target_pct: float = Form(...),
    max_drawdown_pct: float = Form(...),
    user: dict = Depends(require_login),
):
    if (
        tier_amount not in PROP_EVAL_TIERS
        or not (0 < profit_target_pct <= 50)
        or not (0 < max_drawdown_pct <= 50)
        or repo.get_active_evaluation(user["id"]) is not None
    ):
        # Ongeldige input of dubbele start (bv. twee tabbladen tegelijk):
        # stil negeren, het dashboard toont sowieso alleen het
        # startformulier als er nog geen actieve run is.
        return RedirectResponse(url="/evaluatie", status_code=303)
    repo.create_evaluation(user["id"], tier_amount, profit_target_pct, max_drawdown_pct)
    return RedirectResponse(url="/evaluatie", status_code=303)


@app.post("/evaluatie/stop")
async def stop_evaluation(user: dict = Depends(require_login)):
    active = repo.get_active_evaluation(user["id"])
    if active:
        repo.close_evaluation(active["id"], "gestopt", "handmatig gestopt")
    return RedirectResponse(url="/evaluatie", status_code=303)


@app.get("/evaluatie")
async def evaluatie_page(request: Request, user: dict = Depends(require_login)):
    eval_ctx = _build_eval_context(user, request)
    eval_display = eval_ctx["eval_display"]
    balance_curve = repo.list_evaluation_balance_curve(eval_display["id"]) if eval_display else []
    eval_stats = _eval_history_stats(eval_ctx["eval_history"])
    eval_coaching_tip = _eval_coaching_tip(
        eval_display, eval_ctx["eval_daily_loss_used_pct"], eval_ctx["eval_drawdown_used_pct"],
        eval_ctx["eval_profit_progress_pct"],
    )
    discipline_profile = _build_discipline_profile(eval_display["id"]) if eval_display else None

    return templates.TemplateResponse(request, "evaluatie.html", {
        "user": user,
        "coins": repo.list_coins(),
        "balance_curve": balance_curve,
        "eval_stats": eval_stats,
        "eval_coaching_tip": eval_coaching_tip,
        "discipline_profile": discipline_profile,
        **eval_ctx,
    })


# ---------------------------------------------------------------------------
# Oefentrades: handmatig een richting kiezen om te oefenen met de volledige
# technische toetsing en risicoberekening, zonder dat er een echt signaal
# via Discord voor nodig is. Telt niet mee in de echte winrate/resultaten.
# ---------------------------------------------------------------------------

async def _fetch_practice_trade_calc(symbol: str, direction: str):
    """Live technische berekening voor een oefentrade: candles ophalen,
    indicatoren en stop loss/take profit. Gedeeld door het daadwerkelijk
    aanmaken van een oefentrade en de live-voorbeeldroute ervoor, zodat de
    preview nooit kan afwijken van wat er bij versturen echt gebeurt."""
    df = await asyncio.to_thread(exchange.fetch_ohlcv, symbol)
    ind = indicators.compute_indicators(df)
    swing_low, swing_high = indicators.swing_levels(df)
    stop_take = risk.compute_stop_take(direction, ind.price, ind.atr, swing_low=swing_low, swing_high=swing_high)
    return df, ind, stop_take


def _resolve_practice_risk_eur(
    user: dict, active_eval: Optional[dict], manual_risk_eur: Optional[float],
    direction: str, entry_price: float, stop_loss: float, take_profit: float,
) -> tuple[float, Optional[str], bool, Optional[float], float, bool, float, float]:
    """Risicobedrag voor een oefentrade, en cost_rate voor de fee-aanpassing
    van compute_position_size (Task 3). Zonder actieve evaluatie: exact
    zoals bij een echt signaal zonder evaluatie, handmatige invoer of
    portfolio_eur x risk_percent, geen fees. Met actieve evaluatie EN
    voldoende budget: dezelfde dagbudget/drawdown/hefboom-grenzen als een
    echt signaal (risk.compute_eval_risk_eur), en handmatige invoer wordt
    daar nu OOK door gecapt, niet alleen door de hefboomlimiet. Met actieve
    evaluatie maar geblokkeerd budget (risk.eval_sizing_blocked): gedraagt
    de trade zich VOLLEDIG alsof er geen actieve evaluatie is, exact zoals
    signal_processor._resolve_signal_risk bij een echt signaal (sectie 3
    van de spec) — normale portfolio-sizing, geen cap, en niet aan de
    evaluatie gekoppeld, anders blijft een ongecapt handmatig bedrag toch
    meetellen in repo.total_open_risk_eur_for_evaluation voor latere
    sizing op diezelfde run. Geeft (risk_eur, notitie-of-None, is-gecapt,
    max-toegestaan-of-None, cost_rate, link_to_evaluation, effective_stop_loss,
    effective_take_profit) — de aanroeper gebruikt link_to_evaluation om
    evaluation_id wel/niet mee te geven aan create_journal_entry, en de
    effectieve stop/take vervangen de ruwe waarden overal waar die verder
    gebruikt worden (sizing, opslag, weergave)."""
    if not active_eval:
        computed_risk_eur = (
            manual_risk_eur if manual_risk_eur is not None
            else risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"])
        )
        return computed_risk_eur, None, False, None, 0.0, False, stop_loss, take_profit

    open_risk_eur = repo.total_open_risk_eur_for_evaluation(active_eval["id"])
    if risk.eval_sizing_blocked(active_eval, open_risk_eur):
        computed_risk_eur = (
            manual_risk_eur if manual_risk_eur is not None
            else risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"])
        )
        leverage_note = (
            "Systeem: dagbudget of drawdown-ruimte van je evaluatie is (bijna) op, "
            "deze oefentrade telt niet mee voor je evaluatie."
        )
        return computed_risk_eur, leverage_note, False, None, 0.0, False, stop_loss, take_profit

    max_pct = risk.eval_max_stop_pct(active_eval["tier_amount"])
    capped_stop = risk.apply_eval_stop_cap(direction, entry_price, stop_loss, take_profit, max_pct)
    max_risk_eur = risk.compute_eval_risk_eur(
        active_eval, user["risk_percent"], open_risk_eur, entry_price, capped_stop.stop_loss,
    )
    cost_rate = risk.EVAL_TRADE_FEE_RATE + risk.EVAL_LEVERAGE_DAILY_RATE * risk.EVAL_SIZING_DAYS_ASSUMPTION
    requested_risk_eur = manual_risk_eur if manual_risk_eur is not None else max_risk_eur
    capped = requested_risk_eur > max_risk_eur > 0
    computed_risk_eur = min(requested_risk_eur, max_risk_eur) if max_risk_eur > 0 else requested_risk_eur
    leverage_note = (
        f"Systeem: risico verlaagd van €{requested_risk_eur:.2f} naar €{computed_risk_eur:.2f} "
        f"om binnen de regels van je evaluatie te blijven."
    ) if capped else None
    return (
        computed_risk_eur, leverage_note, capped, max_risk_eur, cost_rate, True,
        capped_stop.stop_loss, capped_stop.take_profit,
    )


@app.post("/coins/{symbol}/oefen-preview")
async def preview_practice_trade(
    symbol: str,
    direction: str = Form(...),
    risk_eur: str = Form(""),
    user: dict = Depends(require_login),
):
    """Live rekenhulp voor het oefentrade-formulier: dezelfde technische
    berekening en hefboom-cap als het echte aanmaken, maar slaat niets op.
    Laat je vooraf zien welke positie en of die gecapt wordt, in plaats
    van dat achteraf op de trade-kaart te ontdekken."""
    symbol = symbol.upper()
    if direction not in ("long", "short") or not repo.coin_is_tracked(symbol):
        return JSONResponse({"error": "ongeldige coin of richting"}, status_code=400)

    # Geen voor-invulling bij een leeg risicoveld: _resolve_practice_risk_eur
    # leest None zelf als "bepaal het bedrag", en dat valt met een actieve
    # evaluatie op het evaluatie-bedrag uit, niet op portfolio x risk_percent.
    # De aanmaakroute geeft None door, dus hier ook — anders toont de preview
    # een ander bedrag dan er bij versturen echt gebruikt wordt.
    manual_risk_eur = _parse_optional_float(risk_eur)

    _df, ind, stop_take = await _fetch_practice_trade_calc(symbol, direction)
    active_eval = repo.get_active_evaluation(user["id"])
    (
        used_risk_eur, leverage_note, capped, max_risk_eur, cost_rate, _link_to_evaluation,
        effective_stop_loss, effective_take_profit,
    ) = _resolve_practice_risk_eur(
        user, active_eval, manual_risk_eur, direction, ind.price, stop_take.stop_loss, stop_take.take_profit,
    )
    position_size = risk.compute_position_size(used_risk_eur, ind.price, effective_stop_loss, cost_rate=cost_rate)
    notional_eur = (position_size * ind.price) if position_size else None

    return JSONResponse({
        "entry_price": ind.price,
        "stop_loss": effective_stop_loss,
        "take_profit": effective_take_profit,
        "requested_risk_eur": manual_risk_eur,
        "used_risk_eur": used_risk_eur,
        "position_size": position_size,
        "notional_eur": notional_eur,
        "capped": capped,
        "max_risk_eur": max_risk_eur,
        "note": leverage_note,
    })


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
    # Zonder dit toont dezelfde open evaluatie-trade wel "2e trade vandaag"
    # op het dashboard maar niets op de coin-pagina: allebei renderen via
    # macros.open_trade_body, dus allebei hebben deze feiten nodig.
    _attach_discipline_facts(open_trades)
    # Zelfde reden: macros.open_trade_body's SL/TP-voortgangsbalk leest
    # sltp_progress_pct, dat de dashboard-route al zet maar deze route nog
    # niet — zonder dit rendert de balk hier met een lege/ongeldige
    # "width: %" in plaats van gewoon weggelaten te worden.
    for e in open_trades:
        e["sltp_progress_pct"] = (
            risk.compute_sltp_progress_pct(e["direction"], e["current_price"], e["stop_loss"], e["take_profit"])
            if e["current_price"] is not None and e["stop_loss"] and e["take_profit"] else None
        )
    open_signal_ids = {e["signal_id"] for e in open_trades}
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
        if s["id"] not in open_signal_ids and (s["stop_loss"] or s["take_profit"])
    ]
    for s in recent_signals:
        s.setdefault("entry_price", None)  # signalen zijn geen journal-rijen, dat veld bestaat niet
        pending_entry = pending_by_signal_id.get(s["id"])
        if pending_entry is not None:
            s["stop_loss"] = pending_entry["stop_loss"]
            s["take_profit"] = pending_entry["take_profit"]
    for entry in recent_signals:
        entry["user_confirmed"] = repo.user_confirmed(
            entry["pass_pct"], bool(entry["hard_gates_ok"]), user["confirm_threshold_pct"]
        )
    winrate = repo.winrate_stats(user["id"])
    open_trades = _add_signal_context(open_trades, winrate)
    recent_signals = _add_signal_context(recent_signals, winrate)

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

    # Trackrecord van de community zelf: klopte de lange-termijn richting
    # achteraf. Vereist een live koers, mislukt die (exchange down, coin
    # niet (meer) verhandelbaar) dan blijft dit gewoon leeg in plaats van de
    # hele pagina te breken.
    long_term_track_record = None
    try:
        current_price = await asyncio.to_thread(exchange.fetch_last_price, symbol)
        long_term_track_record = repo.coin_long_term_track_record(symbol, current_price)
    except Exception:
        logger.exception("Live prijs voor trackrecord van %s kon niet opgehaald worden", symbol)

    coin = repo.get_coin(symbol)
    active_swing_watches = repo.active_swing_watches_for_coin(symbol)
    coin_narratives = repo.list_narratives_for_coin(symbol)
    for narrative in coin_narratives:
        narrative["timeline"] = repo.list_narrative_messages(narrative["id"])

    narrative_updates = [
        {"received_at": entry["received_at"], "direction": narrative["direction"]}
        for narrative in coin_narratives
        for entry in narrative["timeline"]
    ]

    active_evaluation = repo.get_active_evaluation(user["id"])

    return templates.TemplateResponse(request, "coin.html", {
        "user": user,
        "active_evaluation": active_evaluation,
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
        "long_term_track_record": long_term_track_record,
        "coin_note": coin["note"] if coin else None,
        "is_muted": repo.is_coin_muted(user["id"], symbol),
        "active_swing_watches": active_swing_watches,
        "coin_narratives": coin_narratives,
        "narrative_updates": narrative_updates,
    })


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
    return RedirectResponse(url="/dashboard", status_code=303)


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
    }
