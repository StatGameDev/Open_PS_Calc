"""Array-based helpers for multi-hit PMF computation.
Used by pmf/multi_hit.py — not needed for single-hit pipeline work.
"""
import numpy as np


def pmf_dict_to_array(pmf: dict[int, float], lo: int, hi: int) -> np.ndarray:
    """Pack a sparse PMF dict into a dense numpy array aligned to [lo, hi]."""
    arr = np.zeros(hi - lo + 1, dtype=np.float64)
    for v, p in pmf.items():
        arr[v - lo] = p
    return arr


def percentiles_from_array(
    arr: np.ndarray, support: range, percentiles: list[int]
) -> list[float]:
    """Exact CDF walk over a dense PMF array. O(len(arr)).
    Returns the damage value at each requested percentile."""
    cdf = np.cumsum(arr)
    results = []
    for pct in percentiles:
        idx = int(np.searchsorted(cdf, pct / 100.0))
        idx = min(idx, len(arr) - 1)
        results.append(float(support[idx]))
    return results
