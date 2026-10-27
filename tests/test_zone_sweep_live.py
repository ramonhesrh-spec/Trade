"""De live zone-sweep-motor (app/zone_sweep_live.py) tegen een kunstmatige markt: detectie op de laatst gesloten candle, één kaart per zone,
melding één keer, dagcap, vullen wordt een signaal buiten de keten, een kaart zonder doel met de referentie-uitgang, verval voorbij de stop,
en CEO-only als ZONE_SWEEP_PUBLIC uit staat."""
import asyncio
import unittest
from unittest import mock

import pandas as pd

from app import config, db, level_check, push_notify, range_sweep_live, repo, rule_live
from app import zone_sweep_live as live
from app.replay import rangesweep as rs, zonesweep as zs, zonesweep_lab as zl
from tests.replay.test_zonesweep import DRIFT, FLAT, PRIK_HERSTEL, START, ZONE
from tests.test_samenval import DbCase
from tests.test_zone_sweep import HIGH

TEST_VARIANT = zl.ZSVariant("ZS_T", "1h", "zone", False)
FILL = (100.6, 100.7, 100.2, 100.5)                 # raakt de limiet 100,3
TO_TARGET = (100.5, 104.2, 100.5, 104.1)            # raakt het doel 104,0
CRASH = (100.5, 100.5, 98.0, 98.2)                  # door de stop (99,2 min een kwart ATR)
GAP = (98.0, 98.2, 97.5, 97.8)                      # opent voorbij de stop, zonder de limiet te raken
QUIET = [(104.1, 104.3, 103.9, 104.1)] * 12


def bars(rows):
    b1h = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    b1h.insert(0, "timestamp", pd.date_range(START, periods=len(b1h), freq="1h"))
    b1h["volume"] = 1.0
    b15 = b1h.loc[b1h.index.repeat(4)].reset_index(drop=True)
    b15["timestamp"] = pd.date_range(START, periods=len(b15), freq="15min")
    return {"15m": b15, "1h": b1h, "4h": rs.resample(b1h, "4h")}


class EngineCase(DbCase):
    target = True
    after = [FILL, TO_TARGET] + QUIET

    def setUp(self):
        super().setUp()
        self.student = repo.create_user("b", "x", 0, 1)
        self.ceo = repo.get_user_by_username("a")["id"]
        prefix = HIGH + [FLAT] * 40 if self.target else [FLAT] * 62
        self.rows = prefix + ZONE + DRIFT + [PRIK_HERSTEL]
        self.placed = START + pd.Timedelta(hours=len(self.rows))
        self.bars = bars(self.rows + self.after)
        self.pushed = []
        for p in (mock.patch.object(config, "CEO_USERNAME", ""), mock.patch.object(config, "ZONE_SWEEP_ENABLED", True),
                  mock.patch.object(config, "ZONE_SWEEP_PUBLIC", True), mock.patch.object(config, "ZONE_SWEEP_MAX_PER_DAY", 10),
                  mock.patch.object(zl, "VARIANTS", zl.VARIANTS + (TEST_VARIANT,)), mock.patch.object(live, "LIVE_VARIANTS", ("ZS_T",)),
                  mock.patch.object(live, "COINS", ("BTC",)), mock.patch.object(range_sweep_live, "fetch_bars", self.fetch),
                  mock.patch.object(push_notify, "is_quiet_now", return_value=False),
                  mock.patch("app.push_notify.send_push", self.fake_push)):
            p.start()
            self.addCleanup(p.stop)

    def fetch(self, coin, timeframe, limit):
        # Met een stuk toekomst erbij: wat na `now` komt mag de motor nooit zien en moet hij zelf wegsnijden.
        df = self.bars[timeframe]
        return df[df["timestamp"] < pd.Timestamp(self.now) + pd.Timedelta(hours=12)].tail(limit).reset_index(drop=True)

    async def fake_push(self, user_id, title, body, url, silent=False, tag=None, badge=None):
        self.pushed.append({"user": user_id, "title": title, "body": body, "url": url})

    def run_(self, fn, now):
        self.now = now.to_pydatetime()
        asyncio.run(fn(self.now))

    def scan(self, minutes=5):
        self.run_(live.scan, self.placed + pd.Timedelta(minutes=minutes))

    def track(self, minutes=20):
        self.run_(live.track, self.placed + pd.Timedelta(minutes=minutes))

    def follow(self, minutes):
        self.run_(live.follow, self.placed + pd.Timedelta(minutes=minutes))

    def cards(self, *states):
        return repo.list_zone_sweep_setups(states or live.ALL_STATES)

    def signals(self):
        with db.session() as conn:
            return [dict(r) for r in conn.execute("SELECT * FROM signals WHERE trade_type = 'zone_sweep' ORDER BY id")]

    def titles(self, part):
        return [p for p in self.pushed if part in p["title"]]


class ScanTest(EngineCase):
    def test_one_card_with_limit_stop_and_target_announced_once(self):
        self.scan()
        cards = self.cards()
        self.assertEqual(len(cards), 1)
        c = cards[0]
        s = zs.find_setups(rs.build_frames(*(self.bars[tf][self.bars[tf]["timestamp"] < self.placed] for tf in ("15m", "1h", "4h"))),
                           "1h", "zone", False)[0][0]
        self.assertEqual((c["state"], c["direction"], c["variant"], c["tf"]), ("waiting", "long", "ZS_T", "1h"))
        self.assertAlmostEqual(c["limit_price"], 100.3)
        self.assertAlmostEqual(c["stop_loss"], zs.final_stop(s, "wick_025"))
        self.assertAlmostEqual(c["take_profit"], 104.0)
        news = self.titles("Zone-sweep · ongetest")
        self.assertEqual({p["user"] for p in news}, {self.ceo, self.student})
        self.assertEqual({p["url"] for p in news}, {f"/smc#radar-zsweep-{c['id']}"})
        self.assertIn("Limiet 100.30", news[0]["body"])
        self.scan(minutes=10)
        self.assertEqual(len(self.cards()), 1)                 # dezelfde zone geeft geen tweede kaart
        self.assertEqual(len(self.titles("Zone-sweep · ongetest")), 2)

    def test_only_setups_from_the_last_closed_candle(self):
        self.scan(minutes=65)                 # binnen het zoekvenster na het volgende slot, maar de setup is een uur oud
        self.assertEqual(self.cards(), [])
        self.scan(minutes=45)                 # buiten het zoekvenster: de motor haalt niets op
        self.assertEqual(self.cards(), [])

    def test_engine_off_does_nothing(self):
        with mock.patch.object(config, "ZONE_SWEEP_ENABLED", False):
            self.scan()
        self.assertEqual(self.cards(), [])

    def test_daily_cap_keeps_the_card_quiet(self):
        with mock.patch.object(config, "ZONE_SWEEP_MAX_PER_DAY", 0):
            self.scan()
        cards = self.cards()
        self.assertEqual(len(cards), 1)
        self.assertEqual(cards[0]["quiet"], 1)
        self.assertEqual(self.pushed, [])


class FillTest(EngineCase):
    def test_fill_makes_one_signal_outside_the_chain_with_journal_and_push(self):
        self.scan()
        self.track()
        self.track(minutes=25)
        sigs = self.signals()
        self.assertEqual(len(sigs), 1)
        g = sigs[0]
        self.assertEqual((g["trade_type"], g["price"], g["take_profit"]), ("zone_sweep", 100.3, 104.0))
        self.assertAlmostEqual(g["stop_loss"], self.cards()[0]["stop_loss"])
        self.assertEqual(self.cards()[0]["state"], "filled")
        self.assertIsNone(repo.get_chain_link(g["id"]))
        with db.session() as conn:
            users = {r["user_id"] for r in conn.execute("SELECT user_id FROM journal_entries WHERE signal_id = ?", (g["id"],))}
        self.assertEqual(users, {self.ceo, self.student})
        filled = self.titles("Zone-sweep gevuld")
        self.assertEqual({p["user"] for p in filled}, {self.ceo, self.student})
        self.assertEqual(len(filled), 2)
        self.assertEqual(repo.get_zone_sweep_trade(g["id"]), None)      # met een doel beslist level_check de uitkomst


class NotPublicTest(EngineCase):
    def test_ceo_only_when_not_public(self):
        with mock.patch.object(config, "ZONE_SWEEP_PUBLIC", False):
            self.scan()
            self.track()
        self.assertTrue(self.pushed)
        self.assertEqual({p["user"] for p in self.pushed}, {self.ceo})
        sid = self.signals()[0]["id"]
        with db.session() as conn:
            users = {r["user_id"] for r in conn.execute("SELECT user_id FROM journal_entries WHERE signal_id = ?", (sid,))}
        self.assertEqual(users, {self.ceo})
        self.assertIn("zone_sweep", rule_live.ceo_only_types(True, False))
        self.assertNotIn("zone_sweep", rule_live.ceo_only_types(True, True))


class GapTest(EngineCase):
    after = [GAP] + QUIET

    def test_open_past_the_stop_before_the_fill_ends_the_card(self):
        self.scan()
        self.track()
        self.assertEqual(self.cards()[0]["state"], "stop_voor_vulling")
        self.assertEqual(self.signals(), [])


class NoTargetTest(EngineCase):
    target = False
    after = [FILL, CRASH] + QUIET

    def test_card_without_target_measures_the_reference_exit(self):
        self.scan()
        card = self.cards()[0]
        self.assertIsNone(card["take_profit"])
        self.assertIn("geen doel", self.titles("Zone-sweep · ongetest")[0]["body"])
        self.track()
        g = self.signals()[0]
        self.assertIsNone(g["take_profit"])
        self.assertIsNotNone(repo.get_zone_sweep_trade(g["id"]))
        self.follow(minutes=2 * 60 + 10)
        trade = repo.get_zone_sweep_trade(g["id"])
        self.assertIsNotNone(trade["stop_hit_at"])
        self.assertAlmostEqual(trade["ref_r"], -1.0)
        g = repo.get_signal(g["id"])
        self.assertEqual(g["auto_outcome"], "stop_loss")
        self.assertAlmostEqual(repo.get_trade_result(g["id"])["r_value"], -1.0)

    def test_level_check_leaves_a_card_without_target_alone(self):
        self.scan()
        self.track()
        sid = self.signals()[0]["id"]
        crash = pd.DataFrame({"timestamp": [pd.Timestamp.now(tz="UTC")], "open": [90.0], "high": [107.0], "low": [90.0], "close": [90.0], "volume": [1.0]})
        row = {**repo.get_signal(sid), "id": sid}
        self.pushed.clear()
        with mock.patch.object(repo, "list_unresolved_signals_with_levels", lambda: [row]), \
                mock.patch.object(repo, "list_open_entries_with_levels", lambda: [{**row, "signal_id": sid, "entry_price": 100.3, "user_id": self.ceo}]), \
                mock.patch.object(level_check, "_fetch_since", lambda coin, since: crash), \
                mock.patch.object(level_check.exchange, "fetch_ohlcv", lambda *a, **k: crash):
            asyncio.run(level_check.check_signal_outcomes())
            asyncio.run(level_check.check_open_trades())
        self.assertIsNone(repo.get_signal(sid)["auto_outcome"])
        self.assertEqual(self.pushed, [])


if __name__ == "__main__":
    unittest.main()
