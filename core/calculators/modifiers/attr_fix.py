from __future__ import annotations
from typing import Optional
from core.models.build import PlayerBuild
from core.models.weapon import Weapon
from core.models.target import Target
from core.models.damage import DamageResult
from core.data_loader import loader
from core.server_profiles import get_profile
from pmf.operations import _scale_floor, pmf_stats

# Ground element attack amplification table (enchant_eff, by skill level 1-5)
# skill.c:25191: const int skill_enchant_eff[5] = { 10, 14, 17, 19, 20 };
_ENCHANT_EFF = (10, 14, 17, 19, 20)
# PS override (G157): levels cap at 3, different amplification values.
_PS_ENCHANT_EFF = (10, 15, 20)

# Element integer constants (ELE_*) for ground effect matching
# weapon_endow.md / Hercules elements.conf
_ELE_FIRE  = 4
_ELE_WATER = 5
_ELE_WIND  = 6

_GROUND_ELEMENT = {
    "SC_VOLCANO":    _ELE_FIRE,
    "SC_DELUGE":     _ELE_WATER,
    "SC_VIOLENTGALE": _ELE_WIND,
}


class AttrFix:
    """Element damage multiplier (after active status bonuses, verbatim position in battle_calc_weapon_attack)."""

    @staticmethod
    def calculate(weapon: Optional[Weapon], target: Target, pmf: dict, result: DamageResult,
                  build: PlayerBuild | None = None,
                  atk_element: int | None = None) -> dict:
        """atk_element: effective attacking element. If None, uses weapon.element (auto-attack path).
        For skills: pass the skill's element from skills.json (battle.c:4807 skill->get_ele()).
        Ele_Weapon / Ele_Endowed / Ele_Random fall back to weapon.element at the call site."""
        eff_ele = atk_element if atk_element is not None else weapon.element
        defending = loader.get_element_name(target.element)
        attacking = loader.get_element_name(eff_ele)
        multiplier = loader.get_attr_fix_multiplier(attacking, defending, target.element_level or 1)

        # Ground element attack amplification: ratio += enchant_eff[lv-1] when
        # attack element matches the ground element.
        # battle.c:395-400 (inside battle_attr_fix, applies to attacker's SC):
        #   if(sc->data[SC_VOLCANO] && atk_elem == ELE_FIRE)
        #       ratio += skill->enchant_eff[sc->data[SC_VOLCANO]->val1-1];
        # (same pattern for SC_DELUGE/ELE_WATER and SC_VIOLENTGALE/ELE_WIND)
        # Pre-renewal: element check for the stat bonus is separate; the ratio
        # amplification has NO element check on the attacker's armor — it only
        # checks atk_elem (the weapon/skill attack element).
        if build is not None:
            ge = build.support_buffs.get("ground_effect")
            if ge in _GROUND_ELEMENT and eff_ele == _GROUND_ELEMENT[ge]:
                ge_lv = int(build.support_buffs.get("ground_effect_lv", 1))
                _profile = get_profile(build.server)
                _eff_table = _PS_ENCHANT_EFF if "GROUND_EFFECT_PS_VALUES" in _profile.mechanic_flags else _ENCHANT_EFF
                enchant_bonus = _eff_table[ge_lv - 1]
                multiplier += enchant_bonus
                result.add_step(
                    name=f"{ge} enchant",
                    value=None,
                    note=f"Ground enchant Lv{ge_lv}: +{enchant_bonus}% to element ratio",
                    formula=f"enchant_eff[{ge_lv}-1] = {enchant_bonus}",
                    hercules_ref=f"battle.c:395-400 ratio+=skill->enchant_eff[val1-1]; skill.c:25191",
                )

        pmf = _scale_floor(pmf, multiplier, 100)

        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            name="Attr Fix",
            value=av,
            min_value=mn,
            max_value=mx,
            multiplier=multiplier / 100.0,
            note=f"{attacking} vs {defending} Lv{target.element_level or 1} ({multiplier}%)",
            formula=f"dmg * {multiplier} // 100 (from attr_fix table + ground enchant)",
            hercules_ref="battle.c: if (tstatus->ele) wd.damage = battle_calc_elem_damage(...);"
        )
        return pmf