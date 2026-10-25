"""Marktcontext: gemeten feiten van publieke bronnen naast Binance (Hyperliquid, Bybit, OKX, Fear and Greed, DefiLlama), gelijk gemaakt en in gewone
woorden. Pure functies zonder netwerk of database: de ophaler (app/market_context_live.py), de pagina's en de tests rekenen met dezelfde code.

Wat dit niet is: een signaal. Geen motor, filter of melding leest deze waarden; ze staan als gemeten feit op kaart en Vandaag, en de stand bij het
ontstaan van een zone-radar-kaart wordt bewaard zodat Bewijs (track_record.funding_split) kan tonen of extreme funding samengaat met een andere uitkomst.
De teksten beschrijven wie betaalt of hoeveel er veranderde, nooit wat je moet doen of wat er gaat gebeuren."""
import math
from datetime import datetime, timedelta, timezone
from typing import Optional

from app import freshness

STANDARD_HOURS = 8
# Vooraf vastgelegd, nooit op data afgesteld. De basis op Binance, Bybit en OKX is +0,01% per 8 uur (de rentecomponent): in een rustige markt
# staat funding daar. 0,05% is vijf keer die basis, het gebied waar longs duidelijk opeengepakt zitten; -0,03% ligt even ver (0,04) onder de basis
# en betekent dat shorts duidelijk meer betalen dan de rente. Zo is de band rond de basis symmetrisch en niet rond nul.
FUNDING_HIGH_PCT = 0.05
FUNDING_LOW_PCT = -0.03
# Een verschil tussen beurzen telt alleen tussen metingen die bijna tegelijk zijn: een oude OKX-waarde naast een verse Binance-waarde meet een
# verschil dat er nooit op één moment was. Eén scancyclus (5 minuten) plus marge.
SPREAD_MAX_GAP_S = 15 * 60
# De stand bij het ontstaan van een kaart moet ook echt die stand zijn: ouder dan twee cycli van de ophaler en het is een stand van eerder.
SNAPSHOT_MAX_AGE_S = 30 * 60
OI_LOOKBACK = timedelta(hours=24)
OI_TOLERANCE = timedelta(minutes=90)

VENUES = ("binance", "hyperliquid", "bybit", "okx")
SOURCE_NAMES = {"binance": "Binance", "hyperliquid": "Hyperliquid", "bybit": "Bybit", "okx": "OKX", "alternative": "alternative.me",
                "defillama": "DefiLlama"}
MARKET = "markt"
# Het eigen label van alternative.me, in volgorde; opgeslagen als index zodat de tabel alleen getallen bevat.
FNG_CLASSES = ("Extreme Fear", "Fear", "Neutral", "Greed", "Extreme Greed")
FNG_WORDS = ("extreme angst", "angst", "neutraal", "hebzucht", "extreme hebzucht")
VANDAAG_COINS = ("BTC", "ETH")


def _num(value) -> Optional[float]:
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _nl(value: float, decimals: int, sign: bool = False) -> str:
    text = f"{value:+.{decimals}f}" if sign else f"{value:.{decimals}f}"
    return text.replace(".", ",")


def per_8h_pct(rate: Optional[float], interval_hours: Optional[float]) -> Optional[float]:
    """Een funding rate per betaalinterval als procent per 8 uur: Hyperliquid betaalt elk uur, sommige Binance- en Bybit-contracten elke 4 uur."""
    if rate is None or not interval_hours or interval_hours <= 0:
        return None
    return rate * 100 * STANDARD_HOURS / interval_hours


def funding_label(pct: Optional[float]) -> Optional[str]:
    if pct is None:
        return None
    if pct >= FUNDING_HIGH_PCT:
        return "hoog"
    if pct <= FUNDING_LOW_PCT:
        return "laag"
    return None


def is_extreme(pct: Optional[float]) -> bool:
    return funding_label(pct) is not None


def _payer(pct: float) -> str:
    return "longs betalen" if pct > 0 else "shorts betalen" if pct < 0 else "niemand betaalt"


def _funding_value(pct: float) -> str:
    return f"{'0,000' if round(pct, 3) == 0 else _nl(pct, 3, sign=True)}%"


def funding_text(pct: float) -> str:
    return f"Funding {_funding_value(pct)} per 8u: {_payer(round(pct, 3))}"


def widest_spread(funding: dict[str, float]) -> Optional[tuple[str, float]]:
    """De beurs die het verst van Binance afligt en hoeveel (procentpunt per 8 uur, absoluut). None zonder Binance of zonder andere beurs."""
    base = funding.get("binance")
    if base is None:
        return None
    diffs = [(abs(v - base), venue) for venue, v in funding.items() if venue != "binance" and v is not None]
    if not diffs:
        return None
    diff, venue = max(diffs, key=lambda d: (d[0], -VENUES.index(d[1]) if d[1] in VENUES else 0))
    return venue, round(diff, 6)


def spread_text(venue: str, diff: float) -> str:
    return f"Binance en {SOURCE_NAMES.get(venue, venue)} wijken {_nl(abs(diff), 3)}% af"


def oi_change_pct(now_value: Optional[float], past_value: Optional[float]) -> Optional[float]:
    if now_value is None or not past_value:
        return None
    return (now_value - past_value) / past_value * 100


def _at(iso: str) -> Optional[datetime]:
    try:
        t = datetime.fromisoformat(iso)
    except (TypeError, ValueError):
        return None
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def value_near(series: list[tuple[str, float]], target: datetime, tolerance: timedelta = OI_TOLERANCE) -> Optional[float]:
    """De waarde die het dichtst bij `target` gemeten is, alleen binnen de marge: liever geen vergelijking dan een met een stand van een ander moment."""
    best = None
    for iso, value in series:
        at = _at(iso)
        if at is None:
            continue
        gap = abs(at - target)
        if gap <= tolerance and (best is None or gap < best[0]):
            best = (gap, value)
    return best[1] if best else None


# --- Parsers: ruwe API-antwoorden naar {metric: waarde}. Elk onverwacht formaat geeft een lege uitkomst, nooit een uitzondering. ---

def parse_hyperliquid(raw, coins) -> dict:
    """metaAndAssetCtxs: [meta met universe, lijst assetCtxs in dezelfde volgorde]. funding is per uur; openInterest is in coins, dus maal markPx."""
    try:
        universe, ctxs = raw[0]["universe"], raw[1]
        wanted = set(coins)
        out = {}
        for asset, ctx in zip(universe, ctxs):
            name = asset.get("name")
            if name not in wanted:
                continue
            funding, oi, mark, oracle = (_num(ctx.get(k)) for k in ("funding", "openInterest", "markPx", "oraclePx"))
            row = {k: v for k, v in (("funding_8h", per_8h_pct(funding, 1)), ("oi_usd", oi * mark if oi is not None and mark else None),
                                     ("mark", mark), ("oracle", oracle)) if v is not None}
            if row:
                out[name] = row
        return out
    except (TypeError, KeyError, IndexError, AttributeError):
        return {}


def parse_bybit(raw, coins) -> dict:
    """v5 tickers, category linear. fundingIntervalHour staat in de ticker; ontbreekt hij, dan 8 uur, het standaardinterval van Bybit."""
    try:
        if raw.get("retCode") != 0:
            return {}
        wanted = {f"{c}USDT": c for c in coins}
        out = {}
        for t in raw["result"]["list"]:
            coin = wanted.get(t.get("symbol"))
            if not coin:
                continue
            interval = _num(t.get("fundingIntervalHour")) or STANDARD_HOURS
            row = {k: v for k, v in (("funding_8h", per_8h_pct(_num(t.get("fundingRate")), interval)),
                                     ("oi_usd", _num(t.get("openInterestValue")))) if v is not None}
            if row:
                out[coin] = row
        return out
    except (TypeError, KeyError, AttributeError):
        return {}


def parse_okx(raw) -> dict:
    """public/funding-rate voor één instId. Het interval volgt uit nextFundingTime min fundingTime (ms); zonder die twee 8 uur."""
    try:
        if raw.get("code") != "0" or not raw.get("data"):
            return {}
        d = raw["data"][0]
        start, nxt = _num(d.get("fundingTime")), _num(d.get("nextFundingTime"))
        interval = (nxt - start) / 3_600_000 if start and nxt and nxt > start else STANDARD_HOURS
        pct = per_8h_pct(_num(d.get("fundingRate")), interval)
        return {"funding_8h": pct} if pct is not None else {}
    except (TypeError, KeyError, AttributeError, IndexError):
        return {}


def parse_binance_premium(raw, funding_info, coins) -> dict:
    """premiumIndex (alle perpetuals) met fundingInfo voor de contracten met een afwijkend interval; wat daar niet in staat, betaalt elke 8 uur."""
    try:
        intervals = {}
        for i in funding_info or []:
            hours = _num(i.get("fundingIntervalHours"))
            if hours:
                intervals[i.get("symbol")] = hours
        wanted = {f"{c}USDT": c for c in coins}
        out = {}
        for p in raw:
            coin = wanted.get(p.get("symbol"))
            if not coin:
                continue
            row = {k: v for k, v in (("funding_8h", per_8h_pct(_num(p.get("lastFundingRate")), intervals.get(p["symbol"], STANDARD_HOURS))),
                                     ("mark", _num(p.get("markPrice")))) if v is not None}
            if row:
                out[coin] = row
        return out
    except (TypeError, KeyError, AttributeError):
        return {}


def parse_binance_oi(raw) -> dict:
    """openInterestHist, period 1h, limit 25: de laatste rij is nu, de eerste 24 uur terug (de tijden worden gecontroleerd, niet aangenomen)."""
    try:
        rows = sorted(((int(r["timestamp"]), _num(r["sumOpenInterestValue"])) for r in raw), key=lambda r: r[0])
        if not rows or rows[-1][1] is None:
            return {}
        last_ms, last = rows[-1]
        out = {"oi_usd": last}
        target = last_ms - int(OI_LOOKBACK.total_seconds() * 1000)
        tol = OI_TOLERANCE.total_seconds() * 1000
        past = [(abs(t - target), v) for t, v in rows if abs(t - target) <= tol and v]
        change = oi_change_pct(last, min(past)[1]) if past else None
        if change is not None:
            out["oi_change_24h"] = change
        return out
    except (TypeError, KeyError, ValueError, AttributeError):
        return {}


def parse_fear_greed(raw) -> dict:
    try:
        d = raw["data"][0]
        value = _num(d.get("value"))
        if value is None:
            return {}
        out = {"fear_greed": value}
        if d.get("value_classification") in FNG_CLASSES:
            out["fear_greed_class"] = float(FNG_CLASSES.index(d["value_classification"]))
        return out
    except (TypeError, KeyError, IndexError, AttributeError):
        return {}


def _stable_total(row: dict) -> Optional[float]:
    values = [_num(v) for v in (row.get("totalCirculatingUSD") or {}).values()]
    values = [v for v in values if v is not None]
    return sum(values) if values else None


def parse_stablecoins(raw) -> dict:
    """stablecoincharts/all: één rij per dag. Totaal is de som over alle pegs in dollars; de verandering vergelijkt met de rij van 7 dagen eerder."""
    try:
        rows = sorted(((int(r["date"]), _stable_total(r)) for r in raw), key=lambda r: r[0])
        rows = [r for r in rows if r[1]]
        if not rows:
            return {}
        last_day, last = rows[-1]
        out = {"stablecoin_usd": last}
        week = [v for d, v in rows if d == last_day - 7 * 86400]
        if week:
            out["stablecoin_change_7d"] = oi_change_pct(last, week[0])
        return out
    except (TypeError, KeyError, ValueError, AttributeError):
        return {}


# --- Weergave ---

def latest(rows: list[dict]) -> dict:
    """{coin: {bron: {metric: (waarde, gemeten_op)}}} met per metric de nieuwste meting."""
    out: dict = {}
    for r in rows:
        cell = out.setdefault(r["coin"], {}).setdefault(r["bron"], {})
        old = cell.get(r["metric"])
        if old is None or (_at(r["gemeten_op"]) or datetime.min.replace(tzinfo=timezone.utc)) > (_at(old[1]) or datetime.min.replace(tzinfo=timezone.utc)):
            cell[r["metric"]] = (r["waarde"], r["gemeten_op"])
    return out


def _line(label: str, value: str, bron: str, at: str, now: datetime, note: str = "", flag: Optional[str] = None) -> dict:
    return {"label": label, "value": value, "note": note, "flag": flag, "source": SOURCE_NAMES.get(bron, bron),
            "age": freshness.age_text(freshness.age_seconds(at, now))}


def _funding_now(coin_latest: dict) -> dict[str, tuple[float, str]]:
    return {v: coin_latest[v]["funding_8h"] for v in VENUES if "funding_8h" in coin_latest.get(v, {})}


def _spread(funding: dict[str, tuple[float, str]]) -> Optional[tuple[str, float, str]]:
    if "binance" not in funding:
        return None
    base_at = _at(funding["binance"][1])
    close = {v: val for v, (val, at) in funding.items()
             if v == "binance" or (base_at and _at(at) and abs((_at(at) - base_at).total_seconds()) <= SPREAD_MAX_GAP_S)}
    widest = widest_spread(close)
    return (*widest, funding["binance"][1]) if widest else None


def coin_lines(coin_latest: dict, now: datetime) -> list[dict]:
    """Het blok Context op een kaart: funding (Binance, anders de eerste beurs die er is), het grootste verschil met Binance, OI over 24 uur.
    Een waarde die er niet is, krijgt geen regel."""
    lines = []
    funding = _funding_now(coin_latest)
    if funding:
        bron = next(v for v in VENUES if v in funding)
        pct, at = funding[bron]
        lines.append(_line("Funding", f"{_funding_value(pct)} per 8u", bron, at, now, _payer(round(pct, 3)), funding_label(pct)))
    spread = _spread(funding)
    if spread:
        venue, diff, at = spread
        lines.append(_line("Verschil tussen beurzen", f"{_nl(diff, 3)}%", "binance", at, now, spread_text(venue, diff)))
        lines[-1]["source"] = ""          # de tekst noemt beide beurzen al
    for bron in ("binance", "hyperliquid"):
        oi = coin_latest.get(bron, {}).get("oi_change_24h")
        if oi:
            lines.append(_line("Open interest 24u", f"{_nl(oi[0], 1, sign=True)}%", bron, oi[1], now))
            break
    return lines


def _money(usd: float) -> str:
    return f"${_nl(usd / 1e9, 1)} mld"


def market_view(all_latest: dict, now: datetime) -> dict:
    """Het blok Marktcontext op Vandaag: Fear and Greed, de stablecoin-voorraad en funding van BTC en ETH per beurs."""
    lines = []
    m = all_latest.get(MARKET, {})
    fng = m.get("alternative", {}).get("fear_greed")
    if fng:
        cls = m.get("alternative", {}).get("fear_greed_class")
        word = FNG_WORDS[int(cls[0])] if cls and 0 <= int(cls[0]) < len(FNG_WORDS) else ""
        lines.append(_line("Fear and Greed", f"{fng[0]:.0f}", "alternative", fng[1], now, word))
    stable = m.get("defillama", {}).get("stablecoin_usd")
    if stable:
        change = m.get("defillama", {}).get("stablecoin_change_7d")
        lines.append(_line("Stablecoin-voorraad", _money(stable[0]), "defillama", stable[1], now,
                           f"{_nl(change[0], 2, sign=True)}% in 7 dagen" if change else ""))
    funding = []
    for coin in VANDAAG_COINS:
        per = _funding_now(all_latest.get(coin, {}))
        venues = [{"source": SOURCE_NAMES[v], "value": _funding_value(per[v][0]), "flag": funding_label(per[v][0]),
                   "age": freshness.age_text(freshness.age_seconds(per[v][1], now))} for v in VENUES if v in per]
        if venues:
            funding.append({"coin": coin, "venues": venues})
    table = None
    if funding:
        coins = [f["coin"] for f in funding]
        by = {f["coin"]: {v["source"]: v for v in f["venues"]} for f in funding}
        sources = [SOURCE_NAMES[v] for v in VENUES if any(SOURCE_NAMES[v] in by[c] for c in coins)]
        table = {"coins": coins, "rows": [{"source": s, "cells": [by[c].get(s) for c in coins]} for s in sources]}
    return {"lines": lines, "funding": funding, "table": table}


SNAPSHOT_KEYS = ("ctx_funding", "ctx_oi_change_24h", "ctx_spread")


def snapshot(coin_latest: dict, now: datetime) -> dict:
    """De stand bij het ontstaan van een kaart: Binance-funding, Binance-OI over 24 uur en het grootste verschil met Binance. Alleen verse waarden."""
    def fresh(cell):
        if not cell:
            return None
        age = freshness.age_seconds(cell[1], now)
        return cell[0] if age is not None and age <= SNAPSHOT_MAX_AGE_S else None

    binance = coin_latest.get("binance", {})
    funding = fresh(binance.get("funding_8h"))
    spread = _spread({v: c for v, c in _funding_now(coin_latest).items() if fresh(c) is not None})
    return {"ctx_funding": funding, "ctx_oi_change_24h": fresh(binance.get("oi_change_24h")), "ctx_spread": spread[1] if spread else None}


def snapshot_lines(row: dict) -> list[dict]:
    """De bewaarde stand bij het ontstaan, voor de kanspagina; bron en tijd zijn die van de kaart zelf."""
    lines = []
    if row.get("ctx_funding") is not None:
        pct = row["ctx_funding"]
        lines.append({"label": "Funding", "value": f"{_funding_value(pct)} per 8u", "note": _payer(round(pct, 3)), "flag": funding_label(pct),
                      "source": "Binance", "age": ""})
    if row.get("ctx_spread") is not None:
        lines.append({"label": "Verschil tussen beurzen", "value": f"{_nl(abs(row['ctx_spread']), 3)}%", "note": "", "flag": None,
                      "source": "Binance tegen de verste beurs", "age": ""})
    if row.get("ctx_oi_change_24h") is not None:
        lines.append({"label": "Open interest 24u", "value": f"{_nl(row['ctx_oi_change_24h'], 1, sign=True)}%", "note": "", "flag": None,
                      "source": "Binance", "age": ""})
    return lines
