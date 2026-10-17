"""Labfamilie range sweep (docs/onderzoek/range-sweep/preregistratie.md). Vijftien varianten in twee families, elk met twee getoetste stops, vooraf
vastgelegd: niets hier wordt na een run aangepast of toegevoegd. De kop is de stopkwaliteit (stopquality.accept); de strenge toets op een voordeel
(trendlab.evaluate plus een week-geclusterde t van minstens EDGE_T_MIN) staat ernaast.

Candles: 15m, 1u en 4u uit de cache; 30m en 2u worden daaruit samengevoegd (rangesweep.build_frames, vakken op UTC-grenzen). De HTF-context van de
hogere timeframe (4u-trend en 180 candles hoog-laag) gebruikt uitsluitend gesloten candles: elke waarde die bij een slot hoort komt uit candles die op
dat moment gesloten waren. Het lab heeft alleen gesloten candles; live voert men elk frame door rangesweep.closed_only.

Kosten: LAB_COST_PCT per rondreis, omgerekend naar R met het echte risico per trade (stopquality.measure). Rijen van alle coins worden achter elkaar
gezet en samen beoordeeld (`judge`); `run_coin` houdt geen toestand tussen coins, behalve de cache die de aanroeper per coin nieuw maakt."""
from dataclasses import dataclass
from typing import Callable, Optional

import numpy as np
import pandas as pd

from app import chance_checks
from app.replay import candles as candle_cache, rangesweep as rs, stats, stopquality as sq, trendlab as tl
from app.replay.lab import OI_MOVE_PCT, SAMPLE_LAG, add_indicators


@dataclass(frozen=True)
class RSVariant:
    name: str
    family: str
    tf: str
    entry: str
    confirm: str
    htf: bool
    oi_flush: bool

    @property
    def stops(self) -> tuple[str, ...]:
        return rs.TESTED_STOPS[self.family]


VARIANTS = (
    RSVariant("RZ_30M", "zone", "30m", "zone", "slot", True, False),
    RSVariant("RZ_1H", "zone", "1h", "zone", "slot", True, False),
    RSVariant("RZ_2H", "zone", "2h", "zone", "slot", True, False),
    RSVariant("RZ_4H", "zone", "4h", "zone", "slot", True, False),
    RSVariant("RZ_1H_CHOCH", "zone", "1h", "zone", "choch15", True, False),
    RSVariant("RZ_2H_CHOCH", "zone", "2h", "zone", "choch15", True, False),
    RSVariant("RZ_2H_ZONDERHTF", "zone", "2h", "zone", "slot", False, False),
    RSVariant("RZ_2H_SPLIT", "zone", "2h", "split", "slot", True, False),
    RSVariant("RS_30M", "sweep", "30m", "ob", "slot", True, False),
    RSVariant("RS_1H", "sweep", "1h", "ob", "slot", True, False),
    RSVariant("RS_2H", "sweep", "2h", "ob", "slot", True, False),
    RSVariant("RS_4H", "sweep", "4h", "ob", "slot", True, False),
    RSVariant("RS_1H_CHOCH", "sweep", "1h", "ob", "choch15", True, False),
    RSVariant("RS_1H_ZONDERHTF", "sweep", "1h", "ob", "slot", False, False),
    RSVariant("RS_1H_OIFLUSH", "sweep", "1h", "ob", "slot", True, True),
)
PRIOR_VARIANTS = 34
TESTED_TOTAL = PRIOR_VARIANTS + sum(len(v.stops) for v in VARIANTS)
EDGE_T_MIN = 3.4
LAB_COST_PCT = 0.12
# Dezelfde drempel en vertraging als replay.lab (pre-registratie, 'OI-daling'): een daling van minstens OI_MOVE_PCT procent.
OI_FLUSH_PCT = -OI_MOVE_PCT
OI_LAG = SAMPLE_LAG
# Trekkingen per echte trade: meer dan één maakt het placebo-gemiddelde per paar stabiel (stopquality.accept middelt per paar).
PLACEBO_DRAWS = 20
PLACEBO_SEED = 7


def oi_change_pct(metrics: Optional[pd.DataFrame], t0: pd.Timestamp, t1: pd.Timestamp) -> Optional[float]:
    """Procentuele verandering van open interest tussen het laatste punt vóór t0 en het laatste vóór t1, elk met OI_LAG vertraging (een 5m-punt staat
    er pas na zijn eigen periode). None als er vóór t0 geen bruikbaar punt is."""
    if metrics is None or metrics.empty:
        return None
    ts, oi = metrics["timestamp"], metrics["oi"].to_numpy(float)
    a, b = int(ts.searchsorted(t0 - OI_LAG, side="right")) - 1, int(ts.searchsorted(t1 - OI_LAG, side="right")) - 1
    if a < 0 or b < 0 or not np.isfinite(oi[a]) or not np.isfinite(oi[b]) or oi[a] == 0:
        return None
    return float((oi[b] / oi[a] - 1) * 100)


def _cached(cache: dict, key, owners: tuple, build: Callable):
    """De cache geldt voor precies de frames waaruit hij gebouwd is (identiteit): een cache die per ongeluk met een andere coin gedeeld wordt,
    rekent opnieuw in plaats van de ranges van de vorige coin te geven."""
    hit = cache.get(key)
    if hit is not None and len(hit[0]) == len(owners) and all(x is y for x, y in zip(hit[0], owners)):
        return hit[1]
    value = build()
    cache[key] = (owners, value)
    return value


def _ranges(v: RSVariant, frames: dict, cache: dict):
    return _cached(cache, ("ranges", v.tf), (frames[v.tf],), lambda: rs.range_series(frames[v.tf], v.tf))


def _trigger(v: RSVariant, frames: dict, cache: dict) -> pd.DataFrame:
    tf = rs.TRIGGER_TF[v.tf]
    return _cached(cache, ("trigger", tf), (frames[tf],), lambda: add_indicators(frames[tf]).reset_index(drop=True))


def _atr15(frames: dict, cache: dict) -> np.ndarray:
    return _cached(cache, ("atr15",), (frames["15m"], frames["1h"]),
                   lambda: sq.atr_on_15m(frames["15m"], add_indicators(frames["1h"]).reset_index(drop=True)))


def load_frames(coin: str, years: float, ensure: Callable = candle_cache.ensure_candles) -> dict[str, pd.DataFrame]:
    """15m, 1u en 4u uit de cache van het lab (gedownload als ze er nog niet zijn); 30m en 2u daaruit samengevoegd."""
    return rs.build_frames(*(ensure(coin, years, timeframe=tf) for tf in ("15m", "1h", "4h")))


def run_coin(v: RSVariant, coin: str, frames: dict, cost_pct: float, cache: dict, metrics: Optional[pd.DataFrame] = None) -> pd.DataFrame:
    """Alle setups van één variant op één coin, per setup één rij per stop van rs.raw_stops (de getoetste en de beschrijvende). `cache` is per coin."""
    b15, atr15 = frames["15m"], _atr15(frames, cache)
    setups, _ = rs.find_setups(frames, v.tf, v.family, v.entry, v.confirm, v.htf, ranges=_ranges(v, frames, cache))
    # Vaste volgorde, zodat row_id niet afhangt van de volgorde waarin de detector zones of sweeps vond.
    setups = sorted(setups, key=lambda s: (s["placed_at"], s["direction"], s["zone_low"], s["zone_high"]))
    rows = []
    for k, s in enumerate(setups):
        if v.oi_flush:
            change = oi_change_pct(metrics, s["sweep_at"], s["return_at"])
            if change is None or change > OI_FLUSH_PCT:
                continue
        _, score = chance_checks.weighted_finish(chance_checks.range_sweep_checks(s["features"], v.tf))
        mid = (s["range_high"] + s["range_low"]) / 2
        short = s["direction"] == "short"
        for name in rs.raw_stops(s):
            stop = rs.final_stop(s, name)
            base = {"row_id": f"{coin}:{v.name}:{k}", "coin": coin, "variant": v.name, "stop_name": name, "placed_at": s["placed_at"],
                    "direction": s["direction"], "grade": chance_checks.grade_of(score), "score": score}
            if not all((stop > p) if short else (stop < p) for _, p in s["legs"]):
                rows.append({**base, "at": s["placed_at"], "filled": False, "cancel": "stop binnen de instapzone"})
                continue
            fills = sq.simulate_fills(s["direction"], s["legs"], stop, mid, b15, s["place_idx15"])
            if not fills["filled"]:
                rows.append({**base, "at": s["placed_at"], "filled": False, "cancel": fills["cancel"]})
                continue
            m = sq.measure(s["direction"], fills["filled"], stop, b15, atr15, s["range_high"], s["range_low"], cost_pct)
            rows.append({**base, "at": b15["timestamp"].iloc[fills["first"]], "filled": True, "cancel": "", **m})
    return pd.DataFrame(rows)


def placebo_coin(v: RSVariant, frames: dict, cache: dict, real: pd.DataFrame, cost_pct: float, seed: int = PLACEBO_SEED,
                 draws: int = PLACEBO_DRAWS) -> pd.DataFrame:
    """Willekeurige instappen voor de gevulde rijen van `real` (één stop, één coin), zie stopquality.placebo_rows."""
    b_tf, ranges = _ranges(v, frames, cache)
    bt = _trigger(v, frames, cache)
    return sq.placebo_rows(real, frames["15m"], bt, rs.active_for(bt, b_tf, ranges, v.tf), _atr15(frames, cache), cost_pct, seed, draws)


def placebo_by_stop(v: RSVariant, frames: dict, cache: dict, rows: pd.DataFrame, cost_pct: float, seed: int = PLACEBO_SEED,
                    draws: int = PLACEBO_DRAWS) -> dict[str, pd.DataFrame]:
    """Per getoetste stop de placeborijen van één coin; de aanroeper voegt ze per stop over de coins samen voor `judge`."""
    return {name: placebo_coin(v, frames, cache, rows[rows["stop_name"] == name] if len(rows) else rows, cost_pct, seed, draws) for name in v.stops}


def edge_verdict(prim: pd.DataFrame, plac: pd.DataFrame) -> dict:
    """De strenge toets op een voordeel: trendlab.evaluate op de netto R bij de meelopende referentie-uitgang, plus t per week van minstens EDGE_T_MIN."""
    if not len(prim):
        return {"n": 0, "passes": False, "t_week": 0.0, "checks": {}, "reason": "geen vullingen"}
    trades = pd.DataFrame({"at": prim["at"], "gross": prim["ref_trail"].astype(float), "net": prim["ref_trail"].astype(float) - prim["cost_r"].astype(float),
                           "risk_pct": prim["stop_pct"].astype(float)})
    placebo = (pd.DataFrame({"gross": plac["ref_trail"].astype(float), "net": plac["ref_trail"].astype(float) - plac["cost_r"].astype(float)})
               if len(plac) else pd.DataFrame(columns=["gross", "net"]))
    ev = tl.evaluate(trades, placebo)
    t = stats.cluster_t(trades["net"].tolist(), [stats.week_key(x) for x in trades["at"]])
    checks = {**ev.get("checks", {}), f"t per week minstens {EDGE_T_MIN}": t >= EDGE_T_MIN}
    passes = bool(ev.get("passes")) and t >= EDGE_T_MIN
    return {**ev, "t_week": t, "checks": checks, "passes": passes, "reason": "" if passes else "faalt: " + ", ".join(k for k, ok in checks.items() if not ok)}


def judge(rows: pd.DataFrame, placebo: dict, v: RSVariant) -> dict:
    """rows: de rijen van alle coins samen voor deze variant. placebo: per getoetste stop de placeborijen van de gevulde rijen met die stop."""
    part = lambda name: rows[rows["stop_name"] == name] if len(rows) else rows
    out = {rs.DESCRIPTIVE_STOP: {"summary": sq.summarize(part(rs.DESCRIPTIVE_STOP))}}
    for name in v.stops:
        p = part(name)
        summary = sq.summarize(p)
        filled = p[p["filled"].astype(bool)] if len(p) else p
        plac = placebo.get(name, pd.DataFrame())
        out[name] = {"summary": summary, "quality": sq.accept(summary, filled, plac), "edge": edge_verdict(filled, plac), "doelkans": sq.doelkans_table(summary)}
    return out


def select_live(results: list[tuple[RSVariant, dict]]) -> Optional[tuple[RSVariant, str]]:
    """Vooraf vastgelegd: geslaagd op stopkwaliteit, dan de meeste vullingen, dan de laagste mediane kosten, dan de bredere stop (buffer, dan mediane
    stopafstand). De laatste sleutels (namen) maken de keuze onafhankelijk van de volgorde van `results`."""
    cands = [(v, name, r[name]) for v, r in results for name in v.stops if r.get(name, {}).get("quality", {}).get("passes")]
    if not cands:
        return None
    v, name, _ = min(cands, key=lambda c: (-c[2]["summary"]["n"], c[2]["summary"]["median_cost_r"], -rs.STOP_BUFFER[c[1]][1],
                                           -c[2]["summary"].get("median_stop_pct", 0.0), c[0].name, c[1]))
    return v, name
