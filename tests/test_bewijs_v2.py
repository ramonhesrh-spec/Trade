"""Bewijs v2, drie metingen (geen motor leest ze): spot en perps gescheiden per focus-soort, funding in de kosten, en MAE/MFE zonder doel gemeten
op dezelfde 5m-candles en dezelfde manier als met doel. Geen netwerk: de beurs en de funding-API zijn nagebootst."""
import asyncio
import sqlite3
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

import pandas as pd

from app import config, db, excursion, funding, level_check, outcome_measure, repo, track_record
from tests.test_basis_mae import bars
from tests.test_samenval import DbCase
from tests.test_web_focus import Base, signal

T0 = datetime(2026, 10, 1, 6, 0, tzinfo=timezone.utc)


def row(outcome, market=None, trade_type="zone_radar", funding_r=None, funding_status=None, price=100.0, stop=99.0, take=102.0):
    return {"price": price, "stop_loss": stop, "take_profit": take, "auto_outcome": outcome, "trade_type": trade_type, "message_id": None,
            "created_at": "2026-10-30T10:00:00+00:00", "auto_outcome_at": "2026-10-30T12:00:00+00:00", "candle_market": market,
            "funding_r": funding_r, "funding_status": funding_status}


def entry(rows, trade_type="zone_radar", **kw):
    return next(e for e in track_record.summarize(rows, 0.06, **kw) if e["trade_type"] == trade_type)


class EraSplitTest(unittest.TestCase):
    def test_perps_are_the_main_numbers_and_spot_the_older_part(self):
        rows = [row("take_profit", "perp"), row("stop_loss", "perp"), row("stop_loss", None), row("stop_loss", "spot"), row(None, "spot")]
        e = entry(rows, era_types=("zone_radar",))
        self.assertEqual((e["resolved"], e["wins"]), (2, 1))
        self.assertAlmostEqual(e["gross_total"], 1.0)
        old = e["older"]
        self.assertEqual((old["resolved"], old["wins"], old["open_or_expired"]), (2, 0, 1))
        self.assertAlmostEqual(old["gross_total"], -2.0)
        self.assertEqual(old["label"], track_record.SPOT_ERA_LABEL)
        self.assertEqual(track_record.SPOT_ERA_LABEL, "Vóór 1 november (spot-candles)")

    def test_only_spot_rows_still_give_a_focus_row_with_an_empty_main_part(self):
        e = entry([row("take_profit", None)], era_types=("zone_radar",))
        self.assertEqual(e["resolved"], 0)
        self.assertIsNone(e["avg_net"])
        self.assertEqual(e["older"]["resolved"], 1)

    def test_without_era_types_nothing_is_split(self):
        e = entry([row("take_profit", "perp"), row("stop_loss", None)])
        self.assertEqual(e["resolved"], 2)
        self.assertIsNone(e.get("older"))

    def test_other_types_and_the_total_are_not_split(self):
        rows = [row("take_profit", "perp"), row("stop_loss", None), row("stop_loss", None, trade_type="smc")]
        out = track_record.summarize(rows, 0.06, era_types=("zone_radar",))
        total = next(e for e in out if e["source"] == "alles")
        self.assertEqual(total["resolved"], 3)
        self.assertIsNone(next(e for e in out if e["trade_type"] == "smc").get("older"))


class FundingPureTest(unittest.TestCase):
    def events(self, hours, rate=0.0001, start=T0):
        return [(pd.Timestamp(start + timedelta(hours=h)), rate) for h in hours]

    def test_a_long_pays_positive_funding_and_a_short_receives_it(self):
        ev = self.events([2, 10, 18])                  # drie momenten binnen het venster
        long = funding.measure("long", 100.0, 99.0, ev, T0, T0 + timedelta(hours=20))
        short = funding.measure("short", 100.0, 101.0, ev, T0, T0 + timedelta(hours=20))
        self.assertEqual(long["events"], 3)
        self.assertAlmostEqual(long["funding_pct"], 0.03)       # 3 x 0,01%
        self.assertAlmostEqual(long["funding_r"], 0.03)         # stop op 1%: 0,03% is 0,03R
        self.assertAlmostEqual(short["funding_r"], -0.03)       # short ontvangt: negatieve kosten

    def test_negative_rates_flip_the_sign(self):
        ev = self.events([2], rate=-0.0005)
        self.assertAlmostEqual(funding.measure("long", 100.0, 98.0, ev, T0, T0 + timedelta(hours=3))["funding_r"], -0.025)  # 0,05% / 2%
        self.assertAlmostEqual(funding.measure("short", 100.0, 102.0, ev, T0, T0 + timedelta(hours=3))["funding_r"], 0.025)

    def test_only_moments_strictly_inside_the_window_count(self):
        ev = self.events([0, 4, 8, 12])                # 4-uursinterval van een afwijkend contract; 0 en 12 vallen op de randen
        m = funding.measure("long", 100.0, 99.0, ev, T0, T0 + timedelta(hours=12))
        self.assertEqual(m["events"], 2)
        self.assertAlmostEqual(m["funding_r"], 0.02)

    def test_no_moment_in_the_window_is_a_measured_zero(self):
        m = funding.measure("long", 100.0, 99.0, self.events([9]), T0, T0 + timedelta(hours=1))
        self.assertEqual((m["events"], m["funding_r"]), (0, 0.0))

    def test_the_perp_symbol_follows_the_1000_contract(self):
        self.assertEqual(funding.symbol("PEPE"), "1000PEPEUSDT")
        self.assertEqual(funding.symbol("btc"), "BTCUSDT")


class FundingInBewijsTest(unittest.TestCase):
    def test_net_subtracts_cost_and_measured_funding(self):
        rows = [row("take_profit", "perp", funding_r=0.10, funding_status="gemeten"),
                row("stop_loss", "perp", funding_r=-0.04, funding_status="gemeten"),
                row("stop_loss", "perp", funding_status="onbekend"),
                row("stop_loss", "perp")]                       # nog niet nagerekend: ook onbekend
        e = entry(rows)
        self.assertAlmostEqual(e["gross_total"], -1.0)
        self.assertAlmostEqual(e["funding_total"], 0.06)
        self.assertAlmostEqual(e["net_total"], -1.0 - 4 * 0.06 - 0.06)
        self.assertAlmostEqual(e["avg_funding_r"], 0.06 / 4)
        self.assertEqual((e["funding_measured"], e["funding_unknown"]), (2, 2))

    def test_no_funding_measured_is_none_not_zero(self):
        e = entry([row("take_profit", "perp")])
        self.assertIsNone(e["avg_funding_r"])
        self.assertEqual(e["funding_unknown"], 1)

    def test_the_net_r_elsewhere_also_counts_funding(self):
        r = row("take_profit", "perp", funding_r=0.5, funding_status="gemeten")
        self.assertAlmostEqual(track_record.net_signal_r(r, 0.06), 2.0 - 0.06 - 0.5)

    def test_cost_text_explains_the_funding_rule(self):
        self.assertEqual(track_record.cost_text(0.06),
                         "netto na 0,06% kosten per rondreis en de funding die de trade betaalde of ontving (long betaalt bij een positieve rate,"
                         " short ontvangt hem), beide omgerekend naar R met de stopafstand")


class FakeGet:
    def __init__(self, events=(), fail=False):
        self.calls, self.events, self.fail = [], list(events), fail

    def __call__(self, path, params, timeout=None):
        self.calls.append((path, dict(params), timeout))
        if self.fail:
            raise OSError("geen netwerk")
        lo, hi = params["startTime"], params.get("endTime", 10 ** 15)
        return [{"fundingTime": t, "fundingRate": str(r)} for t, r in self.events if lo <= t <= hi]


def ms(moment):
    return int(moment.timestamp() * 1000)


class FundingRecordTest(DbCase):
    def setUp(self):
        super().setUp()
        outcome_measure.clear_cache()
        self.sid = self.insert_signal(trade_type="zone_radar", price=100.0, stop_loss=99.0, take_profit=102.0)
        self.sig = repo.get_signal(self.sid)

    def test_a_focus_trade_stores_the_measured_funding_with_one_call(self):
        get = FakeGet([(ms(T0 + timedelta(hours=2)), 0.0001), (ms(T0 + timedelta(hours=10)), 0.0003)])
        with mock.patch.object(outcome_measure, "_funding_get", get):
            outcome_measure.record_funding(self.sig, T0, T0 + timedelta(hours=12))
            outcome_measure.record_funding(self.sig, T0, T0 + timedelta(hours=11))   # binnen het al opgehaalde venster: uit de cache
        f = repo.get_trade_funding(self.sid)
        self.assertEqual(f["status"], "gemeten")
        self.assertAlmostEqual(f["funding_r"], 0.04)
        self.assertEqual(f["events"], 2)
        self.assertEqual(len(get.calls), 1)
        path, params, timeout = get.calls[0]
        self.assertEqual((path, params["symbol"]), ("/fapi/v1/fundingRate", "BTCUSDT"))
        self.assertEqual(timeout, outcome_measure.TIMEOUT_S)

    def test_a_failed_call_is_unknown_never_zero(self):
        with mock.patch.object(outcome_measure, "_funding_get", FakeGet(fail=True)):
            outcome_measure.record_funding(self.sig, T0, T0 + timedelta(hours=12))
        f = repo.get_trade_funding(self.sid)
        self.assertEqual(f["status"], "onbekend")
        self.assertIsNone(f["funding_r"])

    def test_a_type_outside_focus_is_not_measured(self):
        sid = self.insert_signal(trade_type="smc")
        get = FakeGet()
        with mock.patch.object(outcome_measure, "_funding_get", get):
            outcome_measure.record_funding(repo.get_signal(sid), T0, T0 + timedelta(hours=12))
        self.assertIsNone(repo.get_trade_funding(sid))
        self.assertEqual(get.calls, [])

    def test_the_quality_report_carries_funding_and_market(self):
        with mock.patch.object(outcome_measure, "_funding_get", FakeGet([(ms(T0 + timedelta(hours=2)), 0.0001)])):
            outcome_measure.record_funding(self.sig, T0, T0 + timedelta(hours=12))
        r = next(r for r in repo.list_signals_for_quality_report() if r["id"] == self.sid)
        self.assertAlmostEqual(r["funding_r"], 0.01)
        self.assertEqual(r["funding_status"], "gemeten")
        self.assertIn("candle_market", r)


class LevelCheckRecordsFundingTest(DbCase):
    def test_the_outcome_check_stores_funding_until_the_end_of_the_exit_candle(self):
        outcome_measure.clear_cache()
        sid = repo.insert_signal({"coin": "BTC", "direction": "long", "category": "day_trading", "trade_type": "zone_radar", "price": 100.0,
                                  "stop_loss": 99.0, "take_profit": 102.0, "technical_confirmed": 1, "hard_gates_ok": 1, "confidence": "x"}, chain_it=False)
        created = datetime.now(timezone.utc).replace(second=0, microsecond=0) - timedelta(minutes=60)
        with db.session() as conn:
            conn.execute("UPDATE signals SET created_at = ? WHERE id = ?", (created.isoformat(), sid))
        frame = bars([(100.3, 99.4), (101.0, 99.8), (102.4, 100.5)], start=created + timedelta(minutes=5))
        # Doel in de candle van +15m; een funding-moment binnen die candle telt mee, een na het einde van die candle niet.
        get = FakeGet([(ms(created + timedelta(minutes=17)), 0.0002), (ms(created + timedelta(minutes=21)), 0.0009)])
        with mock.patch("app.exchange.fetch_ohlcv", lambda *a, **k: frame), mock.patch.object(outcome_measure, "_funding_get", get):
            asyncio.run(level_check.check_signal_outcomes())
        self.assertEqual(repo.get_signal(sid)["auto_outcome"], "take_profit")
        f = repo.get_trade_funding(sid)
        self.assertEqual((f["status"], f["events"]), ("gemeten", 1))
        self.assertAlmostEqual(f["funding_r"], 0.02)


class ExcursionWithoutTargetTest(DbCase):
    """Zonder doel: de 5m-candles van de vulling tot de uitgang, gemeten met excursion.measure zoals level_check dat met doel doet."""

    def setUp(self):
        super().setUp()
        self.sid = self.insert_signal(trade_type="zone_sweep", price=100.0, stop_loss=99.0, take_profit=None)
        self.created = "2026-10-30T10:02:00+00:00"
        # 09:55 opende vóór de vulling en telt niet; 10:20 opent na de uitgang en telt niet.
        self.frame = bars([(105.0, 90.0), (100.5, 99.6), (101.2, 99.7), (101.9, 99.5), (100.8, 99.8), (108.0, 92.0)],
                          start=datetime(2026, 10, 30, 9, 55, tzinfo=timezone.utc))

    def fetch(self, coin, timeframe="5m", limit=1000, since=None):
        self.calls.append((coin, timeframe, since))
        return self.frame[self.frame["timestamp"] >= pd.Timestamp(since, unit="ms", tz="UTC")].head(limit).reset_index(drop=True)

    def test_same_numbers_as_level_check_on_the_same_candles(self):
        self.calls = []
        end = pd.Timestamp("2026-10-30T10:20:00+00:00")
        with mock.patch.object(outcome_measure, "_candles_fetch", self.fetch):
            outcome_measure.record_excursion(self.sid, "BTC", "long", 100.0, 99.0, self.created, end)
        stored = repo.get_trade_excursion(self.sid)
        window = level_check.candles_after(self.frame, self.created)
        window = window[window["timestamp"] < end]
        with_target = excursion.measure("long", 100.0, 99.0, 150.0, window)     # een doel dat nooit geraakt wordt: dezelfde meting
        self.assertAlmostEqual(stored["mae_r"], with_target["mae_r"])
        self.assertAlmostEqual(stored["mfe_r"], with_target["mfe_r"])
        self.assertAlmostEqual(stored["mae_r"], 0.5)
        self.assertAlmostEqual(stored["mfe_r"], 1.9)
        self.assertEqual(stored["timeframe"], "5m")
        self.assertEqual(self.calls[0][1], "5m")

    def test_a_failed_fetch_stores_unknown_not_the_running_measure(self):
        repo.set_trade_excursion(self.sid, 0.3, 0.9, "15m")
        with mock.patch.object(outcome_measure, "_candles_fetch", side_effect=OSError("geen netwerk")):
            outcome_measure.record_excursion(self.sid, "BTC", "long", 100.0, 99.0, self.created, pd.Timestamp("2026-10-30T10:20:00+00:00"))
        x = repo.get_trade_excursion(self.sid)
        self.assertIsNone(x["mae_r"])
        self.assertEqual(x["timeframe"], "onbekend")

    def test_candles_that_stop_short_of_the_exit_are_unknown(self):
        self.frame = self.frame.head(3)
        with mock.patch.object(outcome_measure, "_candles_fetch", self.fetch):
            self.calls = []
            outcome_measure.record_excursion(self.sid, "BTC", "long", 100.0, 99.0, self.created, pd.Timestamp("2026-10-30T10:20:00+00:00"))
        self.assertIsNone(repo.get_trade_excursion(self.sid)["mae_r"])

    def test_unknown_counts_as_unmeasured_on_bewijs(self):
        rows = [{"trade_type": "zone_sweep", "auto_outcome": "stop_loss", "price": 100.0, "stop_loss": 99.0, "take_profit": None, "mae_r": None,
                 "mfe_r": None, "r_override": -1.0}]
        self.assertEqual(excursion.stats(rows)["zone_sweep"]["unmeasured"], 1)


SCRIPTS = Path(__file__).resolve().parent.parent / "scripts"


def load(name):
    import importlib.util
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def run_main(mod, *args):
    import contextlib
    import io
    out = io.StringIO()
    with mock.patch("sys.argv", [mod.__name__, *args]), contextlib.redirect_stdout(out):
        mod.main()
    return out.getvalue()


class ExitEndTest(unittest.TestCase):
    def test_a_reference_exit_ends_with_its_15m_candle(self):
        row = {"auto_outcome_at": "2026-10-30T13:07:00+00:00", "mae_timeframe": None}
        self.assertEqual(outcome_measure.exit_end(row, "2026-10-30T12:45:00+00:00"), pd.Timestamp("2026-10-30T13:00:00+00:00"))

    def test_an_outcome_from_level_check_ends_with_its_candle(self):
        self.assertEqual(outcome_measure.exit_end({"auto_outcome_at": "2026-10-30T12:45:00+00:00", "mae_timeframe": "15m"}),
                         pd.Timestamp("2026-10-30T13:00:00+00:00"))
        self.assertEqual(outcome_measure.exit_end({"auto_outcome_at": "2026-10-30T12:45:00+00:00", "mae_timeframe": "onbekend"}),
                         pd.Timestamp("2026-10-30T12:50:00+00:00"))


class FundingCheckScriptTest(DbCase):
    def setUp(self):
        super().setUp()
        outcome_measure.clear_cache()
        self.ids = []
        for outcome in ("take_profit", "stop_loss"):
            sid = self.insert_signal(trade_type="zone_radar", coin="SOL")
            with db.session() as conn:
                conn.execute("UPDATE signals SET auto_outcome = ?, auto_outcome_at = ?, created_at = ? WHERE id = ?",
                             (outcome, (T0 + timedelta(hours=12)).isoformat(), T0.isoformat(), sid))
            self.ids.append(sid)
        self.get = FakeGet([(ms(T0 + timedelta(hours=2)), 0.0001), (ms(T0 + timedelta(hours=10)), 0.0001)])

    def test_read_only_by_default_with_one_call_per_coin(self):
        with mock.patch.object(outcome_measure, "_funding_get", self.get):
            out = run_main(load("funding_check"), "--dagen", "400")
        self.assertIsNone(repo.get_trade_funding(self.ids[0]))
        self.assertEqual(len(self.get.calls), 1)
        self.assertIn("Alleen-lezen", out)
        self.assertIn("2 gemeten, 0 onbekend", out)

    def test_opslaan_stores_each_trade(self):
        with mock.patch.object(outcome_measure, "_funding_get", self.get):
            run_main(load("funding_check"), "--dagen", "400", "--opslaan")
        f = repo.get_trade_funding(self.ids[1])
        self.assertEqual(f["status"], "gemeten")
        self.assertAlmostEqual(f["funding_r"], 0.02)

    def test_a_failed_call_is_counted_and_stored_as_unknown(self):
        with mock.patch.object(outcome_measure, "_funding_get", FakeGet(fail=True)):
            out = run_main(load("funding_check"), "--dagen", "400", "--opslaan")
        self.assertIn("0 gemeten, 2 onbekend", out)
        self.assertEqual(repo.get_trade_funding(self.ids[0])["status"], "onbekend")


class MaeCheckRedoTest(DbCase):
    def test_opnieuw_measures_a_trade_without_target_on_5m_candles(self):
        sid = self.insert_signal(trade_type="zone_sweep", take_profit=None)
        created = datetime(2026, 10, 30, 10, 0, tzinfo=timezone.utc)
        with db.session() as conn:
            conn.execute("UPDATE signals SET auto_outcome = 'stop_loss', auto_outcome_at = ?, created_at = ? WHERE id = ?",
                         ((created + timedelta(minutes=40)).isoformat(), created.isoformat(), sid))
        repo.set_trade_result(sid, -1.0, (created + timedelta(minutes=40)).isoformat())
        repo.set_trade_excursion(sid, 0.2, 0.3, "15m")                 # de oude lopende meting
        frame = bars([(100.5, 99.6), (101.5, 99.7), (100.2, 98.9), (100.0, 99.5), (100.0, 99.5), (100.0, 99.5)], start=created)
        with mock.patch.object(outcome_measure, "_candles_fetch", lambda coin, timeframe, limit, since: frame), \
                mock.patch.object(repo, "reference_exits", lambda: {sid: (created + timedelta(minutes=10)).isoformat()}):
            out = run_main(load("mae_check"), "--opnieuw", "--dagen", "400")
        x = repo.get_trade_excursion(sid)
        self.assertEqual(x["timeframe"], "5m")
        self.assertAlmostEqual(x["mae_r"], 1.0)
        self.assertAlmostEqual(x["mfe_r"], 1.5)
        self.assertIn("1 opnieuw gemeten", out)


class OldDatabaseMigrationTest(unittest.TestCase):
    def test_an_old_database_gets_trade_funding_and_a_nullable_excursion(self):
        import tempfile
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        path = str(Path(tmp.name) / "old.db")
        with mock.patch.object(config, "DATABASE_PATH", path):
            db.init_db()
            with db.session() as conn:
                conn.execute("DROP TABLE trade_funding")
                conn.execute("DROP TABLE trade_excursions")
                conn.execute("""CREATE TABLE trade_excursions (signal_id INTEGER PRIMARY KEY, mae_r REAL NOT NULL, mfe_r REAL NOT NULL,
                                timeframe TEXT, measured_at TEXT NOT NULL)""")
                conn.execute("INSERT INTO trade_excursions VALUES (7, 0.4, 1.2, '5m', '2026-10-30T10:00:00+00:00')")
            db.init_db()
            db.init_db()                                   # idempotent
            repo.set_trade_excursion(8, None, None, "onbekend")
            self.assertAlmostEqual(repo.get_trade_excursion(7)["mae_r"], 0.4)   # oude meting blijft
            self.assertIsNone(repo.get_trade_excursion(8)["mae_r"])
            repo.set_trade_funding(7, None, None, 0, "onbekend", "2026-10-30T10:00:00+00:00", "2026-10-30T12:00:00+00:00")
            self.assertEqual(repo.get_trade_funding(7)["status"], "onbekend")
        with sqlite3.connect(path) as raw:
            cols = {r[1]: r[3] for r in raw.execute("PRAGMA table_info(trade_excursions)")}
        self.assertEqual(cols["mae_r"], 0)                 # notnull uit


def perp_signal(coin, trade_type, outcome, market="perp", **kw):
    sid = signal(coin, trade_type, outcome, **kw)
    with db.session() as conn:
        conn.execute("UPDATE signals SET candle_market = ? WHERE id = ?", (market, sid))
    return sid


class BewijsPageTest(Base):
    def test_a_focus_type_shows_perps_as_main_and_spot_apart(self):
        perp_signal("SOL", "zone_radar", "take_profit")
        perp_signal("SOL", "zone_radar", "stop_loss")
        perp_signal("ETH", "zone_radar", "stop_loss", market=None)
        with mock.patch.object(config, "TRACK_RECORD_COST_PCT", 0.06):
            html = self.client.get("/bewijs").text
        self.assertIn("+0,50R", html)                      # bruto per trade op perps: (2 - 1) / 2
        self.assertIn("Vóór 1 november (spot-candles)", html)
        self.assertIn("proof-older", html)

    def test_funding_line_and_unknown_count(self):
        sid = perp_signal("SOL", "zone_radar", "take_profit")
        perp_signal("SOL", "zone_radar", "stop_loss")
        repo.set_trade_funding(sid, 0.08, 0.008, 1, "gemeten", "2026-10-30T10:00:00+00:00", "2026-10-30T12:00:00+00:00")
        html = self.client.get("/bewijs").text
        self.assertIn("waarvan funding +0,04R", html)       # 0,08 over twee afgeronde trades
        self.assertIn("1 trade met onbekende funding", html)


if __name__ == "__main__":
    unittest.main()
