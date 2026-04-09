"""
BattleConfig — tunables mirroring conf/battle/battle.conf for pre-renewal.

Instantiated per server profile in server_profiles.py.
"""
from dataclasses import dataclass

@dataclass
class BattleConfig:
    """Exact tunables from conf/battle/battle.conf (pre-renewal only – full clean structure)."""
    weapon_damage_rate: int = 100
    short_attack_damage_rate: int = 100
    long_attack_damage_rate: int = 100
    critical_rate: int = 100     # global crit rate multiplier (status.c:3919, default 100 = no change)
    critical_min: int = 10       # minimum crit chance in 0.1% units (calc_critical ~line 4743, default 10 = 1.0%)
    enable_critical: bool = True
    max_aspd: int = 190
    enable_perfect_flee: bool = True

    # Hit/miss rate clamps (battle.c:4469/5024, #ifndef RENEWAL)
    min_hitrate: int = 5     # minimum_hit_rate (default 5%)
    max_hitrate: int = 100   # maximum_hit_rate (default 100%)

    # Full VIT penalty support (pure mechanics, no legacy fields)
    vit_penalty_target: int = 0      # bitmask: 1=PC, 2=MOB, 4=BOSS, etc.
    vit_penalty_count: int = 3       # hits before penalty starts
    vit_penalty_num: int = 5         # % or flat reduction per extra hit
    vit_penalty_type: int = 0        # 0=off, 1=percentage, 2=flat