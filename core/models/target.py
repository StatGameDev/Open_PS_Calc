"""
Target — mirror of struct status_data for the target side in damage calculations.

Populated by TargetStateSection.apply_to_target() from the GUI; consumed by
DefenseFix, hit_chance, and apply_mob_scs (target_utils.py) across the
BF_WEAPON and BF_MAGIC pipelines.
"""
from dataclasses import dataclass, field
from typing import Dict

@dataclass
class Target:
    def_: int = 0
    vit: int = 0
    size: str = "Medium"    # Small / Medium / Large
    race: str = "Formless"
    element: int = 0
    element_level: int = 1   # 1-4 for attr_fix table
    is_boss: bool = False
    level: int = 1
    luk: int = 0              # tstatus->luk — used in crit roll: cri -= luk*2 (battle.c:4957)
    agi: int = 0              # tstatus->agi — used in FLEE calc: flee = level + agi (status.c)
    is_pc: bool = False
    targeted_count: int = 1   # unit_counttargeted(bl) value for VIT penalty (pre-renewal exact)
    sub_race: Dict[str, int] = field(default_factory=dict)   # RC_* keys — player's race resistance
    sub_ele:  Dict[str, int] = field(default_factory=dict)   # Ele_* keys — element resistance
    sub_size: Dict[str, int] = field(default_factory=dict)   # Size_* keys — size resistance
    near_attack_def_rate: int = 0   # % reduction vs melee
    long_attack_def_rate: int = 0   # % reduction vs ranged
    magic_def_rate: int = 0         # % reduction vs magic
    mdef_: int = 0                  # tstatus->mdef (hard MDEF)
    int_:  int = 0                  # tstatus->int (soft MDEF)
    armor_element: int = 0          # 0 = Neutral
    flee:  int = 0                  # tstatus->flee — pre-populated: level+agi (status.c:3865 #else)
    str:   int = 0                  # tstatus->str  — SC_BLESSING debuff: str >>= 1
    dex:   int = 0                  # tstatus->dex  — mob hit = level+dex (status.c:3864 #else); SC_QUAGMIRE/BLESSING
    hit:   int = 0                  # tstatus->hit  — pre-populated: level+dex; SC_BLIND: hit -= hit*25/100
    def_percent: int = 100          # st->def_percent — SC_POISON: -= 25 (status.c:4431); SC_PROVOKE mob path
    mdef_percent: int = 100         # SC_MINDBREAKER: mdef_percent -= 12*lv (status.c:4453-4454)
    matk_percent: int = 100         # SC_MINDBREAKER: matk_percent += 20*lv (status.c:4376-4377) — incoming magic
    aspd_rate: int = 1000           # SC_DONTFORGETME: aspd_rate += 10*val2 (status.c:5667); 1000=100%, >1000=slower
    target_active_scs: Dict[str, int] = field(default_factory=dict)
    # SC flags written by TargetStateSection.apply_to_target(); read by DefenseFix, hit_chance, apply_mob_scs.
    mailbreaker: bool = False   # +10% damage taken; not vs bosses
    venom_dust:  bool = False   # +10% damage taken; all targets
    raided:      bool = False   # +10% damage taken; all targets
    # All three stack multiplicatively with each other and with Lex Aeterna.