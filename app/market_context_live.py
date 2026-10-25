"""Marktcontext live: haalt elke snelcyclus (market_scanner.scan_smc_fast, elke 5 minuten) de publieke bronnen op die aan de beurt zijn en schrijft
de metingen in de tabel market_context. Rekenen en lezen van de antwoorden gebeurt in app/market_context.py.

Waarom zo voorzichtig: dit is weergave, geen beslissing. Daarom draait het naast de motoren, heeft elke bron een eigen cache (de tijd van de laatste
geslaagde meting in de tabel: de snelcyclus is een los proces per run, een cache in het geheugen zou niets onthouden), en wacht de scan hooguit
RUN_TIMEOUT_S. Elke HTTP-aanroep loopt via _request: timeout 5 seconden, bij elke fout None en een logregel, nooit een uitzondering naar buiten.
Een mislukte bron schrijft niets, dus de oude waarde blijft met zijn eigen tijd staan.

Endpoints (alleen publiek, zonder sleutel):
  Binance USDⓈ-M futures, https://developers.binance.com/docs/derivatives/usds-margined-futures/market-data/rest-api
    GET https://fapi.binance.com/fapi/v1/premiumIndex                          markprijs en lastFundingRate van alle perpetuals
    GET https://fapi.binance.com/fapi/v1/fundingInfo                           alleen contracten met een afwijkend interval (fundingIntervalHours)
    GET https://fapi.binance.com/futures/data/openInterestHist?symbol=BTCUSDT&period=1h&limit=25   OI in dollars, nu en 24 uur terug
  Hyperliquid, https://hyperliquid.gitbook.io/hyperliquid-docs/for-developers/api/info-endpoint/perpetuals
    POST https://api.hyperliquid.xyz/info  {"type": "metaAndAssetCtxs"}        funding (per uur), openInterest (in coins), markPx, oraclePx
  Bybit v5, https://bybit-exchange.github.io/docs/v5/market/tickers
    GET https://api.bybit.com/v5/market/tickers?category=linear               fundingRate, fundingIntervalHour, openInterestValue
  OKX v5, https://www.okx.com/docs-v5/en/#public-data-rest-api-get-funding-rate
    GET https://www.okx.com/api/v5/public/funding-rate?instId=BTC-USDT-SWAP   één contract per aanroep, interval uit fundingTime/nextFundingTime
  Fear and Greed, https://alternative.me/crypto/fear-and-greed-index/#api
    GET https://api.alternative.me/fng/?limit=1                                één getal per dag met het eigen label van de bron
  DefiLlama stablecoins, https://api-docs.defillama.com/ (sectie stablecoins)
    GET https://stablecoins.llama.fi/stablecoincharts/all                     totale voorraad per dag, per peg in dollars"""
import asyncio
import json
import logging
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from app import config, repo
from app import market_context as mc

logger = logging.getLogger("market_context_live")

TIMEOUT_S = 5
# De hele ophaalronde, ook als een bron blijft hangen: daarna gaat de scan door met wat binnen is.
RUN_TIMEOUT_S = 20
# Funding en OI veranderen per minuut; Fear and Greed en de stablecoin-voorraad één keer per dag. 30 seconden marge op de 5 minuten, anders valt
# een bron die net iets minder dan 5 minuten oud is een hele cyclus over door de speling van de timer.
FAST_TTL_S = 5 * 60 - 30
SLOW_TTL_S = 6 * 3600
KEEP_DAYS = 30
USER_AGENT = "HesPulse/1.0 (+marktcontext)"

BINANCE_URL = "https://fapi.binance.com"
HYPERLIQUID_URL = "https://api.hyperliquid.xyz/info"
BYBIT_URL = "https://api.bybit.com/v5/market/tickers"
OKX_URL = "https://www.okx.com/api/v5/public/funding-rate"
FNG_URL = "https://api.alternative.me/fng/"
STABLECOINS_URL = "https://stablecoins.llama.fi/stablecoincharts/all"


def _request(url: str, params: Optional[dict] = None, body: Optional[dict] = None):
    """De enige plek met netwerk. GET met params, of POST met een JSON-body. None bij elke fout (netwerk, status, geen JSON)."""
    full = f"{url}?{urllib.parse.urlencode(params)}" if params else url
    data = json.dumps(body).encode() if body is not None else None
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if data is not None:
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(full, data=data, headers=headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
            return json.loads(resp.read())
    except Exception as exc:        # ook ssl-, socket- en JSON-fouten: niets hiervan mag de scan raken
        logger.warning("Marktcontext: %s niet op te halen (%s)", url, exc)
        return None


def fetch_binance_premium():
    return _request(f"{BINANCE_URL}/fapi/v1/premiumIndex")


def fetch_binance_funding_info():
    return _request(f"{BINANCE_URL}/fapi/v1/fundingInfo")


def fetch_binance_oi(coin: str):
    return _request(f"{BINANCE_URL}/futures/data/openInterestHist", {"symbol": f"{coin}USDT", "period": "1h", "limit": 25})


def fetch_hyperliquid():
    return _request(HYPERLIQUID_URL, body={"type": "metaAndAssetCtxs"})


def fetch_bybit():
    return _request(BYBIT_URL, {"category": "linear"})


def fetch_okx(coin: str):
    return _request(OKX_URL, {"instId": f"{coin}-USDT-SWAP"})


def fetch_fear_greed():
    return _request(FNG_URL, {"limit": 1})


def fetch_stablecoins():
    return _request(STABLECOINS_URL)


# --- Per bron: {coin: {metric: waarde}} of None als de bron niets gaf. Draait in een eigen thread. ---

def _per_coin(coins, fetch: Callable, parse: Callable, deadline: float) -> dict:
    """Eén aanroep per coin na elkaar (OKX en de OI-historie van Binance kennen geen 'alle coins'), en stoppen bij de deadline: na elkaar blijft
    ruim onder de limieten per IP, en de deadline zorgt dat een hangende bron het proces niet minutenlang openhoudt na de scan."""
    out = {}
    for coin in coins:
        if time.monotonic() > deadline:
            break
        row = parse(fetch(coin))
        if row:
            out[coin] = row
    return out


def _binance(coins, deadline):
    premium = fetch_binance_premium()
    info = fetch_binance_funding_info()
    out = {}
    if premium is not None:
        parsed = mc.parse_binance_premium(premium, info, coins)
        for coin, row in parsed.items():
            if info is None:
                # Zonder fundingInfo is niet te zien welk contract elke 4 uur betaalt; dan liever geen funding dan een die half zo groot lijkt.
                row = {k: v for k, v in row.items() if k != "funding_8h"}
            if row:
                out[coin] = row
    for coin, row in _per_coin(coins, fetch_binance_oi, mc.parse_binance_oi, deadline).items():
        out.setdefault(coin, {}).update(row)
    return out or None


def _hyperliquid(coins, deadline):
    return mc.parse_hyperliquid(fetch_hyperliquid(), coins) or None


def _bybit(coins, deadline):
    return mc.parse_bybit(fetch_bybit(), coins) or None


def _okx(coins, deadline):
    return _per_coin(coins, fetch_okx, mc.parse_okx, deadline) or None


def _fear_greed(coins, deadline):
    row = mc.parse_fear_greed(fetch_fear_greed())
    return {mc.MARKET: row} if row else None


def _stablecoins(coins, deadline):
    row = mc.parse_stablecoins(fetch_stablecoins())
    return {mc.MARKET: row} if row else None


SOURCES: dict[str, tuple[int, Callable]] = {
    "binance": (FAST_TTL_S, _binance), "hyperliquid": (FAST_TTL_S, _hyperliquid), "bybit": (FAST_TTL_S, _bybit), "okx": (FAST_TTL_S, _okx),
    "alternative": (SLOW_TTL_S, _fear_greed), "defillama": (SLOW_TTL_S, _stablecoins),
}


def _due(now: datetime) -> list[str]:
    due = []
    for bron, (ttl, _) in SOURCES.items():
        last = repo.market_context_last_at(bron)
        at = datetime.fromisoformat(last) if last else None
        if at is not None and at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at is None or (now - at).total_seconds() >= ttl:
            due.append(bron)
    return due


def _guarded(fn: Callable, coins, deadline):
    try:
        return fn(coins, deadline)
    except Exception:
        logger.exception("Marktcontext: verwerken van een bron is mislukt")
        return None


def _with_hyperliquid_oi_change(data: dict, now: datetime) -> None:
    """Hyperliquid geeft geen OI van gisteren mee; de vergelijking komt uit onze eigen eerdere meting, en alleen als die rond 24 uur terug ligt."""
    since = (now - mc.OI_LOOKBACK - mc.OI_TOLERANCE).isoformat()
    for coin, row in data.items():
        if "oi_usd" not in row:
            continue
        past = mc.value_near(repo.market_context_series(coin, "hyperliquid", "oi_usd", since), now - mc.OI_LOOKBACK)
        change = mc.oi_change_pct(row["oi_usd"], past)
        if change is not None:
            row["oi_change_24h"] = change


async def run(now: Optional[datetime] = None) -> None:
    """Draait in de SMC-snelcyclus naast de motoren. Leest niets terug in een beslissing; schrijft alleen metingen en een levensteken."""
    if not config.MARKET_CONTEXT_ENABLED:
        return
    now = now or datetime.now(timezone.utc)
    coins = [c["symbol"] for c in repo.list_coins()]
    due = _due(now)
    if not due:
        return
    deadline = time.monotonic() + RUN_TIMEOUT_S
    # Een eigen pool die niet op zijn threads wacht: asyncio.run wacht wel op de standaardpool, en dan zou een hangende bron de scan alsnog ophouden.
    pool = ThreadPoolExecutor(max_workers=len(due), thread_name_prefix="marktcontext")
    loop = asyncio.get_running_loop()
    tasks = {asyncio.ensure_future(loop.run_in_executor(pool, _guarded, SOURCES[b][1], coins, deadline)): b for b in due}
    done, pending = await asyncio.wait(tasks, timeout=RUN_TIMEOUT_S)
    pool.shutdown(wait=False, cancel_futures=True)
    for t in pending:
        t.cancel()
    stamp = now.isoformat()
    rows, failed = [], []
    for task, bron in sorted(tasks.items(), key=lambda kv: list(SOURCES).index(kv[1])):
        data = task.result() if task in done else None
        if not data:
            failed.append(bron)
            continue
        if bron == "hyperliquid":
            _with_hyperliquid_oi_change(data, now)
        rows += [(coin, bron, metric, float(value), stamp) for coin, metrics in data.items() for metric, value in metrics.items()]
    try:
        repo.add_market_context(rows)
        repo.prune_market_context((now - timedelta(days=KEEP_DAYS)).isoformat())
    except Exception:
        logger.exception("Marktcontext wegschrijven is mislukt")
        return
    detail = f"{len(due) - len(failed)} van {len(due)} bronnen" + (f", mislukt: {', '.join(failed)}" if failed else "")
    repo.beat("marktcontext", detail)
    logger.info("Marktcontext: %s, %s metingen", detail, len(rows))


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    from app import db
    db.init_db()
    asyncio.run(run())
