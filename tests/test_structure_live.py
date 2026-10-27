import asyncio
import json
import unittest
from datetime import datetime, timedelta, timezone
from unittest import mock

import pandas as pd

from app import config, db, repo, structure_live as sl
from app.replay import breakretest as br
from app.replay.lab import make_bars
from tests.replay.test_breakretest import frame
from tests.test_samenval import DbCase

CUT = 4800                      # breukcandle = 4800 / 30 = bar 160, ruim voorbij de minimale historie
BREAK_BAR = CUT // 30


class PureTest(unittest.TestCase):
    def test_line_value_follows_slope_per_30m(self):
        s = {"p1_at": "2026-03-02T00:00:00+00:00", "line_a": 100.0, "line_slope": 0.1}
        self.assertAlmostEqual(sl.line_value(s, pd.Timestamp("2026-03-02T03:00:00+00:00")), 100.6)

    def test_parse_grade_rejects_unknown_and_truncates(self):
        self.assertEqual(sl.parse_grade({"grade": "a", "reason": "x" * 400})[0], "A")
        self.assertEqual(len(sl.parse_grade({"grade": "A", "reason": "x" * 400})[1]), sl.REASON_MAX)
        self.assertIsNone(sl.parse_grade({"grade": "S", "reason": ""})[0])

    def test_disable_needs_enough_negative_results(self):
        win = {"price": 100, "stop_loss": 99, "take_profit": 102, "auto_outcome": "take_profit"}
        loss = {**win, "auto_outcome": "stop_loss"}
        self.assertTrue(sl.should_disable([win] * 8 + [loss] * 22, 30))
        self.assertFalse(sl.should_disable([loss] * 29, 30))


class CapTest(unittest.TestCase):
    def test_full_cap_picks_the_chance_closest_to_its_limit_not_the_letter(self):
        cands = [{"id": 1, "grade": "A", "dist_pct": 2.5}, {"id": 2, "grade": "C", "dist_pct": -0.4}, {"id": 3, "grade": "B", "dist_pct": 1.0}]
        sent, held = sl.choose(cands, 2)
        self.assertEqual([c["id"] for c in sent], [2, 3])
        self.assertEqual([c["id"] for c in held], [1])

    def test_room_zero_or_negative_sends_nothing(self):
        cands = [{"id": 1, "dist_pct": 1.0}]
        self.assertEqual(sl.choose(cands, 0), ([], cands))
        self.assertEqual(sl.choose(cands, -3), ([], cands))


class ChartTest(unittest.TestCase):
    def test_svg_has_line_zone_limit_stop_targets_and_price(self):
        from app import setup_chart
        candles = [[f"2026-03-02T{h:02d}:00:00+00:00", 100 - h, 101 - h, 99 - h, 100 - h] for h in range(10)]
        setup = {"coin": "BTC", "direction": "short", "kind": "RANGE", "line_a": 100.0, "line_slope": 0.0,
                 "p1_at": "2026-03-02T01:00:00+00:00", "break_at": "2026-03-02T06:00:00+00:00"}
        plan = {"level": 95.0, "stop": 96.0, "targets": [93.0, 91.0], "targets_r": [2.0, 4.0]}
        svg = setup_chart.setup_svg(candles, setup, plan, price=94.0)
        for cls in ("sc-stopzone", "sc-structure", "sc-limit", "sc-stop", "sc-target", "sc-price", "sc-break"):
            self.assertIn(cls, svg)
        self.assertEqual(svg.count("sc-body"), 10)
        self.assertEqual(setup_chart.setup_svg([], setup, plan), "")

    def test_long_labels_stay_inside_the_chart(self):
        import re
        from app import setup_chart
        candles = [[f"2026-03-02T{h:02d}:00:00+00:00", 2440 - h, 2446 - h, 2434 - h, 2439 - h] for h in range(20)]
        setup = {"coin": "ETH", "direction": "long", "kind": "RANGE", "line_a": 2420.0, "line_slope": 0.0,
                 "p1_at": "2026-03-02T01:00:00+00:00", "break_at": "2026-03-02T15:00:00+00:00"}
        plan = {"level": 2356.88, "stop": 2347.45, "targets": [2388.61, 2429.41, 2453.40], "targets_r": [3.4, 7.7, 10.2]}
        svg = setup_chart.setup_svg(candles, setup, plan, price=2377.08)
        labels = re.findall(r'<text class="sc-label [^"]+" x="([\d.]+)"[^>]*>([^<]+)</text>', svg)
        self.assertIn("T3 2453.4 · 10.2R", [t for _, t in labels])
        for x, text in labels:
            self.assertLessEqual(float(x) + len(text) * setup_chart.LABEL_CHAR_W, setup_chart.W, text)


class LiveTest(DbCase):
    def setUp(self):
        super().setUp()
        self.f = frame(minutes=60 * 24 * 6, plant=True, cut=CUT)
        self.bars = make_bars(self.f, 30)
        self.pushed = []
        self.graded = []
        patcher = mock.patch.object(sl, "MIN_RR", 0.0)       # het synthetische zwaaipunt ligt dichtbij: de ruimte-eis testen we apart
        patcher.start()
        self.addCleanup(patcher.stop)

    def fetch(self, n_closed, step_min=None):
        bars, f = self.bars, self.f

        def fake(coin, timeframe="30m", limit=300, since=None):
            if timeframe == "30m":
                return bars.iloc[:n_closed + 1][["timestamp", "open", "high", "low", "close", "volume"]]
            end = bars.at[n_closed - 1, "close_time"]
            part = f[f["timestamp"] < end].set_index("timestamp").resample("5min").agg(
                {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}).dropna().reset_index()
            return part.tail(limit)
        return fake

    def run_live(self, n_closed, grade="A"):
        async def fake_push(user_id, title, body, url, silent=False, tag=None):
            self.pushed.append((title, body, url, silent))

        def fake_claude(ctx):
            self.graded.append(ctx)
            return {"grade": grade, "reason": "Schone range, duidelijke breuk."}

        now = (self.bars.at[n_closed - 1, "close_time"]).to_pydatetime()
        with mock.patch("app.exchange.fetch_ohlcv", self.fetch(n_closed)), mock.patch("app.push_notify.send_push", fake_push), \
                mock.patch.object(sl, "call_claude", fake_claude), mock.patch.object(config, "FIXED_COINS", ["BTC"]), \
                mock.patch.object(repo, "list_coins", lambda: [{"symbol": "BTC"}]):
            asyncio.run(sl.run(now))

    def test_discovers_break_grades_it_and_alerts_once_with_plan(self):
        self.run_live(BREAK_BAR + 4)
        rows = repo.list_structure_setups(("waiting",))
        self.assertEqual(len(rows), 1)
        self.assertEqual((rows[0]["direction"], rows[0]["grade"]), ("short", "A"))
        title, body, url, silent = self.pushed[0]
        self.assertIn("Structuur wacht", title)
        self.assertNotIn("ngetest", title + body)
        self.assertIn("Limietorder", body)
        self.assertIn("Doelen", body)
        self.assertTrue(url.startswith("/structuur#structuur-"))
        self.assertEqual(len(self.graded), 1)
        self.assertIn("laatste_candles_30m", self.graded[0])
        self.run_live(BREAK_BAR + 4)
        self.assertEqual(len(self.graded), 1)                 # dezelfde breuk wordt niet opnieuw beoordeeld

    def test_a_plan_the_price_already_passed_is_not_announced(self):
        with mock.patch("app.trade_plan.plan_state", return_value="doel_geraakt"):
            self.run_live(BREAK_BAR + 4, grade="A")
        self.assertEqual(self.pushed, [])
        self.assertEqual(self.graded, [])                              # ook geen Claude-aanroep voor een plan dat niemand ziet
        self.assertEqual(repo.list_structure_setups(("waiting",)), [])
        kept = repo.list_structure_setups(("geen_plan",))
        self.assertEqual(len(kept), 1)
        self.assertIn("al voorbij", kept[0]["reason"])

    def test_every_grade_is_announced_the_same_loud_way(self):
        # Het oordeel is alleen nog een meting: A, B en C krijgen bij het ontstaan dezelfde luide melding zonder letter of woord.
        from app import push_notify
        for grade in ("A", "B", "C"):
            with self.subTest(grade=grade):
                self.setUp()                                               # verse database: het pushbudget en de dedupe van de vorige ronde tellen niet
                self.run_live(BREAK_BAR + 4, grade=grade)
                self.assertEqual(len(self.pushed), 1)
                title, body, url, silent = self.pushed[0]
                self.assertEqual(title, push_notify.alert_title("BTC", "short", "Structuur wacht"))
                self.assertFalse(silent)
                self.assertNotIn("Schone range", body)                     # de toelichting van het oordeel staat er niet in
                self.assertTrue(url.startswith("/structuur#structuur-"))
                self.assertEqual(repo.list_structure_setups(("waiting",))[0]["grade"], grade)     # het oordeel blijft als meting

    def test_grade_c_fill_is_a_loud_structuur_c_signal(self):
        self.run_live(BREAK_BAR + 4, grade="C")
        self.pushed.clear()
        self.run_live(BREAK_BAR + 9)
        self.assertEqual([r["trade_type"] for r in repo.list_signals_for_quality_report(None)], ["structuur_c"])   # Bewijs houdt C apart
        filled = [p for p in self.pushed if "gevuld" in p[0]]
        self.assertEqual(len(filled), 1)
        self.assertFalse(filled[0][3])
        sig = repo.list_signals_for_quality_report(None)[0]
        full = repo.get_signal(sig["id"])
        self.assertNotIn("CEO", full["reason"])
        self.assertEqual(full["confidence"], "Structuur")

    def test_grade_c_respects_budget_and_conflict_rule(self):
        user_id = repo.list_users()[0]["id"]
        now = datetime.now(timezone.utc).isoformat()
        repo.record_push(user_id, "BTC", "long", now)           # tegenstrijdig met de short van de kans
        self.run_live(BREAK_BAR + 4, grade="C")
        self.assertEqual(self.pushed, [])
        self.assertTrue(any("Tegenstrijdig" in n["body"] for n in repo.list_notifications(user_id)))

    def test_grade_c_respects_daily_budget(self):
        user_id = repo.list_users()[0]["id"]
        now = datetime.now(timezone.utc).isoformat()
        for coin in ("ETH", "SOL", "XRP", "ADA", "DOGE", "LINK", "BNB", "AVAX", "SUI", "DOT", "LTC", "BCH", "NEAR", "ATOM", "UNI"):
            repo.record_push(user_id, coin, "long", now)
        self.run_live(BREAK_BAR + 4, grade="C")
        self.assertEqual(self.pushed, [])

    def test_grade_c_respects_daily_structure_cap(self):
        with mock.patch.object(config, "STRUCTURE_MAX_ALERTS_PER_DAY", 0):
            self.run_live(BREAK_BAR + 4, grade="C")
        self.assertEqual(self.pushed, [])
        self.assertEqual(self.graded, [])

    def test_retest_fills_and_becomes_a_tracked_signal(self):
        self.run_live(BREAK_BAR + 4)
        self.pushed.clear()
        self.run_live(BREAK_BAR + 9)                           # de koers is terug bij het gebroken niveau
        rows = repo.list_signals_for_quality_report(None)
        self.assertEqual([r["trade_type"] for r in rows], ["structuur"])
        self.assertIsNotNone(repo.list_structure_setups(("fired",))[0]["signal_id"])
        sig = rows[0]
        self.assertGreater(sig["stop_loss"], sig["price"])     # short: stop boven de instap
        self.assertLess(sig["take_profit"], sig["price"])
        self.assertTrue(any("gevuld" in t for t, *_ in self.pushed))
        full = repo.get_signal(repo.list_structure_setups(("fired",))[0]["signal_id"])
        self.assertTrue(full["reason"].startswith(("✓", "✗")))        # gemeten kenmerken in de vorm die de kaart leest
        self.assertIsNotNone(full["pass_pct"])
        self.assertIn("Structuur", full["plain_explanation"])        # de uitleg in woorden staat apart

    def test_follow_reports_each_target_and_moves_stop_to_entry_at_t1(self):
        t0 = pd.Timestamp("2026-03-05T10:00:00+00:00")
        plan = {"level": 100.0, "stop": 101.0, "risk_pct": 1.0, "targets": [98.0, 97.0, 96.0], "targets_r": [2.0, 3.0, 4.0],
                "fired": {"entry": 100.0, "stop": 101.0, "targets": [98.0, 97.0, 96.0], "hits": 0, "closed": False, "at": t0.isoformat()}}
        sid = repo.insert_structure_setup({
            "coin": "BTC", "direction": "short", "kind": "RANGE", "break_at": t0.isoformat(), "p1_at": t0.isoformat(), "line_a": 100.0,
            "line_slope": 0.0, "atr": 0.5, "grade": "A", "reason": "x", "features": "{}", "state": "waiting",
            "expires_at": (t0 + timedelta(hours=3)).isoformat(), "plan": json.dumps(plan)})
        sig = self.insert_signal(trade_type="structuur", direction="short", price=100.0, stop_loss=101.0, take_profit=97.0)
        repo.set_structure_state(sid, "fired", sig)

        def candles(rows):
            return pd.DataFrame([{"timestamp": t0 + timedelta(minutes=5 * i), "open": o, "high": h, "low": l, "close": c, "volume": 1.0}
                                 for i, (o, h, l, c) in enumerate(rows)])

        def follow(df):
            async def fake_push(user_id, title, body, url, silent=False, tag=None):
                self.pushed.append((title, body, silent))
            with mock.patch("app.exchange.fetch_ohlcv", lambda *a, **k: df), mock.patch("app.push_notify.send_push", fake_push):
                asyncio.run(sl._follow(datetime(2026, 3, 6, tzinfo=timezone.utc)))

        follow(candles([(100, 100.4, 99.6, 99.8), (99.8, 99.9, 97.9, 98.0)]))               # T1 geraakt, stop blijft onder de instap
        self.assertEqual(len(self.pushed), 1)
        self.assertIn("T1 van 3", self.pushed[0][0])
        self.assertIn("Zet je stop op de instap", self.pushed[0][1])
        follow(candles([(100, 100.4, 99.6, 99.8), (99.8, 99.9, 97.9, 98.0)]))               # zelfde candles: niet nog een keer
        self.assertEqual(len(self.pushed), 1)
        follow(candles([(100, 100.4, 99.6, 99.8), (99.8, 99.9, 97.9, 98.0), (98.0, 98.1, 96.9, 97.0)]))   # T2 erbij
        self.assertEqual(len(self.pushed), 2)
        self.assertIn("T2 van 3", self.pushed[1][0])
        self.assertIn("▰▰▱", self.pushed[1][0])                            # voortgang in de titel van de lopende melding
        self.assertFalse(self.pushed[0][2])                                 # T1 is luid: je stop moet naar de instap
        self.assertTrue(self.pushed[1][2])                                  # T2 vervangt stil dezelfde melding
        follow(candles([(100, 100.4, 99.6, 99.8), (99.8, 99.9, 97.9, 98.0), (98.0, 98.1, 96.9, 97.0), (97.0, 100.2, 96.9, 100.0)]))  # terug op de instap
        fired = json.loads(repo.list_structure_setups(("fired",))[0]["plan"])["fired"]
        self.assertTrue(fired["closed"])
        texts = [e["text"] for e in fired["events"]]                       # tijdlijn voor de pagina van de kans
        self.assertTrue(any(t.startswith("T1 geraakt") for t in texts) and any(t.startswith("T2 geraakt") for t in texts))
        self.assertIn("Stop op de instap geraakt, break-even", texts)
        self.assertEqual(fired["hits"], 2)

    def test_close_liquidity_falls_back_to_a_fixed_ladder_instead_of_dropping_the_setup(self):
        # De synthetische koers ligt na de breuk al voorbij 1R; deze test gaat over de trap, niet over of het plan nog open is.
        with mock.patch.object(sl, "MIN_RR", 50.0), mock.patch("app.trade_plan.plan_state", return_value="wacht"):    # geen zwaaipunt ligt ver genoeg
            self.run_live(BREAK_BAR + 4)
        rows = repo.list_structure_setups(("waiting",))
        self.assertEqual(len(rows), 1)
        plan = json.loads(rows[0]["plan"])
        self.assertEqual(plan["targets_r"], [1.0, 2.0, 3.0])
        self.assertFalse(plan["from_levels"])

    def test_grade_c_fill_is_its_own_signal_type_and_is_announced(self):
        self.run_live(BREAK_BAR + 4, grade="C")
        self.pushed.clear()
        self.run_live(BREAK_BAR + 9)                               # de koers komt terug bij het niveau
        rows = repo.list_signals_for_quality_report(None)
        self.assertEqual([r["trade_type"] for r in rows], ["structuur_c"])
        self.assertTrue(self.pushed and not any(p[3] for p in self.pushed))   # een gevulde trade krijgt altijd een melding, ook bij zwak

    def test_stop_with_room_widens_a_tight_stop_to_the_floor(self):
        self.assertAlmostEqual(sl.stop_with_room("short", 100.0, 100.0, 0.05), 100.4)      # kwart ATR gaf 100,0125: te krap
        self.assertAlmostEqual(sl.stop_with_room("long", 100.0, 100.0, 0.05), 99.6)
        self.assertAlmostEqual(sl.stop_with_room("short", 100.0, 101.0, 0.4), 101.1)       # ruim genoeg: ongemoeid

    def test_off_switch(self):
        with mock.patch.object(config, "STRUCTURE_ENABLED", False):
            self.run_live(BREAK_BAR + 4)
        self.assertEqual(self.pushed, [])


if __name__ == "__main__":
    unittest.main()
