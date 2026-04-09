"""
BattlePipeline — top-level orchestrator for all outgoing damage calculations.

Routing:
  skill.attack_type == "Magic"          → MagicPipeline (magic_pipeline.py)
  skill_name == "CR_GRANDCROSS"         → GrandCrossPipeline (grand_cross_pipeline.py)
  skill in IMPLEMENTED_BF_MISC_SKILLS   → _run_misc_branch() (flat formula, no DEF)
  everything else                       → _run_branch() × 2 (normal + crit)

BF_WEAPON step order: see BattlePipeline class docstring.
BF_MISC step order: BF_MISC flat formula → CardFix → AttrFix → FinalRateBonus.

Module-level constants:
  _WEAPON_TYPE_TO_HERC  — item_db weapon_type string → Hercules W_* enum (battle.c:676-686)
  _AUTOSPELL_DB         — vanilla SA_AUTOSPELL unlock table (autospell_db.conf)
  _PS_AUTOSPELL_DB      — PS SA_AUTOSPELL unlock table (PayonStoriesData)
  _DC_SKILLS            — PF_DOUBLECASTING eligible spells (skill.c:3938)
  _VARIABLE_HIT_SKILLS  — skills with map/field-dependent hit counts
"""
import dataclasses

from core.build_manager import BuildManager, effective_is_ranged
from core.bonus_definitions import _ELE_STR_TO_INT
from core.server_profiles import ServerProfile, STANDARD, get_profile

# Jobs that can dual-wield (Assassin, Assassin Cross).
# Source: battle.c:4855-4859 — skills always use RH only; dual-wield is normal attack only.
_DUAL_WIELD_JOBS: frozenset = frozenset({12, 4013})
# PS-Arch-7: Rogue (17) + Stalker (4018) — bow DA via AC_VULTURE, 1H sword DA via SM_SWORD
_ROGUE_JOBS: frozenset = frozenset({17, 4018})

# weapon.weapon_type (item_db string) → Hercules W_* constant used in bWeaponAtk item scripts.
# Source: battle.c:676-686 battle_calc_base_damage2 — sd->weapon_atk_rate[sd->weapontype1].
_WEAPON_TYPE_TO_HERC: dict[str, str] = {
    "Knife":             "W_DAGGER",   "1HSword":  "W_1HSWORD",
    "2HSword":           "W_2HSWORD",  "1HSpear":  "W_1HSPEAR",
    "2HSpear":           "W_2HSPEAR",  "1HAxe":    "W_1HAXE",
    "2HAxe":             "W_2HAXE",    "Mace":     "W_MACE",
    "Staff":             "W_STAFF",    "2HStaff":  "W_2HSTAFF",
    "Bow":               "W_BOW",      "Knuckle":  "W_KNUCKLE",
    "MusicalInstrument": "W_MUSICAL",  "Whip":     "W_WHIP",
    "Book":              "W_BOOK",     "Katar":    "W_KATAR",
    "Revolver":          "W_REVOLVER", "Rifle":    "W_RIFLE",
    "Gatling":           "W_GATLING",  "Shotgun":  "W_SHOTGUN",
    "Grenade":           "W_GRENADE",  "Fuuma":    "W_HUUMA",
}
from core.models.damage import DamageResult, BattleResult
from core.models.calc_context import CalcContext
from pmf.operations import _scale_floor, _add_flat, _uniform_pmf, pmf_stats
from core.calculators.magic_pipeline import MagicPipeline
from core.calculators.grand_cross_pipeline import GrandCrossPipeline
from core.models.build import PlayerBuild
from core.models.status import StatusData
from core.models.weapon import Weapon
from core.models.skill import SkillInstance
from core.models.target import Target
from core.config import BattleConfig
from core.data_loader import loader
from core.models.gear_bonuses import GearBonuses
from core.calculators.status_calculator import StatusCalculator
from core.calculators.modifiers.base_damage import BaseDamage
from core.calculators.modifiers.skill_ratio import SkillRatio
from core.calculators.modifiers.attr_fix import AttrFix
from core.calculators.modifiers.forge_bonus import ForgeBonus
from core.calculators.modifiers.card_fix import CardFix
from core.calculators.modifiers.defense_fix import DefenseFix
from core.calculators.modifiers.mastery_fix import MasteryFix
from core.calculators.modifiers.active_status_bonus import ActiveStatusBonus
from core.calculators.modifiers.refine_fix import RefineFix
from core.calculators.modifiers.final_rate_bonus import FinalRateBonus
from core.calculators.modifiers.crit_chance import calculate_crit_chance, is_crit_eligible
from core.calculators.modifiers.crit_atk_rate import CritAtkRate
from core.calculators.modifiers.hit_chance import calculate_hit_chance
from core.models.attack_definition import AttackDefinition
from core.calculators.dps_calculator import calculate_dps, FormulaSelectionStrategy
from core.calculators.skill_timing import calculate_skill_timing
from core.calculators.proc_keys import PROC_AUTO_BLITZ, PROC_AUTOSPELL, PROC_DOUBLE_BOLT, PROC_HOLY_STRIKE, PROC_TRIPLE_ATTACK
from core.models.autocast_spec import AutocastSpec
from core.calculators.modifiers.skill_ratio import (
    IMPLEMENTED_BF_WEAPON_SKILLS, IMPLEMENTED_BF_MAGIC_SKILLS,
    IMPLEMENTED_BF_MISC_SKILLS, _BF_MISC_FORMULAS,
)


# ---------------------------------------------------------------------------
# PF_DOUBLECASTING — skills that trigger a second cast via addtimerskill(tick+amotion, flag|2).
# Vanilla (SC_DOUBLECASTING): MG_COLDBOLT/FIREBOLT/LIGHTNINGBOLT only (skill.c:3938).
# PS SA_DOUBLEBOLT: passive Sage skill; doubles MG_LIGHTNINGBOLT, MG_SOULSTRIKE,
#   WZ_EARTHSPIKE at max lv (lv1). Check: build.mastery_levels["SA_DOUBLEBOLT"] > 0.
# ---------------------------------------------------------------------------
_DC_SKILLS: frozenset[str] = frozenset({
    "MG_COLDBOLT", "MG_FIREBOLT", "MG_LIGHTNINGBOLT",
})
_PS_SA_DOUBLEBOLT_SKILLS: frozenset[str] = frozenset({
    "MG_LIGHTNINGBOLT", "MG_SOULSTRIKE", "WZ_EARTHSPIKE",
})

# ---------------------------------------------------------------------------
# Variable-hit magic skills: hit count is map/field-dependent, not fixed.
# Per-hit damage is shown as the main result; a 100%-chance proc_branch shows
# the maximum possible total (all cells hit). DPS uses max hits.
# Max hits derived from Hercules: range = skill_lv // 2; grid = (2r+1)^2.
# skill.c:5487-5516 (WZ_WATERBALL case: count over water cells in range).
# ---------------------------------------------------------------------------
_VARIABLE_HIT_SKILLS: dict[str, list[int]] = {
    # lv:            1  2   3   4   5   6   7   8   9  10
    # Levels 6-10: PC cast of mob-level skill; Hercules falls to range = maxlv//2 = 2 → 25 cells.
    # (Mob-exclusive lv10 range=4 is gated on BL_MOB in skill.c:5500 — not applicable here.)
    "WZ_WATERBALL": [1, 9, 9, 25, 25, 25, 25, 25, 25, 25],
}

# ---------------------------------------------------------------------------
# Zone-avg weapon skills: chance-based skills where hit count depends on target
# position. Per-hit (single-hit) damage is the main result; a 100%-chance
# proc_branch shows the expected total (avg hits × single hit). DPS uses
# expected total. Zone probabilities stored per-profile in
# ServerProfile.weapon_avg_hits_by_zone; zone selected via {SKILL}_zone param.
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# SA_AUTOSPELL (Hindsight) — VANILLA PRE-RENEWAL DATA
# Source: Hercules/db/pre-re/autospell_db.conf
#
# Format: {spell_constant: {sa_autospell_level: max_proc_level}}
# SA levels absent from a spell's dict mean the spell is not yet available.
# ---------------------------------------------------------------------------
_AUTOSPELL_DB: dict[str, dict[int, int]] = {
    "MG_NAPALMBEAT":    {1:3, 2:3, 3:3, 4:3, 5:3, 6:3, 7:3, 8:3, 9:3, 10:3},
    "MG_COLDBOLT":      {2:1, 3:2, 4:3, 5:3, 6:3, 7:3, 8:3, 9:3, 10:3},
    "MG_FIREBOLT":      {2:1, 3:2, 4:3, 5:3, 6:3, 7:3, 8:3, 9:3, 10:3},
    "MG_LIGHTNINGBOLT": {2:1, 3:2, 4:3, 5:3, 6:3, 7:3, 8:3, 9:3, 10:3},
    "MG_SOULSTRIKE":    {5:1, 6:2, 7:3, 8:3, 9:3, 10:3},
    "MG_FIREBALL":      {8:1, 9:2, 10:2},
    "MG_FROSTDIVER":    {10:1},
}

# SA_AUTOSPELL (Hindsight) — PAYON STORIES DATA
# Source: PayonStoriesData/skill_database_flat.jsonl — SA_AUTOSPELL
# PS: one spell available per SA level (different list from vanilla). Proc chance: flat 30%.
# Same format as _AUTOSPELL_DB — spell → {sa_lv: max_proc_lv}.
# Each spell only appears at one SA level; selecting wrong spell → max_proc_lv=0 → no proc.
_PS_AUTOSPELL_DB: dict[str, dict[int, int]] = {
    "MG_SOULSTRIKE":    {1: 5},   # SA lv1 → Soul Strike max lv5
    "MG_FIREBOLT":      {2: 4},   # SA lv2 → Fire Bolt max lv4 (variance: 50%lv2,35%lv3,15%lv4)
    "MG_COLDBOLT":      {3: 4},   # SA lv3 → Cold Bolt max lv4
    "MG_LIGHTNINGBOLT": {4: 4},   # SA lv4 → Lightning Bolt max lv4
    "WZ_EARTHSPIKE":    {5: 2},   # SA lv5 → Earth Spike max lv2
    "MG_FIREBALL":      {6: 10},  # SA lv6 → Fire Ball max lv10
    "MG_THUNDERSTORM":  {7: 3},   # SA lv7 → Thunderstorm max lv3
    "WZ_HEAVENDRIVE":   {8: 3},   # SA lv8 → Heaven's Drive max lv3
    "MG_STONECURSE":    {9: 10},  # SA lv9 → Stone Curse max lv10 (no gem cost)
    "MG_SAFETYWALL":    {10: 5},  # SA lv10 → Safety Wall max lv5 (no gem cost)
}

# Skill IDs for the autospell spells (from docs/lookup/skill_ref.tsv).
_AUTOSPELL_SPELL_IDS: dict[str, int] = {
    "MG_NAPALMBEAT":    11,
    "MG_SAFETYWALL":    12,
    "MG_SOULSTRIKE":    13,
    "MG_COLDBOLT":      14,
    "MG_FROSTDIVER":    15,
    "MG_STONECURSE":    16,
    "MG_FIREBALL":      17,
    "MG_FIREBOLT":      19,
    "MG_LIGHTNINGBOLT": 20,
    "MG_THUNDERSTORM":  21,
    "WZ_EARTHSPIKE":    90,
    "WZ_HEAVENDRIVE":   91,
}


def get_autospell_available(sa_lv: int, server: str) -> frozenset[str]:
    """Return spell constants available to memorize at the given SA_AUTOSPELL level.

    A spell is available if it has any unlock entry at or below sa_lv.
    GUI calls this with server: str — resolves to the correct DB internally.
    """
    db = _PS_AUTOSPELL_DB if get_profile(server) is not STANDARD else _AUTOSPELL_DB
    return frozenset(spell for spell, levels in db.items() if any(k <= sa_lv for k in levels))


def _skill_period_ms(
    cast_ms: int,
    delay_ms: int,
    skill_data: dict | None,
    skill_lv: int,
    ps_min_period: int,
    adelay_floor: float,
) -> float:
    """DPS period floor: max(cast+ACD, vanilla_cd, ps_min_period, adelay).

    vanilla_cd: per-skill blockpc cooldown from skill_db.conf CoolDown[lv] — immune to
    Bragi/delayrate (applied here, not inside skill_timing). Source: skill.c:6529.
    ps_min_period: PS-server per-skill cooldowns (ServerProfile.skill_min_period_ms).
    Caller passes adelay for single use; 2*adelay for Double Cast.
    """
    _cds = (skill_data.get("cool_down") or []) if skill_data else []
    vanilla_cd = _cds[skill_lv - 1] if skill_lv - 1 < len(_cds) else 0
    return float(max(cast_ms + delay_ms, vanilla_cd, ps_min_period, adelay_floor))


def _resolve_is_ranged(build: PlayerBuild, weapon: Weapon, skill: SkillInstance) -> bool:
    """Determine BF_SHORT (False) vs BF_LONG (True) for a skill attack.

    Skills with an explicit non-negative range in skill_db override the weapon-derived flag.
    Negative range values mean 'use weapon range' and fall back to effective_is_ranged.
    Source: battle.c:3789-3792 battle_range_type:
        skill_get_range2 < 5 → BF_SHORT; else BF_LONG
    """
    if skill.id != 0:
        skill_data = loader.get_skill(skill.id)
        if skill_data:
            range_list = skill_data.get("range", [])
            if range_list:
                idx = min(skill.level - 1, len(range_list) - 1)
                r = range_list[idx]
                if r >= 0:
                    return r >= 5   # BF_LONG threshold from battle_range_type
    return effective_is_ranged(build, weapon)


class BattlePipeline:
    """
    Orchestrator for the full pre-renewal BF_WEAPON damage calculation.
    Returns a BattleResult containing both normal and crit branches.

    Correct step order (per battle_calc_weapon_attack source, #ifndef RENEWAL):
      BaseDamage         ← battle_calc_base_damage2 (SizeFix INTERNAL, before batk)
      SkillRatio         ← battle_calc_skillratio
      [CritAtkRate]      ← ATK_ADDRATE(crit_atk_rate) — crit branch only, pre-defense (line 5333)
      DefenseFix         ← battle->calc_defense (~lines 5720-5738) — skipped on crit
      ActiveStatusBonus  ← SC_AURABLADE etc., POST-defense (lines 5770-5795)
      RefineFix          ← ATK_ADD2(sstatus->rhw.atk2, ...) lines 5803-5805 — BOTH branches
      MasteryFix         ← battle->calc_masteryfix (#ifndef RENEWAL, lines 5812-5818)
      AttrFix            ← calc_elefix (after mastery in pre-renewal)
      FinalRateBonus
    """

    def __init__(self, config: BattleConfig):
        self.config = config

    def calculate(self,
                  status: StatusData,
                  weapon: Weapon,
                  skill: SkillInstance,
                  target: Target,
                  build: PlayerBuild,
                  gear_bonuses: GearBonuses) -> BattleResult:
        """Run both normal and crit branches. Returns BattleResult.

        If the skill's attack_type is 'Magic' (from skills.json), routes to MagicPipeline.
        Magic result is stored in BattleResult.magic and also mirrored to .normal so
        the existing GUI StepsBar / summary display shows it without changes.
        """
        skill_data = loader.get_skill(skill.id)
        attack_type = skill_data.get("attack_type", "Weapon") if skill_data else "Weapon"
        skill_name: str = skill_data.get("name", "") if skill_data else ""

        # Resolve profile early — needed by skill hydration (MO_EXTREMITYFIST check) and gb compute.
        profile = get_profile(build.server)

        # Hydrate SkillInstance from skills.json before any _run_branch call.
        # Ensures NK flags and SizeFix bypass are correctly set for all branches.
        skill.name = skill_name
        damage_type = skill_data.get("damage_type", []) if skill_data else []
        skill.nk_ignore_def  = "IgnoreDefense" in damage_type
        skill.nk_ignore_flee = "IgnoreFlee" in damage_type
        # MO_EXTREMITYFIST DEF handling: profile controls whether vanilla IgnoreDefense applies.
        # When MO_EXTREMITYFIST_NK_NORMAL_DEF is set, DEF is not ignored — post-DefenseFix
        # reduction step fires instead (see below in _run_branch).
        # Vanilla: IgnoreDefense flag active. PS: cleared via mechanic_flags.
        if skill_name == "MO_EXTREMITYFIST" and "MO_EXTREMITYFIST_NK_NORMAL_DEF" in profile.mechanic_flags:
            skill.nk_ignore_def = False
        # SizeFix bypass: hardcoded in battle.c (not in skill_db.conf).
        # battle.c:5279 #ifndef RENEWAL: (skill_id == MO_EXTREMITYFIST ? 8 : 0) → flag&8 skips SizeFix.
        _NO_SIZEFIX_SKILLS = frozenset({"MO_EXTREMITYFIST"})
        skill.ignore_size_fix = skill_name in _NO_SIZEFIX_SKILLS

        # amotion = 2000 - aspd*10  (status.c:2112; status.c:2134: adelay = 2 × amotion)
        # Floored at 100 to match cap_value(i, pc_max_aspd(sd), 2000) in Hercules.
        amotion: int = max(100, int(2000 - status.aspd * 10))
        # adelay = 2 × amotion — minimum period floor for all skills.
        # The client plays an animation for adelay before accepting new skill input.
        # Skills with no animation lock use amotion instead (see ServerProfile.skill_no_adelay_lock).
        adelay: float = float(2 * amotion)

        # Apply skill level cap overrides (ServerProfile.skill_level_cap_overrides) before any calculation.
        if profile.skill_level_cap_overrides:
            _cap = profile.skill_level_cap_overrides.get(skill_name)
            if _cap is not None and skill.level > _cap:
                skill = dataclasses.replace(skill, level=_cap)

        # SA_AUTOSPELL (Hindsight): normal auto-attack with a memorized spell proc.
        # Primary attack = Normal Attack (id=0); proc appended to proc_branches.
        if skill_name == "SA_AUTOSPELL":
            return self._calculate_hindsight(status, weapon, skill, target, build)

        # GearBonuses pre-computed by resolve_player_state() and passed in — no recompute here.
        gb = gear_bonuses

        if skill_name in IMPLEMENTED_BF_MISC_SKILLS or skill_name in profile.misc_formulas:
            misc_result = self._run_misc_branch(
                status, skill, target, build, skill_name, skill_data,
                is_ranged=_resolve_is_ranged(build, weapon, skill),
                gear_bonuses=gb, profile=profile,
            )
            hit_chance = 100.0  # IgnoreFlee — all current BF_MISC skills auto-hit
            if skill_data and "IgnoreFlee" not in (skill_data.get("damage_type") or []):
                hit_chance, _ = calculate_hit_chance(status, target, self.config)
            cast_ms, delay_ms = calculate_skill_timing(
                skill_name, skill.level, skill_data, status, gb, build.support_buffs,
                server=build.server,
            ) if skill_data else (0, 0)
            misc_period = _skill_period_ms(cast_ms, delay_ms, skill_data, skill.level,
                                           profile.skill_min_period_ms.get(skill_name, 0), adelay)
            if skill_name in profile.ps_attack_interval:
                misc_period = float(profile.ps_attack_interval[skill_name](status, amotion))
            misc_dps = misc_result.avg_damage / misc_period * 1000 if misc_period > 0 else 0.0
            misc_br = BattleResult(
                normal=misc_result,
                magic=None,
                crit=None,
                crit_chance=0.0,
                hit_chance=hit_chance,
                perfect_dodge=0.0,
                dps=misc_dps,
                period_ms=misc_period,
                dps_valid=True,
            )
            self._apply_item_autocasts(misc_br, status, weapon, skill, target, build,
                                       gear_bonuses=gb, profile=profile)
            return misc_br

        if skill_name == "CR_GRANDCROSS":
            gc_result = GrandCrossPipeline(self.config).calculate(
                status, weapon, skill, target, build, gb, profile=profile
            )
            hit_chance = 100.0   # NK_IGNORE_FLEE: skill_db.conf:7508
            perfect_dodge = 0.0
            if skill_data:
                cast_ms, delay_ms = calculate_skill_timing(
                    skill_name, skill.level, skill_data, status, gb, build.support_buffs,
                    server=build.server,
                )
                gc_period = _skill_period_ms(cast_ms, delay_ms, skill_data, skill.level,
                                             profile.skill_min_period_ms.get(skill_name, 0), adelay)
            else:
                gc_period = adelay
            gc_dps = gc_result.avg_damage / gc_period * 1000 if gc_period > 0 else 0.0
            gc_br = BattleResult(
                normal=gc_result,
                magic=gc_result,
                crit=None,
                crit_chance=0.0,
                hit_chance=hit_chance,
                perfect_dodge=perfect_dodge,
                dps=gc_dps,
                period_ms=gc_period,
                dps_valid=True,
            )
            self._apply_item_autocasts(gc_br, status, weapon, skill, target, build,
                                       gear_bonuses=gb, profile=profile)
            return gc_br

        if attack_type == "Magic":
            magic_result = MagicPipeline(self.config).calculate(status, skill, target, build, gb, profile=profile)
            hit_chance, perfect_dodge = calculate_hit_chance(status, target, self.config)
            # Monsters do not have perfect dodge vs player attacks; only player characters do.
            if build.target_mob_id is not None:
                perfect_dodge = 0.0
            # Double Cast: detect early so the period floor is computed correctly up front.
            # Vanilla SC_DOUBLECASTING toggle: MG_COLDBOLT/FIREBOLT/LIGHTNINGBOLT (skill.c:3936-3944).
            # PS: same toggle also covers SOULSTRIKE + EARTHSPIKE (SA_DOUBLEBOLT passive).
            _dc_set = (_DC_SKILLS | _PS_SA_DOUBLEBOLT_SKILLS) if profile is not STANDARD else _DC_SKILLS
            _dc_active = (skill_name in _dc_set
                          and build.active_status_levels.get("SC_DOUBLECASTING", 0) > 0)

            # Compute period and DPS for magic skills.
            # dps_valid=True only for skills with a confirmed ratio in IMPLEMENTED_BF_MAGIC_SKILLS.
            # Both single_period and dc_period are always computed so the DC block can reference
            # them by name. When DC becomes probabilistic, only the weighting changes here.
            if skill_data:
                cast_ms, delay_ms = calculate_skill_timing(
                    skill_name, skill.level, skill_data, status, gb, build.support_buffs,
                    server=build.server,
                )
                _min_period = profile.skill_min_period_ms.get(skill_name, 0)
                single_period = _skill_period_ms(cast_ms, delay_ms, skill_data, skill.level, _min_period, adelay)
                dc_period     = _skill_period_ms(cast_ms, delay_ms, skill_data, skill.level, _min_period, 2 * adelay)
                if skill_name in profile.ps_attack_interval:
                    single_period = profile.ps_attack_interval[skill_name](status, amotion)
                    dc_period     = single_period
            else:
                single_period = adelay
                dc_period     = 2 * adelay
            magic_period = dc_period if _dc_active else single_period
            magic_dps = (magic_result.avg_damage / magic_period * 1000
                         if magic_period > 0 else 0.0)
            magic_br = BattleResult(
                normal=magic_result,   # mirrored so GUI shows steps without changes
                magic=magic_result,
                crit=None,
                crit_chance=0.0,
                hit_chance=hit_chance,
                perfect_dodge=perfect_dodge,
                dps=magic_dps,
                period_ms=float(magic_period),
                dps_valid=skill_name in IMPLEMENTED_BF_MAGIC_SKILLS,
            )
            if _dc_active:
                # Modelled as a proc branch (100% chance) so later systems treat it uniformly.
                # No Hindsight half-level on this path — direct cast, not a Hindsight proc.
                no_dc_build = dataclasses.replace(
                    build,
                    active_status_levels={k: v for k, v in build.active_status_levels.items()
                                         if k != "SC_DOUBLECASTING"},
                )
                dc_result = MagicPipeline(self.config).calculate(
                    status, skill, target, no_dc_build, gb, profile=profile)
                magic_br.proc_branches[PROC_DOUBLE_BOLT] = dc_result
                magic_br.proc_chances[PROC_DOUBLE_BOLT]  = 100.0
                # DPS: main skill consumes the full dc_period; DC second cast fires within it (zero delay).
                magic_br.attacks = [
                    AttackDefinition(float(magic_result.avg_damage), 0.0, float(dc_period), 1.0),
                    AttackDefinition(float(dc_result.avg_damage),    0.0, 0.0,              1.0),
                ]
                magic_br.dps = calculate_dps(magic_br.attacks, FormulaSelectionStrategy())

            # Variable-hit skills: show per-hit as main result + max-count proc_branch.
            # DPS overridden to use max hits × per-hit avg.
            _vhc = _VARIABLE_HIT_SKILLS.get(skill_name)
            if _vhc and skill.level <= len(_vhc):
                max_hits = _vhc[skill.level - 1]
                if max_hits > 1:
                    max_pmf = _scale_floor(magic_result.pmf, max_hits, 1)
                    _mn, _mx, _av = pmf_stats(max_pmf)
                    max_dr = DamageResult()
                    max_dr.pmf = max_pmf
                    max_dr.min_damage = _mn
                    max_dr.max_damage = _mx
                    max_dr.avg_damage = _av
                    magic_br.proc_branches["max_hits"] = max_dr
                    magic_br.proc_chances["max_hits"]  = 100.0
                    magic_br.proc_labels["max_hits"]   = f"Max hits ×{max_hits}"
                    magic_br.dps = (_av / magic_period * 1000
                                    if magic_period > 0 else 0.0)

            self._apply_item_autocasts(magic_br, status, weapon, skill, target, build,
                                       gear_bonuses=gb, profile=profile)
            return magic_br

        # skill_data is not forwarded to _run_branch — it reloads it internally (line 1520)
        # for ForgeBonus hit-count (div) and skill element lookup. This keeps _run_branch's
        # signature uniform across all callers: proc branches, dual-wield, and autocasts
        # don't have skill_data in scope.

        # Crit eligibility and chance
        is_eligible, crit_chance = calculate_crit_chance(status, weapon, skill, target, self.config,
                                                          server=build.server)

        hit_chance, perfect_dodge = calculate_hit_chance(status, target, self.config)
        # Monsters do not have perfect dodge vs player attacks; only player characters do.
        if build.target_mob_id is not None:
            perfect_dodge = 0.0

        # PS mechanic_flags: nk_ignore_flee overrides (e.g. CR_SHIELDBOOMERANG, CR_SHIELDCHARGE).
        # Applied after skills.json hydration so PS can add flags vanilla skill_db doesn't have.
        if f"{skill_name}_NK_IGNORE_FLEE" in profile.mechanic_flags:
            skill.nk_ignore_flee = True
        if skill.nk_ignore_flee:
            hit_chance = 100.0
            perfect_dodge = 0.0

        # PS: Holy Cross accuracy bonus — +2% hit rate per skill level (multiplier, capped at 100%).
        if profile is not STANDARD and skill_name == "CR_HOLYCROSS":
            hit_chance = min(100.0, hit_chance * (1 + 0.02 * skill.level))

        # AS_SONICACCEL: hitpercbonus += 50 on AS_SONICBLOW → hitrate × 1.5 (battle.c:5088, 5129)
        if skill_name == "AS_SONICBLOW" and build.skill_params.get("AS_SONICBLOW_sonic_accel", True):
            hit_chance = min(100.0, hit_chance * 1.5)

        normal = self._run_branch(status, weapon, skill, target, build, is_crit=False, profile=profile, gear_bonuses=gb)
        crit = (self._run_branch(status, weapon, skill, target, build, is_crit=True, profile=profile, gear_bonuses=gb)
                if is_eligible else None)

        # PS: Bowling Bash / Brandish Spear — second hit as a separate pipeline instance.
        # Each skill fires 2 hits; the second hit does NOT benefit from SC_LEXAETERNA
        # (Lex Aeterna doubles only the first consumed hit, then removes itself).
        # Bowling Bash: always fires; Brandish Spear: only when double-hit toggle is on.
        second_hit = None
        second_hit_crit = None
        if profile is not STANDARD:
            _needs_second = (
                skill_name == "KN_BOWLINGBASH"
                or (skill_name == "KN_BRANDISHSPEAR"
                    and build.skill_params.get("KN_BRANDISHSPEAR_double", False))
            )
            if _needs_second:
                _stripped = dataclasses.replace(
                    build,
                    active_status_levels={k: v for k, v in build.active_status_levels.items()
                                         if k != "SC_LEXAETERNA"},
                )
                second_hit = self._run_branch(
                    status, weapon, skill, target, _stripped, is_crit=False, profile=profile, gear_bonuses=gb)
                second_hit_crit = (
                    self._run_branch(status, weapon, skill, target, _stripped,
                                     is_crit=True, profile=profile, gear_bonuses=gb)
                    if is_eligible else None
                )

        # Katar second hit — normal attacks only (skill_id == 0).
        # Source: battle.c:5941-5952 (#ifndef RENEWAL):
        #   temp = pc->checkskill(sd, TF_DOUBLE)
        #   wd.damage2 = wd.damage * (1 + (temp * 2)) / 100
        #   if (wd.damage && !wd.damage2) wd.damage2 = 1;   // pre-renewal minimum
        # Applied AFTER full pipeline (post-CardFix wd.damage); CardFix does NOT run on damage2
        # because flag.lh is set after the CardFix block.
        katar_second = None
        katar_second_crit = None
        if weapon.weapon_type == "Katar" and skill.id == 0:
            tf_level = gb.effective_mastery.get("TF_DOUBLE", 0)
            # AS_KATAR katar second-hit factor contribution (profile-driven).
            # Vanilla: no contribution (factor = 1 + TF_DOUBLE*2 only).
            # PS: AS_KATAR contributes katar_second_factor_per_lv × lv (hardcoded ×4 in _katar_second_hit).
            as_katar_lv = (gb.effective_mastery.get("AS_KATAR", 0)
                           if profile.passive_overrides.get("AS_KATAR", {}).get("katar_second_factor_per_lv", 0)
                           else 0)
            katar_second = self._katar_second_hit(normal, tf_level, as_katar_lv)
            if crit is not None:
                katar_second_crit = self._katar_second_hit(crit, tf_level, as_katar_lv)

        # TF_DOUBLE (Knife) / GS_CHAINACTION (Revolver) double-hit proc branches.
        # Only eligible on normal auto-attacks (skill.id == 0).
        # Crit and proc are mutually exclusive (battle.c:4926).
        # proc_chance = 5 * skill_level  (percent).
        # Source: pc.c pc_checkskill; battle.c:4926 proc vs crit mutex.
        proc_chance = 0.0
        double_hit = None
        double_hit_crit = None
        if skill.id == 0:
            tf_level = gb.effective_mastery.get("TF_DOUBLE", 0)
            gs_level = gb.effective_mastery.get("GS_CHAINACTION", 0)
            if weapon.weapon_type == "Knife" and tf_level > 0:
                proc_chance = profile.proc_rate_overrides.get("TF_DOUBLE", 5.0) * tf_level
            elif weapon.weapon_type == "Revolver" and gs_level > 0:
                proc_chance = profile.proc_rate_overrides.get("GS_CHAINACTION", 5.0) * gs_level
            elif weapon.weapon_type == "Bow" and build.job_id in _ROGUE_JOBS:
                # PS-Arch-7: AC_VULTURE unlocks bow DA for Rogue/Stalker.
                # Effective level = min(vulture_lv, tf_double_lv); rate 7/lv (PS-only).
                vulture_lv = gb.effective_mastery.get("AC_VULTURE", 0)
                eff_lv = min(vulture_lv, tf_level)
                if eff_lv > 0:
                    proc_chance = profile.proc_rate_overrides.get("AC_VULTURE", 0.0) * eff_lv
            elif weapon.weapon_type == "1HSword" and build.job_id in _ROGUE_JOBS:
                # PS-Arch-7: SM_SWORD unlocks 1H sword DA for Rogue/Stalker.
                # Effective level = min(sm_sword_lv, tf_double_lv); rate 7/lv (PS-only).
                sm_sword_lv = gb.effective_mastery.get("SM_SWORD", 0)
                eff_lv = min(sm_sword_lv, tf_level)
                if eff_lv > 0:
                    proc_chance = profile.proc_rate_overrides.get("SM_SWORD", 0.0) * eff_lv
            if proc_chance > 0:
                double_hit = self._run_branch(
                    status, weapon, skill, target, build, is_crit=False, proc_hit_count=2, profile=profile, gear_bonuses=gb)
                if is_eligible:
                    double_hit_crit = self._run_branch(
                        status, weapon, skill, target, build, is_crit=True, proc_hit_count=2, profile=profile, gear_bonuses=gb)

        # Dual-wield branch — normal attack only, Assassin / Assassin Cross.
        # ATK_RATER: RH damage *= (50 + AS_RIGHT_lv*10) / 100  (battle.c:5923-5926)
        # ATK_RATEL: LH damage *= (30 + AS_LEFT_lv*10) / 100   (battle.c:5929-5932)
        # Both have pre-renewal floor of 1 (battle.c:5937-5938, #else branch).
        # LH active when lhw.atk != 0 (battle.c:4861) → Unarmed fallback means atk=0 → skip.
        lh_normal = None
        lh_crit   = None
        if build.job_id in _DUAL_WIELD_JOBS and skill.id == 0:
            as_right_lv = gb.effective_mastery.get("AS_RIGHT", 0)
            as_left_lv  = gb.effective_mastery.get("AS_LEFT", 0)
            # gb.script_atk_ele_lh holds the LH weapon element from bAtkEle item scripts
            # (computed by GearBonusAggregator; see gear_bonus_aggregator.py).
            # pc.c:2588-2609: lr_flag==1 → lhw.ele; gb already computed above.
            lh_weapon = BuildManager.resolve_weapon(
                build.equipped.get("left_hand"),
                build.refine_levels.get("left_hand", 0),
                element_override=None,
                is_forged=build.lh_is_forged,
                forge_sc_count=build.lh_forge_sc_count,
                forge_ranked=build.lh_forge_ranked,
                forge_element=build.lh_forge_element,
                script_atk_ele_rh=gb.script_atk_ele_lh,
            )
            if lh_weapon.weapon_type != "Unarmed":
                # Apply RH penalty rate to existing normal/crit results.
                # PS: rate table overridden via ServerProfile.passive_overrides["AS_RIGHT"]["atk_per_lv"].
                _rh_tbl = profile.passive_overrides.get("AS_RIGHT", {}).get("atk_per_lv")
                rh_rate = (_rh_tbl[as_right_lv - 1] if (_rh_tbl and as_right_lv > 0)
                           else 50 + as_right_lv * 10)
                normal = self._apply_dualwield_rate(normal, rh_rate, "RH", as_right_lv)
                if crit is not None:
                    crit = self._apply_dualwield_rate(crit, rh_rate, "RH", as_right_lv)
                # Compute LH branches and apply LH penalty rate.
                # PS: rate table overridden via ServerProfile.passive_overrides["AS_LEFT"]["atk_per_lv"].
                _lh_tbl = profile.passive_overrides.get("AS_LEFT", {}).get("atk_per_lv")
                lh_rate = (_lh_tbl[as_left_lv - 1] if (_lh_tbl and as_left_lv > 0)
                           else 30 + as_left_lv * 10)
                lh_normal_raw = self._run_branch(status, lh_weapon, skill, target, build, is_crit=False, profile=profile, gear_bonuses=gb)
                lh_normal = self._apply_dualwield_rate(lh_normal_raw, lh_rate, "LH", as_left_lv)
                if is_eligible:
                    lh_crit_raw = self._run_branch(status, lh_weapon, skill, target, build, is_crit=True, profile=profile, gear_bonuses=gb)
                    lh_crit = self._apply_dualwield_rate(lh_crit_raw, lh_rate, "LH", as_left_lv)
                # Proc branches also need ATK_RATER: damage_div_fix only scales wd.damage (RH),
                # then ATK_RATER/ATK_RATEL are applied on top (battle.c:5567 → 5923-5932).
                # LH is NOT doubled by the proc — it contributes its normal value to the proc swing.
                if double_hit is not None:
                    double_hit = self._apply_dualwield_rate(double_hit, rh_rate, "RH", as_right_lv)
                if double_hit_crit is not None:
                    double_hit_crit = self._apply_dualwield_rate(double_hit_crit, rh_rate, "RH", as_right_lv)

        # Auto Blitz Beat proc — normal auto-attack only, Bow weapon, HT_BLITZBEAT > 0.
        # Fires independently of hit/miss/crit/proc on every swing (skill.c:1633-1636).
        # pre_delay=0, post_delay=0 → contributes to DPS numerator only (no time consumed).
        # Source: skill.c:1633-1636 (trigger); battle.c:4242-4247 (damage formula).
        proc_branches: dict = {}
        proc_chances:  dict = {}
        if (skill.id == 0
                and weapon.weapon_type == "Bow"
                and gb.effective_mastery.get("HT_BLITZBEAT", 0) > 0):
            auto_blitz_result, auto_blitz_chance = self._calculate_auto_blitz(status, build, gb)
            proc_branches[PROC_AUTO_BLITZ] = auto_blitz_result
            proc_chances[PROC_AUTO_BLITZ]  = auto_blitz_chance

        # PS_PR_HOLYSTRIKE proc — melee auto-attack, vs Undead/Shadow element.
        # Skill path (Priest only): 20 + floor(luk/10)%, requires PS_PR_HOLYSTRIKE skill > 0.
        # Combo path (any job): gb.holy_strike_bonus_chance from gear (Ancient Mummy + Mummy Card).
        # Both paths stack additively into a single proc branch.
        # Source: payon_stories_plan.md (user-supplied formula, ps_skill_db.json id=2622).
        _HS_JOBS = frozenset({7, 4008})
        _HS_ELEMENTS = frozenset({7, 9})  # 7=Dark(Shadow), 9=Undead
        if (skill.id == 0
                and "PS_HOLYSTRIKE_PROC" in profile.mechanic_flags
                and target.element in _HS_ELEMENTS):
            hs_chance = float(gb.holy_strike_bonus_chance)  # combo: any job
            if build.job_id in _HS_JOBS and gb.effective_mastery.get("PS_PR_HOLYSTRIKE", 0) > 0:
                hs_chance += 20.0 + status.luk // 10       # skill: Priest only
            if hs_chance > 0:
                hs_skill = SkillInstance(id=2622, level=1, name="PS_PR_HOLYSTRIKE")
                proc_branches[PROC_HOLY_STRIKE] = self._run_branch(
                    status, weapon, hs_skill, target, build, is_crit=False, profile=profile, gear_bonuses=gb)
                proc_chances[PROC_HOLY_STRIKE] = hs_chance

        # MO_TRIPLEATTACK proc — normal auto-attack only, MO_TRIPLEATTACK passive > 0.
        # Replaces the normal attack on proc (battle.c:6640 returns ATK_DEF/ATK_MISS early).
        # Vanilla rate: (30 - triple_lv)%. Source: battle.c:6633-6640.
        # PS bonus: +floor(chaincombo_lv/2) + floor(combofinish_lv*2/3). Source: PS server files.
        # ACD when Chain Combo is learned: max(0, 1000 − 4×AGI − 2×DEX) ms (skill.c:3422-3426,
        #   17437); triple_period = max(amotion, that ACD). Without Chain Combo: triple_period = adelay.
        triple_proc_chance = 0.0
        triple_result      = None
        triple_period      = 0.0  # resolved after adelay is computed below
        _triple_lv = gb.effective_mastery.get("MO_TRIPLEATTACK", 0)
        if skill.id == 0 and _triple_lv > 0:
            triple_proc_chance = float(30 - _triple_lv)
            if "MO_TRIPLEATTACK_PS_BONUS" in profile.mechanic_flags:
                _cc_lv = gb.effective_mastery.get("MO_CHAINCOMBO", 0)
                _cf_lv = gb.effective_mastery.get("MO_COMBOFINISH", 0)
                triple_proc_chance += _cc_lv // 2 + _cf_lv * 2 // 3
            _ta_skill = SkillInstance(id=263, level=_triple_lv, name="MO_TRIPLEATTACK")
            triple_result = self._run_branch(
                status, weapon, _ta_skill, target, build, is_crit=False, profile=profile, gear_bonuses=gb)
            proc_branches[PROC_TRIPLE_ATTACK] = triple_result
            proc_chances[PROC_TRIPLE_ATTACK]  = triple_proc_chance

        # DPS calculation.
        # TF_DOUBLE / GS_CHAINACTION proc fires within the same swing, same period.

        # MO_TRIPLEATTACK proc period — resolved here after adelay is available.
        # With Chain Combo learned: canact_tick uses delay_fix(MO_TRIPLEATTACK, lv)
        #   = max(0, 1000 − 4×AGI − 2×DEX) ms (skill.c:3422-3426, 17437).
        #   triple_period = max(adelay, that ACD).
        # Without Chain Combo: only clif->combo_delay(adelay) — no extra ACD.
        if _triple_lv > 0:
            if gb.effective_mastery.get("MO_CHAINCOMBO", 0) > 0:
                _raw_ta_acd = max(0, 1000 - 4 * status.agi - 2 * status.dex)
                triple_period = float(max(adelay, _raw_ta_acd))
            else:
                triple_period = adelay

        # Period: auto-attack uses adelay; skills use max(cast+delay, adelay).
        if skill.id == 0:
            period = adelay
            dps_valid = True
        else:
            cast_ms, delay_ms = calculate_skill_timing(
                skill_name, skill.level, skill_data, status, gb, build.support_buffs,
                server=build.server,
            ) if skill_data else (0, 0)
            period = _skill_period_ms(cast_ms, delay_ms, skill_data, skill.level,
                                      profile.skill_min_period_ms.get(skill_name, 0), adelay)
            if skill_name in profile.ps_attack_interval:
                period = float(profile.ps_attack_interval[skill_name](status, amotion))
            dps_valid = skill_name in IMPLEMENTED_BF_WEAPON_SKILLS

        p    = proc_chance / 100.0         # double-hit additive proc (TF_DOUBLE / GS_CHAINACTION)
        p_ta = triple_proc_chance / 100.0  # triple attack replacement proc (MO_TRIPLEATTACK)
        # Crit, double-hit proc, and triple attack proc are mutually exclusive
        # (triple fires before double-hit; both checked before crit on main swing).
        eff_crit = crit_chance / 100.0 * (1.0 - p - p_ta)
        h        = hit_chance / 100.0

        # Katar: both hits land in the same action — sum for DPS.
        # Dual-wield: both hands land in the same swing — sum RH + LH.
        # PS second hit (Bowling Bash / Brandish Spear): same swing, sum into total.
        normal_avg = (float(normal.avg_damage) + (float(katar_second.avg_damage) if katar_second else 0.0)
                      + (float(lh_normal.avg_damage) if lh_normal else 0.0)
                      + (float(second_hit.avg_damage) if second_hit else 0.0))
        crit_avg   = ((float(crit.avg_damage) + (float(katar_second_crit.avg_damage) if katar_second_crit else 0.0)
                       + (float(lh_crit.avg_damage) if lh_crit else float(lh_normal.avg_damage) if lh_normal else 0.0)
                       + (float(second_hit_crit.avg_damage) if second_hit_crit
                          else float(second_hit.avg_damage) if second_hit else 0.0))
                      if crit else normal_avg)
        # Proc swing: RH is doubled, LH contributes its normal value (proc does not double LH).
        double_avg = (float(double_hit.avg_damage) + (float(lh_normal.avg_damage) if lh_normal else 0.0)) if double_hit else 0.0
        # Triple attack replaces the normal swing — its own _run_branch result, no LH contribution.
        triple_avg = float(triple_result.avg_damage) if triple_result else 0.0

        # Probability tree — sums to 1.0:
        #   crits auto-hit (bypass FLEE), so weight = eff_crit, NOT eff_crit * h.
        #   proc/triple can miss — miss is zero damage but still consumes the full period.
        #   triple_period > period when Chain Combo is learned (extra ACD on triple swing).
        # Future sessions: append AttackDefinition entries here; do not add named fields.
        attacks = [
            AttackDefinition(normal_avg, 0.0, period,        (1.0 - p - p_ta - eff_crit) * h),        # normal hit
            AttackDefinition(0.0,        0.0, period,        (1.0 - p - p_ta - eff_crit) * (1.0 - h)), # normal miss
            AttackDefinition(crit_avg,   0.0, period,        eff_crit),                                 # crit (auto-hit)
            AttackDefinition(double_avg, 0.0, period,        p * h),                                   # double proc hit
            AttackDefinition(0.0,        0.0, period,        p * (1.0 - h)),                           # double proc miss
            AttackDefinition(triple_avg, 0.0, triple_period, p_ta * h),                                # triple proc hit
            AttackDefinition(0.0,        0.0, triple_period, p_ta * (1.0 - h)),                        # triple proc miss
        ]
        # Auto Blitz / Holy Strike fire within the same swing with no extra delay.
        # pre_delay=0, post_delay=0 → contributes to Σ(chance×dmg) but not Σ(chance×time).
        # Triple attack is NOT in this loop — it uses triple_period (replacement, not additive).
        for key, dr in proc_branches.items():
            if key == PROC_TRIPLE_ATTACK:
                continue  # handled in attacks array above with triple_period
            attacks.append(AttackDefinition(float(dr.avg_damage), 0.0, 0.0,
                                            proc_chances[key] / 100.0))
        dps = calculate_dps(attacks, FormulaSelectionStrategy())

        weapon_br = BattleResult(
            normal=normal,
            crit=crit,
            crit_chance=crit_chance,
            hit_chance=hit_chance,
            perfect_dodge=perfect_dodge,
            katar_second=katar_second,
            katar_second_crit=katar_second_crit,
            proc_chance=proc_chance,
            double_hit=double_hit,
            double_hit_crit=double_hit_crit,
            second_hit=second_hit,
            second_hit_crit=second_hit_crit,
            lh_normal=lh_normal,
            lh_crit=lh_crit,
            proc_branches=proc_branches,
            proc_chances=proc_chances,
            dps=dps,
            attacks=attacks,
            period_ms=period,
            dps_valid=dps_valid,
        )
        # Zone-avg weapon skills: add expected-total proc_branch + override DPS.
        # Mirrors WaterBall's max-hits proc_branch pattern for chance-based weapon skills.
        _zone_avg = profile.weapon_avg_hits_by_zone.get(skill_name)
        if _zone_avg:
            zone = build.skill_params.get(f"{skill_name}_zone", 1)
            expected = _zone_avg[min(zone - 1, len(_zone_avg) - 1)]
            num = round(expected * 10)   # e.g. 3.6 → 36 for _scale_floor(pmf, 36, 10)
            avg_pmf = _scale_floor(normal.pmf, num, 10)
            mn, mx, av = pmf_stats(avg_pmf)
            avg_dr = DamageResult(pmf=avg_pmf, min_damage=mn, max_damage=mx, avg_damage=av)
            weapon_br.proc_branches["zone_avg_hits"] = avg_dr
            weapon_br.proc_chances["zone_avg_hits"]  = 100.0
            weapon_br.proc_labels["zone_avg_hits"]   = f"Avg ×{expected:.1f}"
            weapon_br.dps = float(av) / period * 1000 if period > 0 else 0.0

        self._apply_item_autocasts(weapon_br, status, weapon, skill, target, build,
                                   gear_bonuses=gb, profile=profile)
        return weapon_br

    @staticmethod
    def _katar_second_hit(first: DamageResult, tf_level: int, as_katar_lv: int = 0) -> DamageResult:
        """Compute katar second-hit DamageResult from the first hit's final PMF.

        Vanilla: damage2 = max(1, damage1 * (1 + TF_DOUBLE_level * 2) // 100)
        PS:      damage2 = max(1, damage1 * (1 + TF_DOUBLE_level * 2 + AS_KATAR_level * 4) // 100)
        Source: battle.c:5941-5952 (#ifndef RENEWAL)
        """
        factor = 1 + tf_level * 2 + as_katar_lv * 4
        out_pmf: dict = {}
        for dmg, prob in first.pmf.items():
            d2 = max(1, dmg * factor // 100)
            out_pmf[d2] = out_pmf.get(d2, 0.0) + prob
        mn, mx, av = pmf_stats(out_pmf)
        dr = DamageResult()
        dr.pmf = out_pmf
        dr.min_damage = mn
        dr.max_damage = mx
        dr.avg_damage = av
        ps_note = f" + AS_KATAR lv{as_katar_lv}×4 [PS]" if as_katar_lv else ""
        dr.add_step(
            "Katar 2nd Hit",
            value=av, min_value=mn, max_value=mx,
            note=f"TF_DOUBLE lv{tf_level}×2{ps_note}: damage × {factor}÷100, min 1",
            formula=f"max(1, damage * {factor} // 100)",
            hercules_ref="battle.c:5941-5952 (#ifndef RENEWAL): wd.damage2 = wd.damage*(1+(TF_DOUBLE*2))/100",
        )
        return dr

    @staticmethod
    def _apply_dualwield_rate(source: DamageResult, numerator: int, hand: str, skill_lv: int) -> DamageResult:
        """Scale a branch's PMF by the dual-wield hand rate, floor each output to min 1.

        Formula: damage = damage * numerator / 100  (integer division), then max(1, result).
        RH: numerator = 50 + AS_RIGHT_lv*10 (ATK_RATER macro, battle.c:5923-5926)
        LH: numerator = 30 + AS_LEFT_lv*10  (ATK_RATEL macro, battle.c:5929-5932)
        Pre-renewal floor of 1: battle.c:5937-5938 (#else branch, not RENEWAL).
        """
        out_pmf: dict = {}
        for dmg, prob in source.pmf.items():
            scaled = max(1, dmg * numerator // 100)
            out_pmf[scaled] = out_pmf.get(scaled, 0.0) + prob
        mn, mx, av = pmf_stats(out_pmf)
        dr = DamageResult()
        dr.pmf = out_pmf
        dr.min_damage = mn
        dr.max_damage = mx
        dr.avg_damage = av
        # Copy existing steps so the StepsBar shows the full chain.
        dr.steps = list(source.steps)
        skill_key = "AS_RIGHT" if hand == "RH" else "AS_LEFT"
        dr.add_step(
            f"Dual-Wield {hand} Rate",
            value=av, min_value=mn, max_value=mx,
            multiplier=numerator / 100,
            note=f"{skill_key} lv{skill_lv}: damage × {numerator} ÷ 100, floor 1",
            formula=f"max(1, damage * {numerator} // 100)",
            hercules_ref=(
                "battle.c:5923-5926 ATK_RATER: wd.damage * (50+AS_RIGHT*10)/100"
                if hand == "RH" else
                "battle.c:5929-5932 ATK_RATEL: wd.damage2 * (30+AS_LEFT*10)/100"
            ),
        )
        return dr

    @staticmethod
    def _calculate_auto_blitz(status: StatusData, build: PlayerBuild, gear_bonuses: GearBonuses) -> tuple[DamageResult, float]:
        """Auto Blitz Beat proc damage and per-swing proc chance.

        Proc condition: pc_isfalcon + W_BOW weapon + HT_BLITZBEAT > 0 (skill.c:1633)
        Proc chance: (luk*3 + 1) / 10 %, capped at 100% (skill.c:1633: rnd()%1000 <= luk*3)
        Proc level: min(HT_BLITZBEAT_lv, job_level/10 + 1) — sets hit count only (skill.c:1634-1636)
        Damage: (DEX/10 + INT/2 + HT_STEELCROW_lv*3 + 40)*2 — independent of proc level
        Source: battle.c:4242-4247
        """
        blitz_lv    = gear_bonuses.effective_mastery.get("HT_BLITZBEAT", 0)
        steelcrow   = gear_bonuses.effective_mastery.get("HT_STEELCROW", 0)
        proc_level  = min(blitz_lv, build.job_level // 10 + 1)
        proc_chance = min(100.0, (status.luk * 3 + 1) / 10.0)

        profile = get_profile(build.server)
        blitz_override = profile.misc_formulas.get("HT_BLITZBEAT")
        if blitz_override is not None:
            # PS: per-hit = (LUK + INT/2 + 6*HT_STEELCROW + 20)*2; total = per-hit * proc_level.
            avg_dmg = max(1, blitz_override(proc_level, status, None, build)[0])
            blitz_note = (f"LUK={status.luk} INT={status.int_} HT_STEELCROW lv{steelcrow}  →  "
                          f"{proc_level} hit{'s' if proc_level != 1 else ''}  "
                          f"(proc lv = min(HT_BLITZBEAT {blitz_lv}, job_lv {build.job_level}//10+1)) [PS]")
            blitz_formula = (f"(luk + int//2 + steelcrow×6 + 20) × 2 × {proc_level} hits  =  "
                             f"({status.luk} + {status.int_//2} + {steelcrow * 6} + 20) × 2 × {proc_level}")
            blitz_ref = "PS: (LUK + INT/2 + 6*HT_STEELCROW + 20)*2 per hit"
        else:
            avg_dmg = max(1, (status.dex // 10 + status.int_ // 2 + steelcrow * 3 + 40) * 2 * proc_level)
            blitz_note = (f"DEX={status.dex} INT={status.int_} HT_STEELCROW lv{steelcrow}  →  "
                          f"{proc_level} hit{'s' if proc_level != 1 else ''}  "
                          f"(proc lv = min(HT_BLITZBEAT {blitz_lv}, job_lv {build.job_level}//10+1))")
            blitz_formula = (f"(dex//10 + int//2 + steelcrow×3 + 40) × 2 × {proc_level} hits  =  "
                             f"({status.dex//10} + {status.int_//2} + {steelcrow*3} + 40) × 2 × {proc_level}")
            blitz_ref = "battle.c:4242-4247: (dex/10+int_/2+steelcrow*3+40)*2"

        dr = DamageResult()
        dr.min_damage = avg_dmg
        dr.max_damage = avg_dmg
        dr.avg_damage = avg_dmg
        dr.pmf = {avg_dmg: 1.0}
        dr.add_step(
            "Auto Blitz Beat",
            value=avg_dmg, min_value=avg_dmg, max_value=avg_dmg,
            note=blitz_note,
            formula=blitz_formula,
            hercules_ref=blitz_ref,
        )
        return dr, proc_chance

    def _calculate_hindsight(self,
                             status: StatusData,
                             weapon: Weapon,
                             skill: SkillInstance,
                             target: Target,
                             build: PlayerBuild,
                             gear_bonuses: GearBonuses) -> BattleResult:
        """SA_AUTOSPELL (Hindsight): normal auto-attack + memorized magic spell proc.

        Proc chance: 5 + SA_AUTOSPELL_level × 2 percent.
        Source: status.c:7778 (#ifndef RENEWAL): val4 = 5 + val1*2

        Proc level randomisation (battle.c:6784-6792):
          i = rnd()%100
          if i >= 50: skill_lv -= 2   [50% chance → max-2, min 1]
          elif i >= 15: skill_lv -= 1 [35% chance → max-1, min 1]
          else: skill_lv stays        [15% chance → max]
        DPS avg = 0.50×dmg(max-2) + 0.35×dmg(max-1) + 0.15×dmg(max).
        """
        sa_lv = skill.level
        _hs_profile = get_profile(build.server)

        # Run full normal auto-attack pipeline (handles katar/dual-wield/blitz/chainaction).
        auto_result = self.calculate(status, weapon, SkillInstance(id=0), target, build, gear_bonuses)

        # Spell and proc-chance lookup.
        # PS uses _PS_AUTOSPELL_DB (one unlock-level entry per spell); proc chance is flat 30%.
        # Vanilla uses _AUTOSPELL_DB with player-selected spell; proc chance = 5+lv×2%.
        spell_name  = build.skill_params.get("SA_AUTOSPELL_spell", "MG_NAPALMBEAT")
        if _hs_profile is not STANDARD:
            # PS DB stores only the unlock level per spell; find the highest
            # available entry <= sa_lv so spells remain valid above their unlock level.
            lv_dict = _PS_AUTOSPELL_DB.get(spell_name, {})
            valid_keys = [k for k in lv_dict if k <= sa_lv]
            max_proc_lv = lv_dict[max(valid_keys)] if valid_keys else 0
            proc_chance = 30  # PS: flat 30% at all levels (status.c vanilla: 5+2*lv)
        else:
            max_proc_lv = _AUTOSPELL_DB.get(spell_name, {}).get(sa_lv, 0)
            proc_chance = 5 + sa_lv * 2  # status.c:7778

        spell_id = _AUTOSPELL_SPELL_IDS.get(spell_name)

        if max_proc_lv > 0 and spell_id is not None:
            lv_max = max_proc_lv
            lv_m1  = max(1, max_proc_lv - 1)
            lv_m2  = max(1, max_proc_lv - 2)
            r_max = MagicPipeline(self.config).calculate(
                status, SkillInstance(id=spell_id, level=lv_max), target, build, gear_bonuses, profile=_hs_profile)
            r_m1  = (MagicPipeline(self.config).calculate(
                status, SkillInstance(id=spell_id, level=lv_m1), target, build, gear_bonuses, profile=_hs_profile)
                     if lv_m1 < lv_max else r_max)
            r_m2  = (MagicPipeline(self.config).calculate(
                status, SkillInstance(id=spell_id, level=lv_m2), target, build, gear_bonuses, profile=_hs_profile)
                     if lv_m2 < lv_m1 else r_m1)

            weighted_avg = int(round(
                0.15 * r_max.avg_damage +
                0.35 * r_m1.avg_damage  +
                0.50 * r_m2.avg_damage
            ))

            # Build a display DamageResult: max-level steps + weighted avg for DPS.
            proc_dr = DamageResult()
            proc_dr.steps      = list(r_max.steps)
            proc_dr.min_damage = r_m2.min_damage
            proc_dr.max_damage = r_max.max_damage
            proc_dr.avg_damage = weighted_avg
            proc_dr.pmf        = r_max.pmf
            proc_dr.add_step(
                "Autocast Level Variance",
                value=weighted_avg, min_value=r_m2.min_damage, max_value=r_max.max_damage,
                note=(f"15%@lv{lv_max}, 35%@lv{lv_m1}, 50%@lv{lv_m2} → "
                      f"weighted avg {weighted_avg} (used for DPS)"),
                formula="0.15×lv_max + 0.35×max(1,lv-1) + 0.50×max(1,lv-2)",
                hercules_ref="battle.c:6784-6792",
            )

            # Extend proc_branches — auto_result may already have PROC_AUTO_BLITZ.
            auto_result.proc_branches[PROC_AUTOSPELL] = proc_dr
            auto_result.proc_chances[PROC_AUTOSPELL]  = float(proc_chance)

            # Recompute DPS with the added proc entry (zero-delay: fires within same swing).
            auto_result.attacks.append(
                AttackDefinition(float(weighted_avg), 0.0, 0.0, proc_chance / 100.0)
            )
            auto_result.dps = calculate_dps(auto_result.attacks, FormulaSelectionStrategy())

            # Double Cast on Hindsight proc: fires a second bolt at ceil(proc_lv/2).
            # Vanilla SC_DOUBLECASTING toggle: bolt spells only (skill.c:3936-3944).
            # PS: same toggle also covers SOULSTRIKE + EARTHSPIKE (SA_DOUBLEBOLT passive).
            # DC fires iff Hindsight fires → same proc_chance as PROC_AUTOSPELL.
            _hs_dc_set = (_DC_SKILLS | _PS_SA_DOUBLEBOLT_SKILLS) if _hs_profile is not STANDARD else _DC_SKILLS
            if (spell_name in _hs_dc_set
                    and build.active_status_levels.get("SC_DOUBLECASTING", 0) > 0):
                no_dc_build = dataclasses.replace(
                    build,
                    active_status_levels={k: v for k, v in build.active_status_levels.items()
                                         if k != "SC_DOUBLECASTING"},
                )
                dc_lv_max = max(1, (lv_max + 1) // 2)
                dc_lv_m1  = max(1, (lv_m1  + 1) // 2)
                dc_lv_m2  = max(1, (lv_m2  + 1) // 2)

                dc_r_max = MagicPipeline(self.config).calculate(
                    status, SkillInstance(id=spell_id, level=dc_lv_max),
                    target, no_dc_build, gear_bonuses, profile=_hs_profile)
                dc_r_m1 = (MagicPipeline(self.config).calculate(
                    status, SkillInstance(id=spell_id, level=dc_lv_m1),
                    target, no_dc_build, gear_bonuses, profile=_hs_profile)
                           if dc_lv_m1 < dc_lv_max else dc_r_max)
                dc_r_m2 = (MagicPipeline(self.config).calculate(
                    status, SkillInstance(id=spell_id, level=dc_lv_m2),
                    target, no_dc_build, gear_bonuses, profile=_hs_profile)
                           if dc_lv_m2 < dc_lv_m1 else dc_r_m1)

                dc_avg = int(round(
                    0.15 * dc_r_max.avg_damage +
                    0.35 * dc_r_m1.avg_damage  +
                    0.50 * dc_r_m2.avg_damage
                ))
                dc_dr = DamageResult()
                dc_dr.steps      = list(dc_r_max.steps)
                dc_dr.min_damage = dc_r_m2.min_damage
                dc_dr.max_damage = dc_r_max.max_damage
                dc_dr.avg_damage = dc_avg
                dc_dr.pmf        = dc_r_max.pmf
                dc_dr.add_step(
                    "Double Bolt — Level Variance",
                    value=dc_avg, min_value=dc_r_m2.min_damage, max_value=dc_r_max.max_damage,
                    note=(f"ceil(proc_lv/2): lv_max→lv{dc_lv_max}, "
                          f"lv_m1→lv{dc_lv_m1}, lv_m2→lv{dc_lv_m2}; "
                          f"weighted avg {dc_avg}"),
                    formula="ceil(proc_lv/2) per variance tier; flag|2 prevents chain",
                    hercules_ref="skill.c:3936-3944: addtimerskill(tick+amotion, flag|2)",
                )
                auto_result.proc_branches[PROC_DOUBLE_BOLT] = dc_dr
                auto_result.proc_chances[PROC_DOUBLE_BOLT]  = float(proc_chance)
                auto_result.attacks.append(
                    AttackDefinition(float(dc_avg), 0.0, 0.0, proc_chance / 100.0)
                )
                auto_result.dps = calculate_dps(auto_result.attacks, FormulaSelectionStrategy())

        return auto_result

    def _apply_item_autocasts(
        self,
        result: BattleResult,
        status: StatusData,
        weapon: Weapon,
        skill: SkillInstance,
        target: Target,
        build: PlayerBuild,
        gear_bonuses: GearBonuses,
        profile: ServerProfile,
    ) -> None:
        """Append item autocast proc branches to result in-place.

        bAutoSpell: fires on Normal Attack only (skill.id == 0); ranged attacks halve the chance.
          Source: skill.c:2472-2473 (BF_WEAPON|BF_NORMAL trigger), skill.c:2491 (arrow halving)
        bAutoSpellOnSkill: fires when src_skill_id matches the active skill (any attack type).
          Source: skill.c:2609-2671 (autospell3 loop), pc.c:4215 (SP_AUTOSPELL_ONSKILL)

        Does NOT call calculate() to prevent recursion into _apply_item_autocasts.
        """

        specs_to_run: list[tuple[str, AutocastSpec, float]] = []
        is_ranged = _resolve_is_ranged(build, weapon, skill)

        # bAutoSpell: attack-time procs — only on Normal Attack (skill.id == 0).
        # Source: pc.c:2136 — default flag sets BF_WEAPON|BF_NORMAL, blocked by skill attacks.
        if skill.id == 0:
            for idx, spec in enumerate(gear_bonuses.autocast_on_attack):
                rate = spec.chance_per_mille
                if is_ranged:
                    rate = rate // 2  # skill.c:2491: rate /= 2 when sd->state.arrow_atk
                chance_pct = rate / 10.0
                specs_to_run.append((f"autocast_atk_{idx}", spec, chance_pct))

        # bAutoSpellOnSkill: fires when src_skill_id matches the active skill.
        # No ranged halving in the autospell3 path. Source: skill.c:2609-2671.
        for idx, spec in enumerate(gear_bonuses.autocast_on_skill):
            if spec.src_skill_id == skill.id:
                chance_pct = spec.chance_per_mille / 10.0
                specs_to_run.append((f"autocast_skill_{idx}", spec, chance_pct))

        if not specs_to_run:
            return

        for key, spec, chance_pct in specs_to_run:
            proc_dr = self._run_autocast_spell(spec, status, weapon, target, build,
                                               gear_bonuses=gear_bonuses, profile=profile)
            result.proc_branches[key] = proc_dr
            result.proc_chances[key] = chance_pct
            # Human-readable label — server-aware via G208 resolver.
            skill_data = loader.get_skill(spec.skill_id)
            constant = skill_data.get("name", "") if skill_data else ""
            desc = (loader.get_skill_display_name(constant, profile)
                    if constant else f"Skill {spec.skill_id}")
            result.proc_labels[key] = f"{desc} Lv.{spec.skill_level}"
            # DPS contribution — zero delay: fires within the same swing.
            result.attacks.append(
                AttackDefinition(float(proc_dr.avg_damage), 0.0, 0.0, chance_pct / 100.0)
            )

        # Recompute DPS with added proc entries.
        result.dps = calculate_dps(result.attacks, FormulaSelectionStrategy())

    def _run_autocast_spell(
        self,
        spec: AutocastSpec,
        status: StatusData,
        weapon: Weapon,
        target: Target,
        build: PlayerBuild,
        gear_bonuses: GearBonuses,
        profile: ServerProfile,
    ) -> DamageResult:
        """Run a single autocast spec through the appropriate pipeline branch.

        Routes to MagicPipeline for Magic attack_type; _run_branch() for everything else.
        Does NOT call calculate() — no recursion into _apply_item_autocasts.
        No-damage spells (unimplemented skills, status-effect-only spells) produce a
        non-zero result from the weapon pipeline; DPS contribution is whatever the
        pipeline outputs for an unimplemented skill ratio.
        """
        proc_skill_data = loader.get_skill(spec.skill_id)
        proc_skill = SkillInstance(id=spec.skill_id, level=spec.skill_level)

        attack_type = "Weapon"
        if proc_skill_data:
            attack_type = proc_skill_data.get("attack_type", "Weapon")
            proc_skill.name = proc_skill_data.get("name", "")
            damage_type = proc_skill_data.get("damage_type", [])
            proc_skill.nk_ignore_def  = "IgnoreDefense" in damage_type
            proc_skill.nk_ignore_flee = "IgnoreFlee" in damage_type
            proc_skill.ignore_size_fix = proc_skill.name in {"MO_EXTREMITYFIST"}

        if attack_type == "Magic":
            return MagicPipeline(self.config).calculate(status, proc_skill, target, build,
                                                        gear_bonuses, profile=profile)
        else:
            return self._run_branch(status, weapon, proc_skill, target, build, is_crit=False,
                                    gear_bonuses=gear_bonuses, profile=profile)

    def _run_misc_branch(self,
                         status: StatusData,
                         skill: SkillInstance,
                         target: Target,
                         build: PlayerBuild,
                         skill_name: str,
                         skill_data: dict,
                         is_ranged: bool,
                         gear_bonuses: GearBonuses,
                         profile: ServerProfile) -> DamageResult:
        """BF_MISC damage pipeline: flat formula → CardFix → AttrFix (unless IgnoreElement).
        No BaseDamage, no SkillRatio, no DEF reduction.
        Source: battle.c:4169 battle_calc_misc_attack.
        """
        result = DamageResult()
        formula_fn = profile.misc_formulas.get(skill_name) or _BF_MISC_FORMULAS.get(skill_name)
        min_dmg, max_dmg = formula_fn(skill.level, status, target, build, gb=gear_bonuses)
        min_dmg = max(1, min_dmg)
        max_dmg = max(min_dmg, max_dmg)

        pmf = _uniform_pmf(min_dmg, max_dmg)
        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            "BF_MISC Damage", value=av, min_value=mn, max_value=mx,
            note=f"{skill_name} flat formula (range [{min_dmg}, {max_dmg}])",
            formula=f"[{min_dmg}, {max_dmg}]",
            hercules_ref="battle.c:4169 battle_calc_misc_attack",
        )

        # Resolve attack element for CardFix (bAddAtkEle) and AttrFix.
        # Default 0=Neutral (battle.c:4207-4213: s_ele<0 → ELE_NEUTRAL).
        eff_atk_ele = 0
        if skill_data:
            ele_list = skill_data.get("element", [])
            if ele_list:
                idx = min(skill.level - 1, len(ele_list) - 1)
                v = _ELE_STR_TO_INT.get(ele_list[idx])
                if v is not None:
                    eff_atk_ele = v

        # CardFix: attacker-side race/ele/size/long_atk/atk_ele bonuses (battle.c:4523).
        # AM_SPHEREMINE bypasses CardFix — damage is a raw formula; only AttrFix applies.
        if skill_name != "AM_SPHEREMINE":
            pmf = CardFix.calculate(build, gear_bonuses, eff_atk_ele, target, is_ranged, pmf, result)

        # bSkillAtk: after cardfix, before attr_fix. battle.c:4535 (after calc_cardfix 4523, before attr_fix 4557)
        if skill_atk_bonus := gear_bonuses.skill_atk.get(skill_name, 0):
            pmf = _scale_floor(pmf, 100 + skill_atk_bonus, 100)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                name="Skill ATK Bonus",
                value=av, min_value=mn, max_value=mx,
                multiplier=(100 + skill_atk_bonus) / 100.0,
                note=f"bSkillAtk: {skill_name} +{skill_atk_bonus}%",
                formula=f"dmg × (100 + {skill_atk_bonus}) / 100",
                hercules_ref="pc.c:3513-3527 SP_SKILL_ATK; battle.c:4535 md.damage += md.damage*modifier/100 (after calc_cardfix 4523, before attr_fix 4557)",
            )

        # AttrFix: skipped if IgnoreElement (NK_NO_ELEFIX) — battle.c:4558
        damage_types = skill_data.get("damage_type", []) if skill_data else []
        if "IgnoreElement" not in damage_types:
            pmf = AttrFix.calculate(None, target, pmf, result, build, atk_element=eff_atk_ele)

        # PR_LEXAETERNA ×2
        if target.target_active_scs.get("PR_LEXAETERNA"):
            pmf = _scale_floor(pmf, 2, 1)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                "Lex Aeterna", value=av, min_value=mn, max_value=mx,
                multiplier=2.0, note="PR_LEXAETERNA doubles next hit",
                formula="dmg × 2", hercules_ref="status.c:8490",
            )

        # === DAMAGE-RECEIVED BONUS (Mailbreaker, Venom Dust, Raided — multiplicative) ===
        if target.mailbreaker:
            pmf = _scale_floor(pmf, 110, 100)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                "Mailbreaker", value=av, min_value=mn, max_value=mx,
                multiplier=1.1, note="+10% damage taken (Mailbreaker debuff; no bosses)",
                formula="dmg × 110 ÷ 100", hercules_ref="G112",
            )
        if target.venom_dust:
            pmf = _scale_floor(pmf, 110, 100)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                "Venom Dust", value=av, min_value=mn, max_value=mx,
                multiplier=1.1, note="+10% damage taken (Venom Dust debuff)",
                formula="dmg × 110 ÷ 100", hercules_ref="G112",
            )
        if target.raided:
            pmf = _scale_floor(pmf, 110, 100)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                "Raided", value=av, min_value=mn, max_value=mx,
                multiplier=1.1, note="+10% damage taken (Raided debuff)",
                formula="dmg × 110 ÷ 100", hercules_ref="G112",
            )

        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            "Final Damage", value=av, min_value=mn, max_value=mx,
            note="BF_MISC branch", formula="", hercules_ref="",
        )
        result.min_damage = mn
        result.max_damage = mx
        result.avg_damage = av
        result.pmf = pmf
        return result

    def _run_branch(self,
                    status: StatusData,
                    weapon: Weapon,
                    skill: SkillInstance,
                    target: Target,
                    build: PlayerBuild,
                    is_crit: bool,
                    proc_hit_count: int = 1,
                    profile: ServerProfile = STANDARD,
                    gear_bonuses: GearBonuses = None) -> DamageResult:
        """Run a single damage branch (normal or crit) through the full modifier chain.

        proc_hit_count > 1: for proc skills (e.g. Triple Attack, Blitz Beat) that deal
        multiple hits with the same base PMF — SkillRatio hit count is multiplied by this
        value rather than running the pipeline multiple times.
        Output: DamageResult with all steps recorded; caller stores it in BattleResult.
        """
        result = DamageResult()
        is_ranged = _resolve_is_ranged(build, weapon, skill)

        # Informational input steps — show values entering the pipeline
        result.add_step(
            "Status BATK", status.batk,
            note=f"STR={status.str} DEX={status.dex}",
            formula="str + (str//10)^2 + dex//5 + luk//5",
            hercules_ref="status.c: status_calc_batk (pre-renewal)",
        )
        result.add_step(
            "Weapon ATK", weapon.atk,
            note=f"Raw weapon ATK from item_db (wa->atk); refine bonus applied post-defense as RefineFix",
            formula="weapon.atk",
            hercules_ref="battle.c: atkmax = wa->atk (inside battle_calc_base_damage2 for PC)",
        )
        if is_crit:
            result.add_step(
                "Branch", 0,
                note="CRIT BRANCH — damage=atkmax, DEF bypassed",
                formula="flag.cri=1",
                hercules_ref="battle.c:4988-4989 (#ifndef RENEWAL): flag.idef=flag.idef2=flag.hit=1",
            )

        ctx = CalcContext(
            skill_levels=gear_bonuses.effective_mastery,
            skill_params=build.skill_params,
            base_level=build.base_level,
            base_str=build.base_str,
            str_=status.str,
            vit=status.vit,
            dex=status.dex,
            int_=status.int_,
            weapon_type=weapon.weapon_type if weapon else "",
        )        # CalcContext — used by MasteryFix and SkillRatio
        hit_count = 1     # actual hit count from SkillRatio; used by ForgeBonus and sphere/coin bonus

        # === NJ_ISSEN — pre-renewal fixed HP-based damage formula ===
        # battle.c:5173 (#ifndef RENEWAL): wd.damage = 40*sstatus->str + skill_lv*(sstatus->hp/10+35)
        # Completely replaces BaseDamage + SkillRatio; continues through rest of pipeline normally.
        if skill.name == "NJ_ISSEN":
            hp = build.skill_params.get("NJ_ISSEN_current_hp") or status.max_hp
            fixed_dmg = 40 * status.str + skill.level * (hp // 10 + 35)
            pmf: dict = {fixed_dmg: 1.0}
            result.add_step(
                "NJ_ISSEN Damage", fixed_dmg,
                min_value=fixed_dmg, max_value=fixed_dmg,
                note=f"STR={status.str}  HP={hp}  Lv={skill.level}",
                formula=f"40×{status.str} + {skill.level}×({hp}//10 + 35) = {fixed_dmg}",
                hercules_ref="battle.c:5173 #ifndef RENEWAL: wd.damage = 40*sstatus->str + skill_lv*(sstatus->hp/10+35)",
            )
            # === PS NJ_ISSEN Mirror Image bonus ===
            # n = attacks_left from Mirror Image (NJ_UTSUSEMI); 0 = not active → no bonus.
            # n≥1: damage × (105+5×n)/100. Source: user-confirmed; 10-30% over 5 stacks.
            if "NJ_ISSEN_MIRROR_BONUS" in profile.mechanic_flags:
                _n = build.skill_params.get("NJ_ISSEN_attacks_left", 0)
                if _n and _n >= 1:
                    _mi_num = 105 + 5 * _n
                    _mi_dmg = fixed_dmg * _mi_num // 100
                    pmf = {_mi_dmg: 1.0}
                    result.add_step(
                        "Mirror Image Bonus", _mi_dmg,
                        min_value=_mi_dmg, max_value=_mi_dmg,
                        multiplier=_mi_num / 100,
                        note=f"Mirror Image attacks_left={_n} → ×{_mi_num}%",
                        formula=f"{fixed_dmg} × {_mi_num} // 100 = {_mi_dmg}",
                        hercules_ref="ps_skill_db.json id=544 (user-confirmed)",
                    )
        elif skill.name == "CR_SHIELDBOOMERANG":
            # battle.c:4712-4715 (#ifndef RENEWAL): flag.weapon = 0 — suppresses weapon ATK + SizeFix.
            # battle.c:5228-5235: wd.damage = batk; ATK_ADD(sd->inventory_data[shield]->weight / 10)
            # SkillRatio still applies normally: skillratio += 30*skill_lv (battle.c:2167-2168).
            # Weapon mastery (add_mastery, battle.c:834) runs unconditionally based on equipped weapon.
            # RefineFix skipped (weapon refine N/A); shield refine added post-CardFix (battle.c:5876-5880).
            # Star crumbs explicitly excluded: battle.c:917 — ForgeBonus skipped.
            _shield_id = build.equipped.get("left_hand")
            _shield_item = loader.get_item(_shield_id) if _shield_id else None
            _shield_wt = (_shield_item["weight"] // 10) if _shield_item else 0
            _sb_base = status.batk + _shield_wt
            pmf = {_sb_base: 1.0}
            result.add_step(
                "Shield Base Damage", _sb_base,
                min_value=_sb_base, max_value=_sb_base,
                note=f"BATK={status.batk} + shield weight({_shield_wt * 10})÷10={_shield_wt}",
                formula=f"batk + shield_weight//10 = {status.batk} + {_shield_wt} = {_sb_base}",
                hercules_ref="battle.c:5228-5235 #ifndef RENEWAL: wd.damage=batk; ATK_ADD(weight/10)",
            )
            pmf, hit_count = SkillRatio.calculate(skill, pmf, build, result, target, weapon=weapon,
                                                   profile=profile, ctx=ctx, gear_bonuses=gear_bonuses)

        else:
            # === BASE DAMAGE — mirrors battle_calc_base_damage2 exactly ===
            # SizeFix is applied inside this step before batk (A4 fix).
            # Crit branch: damage = atkmax (no roll). Overrefine still randomizes.
            pmf: dict = BaseDamage.calculate(status, weapon, build, target, skill, result,
                                             is_crit=is_crit)

            # === bWeaponAtk — inside battle_calc_base_damage2 after overrefine ===
            # battle.c:676-686: if (sd->weapon_atk_rate[weapontype]) damage += damage * rate / 100;
            _herc_wtype = _WEAPON_TYPE_TO_HERC.get(weapon.weapon_type, "")
            _watk_rate = gear_bonuses.weapon_atk_rate.get(_herc_wtype, 0)
            if _watk_rate:
                pmf = _scale_floor(pmf, 100 + _watk_rate, 100)
                mn, mx, av = pmf_stats(pmf)
                result.add_step(
                    "bWeaponAtk",
                    value=av, min_value=mn, max_value=mx,
                    multiplier=(100 + _watk_rate) / 100,
                    note=f"bWeaponAtk +{_watk_rate}% for {weapon.weapon_type} ({_herc_wtype})",
                    formula=f"dmg * (100 + {_watk_rate}) // 100",
                    hercules_ref="battle.c:676-686: damage += damage * sd->weapon_atk_rate[weapontype] / 100",
                )

            # === bAtkRate — #ifndef RENEWAL, battle.c:5330 (pre-skill-ratio) ===
            # ATK_ADDRATE(sd->bonus.atk_rate) applied before SkillRatio in the default case.
            if gear_bonuses.atk_rate:
                pmf = _scale_floor(pmf, 100 + gear_bonuses.atk_rate, 100)
                mn, mx, av = pmf_stats(pmf)
                result.add_step(
                    "bAtkRate",
                    value=av,
                    min_value=mn,
                    max_value=mx,
                    multiplier=(100 + gear_bonuses.atk_rate) / 100,
                    note=f"bAtkRate +{gear_bonuses.atk_rate}% (from gear — applied before Skill Ratio)",
                    formula=f"dmg * (100 + {gear_bonuses.atk_rate}) // 100",
                    hercules_ref="battle.c:5330 #ifndef RENEWAL: ATK_ADDRATE(sd->bonus.atk_rate)",
                )

            # === SKILL RATIO ===
            pmf, hit_count = SkillRatio.calculate(skill, pmf, build, result, target, weapon=weapon,
                                                   profile=profile, ctx=ctx, gear_bonuses=gear_bonuses)

            # === GS_MAGICALBULLET: ATK_ADD(matk_max) — #ifndef RENEWAL (battle.c:5503-5505) ===
            # Applies after skill ratio, pre-defense. Uses max MATK (status->get_matk(src, 2)).
            if skill.name == "GS_MAGICALBULLET":
                pmf = _add_flat(pmf, status.matk_max)
                mn, mx, av = pmf_stats(pmf)
                result.add_step(
                    "MATK Add", value=av, min_value=mn, max_value=mx,
                    note=f"GS_MAGICALBULLET: ATK_ADD(MATK={status.matk_max})",
                    formula=f"dmg + {status.matk_max}",
                    hercules_ref="battle.c:5503-5505 #ifndef RENEWAL",
                )

            # === PROC HIT COUNT — mirrors damage_div_fix at battle.c:5567 (#ifndef RENEWAL) ===
            # For TF_DOUBLE / GS_CHAINACTION proc branches: proc_hit_count=2 doubles the total.
            # Normal auto-attacks and skill branches keep the default proc_hit_count=1 (no-op).
            if proc_hit_count > 1:
                pmf = _scale_floor(pmf, proc_hit_count, 1)
                mn, mx, av = pmf_stats(pmf)
                result.add_step(
                    "Proc ×2",
                    value=av, min_value=mn, max_value=mx,
                    multiplier=float(proc_hit_count),
                    note=f"Double-hit proc: ×{proc_hit_count} hits",
                    formula=f"dmg * {proc_hit_count}",
                    hercules_ref="battle.c:5567 (#ifndef RENEWAL): damage_div_fix",
                )

        # === PS RG_BACKSTAP OPPORTUNITY — ×1.4 when opportunity toggle active ===
        # Payon Stories: Backstab ×1.4 when attack comes from Opportunity (RG_QUICKSTEP).
        # User-toggled via skill_param "RG_BACKSTAP_opportunity" (only visible in PS mode).
        # Placement: after SkillRatio, before DefenseFix (same position as Lex Aeterna concept:
        # multiplicative on the skill damage).
        if ("RG_BACKSTAP_OPPORTUNITY_BONUS" in profile.mechanic_flags
                and skill.name == "RG_BACKSTAP"
                and build.skill_params.get("RG_BACKSTAP_opportunity")):
            pmf = _scale_floor(pmf, 140, 100)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                "Opportunity ×1.4", value=av, min_value=mn, max_value=mx,
                multiplier=1.4,
                note="PS: RG_BACKSTAP from Opportunity (RG_QUICKSTEP) → ×1.4",
                formula="dmg × 140 // 100",
                hercules_ref="PayonStoriesData/skill_database_flat.jsonl — RG_BACKSTAP Opportunity bonus",
            )

        # === PS BA_MUSICALSTRIKE PERFORMING BONUS ===
        # Payon Stories: +100 ratio when caster is performing (Bard active in song).
        # Base PS ratio is 175+25*lv; performing → 275+25*lv.
        # Applied as (275+25*lv)/(175+25*lv) scale after SkillRatio has already applied the base.
        # Source: payon_stories_plan.md — Musical Strike Performing Bonus.
        if ("BA_MUSICALSTRIKE_PERFORMING_BONUS" in profile.mechanic_flags
                and skill.name == "BA_MUSICALSTRIKE"
                and build.skill_params.get("BA_MUSICALSTRIKE_performing")):
            base_ratio = 175 + 25 * skill.level
            performing_ratio = base_ratio + 100
            pmf = _scale_floor(pmf, performing_ratio, base_ratio)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                "Performing Bonus", value=av, min_value=mn, max_value=mx,
                multiplier=round(performing_ratio / base_ratio, 4),
                note=f"PS: BA_MUSICALSTRIKE performing → ratio {base_ratio}% → {performing_ratio}%",
                formula=f"dmg × {performing_ratio} // {base_ratio}",
                hercules_ref="PayonStoriesData/skill_database_flat.jsonl — BA_MUSICALSTRIKE performing bonus",
            )

        # === PS DC_THROWARROW PERFORMING BONUS ===
        # Payon Stories: +100 ratio when caster is performing (Dancer active in dance).
        # Base PS ratio is 175+25*lv; performing → 275+25*lv.
        # Applied as (275+25*lv)/(175+25*lv) scale after SkillRatio has already applied the base.
        if ("DC_THROWARROW_PERFORMING_BONUS" in profile.mechanic_flags
                and skill.name == "DC_THROWARROW"
                and build.skill_params.get("DC_THROWARROW_performing")):
            base_ratio = 175 + 25 * skill.level
            performing_ratio = base_ratio + 100
            pmf = _scale_floor(pmf, performing_ratio, base_ratio)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                "Performing Bonus", value=av, min_value=mn, max_value=mx,
                multiplier=round(performing_ratio / base_ratio, 4),
                note=f"PS: DC_THROWARROW performing → ratio {base_ratio}% → {performing_ratio}%",
                formula=f"dmg × {performing_ratio} // {base_ratio}",
                hercules_ref="PayonStoriesData/skill_balance_full.md — DC_THROWARROW performing bonus",
            )

        # === SC_CLOAKING DAMAGE BONUS (profile-driven via mechanic_flags) ===
        # Auto-attack from Cloaking: ×2 damage (JSONL id=135).
        # AS_SONICBLOW while Cloaking: ×1.1 damage (JSONL id=136).
        if "SC_CLOAKING_BONUS" in profile.mechanic_flags and build.active_status_levels.get("SC_CLOAKING"):
            if skill.id == 0:
                pmf = _scale_floor(pmf, 200, 100)
                mn, mx, av = pmf_stats(pmf)
                result.add_step(
                    "Cloaking ×2", value=av, min_value=mn, max_value=mx,
                    multiplier=2.0,
                    note="PS: first auto-attack from Cloaking state — ×2 damage",
                    formula="dmg × 200 // 100",
                    hercules_ref="PayonStoriesData/skill_database_flat.jsonl id=135 — AS_CLOAKING",
                )
            elif skill.name == "AS_SONICBLOW":
                pmf = _scale_floor(pmf, 110, 100)
                mn, mx, av = pmf_stats(pmf)
                result.add_step(
                    "Cloaking ×1.1", value=av, min_value=mn, max_value=mx,
                    multiplier=1.1,
                    note="PS: AS_SONICBLOW while Cloaking — +10% damage",
                    formula="dmg × 110 // 100",
                    hercules_ref="PayonStoriesData/skill_database_flat.jsonl id=136 — AS_SONICBLOW cloaking bonus",
                )

        # === CRIT ATK RATE — pre-defense, crit branch only (battle.c:5333) ===
        if is_crit:
            pmf = CritAtkRate.calculate(build, pmf, result, weapon=weapon, profile=profile, skill=skill, gb=gear_bonuses)

        # === DEFENSE FIX — skipped entirely on crit or NK_IGNORE_DEF (flag.idef=flag.idef2=1) ===
        pmf = DefenseFix.calculate(target, build, gear_bonuses, pmf, self.config, result,
                                   is_crit=is_crit, skill=skill)

        # === MO_EXTREMITYFIST DEF REDUCTION (profile-driven via mechanic_flags) ===
        # Applied post-DefenseFix when MO_EXTREMITYFIST_NK_NORMAL_DEF is set.
        # Vanilla skips DefenseFix via nk_ignore_def=True; profile clears that flag and
        # applies this reduction instead.
        # Source: PayonStoriesData/skill_database_flat.jsonl — MO_EXTREMITYFIST
        if "MO_EXTREMITYFIST_NK_NORMAL_DEF" in profile.mechanic_flags and skill.name == "MO_EXTREMITYFIST":
            factor_num = max(0, 100 - target.def_)
            pmf = _scale_floor(pmf, factor_num, 100)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                "EF DEF Reduction", value=av, min_value=mn, max_value=mx,
                multiplier=factor_num / 100,
                note=f"PS: MO_EXTREMITYFIST × max(0, 100 - DEF={target.def_}) / 100",
                formula=f"dmg × max(0, 100 - {target.def_}) // 100 = dmg × {factor_num} // 100",
                hercules_ref="PayonStoriesData/skill_database_flat.jsonl — MO_EXTREMITYFIST",
            )

        # === ACTIVE STATUS BONUSES — POST-defense (lines 5770-5795) ===
        pmf = ActiveStatusBonus.calculate(weapon, build, skill, pmf, result, profile=profile)

        # === REFINE BONUS (atk2) — POST-defense, PRE-mastery (lines 5803-5805) ===
        # A6 fix: moved out of BaseDamage to its correct Hercules position.
        # CR_SHIELDBOOMERANG: weapon refine N/A (flag.weapon=0); shield refine handled post-CardFix.
        if skill.name != "CR_SHIELDBOOMERANG":
            pmf = RefineFix.calculate(weapon, skill, pmf, result)

        # === MASTERY FIX — #ifndef RENEWAL, lines 5812-5818 ===
        pmf = MasteryFix.calculate(weapon, build, target, pmf, result, skill, profile=profile, ctx=ctx)

        # === ATTR FIX ===
        # Resolve attacking element — battle.c:4807: s_ele = skill_id ? skill->get_ele() : -1
        # If get_ele() returns -1 (Ele_Weapon), weapon element is used — this is the default path.
        # If get_ele() returns a fixed element (e.g. Ele_Poison for TF_POISON), that element wins.
        # Ele_Weapon / Ele_Endowed / Ele_Random are absent from _ELE_STR_TO_INT → None → weapon.element.
        skill_data = loader.get_skill(skill.id)  # also used by ForgeBonus below
        eff_atk_ele = weapon.element
        if skill.id != 0 and skill_data:
            ele_list = skill_data.get("element", [])
            if ele_list:
                idx = min(skill.level - 1, len(ele_list) - 1)
                v = _ELE_STR_TO_INT.get(ele_list[idx])
                if v is not None:
                    eff_atk_ele = v
        # PS skill element override — after standard resolution so it takes precedence.
        if skill.name in profile.skill_elements:
            eff_atk_ele = profile.skill_elements[skill.name]
        # PS: Gunslingers cannot receive weapon endow/converter.
        # Only blocks when eff_atk_ele came from weapon.element (not a skill-fixed element),
        # and an endow was actually applied (build.weapon_element is not None).
        # GS weapons are Neutral base; restoring to 0 undoes any endow override.
        # Source: PayonStoriesData — GS job 24 cannot be weapon-endowed.
        if ("GS_BLOCK_ENDOW" in profile.mechanic_flags
                and build.job_id == 24
                and build.weapon_element is not None
                and eff_atk_ele == weapon.element):
            eff_atk_ele = 0  # Neutral — ignore endow/converter
        pmf = AttrFix.calculate(weapon, target, pmf, result, build, atk_element=eff_atk_ele)

        # === FORGE BONUS — flat star ATK × div, after AttrFix, before CardFix ===
        # Source: battle.c:5864 (#ifndef RENEWAL): ATK_ADD2(wd.div_*right_weapon.star, ...)
        # CR_SHIELDBOOMERANG explicitly excluded: battle.c:917 — if(skill_id != CR_SHIELDBOOMERANG)
        # div = hit_count from SkillRatio (authoritative — includes _BF_WEAPON_HIT_COUNT_FN overrides).
        div = hit_count
        if skill.name != "CR_SHIELDBOOMERANG":
            pmf = ForgeBonus.calculate(weapon, div, pmf, result)

        # === SPIRIT SPHERE BONUS — +3 ATK per sphere per hit ===
        # Source: battle.c:5865-5868 (#ifndef RENEWAL):
        #   if skill==MO_FINGEROFFENSIVE: ATK_ADD(wd.div_*sd->spiritball_old*3)
        #   else:                         ATK_ADD(wd.div_*sd->spiritball*3)
        # MO_FINGEROFFENSIVE uses spiritball_old (spheres at attack start → skill_params);
        # all other skills use the current sphere count (active_status_levels).
        _skill_name = (skill_data.get("name", "") if skill_data else "")
        if _skill_name == "MO_FINGEROFFENSIVE":
            _spheres = int(build.skill_params.get("MO_FINGEROFFENSIVE_spheres", 0))
        else:
            # GS coins also use sd->spiritball; stored as GS_COINS in active_status_levels.
            _spheres = (int(build.active_status_levels.get("MO_SPIRITBALL", 0))
                        or int(build.active_status_levels.get("GS_COINS", 0)))
        if _spheres > 0:
            _is_coins = bool(build.active_status_levels.get("GS_COINS", 0))
            _step_label = "Coin Bonus" if _is_coins else "Spirit Sphere Bonus"
            _unit = "coin(s)" if _is_coins else "sphere(s)"
            _sphere_flat = _spheres * div * 3
            pmf = {k + _sphere_flat: v for k, v in pmf.items()}
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                _step_label,
                value=av, min_value=mn, max_value=mx,
                note=f"{_spheres} {_unit} × div({div}) × 3 = +{_sphere_flat} flat",
                formula=f"spiritball({_spheres}) × div({div}) × 3 = +{_sphere_flat}",
                hercules_ref="battle.c:5865-5868 (#ifndef RENEWAL): ATK_ADD(wd.div_*spiritball*3)",
            )

        # === CARD FIX — race/ele/size/long_atk/atk_ele bonuses; target resist (PvP) ===
        pmf = CardFix.calculate(build, gear_bonuses, eff_atk_ele, target, is_ranged, pmf, result)

        # === CR_SHIELDBOOMERANG: shield refine bonus — applied AFTER CardFix (sd side) ===
        # Source: battle.c:5876-5880 (#ifndef RENEWAL):
        #   if (skill_id == CR_SHIELDBOOMERANG) ATK_ADD(10 * sd->status.inventory[shield_idx].refine)
        if skill.name == "CR_SHIELDBOOMERANG":
            _shield_refine = build.refine_levels.get("left_hand", 0)
            if _shield_refine:
                pmf = _add_flat(pmf, 10 * _shield_refine)
                mn, mx, av = pmf_stats(pmf)
                result.add_step(
                    "Shield Refine Bonus", av,
                    min_value=mn, max_value=mx,
                    note=f"Shield +{_shield_refine} × 10 = +{10 * _shield_refine} ATK (post-CardFix)",
                    formula=f"dmg + 10 × {_shield_refine} = dmg + {10 * _shield_refine}",
                    hercules_ref="battle.c:5876-5880 #ifndef RENEWAL: ATK_ADD(10*inventory[shield].refine)",
                )

        # === FINAL RATE BONUS ===
        pmf = FinalRateBonus.calculate(is_ranged, pmf, self.config, result)

        # === PS: SC_COMBOFINISH_BUFF +15% — post-FinalRateBonus ===
        # Source: ps_skill_db.json id=273 — MO_COMBOFINISH "+15% Damage for 8 Seconds".
        if build.active_status_levels.get("SC_COMBOFINISH_BUFF"):
            pmf = _scale_floor(pmf, 115, 100)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                "Combo Finish Buff", value=av, min_value=mn, max_value=mx,
                multiplier=1.15,
                note="PS SC_COMBOFINISH_BUFF: +15% damage (8s after MO_COMBOFINISH)",
                formula="dmg × 115 ÷ 100",
                hercules_ref="ps_skill_db.json id=273: MO_COMBOFINISH '+15% Damage for 8 Seconds'",
            )

        # === PR_LEXAETERNA ×2 — applies to ALL damage types ===
        # SC_LEXAETERNA doubles the next hit regardless of physical/magic.
        # Source: battle.c (battle_calc_damage path); status.c:8490 (SC init)
        if target.target_active_scs.get("PR_LEXAETERNA"):
            pmf = _scale_floor(pmf, 2, 1)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                "Lex Aeterna", value=av, min_value=mn, max_value=mx,
                multiplier=2.0, note="PR_LEXAETERNA doubles next hit",
                formula="dmg × 2", hercules_ref="status.c:8490",
            )

        # === DAMAGE-RECEIVED BONUS (Mailbreaker, Venom Dust, Raided — multiplicative) ===
        if target.mailbreaker:
            pmf = _scale_floor(pmf, 110, 100)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                "Mailbreaker", value=av, min_value=mn, max_value=mx,
                multiplier=1.1, note="+10% damage taken (Mailbreaker debuff; no bosses)",
                formula="dmg × 110 ÷ 100", hercules_ref="G112",
            )
        if target.venom_dust:
            pmf = _scale_floor(pmf, 110, 100)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                "Venom Dust", value=av, min_value=mn, max_value=mx,
                multiplier=1.1, note="+10% damage taken (Venom Dust debuff)",
                formula="dmg × 110 ÷ 100", hercules_ref="G112",
            )
        if target.raided:
            pmf = _scale_floor(pmf, 110, 100)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                "Raided", value=av, min_value=mn, max_value=mx,
                multiplier=1.1, note="+10% damage taken (Raided debuff)",
                formula="dmg × 110 ÷ 100", hercules_ref="G112",
            )

        # Final summary step
        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            "Final Damage",
            value=av,
            min_value=mn,
            max_value=mx,
            note=("CRIT branch" if is_crit else "Normal branch"),
            formula="",
            hercules_ref="",
        )

        result.min_damage = mn
        result.max_damage = mx
        result.avg_damage = av
        result.pmf = pmf

        return result
