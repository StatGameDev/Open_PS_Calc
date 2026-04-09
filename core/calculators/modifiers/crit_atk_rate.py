from core.models.build import PlayerBuild
from core.models.damage import DamageResult
from core.models.gear_bonuses import GearBonuses
from core.models.weapon import Weapon
from core.server_profiles import ServerProfile, STANDARD
from pmf.operations import _scale_floor, pmf_stats


class CritAtkRate:
    """Applies sd->bonus.crit_atk_rate to the crit branch only, pre-defense.

    Source: battle.c lines 5333-5334 (#ifndef RENEWAL, inside switch-default,
    before calc_defense is called — i.e. pre-defense):

        if(flag.cri && sd->bonus.crit_atk_rate)
            ATK_ADDRATE(sd->bonus.crit_atk_rate);

    Since crits bypass defense entirely (flag.idef = flag.idef2 = 1), the
    pre-defense vs. post-defense position is irrelevant for final output, but
    this matches the exact Hercules source position.

    Only called on the crit branch by BattlePipeline._run_branch(is_crit=True).
    """

    @staticmethod
    def calculate(build: PlayerBuild, pmf: dict, result: DamageResult, weapon: Weapon = None,
                  profile: ServerProfile = STANDARD, skill=None, gb: GearBonuses = None) -> dict:
        rate = build.bonus_crit_atk_rate
        mn, mx, av = pmf_stats(pmf)
        if rate == 0:
            result.add_step(
                name="Crit ATK Rate",
                value=av,
                min_value=mn,
                max_value=mx,
                note="bonus.crit_atk_rate = 0 (no bCriticalDamage bonus)",
                formula="no change",
                hercules_ref="battle.c:5333: if(flag.cri && sd->bonus.crit_atk_rate) ATK_ADDRATE(sd->bonus.crit_atk_rate);",
            )
        else:
            pmf = _scale_floor(pmf, 100 + rate, 100)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                name="Crit ATK Rate",
                value=av,
                min_value=mn,
                max_value=mx,
                multiplier=(100 + rate) / 100.0,
                note=f"bonus.crit_atk_rate = {rate}% (from bCriticalDamage card/gear effect)",
                formula=f"damage * (100 + {rate}) / 100",
                hercules_ref="battle.c:5333: if(flag.cri && sd->bonus.crit_atk_rate) ATK_ADDRATE(sd->bonus.crit_atk_rate);",
            )

        # PS-4: AS_KATAR lv10 grants +50% crit damage on Katar weapons.
        # Excludes AS_SONICBLOW and AS_GRIMTOOTH (user confirmation, PS-Thief session).
        _skill_name = skill.name if skill is not None else ""
        if ("AS_KATAR_KATAR_CRIT_DMG_BONUS" in profile.mechanic_flags
                and weapon is not None and weapon.weapon_type == "Katar"
                and (gb.effective_mastery if gb is not None else build.mastery_levels).get("AS_KATAR", 0) == 10
                and _skill_name not in {"AS_SONICBLOW", "AS_GRIMTOOTH"}):
            pmf = _scale_floor(pmf, 150, 100)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                name="AS_KATAR Crit Bonus",
                value=av,
                min_value=mn,
                max_value=mx,
                multiplier=1.5,
                note="AS_KATAR lv10 [PS]: ×1.5 crit damage",
                formula="damage * 150 / 100",
                hercules_ref="PS-4: AS_KATAR lv10 +50% crit damage (Payon Stories)",
            )

        return pmf
