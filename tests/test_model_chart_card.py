"""De kaartgrafiek van het HesPulse-model zoals een analist hem tekent (card_chart.model_svg): rustige candles, de 4u-range met evenwicht,
de zones van het model als licht vlak met de naam erin, swing, sweep en structuurbreuk als korte lijn met label, limiet, stop en doel met prijs.
Alles uit de opgeslagen planrij (model_card.row_of op een echt scenario uit model.scenarios); de grafiek bepaalt nooit zelf een richting."""
import json
import re
import unittest

import pandas as pd

from app import card_chart, model as M, model_card
from tests.hespulse_model import synth as S
from tests.hespulse_model.test_model import base_rows


def candles(df: pd.DataFrame) -> list[list]:
    return [[int(r.timestamp.timestamp()), r.open, r.high, r.low, r.close] for r in df.itertuples()]


def scenario_row(mirror=False):
    rows = base_rows(after=24)
    rows = S.mirror_rows(rows) if mirror else rows
    fr = S.frames(rows)
    now = fr["15m"]["timestamp"].iloc[-1] + pd.Timedelta(minutes=15)
    direction = "short" if mirror else "long"
    (sc,) = [s for s in M.scenarios(fr, now) if s["direction"] == direction and s["entry"]]
    row = model_card.row_of("SOL", sc)
    return row, fr, now


def view_box(svg: str) -> tuple[float, float]:
    w, h = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg).groups()
    return float(w), float(h)


def texts(svg: str) -> list[dict]:
    """Elke tekst met een geschat vlak: 11px tekst is hoogstens 6,6 breed per teken (mono), 12px 7,2."""
    out = []
    for m in re.finditer(r'<text class="([^"]*)" x="([-\d.]+)" y="([-\d.]+)"(?: text-anchor="(\w+)")?[^>]*>([^<]*)</text>', svg):
        cls, x, y, anchor, t = m.group(1), float(m.group(2)), float(m.group(3)), m.group(4) or "start", m.group(5)
        t = t.replace("&amp;", "&")
        w = len(t) * card_chart.MODEL_CHAR_W
        x0 = x if anchor == "start" else x - w if anchor == "end" else x - w / 2
        out.append({"cls": cls, "text": t, "box": (x0, y - 10, x0 + w, y + 2)})
    return out


def label_y(svg: str, name: str) -> float:
    """De y van de horizontale lijn bij dit label rechts (lijn en label per niveau)."""
    m = re.search(r'<line class="[^"]*" x1="[^"]*" x2="[^"]*" y1="([\d.]+)"[^>]*/><text class="[^"]*"[^>]*>' + re.escape(name), svg)
    assert m, name
    return float(m.group(1))


class Base(unittest.TestCase):
    mirror = False

    def setUp(self):
        self.row, self.fr, self.now = scenario_row(self.mirror)
        self.c1 = candles(self.fr["1h"])
        self.svg = card_chart.model_svg(self.row, self.c1, None)

    def check_inside_and_no_overlap(self, svg):
        W, H = view_box(svg)
        for t in texts(svg):
            x0, y0, x1, y1 = t["box"]
            self.assertTrue(0 <= x0 and x1 <= W and 0 <= y0 and y1 <= H, (t["text"], t["box"], W, H))
        for m in re.finditer(r'<(?:line|rect|circle) [^>]*>', svg):
            for k, v in re.findall(r' (x|x1|x2|cx)="([-\d.]+)"', m.group(0)):
                self.assertTrue(0 <= float(v) <= W, m.group(0))
            for k, v in re.findall(r' (y|y1|y2|cy)="([-\d.]+)"', m.group(0)):
                self.assertTrue(0 <= float(v) <= H, m.group(0))
        boxes = texts(svg)
        for i, a in enumerate(boxes):
            for b in boxes[i + 1:]:
                A, B = a["box"], b["box"]
                hit = A[0] < B[2] and B[0] < A[2] and A[1] < B[3] and B[1] < A[3]
                self.assertFalse(hit, (a["text"], b["text"], A, B))


class LongChart(Base):
    def test_labels_and_zones(self):
        svg = self.svg
        for name in ("4u range high", "4u range low", "evenwicht", "15m FVG", "1u swing low", "sweep", "Limiet", "Stop", "Doel"):
            self.assertIn(f">{name}", svg, name)
        self.assertIn(">15m CHoCH<", svg) if self.row["shift_label"] == "CHOCH" else self.assertRegex(svg, r">15m (BOS|MSB)<")
        self.assertEqual(svg.count('class="mc-zone"'), 1)                 # geen overlap met het OB: alleen de gap
        self.assertEqual((svg.count('class="mc-pos-risk"'), svg.count('class="mc-pos-win"')), (1, 1))   # het positievak van A
        self.assertIn(">SOL · 1u · long<", svg)
        self.assertNotIn("Nu ", svg)

    def test_direction_from_the_row(self):
        y_stop, y_limit, y_take = label_y(self.svg, "Stop"), label_y(self.svg, "Limiet"), label_y(self.svg, "Doel")
        self.assertTrue(y_take < y_limit < y_stop, (y_take, y_limit, y_stop))
        self.assertLess(label_y(self.svg, "4u range high"), label_y(self.svg, "evenwicht"))

    def test_everything_inside_the_view_box_without_overlap(self):
        self.check_inside_and_no_overlap(self.svg)

    def test_close_levels_are_spread_like_the_ladder(self):
        """Stop vlak bij de rand van de range: de lijnen blijven op hun prijs, de labels schuiven uit elkaar."""
        row = {**self.row, "stop_loss": self.row["range_low"] * 1.0002}
        svg = card_chart.model_svg(row, self.c1, None)
        self.check_inside_and_no_overlap(svg)

    def test_ob_overlap_draws_both_and_a_poc_target_says_dag_poc(self):
        d = json.loads(self.row["steps"])
        e = d["entry"]
        e.update(ob_overlap=True)
        row = {**self.row, "steps": json.dumps(d), "ob_overlap": 1, "target_kind": "poc", "target_text": "Dag-POC 12 okt"}
        svg = card_chart.model_svg(row, self.c1, None)
        self.assertEqual(svg.count('class="mc-zone"'), 2)
        self.assertIn(">15m OB<", svg)
        self.assertIn(">dag-POC<", svg)
        self.check_inside_and_no_overlap(svg)

    def test_equal_lows_say_eql(self):
        d = json.loads(self.row["steps"])
        for s in d["steps"]:
            if s["stap"] == "sweep":
                s["pool_n"] = 2
        svg = card_chart.model_svg({**self.row, "steps": json.dumps(d)}, self.c1, None)
        self.assertIn(">EQL<", svg)
        self.assertNotIn(">1u swing low<", svg)

    def test_moment_a_has_range_and_pool_but_no_order(self):
        row = {k: v for k, v in self.row.items() if k not in ("limit_price", "stop_loss", "take_profit", "zone_low", "zone_high")}
        d = json.loads(row["steps"])
        d["steps"] = [s for s in d["steps"] if s["stap"] == "ontdekt"]
        d["entry"] = None
        row.update(status="wacht_sweep", steps=json.dumps(d))
        svg = card_chart.model_svg(row, self.c1, None)
        for name in ("4u range high", "4u range low", "evenwicht", "1u swing low"):
            self.assertIn(f">{name}", svg)
        for name in ("Limiet", "Stop", "Doel", "15m FVG"):
            self.assertNotIn(f">{name}", svg)
        self.assertNotIn("mc-pos-", svg)                                   # geen plan, dus geen positievak
        self.check_inside_and_no_overlap(svg)
        # CEO 2026-11-03: het positievak komt pas als het plan bekend is; hier een klaar B-plan van de route.
        plan = {"limit": self.row["limit_price"], "stop": self.row["stop_loss"], "take": self.row["take_profit"],
                "known_at": json.loads(self.row["steps"])["entry"]["known_at"] if json.loads(self.row["steps"]).get("entry") else None}
        with_plan = card_chart.model_svg({**row, "pos_plan": plan}, self.c1, None)
        self.assertIn('class="mc-pos-risk"', with_plan)
        self.assertIn('class="mc-pos-win"', with_plan)
        self.check_inside_and_no_overlap(with_plan)

    def test_big_view_is_the_same_drawing_larger(self):
        big = card_chart.model_svg(self.row, self.c1, None, big=True)
        self.assertGreater(view_box(big)[1], view_box(self.svg)[1])
        self.assertIn(">4u range high", big)
        self.check_inside_and_no_overlap(big)

    def test_old_rows_without_pool_point_still_draw(self):
        d = json.loads(self.row["steps"])
        for s in d["steps"]:
            s.pop("pool_at", None)
            s.pop("pool_n", None)
        d.pop("entry")
        svg = card_chart.model_svg({**self.row, "steps": json.dumps(d)}, self.c1, None)
        self.assertIn(">1u swing low<", svg)
        self.assertIn(">15m FVG<", svg)
        self.check_inside_and_no_overlap(svg)


class ShortChart(Base):
    mirror = True

    def test_labels(self):
        for name in ("4u range high", "4u range low", "evenwicht", "15m FVG", "1u swing high", "sweep", "Limiet", "Stop", "Doel"):
            self.assertIn(f">{name}", self.svg, name)
        self.assertIn(">SOL · 1u · short<", self.svg)

    def test_short_target_below_entry_below_stop(self):
        y_stop, y_limit, y_take = label_y(self.svg, "Stop"), label_y(self.svg, "Limiet"), label_y(self.svg, "Doel")
        self.assertTrue(y_stop < y_limit < y_take, (y_stop, y_limit, y_take))
        self.assertTrue(self.row["take_profit"] < self.row["limit_price"] < self.row["stop_loss"])

    def test_everything_inside_the_view_box_without_overlap(self):
        self.check_inside_and_no_overlap(self.svg)


class TimeframeChoice(unittest.TestCase):
    """De range (vanaf zijn swing) en de entry moeten samen in beeld: het kleinste tijdframe waarop dat in MODEL_MAX_BARS past."""

    def row(self, days):
        now = pd.Timestamp("2026-11-02T12:00:00Z")
        return {"steps": json.dumps({"swing_at": (now - pd.Timedelta(days=days)).isoformat()})}, now

    def test_choice(self):
        for days, tf in ((0.5, "15m"), (3, "1h"), (8, "4h")):
            row, now = self.row(days)
            self.assertEqual(card_chart.model_tf(row, now), tf, days)


if __name__ == "__main__":
    unittest.main()


class EntryLineStart(unittest.TestCase):
    """Een instappunt op "Groot" begint op het moment dat de app hem zag, niet links van de grafiek (CEO 2026-11-03, ONDO V1)."""

    def setUp(self):
        self.row, _, _ = scenario_row()

    def alt(self, row, point):
        (m,) = [m for m in card_chart.model_marks(row, [point]) if m["kind"] == "alt"]
        return m

    def test_line_starts_at_the_later_of_rule_moment_and_storing(self):
        row = {**self.row, "detected_at": "2026-11-02T12:30:39+00:00"}
        m = self.alt(row, {"code": "V1", "limit": 0.4063, "known_at": "2026-11-02T08:00:00+00:00"})
        self.assertEqual(m["time"], int(pd.Timestamp("2026-11-02T12:30:39Z").timestamp()))

    def test_counterexample_rule_moment_after_storing_wins(self):
        row = {**self.row, "detected_at": "2026-11-02T08:00:00+00:00"}
        m = self.alt(row, {"code": "B", "limit": 0.4016, "known_at": "2026-11-02T09:15:00+00:00"})
        self.assertEqual(m["time"], int(pd.Timestamp("2026-11-02T09:15:00Z").timestamp()))

    def test_without_any_moment_the_line_has_no_start(self):
        row = {**self.row, "detected_at": None}
        self.assertIsNone(self.alt(row, {"code": "P", "limit": 1.0})["time"])
