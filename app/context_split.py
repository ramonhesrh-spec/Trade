"""Hypothese H1 (docs/onderzoek/hypotheses.md): staat een trade mee met, tegen of los van de 4u-context van de eigen coin en van BTC?

Alleen meting. Geen motor, filter of melding leest dit. De context is precies die van het HesPulse-model (`model.Context4h`): een 4u-breuk
omhoog (long) of omlaag (short, gespiegeld) die op het moment van de trade al herkenbaar was, hoogstens `model.BIAS_MAX_BARS` candles oud,
en nog niet ongedaan gemaakt door een slot voorbij de range. Zo meet H1 de regel die het model al gebruikt, niet een nieuwe die we achteraf
kiezen."""
from typing import Optional

import pandas as pd

from app import model

MEE, TEGEN, NEUTRAAL, ONBEKEND = "mee", "tegen", "neutraal", "onbekend"
GROUPS = (MEE, TEGEN, NEUTRAAL, ONBEKEND)
# 400 candles van 4u (ruim 66 dagen): genoeg voor 30 dagen trades plus de 60 candles bias en de ATR-aanloop.
FETCH_4H = 400


def _ts(t) -> pd.Timestamp:
    t = pd.Timestamp(t)
    return t.tz_localize("UTC") if t.tzinfo is None else t.tz_convert("UTC")


class Bias:
    """De 4u-context van één coin voor beide richtingen, één keer opgebouwd en dan per moment op te vragen."""

    def __init__(self, df4: Optional[pd.DataFrame]):
        self.ok = df4 is not None and len(df4) > model.BIAS_MAX_BARS
        if self.ok:
            self.first = _ts(df4["timestamp"].iloc[0]) + model.TF["4h"] * (model.BIAS_MAX_BARS + 20)
            self.ctx = {"long": model.Context4h(model._frame(df4, "4h", False), "long"),
                        "short": model.Context4h(model._frame(df4, "4h", True), "short")}

    def side(self, t) -> Optional[str]:
        """'long', 'short' of None (geen bruikbare breuk) op moment t; ONBEKEND als de candles niet ver genoeg terug gaan."""
        t = _ts(t)
        if not self.ok or t < self.first:
            return ONBEKEND
        ns = t.value
        if self.ctx["long"].at(ns) is not None:
            return "long"
        if self.ctx["short"].at(ns) is not None:
            return "short"
        return None

    def group(self, direction: str, t) -> str:
        s = self.side(t)
        if s == ONBEKEND:
            return ONBEKEND
        return NEUTRAAL if s is None else MEE if s == direction else TEGEN
