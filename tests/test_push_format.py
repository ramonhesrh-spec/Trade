import unittest

from app import push_notify as pn


class PushFormatTest(unittest.TestCase):
    def test_title_is_one_short_line_with_direction_arrow(self):
        self.assertEqual(pn.alert_title("BTC", "long", "SMC"), "▲ BTC long · SMC")
        self.assertEqual(pn.alert_title("SOL", "short", "Script (ongetest)"), "▼ SOL short · Script (ongetest)")
        self.assertLessEqual(len(pn.alert_title("AVAX", "short", "Samenval (ongetest)")), 40)

    def test_body_has_order_first_then_stop_take_then_notes_without_empty_lines(self):
        body = pn.trade_body("Limietorder", 67350.0, 66950.0, 68350.0, 2.5, "Als: boven 67400", "", "Ongetest.")
        self.assertEqual(body.splitlines(), ["Limietorder 67350.00 · R:R 2.5", "Stop 66950.00 · Take 68350.00", "Als: boven 67400", "Ongetest.", pn.OPEN_PLAN_LINE])

    def test_small_prices_keep_four_decimals_and_rr_is_optional(self):
        self.assertEqual(pn.trade_body("Entry", 0.1632, 0.166, 0.155).splitlines(), ["Entry 0.1632", "Stop 0.1660 · Take 0.1550", pn.OPEN_PLAN_LINE])


if __name__ == "__main__":
    unittest.main()
