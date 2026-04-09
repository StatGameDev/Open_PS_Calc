"""
MagicPipeline — BF_MAGIC outgoing damage (player → any target).

Position: called by BattlePipeline when attack_type == "Magic" and skill is not CR_GRANDCROSS.
Input:  StatusData.matk_min / matk_max, SkillInstance, Target.
Output: DamageResult with BF_MAGIC step breakdown; result mirrored to BattleResult.magic.

Key difference from BF_WEAPON: DefenseFix and AttrFix are applied per-hit before the hit
count multiplier, not to the accumulated total. This follows the source order in
battle_calc_magic_attack (battle.c:3828, #else not RENEWAL).
"""
import dataclasses
from functools import reduce

from core.models.damage import DamageResult
from core.models.calc_context import CalcContext
from pmf.operations import _uniform_pmf, _scale_floor, _convolve, pmf_stats
from core.models.build import PlayerBuild
from core.models.status import StatusData
from core.models.skill import SkillInstance
from core.models.target import Target
from core.config import BattleConfig
from core.data_loader import loader
from core.models.gear_bonuses import GearBonuses
from core.server_profiles import ServerProfile, STANDARD
from core.calculators.modifiers.skill_ratio import SkillRatio
from core.calculators.modifiers.defense_fix import DefenseFix
from core.calculators.modifiers.attr_fix import AttrFix
from core.calculators.modifiers.card_fix import CardFix
from core.calculators.modifiers.final_rate_bonus import FinalRateBonus


class MagicPipeline:
    """
    Orchestrator for pre-renewal BF_MAGIC outgoing damage (player → any target).

    Step order (battle_calc_magic_attack, #else not RENEWAL):
      MATK roll       — random in [matk_min, matk_max]; matk_max on SC_MAXIMIZEPOWER
      SkillRatio      — battle_calc_skillratio BF_MAGIC (per-hit ratio)
      SkillATKBonus   — bSkillAtk gear bonus after ratio, before defense (battle.c:4055-4056)
      DefenseFix      — damage*(100-mdef)/100 - mdef2  (magic_defense_type=0, per-hit)
      AttrFix         — skill element vs target element (attr_fix table, per-hit)
      CardFix(magic)  — target-side only if is_pc (sub_ele/sub_race/magic_def_rate); before hit_count
      Hit count ×N    — ad.div_ multiplication after defense+attr_fix+cardfix
      FinalRateBonus  — weapon_damage_rate
    Source: battle.c:3828 battle_calc_magic_attack (#else not RENEWAL).
    """

    def __init__(self, config: BattleConfig):
        self.config = config

    def calculate(self,
                  status: StatusData,
                  skill: SkillInstance,
                  target: Target,
                  build: PlayerBuild,
                  gear_bonuses: GearBonuses,
                  profile: ServerProfile = STANDARD) -> DamageResult:
        result = DamageResult()
        active = getattr(build, 'active_status_levels', {})

        # === PR_TURNUNDEAD — fixed formula, bypasses MATK pipeline ===
        # battle.c:3959-3972 case PR_TURNUNDEAD (#else not RENEWAL):
        #   i = 20*lv + luk + int_ + base_lv + 200 - 200*hp/max_hp; if i>700: i=700
        #   success (rnd()%1000 < i and not boss): damage = target.hp (instakill)
        #   failure (#else not RENEWAL): damage = base_lv + int_ + lv*10  (PS: ×2.5)
        if getattr(skill, "name", "") == "PR_TURNUNDEAD":
            hp_pct = int(build.skill_params.get("PR_TURNUNDEAD_hp_pct", 100))
            i = 20 * skill.level + status.luk + status.int_ + build.base_level + 200 - 200 * hp_pct // 100
            i = min(700, i)
            success_pct = i / 10
            failure_dmg = build.base_level + status.int_ + skill.level * 10
            if "PR_TURNUNDEAD_PS_BONUS" in profile.mechanic_flags:
                failure_dmg = int(failure_dmg * 2.5)
                ps_note = " [PS ×2.5]"
            else:
                ps_note = ""
            result.add_step(
                "Turn Undead",
                failure_dmg,
                min_value=failure_dmg,
                max_value=failure_dmg,
                note=(f"Success (instakill) chance: {success_pct:.1f}% (if target not boss, HP={hp_pct}%); "
                      f"failure damage{ps_note}: {failure_dmg}"),
                formula=(f"base_lv + int_ + lv×10{' × 2.5' if ps_note else ''} = "
                         f"{build.base_level} + {status.int_} + {skill.level}×10"),
                hercules_ref="battle.c:3963-3971 case PR_TURNUNDEAD (#else not RENEWAL)",
            )
            result.min_damage = failure_dmg
            result.max_damage = failure_dmg
            result.avg_damage = failure_dmg
            result.pmf = {failure_dmg: 1.0}
            return result

        # --- MATK base roll ---
        # status.c:3783/3790 #else not RENEWAL (already computed in StatusData)
        maximize = "SC_MAXIMIZEPOWER" in active
        if maximize:
            pmf: dict = {status.matk_max: 1.0}
            matk_note = f"MATK {status.matk_max} (SC_MAXIMIZEPOWER: use max)"
        else:
            pmf = _uniform_pmf(status.matk_min, status.matk_max)
            matk_note = f"MATK roll [{status.matk_min}–{status.matk_max}]"

        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            name="MATK Base",
            value=av,
            min_value=mn,
            max_value=mx,
            note=matk_note,
            formula="int_ + (int_//7)^2 to int_ + (int_//5)^2",
            hercules_ref="status.c:3783-3792 status_base_matk_min/max (#else not RENEWAL)\n"
                         "battle_calc_magic_attack: MATK_ADD(status->get_matk(src, 2))",
        )

        # --- Skill Ratio, Defense, AttrFix — per wave ---
        # Each wave is an independent skill->attack() call (skill_unit_onplace_timer, skill.c:13883).
        # Wave-indexed skills (profile.magic_wave_ratios) have a different ratio per wave and are
        # convolved as independent random variables. Fixed-ratio skills run the pipeline once and
        # multiply by wave_count at the end (same damage each wave → scale is exact).
        skill_name = getattr(skill, "name", "") or ""
        ctx = CalcContext(
            skill_levels=gear_bonuses.effective_mastery,
            skill_params=build.skill_params,
            base_level=build.base_level,
            str_=status.str,
            vit=status.vit,
            dex=status.dex,
            int_=status.int_,
            weapon_type="",  # magic pipeline — no weapon context
        )

        # Compute element and MDEF-ignore up front — used in both branches.
        skill_data = loader.get_skill(skill.id)
        skill_ele_raw = None
        if skill_data:
            ele_list = skill_data.get("element")
            if ele_list and skill.level <= len(ele_list):
                skill_ele_raw = ele_list[skill.level - 1]
        magic_ele_name = skill_ele_raw[4:] if (skill_ele_raw and skill_ele_raw.startswith("Ele_")) else "Neutral"
        defending = loader.get_element_name(target.element)
        multiplier = loader.get_attr_fix_multiplier(magic_ele_name, defending, target.element_level or 1)

        # PS Soul Strike / FirePillar MDEF ignore.
        mdef_ignore_pct = 0
        if ("MG_SOULSTRIKE_MDEF_IGNORE" in profile.mechanic_flags
                and skill_name == "MG_SOULSTRIKE"
                and build.skill_params.get("MG_SOULSTRIKE_mdef_ignore", True)):
            mdef_ignore_pct = 50
        elif ("WZ_FIREPILLAR_MDEF_IGNORE" in profile.mechanic_flags
              and skill_name == "WZ_FIREPILLAR"):
            mdef_ignore_pct = 50

        wave_fn = profile.magic_wave_ratios.get(skill_name)
        if wave_fn is not None:
            # === Per-wave pipeline (variable ratio per wave) ===
            # Each wave goes through the full pipeline independently: ratio → MDEF → AttrFix → hit_count.
            # Waves are convolved as independent random variables (each fires a separate MATK roll).
            # Source: skill_unit_onplace_timer (skill.c:13883) calls skill->attack() per interval.
            wave_count = SkillRatio.get_magic_wave_count(skill_name, build)
            hit_count_raw = SkillRatio.get_magic_hit_count(skill, build, target, profile, ctx)
            hit_count = max(1, abs(hit_count_raw))

            skill_atk_bonus = gear_bonuses.skill_atk.get(skill_name, 0)
            wave_pmfs = []
            for wave_idx in range(1, wave_count + 1):
                wave_ctx = dataclasses.replace(ctx, wave_idx=wave_idx)
                ri = wave_fn(skill.level, target, wave_ctx)
                w_pmf = _scale_floor(pmf, ri, 100)
                # bSkillAtk: after ratio, before defense. battle.c:4055-4056
                if skill_atk_bonus:
                    w_pmf = _scale_floor(w_pmf, 100 + skill_atk_bonus, 100)
                _wave_result = DamageResult()  # per-wave steps not shown individually
                w_pmf = DefenseFix.calculate_magic(target, gear_bonuses, w_pmf, _wave_result,
                                                   mdef_ignore_pct=mdef_ignore_pct)
                if multiplier != 100:
                    w_pmf = _scale_floor(w_pmf, multiplier, 100)
                # CardFix per-wave: calc_cardfix before damage_div_fix per battle_calc_magic_attack
                w_pmf = CardFix.calculate_magic(target, "Ele_" + magic_ele_name, w_pmf, _wave_result,
                                                gear_bonuses)
                if hit_count > 1:
                    w_pmf = _scale_floor(w_pmf, hit_count, 1)
                mn, mx, av = pmf_stats(w_pmf)
                result.add_step(
                    name=f"Wave {wave_idx}/{wave_count} (ratio={ri}%)",
                    value=av,
                    min_value=mn,
                    max_value=mx,
                    multiplier=ri / 100.0,
                    note=f"MATK × {ri}%"
                         + (f" +{skill_atk_bonus}% bSkillAtk" if skill_atk_bonus else "")
                         + f" → MDEF ({magic_ele_name} vs {defending} Lv{target.element_level or 1})"
                         + (f" × {hit_count} hits" if hit_count > 1 else ""),
                    formula=f"MATK × {ri}%"
                            + (f" × (100+{skill_atk_bonus})/100" if skill_atk_bonus else "")
                            + f" → DefenseFix → AttrFix({multiplier}%)"
                            + (f" × {hit_count}" if hit_count > 1 else ""),
                    hercules_ref="skill_unit_onplace_timer (skill.c:13883): each wave is an independent skill->attack()",
                )
                wave_pmfs.append(w_pmf)

            pmf = reduce(_convolve, wave_pmfs)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                name=f"All Waves Combined ({wave_count} waves)",
                value=av,
                min_value=mn,
                max_value=mx,
                multiplier=1.0,
                note=f"Convolution of {wave_count} independent wave PMFs (each wave rolls MATK separately)",
                formula=f"PMF[wave1] ⊛ PMF[wave2] ⊛ … ⊛ PMF[wave{wave_count}]",
                hercules_ref="skill_unit_onplace_timer (skill.c:13883)",
            )

        else:
            # === Normal pipeline (fixed ratio, same damage each wave) ===
            pmf, hit_count_raw, wave_count = SkillRatio.calculate_magic(skill, pmf, build, target, result,
                                                                         profile=profile, ctx=ctx,
                                                                         gear_bonuses=gear_bonuses)

            # Defense Fix — per-hit.
            # Source: battle_calc_magic_attack: damage*(100-mdef)/100 - mdef2 (magic_defense_type=0)
            pmf = DefenseFix.calculate_magic(target, gear_bonuses, pmf, result,
                                             mdef_ignore_pct=mdef_ignore_pct)

            # Attr Fix — per-hit.
            if multiplier != 100:
                pmf = _scale_floor(pmf, multiplier, 100)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                name="Attr Fix (Magic)",
                value=av,
                min_value=mn,
                max_value=mx,
                multiplier=multiplier / 100.0,
                note=f"{magic_ele_name} vs {defending} Lv{target.element_level or 1} ({multiplier}%)",
                formula=f"dmg * {multiplier} // 100",
                hercules_ref="battle_calc_magic_attack: battle->attr_fix(src,target,ad.damage,s_ele,...)",
            )

            # Card Fix (magic) — #ifndef RENEWAL: calc_cardfix before damage_div_fix.
            # battle.c:4073-4078 (#ifndef RENEWAL): calc_cardfix(BF_MAGIC) before damage_div_fix.
            pmf = CardFix.calculate_magic(target, "Ele_" + magic_ele_name, pmf, result, gear_bonuses)

            # Hit count — applied after defense+attr_fix+cardfix, per source order.
            # Source: battle.c:3823 damage_div_fix
            hit_count = hit_count_raw if hit_count_raw > 0 else 1
            if hit_count_raw > 1:
                pmf = _scale_floor(pmf, hit_count_raw, 1)
                mn, mx, av = pmf_stats(pmf)
                result.add_step(
                    name=f"Hit Count ×{hit_count_raw}",
                    value=av,
                    min_value=mn,
                    max_value=mx,
                    multiplier=float(hit_count_raw),
                    note=f"{hit_count_raw} actual hits × per-hit damage",
                    formula=f"per_hit_dmg × {hit_count_raw}",
                    hercules_ref="battle.c:3823: damage_div_fix: div>1 → dmg*=div",
                )
            elif hit_count_raw < 0:
                mn, mx, av = pmf_stats(pmf)
                result.add_step(
                    name=f"Hit Count ×{abs(hit_count_raw)} (cosmetic)",
                    value=av,
                    min_value=mn,
                    max_value=mx,
                    multiplier=1.0,
                    note=f"{abs(hit_count_raw)} cosmetic hits — damage not multiplied",
                    formula="no change (cosmetic multi-hit)",
                    hercules_ref="battle.c:3823: damage_div_fix: div<0 → div=abs(div), dmg unchanged",
                )

            # Wave count — each wave fires the same damage independently.
            # All waves identical → scale is exact (no convolution needed).
            # Source: skill_unit_onplace_timer (skill.c:13883); SkillData1 / Unit.Interval.
            if wave_count > 1:
                pmf = _scale_floor(pmf, wave_count, 1)
                mn, mx, av = pmf_stats(pmf)
                result.add_step(
                    name=f"Wave Count ×{wave_count}",
                    value=av,
                    min_value=mn,
                    max_value=mx,
                    multiplier=float(wave_count),
                    note=f"{wave_count} independent damage waves (ground unit fires {wave_count}×)",
                    formula=f"per_wave_dmg × {wave_count}",
                    hercules_ref="skill_db.conf: SkillData1 / Unit.Interval = wave count; "
                                 "skill_unit_onplace_timer (skill.c:13883) fires skill->attack() each interval",
                )

        # --- Final Rate Bonus ---
        # weapon_damage_rate also applies to magic in the source (same final multiplier)
        pmf = FinalRateBonus.calculate(is_ranged=False, pmf=pmf, config=self.config, result=result)

        if target.target_active_scs.get("PR_LEXAETERNA"):
            pmf = _scale_floor(pmf, 2, 1)
            mn, mx, av = pmf_stats(pmf)
            result.add_step("Lex Aeterna", value=av, min_value=mn, max_value=mx,
                multiplier=2.0, note="PR_LEXAETERNA doubles magic damage",
                formula="dmg × 2", hercules_ref="status.c:8490")

        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            "Final Magic Damage",
            value=av,
            min_value=mn,
            max_value=mx,
            note="BF_MAGIC branch",
            formula="",
            hercules_ref="",
        )

        result.min_damage = mn
        result.max_damage = mx
        result.avg_damage = av
        result.pmf = pmf

        return result
