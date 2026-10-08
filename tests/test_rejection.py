import asyncio
import unittest
from unittest import mock

import numpy as np
import pandas as pd

from app import config, repo, smc_eval
from app import rejection_live as rl
from app.replay import rejection as rj
from tests.test_samenval import DbCase


def frame(direction: str, trigger: int = 150) -> pd.DataFrame:
    """Golvende koers met drie toppen (short) of drie dalen (long) op 103 / 97 en een afwijzing op `trigger`."""
    n = 200
    t = pd.date_range("2026-10-01", periods=n, freq="30min", tz="UTC")
    mid = 100 + np.sin(np.arange(n) / 9)
    o, c = mid.copy(), mid.copy() + np.random.default_rng(1).normal(0, 0.05, n)
    h, l = np.maximum(o, c) + 0.15, np.minimum(o, c) - 0.15
    if direction == "short":
        h[[60, 90, 120]] = 103.0
        o[[60, 90, 120]], c[[60, 90, 120]] = 102.2, 102.4
        h[trigger], o[trigger], c[trigger] = 103.05, 102.8, 101.9
    else:
        l[[60, 90, 120]] = 97.0
        o[[60, 90, 120]], c[[60, 90, 120]] = 97.8, 97.6
        l[trigger], o[trigger], c[trigger] = 96.9, 97.2, 98.4        # prikt onder het niveau (sweep) en sluit erboven
    return pd.DataFrame({"timestamp": t, "open": o, "high": h, "low": l, "close": c, "volume": np.full(n, 10.0)})


class DetectorTest(unittest.TestCase):
    def test_resistance_rejection_is_a_short_with_stop_beyond_the_wick(self):
        df = frame("short")
        ev = rj.find_rejections(df)
        e = ev[ev["bar"] == 150].iloc[0]
        self.assertEqual((e["direction"], int(e["touches"])), ("short", 3))
        plan = rj.plan_for(next(ev[ev["bar"] == 150].itertuples()), df, smc_eval.floor_stop)
        self.assertGreater(plan["stop"], 103.05)
        self.assertLess(plan["targets"][0], plan["entry"])
        self.assertTrue(all(r >= 1.0 for r in plan["targets_r"]))

    def test_support_sweep_and_reclaim_is_a_long(self):
        df = frame("long")
        ev = rj.find_rejections(df)
        row = ev[(ev["bar"] == 150) & (ev["direction"] == "long")].iloc[0]
        self.assertTrue(row["swept"])                                        # prikte onder het niveau, sloot erboven
        plan = rj.plan_for(next(ev[(ev["bar"] == 150)].itertuples()), df, smc_eval.floor_stop)
        self.assertLess(plan["stop"], 96.9)
        self.assertGreater(plan["targets"][0], plan["entry"])

    def test_no_event_when_the_level_has_too_few_touches(self):
        df = frame("short")
        df.loc[[90, 120], "high"] = 101.0                                    # nog maar één top op 103
        self.assertTrue(rj.find_rejections(df).query("bar == 150 and direction == 'short'").empty)

    def test_same_rejection_counts_once_within_the_cooldown(self):
        df = frame("short")
        df.loc[151, ["open", "high", "close"]] = [102.0, 103.0, 101.5]       # de volgende candle voldoet ook, maar is dezelfde afwijzing
        ev = rj.find_rejections(df)
        self.assertEqual(len(ev[(ev["direction"] == "short") & (ev["bar"].between(150, 152))]), 1)


class LiveTest(DbCase):
    def setUp(self):
        super().setUp()
        self.pushed = []
        self.df = frame("short")
        self.now = self.df["timestamp"].iloc[150] + pd.Timedelta(minutes=31)

    def run_live(self, **cfg):
        async def fake_push(user_id, title, body, url, silent=False, tag=None):
            self.pushed.append((title, body, silent, tag))
        with mock.patch("app.exchange.fetch_ohlcv", lambda *a, **k: self.df[self.df["timestamp"] <= self.now]), \
                mock.patch("app.push_notify.send_push", fake_push), mock.patch.object(repo, "list_coins", lambda: [{"symbol": "BTC"}]), \
                mock.patch.object(config, "FIXED_COINS", ["BTC"]), \
                mock.patch.multiple(config, REJECTION_ENABLED=cfg.get("enabled", True), REJECTION_MAX_PER_DAY=cfg.get("cap", 8)):
            asyncio.run(rl.run(self.now.to_pydatetime()))

    def test_rejection_becomes_a_signal_with_one_trade_notification_once(self):
        self.run_live()
        rows = repo.list_signals_for_quality_report(None)
        self.assertEqual([r["trade_type"] for r in rows], ["rejectie"])
        title, body, silent, tag = self.pushed[0]
        self.assertIn("Rejectie", title)
        self.assertIn("3 aanrakingen", body)
        self.assertTrue(tag.startswith("trade-"))                            # dezelfde tag als de volgmeldingen: één lopende melding
        self.run_live()
        self.assertEqual(len(repo.list_signals_for_quality_report(None)), 1)  # zelfde afwijzing, tweede scan: niets

    def test_daily_cap_and_off_switch(self):
        self.run_live(cap=0)
        self.assertEqual(repo.list_signals_for_quality_report(None), [])
        self.run_live(enabled=False)
        self.assertEqual(self.pushed, [])


if __name__ == "__main__":
    unittest.main()


class ReplayRunTest(unittest.TestCase):
    @staticmethod
    def minute_frame(df30: pd.DataFrame) -> pd.DataFrame:
        """1m-candles die terug naar dezelfde 30m-candles samenvoegen: open, hoog, laag en slot staan op vaste minuten."""
        rows = []
        for r in df30.itertuples():
            path = [r.open, r.high, r.low] + [(r.open + r.close) / 2] * 26 + [r.close]
            for i, price in enumerate(path):
                rows.append({"timestamp": r.timestamp + pd.Timedelta(minutes=i), "open": price, "high": price, "low": price, "close": price, "volume": 1.0})
        return pd.DataFrame(rows)

    def test_run_simulates_the_planted_rejection_with_costs_and_a_ladder(self):
        trades = rj.run(self.minute_frame(frame("short")), cost_pct=0.06)
        self.assertEqual(list(trades.columns), ["at", "direction", "swept", "touches", "vol_ratio", "risk_pct", "net", "outcome", "target_r"])
        row = trades[(trades["direction"] == "short") & (trades["touches"] >= 3)].iloc[0]
        self.assertGreaterEqual(row["risk_pct"], config.SMC_MIN_STOP_PCT - 1e-9)            # stop minimaal zoals live
        self.assertIn(row["outcome"], ("stop", "be", "doel", "tijd"))

    def test_run_returns_an_empty_frame_with_columns_when_nothing_is_found(self):
        flat = frame("short").assign(open=100.0, high=100.1, low=99.9, close=100.0)
        self.assertTrue(rj.run(self.minute_frame(flat)).empty)
