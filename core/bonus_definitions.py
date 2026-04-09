"""
Single source of truth for item script bonus type definitions.

Adding a new bonus type = one entry in BONUS1, BONUS2, BONUS3, or BONUS4.
Both item_script_parser and gear_bonus_aggregator import from here.
No imports from either of those modules — zero circular dependency risk.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

# ---------------------------------------------------------------------------
# Enum string → display name maps
# ---------------------------------------------------------------------------

RACE_NAMES: dict[str, str] = {
    "RC_Formless": "Formless", "RC_Undead": "Undead", "RC_Brute": "Brute",
    "RC_Plant": "Plant", "RC_Insect": "Insect", "RC_Fish": "Fish",
    "RC_Demon": "Demon", "RC_DemiHuman": "Demi-Human", "RC_Angel": "Angel",
    "RC_Dragon": "Dragon", "RC_Boss": "Boss monsters",
    "RC_NonBoss": "Normal monsters", "RC_All": "all races",
    "RC_DemiPlayer":    "Demi-Human & Players",
    "RC_NonDemiPlayer": "All except Demi-Human & Players",
    "RC_NonPlayer":     "All non-player races",
}

ELEMENT_NAMES: dict[str, str] = {
    "Ele_Neutral": "Neutral", "Ele_Water": "Water", "Ele_Earth": "Earth",
    "Ele_Fire": "Fire", "Ele_Wind": "Wind", "Ele_Poison": "Poison",
    "Ele_Holy": "Holy", "Ele_Dark": "Dark", "Ele_Ghost": "Ghost",
    "Ele_Undead": "Undead", "Ele_All": "all elements",
}

# Hercules element string constant → int ID (matches data_loader.get_element_name ordering)
_ELE_STR_TO_INT: dict[str, int] = {
    "Ele_Neutral": 0, "Ele_Water": 1, "Ele_Earth": 2, "Ele_Fire": 3,
    "Ele_Wind": 4, "Ele_Poison": 5, "Ele_Holy": 6, "Ele_Dark": 7,
    "Ele_Ghost": 8, "Ele_Undead": 9,
}

SIZE_NAMES: dict[str, str] = {
    "Size_Small": "Small", "Size_Medium": "Medium", "Size_Large": "Large",
    "Size_All": "all sizes",
}

STATUS_NAMES: dict[str, str] = {
    # Vanilla Eff_* constants (constants.conf) map to these SC_* keys
    "Eff_Poison":  "Poison",   "SC_POISON":   "Poison",
    "Eff_Curse":   "Curse",    "SC_CURSE":    "Curse",
    "Eff_Silence": "Silence",  "SC_SILENCE":  "Silence",
    "Eff_Sleep":   "Sleep",    "SC_SLEEP":    "Sleep",
    "Eff_Stun":    "Stun",     "SC_STUN":     "Stun",
    "Eff_Freeze":  "Freeze",   "SC_FREEZE":   "Freeze",
    "Eff_Stone":   "Stone",    "SC_STONE":    "Stone",
    "Eff_Blind":   "Blind",    "SC_BLIND":    "Blind",
    "Eff_Bleeding": "Bleeding","SC_BLEEDING": "Bleeding",
    "Eff_Confusion": "Confusion", "SC_CONFUSION": "Confusion",
    # PS-custom status effects
    "SC_PS_HYPOTHERMIA": "Hypothermia",
    "SC_CHILLED":        "Chilled",
}

CLASS_NAMES: dict[str, str] = {
    "Class_Normal": "Normal monsters", "Class_Boss": "Boss monsters",
    "Class_Guardian": "Guardians", "Class_All": "all monster types",
}


def _race(v: str) -> str:
    return RACE_NAMES.get(v, v)


def _ele(v: str) -> str:
    return ELEMENT_NAMES.get(v, v)


def _size(v: str) -> str:
    return SIZE_NAMES.get(v, v)


def _cls(v: str) -> str:
    return CLASS_NAMES.get(v, v)


def _sc(v: str) -> str:
    return STATUS_NAMES.get(v, v)


# ---------------------------------------------------------------------------
# BonusDef
# ---------------------------------------------------------------------------

@dataclass
class BonusDef:
    """
    Definition for one bonus type at a given arity.

    description  Callable producing the human-readable effect string.
                 Arity-1 signature: (int,)
                 Arity-2 signature: (str, int)   — key, value
                 Arity-3 signature: (str, str, int) or similar
    field        GearBonuses attribute name to accumulate into.
                 None = display-only (no GearBonuses mutation).
    mode         "add"       scalar: bonuses.<field> += value
                 "dict"      keyed dict: bonuses.<field>[key] += value
                             Arity-2: key from param[0] (str), value from param[1] (int).
                             Arity-1: key from param[0] (str), value fixed at 1 (presence flag).
                 "dict_keys" arity-1 int value written to each key in `keys` list.
                 "multi"     multiple scalars: each name in `fields` gets += value
                 "assign"    last-wins scalar: bonuses.<field> = transform(value)
    fields       For mode="multi": list of GearBonuses attribute names.
    transform    Optional callable applied to the raw param before assignment.
                 Used with mode="assign" to convert string tokens to int IDs.
    keys         For mode="dict_keys": fixed list of dict keys to write the int value into.
    """
    description: Callable
    field: str | None = None
    mode: str = "add"
    fields: list[str] | None = None
    transform: Callable | None = None
    keys: list[str] | None = None


# ---------------------------------------------------------------------------
# Arity-1 table  (bonus bXxx, val)
# ---------------------------------------------------------------------------
#
# field=None        →  display-only
# mode="add"        →  bonuses.<field> += v          (default)
# mode="multi"      →  each field in fields += v
# mode="dict_keys"  →  bonuses.<field>[k] += v for each k in keys

BONUS1: dict[str, BonusDef] = {
    # Stats
    "bStr":    BonusDef(lambda v: f"STR +{v}." if v > 0 else f"STR {v}.", "str_"),
    "bAgi":    BonusDef(lambda v: f"AGI +{v}." if v > 0 else f"AGI {v}.", "agi"),
    "bVit":    BonusDef(lambda v: f"VIT +{v}." if v > 0 else f"VIT {v}.", "vit"),
    "bInt":    BonusDef(lambda v: f"INT +{v}." if v > 0 else f"INT {v}.", "int_"),
    "bDex":    BonusDef(lambda v: f"DEX +{v}." if v > 0 else f"DEX {v}.", "dex"),
    "bLuk":    BonusDef(lambda v: f"LUK +{v}." if v > 0 else f"LUK {v}.", "luk"),
    "bAllStats": BonusDef(
        lambda v: f"All Stats +{v}." if v > 0 else f"All Stats {v}.",
        mode="multi", fields=["str_", "agi", "vit", "int_", "dex", "luk"],
    ),
    "bAgiVit": BonusDef(
        lambda v: f"AGI +{v}, VIT +{v}.",
        mode="multi", fields=["agi", "vit"],
    ),
    "bAgiDexStr": BonusDef(
        lambda v: f"AGI +{v}, DEX +{v}, STR +{v}.",
        mode="multi", fields=["agi", "dex", "str_"],
    ),

    # Flat combat
    "bBaseAtk":  BonusDef(lambda v: f"ATK +{v}." if v > 0 else f"ATK {v}.", "batk"),
    "bMatk":     BonusDef(lambda v: f"MATK +{v}." if v > 0 else f"MATK {v}."),  # display-only — MATK flat bonus not modelled in pipeline
    "bHit":      BonusDef(lambda v: f"HIT +{v}." if v > 0 else f"HIT {v}.", "hit"),
    "bFlee":     BonusDef(lambda v: f"FLEE +{v}." if v > 0 else f"FLEE {v}.", "flee"),
    "bFlee2":    BonusDef(lambda v: f"Perfect Dodge +{v}." if v > 0 else f"Perfect Dodge {v}.", "flee2"),
    "bCritical": BonusDef(lambda v: f"CRIT +{v}." if v > 0 else f"CRIT {v}.", "cri"),
    "bCritAtkRate": BonusDef(lambda v: f"Critical damage +{v}%." if v > 0 else f"Critical damage {v}%.", "crit_atk_rate"),
    "bLongAtkRate": BonusDef(lambda v: f"Long-range damage +{v}%." if v > 0 else f"Long-range damage {v}%.", "long_atk_rate"),
    "bAtkRate":     BonusDef(lambda v: f"Physical ATK +{v}%.", "atk_rate"),
    "bHolyStrikeChance": BonusDef(lambda v: f"+{v}% Holy Strike proc chance.", "holy_strike_bonus_chance"),

    # HP/SP
    "bMaxHP":     BonusDef(lambda v: f"MaxHP +{v}." if v > 0 else f"MaxHP {v}.", "maxhp"),
    "bMaxSP":     BonusDef(lambda v: f"MaxSP +{v}." if v > 0 else f"MaxSP {v}.", "maxsp"),
    "bMaxHPrate": BonusDef(lambda v: f"MaxHP +{v}%." if v > 0 else f"MaxHP {v}%.", "maxhp_rate"),
    "bMaxSPrate": BonusDef(lambda v: f"MaxSP +{v}%." if v > 0 else f"MaxSP {v}%.", "maxsp_rate"),

    # Defence
    "bDef":          BonusDef(lambda v: f"DEF +{v}." if v > 0 else f"DEF {v}.", "def_"),
    "bMdef":         BonusDef(lambda v: f"MDEF +{v}." if v > 0 else f"MDEF {v}.", "mdef_"),
    "bNearAtkDef":   BonusDef(lambda v: f"Near-range damage resistance +{v}%.", "near_atk_def_rate"),
    "bLongAtkDef":   BonusDef(lambda v: f"Long-range damage resistance +{v}%.", "long_atk_def_rate"),
    "bMagicDefRate": BonusDef(lambda v: f"Magic damage reduction +{v}%.", "magic_def_rate"),
    # pc.c:2770 — arity-1 form ignores race; applies to all targets (boss + non-boss).
    # Writes to both RC_NonBoss and RC_Boss so defense_fix picks it up for any target.
    "bIgnoreMdefRate": BonusDef(
        lambda v: f"Ignores {v}% of all targets' MDEF.",
        field="ignore_mdef_rate", mode="dict_keys", keys=["RC_NonBoss", "RC_Boss"],
    ),
    # pc.c — arity-1 form: param is a race constant string (e.g. RC_All); presence triggers
    # pdef=1 path in defense_fix.py for that race group.
    "bDefRatioAtkRace": BonusDef(
        lambda v: f"Bypasses DEF against {_race(str(v))}.",
        field="def_ratio_atk_race", mode="dict",
    ),

    # ASPD
    "bAspdRate": BonusDef(lambda v: f"ASPD +{v}%." if v > 0 else f"ASPD {v}%.", "aspd_percent"),
    "bAspd":     BonusDef(lambda v: f"ASPD +{v} (flat)." if v > 0 else f"ASPD {v} (flat).", "aspd_add"),

    # Skill timing
    "bCastrate":    BonusDef(lambda v: f"Casting time {'reduced' if v < 0 else 'increased'} by {abs(v)}%.", "castrate"),
    # bVarCastrate → same sd->castrate field in pre-renewal (pc.c:2639 #ifndef RENEWAL_CAST)
    "bVarCastrate": BonusDef(lambda v: f"Casting time {'reduced' if v < 0 else 'increased'} by {abs(v)}%.", "castrate"),
    "bDelayrate":   BonusDef(lambda v: f"After-cast delay {'reduced' if v < 0 else 'increased'} by {abs(v)}%.", "delayrate"),

    # MATK%  — status.c:1995-1997: matk *= matk_rate/100; matk_rate starts at 100, gear adds delta
    "bMatkRate": BonusDef(lambda v: f"MATK +{v}%." if v > 0 else f"MATK {v}%.", "matk_rate"),

    # Element overrides — script assigns element to weapon / armor.
    # bAtkEle / bDefEle params arrive as strings: "Ele_Fire", "Ele_Water", etc.
    # _ELE_STR_TO_INT maps them to the int 0-9 used throughout the pipeline.
    # Default path writes to script_atk_ele_rh; aggregator overrides to script_atk_ele_lh
    # for items equipped in the left_hand slot (pc.c:2588-2609 lr_flag routing).
    "bAtkEle": BonusDef(
        lambda v: f"Changes weapon element to {ELEMENT_NAMES.get(str(v), str(v))}.",
        field="script_atk_ele_rh", mode="assign", transform=_ELE_STR_TO_INT.get,
    ),
    "bDefEle": BonusDef(
        lambda v: f"Changes armor element to {ELEMENT_NAMES.get(str(v), str(v))}.",
        field="script_def_ele", mode="assign", transform=_ELE_STR_TO_INT.get,
    ),

    # Display-only miscellaneous
    "bIgnoreDefRace": BonusDef(lambda v: f"Ignores DEF of {RACE_NAMES.get(str(v), str(v))}."),
    "bShortWeaponDamageReturn": BonusDef(lambda v: f"Reflects {v}% melee physical damage back to attacker."),
    "bHPrecovRate":  BonusDef(lambda v: f"Natural HP recovery +{v}%." if v > 0 else f"Natural HP recovery {v}%."),
    "bSPrecovRate":  BonusDef(lambda v: f"Natural SP recovery +{v}%." if v > 0 else f"Natural SP recovery {v}%."),
    "bUseSPrate":    BonusDef(lambda v: f"SP consumption {'reduced' if v < 0 else 'increased'} by {abs(v)}%."),
    "bHealPower":    BonusDef(lambda v: f"Heal effectiveness +{v}%."),
    "bSpeedRate":    BonusDef(lambda v: f"Movement speed +{v}%." if v > 0 else f"Movement speed {v}%."),
    "bSplashRange":  BonusDef(lambda v: f"Attack splash range +{v} cells."),
    "bSPDrainValue": BonusDef(lambda v: f"Drains {v} SP per physical hit."),
    "bBreakArmorRate":  BonusDef(lambda v: f"{v/100:.0f}% chance to break the target's armor per hit."),
    "bBreakWeaponRate": BonusDef(lambda v: f"{v/100:.0f}% chance to break the target's weapon per hit."),
    "bUnbreakableWeapon": BonusDef(lambda _v: "Weapon cannot be broken."),
    "bUnbreakableHelm":   BonusDef(lambda _v: "Headgear cannot be broken."),
}

# ---------------------------------------------------------------------------
# Arity-2 table  (bonus2 bXxx, key, val)
# ---------------------------------------------------------------------------
#
# mode="dict"  →  bonuses.<field>[key] += val
# field=None   →  display-only

BONUS2: dict[str, BonusDef] = {
    # Routed to GearBonuses dicts
    "bAddRace":      BonusDef(lambda r, v: f"Increases physical damage against {_race(r)} by {v}%.", "add_race", "dict"),
    "bSubEle":       BonusDef(lambda e, v: f"Reduces damage from {_ele(e)}-element attacks by {v}%." if v > 0 else f"Increases damage from {_ele(e)}-element attacks by {abs(v)}%.", "sub_ele", "dict"),
    "bSubRace":      BonusDef(lambda r, v: f"Reduces damage from {_race(r)} by {v}%." if v > 0 else f"Increases damage from {_race(r)} by {abs(v)}%.", "sub_race", "dict"),
    "bAddSize":      BonusDef(lambda s, v: f"Increases physical damage against {_size(s)} monsters by {v}%.", "add_size", "dict"),
    "bAddEle":       BonusDef(lambda e, v: f"Increases physical damage against {_ele(e)}-element monsters by {v}%.", "add_ele", "dict"),
    "bAddAtkEle":    BonusDef(lambda e, v: f"Increases damage of {_ele(e)}-element attacks by {v}%.", "add_atk_ele", "dict"),
    "bIgnoreDefRate":  BonusDef(lambda r, v: f"Ignores {v}% of {_race(r)} DEF.", "ignore_def_rate", "dict"),
    "bIgnoreDefEle":   BonusDef(lambda e, v: f"Ignores {v}% of {_ele(e)}-element target's DEF.", "ignore_def_ele", "dict"),
    "bIgnoreMdefRate": BonusDef(lambda r, v: f"Ignores {v}% of {_race(r)} MDEF.", "ignore_mdef_rate", "dict"),
    "bSkillAtk":     BonusDef(lambda sk, v: f"Increases {sk} damage by {v}%.", "skill_atk", "dict"),
    "bSkillSpCost":  BonusDef(lambda sk, v: f"{'Increases' if v > 0 else 'Reduces'} {sk} SP cost by {abs(v)}.", field=None),
    "bCastrate":     BonusDef(lambda sk, v: f"{'Reduces' if v < 0 else 'Increases'} {sk} cast time by {abs(v)}%.", "skill_castrate", "dict"),
    "bDelayrate":    BonusDef(lambda sk, v: f"{'Reduces' if v < 0 else 'Increases'} {sk} after-cast delay by {abs(v)}%.", "skill_delayrate", "dict"),
    "bWeaponAtk":    BonusDef(lambda wtype, v: f"+{v}% ATK with {wtype}-type weapons.", "weapon_atk_rate", "dict"),
    # pdef=1 bonuses — presence in the dict triggers DEF-as-multiplier formula (battle.c:5686/5694)
    "bDefRatioAtkEle":  BonusDef(lambda e, v: f"Bypasses DEF against {_ele(e)}-element targets.", "def_ratio_atk_ele", "dict"),
    "bDefRatioAtkRace": BonusDef(lambda r, v: f"Bypasses DEF against {_race(r)}.", "def_ratio_atk_race", "dict"),

    "bMagicAddRace":    BonusDef(lambda r, v: f"Increases magic damage against {_race(r)} by {v}%.", "magic_add_race", "dict"),
    # Display-only
    "bCriticalAddRace": BonusDef(lambda r, v: f"CRIT rate +{v} against {_race(r)}."),
    "bExpAddRace":      BonusDef(lambda r, v: f"EXP gain +{v}% from {_race(r)}."),
    "bResEff":          BonusDef(lambda sc, v: f"Increases resistance to {_sc(sc)} by {v//100}%."),
    "bAddEff":          BonusDef(lambda sc, v: f"{v//100:.0f}% chance to inflict {_sc(sc)} on hit."),
    "bAddEffWhenHit":   BonusDef(lambda sc, v: f"{v//100:.0f}% chance to inflict {_sc(sc)} when hit."),
    "bAddEff2":         BonusDef(lambda sc, v: f"{v//100:.0f}% chance to self-inflict {_sc(sc)} on hit."),
    "bAddDamageClass":  BonusDef(lambda cls_, v: f"Increases damage against {_cls(cls_)} by {v}%."),
    "bSubSize":         BonusDef(lambda s, v: f"Reduces damage from {_size(s)} monsters by {v}%."),
    "bSPGainRace":      BonusDef(lambda r, v: f"Gains {v} SP per kill of {_race(r)}."),
    "bAddItemHealRate": BonusDef(lambda _id, v: f"Increases healing from items by {v}%."),
    "bWeaponComaRace":  BonusDef(lambda r, v: f"{v//100:.0f}% chance to inflict Coma on {_race(r)} per hit."),
    "bHPDrainRate":     BonusDef(lambda v1, v2: f"Drains {v2} HP per {v1} physical hits."),
    "bHPLossRate":      BonusDef(lambda v1, v2: f"Loses {v1} HP every {v2//1000:.0f} seconds."),
    "bAddMonsterDropItem": BonusDef(lambda _id, v: f"Monsters drop an item at {v/100:.2f}% rate."),
    "bSPDrainRate":     BonusDef(lambda v1, v2: f"Drains {v2} SP per {v1} physical hits."),
    "bAddSkillBlow":    BonusDef(lambda sk, v: f"{sk} knocks enemies back {v} cells."),
}

# ---------------------------------------------------------------------------
# Arity-3 table  (bonus3 bXxx, a, b, c)
# ---------------------------------------------------------------------------
#
# All display-only (field=None).

BONUS3: dict[str, BonusDef] = {
    "bAutoSpell":        BonusDef(lambda sk, lv, v: f"{v//10:.0f}% chance to auto-cast {sk} Lv.{lv} on physical attack."),
    "bAutoSpellWhenHit": BonusDef(lambda sk, lv, v: f"{v//10:.0f}% chance to auto-cast {sk} Lv.{lv} when hit."),
    "bAddEffOnSkill":    BonusDef(lambda sk, sc, v: f"{v//100:.0f}% chance to inflict {_sc(sc)} on {sk} hit."),
    "bAddEff":           BonusDef(lambda sc, v1, v2: f"[Conditional] {v1//100:.0f}% chance to inflict {_sc(sc)}."),
    "bSubEle":           BonusDef(lambda e, v, _flag: f"Reduces {_ele(e)}-element damage by {v}% (conditional)."),
    "bAddMonsterDropItem": BonusDef(lambda _id, v, _ty: f"Monsters drop an item at {v/100:.2f}% rate (type-conditional)."),
    "bAddClassDropItem":   BonusDef(lambda cls_, v, _ty: f"{_cls(cls_)} drop an item at {v/100:.2f}% rate."),
    "bAddEffWhenHit":    BonusDef(lambda sc, v1, _flag: f"[Conditional] {v1//100:.0f}% chance to inflict {_sc(sc)} when hit."),
    "bSPDrainRate":      BonusDef(lambda v1, v2, _flag: f"Drains {v2} SP per {v1} hits (conditional)."),
}

# bonus4 entries (4 params after the bonus type).
# Display-only (field=None); aggregator routes these via _build_autocast_spec() (gear_bonus_aggregator.py).
BONUS4: dict[str, BonusDef] = {
    "bAutoSpell":        BonusDef(lambda sk, lv, v, _flag: f"{v//10:.0f}% chance to auto-cast {sk} Lv.{lv} on physical attack."),
    "bAutoSpellWhenHit": BonusDef(lambda sk, lv, v, _flag: f"{v//10:.0f}% chance to auto-cast {sk} Lv.{lv} when hit."),
    "bAutoSpellOnSkill": BonusDef(lambda src, proc, lv, v: f"{v//10:.0f}% chance to auto-cast {proc} Lv.{lv} when using {src}."),
}
