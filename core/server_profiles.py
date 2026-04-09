"""Server profile system — per-server deviation tables for the damage pipeline.

ServerProfile is a frozen dataclass holding all server-specific deviations from vanilla
Hercules as callable tables. Each field is an override dict keyed by skill/SC name; an empty
dict means vanilla behaviour applies for all keys not present.

Two profiles are defined:
  STANDARD      — all override dicts empty; pipeline falls back to vanilla Hercules throughout.
  PAYON_STORIES — populated with verified PS deviations (weapon_ratios, magic_ratios,
                  mechanic_flags, passive_overrides, etc.).

Consumption: BattlePipeline.calculate() and StatusCalculator.calculate() resolve the active
profile once per pipeline entry and pass it to each modifier. Modifiers check the profile dict
first, then fall back to vanilla. No repeated name-string comparisons in hot paths.

get_profile(server_name) → ServerProfile  resolves by name; unknown names return STANDARD.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable


@dataclass(frozen=True)
class ServerProfile:
    name: str
    # BF_WEAPON ratio overrides: skill_name → (lv, tgt) → int ratio %
    weapon_ratios: dict[str, Callable]
    # BF_WEAPON hit-count overrides: skill_name → (lv, tgt) → int hit_count
    weapon_hit_counts: dict[str, Callable]
    # Post-defense % damage bonuses from active SCs: SC_key → rate int
    # Applied in ActiveStatusBonus as _scale_floor(pmf, 100+rate, 100).
    rate_bonuses: dict[str, int]
    # BF_MAGIC ratio overrides: skill_name → (lv, tgt, ctx=None) → int ratio %
    # Consumed by SkillRatio.calculate_magic() (skill_ratio.py).
    magic_ratios: dict[str, Callable]
    # BF_MAGIC hit-count overrides: skill_name → (lv, tgt, ctx=None) → int hit_count
    # Consumed by SkillRatio.get_magic_hit_count() (skill_ratio.py).
    magic_hit_counts: dict[str, Callable]
    # BF_MAGIC wave-indexed ratio overrides: skill_name → (lv, tgt, ctx=None) → int ratio %
    # ctx.wave_idx carries the 1-based wave index (set per-wave by calculate_magic()).
    # Used when each of the N waves deals a different ratio (e.g. PS WZ_VERMILION).
    # Overrides the entire ratio+wave_count path in calculate_magic().
    magic_wave_ratios: dict[str, Callable]
    # BF_MISC formula overrides: skill_name → (lv, status, target, build, gb=None) → (min_dmg, max_dmg)
    # Also enables PS-only BF_MISC skills (e.g. AM_SPHEREMINE) absent from vanilla _BF_MISC_FORMULAS.
    # Consumed by BattlePipeline BF_MISC dispatch (battle_pipeline.py).
    misc_formulas: dict[str, Callable]
    # Per-skill element overrides: skill_name → int element (0=Neutral, 1=Water, …)
    # Consumed by BattlePipeline after standard skill_data element resolution (battle_pipeline.py).
    skill_elements: dict[str, int]
    # mastery_key → flat bonus per mastery level
    # Consumed by MasteryFix (mastery_fix.py).
    mastery_per_level: dict
    # Mastery overrides requiring CalcContext (base_level-scaling etc); replaces mechanic_flag inline branches.
    # Schema: {mastery_key: (mastery_level, target, ctx=None) → int | None}
    # None return means no bonus for this condition.
    mastery_ctx_overrides: dict[str, Callable]
    # CR_GRANDCROSS mastery overrides: different per-mastery bonuses when using Grand Cross.
    # Schema: {mastery_key: (mastery_level, target, build) → int}
    # Takes priority over mastery_ctx_overrides and mastery_per_level for that skill.
    # Empty dict on STANDARD → vanilla mastery values apply.
    gc_mastery_overrides: dict[str, Callable]
    # Mechanic flag overrides: string sentinels checked by individual modifiers and pipeline steps.
    # e.g. "CR_SHIELDBOOMERANG_NK_IGNORE_FLEE", "SC_CLOAKING_BONUS". Consumed across multiple modules.
    mechanic_flags: frozenset
    # Passive stat overrides: HIT/FLEE/CRI/katar-factor additions per skill/SC.
    # Schema: {skill_or_sc_key: {stat_key: value}}
    # Known stat keys:
    #   hit_per_lv, flee_per_lv, cri_per_lv  — flat addend × level
    #   cri_at_max_lv                          — flat CRI added when skill == max level
    #   katar_second_factor_per_lv             — contributes level×N to _katar_second_hit factor
    passive_overrides: dict
    # SC / passive skill ASPD deviations from vanilla.
    # Schema: {skill_or_sc_key: spec_dict}
    # Known spec shapes:
    #   {"quicken": {"WeaponType": callable(lv) → int, "other": callable(lv) → int}}
    #       — replaces the vanilla quicken-pool value for that SC
    #   {"lv10_rate": {"WeaponType": int_delta, ...}}
    #       — applies sc_aspd_rate += delta when mastery_level >= 10 and weapon matches
    # Consumed by ASPDCalculator (aspd.py).
    aspd_buffs: dict
    # Double-hit proc rate overrides: skill_name → rate% per level.
    # Vanilla default is 5.0%/lv for TF_DOUBLE and GS_CHAINACTION.
    # Consumed by BattlePipeline proc_branch logic (battle_pipeline.py).
    proc_rate_overrides: dict[str, float]
    # SC_STEELBODY formula override: (def_fn, mdef_fn) or None for vanilla 90 flat.
    # Each callable: (equip_value: int) → int DEF/MDEF to set.
    steelbody_override: tuple | None
    # Super Novice HP/SP bonus tables.
    # {level_threshold: bonus_value} — summed for all thresholds <= base_level.
    # Empty dicts in STANDARD → no bonus. Consumed by StatusCalculator (status_calculator.py).
    sn_hp_bonus: dict[int, int]
    sn_sp_bonus: dict[int, int]
    # BF_WEAPON skills confirmed PS ratio == vanilla.
    # If a skill is in IMPLEMENTED_BF_WEAPON_SKILLS and NOT in weapon_ratios and NOT here,
    # SkillRatio.calculate() emits a warning DamageStep (vanilla used as unverified fallback).
    weapon_vanilla_ok: frozenset
    # BF_MAGIC skills confirmed PS ratio == vanilla. Same warning logic as weapon_vanilla_ok.
    magic_vanilla_ok: frozenset
    # Regen tick intervals in seconds.
    # HP: standing / sitting. SP: standing / sitting. Skills (Inc HP / SP Recovery): single value.
    tick_hp_stand: int
    tick_hp_sit: int
    tick_sp_stand: int
    tick_sp_sit: int
    tick_skill: int
    # Per-skill minimum period in ms: skill_name → floor applied to max(cast+delay, amotion).
    # Used for PS fixed cooldowns (e.g. BA_MUSICALSTRIKE / DC_THROWARROW: 300 ms).
    # Empty dict on STANDARD → no override.
    skill_min_period_ms: dict[str, int]
    # Per-skill ACD formula overrides: skill_name → (status) → int ms.
    # Replaces base_delay (pre-reduction) for that skill on PS server.
    # Empty dict on STANDARD → no override.
    ps_skill_delay_fn: dict[str, Callable]
    # Skills with ACD forced to minimum (effective_delay = _MIN_SKILL_DELAY_MS).
    # Empty frozenset on STANDARD → no override.
    ps_acd_zero: frozenset
    # Skills with cast time forced to 0 (effective_cast = 0).
    # Empty frozenset on STANDARD → no override.
    ps_zero_cast: frozenset
    # Per-skill DPS period override: skill_name → (status, amotion_ms) → int period_ms.
    # Replaces max(cast+delay, amotion) for that skill.
    # Empty dict on STANDARD → no override.
    ps_attack_interval: dict[str, Callable]
    # Per-skill max level caps for GUI LevelWidget and pipeline: skill_name → max_lv.
    # Empty dict on STANDARD → no override.
    skill_level_cap_overrides: dict[str, int]
    # Passive incoming elemental resists, weapon-gated, level-gated.
    # Schema: {skill_key: {"sub_ele_at_max_lv": {Ele_key: pct}, "weapon_types": [str], "max_level": int}}
    #   sub_ele_at_max_lv  — element resist added when mastery_level >= max_level
    #   weapon_types       — resist only applies when player's weapon type is in this list
    #   max_level          — skill level required to trigger the resist
    # Empty dict on STANDARD → no override. Consumed by StatusCalculator (status_calculator.py).
    passive_resists: dict

    # PS per-job stat bonus overrides (replaces job_db2.txt for listed jobs).
    # Schema: {job_id: [(level, stat_key), ...]} where stat_key ∈ {"str_","agi","vit","int_","dex","luk"}.
    # Each tuple means: at that job_level, that stat gains +1. Multiple tuples at the same level are allowed.
    # Empty dict on STANDARD → use vanilla job_db2.txt for all jobs.
    ps_job_bonuses: dict

    # PS-specific weapon_type → mastery_key additions (consulted when vanilla lookup returns None).
    # Empty dict on STANDARD → vanilla mastery_weapon_map.json only. Consumed by MasteryFix (mastery_fix.py).
    ps_mastery_weapon_map: dict[str, str]

    # PS-specific flat ATK additions applied after SkillRatio scaling (ATK_ADD equivalent).
    # Schema: {skill_name: (params, lv) → int flat}
    # Empty dict on STANDARD → no flat add for any skill. Consumed by SkillRatio.calculate() (skill_ratio.py).
    param_skill_flat_adds: dict[str, Callable]

    # Zone-based average hit counts for chance-based weapon skills (e.g. GS_DESPERADO).
    # Schema: {skill_name: (avg_hits_zone1, avg_hits_zone2, ...)}
    # Zone is selected by the {SKILL}_zone skill param (1-indexed).
    # weapon_hit_counts for these skills must return 1 so the main result is single-hit damage.
    # BattlePipeline adds a 100%-chance "Avg ×N" proc_branch and overrides DPS with expected total.
    # Empty dict on STANDARD → no zone-based display for any skill.
    weapon_avg_hits_by_zone: dict[str, tuple[float, ...]]
    # Whether to use PS skill display names from ps_skill_db.json.
    # True → get_skill_display_name() prefers ps_skill_db[constant]["name"] when available.
    use_ps_skill_names: bool
    # Whether to apply PS data layers (item overrides, custom items, custom mobs, item combos).
    # True → data_loader.py uses PayonStoriesData/ files instead of vanilla core/data/pre-re/ only.
    use_ps_data: bool

    # PS changelog 2026-03-23: Blade Mastery (SM_TWOHANDSWORD) extends to SM_SWORD weapon types.
    # Schema: {vanilla_mastery_key: preferred_mastery_key}
    # In mastery_fix.py: if player has preferred_key > 0, redirect from vanilla to preferred.
    # Rogue (SM_SWORD > 0, SM_TWOHANDSWORD = 0) is unaffected.
    # Empty dict on STANDARD → no redirection.
    mastery_prefer_fallback: dict[str, str]

    # PS changelog 2026-03-23: SM_SWORD removed from Swordsman tree.
    # Schema: {skill_constant: frozenset[job_id]} — hide passive row for these jobs on PS.
    # Empty dict on STANDARD → no job-based hiding.
    passive_hidden_for_jobs: dict[str, frozenset]

    # Pet bonus overrides: pet_name → bonus dict. Entries here COMPLETELY replace the
    # vanilla PET_BONUSES entry for that name. PS-custom pets also live here.
    # Empty dict on both STANDARD and PAYON_STORIES — user fills PS data when needed.
    pet_bonuses: dict[str, dict]


# NJ_KIRIKAGE per-level ratio tables (hiding ON/OFF). Source: ps_skill_db.json id=530.
_NJ_KIRIKAGE_HIDE_ON:  list[int] = [100, 200, 400, 600, 800]
_NJ_KIRIKAGE_HIDE_OFF: list[int] = [100, 190, 280, 360, 450]
# NJ_KASUMIKIRI (Haze Slash) per-level ratio table. Source: ps_skill_db.json id=528.
_NJ_KASUMIKIRI_RATIOS: list[int] = [100, 125, 150, 175, 200, 250, 275, 300, 325, 375]

# ---------------------------------------------------------------------------
# BF_WEAPON ratio overrides — all verified from ps_skill_db.json
# ---------------------------------------------------------------------------
_PS_BF_WEAPON_RATIOS: dict[str, Callable] = {
    # JSONL: "Damage 400%, 2 hits" — 400% per hit; second hit modelled at pipeline level
    "KN_BOWLINGBASH":    lambda lv, tgt, ctx=None: 400,
    # JSONL: "(100+20*lv)% × distance multiplier"; distance param selects multiplier at pipeline level
    "KN_BRANDISHSPEAR":  lambda lv, tgt, ctx=None: int(
        (100 + 20 * lv) * {1: 11/6, 2: 1.75, 3: 1.5, 4: 1.0}.get(
            ctx.skill_params.get("KN_BRANDISHSPEAR_dist", 4) if ctx else 4, 1.0)),
    # JSONL: "500% + 40% per level"; PS lv10 = 900%
    "AS_SONICBLOW":      lambda lv, tgt, ctx=None: 500 + 40 * lv,
    # PS changelog 2026-03-23: 200% ATK (vanilla: 100% flat, battle.c:no case in switch).
    "KN_AUTOCOUNTER":    lambda lv, tgt, ctx=None: 200,
    # PS changelog 2026-03-23: (100+40*lv)%, max lv 5. Vanilla: 100+20*lv (battle.c:2085-2086).
    "KN_SPEARSTAB":      lambda lv, tgt, ctx=None: 100 + 40 * lv,
    # JSONL: "300% + 25% per level"; PS lv10 = 550%
    "CR_HOLYCROSS":      lambda lv, tgt, ctx=None: 300 + 25 * lv,
    # JSONL: "100% + 100% per level"; PS lv5 = 600%
    "RG_RAID":           lambda lv, tgt, ctx=None: 100 + 100 * lv,
    # JSONL: "100% + 80% per level"; PS lv5 = 500%
    "AM_ACIDTERROR":     lambda lv, tgt, ctx=None: 100 + 80 * lv,
    # User correction: 200+40*lv (JSONL was stale; Rogue reworked since DB scraped).
    # PS removes bow-split: single ratio regardless of weapon type.
    "RG_BACKSTAP":       lambda lv, tgt, ctx=None: 200 + 40 * lv,

    # AS_SPLASHER: (500+50*lv)% + 30*poison_react_lv additive (from ctx.skill_params).
    # Vanilla adds 20*AS_POISONREACT mastery; PS replaces with skill param.
    "AS_SPLASHER":       lambda lv, tgt, ctx=None: (
        500 + 50 * lv + 30 * (ctx.skill_params.get("AS_SPLASHER_poison_react_lv", 0) if ctx else 0)
    ),

    # --- Crusader ---
    # JSONL lv1=140%, lv5=300%; vanilla=100+30*lv
    "CR_SHIELDBOOMERANG": lambda lv, tgt, ctx=None: 100 + 40 * lv,
    # JSONL lv1=220%, lv5=300%; vanilla=100+20*lv
    "CR_SHIELDCHARGE":    lambda lv, tgt, ctx=None: 200 + 20 * lv,
    # --- Merchant ---
    # JSONL description: "250% Attack"; vanilla=cart weight formula (~150-250%)
    # PS removes cart weight scaling. SkillRatio profile.weapon_ratios takes priority
    # over _PARAM_SKILL_RATIO_FNS, bypassing the cart weight param fn.
    "MC_CARTREVOLUTION":  lambda lv, tgt, ctx=None: 250,
    # JSONL: 100+50*lv (lv10=600%). Zeny Pincher (PS_BS_ZENYPINCHER_active toggle) × 0.4.
    # Removed from _PS_WEAPON_VANILLA_OK because the toggle creates a PS-specific ratio path.
    "MC_MAMMONITE":       lambda lv, tgt, ctx=None: int(
        (100 + 50 * lv) * (0.4 if (ctx and ctx.skill_params.get("PS_BS_ZENYPINCHER_active")) else 1.0)
    ),
    # --- Monk ---
    # JSONL lv1=240%, lv5=560%; vanilla=150+50*lv (battle.c:2211-2212)
    "MO_CHAINCOMBO":      lambda lv, tgt, ctx=None: 160 + 80 * lv,
    # JSONL lv1=340%, lv5=680%; vanilla=240+60*lv (battle.c:2214-2215)
    "MO_COMBOFINISH":     lambda lv, tgt, ctx=None: 255 + 85 * lv,
    # --- Thief / Rogue ---
    # PS_RG_TRICKARROW: 2 hits × 100% = 200% total. Source: ps_skill_db.json (PS custom).
    "PS_RG_TRICKARROW":   lambda lv, tgt, ctx=None: 100,
    # PS_RG_QUICKSTEP: 10% ATK, 4s CD. Source: ps_skill_db.json (PS custom).
    "PS_RG_QUICKSTEP":    lambda lv, tgt, ctx=None: 10,
    # PS_PR_HOLYSTRIKE: [101 + BaseSTR + BaseLv]% ATK. Holy element. Proc on melee auto.
    # Source: ps_skill_db.json id=2622.
    "PS_PR_HOLYSTRIKE":   lambda lv, tgt, ctx=None: 101 + (ctx.base_str if ctx else 0) + (ctx.base_level if ctx else 0),
    # --- Alchemist ---
    # JSONL lv1=240%, lv5=400%; vanilla=100+20*lv (battle.c:2181-2182)
    "AM_DEMONSTRATION":   lambda lv, tgt, ctx=None: 200 + 40 * lv,
    # --- Archer / Hunter ---
    # HT_FREEZINGTRAP hybrid formula — (25+25*lv)% ATK + 650 flat.
    # Source: user-confirmed from PS developer. Vanilla: 50+10*lv, no flat.
    "HT_FREEZINGTRAP":    lambda lv, tgt, ctx=None: 25 + 25 * lv,
    # --- Bard / Dancer ---
    # JSONL lv1=200%, lv5=300%; vanilla=125+25*lv (battle.c:2217-2219)
    "BA_MUSICALSTRIKE":   lambda lv, tgt, ctx=None: 175 + 25 * lv,
    "DC_THROWARROW":      lambda lv, tgt, ctx=None: 175 + 25 * lv,
    # --- Gunslinger ---
    # JSONL description: "420% Total Damage, 3 hits" → 140% per hit; vanilla=100+50*lv × 1 hit
    "GS_TRIPLEACTION":    lambda lv, tgt, ctx=None: 140,
    # GS_TRACKING: 100+160*lv (lv1=260%, lv10=1700%). Source: ps_skill_db.json id=512.
    "GS_TRACKING":        lambda lv, tgt, ctx=None: 100 + 160 * lv,
    # JSONL lv1=120%, lv10=300%; vanilla=50+50*lv (battle.c:2320-2323); avg 6 hits in PS
    "GS_DESPERADO":       lambda lv, tgt, ctx=None: 100 + 20 * lv,
    # JSONL lv1=130%, lv10=400%; vanilla=100+50*lv (battle.c:2325-2326)
    "GS_DUST":            lambda lv, tgt, ctx=None: 100 + 30 * lv,
    # JSONL lv1=425%, lv10=1100%; vanilla=300+100*lv (battle.c:2328-2329)
    "GS_FULLBUSTER":      lambda lv, tgt, ctx=None: 350 + 75 * lv,
    # JSONL lv1=220%, lv10=400%; vanilla=100+20*(lv-1) (battle.c:2331-2337)
    "GS_SPREADATTACK":    lambda lv, tgt, ctx=None: 200 + 20 * lv,
    # JSONL lv1=260%, lv10=800%; element forced Neutral (see skill_elements below)
    "GS_GROUNDDRIFT":     lambda lv, tgt, ctx=None: 200 + 60 * lv,
    # GS_PIERCINGSHOT (Wounding Shot) — 100+20*lv regardless of weapon. Source: ps_skill_db.json id=516.
    # Vanilla: 100+20*lv with #ifndef RENEWAL guard (battle.c:2313-2315); formula matches but range differs.
    "GS_PIERCINGSHOT":    lambda lv, tgt, ctx=None: 100 + 20 * lv,
    # GS_BULLSEYE (Tranq Shot) — 100% flat. Source: ps_skill_db.json id=517.
    # Vanilla: 500% to DemiHuman/Brute non-boss (battle.c:2303-2308).
    "GS_BULLSEYE":        lambda lv, tgt, ctx=None: 100,
    # GS_MAGICALBULLET (Soul Bullet) — (50+DEX+BaseLv)% per hit × 3 hits, Ghost element.
    # Source: ps_skill_db.json id=518.
    "GS_MAGICALBULLET":   lambda lv, tgt, ctx=None: 50 + (ctx.dex if ctx else 0) + (ctx.base_level if ctx else 0),
    # --- Ninja BF_WEAPON ---
    # NJ_KIRIKAGE (Shadow Slash). Hiding ON: per-level table; Hiding OFF: table − 10×range_pp.
    # PS_NJ_SHADOWSWITHIN toggle: +(25+5×lv)% bonus when active. Source: ps_skill_db.json id=530.
    "NJ_KIRIKAGE":        lambda lv, tgt, ctx=None: (
        (_NJ_KIRIKAGE_HIDE_ON[lv - 1] if (ctx and ctx.skill_params.get("NJ_KIRIKAGE_hiding"))
         else max(0, _NJ_KIRIKAGE_HIDE_OFF[lv - 1] - 10 * (ctx.skill_params.get("NJ_KIRIKAGE_range_pp", 0) if ctx else 0)))
        + (25 + 5 * lv if (ctx and ctx.skill_params.get("PS_NJ_SHADOWSWITHIN_active")) else 0)
    ),
    # NJ_KASUMIKIRI (Haze Slash). Per-level ratio; [When Hidden] ×1.4. Source: ps_skill_db.json id=528.
    "NJ_KASUMIKIRI":      lambda lv, tgt, ctx=None: int(
        _NJ_KASUMIKIRI_RATIOS[lv - 1]
        * (1.4 if (ctx and ctx.skill_params.get("NJ_KASUMIKIRI_hiding")) else 1.0)
    ),
    # JSONL lv1=350%, lv5=950%; vanilla=150+150*lv (battle.c:2338-2339)
    "NJ_HUUMA":           lambda lv, tgt, ctx=None: 200 + 150 * lv,
}

_PS_BF_WEAPON_HIT_COUNT_FN: dict[str, Callable] = {
    # JSONL description: "3 times in one attack (420% Total Damage)" → 3 hits × 140%
    # Vanilla GS_TRIPLEACTION: 1 hit (no hit-count case in skill.c for GS_TRIPLEACTION)
    "GS_TRIPLEACTION":  lambda lv, tgt, ctx=None: 3,
    # GS_RAPIDSHOWER: 5 hits (vanilla: 1 hit, same per-hit ratio). Source: ps_skill_db.json id=515.
    "GS_RAPIDSHOWER":   lambda lv, tgt, ctx=None: 5,
    # PS_RG_TRICKARROW: 2 hits × 100%. Source: ps_skill_db.json (PS custom).
    "PS_RG_TRICKARROW": lambda lv, tgt, ctx=None: 2,
    # GS_DESPERADO: single-hit as main result; avg hits shown via weapon_avg_hits_by_zone.
    "GS_DESPERADO":     lambda lv, tgt, ctx=None: 1,
    # GS_MAGICALBULLET: 3 hits. Source: ps_skill_db.json id=518.
    "GS_MAGICALBULLET": lambda lv, tgt, ctx=None: 3,
    # NJ_KASUMIKIRI: 5 cosmetic hits (negative = cosmetic; ratio encodes total damage).
    # Source: ps_skill_db.json id=528 description "Executes 5 strikes".
    "NJ_KASUMIKIRI":    lambda lv, tgt, ctx=None: -5,
}

# ---------------------------------------------------------------------------
# Per-skill element overrides
# skill_name → int element (0=Neutral, 1=Water, 2=Earth, 3=Fire, 4=Wind, ...)
# Applied in _run_branch() after standard skill_data element resolution (battle_pipeline.py).
# ---------------------------------------------------------------------------
_VANILLA_SKILL_ELEMENTS: dict[str, int] = {
    # CR_SHIELDBOOMERANG forces Neutral element. Source: battle.c:539-540 (s_ele = ELE_NEUTRAL).
    "CR_SHIELDBOOMERANG": 0,
}

_PS_SKILL_ELEMENTS: dict[str, int] = {
    # CR_SHIELDBOOMERANG: same as vanilla — Neutral forced.
    "CR_SHIELDBOOMERANG": 0,
    # GS_GROUNDDRIFT: no entry needed — GS_BLOCK_ENDOW suppresses all weapon endows for GS jobs,
    # so element resolves Neutral without an explicit override.
    # PS_PR_HOLYSTRIKE: always Holy element (regardless of weapon element). Source: ps_skill_db.json id=2622.
    "PS_PR_HOLYSTRIKE": 6,
}

# ---------------------------------------------------------------------------
# Mechanic flag overrides
# Each entry is a string sentinel checked by pipeline steps and modifiers.
# ---------------------------------------------------------------------------
_PS_MECHANIC_FLAGS: frozenset = frozenset({
    # PS: CR_SHIELDBOOMERANG and CR_SHIELDCHARGE can no longer miss.
    # Vanilla: neither has IgnoreFlee in skill_db. PS adds nk_ignore_flee.
    # Source: payon_stories_plan.md — mechanic changes section.
    "CR_SHIELDBOOMERANG_NK_IGNORE_FLEE",
    "CR_SHIELDCHARGE_NK_IGNORE_FLEE",
    # PS: MO_EXTREMITYFIST does NOT ignore DEF; instead applies post-DefenseFix DEF reduction.
    # Vanilla: nk_ignore_def = True. PS: cleared → DEF reduction step applied in _run_branch().
    "MO_EXTREMITYFIST_NK_NORMAL_DEF",
    # PS: SC_CLOAKING bonuses — first auto-attack ×2; AS_SONICBLOW while cloaking +10%.
    "SC_CLOAKING_BONUS",
    # PS: BA_MUSICALSTRIKE +100 ratio when caster is performing (active in song).
    "BA_MUSICALSTRIKE_PERFORMING_BONUS",
    # PS: DC_THROWARROW +100 ratio when caster is performing (active in dance).
    "DC_THROWARROW_PERFORMING_BONUS",
    # PS: RG_BACKSTAP ×1.4 from Opportunity (RG_QUICKSTEP) trigger.
    "RG_BACKSTAP_OPPORTUNITY_BONUS",
    # PS: Gunslinger (job 24) cannot be weapon-endowed — any endow/converter is blocked.
    "GS_BLOCK_ENDOW",
    # PS: MG_SOULSTRIKE ignores 50% of target MDEF.
    "MG_SOULSTRIKE_MDEF_IGNORE",
    # PS: AS_KATAR lv10 grants +50% crit damage on Katar weapons.
    # Does NOT apply to AS_SONICBLOW or AS_GRIMTOOTH.
    "AS_KATAR_KATAR_CRIT_DMG_BONUS",
    # PS: Target LUK-based crit reduction (cri -= luk*2) is disabled.
    "PS_CRIT_SHIELD_DISABLED",
    # PS: PR_MACEMASTERY applies to Staff, 2HStaff, Book, and Knuckle in addition to Mace.
    "PR_MACEMASTERY_EXPANDED_WEAPON_TYPES",
    # PS: WZ_FIREPILLAR ignores 50% of target MDEF (unconditional).
    "WZ_FIREPILLAR_MDEF_IGNORE",
    # RG_BACKSTAP cannot miss in PS (nk_ignore_flee).
    "RG_BACKSTAP_NK_IGNORE_FLEE",
    # PR_TURNUNDEAD failure damage ×2.5 in PS.
    "PR_TURNUNDEAD_PS_BONUS",
    # PS_PR_HOLYSTRIKE proc enabled (Priest melee auto-attack vs Undead/Shadow).
    "PS_HOLYSTRIKE_PROC",
    # PS GS_ADJUSTMENT removes the vanilla −30 HIT penalty.
    # Vanilla: −30 HIT + +30 FLEE. PS: +30 FLEE only. Source: ps_skill_db.json id=505.
    "SC_GS_ADJUSTMENT_SKIP_HIT_PENALTY",
    # PS GS_ADJUSTMENT reduces incoming ranged physical damage by 30%.
    # Source: ps_skill_db.json id=505 — "receives 30% less damage from ranged physical attacks".
    "SC_GS_ADJUSTMENT_LR_REDUCE",
    # PS NJ_ISSEN Mirror Image bonus — (105+5×n)/100 multiplier when attacks_left≥1.
    # Source: user-confirmed; 10-30% bonus over 5 Mirror Image stacks.
    "NJ_ISSEN_MIRROR_BONUS",
    # PS MO_CHAINCOMBO and MO_COMBOFINISH passive levels boost MO_TRIPLEATTACK proc rate.
    # Chain Combo lv N: +floor(N/2)%; Combo Finish lv N: +floor(N×2/3)%. Source: PS server files.
    "MO_TRIPLEATTACK_PS_BONUS",
    # PS SA_VOLCANO/SA_DELUGE/SA_VIOLENTGALE use different enchant_eff, FLEE table,
    # MATK% bonus (Volcano), and no armor element restriction on stat bonuses.
    "GROUND_EFFECT_PS_VALUES",
    # PS: BS_OVERTHRUST party cast gives the full 5×level% bonus (same as self-cast).
    # Vanilla: party members receive fixed val3=5 (5%) regardless of caster's skill level.
    # status.c:8293-8298 #ifndef RENEWAL — val2==1 means self-cast; else val3=5 flat.
    "BS_OVERTHRUST_PARTY_FULL_BONUS",
})

# ---------------------------------------------------------------------------
# Post-defense % damage rate bonuses from active SCs
# Applied in ActiveStatusBonus (active_status_bonus.py) instead of (or in addition to) any
# flat BATK contribution these SCs make in vanilla.
# ---------------------------------------------------------------------------
_PS_RATE_BONUSES: dict[str, int] = {
    # SC_GS_GATLINGFEVER: +40% all damage (all levels) per JSONL.
    # Vanilla: batk += 20+10*lv (status.c:4481 #ifndef RENEWAL).
    # In PS mode, StatusCalculator skips the flat batk add (see status_calculator.py).
    "SC_GS_GATLINGFEVER":  40,
    # SC_GS_MADNESSCANCEL (renamed "Barrage" in PS): +30% all damage (all levels).
    # Vanilla: absent — #ifdef RENEWAL only in battle_calc_masteryfix.
    "SC_GS_MADNESSCANCEL": 30,
    # SC_COMBOFINISH_BUFF: applied post-FinalRateBonus in battle_pipeline.py, not here.
}


# ---------------------------------------------------------------------------
# BF_MAGIC ratio overrides — all verified from ps_skill_db.json
# ---------------------------------------------------------------------------
_PS_BF_MAGIC_RATIOS: dict[str, Callable] = {
    # JSONL lv1=70%, lv10=340%; vanilla=70+10*lv (same formula, different base+step)
    "MG_FIREBALL":    lambda lv, tgt, ctx=None: 40 + 30 * lv,
    # JSONL: "140% of caster's MATK"; vanilla=100%/hit (no BF_MAGIC case, default 100)
    "WZ_EARTHSPIKE":  lambda lv, tgt, ctx=None: 140,
    # JSONL: "140% of caster's MATK"; vanilla=100%/hit (#ifdef RENEWAL case only)
    "WZ_HEAVENDRIVE": lambda lv, tgt, ctx=None: 140,
    # JSONL "Freezing Spear": "85% of the caster's MATK"; vanilla=100%/hit (#ifdef RENEWAL case only)
    "NJ_HYOUSENSOU":  lambda lv, tgt, ctx=None: 85,
    # NJ_RAIGEKISAI (Lightning Jolt): 150+60*lv (lv1=210%, lv5=450%). Vanilla (battle.c:1728): 160+40*lv.
    "NJ_RAIGEKISAI":  lambda lv, tgt, ctx=None: 150 + 60 * lv,
    # AL_HOLYLIGHT: [100% + (1 + Base Level)]% MATK. ctx.base_level used at runtime.
    # Source: ps_skill_db.json. Falls back to vanilla flat 125% when ctx is None.
    "AL_HOLYLIGHT":   lambda lv, tgt, ctx=None: 101 + (ctx.base_level if ctx else 125),
    # WZ_FROSTNOVA: 50*lv% base + 10% per Frost Diver level. Source: ps_skill_db.json.
    "WZ_FROSTNOVA":   lambda lv, tgt, ctx=None: 50 * lv + 10 * (ctx.skill_params.get("WZ_FROSTNOVA_frostdiver_lv", 0) if ctx else 0),
    # PR_MAGNUS: non-Undead/non-Demon targets take ×0.5 damage (ratio 50%).
    # Vanilla ratio = 100% (unchanged). target.element==9 → Undead; target.race=="Demon" → Demon.
    # Source: ps_skill_db.json — "Non-undead/demon take 50% reduced damage".
    "PR_MAGNUS":      lambda lv, tgt, ctx=None: 100 if (tgt and (tgt.element == 9 or tgt.race == "Demon")) else 50,
    # PS: (50 + 2*FireWall_level)% MATK per hit. Hit count = vanilla. Ignores 50% MDEF (see mechanic_flag).
    # WZ_FIREPILLAR has a 5-second priming time before activation — relevant to DPS/timing (see gaps.md).
    # FireWall level comes from skill param "WZ_FIREPILLAR_firewall_lv" (user input via dropdown).
    "WZ_FIREPILLAR":  lambda lv, tgt, ctx=None: 50 + 2 * (ctx.skill_params.get("WZ_FIREPILLAR_firewall_lv", 0) if ctx else 0),
    # WZ_SIGHTRASHER: 100+75*lv (lv1=175%, lv5=475%). Vanilla: 100+20*lv.
    # Source: ps_skill_db.json id=81.
    "WZ_SIGHTRASHER": lambda lv, tgt, ctx=None: 100 + 75 * lv,
}

# ---------------------------------------------------------------------------
# BF_MAGIC hit-count overrides
# NJ_HUUJIN (Wind Blade): vanilla [1,2,2,3,3,4,4,5,5,6]; PS [1,2,2,3,3,4,5,6,7,8]
# Diverges at lv7+. Verified from ps_skill_db.json levels[].effect.
# NJ_KAENSIN: vanilla per-cell counts are in vanilla _BF_MAGIC_HIT_COUNT_FN (skill_ratio.py).
# ---------------------------------------------------------------------------
_NJ_HUUJIN_PS_HITS = [1, 2, 2, 3, 3, 4, 5, 6, 7, 8]
# NJ_KAENSIN per-cell hit counts: vanilla 3/3/3/3/6/6/6/6/9/9 by level.
# Multi-enemy toggle (NJ_KAENSIN_multi) divides by 3 → 1/1/1/1/2/2/2/2/3/3.
_NJ_KAENSIN_HITS      = [3, 3, 3, 3, 6, 6, 6, 6, 9, 9]
_NJ_KAENSIN_MULTI_HITS = [1, 1, 1, 1, 2, 2, 2, 2, 3, 3]
_PS_BF_MAGIC_HIT_COUNT_FN: dict[str, Callable] = {
    "NJ_HUUJIN": lambda lv, tgt, ctx=None: _NJ_HUUJIN_PS_HITS[lv - 1],
    # Multi toggle reads NJ_KAENSIN_multi from ctx.skill_params; falls back to vanilla counts.
    "NJ_KAENSIN": lambda lv, tgt, ctx=None: (
        _NJ_KAENSIN_MULTI_HITS[lv - 1]
        if (ctx and ctx.skill_params.get("NJ_KAENSIN_multi"))
        else _NJ_KAENSIN_HITS[lv - 1]
    ),
}

# ---------------------------------------------------------------------------
# BF_MAGIC wave-indexed ratio overrides
# Used when each wave of a ground skill deals a different ratio per wave.
# Callable signature: (lv, tgt, ctx=None) → int ratio % (ctx.wave_idx is 1-based)
# Consumed by MagicPipeline per-wave branch (magic_pipeline.py).
# ---------------------------------------------------------------------------
_PS_BF_MAGIC_WAVE_RATIOS: dict[str, Callable] = {
    # JSONL: "Damage is 20% of the caster's MATK * Skill Level * Wave Number"
    # Wave 1 = 20*lv%, Wave 2 = 40*lv%, Wave 3 = 60*lv%, Wave 4 = 80*lv%
    # Total across 4 waves = 200*lv% (e.g. lv10 = 2000%)
    # wave_idx is carried in ctx.wave_idx (1-based); ctx=None fallback uses wave 1.
    "WZ_VERMILION": lambda lv, tgt, ctx=None: 20 * lv * (ctx.wave_idx if ctx else 1),
}

# ---------------------------------------------------------------------------
# BF_WEAPON skills confirmed PS ratio == vanilla.
# Source: ps_skill_db.json vs _BF_WEAPON_RATIOS / _PARAM_SKILL_RATIO_FNS.
# Skills listed here will NOT trigger the unverified-ratio warning in SkillRatio.calculate().
# ---------------------------------------------------------------------------
_PS_WEAPON_VANILLA_OK: frozenset[str] = frozenset({
    # Swordman / Knight / Crusader
    "SM_BASH",          # 100+30*lv — PS 130–400% matches
    "SM_MAGNUM",        # 100+20*lv — PS 120–300% matches
    "KN_SPEARSTAB",     # 100+20*lv — PS 120–300% matches
    "KN_SPEARBOOMERANG", # 100+50*lv — PS 150–350% matches
    "KN_PIERCE",        # 100+10*lv — PS 110–200% matches
    # KN_AUTOCOUNTER removed — PS changelog 2026-03-23: 200% ATK (see _PS_BF_WEAPON_RATIOS)
    "KN_CHARGEATK",     # param-driven — no PS description → unchanged
    # Merchant — MC_MAMMONITE moved to _PS_BF_WEAPON_RATIOS (Zeny Pincher toggle)
    # Thief / Assassin / Rogue
    "TF_SPRINKLESAND",  # 130 flat — no PS description → unchanged
    "AS_GRIMTOOTH",     # 100+20*lv — PS 120–200% matches
    "AS_VENOMKNIFE",    # 100 flat — no PS description → unchanged
    "RG_INTIMIDATE",    # 100+30*lv — PS 130–250% matches
    # Archer / Hunter
    "AC_SHOWER",        # 75+5*lv — PS 80–125% matches
    "AC_CHARGEARROW",   # 150 flat — no PS description → unchanged
    "HT_PHANTASMIC",    # 150 flat — no PS description → unchanged
    # Monk
    "MO_BALKYOUNG",     # 300 flat — no PS description → unchanged
    "MO_FINGEROFFENSIVE", # 100+50*lv — PS 150–350%/sphere matches
    "MO_INVESTIGATE",   # 100+75*lv — no PS description → unchanged
    # Taekwon
    "TK_STORMKICK",     # 160+20*lv — PS 180–300% matches (max_lv 7 in PS)
    "TK_DOWNKICK",      # 160+20*lv — PS 180–300% matches
    "TK_TURNKICK",      # 190+30*lv — PS 220–400% matches
    "TK_COUNTER",       # 190+30*lv — PS 220–400% matches
    "TK_JUMPKICK",      # 30+10*lv base — PS 40–100% matches base formula
    # Gunslinger
    # GS_BULLSEYE removed: PS changes to 100% flat (see _PS_BF_WEAPON_RATIOS)
    # GS_PIERCINGSHOT removed: PS ratio 100+20*lv regardless of weapon (see _PS_BF_WEAPON_RATIOS)
    # Ninja BF_WEAPON
    "NJ_KUNAI",         # 100 flat + mastery — no PS description → unchanged
    "NJ_ISSEN",         # inline HP formula — no PS description → unchanged
    "NJ_SYURIKEN",      # vanilla ratio 100% unchanged; PS adds flat +5/lv via param_skill_flat_adds
})

# ---------------------------------------------------------------------------
# BF_MAGIC skills confirmed PS ratio == vanilla.
# Source: ps_skill_db.json vs _BF_MAGIC_RATIOS.
# ---------------------------------------------------------------------------
_PS_MAGIC_VANILLA_OK: frozenset[str] = frozenset({
    # Mage / Wizard / High Wizard
    "MG_NAPALMBEAT",    # 70+10*lv — PS 80–170% matches
    "MG_SOULSTRIKE",    # 100+(5*lv if undead) — PS shows bolts/SP, no ratio → unchanged
    "MG_FIREWALL",      # 50 flat — PS shows hits/duration only → unchanged
    "MG_THUNDERSTORM",  # 80 flat — no PS description → unchanged
    "MG_FROSTDIVER",    # 100+10*lv — PS 110–200% matches
    "MG_COLDBOLT",      # 100/hit — no PS description → unchanged
    "MG_FIREBOLT",      # 100/hit — no PS description → unchanged
    "MG_LIGHTNINGBOLT", # 100/hit — no PS description → unchanged
    "WZ_SIGHTBLASTER",  # 100 default — no BF_MAGIC switch case; G150 PS ratio unchanged
    "WZ_WATERBALL",     # 100+30*lv — PS 130–250% matches
    "WZ_STORMGUST",     # 100+40*lv — PS 140–500% matches
    "WZ_JUPITEL",       # 100/hit — PS shows hits/push only, no ratio → unchanged
    "WZ_METEOR",        # 100 — PS shows meteor/hit counts only → unchanged
    "HW_NAPALMVULCAN",  # 70+10*lv — no PS description → unchanged
    # Acolyte / Priest
    "AL_RUWACH",        # 145 — no PS description → unchanged
    # AL_HOLYLIGHT excluded: moved to _PS_BF_MAGIC_RATIOS lambda — no warning needed.
    # PR_MAGNUS excluded: moved to _PS_BF_MAGIC_RATIOS lambda (×0.5 for non-Undead/Demon targets).
    # Ninja BF_MAGIC
    "NJ_KOUENKA",       # 90 — no PS description → unchanged
    "NJ_KAENSIN",       # 50/hit — PS 50% matches (hit count may differ; ratio unchanged)
    "NJ_HYOUSYOURAKU",  # 100+50*lv — PS 150–350% matches
    "NJ_KAMAITACHI",    # 100+100*lv — PS 200–600% matches
    "NJ_HUUJIN",        # 100/hit — ratio unchanged; hit counts overridden via magic_hit_counts
})

# ---------------------------------------------------------------------------
# Passive stat overrides (PS deviations from vanilla status.c)
# Schema: {skill_or_sc_key: {stat_key: value}}
# Known stat keys:
#   hit_per_lv, flee_per_lv, cri_per_lv  — flat addend × level
#   str_per_lv, int_per_lv               — flat stat addend × level
#   cri_at_max_lv                         — flat CRI added when skill == max level
#   katar_second_factor_per_lv            — contributes level×N to katar second-hit factor
#   aspd_pct_per_lv                       — int or list[int]; ASPD % per level (or per-level table)
#   atk_per_lv                            — list[int]; non-linear flat ATK indexed by lv-1
#     Consumed by mastery_fix.py (flat ATK bonus override for weapon-mapped skills)
#     and battle_pipeline.py (dual-wield rate table for AS_RIGHT / AS_LEFT).
# ---------------------------------------------------------------------------
_PS_PASSIVE_OVERRIDES: dict = {
    # GS_SINGLEACTION: +4 HIT/lv (vanilla: +2/lv, status.c:2047)
    "GS_SINGLEACTION":   {"hit_per_lv": 4},
    # MO_DODGE: +2 FLEE/lv (vanilla: (lv*3)>>1 ≈ 1.5/lv, status.c:2066)
    "MO_DODGE":          {"flee_per_lv": 2},
    # NJ_TOBIDOUGU: +2 HIT/lv (new in PS; vanilla: no HIT bonus)
    "NJ_TOBIDOUGU":      {"hit_per_lv": 2},
    # SA_FREECAST: +4 FLEE/lv (new in PS; vanilla: no FLEE bonus)
    "SA_FREECAST":       {"flee_per_lv": 4},
    # AS_KATAR lv10: +50 CRI display (= +5.0% before Katar doubling).
    # Also contributes 4%/lv to katar second-hit factor (see _katar_second_hit).
    "AS_KATAR":          {"cri_at_max_lv": 50, "katar_second_factor_per_lv": 4},
    # DC_DANCINGLESSON lv10: +100 CRI display (= +10.0%).
    "DC_DANCINGLESSON":  {"cri_at_max_lv": 100},
    # SC_TWOHANDQUICKEN (active SC): +1 FLEE/lv and +10 CRI/lv (vanilla: #ifdef RENEWAL only)
    # PS changelog 2026-03-23: crit increased from 0.8%/lv to 1%/lv (8 → 10 CRI units).
    "SC_TWOHANDQUICKEN": {"flee_per_lv": 1, "cri_per_lv": 10},
    # SC_SPEARQUICKEN (active SC): +10 CRI/lv (vanilla: #ifdef RENEWAL only)
    "SC_SPEARQUICKEN":   {"cri_per_lv": 10},
    # SC_NJ_NEN (active SC): +2×lv STR/INT (vanilla: +1×lv; status.c:3962-3963 / 4148-4149)
    "SC_NJ_NEN":         {"str_per_lv": 2, "int_per_lv": 2},
    # MO_IRONHAND ASPD −1%/lv (new in PS; vanilla: no ASPD bonus).
    "MO_IRONHAND":       {"aspd_pct_per_lv": 1},
    # SA_ADVANCEDBOOK PS — ATK [10,15,20,25,30] and ASPD [3,4,5,6,7]% per lv (Book only).
    # Source: ps_skill_db.json id=274. Vanilla: flat 5 ATK/lv, 5%/lv ASPD.
    "SA_ADVANCEDBOOK":   {"atk_per_lv": [10, 15, 20, 25, 30],
                          "aspd_pct_per_lv": [3, 4, 5, 6, 7]},
    # AS_RIGHT/AS_LEFT PS dual-wield rates as per-level tables.
    # Source: ps_skill_db.json id=132/133.
    # Vanilla: AS_RIGHT = 50+lv*10 [60,70,80,90,100], AS_LEFT = 30+lv*10 [40,50,60,70,80].
    "AS_RIGHT":          {"atk_per_lv": [80, 90, 100, 110, 120]},
    "AS_LEFT":           {"atk_per_lv": [60, 70, 80,  90,  100]},
    # AS_ENCHANTPOISON passive +2%/lv vs Poison element (new in PS; vanilla: no bonus).
    # Source: ps_skill_db.json — "Increases damage against Poison element monsters by 2% per level."
    "AS_ENCHANTPOISON":  {"addele_per_lv": {"Ele_Poison": 2}},
}

# ---------------------------------------------------------------------------
# Passive incoming elemental resists (weapon-gated, lv10 only).
# Source: ps_skill_db.json descriptions for GS_DUST (id=518), GS_FULLBUSTER (id=519),
#         GS_SPREADATTACK (id=520). Consumed by StatusCalculator (status_calculator.py).
# ---------------------------------------------------------------------------
_PS_PASSIVE_RESISTS: dict = {
    # GS_DUST lv10: +7% Neutral resist. Requires Shotgun or Grenade Launcher.
    "GS_DUST":        {"sub_ele_at_max_lv": {"Ele_Neutral": 7},
                       "weapon_types": ["Shotgun", "Grenade"], "max_level": 10},
    # GS_FULLBUSTER lv10: +7% Neutral resist. Requires Shotgun.
    "GS_FULLBUSTER":  {"sub_ele_at_max_lv": {"Ele_Neutral": 7},
                       "weapon_types": ["Shotgun"], "max_level": 10},
    # GS_SPREADATTACK lv10: +7% Neutral resist. Requires Shotgun.
    "GS_SPREADATTACK": {"sub_ele_at_max_lv": {"Ele_Neutral": 7},
                        "weapon_types": ["Shotgun"], "max_level": 10},
}

# ---------------------------------------------------------------------------
# PS per-job stat bonus override table (Gunslinger job 24).
# User-supplied. Each tuple = (job_level, stat_key): that level awards +1 to that stat.
# Multiple tuples at the same level are valid. Consumed by StatusCalculator (status_calculator.py).
# ---------------------------------------------------------------------------
_PS_JOB_BONUSES: dict[int, list] = {
    24: [  # Gunslinger
        ( 1, "dex"), ( 2, "luk"), ( 3, "agi"), ( 4, "luk"),
        ( 6, "dex"), ( 7, "dex"), (11, "dex"), (12, "luk"),
        (13, "agi"), (17, "dex"), (21, "luk"), (25, "dex"),
        (30, "dex"), (31, "luk"), (32, "str_"), (36, "agi"),
        (36, "dex"), (41, "str_"), (45, "dex"), (47, "dex"),
        (50, "str_"), (51, "luk"), (52, "int_"), (55, "dex"),
        (59, "agi"), (60, "vit"), (61, "int_"), (62, "dex"),
        (63, "luk"), (64, "str_"), (66, "agi"), (70, "dex"),
    ],
}

# ---------------------------------------------------------------------------
# ASPD buff overrides
# Schema described in ServerProfile.aspd_buffs field comment above.
# ---------------------------------------------------------------------------
_PS_ASPD_BUFFS: dict = {
    # SC_TWOHANDQUICKEN: weapon-type-dependent quicken (PS changelog 2026-03-23).
    # 2HSword: 300 (30%) unchanged. 1HSword: 100 (10%) new. All other types: 0 (no buff).
    "SC_TWOHANDQUICKEN": {
        "quicken": {
            "2HSword": lambda lv: 300,
            "1HSword": lambda lv: 100,
        }
    },
    # SC_SPEARQUICKEN: weapon-type-dependent quicken formula (replaces vanilla 200+10*lv).
    # PS: 2HSpear = 200+15*lv, others = 75+5*lv.
    "SC_SPEARQUICKEN": {
        "quicken": {
            "2HSpear": lambda lv: 200 + 15 * lv,
            "1HSpear": lambda lv: 75 + 5 * lv,
        }
    },
    # Passive lv10 ASPD rate bonuses (new in PS; vanilla: no bonus).
    # Negative delta = faster (aspd_rate reduction).
    # BA_MUSICALLESSON lv10: −10% delay on MusicalInstrument weapons.
    "BA_MUSICALLESSON": {"lv10_rate": {"MusicalInstrument": -100}},
    # BS_AXEMASTERY lv10: −8% delay on Axe/2HAxe weapons.
    "BS_AXEMASTERY":    {"lv10_rate": {"Axe": -80, "2HAxe": -80}},
    # PR_MACEMASTERY lv10: −12% delay on Mace and Book weapons.
    "PR_MACEMASTERY":   {"lv10_rate": {"Mace": -120, "Book": -120}},
    # SC_GS_GATLINGFEVER flee suppress in PS.
    # Vanilla: flee -= val4 = 5×lv (status.c:4883). PS: no flee penalty.
    "SC_GS_GATLINGFEVER": {"sc_quicken": {"flee_suppress": True}},
    # SC_GS_MADNESSCANCEL quicken floor = 20.
    # Vanilla: if aspd_add < 20, set aspd_add = 20 (status.c:~5560 pre-renewal).
    "SC_GS_MADNESSCANCEL": {"sc_quicken": {"quicken_floor": 20}},
}

# ---------------------------------------------------------------------------
# Proc rate overrides
# TF_DOUBLE / GS_CHAINACTION: vanilla 5%/lv → PS 7%/lv.
# ---------------------------------------------------------------------------
_PS_PROC_RATE_OVERRIDES: dict[str, float] = {
    "TF_DOUBLE":      7.0,
    "GS_CHAINACTION": 7.0,
    # PS bow DA (Rogue/Stalker only) and 1H sword DA (Rogue/Stalker only).
    # Proc chance = rate * min(skill_lv, TF_DOUBLE_lv). Not present on standard server → 0.0 default.
    "AC_VULTURE":     7.0,
    "SM_SWORD":       7.0,
}

# ---------------------------------------------------------------------------
# SC_STEELBODY formula override
# Vanilla: returns 90 flat (status.c:4993/5141 #ifndef RENEWAL).
# PS DEF:  min(90, equip_def * 2)
# PS MDEF: min(90, equip_mdef * 4)
# ---------------------------------------------------------------------------
_PS_STEELBODY_OVERRIDE: tuple = (
    lambda d: min(90, d * 2),   # DEF formula
    lambda d: min(90, d * 4),   # MDEF formula
)

# ---------------------------------------------------------------------------
# Super Novice HP/SP bonus tables
# Applied after standard HP/SP calc when build.job_id == 23 (Super Novice).
# Sum all bonuses for thresholds <= base_level.
# ---------------------------------------------------------------------------
_PS_SN_HP_BONUS: dict[int, int] = {
    40: 100, 50: 150, 60: 200, 70: 250, 80: 300, 90: 400, 99: 1000,
}
_PS_SN_SP_BONUS: dict[int, int] = {
    20: 10, 30: 10, 40: 10, 50: 10, 60: 10, 70: 10, 80: 10, 90: 10, 99: 30,
}

STANDARD = ServerProfile(
    name="standard",
    weapon_ratios={},
    # GS_DESPERADO: single-hit as main result; avg hits shown via weapon_avg_hits_by_zone.
    weapon_hit_counts={"GS_DESPERADO": lambda lv, tgt, ctx=None: 1},
    rate_bonuses={},
    magic_ratios={},
    magic_hit_counts={},
    magic_wave_ratios={},
    mastery_per_level={},
    mastery_ctx_overrides={},
    gc_mastery_overrides={},
    misc_formulas={},
    skill_elements=_VANILLA_SKILL_ELEMENTS,
    mechanic_flags=frozenset(),
    passive_overrides={},
    aspd_buffs={},
    proc_rate_overrides={},
    steelbody_override=None,
    sn_hp_bonus={},
    sn_sp_bonus={},
    weapon_vanilla_ok=frozenset(),
    magic_vanilla_ok=frozenset(),
    tick_hp_stand=10,
    tick_hp_sit=5,
    tick_sp_stand=8,
    tick_sp_sit=4,
    tick_skill=10,
    skill_min_period_ms={},
    ps_skill_delay_fn={},
    ps_acd_zero=frozenset(),
    ps_zero_cast=frozenset(),
    ps_attack_interval={},
    skill_level_cap_overrides={},
    passive_resists={},
    ps_job_bonuses={},
    ps_mastery_weapon_map={},
    param_skill_flat_adds={},
    # GS_DESPERADO — vanilla zone probabilities × 10 fires.
    # Source: skill.c:13538–13553. Interval=100ms, SkillData1=1000ms → 10 fires per unit.
    # Zone 1 (0–1 cells): 36% × 10 = 3.6; Zone 2 (2 cells): 24% × 10 = 2.4;
    # Zone 3 (3 cells / far cross): 12% × 10 = 1.2; Zone 4 (far diag): 8% × 10 = 0.8;
    # Zone 5 (corner ±3,±3): 4% × 10 = 0.4.
    weapon_avg_hits_by_zone={"GS_DESPERADO": (3.6, 2.4, 1.2, 0.8, 0.4)},
    use_ps_skill_names=False,
    use_ps_data=False,
    mastery_prefer_fallback={},
    passive_hidden_for_jobs={},
    pet_bonuses={},
)

# ---------------------------------------------------------------------------
# Mastery per-level overrides
# Tuple = (unmounted, mounted) for spear masteries. Consumed by MasteryFix (mastery_fix.py).
# ---------------------------------------------------------------------------
_PS_MASTERY_PER_LEVEL: dict = {
    "KN_SPEARMASTERY": (5, 7),
    "CR_SPEARMASTERY": (5, 7),
    "MO_IRONHAND":     5,
    "AS_KATAR":        4,
    "BA_MUSICALLESSON": 5,
    "DC_DANCINGLESSON": 5,
    "BS_AXEMASTERY":   5,
    "PR_MACEMASTERY":  4,
}

# Mastery overrides requiring CalcContext (AL_DEMONBANE base_level scaling).
# Consumed by MasteryFix (mastery_fix.py).
_PS_MASTERY_CTX_OVERRIDES: dict[str, Callable] = {
    # AL_DEMONBANE — +4/lv vs all targets (not players); +1/lv extra vs Demon race or Undead element.
    # vs Demon/Undead element: 5*ml. vs everything else: 4*ml.
    "AL_DEMONBANE": lambda ml, tgt, ctx=None: (
        None if (tgt and tgt.is_pc) else
        5 * ml if (tgt and (tgt.race in ("Undead", "Demon") or tgt.element == 9)) else
        4 * ml
    ),
    # GS_DUST — flat +STR ATK at any level, Shotgun/Grenade weapons only (weapon-gate via ps_mastery_weapon_map).
    "GS_DUST": lambda ml, tgt, ctx=None: ctx.str_ if (ctx and ml > 0) else None,
}

# PS CR_GRANDCROSS mastery overrides.
# Spear Mastery contribution to GC: mounted 7→2/lv, unmounted 5→1/lv.
# Demon Bane contribution to GC: 1/lv vs Demon race OR Undead element (9), 0 vs others.
_PS_GC_MASTERY_OVERRIDES: dict[str, Callable] = {
    "KN_SPEARMASTERY": lambda ml, tgt, build: ml * (2 if build.is_riding_peco else 1),
    "CR_SPEARMASTERY": lambda ml, tgt, build: ml * (2 if build.is_riding_peco else 1),
    # +1/lv + ceil(base_level/2) flat vs Demon race OR Undead element; 0 otherwise.
    # Source: in-game testing on PS server.
    "AL_DEMONBANE": lambda ml, tgt, build: (
        ml + (build.base_level + 1) // 2
        if (tgt is not None and (tgt.race == "Demon" or tgt.element == 9))
        else 0
    ),
}

# PS weapon types that map to GS_DUST mastery (vanilla has no GS weapon mastery).
_PS_MASTERY_WEAPON_MAP: dict[str, str] = {
    "Shotgun": "GS_DUST",
    "Grenade": "GS_DUST",
}

def _ps_misc_blitz_base(status, build, gb=None) -> int:
    """PS HT_BLITZBEAT per-hit base: (LUK + INT/2 + 6*HT_STEELCROW + 20) * 2."""
    steelcrow_lv = (gb.effective_mastery if gb is not None else build.mastery_levels).get("HT_STEELCROW", 0)
    return (status.luk + status.int_ // 2 + steelcrow_lv * 6 + 20) * 2


# BF_MISC formula overrides and PS-only skills.
# Callable signature: (lv, status, target, build, gb=None) → (min_dmg, max_dmg).
# Consumed by BattlePipeline BF_MISC dispatch (battle_pipeline.py).
_PS_BF_MISC_FORMULAS: dict[str, Callable] = {
    # PS: lv*(70+DEX)*(70+INT)//65. Wind element. IgnoreDEF (BF_MISC pipeline; no DefenseFix).
    "HT_BLASTMINE":    lambda lv, status, target, build, gb=None: (
        lv * (70 + status.dex) * (70 + status.int_) // 65,
        lv * (70 + status.dex) * (70 + status.int_) // 65,
    ),
    # PS: lv*(80+DEX)*(100+INT)//70. Earth element. IgnoreDEF.
    "HT_LANDMINE":     lambda lv, status, target, build, gb=None: (
        lv * (80 + status.dex) * (100 + status.int_) // 70,
        lv * (80 + status.dex) * (100 + status.int_) // 70,
    ),
    # PS: lv*(30+DEX)*(100+INT)//100. Fire element. IgnoreDEF.
    "HT_CLAYMORETRAP": lambda lv, status, target, build, gb=None: (
        lv * (30 + status.dex) * (100 + status.int_) // 100,
        lv * (30 + status.dex) * (100 + status.int_) // 100,
    ),
    # PS per-hit: (LUK + INT/2 + 6*HT_STEELCROW + 20)*2. Total = per-hit * lv (lv = hit count).
    "HT_BLITZBEAT":    lambda lv, status, target, build, gb=None: (
        _ps_misc_blitz_base(status, build, gb=gb) * lv,
        _ps_misc_blitz_base(status, build, gb=gb) * lv,
    ),
    # PS-only: Marine Sphere HP = 1000 + 200*lv + 25*VIT. Explodes for Fire DEF-ignoring damage.
    # IgnoreDEF (BF_MISC pipeline). Fire element (AttrFix applies via skill_data element field).
    # Sphere count (1–3) comes from skill param "AM_SPHEREMINE_count".
    "AM_SPHEREMINE":   lambda lv, status, target, build, gb=None: (
        (1000 + 200 * lv + 25 * status.vit) * build.skill_params.get("AM_SPHEREMINE_count", 1),
        (1000 + 200 * lv + 25 * status.vit) * build.skill_params.get("AM_SPHEREMINE_count", 1),
    ),
    # NJ_ZENYNAGE: uniform [lv*1000, lv*2000] zeny. PS removes boss/PC reduction.
    # Source: ps_skill_db.json id=526 — "1000~2000 Zeny" at lv1, scaling by lv.
    # Vanilla: zeny_cost=500*lv, range [zeny_cost, 2*zeny_cost-1], boss//3, pc//2.
    "NJ_ZENYNAGE":     lambda lv, status, target, build, gb=None: (lv * 1000, lv * 2000),
    # PS_CORRUPTINGDRAIN — autocast proc via PS custom card. Heals 75% of damage dealt.
    # Formula: 100 + STR + STR²/40 + DEX + DEX²/40 + INT + INT²/40 + LUK + LUK²/40.
    # Source: user-confirmed formula.
    "PS_CORRUPTINGDRAIN": lambda lv, status, target, build, gb=None: (
        (d := 100 + status.str + status.str ** 2 // 40
                  + status.dex + status.dex ** 2 // 40
                  + status.int_ + status.int_ ** 2 // 40
                  + status.luk + status.luk ** 2 // 40),
        d,
    ),
}

# ---------------------------------------------------------------------------
# Per-skill ACD formula overrides (AGI/DEX-based delay).
# Callable: (status: StatusData) → int ms — replaces base_delay for that skill.
# Source: ps_skill_db.json. Consumed by DPS timing calculator (skill_timing.py).
# ---------------------------------------------------------------------------
_PS_SKILL_DELAY_FN: dict[str, Callable] = {
    # AS_SONICBLOW ACD = 2000−(4×AGI+2×DEX) ms. Source: ps_skill_db.json.
    "AS_SONICBLOW":  lambda s: max(0, 2000 - (4 * s.agi + 2 * s.dex)),
    # MO_CHAINCOMBO ACD = 1300−(4×AGI+2×DEX) ms. Source: ps_skill_db.json.
    "MO_CHAINCOMBO": lambda s: max(0, 1300 - (4 * s.agi + 2 * s.dex)),
    # MO_COMBOFINISH ACD = same formula as Chain Combo. Source: ps_skill_db.json.
    "MO_COMBOFINISH": lambda s: max(0, 1300 - (4 * s.agi + 2 * s.dex)),
    # NJ_KASUMIKIRI/NJ_KUNAI: 1000−(4×AGI+2×DEX) ms ACD. Source: ps_skill_db.json id=528.
    "NJ_KASUMIKIRI": lambda s: max(0, 1000 - (4 * s.agi + 2 * s.dex)),
    "NJ_KUNAI":      lambda s: max(0, 1000 - (4 * s.agi + 2 * s.dex)),
    # NJ_HUUMA: 2350−(8×AGI+4×DEX) ms ACD. Source: ps_skill_db.json id=523.
    "NJ_HUUMA":      lambda s: max(0, 2350 - (8 * s.agi + 4 * s.dex)),
    # CR_SHIELDBOOMERANG: fixed 700ms ACD (on top of ASPD period). Source: ps_skill_db.json.
    "CR_SHIELDBOOMERANG": lambda s: 700,
}

# ---------------------------------------------------------------------------
# Skills with ACD forced to minimum (effectively zero ACD).
# effective_delay = _MIN_SKILL_DELAY_MS (100 ms engine floor).
# ---------------------------------------------------------------------------
_PS_ACD_ZERO: frozenset[str] = frozenset({
    "NJ_KOUENKA",     # ACD removed in PS. Source: ps_skill_db.json.
    "NJ_HUUJIN",      # ACD removed in PS. Source: ps_skill_db.json.
    "RG_BACKSTAP",    # PS removes vanilla 0.5s ACD minimum; period = amotion.
})

# ---------------------------------------------------------------------------
# Skills with cast time forced to 0 in PS.
# ---------------------------------------------------------------------------
_PS_ZERO_CAST: frozenset[str] = frozenset({
    "AS_SPLASHER",    # No cast time in PS. Source: ps_skill_db.json.
    "KN_CHARGEATK",   # No cast time in PS (vanilla has cast time). Source: ps_skill_db.json.
})

# ---------------------------------------------------------------------------
# Per-skill DPS period override — bypasses max(cast+delay, amotion).
# Callable: (status: StatusData, amotion_ms: int) → int period_ms.
# ---------------------------------------------------------------------------
_PS_ATTACK_INTERVAL: dict[str, Callable] = {
    # NJ_SYURIKEN: attack fires at amotion rate (same as auto-attack timing).
    "NJ_SYURIKEN": lambda s, am: am,
}

# ---------------------------------------------------------------------------
# Per-skill max level cap overrides (GUI LevelWidget max + pipeline cap).
# ---------------------------------------------------------------------------
_PS_SKILL_LEVEL_CAP_OVERRIDES: dict[str, int] = {
    "AS_ENCHANTPOISON": 5,  # PS max lv 5 (vanilla 10). Source: ps_skill_db.json.
    "NJ_ZENYNAGE":      5,  # PS max lv 5 (vanilla 10). Source: ps_skill_db.json.
    "KN_SPEARSTAB":     5,  # PS changelog 2026-03-23: max lv 5 (vanilla 10).
}

# ---------------------------------------------------------------------------
# Per-skill minimum period overrides (fixed cooldowns).
# Schema: skill_name → minimum period in ms (floor on max(cast+delay, amotion)).
# ---------------------------------------------------------------------------
_PS_SKILL_MIN_PERIOD_MS: dict[str, int] = {
    # BA_MUSICALSTRIKE and DC_THROWARROW both carry a 0.3 s fixed cooldown in PS.
    # Applies when ASPD-based period would otherwise be shorter.
    "BA_MUSICALSTRIKE": 300,
    "DC_THROWARROW":    300,
    # GS_TRIPLEACTION minimum period 0.45s. Source: ps_skill_db.json id=502.
    "GS_TRIPLEACTION":  450,
    # Per-skill cooldowns (blockpc, not ACD — immune to Bragi/delayrate). Source: ps_skill_db.json.
    "AS_SPLASHER":      3000,
    "GS_RAPIDSHOWER":   1000,
    "KN_CHARGEATK":     3000,
    "PS_RG_QUICKSTEP":  4000,
}

# PS flat ATK additions applied after SkillRatio scaling (ATK_ADD equivalent).
# Source: ps_skill_db.json. Consumed by SkillRatio.calculate() (skill_ratio.py).
_PS_PARAM_SKILL_FLAT_ADDS: dict[str, Callable] = {
    # MO_EXTREMITYFIST flat bonus. Source: ps_skill_db.json id=271 —
    # "ATK * (8 + SP/10) + 400/550/700/850/1000 Damage" → flat part = 250 + 150*lv.
    "MO_EXTREMITYFIST": lambda params, lv: 250 + 150 * lv,
    # HT_FREEZINGTRAP +650 flat. Source: user-confirmed from PS developer.
    "HT_FREEZINGTRAP":  lambda params, lv: 650,
    # NJ_SYURIKEN +5/lv flat ATK add. Source: ps_skill_db.json id=523 (Damage +5 per lv).
    "NJ_SYURIKEN":      lambda params, lv: 5 * lv,
}

# ---------------------------------------------------------------------------
# PS changelog 2026-03-23: Blade Mastery — SM_TWOHANDSWORD extends to SM_SWORD weapon types.
# ---------------------------------------------------------------------------
_PS_MASTERY_PREFER_FALLBACK: dict[str, str] = {
    # SM_SWORD weapon types (1HSword, Knife) now benefit from SM_TWOHANDSWORD (Blade Mastery)
    # when the player has it. Rogue keeps SM_SWORD (SM_TWOHANDSWORD = 0 → no redirect).
    "SM_SWORD": "SM_TWOHANDSWORD",
}

# ---------------------------------------------------------------------------
# PS changelog 2026-03-23: SM_SWORD (1H Sword Mastery) removed from Swordsman tree.
# Passive section hides SM_SWORD row for these jobs on PS.
# Job IDs: Swordsman=1, Knight=7, Crusader=14, Lord Knight=4008, Paladin=4015.
# ---------------------------------------------------------------------------
_PS_PASSIVE_HIDDEN_FOR_JOBS: dict[str, frozenset] = {
    "SM_SWORD": frozenset({1, 7, 14, 4008, 4015}),
}

PAYON_STORIES = ServerProfile(
    name="payon_stories",
    weapon_ratios=_PS_BF_WEAPON_RATIOS,
    weapon_hit_counts=_PS_BF_WEAPON_HIT_COUNT_FN,
    rate_bonuses=_PS_RATE_BONUSES,
    magic_ratios=_PS_BF_MAGIC_RATIOS,
    magic_hit_counts=_PS_BF_MAGIC_HIT_COUNT_FN,
    magic_wave_ratios=_PS_BF_MAGIC_WAVE_RATIOS,
    skill_elements=_PS_SKILL_ELEMENTS,
    mastery_per_level=_PS_MASTERY_PER_LEVEL,
    mastery_ctx_overrides=_PS_MASTERY_CTX_OVERRIDES,
    gc_mastery_overrides=_PS_GC_MASTERY_OVERRIDES,
    misc_formulas=_PS_BF_MISC_FORMULAS,
    mechanic_flags=_PS_MECHANIC_FLAGS,
    passive_overrides=_PS_PASSIVE_OVERRIDES,
    aspd_buffs=_PS_ASPD_BUFFS,
    proc_rate_overrides=_PS_PROC_RATE_OVERRIDES,
    steelbody_override=_PS_STEELBODY_OVERRIDE,
    sn_hp_bonus=_PS_SN_HP_BONUS,
    sn_sp_bonus=_PS_SN_SP_BONUS,
    weapon_vanilla_ok=_PS_WEAPON_VANILLA_OK,
    magic_vanilla_ok=_PS_MAGIC_VANILLA_OK,
    tick_hp_stand=4,
    tick_hp_sit=2,
    tick_sp_stand=6,
    tick_sp_sit=3,
    tick_skill=5,
    skill_min_period_ms=_PS_SKILL_MIN_PERIOD_MS,
    ps_skill_delay_fn=_PS_SKILL_DELAY_FN,
    ps_acd_zero=_PS_ACD_ZERO,
    ps_zero_cast=_PS_ZERO_CAST,
    ps_attack_interval=_PS_ATTACK_INTERVAL,
    skill_level_cap_overrides=_PS_SKILL_LEVEL_CAP_OVERRIDES,
    passive_resists=_PS_PASSIVE_RESISTS,
    ps_job_bonuses=_PS_JOB_BONUSES,
    ps_mastery_weapon_map=_PS_MASTERY_WEAPON_MAP,
    param_skill_flat_adds=_PS_PARAM_SKILL_FLAT_ADDS,
    # GS_DESPERADO — PS zone probabilities × 10 fires.
    # Zone 1: 63% × 10 = 6.3; Zone 2: 42% × 10 = 4.2; Zone 3: 21% × 10 = 2.1;
    # Zone 4: 14% × 10 = 1.4; Zone 5: 7% × 10 = 0.7.
    weapon_avg_hits_by_zone={"GS_DESPERADO": (6.3, 4.2, 2.1, 1.4, 0.7)},
    use_ps_skill_names=True,
    use_ps_data=True,
    mastery_prefer_fallback=_PS_MASTERY_PREFER_FALLBACK,
    passive_hidden_for_jobs=_PS_PASSIVE_HIDDEN_FOR_JOBS,
    pet_bonuses={},
)

_PROFILES: dict[str, ServerProfile] = {
    "standard":      STANDARD,
    "payon_stories": PAYON_STORIES,
}


def get_profile(server: str) -> ServerProfile:
    """Return the ServerProfile for the given server name. Falls back to STANDARD."""
    return _PROFILES.get(server, STANDARD)
