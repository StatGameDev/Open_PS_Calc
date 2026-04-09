"""
gear_bonuses — GearBonuses dataclass: aggregated numeric bonuses from all equipped item scripts.

Populated by GearBonusAggregator (gear_bonus_aggregator.py) each time equipment changes.
Consumed by build_applicator.py, status_calculator.py, and the damage pipeline calculators.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, TYPE_CHECKING

from core.models.item_effect import ItemEffect
from core.models.sc_effect import SCEffect

if TYPE_CHECKING:
    from core.models.autocast_spec import AutocastSpec


@dataclass
class GearBonuses:
    """
    Aggregated numeric bonuses parsed from all equipped item scripts.
    These are added on top of the manually-entered bonus_* fields in PlayerBuild (core/models/build.py).
    Not saved to disk — recomputed each time equipment changes.
    """
    # Flat stat bonuses
    str_: int = 0
    agi: int = 0
    vit: int = 0
    int_: int = 0
    dex: int = 0
    luk: int = 0

    # Combat bonuses
    batk: int = 0       # bBaseAtk
    hit: int = 0        # bHit
    flee: int = 0       # bFlee
    flee2: int = 0      # bFlee2 (perfect dodge)
    cri: int = 0        # bCritical
    crit_atk_rate: int = 0  # bCritAtkRate (%)
    long_atk_rate: int = 0  # bLongAtkRate (%)

    # Defensive
    def_: int = 0       # bDef (hard DEF)
    mdef_: int = 0      # bMdef (hard MDEF)

    # Status bonuses
    maxhp: int = 0      # bMaxHP
    maxsp: int = 0      # bMaxSP
    maxhp_rate: int = 0  # bMaxHPrate — % rate bonus to MaxHP
    maxsp_rate: int = 0  # bMaxSPrate — % rate bonus to MaxSP
    matk_rate: int = 0   # bMatkRate  — % rate bonus to MATK
    sp_recov_rate: int = 0   # bSPrecovRate — SP natural recovery rate bonus (deferred)
    hp_recov_rate: int = 0   # bHPrecovRate — HP natural recovery rate bonus (deferred)
    res_eff: dict = field(default_factory=dict)  # {Eff_*: Hercules units} status resist

    # Element overrides from scripts — int 0-9 or None if not overridden.
    # Split by hand slot to mirror pc_bonus SP_ATKELE lr_flag routing (pc.c:2588-2609).
    script_atk_ele_rh: int | None = None  # bAtkEle on RH-slot items → rhw.ele
    script_atk_ele_lh: int | None = None  # bAtkEle on LH-slot items → lhw.ele
    script_def_ele: int | None = None     # bDefEle — armor element from script

    # ASPD
    aspd_percent: int = 0   # bAspdRate
    aspd_add: int = 0       # bAspd (flat amotion reduction)

    # All parsed bonus effects across all equipped items (for tooltips)
    all_effects: List[ItemEffect] = field(default_factory=list)

    # SC effects from sc_start/sc_start2/sc_start4 calls across all items.
    # Routed to StatusCalculator via build_applicator.py → status_calculator.py.
    sc_effects: List[SCEffect] = field(default_factory=list)

    # race/size/element multipliers — populated by GearBonusAggregator (gear_bonus_aggregator.py);
    # not read by the damage pipeline.
    add_race: Dict[str, int] = field(default_factory=dict)        # {race: bonus%} physical (bAddRace)
    magic_add_race: Dict[str, int] = field(default_factory=dict)  # {race: bonus%} magic  (bMagicAddRace, magic_addrace)
    sub_ele: Dict[str, int] = field(default_factory=dict)    # {ele: resist%}
    sub_race: Dict[str, int] = field(default_factory=dict)   # {race: resist%}
    add_size: Dict[str, int] = field(default_factory=dict)   # {size: bonus%}
    add_ele: Dict[str, int] = field(default_factory=dict)         # {ele: bonus%} target element
    add_atk_ele: Dict[str, int] = field(default_factory=dict)     # {ele: bonus%} outgoing attack element (bAddAtkEle)
    ignore_def_rate: Dict[str, int] = field(default_factory=dict)   # {race: %}
    ignore_def_ele: Dict[str, int] = field(default_factory=dict)    # {ele: %} PS-custom partial DEF pierce by target element (bIgnoreDefEle)
    ignore_mdef_rate: Dict[str, int] = field(default_factory=dict)  # {race: %}
    skill_atk: Dict[str, int] = field(default_factory=dict)  # {skill: %}
    holy_strike_bonus_chance: int = 0  # bHolyStrikeChance: gear/combo bonus proc chance (PS-custom)

    # Incoming damage rate modifiers (for target-side CardFix / PvP)
    near_atk_def_rate: int = 0   # bNearAtkDef — % reduction vs melee
    long_atk_def_rate: int = 0   # bLongAtkDef — % reduction vs ranged
    magic_def_rate:    int = 0   # bMagicDefRate — % reduction vs magic
    atk_rate:          int = 0   # bAtkRate — flat % bonus to physical ATK
    weapon_atk_rate: Dict[str, int] = field(default_factory=dict)  # bWeaponAtk: Hercules W_* const → ATK%

    # pdef=1 bitmask from def_ratio_atk_ele/race card bonuses (battle.c:5686/5694).
    # Keys: "Ele_Fire" / "RC_DemiHuman" etc. — presence (value>0) means pdef=1 triggers.
    def_ratio_atk_ele: Dict[str, int] = field(default_factory=dict)   # bDefRatioAtkEle
    def_ratio_atk_race: Dict[str, int] = field(default_factory=dict)  # bDefRatioAtkRace

    # Item autocast proc specs parsed from bonus3/bonus4 autocast scripts.
    # Populated by GearBonusAggregator._build_autocast_spec() (gear_bonus_aggregator.py).
    # autocast_on_attack: bAutoSpell  — fires on Normal Attack only (skill.id == 0)
    # autocast_on_skill:  bAutoSpellOnSkill — fires when src_skill_id matches active skill
    # autocast_when_hit:  bAutoSpellWhenHit — parsed for tooltip display; not wired into outgoing pipeline
    autocast_on_attack: List["AutocastSpec"] = field(default_factory=list)
    autocast_on_skill:  List["AutocastSpec"] = field(default_factory=list)
    autocast_when_hit:  List["AutocastSpec"] = field(default_factory=list)

    # Active item combos (item_combo_db): human-readable labels for fired combos.
    # Populated by GearBonusAggregator.apply_combo_bonuses() (gear_bonus_aggregator.py).
    # Format: "Item A + Item B -> effect text"
    active_combo_descriptions: List[str] = field(default_factory=list)

    # Skill timing
    # castrate: sum of bCastrate / bVarCastrate val deltas.
    #   sd->castrate in Hercules starts at 100; gear_bonuses.castrate is the delta.
    #   Applied as: time = time * (100 + castrate) // 100  (pc.c:2639; skill.c:~17197)
    castrate: int = 0
    # delayrate: sum of bDelayrate val deltas. Same delta-from-100 convention.
    #   Applied as: time = time * (100 + delayrate) // 100  (pc.c:3020; skill.c:~17506)
    delayrate: int = 0
    # skill_castrate: per-skill cast reduction from bonus2 bCastrate,skill_name,val.
    #   Keys are skill constant name strings (e.g. "AL_HOLYLIGHT").  (pc.c:3607)
    skill_castrate: Dict[str, int] = field(default_factory=dict)
    # skill_delayrate: per-skill ACD reduction from bonus2 bDelayrate,skill_name,val.
    #   Keys are skill constant name strings. PS-custom (no vanilla Hercules equivalent).
    #   Stacks additively with delayrate; applied as: time = time * (100 + delayrate + skill_delayrate[sk]) // 100
    skill_delayrate: Dict[str, int] = field(default_factory=dict)

    # Skill grants from `skill X,N` item scripts (pc_skill ADDSKILL_TEMP).
    # {skill_constant: max_granted_level} — max taken across all equipped items.
    skill_grants: Dict[str, int] = field(default_factory=dict)

    # Merged effective skill levels: max(mastery_levels[X], skill_grants[X]) for all X.
    # Populated by GearBonusAggregator.compute() (gear_bonus_aggregator.py) using script_ctx.skill_levels as base.
    # Use this everywhere calculators currently read build.mastery_levels for skill checks.
    # Limitation: skill_grants are not visible to getskilllv() in ItemScriptContext during
    # aggregation (chicken-and-egg); no real item currently triggers this path.
    effective_mastery: Dict[str, int] = field(default_factory=dict)

    # Card-only sub-aggregate: all bonus fields reflect contributions from card slots only.
    # Mirrors Hercules param_bonus[] (card scripts) vs param_equip[] (equipment scripts).
    # Populated by GearBonusAggregator.compute() (gear_bonus_aggregator.py). from_cards.from_cards is always None.
    # Use for formula exclusions (SC_CONCENTRATION).
    from_cards: GearBonuses | None = field(default=None)
