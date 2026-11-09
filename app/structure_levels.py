"""De structuur van één tijdframe als benoemde niveaus voor de schuifbare grafiek ("Groot"), zoals een analist hem tekent (CEO 2026-11-03,
voorbeeld BTC 12u: "H12 range high/low", "H12 MSB", "H12 FVG", "H12 swing low", "H12 bullish OB", "EQH"). Wisselt de gebruiker van
tijdframe, dan rekent de grafiek dit opnieuw op dat tijdframe.

Alleen gesloten candles en dezelfde regels als het HesPulse-model (model.swing_highs/lows, model.breaks), zodat wat de grafiek toont niet
botst met wat het model ziet. Alleen weergave: geen motor, filter of melding leest dit."""
from typing import Optional

import numpy as np
import pandas as pd

from app import model

# De dag erbij (CEO 2026-11-03: "en ook op dag checken"): dezelfde regels, pivots met 2 candles zoals op 4u.
K = {"15m": model.K_15M, "1h": model.K_1H, "4h": model.K_4H, "12h": model.K_4H, "1d": model.K_4H}
TF_TEXT = {"15m": "15m", "1h": "1u", "4h": "4u", "12h": "12u", "1d": "D"}
SECONDS = {"15m": 900, "1h": 3600, "4h": 14400, "12h": 43200, "1d": 86400}
TREND_TFS = ("1d", "4h", "1h", "15m")
EQUAL_ATR = model.POOL_EQUAL_ATR          # gelijke toppen of bodems binnen 0,1 ATR: EQH/EQL, dezelfde maat als de pools van het model
FVG_LOOKBACK = 150                        # zoveel candles terug zoeken naar een nog open gap


def _frame(rows: list[list], tf: str, now_s: float) -> Optional[model.Frame]:
    closed = [r for r in rows if r[0] + SECONDS[tf] <= now_s]
    if len(closed) < 30:
        return None
    df = pd.DataFrame(closed, columns=["t", "open", "high", "low", "close"])
    df.insert(0, "timestamp", pd.to_datetime(df.pop("t"), unit="s", utc=True))
    return model._frame(df, tf, False)


def _t(fr: model.Frame, i: int) -> int:
    return int(fr.ts[i].value // 10**9)


def open_fvgs(fr: model.Frame) -> list[dict]:
    """Alle nog open fair value gaps in de laatste FVG_LOOKBACK gesloten candles: {low, high, time, up_gap}. Een latere lont in de gap maakt
    hem kleiner; helemaal gevuld valt hij weg. Gedeeld door Groot (levels) en de meting van hogere tijdframes (app/htf_zones.py)."""
    last, out = fr.n - 1, []
    for i in range(max(2, last - FVG_LOOKBACK), last + 1):
        if fr.h[i - 2] < fr.l[i]:                       # gap omhoog
            lo, hi = float(fr.h[i - 2]), float(fr.l[i])
            later = fr.l[i + 1:last + 1]
            if len(later):
                hi = min(hi, float(later.min()))
            if hi > lo:
                out.append({"low": lo, "high": hi, "time": _t(fr, i - 1), "up_gap": True})
        if fr.l[i - 2] > fr.h[i]:                       # gap omlaag
            lo, hi = float(fr.h[i]), float(fr.l[i - 2])
            later = fr.h[i + 1:last + 1]
            if len(later):
                lo = max(lo, float(later.max()))
            if hi > lo:
                out.append({"low": lo, "high": hi, "time": _t(fr, i - 1), "up_gap": False})
    return out


def day_bias(rows: Optional[list[list]], now_s: float) -> Optional[str]:
    """De richting van de dag zoals model.DailyBias: de laatste breuk op gesloten dagcandles, 'long', 'short' of None."""
    if not rows:
        return None
    t = levels(rows, "1d", now_s)["trend"]
    return {"bullish": "long", "bearish": "short"}.get(t)


def levels(rows: list[list], tf: str, now_s: float, bias: Optional[str] = None) -> dict:
    """{"lines": [{value, time, label, kind}], "zones": [{low, high, time, label, kind}], "trend": "bullish" | "bearish" | None}; leeg als er
    te weinig gesloten candles zijn. De trend is de richting van de laatste structuurbreuk, dezelfde regel als de bias van het model.

    bias ('long'/'short', de richting van de dag): dan volgen range, evenwicht, MSB en order block alleen de laatste breuk in die richting en
    rekt de range op na een slot door de rand, net als het model top-down (B-2026-11-03-09: "Groot spreekt de kaart tegen"). `herstel` zegt
    dan of de laatste breuk tegen de dag in ging."""
    out: dict = {"lines": [], "zones": [], "trend": None, "herstel": False}
    if tf not in K:
        return out
    fr = _frame(rows, tf, now_s)
    if fr is None:
        return out
    k, word, last = K[tf], TF_TEXT[tf], fr.n - 1
    close = float(fr.c[last])
    atr = float(fr.atr[last]) if np.isfinite(fr.atr[last]) else 0.0
    known_hi = [p for p in np.flatnonzero(model.swing_highs(fr, k)) if p + k <= last]
    known_lo = [p for p in np.flatnonzero(model.swing_lows(fr, k)) if p + k <= last]

    # Range en de laatste structuurbreuk (MSB): dezelfde breuken als de bias van het model.
    brk = model.breaks(fr, k)
    if brk:
        out["trend"] = "bullish" if brk[-1].up else "bearish"
        out["herstel"] = bias is not None and brk[-1].up != (bias == "long")
    if bias is not None:
        brk = [b for b in brk if b.up == (bias == "long")]
    if brk:
        b = brk[-1]
        name = {"CHOCH": "CHoCH", "BOS": "BOS"}.get(b.label, "MSB")
        out["lines"].append({"value": b.level, "time": _t(fr, b.swing), "label": f"{word} {name}", "short": name, "kind": "msb"})
        # De dealing range zoals model.Context4h: bij een breuk omhoog de laagste low tussen de gebroken top en de breuk, en de hoogste high
        # sinds die top; omlaag gespiegeld. Zo is het de hele poot die brak, niet alleen het stuk na de breuk.
        if b.up:
            lo_i = b.swing + 1 + int(np.argmin(fr.l[b.swing + 1:b.i + 1]))
            hi_i = b.swing + int(np.argmax(fr.h[b.swing:last + 1]))
        else:
            hi_i = b.swing + 1 + int(np.argmax(fr.h[b.swing + 1:b.i + 1]))
            lo_i = b.swing + int(np.argmin(fr.l[b.swing:last + 1]))
        if bias is not None:
            # Opgerekte range zoals model.Context4h top-down: een slot door de verre rand verschuift die rand naar het nieuwe uiterste.
            if b.up:
                through = np.flatnonzero(fr.c[b.i + 1:last + 1] < fr.l[lo_i])
                if len(through):
                    x = b.i + 1 + int(through[0])
                    lo_i = x + int(np.argmin(fr.l[x:last + 1]))
            else:
                through = np.flatnonzero(fr.c[b.i + 1:last + 1] > fr.h[hi_i])
                if len(through):
                    x = b.i + 1 + int(through[0])
                    hi_i = x + int(np.argmax(fr.h[x:last + 1]))
        out["lines"].append({"value": float(fr.h[hi_i]), "time": _t(fr, hi_i), "label": f"{word} range high", "short": "RH", "kind": "range"})
        out["lines"].append({"value": float(fr.l[lo_i]), "time": _t(fr, lo_i), "label": f"{word} range low", "short": "RL", "kind": "range"})
        # Premium en discount (CEO 2026-11-03: "wel premium en discount, ik bedoelde dat wij dat niet hebben"): de helften van de range
        # boven en onder het evenwicht, zoals het model ze gebruikt (shorts in premium, longs in discount).
        H, L = float(fr.h[hi_i]), float(fr.l[lo_i])
        eq = (H + L) / 2
        t0 = _t(fr, min(lo_i, hi_i))
        out["lines"].append({"value": eq, "time": t0, "label": f"{word} evenwicht 0,5", "short": "EQ", "kind": "eq50"})
        out["zones"].append({"low": eq, "high": H, "time": t0, "label": "premium", "kind": "premium"})
        out["zones"].append({"low": L, "high": eq, "time": t0, "label": "discount", "kind": "discount"})
        # Order block: de laatste candle tegen de richting vóór de beweging die brak, zolang de koers er niet doorheen sloot.
        start = lo_i if b.up else hi_i
        against = [j for j in range(max(0, start - 3), min(b.i, start + 1) + 1) if (fr.c[j] < fr.o[j]) == b.up]
        if against:
            j = against[-1]
            lo, hi = float(fr.l[j]), float(fr.h[j])
            broken = (fr.c[j + 1:last + 1] < lo).any() if b.up else (fr.c[j + 1:last + 1] > hi).any()
            if not broken:
                out["zones"].append({"low": lo, "high": hi, "time": _t(fr, j), "label": f"{word} {'bullish' if b.up else 'bearish'} OB", "short": "OB",
                                     "kind": "ob"})

    # De laatste swing high en low, of EQH/EQL als de twee laatste binnen 0,1 ATR liggen.
    for pts, arr, up in ((known_hi, fr.h, True), (known_lo, fr.l, False)):
        if not pts:
            continue
        p = pts[-1]
        if len(pts) >= 2 and atr and abs(arr[pts[-1]] - arr[pts[-2]]) <= EQUAL_ATR * atr:
            q = pts[-2]
            v = max(arr[p], arr[q]) if up else min(arr[p], arr[q])
            out["lines"].append({"value": float(v), "time": _t(fr, q), "label": f"{word} {'EQH' if up else 'EQL'}", "short": "EQH" if up else "EQL", "kind": "eq"})
        else:
            out["lines"].append({"value": float(arr[p]), "time": _t(fr, p), "label": f"{word} swing {'high' if up else 'low'}", "short": "SH" if up else "SL", "kind": "swing"})

    # De dichtste nog open fair value gap boven en onder de koers.
    gaps = open_fvgs(fr)
    below = [{**g, "label": f"{word} FVG", "short": "FVG", "kind": "fvg"} for g in gaps if g["up_gap"] and g["high"] < close]
    above = [{**g, "label": f"{word} FVG", "short": "FVG", "kind": "fvg"} for g in gaps if g["up_gap"] is False and g["low"] > close]
    for z in below + above:
        z.pop("up_gap")
    if below:
        out["zones"].append(max(below, key=lambda z: z["high"]))
    if above:
        out["zones"].append(min(above, key=lambda z: z["low"]))
    return out


# Liquiditeit: de dichtstbijzijnde onaangeroerde swing high (BSL) en swing low (SSL) van 1u en 4u, zoals f_pools in tradingview/hespulse_clean.pine
# en Pools._touch van het model: een latere candle die hem raakt (high gelijk of hoger, low gelijk of lager) verbruikt hem, de candles rechts van de
# pivot tellen niet mee, en een pool is hoogstens POOL_AGE candles oud (model.POOL_LOOKBACK).
POOL_TFS = {"1h": model.K_1H, "4h": model.K_4H}
POOL_AGE = model.POOL_LOOKBACK


def pools(rows: Optional[list[list]], tf: str, now_s: float) -> dict:
    """{"bsl": {value, time, eq} | None, "ssl": {...} | None, "atr": float}; eq als nog een onaangeroerde pivot binnen 0,1 ATR ligt."""
    out = {"bsl": None, "ssl": None, "atr": 0.0}
    k = POOL_TFS.get(tf)
    fr = _frame(rows, tf, now_s) if k and rows else None
    if fr is None:
        return out
    hi_f, lo_f = model.swing_highs(fr, k), model.swing_lows(fr, k)
    highs: list[tuple[float, int]] = []
    lows: list[tuple[float, int]] = []
    for i in range(fr.n):
        highs = [p for p in highs if not (fr.h[i] >= p[0] or i - p[1] >= POOL_AGE)]
        lows = [p for p in lows if not (fr.l[i] <= p[0] or i - p[1] >= POOL_AGE)]
        q = i - k
        if q >= 0:
            if hi_f[q]:
                highs.append((float(fr.h[q]), q))
            if lo_f[q]:
                lows.append((float(fr.l[q]), q))
    atr = float(fr.atr[-1]) if np.isfinite(fr.atr[-1]) else 0.0

    def pick(items, nearest):
        if not items:
            return None
        best = nearest(items, key=lambda p: p[0])
        eq = bool(atr) and any(p is not best and abs(p[0] - best[0]) <= EQUAL_ATR * atr for p in items)
        return {"value": best[0], "time": _t(fr, best[1]), "eq": eq}

    out.update(bsl=pick(highs, min), ssl=pick(lows, max), atr=atr)
    return out


def pool_lines(rows_by_tf: dict, tf: str, now_s: float) -> list[dict]:
    """De pool-lijnen voor "Groot" op tijdframe tf: 4u bij 15m, 1u en 4u; 1u bij 15m en 1u. Een niveau van 1u binnen 0,1 ATR (1u) van dat van 4u
    blijft weg: dat is hetzelfde niveau. {value, time, label, short, side, kind: "pool"}."""
    want = [t for t, ok in (("4h", tf in ("15m", "1h", "4h")), ("1h", tf in ("15m", "1h"))) if ok]
    res = {t: pools(rows_by_tf.get(t), t, now_s) for t in want}
    out = []
    for t in want:
        p = res[t]
        for side, high in (("bsl", True), ("ssl", False)):
            lv = p[side]
            if not lv:
                continue
            ref = res.get("4h", {}).get(side) if t == "1h" else None
            if ref and abs(lv["value"] - ref["value"]) <= EQUAL_ATR * p["atr"]:
                continue
            name = ("EQH" if lv["eq"] else "BSL") if high else ("EQL" if lv["eq"] else "SSL")
            label = f"{TF_TEXT[t]} {name}"
            out.append({"value": lv["value"], "time": lv["time"], "label": label, "short": label, "side": side, "kind": "pool"})
    return out
