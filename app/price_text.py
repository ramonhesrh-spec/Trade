"""Prijzen om te lezen: komma als decimaalteken en een aantal decimalen dat bij de prijs past (80,92 voor HYPE, niet 80,9200).
Kopiëren geeft hetzelfde getal met een punt, want dat plak je in een orderveld. web/static/ladder.js heeft dezelfde regel (tests/test_static_js.py).

Meldingsteksten houden chance_steps.fmt: daar staan golden tests op."""
import math

SIG_DIGITS = 3      # onder 0,01 (PEPE) zouden zes decimalen 0,000012 geven: dan minstens drie cijfers die tellen


def decimals(value: float) -> int:
    v = abs(value)
    if v >= 10:
        return 2
    if v >= 1:
        return 3
    if v >= 0.01:
        return 4
    if v == 0:
        return 0
    return max(6, SIG_DIGITS - 1 - math.floor(math.log10(v)))


def plain(value: float) -> str:
    return f"{value:.{decimals(value)}f}"


def nl(value: float) -> str:
    return plain(value).replace(".", ",")
