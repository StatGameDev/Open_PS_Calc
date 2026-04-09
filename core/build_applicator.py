"""
build_applicator — Apply gear bonuses, pet bonuses, and consumable buffs to PlayerBuild.

Business logic for stacking all bonus sources (gear scripts, manual adjustments,
consumables, clan bonuses, pet bonuses, weapon endow) onto a PlayerBuild. Extracted
from the GUI layer — all build mutation belongs in core.

Called by resolve_player_state() (player_state_builder.py) during both gear passes.
"""
import dataclasses

from core.models.build import PlayerBuild
from core.models.gear_bonuses import GearBonuses


def compute_consumable_bonuses(consumable_buffs: dict) -> dict[str, int]:
    """Map consumable_buffs keys to stat deltas. Called inside apply_gear_bonuses().

    SC conflict routing: each SC slot takes the max of all sources.
    (Hercules sc_start blocks lower val1, status.c:7362-7363)
    Per-stat food, all-stat food, and Grilled Corn all write to the same
    SC_FOOD_STR/AGI/etc. slots → effective = max(food_X, food_all, grilled_corn_component).
    """
    cb = consumable_buffs
    result: dict[str, int] = {}

    # All-stats food baseline (contributes to every stat slot)
    food_all = int(cb.get("food_all", 0))

    # Grilled Corn: +2 STR/AGI/INT (SC_FOOD_*; competes with per-stat and all-stat food)
    grilled_corn = bool(cb.get("grilled_corn", False))
    gc = 2 if grilled_corn else 0

    # Stat foods: max() per SC slot (status.c:7362-7363)
    # food_str/agi/int also compete with grilled_corn; food_vit/dex/luk do not
    str_food = max(int(cb.get("food_str", 0)), food_all, gc)
    agi_food = max(int(cb.get("food_agi", 0)), food_all, gc)
    vit_food = max(int(cb.get("food_vit", 0)), food_all)
    int_food = max(int(cb.get("food_int", 0)), food_all, gc)
    dex_food = max(int(cb.get("food_dex", 0)), food_all)
    luk_food = max(int(cb.get("food_luk", 0)), food_all)

    if str_food: result["str"] = str_food
    if agi_food: result["agi"] = agi_food
    if vit_food: result["vit"] = vit_food
    if int_food: result["int"] = int_food
    if dex_food: result["dex"] = dex_food
    if luk_food: result["luk"] = luk_food

    # ASPD potions: SC_ATTHASTE_POTION1/2/3 (status.c:7851, 5661-5663)
    # aspd_rate -= 100/150/200 out of 1000 → 10/15/20% faster
    _ASPD_VALS = (0, 10, 15, 20)
    aspd_potion = int(cb.get("aspd_potion", 0))
    if aspd_potion:
        result["aspd_percent"] = _ASPD_VALS[aspd_potion]

    # HIT food: SC_FOOD_BASICHIT hit += val1 (status.c:4799-4800)
    hit_food = int(cb.get("hit_food", 0))
    if hit_food:
        result["hit"] = hit_food

    # FLEE food: SC_FOOD_BASICAVOIDANCE flee += val1 (status.c:4864-4865)
    flee_food = int(cb.get("flee_food", 0))
    if flee_food:
        result["flee"] = flee_food

    # CRI food: SC_FOOD_CRITICALSUCCESSVALUE critical += val1 (status.c:4751-4752, no 10× scale)
    if cb.get("cri_food"):
        result["cri"] = 7

    # ATK items: SC_PLUSATTACKPOWER batk += val1 (status.c:4476, #ifndef RENEWAL)
    atk_item = int(cb.get("atk_item", 0))
    if atk_item:
        result["batk"] = atk_item

    # MATK flat: SC_PLUSMAGICPOWER (matk_item) + SC_MATKFOOD (matk_food) — separate SC slots, stack
    # SC_PLUSMAGICPOWER: matk += val1 (status.c:4635-4636)
    # SC_MATKFOOD:       matk += val1 (status.c:4637-4638)
    matk_flat = int(cb.get("matk_item", 0))
    if cb.get("matk_food"):
        matk_flat += 10
    if matk_flat:
        result["matk_flat"] = matk_flat

    return result


_ENDOW_SC_ELEMENT: dict[str, int] = {
    "SC_PROPERTYFIRE":   3,  # Fire  (get_element_name: 3→Fire)
    "SC_PROPERTYWATER":  1,  # Water (get_element_name: 1→Water)
    "SC_PROPERTYWIND":   4,  # Wind  (get_element_name: 4→Wind)
    "SC_PROPERTYGROUND": 2,  # Earth (get_element_name: 2→Earth)
}


def apply_weapon_endow(eff_build: PlayerBuild) -> None:
    """Resolve weapon endow SC onto eff_build.weapon_element (mutates in place).

    Priority: SC_ENCHANTPOISON (self-cast) > support weapon_endow_sc > SC_ASPERSIO.
    Moved from gui/main_window.py — build-level logic belongs in core.
    """
    if "SC_ENCHANTPOISON" in eff_build.active_status_levels:
        eff_build.weapon_element = 5  # Poison
    else:
        endow_sc = eff_build.support_buffs.get("weapon_endow_sc")
        if endow_sc:
            eff_build.weapon_element = _ENDOW_SC_ELEMENT[endow_sc]
        elif eff_build.support_buffs.get("SC_ASPERSIO"):
            eff_build.weapon_element = 6  # Holy


_CLAN_STATS: dict[str, dict[str, int]] = {
    "sword_clan":      {"str": 1, "vit": 1, "maxhp": 30, "maxsp": 10},
    "arch_wand_clan":  {"int": 1, "dex": 1, "maxhp": 30, "maxsp": 10},
    "golden_mace_clan":{"int": 1, "vit": 1, "maxhp": 30, "maxsp": 10},
    "crossbow_clan":   {"dex": 1, "agi": 1, "maxhp": 30, "maxsp": 10},
    "artisan_clan":    {"dex": 1, "luk": 1, "maxhp": 30, "maxsp": 10},
    "vile_wind_clan":  {"str": 1, "agi": 1, "maxhp": 30, "maxsp": 10},
}


def apply_gear_bonuses(build: PlayerBuild, gear_bonuses: GearBonuses) -> PlayerBuild:
    """Return a new PlayerBuild with all bonus sources stacked on top of base values.

    Sources stacked: gear scripts (GearBonuses) + Manual Adj + consumable buffs.
    SC stat buffs (SC_BLESSING, SC_INC_AGI, SC_GLORIA) are applied directly in
    StatusCalculator after SC_CONCENTRATION to preserve Hercules ordering.

    The original build is unchanged so save_build always writes clean values.
    Caller must pass a GearBonuses already augmented with apply_passive_bonuses()
    if passive skill bonuses should feed into player_build_to_target.
    """
    gb = gear_bonuses
    ma = build.manual_adj_bonuses
    cons = compute_consumable_bonuses(build.consumable_buffs)
    cl = _CLAN_STATS.get(build.clan, {})
    return dataclasses.replace(
        build,
        bonus_str=build.bonus_str + gb.str_ + ma.get("str", 0) + cons.get("str", 0) + cl.get("str", 0),
        bonus_agi=build.bonus_agi + gb.agi + ma.get("agi", 0) + cons.get("agi", 0) + cl.get("agi", 0),
        bonus_vit=build.bonus_vit + gb.vit + ma.get("vit", 0) + cons.get("vit", 0) + cl.get("vit", 0),
        bonus_int=build.bonus_int + gb.int_ + ma.get("int", 0) + cons.get("int", 0) + cl.get("int", 0),
        bonus_dex=build.bonus_dex + gb.dex + ma.get("dex", 0) + cons.get("dex", 0) + cl.get("dex", 0),
        bonus_luk=build.bonus_luk + gb.luk + ma.get("luk", 0) + cons.get("luk", 0) + cl.get("luk", 0),
        bonus_batk=build.bonus_batk + gb.batk + ma.get("batk", 0) + cons.get("batk", 0),
        bonus_hit=build.bonus_hit + gb.hit + ma.get("hit", 0) + cons.get("hit", 0),
        bonus_flee=build.bonus_flee + gb.flee + ma.get("flee", 0) + cons.get("flee", 0),
        bonus_cri=build.bonus_cri + gb.cri + ma.get("cri", 0) + cons.get("cri", 0),
        equip_def=build.equip_def + gb.def_ + ma.get("def", 0),
        equip_mdef=build.equip_mdef + gb.mdef_ + ma.get("mdef", 0),
        bonus_maxhp=build.bonus_maxhp + gb.maxhp + ma.get("maxhp", 0) + cl.get("maxhp", 0),
        bonus_maxsp=build.bonus_maxsp + gb.maxsp + ma.get("maxsp", 0) + cl.get("maxsp", 0),
        bonus_aspd_percent=build.bonus_aspd_percent + gb.aspd_percent + ma.get("aspd_pct", 0) + cons.get("aspd_percent", 0),
        bonus_aspd_add=build.bonus_aspd_add + gb.aspd_add,
        bonus_crit_atk_rate=build.bonus_crit_atk_rate + gb.crit_atk_rate + ma.get("crit_dmg_pct", 0),
        bonus_matk_rate=build.bonus_matk_rate + gb.matk_rate,
        bonus_maxhp_rate=build.bonus_maxhp_rate + gb.maxhp_rate,
        bonus_flee2=build.bonus_flee2 + gb.flee2,
        bonus_maxsp_rate=build.bonus_maxsp_rate + gb.maxsp_rate,
        bonus_matk_flat=build.bonus_matk_flat + cons.get("matk_flat", 0),
    )


def apply_pet_bonuses(gb: GearBonuses, pet_key: str, profile) -> None:
    """Mutate GearBonuses in-place with the pet's loyal EquipScript bonuses.

    PS overrides in profile.pet_bonuses completely replace the vanilla entry.
    Called after apply_passive_bonuses(), before apply_gear_bonuses().
    Source: pet_db.conf EquipScript (loyal); status.c:1815-1823.
    """
    if not pet_key:
        return
    from core.data.pets import PET_BONUSES
    bonus = profile.pet_bonuses.get(pet_key, PET_BONUSES.get(pet_key, {}))
    if not bonus:
        return
    gb.str_          += bonus.get("str_", 0)
    gb.agi           += bonus.get("agi", 0)
    gb.vit           += bonus.get("vit", 0)
    gb.int_          += bonus.get("int_", 0)
    gb.dex           += bonus.get("dex", 0)
    gb.luk           += bonus.get("luk", 0)
    gb.batk          += bonus.get("batk", 0)
    gb.hit           += bonus.get("hit", 0)
    gb.flee          += bonus.get("flee", 0)
    gb.flee2         += bonus.get("flee2", 0)
    gb.cri           += bonus.get("cri", 0)
    gb.def_          += bonus.get("def_", 0)
    gb.mdef_         += bonus.get("mdef_", 0)
    gb.maxhp         += bonus.get("maxhp", 0)
    gb.maxsp         += bonus.get("maxsp", 0)
    gb.atk_rate      += bonus.get("atk_rate", 0)
    gb.matk_rate     += bonus.get("matk_rate", 0)
    gb.aspd_percent  += bonus.get("aspd_percent", 0)
    gb.crit_atk_rate += bonus.get("crit_atk_rate", 0)
    gb.maxhp_rate    += bonus.get("maxhp_rate", 0)
    gb.maxsp_rate    += bonus.get("maxsp_rate", 0)
    gb.castrate      += bonus.get("castrate", 0)
    for k, v in bonus.get("sub_ele", {}).items():
        gb.sub_ele[k] = gb.sub_ele.get(k, 0) + v
    for k, v in bonus.get("add_ele", {}).items():
        gb.add_ele[k] = gb.add_ele.get(k, 0) + v
    for k, v in bonus.get("sub_race", {}).items():
        gb.sub_race[k] = gb.sub_race.get(k, 0) + v
    for k, v in bonus.get("add_race", {}).items():
        gb.add_race[k] = gb.add_race.get(k, 0) + v
    for k, v in bonus.get("magic_add_race", {}).items():
        gb.magic_add_race[k] = gb.magic_add_race.get(k, 0) + v
    for k, v in bonus.get("res_eff", {}).items():
        gb.res_eff[k] = gb.res_eff.get(k, 0) + v


def resolve_armor_element(armor_element_override: int, gear_bonuses: GearBonuses) -> int:
    """Resolve effective armor element using three-tier precedence.

    Precedence:
      1. armor_element_override (non-zero = user has explicitly set an element)
      2. gear_bonuses.script_def_ele (bDefEle from equipped item scripts, e.g. Pasana Card)
      3. 0 / Neutral (all armors are Neutral by default in pre-renewal)
    """
    if armor_element_override != 0:
        return armor_element_override
    if gear_bonuses.script_def_ele is not None:
        return gear_bonuses.script_def_ele
    return 0
