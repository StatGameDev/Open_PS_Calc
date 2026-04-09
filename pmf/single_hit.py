"""SingleHitPMF — thin wrapper around a completed pipeline DamageResult.
Used as input to pmf/multi_hit.py compute_multi_hit().

from_damage_result() requires DamageResult.pmf to be populated.
"""
from __future__ import annotations
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from core.models.damage import DamageResult


@dataclass
class SingleHitPMF:
    pmf: dict[int, float]   # sums to 1.0; keys are integer damage values
    min_dmg: int
    max_dmg: int
    mean: float             # populated by finalize()
    variance: float         # populated by finalize()

    def finalize(self) -> "SingleHitPMF":
        """Compute mean and variance in one O(n) pass. Call after pmf is fully built."""
        mu = sum(v * p for v, p in self.pmf.items())
        var = sum((v - mu) ** 2 * p for v, p in self.pmf.items())
        self.mean = mu
        self.variance = var
        return self

    @classmethod
    def from_damage_result(cls, result: "DamageResult") -> "SingleHitPMF":
        """Build a SingleHitPMF from a pipeline-produced DamageResult.
        Requires result.pmf to be a populated dict[int, float].
        """
        pmf = result.pmf
        obj = cls(
            pmf=pmf,
            min_dmg=min(pmf),
            max_dmg=max(pmf),
            mean=0.0,
            variance=0.0,
        )
        return obj.finalize()
