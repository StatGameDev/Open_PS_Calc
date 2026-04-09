"""
AttackDefinition — one outcome type in the DPS attack distribution.

avg_damage : average damage for this outcome (0.0 for a miss).
pre_delay  : cast/startup time before the hit lands, in ms (0 for auto-attacks).
post_delay : after-delay before the next action (adelay), in ms.
chance     : steady-state probability weight; must sum to 1.0 across the list
             passed to calculate_dps() (dps_calculator.py).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class AttackDefinition:
    avg_damage: float
    pre_delay:  float   # ms
    post_delay: float   # ms
    chance:     float   # steady-state probability weight
