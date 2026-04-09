from core.models.damage import DamageResult
from pmf.operations import _uniform_pmf, _scale_floor, pmf_stats
from core.models.target import Target
from core.models.build import PlayerBuild
from core.models.gear_bonuses import GearBonuses
from core.config import BattleConfig
from core.data_loader import loader
from core.calculators.modifiers.defense_fix import DefenseFix
from core.calculators.modifiers.card_fix import CardFix


class IncomingPhysicalPipeline:
    """
    Pre-renewal incoming physical damage pipeline (mob → player).

    Step order:
      MobBaseATK — weapon roll [atk_min, atk_max−1] + batk (fixed at spawn)
      AttrFix    — mob element vs player armor element
      DefenseFix — BF_WEAPON, player as defender (is_pc=True → PC VIT DEF formula)
      CardFix    — target-side only (player resistance cards; mob has no gear)

    Mob ATK is computed internally from mob_db. The mob_atk_bonus_rate parameter
    provides a %-modifier on the weapon component for buff/debuff support
    (e.g. Provoke = +23, Curse = negative). The caller computes the combined
    net rate from active SCs and passes it here.
    Batk is kept separate because Hercules buffs target rhw.atk/atk2, not batk.

    Source: battle.c battle_calc_base_damage2 (#else RENEWAL);
            mob.c:4937 mob_read_db_sub;
            status.c:3749-3774 status_base_atk BL_MOB (#else not RENEWAL).
    """

    def __init__(self, config: BattleConfig):
        self.config = config

    def calculate(
        self,
        mob_id: int,
        player_target: Target,
        gear_bonuses: GearBonuses,
        build: PlayerBuild,
        is_ranged: bool = False,
        mob_atk_bonus_rate: int = 0,   # % modifier to weapon component (Provoke, Curse, etc.)
        ele_override: int | None = None,  # None = Mob Natural (→ Neutral); int 0-9 = element override
    ) -> DamageResult:
        result = DamageResult()

        mob_data = loader.get_monster_data(mob_id)
        if mob_data is None:
            return result

        mob_name          = mob_data.get("name", f"Mob {mob_id}")
        mob_element       = mob_data.get("element", 0)
        # ele_override: UI "Ele" dropdown. None = "Mob Natural" → treat as Neutral (0).
        # Controls both AttrFix and CardFix element lookup for the incoming attack.
        eff_element = ele_override if ele_override is not None else 0
        mob_race          = mob_data.get("race", "Formless")
        mob_size          = mob_data.get("size", "Medium")
        db_atk_min        = mob_data.get("atk_min", 1)
        db_atk_max        = mob_data.get("atk_max", 1)
        mob_str           = mob_data.get("stats", {}).get("str", 0)

        # --- Mob Base ATK ---
        # BATK: str + (str//10)^2 — pre-renewal BL_MOB path (no dex/luk terms).
        # status.c:3749-3774 status_base_atk #else not RENEWAL, BL_MOB case.
        batk = mob_str + (mob_str // 10) ** 2

        # Weapon component roll: rnd()%(atk2 - atk1) + atk1 → [atk_min, atk_max-1]
        # mob_atk_bonus_rate mirrors SC effects that change rhw.atk/atk2 post-spawn.
        # Applied to weapon component only (batk is a separate status field).
        atk_min = db_atk_min * (100 + mob_atk_bonus_rate) // 100 if mob_atk_bonus_rate else db_atk_min
        atk_max = db_atk_max * (100 + mob_atk_bonus_rate) // 100 if mob_atk_bonus_rate else db_atk_max

        eff_min = atk_min + batk
        eff_max = max(eff_min, (atk_max - 1) + batk)
        eff_avg = (eff_min + eff_max) // 2

        modifier_note = f" ×{100 + mob_atk_bonus_rate}% weapon component" if mob_atk_bonus_rate else ""
        pmf: dict = _uniform_pmf(eff_min, eff_max)

        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            name="Mob Base ATK",
            value=av,
            min_value=mn,
            max_value=mx,
            note=(f"{mob_name}: weapon [{db_atk_min}, {db_atk_max - 1}]"
                  f" + batk {batk} (str {mob_str}){modifier_note}"
                  f" → [{eff_min}, {eff_max}] (fixed at spawn)"),
            formula="rnd(atk_min, atk_max-1) + str + (str//10)^2",
            hercules_ref="mob.c:4937 mob_read_db_sub rhw.atk/atk2;\n"
                         "status.c:3749 status_base_atk BL_MOB (#else not RENEWAL)",
        )

        # --- Attr Fix: attack element vs player armor element ---
        # eff_element drives both AttrFix and CardFix (Mob Natural → Neutral).
        atk_ele_name    = loader.get_element_name(eff_element)
        player_ele_name = loader.get_element_name(player_target.armor_element)
        multiplier = loader.get_attr_fix_multiplier(
            atk_ele_name, player_ele_name, player_target.element_level or 1
        )
        if multiplier != 100:
            pmf = _scale_floor(pmf, multiplier, 100)
        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            name="Attr Fix",
            value=av,
            min_value=mn,
            max_value=mx,
            multiplier=multiplier / 100.0,
            note=f"{atk_ele_name} vs {player_ele_name} Lv{player_target.element_level or 1} ({multiplier}%)",
            formula=f"dmg * {multiplier} // 100",
            hercules_ref="battle.c: battle_calc_elem_damage (attr_fix table)",
        )

        # --- Defense Fix: player as defender, is_pc=True → PC VIT DEF formula ---
        # Mob is the attacker — no gear, so no ignore_def bonuses (empty GearBonuses).
        # build=None: getattr(None, "ignore_hard_def", False) → False, which is correct
        # (mob attacks cannot ignore player hard DEF via gear cards).
        pmf = DefenseFix.calculate(
            target=player_target,
            build=None,
            gear_bonuses=GearBonuses(),
            pmf=pmf,
            config=self.config,
            result=result,
            is_crit=False,
        )

        # --- Card Fix: target-side only (player resistance cards vs mob attacker) ---
        # Mob has no attacker-side gear. Player's sub_ele/sub_race/sub_size and
        # near/long_attack_def_rate are keyed against mob's actual element/race/size.
        pmf = CardFix.calculate_incoming_physical(
            mob_race=mob_race,
            mob_element=eff_element,
            mob_size=mob_size,
            is_ranged=is_ranged,
            player_target=player_target,
            pmf=pmf,
            result=result,
        )

        # --- PR_LEXAETERNA ×2 ---
        # Source: same as outgoing — battle.c SC_LEXAETERNA doubles the next hit.
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
            "Final Incoming Physical Damage",
            value=av,
            min_value=mn,
            max_value=mx,
            note="mob → player, pre-renewal BF_WEAPON",
            formula="",
            hercules_ref="",
        )

        result.min_damage = mn
        result.max_damage = mx
        result.avg_damage = av
        result.pmf = pmf

        return result
