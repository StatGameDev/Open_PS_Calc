"""
target_utils — SC mutation helpers for mob Target stats.

Applies active SC debuffs (SC_BLIND, SC_POISON, SC_QUAGMIRE, etc.) to a mob
Target via direct field mutation.  Mob targets are not run through
StatusCalculator; this module fills that role for the target side.

apply_mob_scs() is called from _run_battle_pipeline() (battle_pipeline.py)
immediately after apply_to_target() populates target.target_active_scs.
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from core.models.target import Target
from core.server_profiles import get_profile

if TYPE_CHECKING:
    from core.models.status import StatusData

# SC_COMMON (status.h:99-114): bosses are immune to all of these.
# Source: status.c:7472 (is_boss_resist_sc), status.c:10687 (is_boss_resist_sc fn)
_BOSS_IMMUNE_SCS = frozenset({
    "SC_STONE", "SC_FREEZE", "SC_STUN", "SC_SLEEP",
    "SC_POISON", "SC_CURSE", "SC_SILENCE", "SC_CONFUSION", "SC_BLIND",
    "SC_PS_HYPOTHERMIA",
})
# SCs with NoBoss flag — confirmed immune for bosses
# Source: db/pre-re/sc_config.conf, status.c:7472
_BOSS_IMMUNE_NOBOSS = frozenset({
    "SC_PROVOKE", "SC_DECREASEAGI",
})
_ALL_BOSS_IMMUNE = _BOSS_IMMUNE_SCS | _BOSS_IMMUNE_NOBOSS


def apply_mob_scs(target: Target, server: str = "standard") -> None:
    """Apply stat modifications from target_active_scs to a mob Target.

    Called in _run_battle_pipeline() immediately after apply_to_target() has
    populated target.target_active_scs.  Mob targets are not run through
    StatusCalculator, so stat-cascade effects must be applied here via direct
    field mutation.  Player targets receive the same effects through
    StatusCalculator (fed via collect_target_player_scs() in TargetStateSection).

    Boss Protocol: boss mobs are immune to SC_COMMON ailments and any SC
    with NoBoss flag.  Guarded per-SC below.
    Source: status.c:7472, status.h:99-114, db/pre-re/sc_config.conf.
    """
    scs = target.target_active_scs
    # Snapshot original equip DEF/MDEF (from mob_db) before any SC mutations.
    # Needed by SC_STEELBODY PS formula which uses the pre-buff equipment value.
    _orig_def  = target.def_
    _orig_mdef = target.mdef_

    def _blocked(sc_key: str) -> bool:
        return target.is_boss and sc_key in _ALL_BOSS_IMMUNE

    # ── SC_DECREASEAGI: agi -= 2+lv  (status.c:7633, 4025-4026) ─────────────
    if "SC_DECREASEAGI" in scs and not _blocked("SC_DECREASEAGI"):
        lv = int(scs["SC_DECREASEAGI"])
        delta = 2 + lv
        target.agi  = max(0, target.agi  - delta)
        target.flee = max(0, target.flee - delta)  # flee = level+agi; propagate

    # ── SC_BLIND ─────────────────────────────────────────────────────────────
    # hit  -= hit  * 25 / 100  (status.c:4817)
    # flee -= flee * 25 / 100  (status.c:4903)
    if "SC_BLIND" in scs and not _blocked("SC_BLIND"):
        target.hit  = target.hit  - target.hit  * 25 // 100
        target.flee = target.flee - target.flee * 25 // 100

    # ── SC_CURSE: luk = 0  (status.c:4261-4262) ──────────────────────────────
    if "SC_CURSE" in scs and not _blocked("SC_CURSE"):
        target.luk = 0

    # ── SC_POISON: def_percent -= 25  (status.c:4431-4432, no guard) ─────────
    # PS: increased penalty — def_percent -= 50.
    if "SC_POISON" in scs and not _blocked("SC_POISON"):
        _poison_def_penalty = 50 if server == "payon_stories" else 25
        target.def_percent = max(0, target.def_percent - _poison_def_penalty)

    # ── SC_SLEEP: force-hit via opt1 (battle.c:5014); crit×2 (battle.c:4959)
    # No stat mutation here — handled in hit_chance.py and crit_chance.py via
    # target_active_scs flag.  Boss immune (SC_COMMON).

    # ── SC_QUAGMIRE ───────────────────────────────────────────────────────────
    # agi -= val2, dex -= val2; val2 = 10×lv for mobs (status.c:4027-4028, 4211-4212, 8343-8344)
    if "SC_QUAGMIRE" in scs:
        lv   = int(scs["SC_QUAGMIRE"])
        val2 = 10 * lv
        target.agi  = max(0, target.agi  - val2)
        target.dex  = max(0, target.dex  - val2)
        target.flee = max(0, target.flee - val2)  # propagate agi change
        target.hit  = max(0, target.hit  - val2)  # propagate dex change

    # ── SC_PS_HYPOTHERMIA (Hypothermia — PS only) ────────────────────────────
    # -10 DEX → -10 HIT (stacks with SC_QUAGMIRE; user-confirmed PS behaviour)
    # -20% ASPD (aspd_rate += 200); not consumed by current outgoing pipeline.
    # Boss immune (added to _BOSS_IMMUNE_SCS).
    if "SC_PS_HYPOTHERMIA" in scs and not _blocked("SC_PS_HYPOTHERMIA"):
        target.dex      = max(0, target.dex - 10)
        target.hit      = max(0, target.hit - 10)
        target.aspd_rate += 200

    # ── SC_BLESSING debuff ───────────────────────────────────────────────────
    # str >>= 1, dex >>= 1; mob-only; only Undead element (9) or Demon race.
    # BL_PC is hard-blocked in Hercules (status.c:8271-8275).
    # Source: status.c:3964-3968 (str), 4213-4218 (dex), 8271-8275 (PC guard)
    if "SC_BLESSING" in scs:
        if target.element == 9 or target.race == "Demon":
            old_dex    = target.dex
            target.str = target.str >> 1
            target.dex = target.dex >> 1
            dex_delta  = old_dex - target.dex
            target.hit = max(0, target.hit - dex_delta)  # hit = level+dex; propagate

    # ── SC_CRUCIS ────────────────────────────────────────────────────────────
    # def -= def * val2 / 100; val2 = 10+4*lv  (status.c:7662-7664, 5022-5023)
    # Mob-only: Undead element (9) or Demon race; BL_PC hard-blocked (status.c:7205-7207)
    if "SC_CRUCIS" in scs:
        if target.element == 9 or target.race == "Demon":
            lv   = int(scs["SC_CRUCIS"])
            val2 = 10 + 4 * lv
            target.def_ = max(0, target.def_ - target.def_ * val2 // 100)

    # ── SC_PROVOKE ────────────────────────────────────────────────────────────
    # def_percent -= 5+5×lv  (status.c:4401-4402)
    # NoBoss flag — already in _BOSS_IMMUNE_NOBOSS (status.c:7472, sc_config.conf)
    if "SC_PROVOKE" in scs and not _blocked("SC_PROVOKE"):
        lv = int(scs["SC_PROVOKE"])
        target.def_percent = max(0, target.def_percent - (5 + 5 * lv))

    # ── SC_FLING ──────────────────────────────────────────────────────────────
    # val2 = 5×coins → def_percent -= val2 (status.c:8356-8357, status.c:4422-4423).
    # No NoBoss flag — sc_config.conf:5721-5725.
    if "SC_FLING" in scs:
        target.def_percent = max(0, target.def_percent - 5 * int(scs["SC_FLING"]))

    # ── Strip debuffs ─────────────────────────────────────────────────────────
    # Vanilla mob penalties set in status.c:7757-7771 (sd==NULL branches):
    #   SC_NOEQUIPSHIELD: val2=15 → def_percent -= 15  (−15% DEF)
    #   SC_NOEQUIPARMOR:  val2=40 → vit -= vit*40/100  (−40% VIT)
    #   SC_NOEQUIPHELM:   val2=40 → int_ -= int_*40/100 (−40% INT)
    #   SC_NOEQUIPWEAPON: val2=25 → atk_percent -= 25  (−25% ATK, mob only)
    # PS overrides (ps_skill_db.json id=216/217/218/215):
    #   SC_NOEQUIPSHIELD PS: −30% hard DEF
    #   SC_NOEQUIPARMOR  PS: −30% hard MDEF
    #   SC_NOEQUIPHELM   PS: −40% INT (same as vanilla)
    #   SC_NOEQUIPWEAPON PS: −40% ATK — applied in main_window.py as mob_atk_bonus_rate.
    # SC_NOEQUIPHELM INT reduction also consumed in main_window.py as mob_int_bonus_rate
    #   for IncomingMagicPipeline (mob MATK formula uses INT).
    if "SC_NOEQUIPSHIELD" in scs:
        if server == "payon_stories":
            # PS: hard DEF only (status.c:4419-4420 via def_percent not applicable — PS targets def_ directly).
            target.def_ = max(0, target.def_ * 70 // 100)
        else:
            # vanilla: def_percent -= 15 (status.c:4419-4420); DefenseFix applies to both def1 and vit_def.
            target.def_percent = max(0, target.def_percent - 15)
    if "SC_NOEQUIPARMOR" in scs:
        if server == "payon_stories":
            target.mdef_ = max(0, target.mdef_ * 70 // 100)
        else:
            target.vit = max(0, target.vit * 60 // 100)
    if "SC_NOEQUIPHELM" in scs:
        target.int_ = max(0, target.int_ * 60 // 100)

    # ── SC_MINDBREAKER ───────────────────────────────────────────────────────
    # matk_percent += 20×lv  (status.c:4376-4377, 8379-8382)
    # mdef_percent -= 12×lv  (status.c:4453-4454, 8379-8382)
    if "SC_MINDBREAKER" in scs:
        lv = int(scs["SC_MINDBREAKER"])
        target.matk_percent = 100 + 20 * lv
        target.mdef_percent = max(0, 100 - 12 * lv)

    # ── SC_DONTFORGETME ──────────────────────────────────────────────────────
    # aspd_rate += 10 * val2  (status.c:5667)
    # val2 = caster_agi/10 + 3*lv + 5  (skill.c:13270 #else pre-renewal)
    # caster_agi stored alongside level in target_active_scs as "SC_DONTFORGETME_agi".
    if "SC_DONTFORGETME" in scs:
        lv         = int(scs["SC_DONTFORGETME"])
        caster_agi = int(scs.get("SC_DONTFORGETME_agi", 0))
        val2       = caster_agi // 10 + 3 * lv + 5
        target.aspd_rate += 10 * val2
        # simplified: aspd_rate set but not consumed by any current pipeline.

    # ── damage-taken debuffs ──────────────────────────────────────────────────
    # mailbreaker/venom_dust/raided flags are set by apply_to_target() and consumed
    # by the pipeline as separate ×1.1 multiplicative steps.

    # ── SC_STEELBODY — must be last (overrides all other DEF/MDEF values) ────
    # Vanilla: returns 90 flat (status.c:4993 + 5141 #ifndef RENEWAL).
    # PS:  def_ = min(90, equip_def * 2),  mdef = min(90, equip_mdef * 4)
    # For mobs equip_def == target.def_ before any SC mutations; store originals
    # above SC_DECREASEAGI if needed — but SC_STEELBODY mobs rarely have debuffs,
    # so reading current target values (pre-mutation) is correct here at block end.
    # Because SC_STEELBODY is applied last it wins over SC_CRUCIS / SC_POISON / SC_PROVOKE.
    # Source: PayonStoriesData/ps_skill_db.json id=268 (PS); status.c:4993+5141 (vanilla)
    if "SC_STEELBODY" in scs:
        override = get_profile(server).steelbody_override
        if override is not None:
            target.def_  = override[0](_orig_def)
            target.mdef_ = override[1](_orig_mdef)
        else:
            target.def_  = 90
            target.mdef_ = 90
