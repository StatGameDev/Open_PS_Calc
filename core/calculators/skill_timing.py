"""
Skill timing calculator: effective cast time + after-cast delay for a single skill use.

Sources (all pre-renewal, #ifndef RENEWAL_CAST guards respected):
  Cast time:  skill_castfix      (skill.c:17176)
  ACD:        skill_delay_fix    (skill.c:17414)
  Period floor: unit_skilluse_id2 (unit.c:1846)
    canact_tick = tick + max(casttime, max(amotion, min_skill_delay_limit=100))
  then at cast-end:
    canact_tick = max(tick + delay_fix(), ud->canact_tick)
  Combined: period = max(cast + delay, amotion)   (amotion >= 100 always)
"""
from __future__ import annotations

from core.models.status import StatusData
from core.models.gear_bonuses import GearBonuses
from core.server_profiles import get_profile

# Monk combo skills receive an AGI/DEX-based ACD reduction.
# Source: skill_delay_fix (skill.c:17437)
#   time -= (4 * status_get_agi(bl) + 2 * status_get_dex(bl))
_MONK_COMBO_SKILLS: frozenset[str] = frozenset({
    "MO_TRIPLEATTACK",
    "MO_CHAINCOMBO",
    "MO_COMBOFINISH",
    "CH_TIGERFIST",
    "CH_CHAINCRUSH",
})

# DEX scale used by skill_castfix for the pre-renewal DEX reduction step.
# Default value from conf/map/battle/skill.conf:64 (castrate_dex_scale = 150).
_CASTRATE_DEX_SCALE: int = 150

# Minimum after-cast delay enforced by Hercules regardless of reductions.
# conf/map/battle/skill.conf:48 (min_skill_delay_limit = 100 ms).
_MIN_SKILL_DELAY_MS: int = 100

# PS cast time overrides: skill_name → int (fixed ms) or Callable[[skill_lv], int].
# Each entry replaces base_cast before DEX/gear reduction; reductions still apply.
_PS_CAST_TIME_OVERRIDES: dict[str, int | Callable] = {
    "AM_ACIDTERROR":  500,                             # 0.5 s (was 1 s). Source: ps_skill_db.json id=231.
    # WZ_FROSTNOVA: 2.3−0.3×lv s cast time. Source: ps_skill_db.json id=83.
    "WZ_FROSTNOVA":   lambda lv: max(0, 2300 - 300 * lv),
    # WZ_METEOR: 10 s cast time (vanilla 15 s). Source: ps_skill_db.json id=86.
    "WZ_METEOR":      10000,
    # GS_TRACKING cast time = 1+0.1×lv s. Source: ps_skill_db.json id=512.
    "GS_TRACKING":    lambda lv: 1000 + 100 * lv,
    # GS_PIERCINGSHOT cast time 3 s. Source: ps_skill_db.json id=516.
    "GS_PIERCINGSHOT": 3000,
}



def calculate_skill_timing(
    skill_name: str,
    skill_lv: int,
    skill_data: dict,
    status: StatusData,
    gear_bonuses: GearBonuses,
    support_buffs: dict,
    server: str = "standard",
) -> tuple[int, int]:
    """Return (effective_cast_ms, effective_delay_ms) for one use of skill at skill_lv.

    The caller applies the amotion floor:
        period = max(effective_cast + effective_delay, amotion)

    effective_delay is always >= _MIN_SKILL_DELAY_MS (100 ms).
    effective_cast  is always >= 0.
    """
    lv_idx = skill_lv - 1
    profile = get_profile(server)

    # ── Cast time ─────────────────────────────────────────────────────────────
    # skill_castfix (skill.c:17176, #ifndef RENEWAL_CAST)
    cast_times = skill_data.get("cast_time") or []
    base_cast: int = cast_times[lv_idx] if lv_idx < len(cast_times) else 0

    # PS cast time override — replaces base_cast; DEX/gear reductions still apply.
    # Value may be int (fixed) or Callable[[skill_lv], int] (level-dependent).
    if server == "payon_stories" and skill_name in _PS_CAST_TIME_OVERRIDES:
        _ct_override = _PS_CAST_TIME_OVERRIDES[skill_name]
        base_cast = _ct_override(skill_lv) if callable(_ct_override) else _ct_override

    cast_time_options: list = skill_data.get("cast_time_options") or []
    ignore_dex: bool = "IgnoreDex" in cast_time_options

    if base_cast == 0:
        effective_cast = 0
    elif ignore_dex:
        # CastTimeOptions.IgnoreDex: true → skip DEX reduction entirely (skill.c:17180)
        effective_cast = base_cast
    else:
        # DEX reduction (skill.c:17181):
        #   scale = castrate_dex_scale - dex
        #   if scale > 0: time = time * scale / castrate_dex_scale
        #   else: return 0  (instant cast when dex >= scale)
        scale = _CASTRATE_DEX_SCALE - status.dex
        effective_cast = base_cast * max(0, scale) // _CASTRATE_DEX_SCALE

    # Global gear castrate — sd->castrate = 100 + gear_bonuses.castrate
    # Applied when !(castnodex & 4) (default for most skills). (skill.c:~17197; pc.c:2639)
    if gear_bonuses.castrate != 0:
        effective_cast = effective_cast * (100 + gear_bonuses.castrate) // 100

    # Per-skill castrate — bonus2 bCastrate,skill_name,val (pc.c:3607)
    per_skill_cr = gear_bonuses.skill_castrate.get(skill_name, 0)
    if per_skill_cr != 0:
        effective_cast = effective_cast * (100 + per_skill_cr) // 100

    # SC_POEMBRAGI val2: cast time reduction % (skill.c:17252)
    # StatusCalculator already computes this as status.cast_time_reduction_pct.
    if status.cast_time_reduction_pct and effective_cast > 0:
        effective_cast -= effective_cast * status.cast_time_reduction_pct // 100

    # SC_SUFFRAGIUM val2: 15×lv % reduction (status.c:8485; skill.c:17244)
    # Consumed on cast — treated as always active for the cast being evaluated.
    suf_lv = int(support_buffs.get("SC_SUFFRAGIUM", 0))
    if suf_lv > 0 and effective_cast > 0:
        effective_cast -= effective_cast * (15 * suf_lv) // 100

    # SC-based cast time increases — separate multiplicative step after Bragi/Suffragium.
    # Mirrors SC_SLOWCAST in skill_castfix_sc (skill.c:17242): time += time * val2 / 100.
    # SC_PS_HYPOTHERMIA contributes +20% via status.cast_time_penalty_pct.
    if status.cast_time_penalty_pct and effective_cast > 0:
        effective_cast += effective_cast * status.cast_time_penalty_pct // 100

    effective_cast = max(effective_cast, 0)

    # PS zero cast override — force effective_cast to 0 regardless of stat reductions.
    if skill_name in profile.ps_zero_cast:
        effective_cast = 0

    # ── After-cast delay ──────────────────────────────────────────────────────
    # skill_delay_fix (skill.c:17414)
    delays = skill_data.get("after_cast_act_delay") or []
    base_delay: int = delays[lv_idx] if lv_idx < len(delays) else 0

    # PS formula-driven ACD: replaces base_delay entirely for listed skills.
    # Callable: (status) → int ms (already floored at 0 inside the lambda).
    if skill_name in profile.ps_skill_delay_fn:
        base_delay = profile.ps_skill_delay_fn[skill_name](status)

    # Monk combo AGI/DEX reduction (skill.c:17437):
    #   time -= (4 * agi + 2 * dex)
    elif skill_name in _MONK_COMBO_SKILLS:
        base_delay -= 4 * status.agi + 2 * status.dex

    # SC_POEMBRAGI val3: ACD reduction % (skill.c:17486)
    # StatusCalculator already computes this as status.after_cast_delay_reduction_pct.
    if status.after_cast_delay_reduction_pct and base_delay > 0:
        base_delay -= base_delay * status.after_cast_delay_reduction_pct // 100

    # Global + per-skill gear delayrate — additive sum, then single multiply.
    # Global: sd->delayrate (skill.c:~17506; pc.c:3020)
    # Per-skill: bonus2 bDelayrate,skill_name,val (PS-custom, no Hercules equivalent)
    total_delayrate = gear_bonuses.delayrate + gear_bonuses.skill_delayrate.get(skill_name, 0)
    if total_delayrate != 0:
        base_delay = base_delay * (100 + total_delayrate) // 100

    # PS ACD zero override — force effective_delay to minimum (effectively no ACD).
    if skill_name in profile.ps_acd_zero:
        effective_delay = _MIN_SKILL_DELAY_MS
    else:
        # min_skill_delay_limit = 100 ms (skill.conf:48)
        effective_delay = max(base_delay, _MIN_SKILL_DELAY_MS)

    return effective_cast, effective_delay
