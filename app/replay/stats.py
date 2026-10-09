"""Statistiek voor het lab. Trades in dezelfde week hangen samen (alle coins volgen BTC), dus de marge komt uit het herbemonsteren van weken, niet van trades."""
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
