"""Labfamilie zone-sweep (docs/onderzoek/zone-sweep/preregistratie.md). Zeven varianten, elk met twee getoetste stops, vooraf vastgelegd: niets
hier wordt na een run aangepast of toegevoegd. Dezelfde machinerie als de range sweep (rangesweep_lab): vulling, verval en meting via
`rangesweep_lab.stop_row`, de kop is de stopkwaliteit (stopquality.accept), de strenge toets (`rangesweep_lab.edge_verdict`, t per week van
minstens EDGE_T_MIN) staat ernaast. Kosten, jaren, placebo-trekkingen en seed zijn die van de range sweep.

Placebo: per gevulde trade een willekeurig 1u-slot binnen een actieve zone van dezelfde soort (vraagzone bij long, aanbodzone bij short) op het
timeframe van de variant, zonder prik of herstel, met dezelfde stopafstand in ATR (stopquality.placebo_rows, zonesweep.active_zones)."""
from dataclasses import dataclass
from typing import Optional

import pandas as pd

from app.replay import rangesweep_lab as rl, stopquality as sq, zonesweep as zs
from app.replay.lab import add_indicators


@dataclass(frozen=True)
class ZSVariant:
    name: str
    tf: str
    entry: str
    htf: bool
    oi_flush: bool = False

    @property
    def stops(self) -> tuple[str, ...]:
        return zs.TESTED_STOPS

    @property
    def descriptive_stop(self) -> Optional[str]:
        # zonesweep.raw_stops kent alleen de twee getoetste stops; er is geen beschrijvende stop zoals zone_0 bij de range sweep.
        return None


VARIANTS = (
    ZSVariant("ZS_1H", "1h", "zone", True),
    ZSVariant("ZS_2H", "2h", "zone", True),
    ZSVariant("ZS_4H", "4h", "zone", True),
    ZSVariant("ZS_1H_ZONDERHTF", "1h", "zone", False),
    ZSVariant("ZS_2H_ZONDERHTF", "2h", "zone", False),
    ZSVariant("ZS_4H_ZONDERHTF", "4h", "zone", False),
    ZSVariant("ZS_2H_MIDDEN", "2h", "midden", True),
)
# Register: 34 eerder bekeken varianten plus de 30 toetsen van de range sweep (rangesweep_lab.TESTED_TOTAL = 64), plus deze 14.
PRIOR_VARIANTS = rl.TESTED_TOTAL
TESTED_TOTAL = PRIOR_VARIANTS + sum(len(v.stops) for v in VARIANTS)
KILL_TESTS = sum(len(v.stops) for v in VARIANTS)
EDGE_T_MIN = rl.EDGE_T_MIN
LAB_COST_PCT = rl.LAB_COST_PCT
LAB_YEARS = rl.LAB_YEARS
PLACEBO_DRAWS = rl.PLACEBO_DRAWS
PLACEBO_SEED = rl.PLACEBO_SEED
STOP_KEY, EDGE_KEY = "zone_sweep_stop", "zone_sweep"

load_frames = rl.load_frames
edge_verdict = rl.edge_verdict
judge = rl.judge


def _setups(v: ZSVariant, frames: dict, cache: dict) -> list[dict]:
    return rl._cached(cache, ("zs_setups", v.tf, v.entry, v.htf), (frames[v.tf], frames[zs.TRIGGER_TF], frames["15m"], frames["4h"]),
                      lambda: zs.find_setups(frames, v.tf, v.entry, v.htf)[0])


def _trigger(frames: dict, cache: dict) -> pd.DataFrame:
    return rl._cached(cache, ("trigger", zs.TRIGGER_TF), (frames[zs.TRIGGER_TF],),
                      lambda: add_indicators(frames[zs.TRIGGER_TF]).reset_index(drop=True))


def _active(v: ZSVariant, kind: str, frames: dict, cache: dict) -> list:
    return rl._cached(cache, ("zs_active", v.tf, kind), (frames[v.tf], frames[zs.TRIGGER_TF]), lambda: zs.active_zones(frames, v.tf, kind))


def run_coin(v: ZSVariant, coin: str, frames: dict, cost_pct: float, cache: dict, metrics=None) -> pd.DataFrame:
    """Alle setups van één variant op één coin, per setup één rij per getoetste stop. `metrics` (OI) wordt niet gebruikt: de zone-sweep heeft geen
    OI-variant; de parameter staat er zodat de aanroeper beide families gelijk behandelt."""
    b15, atr15 = frames["15m"], rl._atr15(frames, cache)
    setups = sorted(_setups(v, frames, cache), key=lambda s: (s["placed_at"], s["direction"], s["zone_low"], s["zone_high"]))
    rows = []
    for k, s in enumerate(setups):
        rows += [rl.stop_row(s, name, zs.final_stop(s, name), f"{coin}:{v.name}:{k}", coin, v.name, b15, atr15, cost_pct) for name in zs.raw_stops(s)]
    return pd.DataFrame(rows)


def placebo_coin(v: ZSVariant, frames: dict, cache: dict, real: pd.DataFrame, cost_pct: float, seed: int = PLACEBO_SEED,
                 draws: int = PLACEBO_DRAWS) -> pd.DataFrame:
    """Per kant een eigen kandidatenset (long in vraagzones, short in aanbodzones). Short trekt met seed + 1, zodat de twee kanten niet dezelfde
    reeks trekkingen delen; de uitkomst hangt nog steeds alleen van de seed af."""
    if not len(real):
        return pd.DataFrame()
    bt, atr15 = _trigger(frames, cache), rl._atr15(frames, cache)
    parts = []
    for direction, kind, sd in ((zs.LONG, "bull", seed), (zs.SHORT, "bear", seed + 1)):
        side = real[real["direction"] == direction]
        if len(side):
            parts.append(sq.placebo_rows(side, frames["15m"], bt, _active(v, kind, frames, cache), atr15, cost_pct, sd, draws))
    parts = [p for p in parts if len(p)]
    return pd.concat(parts, ignore_index=True) if parts else pd.DataFrame()


def placebo_by_stop(v: ZSVariant, frames: dict, cache: dict, rows: pd.DataFrame, cost_pct: float, seed: int = PLACEBO_SEED,
                    draws: int = PLACEBO_DRAWS) -> dict[str, pd.DataFrame]:
    return {name: placebo_coin(v, frames, cache, rows[rows["stop_name"] == name] if len(rows) else rows, cost_pct, seed, draws) for name in v.stops}


def select_live(results: list[tuple]) -> Optional[tuple]:
    """Dezelfde vooraf vastgelegde keuze als de range sweep, met de buffers van zonesweep.BUFFERS."""
    return rl.select_live(results, buffer=lambda name: zs.BUFFERS[name])
