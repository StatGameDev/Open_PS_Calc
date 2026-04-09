from __future__ import annotations
from typing import Optional
from core.models.build import PlayerBuild
from core.models.gear_bonuses import GearBonuses
from core.models.target import Target
from core.models.damage import DamageResult
from pmf.operations import _scale_floor, pmf_stats

# Map target.race display names → RC_* keys used in GearBonuses dicts
_RACE_TO_RC = {
    "Formless":  "RC_Formless",
    "Undead":    "RC_Undead",
    "Brute":     "RC_Brute",
    "Plant":     "RC_Plant",
    "Insect":    "RC_Insect",
    "Fish":      "RC_Fish",
    "Demon":     "RC_Demon",
    "Demi-Human": "RC_DemiHuman",
    "Angel":     "RC_Angel",
    "Dragon":    "RC_Dragon",
}

# Map target.element int → Ele_* keys
_ELE_TO_KEY = {
    0: "Ele_Neutral", 1: "Ele_Water",  2: "Ele_Earth", 3: "Ele_Fire",
    4: "Ele_Wind",    5: "Ele_Poison", 6: "Ele_Holy",  7: "Ele_Dark",
    8: "Ele_Ghost",   9: "Ele_Undead",
}

# Map target.size display names → Size_* keys
_SIZE_TO_KEY = {
    "Small":  "Size_Small",
    "Medium": "Size_Medium",
    "Large":  "Size_Large",
}


class CardFix:
    """Card and equipment bonus multipliers applied after AttrFix.

    Attacker side: race/element/size damage bonuses from equipped cards/gear.
    Target side (is_pc=True only): sub_ele/sub_size/sub_race resist from
    target's own equipped cards (populated when PvP is wired in Session D).

    Sources: battle.c battle_calc_weapon_attack, bAddRace/bAddEle/bAddSize
    bonus application; bSubEle/bSubRace/bSubSize for PC target reduction.
    G11: bLongAtkRate applied here for ranged attacks only.
    """

    @staticmethod
    def calculate(build: PlayerBuild,
                  gear_bonuses: GearBonuses,
                  atk_element: int,
                  target: Target,
                  is_ranged: bool,
                  pmf: dict,
                  result: DamageResult) -> dict:

        # --- Attacker-side bonuses ---
        race_rc      = _RACE_TO_RC.get(target.race, "")
        boss_rc      = "RC_Boss" if target.is_boss else "RC_NonBoss"
        ele_key      = _ELE_TO_KEY.get(target.element, "")
        size_key     = _SIZE_TO_KEY.get(target.size, "")
        atk_ele_key  = _ELE_TO_KEY.get(atk_element, "Ele_Neutral")

        add_race = gear_bonuses.add_race
        add_ele  = gear_bonuses.add_ele
        add_size = gear_bonuses.add_size

        # battle.c:1183-1198 — five separate multiplicative steps (melee, non-left path).
        # RC_All is decomposed into RC_Boss/RC_NonBoss at storage time (gear_bonus_aggregator.py).
        # Ele_All / Size_All are our custom additive-within-step extensions; no Hercules equivalent.
        # battle.c:1261-1262 (#ifndef RENEWAL) — long ATK rate as a sixth multiplicative step.
        # bAddAtkEle: PS-custom seventh step, keyed on the outgoing attack element (not target element).
        race_bonus    = add_race.get(race_rc, 0)                                    # ① specific race
        ele_bonus     = add_ele.get(ele_key, 0) + add_ele.get("Ele_All", 0)        # ② target element
        size_bonus    = add_size.get(size_key, 0) + add_size.get("Size_All", 0)    # ③ size
        boss_bonus    = add_race.get(boss_rc, 0)                                    # ④ boss/nonboss class
        long_bonus    = gear_bonuses.long_atk_rate if is_ranged else 0              # ⑤ long ATK
        atk_ele_bonus = gear_bonuses.add_atk_ele.get(atk_ele_key, 0)               # ⑥ attack element

        mn_in, mx_in, av_in = pmf_stats(pmf)

        for bonus in (race_bonus, ele_bonus, size_bonus, boss_bonus, long_bonus, atk_ele_bonus):
            if bonus:
                pmf = _scale_floor(pmf, 100 + bonus, 100)

        # --- Target-side reductions (PvP only — all dicts empty for mob targets) ---
        # battle.c:1269-1341 target-side path — each reduction is its own multiplicative step.
        # Player attacker is always Size_Medium, RC_DemiHuman, RC_NonBoss.
        # atk_ele_key is the resolved effective attack element (accounts for endow, skill element, PS overrides).
        if target.is_pc:
            t_ele  = target.sub_ele.get(atk_ele_key, 0) + target.sub_ele.get("Ele_All", 0)
            t_size = target.sub_size.get("Size_Medium", 0)
            t_race = target.sub_race.get("RC_DemiHuman", 0)
            t_near_long = (target.long_attack_def_rate if is_ranged else target.near_attack_def_rate)
            for reduction in (t_ele, t_size, t_race, t_near_long):
                if reduction:
                    pmf = _scale_floor(pmf, 100 - reduction, 100)

        mn, mx, av = pmf_stats(pmf)
        multiplier = (av / av_in) if av_in else 1.0
        result.add_step(
            name="Card Fix",
            value=av,
            min_value=mn,
            max_value=mx,
            multiplier=multiplier,
            note=(f"Race {race_rc}+{race_bonus}%"
                  f"  {'Boss' if target.is_boss else 'NonBoss'}+{boss_bonus}%"
                  f"  Ele+{add_ele.get(ele_key,0)}%"
                  f"  Size+{add_size.get(size_key,0)}%"
                  + (f"  LongAtk+{long_bonus}%" if is_ranged else "")
                  + (f"  AtkEle({atk_ele_key})+{atk_ele_bonus}%" if atk_ele_bonus else "")),
            formula=(f"dmg × (100+{race_bonus})/100 × (100+{ele_bonus})/100"
                     f" × (100+{size_bonus})/100 × (100+{boss_bonus})/100"
                     + (f" × (100+{long_bonus})/100" if long_bonus else "")
                     + (f" × (100+{atk_ele_bonus})/100" if atk_ele_bonus else "")),
            hercules_ref="battle.c:1183-1198 bAddRace/bAddEle/bAddSize multiplicative chain; battle.c:1261 bLongAtkRate",
        )

        return pmf

    @staticmethod
    def calculate_incoming_physical(
        mob_race: str,
        mob_element: int,
        mob_size: str,
        is_ranged: bool,
        player_target: Target,
        pmf: dict,
        result: DamageResult,
    ) -> dict:
        """Target-side CardFix for incoming physical (mob → player).

        Mob has no gear, so attacker-side bonuses are zero.
        Player's sub_ele/sub_race/sub_size and near/long_attack_def_rate apply,
        keyed against the mob's actual element, race, and size.
        Source: battle.c battle_calc_cardfix cflag=0, target-side path.
        """
        mn, mx, av = pmf_stats(pmf)
        if not player_target.is_pc:
            result.add_step(
                name="Card Fix (Incoming Physical)",
                value=av, min_value=mn, max_value=mx,
                multiplier=1.0,
                note="target is not a player — no card resist",
                formula="no change",
                hercules_ref="battle.c battle_calc_cardfix: target-side only for is_pc",
            )
            return pmf

        ele_key  = _ELE_TO_KEY.get(mob_element, "Ele_Neutral")
        race_rc  = _RACE_TO_RC.get(mob_race, "")
        size_key = _SIZE_TO_KEY.get(mob_size, "")

        # battle.c:1269-1341 target-side path — each reduction is its own multiplicative step.
        mn_in, mx_in, av_in = pmf_stats(pmf)
        t_ele       = player_target.sub_ele.get(ele_key, 0) + player_target.sub_ele.get("Ele_All", 0)
        t_size      = player_target.sub_size.get(size_key, 0)
        t_race      = player_target.sub_race.get(race_rc, 0)
        t_near_long = (player_target.long_attack_def_rate if is_ranged else player_target.near_attack_def_rate)
        for reduction in (t_ele, t_size, t_race, t_near_long):
            if reduction:
                pmf = _scale_floor(pmf, 100 - reduction, 100)

        mn, mx, av = pmf_stats(pmf)
        multiplier = (av / av_in) if av_in else 1.0
        result.add_step(
            name="Card Fix (Incoming Physical)",
            value=av, min_value=mn, max_value=mx,
            multiplier=multiplier,
            note=(f"Ele({ele_key})-{player_target.sub_ele.get(ele_key,0)}%"
                  f"  Size({size_key})-{t_size}%"
                  f"  Race({race_rc})-{t_race}%"
                  f"  {'Long' if is_ranged else 'Near'}Def-{t_near_long}%"),
            formula=(f"dmg × (100-{t_ele})/100 × (100-{t_size})/100"
                     f" × (100-{t_race})/100 × (100-{t_near_long})/100"),
            hercules_ref="battle.c:1269-1341 cflag=0 target-side: sub_ele/sub_size/sub_race/near_long_attack_def_rate",
        )
        return pmf

    @staticmethod
    def calculate_incoming_magic(
        mob_race: str,
        magic_ele_name: str,
        player_target: Target,
        pmf: dict,
        result: DamageResult,
    ) -> dict:
        """Target-side CardFix for incoming magic (mob → player).

        Like calculate_magic but uses the mob's actual race instead of hardcoded
        RC_DemiHuman. Attacker-side magic bonuses are Renewal-only — skipped.
        Source: battle.c battle_calc_cardfix cflag=0 BF_MAGIC, target-side path.
        """
        mn, mx, av = pmf_stats(pmf)
        if not player_target.is_pc:
            result.add_step(
                name="Card Fix (Incoming Magic)",
                value=av, min_value=mn, max_value=mx,
                multiplier=1.0,
                note="target is not a player — no magic card resist",
                formula="no change",
                hercules_ref="battle.c battle_calc_cardfix: target-side only for is_pc",
            )
            return pmf

        race_rc = _RACE_TO_RC.get(mob_race, "")

        # battle.c:1086-1143 target-side path — each reduction is its own multiplicative step.
        mn_in, mx_in, av_in = pmf_stats(pmf)
        t_ele       = player_target.sub_ele.get(magic_ele_name, 0) + player_target.sub_ele.get("Ele_All", 0)
        t_race      = player_target.sub_race.get(race_rc, 0)
        t_magic_def = player_target.magic_def_rate
        for reduction in (t_ele, t_race, t_magic_def):
            if reduction:
                pmf = _scale_floor(pmf, 100 - reduction, 100)

        mn, mx, av = pmf_stats(pmf)
        multiplier = (av / av_in) if av_in else 1.0
        result.add_step(
            name="Card Fix (Incoming Magic)",
            value=av, min_value=mn, max_value=mx,
            multiplier=multiplier,
            note=(f"Ele({magic_ele_name})-{player_target.sub_ele.get(magic_ele_name,0)}%"
                  f"  Race({race_rc})-{t_race}%"
                  f"  MagicDef-{t_magic_def}%"),
            formula=(f"dmg × (100-{t_ele})/100 × (100-{t_race})/100 × (100-{t_magic_def})/100"),
            hercules_ref="battle.c:1086-1143 cflag=0 BF_MAGIC target-side: sub_ele/sub_race/magic_def_rate",
        )
        return pmf

    @staticmethod
    def calculate_magic(target: Target, magic_ele_name: str,
                        pmf: dict, result: DamageResult,
                        gear_bonuses: Optional[GearBonuses] = None) -> dict:
        """BF_MAGIC CardFix — attacker-side magic race bonus + target-side resist (is_pc only).

        Attacker-side (battle.c:1073–1077, no RENEWAL guard):
          cardfix *= (100 + magic_addrace[target_race]) / 100
          cardfix *= (100 + magic_addrace[RC_BOSS or RC_NONBOSS]) / 100
          Note: bAddRace (right_weapon.addrace) is NOT applied to magic in any version.
          magic_addrace is a separate field set by bMagicAddRace cards and SA_DRAGONOLOGY.
        Target-side (is_pc only): sub_ele, sub_race (RC_DemiHuman), magic_def_rate.
        """
        # --- Attacker-side race bonus (all targets) ---
        # battle.c:1072-1085 — two separate multiplicative steps: specific race then boss/nonboss class.
        # RC_All is decomposed into RC_Boss/RC_NonBoss at storage time (gear_bonus_aggregator.py).
        mn_in, mx_in, av_in = pmf_stats(pmf)
        race_bonus = 0
        boss_bonus = 0
        if gear_bonuses is not None:
            mar = gear_bonuses.magic_add_race
            race_rc = _RACE_TO_RC.get(target.race, "")
            boss_rc = "RC_Boss" if target.is_boss else "RC_NonBoss"
            race_bonus = mar.get(race_rc, 0)
            boss_bonus = mar.get(boss_rc, 0)
            for bonus in (race_bonus, boss_bonus):
                if bonus:
                    pmf = _scale_floor(pmf, 100 + bonus, 100)

        mn, mx, av = pmf_stats(pmf)
        if not target.is_pc:
            multiplier = (av / av_in) if av_in else 1.0
            result.add_step(
                name="Card Fix (Magic)",
                value=av, min_value=mn, max_value=mx,
                multiplier=multiplier,
                note=(f"MagicRace {race_rc}+{race_bonus}%"
                      f"  {'Boss' if target.is_boss else 'NonBoss'}+{boss_bonus}%"
                      if (race_bonus or boss_bonus) else "no magic card bonuses"),
                formula=(f"dmg × (100+{race_bonus})/100 × (100+{boss_bonus})/100"
                         if (race_bonus or boss_bonus) else "no change"),
                hercules_ref="battle.c:1072-1085 BF_MAGIC attacker-side magic_addrace multiplicative chain",
            )
            return pmf

        # --- Target-side resist (is_pc only) ---
        # battle.c:1086-1143 — each reduction is its own multiplicative step.
        # Player attacker is always RC_DemiHuman; near/long_attack_def_rate applies pre-renewal.
        t_ele       = target.sub_ele.get(magic_ele_name, 0) + target.sub_ele.get("Ele_All", 0)
        t_race      = target.sub_race.get("RC_DemiHuman", 0)
        t_magic_def = target.magic_def_rate
        for reduction in (t_ele, t_race, t_magic_def):
            if reduction:
                pmf = _scale_floor(pmf, 100 - reduction, 100)

        mn, mx, av = pmf_stats(pmf)
        multiplier = (av / av_in) if av_in else 1.0
        result.add_step(
            name="Card Fix (Magic)",
            value=av, min_value=mn, max_value=mx,
            multiplier=multiplier,
            note=(f"MagicRace {race_rc}+{race_bonus}%"
                  f"  {'Boss' if target.is_boss else 'NonBoss'}+{boss_bonus}%"
                  f"  Ele({magic_ele_name})-{target.sub_ele.get(magic_ele_name,0)}%"
                  f"  Race(DemiHuman)-{target.sub_race.get('RC_DemiHuman',0)}%"
                  f"  MagicDef-{target.magic_def_rate}%"),
            formula=(f"dmg × (100+{race_bonus})/100 × (100+{boss_bonus})/100"
                     f" × (100-{t_ele})/100 × (100-{t_race})/100 × (100-{t_magic_def})/100"),
            hercules_ref="battle.c:1072-1085 BF_MAGIC attacker-side; battle.c:1086-1143 target-side sub_ele/sub_race/magic_def_rate",
        )
        return pmf
