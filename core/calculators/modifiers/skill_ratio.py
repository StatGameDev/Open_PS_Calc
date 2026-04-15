"""
SkillRatio — applies the battle_calc_skillratio multiplier and per-skill hit count.

Position: BF_WEAPON step 2 (after BaseDamage), BF_MAGIC step 1, BF_MISC entry point.
Input:  raw PMF from BaseDamage (weapon) or MATK roll (magic).
Output: PMF scaled by ratio/100; hit count applied as repeated convolution.

Ratio tables:
  _BF_WEAPON_RATIOS   — vanilla BF_WEAPON skill ratios (battle.c:2039 battle_calc_skillratio)
  _BF_MISC            — BF_MISC formulas (flat or stat-derived, dispatched by BattlePipeline)
  _BF_MAGIC_RATIOS    — vanilla BF_MAGIC ratios (battle.c:1631-1785 battle_calc_skillratio)
  _PARAM_WEAPON_RATIO_FNS — weapon-type-dependent ratio splits (e.g. RG_BACKSTAP)

ServerProfile.weapon_ratios / magic_ratios take priority over the vanilla tables.

Source: battle.c:2039 battle_calc_skillratio — BF_WEAPON switch (#else not RENEWAL)
        battle.c:1631-1785 battle_calc_skillratio — BF_MAGIC switch (#else not RENEWAL)
        battle.c:4169 battle_calc_misc_attack
        battle.c:3823 damage_div_fix — hit count application
"""
from typing import Callable

from core.models.skill import SkillInstance
from core.models.damage import DamageResult
from core.models.build import PlayerBuild
from core.models.calc_context import CalcContext
from core.models.gear_bonuses import GearBonuses
from core.data_loader import loader
from pmf.operations import _scale_floor, _add_flat, pmf_stats
from core.server_profiles import ServerProfile, STANDARD

# Pre-renewal BF_WEAPON skill ratios from battle_calc_skillratio BF_WEAPON switch.
# Source: battle.c:2039 battle_calc_skillratio, case BF_WEAPON. Each lambda: (lv, tgt) → int ratio %.
# tgt is a Target instance (or None for skills that don't depend on target stats).
# Skills not listed fall back to ratio_base / ratio_per_level in skills.json, or default 100.
#
# Deferred (special mechanics — not simple level-linear):
#   AS_SPLASHER   — ratio 500+50*lv but adds 20*AS_POISONREACT mastery (battle.c:2249-2252); BF_WEAPON #ifndef RENEWAL (skill.c:5200)
#   RG_BACKSTAP   — weapon-type-dependent; handled in _PARAM_WEAPON_RATIO_FNS (battle.c:2152-2156) [IMPLEMENTED]
#   NJ_ISSEN      — #ifndef RENEWAL: wd.damage = 40*STR + lv*(HP/10 + 35) (replaces base damage; needs skill_params: current HP input)
#   GS_MAGICALBULLET — ratio=100; ATK_ADD(matk_max) handled post-SkillRatio in _run_branch (battle.c:5503-5505 #ifndef RENEWAL) [IMPLEMENTED]
#   BA_DISSONANCE — BF_MISC, not BF_WEAPON; flat 30+10*lv +MUSICALLESSON (battle.c:4260-4263)
#   TF_THROWSTONE — BF_MISC, flat 50 damage (battle.c:4257-4258)
#   NJ_ZENYNAGE   — BF_MISC dispatch (skill.c:5550); zeny-cost random damage (battle.c:4341-4349) [IMPLEMENTED]
#   GS_FLING      — BF_MISC dispatch (skill.c:5548); damage = job_level (battle.c:4350) [IMPLEMENTED]
#   HT_LANDMINE   — BF_MISC, lv*(dex+75)*(100+int)/100 (battle.c:4228-4230)
#   HT_BLASTMINE  — BF_MISC, lv*(dex/2+50)*(100+int)/100 (battle.c:4232-4233)
#   HT_CLAYMORETRAP — BF_MISC, lv*(dex/2+75)*(100+int)/100 (battle.c:4235-4236)
_BF_WEAPON_RATIOS: dict = {
    # --- Swordman / Knight / Crusader ---
    # battle.c:2042-2044
    "SM_BASH":           lambda lv, tgt, ctx=None: 100 + 30 * lv,
    # battle.c:2046-2048; BF_LONG (range=9 in skill_db); fire endow handled separately via SC
    "SM_MAGNUM":         lambda lv, tgt, ctx=None: 100 + 20 * lv,
    # battle.c:2091-2095; primary target only (flag=0); AoE ring cells use flag 1/2/3 (Q3)
    "KN_BRANDISHSPEAR":  lambda lv, tgt, ctx=None: 100 + 20 * lv,
    # battle.c:2085-2086
    "KN_SPEARSTAB":      lambda lv, tgt, ctx=None: 100 + 20 * lv,
    # battle.c:2088-2089; BF_LONG from lv2 (range=[3,5,7,9,11])
    "KN_SPEARBOOMERANG": lambda lv, tgt, ctx=None: 100 + 50 * lv,
    # battle.c:2078-2080; hit_count overridden by _BF_WEAPON_HIT_COUNT_FN below (tgt.size+1)
    "KN_PIERCE":         lambda lv, tgt, ctx=None: 100 + 10 * lv,
    # battle.c:2104-2106
    "KN_BOWLINGBASH":    lambda lv, tgt, ctx=None: 100 + 40 * lv,
    # battle.c:2164-2165
    "CR_SHIELDCHARGE":   lambda lv, tgt, ctx=None: 100 + 20 * lv,
    # battle.c:2167-2168; BF_LONG from lv2 (range=[3,5,7,9,11])
    "CR_SHIELDBOOMERANG": lambda lv, tgt, ctx=None: 100 + 30 * lv,
    # battle.c:2170-2179; RENEWAL adds 2hspear bonus — not applicable in pre-re
    "CR_HOLYCROSS":      lambda lv, tgt, ctx=None: 100 + 35 * lv,

    # --- Merchant ---
    # battle.c:2050-2051
    "MC_MAMMONITE":      lambda lv, tgt, ctx=None: 100 + 50 * lv,

    # --- Thief / Assassin / Rogue ---
    # No case in switch → default ratio=100. Include for dps_valid. battle.c:no case
    "TF_POISON":         lambda lv, tgt, ctx=None: 100,
    # battle.c:2117-2118
    "TF_SPRINKLESAND":   lambda lv, tgt, ctx=None: 130,
    # battle.c:2114-2115; skills.json number_of_hits=-8 (cosmetic); ratio encodes full damage
    "AS_SONICBLOW":      lambda lv, tgt, ctx=None: 400 + 40 * lv,
    # battle.c:2108-2109
    "AS_GRIMTOOTH":      lambda lv, tgt, ctx=None: 100 + 20 * lv,
    # No case in switch → default ratio=100 (atk=Misc in skill_db but BF_WEAPON in castend). battle.c:no case
    "AS_VENOMKNIFE":     lambda lv, tgt, ctx=None: 100,
    # battle.c:2158-2159
    "RG_RAID":           lambda lv, tgt, ctx=None: 100 + 40 * lv,
    # battle.c:2161-2162; "copies skill" is a gameplay mechanic, ratio itself is level-linear
    "RG_INTIMIDATE":     lambda lv, tgt, ctx=None: 100 + 30 * lv,

    # --- Archer / Hunter ---
    # battle.c:2056-2058; BF_LONG (range=-9 → bow weapon)
    "AC_DOUBLE":         lambda lv, tgt, ctx=None: 100 + 10 * (lv - 1),
    # battle.c:2060-2066 #else RENEWAL
    "AC_SHOWER":         lambda lv, tgt, ctx=None: 75 + 5 * lv,
    # battle.c:2068-2070; BF_LONG
    "AC_CHARGEARROW":    lambda lv, tgt, ctx=None: 150,
    # battle.c:2357-2358; BF_LONG
    "HT_PHANTASMIC":     lambda lv, tgt, ctx=None: 150,

    # --- Monk ---
    # battle.c:2208-2209; procs from normal attack via battle_calc_weapon_attack (battle.c:6633)
    "MO_TRIPLEATTACK":   lambda lv, tgt, ctx=None: 100 + 20 * lv,
    # battle.c:2211-2212
    "MO_CHAINCOMBO":     lambda lv, tgt, ctx=None: 150 + 50 * lv,
    # battle.c:2214-2215
    "MO_COMBOFINISH":    lambda lv, tgt, ctx=None: 240 + 60 * lv,

    # battle.c:2360-2361
    "MO_BALKYOUNG":      lambda lv, tgt, ctx=None: 300,

    # --- Bard / Dancer ---
    # battle.c:2217-2219; both share same case; BF_LONG (range=9)
    "BA_MUSICALSTRIKE":  lambda lv, tgt, ctx=None: 125 + 25 * lv,
    "DC_THROWARROW":     lambda lv, tgt, ctx=None: 125 + 25 * lv,

    # --- Alchemist ---
    # battle.c:2181-2182; complex MATK+ATK formula is #ifdef RENEWAL only; pre-re: standard pipeline
    "AM_DEMONSTRATION":  lambda lv, tgt, ctx=None: 100 + 20 * lv,
    # battle.c:2184-2189 #else (pre-re): skillratio += 40*lv; def1 forced to 0 in DefenseFix (battle.c:1474 #ifndef RENEWAL)
    "AM_ACIDTERROR":     lambda lv, tgt, ctx=None: 100 + 40 * lv,

    # --- Hunter traps ---
    # battle.c:2073-2077 #ifndef RENEWAL
    "HT_FREEZINGTRAP":   lambda lv, tgt, ctx=None: 50 + 10 * lv,

    # --- Knight ---
    # battle.c: no case in skillratio switch → default 100; BF_NORMAL flag + halved amotion (timing only)
    "KN_AUTOCOUNTER":    lambda lv, tgt, ctx=None: 100,

    # --- Monk ---
    # battle.c:2191-2192; hit_count = spirit spheres held (battle.c:4698-4704: wd.div_ = sd->spiritball_old)
    "MO_FINGEROFFENSIVE": lambda lv, tgt, ctx=None: 100 + 50 * lv,
    # battle.c:2194-2195; flag.pdef=flag.pdef2=2 (battle.c:4759) → DEF reversal handled in DefenseFix
    "MO_INVESTIGATE":    lambda lv, tgt, ctx=None: 100 + 75 * lv,

    # --- Taekwon ---
    # battle.c:2281-2282
    "TK_STORMKICK":      lambda lv, tgt, ctx=None: 160 + 20 * lv,
    # battle.c:2278-2279
    "TK_DOWNKICK":       lambda lv, tgt, ctx=None: 160 + 20 * lv,
    # battle.c:2284-2285
    "TK_TURNKICK":       lambda lv, tgt, ctx=None: 190 + 30 * lv,
    # battle.c:2287-2288
    "TK_COUNTER":        lambda lv, tgt, ctx=None: 190 + 30 * lv,

    # --- Gunslinger ---
    # battle.c:2300-2302: skillratio += 50*lv
    "GS_TRIPLEACTION":   lambda lv, tgt, ctx=None: 100 + 50 * lv,
    # battle.c:2303-2308: +400 vs Brute/Demi-Human non-boss only (#ifndef RENEWAL guard not present)
    "GS_BULLSEYE":       lambda lv, tgt, ctx=None: 100 + (400 if (tgt and tgt.race in ("Brute", "Demi-Human") and not tgt.is_boss) else 0),
    # battle.c:2309-2311: skillratio += 100*(lv+1) → 200+100*lv
    "GS_TRACKING":       lambda lv, tgt, ctx=None: 200 + 100 * lv,
    # battle.c:2313-2315 #ifndef RENEWAL: skillratio += 20*lv
    "GS_PIERCINGSHOT":   lambda lv, tgt, ctx=None: 100 + 20 * lv,
    # battle.c:2317-2318: skillratio += 10*lv
    "GS_RAPIDSHOWER":    lambda lv, tgt, ctx=None: 100 + 10 * lv,
    # battle.c:2320-2323: skillratio += 50*(lv-1); SC_FALLEN_ANGEL×2 is renewal-only → 50+50*lv
    "GS_DESPERADO":      lambda lv, tgt, ctx=None: 50 + 50 * lv,
    # battle.c:2325-2326: skillratio += 50*lv
    "GS_DUST":           lambda lv, tgt, ctx=None: 100 + 50 * lv,
    # battle.c:2328-2329: skillratio += 100*(lv+2) → 300+100*lv
    "GS_FULLBUSTER":     lambda lv, tgt, ctx=None: 300 + 100 * lv,
    # battle.c:2331-2337 #ifndef RENEWAL: skillratio += 20*(lv-1)
    "GS_SPREADATTACK":   lambda lv, tgt, ctx=None: 100 + 20 * (lv - 1),
    # battle.c:5478 default: no explicit pre-re case → ratio=100; ATK_ADD(matk_max) in _run_branch (5503-5505)
    # Element: Ele_Ghost (skill_db.conf). BF_WEAPON dispatch via skill.c:4862 (overrides skill_db AttackType=Misc).
    "GS_MAGICALBULLET":  lambda lv, tgt, ctx=None: 100,

    # --- Ninja BF_WEAPON ---
    # battle.c:2338-2339: skillratio += 50 + 150*lv → 150+150*lv
    "NJ_HUUMA":          lambda lv, tgt, ctx=None: 150 + 150 * lv,
    # battle.c:2344-2345: skillratio += 10*lv
    "NJ_KASUMIKIRI":     lambda lv, tgt, ctx=None: 100 + 10 * lv,
    # battle.c:2347-2348: skillratio += 100*(lv-1) → 100*lv
    "NJ_KIRIKAGE":       lambda lv, tgt, ctx=None: 100 * lv,
    # No case in calc_skillratio → default 100%; mastery +60 in MasteryFix (battle.c:852-855 #ifndef RENEWAL)
    "NJ_KUNAI":          lambda lv, tgt, ctx=None: 100,
    # NJ_SYURIKEN: ratio=100 but also carries flat_add=4*lv — handled in _PARAM_SKILL_RATIO_FNS below.
}

# Hit count overrides for BF_WEAPON skills whose div_ is set to target-size+1 in battle.c.
# Each lambda: (lv, tgt) → int hit_count. Used instead of number_of_hits from skills.json.
# battle.c:4719-4722: wd.div_ = (wd.div_>0 ? tstatus->size+1 : -(tstatus->size+1))
# Target size: SZ_SMALL=0 → 1 hit, SZ_MEDIUM=1 → 2 hits, SZ_LARGE=2 → 3 hits.
# Falls back to skills.json number_of_hits (= max value) when target is None.
_SIZE_TO_HITS = {"Small": 1, "Medium": 2, "Large": 3}
_BF_WEAPON_HIT_COUNT_FN: dict = {
    # battle.c:4719-4722: wd.div_ = tstatus->size+1; SZ_SMALL=0→1hit, SZ_MEDIUM=1→2, SZ_LARGE=2→3
    "KN_PIERCE": lambda lv, tgt, ctx=None: _SIZE_TO_HITS.get(tgt.size, 2) if tgt is not None else 3,
}

# Skills whose ratio depends on build.skill_params (runtime combat context).
# Each callable: (params, level, target) -> (ratio, ratio_src, flat_add).
# flat_add is the ATK_ADD bonus applied after ratio scaling (0 for most skills).
# Adding a new param skill: one entry here + one entry in gui/skill_param_defs.py.

def _ratio_chargeatk(params: dict, lv: int, tgt) -> tuple[int, str, int]:
    # battle.c:2350-2359: skillratio += 100*(k ? (k-1)/3 : 0); capped at 300.
    dist = params.get("KN_CHARGEATK_dist", 1)
    return 100 + 100 * min((dist - 1) // 3, 2), f"KN_CHARGEATK dist={dist} (battle.c:2350-2359)", 0


def _ratio_cartrev(params: dict, lv: int, tgt) -> tuple[int, str, int]:
    # battle.c:2120-2127: skillratio += 50 + 100*cart_weight/cart_weight_max.
    cart_pct = params.get("MC_CARTREVOLUTION_pct", 0)
    return 150 + cart_pct, f"MC_CARTREVOLUTION cart={cart_pct}% (battle.c:2120-2127)", 0


def _ratio_extremityfist(params: dict, lv: int, tgt) -> tuple[int, str, int]:
    # battle.c:2197-2206 #ifndef RENEWAL: skillratio = min(100+100*(8+sp/10), 60000).
    sp = params.get("MO_EXTREMITYFIST_sp", 0)
    return min(100 + 100 * (8 + sp // 10), 60000), f"MO_EXTREMITYFIST sp={sp} (battle.c:2197-2206 #ifndef RENEWAL)", 0


def _ratio_jumpkick(params: dict, lv: int, tgt) -> tuple[int, str, int]:
    # battle.c:2290-2300: base=30+10*lv; +10*lv/3 if SC_COMBOATTACK; ×2 if SC_STRUP.
    combo = bool(params.get("TK_JUMPKICK_combo", False))
    running = bool(params.get("TK_JUMPKICK_running", False))
    ratio = 30 + 10 * lv + (10 * lv // 3 if combo else 0)
    if running:
        ratio *= 2
    return ratio, f"TK_JUMPKICK lv={lv} combo={combo} running={running} (battle.c:2290-2300)", 0


def _ratio_nj_syuriken(params: dict, lv: int, tgt) -> tuple[int, str, int]:
    # battle.c:5506 #ifndef RENEWAL: ATK_ADD(4*skill_lv) after calc_skillratio; ratio has no case → 100.
    flat = 4 * lv
    return 100, f"NJ_SYURIKEN ratio=100 +{flat} flat ATK (battle.c:5506 #ifndef RENEWAL)", flat


_PARAM_SKILL_RATIO_FNS: dict = {
    "KN_CHARGEATK":      _ratio_chargeatk,
    "MC_CARTREVOLUTION": _ratio_cartrev,
    "MO_EXTREMITYFIST":  _ratio_extremityfist,
    "TK_JUMPKICK":       _ratio_jumpkick,
    "NJ_SYURIKEN":       _ratio_nj_syuriken,
}


def _ratio_backstap(params: dict, lv: int, tgt, weapon) -> tuple[int, str, int]:
    # battle.c:2152-2156: bow with backstab_bow_penalty (default=1) → (200+40*lv)/2 added to base
    # 100 → effective ratio 200+20*lv. Other weapons: 200+40*lv added to base 100 → 300+40*lv.
    is_bow = (weapon is not None and weapon.weapon_type == "Bow")
    ratio = 200 + 20 * lv if is_bow else 300 + 40 * lv
    note = "bow (halved by backstab_bow_penalty)" if is_bow else "melee"
    return ratio, f"RG_BACKSTAP {note} ratio={ratio}% (battle.c:2152-2156)", 0


# Skills whose ratio depends on weapon type (not available in _PARAM_SKILL_RATIO_FNS params dict).
# Each callable: (params, level, target, weapon) -> (ratio, ratio_src, flat_add).
_PARAM_WEAPON_RATIO_FNS: dict = {
    "RG_BACKSTAP": _ratio_backstap,
}

# BF_WEAPON skills with confirmed ratios implemented in this module.
# Derived from _BF_WEAPON_RATIOS keys + _PARAM_SKILL_RATIO_FNS keys + _PARAM_WEAPON_RATIO_FNS keys.
# BattlePipeline checks this set to set dps_valid=True only when ratio is known.
IMPLEMENTED_BF_WEAPON_SKILLS: frozenset[str] = (
    frozenset(_BF_WEAPON_RATIOS.keys()) | frozenset(_PARAM_SKILL_RATIO_FNS.keys())
    | frozenset(_PARAM_WEAPON_RATIO_FNS.keys())
    | {"NJ_ISSEN"}  # Fixed HP-formula: handled inline in battle_pipeline._run_branch
)

# BF_MISC skill formulas (traps, throw, zeny attacks).
# Each callable: (skill_lv, status, target, build) → (min_damage, max_damage).
# Pipeline: formula → CardFix → AttrFix (unless IgnoreElement). No BaseDamage, no SkillRatio, no DEF.
# Source: battle.c:4169 battle_calc_misc_attack.

def _misc_nj_zenynage(lv: int, target) -> tuple[int, int]:
    # battle.c:4341-4349 #else (pre-renewal):
    # zeny_cost = skill->get_zeny(NJ_ZENYNAGE, lv) → 500*lv (skill_db.conf pre-re)
    # md.damage = rnd()%zeny_cost + zeny_cost → uniform [zeny_cost, 2*zeny_cost-1]
    # is_boss: //3; target is_pc (tsd): //2; else: full
    zeny_cost = 500 * lv
    if zeny_cost == 0:
        zeny_cost = 2  # battle.c:4342: if (!md.damage) md.damage = 2
    min_dmg = zeny_cost
    max_dmg = 2 * zeny_cost - 1
    if target.is_boss:
        min_dmg = min_dmg // 3
        max_dmg = max_dmg // 3
    elif target.is_pc:
        min_dmg = min_dmg // 2
        max_dmg = max_dmg // 2
    return (max(1, min_dmg), max(1, max_dmg))


def _misc_blitz_base(status, build, gb=None) -> int:
    """Shared base for HT_BLITZBEAT and SN_FALCONASSAULT.

    Formula: (DEX/10 + INT/2 + HT_STEELCROW_lv*3 + 40) * 2
    Source: battle.c:4242-4247 — case HT_BLITZBEAT / SN_FALCONASSAULT
    Note: total damage is independent of skill level (level only sets hit count 1–5).
    """
    steelcrow_lv = (gb.effective_mastery if gb is not None else build.mastery_levels).get("HT_STEELCROW", 0)
    return (status.dex // 10 + status.int_ // 2 + steelcrow_lv * 3 + 40) * 2


_BF_MISC_FORMULAS: dict = {
    # battle.c:4341-4349; ZenyCost=500*lv; IgnoreElement+IgnoreFlee (skill_db.conf)
    "NJ_ZENYNAGE": lambda lv, status, target, build, gb=None: _misc_nj_zenynage(lv, target),
    # battle.c:4350: damage = sd->status.job_level; lv1 only; IgnoreElement+IgnoreFlee
    "GS_FLING": lambda lv, status, target, build, gb=None: (build.job_level, build.job_level),
    # battle.c:4242-4247: (dex/10+int_/2+steelcrow*3+40)*2 is PER-HIT damage.
    # Total = per-hit × skill_lv (1 hit at lv1, 2 at lv2, ..., 5 at lv5).
    "HT_BLITZBEAT": lambda lv, status, target, build, gb=None: (
        _misc_blitz_base(status, build, gb=gb) * lv, _misc_blitz_base(status, build, gb=gb) * lv
    ),
    # battle.c:4248-4255: same base × (150+70*lv)//100 (5-hit div_fix doesn't change total)
    "SN_FALCONASSAULT": lambda lv, status, target, build, gb=None: (
        _misc_blitz_base(status, build, gb=gb) * (150 + 70 * lv) // 100,
        _misc_blitz_base(status, build, gb=gb) * (150 + 70 * lv) // 100,
    ),
    # battle.c:4228-4230 #else (pre-renewal): lv*(dex+75)*(100+int_)/100
    "HT_LANDMINE": lambda lv, status, target, build, gb=None: (
        lv * (status.dex + 75) * (100 + status.int_) // 100,
        lv * (status.dex + 75) * (100 + status.int_) // 100,
    ),
    # battle.c:4232-4233 #else (pre-renewal): lv*(dex/2+50)*(100+int_)/100
    "HT_BLASTMINE": lambda lv, status, target, build, gb=None: (
        lv * (status.dex // 2 + 50) * (100 + status.int_) // 100,
        lv * (status.dex // 2 + 50) * (100 + status.int_) // 100,
    ),
    # battle.c:4235-4236 #else (pre-renewal): lv*(dex/2+75)*(100+int_)/100
    "HT_CLAYMORETRAP": lambda lv, status, target, build, gb=None: (
        lv * (status.dex // 2 + 75) * (100 + status.int_) // 100,
        lv * (status.dex // 2 + 75) * (100 + status.int_) // 100,
    ),
    # battle.c:4257-4258: flat 50, no RENEWAL guard (applies both)
    "TF_THROWSTONE": lambda lv, status, target, build, gb=None: (50, 50),
    # battle.c:4260-4263: 30+lv*10 + 3*BA_MUSICALLESSON, no RENEWAL guard
    "BA_DISSONANCE": lambda lv, status, target, build, gb=None: (
        30 + lv * 10 + 3 * (gb.effective_mastery if gb is not None else build.mastery_levels).get("BA_MUSICALLESSON", 0),
        30 + lv * 10 + 3 * (gb.effective_mastery if gb is not None else build.mastery_levels).get("BA_MUSICALLESSON", 0),
    ),
}

IMPLEMENTED_BF_MISC_SKILLS: frozenset[str] = frozenset(_BF_MISC_FORMULAS.keys())

# PS-only BF_MISC skills that have no vanilla formula (PS profile provides the formula).
# Shown in the skill browser for all modes; the pipeline gates them via profile.misc_formulas.
PS_ONLY_BF_MISC_SKILLS: frozenset[str] = frozenset({"AM_SPHEREMINE", "PS_CORRUPTINGDRAIN"})

# Pre-renewal magic skill ratios from battle_calc_skillratio BF_MAGIC switch.
# Source: battle.c:1631-1785 #else not RENEWAL.
# All unlisted skills use default ratio = 100.
# ELE_UNDEAD = 9 (map.h). Default undead_detect_type=0 → element check only.
_BF_MAGIC_RATIOS = {
    "MG_NAPALMBEAT":   lambda lv, tgt, ctx=None: 70 + 10 * lv,
    "MG_FIREBALL":     lambda lv, tgt, ctx=None: 70 + 10 * lv,   # pre-re: same formula as napalmbeat
    "MG_SOULSTRIKE":   lambda lv, tgt, ctx=None: 100 + (5 * lv if (tgt and tgt.element == 9) else 0),
    "MG_FIREWALL":     lambda lv, tgt, ctx=None: 50,
    "MG_THUNDERSTORM": lambda lv, tgt, ctx=None: 80,              # pre-re: skillratio -= 20
    "MG_FROSTDIVER":   lambda lv, tgt, ctx=None: 100 + 10 * lv,
    "AL_HOLYLIGHT":    lambda lv, tgt, ctx=None: 125,
    "AL_RUWACH":       lambda lv, tgt, ctx=None: 145,
    "WZ_FROSTNOVA":    lambda lv, tgt, ctx=None: (100 + 10 * lv) * 2 // 3,
    "WZ_FIREPILLAR":   lambda lv, tgt, ctx=None: 40 + 20 * lv,   # lv <= 10; lv > 10 not in pre-re
    "WZ_SIGHTRASHER":  lambda lv, tgt, ctx=None: 100 + 20 * lv,
    "WZ_WATERBALL":    lambda lv, tgt, ctx=None: 100 + 30 * lv,
    "WZ_STORMGUST":    lambda lv, tgt, ctx=None: 100 + 40 * lv,
    "HW_NAPALMVULCAN": lambda lv, tgt, ctx=None: 70 + 10 * lv,
    "WZ_VERMILION":    lambda lv, tgt, ctx=None: 80 + 20 * lv,   # pre-re: #else RENEWAL (20*lv-20)
    # battle.c:1631-1785 BF_MAGIC switch — no case for these skills → default ratio 100.
    # Multi-hit comes from number_of_hits in skills.json (lv hits each).
    # battle.c:4005-4007 (bolt spell section, inside default: block which calls calc_skillratio)
    "MG_COLDBOLT":     lambda lv, tgt, ctx=None: 100,
    "MG_FIREBOLT":     lambda lv, tgt, ctx=None: 100,
    "MG_LIGHTNINGBOLT": lambda lv, tgt, ctx=None: 100,
    # WZ_JUPITEL: no case in BF_MAGIC switch; multi-hit by level from skills.json
    "WZ_JUPITEL":      lambda lv, tgt, ctx=None: 100,
    # WZ_EARTHSPIKE: no case in BF_MAGIC switch; single-hit each cast
    "WZ_EARTHSPIKE":   lambda lv, tgt, ctx=None: 100,
    # WZ_SIGHTBLASTER: no case in BF_MAGIC switch; default ratio 100. (battle.c:1678 is WZ_SIGHTRASHER)
    "WZ_SIGHTBLASTER": lambda lv, tgt, ctx=None: 100,
    # WZ_HEAVENDRIVE/WZ_METEOR: case only in #ifdef RENEWAL block; pre-re uses default 100
    "WZ_HEAVENDRIVE":  lambda lv, tgt, ctx=None: 100,
    "WZ_METEOR":       lambda lv, tgt, ctx=None: 100,
    # PR_MAGNUS: no case in BF_MAGIC switch; standard MATK × 100%; targets Undead/Demon only
    "PR_MAGNUS":       lambda lv, tgt, ctx=None: 100,

    # --- Ninja BF_MAGIC ---
    # battle.c:1699-1702: skillratio -= 10 → base 90.
    # Charm bonus (+20*charm_count if CHARM_TYPE_FIRE) is dead code in pre-re: charms are set
    # by KO_* (Kagerou/Oboro) skills only; Ninja (job 25) always has charm_type=CHARM_TYPE_NONE.
    "NJ_KOUENKA":      lambda lv, tgt, ctx=None: 90,
    # battle.c:1704-1708: skillratio -= 50 → base 50.
    # Charm bonus (+10*charm_count) dead in pre-re (see NJ_KOUENKA note above).
    "NJ_KAENSIN":      lambda lv, tgt, ctx=None: 50,
    # battle.c:1709-1713: skillratio += 50*(lv-1) → 50+50*lv.
    # Charm bonus (+15*charm_count) dead in pre-re.
    "NJ_BAKUENRYU":    lambda lv, tgt, ctx=None: 50 + 50 * lv,
    # battle.c:1715-1720: case is #ifdef RENEWAL only → pre-re default 100.
    "NJ_HYOUSENSOU":   lambda lv, tgt, ctx=None: 100,
    # battle.c:1723-1726: skillratio += 50*lv → 100+50*lv.
    # Charm bonus (+25*charm_count CHARM_TYPE_WATER) dead in pre-re.
    "NJ_HYOUSYOURAKU": lambda lv, tgt, ctx=None: 100 + 50 * lv,
    # battle.c:1728-1731: skillratio += 60+40*lv → 160+40*lv.
    # Charm bonus (+15*charm_count CHARM_TYPE_WIND) dead in pre-re.
    "NJ_RAIGEKISAI":   lambda lv, tgt, ctx=None: 160 + 40 * lv,
    # battle.c:1733-1755: falls through to NPC_ENERGYDRAIN: skillratio += 100*lv → 100+100*lv.
    # Charm bonus (+10*charm_count CHARM_TYPE_WIND) dead in pre-re.
    "NJ_KAMAITACHI":   lambda lv, tgt, ctx=None: 100 + 100 * lv,
    # battle.c:1757-1763: case is #ifdef RENEWAL only → pre-re default 100.
    # Hit count varies by level (skills.json positive number_of_hits); PS adds more hits at lv7+.
    "NJ_HUUJIN":       lambda lv, tgt, ctx=None: 100,
}

# BF_MAGIC skills with confirmed ratios implemented above.
# Derived from _BF_MAGIC_RATIOS keys.
# BattlePipeline checks this set to set dps_valid=True for magic skills.
IMPLEMENTED_BF_MAGIC_SKILLS: frozenset[str] = frozenset(_BF_MAGIC_RATIOS.keys())

# Vanilla BF_MAGIC hit-count overrides — for skills where the true per-hit count differs
# from skills.json NumberOfHits (which reflects Hercules skill_db.conf, not real RO behaviour).
# NJ_KAENSIN: per-cell hit counts 3/3/3/3/6/6/6/6/9/9 are vanilla RO behaviour; Hercules
# skill_db.conf has NumberOfHits=1 (ground-skill unit construct — not per-cell RO behaviour).
# simplified: hit counts model a single target; per-cell AoE targeting not modelled.
_BF_MAGIC_HIT_COUNT_FN: dict[str, Callable] = {
    "NJ_KAENSIN": lambda lv, tgt, ctx=None: [3, 3, 3, 3, 6, 6, 6, 6, 9, 9][lv - 1],
}

# Ground skills (SkillType.Place: true) place a unit that fires skill->attack() once per
# Unit.Interval tick for SkillData1 ms.  Each fire is a fully independent pipeline pass
# (separate MATK roll, separate MDEF, separate AttrFix).  This wave count is orthogonal to
# NumberOfHits: negative NumberOfHits is cosmetic WITHIN each wave; wave_count is how many
# times the whole wave fires.
# wave_count = SkillData1 / Unit.Interval  (from skill_db.conf).
# Source: battle_calc_magic_attack called from skill_unit_onplace_timer (skill.c:13883).
_BF_MAGIC_WAVE_COUNTS: dict[str, int] = {
    "WZ_VERMILION": 4,    # SkillData1=4000ms / Interval=1250ms; skill_db.conf
    "WZ_STORMGUST": 10,   # SkillData1=4600ms / Interval=450ms; fires at t=450…4500ms
}


class SkillRatio:
    """Exact Skill Ratio step.
    Source lines (verbatim from repo):
    battle.c: int ratio = battle_calc_skillratio(src, bl, skill_id, skill_lv,
    (skill_get_type(skill_id) == BF_WEAPON) ?
    skill_get_damage(skill_id, skill_lv) : 100);
    battle.c: wd.damage = (int64)wd.damage * ratio / 100;"""

    @staticmethod
    def calculate(skill: SkillInstance, pmf: dict, build: PlayerBuild, result: DamageResult,
                  target=None, weapon=None, profile: ServerProfile = STANDARD,
                  ctx=None, gear_bonuses: GearBonuses | None = None) -> dict:
        """Applies skill ratio and hit count to the PMF.

        target is passed through to ratio lambdas so Q2 stat-dependent skills
        (MO_INVESTIGATE, MO_EXTREMITYFIST, etc.) can access target DEF / HP.
        weapon is passed through to _PARAM_WEAPON_RATIO_FNS callables (e.g. RG_BACKSTAP bow-split).
        profile is checked first for PS ratio and hit-count overrides; falls back to vanilla.
        ctx (CalcContext) is forwarded to all ratio/hit-count callables as the 3rd positional arg.
        """
        skill_data = loader.get_skill(skill.id)
        skill_name = skill_data.get("name", "") if skill_data else ""

        # Priority: PS profile.weapon_ratios → _PARAM_WEAPON_RATIO_FNS → _PARAM_SKILL_RATIO_FNS
        #           → _BF_WEAPON_RATIOS → JSON ratio_per_level → default 100.
        # PS profile takes highest priority so it can replace weapon-type-split skills like
        # RG_BACKSTAP (vanilla bow-split via _PARAM_WEAPON_RATIO_FNS; PS has single flat ratio).
        params = getattr(build, 'skill_params', {})
        flat_add = 0  # ATK_ADD bonus after ratio scaling; set by _PARAM_SKILL_RATIO_FNS entries
        if (ratio_fn := profile.weapon_ratios.get(skill_name)) is not None:
            ratio = ratio_fn(skill.level, target, ctx)
            ratio_src = f"PS profile.weapon_ratios[{skill_name!r}]"
        elif fn := _PARAM_WEAPON_RATIO_FNS.get(skill_name):
            ratio, ratio_src, flat_add = fn(params, skill.level, target, weapon)
        elif fn := _PARAM_SKILL_RATIO_FNS.get(skill_name):
            ratio, ratio_src, flat_add = fn(params, skill.level, target)
        elif (ratio_fn := _BF_WEAPON_RATIOS.get(skill_name)) is not None:
            ratio = ratio_fn(skill.level, target, ctx)
            ratio_src = f"_BF_WEAPON_RATIOS[{skill_name!r}]"
        elif skill_data and skill_data.get("ratio_per_level"):
            ratio_list = skill_data["ratio_per_level"]
            ratio = ratio_list[skill.level - 1] if skill.level <= len(ratio_list) else skill_data.get("ratio_base", 100)
            ratio_src = f"ratio_per_level[lv{skill.level}]"
        else:
            ratio = skill_data.get("ratio_base", 100) if skill_data else 100
            ratio_src = "ratio_base (default 100)"

        # PS-specific flat add (applied after any ratio branch including weapon_ratios).
        # Allows profile to add flat ATK_ADD on top of any ratio source (e.g. HT_FREEZINGTRAP +650).
        if ps_flat_fn := profile.param_skill_flat_adds.get(skill_name):
            flat_add += ps_flat_fn(params, skill.level)

        active = getattr(build, 'active_status_levels', {})

        # SC_OVERTHRUST / SC_OVERTHRUSTMAX add to skillratio (not flat ATK).
        # status.c: SC_OVERTHRUST val3 = 5*val1 (self-cast, pre-renewal)
        # status.c: SC_OVERTHRUSTMAX val2 = 20*val1
        # SC_OVERTHRUSTMAX cancels SC_OVERTHRUST in the emulator — both can't be active.
        # battle.c:2919-2922 inside battle_calc_skillratio (no RENEWAL guard):
        #   if(sc->data[SC_OVERTHRUST])    skillratio += sc->data[SC_OVERTHRUST]->val3;
        #   if(sc->data[SC_OVERTHRUSTMAX]) skillratio += sc->data[SC_OVERTHRUSTMAX]->val2;
        if "SC_OVERTHRUST" in active:
            ratio += 5 * active["SC_OVERTHRUST"]
        elif (ot_lv := int(build.support_buffs.get("SC_OVERTHRUST", 0))) > 0:
            if "BS_OVERTHRUST_PARTY_FULL_BONUS" in profile.mechanic_flags:
                ratio += 5 * ot_lv  # PS: full 5×level (status.c:8295-8296 self path)
            else:
                ratio += 5          # vanilla: fixed val3=5 (status.c:8297-8298)
        if "SC_OVERTHRUSTMAX" in active:
            ratio += 20 * active["SC_OVERTHRUSTMAX"]

        # AS_SONICACCEL: ATK_ADDRATE(10) on AS_SONICBLOW → ratio × 1.1 (battle.c:5607)
        if skill_name == "AS_SONICBLOW" and params.get("AS_SONICBLOW_sonic_accel", True):
            ratio = ratio * 110 // 100
            ratio_src += " ×1.1 (Sonic Accel)"

        # NK flags (loaded here – ready for future NK_IGNORE_DEF etc. checks)
        nk_flags = skill_data.get("nk_flags", []) if skill_data else []  # noqa: F841

        # Multi-hit from number_of_hits field.
        # Negative = cosmetic (ratio already encodes full damage; do NOT multiply pmf).
        # Positive = actual multi-hit (each hit is separate; multiply pmf × n).
        # Source: battle.c:3823 damage_div_fix macro.
        hit_count_raw = 1
        if skill_name == "MO_FINGEROFFENSIVE":
            # battle.c:4698-4704: wd.div_ = sd->spiritball_old (spheres held at cast).
            # skill_params["MO_FINGEROFFENSIVE_spheres"] is always populated by collect_into().
            hit_count_raw = max(1, params.get("MO_FINGEROFFENSIVE_spheres", 1))
        else:
            # Priority: PS profile.weapon_hit_counts → vanilla _BF_WEAPON_HIT_COUNT_FN → skills.json
            ps_hc_fn = profile.weapon_hit_counts.get(skill_name)
            hit_count_fn = ps_hc_fn or _BF_WEAPON_HIT_COUNT_FN.get(skill_name)
            if hit_count_fn is not None:
                # Override: fixed hit count (e.g. KN_PIERCE: tgt.size+1; KN_BOWLINGBASH PS: 2).
                hit_count_raw = hit_count_fn(skill.level, target, ctx)
            elif skill_data:
                noh = skill_data.get("number_of_hits")
                if noh and skill.level <= len(noh):
                    hit_count_raw = noh[skill.level - 1]
        hit_count = hit_count_raw if hit_count_raw > 0 else 1
        display_hits = abs(hit_count_raw)
        cosmetic = hit_count_raw < 0

        # Two sequential scale() calls — keep separate to preserve Hercules integer rounding.
        # battle.c: wd.damage = (int64)wd.damage * ratio / 100;  (then × hit_count separately)
        pmf = _scale_floor(pmf, ratio, 100)
        if flat_add > 0:
            # ATK_ADD: applied after skillratio scale, before damage_div_fix (battle.c:5506 #ifndef RENEWAL)
            pmf = _add_flat(pmf, flat_add)
        pmf = _scale_floor(pmf, hit_count, 1)

        # bSkillAtk: ATK_ADDRATE after damage_div_fix, before defense. battle.c:5657-5658
        if gear_bonuses and (skill_atk_bonus := gear_bonuses.skill_atk.get(skill_name, 0)):
            pmf = _scale_floor(pmf, 100 + skill_atk_bonus, 100)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                name="Skill ATK Bonus",
                value=av, min_value=mn, max_value=mx,
                multiplier=(100 + skill_atk_bonus) / 100.0,
                note=f"bSkillAtk: {skill_name} +{skill_atk_bonus}%",
                formula=f"dmg × (100 + {skill_atk_bonus}) / 100",
                hercules_ref="pc.c:3513-3527 SP_SKILL_ATK; battle.c:5657-5658 ATK_ADDRATE(i) after div_fix",
            )

        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            name=f"Skill Ratio (ID {skill.id} Lv {skill.level})",
            value=av,
            min_value=mn,
            max_value=mx,
            multiplier=ratio / 100.0,
            note=skill_data.get("description", "") if skill_data else "",
            formula=(f"dmg × {ratio}% + {flat_add} × {display_hits} cosmetic hits   ({ratio_src})"
                     if (cosmetic and flat_add) else
                     f"dmg × {ratio}% × {display_hits} cosmetic hits   ({ratio_src})"
                     if cosmetic else
                     f"dmg × {ratio}% + {flat_add} × {hit_count} hits   ({ratio_src})"
                     if flat_add else
                     f"dmg × {ratio}% × {hit_count} hits   ({ratio_src})"),
            hercules_ref="battle.c: battle_calc_skillratio — BF_WEAPON ratio from _BF_WEAPON_RATIOS dict\n"
                         "battle.c:2919-2922: if(sc->data[SC_OVERTHRUST]) skillratio += SC_OVERTHRUST->val3;\n"
                         "battle.c:2921-2922: if(sc->data[SC_OVERTHRUSTMAX]) skillratio += SC_OVERTHRUSTMAX->val2;\n"
                         "battle.c: wd.damage = (int64)wd.damage * ratio / 100;\n"
                         "battle.c:3823: damage_div_fix: div>1 → dmg*=div; div<0 → cosmetic (unchanged)"
        )
        # PS completeness guard: warn when vanilla is used as unverified fallback.
        # Fires when: non-standard profile AND skill not in PS overrides AND not confirmed vanilla-ok.
        if (profile is not STANDARD
                and skill_name  # basic attack (id=0) has no name; no ratio to verify
                and skill_name not in profile.weapon_ratios
                and skill_name not in profile.weapon_vanilla_ok):
            result.add_step(
                name="⚠ Vanilla fallback (PS unaudited)",
                value=av, min_value=mn, max_value=mx,
                multiplier=1.0,
                note=(f"{skill_name}: PS formula not confirmed — using vanilla as fallback. "
                      "Add to _PS_BF_WEAPON_RATIOS (if different) or _PS_WEAPON_VANILLA_OK (if same)."),
                formula="unverified vanilla fallback",
                hercules_ref="",
            )
        return pmf, hit_count

    @staticmethod
    def get_magic_wave_count(skill_name: str, build: PlayerBuild) -> int:
        """Wave count for a magic skill (SkillData1 / Unit.Interval from skill_db.conf),
        overrideable via build.skill_params (e.g. WZ_STORMGUST_waves)."""
        wave_count = _BF_MAGIC_WAVE_COUNTS.get(skill_name, 1)
        return build.skill_params.get(f"{skill_name}_waves", wave_count)

    @staticmethod
    def get_magic_hit_count(skill: SkillInstance, build: PlayerBuild, target,
                            profile: ServerProfile = STANDARD, ctx=None) -> int:
        """Hit count (raw, signed) for a magic skill without applying ratio.
        Negative = cosmetic (animation only, damage not multiplied).
        Priority: profile.magic_hit_counts → _BF_MAGIC_HIT_COUNT_FN → skills.json → 1.
        Source: battle.c:3823 damage_div_fix macro.
        """
        skill_data = loader.get_skill(skill.id)
        skill_name = skill_data.get("name", "") if skill_data else ""
        hit_count_raw = 1
        ps_hc_fn = profile.magic_hit_counts.get(skill_name)
        if ps_hc_fn is not None:
            hit_count_raw = ps_hc_fn(skill.level, target, ctx)
        elif (vanilla_hc_fn := _BF_MAGIC_HIT_COUNT_FN.get(skill_name)) is not None:
            hit_count_raw = vanilla_hc_fn(skill.level, target, ctx)
        elif skill_data:
            noh = skill_data.get("number_of_hits")
            if noh and skill.level <= len(noh):
                hit_count_raw = noh[skill.level - 1]
        return hit_count_raw

    @staticmethod
    def calculate_magic(skill: SkillInstance, pmf: dict, build: PlayerBuild, target,
                        result: DamageResult,
                        profile: ServerProfile = STANDARD,
                        ctx=None, gear_bonuses: GearBonuses | None = None) -> tuple:
        """Applies BF_MAGIC skill ratio (per-hit only). Returns (pmf, hit_count, wave_count).

        hit_count is returned separately so the caller can apply it AFTER defense and
        attr_fix, matching the exact Hercules source order:
          MATK_RATE(skillratio) → calc_defense → attr_fix → × ad.div_
        Source: battle_calc_magic_attack, battle.c:1631-1785 (#else not RENEWAL).

        wave_count is the number of independent ground-skill pipeline passes (default 1).
        Comes from SkillData1 / Unit.Interval in skill_db.conf; orthogonal to hit_count.
        Ground skills with wave_count > 1 apply the full pipeline wave_count times.

        profile.magic_ratios overrides _BF_MAGIC_RATIOS for PS server.
        ctx (CalcContext) is forwarded to all ratio/hit-count callables as the 3rd positional arg.
        profile.magic_hit_counts overrides skills.json number_of_hits for PS server.
        """
        skill_data = loader.get_skill(skill.id)
        skill_name = skill_data.get("name", "") if skill_data else ""

        # Raw hit count from skills.json number_of_hits — sign is significant:
        #   positive (e.g. +5): actual multi-hit — caller multiplies dmg × n after defense+attrfix
        #   negative (e.g. -3): cosmetic multi-hit — animation shows n hits, dmg is NOT multiplied
        # Source: battle.c:3823 damage_div_fix macro:
        #   if (div > 1) dmg *= div;          ← actual multi-hit
        #   else if (div < 0) div *= -1;      ← cosmetic: just flip sign for display, dmg unchanged
        # Priority: PS profile.magic_hit_counts → vanilla _BF_MAGIC_HIT_COUNT_FN → skills.json
        # PS profile takes priority (e.g. NJ_HUUJIN lv7+ diverges from vanilla).
        # _BF_MAGIC_HIT_COUNT_FN covers skills where Hercules skill_db.conf NumberOfHits
        # differs from true vanilla RO behaviour (e.g. NJ_KAENSIN per-cell counts).
        hit_count_raw = 1
        ps_hc_fn = profile.magic_hit_counts.get(skill_name)
        if ps_hc_fn is not None:
            hit_count_raw = ps_hc_fn(skill.level, target, ctx)
        elif (vanilla_hc_fn := _BF_MAGIC_HIT_COUNT_FN.get(skill_name)) is not None:
            hit_count_raw = vanilla_hc_fn(skill.level, target, ctx)
        elif skill_data:
            noh = skill_data.get("number_of_hits")
            if noh and skill.level <= len(noh):
                hit_count_raw = noh[skill.level - 1]   # raw, NOT abs()

        display_hits = abs(hit_count_raw)
        cosmetic = hit_count_raw < 0

        # Wave count: static default from skill_db SkillData1/Interval, overrideable via
        # build.skill_params (e.g. WZ_STORMGUST_waves for freeze-threshold scenarios).
        wave_count = _BF_MAGIC_WAVE_COUNTS.get(skill_name, 1)
        wave_count = build.skill_params.get(f"{skill_name}_waves", wave_count)

        # Normal single-ratio path.
        # PS profile.magic_ratios takes priority over vanilla _BF_MAGIC_RATIOS.
        # AL_HOLYLIGHT PS formula is a data-driven lambda in _PS_BF_MAGIC_RATIOS
        # (uses ctx.base_level at runtime).
        ratio_fn = profile.magic_ratios.get(skill_name) or _BF_MAGIC_RATIOS.get(skill_name)
        ratio = ratio_fn(skill.level, target, ctx) if ratio_fn else 100
        ratio_src = ("PS override" if skill_name in profile.magic_ratios
                     else "vanilla" if skill_name in _BF_MAGIC_RATIOS
                     else "default 100")

        pmf = _scale_floor(pmf, ratio, 100)
        mn, mx, av = pmf_stats(pmf)
        result.add_step(
            name=f"Magic Skill Ratio (ID {skill.id} Lv {skill.level})",
            value=av,
            min_value=mn,
            max_value=mx,
            multiplier=ratio / 100.0,
            note=skill_data.get("description", "") if skill_data else "",
            formula=(f"MATK × {ratio}%  ({display_hits} cosmetic hits — dmg not multiplied)  [{ratio_src}]"
                     if cosmetic else
                     f"MATK × {ratio}%  ({display_hits} hits applied after defense)  [{ratio_src}]"),
            hercules_ref="battle.c:1631-1785: battle_calc_skillratio BF_MAGIC switch (#else not RENEWAL)\n"
                         "battle.c:3823: damage_div_fix: div>1 → dmg*=div; div<0 → cosmetic (div negated, dmg unchanged)"
        )
        # bSkillAtk: applied after ratio, before defense. battle.c:4055-4056
        if gear_bonuses and (skill_atk_bonus := gear_bonuses.skill_atk.get(skill_name, 0)):
            pmf = _scale_floor(pmf, 100 + skill_atk_bonus, 100)
            mn, mx, av = pmf_stats(pmf)
            result.add_step(
                name="Skill ATK Bonus",
                value=av, min_value=mn, max_value=mx,
                multiplier=(100 + skill_atk_bonus) / 100.0,
                note=f"bSkillAtk: {skill_name} +{skill_atk_bonus}%",
                formula=f"MATK × (100 + {skill_atk_bonus}) / 100",
                hercules_ref="pc.c:3513-3527 SP_SKILL_ATK; battle.c:4055-4056 ad.damage += ad.damage*i/100",
            )
        # PS completeness guard: warn when vanilla is used as unverified fallback.
        if (profile is not STANDARD
                and skill_name
                and skill_name not in profile.magic_ratios
                and skill_name not in profile.magic_vanilla_ok):
            result.add_step(
                name="⚠ Vanilla fallback (PS unaudited)",
                value=av, min_value=mn, max_value=mx,
                multiplier=1.0,
                note=(f"{skill_name}: PS formula not confirmed — using vanilla as fallback. "
                      "Add to _PS_BF_MAGIC_RATIOS (if different) or _PS_MAGIC_VANILLA_OK (if same)."),
                formula="unverified vanilla fallback",
                hercules_ref="",
            )
        return pmf, hit_count_raw, wave_count