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
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import advice as advice_module
from app import config, db, exchange, explain, indicators, repo, risk, security, telegram_notify
from app.signal_processor import compute_advanced_extra_factors

logger = logging.getLogger("web")

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.globals["disclaimer"] = config.DISCLAIMER

app = FastAPI(title="HesPulse")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

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
        return RedirectResponse(url="/dashboard", status_code=303)

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
    Telegram koppelen, hoog vertrouwen), maar bereikbaar voor wie al is
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
    response = RedirectResponse(url="/dashboard", status_code=303)
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
    response = RedirectResponse(url="/dashboard", status_code=303)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=config.SESSION_HOURS * 3600)
    return response


# ---------------------------------------------------------------------------
# Dashboard startpagina
# ---------------------------------------------------------------------------

def _add_signal_context(entries: list[dict], winrate: dict) -> list[dict]:
    """Voegt aan elk signaal het concrete advies toe (wat kan je beter
    doen dan nu instappen) en een slagingskans op basis van de eigen
    trackrecord van dit vertrouwen-niveau tot nu toe."""
    for entry in entries:
        entry["advice"] = advice_module.build_advice(entry)
        bucket = "hoog_vertrouwen" if entry.get("confidence") == "hoog vertrouwen" else "laag_vertrouwen"
        stats = winrate[bucket]
        entry["success_rate"] = stats["winrate"]
        entry["success_sample"] = stats["total"]
    return entries


def _position_size(entry: dict) -> Optional[float]:
    """Eigen positiegrootte als die is ingevuld, anders de berekende waarde
    op basis van risicobedrag en stop-afstand."""
    if entry.get("position_size_override") is not None:
        return entry["position_size_override"]
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
    practice_closed = [e for e in practice_entries if e["exit_price"] is not None]
    cumulative = repo.cumulative_result_series(user["id"])
    ratio_stats = repo.winrate_by_ratio(user["id"])
    coin_stats = repo.coin_stats(user["id"])
    coins = repo.list_coins()
    # Niet herkende berichten zijn een operator-signaal (is de AI-interpretatie
    # goed afgesteld?), geen bruikbare informatie voor een gewone gebruiker:
    # die kan er toch niks mee, en het oogt onbetrouwbaar. Daarom alleen
    # zichtbaar voor de eigen operator-account (ADMIN_TELEGRAM_CHAT_ID).
    is_admin = bool(config.ADMIN_TELEGRAM_CHAT_ID) and user["telegram_chat_id"] == config.ADMIN_TELEGRAM_CHAT_ID
    unclear_messages = repo.recent_unclear_messages() if is_admin else None

    # Setup-checklist: alleen zichtbaar zolang niet alle stappen gezet zijn,
    # verdwijnt vanzelf zodra dat wel zo is. "Eerste melding ontvangen" kijkt
    # naar telegram_sent op een echt signaal, een voorbeeldmelding
    # (/telegram/voorbeeld) telt hier bewust niet in mee.
    onboarding = {
        "telegram_linked": bool(user["telegram_chat_id"]),
        "portfolio_set": user["portfolio_eur"] > 0,
        "first_alert_received": any(e["telegram_sent"] for e in all_entries),
    }
    onboarding_complete = all(onboarding.values())

    # Risico dat nu echt in de markt staat: alleen trades die al genomen
    # zijn (eigen entry ingevuld), niet nog niet bevestigde signalen, die
    # hebben nog geen kapitaal gekost.
    open_risk_eur = sum(e["risk_eur"] or 0 for e in taken_entries)
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
        "entries": entries,
        "open_entries": open_entries,
        "taken_entries": taken_entries,
        "pending_entries": pending_entries,
        "open_risk_eur": open_risk_eur,
        "open_risk_pct": open_risk_pct,
        "correlation_warning": correlation_warning,
        "practice_open": practice_open,
        "practice_closed": practice_closed,
        "winrate": winrate,
        "cumulative": cumulative,
        "ratio_stats": ratio_stats,
        "coin_stats": coin_stats,
        "coins": coins,
        "status_filter": status,
        "starting_portfolio_eur": starting_portfolio_eur,
        "total_realized_eur": total_realized_eur,
        "portfolio_change_pct": portfolio_change_pct,
        "unclear_messages": unclear_messages,
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
    return {
        "exchange_ok": exchange_ok,
        "last_message_at": repo.last_message_received_at(),
        "server_started_at": SERVER_STARTED_AT,
        "checked_at": db.now_iso(),
        "pending_count": repo.count_pending_signals(user["id"]),
        "week_result_eur": repo.week_result_eur(user["id"]),
    }


@app.get("/export/logboek.csv")
async def export_journal_csv(user: dict = Depends(require_login)):
    entries = repo.list_journal(user["id"], status=None, limit=100000)

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow([
        "tijdstip", "coin", "richting", "vertrouwen", "technisch_bevestigd",
        "prijs", "stop_loss", "take_profit", "risicobedrag_eur", "status",
        "entry_price", "exit_price", "exit_time", "resultaat_eur", "resultaat_pct", "notitie",
    ])
    for e in entries:
        writer.writerow([
            e["created_at"], e["coin"], e["direction"], e["confidence"],
            "ja" if e["technical_confirmed"] else "nee",
            e["price"], e["stop_loss"], e["take_profit"], e["risk_eur"], e["status"],
            e["entry_price"], e["exit_price"], e["exit_time"], e["result_eur"], e["result_pct"],
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
    portfolio_eur: float = Form(...),
    risk_percent: float = Form(...),
    telegram_chat_id: str = Form(""),
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
    repo.update_user_settings(
        user["id"], portfolio_eur, risk_percent, telegram_chat_id.strip() or None, start, end,
    )
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/telegram/voorbeeld")
async def send_demo_telegram_message(user: dict = Depends(require_login)):
    """Stuurt een voorbeeldmelding naar de gekoppelde Telegram chat van de
    ingelogde gebruiker, zodat die meteen ziet hoe een echte kans eruitziet
    zonder op een echt signaal te hoeven wachten."""
    if user["telegram_chat_id"]:
        await telegram_notify.send_demo_signal_message(user["telegram_chat_id"])
    return RedirectResponse(url="/dashboard", status_code=303)


@app.post("/journal/{entry_id}/status")
async def update_journal_status(
    entry_id: int,
    status: str = Form(...),
    entry_price: str = Form(""),
    user: dict = Depends(require_login),
):
    entry = float(entry_price) if entry_price.strip() else None
    repo.update_journal_status(entry_id, user["id"], status, entry_price=entry)
    return RedirectResponse(url="/dashboard", status_code=303)


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
    try:
        repo.close_journal_trade(entry_id, user["id"], exit_price, exit_time)
    except ValueError:
        # Geen eigen entry gevonden (niet van deze gebruiker, of nog geen
        # entry prijs ingevuld). Stil negeren, niets om te sluiten.
        pass
    return RedirectResponse(url=_safe_next(next), status_code=303)


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
    user: dict = Depends(require_login),
):
    """Een oefentrade heeft geen echte melding om naar terug te vallen,
    dus 'weggooien' verwijdert de regel echt, anders dan de 'Terugzetten'
    knop bij een echte trade."""
    repo.delete_practice_entry(entry_id, user["id"])
    return RedirectResponse(url="/dashboard", status_code=303)


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
    user: dict = Depends(require_login),
):
    repo.update_journal_note(entry_id, user["id"], note)
    return RedirectResponse(url="/dashboard", status_code=303)


# ---------------------------------------------------------------------------
# Oefentrades: handmatig een richting kiezen om te oefenen met de volledige
# technische toetsing en risicoberekening, zonder dat er een echt signaal
# via Discord voor nodig is. Telt niet mee in de echte winrate/resultaten.
# ---------------------------------------------------------------------------

@app.post("/coins/{symbol}/oefen")
async def create_practice_trade(
    symbol: str,
    direction: str = Form(...),
    user: dict = Depends(require_login),
):
    symbol = symbol.upper()
    if direction not in ("long", "short") or not repo.coin_is_tracked(symbol):
        return RedirectResponse(url=f"/coins/{symbol}", status_code=303)

    df = await asyncio.to_thread(exchange.fetch_ohlcv, symbol)
    ind = indicators.compute_indicators(df)
    swing_low, swing_high = indicators.swing_levels(df)

    extra_factors = None
    if config.ENABLE_ADVANCED_FACTORS:
        extra_factors = await compute_advanced_extra_factors(symbol, direction, df)
    confirmed, reason = indicators.confirms_direction(
        ind, direction, extra_factors=extra_factors, include_advanced=config.ENABLE_ADVANCED_FACTORS,
    )
    stop_take = risk.compute_stop_take(direction, ind.price, ind.atr, swing_low=swing_low, swing_high=swing_high)

    confidence = "hoog vertrouwen" if confirmed else "laag vertrouwen"
    plain_explanation = await asyncio.to_thread(
        explain.explain_signal, symbol, direction, confidence, reason,
        ind.price, stop_take.stop_loss, stop_take.take_profit,
    )

    message_id = repo.insert_message("Handmatige oefentrade", [])
    repo.mark_message_processed(
        message_id, symbol, direction, "oefening", False,
        note="Handmatige oefentrade, aangemaakt vanaf het dashboard",
    )
    signal_id = repo.insert_signal({
        "message_id": message_id, "coin": symbol, "direction": direction, "category": "oefening",
        "price": ind.price, "rsi": ind.rsi, "macd": ind.macd, "macd_signal": ind.macd_signal,
        "volume_ratio": ind.volume_ratio, "ema9": ind.ema9, "ema21": ind.ema21, "atr": ind.atr,
        "atr_avg20": ind.atr_avg20, "adx": ind.adx,
        "technical_confirmed": int(confirmed),
        "confidence": confidence,
        "reason": reason, "stop_loss": stop_take.stop_loss, "take_profit": stop_take.take_profit,
        "context_note": None, "is_practice": 1, "plain_explanation": plain_explanation or None,
    })
    risk_eur = risk.compute_risk_eur(user["portfolio_eur"], user["risk_percent"])
    entry_id = repo.create_journal_entry(signal_id, user["id"], risk_eur)
    repo.update_journal_status(entry_id, user["id"], "genomen", entry_price=ind.price)

    return RedirectResponse(url="/dashboard", status_code=303)


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
    open_signal_ids = {e["signal_id"] for e in open_trades}
    recent_signals = [
        s for s in repo.list_recent_signals(symbol)
        if s["id"] not in open_signal_ids and (s["stop_loss"] or s["take_profit"])
    ]
    for s in recent_signals:
        s.setdefault("entry_price", None)  # signalen zijn geen journal-rijen, dat veld bestaat niet
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

    long_term_messages = repo.list_recent_long_term_messages(symbol)

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
        "long_term_messages": long_term_messages,
        "long_term_track_record": long_term_track_record,
        "coin_note": coin["note"] if coin else None,
        "is_muted": repo.is_coin_muted(user["id"], symbol),
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
    """Zet Telegram-meldingen voor deze coin weer aan voor de ingelogde
    gebruiker, na een eerdere mute-suggestie (zie
    signal_processor.REPEATED_IGNORE_MUTE_THRESHOLD)."""
    repo.unmute_coin(user["id"], symbol.upper())
    return RedirectResponse(url=f"/coins/{symbol.upper()}", status_code=303)


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

    return {"candles": candles, "ema9": ema9_series, "ema21": ema21_series}
