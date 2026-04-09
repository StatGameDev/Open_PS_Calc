"""
Grand Cross (CR_GRANDCROSS) damage pipeline.

CR_GRANDCROSS is a hybrid BF_WEAPON + BF_MAGIC skill that applies Holy element.
It has its own damage formula in battle.c, separate from the standard BF_WEAPON
and BF_MAGIC pipelines.

Source summary:
  - battle.c:4090-4135  battle_calc_misc_attack case CR_GRANDCROSS
  - battle.c:4121-4135  combine weapon + magic components, apply outer GC ratio
  - skill.c:2759         BF_WEAPON flag added post-calc (for card/rate callers)
  - skill_db.conf:7497   element = Ele_Holy
  - skill_db.conf:7503   AttackType = Magic
  - skill_db.conf:7505   IgnoreCards = true
  - skill_db.conf:7508   IgnoreFlee = true
  - skill_db.conf:7515   HPRateCost = 20 (20% HP cost)
  - skill_db.conf:7519   CastTime = 2000 ms
  - skill_db.conf:7523   AfterCastActDelay = 1500 ms
"""

from core.models.damage import DamageResult
from core.models.build import PlayerBuild
from core.models.status import StatusData
from core.models.weapon import Weapon
from core.models.skill import SkillInstance
from core.models.target import Target
from core.config import BattleConfig
from core.data_loader import loader
from core.models.gear_bonuses import GearBonuses
from core.server_profiles import ServerProfile, STANDARD
from pmf.operations import _scale_floor, _add_flat, _uniform_pmf, pmf_stats, _convolve
from core.calculators.modifiers.base_damage import BaseDamage
from core.calculators.modifiers.skill_ratio import SkillRatio
from core.calculators.modifiers.defense_fix import DefenseFix
from core.calculators.modifiers.refine_fix import RefineFix
from core.calculators.modifiers.attr_fix import AttrFix
from core.calculators.modifiers.card_fix import CardFix
from core.calculators.modifiers.final_rate_bonus import FinalRateBonus

# Duplicate of the dict in battle_pipeline.py — DO NOT import from there (circular import).
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

# Holy element integer index used by AttrFix.calculate(atk_element=...).
# Source: bonus_definitions.py _ELE_STR_TO_INT — "Holy" maps to 6.
_ELE_HOLY: int = 6

# Exported for combat_controls._IMPLEMENTED_SKILLS so CR_GRANDCROSS appears in the dropdown.
IMPLEMENTED_GRAND_CROSS_SKILLS: frozenset[str] = frozenset({"CR_GRANDCROSS"})


class GrandCrossPipeline:
    """
    Damage pipeline for CR_GRANDCROSS (Grand Cross).

    Computes weapon and magic sub-components separately, then combines them
    with an outer Holy attr fix and the skill's 100+40×lv ratio.

    Step order:
      [W] BaseDamage → WeaponAtkRate → AtkRate → SkillRatio → DefenseFix →
          RefineFix → MasteryFix(skill=None) → AttrFix(Holy)
      [M] MATK Base → DefenseFix(magic) → AttrFix(Holy)
      Combined: [W]+[M] → AttrFix(Holy) combined → GC Ratio × (100+40×lv) →
                CardFix(magic) → FinalRateBonus
    """

    def __init__(self, config: BattleConfig):
        self.config = config

    def calculate(self,
                  status: StatusData,
                  weapon: Weapon,
                  skill: SkillInstance,
                  target: Target,
                  build: PlayerBuild,
                  gear_bonuses: GearBonuses,
                  profile: ServerProfile = STANDARD) -> DamageResult:
        """
        Returns a single DamageResult with [W]- and [M]-prefixed sub-steps followed
        by the combined steps. The caller (BattlePipeline) wraps this in a BattleResult.
        """
        result = DamageResult()

        # -----------------------------------------------------------------------
        # WEAPON SUB-PATH
        # battle.c:4090-4120 — standard BF_WEAPON calc up to MasteryFix + 1st AttrFix
        # -----------------------------------------------------------------------
        result_w = DamageResult()

        # BaseDamage
        # battle_calc_base_damage2: ATK roll (weapon + status ATK; SizeFix internal)
        pmf_w = BaseDamage.calculate(status, weapon, build, target, skill, result_w)

        # bWeaponAtk (battle.c:676-686)
        _herc_wtype = _WEAPON_TYPE_TO_HERC.get(weapon.weapon_type, "")
        _watk_rate = gear_bonuses.weapon_atk_rate.get(_herc_wtype, 0)
        if _watk_rate:
            pmf_w = _scale_floor(pmf_w, 100 + _watk_rate, 100)
            mn, mx, av = pmf_stats(pmf_w)
            result_w.add_step(
                name="Weapon ATK Rate",
                value=av, min_value=mn, max_value=mx,
                multiplier=(100 + _watk_rate) / 100.0,
                formula=f"atk × (100 + {_watk_rate}) // 100",
                hercules_ref="battle.c:676-686 bWeaponAtk",
            )

        # bAtkRate (battle.c:5330 #ifndef RENEWAL)
        if gear_bonuses.atk_rate:
            pmf_w = _scale_floor(pmf_w, 100 + gear_bonuses.atk_rate, 100)
            mn, mx, av = pmf_stats(pmf_w)
            result_w.add_step(
                name="ATK Rate",
                value=av, min_value=mn, max_value=mx,
                multiplier=(100 + gear_bonuses.atk_rate) / 100.0,
                formula=f"atk × (100 + {gear_bonuses.atk_rate}) // 100",
                hercules_ref="battle.c:5330 #ifndef RENEWAL bAtkRate",
            )

        # SkillRatio — ratio=100 default; SC_OVERTHRUST still adds here via SkillRatio.
        # Pass profile=STANDARD to suppress "PS unaudited" warning (GC is vanilla).
        pmf_w, _ = SkillRatio.calculate(skill, pmf_w, build, result_w,
                                        target=target, weapon=weapon,
                                        profile=STANDARD, ctx=None, gear_bonuses=gear_bonuses)

        # DefenseFix BF_WEAPON — CR_GRANDCROSS has no pdef/idef flags.
        # flag.pdef not set: battle.c:5673; flag.idef not set: battle.c:5700
        # nk_ignore_def=False, so normal VIT-DEF reduction applies.
        pmf_w = DefenseFix.calculate(target, build, gear_bonuses, pmf_w,
                                     self.config, result_w,
                                     is_crit=False, skill=skill)

        # RefineFix — CR_GRANDCROSS (id=254) NOT in _REFINE_SKIP_SKILLS → applies.
        # battle.c:5797-5805 #ifndef RENEWAL
        pmf_w = RefineFix.calculate(weapon, skill, pmf_w, result_w)

        # --- Mastery Fix (GC-specific inline) ---
        # battle.c:834: add_mastery runs before the switch; switch returns early at 839.
        # Vanilla: full mastery values. PS: gc_mastery_overrides reduces contributions.
        # NJ_TOBIDOUGU / NJ_KUNAI / TF_POISON — skill-gated in source, safely irrelevant here.

        # Step 1: AL_DEMONBANE — universal first check in add_mastery (battle.c:713-717),
        # independent of weapon type.
        # Vanilla condition: battle_check_undead(race, def_ele) = Undead race OR Undead element
        #                    OR race == Demon.  Mob-only (target->type==BL_MOB, battle.c:714).
        # PS GC: reduced to 1/lv vs Demon race OR Undead element; 0 vs others; race==Undead dropped.
        _db_lv = gear_bonuses.effective_mastery.get("AL_DEMONBANE", 0)
        if _db_lv > 0:
            if override_fn := profile.gc_mastery_overrides.get("AL_DEMONBANE"):
                _db_bonus = override_fn(_db_lv, target, build)
                if _db_bonus:
                    _db_note = f"AL_DEMONBANE Lv {_db_lv} [PS GC]: +{_db_bonus}"
                    _db_formula = f"dmg + {_db_bonus}"
                else:
                    _db_note = f"AL_DEMONBANE Lv {_db_lv} [PS GC]: no bonus"
                    _db_formula = "dmg (no change)"
            else:
                # Vanilla: lv * (3 + base_lv / 20.0) vs Undead(race/ele) or Demon; mob-only.
                _db_match = (
                    target is not None
                    and not target.is_pc
                    and (target.race in ("Undead", "Demon") or target.element == 9)
                )
                if _db_match:
                    _db_bonus = int(_db_lv * (3 + build.base_level / 20.0))
                    _db_note = f"AL_DEMONBANE Lv {_db_lv} (Undead/Demon): +{_db_bonus}"
                    _db_formula = f"dmg + lv * (3 + base_lv/20.0)"
                else:
                    _db_bonus = 0
                    _db_note = f"AL_DEMONBANE Lv {_db_lv}: no bonus"
                    _db_formula = "dmg (no change)"
            if _db_bonus:
                pmf_w = _add_flat(pmf_w, _db_bonus)
            mn, mx, av = pmf_stats(pmf_w)
            result_w.add_step(
                name="Demon Bane",
                value=av, min_value=mn, max_value=mx,
                note=_db_note,
                formula=_db_formula,
                hercules_ref="battle.c:713-717 add_mastery: AL_DEMONBANE universal (before weapon switch)",
            )

        # Step 2: Weapon-type mastery (switch in add_mastery, battle.c:733-809).
        mastery_key = loader.get_mastery_weapon_map().get(weapon.weapon_type)
        if mastery_key is None and profile.ps_mastery_weapon_map:
            mastery_key = profile.ps_mastery_weapon_map.get(weapon.weapon_type)
        # PS changelog 2026-03-23: Blade Mastery redirect (same logic as mastery_fix.py).
        # SM_SWORD (1HSword/Knife) → SM_TWOHANDSWORD when player has SM_TWOHANDSWORD > 0.
        if mastery_key and profile.mastery_prefer_fallback:
            _pref = profile.mastery_prefer_fallback.get(mastery_key)
            if _pref and gear_bonuses.effective_mastery.get(_pref, 0) > 0:
                mastery_key = _pref
        _gc_bonus = 0
        _gc_note = f"No weapon mastery for {weapon.weapon_type}"
        _gc_formula = "dmg (no mastery)"

        if mastery_key is not None:
            _ml = gear_bonuses.effective_mastery.get(mastery_key, 0)
            if _ml > 0:
                if override_fn := profile.gc_mastery_overrides.get(mastery_key):
                    _gc_bonus = override_fn(_ml, target, build)
                    if _gc_bonus:
                        _gc_note = f"{mastery_key} Lv {_ml} [PS GC]: +{_gc_bonus}"
                        _gc_formula = f"dmg + {_gc_bonus}"
                    else:
                        _gc_note = f"{mastery_key} Lv {_ml} [PS GC]: no bonus"
                        _gc_formula = "dmg (no change)"
                else:
                    _mult = loader.get_mastery_multiplier(mastery_key, build)
                    _gc_bonus = _ml * _mult
                    _gc_note = f"{mastery_key} Lv {_ml}: +{_gc_bonus}"
                    _gc_formula = f"dmg + lv * {_mult}"
            else:
                _gc_note = f"{mastery_key} Lv 0: no bonus"
                _gc_formula = "dmg (no change)"

        if _gc_bonus:
            pmf_w = _add_flat(pmf_w, _gc_bonus)
        mn, mx, av = pmf_stats(pmf_w)
        result_w.add_step(
            name="Mastery Fix",
            value=av, min_value=mn, max_value=mx,
            note=_gc_note,
            formula=_gc_formula,
            hercules_ref="battle.c:759-769 add_mastery: weapon switch KN_SPEARMASTERY (Peco=5/lv, foot=4/lv)",
        )

        # BS_WEAPONRESEARCH: flat +2/lv, no skill gate — always applies.
        # battle.c:5828 #ifndef RENEWAL: ATK_ADD(temp*2)
        _bs_wr_lv = gear_bonuses.effective_mastery.get("BS_WEAPONRESEARCH", 0)
        if _bs_wr_lv:
            pmf_w = _add_flat(pmf_w, _bs_wr_lv * 2)
            mn, mx, av = pmf_stats(pmf_w)
            result_w.add_step(
                name="Weapon Research",
                value=av, min_value=mn, max_value=mx,
                note=f"BS_WEAPONRESEARCH Lv {_bs_wr_lv}: +{_bs_wr_lv * 2}",
                formula=f"dmg + {_bs_wr_lv * 2}",
                hercules_ref="battle.c:5828 #ifndef RENEWAL: ATK_ADD(temp*2)",
            )

        # ASC_KATAR: % bonus (Katar only) — battle.c:927-929 #else
        _asc_katar_lv = gear_bonuses.effective_mastery.get("ASC_KATAR", 0)
        if weapon.weapon_type == "Katar" and _asc_katar_lv > 0:
            _katar_ratio = 100 + 10 + 2 * _asc_katar_lv
            pmf_w = _scale_floor(pmf_w, _katar_ratio, 100)
            mn, mx, av = pmf_stats(pmf_w)
            result_w.add_step(
                name="Adv. Katar Mastery",
                value=av, min_value=mn, max_value=mx,
                multiplier=_katar_ratio / 100.0,
                note=f"ASC_KATAR Lv {_asc_katar_lv}: ×{_katar_ratio / 100:.2f}",
                formula=f"dmg * (100 + 10 + 2 × {_asc_katar_lv}) / 100",
                hercules_ref="battle.c:927-929 #else: damage += damage * (10 + 2 * skill2_lv) / 100",
            )

        # AttrFix ELE_HOLY — 1st pass on weapon component
        # battle.c:5834: calc_elefix(ELE_HOLY, sd, target, wd)
        pmf_w = AttrFix.calculate(weapon, target, pmf_w, result_w, build,
                                  atk_element=_ELE_HOLY)

        # -----------------------------------------------------------------------
        # MAGIC SUB-PATH
        # battle.c:4101-4119 — MATK + MDEF + 1st Holy attr fix
        # -----------------------------------------------------------------------
        result_m = DamageResult()

        # MATK base roll (same logic as MagicPipeline)
        # status.c:3783/3790 #else not RENEWAL (stored in StatusData)
        maximize = "SC_MAXIMIZEPOWER" in getattr(build, 'active_status_levels', {})
        if maximize:
            pmf_m: dict = {status.matk_max: 1.0}
            matk_note = f"MATK {status.matk_max} (SC_MAXIMIZEPOWER: use max)"
        else:
            pmf_m = _uniform_pmf(status.matk_min, status.matk_max)
            matk_note = f"MATK roll [{status.matk_min}–{status.matk_max}]"

        mn, mx, av = pmf_stats(pmf_m)
        result_m.add_step(
            name="MATK Base",
            value=av, min_value=mn, max_value=mx,
            note=matk_note,
            formula="int_ + (int_//7)^2 to int_ + (int_//5)^2",
            hercules_ref="battle.c:4101 — CR_GRANDCROSS magic component: ad2.damage = battle->get_matk(src,2)",
        )

        # MDEF (magic defense) — battle.c:1585 #else not RENEWAL
        pmf_m = DefenseFix.calculate_magic(target, gear_bonuses, pmf_m, result_m)

        # AttrFix ELE_HOLY — 1st pass on magic component (battle.c:4117)
        # weapon=None is safe: atk_element override takes priority in AttrFix.calculate()
        pmf_m = AttrFix.calculate(None, target, pmf_m, result_m, build,
                                  atk_element=_ELE_HOLY)

        # -----------------------------------------------------------------------
        # COMBINE — merge sub-step logs then convolve PMFs
        # -----------------------------------------------------------------------
        # Prefix and merge sub-steps into main result
        for step in result_w.steps:
            step.name = f"[W] {step.name}"
            result.steps.append(step)
        for step in result_m.steps:
            step.name = f"[M] {step.name}"
            result.steps.append(step)

        # Convolve (sum of two independent stochastic variables)
        pmf = _convolve(pmf_w, pmf_m)
        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            name="Weapon + Magic Combined",
            value=av, min_value=mn, max_value=mx,
            note="W_component + M_component merged",
            formula="pmf_w ⊕ pmf_m (convolution / sum of independent PMFs)",
            hercules_ref="battle.c:4121 wd.damage + ad2.damage",
        )

        # 2nd Holy attr fix pass on combined sum (battle.c:4124)
        # calc_elefix applied again to the merged total
        holy_mult = loader.get_attr_fix_multiplier(
            "Holy", loader.get_element_name(target.element), target.element_level or 1
        )
        if holy_mult != 100:
            pmf = _scale_floor(pmf, holy_mult, 100)
            mn, mx, av = pmf_stats(pmf)
            defending = loader.get_element_name(target.element)
            result.add_step(
                name="Attr Fix (Holy) — Combined",
                value=av, min_value=mn, max_value=mx,
                multiplier=holy_mult / 100.0,
                note=f"Holy vs {defending} Lv{target.element_level or 1} ({holy_mult}%)",
                formula=f"(wd + ad2) × {holy_mult} // 100",
                hercules_ref="battle.c:4124 calc_elefix(ELE_HOLY) on combined damage",
            )

        # Grand Cross outer skill ratio (battle.c:4124): × (100 + 40×skill_lv) / 100
        # lv1=140%, lv2=180%, ..., lv5=300%, lv10=500%
        gc_ratio = 100 + 40 * skill.level
        pmf = _scale_floor(pmf, gc_ratio, 100)
        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            name=f"GC Ratio Lv{skill.level}",
            value=av, min_value=mn, max_value=mx,
            multiplier=gc_ratio / 100.0,
            note=f"100 + 40 × {skill.level} = {gc_ratio}%",
            formula=f"dmg × {gc_ratio} // 100",
            hercules_ref="battle.c:4124 wd.damage = wd.damage * (100 + 40 * skill_lv) / 100",
        )

        # CardFix (magic) — IgnoreCards=true (skill_db.conf:7505) suppresses attacker-side
        # magic_addrace. Target-side (sub_ele/sub_race/magic_def_rate) still applies if
        # target.is_pc. Pass "Ele_Holy" as the element string.
        # battle.c:4134 #ifndef RENEWAL
        pmf = CardFix.calculate_magic(target, "Ele_Holy", pmf, result, gear_bonuses)

        # FinalRateBonus — weapon_damage_rate applies to Grand Cross (not ranged)
        pmf = FinalRateBonus.calculate(is_ranged=False, pmf=pmf,
                                       config=self.config, result=result)

        # Finalize result
        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            name="Final Grand Cross Damage",
            value=av, min_value=mn, max_value=mx,
            note="CR_GRANDCROSS combined weapon+magic Holy damage",
            formula="",
            hercules_ref="battle.c:4090-4135 case CR_GRANDCROSS",
        )
        result.min_damage = mn
        result.max_damage = mx
        result.avg_damage = av
        result.pmf = pmf
        return result
