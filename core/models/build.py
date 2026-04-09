"""
PlayerBuild — all player-controlled inputs to the damage calculator.

Holds base stats, gear slots, refine levels, skill levels, buff states, and
per-cast parameters. Populated by the GUI; consumed by resolve_player_state()
(player_state_builder.py) to produce the computed GearBonuses / StatusData.

Not saved as-is — save_build() serialises the pre-bonus base values only.
Bonus fields (bonus_str, bonus_batk, etc.) are recomputed on every load.
"""
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class PlayerBuild:
    """Player character state as entered in the GUI.

    Base stats are the raw points allocated by the player. Bonus fields are
    computed from gear scripts and consumables by apply_gear_bonuses()
    (build_applicator.py); they are not set by the GUI directly.
    """
    base_level: int = 1
    job_level: int = 1
    job_id: int = 0

    base_str: int = 1
    base_agi: int = 1
    base_vit: int = 1
    base_int: int = 1
    base_dex: int = 1
    base_luk: int = 1

    bonus_str: int = 0
    bonus_agi: int = 0
    bonus_vit: int = 0
    bonus_int: int = 0
    bonus_dex: int = 0
    bonus_luk: int = 0

    equip_def: int = 0          # Hard DEF
    equip_mdef: int = 0         # Hard MDEF (from bMdef scripts)
    bonus_def2: int = 0         # Extra soft DEF from items / foods / SCs

    bonus_batk: int = 0
    bonus_cri: int = 0
    bonus_hit: int = 0
    bonus_flee: int = 0
    bonus_aspd_percent: int = 0
    bonus_aspd_add: int = 0      # flat amotion reduction from bAspd
    bonus_maxhp: int = 0         # flat MaxHP addend from items/cards
    bonus_maxsp: int = 0         # flat MaxSP addend from items/cards
    bonus_crit_atk_rate: int = 0  # bCritAtkRate — % bonus to crit damage
    bonus_matk_rate: int = 0      # bMatkRate — % rate bonus to MATK
    bonus_maxhp_rate: int = 0     # bMaxHPrate — % rate bonus to MaxHP

    # None = derive from equipped weapon's weapon_type at calc time.
    # Set True/False explicitly to override (e.g. musical instrument played melee).
    is_ranged_override: Optional[bool] = None

    no_sizefix: bool = False    # sd->special_state.no_sizefix – exact bypass for size fix

    # Conditional mastery support – exact flags needed for KN_SPEARMASTERY etc.
    # (pre-renewal only, mirrors pc_isridingpeco / pc_isridingdragon)
    is_riding_peco: bool = False

    # Full active status bonus support – all SC_* levels from the investigation
    active_status_levels: Dict[str, int] = field(default_factory=dict)
    # Key = "SC_AURABLADE", "SC_MAXIMIZEPOWER", etc.
    # Value = skill/level that set the status

    mastery_levels: Dict[str, int] = field(default_factory=dict)
    # Key = mastery skill name (e.g. "SM_SWORD", "KN_SPEARMASTERY")
    # Value = skill level

    server: str = "payon_stories"  # "standard" or "payon_stories"

    # Save/load identity and equipment slots
    name: str = ""
    equipped: Dict[str, Optional[int]] = field(default_factory=dict)
    # Key = slot name (e.g. "right_hand", "ammo"), value = item ID or None
    refine_levels: Dict[str, int] = field(default_factory=dict)
    # Key = slot name, value = refine count for that slot
    weapon_element: Optional[int] = None
    # Element override for right_hand weapon (int 0-9). None = use item_db element.
    # Used for elemental imbues until a proper SC/item imbue system is implemented.
    armor_element: int = 0
    # Element of worn armor (int 0-9). Default 0 = Neutral (no armor element card).
    # Used for incoming damage pipeline: attr_fix(attacker.element, player.armor_element).
    target_mob_id: Optional[int] = None
    # When set, pipeline resolves target via loader.get_monster(target_mob_id).
    # None = caller supplies Target manually (used by GUI inputs once built).

    # Manual Stat Adjustments (pure numeric escape hatch — no source attribution).
    # Keys: "str","agi","vit","int","dex","luk","batk","hit","flee","cri","def","mdef","aspd_pct","maxhp","maxsp","crit_dmg_pct"
    manual_adj_bonuses: Dict[str, int] = field(default_factory=dict)

    # Forged weapon properties — right_hand.
    # is_forged=True hides card slots and activates forge_element in resolve_weapon.
    # forge_element: element from forge process (int 0-9); overridden by weapon_element if set.
    is_forged: bool = False
    forge_sc_count: int = 0    # star crumb count (0–3)
    forge_ranked: bool = False  # forger was ranked blacksmith (+10 star)
    forge_element: int = 0     # element from elemental stone (0=Neutral/none)

    # Forged weapon properties — left_hand (dual-wield only).
    # Same semantics as above; no weapon_element override for LH (uses item_db / forge_element).
    lh_is_forged: bool = False
    lh_forge_sc_count: int = 0
    lh_forge_ranked: bool = False
    lh_forge_element: int = 0

    # Party/support buffs and debuffs cast on the player's team.
    # Keys: SC_* strings; values: level or bool depending on the buff.
    # e.g. {"SC_ADRENALINE": 0, "SC_BLESSING": 0, "SC_IMPOSITIOMANUS": 0, ...}
    support_buffs: Dict[str, object] = field(default_factory=dict)

    # Debuffs the enemy has applied TO the player (affects incoming damage calcs).
    # Keys: SC_* strings; values: level or bool.
    # e.g. {"SC_ETERNALCHAOS": False, "SC_CURSE": False, ...}
    player_active_scs: Dict[str, object] = field(default_factory=dict)

    # Persisted target debuffs — the player's intended state for the enemy target.
    # Written by TargetStateSection.collect_into(); read back by load_build().
    # Pipeline never reads this dict — it reads target.target_active_scs after apply_to_target().
    target_debuffs: Dict[str, object] = field(default_factory=dict)
    # Keys: SC_ETERNALCHAOS, SC_PROVOKE (level), SC_DECREASEAGI (level),
    #       SC_QUAGMIRE (level), SC_MINDBREAKER (level), PR_LEXAETERNA

    # Bard/Dancer song state — per-song levels, caster stats, and lesson level.
    # Each song/dance: "{SC_KEY}" (level), "{SC_KEY}_{stat}" (caster stat), "{SC_KEY}_lesson" (lesson lv).
    # Ensemble keys: "SC_DRUMBATTLE", "SC_NIBELUNGEN", "SC_SIEGFRIED" (level only).
    song_state: Dict[str, object] = field(default_factory=dict)

    # Skill runtime parameters — combat-context values that vary per cast.
    # Not saved to disk; reset to UI defaults on build load.
    # Keys: "KN_CHARGEATK_dist" (int, cell distance 1/4/7 representing tiers),
    #       "MC_CARTREVOLUTION_pct" (int 0-100, cart weight %),
    #       "MO_EXTREMITYFIST_sp" (int, current SP at cast time),
    #       "TK_JUMPKICK_combo" (bool, SC_COMBOATTACK active),
    #       "TK_JUMPKICK_running" (bool, SC_STRUP / TK_RUN active).
    skill_params: Dict[str, Any] = field(default_factory=dict)

    # Consumable buffs — stat foods, ASPD potions, ATK/MATK items, combat stat items.
    # Keys defined in docs/consumables_design.md "Storage Keys" section. Same typing as support_buffs.
    # food_str/agi/vit/int/dex/luk (int 0-21), food_all (0/3/6/10), grilled_corn (bool),
    # aspd_potion (0-3), hit_food (int), flee_food (int), cri_food (bool),
    # atk_item (int), matk_item (int), matk_food (bool).
    consumable_buffs: Dict[str, object] = field(default_factory=dict)

    # Flat MATK addend from SC_PLUSMAGICPOWER / SC_MATKFOOD consumables.
    # Accumulated in apply_gear_bonuses(); applied in StatusCalculator after rate scaling.
    # source: status.c:4635-4638.
    bonus_matk_flat: int = 0

    # PS Clan membership — stat bonus applied via apply_gear_bonuses().
    # "" = no clan. Values: "sword_clan", "arch_wand_clan", "golden_mace_clan",
    # "crossbow_clan", "artisan_clan", "vile_wind_clan".
    clan: str = ""

    # Pet selection — "" = no pet. Resolved to bonus dict via apply_pet_bonuses() (build_applicator.py).
    selected_pet: str = ""
    bonus_flee2: int = 0        # accumulated from gb.flee2
    bonus_maxsp_rate: int = 0   # accumulated from gb.maxsp_rate

    # Current HP/SP at cast time — None means "use max_hp/max_sp" (full health assumption).
    # Used in ItemScriptContext to evaluate item script conditionals on Hp/MaxHp/Sp/MaxSp.
    current_hp: int | None = None
    current_sp: int | None = None