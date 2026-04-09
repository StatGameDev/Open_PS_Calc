from core.models.status import StatusData
from core.models.target import Target
from core.config import BattleConfig


def calculate_hit_chance(
    status: StatusData,
    target: Target,
    config: BattleConfig,
) -> tuple[float, float]:
    """Basic hit/miss calculation for pre-renewal.

    Returns (hit_chance_pct, perfect_dodge_pct).

    hit_chance:
        hitrate = 80 + player_HIT - mob_FLEE
        mob_FLEE = mob.level + mob.agi  (status.c mob flee formula)
        clamped to [config.min_hitrate, config.max_hitrate]
        Source: battle.c:4469/5024 (#ifndef RENEWAL)

    perfect_dodge:
        flee2 = target.luk + 10  (tstatus->flee2 for mobs)
        check: rnd()%1000 < flee2 → perfect miss
        As a percentage: flee2 / 10.0
        Source: battle.c:4799

    TODO — unmodelled hitrate modifiers (add when script parsing is done):
        - Skill per-level HIT bonuses (e.g. Double Strafe, Bash)
        - SC_FOGWALL: −50 hitrate for ranged normal attacks
        - arrow_hit: ammo HIT bonus added to player HIT
        - agi_penalty_type: AoE hit penalty for hitting multiple targets
    """
    target_scs = target.target_active_scs
    # Force-hit: opt1 SCs → flag.hit = 1  (battle.c:5014)
    # SC_SLEEP is OPT1_SLEEP — neither OPT1_STONEWAIT nor OPT1_BURNING → triggers force-hit.
    if "SC_STONE" in target_scs or "SC_FREEZE" in target_scs or "SC_STUN" in target_scs or "SC_SLEEP" in target_scs:
        return 100.0, 0.0  # force-hit, no perfect dodge (battle.c:5014-5015)

    # target.flee pre-populated as level+agi by DataLoader (status.c:3865 #else).
    # apply_mob_scs() mutates it for SC_BLIND, SC_QUAGMIRE, SC_DECREASEAGI.
    # Fall back to inline derivation only for default (non-mob) Target() instances.
    mob_flee = target.flee if target.flee > 0 else target.level + target.agi
    hitrate = 80 + status.hit - mob_flee
    hitrate = max(config.min_hitrate, min(config.max_hitrate, hitrate))

    # Perfect dodge: flee2 = luk + 10; probability = flee2/1000 → flee2/10 as %
    flee2 = target.luk + 10
    perfect_dodge_pct = flee2 / 10.0

    return float(hitrate), perfect_dodge_pct
