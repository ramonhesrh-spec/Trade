import unittest
from datetime import date

import numpy as np
import pandas as pd

from app.replay import sessions as ss


def frame(days=30, plant=None, seed=4):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2026-06-01", periods=days * 1440, freq="1min", tz="UTC")       # begint op een maandag
    p = 100 + np.cumsum(rng.normal(0, 0.01, len(idx)))
    df = pd.DataFrame({"timestamp": idx, "open": p, "high": p + 0.02, "low": p - 0.02, "close": p, "volume": 1.0})
    if plant == "orb_up":       # elke werkdag: rustige opening range, daarna een stijging
        for d in range(1, days - 1):
            day = idx[0].normalize() + pd.Timedelta(days=d)
            if day.weekday() >= 5:
                continue
            t0 = ss.session_times(day.date())["ny"][0]
            i = df.index[df["timestamp"] == t0][0]
            df.loc[i:i + 29, ["open", "high", "low", "close"]] = 100.0
            df.loc[i:i + 29, "high"] = 100.2
            df.loc[i:i + 29, "low"] = 99.8
            ramp = 100.0 + np.linspace(0.05, 2.5, 150)
            df.loc[i + 30:i + 179, "close"] = ramp
            df.loc[i + 30:i + 179, "open"] = np.concatenate([[100.0], ramp[:-1]])
            df.loc[i + 30:i + 179, "high"] = ramp + 0.02
            df.loc[i + 30:i + 179, "low"] = np.concatenate([[100.0], ramp[:-1]]) - 0.02
    return df


class SessionsTest(unittest.TestCase):
    def test_session_times_follow_daylight_saving(self):
        summer = ss.session_times(date(2026, 6, 3))
        winter = ss.session_times(date(2026, 1, 14))
        self.assertEqual(summer["ny"][0], pd.Timestamp("2026-06-03 13:30", tz="UTC"))
        self.assertEqual(winter["ny"][0], pd.Timestamp("2026-01-14 14:30", tz="UTC"))
        self.assertEqual(summer["london"][0], pd.Timestamp("2026-06-03 07:00", tz="UTC"))
        self.assertEqual(winter["london"][0], pd.Timestamp("2026-01-14 08:00", tz="UTC"))

    def test_orb_follow_wins_on_planted_breakouts_and_mirror_loses(self):
        f = frame(plant="orb_up")
        t = pd.DataFrame(ss.orb_trades("BTC", f))
        self.assertGreater(len(t), 10)
        follow = t[(t["variant"] == "ORB mee") & (t["rr"] == 1.0)]
        mirror = t[(t["variant"] == "ORB spiegel") & (t["rr"] == 1.0)]
        self.assertGreater(follow["r_net"].mean(), 0.5)
        self.assertLess(mirror["r_net"].mean(), -0.5)

    def test_random_walk_has_no_orb_edge(self):
        t = pd.DataFrame(ss.orb_trades("BTC", frame(days=120)))
        if t.empty:
            return
        rows = ss.summarize(t, t["at"].quantile(0.7))
        self.assertFalse([r for r in rows if r["variant"] == "ORB mee" and ss.passes(r)])

    def test_sweep_of_london_high_is_found_and_faded(self):
        f = frame(days=10)
        day = pd.Timestamp("2026-06-03", tz="UTC")                      # woensdag
        t = ss.session_times(day.date())
        f.loc[(f["timestamp"] >= t["london"][0]) & (f["timestamp"] < t["london"][1]), ["open", "high", "low", "close"]] = 100.0
        f.loc[(f["timestamp"] >= t["london"][0]) & (f["timestamp"] < t["london"][1]), "high"] = 100.5
        f.loc[(f["timestamp"] >= t["london"][0]) & (f["timestamp"] < t["london"][1]), "low"] = 99.9
        i = f.index[f["timestamp"] == t["london"][1] + pd.Timedelta(minutes=20)][0]       # 20 minuten na het einde van London
        f.loc[i:i + 4, ["open", "close"]] = 100.2
        f.loc[i:i + 4, "high"] = 100.2
        f.loc[i + 4, "high"] = 101.0                                      # prik door 100,5, slot terug eronder
        f.loc[i + 4, "close"] = 100.2
        fall = 100.2 - np.linspace(0.05, 2.0, 120)
        f.loc[i + 5:i + 124, "close"] = fall
        f.loc[i + 5:i + 124, "open"] = np.concatenate([[100.2], fall[:-1]])
        f.loc[i + 5:i + 124, "high"] = np.concatenate([[100.2], fall[:-1]]) + 0.02
        f.loc[i + 5:i + 124, "low"] = fall - 0.02
        trades = pd.DataFrame(ss.sweep_trades("BTC", f))
        fade = trades[(trades["variant"] == "SWEEP fade") & (trades["rr"] == 1.0)]
        self.assertGreaterEqual(len(fade), 1)
        self.assertTrue(fade["win"].any())

    def test_amd_days_flags_bullish_sweep_of_asia_low(self):
        f = frame(days=10)
        day = pd.Timestamp("2026-06-03", tz="UTC")
        t = session_times = ss.session_times(day.date())
        asia = (f["timestamp"] >= day) & (f["timestamp"] < day + pd.Timedelta(hours=7))
        f.loc[asia, ["open", "close"]] = 100.0
        f.loc[asia, "high"] = 100.3
        f.loc[asia, "low"] = 99.8
        i = f.index[f["timestamp"] == t["london"][0] + pd.Timedelta(minutes=60)][0]
        f.loc[i:i + 4, ["open", "close", "high", "low"]] = 100.0
        f.loc[i + 4, "low"] = 99.4                                        # prik onder de Azië-laag
        f.loc[i + 4, "close"] = 100.1                                     # en terug erboven
        amd = ss.amd_days("BTC", f)
        row = amd[amd["at"] == t["ny"][0]]
        self.assertEqual(list(row["sweep"]), ["bullish"])

    def test_london_direction_ignores_everything_after_new_york_opens(self):
        f = frame(days=20)
        day = pd.Timestamp("2026-06-03", tz="UTC")
        t = ss.session_times(day.date())
        base = ss.london_to_ny("BTC", f)
        row = base[(base["at"] == t["ny"][0]) & (base["variant"] == "LONDON mee 60m")]["gross_bp"].iloc[0]
        g = f.copy()
        late = g["timestamp"] >= t["ny"][0] + pd.Timedelta(minutes=1)          # na de opening mag de richting van London niet meer veranderen
        g.loc[late & (g["timestamp"] < t["london"][1]), ["open", "high", "low", "close"]] += 50.0
        moved = ss.london_to_ny("BTC", g)
        sign_before = np.sign(f[(f["timestamp"] >= t["london"][0]) & (f["timestamp"] < t["ny"][0])]["close"].iloc[-1] - f[(f["timestamp"] >= t["london"][0]) & (f["timestamp"] < t["ny"][0])]["open"].iloc[0])
        sign_after = np.sign(g[(g["timestamp"] >= t["london"][0]) & (g["timestamp"] < t["ny"][0])]["close"].iloc[-1] - g[(g["timestamp"] >= t["london"][0]) & (g["timestamp"] < t["ny"][0])]["open"].iloc[0])
        self.assertEqual(sign_before, sign_after)
        mee = moved[(moved["at"] == t["ny"][0]) & (moved["variant"] == "LONDON mee 60m")]["gross_bp"].iloc[0]
        tegen = moved[(moved["at"] == t["ny"][0]) & (moved["variant"] == "LONDON tegen 60m")]["gross_bp"].iloc[0]
        self.assertAlmostEqual(mee, -tegen)
        self.assertNotEqual(round(row, 3), round(mee, 3))      # de uitkomst veranderde wel, de voorspelling niet

    def test_trail_exit_lets_winners_run_and_stops_losers(self):
        # long: instap 100, stop 99 (risico 1), meelopende stop op 1 onder het hoogste punt
        highs = np.array([100.5, 101.0, 103.0, 104.0, 104.0]); lows = np.array([99.8, 100.4, 101.8, 103.2, 102.9]); closes = np.array([100.4, 100.9, 102.9, 103.9, 103.0])
        gross, net = ss.trail_exit("long", 100.0, 99.0, 1.0, highs, lows, closes)
        self.assertAlmostEqual(gross, 3.0)                          # stop meegelopen naar 103 en daar geraakt
        self.assertLess(net, gross)
        g2, _ = ss.trail_exit("long", 100.0, 99.0, 1.0, np.array([100.2, 100.1]), np.array([98.9, 99.5]), np.array([99.0, 99.8]))
        self.assertAlmostEqual(g2, -1.0)                            # meteen de beginstop

    def test_orb_trailing_rows_exist_on_planted_trend(self):
        f = frame(plant="orb_up")
        t = pd.DataFrame(ss.orb_trailing("BTC", f))
        self.assertGreater(len(t), 10)
        self.assertGreater(t[t["variant"] == "ORB trail 2xATR"]["r_net"].mean(), 0.5)

    def test_sweep_and_london_and_hours_run(self):
        f = frame(days=40)
        ss.sweep_trades("BTC", f)
        lon = ss.london_to_ny("BTC", f)
        self.assertEqual(set(lon["variant"]), {"LONDON mee 60m", "LONDON tegen 60m", "LONDON mee 120m", "LONDON tegen 120m"})
        hm = ss.hour_map({"BTC": f}, f["timestamp"].iloc[len(f) // 2])
        self.assertEqual(len(hm), 24)


if __name__ == "__main__":
    unittest.main()
