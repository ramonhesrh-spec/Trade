import unittest
from unittest import mock

from app import config, focus


class FocusTypesTest(unittest.TestCase):
    def test_focus_types_are_the_three_live_kinds(self):
        self.assertEqual(focus.FOCUS_TYPES, ("structuur", "structuur_c", "zone_radar", "zone_sweep", "poc_radar"))

    def test_is_focus(self):
        for t in ("structuur", "structuur_c", "zone_radar", "zone_sweep", "poc_radar"):
            self.assertTrue(focus.is_focus(t))
        for t in ("day_trading", "patroon", "trend", "rejectie", "script", "smc", "smc_waarschuwing", "swing",
                  "range_sweep", "range_watch", "don55_trend", "samenval", None, ""):
            self.assertFalse(focus.is_focus(t))

    def test_label(self):
        self.assertEqual(focus.label("structuur"), "Structuur A/B")
        self.assertEqual(focus.label("structuur_c"), "Structuur C")
        self.assertEqual(focus.label("zone_radar"), "Zone-radar")
        self.assertEqual(focus.label("poc_radar"), "POC-radar")
        self.assertEqual(focus.label("smc"), "SMC liquidity sweep")         # de gewone naam van Bewijs
        self.assertEqual(focus.label("iets_nieuws"), "iets_nieuws")


class EngineOnTest(unittest.TestCase):
    def test_focus_on_only_focus_types_run(self):
        self.assertTrue(focus.engine_on("zone_radar", focus_on=True))
        self.assertFalse(focus.engine_on("trend", focus_on=True))

    def test_focus_off_restores_everything(self):
        self.assertTrue(focus.engine_on("trend", focus_on=False))
        self.assertTrue(focus.engine_on("day_trading", focus_on=False))

    def test_own_flag_still_wins(self):
        self.assertFalse(focus.engine_on("zone_radar", enabled=False, focus_on=True))
        self.assertFalse(focus.engine_on("trend", enabled=False, focus_on=False))

    def test_reads_config_when_not_given(self):
        with mock.patch.object(config, "ENGINE_FOCUS", True):
            self.assertFalse(focus.engine_on("smc"))
            self.assertTrue(focus.active())
        with mock.patch.object(config, "ENGINE_FOCUS", False):
            self.assertTrue(focus.engine_on("smc"))
            self.assertFalse(focus.active())

    def test_default_is_on(self):
        import importlib
        import os
        try:
            with mock.patch.dict(os.environ, {}, clear=False):
                os.environ.pop("ENGINE_FOCUS", None)
                with mock.patch("dotenv.load_dotenv"):
                    importlib.reload(config)
                    self.assertTrue(config.ENGINE_FOCUS)
        finally:
            importlib.reload(config)          # buiten patch.dict: de rest van de suite houdt de omgeving van tests/__init__.py


class SplitTest(unittest.TestCase):
    def test_split_keeps_order_and_drops_nothing(self):
        rows = [{"trade_type": "smc"}, {"trade_type": "zone_radar"}, {"trade_type": "structuur"}, {"trade_type": "trend"}]
        on, off = focus.split(rows, focus_on=True)
        self.assertEqual([r["trade_type"] for r in on], ["zone_radar", "structuur"])
        self.assertEqual([r["trade_type"] for r in off], ["smc", "trend"])

    def test_split_without_focus_keeps_all_in_front(self):
        rows = [{"trade_type": "smc"}, {"trade_type": "zone_radar"}]
        self.assertEqual(focus.split(rows, focus_on=False), (rows, []))


if __name__ == "__main__":
    unittest.main()
