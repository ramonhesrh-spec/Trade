import unittest

from web import main


def render(src: str, **ctx) -> str:
    env = main.templates.env
    return env.from_string('{% import "_macros.html" as m %}' + src).render(**ctx)


class LayoutMacroTests(unittest.TestCase):
    def test_headline_toont_getal_eenheid_en_toon(self):
        html = render('{{ m.headline("Resultaat", "+1,20", "R", delta="+0,40R vandaag", tone="pos") }}')
        self.assertIn('class="hl-num"', html)
        self.assertIn('>+1,20</span><span class="hl-unit">R</span>', html)
        self.assertIn('class="hl-delta pos"', html)

    def test_headline_zet_attributen_op_het_getal(self):
        html = render('{{ m.headline("Koers", "1", attrs={"id": "coin-price", "data-symbol": "BTC"}) }}')
        self.assertIn('id="coin-price"', html)
        self.assertIn('data-symbol="BTC"', html)

    def test_keylines_uitleg_via_popover(self):
        html = render('{{ m.keylines([{"label": "Winrate", "value": "52", "unit": "%", "explain": "Alleen doel en stop."}], "bw") }}')
        self.assertIn('popovertarget="bw-1"', html)
        self.assertIn('id="bw-1" popover', html)
        self.assertIn('class="kl-term"', html)

    def test_utabs_paneeltab_heeft_aria_controls(self):
        html = render('{{ m.utabs([{"key": "a", "label": "Kansen", "href": "#tab-a"}, {"key": "b", "label": "Markt", "href": "/x"}], "a") }}')
        self.assertIn('aria-controls="tab-a"', html)
        self.assertIn('class="ut-tab is-active"', html)
        self.assertEqual(html.count("aria-controls"), 1)

    def test_market_row_live_hooks(self):
        html = render('{{ m.market_row("BTC", "BTC", chip="long", chip_tone="pos", price_coin="BTC", chg_coin="BTC", el="summary") }}')
        self.assertTrue(html.strip().startswith('<summary class="mrow"'))
        self.assertIn('data-vd-price="BTC"', html)
        self.assertIn('data-spark-chg="BTC" data-spark-short', html)

    def test_geen_em_dash_in_nieuwe_macros(self):
        src = (main.BASE_DIR / "templates" / "_macros.html").read_text()
        new = src.split("===== Indeling", 1)[1]
        self.assertNotIn("—", new)
        self.assertNotIn("–", new)
