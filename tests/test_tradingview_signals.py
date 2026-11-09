"""De sweep-keten van tradingview/hespulse_clean.pine (L?, S?, L+, S+) is een kopie van app/model.py (4.8 tot 4.11). Pine draait hier niet, dus
deze test houdt een Python-versie bij in precies de stappen van de functie f_sig/f_disp (scalars, lussen, geen numpy) en eist dat die bij
dezelfde 1u-pools op willekeurige 15m-candles dezelfde sweep- en displacement-momenten geeft als _Run._step van het model, voor long en short.

Buiten de toets blijven (staat in de kop van het script): de 4u-range (premium en discount), de groepering van gelijke pools en het doel. De ATR
komt uit het model zelf: het script rekent dezelfde Wilder-recursie, maar over de candles die TradingView laadt."""
import random
import types
import unittest

import numpy as np
import pandas as pd

from app import model as M

NEVER = M.NEVER
MAX_AGE = 460          # candles van 15m: een pool is hoogstens 120 candles van 1u oud, en de 480 van f_fresh dekken dat
START = pd.Timestamp("2026-01-05T00:00:00Z")


def walk(seed: int, n: int = 900):
    """Een 15m-reeks met golven, zodat er prikken door eerdere bodems, herstel en breuken in voorkomen."""
    rnd = random.Random(seed)
    price, drift, rows = 100.0, 0.0, []
    for i in range(n):
        if i % 40 == 0:
            drift = rnd.uniform(-0.12, 0.12)
        o = price
        c = o + drift + rnd.gauss(0, 0.28)
        h = max(o, c) + abs(rnd.gauss(0, 0.16))
        l = min(o, c) - abs(rnd.gauss(0, 0.16))
        rows.append([o, h, l, c])
        price = c
    return rows


def frame_of(rows, tf, mirror):
    step = {"15m": 15, "1h": 60, "4h": 240}[tf]
    df = pd.DataFrame(rows, columns=["open", "high", "low", "close"])
    df.insert(0, "timestamp", [START + pd.Timedelta(minutes=step) * i for i in range(len(df))])
    return M._frame(df, tf, mirror)


def pools_for(rows, d, seed):
    """Echte 1u-achtige pools: de laagste low (long) of hoogste high (short) van een blok van 16 candles, bekend vier uur na het blok."""
    out = []
    block = 16
    for b in range(2, len(rows) // block - 2):
        seg = rows[b * block:(b + 1) * block]
        level = min(r[2] for r in seg) if d == 1 else max(r[1] for r in seg)
        known_idx = (b + 1) * block + 16
        out.append((level, known_idx))
    return out


def pine_signals(d, rows, atr, pools):
    """De stappen van f_sig en f_disp. rows: [open, high, low, close] in echte prijzen; pools: (niveau, index vanaf wanneer bekend)."""
    n = len(rows)
    O, H, L, C = ([r[j] for r in rows] for j in range(4))

    def fh(i):
        return H[i] if d == 1 else -L[i]

    def fl(i):
        return L[i] if d == 1 else -H[i]

    def fo(i):
        return O[i] if d == 1 else -O[i]

    def fc(i):
        return C[i] if d == 1 else -C[i]

    def fresh(t, lv, known):
        for o in range(1, min(480, t) + 1):
            if t - o < known:
                break
            if fl(t - o) <= lv:
                return False
        return True

    def disp(j, c, last):
        res = -1
        for m in range(j, c + 1):
            if res < 0 and np.isfinite(atr[m]):
                kk = -1
                q = m - 1
                while q >= max(0, m - 5) and kk < 0:
                    if fc(q) < fo(q):
                        kk = q
                    q -= 1
                if kk >= 0 and fc(m) - fh(kk) >= 1.0 * atr[m]:
                    any_g = any_u = False
                    for i in range(max(kk + 2, 2), m + 2):
                        if i <= last and fh(i - 2) < fl(i):
                            any_g = True
                            filled = False
                            for q2 in range(i + 1, last + 1):
                                if fl(q2) <= fl(i):
                                    filled = True
                            if not filled:
                                any_u = True
                    if any_g:
                        res = 1 if any_u else 0
                    elif m + 1 > last:
                        res = 2
        return 0 if res < 0 else res

    ph, pool_lv, j_bar, x_low, atr_j, top_b, r_bar, c_bar, last_top = 0, None, None, None, None, None, None, None, None
    events = []
    for t in range(n):
        pk = t >= 4
        if pk:
            for q in (1, 2):
                if not fh(t - 2 - q) < fh(t - 2):
                    pk = False
                if not fh(t - 2 + q) <= fh(t - 2):
                    pk = False
        if pk:
            last_top = fh(t - 2)
        if ph == 0 and np.isfinite(atr[t]) and t >= 1:
            best = None
            for level, known in pools:
                m = d * level
                if known <= t < known + MAX_AGE and m < fc(t - 1) and fl(t) <= m and fresh(t, m, known):
                    best = m if best is None else min(best, m)
            if best is not None and fl(t) <= best - 0.1 * atr[t]:
                ph, pool_lv, j_bar, x_low, atr_j, top_b = 1, best, t, fl(t), atr[t], last_top
        if ph == 1:
            x_low = min(x_low, fl(t))
            if pool_lv - x_low > 2.5 * atr_j:
                ph = 0
            elif fc(t) > pool_lv:
                events.append((t, "sweep"))
                if top_b is None:
                    ph = 0
                else:
                    r_bar, ph = t, 2
            elif t >= j_bar + 5:
                ph = 0
        if ph == 2:
            if t > r_bar and fc(t) < x_low:
                ph = 0
            elif fc(t) > top_b:
                c_bar, ph = t, 3
            elif t >= j_bar + 24:
                ph = 0
        if ph == 3:
            res = disp(j_bar, c_bar, t)
            if res == 1:
                events.append((t, "plus"))
                ph = 0
            elif res == 0:
                ph = 0
    return events


def model_events(d, rows, pools):
    """De echte _step van het model op dezelfde pools. Pools zijn in het (gespiegelde) long-frame; de model-pool valt weg bij de eerste aanraking."""
    mirror = d == -1
    f15 = frame_of(rows, "15m", mirror)
    f1 = frame_of(rows[::4][:200], "1h", mirror)
    f4 = frame_of(rows[::16][:80], "4h", mirror)
    run = M._Run("long" if d == 1 else "short", f4, f1, f15, None, None)
    ct = f15.ct
    plist = []
    for level, known in pools:
        lv = d * level
        start = known
        hit = np.flatnonzero(f15.l[start:] <= lv)
        touched = int(ct[start + hit[0]]) if len(hit) else NEVER
        plist.append(M.Pool(lv, START.isoformat(), int(ct[known - 1]), touched, 1))
    run.pools.valid = lambda t_ns, ctx, close: [p for p in plist if p.known <= t_ns < p.known + MAX_AGE * 900 * 10**9 and p.touched > t_ns
                                                and p.level < close]
    ctx = types.SimpleNamespace(L=-1e12, H=1e12, eq=1e12, range_id="x", b=0, s=0, known=0)

    def fresh_active():
        return M._Active(ctx, 0, None, [], {})

    a, events, seen, keep = fresh_active(), [], set(), []
    for t in range(M.WARMUP_15M + 1, f15.n):
        run._step(a, t, ctx)
        T = int(ct[t])
        steps = list(a.steps) + [s for x in a.attempts for s in x["steps"]]
        for s in steps:
            if id(s) not in seen and s["stap"] == "sweep" and s["at"] == T:
                events.append((t, "sweep"))
            seen.add(id(s))
            keep.append(s)             # een vrijgegeven dict zou zijn id aan een nieuwe stap doorgeven
        if a.entry is not None:
            events.append((t, "plus"))
            a = fresh_active()
    return events


class SignalPortTest(unittest.TestCase):
    def test_zelfde_keten_als_het_model(self):
        counts = {"sweep": 0, "plus": 0}
        for seed in range(60):
            rows = walk(seed)
            for d in (1, -1):
                f15 = frame_of(rows, "15m", d == -1)
                atr = f15.atr
                pools = pools_for(rows, d, seed)
                pine = [e for e in pine_signals(d, rows, atr, pools) if e[0] > M.WARMUP_15M]
                with self.subTest(seed=seed, d=d):
                    self.assertEqual(pine, model_events(d, rows, pools))
                for _, kind in pine:
                    counts[kind] += 1
        # Een toets die nooit iets ziet bewijst niets: er moeten sweeps en volledige ketens in de data zitten.
        self.assertGreater(counts["sweep"], 40)
        self.assertGreater(counts["plus"], 5)

    def test_het_script_bevat_de_stappen(self):
        src = open("tradingview/hespulse_clean.pine", encoding="utf-8").read()
        for needed in ("2.5 * atrJ", "0.1 * atr15", "jBar + 5", "jBar + 24", "m - 5", "1.0 * atr15", "480", "xloc = xloc.bar_time",
                       "f_sig(1,", "f_sig(-1,", "display = display.none", "POOL_AGE = 120", "showWeak"):
            self.assertIn(needed, src)


if __name__ == "__main__":
    unittest.main()
