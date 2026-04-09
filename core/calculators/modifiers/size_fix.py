from core.models.weapon import Weapon
from core.models.build import PlayerBuild
from core.models.target import Target
from core.models.damage import DamageRange, DamageResult
from core.models.skill import SkillInstance
from core.data_loader import loader


class SizeFix:
    """Exact Size Fix step for BF_WEAPON attacks in pre-renewal.
    Source lines (verbatim from repo):
    battle.c: if (!(sd->special_state.no_sizefix || (flag&8)))
    battle.c:     damage = damage * ( type == EQI_HAND_L ? sd->left_weapon.atkmods[t_size] : sd->right_weapon.atkmods[t_size] ) / 100;
    status.c: sd->right_weapon.atkmods[0] = status->dbs->atkmods[0][sd->weapontype1];
    status.c: sd->right_weapon.atkmods[1] = status->dbs->atkmods[1][sd->weapontype1];
    status.c: sd->right_weapon.atkmods[2] = status->dbs->atkmods[2][sd->weapontype1];"""

    @staticmethod
    def calculate(weapon: Weapon, build: PlayerBuild, target: Target, dmg: DamageRange, skill: SkillInstance, result: DamageResult) -> DamageRange:
        if build.no_sizefix or skill.ignore_size_fix:
            rate = 100
            note = "no_sizefix or flag&8 active – size fix bypassed"
        else:
            rate = loader.get_size_fix_multiplier(weapon.weapon_type, target.size)
            note = f"{weapon.weapon_type} vs {target.size} target ({weapon.hand} hand)"

        dmg = dmg.scale(rate, 100)

        result.add_step(
            name="Size Fix",
            value=dmg.avg,
            min_value=dmg.min,
            max_value=dmg.max,
            multiplier=rate / 100.0,
            note=note,
            formula=f"dmg * {rate} // 100   (size_fix table[{target.size}][{weapon.weapon_type}])",
            hercules_ref="battle.c: if (!(sd->special_state.no_sizefix || (flag&8)))\n"
                         "    damage = damage * ( type == EQI_HAND_L ? sd->left_weapon.atkmods[t_size] : sd->right_weapon.atkmods[t_size] ) / 100;\n"
                         "status.c: sd->right_weapon.atkmods[0] = status->dbs->atkmods[0][sd->weapontype1];\n"
                         "status.c: sd->right_weapon.atkmods[1] = status->dbs->atkmods[1][sd->weapontype1];\n"
                         "status.c: sd->right_weapon.atkmods[2] = status->dbs->atkmods[2][sd->weapontype1];"
        )
        return dmg