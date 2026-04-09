from core.models.weapon import Weapon
from core.models.skill import SkillInstance
from core.models.damage import DamageResult
from core.data_loader import loader
from pmf.operations import _add_flat, pmf_stats

# Skills that suppress the refine bonus entirely (battle.c:5797-5799, #ifndef RENEWAL)
_REFINE_SKIP_SKILLS = frozenset({
    # MO_INVESTIGATE = 263, MO_EXTREMITYFIST = 264 — not pre-renewal focus skills
    # Include by numeric ID in case skill constants aren't defined here
    263,  # MO_INVESTIGATE
    264,  # MO_EXTREMITYFIST
})

# MO_FINGEROFFENSIVE multiplies atk2 by wd.div_ (battle.c:5803).
# We treat it as ×1 for now (single-hit context). ID=262.
_FINGEROFFENSIVE = 262


class RefineFix:
    """Adds the deterministic refine bonus (atk2 = wa->atk2) after defense.

    Hercules position: battle_calc_weapon_attack #ifndef RENEWAL, lines 5797-5805.
    Applied AFTER calc_defense and SC_AURABLADE, BEFORE calc_masteryfix.
    Applied to BOTH normal and crit branches (not gated on flag.cri).

    Source:
        #ifndef RENEWAL
        //Refine bonus
        if( sd && flag.weapon && skill_id != MO_INVESTIGATE && skill_id != MO_EXTREMITYFIST )
        { // Counts refine bonus multiple times
            if( skill_id == MO_FINGEROFFENSIVE )
            {
                ATK_ADD2(wd.div_*sstatus->rhw.atk2, wd.div_*sstatus->lhw.atk2);
            } else {
                ATK_ADD2(sstatus->rhw.atk2, sstatus->lhw.atk2);
            }
        }
        #endif
    """

    @staticmethod
    def calculate(weapon: Weapon, skill: SkillInstance, pmf: dict, result: DamageResult) -> dict:
        if skill.id in _REFINE_SKIP_SKILLS:
            result.add_step(
                name="Refine Bonus",
                value=0,
                note=f"Suppressed for skill {skill.id} (MO_INVESTIGATE / MO_EXTREMITYFIST)",
                formula="0",
                hercules_ref="battle.c lines 5797-5799: #ifndef RENEWAL refine bonus skip for MO_INVESTIGATE/MO_EXTREMITYFIST",
            )
            return pmf

        refine_bonus = loader.get_refine_bonus(weapon.level, weapon.refine)

        if refine_bonus == 0:
            result.add_step(
                name="Refine Bonus",
                value=0,
                note="No refine bonus (unrefined weapon or refine level 0)",
                formula="atk2 = 0",
                hercules_ref="battle.c lines 5803-5805: ATK_ADD2(sstatus->rhw.atk2, ...) — value is 0",
            )
            return pmf

        pmf = _add_flat(pmf, refine_bonus)
        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            name="Refine Bonus",
            value=av,
            min_value=mn,
            max_value=mx,
            multiplier=1.0,
            note=(f"+{weapon.refine} refine on Lv {weapon.level} weapon → flat +{refine_bonus}"
                  " (post-defense, not multiplied by SkillRatio or reduced by DEF)"),
            formula=f"damage + atk2  where atk2 = get_refine_bonus({weapon.level}, {weapon.refine}) = {refine_bonus}",
            hercules_ref="battle.c lines 5797-5805 (#ifndef RENEWAL):\n"
                         "if( sd && flag.weapon && skill_id != MO_INVESTIGATE && skill_id != MO_EXTREMITYFIST )\n"
                         "    ATK_ADD2(sstatus->rhw.atk2, sstatus->lhw.atk2);\n"
                         "status.c: if (r) wa->atk2 = refine->get_bonus(wlv, r) / 100;",
        )
        return pmf
