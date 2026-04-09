from core.models.damage import DamageResult
from core.config import BattleConfig
from pmf.operations import _scale_floor, _floor_at, pmf_stats


class FinalRateBonus:
    """Exact pre-renewal final rate multipliers (weapon/short/long) applied at the very end.
    Source lines (verbatim from repo):
    battle.c: if (wd.flag&BF_SHORT) damage = damage * battle_config.short_attack_damage_rate / 100;
    battle.c: else damage = damage * battle_config.long_attack_damage_rate / 100;
    battle.c: damage = damage * battle_config.weapon_damage_rate / 100;"""

    @staticmethod
    def calculate(is_ranged: bool, pmf: dict, config: BattleConfig, result: DamageResult) -> dict:
        # Step 1: short/long attack rate (Hercules applies this first)
        if is_ranged:
            sl_rate = config.long_attack_damage_rate
            sl_label = "Long"
        else:
            sl_rate = config.short_attack_damage_rate
            sl_label = "Short"

        pmf = _scale_floor(pmf, sl_rate, 100)
        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            name=f"Final Rate Bonus ({sl_label})",
            value=av,
            min_value=mn,
            max_value=mx,
            multiplier=sl_rate / 100.0,
            note=f"{sl_label} attack damage rate: {sl_rate}%",
            formula=f"dmg * {sl_rate} // 100 (battle_config.{sl_label.lower()}_attack_damage_rate)",
            hercules_ref="battle.c: if (wd.flag&BF_SHORT) damage = damage * battle_config.short_attack_damage_rate / 100;\n"
                         "battle.c: else damage = damage * battle_config.long_attack_damage_rate / 100;"
        )

        # Step 2: weapon_damage_rate (Hercules applies this after short/long)
        pmf = _scale_floor(pmf, config.weapon_damage_rate, 100)
        pmf = _floor_at(pmf, 1)
        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            name="Final Rate Bonus (Weapon)",
            value=av,
            min_value=mn,
            max_value=mx,
            multiplier=config.weapon_damage_rate / 100.0,
            note=f"Weapon damage rate: {config.weapon_damage_rate}%",
            formula=f"dmg * {config.weapon_damage_rate} // 100 (battle_config.weapon_damage_rate)",
            hercules_ref="battle.c: damage = damage * battle_config.weapon_damage_rate / 100;"
        )
        return pmf