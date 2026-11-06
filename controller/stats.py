"""Deterministic statistics. No randomness anywhere: the same counts always give the same decision."""
from __future__ import annotations

import math


def norm_sf(z: float) -> float:
    """P(Z > z) for standard normal."""
    return 0.5 * math.erfc(z / math.sqrt(2))


def two_prop_z(s1, n1, s2, n2) -> float:
    """z for (p1 - p2) using pooled variance. Positive = arm 1 better."""
    if n1 == 0 or n2 == 0:
        return 0.0
    p = (s1 + s2) / (n1 + n2)
    se = math.sqrt(max(p * (1 - p), 1e-12) * (1 / n1 + 1 / n2))
    return (s1 / n1 - s2 / n2) / se


def wilson(s, n, z=1.96):
    if n == 0:
        return (0.0, 1.0)
    p = s / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (c - h, c + h)


def holm(pvals: dict, alpha: float) -> set:
    """Holm step-down: returns the keys whose null is rejected at family-wise level alpha."""
    out = set()
    items = sorted(pvals.items(), key=lambda kv: kv[1])
    m = len(items)
    for i, (k, p) in enumerate(items):
        if p <= alpha / (m - i):
            out.add(k)
        else:
            break
    return out


def n_per_arm(p: float, rel_lift: float, alpha=0.05, power=0.8) -> int:
    """Sample size per arm (two-sided alpha) to detect a relative lift on a base rate p."""
    za, zb = 1.959964, 0.841621
    if power != 0.8 or alpha != 0.05:
        from statistics import NormalDist
        za, zb = NormalDist().inv_cdf(1 - alpha / 2), NormalDist().inv_cdf(power)
    p2 = p * (1 + rel_lift)
    pb = (p + p2) / 2
    num = (za * math.sqrt(2 * pb * (1 - pb)) + zb * math.sqrt(p * (1 - p) + p2 * (1 - p2))) ** 2
    return math.ceil(num / (p2 - p) ** 2)


def binom_excess_z(k, n, p0) -> float:
    """How many SDs the observed count k in n is above the baseline rate p0."""
    if n == 0:
        return 0.0
    sd = math.sqrt(max(n * p0 * (1 - p0), 1e-12))
    return (k - n * p0) / sd


def poisson_sf(k, mu) -> float:
    """P(X >= k) for X ~ Poisson(mu). Exact enough for small rates, where the normal approx overstates z."""
    if k <= 0:
        return 1.0
    term = math.exp(-mu)
    cdf = term
    for i in range(1, k):
        term *= mu / i
        cdf += term
    return max(0.0, 1.0 - cdf)
