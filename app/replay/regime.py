"""Regime: hoe onrustig is de markt nu, vergeleken met de laatste weken? Een regel die meebeweegt (momentum) hoort in een onrustige markt
te winnen en een regel die terugpakt (mean reversion) in een rustige. Gemiddeld over alles kan dat tegen elkaar wegvallen: bruto nul. Dit
bestand geeft elk moment een label op basis van de gerealiseerde volatiliteit van BTC over de afgelopen 24 uur, gedeeld door de mediaan
van de laatste 30 dagen. Alleen informatie van vóór het moment zelf."""
import numpy as np
import pandas as pd

WINDOW = 1440
HISTORY = 30 * 1440
LOW, HIGH = 0.8, 1.25


def vol_ratio(btc: pd.DataFrame) -> pd.Series:
    """Per minuut: realized vol 24u / mediaan daarvan over 30 dagen. Een minuut later bruikbaar (shift 1), dus zonder de minuut zelf."""
    close = btc.set_index("timestamp")["close"]
    r = np.log(close).diff()
    rv = np.sqrt((r ** 2).rolling(WINDOW, min_periods=WINDOW // 2).sum())
    base = rv.rolling(HISTORY, min_periods=HISTORY // 3).median()
    return (rv / base).shift(1)


def label(ratio: float) -> str:
    if not np.isfinite(ratio):
        return "onbekend"
    return "rustig" if ratio < LOW else "onrustig" if ratio > HIGH else "normaal"


def tag(times: pd.Series, ratio: pd.Series) -> pd.Series:
    """Label per tijdstip (asof: de laatste bekende waarde op of vóór dat moment)."""
    idx = ratio.index.searchsorted(pd.DatetimeIndex(times), side="right") - 1
    values = np.where(idx >= 0, ratio.to_numpy()[np.clip(idx, 0, None)], np.nan)
    return pd.Series([label(v) for v in values], index=times.index if hasattr(times, "index") else None)


def tail_events(btc: pd.DataFrame, minutes: int = 60, threshold_pct: float = 2.5, gap_hours: int = 12) -> pd.DataFrame:
    """Zeldzame uitschieters: BTC beweegt in `minutes` minuten minstens `threshold_pct` procent. Eén gebeurtenis per `gap_hours`.
    Kolommen: at (moment van de uitschieter, bekend na die minuut), move_pct (teken geeft crash of piek), i (positie in het frame)."""
    close = btc["close"].to_numpy()
    move = (close[minutes:] / close[:-minutes] - 1) * 100
    hit = np.flatnonzero(np.abs(move) >= threshold_pct) + minutes
    out, last = [], -10 ** 9
    for i in hit:
        if i - last >= gap_hours * 60:
            out.append((btc["timestamp"].iloc[i], float(move[i - minutes]), int(i)))
            last = i
    return pd.DataFrame(out, columns=["at", "move_pct", "i"])
