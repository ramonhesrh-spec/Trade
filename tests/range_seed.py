"""Gedeelde zaaihulp voor de paginatests van de range sweep: een wachtende setup met plan, en een labrij met doelkans."""
import json
from datetime import datetime, timedelta, timezone

from app import repo

LAB = {"variant": "RZ_2H", "stop_name": "zone_05", "doelkans": [{"r": r, "p_text": f"{60 - 8 * r}%", "ci_text": "40 tot 60%", "n": 412} for r in range(1, 7)]}


def setup_row(coin="ARB", direction="short", hours_left=5.0, **kw):
    """Een zone-retest op 2u bij een koers van 100 (de tests mocken 100): short met limieten op 101 en 101,5 en stop 103, long gespiegeld."""
    now = datetime.now(timezone.utc)
    short = direction == "short"
    candles = [[(now - timedelta(hours=2 * (30 - i))).isoformat(), 99.0 + (i % 5) * 0.4, 100.6 + (i % 5) * 0.4, 98.6 + (i % 5) * 0.4, 99.5 + (i % 4) * 0.4] for i in range(30)]
    zone_low, zone_high = (101.0, 102.0) if short else (98.0, 99.0)
    plan = {"tf": "2h", "candles": candles, "zones": [{"low": 104.0, "high": 105.0, "from": candles[2][0], "kind": "aanbod"}], "stop": 103.0 if short else 97.0,
            "mid": 99.0 if short else 101.0, "opp": 90.0 if short else 110.0}
    row = {"coin": coin, "direction": direction, "variant": "RZ_2H", "family": "zone", "stop_name": "zone_05", "range_tf": "2h",
           "range_high": 108.0 if short else 110.0, "range_low": 90.0 if short else 92.0, "range_first_at": candles[4][0], "zone_low": zone_low, "zone_high": zone_high,
           "zone_at": candles[20][0], "sweep_at": None, "extreme": None, "placed_at": (now - timedelta(hours=1)).isoformat(),
           "legs": json.dumps([[0.4, 101.0], [0.6, 101.5]] if short else [[0.4, 99.0], [0.6, 98.5]]), "stop": 103.0 if short else 97.0, "atr_t": 1.0,
           "score": 85.0, "grade": "A", "reason": "✓ Beide randen minstens 4 keer aangeraakt | ✗ Zone dun (hooguit 1,5 ATR)", "features": "{}",
           "liq_json": json.dumps({"ok": False}), "expires_at": (now + timedelta(hours=hours_left)).isoformat(), "plan": json.dumps(plan)}
    row.update(kw)
    return row


def seed_setup(**kw) -> int:
    return repo.insert_range_sweep_setup(setup_row(**kw))


def seed_lab(passes=True) -> None:
    repo.set_rule_lab("range_sweep_stop", passes, LAB, datetime.now(timezone.utc).isoformat())


def seed_trade(coin="ARB", direction="short", ref_r=None, stop_hit=False, closed=False, reached=0, mae=0.0, mfe=0.0, **setup_kw) -> int:
    """Een gevulde range sweep: setup in staat 'filled', signaal, meting en (met ref_r) de referentie-uitkomst zoals de motor ze schrijft. Geeft het signaal-id.
    reached: tot en met welk R-niveau (1 tot 6) de koers vóór de stop kwam."""
    now = datetime.now(timezone.utc)
    setup_kw.setdefault("placed_at", (now - timedelta(hours=33)).isoformat())          # de limiet staat er vóór hij vult
    setup_id = seed_setup(coin=coin, direction=direction, **setup_kw)
    short = direction == "short"
    entry, stop = (101.3, 103.0) if short else (98.7, 97.0)
    filled_at = (now - timedelta(hours=30)).isoformat()
    signal_id = repo.insert_signal({
        "message_id": None, "coin": coin, "direction": direction, "category": "day_trading", "trade_type": "range_sweep", "pattern_name": "RZ_2H",
        "price": entry, "stop_loss": stop, "take_profit": None, "confidence": "Zone-retest A", "reason": "✓ a | ✗ b", "pass_pct": 85.0,
        "technical_confirmed": 1, "hard_gates_ok": 1, "is_practice": 0, "plain_explanation": "Zone-retest 2u: limiet gevuld."}, chain_it=False)
    repo.set_range_sweep_setup_state(setup_id, "filled", signal_id)
    repo.insert_range_sweep_trade(signal_id, setup_id, json.dumps([[0.4, 101.0, filled_at], [0.6, 101.5, (now - timedelta(hours=29)).isoformat()]]), entry, stop, filled_at)
    fields = {"mae_r": mae, "mfe_r": mfe, **{f"reached_{k}r_at": (now - timedelta(hours=28 - k)).isoformat() for k in range(1, reached + 1)}}
    if stop_hit:
        fields["stop_hit_at"] = (now - timedelta(hours=5)).isoformat()
    if closed or stop_hit:
        fields["closed_at"] = (now - timedelta(hours=4)).isoformat()
    if ref_r is not None:
        fields.update(ref_r=ref_r, ref_closed_at=(now - timedelta(hours=5)).isoformat())
        repo.set_trade_result(signal_id, ref_r, (now - timedelta(hours=5)).isoformat())
        repo.mark_signal_auto_outcome(signal_id, "take_profit" if ref_r > 0 else "stop_loss", (now - timedelta(hours=5)).isoformat())
    if fields:
        repo.update_range_sweep_trade(signal_id, **fields)
    return signal_id


STOP_SUMMARY = {"n": 412, "weeks": 120, "stop_hit": {"p": 0.55, "ci": [0.5, 0.6]}, "reach": {str(k): {"p": 0.5 / k, "ci": [0.4 / k, 0.6 / k]} for k in range(1, 7)},
                "median_stop_pct": 2.4, "median_cost_r": 0.05, "tight_rate": 0.18, "mae_q": [0.3, 0.6, 0.9, 1.0], "mfe_q": [0.4, 0.9, 1.8, 3.1]}


def seed_labs(stop_passes=True, edge_passes=False) -> None:
    """Zoals strategy_lab --opslaan ze schrijft: de stopkwaliteit (de kop van de proef) en de strenge toets ernaast. Verwacht: stop PASS, voordeel FAIL."""
    now = datetime.now(timezone.utc).isoformat()
    repo.set_rule_lab("range_sweep_stop", stop_passes, {**LAB, "quality": {"passes": stop_passes}, "summary": STOP_SUMMARY}, now)
    repo.set_rule_lab("range_sweep", edge_passes, {"variant": "RZ_2H", "stop_name": "zone_05", "n": 412, "avg": 0.02, "t_week": 1.1,
                                                   "reason": "t_week 1,1 onder de horde van 3,4"}, now)
