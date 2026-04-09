"""
data_loader — Singleton loader for all pre-renewal game data.

Loads item/mob/skill databases from core/data/pre-re/ (Hercules DB structure).
PS server data is layered on top via two JSON files in PayonStoriesData/:
  ps_item_overrides.json — changes to vanilla items (stats, scripts, flags)
  ps_item_manual.json    — PS-custom items absent from vanilla DB

The module-level `loader` instance is the single access point. All modules that
need DB access import `loader` directly (e.g. `from core.data_loader import loader`).
"""
from pathlib import Path
from typing import Dict, Any, Optional, ClassVar
import json
from functools import lru_cache

from core.models.build import PlayerBuild
from core.models.target import Target
from core.models.weapon import Weapon


class DataLoader:
    """
    SINGLE SOURCE OF TRUTH for all pre-renewal data.
    Loaded exclusively from core/data/pre-re (exact mirror of Hercules DB structure).
    No simplifications. No invented values. Only files confirmed in the repo.
    """

    # Class-level declarations so type checker knows the attributes exist
    _instance: ClassVar[Optional["DataLoader"]] = None
    base_path: Path
    _cache: Dict[str, Any]

    def __new__(cls, base_path: str = "core/data/pre-re"):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.base_path = Path(base_path)
            cls._instance._cache = {}          # no annotation here
            cls._instance._skill_name_to_id = None  # lazy reverse lookup; populated by get_skill_id_by_name()
            cls._instance._profile = None      # set via set_profile(); None → vanilla-only
        return cls._instance

    def set_profile(self, profile) -> None:
        """Set the active server profile. Controls whether PS data layers are applied.
        Call whenever the user changes server (MainWindow server_changed signal)."""
        self._profile = profile

    @property
    def _use_ps_data(self) -> bool:
        return self._profile is not None and self._profile.use_ps_data

    @lru_cache(maxsize=None)
    def _load_json(self, relative_path: str) -> Dict:
        """Internal cached loader – fails fast if file missing"""
        full_path = self.base_path / relative_path
        if not full_path.exists():
            raise FileNotFoundError(f"Missing required data file: {full_path}")
        with open(full_path, "r", encoding="utf-8") as f:
            return json.load(f)

    # =============================================================
    # Item database
    # =============================================================
    # ------------------------------------------------------------------
    # PS item layer loaders (cached on instance, not lru_cache —
    # PayonStoriesData/ is outside base_path and changes independently)
    # ------------------------------------------------------------------

    def _load_ps_item_overrides(self) -> dict[str, dict]:
        if hasattr(self, "_ps_item_overrides_cache"):
            return self._ps_item_overrides_cache  # type: ignore[return-value]
        path = Path(__file__).parent.parent / "PayonStoriesData" / "ps_item_overrides.json"
        try:
            self._ps_item_overrides_cache: dict[str, dict] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (json.JSONDecodeError, OSError):
            self._ps_item_overrides_cache = {}
        return self._ps_item_overrides_cache

    def _load_ps_item_manual(self) -> dict[str, dict]:
        if hasattr(self, "_ps_item_manual_cache"):
            return self._ps_item_manual_cache  # type: ignore[return-value]
        path = Path(__file__).parent.parent / "PayonStoriesData" / "ps_item_manual.json"
        try:
            self._ps_item_manual_cache: dict[str, dict] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
        except (json.JSONDecodeError, OSError):
            self._ps_item_manual_cache = {}
        return self._ps_item_manual_cache

    @staticmethod
    def _normalize_item(item: Optional[Dict]) -> Optional[Dict]:
        """Enforce item invariants that must hold regardless of DB value.
        Mid/lower headgear are never refineable in pre-renewal.
        Returns a new dict only when a field is overridden — safe to call on
        cached objects since it never mutates in-place."""
        if item is None:
            return None
        loc = item.get("loc", [])
        if ("EQP_HEAD_MID" in loc or "EQP_HEAD_LOW" in loc) and item.get("refineable", True):
            return {**item, "refineable": False}
        return item

    def _apply_ps_item_layers(self, str_id: str, base: Optional[Dict]) -> Optional[Dict]:
        """Merge PS overrides then manual on top of base.
        Layer order (last wins): vanilla base → ps_item_overrides → ps_item_manual.
        Internal keys (_ps_custom, _renewal_base, description) are stripped from
        the item dict; description is handled separately via get_item_description().
        weapon_level in overrides maps to the vanilla 'level' field."""
        _STRIP = {"_ps_custom", "_renewal_base", "description"}
        _REMAP = {"weapon_level": "level"}

        if not self._use_ps_data:
            return base

        override = self._load_ps_item_overrides().get(str_id, {})
        manual   = self._load_ps_item_manual().get(str_id, {})

        if not override and not manual:
            return base

        result = dict(base) if base else {}
        if not result:
            result["id"] = int(str_id)

        for src in (override, manual):
            for k, v in src.items():
                if k in _STRIP:
                    continue
                result[_REMAP.get(k, k)] = v

        return result if result else None

    # ------------------------------------------------------------------
    # Item database
    # ------------------------------------------------------------------

    def get_convenience_cards(self) -> list:
        """Return the list of pinned convenience cards from core/data/convenience_cards.json."""
        if not hasattr(self, "_convenience_cards_cache"):
            path = Path(__file__).parent / "data" / "convenience_cards.json"
            self._convenience_cards_cache = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        return self._convenience_cards_cache

    def get_item(self, item_id: int) -> Optional[Dict]:
        """Look up an item by numeric ID.
        Merge order: vanilla item_db.json → ps_item_overrides.json → ps_item_manual.json.
        PS-custom items (absent from vanilla) are returned if manual provides enough data."""
        if item_id < 0:
            return next((c for c in self.get_convenience_cards() if c["id"] == item_id), None)
        str_id = str(item_id)
        try:
            data = self._load_json("db/item_db.json")
            base = data.get("items", {}).get(str_id)
        except FileNotFoundError:
            base = None
        return self._normalize_item(self._apply_ps_item_layers(str_id, base))

    def get_items_by_type(self, item_type: str) -> list:
        """Return all items of a given type.
        Includes vanilla items (with PS overrides applied) plus any PS-custom or
        renewal items whose 'type' is set in ps_item_manual.json."""
        try:
            data = self._load_json("db/item_db.json")
            vanilla = {k: v for k, v in data.get("items", {}).items() if v.get("type") == item_type}
        except FileNotFoundError:
            vanilla = {}

        results: dict[str, dict] = {}

        # Vanilla items with PS layers applied
        for str_id, base in vanilla.items():
            merged = self._normalize_item(self._apply_ps_item_layers(str_id, base))
            if merged:
                results[str_id] = merged

        # Non-vanilla items (PS-custom) — only present in PS data mode
        if not self._use_ps_data:
            return list(results.values())
        manual = self._load_ps_item_manual()
        for str_id, man in manual.items():
            if str_id in results:
                continue  # already included above
            if man.get("type") == item_type:
                merged = self._normalize_item(self._apply_ps_item_layers(str_id, None))
                if merged:
                    results[str_id] = merged

        if item_type == "IT_CARD":
            return list(results.values()) + self.get_convenience_cards()
        return list(results.values())

    def get_item_by_aegis(self, aegis_name: str) -> Optional[Dict]:
        """Look up an item by its aegis_name string. Returns None if not found.
        Used by apply_combo_bonuses() to resolve combo item names for display."""
        if not hasattr(self, "_aegis_to_item_cache"):
            try:
                data = self._load_json("db/item_db.json")
                self._aegis_to_item_cache: dict[str, dict] = {
                    v["aegis_name"]: v
                    for v in data.get("items", {}).values()
                    if isinstance(v, dict) and v.get("aegis_name")
                }
            except FileNotFoundError:
                self._aegis_to_item_cache = {}
        return self._aegis_to_item_cache.get(aegis_name)

    # =============================================================
    # Item combo database
    # =============================================================

    def _load_item_combo_db(self) -> list[dict]:
        """Lazy-load item_combo_db.json. Returns [] if file missing."""
        if hasattr(self, "_item_combo_db_cache"):
            return self._item_combo_db_cache  # type: ignore[return-value]
        try:
            self._item_combo_db_cache: list[dict] = self._load_json("db/item_combo_db.json")
        except FileNotFoundError:
            self._item_combo_db_cache = []
        return self._item_combo_db_cache

    def _load_ps_item_combo_db(self) -> list[dict]:
        """Lazy-load PayonStoriesData/ps_item_combo_db.json (PS-custom combos).
        Returns [] if file absent — not required for vanilla operation."""
        if hasattr(self, "_ps_item_combo_db_cache"):
            return self._ps_item_combo_db_cache  # type: ignore[return-value]
        path = Path(__file__).parent.parent / "PayonStoriesData" / "ps_item_combo_db.json"
        try:
            self._ps_item_combo_db_cache: list[dict] = json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        except (json.JSONDecodeError, OSError):
            self._ps_item_combo_db_cache = []
        return self._ps_item_combo_db_cache

    def get_active_combos(self, equipped_aegis: frozenset[str], profile=None) -> list[dict]:
        """Return combos where every required item is present in equipped_aegis.

        equipped_aegis: frozenset of aegis_name strings for all currently equipped items.
        profile: ServerProfile (optional). When provided and server is PS, PS-custom
                 combos from PayonStoriesData/ps_item_combo_db.json are appended to
                 the vanilla list before filtering.

        Returns list of {items: [...], script: "..."} dicts for active combos only.
        """
        combos = self._load_item_combo_db()
        if profile is not None and profile.use_ps_data:
            combos = combos + self._load_ps_item_combo_db()
        return [c for c in combos if all(item in equipped_aegis for item in c["items"])]

    # =============================================================
    # Monster database
    # =============================================================

    def _load_ps_mob_db(self) -> dict[str, dict]:
        """Lazy-load PayonStoriesData/ps_mob_db.json.
        Returns {} and prints a warning if the file is absent (run import_ps_mob_db.py).
        Not cached via lru_cache — PayonStoriesData/ is outside base_path."""
        if hasattr(self, "_ps_mob_db_cache"):
            return self._ps_mob_db_cache  # type: ignore[return-value]
        path = Path(__file__).parent.parent / "PayonStoriesData" / "ps_mob_db.json"
        if not path.exists():
            print(
                "WARNING: PayonStoriesData/ps_mob_db.json not found. "
                "Run tools/import_ps_mob_db.py to generate it.",
                file=__import__("sys").stderr,
            )
            self._ps_mob_db_cache: dict[str, dict] = {}
        else:
            data = json.loads(path.read_text(encoding="utf-8"))
            self._ps_mob_db_cache = data.get("mobs", {})
        return self._ps_mob_db_cache

    def get_monster_data(self, mob_id: int) -> Optional[Dict]:
        """Raw mob_db entry for GUI display (hp, atk_min/max, mdef, etc.).
        Uses ps_mob_db when PS data is active; vanilla mob_db otherwise.
        Returns None if mob_id is not found — caller decides how to handle."""
        if self._use_ps_data:
            return self._load_ps_mob_db().get(str(mob_id))
        try:
            data = self._load_json("db/mob_db.json")
        except FileNotFoundError:
            return None
        return data.get("mobs", {}).get(str(mob_id))

    def get_monster(self, mob_id: int) -> "Target":
        """Returns a Target populated from mob_db for pipeline use.
        Logs WARNING and returns a safe neutral default Target on missing ID.
        Default mirrors Unarmed convention: no modifiers, pipeline never crashes."""
        entry = self.get_monster_data(mob_id)
        if entry is None:
            print(
                f"WARNING: Mob ID {mob_id} not found in mob_db. Using default Target.",
                file=__import__("sys").stderr,
            )
            return Target()  # all-default: DEF 0, VIT 0, Medium, Formless, Neutral/1, not boss, level 1
        stats  = entry.get("stats", {})
        level  = entry["level"]
        agi    = stats.get("agi", 0)
        dex    = stats.get("dex", 0)
        return Target(
            def_=entry["def_"],
            vit=stats.get("vit", entry.get("vit", 0)),
            luk=stats.get("luk", 0),
            agi=agi,
            str=stats.get("str", 0),
            dex=dex,
            # Pre-compute flee and hit (status.c:3864-3865 #else not RENEWAL):
            #   st->flee += level + st->agi
            #   st->hit  += level + st->dex
            # apply_mob_scs() mutates these after SC effects are applied.
            flee=level + agi,
            hit=level + dex,
            size=entry["size"],
            race=entry["race"],
            element=entry["element"],
            element_level=entry["element_level"],
            is_boss=entry["is_boss"],
            level=level,
            mdef_=entry.get("mdef", 0),
            int_=stats.get("int", 0),
        )

    # =============================================================
    # Job database (ASPD base, HP table, SP table per job_id)
    # =============================================================
    def get_job_entry(self, job_id: int) -> Optional[Dict]:
        """Return the job_db.json entry for job_id, or None if not found."""
        try:
            data = self._load_json("tables/job_db.json")
        except FileNotFoundError:
            return None
        return data.get("jobs", {}).get(str(job_id))

    def get_aspd_base(self, job_id: int, weapon_type: str) -> int:
        """Return BaseASPD amotion for (job_id, weapon_type); 2000 if not found.
        Source: job_db.conf BaseASPD, status.c status_base_amotion_pc (#ifndef RENEWAL_ASPD)"""
        entry = self.get_job_entry(job_id)
        if entry is None:
            return 2000  # slowest possible — safe fallback
        return entry.get("aspd_base", {}).get(weapon_type, 2000)

    def get_hp_at_level(self, job_id: int, level: int) -> int:
        """Return base HP for (job_id, level).
        level is 1-indexed. Source: job_db.conf HPTable."""
        entry = self.get_job_entry(job_id)
        if entry is None:
            raise KeyError(f"job_id {job_id} not found in job_db")
        table = entry.get("hp_table", [])
        if not table:
            raise ValueError(f"hp_table empty for job_id {job_id}")
        idx = max(0, min(level - 1, len(table) - 1))
        return table[idx]

    def get_sp_at_level(self, job_id: int, level: int) -> int:
        """Return base SP for (job_id, level).
        level is 1-indexed. Source: job_db.conf SPTable."""
        entry = self.get_job_entry(job_id)
        if entry is None:
            raise KeyError(f"job_id {job_id} not found in job_db")
        table = entry.get("sp_table", [])
        if not table:
            raise ValueError(f"sp_table empty for job_id {job_id}")
        idx = max(0, min(level - 1, len(table) - 1))
        return table[idx]

    # =============================================================
    # Skills (metadata from db/skills.json; damage ratios are in skill_ratio.py)
    # =============================================================
    def get_skill(self, skill_id: int) -> Optional[Dict]:
        try:
            data = self._load_json("db/skills.json")
        except FileNotFoundError:
            return None
        return data.get("skills", {}).get(str(skill_id))

    # =============================================================
    # Tables – only size_fix for now (exact from repo)
    # =============================================================
    def get_size_fix_multiplier(self, weapon_type: str, target_size: str) -> int:
        """Exact lookup from db/pre-re/size_fix.txt (via JSON)"""
        data = self._load_json("tables/size_fix.json")
        try:
            w_idx = data["weapon_types"].index(weapon_type)
            s_idx = data["sizes"].index(target_size)
            return data["table"][s_idx][w_idx]
        except (ValueError, IndexError):
            return 100  # fallback only if index missing – never invented

    # =============================================================
    # Refine bonuses
    # =============================================================
    @lru_cache(maxsize=None)
    def get_refine_bonus(self, weapon_level: int, refine: int) -> int:
        """Exact pre-renewal weapon refine bonus.
        Source: battle_calc_base_damage2 + status_calc_pc_equip + refine_get_bonus"""
        if weapon_level < 1 or weapon_level > 4 or refine < 0:
            return 0
        data = self._load_json("tables/refine_weapon.json")
        rate = data["bonus"][weapon_level]
        return rate * refine

    @lru_cache(maxsize=None)
    def get_overrefine(self, weapon_level: int, refine: int) -> int:
        """Compute sd->right_weapon.overrefine from refine level and weapon level.
        status.c: wd->overrefine = refine->get_randombonus_max(wlv, r) / 100;
        refine.c: rnd_bonus[level] = rnd_bonus_v * (level - rnd_bonus_lv + 2);
                  where level is 0-indexed, rnd_bonus_lv is 1-indexed RandomBonusStartLevel.
        Simplified: randombonus_max = rnd_bonus_v * (refine - safe_start + 1)  (when refine >= safe_start)
        """
        if weapon_level < 1 or weapon_level > 4 or refine <= 0:
            return 0
        data = self._load_json("tables/refine_weapon.json")
        safe_start = data["safe_refine_start"][weapon_level]
        rnd_bonus_v = data["random_bonus_value"][weapon_level]
        if safe_start == 0 or rnd_bonus_v == 0 or refine < safe_start:
            return 0
        randombonus_max = rnd_bonus_v * (refine - safe_start + 1)
        return randombonus_max // 100

    @lru_cache(maxsize=None)
    def get_armor_refine_units(self, refine: int) -> int:
        """Raw refinedef units contributed by one armor piece at the given refine level.
        Caller must sum across all armor slots, then apply (total + 50) // 100 for DEF.
        Source: status.c ~1655  refine->get_bonus(REFINE_TYPE_ARMOR, r)
                refine_db.conf  Armors.StatsPerLevel
        """
        if refine <= 0:
            return 0
        data = self._load_json("tables/refine_armor.json")
        return refine * data["stats_per_level"]

    # =============================================================
    # Mastery bonuses
    # =============================================================

    def get_mastery_multiplier(self, mastery_key: str, build: "PlayerBuild") -> int:
        """Returns the correct per-level multiplier for the current mount state.
        Uses the extended JSON schema; falls back to default if no conditional matches.
        Mirrors the exact if/else order in battle.c for KN_SPEARMASTERY."""
        data = self._load_json("tables/mastery_fix.json")
        mastery = data.get("masteries", {}).get(mastery_key)
        if not mastery:
            return 1
        if build.is_riding_peco and "riding_peco" in mastery:
            return mastery["riding_peco"]
        return mastery.get("default", 1)
    
    # =============================================================
    # Attributes
    # =============================================================

    def get_element_name(self, element_id: int) -> str:
        """Maps element ID (0-9) to name exactly as used in battle.c / status.c."""
        names = {
            0: "Neutral",
            1: "Water",
            2: "Earth",
            3: "Fire",
            4: "Wind",
            5: "Poison",
            6: "Holy",
            7: "Dark",
            8: "Ghost",
            9: "Undead"
        }
        return names.get(element_id, "Neutral")

    def get_attr_fix_multiplier(self, weapon_element: str, target_element: str, element_level: int) -> int:
        """Looks up the elemental damage multiplier from attr_fix.json.
        Returns integer percentage (100 = no change, 150 = 150% damage, etc.)."""
        data = self._load_json("tables/attr_fix.json")
        level = str(element_level or 1)
        return data.get("table", {}).get(target_element, {}).get(level, {}).get(weapon_element, 100)

    def get_mastery_weapon_map(self) -> dict:
        """Returns the weapon_type → mastery_key mapping from mastery_weapon_map.json."""
        data = self._load_json("tables/mastery_weapon_map.json")
        return data.get("mapping", {})

    # =============================================================
    # Active status bonuses
    # =============================================================

    def get_all_skills(self) -> list:
        """All skill entries from db/skills.json. Used by CombatControlsSection."""
        try:
            data = self._load_json("db/skills.json")
        except FileNotFoundError:
            return []
        return list(data.get("skills", {}).values())

    def get_skill_id_by_name(self, name: str) -> int | None:
        """Reverse lookup: skill constant name (e.g. 'MG_FIREBALL') → numeric skill ID.
        Returns None if the name is not found in skills.json.
        Used by GearBonusAggregator (gear_bonus_aggregator.py) to resolve proc spell IDs from item scripts.
        Result is cached lazily on first call.
        """
        if self._skill_name_to_id is None:
            mapping: dict[str, int] = {}
            try:
                data = self._load_json("db/skills.json")
                for sid, sdata in data.get("skills", {}).items():
                    n = sdata.get("name")
                    if n:
                        mapping[n] = int(sid)
            except FileNotFoundError:
                pass
            self._skill_name_to_id = mapping
        return self._skill_name_to_id.get(name)

    def get_skills_for_job(self, job_id: int) -> frozenset:
        """Return frozenset of skill names available to job_id (includes inherited skills).
        Source: core/data/pre-re/tables/skill_tree.json (scraped from Hercules skill_tree.conf).
        Returns frozenset() if file missing or job not found."""
        try:
            data = self._load_json("tables/skill_tree.json")
        except FileNotFoundError:
            return frozenset()
        names = data.get("jobs", {}).get(str(job_id), [])
        return frozenset(names)

    # =============================================================
    # Item + skill descriptions (scraped from VanillaData)
    # =============================================================

    def get_item_description(self, item_id: int) -> Optional[Dict]:
        """Return {name, description, compound_on} for item_id, or None if absent.
        Merge order: vanilla item_descriptions.json → ps_item_overrides → ps_item_manual.
        PS description field is the in-game HTML stat block; compound_on is preserved
        from vanilla when PS layers don't provide one."""
        if item_id < 0:
            card = next((c for c in self.get_convenience_cards() if c["id"] == item_id), None)
            if card is None:
                return None
            return {"name": card["name"], "description": card["description"],
                    "compound_on": card.get("compound_on")}
        str_id = str(item_id)

        try:
            data = self._load_json("db/item_descriptions.json")
            base = dict(data.get("items", {}).get(str_id) or {})
        except FileNotFoundError:
            base = {}

        for src in (self._load_ps_item_overrides(), self._load_ps_item_manual()):
            entry = src.get(str_id, {})
            if "description" in entry:
                base["description"] = entry["description"]
            if "name" in entry:
                base["name"] = entry["name"]

        return base or None

    def get_skill_description(self, skill_constant: str) -> Optional[Dict]:
        """Return {name, description} for a skill constant (e.g. 'SM_BASH'), or None.
        Source: core/data/pre-re/db/skill_descriptions.json (scraped from VanillaData/skilldesctable.txt)
        """
        try:
            data = self._load_json("db/skill_descriptions.json")
        except FileNotFoundError:
            return None
        return data.get("skills", {}).get(skill_constant)

    def get_skill_display_name(self, constant: str, profile=None, short: bool = False) -> str:
        """Return the display name for a skill constant, respecting the server profile.

        Resolution order:
          1. PS profile (profile.use_ps_skill_names=True): ps_skill_db[constant]["name"]
          2. short=True: skill_descriptions.json[constant]["short_name"] if present
          3. skill_descriptions.json[constant]["name"]
          4. constant itself (fallback)

        short=True is intended for space-constrained labels (e.g. passives grid). PS names
        are unaffected — they come from ps_skill_db.json which has no short_name concept.

        Single resolver used by all GUI callsites and battle_pipeline proc labels.
        """
        if profile is not None and profile.use_ps_skill_names:
            ps_entry = self.get_ps_skill(constant)
            if ps_entry and ps_entry.get("name"):
                return ps_entry["name"]
        desc = self.get_skill_description(constant)
        if desc:
            if short and desc.get("short_name"):
                return desc["short_name"]
            if desc.get("name"):
                return desc["name"]
        return constant

    def get_all_monsters(self) -> list:
        """All mob entries for search.
        Uses ps_mob_db when PS data is active (complete replacement); vanilla mob_db otherwise."""
        if self._use_ps_data:
            return list(self._load_ps_mob_db().values())
        try:
            data = self._load_json("db/mob_db.json")
        except FileNotFoundError:
            return []
        return list(data.get("mobs", {}).values())

    def get_active_status_config(self, status_key: str) -> dict:
        """Returns the complete config dict for a given SC_* key from active_status_bonus.json.
        Used by ActiveStatusBonus (core/calculators/modifiers/active_status_bonus.py).
        Exact mirror of get_mastery_multiplier and get_size_fix_multiplier pattern."""
        data = self._load_json("tables/active_status_bonus.json")
        return data.get("bonuses", {}).get(status_key, {})

    # =============================================================
    # Job stat bonuses (Hercules/db/job_db2.txt)
    # =============================================================

    # Jobs with JOBL_UPPER flag — get +52 extra stat points on rebirth.
    # Source: pc.c:7522 ((sd->job & JOBL_UPPER) != 0 ? 52 : 0)
    # Range 4001–4022 = Novice High through Paladin (Peco).
    _JOBL_UPPER_JOBS: ClassVar[frozenset] = frozenset(range(4001, 4023))

    @lru_cache(maxsize=None)
    def _parse_job_bonus_table(self) -> dict:
        """Parse job stat bonus table.

        Format: JobID -> list of stat codes per level.
        Codes: 0=none 1=STR 2=AGI 3=VIT 4=INT 5=DEX 6=LUK
        Source: Hercules/db/job_db2.txt; applied via param_bonus[] in pc.c:2489
        """
        data = self._load_json("tables/job_bonus_table.json")
        return {int(k): v for k, v in data["job_bonuses"].items()}

    def get_job_bonus_stats(self, job_id: int, job_level: int) -> dict:
        """Cumulative job stat bonuses up to job_level.

        Source: Hercules/db/job_db2.txt; pc.c:2489 param_bonus[type-SP_STR]+=val
        Keys match GearBonuses attr names: str_, agi, vit, int_, dex, luk
        """
        table = self._parse_job_bonus_table()
        codes = table.get(job_id, [])
        result = {"str_": 0, "agi": 0, "vit": 0, "int_": 0, "dex": 0, "luk": 0}
        code_to_key = {1: "str_", 2: "agi", 3: "vit", 4: "int_", 5: "dex", 6: "luk"}
        for code in codes[:job_level]:
            key = code_to_key.get(code)
            if key:
                result[key] += 1
        return result

    @lru_cache(maxsize=None)
    def _parse_statpoint_table(self) -> tuple:
        """Parse stat points per base level table.

        Index N-1 = cumulative stat points at base level N.
        Source: Hercules/db/pre-re/statpoint.txt; pc.c:11870 statp[] seed=45
        Returns a tuple (hashable for lru_cache compatibility).
        """
        data = self._load_json("tables/statpoint_table.json")
        return tuple(data["stat_points"])

    def get_stat_points_at_level(self, base_level: int, job_id: int) -> int:
        """Total stat points available at this base level.

        Non-trans: statpoint_table[base_level-1]
        JOBL_UPPER (4001–4022): +52 extra (pc.c:7522)
        """
        table = self._parse_statpoint_table()
        idx = min(max(base_level, 1), len(table)) - 1
        points = table[idx] if table else 48
        if job_id in self._JOBL_UPPER_JOBS:
            points += 52
        return points

    # =============================================================
    # Payon Stories skill database
    # =============================================================

    def _load_ps_skill_db(self) -> dict[str, dict]:
        """Load PayonStoriesData/ps_skill_db.json and key by Hercules constant.

        Builds the map once and caches it on the instance.
        Source of truth: ps_skill_db.json, generated by tools/import_ps_skill_db.py
        from the PS wiki skill simulator JS bundle.

        Each record already carries a 'constant' field (assigned by the scraper via
        vanilla skills.json cross-reference or ps_custom_constants.json).
        Records without a 'constant' field are silently skipped — they are either
        reserved placeholder slots or unimplemented skills with no registered constant.
        """
        if hasattr(self, "_ps_skill_db"):
            return self._ps_skill_db  # type: ignore[return-value]

        db_path = Path(__file__).parent.parent / "PayonStoriesData" / "ps_skill_db.json"
        if not db_path.exists():
            import warnings
            warnings.warn(
                "PayonStoriesData/ps_skill_db.json not found. "
                "Run tools/import_ps_skill_db.py to generate it.",
                stacklevel=2,
            )
            self._ps_skill_db: dict[str, dict] = {}
            return self._ps_skill_db

        try:
            raw: dict[str, dict] = json.loads(db_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            import warnings
            warnings.warn(f"Failed to load ps_skill_db.json: {exc}", stacklevel=2)
            self._ps_skill_db = {}
            return self._ps_skill_db

        result: dict[str, dict] = {}
        for record in raw.values():
            const = record.get("constant")
            if const:
                result[const] = record

        # Apply manual description overrides (survives rescrapes).
        overrides_path = Path(__file__).parent.parent / "PayonStoriesData" / "ps_skill_desc_overrides.json"
        if overrides_path.exists():
            try:
                overrides: dict[str, dict] = json.loads(overrides_path.read_text(encoding="utf-8"))
                for const, patch in overrides.items():
                    if const.startswith("_comment"):
                        continue
                    if const in result:
                        result[const] = {**result[const], **patch}
                    else:
                        # Vanilla skill renamed in PS (e.g. SM_TWOHANDSWORD → "Blade Mastery").
                        result[const] = patch
            except (json.JSONDecodeError, OSError):
                pass  # overrides file malformed — ignore, don't break the DB load

        self._ps_skill_db = result
        return result

    def get_ps_skill(self, skill_name: str) -> dict | None:
        """Return the Payon Stories skill record for the given Hercules constant.

        Returns None if the skill is not found or if ps_skill_db.json is missing.
        Key fields: id, constant, name, max_level, skill_form, sp_cost, hp_cost,
                    description, levels[{level, effect}], requirements.
        To add a new PS-custom skill constant: edit PayonStoriesData/ps_custom_constants.json
        and re-run tools/import_ps_skill_db.py.
        """
        return self._load_ps_skill_db().get(skill_name)

    def get_ps_custom_skills(self) -> list[dict]:
        """Return all PS-custom skill records (constants with PS_ prefix).

        These are skills absent from vanilla skills.json — their IDs are not in
        the vanilla DB and their constants are registered in ps_custom_constants.json.
        Each record carries a 'job' field (list[int]) for skill-combo job filtering.

        Job associations are read live from ps_custom_constants.json so that
        changes to that file take effect without re-running the scraper.

        Used by CombatControlsSection (gui/sections/combat_controls_section.py) to inject
        PS-custom skills into the skill combo when server=payon_stories.
        """
        # Build id → job map from ps_custom_constants.json (authoritative for job data)
        custom_path = Path(__file__).parent.parent / "PayonStoriesData" / "ps_custom_constants.json"
        job_by_id: dict[int, list[int]] = {}
        if custom_path.exists():
            try:
                raw: dict = json.loads(custom_path.read_text(encoding="utf-8"))
                for sid, value in raw.items():
                    try:
                        skill_id = int(sid)
                    except ValueError:
                        continue
                    if isinstance(value, dict):
                        job_by_id[skill_id] = value.get("job", [])
            except (json.JSONDecodeError, OSError):
                pass

        result: list[dict] = []
        for record in self._load_ps_skill_db().values():
            if not record.get("constant", "").startswith("PS_"):
                continue
            rec = dict(record)  # shallow copy — do not mutate the cache
            rec["job"] = job_by_id.get(rec.get("id", -1), [])
            result.append(rec)
        return result

    # =============================================================
    # Visibility filters (hidden_items.json / hidden_mobs.json)
    # =============================================================
    # All four hidden lists use instance-attribute caches (not lru_cache) so that
    # hide() / unhide() can invalidate them without a full DataLoader reload.

    _PS_HIDDEN_ITEMS: ClassVar[Path] = Path(__file__).parent.parent / "PayonStoriesData" / "ps_hidden_items.json"
    _PS_HIDDEN_MOBS:  ClassVar[Path] = Path(__file__).parent.parent / "PayonStoriesData" / "ps_hidden_mobs.json"

    @staticmethod
    def _read_id_list(path: Path) -> list[int]:
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.exists() else []
        except (json.JSONDecodeError, OSError):
            return []

    @staticmethod
    def _write_id_list(path: Path, ids: list[int]) -> None:
        path.write_text(json.dumps(sorted(ids), indent=2), encoding="utf-8")

    def _load_hidden_items(self) -> list[int]:
        if not hasattr(self, "_hidden_items_cache"):
            self._hidden_items_cache: list[int] = self._read_id_list(self.base_path / "db/hidden_items.json")
        return self._hidden_items_cache

    def _load_hidden_mobs(self) -> list[int]:
        if not hasattr(self, "_hidden_mobs_cache"):
            self._hidden_mobs_cache: list[int] = self._read_id_list(self.base_path / "db/hidden_mobs.json")
        return self._hidden_mobs_cache

    def _load_ps_hidden_items(self) -> list[int]:
        if not hasattr(self, "_ps_hidden_items_cache"):
            self._ps_hidden_items_cache: list[int] = self._read_id_list(self._PS_HIDDEN_ITEMS)
        return self._ps_hidden_items_cache

    def _load_ps_hidden_mobs(self) -> list[int]:
        if not hasattr(self, "_ps_hidden_mobs_cache"):
            self._ps_hidden_mobs_cache: list[int] = self._read_id_list(self._PS_HIDDEN_MOBS)
        return self._ps_hidden_mobs_cache

    def is_item_hidden(self, item_id: int) -> bool:
        """Return True if item_id appears in either the vanilla or PS hidden list.
        A 'Show Hidden Items' toggle in the browser overrides this check."""
        if item_id in self._load_hidden_items():
            return True
        if self._use_ps_data and item_id in self._load_ps_hidden_items():
            return True
        return False

    def is_mob_hidden(self, mob_id: int) -> bool:
        """Return True if mob_id appears in either the vanilla or PS hidden list.
        A 'Show Hidden' toggle in the monster browser overrides this check."""
        if mob_id in self._load_hidden_mobs():
            return True
        if self._use_ps_data and mob_id in self._load_ps_hidden_mobs():
            return True
        return False

    def hide_item(self, item_id: int) -> None:
        """Add item_id to the active hidden list and write to disk.
        Writes to ps_hidden_items.json when the PS profile is active, else hidden_items.json."""
        if self._use_ps_data:
            path, attr = self._PS_HIDDEN_ITEMS, "_ps_hidden_items_cache"
        else:
            path, attr = self.base_path / "db/hidden_items.json", "_hidden_items_cache"
        ids = self._read_id_list(path)
        if item_id not in ids:
            ids.append(item_id)
            self._write_id_list(path, ids)
        if hasattr(self, attr):
            delattr(self, attr)

    def unhide_item(self, item_id: int) -> None:
        """Remove item_id from whichever hidden list(s) it appears in and write to disk."""
        for path, attr in (
            (self._PS_HIDDEN_ITEMS, "_ps_hidden_items_cache"),
            (self.base_path / "db/hidden_items.json", "_hidden_items_cache"),
        ):
            ids = self._read_id_list(path)
            if item_id in ids:
                ids.remove(item_id)
                self._write_id_list(path, ids)
                if hasattr(self, attr):
                    delattr(self, attr)

    def hide_mob(self, mob_id: int) -> None:
        """Add mob_id to the active hidden list and write to disk."""
        if self._use_ps_data:
            path, attr = self._PS_HIDDEN_MOBS, "_ps_hidden_mobs_cache"
        else:
            path, attr = self.base_path / "db/hidden_mobs.json", "_hidden_mobs_cache"
        ids = self._read_id_list(path)
        if mob_id not in ids:
            ids.append(mob_id)
            self._write_id_list(path, ids)
        if hasattr(self, attr):
            delattr(self, attr)

    def unhide_mob(self, mob_id: int) -> None:
        """Remove mob_id from whichever hidden list(s) it appears in and write to disk."""
        for path, attr in (
            (self._PS_HIDDEN_MOBS, "_ps_hidden_mobs_cache"),
            (self.base_path / "db/hidden_mobs.json", "_hidden_mobs_cache"),
        ):
            ids = self._read_id_list(path)
            if mob_id in ids:
                ids.remove(mob_id)
                self._write_id_list(path, ids)
                if hasattr(self, attr):
                    delattr(self, attr)

    # =============================================================
    # Cache control (for hot-reload during development)
    # =============================================================
    def clear_cache(self):
        self._cache.clear()
        DataLoader.get_size_fix_multiplier.cache_clear()  # type: ignore[attr-defined]

    def reload_all(self):
        self.clear_cache()
        print("DataLoader reloaded from disk.")


# Global singleton – import as: from core.data_loader import loader
loader = DataLoader()