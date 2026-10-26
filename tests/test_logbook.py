"""Het Logboek als dagtijdlijn (app/logbook.py): wat de app zag, wat jij deed en de gemeten R per dag."""
import unittest
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from app import logbook

TZ = ZoneInfo("Europe/Amsterdam")
NOW = datetime(2026, 10, 25, 22, 30, tzinfo=timezone.utc)          # zondag 25 oktober, 23:30 in Amsterdam (wintertijd)


def sig(sid, coin="BTC", direction="short", price=100.0, stop=101.0, take=98.0, created="2026-10-25T20:40:00+00:00",
        outcome=None, outcome_at=None, **kw):
    return {"id": sid, "coin": coin, "direction": direction, "price": price, "stop_loss": stop, "take_profit": take,
            "created_at": created, "auto_outcome": outcome, "auto_outcome_at": outcome_at, "r_override": None, "trade_type": "zone_radar", **kw}


def plan(key, coin="BTC", direction="short", created="2026-10-25T18:00:00+00:00", signal_id=None):
    return {"key": key, "coin": coin, "direction": direction, "created_at": created, "zone_at": None, "signal_id": signal_id}


def build(**kw):
    args = {"skips": [], "runs": [], "plans": {}, "signals": {}, "taken": [], "seen": [], "now": NOW, "tz": TZ}
    args.update(kw)
    return logbook.timeline(**args)


class TimelineTests(unittest.TestCase):
    def test_vandaag_staat_er_altijd_ook_zonder_iets(self):
        days = build()
        self.assertEqual(len(days), 1)
        self.assertTrue(days[0]["is_today"])
        self.assertEqual(days[0]["date_text"], "Zondag 25 oktober")
        self.assertEqual(days[0]["events"], [])
        self.assertIsNone(days[0]["total_r"])
        self.assertEqual(days[0]["total_text"], "0 R")

    def test_een_trade_via_de_checklist_heeft_order_vulling_en_sluiting_met_r(self):
        s = sig(5, outcome="take_profit", outcome_at="2026-10-25T22:20:00+00:00")
        days = build(runs=[{"plan_key": "zone:1", "coin": "BTC", "direction": "short", "opened_at": "2026-10-25T20:38:00+00:00",
                            "done_at": "2026-10-25T20:39:12+00:00"}],
                     plans={"zone:1": plan("zone:1", signal_id=5)}, signals={5: s})
        ev = days[0]["events"]
        self.assertEqual([e["kind"] for e in ev], ["closed", "filled", "order"])           # nieuwste bovenaan
        closed, filled, order = ev
        self.assertEqual((closed["time"], closed["title"], closed["r_text"], closed["tone"]), ("23:20", "BTC short gesloten", "+2,0 R", "win"))
        self.assertIn("Doel geraakt", closed["sub"])
        self.assertIn("1 u 40 min na instap", closed["sub"])
        self.assertEqual(closed["replay_url"], "/logboek/replay/5")
        self.assertEqual(closed["url"], "/kans/5")
        self.assertEqual((filled["title"], filled["sub"]), ("BTC short gevuld", "Limit op 100,00."))
        self.assertEqual(filled["r_text"], "")
        self.assertEqual((order["time"], order["title"], order["sub"]), ("21:39", "BTC short order gezet", "Checklist in 1 min 12 s."))
        self.assertEqual((days[0]["total_r"], days[0]["total_text"], days[0]["trades"]), (2.0, "+2,0 R", 1))

    def test_een_checklist_zonder_afronding_staat_er_niet(self):
        days = build(runs=[{"plan_key": "zone:1", "coin": "BTC", "direction": "short", "opened_at": "2026-10-25T20:38:00+00:00", "done_at": None}],
                     plans={"zone:1": plan("zone:1")})
        self.assertEqual(days[0]["events"], [])

    def test_een_overgeslagen_plan_met_uitkomst_noemt_die_en_telt_niet_mee(self):
        s = sig(6, coin="SOL", direction="long", price=10.0, stop=9.0, take=11.0, outcome="take_profit", outcome_at="2026-10-25T21:00:00+00:00")
        days = build(skips=[{"plan_key": "zone:2", "coin": "SOL", "direction": "long", "skipped_at": "2026-10-25T18:05:00+00:00"}],
                     plans={"zone:2": plan("zone:2", "SOL", "long", signal_id=6)}, signals={6: s})
        ev = days[0]["events"]
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0]["kind"], ev[0]["time"], ev[0]["title"], ev[0]["r_text"]), ("skipped", "19:05", "SOL long overgeslagen", "0 R"))
        self.assertEqual(ev[0]["sub"], "Jouw keuze. Haalde later zijn doel (+1,0 R niet genomen).")
        self.assertEqual(ev[0]["replay_url"], "/logboek/replay/6")
        self.assertIsNone(days[0]["total_r"])
        self.assertEqual(days[0]["trades"], 0)

    def test_een_overgeslagen_plan_zonder_uitkomst_zegt_alleen_wat_vaststaat(self):
        days = build(skips=[{"plan_key": "zone:2", "coin": "SOL", "direction": "long", "skipped_at": "2026-10-25T18:05:00+00:00"}],
                     plans={"zone:2": plan("zone:2", "SOL", "long")})
        self.assertEqual(days[0]["events"][0]["sub"], "Jouw keuze.")
        self.assertIsNone(days[0]["events"][0]["replay_url"])
        s = sig(6, coin="SOL", direction="long", stop=101.0, take=98.0, outcome="stop_loss", outcome_at="2026-10-25T21:00:00+00:00")
        days = build(skips=[{"plan_key": "zone:2", "coin": "SOL", "direction": "long", "skipped_at": "2026-10-25T18:05:00+00:00"}],
                     plans={"zone:2": plan("zone:2", "SOL", "long", signal_id=6)}, signals={6: s})
        self.assertEqual(days[0]["events"][0]["sub"], "Jouw keuze. Raakte later de stop (−1,0 R).")

    def test_een_overgeslagen_plan_met_afgeronde_checklist_is_wel_een_trade(self):
        s = sig(5, outcome="stop_loss", outcome_at="2026-10-25T21:30:00+00:00")
        days = build(skips=[{"plan_key": "zone:1", "coin": "BTC", "direction": "short", "skipped_at": "2026-10-25T20:30:00+00:00"}],
                     runs=[{"plan_key": "zone:1", "coin": "BTC", "direction": "short", "opened_at": "2026-10-25T20:38:00+00:00", "done_at": "2026-10-25T20:39:00+00:00"}],
                     plans={"zone:1": plan("zone:1", signal_id=5)}, signals={5: s})
        kinds = [e["kind"] for e in days[0]["events"]]
        self.assertNotIn("skipped", kinds)
        self.assertEqual(days[0]["total_text"], "−1,0 R")

    def test_een_genomen_journaalregel_is_een_trade(self):
        s = sig(7, coin="ETH", direction="long", price=100.0, stop=99.0, take=103.0, trade_type="smc", outcome="stop_loss",
                outcome_at="2026-10-25T13:30:00+00:00", created="2026-10-25T12:00:00+00:00")
        days = build(taken=[{"signal_id": 7, "status": "genomen", "entry_price": 100.5, "entry_time": "2026-10-25T12:50:00+00:00"}],
                     signals={7: s})
        ev = days[0]["events"]
        self.assertEqual([e["kind"] for e in ev], ["closed", "taken"])
        self.assertEqual((ev[1]["title"], ev[1]["sub"]), ("ETH long genomen", "Instap 100,50."))
        self.assertIn("Stop geraakt, 40 min na instap.", ev[0]["sub"])
        self.assertEqual(ev[0]["r_text"], "−1,0 R")

    def test_vervallen_heeft_geen_r_en_geen_replay(self):
        s = sig(5, outcome="vervallen", outcome_at="2026-10-25T22:00:00+00:00")
        days = build(taken=[{"signal_id": 5, "status": "genomen", "entry_price": None, "entry_time": "2026-10-25T20:41:00+00:00"}], signals={5: s})
        closed = days[0]["events"][0]
        self.assertEqual((closed["kind"], closed["r_text"], closed["replay_url"]), ("expired", "", None))
        self.assertIsNone(days[0]["total_r"])

    def test_een_open_trade_heeft_nog_geen_sluiting(self):
        days = build(taken=[{"signal_id": 5, "status": "genomen", "entry_price": None, "entry_time": "2026-10-25T20:41:00+00:00"}], signals={5: sig(5)})
        self.assertEqual([e["kind"] for e in days[0]["events"]], ["taken"])
        self.assertEqual(days[0]["events"][0]["sub"], "Instap 100,00.")

    def test_wat_de_app_zag_per_dag(self):
        seen = [{"created_at": "2026-10-25T08:12:00+00:00", "zone_at": "2026-10-25T10:00:00+00:00"},
                {"created_at": "2026-10-25T09:00:00+00:00", "zone_at": None},
                {"created_at": "2026-10-24T09:00:00+00:00", "zone_at": "2026-10-25T11:00:00+00:00"}]
        days = build(seen=seen)
        ev = days[0]["events"]
        self.assertEqual(len(ev), 1)
        self.assertEqual((ev[0]["kind"], ev[0]["time"], ev[0]["title"]), ("seen", "09:12", "Wat de app zag"))
        self.assertEqual(ev[0]["sub"], "2 nieuwe plannen. 2 kwamen in de zone.")
        yesterday = days[1]
        self.assertEqual(yesterday["events"][0]["sub"], "1 nieuw plan.")

    def test_oudere_dagen_samengevat_en_dagtotaal_op_de_sluitdag(self):
        s1 = sig(5, outcome="stop_loss", outcome_at="2026-10-24T15:00:00+00:00", created="2026-10-24T12:00:00+00:00")
        s2 = sig(8, outcome="take_profit", outcome_at="2026-10-24T18:00:00+00:00", created="2026-10-24T13:00:00+00:00", take=99.0)
        taken = [{"signal_id": 5, "status": "genomen", "entry_price": None, "entry_time": "2026-10-24T12:01:00+00:00"},
                 {"signal_id": 8, "status": "aangepast", "entry_price": None, "entry_time": "2026-10-24T13:01:00+00:00"}]
        days = build(taken=taken, signals={5: s1, 8: s2})
        self.assertEqual(len(days), 2)
        old = days[1]
        self.assertFalse(old["is_today"])
        self.assertEqual((old["total_r"], old["trades"]), (0.0, 2))
        self.assertEqual(old["summary"], "Zaterdag 24 okt · 0,0 R · 2 trades")

    def test_een_dag_zonder_trades_zegt_dat(self):
        days = build(skips=[{"plan_key": "zone:2", "coin": "SOL", "direction": "long", "skipped_at": "2026-10-23T10:00:00+00:00"}],
                     plans={"zone:2": plan("zone:2", "SOL", "long")})
        self.assertEqual(days[1]["summary"], "Vrijdag 23 okt · geen trades")

    def test_genegeerd_en_oefentrades_tellen_nooit(self):
        s = sig(5, outcome="take_profit", outcome_at="2026-10-25T21:00:00+00:00")
        p = sig(9, outcome="take_profit", outcome_at="2026-10-25T21:00:00+00:00", is_practice=1)
        days = build(taken=[{"signal_id": 5, "status": "genegeerd", "entry_price": None, "entry_time": None},
                            {"signal_id": 9, "status": "genomen", "entry_price": None, "entry_time": "2026-10-25T20:00:00+00:00"}],
                     signals={5: s, 9: p})
        self.assertEqual(days[0]["events"], [])

    def test_r_komt_uit_signal_r_ook_met_een_meelopende_stop(self):
        s = sig(5, outcome="take_profit", outcome_at="2026-10-25T21:00:00+00:00", r_override=3.4)
        days = build(taken=[{"signal_id": 5, "status": "genomen", "entry_price": None, "entry_time": "2026-10-25T20:41:00+00:00"}], signals={5: s})
        self.assertEqual(days[0]["events"][0]["r_text"], "+3,4 R")

    def test_alleen_de_laatste_dagen(self):
        days = build(skips=[{"plan_key": "zone:2", "coin": "SOL", "direction": "long", "skipped_at": "2026-09-01T10:00:00+00:00"}],
                     plans={"zone:2": plan("zone:2", "SOL", "long")})
        self.assertEqual(len(days), 1)


class FormatTests(unittest.TestCase):
    def test_r_tekst(self):
        self.assertEqual(logbook.r_text(2.0), "+2,0 R")
        self.assertEqual(logbook.r_text(-1.0), "−1,0 R")
        self.assertEqual(logbook.r_text(0.0), "0,0 R")



class WeekInputTests(unittest.TestCase):
    def test_afgeronde_trades_en_overgeslagen_uitkomsten(self):
        s5 = sig(5, outcome="take_profit", outcome_at="2026-10-25T22:20:00+00:00")
        s6 = sig(6, coin="SOL", outcome="stop_loss", outcome_at="2026-10-25T21:00:00+00:00")
        runs = [{"plan_key": "zone:1", "coin": "BTC", "direction": "short", "opened_at": "2026-10-25T20:38:00+00:00", "done_at": "2026-10-25T20:39:12+00:00"}]
        plans = {"zone:1": plan("zone:1", signal_id=5), "zone:2": plan("zone:2", "SOL", signal_id=6), "zone:3": plan("zone:3")}
        skips = [{"plan_key": "zone:2", "skipped_at": "2026-10-25T18:00:00+00:00"}, {"plan_key": "zone:3", "skipped_at": "2026-10-25T18:30:00+00:00"},
                 {"plan_key": "zone:1", "skipped_at": "2026-10-25T18:40:00+00:00"}]
        signals = {5: s5, 6: s6}
        self.assertEqual(logbook.closed_trades(runs, plans, signals, []), [{"signal_id": 5, "at": "2026-10-25T22:20:00+00:00", "r": 2.0}])
        self.assertEqual(logbook.skip_outcomes(skips, runs, plans, signals),
                         [{"at": "2026-10-25T18:00:00+00:00", "outcome": "stop_loss", "r": -1.0}, {"at": "2026-10-25T18:30:00+00:00", "outcome": None, "r": None}])


if __name__ == "__main__":
    unittest.main()
