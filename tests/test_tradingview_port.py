"""Het TradingView-script (tradingview/hespulse_structuur.pine) is een regel-voor-regel kopie van app/structure_levels.levels. Pine draait hier
niet, dus deze test houdt een Python-versie bij in precies de stappen van het Pine-script (arrays, lussen, geen numpy) en eist dat die op
willekeurige candles hetzelfde geeft als de echte code van Groot. Verandert levels(), dan faalt deze test en moet het script mee."""
import random
import unittest

from app import structure_levels as sl

WINDOW = 499            # Groot: 500 opgehaald, de vormende candle valt af
FVG_LOOKBACK = 150
EQUAL_ATR = 0.1


def pine_levels(O, H, L, C, k, bias):
    """De stappen van het Pine-script op de laatste WINDOW gesloten candles, oudste eerst. bias: 1 long, -1 short, 0 geen."""
    n = len(C)
    last = n - 1
    out = {"trend": 0, "herstel": False, "lines": {}, "zones": {}}
    if n < 30:
        return out
    # ATR (Wilder 14, zoals replay.lab.add_indicators): de eerste TR is high min low.
    atr = H[0] - L[0]
    for i in range(1, n):
        tr = max(H[i] - L[i], abs(H[i] - C[i - 1]), abs(L[i] - C[i - 1]))
        atr = atr + (tr - atr) / 14
    # Swings: strikt aan de linkerkant, gelijk mag rechts.
    hiF, loF = [False] * n, [False] * n
    for p in range(k, n - k):
        okh, okl = True, True
        for j in range(1, k + 1):
            if not H[p - j] < H[p]:
                okh = False
            if not H[p + j] <= H[p]:
                okh = False
            if not L[p - j] > L[p]:
                okl = False
            if not L[p + j] >= L[p]:
                okl = False
        hiF[p], loF[p] = okh, okl
    # Breuken (model.breaks).
    hP, hI, hB, lP, lI, lB = [], [], [], [], [], []
    bI, bUp, bLvl, bSw, bLab = [], [], [], [], []
    lastUp = 0
    for i in range(n):
        p = i - k
        if p >= 0:
            if hiF[p]:
                hP.append(H[p]); hI.append(p); hB.append(False)
            if loF[p]:
                lP.append(L[p]); lI.append(p); lB.append(False)
        for side in (1, -1):
            P, I, B = (hP, hI, hB) if side == 1 else (lP, lI, lB)
            js = -1
            for j in range(len(P) - 1, -1, -1):
                if not B[j]:
                    js = j
                    break
            if js >= 0 and (C[i] - P[js]) * side > 0:
                for j in range(len(P)):
                    if not B[j] and (C[i] - P[j]) * side > 0:
                        B[j] = True
                up = 1 if side == 1 else -1
                bI.append(i); bUp.append(up); bLvl.append(P[js]); bSw.append(I[js])
                bLab.append(0 if lastUp == 0 else (1 if lastUp == up else 2))
                lastUp = up
    if bI:
        out["trend"] = bUp[-1]
        out["herstel"] = bias != 0 and bUp[-1] != bias
    m = -1
    for j in range(len(bI) - 1, -1, -1):
        if bias == 0 or bUp[j] == bias:
            m = j
            break
    if m >= 0:
        bi, up, sw = bI[m], bUp[m] == 1, bSw[m]
        out["lines"]["msb"] = (bLvl[m], sw, ["MSB", "BOS", "CHoCH"][bLab[m]])
        if up:
            lo_i = sw + 1
            for j in range(sw + 1, bi + 1):
                if L[j] < L[lo_i]:
                    lo_i = j
            hi_i = sw
            for j in range(sw, last + 1):
                if H[j] > H[hi_i]:
                    hi_i = j
        else:
            hi_i = sw + 1
            for j in range(sw + 1, bi + 1):
                if H[j] > H[hi_i]:
                    hi_i = j
            lo_i = sw
            for j in range(sw, last + 1):
                if L[j] < L[lo_i]:
                    lo_i = j
        if bias != 0:
            x = -1
            for j in range(bi + 1, last + 1):
                if (up and C[j] < L[lo_i]) or (not up and C[j] > H[hi_i]):
                    x = j
                    break
            if x >= 0:
                if up:
                    lo_i = x
                    for j in range(x, last + 1):
                        if L[j] < L[lo_i]:
                            lo_i = j
                else:
                    hi_i = x
                    for j in range(x, last + 1):
                        if H[j] > H[hi_i]:
                            hi_i = j
        out["lines"]["rh"] = (H[hi_i], hi_i)
        out["lines"]["rl"] = (L[lo_i], lo_i)
        out["lines"]["eq"] = ((H[hi_i] + L[lo_i]) / 2, min(lo_i, hi_i))
        start = lo_i if up else hi_i
        ob = -1
        for j in range(max(0, start - 3), min(bi, start + 1) + 1):
            if (C[j] < O[j]) == up:
                ob = j
        if ob >= 0:
            broken = False
            for j in range(ob + 1, last + 1):
                if (up and C[j] < L[ob]) or (not up and C[j] > H[ob]):
                    broken = True
            if not broken:
                out["zones"]["ob"] = (L[ob], H[ob], ob)
    # Laatste swing high en low, of EQH/EQL.
    for kind in ("h", "l"):
        F, A = (hiF, H) if kind == "h" else (loF, L)
        p1, p2 = -1, -1
        for p in range(n - 1, -1, -1):
            if F[p]:
                if p1 < 0:
                    p1 = p
                else:
                    p2 = p
                    break
        if p1 < 0:
            continue
        if p2 >= 0 and atr != 0 and abs(A[p1] - A[p2]) <= EQUAL_ATR * atr:
            v = max(A[p1], A[p2]) if kind == "h" else min(A[p1], A[p2])
            out["lines"]["eq" + kind] = (v, p2)
        else:
            out["lines"]["s" + kind] = (A[p1], p1)
    # Dichtste open FVG onder (gap omhoog) en boven (gap omlaag).
    px = C[last]
    bel, abv = None, None
    for i in range(max(2, last - FVG_LOOKBACK), last + 1):
        if H[i - 2] < L[i]:
            lo, hi = H[i - 2], L[i]
            for j in range(i + 1, last + 1):
                hi = min(hi, L[j])
            if hi > lo and hi < px and (bel is None or hi > bel[1]):
                bel = (lo, hi, i - 1)
        if L[i - 2] > H[i]:
            lo, hi = H[i], L[i - 2]
            for j in range(i + 1, last + 1):
                lo = max(lo, H[j])
            if hi > lo and lo > px and (abv is None or lo < abv[0]):
                abv = (lo, hi, i - 1)
    if bel:
        out["zones"]["fvg_onder"] = bel
    if abv:
        out["zones"]["fvg_boven"] = abv
    return out


def walk(seed: int, step: int, n: int = 520):
    rng = random.Random(seed)
    p, rows = 100.0, []
    for i in range(n):
        o = p
        p = max(1.0, p * (1 + rng.gauss(0, 0.012) + (0.004 if (i // 60) % 2 else -0.004)))
        hi = max(o, p) * (1 + abs(rng.gauss(0, 0.004)))
        lo = min(o, p) * (1 - abs(rng.gauss(0, 0.004)))
        rows.append([1_699_920_000 + i * step, round(o, 4), round(hi, 4), round(lo, 4), round(p, 4)])
    return rows


def app_view(rows, tf, bias):
    """structure_levels.levels in dezelfde vorm als pine_levels, met candlenummers binnen het venster in plaats van tijden."""
    lv = sl.levels(rows, tf, rows[-1][0] + sl.SECONDS[tf], {1: "long", -1: "short", 0: None}[bias])
    t0 = rows[0][0]
    idx = lambda t: (t - t0) // sl.SECONDS[tf]
    out = {"trend": {"bullish": 1, "bearish": -1, None: 0}[lv["trend"]], "herstel": lv["herstel"], "lines": {}, "zones": {}}
    for x in lv["lines"]:
        key = {"msb": "msb", "eq50": "eq", "range": "rh" if x["short"] == "RH" else "rl", "eq": "eqh" if x["short"] == "EQH" else "eql",
               "swing": "sh" if x["short"] == "SH" else "sl"}[x["kind"]]
        out["lines"][key] = (x["value"], idx(x["time"]), x["short"]) if key == "msb" else (x["value"], idx(x["time"]))
    for z in lv["zones"]:
        if z["kind"] == "ob":
            out["zones"]["ob"] = (z["low"], z["high"], idx(z["time"]))
        elif z["kind"] == "fvg":
            out["zones"]["fvg_onder" if z["high"] < rows[-1][4] else "fvg_boven"] = (z["low"], z["high"], idx(z["time"]))
    return out


class PortTest(unittest.TestCase):
    def test_zelfde_als_groot_op_willekeurige_candles(self):
        for seed in range(150):
            for tf in ("15m", "1h", "4h", "1d"):
                rows = walk(seed, sl.SECONDS[tf])[-WINDOW:]
                O, H, L, C = ([r[j] for r in rows] for j in (1, 2, 3, 4))
                for bias in (0, 1, -1):
                    with self.subTest(seed=seed, tf=tf, bias=bias):
                        self.assertEqual(pine_levels(O, H, L, C, sl.K[tf], bias), app_view(rows, tf, bias))

    def test_het_script_bevat_de_stappen(self):
        """Tegenvoorbeeld tegen een stil weggevallen stap: de vaste getallen en namen van levels() staan in het script."""
        src = open("tradingview/hespulse_structuur.pine", encoding="utf-8").read()
        for needed in ("WINDOW = 499", "FVG_LOOKBACK = 150", "EQUAL_ATR = 0.1", "/ 14", "CHoCH", "EQH", "EQL", "RH", "RL", "OB"):
            self.assertIn(needed, src)


if __name__ == "__main__":
    unittest.main()
