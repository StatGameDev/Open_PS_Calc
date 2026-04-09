"""
CalcContext — runtime context threaded into all ServerProfile ratio/hit-count callables.

Constructed once per pipeline entry from PlayerBuild + StatusData, then passed into
SkillRatio.calculate() / calculate_magic() and every callable in weapon_ratios,
magic_ratios, magic_wave_ratios, weapon_hit_counts, magic_hit_counts (server_profiles.py).

All callables use the signature (lv, tgt, ctx=None); lambdas that only need
(lv, tgt) ignore ctx.

wave_idx is set per-wave when iterating magic_wave_ratios (default 0 = not a
wave-indexed call).
"""
from dataclasses import dataclass, field


@dataclass
class CalcContext:
    skill_levels: dict = field(default_factory=dict)
    # Maps skill_name → level; populated from gear_bonuses.effective_mastery (gear_bonus_aggregator.py; mastery merged with gear skill_grants).
    # Cross-skill formulas (e.g. WZ_FROSTNOVA needing MG_FROSTDIVER level) read here.

    skill_params: dict = field(default_factory=dict)
    # Maps skill_param key → value; populated from build.skill_params.
    # Used by magic_ratios lambdas needing user-input params (e.g. WZ_FIREPILLAR_firewall_lv).

    base_level: int = 1
    base_str: int = 0   # build.base_str (allocated points, not total) — for PS_PR_HOLYSTRIKE and similar
    str_: int = 1
    vit: int = 1
    dex: int = 1
    int_: int = 1
    weapon_type: str = ""
    # weapon_type from Weapon.weapon_type (e.g. "Bow", "2HSword"); "" when no weapon.

    wave_idx: int = 0
    # 1-based wave index for magic_wave_ratios callables. 0 = not a wave call.
