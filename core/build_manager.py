"""
BuildManager — save/load of user build files and resolution of equipped item IDs to model objects.

Not a pipeline calculator. Owns:
  save_build / load_build: JSON serialisation of PlayerBuild (canonical save schema).
  resolve_weapon: item ID → Weapon via DataLoader item_db.
  player_build_to_target: converts a player's computed state to a Target for incoming damage pipelines.
  effective_is_ranged: derives the effective ranged flag from build override or weapon type.

DataLoader owns static databases (item_db, skill tables, etc.).
BuildManager owns user-saved build files and item resolution.
"""
import json
from pathlib import Path
from typing import Dict, List, Optional

from core.build_applicator import resolve_armor_element
from core.models.build import PlayerBuild
from core.models.gear_bonuses import GearBonuses
from core.models.status import StatusData
from core.models.target import Target
from core.models.weapon import Weapon, RANGED_WEAPON_TYPES
from core.server_profiles import get_profile

DEFAULT_SAVES_DIR = "saves"



def effective_is_ranged(build: PlayerBuild, weapon: Weapon) -> bool:
    """Return the effective is_ranged flag for a build+weapon pair.

    Honour build.is_ranged_override when explicitly set (True/False).
    Fall back to weapon_type membership in RANGED_WEAPON_TYPES when None.
    """
    if build.is_ranged_override is not None:
        return build.is_ranged_override
    return weapon.weapon_type in RANGED_WEAPON_TYPES


class BuildManager:
    """
    Responsible for save/load of user build files and resolving equipped item IDs
    to model objects via the item database.

    DataLoader owns static databases (item_db, skill tables, etc.).
    BuildManager owns user-saved build files and item resolution.

    Resolution follows C1 pattern: load_build returns a PlayerBuild with item IDs
    embedded in build.equipped. Callers obtain the resolved Weapon (or future
    armour/accessory objects) by calling resolve_weapon separately. This keeps
    PlayerBuild a pure data container and the resolution pattern extensible to
    all future equip slot types.
    """

    @staticmethod
    def save_build(build: PlayerBuild, path: str) -> None:
        """Serialise a PlayerBuild to the canonical save schema JSON."""
        data = {
            "name": build.name,
            "job_id": build.job_id,
            "base_level": build.base_level,
            "job_level": build.job_level,
            "base_stats": {
                "str": build.base_str,
                "agi": build.base_agi,
                "vit": build.base_vit,
                "int": build.base_int,
                "dex": build.base_dex,
                "luk": build.base_luk,
            },
            "bonus_stats": {
                # Flat stat bonuses from gear/cards/foods/buffs — manually entered.
                "str": build.bonus_str,
                "agi": build.bonus_agi,
                "vit": build.bonus_vit,
                "int": build.bonus_int,
                "dex": build.bonus_dex,
                "luk": build.bonus_luk,
                "hit": build.bonus_hit,
                "flee": build.bonus_flee,
                "cri": build.bonus_cri,
                "batk": build.bonus_batk,
                "def": build.equip_def,        # hard DEF total from equipment
                "def2": build.bonus_def2,       # extra soft DEF from items/foods/SCs
                "aspd_percent": build.bonus_aspd_percent,
            },
            "target_mob_id": build.target_mob_id,
            "equipped": build.equipped,
            "refine": build.refine_levels,
            "weapon_element": build.weapon_element,
            "active_buffs": build.active_status_levels,
            "mastery_levels": build.mastery_levels,
            "flags": {
                "is_ranged_override": build.is_ranged_override,  # null = derive from weapon_type
                "is_riding_peco": build.is_riding_peco,
                "no_sizefix": build.no_sizefix,
                "armor_element": build.armor_element,
            },
            "server": build.server,
            "manual_adj": dict(build.manual_adj_bonuses),
            "support_buffs": dict(build.support_buffs),
            "player_active_scs": dict(build.player_active_scs),
            "song_state": dict(build.song_state),
            "consumable_buffs": dict(build.consumable_buffs),
            "clan": build.clan,
            "selected_pet": build.selected_pet,
        }

        # cached_display — read by PlayerTargetBrowserDialog to show build stats
        # without a full load. Computed at save time from the raw (pre-gear-bonus) build.
        from core.data_loader import loader  # local import — avoids circular dependency
        job_entry = loader.get_job_entry(build.job_id)
        job_name = job_entry["name"] if job_entry else ""
        effective_vit = build.base_vit + build.bonus_vit
        hp_base = loader.get_hp_at_level(build.job_id, build.base_level)
        # status.c:1361 status_get_base_maxhp — val += val * vit / 100
        data["cached_display"] = {
            "job_name": job_name,
            "hp": hp_base * (100 + effective_vit) // 100 + build.bonus_maxhp,
            "def_": build.equip_def,
            "mdef": build.equip_mdef,
        }

        out_path = Path(path)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)

    @staticmethod
    def load_build(path: str) -> PlayerBuild:
        """
        Parse a save-schema JSON file into a PlayerBuild.

        Item IDs in build.equipped are populated as-is. The actual Weapon
        object is not constructed here — call resolve_weapon when the weapon
        is needed (pipeline, GUI display, etc.).
        """
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)

        bs = data.get("base_stats", {})
        bn = data.get("bonus_stats", {})
        flags = data.get("flags", {})
        equipped: Dict[str, Optional[int]] = data.get("equipped", {})
        build_name = data.get("name", path)

        # SC_ADRENALINE moved to support_buffs in schema v2 — migrate old saves.
        active_buffs: dict = data.get("active_buffs", {})
        support_buffs: dict = data.get("support_buffs", {})
        if "SC_ADRENALINE" in active_buffs and "SC_ADRENALINE" not in support_buffs:
            support_buffs = dict(support_buffs)
            support_buffs["SC_ADRENALINE"] = active_buffs.pop("SC_ADRENALINE")

        # SC_ASSNCROS moved to song_state in schema v3 — migrate old saves.
        song_state: dict = data.get("song_state", {})
        if "SC_ASSNCROS" in active_buffs and "SC_ASSNCROS" not in song_state:
            song_state = dict(song_state)
            song_state["SC_ASSNCROS"] = active_buffs.pop("SC_ASSNCROS")

        return PlayerBuild(
            name=data.get("name", ""),
            job_id=data.get("job_id", 0),
            base_level=data.get("base_level", 1),
            job_level=data.get("job_level", 1),
            base_str=bs.get("str", 1),
            base_agi=bs.get("agi", 1),
            base_vit=bs.get("vit", 1),
            base_int=bs.get("int", 1),
            base_dex=bs.get("dex", 1),
            base_luk=bs.get("luk", 1),
            bonus_str=bn.get("str", 0),
            bonus_agi=bn.get("agi", 0),
            bonus_vit=bn.get("vit", 0),
            bonus_int=bn.get("int", 0),
            bonus_dex=bn.get("dex", 0),
            bonus_luk=bn.get("luk", 0),
            bonus_hit=bn.get("hit", 0),
            bonus_flee=bn.get("flee", 0),
            bonus_cri=bn.get("cri", 0),
            bonus_batk=bn.get("batk", 0),
            equip_def=bn.get("def", 0),
            bonus_def2=bn.get("def2", 0),
            bonus_aspd_percent=bn.get("aspd_percent", 0),
            target_mob_id=data.get("target_mob_id"),
            equipped=equipped,
            refine_levels=data.get("refine", {}),
            weapon_element=data.get("weapon_element", None),
            # Old files used "weapon_elements": {"right_hand": N} — silently falls back to None.
            active_status_levels=active_buffs,
            mastery_levels=data.get("mastery_levels", {}),
            is_ranged_override=flags.get("is_ranged_override", None),
            is_riding_peco=flags.get("is_riding_peco", False),
            no_sizefix=flags.get("no_sizefix", False),
            armor_element=flags.get("armor_element", 0),
            server=data.get("server", "payon_stories"),
            manual_adj_bonuses=data.get("manual_adj", {}),
            support_buffs=support_buffs,
            player_active_scs=data.get("player_active_scs", {}),
            song_state=song_state,
            consumable_buffs=data.get("consumable_buffs", {}),
            clan=data.get("clan", ""),
            selected_pet=data.get("selected_pet", ""),
        )

    @staticmethod
    def list_builds(directory: str = DEFAULT_SAVES_DIR) -> List[str]:
        """Return stem names of all build files found in directory."""
        return [p.stem for p in Path(directory).glob("*.json")]

    @staticmethod
    def player_build_to_target(
        build: PlayerBuild,
        status: StatusData,
        gear_bonuses: GearBonuses,
        weapon: Optional[Weapon] = None,
    ) -> Target:
        """Convert a player's computed state into a Target for incoming damage pipelines.

        Used when the player is the defender (mob → player, or PvP incoming).
        All players are DemiHuman / Medium / element_level 1 in pre-renewal.

        sub_size is left empty — GearBonuses.add_size is offensive (attacker bonus),
        not defensive resistance.
        """
        # Propagate force-hit ailments and def-zeroing flags so the incoming
        # pipeline sees them, mirroring what apply_to_target() does for mob targets.
        player_scs = getattr(build, "player_active_scs", {})
        target_scs: dict = {}
        for _sc in ("SC_STUN", "SC_FREEZE", "SC_STONE", "SC_SLEEP", "SC_ETERNALCHAOS"):
            if player_scs.get(_sc):
                target_scs[_sc] = int(player_scs[_sc])

        # Resolve effective armor element: bDefEle scripts > explicit override > Neutral.
        # Freeze/Stone then override the effective element for damage calc only.
        base_armor_ele = resolve_armor_element(build.armor_element, gear_bonuses)
        element = base_armor_ele
        if player_scs.get("SC_FREEZE"):
            element = 1  # Ele_Water
        elif player_scs.get("SC_STONE"):
            element = 2  # Ele_Earth

        # Accumulate passive elemental resistances into sub_ele.
        # These apply to all incoming damage types (physical + magic) via CardFix.sub_ele reads.
        sub_ele = dict(gear_bonuses.sub_ele)
        # gear_bonuses.effective_mastery is populated by GearBonusAggregator (gear_bonus_aggregator.py)
        # BS_SKINTEMPER: Skin Tempering — vanilla Neutral 1*lv%, Fire 4*lv%
        # PS override: Neutral 4*lv%, Fire 6*lv%
        # Source: status.c:2189-2192; PS: PayonStoriesData/ps_skill_db.json id=109
        skintemper_lv = gear_bonuses.effective_mastery.get("BS_SKINTEMPER", 0)
        if skintemper_lv:
            if build.server == "payon_stories":
                sub_ele["Ele_Neutral"] = sub_ele.get("Ele_Neutral", 0) + 4 * skintemper_lv
                sub_ele["Ele_Fire"]    = sub_ele.get("Ele_Fire", 0)    + 6 * skintemper_lv
            else:
                sub_ele["Ele_Neutral"] = sub_ele.get("Ele_Neutral", 0) + skintemper_lv
                sub_ele["Ele_Fire"]    = sub_ele.get("Ele_Fire", 0)    + 4 * skintemper_lv
        # WZ_ESTIMATION: Sense — PS only, Fire/Water/Wind/Earth 2% (max_level=1, toggle)
        # Vanilla WZ_ESTIMATION gives no resistance (info skill only).
        # Source: PayonStoriesData/ps_skill_db.json id=93
        if build.server == "payon_stories" and gear_bonuses.effective_mastery.get("WZ_ESTIMATION", 0):
            for _k in ("Ele_Fire", "Ele_Water", "Ele_Wind", "Ele_Earth"):
                sub_ele[_k] = sub_ele.get(_k, 0) + 2

        # Weapon-gated passive elemental resists at max level (profile-driven).
        # Source: ps_skill_db.json per-skill descriptions.
        _profile = get_profile(build.server)
        weapon_type = weapon.weapon_type if weapon is not None else None
        for skill_key, rspec in _profile.passive_resists.items():
            lv = gear_bonuses.effective_mastery.get(skill_key, 0)
            if lv < rspec.get("max_level", 10):
                continue
            wt_req = rspec.get("weapon_types")
            if wt_req and weapon_type not in wt_req:
                continue
            for ele_key, pct in rspec.get("sub_ele_at_max_lv", {}).items():
                sub_ele[ele_key] = sub_ele.get(ele_key, 0) + pct

        return Target(
            def_=status.def_,
            vit=status.vit,
            level=build.base_level,
            is_pc=True,
            size="Medium",
            race="DemiHuman",
            element=element,
            armor_element=base_armor_ele,
            element_level=1,
            luk=status.luk,
            agi=status.agi,
            flee=status.flee,
            mdef_=status.mdef,
            int_=status.int_,
            sub_race=dict(gear_bonuses.sub_race),
            sub_ele=sub_ele,
            sub_size={},   # sub_size not modelled — GearBonuses carries no size-reduction card fields
            near_attack_def_rate=gear_bonuses.near_atk_def_rate,
            long_attack_def_rate=gear_bonuses.long_atk_def_rate,
            magic_def_rate=gear_bonuses.magic_def_rate,
            def_percent=status.def_percent,
            target_active_scs=target_scs,
        )

    @staticmethod
    def resolve_weapon(
        item_id: Optional[int],
        refine: int = 0,
        element_override: Optional[int] = None,
        is_forged: bool = False,
        forge_sc_count: int = 0,
        forge_ranked: bool = False,
        forge_element: int = 0,
        script_atk_ele_rh: Optional[int] = None,
    ) -> Weapon:
        """
        Resolve an item ID to a Weapon via item_db.

        Returns Unarmed defaults (ATK 0, level 1, neutral, no refine) if:
        - item_id is None (slot unequipped)
        - the item ID is not found in item_db

        Element priority:
          1. element_override (manual "Weapon Element" override — always wins)
          2. script_atk_ele_rh (bAtkEle from slot-appropriate item scripts)
             Pass gb.script_atk_ele_rh for RH weapon, gb.script_atk_ele_lh for LH weapon.
          3. forge_element when is_forged=True (elemental stone from forging)
          4. item_db element (base weapon, usually 0 for forgeable weapons)
        """
        from core.data_loader import loader  # local import — avoids circular dependency

        if item_id is None:
            return Weapon()  # Unarmed: atk=0, level=1, element=0, weapon_type="Unarmed"

        item = loader.get_item(item_id)
        if item is None:
            print(
                f'WARNING: Item ID {item_id} not found in item_db. '
                f'Using Unarmed defaults.'
            )
            return Weapon()

        if element_override is not None:
            element = element_override
        elif script_atk_ele_rh is not None:
            element = script_atk_ele_rh  # bAtkEle from slot-appropriate item scripts
        elif is_forged:
            element = forge_element      # elemental stone from forging
        else:
            element = item.get("element", 0)

        return Weapon(
            atk=item.get("atk", 0),
            refine=refine,
            level=item.get("level", 1),
            element=element,
            weapon_type=item.get("weapon_type", "Unarmed"),
            hand="right",
            aegis_name=item.get("aegis_name", ""),
            refineable=item.get("refineable", True),
            forge_sc_count=forge_sc_count if is_forged else 0,
            forge_ranked=forge_ranked if is_forged else False,
        )
