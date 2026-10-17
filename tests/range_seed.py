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
