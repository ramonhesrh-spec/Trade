"""Zone-sweep (docs/onderzoek/zone-sweep/preregistratie.md): de koers prikt onder een actieve vraagzone (long) of boven een aanbodzone (short) en
sluit binnen enkele candles terug. Zones komen van de range sweep (`rangesweep.find_zones`); prik en herstel worden op 1u-candles gemeten. Pure
functies op candles: lab, misser-controle en een eventuele live motor gebruiken dezelfde code. Vulling, verval en stopmeting doet `stopquality`."""
from typing import Optional

import numpy as np
import pandas as pd

from app import smc_eval
from app.replay import rangesweep as rs
from app.replay.lab import add_indicators

LONG, SHORT = rs.LONG, rs.SHORT
TFS = ("1h", "2h", "4h")
# De pre-registratie meet prik en herstel voor alle drie de zone-timeframes op 1u: op 15m is een prik ruis, en 1u is ook wat de range sweep gebruikt.
TRIGGER_TF = "1h"
PRIK_MIN_ATR = 0.1
PRIK_MAX_ATR = 2.5
HERSTEL_BARS = 6
# Op triggercandles: een zone waar een prik zonder herstel of een uitbraak op volgde krijgt even geen tweede kans, anders telt één val als meerdere.
COOLDOWN_BARS = 24
# De referentie-uitgangen van stopquality (midden en overkant) hebben een bovenkant nodig; de laatste swing is de natuurlijke.
REF_LOOKBACK = 60
BUFFERS = {"wick_025": 0.25, "wick_05": 0.5}
TESTED_STOPS = tuple(BUFFERS)


def htf_ok_zone(direction: str, trend: int, hh: float, ll: float, zone_mid: float) -> bool:
    """Dezelfde regel als rangesweep.htf_ok, met het midden van de zone in plaats van het midden van een range."""
    want = -1 if direction == SHORT else 1
    if not (np.isfinite(hh) and np.isfinite(ll)) or hh <= ll:
        return trend == want
    pos = (zone_mid - ll) / (hh - ll)
    return trend == want or (pos >= 0.5 if direction == SHORT else pos <= 0.5)


def _htf_pos(zone_mid: float, hh: float, ll: float) -> Optional[float]:
    return float((zone_mid - ll) / (hh - ll)) if np.isfinite(hh) and np.isfinite(ll) and hh > ll else None


def _scan_zone(z: rs.Zone, bt_cols: tuple, pos_tf: np.ndarray, start: int) -> list[tuple]:
    """Prikken van één zone, in volgorde: ('setup', j, ret, extreme) of ('refused', j, reden, ...). j = eerste prikcandle."""
    hi, lo, cl, atr = bt_cols
    short = z.kind == "bear"
    edge = z.high if short else z.low
    n, out, setup_done, next_ok, j = len(cl), [], False, 0, start
    while j < n:
        depth = (hi[j] - edge) if short else (edge - lo[j])
        if j < next_ok or not np.isfinite(atr[j]) or depth < PRIK_MIN_ATR * atr[j] or not rs.zone_active(z, int(pos_tf[j])):
            j += 1
            continue
        if setup_done:
            out.append(("refused", j, "zone had al een setup", None))
            # Eén weigering per prikreeks: pas als de koers weer aan de goede kant van de rand sluit telt de volgende prik.
            j += 1
            while j < n and ((hi[j] > edge) if short else (lo[j] < edge)):
                j += 1
            continue
        extreme, ret, reason = (hi[j] if short else lo[j]), None, f"geen herstel binnen {HERSTEL_BARS} candles"
        for k in range(j, min(n, j + HERSTEL_BARS)):
            extreme = max(extreme, hi[k]) if short else min(extreme, lo[k])
            if ((extreme - edge) if short else (edge - extreme)) > PRIK_MAX_ATR * atr[j]:
                reason = "uitbraak: de prik is dieper dan 2,5 ATR"
                break
            if (cl[k] < edge) if short else (cl[k] > edge):
                ret = k
                break
        if ret is None:
            out.append(("refused", j, reason, None))
            next_ok = j + COOLDOWN_BARS
            j += 1
            continue
        out.append(("setup", j, ret, float(extreme)))
        setup_done = True
        j = ret + 1
    return out


def find_setups(frames: dict, tf: str, entry: str, use_htf: bool) -> tuple[list[dict], list[dict]]:
    """frames: uitvoer van rangesweep.build_frames met uitsluitend gesloten candles. entry: 'zone' (limiet op de binnenkant van de zone) of
    'midden'. Eén setup per zone, op de eerste geldige prik met herstel."""
    b = add_indicators(frames[tf]).reset_index(drop=True)
    bt = add_indicators(frames[TRIGGER_TF]).reset_index(drop=True)
    b15 = frames["15m"]
    dt, dtf = rs.TF_DELTA[TRIGGER_TF], rs.TF_DELTA[tf]
    ts_t, ts_b, ts15 = bt["timestamp"], b["timestamp"], b15["timestamp"]
    cols = tuple(bt[c].to_numpy(float) for c in ("high", "low", "close", "atr"))
    hi_b, lo_b = b["high"].to_numpy(float), b["low"].to_numpy(float)
    atr_b = b["atr"].to_numpy(float)
    # Per triggercandle de laatste tf-candle die bij zijn openen gesloten was: daarmee wordt de zone beoordeeld, niets uit de toekomst.
    known = (ts_b + dtf).to_numpy()
    pos_tf = np.searchsorted(known, ts_t.to_numpy(), side="right") - 1
    trend, hh, ll = rs.htf_context(bt, frames["4h"])
    setups, refused = [], []
    for z in rs.find_zones(b):
        d = SHORT if z.kind == "bear" else LONG
        start = int(ts_t.searchsorted(ts_b.iloc[z.known_idx] + dtf, side="left"))
        for ev in _scan_zone(z, cols, pos_tf, start):
            kind, j = ev[0], ev[1]
            if kind == "refused":
                refused.append(rs._refusal(ts_t.iloc[j] + dt, d, ev[2], z.low, z.high, float(cols[3][j])))
                continue
            ret, extreme = ev[2], ev[3]
            at = ts_t.iloc[ret] + dt
            tfi = int(((ts_b + dtf) <= at).sum()) - 1
            atr_t = float(atr_b[tfi]) if tfi >= 0 and np.isfinite(atr_b[tfi]) else float(cols[3][ret])
            mid = (z.low + z.high) / 2
            ok = htf_ok_zone(d, int(trend[ret]), float(hh[ret]), float(ll[ret]), mid)
            if use_htf and not ok:
                refused.append(rs._refusal(at, d, "HTF-filter: tegen de 4u-trend en aan de verkeerde kant van de grotere range", z.low, z.high, atr_t))
                continue
            ref_price = float(cols[2][ret])
            price = mid if entry == "midden" else z.inner(d)
            # Een limiet aan de verkeerde kant van de koers is een marktorder: het herstel sloot dan binnen de zone en de instap is meteen, op het slot.
            if not (price > ref_price if d == SHORT else price < ref_price):
                price = ref_price
            # Referentiekader in plaats van een range: de lab-code leest range_high/range_low/range_first_at.
            first = max(0, int(pos_tf[j]) - REF_LOOKBACK + 1)
            last = max(int(pos_tf[j]), first)
            frame_hi, frame_lo = (max(float(hi_b[first:last + 1].max()), z.high), extreme) if d == LONG else (extreme, min(float(lo_b[first:last + 1].min()), z.low))
            depth = (extreme - z.high) if d == SHORT else (z.low - extreme)
            features = {"prik_atr": float(depth / cols[3][j]), "herstel_bars": int(ret - j + 1), "zone_atr": float((z.high - z.low) / atr_t),
                        "with_trend": bool(int(trend[ret]) == (-1 if d == SHORT else 1))}
            setups.append({"direction": d, "family": "zonesweep", "tf": tf, "range_high": frame_hi, "range_low": frame_lo,
                           "range_first_at": ts_b.iloc[first], "zone_low": z.low, "zone_high": z.high, "zone_at": ts_b.iloc[z.ob_idx],
                           "sweep_at": ts_t.iloc[j], "extreme": extreme, "return_at": at, "placed_at": at,
                           "place_idx15": int(ts15.searchsorted(at)), "ref_price": ref_price, "legs": [(1.0, float(price))], "atr_t": atr_t,
                           "htf_trend": int(trend[ret]), "htf_pos": _htf_pos(mid, float(hh[ret]), float(ll[ret])), "htf_ok": bool(ok),
                           "features": features})
    setups.sort(key=lambda s: (s["placed_at"], s["direction"], s["zone_low"], s["zone_high"]))
    return setups, refused


def raw_stops(setup: dict) -> dict[str, float]:
    """Ruwe stops: voorbij het uiterste van de prik plus een buffer in ATR."""
    side = 1 if setup["direction"] == SHORT else -1
    return {name: setup["extreme"] + side * buf * setup["atr_t"] for name, buf in BUFFERS.items()}


def final_stop(setup: dict, name: str) -> float:
    legs = setup["legs"]
    planned = sum(w * p for w, p in legs) / sum(w for w, _ in legs)
    return smc_eval.floor_stop(setup["direction"], planned, raw_stops(setup)[name], min_pct=rs.MIN_STOP_PCT)


def diagnose(frames: dict, at: pd.Timestamp, direction: str, tf: str, entry: str, use_htf: bool,
             window: pd.Timedelta = pd.Timedelta(hours=12), price: Optional[float] = None) -> dict:
    """Voor de misser-controle: zag deze variant een setup rond `at`, en zo niet, welke regel weigerde. price: de instapprijs van de trader; met
    price telt alleen een setup of weigering waarvan zone of limiet binnen 1 ATR van die prijs ligt."""
    setups, refused = find_setups(frames, tf, entry, use_htf)

    def setup_near(s):
        prices = [p for _, p in s["legs"]] + [s["zone_low"], s["zone_high"]]
        return price is None or rs._near(price, min(prices), max(prices), s["atr_t"])

    near = [s for s in setups if s["direction"] == direction and abs(s["placed_at"] - at) <= window and setup_near(s)]
    if near:
        return {"seen": True, "reason": "", "setup": min(near, key=lambda s: abs(s["placed_at"] - at))}
    ref = [r for r in refused if r["direction"] == direction and abs(r["at"] - at) <= window and (price is None or rs._near(price, *r["span"], r["atr"]))]
    if ref:
        return {"seen": False, "reason": min(ref, key=lambda r: abs(r["at"] - at))["reason"], "setup": None}
    b = add_indicators(frames[tf]).reset_index(drop=True)
    idx = int(((b["timestamp"] + rs.TF_DELTA[tf]) <= at).sum()) - 1
    kind = "bear" if direction == SHORT else "bull"
    if idx < 0 or not any(z.kind == kind and rs.zone_active(z, idx) for z in rs.find_zones(b)):
        return {"seen": False, "reason": f"geen actieve {'aanbod' if kind == 'bear' else 'vraag'}zone op {tf}", "setup": None}
    return {"seen": False, "reason": f"wel een zone, maar geen prik {'erboven' if direction == SHORT else 'eronder'}", "setup": None}
