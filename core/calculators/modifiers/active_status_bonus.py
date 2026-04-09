from core.models.weapon import Weapon
from core.models.build import PlayerBuild
from core.models.damage import DamageResult
from core.models.skill import SkillInstance
from core.data_loader import loader
from pmf.operations import _add_flat, _scale_floor, pmf_stats
from core.server_profiles import ServerProfile, STANDARD


class ActiveStatusBonus:
    """Pre-renewal flat ATK bonuses from SC_* in the weapon-attack phase.
    Only SC_AURABLADE is implemented here (flat_per_level, no renewal guard).
    SC_ENCHANTBLADE (complex_flat) and SC_GIANTGROWTH (rate_chance) are deferred.
    Removed entries (see active_status_bonus.json comment for reasons):
      SC_MAXIMIZEPOWER — variance collapse only; handled in base_damage.py
      SC_SPURT         — hallucinated; not present in Hercules source
      SC_GS_MADNESSCANCEL, SC_IMPOSITIO — #ifdef RENEWAL in battle_calc_masteryfix
      SC_OVERTHRUST, SC_OVERTHRUSTMAX   — skillratio bonus; handled in skill_ratio.py
    Source: battle.c battle_calc_weapon_attack, after battle_addmastery call."""

    @staticmethod
    def calculate(weapon: Weapon, build: PlayerBuild, skill: SkillInstance, pmf: dict,
                  result: DamageResult, profile: ServerProfile = STANDARD) -> dict:
        """Applies flat and rate SC_* bonuses to the PMF.

        Flat bonuses (type=flat_per_level / flat) are accumulated and applied as _add_flat.
        Rate bonuses from profile.rate_bonuses are applied as _scale_floor(100+rate, 100)
        for PS-only SCs like SC_GS_GATLINGFEVER (+40%) and SC_GS_MADNESSCANCEL (+30%).
        """
        active_status_levels = getattr(build, 'active_status_levels', {})
        total_flat: int = 0
        total_rate: int = 0
        applied_bonuses: list[str] = []
        note: str = "No active statuses"
        formula: str = "dmg (no SC bonuses)"

        if active_status_levels:
            for sc_key, level in active_status_levels.items():
                config = loader.get_active_status_config(sc_key)
                if not config:
                    continue

                sc_type = config.get("type")
                bonus = 0

                # flat_per_level (Aura Blade; others removed — see class docstring)
                if sc_type == "flat_per_level":
                    mult = config.get("multiplier", 1)
                    bonus = level * mult

                # flat (Madness Cancel)
                elif sc_type == "flat":
                    bonus = config.get("value", 0)

                # complex_flat – DEFERRED (SC_ENCHANTBLADE)
                # i = (enchant_lv*20+100)*lv//150 + status.int_ - target.mdef + status_get_matk(sd,0)
                # Exact formula from battle.c SC_ENCHANTBLADE block.
                elif sc_type == "complex_flat":
                    pass  # TODO: requires StatusData.matk and target.mdef

                # rate_chance – DEFERRED (SC_GIANTGROWTH)
                # 15% chance to apply 200% rate from battle.c SC_GIANTGROWTH block.
                elif sc_type == "rate_chance":
                    pass  # TODO: requires seeded RNG matching Hercules rand()

                # exclusions (Aura Blade on Spiral Pierce, etc.)
                if "exclusions" in config:
                    if skill.id in config["exclusions"]:
                        bonus = 0

                total_flat += bonus
                if bonus:
                    applied_bonuses.append(f"{sc_key} Lv{level} (+{bonus})")

        # PS rate bonuses: SCs that grant a % damage bonus instead of (or replacing) flat BATK.
        # Applied as _scale_floor(pmf, 100+rate, 100) — post-defense multiplicative bonus.
        # SC_GS_GATLINGFEVER: +40% (all lvs; vanilla adds flat batk instead, skipped in StatusCalc).
        # SC_GS_MADNESSCANCEL (Barrage): +30% (PS-only; vanilla is #ifdef RENEWAL).
        for sc_key, rate in profile.rate_bonuses.items():
            if sc_key in active_status_levels:
                total_rate += rate
                applied_bonuses.append(f"{sc_key} PS +{rate}% damage")

        if applied_bonuses:
            note = f"Applied: {', '.join(applied_bonuses)}"
            formula = "dmg + flat bonuses (json); × rate% (PS profile)"
        elif not active_status_levels:
            note = "No active statuses"
            formula = "dmg (no SC bonuses)"
        else:
            note = "Applied: none"
            formula = "dmg (no matching SC bonuses)"

        pmf = _add_flat(pmf, total_flat)
        if total_rate:
            pmf = _scale_floor(pmf, 100 + total_rate, 100)

        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            name="Active Status Bonuses",
            value=av,
            min_value=mn,
            max_value=mx,
            multiplier=((100 + total_rate) / 100) if total_rate else 1.0,
            note=note,
            formula=formula,
            hercules_ref="battle.c: if (sc && sc->data[SC_AURABLADE] && skill_id != LK_SPIRALPIERCE && skill_id != ML_SPIRALPIERCE) { int lv = sc->data[SC_AURABLADE]->val1; ATK_ADD(wd.damage, wd.damage2, 20 * lv); }\n"
                         "battle.c: if (sc && sc->data[SC_ENCHANTBLADE] && skill_id == 0) { ... ATK_ADD(i); }\n"
                         "battle.c: (and every other if (sc && sc->data[SC_XXX]) ATK_ADD / ATK_ADDRATE block after battle_addmastery)\n"
                         "PS: SC_GS_GATLINGFEVER +40% / SC_GS_MADNESSCANCEL +30% via profile.rate_bonuses"
        )
        return pmf