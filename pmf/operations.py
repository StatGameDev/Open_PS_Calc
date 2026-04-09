"""PMF (probability mass function) operations for the damage pipeline.

All functions operate on dict[int, float] where keys are damage values and
values are probabilities summing to 1.0. These replace DamageRange arithmetic
throughout the pipeline — every modifier imports from here.

DamageRange method equivalents:
    .scale(num, denom)          → _scale_floor(pmf, num, denom)
    .add(flat)                  → _add_flat(pmf, flat)
    .add_range(lo, hi, _)       → _convolve(pmf, _uniform_pmf(lo, hi))
    .subtract(vd_min, vd_max, _)→ _subtract_uniform(pmf, vd_min, vd_max)
    .floor_at(n)                → _floor_at(pmf, n)
"""


def _uniform_pmf(lo: int, hi: int) -> dict[int, float]:
    """Discrete uniform PMF over [lo, hi] inclusive."""
    n = hi - lo + 1
    p = 1.0 / n
    return {v: p for v in range(lo, hi + 1)}


def _scale_floor(pmf: dict[int, float], num: int, denom: int) -> dict[int, float]:
    """Deterministic floor-division remap: v → v*num//denom.
    Multiple input values can map to the same output — probabilities accumulate.
    No-op when num == denom."""
    if num == denom:
        return pmf
    out: dict[int, float] = {}
    for v, p in pmf.items():
        key = v * num // denom
        out[key] = out.get(key, 0.0) + p
    return out


def _add_flat(pmf: dict[int, float], flat: int) -> dict[int, float]:
    """Shift all keys by flat. No-op when flat == 0."""
    if flat == 0:
        return pmf
    return {v + flat: p for v, p in pmf.items()}


def _convolve(pmf: dict[int, float], other: dict[int, float]) -> dict[int, float]:
    """General convolution (addition) of two independent PMFs. O(|pmf| * |other|)."""
    out: dict[int, float] = {}
    for v1, p1 in pmf.items():
        for v2, p2 in other.items():
            key = v1 + v2
            out[key] = out.get(key, 0.0) + p1 * p2
    return out


def _subtract_uniform(pmf: dict[int, float], lo: int, hi: int) -> dict[int, float]:
    """Subtract a discrete uniform RV over [lo, hi] from pmf.
    Equivalent to convolving with the negated uniform [-hi, -lo].
    Optimised to _add_flat when lo == hi (no variance)."""
    if lo == hi:
        return _add_flat(pmf, -lo)
    neg_uniform = _uniform_pmf(-hi, -lo)
    return _convolve(pmf, neg_uniform)


def _floor_at(pmf: dict[int, float], n: int = 1) -> dict[int, float]:
    """Accumulate all probability mass at values < n into key n.
    Mirrors max(n, damage) in Hercules."""
    out = {v: p for v, p in pmf.items() if v >= n}
    floor_mass = sum(p for v, p in pmf.items() if v < n)
    if floor_mass > 0:
        out[n] = out.get(n, 0.0) + floor_mass
    return out


def pmf_stats(pmf: dict[int, float]) -> tuple[int, int, int]:
    """Return (min_dmg, max_dmg, avg_dmg) from a PMF.
    avg is the floor of the expected value — matches integer pipeline semantics.
    Used to populate DamageStep.min_value / max_value / value at each step."""
    mu = sum(v * p for v, p in pmf.items())
    return min(pmf), max(pmf), int(mu)
