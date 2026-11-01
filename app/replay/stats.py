"""Statistiek voor het lab. Trades in dezelfde week hangen samen (alle coins volgen BTC), dus de marge komt uit het herbemonsteren van weken, niet van trades."""
import math
import random
from collections import defaultdict


def week_key(ts) -> str:
    iso = ts.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


def cluster_bootstrap_mean(values: list[float], clusters: list, seed: int = 7, n_boot: int = 2000) -> tuple[float, float]:
    """95%-interval van het gemiddelde per trade, herbemonsterd per cluster; vaste seed zodat twee runs hetzelfde zeggen."""
    if not values:
        return 0.0, 0.0
    groups: dict = defaultdict(list)
    for v, c in zip(values, clusters):
        groups[c].append(v)
    keys = list(groups)
    if len(keys) < 2:
        m = sum(values) / len(values)
        return m, m
    rng = random.Random(seed)
    means = []
    for _ in range(n_boot):
        total, count = 0.0, 0
        for _ in keys:
            g = groups[rng.choice(keys)]
            total += sum(g)
            count += len(g)
        means.append(total / count)
    means.sort()
    return means[int(0.025 * n_boot)], means[int(0.975 * n_boot) - 1]


def cluster_t(values: list[float], clusters: list) -> float:
    """t van het gemiddelde met een standaardfout die samenhang binnen een cluster (week) toelaat: se = sqrt(som_c (som_i in c (x_i - m))^2) / N.
    De gewone t telt 8 trades in één BTC-week als 8 metingen; dit telt ze als ongeveer één."""
    n = len(values)
    if n < 2:
        return 0.0
    m = sum(values) / n
    groups: dict = defaultdict(float)
    for v, c in zip(values, clusters):
        groups[c] += v - m
    se = math.sqrt(sum(g * g for g in groups.values())) / n
    return m / se if se > 0 else 0.0


def cluster_bootstrap_diff(a: list[float], a_clusters: list, b: list[float], b_clusters: list, seed: int = 7,
                           n_boot: int = 2000) -> tuple[float, float]:
    """95%-interval van gemiddelde(a) min gemiddelde(b), herbemonsterd per gedeelde cluster (week): een week die terugkomt, brengt zijn trades van
    beide reeksen mee. Voor de schaduwvarianten (app/shadow.py): variant en hoofdversie lopen in dezelfde weken, dus ze delen de samenhang."""
    if not a or not b:
        return 0.0, 0.0
    groups: dict = defaultdict(lambda: [0.0, 0, 0.0, 0])
    for v, c in zip(a, a_clusters):
        groups[c][0] += v
        groups[c][1] += 1
    for v, c in zip(b, b_clusters):
        groups[c][2] += v
        groups[c][3] += 1
    keys = list(groups)
    point = sum(a) / len(a) - sum(b) / len(b)
    if len(keys) < 2:
        return point, point
    rng = random.Random(seed)
    diffs = []
    for _ in range(n_boot):
        sa = na = sb = nb = 0
        for _ in keys:
            g = groups[rng.choice(keys)]
            sa, na, sb, nb = sa + g[0], na + g[1], sb + g[2], nb + g[3]
        if na and nb:
            diffs.append(sa / na - sb / nb)
    if not diffs:
        return point, point
    diffs.sort()
    n = len(diffs)
    return diffs[int(0.025 * n)], diffs[max(int(0.975 * n) - 1, 0)]
