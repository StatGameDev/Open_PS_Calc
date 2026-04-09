"""
Crit chance helpers — not a pipeline step; called by BattlePipeline before branching.

is_crit_eligible(skill_id, skill_name, server) — returns True if the skill can roll crits.
calculate_crit_chance(...)                      — returns (is_eligible, crit_chance_pct).

Source: battle.c:4926-4931 (eligible skill list), battle.c:4933-4945 (crit rate computation).
Crit rate is expressed in 0.1% units internally; converted to percent on return.
"""
from core.models.status import StatusData
from core.models.weapon import Weapon
from core.models.skill import SkillInstance
from core.models.target import Target
from core.config import BattleConfig
from core.server_profiles import get_profile, STANDARD

# Skill IDs — numeric constants matching battle.c / skill.c
# Verified against battle.c:4926-4931
_KN_AUTOCOUNTER    = 8
_SN_SHARPSHOOTING  = 280
_MA_SHARPSHOOTING  = 357
_NJ_KIRIKAGE       = 543

# Vanilla crit-eligible skill names (battle.c:4926-4931).
# NK_CRITICAL does NOT exist as a skill flag — eligibility is a hardcoded list.
# Normal attack (skill_id == 0) handled separately in is_crit_eligible().
_VANILLA_CRIT_ELIGIBLE: frozenset[str] = frozenset({
    "KN_AUTOCOUNTER",
    "SN_SHARPSHOOTING",
    "MA_SHARPSHOOTING",
    "NJ_KIRIKAGE",
})

# PS-only skills that can crit (in addition to vanilla crit-eligible skills).
_PS_CRIT_ELIGIBLE: frozenset[str] = frozenset({
    "AS_SONICBLOW",      # G162: can crit in PS. Source: ps_skill_db.json.
    "AS_GRIMTOOTH",      # G162: can crit in PS. Source: ps_skill_db.json.
    "GS_TRACKING",       # G176: can crit in PS. Source: ps_skill_db.json id=512.
    "PS_PR_HOLYSTRIKE",  # G140: can crit in PS. Source: payon_stories_plan.md (PS custom skill).
})


def is_crit_eligible(skill_id: int, skill_name: str, server: str = "standard") -> bool:
    """Return True if this skill can roll a critical hit.

    Normal attack (skill_id == 0) is always eligible.
    For named skills, checks vanilla whitelist; PS adds further entries.
    Source: battle.c:4926-4931.
    """
    if skill_id == 0:
        return True
    if get_profile(server) is not STANDARD:
        return skill_name in (_VANILLA_CRIT_ELIGIBLE | _PS_CRIT_ELIGIBLE)
    return skill_name in _VANILLA_CRIT_ELIGIBLE


def calculate_crit_chance(
    status: StatusData,
    weapon: Weapon,
    skill: SkillInstance,
    target: Target,
    config: BattleConfig,
    server: str = "standard",
) -> tuple[bool, float]:
    """Return (is_eligible, crit_chance_percent).

    is_eligible: False if the skill cannot roll crits at all.
    crit_chance_percent: 0.0 when not eligible; otherwise the roll probability
                         in percent (0-100), already floored at 0.

    Source: battle.c lines 4926-4986 (#ifndef RENEWAL path).

    Roll in Hercules:
        rnd()%1000 < cri   → flag.cri = 1
    So crit_chance = cri / 10.0 (percent).

    cri starts at sstatus->cri (0.1% units, raw, WITHOUT katar doubling when
    show_katar_crit_bonus = 0 which is the default).

    Adjustments applied here (in source order):
      1. Katar double  (battle.c:4944-4946, #ifndef show_katar_crit_bonus)
      2. arrow_cri     (battle.c:4948-4950) — simplified (ammo CRI bonus not in PlayerBuild)
      3. SC_CAMOUFLAGE (battle.c:4951-4952) — simplified (not in active_status_bonus.json)
      4. cri -= target.luk * 2  (battle.c:4957, pre-renewal, PC attacker)
      5. SC_SLEEP      (battle.c:4963)
      6. KN_AUTOCOUNTER forced crit or cri<<=1 (battle.c:4968-4973)
      7. SN/MA_SHARPSHOOTING cri+=200 (battle.c:4975-4977)
      8. NJ_KIRIKAGE cri += 250+50*lv (battle.c:4979-4981)
      9. critical_min floor (config.critical_min, default 10 = 1.0%)
    """
    if not is_crit_eligible(skill.id, skill.name, server):
        return False, 0.0

    # Start from raw cri (no katar doubling baked in — C6 Step 1 removed it)
    cri: int = status.cri

    # 1. Katar double (battle.c:4944-4946)
    # Under show_katar_crit_bonus=0 (default), status.c did NOT double cri.
    # The doubling happens here at roll time.
    if weapon.weapon_type == "Katar":
        cri <<= 1  # *= 2

    # 2. arrow_cri: not in PlayerBuild — skipped

    # 3. SC_CAMOUFLAGE: not in active_status_bonus.json — skipped

    # 4. Target LUK reduction (battle.c:4957, pre-renewal)
    # "cri -= tstatus->luk * (!sd && tsd ? 3 : 2)"
    # We are always a PC attacker (sd != NULL), so coefficient = 2.
    # PS: PS_CRIT_SHIELD_DISABLED flag disables this reduction entirely.
    if "PS_CRIT_SHIELD_DISABLED" not in get_profile(server).mechanic_flags:
        cri -= target.luk * 2

    # 5. SC_SLEEP: cri <<= 1 when target has SC_SLEEP (battle.c:4959)
    if "SC_SLEEP" in target.target_active_scs:
        cri <<= 1

    # 6–8. Skill-specific cri adjustments (battle.c:4968-4981)
    if skill.id == _KN_AUTOCOUNTER:
        if config.auto_counter_type if hasattr(config, "auto_counter_type") else False:
            # battle_config.auto_counter_type nonzero → forced crit, skip the roll
            return True, 100.0
        else:
            cri <<= 1  # *= 2
    elif skill.id in (_SN_SHARPSHOOTING, _MA_SHARPSHOOTING):
        cri += 200
    elif skill.id == _NJ_KIRIKAGE:
        cri += 250 + 50 * skill.level

    # 9. Floor at critical_min (default 10 = 1.0% in 0.1% units)
    cri = max(config.critical_min, cri)

    # Convert 0.1% units to percent.
    # critical_rate is already baked into status.cri via status.c:3919,
    # so we do NOT apply it again here.
    crit_chance = max(0.0, cri / 10.0)
    return True, crit_chance
