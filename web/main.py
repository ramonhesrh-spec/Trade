"""FastAPI webdashboard. Eén vaste gebruiker, login met JWT sessiecookie,
beperkt aantal inlogpogingen. Draai met:
uvicorn web.main:app --host 0.0.0.0 --port 8000
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app import config, db, exchange, indicators, repo, security

BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

app = FastAPI(title="Crypto alertsysteem")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")

SESSION_COOKIE = "session"


@app.on_event("startup")
def on_startup():
    db.init_db()


@app.exception_handler(401)
async def redirect_to_login(request: Request, exc: HTTPException):
    return RedirectResponse(url="/login", status_code=303)


def require_login(request: Request) -> str:
    token = request.cookies.get(SESSION_COOKIE)
    if not token or not security.verify_session_token(token):
        raise HTTPException(status_code=401)
    return config.DASHBOARD_USERNAME


# ---------------------------------------------------------------------------
# Login
# ---------------------------------------------------------------------------

@app.get("/login")
async def login_form(request: Request):
    return templates.TemplateResponse(request, "login.html", {"error": None})


@app.post("/login")
async def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    if security.is_locked_out():
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Te veel mislukte pogingen. Probeer het later opnieuw."},
            status_code=429,
        )

    ok = username == config.DASHBOARD_USERNAME and security.verify_password(
        password, config.DASHBOARD_PASSWORD_HASH
    )
    security.record_login_attempt(success=ok, ip_address=request.client.host if request.client else "")

    if not ok:
        return templates.TemplateResponse(
            request,
            "login.html",
            {"error": "Onjuiste gebruikersnaam of wachtwoord."},
            status_code=401,
        )

    token = security.create_session_token(username)
    response = RedirectResponse(url="/", status_code=303)
    response.set_cookie(SESSION_COOKIE, token, httponly=True, samesite="lax", max_age=config.SESSION_HOURS * 3600)
    return response


@app.post("/logout")
async def logout():
    response = RedirectResponse(url="/login", status_code=303)
    response.delete_cookie(SESSION_COOKIE)
    return response


# ---------------------------------------------------------------------------
# Dashboard startpagina
# ---------------------------------------------------------------------------

@app.get("/")
async def dashboard(request: Request, status: str = "alle", user: str = Depends(require_login)):
    signals = repo.list_signals(status=None if status == "alle" else status)
    winrate = repo.winrate_stats()
    cumulative = repo.cumulative_result_series()
    coins = repo.list_coins()
    portfolio_eur = db.get_setting("portfolio_eur", "0")
    risk_percent = db.get_setting("risk_percent", str(config.DEFAULT_RISK_PERCENT))

    return templates.TemplateResponse(request, "dashboard.html", {
        "signals": signals,
        "winrate": winrate,
        "cumulative": cumulative,
        "coins": coins,
        "portfolio_eur": portfolio_eur,
        "risk_percent": risk_percent,
        "status_filter": status,
    })


@app.post("/settings/portfolio")
async def update_settings(
    portfolio_eur: float = Form(...),
    risk_percent: float = Form(...),
    user: str = Depends(require_login),
):
    db.set_setting("portfolio_eur", str(portfolio_eur))
    db.set_setting("risk_percent", str(risk_percent))
    return RedirectResponse(url="/", status_code=303)


@app.post("/signals/{signal_id}/status")
async def update_signal_status(
    signal_id: int,
    status: str = Form(...),
    entry_price: str = Form(""),
    user: str = Depends(require_login),
):
    entry = float(entry_price) if entry_price.strip() else None
    repo.update_status(signal_id, status, entry_price=entry)
    return RedirectResponse(url="/", status_code=303)


@app.post("/signals/{signal_id}/close")
async def close_signal(
    signal_id: int,
    exit_price: float = Form(...),
    exit_time: str = Form(...),
    user: str = Depends(require_login),
):
    repo.close_trade(signal_id, exit_price, exit_time)
    return RedirectResponse(url="/", status_code=303)


@app.post("/signals/{signal_id}/note")
async def update_note(
    signal_id: int,
    note: str = Form(""),
    user: str = Depends(require_login),
):
    repo.update_note(signal_id, note)
    return RedirectResponse(url="/", status_code=303)


# ---------------------------------------------------------------------------
# Grafiekpagina per coin
# ---------------------------------------------------------------------------

@app.get("/coins/{symbol}")
async def coin_page(request: Request, symbol: str, user: str = Depends(require_login)):
    symbol = symbol.upper()
    source_levels = repo.list_source_levels(symbol)
    signals = repo.list_signals_for_coin(symbol)
    open_trades = [s for s in signals if s["entry_price"] is not None and s["exit_price"] is None]

    return templates.TemplateResponse(request, "coin.html", {
        "symbol": symbol,
        "source_levels": source_levels,
        "open_trades": open_trades,
        "coins": repo.list_coins(),
    })


@app.get("/api/coins")
async def api_coins(user: str = Depends(require_login)):
    return repo.list_coins()


@app.get("/api/candles/{symbol}")
async def api_candles(symbol: str, user: str = Depends(require_login)):
    df = exchange.fetch_ohlcv(symbol.upper(), timeframe=config.TIMEFRAME, limit=200)
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
