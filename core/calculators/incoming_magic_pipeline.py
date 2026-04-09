from typing import Optional

from core.models.damage import DamageResult
from pmf.operations import _uniform_pmf, _scale_floor, pmf_stats
from core.models.target import Target
from core.models.build import PlayerBuild
from core.models.gear_bonuses import GearBonuses
from core.models.skill import SkillInstance
from core.config import BattleConfig
from core.data_loader import loader
from core.calculators.modifiers.skill_ratio import SkillRatio
from core.calculators.modifiers.defense_fix import DefenseFix
from core.calculators.modifiers.card_fix import CardFix


class IncomingMagicPipeline:
    """
    Pre-renewal incoming magic damage pipeline (mob → player).

    Step order (battle.c:3828 battle_calc_magic_attack #else not RENEWAL):
      MobMATKRoll    — [matk_min, matk_max] from mob int_; mob_matk_bonus_rate for buffs/debuffs
      SkillRatio     — if a named skill is used (BF_MAGIC ratio, per-hit)
      AttrFix        — skill/mob element vs player armor element
      DefenseFix     — player MDEF: damage*(100-mdef)/100 - mdef2
      CardFix        — target-side only (player magic resist cards; mob has no gear)

    mob_matk_bonus_rate mirrors SC effects that change mob MATK post-spawn (e.g. buffs
    from SC_BLESSING, SC_INC_AGI-type effects on mob INT). Default 0 = unmodified.

    Source: status.c:3783-3792 status_base_matk_min/max (#else not RENEWAL);
            battle.c:3828 battle_calc_magic_attack.
    """

    def __init__(self, config: BattleConfig):
        self.config = config

    def calculate(
        self,
        mob_id: int,
        player_target: Target,
        gear_bonuses: GearBonuses,
        build: PlayerBuild,
        skill: Optional[SkillInstance] = None,
        mob_matk_bonus_rate: int = 0,   # % modifier to mob MATK (buffs/debuffs)
        mob_int_bonus_rate: int = 0,    # % modifier to mob INT before MATK formula (e.g. Strip Helm -40)
        ele_override: Optional[int] = None,    # element ID 0-9; None = use skill/mob natural
        ratio_override: Optional[int] = None,  # % ratio (e.g. 300); None = use skill ratio
    ) -> DamageResult:
        result = DamageResult()

        mob_data = loader.get_monster_data(mob_id)
        if mob_data is None:
            return result

        mob_name    = mob_data.get("name", f"Mob {mob_id}")
        mob_element = mob_data.get("element", 0)
        mob_race    = mob_data.get("race", "Formless")
        mob_int_    = mob_data.get("stats", {}).get("int", 0)
        if mob_int_bonus_rate:
            mob_int_ = max(0, mob_int_ * (100 + mob_int_bonus_rate) // 100)

        # --- Mob MATK Roll ---
        # Pre-renewal formula (status.c:3783-3792 #else not RENEWAL):
        #   matk_min = int_ + (int_//7)^2
        #   matk_max = int_ + (int_//5)^2
        # mob_matk_bonus_rate applies uniformly to both bounds (mirrors SC buff effects).
        base_matk_min = mob_int_ + (mob_int_ // 7) ** 2
        base_matk_max = mob_int_ + (mob_int_ // 5) ** 2

        if mob_matk_bonus_rate:
            matk_min = base_matk_min * (100 + mob_matk_bonus_rate) // 100
            matk_max = base_matk_max * (100 + mob_matk_bonus_rate) // 100
        else:
            matk_min = base_matk_min
            matk_max = base_matk_max

        matk_max = max(matk_min, matk_max)
        matk_avg = (matk_min + matk_max) // 2

        modifier_note = f" ×{100 + mob_matk_bonus_rate}%" if mob_matk_bonus_rate else ""
        pmf: dict = _uniform_pmf(matk_min, matk_max)

        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            name="Mob MATK Roll",
            value=av,
            min_value=mn,
            max_value=mx,
            note=(f"{mob_name}: int_ {mob_int_}{modifier_note}"
                  f" → MATK [{matk_min}, {matk_max}]"),
            formula="int_ + (int_//7)^2  to  int_ + (int_//5)^2",
            hercules_ref="status.c:3783-3792 status_base_matk_min/max (#else not RENEWAL)",
        )

        # --- Skill Ratio (BF_MAGIC) — optional ---
        # ratio_override takes priority over skill lookup.
        # SkillRatio.calculate_magic returns (pmf, hit_count); build=None is safe (unused).
        hit_count = 1
        if ratio_override is not None and ratio_override > 0:
            pmf = _scale_floor(pmf, ratio_override, 100)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                name=f"Ratio Override ({ratio_override}%)",
                value=av,
                min_value=mn,
                max_value=mx,
                multiplier=ratio_override / 100.0,
                note=f"Manual ratio override: {ratio_override}%",
                formula=f"dmg × {ratio_override} // 100",
                hercules_ref="(manual override)",
            )
        elif skill is not None and skill.id != 0:
            pmf, hit_count = SkillRatio.calculate_magic(skill, pmf, None, player_target, result)

        # --- Attr Fix: mob/skill element vs player armor element ---
        # ele_override takes priority; otherwise skill element, then mob natural element.
        if ele_override is not None:
            magic_ele_name = loader.get_element_name(ele_override)
        else:
            magic_ele_name = "Neutral"
            if skill is not None and skill.id != 0:
                skill_data = loader.get_skill(skill.id)
                if skill_data:
                    ele_list = skill_data.get("element")
                    if ele_list and skill.level <= len(ele_list):
                        raw = ele_list[skill.level - 1]   # e.g. "Ele_Fire"
                        if raw and raw.startswith("Ele_"):
                            magic_ele_name = raw[4:]       # strip "Ele_" → "Fire"
            if magic_ele_name == "Neutral":
                # Fall back to mob's natural element
                magic_ele_name = loader.get_element_name(mob_element)

        player_ele_name = loader.get_element_name(player_target.armor_element)
        multiplier = loader.get_attr_fix_multiplier(
            magic_ele_name, player_ele_name, player_target.element_level or 1
        )
        if multiplier != 100:
            pmf = _scale_floor(pmf, multiplier, 100)
        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            name="Attr Fix (Magic)",
            value=av,
            min_value=mn,
            max_value=mx,
            multiplier=multiplier / 100.0,
            note=f"{magic_ele_name} vs {player_ele_name} Lv{player_target.element_level or 1} ({multiplier}%)",
            formula=f"dmg * {multiplier} // 100",
            hercules_ref="battle_calc_magic_attack: battle->attr_fix(src,target,ad.damage,s_ele,...)",
        )

        # --- Hit count — applied after defense+attr_fix (per source order) ---
        if hit_count > 1:
            pmf = _scale_floor(pmf, hit_count, 1)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                name=f"Hit Count ×{hit_count}",
                value=av,
                min_value=mn,
                max_value=mx,
                multiplier=float(hit_count),
                note=f"{hit_count} actual hits × per-hit damage",
                formula=f"per_hit_dmg × {hit_count}",
                hercules_ref="battle.c:3823: damage_div_fix: div>1 → dmg*=div",
            )
        elif hit_count < 0:
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                name=f"Hit Count ×{abs(hit_count)} (cosmetic)",
                value=av,
                min_value=mn,
                max_value=mx,
                multiplier=1.0,
                note=f"{abs(hit_count)} cosmetic hits — damage not multiplied",
                formula="no change (cosmetic multi-hit)",
                hercules_ref="battle.c:3823: damage_div_fix: div<0 → div=abs(div), dmg unchanged",
            )

        # --- Defense Fix (magic): player MDEF ---
        # Mob has no ignore_mdef gear → empty GearBonuses (ignore_mdef_rate all zero).
        pmf = DefenseFix.calculate_magic(player_target, GearBonuses(), pmf, result)

        # --- Card Fix (magic, target-side): player's magic resist cards vs mob attacker ---
        # CardFix expects "Ele_XXX" format (card_fix.py); magic_ele_name has "Ele_" stripped.
        magic_ele_key = f"Ele_{magic_ele_name}"
        pmf = CardFix.calculate_incoming_magic(
            mob_race=mob_race,
            magic_ele_name=magic_ele_key,
            player_target=player_target,
            pmf=pmf,
            result=result,
        )

        # --- PR_LEXAETERNA ×2 ---
        if build.player_active_scs.get("PR_LEXAETERNA"):
            pmf = _scale_floor(pmf, 2, 1)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                "Lex Aeterna ×2",
                value=av, min_value=mn, max_value=mx,
                multiplier=2.0,
                note="PR_LEXAETERNA doubles incoming damage",
                formula="damage × 2",
                hercules_ref="battle.c: SC_LEXAETERNA doubles the next hit",
            )

        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            "Final Incoming Magic Damage",
            value=av,
            min_value=mn,
            max_value=mx,
            note="mob → player, pre-renewal BF_MAGIC",
            formula="",
            hercules_ref="",
        )

        result.min_damage = mn
        result.max_damage = mx
        result.avg_damage = av
        result.pmf = pmf

        return result
