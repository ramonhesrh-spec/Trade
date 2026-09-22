"""Chart-patroonherkenning op de 4-uurs candle (config.TIMEFRAME): welk
patroon staat er nu, en wat is de bijbehorende entry/stop/target? Bouwt op
dezelfde pivot-detectie als indicators.detect_sr_zones/detect_trendlines
(indicators._find_pivots), zodat er geen tweede, afwijkende pivot-definitie
ontstaat. Zie docs/superpowers/specs/2026-09-22-patroonherkenning-design.md."""
from dataclasses import dataclass
from typing import Optional

import pandas as pd
import ta

from app import indicators

# Hoe gelijk twee of drie pieken/dalen moeten zijn om als "hetzelfde
# niveau" te tellen. Crypto op de 4u-candle ligt zelden binnen 0.5%
# (SR_ZONE_CLUSTER_TOLERANCE_PCT), 2% is dichter bij hoe deze patronen er
# in de praktijk uitzien.
PEAK_TOLERANCE_PCT = 0.02

# Het hoofd moet minstens dit percentage verder uitsteken dan de
# schouders, anders is het gewoon een triple top/bottom met een
# toevallig randje.
HS_HEAD_MARGIN_PCT = 0.01

# Hoeveel candles na de nek-doorbraak op een geldige terugtest gewacht
# wordt (Task 4, find_entry_options) voordat de kans als vervlogen geldt.
# Zelfde orde-grootte als PENDING_LEVEL_MIN_AGE_MINUTES/4h-candles elders.
NECKLINE_RETEST_MAX_WAIT_CANDLES = 30

# Kleine marge voorbij de extreme van het patroon (top/hoofd/dal) zelf: een
# stop precies OP de extreme zou door een enkele wick al geraakt worden
# terwijl het patroon zelf nog geldig is. Zelfde soort kleine buffer als
# elders in het project (ATR_BUFFER_MULTIPLIER in risk.py), hier als vast
# percentage omdat een patroon-extreme geen eigen ATR-schaal heeft zoals
# een swing-niveau dat wel heeft.
PATTERN_STOP_MARGIN_PCT = 0.005


@dataclass
class PatternMatch:
    name: str
    direction: str  # "long" of "short"
    neckline: float  # of lijnwaarde bij channel_wedge
    extreme: float  # hoogste piek / laagste dal van het patroon zelf
    target: Optional[float]  # None bij divergence (geen gemeten beweging)
    stop_loss: Optional[float]  # None bij divergence
    confirmed_index: int  # candle-index waarop de nek/lijn daadwerkelijk doorbroken werd
    pattern_kind: str  # "top_bottom" | "hs" | "channel_wedge" | "divergence"


def _equal_enough(prices: list[float], tolerance_pct: float) -> bool:
    return (max(prices) - min(prices)) <= tolerance_pct * (sum(prices) / len(prices))


def _find_neckline_break(
    df: pd.DataFrame, after_index: int, neckline: float, kind: str, max_wait: int = 30,
) -> Optional[int]:
    """Eerste candle na het patroon zelf die de nek daadwerkelijk doorbreekt
    (close voorbij de nek, niet alleen een schaduw): zonder deze bevestiging
    is het patroon nooit 'af', slechts een vorm die nog kan mislukken."""
    window = df.iloc[after_index + 1:after_index + 1 + max_wait]
    for idx, row in window.iterrows():
        if kind == "high" and row["close"] < neckline:
            return idx
        if kind == "low" and row["close"] > neckline:
            return idx
    return None


def _pattern_stop_loss(extreme: float, direction: str) -> float:
    return extreme * (1 + PATTERN_STOP_MARGIN_PCT) if direction == "short" \
        else extreme * (1 - PATTERN_STOP_MARGIN_PCT)


def find_double_triple(df: pd.DataFrame, kind: str, n: int) -> list[PatternMatch]:
    """kind='high' -> double/triple top (bearish), kind='low' -> double/
    triple bottom (bullish). n=2 of n=3 pieken/dalen op ongeveer gelijke
    hoogte; de nek is de laagste/hoogste candle tussen de buitenste twee."""
    pivots = sorted([p for p in indicators._find_pivots(df) if p.kind == kind], key=lambda p: p.index)
    direction = "short" if kind == "high" else "long"
    matches = []
    for i in range(len(pivots) - n + 1):
        group = pivots[i:i + n]
        prices = [p.price for p in group]
        if not _equal_enough(prices, PEAK_TOLERANCE_PCT):
            continue
        start, end = group[0].index, group[-1].index
        between = df.iloc[start:end + 1]
        neckline = between["low"].min() if kind == "high" else between["high"].max()
        extreme = max(prices) if kind == "high" else min(prices)
        target = neckline - (extreme - neckline) if kind == "high" else neckline + (neckline - extreme)
        confirmed_index = _find_neckline_break(df, end, neckline, kind)
        if confirmed_index is not None:
            matches.append(PatternMatch(
                name=f"{'triple' if n == 3 else 'double'} {'top' if kind == 'high' else 'bottom'}",
                direction=direction, neckline=neckline, extreme=extreme,
                target=target, stop_loss=_pattern_stop_loss(extreme, direction),
                confirmed_index=confirmed_index, pattern_kind="top_bottom",
            ))
    return matches


def find_head_and_shoulders(df: pd.DataFrame, kind: str) -> list[PatternMatch]:
    """kind='high' -> head & shoulders (bearish), kind='low' -> inverse
    head & shoulders (bullish). Vijf afwisselende pivots nodig: schouder,
    dal, hoofd, dal, schouder (of gespiegeld). Het hoofd moet duidelijk
    verder uitsteken dan de twee schouders, de schouders moeten ongeveer
    gelijk zijn."""
    all_pivots = sorted(indicators._find_pivots(df), key=lambda p: p.index)
    direction = "short" if kind == "high" else "long"
    other = "low" if kind == "high" else "high"
    matches = []
    for i in range(len(all_pivots) - 4):
        window = all_pivots[i:i + 5]
        if [p.kind for p in window] != [kind, other, kind, other, kind]:
            continue
        shoulder1, trough1, head, trough2, shoulder2 = window
        if not _equal_enough([shoulder1.price, shoulder2.price], PEAK_TOLERANCE_PCT):
            continue
        head_beats_shoulders = (
            head.price > max(shoulder1.price, shoulder2.price) * (1 + HS_HEAD_MARGIN_PCT)
            if kind == "high" else
            head.price < min(shoulder1.price, shoulder2.price) * (1 - HS_HEAD_MARGIN_PCT)
        )
        if not head_beats_shoulders:
            continue
        neckline = max(trough1.price, trough2.price) if kind == "high" else min(trough1.price, trough2.price)
        target = neckline - (head.price - neckline) if kind == "high" else neckline + (neckline - head.price)
        confirmed_index = _find_neckline_break(df, shoulder2.index, neckline, kind)
        if confirmed_index is not None:
            matches.append(PatternMatch(
                name="head & shoulders" if kind == "high" else "inverse head & shoulders",
                direction=direction, neckline=neckline, extreme=head.price,
                target=target, stop_loss=_pattern_stop_loss(head.price, direction),
                confirmed_index=confirmed_index, pattern_kind="hs",
            ))
    return matches


def find_reversal_patterns(df: pd.DataFrame) -> list[PatternMatch]:
    """Alle bevestigde double/triple top/bottom- en head & shoulders-
    matches in dit candle-venster, nieuwste eerst niet gegarandeerd (zie
    caller: market_scanner pakt zelf de match met de hoogste
    confirmed_index)."""
    matches: list[PatternMatch] = []
    matches += find_double_triple(df, "high", 2)
    matches += find_double_triple(df, "low", 2)
    matches += find_double_triple(df, "high", 3)
    matches += find_double_triple(df, "low", 3)
    matches += find_head_and_shoulders(df, "high")
    matches += find_head_and_shoulders(df, "low")
    return matches


# Hoeveel de breedte tussen de twee lijnen aan begin en eind van het
# venster nog van elkaar mag afwijken (als fractie van de gemiddelde
# breedte) om als "ongeveer evenwijdig" (kanaal) te tellen in plaats van
# convergerend/divergerend (wedge/driehoek).
CHANNEL_PARALLEL_TOLERANCE_PCT = 0.15

# De twee lijnen moeten minstens dit veelvoud van de ATR uit elkaar
# liggen, anders is de "vorm" ruis: twee bijna samenvallende lijnen zijn
# geen bruikbaar kanaal/wedge.
MIN_PATTERN_WIDTH_ATR_MULTIPLE = 0.5


def classify_channel_wedge(
    trendlines: list[indicators.Trendline], window_len: int, atr: float,
) -> Optional[PatternMatch]:
    """Herkent kanaal/wedge uit de twee lijnen van indicators.detect_trendlines:
    resistance (bovenlijn) en support (onderlijn) allebei dezelfde kant op
    hellend. Beide omhoog en ongeveer evenwijdig -> rising channel
    (bearish, breekt naar beneden door de steunlijn); beide omhoog en
    convergerend -> rising wedge (zelfde richting, scherper). Beide omlaag
    en evenwijdig -> descending channel (bullish, breekt naar boven door
    de weerstandlijn); beide omlaag en convergerend -> falling wedge.

    Driehoek-vormen (tegengestelde hellingen: symmetrical/expanding
    triangle) hebben geen betrouwbare richting uit geometrie alleen — het
    patronenblad van de gebruiker plaatst ze zelf apart als "50/50 kans".
    Die blijven hier bewust ongedetecteerd (geen PatternMatch, dus geen
    aparte melding); een echte uitbraak van zo'n vorm wordt al gevangen
    door de bestaande indicators.find_trendline_breakout_retest via
    market_scanner._check_trendline_retest, ongeacht welke kant hij
    doorbreekt."""
    resistance = next((l for l in trendlines if l.kind == "resistance"), None)
    support = next((l for l in trendlines if l.kind == "support"), None)
    if resistance is None or support is None:
        return None

    start_idx, end_idx = 0, window_len - 1
    width_start = resistance.value_at(start_idx) - support.value_at(start_idx)
    width_end = resistance.value_at(end_idx) - support.value_at(end_idx)
    if width_start <= 0 or width_end <= 0:
        return None  # lijnen kruisen al binnen dit venster, geen bruikbare vorm
    if atr and min(width_start, width_end) < MIN_PATTERN_WIDTH_ATR_MULTIPLE * atr:
        return None

    res_rising = resistance.slope > 0
    sup_rising = support.slope > 0
    if res_rising != sup_rising:
        return None  # driehoek-vorm, zie docstring

    avg_width = (width_start + width_end) / 2
    width_change_pct = (width_end - width_start) / avg_width
    parallel = abs(width_change_pct) <= CHANNEL_PARALLEL_TOLERANCE_PCT

    if res_rising:
        name = "rising channel" if parallel else "rising wedge"
        direction = "short"
        breakout_level = support.value_at(end_idx)
        stop_loss = resistance.value_at(end_idx) * (1 + PATTERN_STOP_MARGIN_PCT)
        height = width_start
        target = breakout_level - height
    else:
        name = "descending channel" if parallel else "falling wedge"
        direction = "long"
        breakout_level = resistance.value_at(end_idx)
        stop_loss = support.value_at(end_idx) * (1 - PATTERN_STOP_MARGIN_PCT)
        height = width_start
        target = breakout_level + height

    return PatternMatch(
        name=name, direction=direction, neckline=breakout_level, extreme=stop_loss,
        target=target, stop_loss=stop_loss, confirmed_index=end_idx, pattern_kind="channel_wedge",
    )


def find_divergence(df: pd.DataFrame) -> Optional[PatternMatch]:
    """Bullish divergence: prijs zet een lagere bodem neer, RSI juist een
    hogere (minder oversold dan de vorige bodem) — momentum zwakt af
    terwijl de prijs nog daalt, vaak een voorbode van een omkeer. Bearish:
    spiegelbeeld op pieken. Kijkt alleen naar de laatste twee pivots van
    hetzelfde soort, niet naar elk historisch paar: voor live signalering
    telt of er NU een divergentie staat, niet of er ooit één stond.

    Puur momentum-signaal, geen eigen neckline/hoogte zoals top/bottom of
    channel_wedge — target/stop_loss blijven None, de caller (Task 4/7)
    valt voor deze pattern_kind terug op risk.compute_stop_take (ATR)."""
    window = df.tail(indicators.SR_ZONE_LOOKBACK).reset_index(drop=True)
    rsi_series = ta.momentum.RSIIndicator(window["close"], window=14).rsi()
    pivots = indicators._find_pivots(window)

    lows = sorted([p for p in pivots if p.kind == "low"], key=lambda p: p.index)
    if len(lows) >= 2:
        prev, last = lows[-2], lows[-1]
        rsi_prev, rsi_last = rsi_series.iloc[prev.index], rsi_series.iloc[last.index]
        if (
            not pd.isna(rsi_prev) and not pd.isna(rsi_last)
            and last.price < prev.price and rsi_last > rsi_prev
        ):
            return PatternMatch(
                name="bullish divergence", direction="long", neckline=last.price,
                extreme=last.price, target=None, stop_loss=None,
                confirmed_index=last.index, pattern_kind="divergence",
            )

    highs = sorted([p for p in pivots if p.kind == "high"], key=lambda p: p.index)
    if len(highs) >= 2:
        prev, last = highs[-2], highs[-1]
        rsi_prev, rsi_last = rsi_series.iloc[prev.index], rsi_series.iloc[last.index]
        if (
            not pd.isna(rsi_prev) and not pd.isna(rsi_last)
            and last.price > prev.price and rsi_last < rsi_prev
        ):
            return PatternMatch(
                name="bearish divergence", direction="short", neckline=last.price,
                extreme=last.price, target=None, stop_loss=None,
                confirmed_index=last.index, pattern_kind="divergence",
            )
    return None


def _check_neckline_retest(df: pd.DataFrame, match: PatternMatch, atr: float) -> Optional[tuple[float, float]]:
    """Is de prijs sinds de nek-doorbraak (match.confirmed_index) weer
    teruggekomen tot dichtbij de nek zelf, zonder de doorbraak ongedaan te
    maken? Zelfde soort toets als indicators.find_breakout_retest, hier op
    één niveau (de nek) in plaats van een zone met een boven- en
    ondergrens. Geeft (low, high) van de retest-band terug, of None als er
    nog geen (geldige) terugtest is geweest."""
    closes = df["close"].reset_index(drop=True)
    if match.confirmed_index >= len(closes) - 1:
        return None
    since = closes.iloc[match.confirmed_index + 1:]
    tolerance = indicators.BREAKOUT_RETEST_TOLERANCE_ATR_MULTIPLE * atr
    current = closes.iloc[-1]
    if match.direction == "short":
        if (since > match.neckline).any():
            return None
        if abs(current - match.neckline) <= tolerance:
            return (match.neckline - tolerance, match.neckline + tolerance)
    else:
        if (since < match.neckline).any():
            return None
        if abs(current - match.neckline) <= tolerance:
            return (match.neckline - tolerance, match.neckline + tolerance)
    return None


def find_entry_options(
    df: pd.DataFrame, match: PatternMatch, atr: float,
    trendlines: Optional[list[indicators.Trendline]] = None,
) -> dict:
    """Twee entry-opties voor een bevestigd patroon: het uitbraakniveau
    zelf (breakout_level, snel, kan nog zonder terugtest zijn) en, als de
    prijs al is teruggekeerd, het retest-niveau (bevestigd). retest_low/
    retest_high zijn None zolang er nog geen retest is geweest — de kaart
    toont dan alleen de uitbraak-optie."""
    if match.pattern_kind == "channel_wedge" and trendlines:
        line = next(
            (l for l in trendlines if (l.kind == "resistance") == (match.direction == "long")), None,
        )
        if line is not None:
            window_len = len(df.tail(indicators.SR_ZONE_LOOKBACK))
            hits = indicators.find_trendline_breakout_retest(df, [line], atr, match.direction)
            if hits:
                tolerance = indicators.BREAKOUT_RETEST_TOLERANCE_ATR_MULTIPLE * atr
                current_value = line.value_at(window_len - 1)
                return {
                    "breakout_level": match.neckline,
                    "retest_low": current_value - tolerance,
                    "retest_high": current_value + tolerance,
                }
        return {"breakout_level": match.neckline, "retest_low": None, "retest_high": None}

    if match.pattern_kind in ("top_bottom", "hs"):
        retest = _check_neckline_retest(df, match, atr)
        return {
            "breakout_level": match.neckline,
            "retest_low": retest[0] if retest else None,
            "retest_high": retest[1] if retest else None,
        }

    return {"breakout_level": match.neckline, "retest_low": None, "retest_high": None}
