"""Afspeel-engine voor SMC-setups: bootst market_scanner._run_smc_check na op een
1m-basis, met de setups in het geheugen (SmcBook, gelijk aan de smc_setups-tabel
en repo.upsert_smc_setup) in plaats van in de database. De beslislogica komt
uit app/smc_eval.py, dezelfde code als live. Niet nagebootst: pushmeldingen,
journal-fan-out en de structurele tegenstrijdigheid-onderdrukking van scan_market."""
from dataclasses import dataclass
from datetime import timedelta
from typing import Optional

import pandas as pd

from app import smc_eval
from app.replay.candles import BASE_DELTAS
from app.replay.outcome import Outcome, resolve
from app.replay.view import ReplayData

ONE_MINUTE = BASE_DELTAS["1m"]
# Zelfde waarde en betekenis als repo.ZONE_DEDUP_PCT; een test bewaakt dat ze gelijk blijven.
ZONE_DEDUP_PCT = 0.3


class SmcBook:
    """In-memory spiegel van de smc_setups-tabel."""

    def __init__(self):
        self._rows: list[dict] = []
        self._next_id = 1

    def upsert(self, coin, direction, zone_low, zone_high, structure_level, sweep_price,
               liquidity_target, atr, seen_until, now_iso) -> int:
        zone_mid = (zone_low + zone_high) / 2
        same_event = next((r for r in reversed(self._rows)
                           if r["coin"] == coin and r["direction"] == direction
                           and r["structure_level"] == structure_level and r["sweep_price"] == sweep_price), None)
        if same_event is not None:
            if same_event["signal_id"] is None and same_event["invalidated_at"] is None:
                same_event.update(zone_low=zone_low, zone_high=zone_high,
                                  liquidity_target=liquidity_target, updated_at=seen_until)
            return same_event["id"]
        # Invoegvolgorde (zoals de tabel), niet forming()'s sortering: live neemt de eerste treffer.
        for row in self._rows:
            if row["coin"] != coin or row["direction"] != direction \
                    or row["signal_id"] is not None or row["invalidated_at"] is not None:
                continue
            existing_mid = (row["zone_low"] + row["zone_high"]) / 2
            if existing_mid and abs(existing_mid - zone_mid) <= ZONE_DEDUP_PCT / 100 * zone_mid:
                row.update(zone_low=zone_low, zone_high=zone_high, structure_level=structure_level,
                           sweep_price=sweep_price, liquidity_target=liquidity_target, atr=atr, updated_at=seen_until)
                return row["id"]
        row = {"id": self._next_id, "coin": coin, "direction": direction, "zone_low": zone_low,
               "zone_high": zone_high, "structure_level": structure_level, "sweep_price": sweep_price,
               "liquidity_target": liquidity_target, "atr": atr, "alert_sent": 0, "signal_id": None,
               "created_at": now_iso, "updated_at": seen_until, "invalidated_at": None, "ended_because": None}
        self._next_id += 1
        self._rows.append(row)
        return row["id"]

    def forming(self, coin: Optional[str] = None) -> list[dict]:
        rows = [r for r in self._rows if r["signal_id"] is None and r["invalidated_at"] is None
                and (coin is None or r["coin"] == coin)]
        return sorted(rows, key=lambda r: r["updated_at"], reverse=True)

    def invalidate(self, setup_id: int, why: str, at_iso: str) -> None:
        # Net als repo.invalidate_smc_setup: alleen een nog bouwende rij.
        for r in self._rows:
            if r["id"] == setup_id and r["signal_id"] is None and r["invalidated_at"] is None:
                r["invalidated_at"], r["ended_because"] = at_iso, why

    def complete(self, setup_id: int, signal_index: int) -> None:
        for r in self._rows:
            if r["id"] == setup_id:
                r["signal_id"] = signal_index

    def all_setups(self) -> list[dict]:
        return [dict(r) for r in self._rows]


@dataclass
class SmcSignal:
    coin: str
    direction: str
    at: pd.Timestamp
    entry: float
    stop: float
    take: float
    setup_id: int
    outcome: Optional[Outcome]
    sniper_price: Optional[float] = None


@dataclass
class SmcFunnelEvent:
    at: pd.Timestamp
    coin: str
    direction: Optional[str]
    kind: str
    detail: str = ""


def _emit(events, t, coin, direction, kind, detail=""):
    if events is not None:
        events.append(SmcFunnelEvent(t, coin, direction, kind, detail))


def _check_cycle(coin, data, book, t, events):
    """Spiegel van market_scanner._check_smc_setup. Geeft de afgewezen setup (dict) of None.

    t mag niet exact op een 15-minutengrens liggen: de afgeleide vormende 15m-candle
    zou dan de laatste gesloten candle zijn en iloc[:-1] laat een gesloten candle
    vallen, anders dan live (replay_smc weigert zulke tijdstippen)."""
    df_15m = data.fetch_ohlcv(coin, timeframe="15m")
    closed_15m = df_15m.iloc[:-1]
    last_candle = closed_15m.iloc[-1]
    now = t.to_pydatetime()
    now_iso = t.isoformat()

    existing = book.forming(coin)
    for existing_setup in existing:
        if smc_eval.setup_expired(existing_setup, now):
            book.invalidate(existing_setup["id"], "vervallen", now_iso)
            _emit(events, t, coin, existing_setup["direction"], "setup_vervallen")
            continue
        verdict = smc_eval.judge_forming_setup(existing_setup, closed_15m)
        if verdict == "rejected":
            return existing_setup
        if verdict == "passed":
            book.invalidate(existing_setup["id"], "doorbraak", now_iso)
            _emit(events, t, coin, existing_setup["direction"], "setup_doorbroken")
            continue

    df_30m = data.fetch_ohlcv(coin, timeframe="30m", limit=smc_eval.SMC_ZONE_SEARCH_LOOKBACK_30M + 1)
    closed_30m = df_30m.iloc[:-1]
    scan = smc_eval.find_candidate(closed_30m, df_30m, closed_15m, last_candle)
    if scan.break_direction is None:
        _emit(events, t, coin, None, scan.skip_reason)
        return None
    for existing_setup in existing:
        # Live roept invalidate ook op al ongeldige rijen aan (zonder effect); hier
        # de controle vooraf zodat het geen dubbele melding geeft.
        if existing_setup["direction"] != scan.break_direction and existing_setup["invalidated_at"] is None \
                and existing_setup["signal_id"] is None:
            book.invalidate(existing_setup["id"], "tegenrichting", now_iso)
            _emit(events, t, coin, existing_setup["direction"], "setup_tegenrichting")
    if scan.candidate is None:
        _emit(events, t, coin, scan.break_direction, scan.skip_reason, scan.detail)
        return None
    c = scan.candidate
    known = {r["id"] for r in book.all_setups()}
    seen_until = (last_candle["timestamp"] + timedelta(minutes=smc_eval.SMC_ENTRY_CANDLE_MINUTES)).isoformat()
    setup_id = book.upsert(coin, c.direction, c.zone_low, c.zone_high, c.structure_level, c.sweep_price,
                           c.liquidity_target, c.atr, seen_until, now_iso)
    if setup_id not in known:
        _emit(events, t, coin, c.direction, "setup_gebouwd")
    setup = next((s for s in book.forming(coin) if s["id"] == setup_id), None)
    if setup is None:
        return None
    _, rejected, _ = smc_eval.last_candle_state(last_candle, c.zone_low, c.zone_high, c.direction)
    if rejected:
        return setup
    return None


def replay_smc(
    coin: str, base: dict, outcome_frame: pd.DataFrame, start: pd.Timestamp, end: pd.Timestamp,
    step: pd.Timedelta = pd.Timedelta(minutes=5), max_age: pd.Timedelta = pd.Timedelta(days=2),
    fee_pct: float = 0.1, slippage_pct: float = 0.05, events: Optional[list] = None,
    book: Optional[SmcBook] = None,
) -> list[SmcSignal]:
    """book: optioneel eigen SmcBook, zodat de aanroeper de setups achteraf kan lezen."""
    if book is None:
        book = SmcBook()
    signals: list[SmcSignal] = []
    if any(x.minute % 15 == 0 and x.second == 0 for x in pd.date_range(start, end, freq=step)):
        raise ValueError("start/step leveren een tijdstip op een 15-minutengrens op (zie _check_cycle)")
    t = start
    while t <= end:
        data = ReplayData(base, t, base_delta=ONE_MINUTE)
        # Live bestaat dit probleem niet; hier is er aan het begin van de data of bij gaten in de
        # 1m-basis te weinig 30m-historie voor de structuurscan.
        if len(data.fetch_ohlcv(coin, timeframe="30m", limit=smc_eval.SMC_ZONE_SEARCH_LOOKBACK_30M + 1)) < \
                smc_eval.SMC_ZONE_SEARCH_LOOKBACK_30M + 1:
            _emit(events, t, coin, None, "te_weinig_historie")
        else:
            setup = _check_cycle(coin, data, book, t, events)
            if setup is not None:
                df_15m = data.fetch_ohlcv(coin, timeframe="15m")
                completion = smc_eval.evaluate_completion(setup, df_15m)
                if completion.signal is None:
                    _emit(events, t, coin, setup["direction"], "afgewezen_geen_signaal", completion.reject_reason)
                else:
                    d = completion.signal
                    outcome = resolve(setup["direction"], d.entry_price, d.stop_loss, d.take_profit,
                                      outcome_frame, t, max_age, fee_pct, slippage_pct)
                    signals.append(SmcSignal(coin, setup["direction"], t, d.entry_price, d.stop_loss, d.take_profit,
                                             setup["id"], outcome, d.sniper_entry_price))
                    book.complete(setup["id"], len(signals))
                    _emit(events, t, coin, setup["direction"], "signaal")
        t += step
    return signals
