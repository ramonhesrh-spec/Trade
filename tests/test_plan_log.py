"""Overslaan en de order-checklist in de database (fase 2, R1 en R2): per gebruiker, met tijdstip, en nooit zichtbaar voor een ander."""
import unittest

from app import db, logbook, repo
from tests.test_samenval import DbCase


class SkipRepoTests(DbCase):
    def setUp(self):
        super().setUp()
        self.a = repo.get_user_by_username("a")["id"]
        self.b = repo.create_user("b", "x", 0, 1)

    def test_overslaan_bewaart_sleutel_coin_richting_en_tijd(self):
        repo.record_plan_skip(self.a, "zone:4", "BTC", "short", "2026-10-25T19:05:00+00:00")
        rows = repo.list_plan_skips(self.a)
        self.assertEqual([(r["plan_key"], r["coin"], r["direction"], r["skipped_at"]) for r in rows],
                         [("zone:4", "BTC", "short", "2026-10-25T19:05:00+00:00")])

    def test_twee_keer_overslaan_houdt_het_eerste_moment(self):
        repo.record_plan_skip(self.a, "zone:4", "BTC", "short", "2026-10-25T19:05:00+00:00")
        repo.record_plan_skip(self.a, "zone:4", "BTC", "short", "2026-10-25T20:00:00+00:00")
        self.assertEqual([r["skipped_at"] for r in repo.list_plan_skips(self.a)], ["2026-10-25T19:05:00+00:00"])

    def test_een_ander_ziet_jouw_overgeslagen_plannen_nooit(self):
        repo.record_plan_skip(self.a, "zone:4", "BTC", "short", "2026-10-25T19:05:00+00:00")
        self.assertEqual(repo.list_plan_skips(self.b), [])

    def test_sinds_filtert_op_tijd(self):
        repo.record_plan_skip(self.a, "zone:4", "BTC", "short", "2026-10-24T10:00:00+00:00")
        repo.record_plan_skip(self.a, "zone:5", "ETH", "long", "2026-10-25T10:00:00+00:00")
        self.assertEqual([r["plan_key"] for r in repo.list_plan_skips(self.a, since_iso="2026-10-25T00:00:00+00:00")], ["zone:5"])


class ChecklistRepoTests(DbCase):
    def setUp(self):
        super().setUp()
        self.a = repo.get_user_by_username("a")["id"]
        self.b = repo.create_user("b", "x", 0, 1)

    def test_openen_en_afronden_bewaart_beide_tijden(self):
        repo.open_checklist(self.a, "zone:4", "BTC", "short", "2026-10-25T21:38:48+00:00")
        self.assertTrue(repo.finish_checklist(self.a, "zone:4", "2026-10-25T21:40:00+00:00"))
        run = repo.list_checklist_runs(self.a)[0]
        self.assertEqual((run["opened_at"], run["done_at"]), ("2026-10-25T21:38:48+00:00", "2026-10-25T21:40:00+00:00"))

    def test_opnieuw_openen_voor_het_afronden_start_de_tijd_opnieuw(self):
        repo.open_checklist(self.a, "zone:4", "BTC", "short", "2026-10-25T20:00:00+00:00")
        repo.open_checklist(self.a, "zone:4", "BTC", "short", "2026-10-25T21:38:48+00:00")
        repo.finish_checklist(self.a, "zone:4", "2026-10-25T21:40:00+00:00")
        self.assertEqual(repo.list_checklist_runs(self.a)[0]["opened_at"], "2026-10-25T21:38:48+00:00")

    def test_een_afgeronde_checklist_verandert_niet_meer(self):
        repo.open_checklist(self.a, "zone:4", "BTC", "short", "2026-10-25T21:38:48+00:00")
        repo.finish_checklist(self.a, "zone:4", "2026-10-25T21:40:00+00:00")
        repo.open_checklist(self.a, "zone:4", "BTC", "short", "2026-10-25T22:00:00+00:00")
        self.assertFalse(repo.finish_checklist(self.a, "zone:4", "2026-10-25T22:01:00+00:00"))
        run = repo.list_checklist_runs(self.a)[0]
        self.assertEqual((run["opened_at"], run["done_at"]), ("2026-10-25T21:38:48+00:00", "2026-10-25T21:40:00+00:00"))

    def test_afronden_zonder_openen_bewaart_niets(self):
        self.assertFalse(repo.finish_checklist(self.a, "zone:4", "2026-10-25T21:40:00+00:00"))
        self.assertEqual(repo.list_checklist_runs(self.a), [])

    def test_een_ander_ziet_jouw_checklist_nooit_en_kan_hem_niet_afronden(self):
        repo.open_checklist(self.a, "zone:4", "BTC", "short", "2026-10-25T21:38:48+00:00")
        self.assertFalse(repo.finish_checklist(self.b, "zone:4", "2026-10-25T21:40:00+00:00"))
        self.assertEqual(repo.list_checklist_runs(self.b), [])
        self.assertIsNone(repo.list_checklist_runs(self.a)[0]["done_at"])


class PlanLookupTests(DbCase):
    def zone(self, key="1h:bear:a", coin="BTC"):
        return repo.insert_zone_radar_setup({"coin": coin, "direction": "short", "tf": "1h", "zone_key": key, "zone_low": 100.0, "zone_high": 101.0,
                                             "stop_loss": 102.0, "take_profit": 96.0, "rr": 2.0, "atr": 0.5, "target_tf": "4h",
                                             "target_low": 96.0, "target_high": 97.0}, "2026-10-25T18:00:00+00:00")

    def test_een_zone_radar_sleutel_geeft_plan_en_vulling(self):
        zid = self.zone()
        sid = repo.fill_zone_radar_setup(zid, {"coin": "BTC", "direction": "short", "category": "day_trading", "trade_type": "zone_radar",
                                               "price": 100.0, "stop_loss": 102.0, "take_profit": 96.0, "confidence": "x", "technical_confirmed": 1, "hard_gates_ok": 1})
        plans = repo.plans_for_keys([f"zone:{zid}", "zone:999", "iets"])
        self.assertEqual(list(plans), [f"zone:{zid}"])
        p = plans[f"zone:{zid}"]
        self.assertEqual((p["coin"], p["direction"], p["created_at"], p["signal_id"]), ("BTC", "short", "2026-10-25T18:00:00+00:00", sid))
        self.assertIsNotNone(p["zone_at"])                     # bij de zone-radar is in de zone komen de vulling zelf

    def test_een_smc_sleutel_met_het_moment_van_de_zonemelding(self):
        with db.session() as conn:
            cur = conn.execute("""INSERT INTO smc_setups (coin, direction, zone_low, zone_high, structure_level, sweep_price, liquidity_target,
                                  created_at, updated_at) VALUES ('ETH', 'long', 99, 100, 101, 98, 106, '2026-10-25T10:00:00+00:00', '2026-10-25T10:00:00+00:00')""")
            setup_id = cur.lastrowid
        self.assertIsNone(repo.plans_for_keys([f"setup:{setup_id}"])[f"setup:{setup_id}"]["zone_at"])
        repo.mark_smc_zone_alert_sent(setup_id)
        first = repo.plans_for_keys([f"setup:{setup_id}"])[f"setup:{setup_id}"]["zone_at"]
        self.assertIsNotNone(first)
        repo.mark_smc_zone_alert_sent(setup_id)                # een tweede keer houdt het eerste moment
        self.assertEqual(repo.plans_for_keys([f"setup:{setup_id}"])[f"setup:{setup_id}"]["zone_at"], first)

    def test_signalen_op_id_met_de_echte_r_en_zonder_oefentrades(self):
        sid = self.insert_signal(auto_outcome="take_profit")
        practice = self.insert_signal(is_practice=1)
        repo.set_trade_result(sid, 3.4, "2026-10-25T21:00:00+00:00")
        rows = repo.signals_by_ids([sid, practice, 999])
        self.assertEqual(list(rows), [sid])
        self.assertEqual(rows[sid]["r_override"], 3.4)

    def test_plan_momenten_sinds(self):
        self.zone("1h:bear:a")
        self.zone("1h:bear:b", "ETH")
        rows = repo.list_plan_moments("2026-10-25T00:00:00+00:00")
        self.assertEqual(len(rows), 2)
        self.assertEqual(repo.list_plan_moments("2026-10-26T00:00:00+00:00"), [])


class DurationTests(unittest.TestCase):
    def test_duur_alleen_als_beide_tijden_bestaan(self):
        self.assertEqual(logbook.checklist_seconds("2026-10-25T21:38:48+00:00", "2026-10-25T21:40:00+00:00"), 72)
        self.assertIsNone(logbook.checklist_seconds("2026-10-25T21:38:48+00:00", None))
        self.assertIsNone(logbook.checklist_seconds(None, "2026-10-25T21:40:00+00:00"))

    def test_een_afronding_voor_het_openen_is_geen_duur(self):
        self.assertIsNone(logbook.checklist_seconds("2026-10-25T21:40:00+00:00", "2026-10-25T21:38:00+00:00"))

    def test_tekst_van_de_duur(self):
        self.assertEqual(logbook.duration_text(72), "1 min 12 s")
        self.assertEqual(logbook.duration_text(45), "45 s")
        self.assertEqual(logbook.duration_text(120), "2 min")
        self.assertEqual(logbook.duration_text(3725), "1 u 2 min")


if __name__ == "__main__":
    unittest.main()
