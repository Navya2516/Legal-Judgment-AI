"""Small, dependency-free statistics used by every report.

All randomness takes an explicit seed so a report can be reproduced exactly.
"""
import math
import random
from typing import Callable, Optional, Sequence


def wilson_interval(successes: int, n: int, z: float = 1.96) -> Optional[tuple[float, float]]:
    """95% Wilson score interval for a proportion. None when n is 0."""
    if n <= 0:
        return None
    p = successes / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


def proportion(successes: int, n: int) -> dict:
    """{"k", "n", "rate", "ci95"}; rate and ci95 are None when n is 0."""
    ci = wilson_interval(successes, n)
    return {
        "k": successes,
        "n": n,
        "rate": (successes / n) if n else None,
        "ci95": [round(ci[0], 4), round(ci[1], 4)] if ci else None,
    }


def mean(values: Sequence[float]) -> Optional[float]:
    return (sum(values) / len(values)) if values else None


def bootstrap_ci(
    values: Sequence[float],
    statistic: Callable[[Sequence[float]], float] = lambda v: sum(v) / len(v),
    *,
    iterations: int = 2000,
    seed: int = 0,
) -> Optional[list[float]]:
    """Percentile bootstrap 95% interval over per-question values. None for fewer than 2 values."""
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    n = len(values)
    stats = sorted(statistic([values[rng.randrange(n)] for _ in range(n)]) for _ in range(iterations))
    lo = stats[int(0.025 * iterations)]
    hi = stats[min(iterations - 1, int(0.975 * iterations))]
    return [round(lo, 4), round(hi, 4)]


def cohens_kappa(a: Sequence[str], b: Sequence[str]) -> Optional[float]:
    """Agreement between two reviewers on the same items, corrected for chance."""
    if len(a) != len(b) or not a:
        return None
    n = len(a)
    observed = sum(x == y for x, y in zip(a, b)) / n
    labels = set(a) | set(b)
    expected = sum((a.count(l) / n) * (b.count(l) / n) for l in labels)
    if expected >= 1.0:
        return 1.0 if observed == 1.0 else None
    return round((observed - expected) / (1 - expected), 4)


def fmt_rate(p: dict) -> str:
    """'83.3% (95% CI 62.0-93.5, 15/18)' for reports."""
    if not p["n"]:
        return "n/a (0 items)"
    lo, hi = p["ci95"]
    return f"{100 * p['rate']:.1f}% (95% CI {100 * lo:.1f}-{100 * hi:.1f}, {p['k']}/{p['n']})"
