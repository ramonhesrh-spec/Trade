"""De live motor van het HesPulse-model (app/model_live.py) tegen een kunstmatige markt (tests/hespulse_model/synth.py): moment A zonder push,
moment B één luide melding binnen het dagbudget, de vulling stil met signaal en journaal, geen tweede melding in een volgende cyclus, en de
oude soorten zonder enige melding als MODEL_ONLY_ALERTS aan staat."""
import asyncio
from unittest import mock

import pandas as pd

from app import config, db, model, model_live, push_notify, push_policy, range_sweep_live as rsl, repo
from tests.hespulse_model import synth as S
from tests.hespulse_model.test_model import TAIL_FROM, base_rows
from tests.test_samenval import DbCase

BACK = S.path([(8, 108.5)], start_price=110.3)          # na de shift terug door de limiet 108,8: de vulling


def five_minutes(b15: pd.DataFrame) -> pd.DataFrame:
    """Elke 15m-candle als drie 5m-candles met dezelfde prijzen: genoeg om een aanraking van de limiet te zien."""
    parts = []
    for k in range(3):
        parts.append(b15.assign(timestamp=b15["timestamp"] + pd.Timedelta(minutes=5 * k)))
    return pd.concat(parts).sort_values("timestamp").reset_index(drop=True)


def at(i15: int, minutes: int = 1) -> pd.Timestamp:
    """Een paar minuten na het sluiten van 15m-candle i15: zo ziet de snelcyclus hem."""
    return S.START + pd.Timedelta(minutes=15) * (i15 + 1) + pd.Timedelta(minutes=minutes)


class Case(DbCase):
    rows = None

    def setUp(self):
        super().setUp()
        self.b = repo.create_user("b", "x", 0, 1)
        self.uid = repo.get_user_by_username("a")["id"]
        fr = S.frames(self.rows or base_rows(after=0) + BACK)
        fr["5m"] = five_minutes(fr["15m"])
        self.fr = fr
        self.sent = []
        for p in (mock.patch.object(config, "HESPULSE_MODEL_ENABLED", True), mock.patch.object(config, "MODEL_ONLY_ALERTS", True),
                  mock.patch.object(repo, "list_coins", return_value=[{"symbol": "BTC"}]),
                  mock.patch.object(rsl, "fetch_bars", lambda coin, tf, limit: self.fr[tf]),
                  mock.patch.object(push_notify, "is_quiet_now", return_value=False),
                  mock.patch.object(push_notify, "send_push", self.fake_push)):
            p.start()
            self.addCleanup(p.stop)

    async def fake_push(self, user_id, title, body, url, silent=False, tag=None, badge=None):
        self.sent.append({"user": user_id, "title": title, "body": body, "url": url, "silent": silent})

    def cycle(self, now: pd.Timestamp):
        async def go():
            # Binnen de lus, zoals scan_smc_fast: buiten asyncio.run zou de bundel open blijven voor de volgende test.
            push_notify.open_bundle()
            await model_live.run(now.to_pydatetime())
            await push_notify.close_bundle()
        asyncio.run(go())

    def notes(self, uid=None):
        with db.session() as conn:
            return [dict(r) for r in conn.execute("SELECT title, body, url FROM notifications WHERE user_id = ? ORDER BY id", (uid or self.uid,))]

    def scenario(self):
        (row,) = repo.list_model_scenarios()
        return row


class MomentTest(Case):
    def test_scenario_discovered_is_only_in_the_app(self):
        self.cycle(at(TAIL_FROM - 5))
        row = self.scenario()
        self.assertEqual(row["status"], "wacht_sweep")
        self.assertEqual(row["detected_at"], at(TAIL_FROM - 5).isoformat())
        self.assertLess(row["discovered_at"], row["detected_at"])
        self.assertEqual(self.sent, [])
        self.assertEqual(self.notes(), [])
        (v1,) = repo.list_model_v1()
        self.assertEqual(v1["state"], "wacht")

    def test_entry_available_is_one_loud_push_per_user_and_only_once(self):
        self.cycle(at(TAIL_FROM - 5))
        self.cycle(at(TAIL_FROM + 4))
        row = self.scenario()
        self.assertEqual((row["status"], row["entry_state"], row["alert_sent"]), ("afgerond", "wacht", 1))
        self.assertEqual(row["entry_at"], S.at(self.fr, TAIL_FROM + 4).isoformat())
        self.assertEqual(row["entry_detected_at"], at(TAIL_FROM + 4).isoformat())
        self.assertEqual(row["vulbaar"], 1)
        loud = [s for s in self.sent if not s["silent"]]
        self.assertEqual(sorted(s["user"] for s in loud), sorted([self.uid, self.b]))      # iedereen ziet het model
        self.assertIn("HesPulse · entry", loud[0]["title"])
        self.assertEqual(loud[0]["url"], f"/smc#radar-model-{row['id']}")
        self.assertEqual(push_policy.used(repo.list_recent_pushes(self.uid, "2000-01-01")), 1)
        self.cycle(at(TAIL_FROM + 5))
        self.assertEqual(len([s for s in self.sent if not s["silent"]]), 2)

    def test_fill_is_silent_signal_with_journal(self):
        self.cycle(at(TAIL_FROM - 5))
        self.cycle(at(TAIL_FROM + 4))
        self.sent.clear()
        self.cycle(at(TAIL_FROM + 12))
        row = self.scenario()
        self.assertEqual(row["entry_state"], "gevuld")
        sig = repo.get_signal(row["signal_id"])
        self.assertEqual((sig["trade_type"], sig["price"], sig["take_profit"]), ("hespulse_model", row["limit_price"], row["take_profit"]))
        with db.session() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM journal_entries WHERE signal_id = ?", (sig["id"],)).fetchone()[0], 2)
            self.assertIsNone(conn.execute("SELECT 1 FROM signal_chain WHERE signal_id = ?", (sig["id"],)).fetchone())
        self.assertTrue(self.sent and all(s["silent"] for s in self.sent))
        self.assertTrue(any("gevuld" in n["title"] for n in self.notes()))

    def test_entry_above_the_daily_budget_is_silent_and_on_the_page(self):
        now = pd.Timestamp.now(tz="UTC").isoformat()          # het budget telt de laatste 24 uur op de klok, niet de candletijd
        for k in range(push_policy.DEFAULT_BUDGET):
            repo.record_push(self.uid, f"C{k}", "long", now)
        self.cycle(at(TAIL_FROM - 5))
        self.cycle(at(TAIL_FROM + 4))
        mine = [s for s in self.sent if s["user"] == self.uid]
        self.assertTrue(mine and all(s["silent"] for s in mine))
        self.assertTrue(any("Dagbudget" in n["body"] for n in self.notes()))

    def test_an_entry_that_expired_before_the_engine_saw_it_never_appears(self):
        self.cycle(at(TAIL_FROM + 4 + model.ENTRY_BARS + 2))
        self.assertTrue(all(r["status"] != "afgerond" for r in repo.list_model_scenarios()))
        self.assertEqual(self.sent, [])

    def test_engine_off_writes_its_heartbeat_and_nothing_else(self):
        with mock.patch.object(config, "HESPULSE_MODEL_ENABLED", False):
            self.cycle(at(TAIL_FROM + 4))
        self.assertEqual(repo.list_model_scenarios(), [])
        self.assertEqual(repo.get_beat("hespulse_model")["detail"], "uit")


class NotFillableTest(Case):
    rows = base_rows(after=0) + [[110.3, 110.35, 108.0, 108.2]] + S.path([(8, 108.0)], start_price=108.2)

    def test_price_already_through_the_limit_gives_no_push(self):
        self.cycle(at(TAIL_FROM - 5))
        self.cycle(at(TAIL_FROM + 5))
        row = self.scenario()
        self.assertEqual((row["status"], row["entry_state"], row["vulbaar"]), ("afgerond", "niet_vulbaar", 0))
        self.assertEqual(self.sent, [])


class V1Test(Case):
    def test_v1_is_measured_silently(self):
        self.cycle(at(TAIL_FROM - 5))
        self.cycle(at(TAIL_FROM + 12))
        self.cycle(at(TAIL_FROM + 13))          # track loopt vóór scan: de cyclus na het afronden ziet dat het scenario klaar is
        (v1,) = repo.list_model_v1()
        # De vroege limiet op de pool (104,95) vulde niet; het scenario rondde af met de entry, dus V1 vervalt op dat moment.
        self.assertEqual(v1["state"], "vervallen")
        with db.session() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM signals WHERE trade_type != 'hespulse_model'").fetchone()[0], 0)


class EndReasonTest(DbCase):
    def test_every_model_end_state_has_a_plain_reason(self):
        from app import end_reason
        for state in ("context_weg", "geen_pool") + model.ENTRY_ENDS:
            text = end_reason.text("hespulse_model", state)
            self.assertNotEqual(text, "Niet meer actief.", state)
            self.assertTrue(text.endswith("."))
        self.assertEqual(end_reason.text("hespulse_model", "vervallen"), "Na 6 uur niet gevuld.")


class OutcomeFromFillTest(Case):
    """Preregistratie §4.14: de uitkomst van H telt vanaf de vulcandle, niet vanaf het opslaan van het signaal, en sluit na 7 dagen ('tijd').
    Eerder deed level_check dit vanaf signals.created_at en liet het na een dag vervallen."""

    def filled(self):
        self.cycle(at(TAIL_FROM - 5))
        self.cycle(at(TAIL_FROM + 4))
        self.cycle(at(TAIL_FROM + 12))
        row = self.scenario()
        self.assertEqual(row["entry_state"], "gevuld")
        return row, pd.Timestamp(row["filled_at"])

    def extend(self, filled_at, candles):
        """Vervangt alles na de vulcandle door eigen 5m-candles (o, h, l, c)."""
        b5 = self.fr["5m"][self.fr["5m"]["timestamp"] <= filled_at]
        ts = [filled_at + pd.Timedelta(minutes=5) * (k + 1) for k in range(len(candles))]
        extra = pd.DataFrame([[t, *c, 1.0] for t, c in zip(ts, candles)], columns=["timestamp", "open", "high", "low", "close", "volume"])
        self.fr["5m"] = pd.concat([b5, extra]).reset_index(drop=True)
        return ts

    def test_stop_in_de_eerste_candle_na_de_vulling_telt_ook_als_het_doel_later_komt(self):
        row, filled_at = self.filled()
        e, sl, tp = row["limit_price"], row["stop_loss"], row["take_profit"]
        mid = (e + tp) / 2
        ts = self.extend(filled_at, [[e, e + 0.01, sl - 0.01, e]] + [[e, mid, e, mid]] * 3 + [[mid, tp + 0.01, mid, tp]])
        self.cycle(ts[-1] + pd.Timedelta(minutes=6))
        sig = repo.get_signal(row["signal_id"])
        self.assertEqual((sig["auto_outcome"], pd.Timestamp(sig["auto_outcome_at"])), ("stop_loss", ts[0]))

    def test_tegenvoorbeeld_zonder_stop_telt_het_doel(self):
        row, filled_at = self.filled()
        e, sl, tp = row["limit_price"], row["stop_loss"], row["take_profit"]
        ts = self.extend(filled_at, [[e, e + 0.01, e - (e - sl) / 2, e]] + [[e, tp + 0.01, e, tp]])
        self.cycle(ts[-1] + pd.Timedelta(minutes=6))
        self.assertEqual(repo.get_signal(row["signal_id"])["auto_outcome"], "take_profit")

    def test_doel_op_dag_drie_telt_nog(self):
        row, filled_at = self.filled()
        e, tp = row["limit_price"], row["take_profit"]
        flat = [[e, e + 0.01, e - 0.01, e]] * (3 * 288)
        ts = self.extend(filled_at, flat + [[e, tp + 0.01, e, tp]])
        self.cycle(ts[-1] + pd.Timedelta(minutes=6))
        self.assertEqual(repo.get_signal(row["signal_id"])["auto_outcome"], "take_profit")

    def test_na_zeven_dagen_tijd_met_r_apart_en_niet_in_de_hoofd_r(self):
        from app import track_record
        row, filled_at = self.filled()
        e, sl = row["limit_price"], row["stop_loss"]
        up = e + (e - sl) * 0.5
        ts = self.extend(filled_at, [[up, up + 0.01, up - 0.01, up]] * (7 * 288 + 2))
        self.cycle(ts[-1] + pd.Timedelta(minutes=6))
        sig = repo.get_signal(row["signal_id"])
        self.assertEqual(sig["auto_outcome"], "tijd")
        self.assertEqual(pd.Timestamp(sig["auto_outcome_at"]), filled_at + model.TIME_LIMIT)
        with db.session() as conn:
            r = conn.execute("SELECT r_value FROM trade_results WHERE signal_id = ?", (sig["id"],)).fetchone()[0]
        self.assertAlmostEqual(r, 0.5)
        self.assertIsNone(track_record.signal_r({**sig, "r_override": r}))

    def test_level_check_laat_de_uitkomst_van_het_model_met_rust(self):
        from app import level_check
        row, filled_at = self.filled()
        with mock.patch.object(level_check, "_fetch_since") as fetch:
            asyncio.run(level_check.check_signal_outcomes())
        fetch.assert_not_called()


class BtcGateTest(Case):
    """Besluit CEO 2026-11-02: een model-entry tegen de BTC-richting op 4u wordt niet gemeld; stil gevolgd met dezelfde regels."""

    def run_with_btc(self, word, gate=True):
        from app import btc_context
        meas = {"btc_4h": word, "corr_96": None, "corr_672": None, "rel_24h": None}
        with mock.patch.object(btc_context, "measure", return_value=meas), mock.patch.object(config, "MODEL_BTC_GATE", gate):
            self.cycle(at(TAIL_FROM - 5))
            self.cycle(at(TAIL_FROM + 4))
            self.cycle(at(TAIL_FROM + 12))
        return self.scenario()

    def test_long_tegen_bearish_btc_geeft_geen_melding_en_wordt_stil_gevolgd(self):
        row = self.run_with_btc("bearish")
        self.assertEqual(row["entry_state"], "btc_tegen")
        self.assertEqual([s for s in self.sent if not s["silent"]], [])
        self.assertIsNone(row["signal_id"])
        self.assertEqual(row["cf_state"], "gevuld")          # dezelfde vulling als H zonder poort (test_fill_is_silent_signal_with_journal)
        with db.session() as conn:
            self.assertEqual(conn.execute("SELECT COUNT(*) FROM signals").fetchone()[0], 0)

    def test_tegenvoorbeeld_bullish_of_onbekend_btc_houdt_niets_tegen(self):
        for word in ("bullish", "onbekend"):
            with self.subTest(word):
                with db.session() as conn:
                    conn.execute("DELETE FROM model_v1"); conn.execute("DELETE FROM model_scenarios")
                self.sent.clear()
                row = self.run_with_btc(word)
                self.assertEqual(row["entry_state"], "gevuld")
                self.assertTrue(any(not s["silent"] for s in self.sent))

    def test_poort_uit_meldt_zoals_eerst(self):
        row = self.run_with_btc("bearish", gate=False)
        self.assertEqual(row["entry_state"], "gevuld")

    def test_de_reden_staat_in_gewone_taal(self):
        from app import end_reason
        self.assertIn("BTC", end_reason.text("hespulse_model", "btc_tegen"))
