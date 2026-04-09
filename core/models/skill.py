"""
SkillInstance — the active skill being calculated (id, level, and battle flags).

Populated by the GUI skill section; passed into BattlePipeline.calculate() as the
primary skill input. Consumed by SkillRatio, CritChance, DefenseFix, and pipeline
routing logic in battle_pipeline.py.
"""
from dataclasses import dataclass

@dataclass
class SkillInstance:
    id: int = 0                     # 0 = Normal Attack, 5 = SM_BASH, ...
    level: int = 1
    is_critical_forced: bool = False
    is_maximize_power: bool = False
    ignore_size_fix: bool = False   # flag&8 – ignores size fix
    name: str = ""                  # populated from skills.json in battle_pipeline.calculate()
    nk_ignore_def: bool = False     # "IgnoreDefense" in damage_type (skill_db.conf → skills.json)
    nk_ignore_flee: bool = False    # "IgnoreFlee" in damage_type