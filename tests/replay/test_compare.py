import unittest

import pandas as pd

from app.replay import compare

T = pd.Timestamp("2026-10-02 12:00", tz="UTC")
H = pd.Timedelta(hours=1)
UNTIL = T + pd.Timedelta(days=2)


def live(id_, coin="ETH", direction="long", at=T):
    return {"id": id_, "coin": coin, "direction": direction, "at": at}


class FoundInTraceTest(unittest.TestCase):
    def check(self, row, all_live, trace):
        return compare.found_in_trace(row, all_live, trace, UNTIL)

    def test_found_inside_window_after_creation(self):
        row = live(1)
        self.assertTrue(self.check(row, [row], [("ETH", "long", T + 10 * H, True)]))

    def test_found_before_creation_within_tolerance(self):
        row = live(1)
        self.assertTrue(self.check(row, [row], [("ETH", "long", T - 2 * H, True)]))
        self.assertFalse(self.check(row, [row], [("ETH", "long", T - 2 * H - pd.Timedelta(minutes=1), True)]))

    def test_outside_window_after_until(self):
        row = live(1)
        self.assertFalse(self.check(row, [row], [("ETH", "long", UNTIL + H, True)]))

    def test_window_ends_at_next_live_row_of_same_coin(self):
        row, nxt = live(1), live(2, direction="short", at=T + 5 * H)
        trace = [("ETH", "long", T + 6 * H, True)]
        self.assertFalse(self.check(row, [row, nxt], trace))
        self.assertTrue(self.check(row, [row, nxt], [("ETH", "long", T + 5 * H, True)]))

    def test_other_coin_does_not_end_window(self):
        row, other = live(1), live(2, coin="BTC", at=T + 5 * H)
        self.assertTrue(self.check(row, [row, other], [("ETH", "long", T + 6 * H, True)]))

    def test_direction_mismatch_and_unconfirmed(self):
        row = live(1)
        self.assertFalse(self.check(row, [row], [("ETH", "short", T + H, True)]))
        self.assertFalse(self.check(row, [row], [("ETH", "long", T + H, False)]))
        self.assertFalse(self.check(row, [row], [("BTC", "long", T + H, True)]))


class StrictTest(unittest.TestCase):
    def test_strict_needs_confirmed_replay_signal_within_two_hours(self):
        row = live(1)
        near = {"coin": "ETH", "direction": "long", "at": T + 2 * H, "confirmed": True}
        self.assertTrue(compare.found_strict(row, [near]))
        self.assertFalse(compare.found_strict(row, [{**near, "at": T + 3 * H}]))
        self.assertFalse(compare.found_strict(row, [{**near, "confirmed": False}]))


if __name__ == "__main__":
    unittest.main()
