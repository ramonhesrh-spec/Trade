"""Acceptatietest (aanvulling CEO 2026-11-02): titel, richting, instap/stop/doel, de getekende tradebox, de uitleg en de melding van een
modelkaart komen uit dezelfde opgeslagen planrij. Een short kan nooit een longtitel, een longpush of een omgekeerde box geven (short: doel <
instap < stop; long: stop < instap < doel), ook niet via een bewaarde grafiek. Plus de BTC-context op de kaart."""
import asyncio
import json
import re
from unittest import mock

import pandas as pd

from app import card_chart, config, db, model_card, model_live, push_notify, radar, range_sweep_live as rsl, repo
from tests.hespulse_model import synth as S
from tests.hespulse_model.test_model import TAIL_FROM, base_rows
from tests.test_model_live import BACK, at, five_minutes
from tests.test_samenval import DbCase


def svg_line_y(svg: str, name: str) -> float:
    """De y van de horizontale lijn met dit label (setup_chart.zone_svg: lijn en label per niveau)."""
    m = re.search(r'<line class="sc-line [^"]*" x1="[^"]*" x2="[^"]*" y1="([\d.]+)"[^>]*/><text class="sc-label[^"]*"[^>]*>' + name, svg)
    assert m, name
    return float(m.group(1))


class Case(DbCase):
    mirror = False

    def setUp(self):
        super().setUp()
        rows = base_rows(after=0) + BACK
        rows = S.mirror_rows(rows) if self.mirror else rows
        fr = S.frames(rows)
        fr["5m"] = five_minutes(fr["15m"])
        self.fr, self.sent = fr, []
        for p in (mock.patch.object(config, "HESPULSE_MODEL_ENABLED", True), mock.patch.object(config, "MODEL_ONLY_ALERTS", True),
                  mock.patch.object(repo, "list_coins", return_value=[{"symbol": "SOL"}]),
                  mock.patch.object(rsl, "fetch_bars", lambda coin, tf, limit: self.fr[tf]),
                  mock.patch.object(push_notify, "is_quiet_now", return_value=False),
                  mock.patch.object(push_notify, "send_push", self.fake_push)):
            p.start()
            self.addCleanup(p.stop)
        for t in (at(TAIL_FROM - 5), at(TAIL_FROM + 4)):
            asyncio.run(model_live.run(t.to_pydatetime()))
        (self.row,) = [r for r in repo.list_model_scenarios() if r["status"] == "afgerond"]

    async def fake_push(self, user_id, title, body, url, silent=False, tag=None, badge=None):
        self.sent.append({"title": title, "body": body, "url": url, "silent": silent})

    def check(self, direction: str):
        row = self.row
        self.assertEqual(row["direction"], direction)
        stop, limit, take = row["stop_loss"], row["limit_price"], row["take_profit"]
        self.assertTrue(stop < limit < take if direction == "long" else take < limit < stop, (stop, limit, take))
        self.assertTrue(model_card.plan_ok(row))
        # De melding: richting en getallen uit dezelfde rij.
        (push,) = [s for s in self.sent if not s["silent"]]
        arrow = "▲" if direction == "long" else "▼"
        self.assertTrue(push["title"].startswith(f"{arrow} SOL {direction} "), push["title"])
        for v in (limit, stop, take):
            self.assertIn(push_notify.fmt_price(v), push["body"])
        # De kaart op Kansen (radar.setup_card) en het blad.
        card = radar.setup_card(model_card.radar_setup(row), limit)
        self.assertEqual(card["direction"], direction)
        self.assertEqual((card["plan"].stop, card["plan"].limit, card["plan"].take), (stop, limit, take))
        # De getekende box: op het scherm staat het doel boven (long) of onder (short) de instap en de stop aan de andere kant.
        candles = [[int(ts.timestamp()), o, h, low, c] for ts, o, h, low, c in self.fr["15m"][["timestamp", "open", "high", "low", "close"]].itertuples(index=False)]
        svg = card_chart.model_svg(row, candles, limit)
        y_stop, y_limit, y_take = svg_line_y(svg, "Stop"), svg_line_y(svg, "Limiet"), svg_line_y(svg, "Doel")
        if direction == "long":
            self.assertTrue(y_take < y_limit < y_stop)
        else:
            self.assertTrue(y_stop < y_limit < y_take)
        # Het signaal bij de vulling en de uitleg.
        sig = model_card.signal_row(row)
        self.assertEqual((sig["direction"], sig["price"], sig["stop_loss"], sig["take_profit"]), (direction, limit, stop, take))
        self.assertIn(direction, model_card.context_lines(row)[2])

    def test_btc_context_is_on_the_card(self):
        ctx = model_card.btc_of(self.row)
        self.assertIn("a", ctx)
        self.assertIn("b", ctx)
        self.assertAlmostEqual(ctx["b"]["corr_96"], 1.0)            # in deze test is BTC dezelfde reeks
        lines = model_card.context_lines(self.row)
        self.assertTrue(lines[0].startswith("Context: SOL 4u "))
        self.assertIn("correlatie 1,00 (24u)", lines[0])
        self.assertTrue(any(line.startswith("Status: entry beschikbaar") for line in lines))


class LongTest(Case):
    def test_long_everything_from_one_row(self):
        self.check("long")


class ShortTest(Case):
    mirror = True

    def test_short_never_looks_like_a_long(self):
        self.check("short")


class GuardTest(DbCase):
    def test_a_reversed_plan_is_never_ok(self):
        self.assertFalse(model_card.plan_ok({"direction": "short", "stop_loss": 99.0, "limit_price": 100.0, "take_profit": 104.0}))
        self.assertFalse(model_card.plan_ok({"direction": "long", "stop_loss": 101.0, "limit_price": 100.0, "take_profit": 104.0}))
        self.assertTrue(model_card.plan_ok({"direction": "short", "stop_loss": 101.0, "limit_price": 100.0, "take_profit": 96.0}))

    def test_card_chart_is_never_cached(self):
        from tests.test_web_model import ModelChart  # noqa: F401  (de route-test daar eist 200; hier de kop)
        src = open("web/main.py", encoding="utf-8").read()
        self.assertIn('return HTMLResponse(svg, headers={"Cache-Control": "no-store"})', src)
