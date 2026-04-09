"""
core/player_state_builder.py

Two-pass player state resolution: gear bonuses + effective build + weapon + status.

Resolves the circular dependency between GearBonusAggregator (which evaluates item
scripts that may condition on MaxHp/MaxSp) and StatusCalculator (which requires
GearBonuses to compute max_hp/max_sp):

  Pass 1: aggregate gear without hp/sp context → preliminary status → max_hp_1
  Pass 2: re-aggregate gear with max_hp_1 in context → final (gb, eff_build, weapon, status)

hp defaults to build.current_hp, or max_hp if None (full-health assumption).

Also eliminates the redundant GearBonuses recompute that previously occurred inside
each pipeline's calculate() method. Pipelines now receive a pre-computed GearBonuses
and must not recompute it internally.

Called by main_window.py (the GUI orchestrator) on every UI state change.
"""
from __future__ import annotations

from core import build_applicator
from core.build_manager import BuildManager
from core.calculators.status_calculator import StatusCalculator
from core.config import BattleConfig
from core.gear_bonus_aggregator import GearBonusAggregator, script_ctx_from_build
from core.models.build import PlayerBuild
from core.models.gear_bonuses import GearBonuses
from core.models.status import StatusData
from core.models.weapon import Weapon
from core.server_profiles import ServerProfile, get_profile


def resolve_player_state(
    build: PlayerBuild,
    config: BattleConfig,
    profile: ServerProfile | None = None,
) -> tuple[GearBonuses, PlayerBuild, Weapon, StatusData]:
    """Resolve gear bonuses, effective build, weapon, and status for a PlayerBuild.

    Returns (gear_bonuses, eff_build, weapon, status) — all pre-computed, ready to
    pass directly into pipeline.calculate(). No further gear aggregation or status
    computation should occur downstream.

    Two passes are run:
      - Pass 1 uses no hp/sp context (max_hp unknown); script conditionals on
        MaxHp/MaxSp fall through conservatively (acceptable as intermediate only).
      - Pass 2 uses max_hp/max_sp from pass 1; all conditionals evaluate correctly.

    Approximation: the max_hp used in pass-2 script context does not include
    bMaxHP bonuses from items that conditioned on MaxHp in pass 1
    (second-order effect, not modelled).
    """
    if profile is None:
        profile = get_profile(build.server)

    def _one_pass(status: StatusData | None) -> tuple[GearBonuses, PlayerBuild, Weapon, StatusData]:
        ctx = script_ctx_from_build(build, status)
        gb = GearBonusAggregator.compute(build.equipped, build.refine_levels, ctx)
        GearBonusAggregator.apply_passive_bonuses(gb, gb.effective_mastery, profile)
        build_applicator.apply_pet_bonuses(gb, build.selected_pet, profile)
        GearBonusAggregator.apply_combo_bonuses(gb, build.equipped, profile, ctx)
        eff = build_applicator.apply_gear_bonuses(build, gb)
        build_applicator.apply_weapon_endow(eff)
        weapon = BuildManager.resolve_weapon(
            eff.equipped.get("right_hand"),
            eff.refine_levels.get("right_hand", 0),
            eff.weapon_element,
            is_forged=eff.is_forged,
            forge_sc_count=eff.forge_sc_count,
            forge_ranked=eff.forge_ranked,
            forge_element=eff.forge_element,
            script_atk_ele_rh=gb.script_atk_ele_rh,
        )
        st = StatusCalculator(config).calculate(eff, weapon, gb)
        return gb, eff, weapon, st

    _gb1, _eff1, _weapon1, status1 = _one_pass(status=None)
    gb, eff, weapon, st = _one_pass(status=status1)
    # Normalize current_hp: the None→max_hp default is only applied inside
    # script_ctx_from_build; materialize it on eff_build so downstream callers
    # that read eff_build.current_hp directly get a real value, not None.
    if eff.current_hp is None:
        eff.current_hp = st.max_hp
    return gb, eff, weapon, st
