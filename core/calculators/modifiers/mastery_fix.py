from core.models.weapon import Weapon
from core.models.build import PlayerBuild
from core.models.damage import DamageResult
from core.models.target import Target
from core.models.skill import SkillInstance
from core.server_profiles import ServerProfile, STANDARD
from core.data_loader import loader
from pmf.operations import _add_flat, _scale_floor, pmf_stats

# PS-4: Additional priest weapon types that gain PR_MACEMASTERY in Payon Stories.
# (Mace already maps to PR_MACEMASTERY in mastery_weapon_map.json.)
_PS_PRIEST_WEAPON_TYPES = frozenset({"Staff", "2HStaff", "Book", "Knuckle"})


# battle.c:838-842: battle_calc_masteryfix returns early (no mastery bonus) for these skills.
_MASTERY_EXEMPT_SKILLS: frozenset = frozenset({
    "MO_INVESTIGATE", "MO_EXTREMITYFIST", "CR_GRANDCROSS",
    "NJ_ISSEN", "CR_ACIDDEMONSTRATION",
})

# Conditional (pre-switch) masteries: apply regardless of weapon type.
# Source: battle.c:713-728 (before the W_ weapon-type switch at ~line 734).
# INVARIANT: these names must NEVER appear in mastery_weapon_map.json.
# Both phase 1 and phase 2 check mastery_ctx_overrides; a weapon-map entry would double-apply.
_SECONDARY_MASTERIES: tuple = ("AL_DEMONBANE", "HT_BEASTBANE")


def _vanilla_secondary_bonus(skill_name: str, lv: int, target: Target, build: PlayerBuild) -> int | None:
    """Vanilla flat ATK bonus for a conditional secondary mastery, or None if condition not met.
    Source: battle.c:713-728."""
    if skill_name == "AL_DEMONBANE":
        # battle.c:713-716: BL_MOB only; battle->check_undead(race, def_ele) OR RC_DEMON.
        # check_undead: race==RC_UNDEAD OR def_ele==ELE_UNDEAD (element 9).
        # Formula: (int)(skill_lv*(3+sd->status.base_level/20.0)) — float division, then truncate.
        if target.is_pc:
            return None
        if target.race in ("Undead", "Demon") or target.element == 9:
            return int(lv * (3 + build.base_level / 20))
        return None
    if skill_name == "HT_BEASTBANE":
        # battle.c:728-730: RC_BRUTE or RC_INSECT. SC_SOULLINK Hunter +STR is a separate gap.
        if target.race in ("Brute", "Insect"):
            return lv * 4
        return None
    return None


class MasteryFix:
    """Exact Mastery Fix step for BF_WEAPON attacks in pre-renewal.
    Source lines (verbatim from repo):
    battle.c: damage = battle->add_mastery(sd, target, damage, left_hand);"""

    @staticmethod
    def calculate(weapon: Weapon, build: PlayerBuild, target: Target, pmf: dict, result: DamageResult,
                  skill: SkillInstance = None, profile: ServerProfile = STANDARD, ctx=None) -> dict:
        """Adds the flat mastery bonus to the PMF."""
        _mastery = ctx.skill_levels if ctx is not None else build.mastery_levels
        # battle.c:838-842: return early from battle_calc_masteryfix for exempt skills.
        if skill is not None and skill.name in _MASTERY_EXEMPT_SKILLS:
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                name="Mastery Fix",
                value=av, min_value=mn, max_value=mx,
                multiplier=1.0,
                note=f"BYPASSED — {skill.name} is exempt (battle.c:838-842)",
                formula="no change (mastery skipped)",
                hercules_ref="battle.c:838-842: battle_calc_masteryfix returns early for these skills",
            )
            return pmf

        # ── PHASE 1: Conditional/secondary masteries ─────────────────────────────────────────
        # Mirrors battle.c:713-728 (before the weapon-type switch).
        # Applied regardless of equipped weapon type; each firing skill emits its own step.
        for _sec_skill in _SECONDARY_MASTERIES:
            _sec_lv = _mastery.get(_sec_skill, 0)
            if _sec_lv == 0:
                continue
            if _override_fn := profile.mastery_ctx_overrides.get(_sec_skill):
                _sec_bonus = _override_fn(_sec_lv, target, ctx)
            else:
                _sec_bonus = _vanilla_secondary_bonus(_sec_skill, _sec_lv, target, build)
            if _sec_bonus:
                pmf = _add_flat(pmf, _sec_bonus)
                _mn, _mx, _av = pmf_stats(pmf)
                result.add_step(
                    name=f"Mastery Fix ({_sec_skill})",
                    value=_av, min_value=_mn, max_value=_mx,
                    multiplier=1.0,
                    note=f"{_sec_skill} Lv {_sec_lv}: +{_sec_bonus}",
                    formula=f"dmg + {_sec_bonus}",
                    hercules_ref="battle.c:713-728: conditional masteries (pre-weapon-switch)",
                )

        # ── PHASE 2: Weapon-type mastery ──────────────────────────────────────────────────────
        mastery_key = loader.get_mastery_weapon_map().get(weapon.weapon_type)

        # G187: PS-specific weapon type → mastery key additions (e.g. Shotgun/Grenade → GS_DUST).
        if mastery_key is None and profile.ps_mastery_weapon_map:
            mastery_key = profile.ps_mastery_weapon_map.get(weapon.weapon_type)

        # PS changelog 2026-03-23: Blade Mastery redirect.
        # If the profile defines a preferred mastery for this key and the player has it, use it.
        # Example: SM_SWORD → SM_TWOHANDSWORD for Swordsman-tree jobs with Blade Mastery.
        if mastery_key and profile.mastery_prefer_fallback:
            _pref = profile.mastery_prefer_fallback.get(mastery_key)
            if _pref and _mastery.get(_pref, 0) > 0:
                mastery_key = _pref

        # PS-4: expand PR_MACEMASTERY to additional priest weapon types.
        if "PR_MACEMASTERY_EXPANDED_WEAPON_TYPES" in profile.mechanic_flags and mastery_key is None and weapon.weapon_type in _PS_PRIEST_WEAPON_TYPES:
            mastery_key = "PR_MACEMASTERY"

        bonus: int = 0
        note: str = f"No mastery defined for {weapon.weapon_type}"
        formula: str = "dmg (no mastery)"

        if mastery_key is not None:
            mastery_level = _mastery.get(mastery_key, 0)

            # G153/G160 (Arch-2): passive_overrides["atk_per_lv"] — non-linear flat ATK table.
            # Takes priority over mastery_ctx_overrides and mastery_per_level.
            _atk_list = profile.passive_overrides.get(mastery_key, {}).get("atk_per_lv")
            if isinstance(_atk_list, list) and mastery_level > 0:
                bonus = _atk_list[mastery_level - 1]
                note = f"{mastery_key} Lv {mastery_level} [PS]: +{bonus}"
                formula = f"dmg + atk_per_lv[{mastery_level - 1}]"
            elif override_fn := profile.mastery_ctx_overrides.get(mastery_key):
                # PS-Arch-3: profile-supplied lambda handles context-dependent mastery formulas.
                override_val = override_fn(mastery_level, target, ctx)
                if override_val is None:
                    note = f"{mastery_key} Lv {mastery_level} [PS]: no bonus ({target.race if target else 'no target'})"
                    formula = "dmg (no change)"
                else:
                    bonus = override_val
                    note = f"{mastery_key} Lv {mastery_level} [PS]: +{bonus}"
                    formula = "dmg + PS_override"
            else:
                # PS-4: profile mastery_per_level overrides DataLoader table.
                ps_val = profile.mastery_per_level.get(mastery_key)
                if ps_val is not None:
                    mult = ps_val[1] if (isinstance(ps_val, tuple) and build.is_riding_peco) else (
                        ps_val[0] if isinstance(ps_val, tuple) else ps_val
                    )
                else:
                    mult = loader.get_mastery_multiplier(mastery_key, build)

                bonus = mastery_level * mult
                note = f"{mastery_key} Lv {mastery_level} for {weapon.weapon_type} ({weapon.hand} hand) (+{bonus})"
                formula = f"dmg + (mastery_level * {mult})"

        pmf = _add_flat(pmf, bonus)

        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            name="Mastery Fix",
            value=av,
            min_value=mn,
            max_value=mx,
            multiplier=1.0,
            note=note,
            formula=formula,
            hercules_ref="battle.c: damage = battle->add_mastery(sd, target, damage, left_hand);"
        )

        # ASC_KATAR: Advanced Katar Mastery — percentage bonus on top of flat AS_KATAR.
        # Source: battle.c:927-929 #else (pre-renewal):
        #   if (weapontype == W_KATAR && skill_id != ASC_BREAKER && weapon)
        #       damage += damage * (10 + 2 * skill2_lv) / 100;
        asc_katar_lv = _mastery.get("ASC_KATAR", 0)
        if weapon.weapon_type == "Katar" and asc_katar_lv > 0:
            ratio = 100 + 10 + 2 * asc_katar_lv   # e.g. lv5 → 120, lv10 → 130
            pmf = _scale_floor(pmf, ratio, 100)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                name="Adv. Katar Mastery",
                value=av,
                min_value=mn,
                max_value=mx,
                multiplier=ratio / 100,
                note=f"ASC_KATAR Lv {asc_katar_lv}: ×{ratio / 100:.2f}",
                formula=f"dmg * (100 + 10 + 2 × {asc_katar_lv}) / 100",
                hercules_ref="battle.c:927-929 #else: damage += damage * (10 + 2 * skill2_lv) / 100"
            )

        # NJ_TOBIDOUGU: skill-based mastery for NJ_SYURIKEN — flat +3*lv damage.
        # battle.c:843-850: case NJ_SYURIKEN: if (NJ_TOBIDOUGU > 0 && weapon) damage += 3 * skill2_lv;
        # The check is on the skill being NJ_SYURIKEN, NOT on weapon_type.
        nj_tobi_lv = _mastery.get("NJ_TOBIDOUGU", 0)
        if skill is not None and skill.name == "NJ_SYURIKEN" and nj_tobi_lv > 0:
            pmf = _add_flat(pmf, 3 * nj_tobi_lv)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                name="Throw Mastery",
                value=av,
                min_value=mn,
                max_value=mx,
                multiplier=1.0,
                note=f"NJ_TOBIDOUGU Lv {nj_tobi_lv}: +{3 * nj_tobi_lv}",
                formula=f"dmg + 3 × {nj_tobi_lv}",
                hercules_ref="battle.c:843-850 case NJ_SYURIKEN: if(NJ_TOBIDOUGU>0 && weapon) damage += 3 * skill2_lv",
            )

        # NJ_KUNAI: flat +60 mastery pre-renewal.
        # battle.c:852-855 #ifndef RENEWAL: case NJ_KUNAI: if(weapon) damage += 60;
        if skill is not None and skill.name == "NJ_KUNAI":
            pmf = _add_flat(pmf, 60)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                name="Kunai Mastery",
                value=av,
                min_value=mn,
                max_value=mx,
                multiplier=1.0,
                note="NJ_KUNAI: +60 flat (pre-renewal)",
                formula="dmg + 60",
                hercules_ref="battle.c:852-855 #ifndef RENEWAL: case NJ_KUNAI: if(weapon) damage += 60",
            )

        # TF_POISON: flat eatk +15 per level when using Envenom.
        # battle.c:511: if (skill_id == TF_POISON) eatk += 15 * skill_lv;
        if skill is not None and skill.name == "TF_POISON":
            poison_bonus = 15 * skill.level
            pmf = _add_flat(pmf, poison_bonus)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                name="Envenom Mastery",
                value=av,
                min_value=mn,
                max_value=mx,
                multiplier=1.0,
                note=f"TF_POISON Lv {skill.level}: +{poison_bonus}",
                formula=f"dmg + 15 × {skill.level}",
                hercules_ref="battle.c:511: if(skill_id==TF_POISON) eatk += 15 * skill_lv",
            )

        # BS_WEAPONRESEARCH: pre-renewal flat ATK +2 per level.
        # battle.c:5828 #ifndef RENEWAL: ATK_ADD(temp*2)
        # Applies post-defense, pre-elemental (mastery_fix position).
        bs_wr_lv = _mastery.get("BS_WEAPONRESEARCH", 0)
        if bs_wr_lv:
            pmf = _add_flat(pmf, bs_wr_lv * 2)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                name="Weapon Research",
                value=av,
                min_value=mn,
                max_value=mx,
                multiplier=1.0,
                note=f"BS_WEAPONRESEARCH Lv {bs_wr_lv}: +{bs_wr_lv * 2}",
                formula=f"dmg + {bs_wr_lv * 2}",
                hercules_ref="battle.c:5828 #ifndef RENEWAL: ATK_ADD(temp*2)",
            )

        return pmf