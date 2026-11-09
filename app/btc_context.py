"""BTC-context op een kaart van het HesPulse-model (aanvulling CEO 2026-11-02): een gemeten kenmerk, geen filter. Geen motor, melding of
volgorde leest dit; Bewijs kan het later beschrijven. Pure functies op gesloten candles uit dezelfde futuresbron (app/exchange.py).

  - BTC 4u: de structuurrichting van BTC volgens de regel van het model (model.Context4h: de laatste 4u-breuk, hoogstens 60 candles oud, range
    nog geldig): 'bullish', 'bearish', 'neutraal' (data, maar geen geldige breuk) of 'onbekend' (geen of te weinig data). Nooit stil neutraal
    als er geen data is.
  - Correlatie: Pearson van coin en BTC op log-rendementen van gesloten 15m-candles, uitgelijnd op hun UTC-tijd, over de laatste 96 (24 uur) en
    672 (7 dagen) kwartierslots. Een rendement bestaat alleen tussen twee opeenvolgende candles; ontbrekende paren worden niet opgevuld. Minder
    dan MIN_SHARE van de slots met een paar, of nulvariantie: 'onvoldoende data' (None).
  - Relatieve sterkte 24u: het rendement van de coin over 96 kwartieren min dat van BTC, in procentpunten. Geen alpha, geen voorspelling."""
import math
from typing import Optional

import numpy as np
import pandas as pd

WINDOWS = (96, 672)
# Vooraf gekozen: een venster telt als er voor minstens 90% van de slots een paar is; anders is het te dun om iets te zeggen.
MIN_SHARE = 0.9
M15 = pd.Timedelta(minutes=15)
BIAS_WORDS = ("bullish", "bearish", "neutraal", "onbekend")


def log_returns(df: pd.DataFrame, now: pd.Timestamp) -> pd.Series:
    """Log-rendement per gesloten 15m-candle, geïndexeerd op zijn openmoment; alleen als de candle ervoor precies een kwartier eerder opende."""
    if df is None or df.empty:
        return pd.Series(dtype=float)
    d = df[df["timestamp"] + M15 <= now].sort_values("timestamp")
    ts = pd.DatetimeIndex(d["timestamp"]).as_unit("ns")
    close = d["close"].to_numpy(float)
    if len(close) < 2:
        return pd.Series(dtype=float)
    with np.errstate(divide="ignore", invalid="ignore"):
        r = np.log(close[1:] / close[:-1])
    ok = (ts[1:] - ts[:-1] == M15) & np.isfinite(r)
    return pd.Series(r[ok], index=ts[1:][ok])


def pearson(a: pd.Series, b: pd.Series, window: int, end: pd.Timestamp) -> Optional[float]:
    """Pearson over de `window` kwartierslots tot en met `end` (een openmoment), alleen op slots waar beide een rendement hebben."""
    start = end - (window - 1) * M15
    a = a[(a.index >= start) & (a.index <= end)]
    b = b[(b.index >= start) & (b.index <= end)]
    both = pd.concat([a, b], axis=1, join="inner").dropna()
    if len(both) < max(2, math.ceil(MIN_SHARE * window)):
        return None
    x, y = both.iloc[:, 0].to_numpy(float), both.iloc[:, 1].to_numpy(float)
    if np.std(x) == 0 or np.std(y) == 0:
        return None
    return float(np.corrcoef(x, y)[0, 1])


def change_pct(df: pd.DataFrame, now: pd.Timestamp, bars: int = 96) -> Optional[float]:
    """Rendement in % van het slot van de laatste gesloten candle ten opzichte van precies `bars` kwartieren eerder; None als een van beide ontbreekt."""
    if df is None or df.empty:
        return None
    d = df[df["timestamp"] + M15 <= now].set_index("timestamp")["close"]
    if d.empty:
        return None
    last = d.index[-1]
    first = last - bars * M15
    if first not in d.index or not d[first]:
        return None
    return float((d[last] / d[first] - 1) * 100)


def bias(df4: Optional[pd.DataFrame], now: pd.Timestamp) -> str:
    from app import model
    if df4 is None or len(df4) < 2 * model.K_4H + 2:
        return "onbekend"
    t = int(pd.Timestamp(now).value)
    for direction, mirror, word in (("long", False, "bullish"), ("short", True, "bearish")):
        f4 = model._frame(model.closed(df4, now, "4h"), "4h", mirror)
        if f4.n and model.Context4h(f4, direction).at(t) is not None:
            return word
    return "neutraal"


def measure(coin_15m: Optional[pd.DataFrame], btc_15m: Optional[pd.DataFrame], btc_4h: Optional[pd.DataFrame], now: pd.Timestamp) -> dict:
    """Alles voor één kaart op moment `now`. Een ontbrekende reeks geeft None per maat, nooit een gok."""
    now = pd.Timestamp(now)
    a, b = log_returns(coin_15m, now), log_returns(btc_15m, now)
    end = now.floor("15min") - M15                  # openmoment van de laatste kwartiercandle die op `now` gesloten is
    corr = {str(w): (pearson(a, b, w, end) if len(a) and len(b) else None) for w in WINDOWS}
    ca, cb = change_pct(coin_15m, now), change_pct(btc_15m, now)
    return {"btc_4h": bias(btc_4h, now), "corr_96": corr["96"], "corr_672": corr["672"],
            "rel_24h": None if ca is None or cb is None else ca - cb, "at": now.isoformat()}


def _num(x: float) -> str:
    return f"{x:.2f}".replace(".", ",").replace("-", "−")


def text(ctx: Optional[dict]) -> str:
    """"BTC 4u: bearish · correlatie 0,82 (24u) / 0,74 (7d)" of "BTC-context onbekend" als er niets gemeten is."""
    if not ctx or (ctx.get("btc_4h") in (None, "onbekend") and ctx.get("corr_96") is None and ctx.get("corr_672") is None):
        return "BTC-context onbekend"
    c96 = _num(ctx["corr_96"]) if ctx.get("corr_96") is not None else "onvoldoende data"
    c672 = _num(ctx["corr_672"]) if ctx.get("corr_672") is not None else "onvoldoende data"
    return f"BTC 4u: {ctx.get('btc_4h') or 'onbekend'} · correlatie {c96} (24u) / {c672} (7d)"


def rel_text(ctx: Optional[dict]) -> str:
    if not ctx or ctx.get("rel_24h") is None:
        return ""
    v = ctx["rel_24h"]
    return f"24u t.o.v. BTC: {'+' if v >= 0 else chr(0x2212)}{abs(v):.1f}".replace(".", ",") + " procentpunt (relatieve sterkte, geen voorspelling)"
