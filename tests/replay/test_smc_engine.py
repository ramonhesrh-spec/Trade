import unittest
from collections import Counter
from unittest import mock

import pandas as pd

from app import repo, smc_eval
from app.replay import smc_engine
from app.replay.smc_engine import SmcBook
from tests.replay.fixtures import make_smc_prone_1m


def upsert(book, **kw):
    args = dict(coin="ETH", direction="short", zone_low=100.0, zone_high=102.0, structure_level=110.0,
                sweep_price=111.0, liquidity_target=90.0, atr=2.0, seen_until="2026-01-01T10:15:00+00:00",
                now_iso="2026-01-01T10:15:00+00:00")
    args.update(kw)
    return book.upsert(**args)


class SmcBookTest(unittest.TestCase):
    def test_same_event_updates_zone_and_target_only(self):
        book = SmcBook()
        a = upsert(book)
        b = upsert(book, zone_low=100.5, zone_high=102.5, liquidity_target=88.0, seen_until="2026-01-01T10:30:00+00:00")
        self.assertEqual(a, b)
        row = book.forming("ETH")[0]
        self.assertEqual((row["zone_low"], row["zone_high"], row["liquidity_target"], row["updated_at"]),
                         (100.5, 102.5, 88.0, "2026-01-01T10:30:00+00:00"))

    def test_zone_within_dedup_pct_updates_existing_row_including_levels(self):
        book = SmcBook()
        a = upsert(book)
        b = upsert(book, structure_level=111.0, sweep_price=112.0, zone_low=100.1, zone_high=102.1)
        self.assertEqual(a, b)
        self.assertEqual(book.forming("ETH")[0]["sweep_price"], 112.0)

    def test_far_zone_creates_new_row(self):
        book = SmcBook()
        a = upsert(book)
        b = upsert(book, structure_level=120.0, sweep_price=121.0, zone_low=110.0, zone_high=112.0)
        self.assertNotEqual(a, b)
        self.assertEqual(len(book.forming("ETH")), 2)

    def test_completed_or_invalidated_same_event_is_returned_but_not_forming(self):
        book = SmcBook()
        a = upsert(book)
        book.invalidate(a, "doorbraak", "2026-01-01T11:00:00+00:00")
        self.assertEqual(upsert(book), a)
        self.assertEqual(book.forming("ETH"), [])

    def test_dedup_pct_is_the_live_constant(self):
        self.assertEqual(smc_engine.ZONE_DEDUP_PCT, repo.ZONE_DEDUP_PCT)


T0 = pd.Timestamp("2026-01-02 12:03", tz="UTC")
STEP15 = pd.Timedelta(minutes=15)
# De zones liggen ver boven de koers (~100): de echte last_candle_state in fase 2 ziet nooit een
# afwijzing, zodat elke afwijzing in deze tests uit de gescripte judge_forming_setup komt.


def candidate(zone_low=1000.0, zone_high=1002.0, level=1100.0, sweep=1110.0, direction="short"):
    return smc_eval.SmcCandidate(direction, zone_low, zone_high, level, sweep, 900.0, 2.0)


def scan_with(cand):
    return smc_eval.SmcScan(cand.direction, cand, None)


NO_BREAK = smc_eval.SmcScan(None, None, "geen_structuurbreuk")
GOOD_SIGNAL = smc_eval.SmcCompletion(smc_eval.SmcSignalDraft(100.0, 105.0, 90.0, 99.0, "reden", 2.0), None)


class ScriptedEngineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = {"ETH": make_smc_prone_1m(days=2, seed=3, start_price=100.0)}

    def run_engine(self, scans, judge, completion, cycles, max_age_hours=None):
        """scans: lijst of callable(call_index) voor find_candidate; judge: callable(setup, closed) -> verdict."""
        events, book = [], SmcBook()
        calls = {"find": 0}

        def find(*_a, **_k):
            i = calls["find"]
            calls["find"] += 1
            return scans(i) if callable(scans) else scans[min(i, len(scans) - 1)]

        patches = [
            mock.patch.object(smc_engine.smc_eval, "find_candidate", side_effect=find),
            mock.patch.object(smc_engine.smc_eval, "judge_forming_setup", side_effect=judge),
            mock.patch.object(smc_engine.smc_eval, "evaluate_completion", return_value=completion),
        ]
        if max_age_hours is not None:
            patches.append(mock.patch.object(smc_eval, "SMC_SETUP_MAX_AGE_HOURS", max_age_hours))
        for p in patches:
            p.start()
        try:
            signals = smc_engine.replay_smc("ETH", self.base, self.base["ETH"], T0, T0 + STEP15 * (cycles - 1),
                                            step=STEP15, events=events, book=book)
        finally:
            for p in reversed(patches):
                p.stop()
        return signals, Counter(e.kind for e in events), events, book, calls["find"]

    def test_a_candidate_is_built_then_rejected_into_a_signal(self):
        signals, kinds, _, book, _ = self.run_engine(
            [scan_with(candidate()), NO_BREAK], lambda s, c: "rejected", GOOD_SIGNAL, cycles=3)
        self.assertEqual((kinds["setup_gebouwd"], kinds["signaal"], kinds["geen_structuurbreuk"]), (1, 1, 1))
        self.assertEqual(len(signals), 1)
        s = signals[0]
        self.assertEqual((s.direction, s.entry, s.stop, s.take, s.sniper_price, s.setup_id, s.at),
                         ("short", 100.0, 105.0, 90.0, 99.0, 1, T0 + STEP15))
        self.assertEqual(book.all_setups()[0]["signal_id"], 1)
        self.assertEqual(book.forming("ETH"), [])

    def test_b_rejected_without_valid_signal_keeps_setup_forming(self):
        no_signal = smc_eval.SmcCompletion(None, "entry_slechter_dan_sniper", "detail")
        signals, kinds, events, book, _ = self.run_engine(
            [scan_with(candidate())], lambda s, c: "rejected", no_signal, cycles=3)
        self.assertEqual(signals, [])
        self.assertEqual((kinds["setup_gebouwd"], kinds["afgewezen_geen_signaal"], kinds["signaal"]), (1, 2, 0))
        rejected = [e for e in events if e.kind == "afgewezen_geen_signaal"]
        self.assertTrue(all(e.detail == "entry_slechter_dan_sniper" for e in rejected))
        self.assertEqual(len(book.forming("ETH")), 1)
        self.assertIsNone(book.all_setups()[0]["signal_id"])

    def test_c_passed_invalidates_and_continues_to_phase_two(self):
        a, b = candidate(), candidate(2000.0, 2002.0, 2100.0, 2110.0)
        _, kinds, _, book, finds = self.run_engine([scan_with(a), scan_with(b)], lambda s, c: "passed", GOOD_SIGNAL, cycles=2)
        self.assertEqual((kinds["setup_doorbroken"], kinds["setup_gebouwd"], finds), (1, 2, 2))
        first, second = book.all_setups()
        self.assertEqual((first["ended_because"], second["invalidated_at"]), ("doorbraak", None))
        self.assertEqual([r["id"] for r in book.forming("ETH")], [second["id"]])

    def test_d_opposite_break_invalidates_existing_setup(self):
        opposite = smc_eval.SmcScan("long", None, "geen_sweep")
        _, kinds, events, book, _ = self.run_engine(
            [scan_with(candidate()), opposite], lambda s, c: "open", GOOD_SIGNAL, cycles=2)
        self.assertEqual((kinds["setup_gebouwd"], kinds["setup_tegenrichting"], kinds["geen_sweep"]), (1, 1, 1))
        self.assertEqual(book.all_setups()[0]["ended_because"], "tegenrichting")
        self.assertEqual([e.direction for e in events if e.kind == "geen_sweep"], ["long"])

    def test_e_setup_older_than_max_age_expires(self):
        # 1 uur ipv 24: setup ontstaat op T0, is op T0+75m (cyclus 6) ouder dan 1 uur.
        _, kinds, _, book, _ = self.run_engine(
            [scan_with(candidate())], lambda s, c: "open", GOOD_SIGNAL, cycles=6, max_age_hours=1)
        self.assertEqual((kinds["setup_vervallen"], kinds["setup_gebouwd"]), (1, 1))
        row = book.all_setups()[0]
        self.assertEqual((row["ended_because"], row["invalidated_at"]), ("vervallen", (T0 + STEP15 * 5).isoformat()))
        # dezelfde breuk wordt na het vervallen niet opnieuw een bouwende setup
        self.assertEqual(book.forming("ETH"), [])

    def test_f_phase_one_returns_on_first_rejected_without_judging_the_rest(self):
        a, b = candidate(), candidate(2000.0, 2002.0, 2100.0, 2110.0)
        judged = []

        def judge(setup, closed):
            judged.append(setup["id"])
            return "rejected" if len(judged) >= 2 else "open"

        signals, kinds, _, book, finds = self.run_engine(
            [scan_with(a), scan_with(b)], judge, GOOD_SIGNAL, cycles=3)
        # cyclus 2 beoordeelt alleen setup 1 (open); cyclus 3 begint bij de recentst bijgewerkte (2) en stopt daar
        self.assertEqual(judged, [1, 2])
        self.assertEqual(finds, 2)
        self.assertEqual([s.setup_id for s in signals], [2])
        self.assertEqual([r["id"] for r in book.forming("ETH")], [1])


    def test_g_passed_first_setup_does_not_stop_judging_the_next(self):
        a, b = candidate(), candidate(2000.0, 2002.0, 2100.0, 2110.0)
        judged = []

        def judge(setup, closed):
            judged.append(setup["id"])
            # cyclus 3: eerst de recentst bijgewerkte (2) "passed", dan setup 1 "rejected"
            return {2: "passed", 3: "rejected"}.get(len(judged), "open")

        signals, kinds, _, book, finds = self.run_engine(
            [scan_with(a), scan_with(b)], judge, GOOD_SIGNAL, cycles=3)
        self.assertEqual(judged, [1, 2, 1])
        self.assertEqual(finds, 2)
        self.assertEqual(kinds["setup_doorbroken"], 1)
        first, second = book.all_setups()
        self.assertEqual((second["ended_because"], first["ended_because"]), ("doorbraak", None))
        self.assertEqual([(s.setup_id, s.at) for s in signals], [(1, T0 + STEP15 * 2)])
        self.assertEqual(first["signal_id"], 1)


class ReplayGuardsTest(unittest.TestCase):
    def test_too_little_history_emits_funnel_event_and_does_nothing_else(self):
        base = {"ETH": make_smc_prone_1m(days=2, seed=3, start_price=100.0)}
        events = []
        with mock.patch.object(smc_engine.smc_eval, "find_candidate") as find:
            signals = smc_engine.replay_smc("ETH", base, base["ETH"], pd.Timestamp("2026-01-01 03:03", tz="UTC"),
                                            pd.Timestamp("2026-01-01 03:33", tz="UTC"), step=STEP15, events=events)
        self.assertEqual(signals, [])
        self.assertEqual([e.kind for e in events], ["te_weinig_historie"] * 3)
        find.assert_not_called()

    def test_time_on_a_15_minute_boundary_is_refused(self):
        base = {"ETH": make_smc_prone_1m(days=2, seed=3, start_price=100.0)}
        with self.assertRaises(ValueError):
            smc_engine.replay_smc("ETH", base, base["ETH"], pd.Timestamp("2026-01-02 12:00", tz="UTC"),
                                  pd.Timestamp("2026-01-02 12:30", tz="UTC"), step=STEP15)


if __name__ == "__main__":
    unittest.main()
