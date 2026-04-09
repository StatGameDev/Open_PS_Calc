"""
weapon — Weapon dataclass and RANGED_WEAPON_TYPES constant.

Weapon mirrors the weapon_data struct (sd->right_weapon / sd->left_weapon) in
Hercules status.c / battle.c. Populated by resolve_weapon() in build_manager.py
from PlayerBuild equipment slots; consumed by the BF_WEAPON damage pipeline.
"""
from dataclasses import dataclass

# Weapon types whose BATK uses DEX as the primary stat (long-range attack flag).
# Matches the W_* cases in battle_calc_base_damage2 / battle_calc_weapon_attack.
# Source: battle.c lines 3262-3272, 5282-5287.
RANGED_WEAPON_TYPES: frozenset = frozenset({
    "Bow", "MusicalInstrument", "Whip",
    "Revolver", "Rifle", "Gatling", "Shotgun", "Grenade",
})


@dataclass
class Weapon:
    """Exact mirror of struct weapon_data used in status.c / battle.c for BF_WEAPON attacks."""
    atk: int = 0
    refine: int = 0
    level: int = 1
    element: int = 0        # 0=Neutral, 1=Water, ...
    weapon_type: str = "Unarmed"   # exact index into size_fix.json table (and sd->weapontype1)
    hand: str = "right"            # "right" or "left" – selects atkmods[t_size] in battle.c sizefix
    aegis_name: str = ""           # AegisName from item_db — display only, no calculation effect
    refineable: bool = True        # Refine: false in item_db → suppress overrefine bonus in base_damage.py
    # Forge bonus fields. Set by resolve_weapon (build_manager.py) from PlayerBuild forge state.
    # ForgeBonus modifier computes star = f(forge_sc_count, forge_ranked) and adds flat per hit.
    forge_sc_count: int = 0        # star crumb count (0–3); 0 = no forge bonus
    forge_ranked: bool = False     # forger was ranked blacksmith (+10 star)