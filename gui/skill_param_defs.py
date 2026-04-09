"""Skill parameter descriptors for the Combat Controls section.

Each entry in SKILL_PARAM_REGISTRY declares the runtime inputs a skill needs
beyond its level — things like distance, cart weight, or sphere count.

Adding a new skill with params:
  1. Add an entry here.
  2. Add the calculation lambda to _PARAM_SKILL_RATIO_FNS in skill_ratio.py.
  Nothing else.

Field notes:
  key             Storage key written to build.skill_params.
  label           Text shown next to the widget.
  widget          "combo" | "spin" | "check"
  default         Value used on reset / new build.
  options         combo → list[(display_str, value)]
                  spin  → (min, max, step, suffix_str)
                  check → unused (None)
  visibility      "always" (default) | "ps_only" | "vanilla_only".
                  "ps_only"      → row hidden when server != "payon_stories".
                  "vanilla_only" → row hidden when server == "payon_stories".
  ps_options      combo only: alternate options list shown in PS mode.
                  When set, the combo repopulates to ps_options when server=="payon_stories"
                  and back to options when server changes to standard.
  mirrors_sc_key  If set: load_build() initialises the widget from
                  build.active_status_levels[mirrors_sc_key] rather than
                  build.skill_params[key]. collect_into() still reads the
                  widget — the combat widget is an independent override.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Literal, Optional


@dataclass
class SkillParamSpec:
    key: str
    label: str
    widget: str                  # "combo" | "spin" | "check"
    default: Any
    options: Any = None          # see module docstring
    mirrors_sc_key: Optional[str] = None
    # If set: load_build() calls this to compute the initial widget value from
    # the build rather than reading build.skill_params[key] or spec.default.
    # Signature: (build) -> Any  (duck-typed; no PlayerBuild import needed here)
    default_from_build: Optional[Callable] = None
    # "always" → always visible; "ps_only" → PS mode only; "vanilla_only" → standard mode only.
    visibility: Literal["always", "ps_only", "vanilla_only"] = "always"
    # combo only: alternate options list for PS mode; None means same options in both modes.
    ps_options: Any = None


SKILL_PARAM_REGISTRY: dict[str, list[SkillParamSpec]] = {
    # MO_FINGEROFFENSIVE — sphere count at cast time.
    # Initialised from Self Buffs (MO_SPIRITBALL) but independently overrideable.
    # default_from_build mirrors the Self Buffs sphere count, falling back to the
    # Call Spirits mastery level as a proxy for max spheres when MO_SPIRITBALL is unset.
    "MO_FINGEROFFENSIVE": [
        SkillParamSpec(
            key="MO_FINGEROFFENSIVE_spheres",
            label="Spirit Spheres:",
            widget="combo",
            default=1,
            options=[(str(n), n) for n in range(1, 6)],
            mirrors_sc_key="MO_SPIRITBALL",
            default_from_build=lambda b: b.active_status_levels.get(
                "MO_SPIRITBALL", b.mastery_levels.get("MO_CALLSPIRITS", 1)
            ),
        ),
    ],

    # KN_CHARGEATK — cell distance tier selects the ratio multiplier.
    "KN_CHARGEATK": [
        SkillParamSpec(
            key="KN_CHARGEATK_dist",
            label="Distance:",
            widget="combo",
            default=1,
            options=[
                ("1–3 tiles  (×100%)", 1),
                ("4–6 tiles  (×200%)", 4),
                ("7+ tiles   (×300%)", 7),
            ],
        ),
    ],

    # MC_CARTREVOLUTION — cart weight % feeds the vanilla ratio formula.
    # PS uses flat 250% (weapon_ratios override) so weight param is hidden in PS mode.
    "MC_CARTREVOLUTION": [
        SkillParamSpec(
            key="MC_CARTREVOLUTION_pct",
            label="Cart weight:",
            widget="spin",
            default=0,
            options=(0, 100, 10, " %"),
            visibility="vanilla_only",
        ),
    ],

    # MO_EXTREMITYFIST — current SP at cast time feeds the ratio formula.
    "MO_EXTREMITYFIST": [
        SkillParamSpec(
            key="MO_EXTREMITYFIST_sp",
            label="Current SP:",
            widget="spin",
            default=0,
            options=(0, 9999, 1, ""),
        ),
    ],

    # NJ_ISSEN — pre-renewal formula uses current HP (battle.c:5173 #ifndef RENEWAL).
    # Default 0 → pipeline falls back to status.max_hp automatically.
    "NJ_ISSEN": [
        SkillParamSpec(
            key="NJ_ISSEN_current_hp",
            label="Current HP:",
            widget="spin",
            default=0,
            options=(0, 99999, 1, ""),
        ),
        # Mirror Image attacks remaining (PS only). 0 = not active, no bonus.
        # n≥1 → damage × (105+5×n)/100. Source: user-confirmed.
        SkillParamSpec(
            key="NJ_ISSEN_attacks_left",
            label="Mirror Image stacks:",
            widget="combo",
            default=0,
            options=[(f"{n}" if n else "0 (off)", n) for n in range(0, 6)],
            visibility="ps_only",
        ),
    ],

    # SA_AUTOSPELL — Hindsight: auto-attacks trigger a memorized magic spell proc.
    # Vanilla: user chooses from available spells; proc chance = 5+lv×2%.
    # PS: one spell per SA level (different list); proc chance = flat 30%.
    # ps_options shows the PS spell list; both use the same SA_AUTOSPELL_spell key.
    "SA_AUTOSPELL": [
        SkillParamSpec(
            key="SA_AUTOSPELL_spell",
            label="Memorized Spell:",
            widget="combo",
            default="MG_NAPALMBEAT",
            options=[
                ("Napalm Beat",     "MG_NAPALMBEAT"),
                ("Cold Bolt",       "MG_COLDBOLT"),
                ("Fire Bolt",       "MG_FIREBOLT"),
                ("Lightning Bolt",  "MG_LIGHTNINGBOLT"),
                ("Soul Strike",     "MG_SOULSTRIKE"),
                ("Fire Ball",       "MG_FIREBALL"),
                ("Frost Diver",     "MG_FROSTDIVER"),
            ],
            ps_options=[
                ("Soul Strike",     "MG_SOULSTRIKE"),    # SA lv1
                ("Fire Bolt",       "MG_FIREBOLT"),       # SA lv2
                ("Cold Bolt",       "MG_COLDBOLT"),       # SA lv3
                ("Lightning Bolt",  "MG_LIGHTNINGBOLT"),  # SA lv4
                ("Earth Spike",     "WZ_EARTHSPIKE"),     # SA lv5
                ("Fire Ball",       "MG_FIREBALL"),       # SA lv6
                ("Thunderstorm",    "MG_THUNDERSTORM"),   # SA lv7
                ("Heaven's Drive",  "WZ_HEAVENDRIVE"),    # SA lv8
                ("Stone Curse",     "MG_STONECURSE"),     # SA lv9
                ("Safety Wall",     "MG_SAFETYWALL"),     # SA lv10
            ],
        ),
    ],

    # BA_MUSICALSTRIKE — PS-only: +100 ratio when caster is performing (active in song).
    # PS base ratio 175+25*lv → performing 275+25*lv. Standard mode has no performing bonus.
    "BA_MUSICALSTRIKE": [
        SkillParamSpec(
            key="BA_MUSICALSTRIKE_performing",
            label="Performing",
            widget="check",
            default=False,
            visibility="ps_only",
        ),
    ],

    # DC_THROWARROW — PS-only: +100 ratio when caster is performing (active in dance).
    # PS base ratio 175+25*lv → performing 275+25*lv. Standard mode has no performing bonus.
    "DC_THROWARROW": [
        SkillParamSpec(
            key="DC_THROWARROW_performing",
            label="Performing",
            widget="check",
            default=False,
            visibility="ps_only",
        ),
    ],

    # MG_SOULSTRIKE — PS-only: 50% MDEF ignore when Soul Strike is learned to lv10.
    # Toggle defaults True; user can disable to see non-ignore damage.
    # JSONL: "if the user has learned Soul Strike to level 10, the skill ignores 50% of the
    # target's MDEF regardless of the current Soul Strike level."
    "MG_SOULSTRIKE": [
        SkillParamSpec(
            key="MG_SOULSTRIKE_mdef_ignore",
            label="MDEF Ignore (Lv10 learned)",
            widget="check",
            default=True,
            visibility="ps_only",
        ),
    ],

    # RG_BACKSTAP — PS-only: Opportunity toggle multiplies output by ×1.4.
    # Opportunity is enabled by RG_QUICKSTEP (PS-only skill) and lets the next Backstab
    # deal 40% extra damage. Visible only in Payon Stories mode.
    "RG_BACKSTAP": [
        SkillParamSpec(
            key="RG_BACKSTAP_opportunity",
            label="Opportunity",
            widget="check",
            default=False,
            visibility="ps_only",
        ),
    ],

    # AS_SONICBLOW — Sonic Acceleration quest skill: ×1.1 ratio + ×1.5 hitrate (battle.c:5607, 5088).
    # Default True — assumed learned unless user overrides.
    "AS_SONICBLOW": [
        SkillParamSpec(
            key="AS_SONICBLOW_sonic_accel",
            label="Sonic Acceleration",
            widget="check",
            default=True,
        ),
    ],

    # AS_SPLASHER — PS-only: Poison React level adds 30*lv% to ratio (additive).
    # Vanilla uses AS_POISONREACT mastery; PS replaces with a skill param.
    # Total at lv10 splasher + lv10 react: 500+500+300 = 1300%.
    "AS_SPLASHER": [
        SkillParamSpec(
            key="AS_SPLASHER_poison_react_lv",
            label="Poison React Lv:",
            widget="spin",
            options=(0, 10, 1, ""),
            default=0,
            visibility="ps_only",
        ),
    ],

    # KN_BRANDISHSPEAR — PS-only: distance range selects damage multiplier; optional double hit.
    # Distance multipliers: Range 1 = ×11/6 (≈1.8333), Range 2 = ×1.75, Range 3 = ×1.5, Range 4+ = ×1.0
    # Double hit: second hit uses same ratio but strips SC_LEXAETERNA (pipeline-level second pass).
    "KN_BRANDISHSPEAR": [
        SkillParamSpec(
            key="KN_BRANDISHSPEAR_dist",
            label="Range:",
            widget="combo",
            default=4,
            options=[
                ("Range 1 (\u00d71.8333)", 1),
                ("Range 2 (\u00d71.75)",   2),
                ("Range 3 (\u00d71.5)",    3),
                ("Range 4+ (\u00d71.0)",   4),
            ],
            visibility="ps_only",
        ),
        SkillParamSpec(
            key="KN_BRANDISHSPEAR_double",
            label="Double Hit",
            widget="check",
            default=False,
            visibility="ps_only",
        ),
    ],

    # WZ_FROSTNOVA — PS-only: ratio = 50*lv + 10*FrostDiver_level per hit.
    # Defaults from build's MG_FROSTDIVER mastery level; user can override independently.
    "WZ_FROSTNOVA": [
        SkillParamSpec(
            key="WZ_FROSTNOVA_frostdiver_lv",
            label="Frost Diver Level:",
            widget="combo",
            default=0,
            options=[("Lv 0 (none)", 0)] + [(f"Lv {n}", n) for n in range(1, 11)],
            default_from_build=lambda b: b.mastery_levels.get("MG_FROSTDIVER", 0),
            visibility="ps_only",
        ),
    ],

    # WZ_FIREPILLAR — PS-only: ratio = (50 + 2*FireWall_level)% per hit.
    # Defaults from build's WZ_FIREWALL mastery level; user can override independently.
    "WZ_FIREPILLAR": [
        SkillParamSpec(
            key="WZ_FIREPILLAR_firewall_lv",
            label="Fire Wall Level:",
            widget="combo",
            default=0,
            options=[("Lv 0 (none)", 0)] + [(f"Lv {n}", n) for n in range(1, 11)],
            default_from_build=lambda b: b.mastery_levels.get("WZ_FIREWALL", 0),
            visibility="ps_only",
        ),
    ],

    # MC_MAMMONITE — PS-only: Zeny Pincher toggle multiplies ratio × 0.4, removes zeny cost.
    # Available to all Merchant family (jobs 5/10/18/4011/4019); Rogue has Mammonite, not Pincher.
    "MC_MAMMONITE": [
        SkillParamSpec(
            key="PS_BS_ZENYPINCHER_active",
            label="Zeny Pincher",
            widget="check",
            default=False,
            visibility="ps_only",
        ),
    ],

    # AM_SPHEREMINE — PS-only: 1–3 spheres detonate simultaneously.
    "AM_SPHEREMINE": [
        SkillParamSpec(
            key="AM_SPHEREMINE_count",
            label="Spheres:",
            widget="combo",
            default=1,
            options=[(f"{n} sphere{'s' if n > 1 else ''}", n) for n in range(1, 4)],
            visibility="ps_only",
        ),
    ],

    # GS_DESPERADO — target distance zone (1=closest, 5=corner).
    # Hercules: 7×7 unit grid (Layout:3), 100ms interval × 10 fires; per-cell hit% from skill.c:13538–13553.
    # Vanilla: 36/24/12/8/4% per zone → 3.6/2.4/1.2/0.8/0.4 expected hits.
    # PS: 63/42/21/14/7% per zone → 6.3/4.2/2.1/1.4/0.7 expected hits.
    "GS_DESPERADO": [
        SkillParamSpec(
            key="GS_DESPERADO_zone",
            label="Distance:",
            widget="combo",
            default=1,
            options=[
                ("Close (0–1 cells)", 1),
                ("Mid (2 cells)", 2),
                ("Far (3 cells)", 3),
                ("Far diagonal", 4),
                ("Corner (±3,±3)", 5),
            ],
        ),
    ],

    # WZ_STORMGUST — hitting waves before target freezes.
    # Storm Gust fires 10 waves (SkillData1=4600ms / Interval=450ms).
    # Water element target freezes after 3 hits and takes no further SG damage while frozen.
    # Default 3 reflects the practical freeze-and-switch scenario.
    # Set to 10 for freeze-immune targets (boss, undead, etc.) or pre-frozen targets.
    "WZ_STORMGUST": [
        SkillParamSpec(
            key="WZ_STORMGUST_waves",
            label="Hitting waves:",
            widget="combo",
            default=3,
            options=[(f"{n} wave{'s' if n != 1 else ''}", n) for n in range(1, 11)],
        ),
    ],

    # NJ_KIRIKAGE (Shadow Slash) — PS-only: hiding toggle selects ratio table; when not hidden,
    # ratio decreases by 10 per range from target. Shadows Within crit bonus (25+5×lv)% applies
    # independently of hiding state.
    # Source: server_profiles.py / ps_skill_db.json id=530.
    "NJ_KIRIKAGE": [
        SkillParamSpec(
            key="NJ_KIRIKAGE_hiding",
            label="Hiding",
            widget="check",
            default=False,
            visibility="ps_only",
        ),
        SkillParamSpec(
            key="NJ_KIRIKAGE_range_pp",
            label="Range:",
            widget="combo",
            default=0,
            options=[(str(n), n) for n in range(6)],
            visibility="ps_only",
        ),
        SkillParamSpec(
            key="PS_NJ_SHADOWSWITHIN_active",
            label="Shadows Within (active)",
            widget="check",
            default=False,
            visibility="ps_only",
        ),
    ],

    # NJ_KASUMIKIRI — PS-only: [When Hidden] ×1.4 damage bonus (Hiding removes on hit; SP halved).
    # Source: ps_skill_db.json id=528 description.
    "NJ_KASUMIKIRI": [
        SkillParamSpec(
            key="NJ_KASUMIKIRI_hiding",
            label="Hiding (×1.4)",
            widget="check",
            default=False,
            visibility="ps_only",
        ),
    ],

    # NJ_KAENSIN — PS-only: multi-enemy toggle divides per-cell hit count by 3.
    # Off (default): 3/3/3/3/6/6/6/6/9/9 hits at lv1–10.
    # On: 1/1/1/1/2/2/2/2/3/3 hits (models hitting multiple enemies per cast).
    "NJ_KAENSIN": [
        SkillParamSpec(
            key="NJ_KAENSIN_multi",
            label="Multi-enemy",
            widget="check",
            default=False,
            visibility="ps_only",
        ),
    ],

    # TK_JUMPKICK — two boolean toggles affect ratio (combo) and a ×2 multiplier (running).
    "TK_JUMPKICK": [
        SkillParamSpec(
            key="TK_JUMPKICK_combo",
            label="Combo Attack",
            widget="check",
            default=False,
        ),
        SkillParamSpec(
            key="TK_JUMPKICK_running",
            label="Running (TK_RUN)",
            widget="check",
            default=False,
        ),
    ],
}
