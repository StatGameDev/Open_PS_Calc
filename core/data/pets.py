"""
Vanilla pet bonus data compiled from Hercules/db/pre-re/pet_db.conf (EquipScript loyal only).
petskillbonus timer entries excluded (no observable effect per user confirmation).

PET_BONUSES dict keys are GearBonuses field names — consumed by GearBonusAggregator (gear_bonus_aggregator.py).
ServerProfile.pet_bonuses overrides individual entries for PS-specific values.
"""

PET_BONUSES: dict[str, dict] = {
    "Alice":             {"mdef_": 1, "sub_race": {"RC_DemiPlayer": 1}},
    "Baby Desert Wolf":  {"int_": 1, "maxsp": 50},
    "Baphomet Jr.":      {"def_": 1, "mdef_": 1, "res_eff": {"Eff_Stun": -100}},
    "Bon Gun":           {"vit": 1, "res_eff": {"Eff_Stun": 100}},
    "ChonChon":          {"agi": 1, "flee": 2},
    "Christmas Goblin":  {"maxhp": 30, "sub_ele": {"Ele_Water": 1}},
    "Christmas Snow Rabbit": {},
    "Deviruchi":         {"atk_rate": 1, "matk_rate": 1, "maxhp_rate": -3, "maxsp_rate": -3},
    "Diabolic":          {},
    "Dokebi":            {"matk_rate": 1, "atk_rate": -1},
    "Deleter":           {},
    "Drops":             {"hit": 3, "batk": 3},
    "Dullahan":          {"crit_atk_rate": 5},
    "Evil Nymph":        {"maxsp": 30},
    "Fire Imp":          {"sub_ele": {"Ele_Fire": 2}, "add_ele": {"Ele_Fire": 2}},
    "Goblin (Flail)":    {},
    "Goblin (Hammer)":   {},
    "Goblin (Knife)":    {},
    "Goblin Leader":     {"add_race": {"RC_DemiPlayer": 3}},
    "Golem":             {"maxhp": 100, "flee": -5},
    "Green Maiden":      {"def_": 1, "sub_race": {"RC_DemiPlayer": 1}},
    "Hunter Fly":        {"flee": -5, "flee2": 2},
    "Incubus":           {"maxsp_rate": 3},
    "Isis":              {"atk_rate": 1, "matk_rate": -1},
    "Leaf Cat":          {"sub_race": {"RC_Brute": 3}},
    "Loli Ruri":         {"maxhp_rate": 3},
    "Lunatic":           {"cri": 2, "batk": 2},
    "Mao Guai":          {"maxsp": 10},
    "Marionette":        {},
    "Medusa":            {"vit": 1, "res_eff": {"Eff_Stone": 500}},
    "Miyabi Doll":       {"int_": 1, "castrate": -3},
    "Munak":             {"int_": 1, "def_": 1},
    "New Year Doll":     {},
    "Nightmare Terror":  {"res_eff": {"Eff_Sleep": 10000}},
    "Orc Warrior":       {"batk": 10, "def_": -3},
    "PecoPeco":          {"maxhp": 150, "maxsp": -10},
    "Petite":            {"def_": -2, "mdef_": -2, "aspd_percent": 1},
    "Picky":             {"str_": 1, "batk": 5},
    "Poison Spore":      {"str_": 1, "int_": 1},
    "Poporing":          {"luk": 2, "sub_ele": {"Ele_Poison": 10}},
    "Poring":            {"luk": 2, "cri": 1},
    "Rice Cake":         {"sub_ele": {"Ele_Neutral": 1}, "maxhp_rate": -1},
    "Rocker":            {"maxhp": 25},
    "Savage Babe":       {"vit": 1, "maxhp": 50},
    "Shinobi":           {"agi": 2},
    "Smokie":            {"agi": 1, "flee2": 1},
    "Sohee":             {"str_": 1, "dex": 1},
    "Spring Rabbit":     {},
    "Steel ChonChon":    {"flee": 6, "agi": -1},
    "Stone Shooter":     {"sub_ele": {"Ele_Fire": 3}},
    "Strange Cramp":     {},
    "Strange Hydra":     {},
    "Succubus":          {},
    "Wanderer":          {},
    "Whisper":           {"flee": 7, "def_": -3},
    "White Lady":        {},
    "Yoyo":              {"cri": 3, "luk": -1},
    "Zealotus":          {"add_race": {"RC_DemiPlayer": 2}, "magic_add_race": {"RC_DemiPlayer": 2}},
}

# Flat stat key → short display label
_FLAT_LABELS: dict[str, str] = {
    "str_":          "STR",
    "agi":           "AGI",
    "vit":           "VIT",
    "int_":          "INT",
    "dex":           "DEX",
    "luk":           "LUK",
    "batk":          "ATK",
    "hit":           "HIT",
    "flee":          "FLEE",
    "flee2":         "PerfDodge",
    "cri":           "CRI",
    "def_":          "DEF",
    "mdef_":         "MDEF",
    "maxhp":         "MaxHP",
    "maxsp":         "MaxSP",
    "atk_rate":      "ATK%",
    "matk_rate":     "MATK%",
    "aspd_percent":  "ASPD%",
    "crit_atk_rate": "CritDmg%",
    "maxhp_rate":    "MaxHP%",
    "maxsp_rate":    "MaxSP%",
    "castrate":      "Cast%",
}

# Ele_* key → display element name
_ELE_NAMES: dict[str, str] = {
    "Ele_Neutral": "Neutral", "Ele_Water": "Water", "Ele_Earth": "Earth",
    "Ele_Fire": "Fire", "Ele_Wind": "Wind", "Ele_Poison": "Poison",
    "Ele_Holy": "Holy", "Ele_Dark": "Dark", "Ele_Ghost": "Ghost",
    "Ele_Undead": "Undead",
}

# RC_* key → display race name
_RACE_NAMES: dict[str, str] = {
    "RC_DemiPlayer": "DemiPlayer", "RC_Brute": "Brute", "RC_Plant": "Plant",
    "RC_Insect": "Insect", "RC_Fish": "Fish", "RC_Demon": "Demon",
    "RC_DemiHuman": "DemiHuman", "RC_Angel": "Angel", "RC_Dragon": "Dragon",
    "RC_Undead": "Undead",
}


def pet_bonus_summary(bonus: dict) -> str:
    """Return a compact inline summary string for dropdown labels, e.g. 'AGI+1  FLEE+2'."""
    parts: list[str] = []

    for key, label in _FLAT_LABELS.items():
        v = bonus.get(key, 0)
        if v:
            parts.append(f"{label}{'+' if v > 0 else ''}{v}")

    for ele_key, v in bonus.get("sub_ele", {}).items():
        name = _ELE_NAMES.get(ele_key, ele_key)
        parts.append(f"{name}Res{'+' if v > 0 else ''}{v}%")

    for ele_key, v in bonus.get("add_ele", {}).items():
        name = _ELE_NAMES.get(ele_key, ele_key)
        parts.append(f"{name}Atk{'+' if v > 0 else ''}{v}%")

    for race_key, v in bonus.get("sub_race", {}).items():
        name = _RACE_NAMES.get(race_key, race_key)
        parts.append(f"vs{name}{'+' if v > 0 else ''}{v}%")

    for race_key, v in bonus.get("add_race", {}).items():
        name = _RACE_NAMES.get(race_key, race_key)
        parts.append(f"vs{name}{'+' if v > 0 else ''}{v}%")

    for race_key, v in bonus.get("magic_add_race", {}).items():
        name = _RACE_NAMES.get(race_key, race_key)
        parts.append(f"Magicvs{name}{'+' if v > 0 else ''}{v}%")

    # res_eff skipped (too verbose)

    return "  ".join(parts)
